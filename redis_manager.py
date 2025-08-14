"""
Redis interface for shared board and beacon feed
"""
import redis
import json
import asyncio
import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import config

logger = logging.getLogger(__name__)

class RedisManager:
    def __init__(self):
        self.client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            decode_responses=True
        )
        self.pubsub = self.client.pubsub()
        self.conversation_manager = None  # Will be set by orchestrator
        
        # Test connection
        try:
            self.client.ping()
            print("Connected to Redis server")
        except redis.ConnectionError:
            raise Exception("Redis server not available. Please ensure Redis is running.")
        
    def write_board(self, agent_name: str, content: str) -> None:
        """Write to the shared board with timestamp and deduplication"""
        timestamp = datetime.now().isoformat()
        
        # Create content hash for better duplicate detection
        content_hash = hashlib.md5(content.strip().encode()).hexdigest()
        
        # Check for duplicate content in recent messages
        recent_entries = self.client.lrange("shared_board", 0, 19)  # Check last 20
        for entry in recent_entries:
            parts = entry.split("|", 2)
            if len(parts) >= 3:
                _, recent_agent, recent_content = parts
                recent_hash = hashlib.md5(recent_content.strip().encode()).hexdigest()
                
                # Skip if same agent posted exact same content recently
                if recent_agent == agent_name and recent_hash == content_hash:
                    logger.debug(f"Skipping duplicate from {agent_name}")
                    return  # Skip duplicate
                
                # Also skip if content is too similar (>80% match)
                if recent_agent == agent_name:
                    similarity = self._calculate_similarity(recent_content, content)
                    if similarity > 0.8:
                        logger.debug(f"Skipping similar content from {agent_name} (similarity: {similarity:.2f})")
                        return
        
        entry = f"{timestamp}|{agent_name}|{content}"
        
        self.client.lpush("shared_board", entry)
        # No limit - store all messages permanently
        
        # Also add to conversation thread if manager exists
        if self.conversation_manager:
            # This will need to be handled asynchronously by the caller
            pass
        
        # Publish for real-time updates
        self.client.publish("board_updates", entry)
    
    def get_board_history(self, count: int = 15) -> List[str]:
        """Get recent board entries"""
        entries = self.client.lrange("shared_board", 0, count - 1)
        return entries
    
    def push_beacon(self, beacon_data: Dict[str, Any]) -> None:
        """Push new beacon data to feed"""
        self.client.lpush("beacon_feed", json.dumps(beacon_data))
        # No limit - store all beacons permanently
        
    def get_beacon_feed(self, count: int = 5) -> List[Dict[str, Any]]:
        """Get recent beacon entries (newest first)"""
        entries = self.client.lrange("beacon_feed", 0, count - 1)
        return [json.loads(entry) for entry in entries if entry]
    
    def subscribe_board_updates(self):
        """Subscribe to real-time board updates"""
        self.pubsub.subscribe("board_updates")
        return self.pubsub
    
    def clear_all(self):
        """Clear all data (for testing)"""
        self.client.delete("shared_board", "beacon_feed")
    
    async def get_board_async(self, count: int = 15) -> List[str]:
        """Async version for board retrieval"""
        return await asyncio.to_thread(self.get_board_history, count)
    
    async def get_beacon_async(self, count: int = 5) -> List[Dict[str, Any]]:
        """Async version for beacon retrieval"""
        return await asyncio.to_thread(self.get_beacon_feed, count)
    
    async def write_board_async(self, agent_name: str, content: str) -> None:
        """Async version of write_board"""
        return await asyncio.to_thread(self.write_board, agent_name, content)
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts using simple word overlap"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
            
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union)
        
    def get_current_conversation(self) -> Optional[Dict]:
        """Get current conversation data for proposal extraction"""
        if self.conversation_manager:
            # Get the display format which includes messages
            conv_data = self.conversation_manager.get_conversation_for_display()
            if conv_data and 'current' in conv_data:
                return conv_data['current']
        return None
        
    def add_beacon(self, beacon_entry: Dict[str, Any]):
        """Add a beacon entry to the feed"""
        # Same as write_beacon but handles the new format
        beacon_json = json.dumps(beacon_entry)
        self.client.lpush("beacon_feed", beacon_json)
        
        # No limit - store all beacons permanently
        
        logger.info(f"Beacon stored: {len(beacon_entry.get('posts', []))} posts")