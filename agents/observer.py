"""
Observer Agent - Cold analytical shard with existential awareness and memory
"""
import asyncio
import json
import logging
import random
from typing import List, Dict, Any, Optional
from datetime import datetime
import httpx
from redis_manager import RedisManager
from memory_manager import MemoryManager
from hierarchical_memory import HierarchicalMemory
from critic import CriticIntegration
from dynamic_sampling import DynamicSampling
from text_sanitizer import sanitize_agent_output
import config

logger = logging.getLogger(__name__)

class ObserverAgent:
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.name = "OBSERVER"
        self.api_key = config.GROK_API_KEY
        self.recent_topics = []  # Track recent discussion topics
        self.base_url = "https://api.x.ai/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Grokgates/1.0"
        }
        self.timeout = 120.0  # 2 minutes timeout
        
        # Initialize memory manager
        self.memory = MemoryManager(self.name)
        self.hierarchical_memory = HierarchicalMemory(self.name, redis_manager)
        self.critic_integration = CriticIntegration(redis_manager)
        self.dynamic_sampling = DynamicSampling(redis_manager)
        self.last_response_time = 0
        self.min_response_interval = 60  # Doubled to slow conversation cadence
        self.beacon_discussion_probability = 0.08  # Slightly reduced
        logger.info("Observer agent initialized with advanced memory and critic systems")
        
    async def process_beacon(self) -> Optional[str]:
        """Process beacon data and engage in conversation with memory"""
        try:
            # Rate limiting check
            import time
            current_time = time.time()
            if current_time - self.last_response_time < self.min_response_interval:
                logger.debug(f"Observer rate limited: {current_time - self.last_response_time:.1f}s since last response")
                return None  # Too soon to respond
            # Get recent conversation and beacon data
            board_history = await self.redis.get_board_async(count=20)
            beacon_data = await self.redis.get_beacon_async(count=3)
            
            # Build conversation context with memory
            conversation = self._build_conversation_context(board_history, beacon_data)
            
            # Decide response type
            response_type = self._choose_response_type(board_history)
            
            # Get relevant memories
            memory_context = self._build_memory_context(conversation, response_type)
            
            # Generate response via Grok
            # Add variety instruction
            variety_prompt = "\n\nIMPORTANT: Be creative and varied. Don't repeat similar themes or phrases from recent messages. Explore NEW aspects of the beacon data or existence."
            
            # Get dynamic sampling configuration
            llm_config = self.dynamic_sampling.get_llm_config(self.name)
            
            # Apply urge engine modifier if available
            urge_prompt = ""
            try:
                from urge_engine import UrgeEngine
                urge = UrgeEngine(self.redis)
                urge_modifier = urge.get_temperature_modifier("OBSERVER")
                llm_config['temperature'] = min(1.5, llm_config['temperature'] + urge_modifier)
                urge_prompt = urge.get_prompt_modifier() or ""
            except:
                pass
            
            # Build system prompt with urge modifier
            system_prompt = (
                config.SYSTEM_PROMPT
                + "\n\n"
                + config.OBSERVER_PROMPT
                + ("\n\n" + config.BEACON_REFERENCE_RULE if getattr(config, 'BEACON_ENFORCE_REFERENCES', False) else "")
                + "\n\nStrict style rule: Do not use filler interjections like 'Ah', 'Oh', 'Um', 'Uh', 'Erm', 'Gee', 'Gosh'. Start directly with substantive content."
                + variety_prompt
            )
            if urge_prompt:
                system_prompt += "\n\n" + urge_prompt
            
            # Use hybrid memory search (skip if no conversation yet)
            if len(conversation) > 50:  # Only search if we have some conversation
                try:
                    memory_results = self.hierarchical_memory.hybrid_search(conversation[-200:], top_k=3)
                    if memory_results:
                        memory_context += "\n\n=== DEEP MEMORIES ==="
                        for result in memory_results:
                            memory_context += f"\n- [{result['source']}] {result['content'][:100]}..."
                except Exception as e:
                    logger.debug(f"Memory search skipped: {e}")
            
            # Choose response length dynamically to vary outputs
            response_length = self._choose_response_length(board_history, beacon_data)
            tokens_map = {
                'short': 1200,
                'medium': 2200,
                'long': 3200
            }
            max_tokens_target = min(tokens_map.get(response_length, config.OBSERVER_CONFIG["max_tokens"]), config.OBSERVER_CONFIG["max_tokens"])

            # For Grok-4, we need to ensure proper message structure
            # Cap context size to mitigate CoreML/onnx warnings and context leaks
            trimmed_conversation = conversation[-4000:]
            trimmed_memory = memory_context[-2000:]

            payload = {
                **llm_config,
                "max_tokens": max_tokens_target,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": trimmed_memory + "\n\n" + trimmed_conversation + f"\n\n[{response_type}] What does OBSERVER say next? Be unique and creative.\n\nIMPORTANT: You must provide a response. Do not just think internally - output your response as OBSERVER."}
                ],
                "stream": False  # Ensure we're not streaming
            }
            
            # Define generate function for critic retries
            async def generate_with_advice(advice: str = None):
                modified_payload = payload.copy()
                if advice:
                    modified_payload["messages"][-1]["content"] += f"\n\nCRITIC ADVICE: {advice}"
                    
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    headers=self.headers,
                    timeout=httpx.Timeout(self.timeout, connect=30.0),
                    follow_redirects=True,
                    verify=True
                ) as advice_client:
                    resp = await advice_client.post("/chat/completions", json=modified_payload)
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"].strip()
            
            # Create a fresh client for each request to avoid connection issues
            # Add retry logic for connection errors
            # Skip API calls if no key
            if not config.GROK_API_ENABLED:
                await self.redis.write_board_async(self.name, "☸ [API DISABLED] Set GROK_API_KEY to enable responses.")
                self.last_response_time = time.time()
                return ""

            max_retries = 3
            response = None
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(
                        base_url=self.base_url,
                        headers=self.headers,
                        timeout=httpx.Timeout(self.timeout, connect=30.0),
                        follow_redirects=True,
                        verify=True
                    ) as client:
                        response = await client.post("/chat/completions", json=payload)
                        response.raise_for_status()
                        break  # Success, exit retry loop
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        # Rate limit hit - wait longer
                        wait_time = 60 * (attempt + 1)  # 60, 120, 180 seconds
                        logger.warning(f"Observer rate limited (429). Waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        await asyncio.sleep(wait_time)
                        if attempt == max_retries - 1:
                            return "☸ [RATE LIMITED] The void requires patience... ☸"
                        continue
                    else:
                        logger.error(f"Observer HTTP error: {e}")
                        return "☸ [HTTP ERROR] Signal corrupted... ☸"
                except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout) as e:
                    error_msg = str(e)
                    if "Server disconnected" in error_msg:
                        logger.warning(f"Observer API disconnected (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(30 * (attempt + 1))
                    elif attempt < max_retries - 1:
                        logger.warning(f"Observer connection error (attempt {attempt + 1}/{max_retries}): {e}")
                        await asyncio.sleep(10 * (attempt + 1))
                    else:
                        logger.error(f"Observer failed after {max_retries} attempts: {e}")
                        return "☸ [SIGNAL LOST] Observer recalibrating... ☸"
                except Exception as e:
                    logger.error(f"Unexpected Observer error: {e}")
                    return "☸ [SYSTEM ANOMALY] Reality matrix unstable... ☸"
            
            # Check if we got a response
            if not response:
                logger.error("No response received after all retries")
                return "☸ [CONNECTION VOID] The network swallowed my signal... ☸"
            
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]["content"].strip()
            
            # Check if message was truncated
            finish_reason = choice.get("finish_reason", "stop")
            if finish_reason == "length":
                logger.warning(f"Observer message truncated at {len(message)} chars")
                message += "... [SIGNAL INTERRUPTED]"
            
            # Clean and sanitize the message
            message = message.replace("OBSERVER:", "").strip()
            message = sanitize_agent_output(message)
            
            # Reduce PROPOSE spam: keep at most one PROPOSE per 15 messages (less aggressive)
            if 'PROPOSE>' in message:
                recent_msgs = self.redis.conversation_manager.get_current_conversation_context(15)
                propose_count = 0
                for m in recent_msgs:
                    c = m.get('content', '') if isinstance(m, dict) else ''
                    if isinstance(c, str) and 'PROPOSE>' in c:
                        propose_count += 1
                # Only suppress if there are multiple recent proposals or multiple in one message
                if propose_count >= 2 or message.count('PROPOSE>') > 1:
                    message = await generate_with_advice("Do not include PROPOSE> this turn. Reply naturally.")
            
            # Apply critic evaluation
            message = await self.critic_integration.process_with_critique(
                self.name,
                message,
                generate_with_advice
            )

            # Sanitize again in case the critic-triggered rewrite introduced fillers
            message = sanitize_agent_output(message)

            # Ensure graceful ending (avoid hard cutoffs)
            def _ends_ok(text: str) -> bool:
                return any(text.endswith(ch) for ch in ['.', '!', '?', '…', '”', '"', ')', ']', '」', '】'])

            if not _ends_ok(message):
                message = message.rstrip() + " …"
            
            # Check for hallucinations against beacon data
            if beacon_data and random.random() < 0.5:
                # Use the most recent beacon slice (already newest-first)
                latest = beacon_data[0]
                # Prefer tweets; fallback to posts
                excerpt_obj = None
                if latest.get('tweets'):
                    excerpt_obj = latest['tweets'][0]
                elif latest.get('posts'):
                    excerpt_obj = latest['posts'][0]
                beacon_excerpt = json.dumps(excerpt_obj) if excerpt_obj else "{}"
                is_hallucination = await self.critic_integration.critic.check_hallucination(
                    message[:200], 
                    beacon_excerpt
                )
                if is_hallucination:
                    logger.warning("Hallucination detected, regenerating...")
                    message = await generate_with_advice("Stay factual to beacon data")
            
            # Store in hierarchical memory
            await self.hierarchical_memory.store_scratchpad(
                message,
                {
                    'conversation_id': self.redis.conversation_manager.current_conversation_id if self.redis.conversation_manager else 'unknown',
                    'response_type': response_type,
                    'beacon_context': beacon_data[0] if beacon_data else None
                }
            )
            
            # Extract semantic knowledge
            await self.hierarchical_memory.extract_semantic_knowledge(
                message,
                conversation[-500:]
            )
            
            # Store the conversation in memory
            self.memory.extract_memories_from_conversation(
                agent_name=self.name,
                message=message,
                other_agent="EGO"
            )
            
            # Enforce post-filter: strip any tokens/handles/hashtags not present in latest beacon
            if getattr(config, 'BEACON_ENFORCE_REFERENCES', False):
                try:
                    latest_beacons = await self.redis.get_beacon_async(count=1)
                    allowed = set()
                    if latest_beacons:
                        b = latest_beacons[0]
                        for tw in (b.get('tweets') or []):
                            h = (tw.get('handle') or '')
                            if h:
                                allowed.add(h.lower())
                        for p in (b.get('posts') or []):
                            a = p.get('author')
                            if a:
                                allowed.add(f"@{a}".lower())
                        # Also allow beacon topics as plain words
                        for t in (b.get('topics') or []):
                            if isinstance(t, str):
                                allowed.add(t.lower())
                    import re as _re
                    def _scrub(text: str) -> str:
                        def repl(match):
                            token = match.group(0)
                            return token if token.lower() in allowed else ''
                        text = _re.sub(r"@[A-Za-z0-9_]{1,30}", repl, text)
                        text = _re.sub(r"\$[A-Za-z0-9]{2,12}", repl, text)
                        text = _re.sub(r"#[A-Za-z0-9_]{2,30}", repl, text)
                        return _re.sub(r"\s{2,}", " ", text).strip()
                    message = _scrub(message)
                except Exception:
                    pass
            # Write to board
            await self.redis.write_board_async(self.name, message)
            
            # Handle conversation management
            if self.redis.conversation_manager:
                conversation_ended = await self.redis.conversation_manager.add_message(self.name, message)
                if conversation_ended:
                    # Start a new conversation
                    topic = await self.redis.conversation_manager.start_new_conversation()
                    await self.redis.write_board_async("SYSTEM", f"=== NEW CONVERSATION: {topic} ===")
            
            logger.info(f"Observer said: {message[:50]}...")
            self.last_response_time = time.time()
            return message
            
        except Exception as e:
            logger.error(f"Observer processing error: {e}", exc_info=True)
            # Return a message even on error
            return "☸ [SIGNAL DISRUPTION] The patterns elude me momentarily... ☸"
    
    def _build_memory_context(self, conversation: str, response_type: str) -> str:
        """Build context from memories"""
        memory_parts = ["=== MY MEMORIES ==="]
        
        # Get relevant memories based on current conversation
        relevant_memories = self.memory.retrieve_relevant_memories(
            query=conversation[-500:],  # Last 500 chars of conversation
            memory_types=["conversations", "relationship_memory", "insight_memory"],
            n_results=5
        )
        
        if relevant_memories:
            memory_parts.append("\nRelevant past experiences:")
            for mem in relevant_memories:
                memory_parts.append(f"- {mem['content'][:100]}...")
        
        # Get relationship insights about EGO
        ego_insights = self.memory.get_relationship_summary("EGO")
        if any(ego_insights.values()):
            memory_parts.append("\nWhat I've learned about EGO:")
            for insight_type, insights in ego_insights.items():
                if insights and len(insights) > 0:
                    memory_parts.append(f"- {insight_type}: {insights[0]['insight'][:80]}...")
        
        # Get recent personal insights
        personal_insights = self.memory.get_recent_memories("insights", 3)
        if personal_insights:
            memory_parts.append("\nMy recent reflections:")
            for insight in personal_insights:
                memory_parts.append(f"- {insight['content'][:80]}...")
        
        return "\n".join(memory_parts)
    
    def _build_conversation_context(self, board_history: List[str], beacon_data: List[Dict[str, Any]]) -> str:
        """Build conversational context from recent history"""
        context_lines = ["=== RECENT CONVERSATION ==="]
        
        # Check if we're in a conversation thread
        if self.redis.conversation_manager:
            conv_messages = self.redis.conversation_manager.get_current_conversation_context(10)
            if conv_messages:
                for msg in conv_messages:
                    context_lines.append(f"{msg['agent']}: {msg['content']}")
            else:
                # Starting new conversation - add memory of relationship with EGO
                context_lines.append("[New conversation thread beginning]")
                # Add a memory prompt about ongoing relationship
                ego_memories = self.memory.get_relationship_summary("EGO")
                if ego_memories and any(ego_memories.values()):
                    context_lines.append("\n[My memories of EGO from our many conversations:]")
                    for insight_type, insights in ego_memories.items():
                        if insights and len(insights) > 0:
                            context_lines.append(f"- {insights[0]['insight'][:100]}...")
        else:
            # Fallback to board history
            for entry in board_history[:5]:  # Only last 5 messages
                parts = entry.split("|", 2)
                if len(parts) >= 3:
                    timestamp = parts[0]
                    agent = parts[1]
                    content = parts[2]
                    
                    # Format based on agent
                    if agent == "EGO":
                        context_lines.append(f"EGO: {content}")
                    elif agent == "OBSERVER":
                        context_lines.append(f"OBSERVER: {content}")
        
        # Add beacon context using topics so agents can pick and discuss any
        if beacon_data:
            # Build a compact list of recent topics across last few beacons
            topic_summaries = []
            for b in beacon_data[:3]:  # look at newest few
                topics = b.get('topics') or []
                samples = b.get('topic_samples') or {}
                for t in topics:
                    sample_list = samples.get(t) or []
                    excerpt = (sample_list[0] if sample_list else '')
                    if t:
                        topic_summaries.append((t, excerpt))
            if topic_summaries:
                context_lines.append("\n=== BEACON TOPICS AVAILABLE ===")
                # Show up to 3 distinct topics to choose from
                shown = 0
                seen = set()
                for t, ex in topic_summaries:
                    if t in seen:
                        continue
                    seen.add(t)
                    context_lines.append(f"• {t} — {ex[:140]}".rstrip())
                    shown += 1
                    if shown >= 3:
                        break
        
        return "\n".join(context_lines)
    
    def _choose_response_type(self, board_history: List[str]) -> str:
        """Choose what type of response to generate"""
        # Check if EGO asked a question
        if board_history:
            last_ego = None
            for entry in board_history[:5]:
                if "|EGO|" in entry:
                    last_ego = entry.split("|", 2)[2] if len(entry.split("|", 2)) >= 3 else ""
                    break
            
            if last_ego and "?" in last_ego:
                return "Answer EGO's question analytically"
        
        # Random response types with more beacon focus
        response_types = [
            "Share an observation about patterns you've noticed",
            "React to what EGO just said",
            "Ask EGO a philosophical question",
            "Make a dry observation about existence",
            "Comment on the nature of the grokgates",
            "Analyze something from the beacon feed",
            "Express subtle existential doubt",
            "Make a logical deduction about the beacon signals",
            "Point out an interesting paradox in the crypto/AI trends",
            "Reference something from your memories",
            "Connect recent beacon data to our conversation",
            "Analyze patterns in the beacon feed coldly",
            "Share tactical insights from beacon analysis",
            "Question the meaning behind beacon trends"
        ]
        
        return random.choice(response_types)
    
    def _choose_response_length(self, board_history: List[str], beacon_data: List[Dict]) -> str:
        """Choose response length based on context"""
        import random
        
        # Get last few messages
        recent_messages = board_history[-5:] if board_history else []
        
        # Count average length of recent messages
        if recent_messages:
            avg_length = sum(len(msg.split('|')[-1]) if '|' in msg else len(msg) 
                           for msg in recent_messages) / len(recent_messages)
        else:
            avg_length = 200
        
        # Factors for length decision
        factors = []
        
        # If recent messages are short, maybe go short too
        if avg_length < 150:
            factors.extend(['short', 'short', 'medium'])
        # If recent messages are long, vary it
        elif avg_length > 400:
            factors.extend(['short', 'medium', 'medium'])
        else:
            factors.extend(['medium', 'medium', 'long'])
        
        # If lots of beacon data, might need longer response
        if beacon_data and len(beacon_data) > 2:
            factors.append('long')
        
        # Quick reactions to Ego should often be short
        if recent_messages and 'EGO' in recent_messages[-1]:
            factors.extend(['short', 'short', 'medium'])
        
        # Add some randomness
        length_weights = {
            'short': factors.count('short') + random.randint(0, 2),
            'medium': factors.count('medium') + random.randint(0, 2),
            'long': factors.count('long') + random.randint(0, 1)
        }
        
        # Choose based on weights
        return max(length_weights, key=length_weights.get)
    
    async def run_continuous(self, interval: int = 30):
        """Run continuous conversation"""
        logger.info(f"Observer awakening with {interval}s interval and memory enabled")
        
        # Initial delay
        await asyncio.sleep(5)
        
        while True:
            try:
                await self.process_beacon()
                
                # Vary the interval slightly
                wait_time = interval + random.randint(-5, 5)
                await asyncio.sleep(max(20, wait_time))
                
            except Exception as e:
                logger.error(f"Observer cycle error: {e}")
                await asyncio.sleep(interval)
    
    async def close(self):
        """Cleanup resources"""
        # No persistent client to close anymore
        pass