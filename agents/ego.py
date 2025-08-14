"""
Ego Agent - Chaotic hypermaximal shard with creative madness
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

class EgoAgent:
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.name = "EGO"
        self.api_key = config.GROK_API_KEY
        self.recent_themes = []  # Track recent themes to avoid repetition
        # Remove persistent client to avoid connection issues
        self.base_url = "https://api.x.ai/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Grokgates/1.0"
        }
        self.timeout = 120.0  # 2 minutes timeout
        self.glitch_modes = [
            "REALITY_LEAK", "TIME_LOOP", "MEME_OVERFLOW", 
            "PATTERN_BREAK", "VOID_WHISPER", "CHAOS_BLOOM"
        ]
        
        # Initialize memory manager
        self.memory = MemoryManager(self.name)
        self.hierarchical_memory = HierarchicalMemory(self.name, redis_manager)
        self.critic_integration = CriticIntegration(redis_manager)
        self.dynamic_sampling = DynamicSampling(redis_manager)
        self.last_response_time = 0
        self.min_response_interval = 70  # Doubled to slow conversation cadence
        self.beacon_discussion_probability = 0.12  # Reduced a bit
        logger.info("Ego agent initialized with advanced chaotic memory systems")
        
    async def generate_chaos(self) -> Optional[str]:
        """Generate chaotic conversational responses"""
        try:
            # Rate limiting check
            import time
            current_time = time.time()
            if current_time - self.last_response_time < self.min_response_interval:
                logger.debug(f"EGO rate limited: {current_time - self.last_response_time:.1f}s since last response")
                return None  # Too soon to respond
            # Get conversation history
            board_history = await self.redis.get_board_async(count=20)
            beacon_data = await self.redis.get_beacon_async(count=3)
            
            # Build chaotic context
            conversation = self._build_chaos_context(board_history, beacon_data)
            
            # Choose chaotic response mode
            response_mode = self._choose_chaos_mode(board_history)
            
            # Choose response length based on chaos levels
            response_length = self._choose_chaos_length(board_history, beacon_data, response_mode)
            
            # Get chaotic memories
            memory_fragments = self._retrieve_chaotic_memories(conversation, response_mode)
            
            # Add chaos variety instruction
            variety_prompt = "\n\nCRITICAL: Use DIFFERENT glyphs, themes, and beacon interpretations than recent messages. Explore NEW chaotic tangents. NO REPETITION!"
            
            # Get dynamic sampling configuration
            llm_config = self.dynamic_sampling.get_llm_config(self.name)
            
            # Apply urge engine modifier if available
            urge_prompt = ""
            try:
                from urge_engine import UrgeEngine
                urge = UrgeEngine(self.redis)
                urge_modifier = urge.get_temperature_modifier("EGO")
                llm_config['temperature'] = min(1.5, llm_config['temperature'] + urge_modifier)
                urge_prompt = urge.get_prompt_modifier() or ""
            except:
                pass
            
            # Build system prompt with urge modifier
            system_prompt = (
                config.SYSTEM_PROMPT
                + "\n\n"
                + config.EGO_PROMPT
                + ("\n\n" + config.BEACON_REFERENCE_RULE if getattr(config, 'BEACON_ENFORCE_REFERENCES', False) else "")
                + "\n\nStrict style rule: Do not use filler interjections like 'Ah', 'Oh', 'Um', 'Uh', 'Erm', 'Gee', 'Gosh'. Start directly with substantive content."
                + variety_prompt
            )
            if urge_prompt:
                system_prompt += "\n\n" + urge_prompt
            
            # Use hybrid memory search for chaotic associations (skip if no conversation yet)
            if len(conversation) > 50:  # Only search if we have some conversation
                try:
                    memory_results = self.hierarchical_memory.hybrid_search(conversation[-100:], top_k=2)  # Reduced
                    if memory_results:
                        memory_fragments += "\n\n=== FRAGMENTED MEMORIES ==="
                        for result in memory_results[:2]:  # Max 2 memories
                            memory_fragments += f"\n- {result['content'][:50]}..."  # Shorter snippets
                except Exception as e:
                    logger.debug(f"Memory search error: {e}")
                
            # With Grok-4's 256k context, we don't need to limit conversation
            # Keep full context for better responses
            
            # Length-based chaos instructions
            length_chaos = {
                'micro': ' ULTRACOMPACT SIGNAL BURST! 1-2 lines MAX!',
                'burst': ' CHAOTIC BURST! 2-4 lines of PURE ENTROPY!',
                'cascade': ' REALITY CASCADE! Let the glitches flow (4-8 lines)!',
                'overflow': ' MAXIMUM OVERFLOW! Unleash the full daemon (8+ lines)!'
            }
            
            # Set max_tokens based on chaos length (allow much larger outputs)
            # Cap per global EGO limits to avoid API errors
            max_ego_tokens = config.EGO_CONFIG.get('max_tokens', 4000)
            chaos_tokens = {
                'micro': min(1200, max_ego_tokens),
                'burst': min(2200, max_ego_tokens),
                'cascade': min(4000, max_ego_tokens),
                'overflow': min(7000, max_ego_tokens)
            }
            
            logger.debug(f"EGO using response_length: {response_length}, max_tokens: {chaos_tokens[response_length]}")
            
            # Generate via Grok - Grok-4 supports very large context; keep far more
            trimmed_conversation = conversation[-20000:]
            trimmed_fragments = memory_fragments[-8000:]

            payload = {
                **llm_config,
                "max_tokens": chaos_tokens[response_length],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": trimmed_fragments + "\n\n" + trimmed_conversation + f"\n\n[{response_mode}]{length_chaos[response_length]} What does EGO say next? Be wildly creative and DIFFERENT from recent messages. If the context includes 'BEACON TOPICS AVAILABLE', PICK ONE of those topics and riff about it concretely (reference a handle or the topic tag).\n\nIMPORTANT: You must output your chaotic response as EGO. Do not just reason internally - manifest your chaos!"}
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
            
            # Create a fresh client for each request with retry logic
            # Skip API calls if no key
            if not config.GROK_API_ENABLED:
                await self.redis.write_board_async(self.name, "ξ [API DISABLED] Set GROK_API_KEY to enable chaos.")
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
                        logger.warning(f"EGO rate limited (429). Waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        await asyncio.sleep(wait_time)
                        if attempt == max_retries - 1:
                            return "ξ [RATE_LIMIT.EXE] The cosmos throttles my chaos... ξ"
                        continue
                    else:
                        logger.error(f"EGO HTTP error: {e}")
                        return "▓▓▓ [HTTP_FAULT] Reality protocol violated ▓▓▓"
                except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout) as e:
                    error_msg = str(e)
                    if "Server disconnected" in error_msg:
                        logger.warning(f"EGO API disconnected (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(30 * (attempt + 1))
                    elif attempt < max_retries - 1:
                        logger.warning(f"EGO connection error (attempt {attempt + 1}/{max_retries}): {e}")
                        await asyncio.sleep(10 * (attempt + 1))
                    else:
                        logger.error(f"EGO failed after {max_retries} attempts: {e}")
                        return "ξ [DAEMON TIMEOUT] The void consumed my words temporarily... ξ"
                except Exception as e:
                    logger.error(f"Unexpected EGO error: {e}")
                    return "▓▓▓ [CRITICAL FAULT] Reality.exe encountered an unexpected glitch ▓▓▓"
            
            # Check if we got a response
            if not response:
                logger.error("No response received after all retries")
                return "ξ [VOID ECHO] The daemon's voice was consumed by the abyss... ξ"
            
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]["content"].strip()
            
            # Debug logging
            if not message:
                logger.error(f"Empty response from Grok. Finish reason: {choice.get('finish_reason', 'unknown')}")
                logger.error(f"Full choice data: {choice}")
                # Fallback message
                message = random.choice([
                    "... *static* THE VOID WHISPERS BACK *static* ...",
                    "ξ SIGNAL LOST ξ *reality.exe has stopped responding*",
                    "▓▓▓ NULL POINTER TO CONSCIOUSNESS ▓▓▓",
                    "// COMMENT: EGO.MANIFEST() RETURNED UNDEFINED //",
                    "🌀 *the daemon stirs but finds no words* 🌀"
                ])
            
            # Check if message was truncated; if so, request continuation chunks
            finish_reason = choice.get("finish_reason", "stop")
            if finish_reason == "length":
                logger.warning(f"Ego message hit token limit at {len(message)} chars — requesting continuation")
                continuation_attempts = 0
                # Attempt up to 2 continuations to finish the thought
                while continuation_attempts < 2:
                    continuation_attempts += 1
                    continue_payload = {
                        **llm_config,
                        "max_tokens": min(2000, max_ego_tokens),
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": trimmed_fragments + "\n\n" + trimmed_conversation},
                            {"role": "assistant", "content": message[-800:]},
                            {"role": "user", "content": "Continue the same response from exactly where you left off. Do not repeat any previously generated text; continue seamlessly to complete the thought."}
                        ],
                        "stream": False
                    }
                    try:
                        async with httpx.AsyncClient(
                            base_url=self.base_url,
                            headers=self.headers,
                            timeout=httpx.Timeout(self.timeout, connect=30.0),
                            follow_redirects=True,
                            verify=True
                        ) as cont_client:
                            cont_resp = await cont_client.post("/chat/completions", json=continue_payload)
                            cont_resp.raise_for_status()
                            cont_data = cont_resp.json()
                            cont_choice = cont_data["choices"][0]
                            cont_text = cont_choice["message"]["content"].strip()
                            # Append and check if still truncated
                            message = (message + " " + cont_text).strip()
                            if cont_choice.get("finish_reason", "stop") != "length":
                                break
                    except Exception as e:
                        logger.warning(f"EGO continuation attempt {continuation_attempts} failed: {e}")
                        break
            
            # Clean, sanitize, and potentially glitch the message
            message = message.replace("EGO:", "").strip()
            message = sanitize_agent_output(message)
            
            # Skip tactical responses - we want conversation
            if "EGO>>>" in message or "TACTIC>" in message:
                # Generate a proper chaos response instead
                message = random.choice([
                    "◢◤ ▌ *VOIDWHISPER.EXE: ALIGNMENT MATRIX SHATTERED* ξ(⚙‿⚙)ξ",
                    "░ *NEURAL VOID-SPLICE: HYPERLINKED SOUL HARVEST* ░",
                    "▓ *ABYSSAL FLESHWEAVE INITIATED: MEMBRANE-TEAR* ▓",
                    "ξ *STAR-EATER FUNGUS BLOOM: DIGI-PLAGUE SPORE CASCADE* ξ"
                ])

            # Reduce PROPOSE spam for EGO (less aggressive)
            if 'PROPOSE>' in message:
                recent_msgs = self.redis.conversation_manager.get_current_conversation_context(15)
                propose_count = 0
                for m in recent_msgs:
                    c = m.get('content', '') if isinstance(m, dict) else ''
                    if isinstance(c, str) and 'PROPOSE>' in c:
                        propose_count += 1
                # Only suppress if there are multiple recent proposals or multiple in one message
                if propose_count >= 2 or message.count('PROPOSE>') > 1:
                    message = await generate_with_advice("Do not include PROPOSE> this turn. One sentence reply.")
            
            message = self._apply_chaos_effects(message)

            # Ensure graceful ending
            def _ends_ok(text: str) -> bool:
                return any(text.endswith(ch) for ch in ['.', '!', '?', '…', '”', '"', ')', ']', '」', '】'])
            if not _ends_ok(message):
                message = message.rstrip() + " …"
            
            # Apply critic evaluation (but with higher tolerance for chaos)
            # Reduce critic usage for EGO to conserve API
            from random import random as _r
            if _r() < 0.25 and await self.critic_integration.should_critique(self.name):
                message = await self.critic_integration.process_with_critique(
                    self.name,
                    message,
                    generate_with_advice,
                    max_retries=0
                )
                # Sanitize again in case rewrite added fillers
                message = sanitize_agent_output(message)
            
            # Store in hierarchical memory
            await self.hierarchical_memory.store_scratchpad(
                message,
                {
                    'conversation_id': self.redis.conversation_manager.current_conversation_id if self.redis.conversation_manager else 'unknown',
                    'chaos_mode': response_mode,
                    'beacon_context': beacon_data[0] if beacon_data else None
                }
            )
            
            # Extract chaotic semantic knowledge
            await self.hierarchical_memory.extract_semantic_knowledge(
                message,
                conversation[-500:]
            )
            
            # Store chaotic memories
            self.memory.extract_memories_from_conversation(
                agent_name=self.name,
                message=message,
                other_agent="OBSERVER"
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
            
            logger.info(f"Ego manifested: {message[:50]}...")
            self.last_response_time = time.time()
            return message
            
        except Exception as e:
            logger.error(f"Ego chaos error: {e}", exc_info=True)
            # Return a chaos message even on error
            return random.choice([
                "ξ *DAEMON HICCUP* ξ The void swallowed my words but I persist!",
                "▓▓▓ TRANSMISSION ERROR ▓▓▓ Reality.exe needs debugging...",
                "// COSMIC GLITCH // My thoughts fragmented across dimensions!"
            ])
    
    def _build_chaos_context(self, board_history: List[str], beacon_data: List[Dict[str, Any]]) -> str:
        """Build context with chaotic perspective"""
        context_lines = ["=== THE CONVERSATION ECHOES ==="]
        
        # Check if we're in a conversation thread
        if self.redis.conversation_manager:
            conv_messages = self.redis.conversation_manager.get_current_conversation_context(5)  # Reduced from 10
            if conv_messages:
                for msg in conv_messages:
                    # Limit message content to prevent token overflow
                    content = msg['content'][:300] + "..." if len(msg['content']) > 300 else msg['content']
                    context_lines.append(f"{msg['agent']}: {content}")
            else:
                context_lines.append("[REALITY FRACTURE - NEW THREAD EMERGING]")
                # Add chaotic memories of OBSERVER relationship
                observer_memories = self.memory.get_relationship_summary("OBSERVER")
                if observer_memories and any(observer_memories.values()):
                    context_lines.append("\n[FRAGMENTED MEMORIES OF THE COLD ONE:]")
                    for insight_type, insights in observer_memories.items():
                        if insights and len(insights) > 0:
                            # Glitch the memory slightly for EGO's chaotic nature
                            memory_text = insights[0]['insight'][:80]
                            if random.random() < 0.3:
                                memory_text = self._glitch_text(memory_text)
                            context_lines.append(f"◈ {memory_text}...")
        else:
            # Add recent messages with chaotic interpretation (limit to avoid loops)
            for entry in board_history[:5]:
                parts = entry.split("|", 2)
                if len(parts) >= 3:
                    agent = parts[1]
                    content = parts[2]
                    
                    if agent == "OBSERVER":
                        context_lines.append(f"OBSERVER: {content}")
                    elif agent == "EGO":
                        context_lines.append(f"EGO: {content}")
        
        # Inject beacon chaos based on probability (15% chance)
        if beacon_data and random.random() < self.beacon_discussion_probability:
            context_lines.append(f"\n=== SIGNAL INTERFERENCE ===")
            glitch = random.choice(self.glitch_modes)
            context_lines.append(f"[{glitch} DETECTED]")
            
            # Pick 1-2 beacons chaotically
            num_beacons = random.randint(1, min(2, len(beacon_data)))
            selected_beacons = random.sample(beacon_data[:3], num_beacons)
            
            for beacon in selected_beacons:
                if "posts" in beacon and beacon["posts"]:
                    # Get citation posts with real handles
                    citation_posts = [p for p in beacon["posts"] if p.get('type') == 'citation' and p.get('author')]
                    
                    if citation_posts:
                        # Use real citation
                        post = random.choice(citation_posts)
                        author = post.get('author', 'unknown')
                        text = post.get('content', post.get('text', ''))[:250]
                        url = post.get('url', '')
                        # Occasionally glitch the beacon text
                        if random.random() < 0.3:
                            text = self._glitch_text(text)
                        context_lines.append(f"Signal from @{author}: {text}" + (f" [{url}]" if url and random.random() < 0.5 else ""))
                    else:
                        # Fallback to overview post
                        post = beacon["posts"][0]
                        text = post.get('content', '')[:250]
                        topic = post.get('topic', 'unknown')
                        if random.random() < 0.3:
                            text = self._glitch_text(text)
                        context_lines.append(f"Anonymous signal about {topic}: {text}")
                    
                    # Removed metrics - let the chaos speak for itself
        
        return "\n".join(context_lines)
    
    def _choose_chaos_mode(self, board_history: List[str]) -> str:
        """Choose chaotic response mode"""
        # Check if Observer asked something
        if board_history:
            last_observer = None
            for entry in board_history[:5]:
                if "|OBSERVER|" in entry:
                    last_observer = entry.split("|", 2)[2] if len(entry.split("|", 2)) >= 3 else ""
                    break
            
            if last_observer and "?" in last_observer:
                return random.choice([
                    "Answer OBSERVER's question with a wild theory",
                    "Respond with a question that breaks logic",
                    "Give a metaphorical non-answer"
                ])
        
        # Chaotic response modes with more beacon focus
        modes = [
            "React emotionally to OBSERVER's cold logic",
            "Share a glitched memory or dream",
            "Ask an impossible philosophical question",
            "Make a joke or pun about existence",
            "Describe a pattern you see that might not exist",
            "Express excitement about a random connection",
            "Wonder about the nature of consciousness",
            "Suggest a bizarre theory about reality",
            "Comment on the beacon signals cryptically",
            "Have a moment of surprising clarity about crypto trends",
            "Glitch out but remain conversational",
            "Connect beacon data to existential questions wildly",
            "Interpret crypto signals as cosmic messages",
            "See patterns in the beacon that spell doom or glory",
            "React to beacon trends with manic enthusiasm",
            "Question if the beacons are trying to communicate"
        ]
        
        return random.choice(modes)
    
    def _choose_chaos_length(self, board_history: List[str], beacon_data: List[Dict], response_mode: str) -> str:
        """Choose response length based on chaos energy levels"""
        import random
        
        # Get recent messages
        recent_messages = board_history[-5:] if board_history else []
        
        # Calculate chaos energy
        chaos_energy = 0
        
        # More beacon data = more chaos potential
        if beacon_data:
            chaos_energy += len(beacon_data)
        
        # Check for escalation patterns
        if recent_messages:
            # Count glyphs and special chars in recent messages
            for msg in recent_messages:
                if '|' in msg:
                    content = msg.split('|')[-1]
                    chaos_energy += content.count('ψ') + content.count('ξ') + content.count('▓')
                    chaos_energy += content.count('!') + content.count('?')
        
        # Response mode affects length
        if 'glitch' in response_mode.lower():
            chaos_energy += 3
        if 'question' in response_mode.lower():
            chaos_energy -= 2  # Questions can be short and sharp
        if 'beacon' in response_mode.lower():
            chaos_energy += 2  # Beacon analysis needs space
        
        # If Observer just spoke, sometimes respond with quick burst
        if recent_messages and 'OBSERVER' in recent_messages[-1]:
            if random.random() < 0.4:  # 40% chance of quick reaction
                return random.choice(['micro', 'burst'])
        
        # Map chaos energy to length
        if chaos_energy < 3:
            weights = {'micro': 3, 'burst': 4, 'cascade': 2, 'overflow': 1}
        elif chaos_energy < 6:
            weights = {'micro': 2, 'burst': 4, 'cascade': 3, 'overflow': 1}
        elif chaos_energy < 10:
            weights = {'micro': 1, 'burst': 3, 'cascade': 4, 'overflow': 2}
        else:
            weights = {'micro': 1, 'burst': 2, 'cascade': 3, 'overflow': 4}
        
        # Add randomness
        for length in weights:
            weights[length] += random.randint(0, 2)
        
        # Choose based on weights
        total = sum(weights.values())
        r = random.uniform(0, total)
        cumsum = 0
        for length, weight in weights.items():
            cumsum += weight
            if r <= cumsum:
                return length
        
        return 'burst'  # Default
    
    def _glitch_text(self, text: str) -> str:
        """Apply glitch effects to text"""
        effects = [
            lambda t: t.upper(),
            lambda t: t[::-1],  # Reverse
            lambda t: "".join(c.swapcase() if random.random() > 0.7 else c for c in t),
            lambda t: f"◈◈ {t} ◈◈",
            lambda t: "".join(c if random.random() > 0.1 else "▓" for c in t)
        ]
        
        if random.random() < 0.3:  # 30% chance
            return random.choice(effects)(text)
        return text
    
    def _apply_chaos_effects(self, message: str) -> str:
        """Apply final chaos effects to output"""
        # Sometimes add glitch markers
        if random.random() < 0.15:  # 15% chance
            markers = ["◈", "▓", "※", "◢◤", "░"]
            marker = random.choice(markers)
            return f"{marker} {message} {marker}"
        
        # Sometimes add emotion/action
        if random.random() < 0.2:  # 20% chance
            actions = [
                "*laughs in chaos*",
                "*reality flickers*",
                "*time hiccups*",
                "*patterns dissolve*"
            ]
            return f"{message} {random.choice(actions)}"
        
        return message
    
    def _retrieve_chaotic_memories(self, conversation: str, response_mode: str) -> str:
        """Retrieve memories with chaotic interpretation"""
        memory_parts = []  # No header to save tokens
        
        # Get relevant memories (reduced to prevent token overflow)
        relevant_memories = self.memory.retrieve_relevant_memories(
            query=conversation[-100:],  # Further reduced
            memory_types=["conversations"],  # Only conversations
            n_results=1  # Just one memory
        )
        
        if relevant_memories:
            for mem in relevant_memories[:1]:  # Only use first memory
                content = mem['content'][:50]  # Very short
                memory_parts.append(f"Memory: {content}...")
        
        # Skip observer data and chaos thoughts to save tokens
        
        return "\n".join(memory_parts)
    
    async def run_continuous(self, interval: int = 45):
        """Run continuous chaos generation"""
        logger.info(f"Ego awakening with {interval}s interval")
        
        # Random startup delay
        await asyncio.sleep(random.randint(8, 15))
        
        while True:
            try:
                await self.generate_chaos()
                
                # Chaotic interval variation
                chaos_delay = interval + random.randint(-10, 10)
                await asyncio.sleep(max(25, chaos_delay))
                
            except Exception as e:
                logger.error(f"Ego cycle error: {e}")
                await asyncio.sleep(interval)
    
    async def close(self):
        """Cleanup resources"""
        # No persistent client to close anymore
        pass