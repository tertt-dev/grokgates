"""
Memory Consolidation Job
Run nightly to consolidate short-term memories into long-term storage
"""
import asyncio
import json
import logging
from datetime import datetime
from redis_manager import RedisManager
from hierarchical_memory import HierarchicalMemory
from conversation_manager import ConversationManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def consolidate_all_memories():
    """Run memory consolidation for all agents"""
    logger.info(f"Starting memory consolidation at {datetime.now()}")
    
    # Initialize components
    redis_mgr = RedisManager()
    
    # Consolidate for each agent
    agents = ['OBSERVER', 'EGO']
    
    for agent_name in agents:
        logger.info(f"Consolidating memories for {agent_name}")
        
        # Create hierarchical memory instance
        memory = HierarchicalMemory(agent_name, redis_mgr)
        
        try:
            # Run consolidation
            await memory.consolidate_memories()
            logger.info(f"Successfully consolidated memories for {agent_name}")
            
        except Exception as e:
            logger.error(f"Error consolidating memories for {agent_name}: {e}")
    
    # Also archive old conversations
    logger.info("Archiving old conversations...")
    conv_mgr = ConversationManager(redis_mgr)
    
    # Use current storage: list of IDs + hash for metadata + per-conv list for messages
    conv_ids = redis_mgr.client.lrange("conversation_list", 0, -1)
    archived_count = 0
    
    for conv_id in conv_ids:
        try:
            metadata_json = redis_mgr.client.hget("conversations", conv_id)
            if not metadata_json:
                continue
            conversation = json.loads(metadata_json)
            
            # Check if conversation is completed and substantial
            if (conversation.get('status') == 'completed' and 
                conversation.get('message_count', 0) >= 5):
                
                # Load messages for this conversation
                raw_msgs = redis_mgr.client.lrange(f"conv:{conv_id}", 0, -1)
                messages = [json.loads(m) for m in raw_msgs if m]
                
                # Create synopsis for each agent
                for agent_name in agents:
                    memory = HierarchicalMemory(agent_name, redis_mgr)
                    await memory.create_synopsis(
                        conversation['id'],
                        messages
                    )
                
                archived_count += 1
                
        except Exception as e:
            logger.error(f"Error processing conversation {conv_id}: {e}")
    
    logger.info(f"Archived {archived_count} conversations")
    logger.info(f"Memory consolidation completed at {datetime.now()}")

async def cleanup_old_scratchpad():
    """Clean up old scratchpad entries"""
    redis_mgr = RedisManager()
    
    # Delete scratchpad entries older than 24h (handled by Redis TTL)
    # But we can also clean up the lists
    for agent in ['OBSERVER', 'EGO']:
        list_key = f"scratchpad_list:{agent}"
        list_length = redis_mgr.client.llen(list_key)
        
        if list_length > 100:
            # Keep only last 100 entries
            redis_mgr.client.ltrim(list_key, 0, 99)
            logger.info(f"Trimmed scratchpad list for {agent}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--cleanup":
        # Run cleanup only
        asyncio.run(cleanup_old_scratchpad())
    else:
        # Run full consolidation
        asyncio.run(consolidate_all_memories())