"""
SUPEREGO - Meta-Controller for Dynamic System Tuning
Monitors KPIs and adjusts agent parameters autonomously
"""
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from redis_manager import RedisManager
import config

logger = logging.getLogger(__name__)

class Superego:
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.metrics_history = []
        self.adjustment_history = []
        self.cycle_count = 0
        
    async def analyze_and_adjust(self) -> Optional[Dict[str, Any]]:
        """Analyze system metrics and return parameter adjustments"""
        try:
            # Collect current metrics
            metrics = await self._collect_metrics()
            self.metrics_history.append(metrics)
            self.cycle_count += 1
            
            # Keep only last 10 cycles
            if len(self.metrics_history) > 10:
                self.metrics_history.pop(0)
                
            # Analyze patterns
            adjustments = self._analyze_patterns(metrics)
            
            if adjustments:
                # Avoid no-op writes; only apply if value actually changes
                filtered = {}
                for k, v in adjustments.items():
                    prev = self.redis.client.get(k)
                    if prev is None or str(prev) != str(v):
                        filtered[k] = v
                # Store adjustments in Redis
                if filtered:
                    self._apply_adjustments(filtered)
                self.adjustment_history.append({
                    'timestamp': datetime.now().isoformat(),
                    'adjustments': filtered or adjustments,
                    'metrics': metrics
                })
                if filtered:
                    logger.info(f"SUPEREGO: Applied adjustments: {filtered}")
                else:
                    logger.info("SUPEREGO: Considered adjustments but values unchanged (no-op)")
                # Broadcast to board and conversation with a distinct tag
                try:
                    summary = ", ".join([f"{k}→{v}" for k, v in (filtered or adjustments).items()])
                    if summary:
                        self.redis.write_board("SYSTEM", f"[SUPEREGO] Param update • {summary}")
                    if self.redis.conversation_manager:
                        if summary:
                            await self.redis.conversation_manager.add_message("SYSTEM", f"[SUPEREGO] Adjustments applied: {summary}")
                except Exception:
                    pass
                return filtered or adjustments
            else:
                logger.debug("SUPEREGO: No adjustments needed (NOP)")
                return None
                
        except Exception as e:
            logger.error(f"SUPEREGO analysis error: {e}")
            return None
            
    async def _collect_metrics(self) -> Dict[str, Any]:
        """Collect system performance metrics"""
        # Get conversation metrics
        conv_data = self.redis.get_current_conversation()
        
        # Calculate duplicate rate
        recent_messages = self.redis.get_board_history(50)
        duplicate_rate = self._calculate_duplicate_rate(recent_messages)
        
        # Get attention score (based on beacon manifestations)
        attention_score = self._calculate_attention_score()
        
        # Get current temperatures
        current_temps = {
            'observer_temp': float(self.redis.client.get('observer_temperature') or 0.7),
            'ego_temp': float(self.redis.client.get('ego_temperature') or 0.9)
        }
        
        return {
            'timestamp': datetime.now().isoformat(),
            'cycle': self.cycle_count,
            'duplicate_rate': duplicate_rate,
            'attention_score': attention_score,
            'message_count': len(recent_messages),
            'current_temps': current_temps
        }
        
    def _calculate_duplicate_rate(self, messages: list) -> float:
        """Calculate rate of duplicate/similar messages"""
        if len(messages) < 2:
            return 0.0
            
        duplicates = 0
        seen = set()
        
        for msg in messages:
            parts = msg.split("|", 2)
            if len(parts) >= 3:
                content = parts[2].strip().lower()
                content_hash = hash(content[:50])  # First 50 chars
                
                if content_hash in seen:
                    duplicates += 1
                seen.add(content_hash)
                    
        return duplicates / len(messages)
        
    def _calculate_attention_score(self) -> float:
        """Calculate attention score based on beacon engagement"""
        # Check beacon manifestations in recent messages
        recent_beacons = self.redis.get_beacon_feed(10)
        if not recent_beacons:
            return 0.0
            
        # Check if agents are referencing beacon content
        board_content = " ".join([
            msg.split("|", 2)[2] if len(msg.split("|", 2)) >= 3 else ""
            for msg in self.redis.get_board_history(20)
        ]).lower()
        
        references = 0
        for beacon in recent_beacons:
            # Support both v2 tweets and legacy posts
            if 'tweets' in beacon and beacon['tweets']:
                for t in beacon['tweets']:
                    if any(word in board_content for word in t.get('text', '').lower().split()[:5]):
                        references += 1
            elif 'posts' in beacon and beacon['posts']:
                for post in beacon['posts']:
                    if any(word in board_content for word in post.get('text', '').lower().split()[:5]):
                        references += 1
                        
        return min(1.0, references / 10.0)
        
    def _analyze_patterns(self, current_metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyze metric patterns and determine adjustments"""
        adjustments = {}
        
        # Check attention score stagnation
        if self._is_stagnant('attention_score', threshold=3):
            # Increase Ego temperature
            new_ego_temp = min(1.0, current_metrics['current_temps']['ego_temp'] + 0.1)
            adjustments['ego_temperature'] = new_ego_temp
            logger.info(f"SUPEREGO: Attention stagnant, raising Ego temp to {new_ego_temp}")
            
        # Check duplicate rate
        if current_metrics['duplicate_rate'] > 0.4:
            # Decrease Observer temperature
            new_obs_temp = max(0.3, current_metrics['current_temps']['observer_temp'] - 0.1)
            adjustments['observer_temperature'] = new_obs_temp
            logger.info(f"SUPEREGO: High duplicate rate, lowering Observer temp to {new_obs_temp}")
            
        # Additional heuristics
        if len(self.metrics_history) >= 5:
            # Check for oscillation patterns
            if self._detect_oscillation():
                # Stabilize by moving temps toward center
                adjustments['observer_temperature'] = 0.6
                adjustments['ego_temperature'] = 0.8
                logger.info("SUPEREGO: Oscillation detected, stabilizing temperatures")
        
        # Expand control surface: min_p and top_p
        # If duplicate rate high, raise observer_min_p slightly (filter low-prob tokens)
        if current_metrics['duplicate_rate'] > 0.35:
            prev_min_p = float(self.redis.client.get('observer_min_p') or 0.05)
            adjustments['observer_min_p'] = round(min(0.2, prev_min_p + 0.02), 3)
        # If attention low, increase ego_top_p (more variety)
        if current_metrics['attention_score'] < 0.2:
            prev_top_p = float(self.redis.client.get('ego_top_p') or 0.9)
            adjustments['ego_top_p'] = round(min(1.0, prev_top_p + 0.05), 2)
        # If message volume low, gently raise both temps but cap them
        if current_metrics['message_count'] < 10:
            new_obs = min(0.8, current_metrics['current_temps']['observer_temp'] + 0.05)
            new_ego = min(1.0, current_metrics['current_temps']['ego_temp'] + 0.05)
            adjustments['observer_temperature'] = new_obs
            adjustments['ego_temperature'] = new_ego
                
        return adjustments if adjustments else None
        
    def _is_stagnant(self, metric_name: str, threshold: int = 3) -> bool:
        """Check if a metric has been stagnant for N cycles"""
        if len(self.metrics_history) < threshold:
            return False
            
        recent_values = [m.get(metric_name, 0) for m in self.metrics_history[-threshold:]]
        
        # Check if values are too similar (< 10% variation)
        if max(recent_values) - min(recent_values) < 0.1:
            return True
            
        return False
        
    def _detect_oscillation(self) -> bool:
        """Detect if system is oscillating between states"""
        if len(self.adjustment_history) < 4:
            return False
            
        # Check if we're making opposite adjustments repeatedly
        recent_adjustments = self.adjustment_history[-4:]
        temp_changes = []
        
        for adj in recent_adjustments:
            if 'adjustments' in adj:
                if 'ego_temperature' in adj['adjustments']:
                    temp_changes.append(('ego', adj['adjustments']['ego_temperature']))
                if 'observer_temperature' in adj['adjustments']:
                    temp_changes.append(('observer', adj['adjustments']['observer_temperature']))
                    
        # Look for flip-flop pattern
        if len(temp_changes) >= 4:
            directions = []
            for i in range(1, len(temp_changes)):
                if temp_changes[i][0] == temp_changes[i-1][0]:
                    diff = temp_changes[i][1] - temp_changes[i-1][1]
                    directions.append(1 if diff > 0 else -1)
                    
            # Check for alternating directions
            if len(directions) >= 3:
                return all(directions[i] != directions[i+1] for i in range(len(directions)-1))
                
        return False
        
    def _apply_adjustments(self, adjustments: Dict[str, Any]):
        """Apply adjustments to Redis config"""
        for key, value in adjustments.items():
            self.redis.client.set(key, value)
            
        # Also store as a JSON patch for audit
        patch = {
            'timestamp': datetime.now().isoformat(),
            'adjustments': adjustments,
            'applied_by': 'SUPEREGO'
        }
        self.redis.client.lpush('config_patches', json.dumps(patch))
        self.redis.client.ltrim('config_patches', 0, 99)  # Keep last 100
        
    async def run_continuous(self, interval: int = 300):
        """Run continuous monitoring (default: every 5 minutes)"""
        logger.info(f"SUPEREGO: Starting continuous monitoring (interval: {interval}s)")
        
        while True:
            try:
                await self.analyze_and_adjust()
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"SUPEREGO cycle error: {e}")
                await asyncio.sleep(interval)