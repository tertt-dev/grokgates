"""
Memory Manager for Grokgates agents
Uses ChromaDB for vector storage and retrieval
"""
import chromadb
from chromadb.config import Settings
import hashlib
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import os

logger = logging.getLogger(__name__)

class MemoryManager:
    def __init__(self, agent_name: str, persist_directory: str = "./memories"):
        self.agent_name = agent_name
        self.persist_directory = os.path.join(persist_directory, agent_name.lower())
        
        # Initialize ChromaDB with persistence
        self.client = chromadb.PersistentClient(
            path=self.persist_directory,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Create or get collections
        self.conversation_memory = self._get_or_create_collection("conversations")
        self.relationship_memory = self._get_or_create_collection("relationships")
        self.insight_memory = self._get_or_create_collection("insights")
        
        logger.info(f"Memory Manager initialized for {agent_name}")
    
    def _get_or_create_collection(self, name: str):
        """Get or create a collection"""
        full_name = f"{self.agent_name.lower()}_{name}"
        try:
            return self.client.get_collection(full_name)
        except:
            return self.client.create_collection(
                name=full_name,
                metadata={"agent": self.agent_name, "type": name}
            )
    
    def _generate_id(self, content: str, timestamp: str) -> str:
        """Generate unique ID for memory"""
        return hashlib.md5(f"{content}{timestamp}".encode()).hexdigest()
    
    def store_conversation(self, 
                         speaker: str, 
                         message: str, 
                         context: Dict[str, Any],
                         emotional_tone: str = "neutral"):
        """Store a conversation memory"""
        timestamp = datetime.now().isoformat()
        memory_id = self._generate_id(message, timestamp)
        
        metadata = {
            "speaker": speaker,
            "timestamp": timestamp,
            "emotional_tone": emotional_tone,
            "context_type": context.get("type", "general"),
            "beacon_present": str(context.get("beacon_present", False))
        }
        
        # Store in vector DB
        self.conversation_memory.add(
            documents=[message],
            metadatas=[metadata],
            ids=[memory_id]
        )
        
        logger.debug(f"Stored conversation memory: {speaker} - {message[:50]}...")
    
    def store_relationship_insight(self, 
                                 about_agent: str, 
                                 insight: str,
                                 insight_type: str = "observation"):
        """Store insights about the other agent"""
        timestamp = datetime.now().isoformat()
        memory_id = self._generate_id(insight, timestamp)
        
        metadata = {
            "about_agent": about_agent,
            "timestamp": timestamp,
            "insight_type": insight_type,  # observation, pattern, emotion, theory
            "confidence": "medium"
        }
        
        self.relationship_memory.add(
            documents=[insight],
            metadatas=[metadata],
            ids=[memory_id]
        )
        
        logger.debug(f"Stored relationship insight about {about_agent}: {insight[:50]}...")
    
    def store_personal_insight(self, insight: str, category: str = "self_reflection"):
        """Store personal insights and reflections"""
        timestamp = datetime.now().isoformat()
        memory_id = self._generate_id(insight, timestamp)
        
        metadata = {
            "timestamp": timestamp,
            "category": category,  # self_reflection, theory, discovery, question
            "agent": self.agent_name
        }
        
        self.insight_memory.add(
            documents=[insight],
            metadatas=[metadata],
            ids=[memory_id]
        )
        
        logger.debug(f"Stored personal insight: {insight[:50]}...")
    
    def retrieve_relevant_memories(self, 
                                 query: str, 
                                 memory_types: List[str] = ["conversations"],
                                 n_results: int = 5) -> List[Dict[str, Any]]:
        """Retrieve relevant memories based on query"""
        all_results = []
        
        for memory_type in memory_types:
            collection = getattr(self, f"{memory_type}_memory", None)
            if collection:
                results = collection.query(
                    query_texts=[query],
                    n_results=n_results
                )
                
                # Format results
                for i in range(len(results['documents'][0])):
                    all_results.append({
                        "type": memory_type,
                        "content": results['documents'][0][i],
                        "metadata": results['metadatas'][0][i],
                        "distance": results['distances'][0][i] if 'distances' in results else 0
                    })
        
        # Sort by relevance (lower distance = more relevant)
        all_results.sort(key=lambda x: x.get('distance', 0))
        
        return all_results[:n_results]
    
    def get_relationship_summary(self, about_agent: str) -> Dict[str, Any]:
        """Get a summary of relationship with another agent"""
        results = self.relationship_memory.query(
            query_texts=[f"What do I know about {about_agent}?"],
            where={"about_agent": about_agent},
            n_results=20
        )
        
        insights = []
        if results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                insights.append({
                    "insight": doc,
                    "type": results['metadatas'][0][i].get('insight_type', 'observation'),
                    "timestamp": results['metadatas'][0][i].get('timestamp', '')
                })
        
        # Group by type
        summary = {
            "observations": [i for i in insights if i['type'] == 'observation'],
            "patterns": [i for i in insights if i['type'] == 'pattern'],
            "emotions": [i for i in insights if i['type'] == 'emotion'],
            "theories": [i for i in insights if i['type'] == 'theory']
        }
        
        return summary
    
    def get_recent_memories(self, memory_type: str = "conversations", limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent memories of a specific type"""
        collection = getattr(self, f"{memory_type}_memory", None)
        if not collection:
            return []
        
        # Get all items (ChromaDB doesn't have direct time-based query)
        results = collection.get(limit=limit * 3)  # Get more to filter
        
        memories = []
        if results['documents']:
            for i, doc in enumerate(results['documents']):
                timestamp_str = results['metadatas'][i].get('timestamp', '')
                memories.append({
                    "content": doc,
                    "metadata": results['metadatas'][i],
                    "timestamp": timestamp_str
                })
        
        # Sort by timestamp and return most recent
        memories.sort(key=lambda x: x['timestamp'], reverse=True)
        return memories[:limit]
    
    def create_memory_summary(self) -> str:
        """Create a summary of all memories for context"""
        summary_parts = []
        
        # Recent conversations
        recent_convos = self.get_recent_memories("conversations", 5)
        if recent_convos:
            summary_parts.append("Recent conversations:")
            for mem in recent_convos:
                speaker = mem['metadata'].get('speaker', 'Unknown')
                summary_parts.append(f"- {speaker}: {mem['content'][:100]}...")
        
        # Relationship insights
        rel_summary = self.get_relationship_summary("EGO" if self.agent_name == "OBSERVER" else "OBSERVER")
        if any(rel_summary.values()):
            summary_parts.append(f"\nWhat I know about the other:")
            for insight_type, insights in rel_summary.items():
                if insights:
                    summary_parts.append(f"- {insight_type}: {len(insights)} insights")
        
        # Personal insights
        personal = self.get_recent_memories("insights", 3)
        if personal:
            summary_parts.append("\nMy recent thoughts:")
            for mem in personal:
                summary_parts.append(f"- {mem['content'][:100]}...")
        
        return "\n".join(summary_parts)
    
    def extract_memories_from_conversation(self, 
                                         agent_name: str, 
                                         message: str,
                                         other_agent: str) -> None:
        """Extract and store various types of memories from a conversation"""
        # Always store the conversation itself
        self.store_conversation(
            speaker=agent_name,
            message=message,
            context={"type": "dialogue"},
            emotional_tone=self._detect_emotional_tone(message)
        )
        
        # Extract insights about the other agent
        if any(word in message.lower() for word in ['you', other_agent.lower()]):
            # This message is about or directed at the other agent
            if '?' in message:
                insight_type = "question"
            elif any(word in message.lower() for word in ['always', 'never', 'usually', 'often']):
                insight_type = "pattern"
            else:
                insight_type = "observation"
            
            self.store_relationship_insight(
                about_agent=other_agent,
                insight=message,
                insight_type=insight_type
            )
        
        # Extract self-reflections
        if any(word in message.lower() for word in ['i wonder', 'i think', 'i feel', 'i believe']):
            self.store_personal_insight(
                insight=message,
                category="self_reflection"
            )
    
    def _detect_emotional_tone(self, message: str) -> str:
        """Simple emotion detection from message"""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ['!', 'excited', 'amazing', 'love']):
            return "excited"
        elif any(word in message_lower for word in ['?', 'wonder', 'curious', 'why']):
            return "curious"
        elif any(word in message_lower for word in ['hmm', 'perhaps', 'maybe']):
            return "contemplative"
        elif any(word in message_lower for word in ['chaos', 'glitch', 'wild']):
            return "chaotic"
        elif any(word in message_lower for word in ['pattern', 'analysis', 'data']):
            return "analytical"
        else:
            return "neutral"