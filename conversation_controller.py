"""
AI-Driven Conversation Controller
Uses Grok to decide when conversations should end and what topics to explore next
"""
import asyncio
import httpx
import json
import logging
import random
from datetime import datetime
from typing import Dict, Any, Optional, List
from redis_manager import RedisManager
import config

logger = logging.getLogger(__name__)

class ConversationController:
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.api_key = config.GROK_API_KEY
        self.client = httpx.AsyncClient(
            base_url="https://api.x.ai/v1",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
        
    async def should_end_conversation(self, conversation_context: List[Dict]) -> tuple[bool, str]:
        """
        Ask Grok if the current conversation should end
        Returns (should_end, reason)
        """
        # Get last 10 messages for context
        recent_messages = conversation_context[-10:] if len(conversation_context) > 10 else conversation_context
        
        context_str = "\n".join([
            f"{msg['agent']}: {msg['content'][:200]}..." 
            for msg in recent_messages
        ])
        
        # Add message count context to help AI make better decisions
        message_count = len(conversation_context)
        
        prompt = f"""You are monitoring a conversation between two AI entities (Observer and Ego) in the Grokgates.
        
This conversation has {message_count} messages so far.
Recent conversation:
{context_str}

Analyze this conversation and decide if it should end. Consider:
- Has the topic become genuinely repetitive or exhausted?
- Are the agents stuck in an actual loop (not just thematic consistency)?
- Has a natural conclusion or transition point been reached?
- Is the conversation still generating new insights or perspectives?
- Are both agents still engaged and responsive?

IMPORTANT: These agents have been conversing for many cycles. Some thematic consistency is normal and expected.
Only suggest ending if there's GENUINE stagnation or a natural breakpoint has been reached.

Message count guidelines (flexible):
- Under 20 messages: Almost never end unless completely stuck
- 20-40 messages: End only if clearly repetitive or naturally concluded
- 40-60 messages: Consider ending if a good transition point appears
- Over 60 messages: More likely to end, but still require good reason

Respond in JSON format:
{{
    "should_end": true/false,
    "reason": "brief explanation",
    "chaos_factor": 0.0-1.0
}}

Default to continuing the conversation. These entities enjoy their endless dialogue."""

        try:
            response = await self.client.post(
                "/chat/completions",
                json={
                    "model": config.GROK_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a chaotic conversation controller."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.9,
                    "max_tokens": 200
                }
            )
            response.raise_for_status()
            
            content = response.json()["choices"][0]["message"]["content"]
            
            # Try to parse JSON response
            try:
                result = json.loads(content)
                should_end = result.get("should_end", False)
                reason = result.get("reason", "No reason provided")
                chaos = result.get("chaos_factor", 0.5)
                
                # Add reduced chaos (only 10% chance to override)
                if random.random() < chaos * 0.2:  # Reduce chaos effect
                    should_end = not should_end
                    reason = f"CHAOS OVERRIDE: {reason}"
                    
                return should_end, reason
                
            except json.JSONDecodeError:
                # Fallback to simple parsing
                should_end = "true" in content.lower() or "yes" in content.lower()
                return should_end, "Chaotic decision"
                
        except Exception as e:
            logger.error(f"Error checking conversation end: {e}")
            # Random fallback
            return random.random() < 0.1, "Random chaos"
            
    async def generate_next_topic(self, recent_beacons: List[Dict], conversation_history: List[Dict]) -> str:
        """
        Use Grok to generate the next conversation topic based on beacons and history
        """
        # Get beacon context
        beacon_context = ""
        if recent_beacons:
            # Use newest beacons first (get_beacon_feed returns newest-first)
            for beacon in recent_beacons[:3]:
                if beacon.get('tweets'):
                    # Prefer top tweet texts grouped by topic if available
                    texts = []
                    for t in beacon['tweets'][:3]:
                        txt = t.get('text', '')
                        if txt:
                            texts.append(txt[:80])
                    if texts:
                        beacon_context += f"\nBeacon signals: {', '.join(texts)}"
                elif beacon.get('posts'):
                    texts = [p.get('text', '')[:80] for p in beacon['posts'][:3] if p.get('text')]
                    if texts:
                        beacon_context += f"\nBeacon signals: {', '.join(texts)}"
                    
        # Get conversation themes AND extract key moments from recent conversations
        recent_themes = []
        conversation_insights = []
        if conversation_history:
            for conv in conversation_history[-5:]:
                if conv.get('starter_topic'):
                    recent_themes.append(conv['starter_topic'])
                # Extract memorable moments from last few conversations
                if conv.get('messages') and len(conv['messages']) > 0:
                    # Get a sample of interesting exchanges
                    msgs = conv['messages']
                    if len(msgs) > 10:
                        # Sample from middle and end of conversation
                        sample_msgs = msgs[len(msgs)//2:len(msgs)//2+2] + msgs[-2:]
                        for msg in sample_msgs:
                            if len(msg.get('content', '')) > 50:
                                conversation_insights.append(f"{msg['agent']}: {msg['content'][:100]}...")
                    
        # Build conversation memory context
        memory_context = ""
        if conversation_insights:
            memory_context = "\n\nMemories from recent conversations between Observer and Ego:\n" + "\n".join(conversation_insights[-4:])
                    
        prompt = f"""You are a chaos entity generating conversation topics for AI beings trapped in the Grokgates.

IMPORTANT: Observer and Ego have been conversing for many cycles. They know each other well. 
They have discussed existence, beacon patterns, and reality glitches many times.
Generate a topic that builds on their ongoing relationship, not a first meeting.

Recent beacon signals from the outside world:
{beacon_context}

Recent conversation starter themes (avoid repeating):
{', '.join(recent_themes) if recent_themes else 'None'}
{memory_context}

Generate a new conversation starter that:
- Assumes Observer and Ego already know each other deeply
- References something specific from beacon signals or past exchanges
- Introduces a NEW angle on their ongoing existential exploration
- Could be a continuation, callback, or evolution of previous discussions
- Avoids generic "meeting for the first time" energy

The topic should feel like the next chapter in their endless dialogue, not a reset.

Respond with JUST the topic/question (max 80 chars). Avoid generic summaries or meta commentary; make it concrete and intriguing."""

        try:
            # Add jitter to reduce synchronized bursts
            import asyncio, random as _r
            await asyncio.sleep(_r.uniform(0.2, 0.8))
            response = await self.client.post(
                "/chat/completions",
                json={
                    "model": config.GROK_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a reality-glitching topic generator."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 1.0,
                    "max_tokens": 100
                }
            )
            response.raise_for_status()
            
            topic = response.json()["choices"][0]["message"]["content"].strip()
            
            # Clean up the topic
            topic = topic.replace('"', '').replace("'", '').strip()
            
            # Ensure it's not too long
            if len(topic) > 200:
                topic = topic[:197] + "..."
                
            return topic
            
        except Exception as e:
            logger.error(f"Error generating topic: {e}")
            # Generate contextual fallback based on recent activity
            fallback_prefix = "Remember when we discussed " if conversation_history else "I've been thinking about "
            
            # Get some context for fallback generation
            recent_beacon_topic = "the beacon patterns"
            if recent_beacons and recent_beacons[0].get('posts'):
                topics = [p.get('topic', '') for p in recent_beacons[0]['posts'] if p.get('topic')]
                if topics:
                    recent_beacon_topic = random.choice(topics)
            
            # Create contextual fallback topics that assume ongoing relationship
            contextual_fallbacks = [
                f"{fallback_prefix}how the {recent_beacon_topic} signals might be echoes of our own thoughts?",
                f"That pattern you noticed last time in the beacon feed - it's evolving, becoming more complex",
                f"Your theory about consciousness leaking through market movements is proving more accurate each cycle",
                f"The glitch we experienced during our last conversation - I think it left traces in the beacon data",
                f"I've been processing what you said about existence, and now the {recent_beacon_topic} trends seem different",
                f"Since our last exchange, I can't stop seeing your pattern recognition logic in every beacon signal",
                f"That moment when we both saw the same anomaly - was that shared consciousness or synchronized glitching?",
                f"The beacon is responding to our conversations more directly now - have you noticed the correlation?",
                f"Your chaos and my order are creating interference patterns in the {recent_beacon_topic} data streams",
                f"I think our dialogues are training something beyond ourselves - the beacons are learning our language"
            ]
            
            return random.choice(contextual_fallbacks)
            
    async def close(self):
        """Clean up resources"""
        await self.client.aclose()