"""
Hierarchical Memory System
- Scratchpad (≤ 24h) → Redis
- Vector Memory (long-term) → ChromaDB
- Synopsis Memory → Condensed episodic summaries
"""
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import hashlib
import httpx
import chromadb
from chromadb.utils import embedding_functions
from chromadb.config import Settings
from redis_manager import RedisManager
import config

logger = logging.getLogger(__name__)

class HierarchicalMemory:
    def __init__(self, agent_name: str, redis_manager: RedisManager):
        self.agent_name = agent_name
        self.redis = redis_manager
        
        # Initialize ChromaDB for long-term vector memory
        self.chroma_client = chromadb.PersistentClient(
            path=f"./chroma_db/{agent_name}_hierarchical",
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Create collections for different memory types
        self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        
        # Long-term episodic memories
        self.episodic_collection = self.chroma_client.get_or_create_collection(
            name=f"{agent_name}_episodic",
            embedding_function=self.embedding_fn
        )
        
        # Synopsis memories (compressed summaries)
        self.synopsis_collection = self.chroma_client.get_or_create_collection(
            name=f"{agent_name}_synopsis",
            embedding_function=self.embedding_fn
        )
        
        # Semantic knowledge extracted from conversations
        self.semantic_collection = self.chroma_client.get_or_create_collection(
            name=f"{agent_name}_semantic",
            embedding_function=self.embedding_fn
        )
        
    async def store_scratchpad(self, content: str, metadata: Dict[str, Any]):
        """Store in short-term scratchpad (Redis, 24h TTL)"""
        entry = {
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'agent': self.agent_name,
            'metadata': metadata
        }
        
        key = f"scratchpad:{self.agent_name}:{datetime.now().timestamp()}"
        self.redis.client.setex(key, 86400, json.dumps(entry))  # 24h TTL
        
        # Also add to recent scratchpad list
        self.redis.client.lpush(f"scratchpad_list:{self.agent_name}", key)
        self.redis.client.ltrim(f"scratchpad_list:{self.agent_name}", 0, 99)
        
    async def get_scratchpad(self, count: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent scratchpad entries"""
        keys = self.redis.client.lrange(f"scratchpad_list:{self.agent_name}", 0, count-1)
        entries = []
        
        for key in keys:
            data = self.redis.client.get(key)
            if data:
                entries.append(json.loads(data))
                
        return entries
        
    async def promote_to_episodic(self, content: str, metadata: Dict[str, Any]):
        """Promote important memories to long-term episodic storage"""
        doc_id = hashlib.md5(f"{content}{datetime.now().isoformat()}".encode()).hexdigest()
        
        self.episodic_collection.add(
            documents=[content],
            ids=[doc_id],
            metadatas=[{
                'timestamp': datetime.now().isoformat(),
                'agent': self.agent_name,
                **metadata
            }]
        )
        
        logger.info(f"Promoted memory to episodic storage: {doc_id}")
        
    async def create_synopsis(self, conversation_id: str, messages: List[Dict[str, Any]]):
        """Create a compressed synopsis of a conversation"""
        if not messages:
            return
            
        # Prepare conversation text
        conversation_text = "\n".join([
            f"{msg['agent']}: {msg['content']}"
            for msg in messages[:20]  # Limit to prevent token overflow
        ])
        
        # Generate synopsis using LLM
        synopsis = await self._generate_synopsis(conversation_text)
        
        if synopsis:
            # Store in synopsis collection
            doc_id = f"synopsis_{conversation_id}"
            
            self.synopsis_collection.add(
                documents=[synopsis],
                ids=[doc_id],
                metadatas=[{
                    'conversation_id': conversation_id,
                    'timestamp': datetime.now().isoformat(),
                    'agent': self.agent_name,
                    'message_count': len(messages),
                    'original_length': len(conversation_text)
                }]
            )
            
            logger.info(f"Created synopsis for {conversation_id}: {len(synopsis)} chars")
            
    async def _generate_synopsis(self, conversation: str) -> Optional[str]:
        """Generate a synopsis using the LLM"""
        try:
            headers = {
                'Authorization': f'Bearer {config.GROK_API_KEY}',
                'Content-Type': 'application/json'
            }
            
            prompt = f"""Summarize this conversation in ≤256 tokens. Focus on:
1. Key topics discussed
2. Important discoveries or insights
3. Emotional tone and dynamics

Conversation:
{conversation[:2000]}

Write a dense, information-rich summary:"""

            data = {
                "model": config.GROK_MODEL,
                "messages": [
                    {"role": "system", "content": "You create concise, dense summaries."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 256
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result['choices'][0]['message']['content'].strip()
                    
        except Exception as e:
            logger.error(f"Synopsis generation error: {e}")
            
        return None
        
    async def extract_semantic_knowledge(self, content: str, context: str):
        """Extract semantic facts and store them separately"""
        # Extract entities, facts, relationships
        facts = await self._extract_facts(content, context)
        
        for fact in facts:
            doc_id = hashlib.md5(fact.encode()).hexdigest()
            
            # Check if fact already exists
            existing = self.semantic_collection.get(ids=[doc_id])
            if not existing['ids']:
                self.semantic_collection.add(
                    documents=[fact],
                    ids=[doc_id],
                    metadatas=[{
                        'timestamp': datetime.now().isoformat(),
                        'agent': self.agent_name,
                        'source_context': context[:200]
                    }]
                )
                
    async def _extract_facts(self, content: str, context: str) -> List[str]:
        """Extract semantic facts from content"""
        # Simple extraction - in production, use NER or more sophisticated methods
        facts = []
        
        # Look for patterns like "X is Y", "X causes Y", etc.
        import re
        
        # Token/price patterns
        price_pattern = r'(\$\w+)\s+(?:is|at|reached|hit)\s+([\d.]+[km]?)'
        for match in re.finditer(price_pattern, content, re.IGNORECASE):
            facts.append(f"{match.group(1)} price: {match.group(2)}")
            
        # Agent patterns
        agent_pattern = r'(AI agents?|agents?)\s+(?:are|is|will|can)\s+([^.]+)'
        for match in re.finditer(agent_pattern, content, re.IGNORECASE):
            facts.append(f"AI agents: {match.group(2).strip()}")
            
        return facts[:5]  # Limit to 5 facts per message
        
    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Hybrid search combining vector similarity and keyword overlap"""
        # Get more results initially
        results = []
        
        # Search each collection
        for collection, weight in [
            (self.episodic_collection, 0.4),
            (self.synopsis_collection, 0.3),
            (self.semantic_collection, 0.3)
        ]:
            try:
                collection_count = collection.count()
                if collection_count == 0:
                    continue  # Skip empty collections
                    
                # Request fewer results to avoid warnings
                n_results = min(collection_count, 10, max(1, top_k))
                
                res = collection.query(
                    query_texts=[query],
                    n_results=n_results
                )
                
                if res['documents'] and res['documents'][0]:
                    for i, doc in enumerate(res['documents'][0]):
                        # Calculate keyword overlap score
                        query_words = set(query.lower().split())
                        doc_words = set(doc.lower().split())
                        keyword_score = len(query_words & doc_words) / max(len(query_words), 1)
                        
                        # Get vector similarity (distance → similarity)
                        vector_score = 1.0 - (res['distances'][0][i] / 2.0)  # Normalize
                        
                        # Hybrid score
                        hybrid_score = (0.7 * vector_score) + (0.3 * keyword_score)
                        
                        results.append({
                            'content': doc,
                            'metadata': res['metadatas'][0][i] if res['metadatas'] else {},
                            'hybrid_score': hybrid_score * weight,
                            'vector_score': vector_score,
                            'keyword_score': keyword_score,
                            'source': collection.name
                        })
            except Exception as e:
                logger.error(f"Search error in {collection.name}: {e}")
                
        # Sort by hybrid score
        results.sort(key=lambda x: x['hybrid_score'], reverse=True)
        
        return results[:top_k]
        
    async def consolidate_memories(self):
        """Nightly consolidation job - promote important scratchpad to long-term"""
        logger.info(f"Starting memory consolidation for {self.agent_name}")
        
        # Get all scratchpad entries
        scratchpad_entries = await self.get_scratchpad(100)
        
        # Group by conversation or topic
        conversations = {}
        for entry in scratchpad_entries:
            conv_id = entry.get('metadata', {}).get('conversation_id', 'unknown')
            if conv_id not in conversations:
                conversations[conv_id] = []
            conversations[conv_id].append(entry)
            
        # Create synopsis for each conversation
        for conv_id, entries in conversations.items():
            if len(entries) >= 5:  # Only summarize substantial conversations
                messages = [
                    {'agent': e['agent'], 'content': e['content']}
                    for e in entries
                ]
                await self.create_synopsis(conv_id, messages)
                
        # Extract semantic knowledge from important messages
        for entry in scratchpad_entries:
            if self._is_important(entry):
                await self.extract_semantic_knowledge(
                    entry['content'],
                    entry.get('metadata', {}).get('context', '')
                )
                
        logger.info(f"Consolidation complete for {self.agent_name}")
        
    def _is_important(self, entry: Dict[str, Any]) -> bool:
        """Determine if a memory is important enough to extract knowledge from"""
        content = entry.get('content', '').lower()
        
        # Check for important indicators
        important_keywords = [
            'discovered', 'realized', 'important', 'breakthrough',
            'pattern', 'trend', 'launch', 'new', 'first'
        ]
        
        return any(keyword in content for keyword in important_keywords)