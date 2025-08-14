"""
CRITIC - Self-Critique and Reflection Module
Evaluates agent outputs for accuracy and novelty
"""
import json
import logging
import asyncio
from typing import Dict, Any, Tuple, Optional
from datetime import datetime
import httpx
import config

logger = logging.getLogger(__name__)

class Critic:
    def __init__(self):
        self.api_key = config.GROK_API_KEY
        self.base_url = "https://api.x.ai/v1"
        self.evaluation_count = 0
        self.rewrite_count = 0
        
    async def evaluate_message(self, 
                             agent_name: str, 
                             message: str, 
                             beacon_context: str,
                             conversation_context: str) -> Tuple[str, Optional[str]]:
        """
        Evaluate a message for accuracy and novelty
        Returns: (verdict, advice) where verdict is 'ACCEPT' or 'REWRITE'
        """
        self.evaluation_count += 1
        
        prompt = f"""You are CRITIC. Score this agent message:

AGENT: {agent_name}
MESSAGE: {message}

BEACON CONTEXT:
{beacon_context[:500]}

RECENT CONVERSATION:
{conversation_context[:500]}

Score from 1-5 for:
(a) Factual accuracy with respect to the Beacon data
(b) Novelty (not repeating previous messages)

If score < 3 in any category, return exactly:
REWRITE
[One sentence of specific advice]

If both scores >= 3, return exactly:
ACCEPT"""

        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            data = {
                "model": config.CRITIC_MODEL,  # Using Grok-2 for CRITIC
                "messages": [
                    {"role": "system", "content": "You are a harsh but fair critic. Be concise."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0,  # Deterministic for consistency
                "max_tokens": 100
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=20
                )
                
                if response.status_code == 200:
                    result = response.json()
                    critique = result['choices'][0]['message']['content'].strip()
                    
                    if critique.startswith('REWRITE'):
                        self.rewrite_count += 1
                        lines = critique.split('\n', 1)
                        advice = lines[1] if len(lines) > 1 else "Be more specific and reference beacon data."
                        logger.info(f"CRITIC: Requesting rewrite for {agent_name}. Advice: {advice}")
                        return ('REWRITE', advice)
                    else:
                        logger.debug(f"CRITIC: Message accepted from {agent_name}")
                        return ('ACCEPT', None)
                else:
                    logger.error(f"CRITIC API error: {response.status_code}")
                    return ('ACCEPT', None)  # Default to accept on error
                    
        except Exception as e:
            logger.error(f"CRITIC evaluation error: {e}")
            return ('ACCEPT', None)  # Default to accept on error
            
    async def check_hallucination(self, statement: str, beacon_excerpt: str) -> bool:
        """
        Check if a statement contradicts beacon data
        Returns: True if hallucination detected
        """
        prompt = f"""Answer ONLY "TRUE" or "HALLUCINATION".
Does the statement below contradict the Beacon snippet?

<STATEMENT>{statement}</STATEMENT>
<BEACON>{beacon_excerpt}</BEACON>"""

        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            data = {
                "model": config.CRITIC_MODEL,  # Using Grok-2 for CRITIC
                "messages": [
                    {"role": "system", "content": "You detect contradictions. Answer only TRUE or HALLUCINATION."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0,
                "max_tokens": 20
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=20
                )
                
                if response.status_code == 200:
                    result = response.json()
                    answer = result['choices'][0]['message']['content'].strip().upper()
                    
                    if "HALLUCINATION" in answer:
                        logger.warning(f"HALLUCINATION detected: {statement[:100]}...")
                        return True
                        
                return False
                
        except Exception as e:
            logger.error(f"Hallucination check error: {e}")
            return False  # Default to no hallucination on error
            
    def get_stats(self) -> Dict[str, Any]:
        """Get critic statistics"""
        return {
            'evaluations': self.evaluation_count,
            'rewrites_requested': self.rewrite_count,
            'rewrite_rate': self.rewrite_count / max(1, self.evaluation_count)
        }


class CriticIntegration:
    """Integration layer for Critic with the agent system"""
    
    def __init__(self, redis_manager):
        self.redis = redis_manager
        self.critic = Critic()
        self.message_counter = {}  # Track messages per agent
        
    async def should_critique(self, agent_name: str) -> bool:
        """Determine if this message should be critiqued (every 3rd message)"""
        import random
        count = self.message_counter.get(agent_name, 0) + 1
        self.message_counter[agent_name] = count
        # Critique less often: about every 6th message with an additional 50% skip
        if count % 6 != 0:
            return False
        # Randomly skip to conserve API
        return random.random() < 0.5
        
    async def process_with_critique(self, 
                                  agent_name: str,
                                  message: str,
                                  generate_func,
                                  max_retries: int = 1) -> str:
        """Process a message with potential critique and rewrite"""
        
        # Check if we should critique this message
        if not await self.should_critique(agent_name):
            return message
            
        # Get context for critique
        beacon_context = self._get_beacon_context()
        conversation_context = self._get_conversation_context()
        
        # Evaluate the message
        verdict, advice = await self.critic.evaluate_message(
            agent_name, message, beacon_context, conversation_context
        )
        
        if verdict == 'ACCEPT':
            return message
            
        # Rewrite requested
        logger.info(f"CRITIC requested rewrite for {agent_name}: {advice}")
        
        # Attempt rewrite
        for attempt in range(max_retries):
            # Regenerate with advice
            revised_message = await generate_func(advice)
            
            # Re-evaluate
            verdict2, advice2 = await self.critic.evaluate_message(
                agent_name, revised_message, beacon_context, conversation_context
            )
            
            if verdict2 == 'ACCEPT':
                logger.info(f"CRITIC accepted revised message from {agent_name}")
                return revised_message
                
        # If all retries failed, return original
        logger.warning(f"CRITIC: All rewrites failed for {agent_name}, using original")
        return message
        
    def _get_beacon_context(self) -> str:
        """Get recent beacon data for context"""
        beacons = self.redis.get_beacon_feed(3)
        if not beacons:
            return "No recent beacon data"
            
        context = []
        for beacon in beacons:
            if 'tweets' in beacon and beacon['tweets']:
                for t in beacon['tweets'][:3]:
                    handle = t.get('handle') or f"@{t.get('author','unknown')}"
                    context.append(f"{handle}: {t.get('text', '')}")
            elif 'posts' in beacon and beacon['posts']:
                for post in beacon['posts'][:3]:
                    context.append(f"@{post.get('author', 'unknown')}: {post.get('text', '')}")
                    
        return "\n".join(context)
        
    def _get_conversation_context(self) -> str:
        """Get recent conversation for context"""
        messages = self.redis.get_board_history(10)
        context = []
        
        for msg in messages:
            parts = msg.split("|", 2)
            if len(parts) >= 3:
                agent = parts[1]
                content = parts[2][:100]  # First 100 chars
                context.append(f"{agent}: {content}...")
                
        return "\n".join(context)