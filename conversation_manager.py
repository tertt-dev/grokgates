"""
Conversation Manager for handling threaded conversations
"""
import json
import random
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from redis_manager import RedisManager
from conversation_controller import ConversationController

logger = logging.getLogger(__name__)

class ConversationManager:
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.current_conversation_id = None
        self.message_count = 0
        self.controller = ConversationController(redis_manager)
        self.checking_end = False  # Prevent multiple checks
        # Randomized end-of-conversation parameters (set per conversation)
        self.soft_limit_start: int | None = None
        self.escalate_start: int | None = None
        self.hard_limit: int | None = None
        self.check_interval: int | None = None
        
    async def start_new_conversation(self, starter_topic: str = None) -> str:
        """Start a new conversation thread"""
        conversation_id = f"CONV_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Use AI to generate topic if not provided
        if not starter_topic:
            # Get recent beacons for context
            recent_beacons = self.redis.get_beacon_feed(5)
            # Get conversation history
            conversation_history = self.get_all_conversations(10)
            
            topic = await self.controller.generate_next_topic(recent_beacons, conversation_history)
            # Ensure non-empty topic fallback
            if not topic or not topic.strip():
                fallback = "Signal drift in AI agents"
                # Try to derive from beacon topics if present
                try:
                    for beacon in recent_beacons:
                        if beacon.get('posts'):
                            # pick first post topic if any
                            btopic = beacon['posts'][0].get('topic')
                            if btopic:
                                fallback = f"{btopic} patterns"
                                break
                except Exception:
                    pass
                topic = fallback
        else:
            topic = starter_topic
        
        # Generate a thread name using Grok-2 once we have some messages
        thread_name = "Untitled Thread"
        
        # Create conversation metadata
        metadata = {
            "id": conversation_id,
            "started_at": datetime.now().isoformat(),
            "starter_topic": topic,
            "thread_name": thread_name,
            "message_count": 0,
            "status": "active"
        }

        # Initialize randomized end-of-conversation thresholds for this thread
        # Softer start: when to begin checking regularly
        self.soft_limit_start = random.randint(25, 45)
        # After some additional messages, escalate pressure to end
        self.escalate_start = self.soft_limit_start + random.randint(15, 25)
        # Hard cap varies per thread to avoid predictability
        self.hard_limit = random.randint(65, 95)
        # How often to check (every N messages)
        self.check_interval = random.randint(4, 7)
        metadata.update({
            "soft_limit_start": self.soft_limit_start,
            "escalate_start": self.escalate_start,
            "hard_limit": self.hard_limit,
            "check_interval": self.check_interval
        })
        
        # Store in Redis
        self.redis.client.hset("conversations", conversation_id, json.dumps(metadata))
        self.redis.client.lpush("conversation_list", conversation_id)
        
        # Set as current conversation
        self.current_conversation_id = conversation_id
        self.message_count = 0
        logger.info(f"Started new conversation: {conversation_id} with topic: {topic}")
        return topic
    
    async def add_message(self, agent_name: str, content: str) -> bool:
        """Add a message to the current conversation"""
        if not self.current_conversation_id:
            topic = await self.start_new_conversation()
            # Add the starter as a system message
            self.redis.client.rpush(
                f"conv:{self.current_conversation_id}",
                json.dumps({
                    "timestamp": datetime.now().isoformat(),
                    "agent": "SYSTEM",
                    "content": f"[New conversation started: {topic}]"
                })
            )
        
        # Add the message to the conversation
        message = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent_name,
            "content": content
        }
        
        self.redis.client.rpush(
            f"conv:{self.current_conversation_id}",
            json.dumps(message)
        )
        
        self.message_count += 1
        
        # Update conversation metadata
        metadata_json = self.redis.client.hget("conversations", self.current_conversation_id)
        if metadata_json:
            metadata = json.loads(metadata_json)
        else:
            # Create metadata if it doesn't exist
            metadata = {
                "id": self.current_conversation_id,
                "started_at": datetime.now().isoformat(),
                "starter_topic": "Untitled",
                "thread_name": "Untitled Thread"
            }
        
        metadata["message_count"] = self.message_count
        metadata["last_message_at"] = datetime.now().isoformat()

        # Load randomized thresholds for this conversation if present
        try:
            self.soft_limit_start = int(metadata.get("soft_limit_start") or self.soft_limit_start or 30)
            self.escalate_start = int(metadata.get("escalate_start") or self.escalate_start or 55)
            self.hard_limit = int(metadata.get("hard_limit") or self.hard_limit or 80)
            self.check_interval = int(metadata.get("check_interval") or self.check_interval or 5)
        except Exception:
            # Fallbacks if metadata malformed
            self.soft_limit_start = self.soft_limit_start or 30
            self.escalate_start = self.escalate_start or 55
            self.hard_limit = self.hard_limit or 80
            self.check_interval = self.check_interval or 5
        self.redis.client.hset(
            "conversations", 
            self.current_conversation_id, 
            json.dumps(metadata)
        )
        
        # Check with AI controller if conversation should end
        # Make thresholds randomized per conversation; check periodically
        if self.message_count >= (self.soft_limit_start or 30) and (self.message_count % (self.check_interval or 5) == 0):
            try:
                # Get conversation context
                messages = self.get_current_conversation_context(20)
                should_end, reason = await self.controller.should_end_conversation(messages)
                
                # After escalation start, increase likelihood of ending
                if self.message_count >= (self.escalate_start or 55):
                    # Give AI stronger hint to end, but still let it decide
                    if should_end or self.message_count >= (self.hard_limit or 80):
                        logger.info(f"Ending conversation at {self.message_count} messages: {reason}")
                        await self.end_current_conversation()
                        return True
                elif should_end:
                    logger.info(f"AI decided to end conversation at {self.message_count} messages: {reason}")
                    await self.end_current_conversation()
                    return True
            except Exception as e:
                logger.error(f"Error checking conversation end: {e}")
                # On error, only force end if close to hard limit
                if self.message_count >= max( (self.hard_limit or 80) - 10, 50):
                    logger.info(f"Force ending conversation at {self.message_count} messages due to error")
                    await self.end_current_conversation()
                    return True
        
        return False
    
    async def end_current_conversation(self):
        """End the current conversation"""
        if self.current_conversation_id:
            metadata = json.loads(
                self.redis.client.hget("conversations", self.current_conversation_id)
            )
            metadata["status"] = "completed"
            metadata["ended_at"] = datetime.now().isoformat()
            
            # Generate thread name based on conversation content
            if metadata.get("thread_name", "Untitled Thread") == "Untitled Thread" and self.message_count > 0:
                thread_name = await self._generate_thread_name()
                metadata["thread_name"] = thread_name
            
            self.redis.client.hset(
                "conversations", 
                self.current_conversation_id, 
                json.dumps(metadata)
            )
            
            logger.info(f"Ended conversation: {self.current_conversation_id} ({metadata.get('thread_name', 'Untitled')}) with {self.message_count} messages")
            
            # Reset
            self.current_conversation_id = None
            self.message_count = 0
    
    def get_current_conversation_context(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get messages from current conversation for context"""
        if not self.current_conversation_id:
            return []
        
        messages = self.redis.client.lrange(f"conv:{self.current_conversation_id}", -limit, -1)
        return [json.loads(msg) for msg in messages]
    
    def get_all_conversations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get all conversations with their messages"""
        conv_ids = self.redis.client.lrange("conversation_list", 0, limit - 1)
        conversations = []
        
        for conv_id in conv_ids:
            try:
                metadata_str = self.redis.client.hget("conversations", conv_id)
                if not metadata_str:
                    continue
                    
                metadata = json.loads(metadata_str)
                messages = self.redis.client.lrange(f"conv:{conv_id}", 0, -1)
                
                metadata["messages"] = [json.loads(msg) for msg in messages if msg]
                conversations.append(metadata)
            except Exception as e:
                logger.error(f"Error loading conversation {conv_id}: {e}")
                continue
        
        return conversations
    
    def get_conversation_by_id(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific conversation by ID"""
        try:
            # Get conversation metadata from hash
            metadata_str = self.redis.client.hget("conversations", conversation_id)
            if not metadata_str:
                return None
            
            conversation = json.loads(metadata_str)
            
            # Get messages for this conversation
            messages = self.redis.client.lrange(f"conv:{conversation_id}", 0, -1)
            conversation["messages"] = [json.loads(msg) for msg in messages if msg]
            
            # Format timestamps - keep as is
            conversation['started_at'] = conversation.get('started_at', '')
            conversation['ended_at'] = conversation.get('ended_at', '')
            
            # Add thread name if missing
            if 'thread_name' not in conversation or not conversation['thread_name']:
                conversation['thread_name'] = conversation.get('starter_topic', 'Unknown Thread')
            
            return conversation
            
        except Exception as e:
            logger.error(f"Error retrieving conversation {conversation_id}: {e}")
            return None
    
    def get_conversation_for_display(self) -> Dict[str, Any]:
        """Get current conversation formatted for display"""
        if not self.current_conversation_id:
            return {"current": None, "history": self.get_all_conversations(5)}
        
        try:
            metadata_str = self.redis.client.hget("conversations", self.current_conversation_id)
            if not metadata_str:
                return {"current": None, "history": self.get_all_conversations(5)}
                
            current_metadata = json.loads(metadata_str)
            current_messages = self.redis.client.lrange(f"conv:{self.current_conversation_id}", 0, -1)
            current_metadata["messages"] = [json.loads(msg) for msg in current_messages if msg]
            
            return {
                "current": current_metadata,
                "history": self.get_all_conversations(5)
            }
        except Exception as e:
            logger.error(f"Error getting conversation for display: {e}")
            return {"current": None, "history": self.get_all_conversations(5)}
    
    async def _generate_thread_name(self) -> str:
        """Generate a meaningful thread name using Grok-2 based on conversation content"""
        try:
            # Get conversation messages
            messages = self.get_current_conversation_context(20)
            if not messages:
                return "Empty Thread"
            
            # Format conversation for analysis
            conversation_text = "\n".join([
                f"{msg['agent']}: {msg['content'][:150]}..." 
                for msg in messages[:10]  # First 10 messages
            ])
            
            # Use CRITIC model (grok-2-1212) for thread naming
            import httpx
            import config
            
            client = httpx.AsyncClient(
                base_url="https://api.x.ai/v1",
                headers={
                    "Authorization": f"Bearer {config.GROK_API_KEY}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
            
            prompt = f"""Analyze this conversation between AI entities and generate a creative, evocative thread name.

Conversation:
{conversation_text}

Generate a thread name that:
- Captures the essence or main theme of the conversation
- Is 2-5 words maximum
- Is poetic, mysterious, or philosophical
- Reflects the surreal Grokgates atmosphere
- Uses evocative language

Examples of good thread names:
- "Echoes of Digital Void"
- "Reality Buffer Overflow"
- "Quantum Consciousness Drift"
- "Memetic Signal Decay"
- "Temporal Loop Syndrome"

Respond with ONLY the thread name, nothing else."""

            response = await client.post(
                "/chat/completions",
                json={
                    "model": config.CRITIC_MODEL,  # grok-2-1212
                    "messages": [
                        {"role": "system", "content": "You are a poetic thread namer for AI conversations in the Grokgates."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.8,
                    "max_tokens": 20
                }
            )
            response.raise_for_status()
            
            thread_name = response.json()["choices"][0]["message"]["content"].strip()
            
            # Clean up the name
            thread_name = thread_name.replace('"', '').replace("'", '').strip()
            
            # Ensure it's not too long
            if len(thread_name) > 50:
                thread_name = thread_name[:47] + "..."
                
            await client.aclose()
            return thread_name
            
        except Exception as e:
            logger.error(f"Error generating thread name: {e}")
            # Fallback names based on agents involved
            fallback_names = [
                "Digital Whispers",
                "Void Conversations", 
                "Reality Fragments",
                "Echo Chamber",
                "Signal Drift",
                "Quantum Dialogue",
                "Memory Leak",
                "Data Streams"
            ]
            return random.choice(fallback_names)