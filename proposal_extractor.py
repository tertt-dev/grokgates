"""
Proposal Extractor for Beacon v1.5
Harvests PROPOSE> tags from agent conversations
"""
import re
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
from collections import Counter
import logging

logger = logging.getLogger(__name__)

class Proposal:
    def __init__(self, text: str, agent: str, timestamp: datetime):
        self.text = text.strip()
        self.agent = agent
        self.timestamp = timestamp
        self.hit = False  # Did it appear in beacon?
        
    def __repr__(self):
        return f"Proposal('{self.text}' by {self.agent} at {self.timestamp})"

class ProposalExtractor:
    def __init__(self, redis_manager):
        self.redis = redis_manager
        self.proposal_pattern = re.compile(r'PROPOSE>\s*(.+?)(?:\n|$)', re.IGNORECASE)
        self.profanity_filter = ['fuck', 'shit', 'damn', 'ass', 'bitch']  # Basic filter
        # Adaptive keyword memory backed by Redis; seeded with a few realistic anchors
        seed_keywords = [
            'pump', 'pump.fun', 'pumpswap', 'airdrop', 'memecoin', 'token', 'launch',
            'solana', 'ethereum', 'bitcoin', '$', '#', 'ai', 'agent', 'grok', 'gpt', 'bonk'
        ]
        try:
            stored = self.redis.client.get('adaptive_signal_keywords')
            if stored:
                seed_keywords = list({*seed_keywords, *stored.split(',')})
        except Exception:
            pass
        self.signal_keywords = seed_keywords
        # Adaptive banlist (for poetic/futuristic fragments) backed by Redis with light seeding
        seed_ban = ['hyperstition', 'eldritch', 'necromancy']
        try:
            stored_ban = self.redis.client.get('adaptive_ban_phrases')
            if stored_ban:
                seed_ban = list({*seed_ban, *stored_ban.split(',')})
        except Exception:
            pass
        self.ban_phrases = seed_ban
        
    def extract_proposals(self, time_window_minutes: int = 30) -> List[Proposal]:
        """Extract proposals from the last N minutes of conversation"""
        proposals = []
        
        # Get recent messages from current conversation
        current_conv = self.redis.get_current_conversation()
        if not current_conv:
            return proposals
            
        cutoff_time = datetime.now() - timedelta(minutes=time_window_minutes)
        
        for msg in current_conv.get('messages', []):
            msg_time = datetime.fromisoformat(msg['timestamp'])
            if msg_time < cutoff_time:
                continue
                
            # Find all PROPOSE> tags in the message
            matches = self.proposal_pattern.findall(msg['content'])
            for match in matches:
                proposal = Proposal(
                    text=match,
                    agent=msg['agent'],
                    timestamp=msg_time
                )
                if self._validate_proposal(proposal):
                    proposals.append(proposal)
                    
        # Rank and deduplicate
        return self._rank_proposals(proposals)
        
    def _validate_proposal(self, proposal: Proposal) -> bool:
        """Filter out invalid or inappropriate proposals"""
        text = proposal.text.lower()
        
        # Check length
        if len(text) < 3 or len(text) > 100:
            return False
            
        # Check profanity
        for word in self.profanity_filter:
            if word in text:
                logger.warning(f"Filtered proposal for profanity: {proposal.text}")
                return False
                
        # Must contain at least one alphanumeric character
        if not re.search(r'\w', text):
            return False
        
        # Reduce nonsense: require reasonable alphanumeric ratio
        alnum = sum(c.isalnum() for c in text)
        if alnum / max(1, len(text)) < 0.5:
            return False
        
        # Require at least one meaningful signal keyword, ticker ($), or hashtag
        if not any(kw in text for kw in self.signal_keywords):
            return False
        # Reject obviously futuristic/poetic prompts that won't yield real posts
        if any(phrase in text for phrase in self.ban_phrases):
            return False
        # Require at least one concrete anchor: ticker, hashtag, or known platform terms
        if not (re.search(r'\$[a-z0-9]{2,10}', text) or re.search(r'#[a-z0-9_]{2,30}', text) or any(p in text for p in ['pump.fun', 'pumpswap'])):
            # If none of the anchors present, enforce presence of proper nouns likely to be on X
            if not any(p in text for p in ['solana','ethereum','bitcoin','grok','gpt','bonk','elon','openai','xai','ai agent','memecoin']):
                return False
        
        # Deduplicate across recent proposals (last 200)
        try:
            recent = self.redis.client.lrange('proposal_history', 0, 199)
            lowered = text.strip().lower()
            for entry in recent:
                if isinstance(entry, str) and lowered in entry.lower():
                    return False
        except Exception:
            pass
            
        return True
        
    def _rank_proposals(self, proposals: List[Proposal], max_proposals: int = 5) -> List[Proposal]:
        """Rank proposals by recency and echo frequency"""
        if not proposals:
            return []
            
        # Count duplicates (case-insensitive)
        text_counts = Counter(p.text.lower() for p in proposals)
        
        # Score by: recency (newer = higher) + echo count
        scored_proposals = []
        seen_texts = set()
        
        for p in sorted(proposals, key=lambda x: x.timestamp, reverse=True):
            text_lower = p.text.lower()
            if text_lower not in seen_texts:
                seen_texts.add(text_lower)
                # Prefer concrete anchors (tickers/hashtags/platform terms)
                anchor_boost = 0
                if re.search(r'\$[a-z0-9]{2,10}', text_lower):
                    anchor_boost += 1.5
                if re.search(r'#[a-z0-9_]{2,30}', text_lower):
                    anchor_boost += 1.0
                if any(p in text_lower for p in ['pump.fun', 'pumpswap', 'solana', 'ethereum', 'bitcoin']):
                    anchor_boost += 0.5
                # Score: echoes + recency + anchor_boost
                recency_score = 1 - (datetime.now() - p.timestamp).seconds / 1800  # 30 min window
                echo_score = text_counts[text_lower]
                total_score = echo_score + recency_score + anchor_boost
                scored_proposals.append((p, total_score))
                
        # Sort by score and return top N
        scored_proposals.sort(key=lambda x: x[1], reverse=True)
        top = [p for p, _ in scored_proposals[:max_proposals]]
        # Feedback: update adaptive dictionaries based on accepted proposals
        try:
            accepted_texts = ' '.join(p.text.lower() for p in top)
            # Extract hashtags and tickers to add as keywords
            new_keys = set()
            new_keys.update(re.findall(r'\$[a-z0-9]{2,10}', accepted_texts))
            new_keys.update(re.findall(r'#[a-z0-9_]{2,30}', accepted_texts))
            if new_keys:
                prev = set(self.signal_keywords)
                merged = prev.union(new_keys)
                self.signal_keywords = list(merged)
                self.redis.client.set('adaptive_signal_keywords', ','.join(sorted(merged)))
            # Extract obviously fantastical words to ban next time (if appear without anchors)
            if not new_keys:
                weird_tokens = [w for w in re.findall(r'[a-z]{6,}', accepted_texts) if w.endswith(('ism','ity','tion'))]
                if weird_tokens:
                    prev_ban = set(self.ban_phrases)
                    merged_ban = prev_ban.union(weird_tokens[:3])
                    self.ban_phrases = list(merged_ban)
                    self.redis.client.set('adaptive_ban_phrases', ','.join(sorted(merged_ban)))
        except Exception:
            pass
        return top
        
    def save_proposal_history(self, proposals: List[Proposal], phase: str):
        """Save proposals to Redis for tracking"""
        for p in proposals:
            entry = {
                'text': p.text,
                'agent': p.agent,
                'timestamp': p.timestamp.isoformat(),
                'phase': phase,
                'hit': p.hit
            }
            self.redis.client.lpush('proposal_history', str(entry))
            # Keep only last 100 proposals
            self.redis.client.ltrim('proposal_history', 0, 99)
            
    def mark_hits(self, proposals: List[Proposal], beacon_content: str):
        """Check which proposals appeared in beacon"""
        beacon_lower = beacon_content.lower()
        
        for p in proposals:
            # Simple substring match for now
            if p.text.lower() in beacon_lower:
                p.hit = True
                logger.info(f"Proposal HIT: '{p.text}' found in beacon!")
                
        return proposals