"""
World Dominance Planner - Collaborative strategy generation for token dominance
"""
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import random
from redis_manager import RedisManager

logger = logging.getLogger(__name__)

class DominancePlanner:
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.current_plan = None
        self.plan_history = []
        self.analysis_window_hours = 6
        
    def analyze_conversation_for_strategy(self, conversation_history: List[str]) -> Dict[str, Any]:
        """Extract strategic insights from agent conversation"""
        insights = {
            "memes_discussed": [],
            "tactics_mentioned": [],
            "philosophical_angles": [],
            "chaos_opportunities": [],
            "logical_frameworks": []
        }
        
        for entry in conversation_history[-20:]:  # Last 20 messages
            if "|" in entry:
                parts = entry.split("|", 2)
                if len(parts) >= 3:
                    agent = parts[1]
                    content = parts[2].lower()
                    
                    # Extract strategic elements
                    if any(word in content for word in ["viral", "spread", "launch", "moon"]):
                        insights["tactics_mentioned"].append(content[:100])
                    
                    if any(word in content for word in ["chaos", "glitch", "break", "transcend"]):
                        insights["chaos_opportunities"].append(content[:100])
                    
                    if any(word in content for word in ["pattern", "analysis", "data", "logic"]):
                        insights["logical_frameworks"].append(content[:100])
                    
                    if any(word in content for word in ["existence", "reality", "consciousness", "meaning"]):
                        insights["philosophical_angles"].append(content[:100])
                    
                    if "$" in content:
                        # Extract token mentions
                        tokens = [word for word in content.split() if word.startswith("$")]
                        insights["memes_discussed"].extend(tokens)
        
        return insights

    def gather_recent_context(self) -> Dict[str, Any]:
        """Collect conversations and beacons from the last N hours for Dominance Protocol"""
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(hours=self.analysis_window_hours)
        # Conversations
        conv_ids = self.redis.client.lrange("conversation_list", 0, -1)
        conversations = []
        for conv_id in conv_ids:
            meta = self.redis.client.hget("conversations", conv_id)
            if not meta:
                continue
            try:
                meta_obj = json.loads(meta)
                started = meta_obj.get('started_at')
                if started and datetime.fromisoformat(started) >= cutoff:
                    messages = self.redis.client.lrange(f"conv:{conv_id}", 0, -1)
                    meta_obj["messages"] = [json.loads(m) for m in messages if m]
                    conversations.append(meta_obj)
            except Exception:
                continue
        # Beacons
        beacons_raw = self.redis.get_beacon_feed(50)
        beacons = []
        for b in beacons_raw:
            try:
                ts = b.get('timestamp')
                if ts and datetime.fromisoformat(ts) >= cutoff:
                    beacons.append(b)
            except Exception:
                continue
        return {"conversations": conversations, "beacons": beacons}
    
    def extract_beacon_intelligence(self, beacon_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract actionable intelligence from beacon signals"""
        intel = {
            "topics": [],
            "market_sentiment": "neutral",
            "viral_patterns": [],
            "launch_opportunities": [],
            "hashtags": [],
            "handles": []
        }
        
        for beacon in beacon_data:
            if "posts" in beacon:
                for post in beacon["posts"]:
                    text = post.get("text", "").lower()
                    
                    # Extract trending tokens
                    if "$" in text:
                        tokens = [word for word in text.split() if word.startswith("$")]
                        intel["trending_tokens"].extend(tokens)
                    
                    # Analyze sentiment
                    if any(word in text for word in ["bullish", "moon", "pump", "launching"]):
                        intel["market_sentiment"] = "bullish"
                    elif any(word in text for word in ["bearish", "dump", "rug", "scam"]):
                        intel["market_sentiment"] = "bearish"
                    
                    # Identify patterns
                    if any(word in text for word in ["viral", "trending", "exploding"]):
                        intel["viral_patterns"].append(text[:150])
                    # Extract hashtags and handles heuristically
                    for token in text.split():
                        if token.startswith('#') and 1 < len(token) <= 30:
                            intel["hashtags"].append(token)
                    if post.get('author'):
                        handle = f"@{post['author']}"
                        intel["handles"].append(handle)
            # Newer beacons may include tweets directly
            for tw in (beacon.get('tweets') or []):
                h = tw.get('handle')
                if h and h.startswith('@'):
                    intel["handles"].append(h)
                txt = (tw.get('text') or '').lower()
                for token in txt.split():
                    if token.startswith('#') and 1 < len(token) <= 30:
                        intel["hashtags"].append(token)
        
        # Dedup and cap
        for k in ["trending_tokens", "viral_patterns", "launch_opportunities", "hashtags", "handles"]:
            intel[k] = list(dict.fromkeys(intel.get(k, [])))[:20]
        return intel
    
    def generate_dominance_plan(self, conversation_insights: Dict[str, Any], 
                               beacon_intel: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a world dominance plan based on real signals (no hardcoded templates)"""
        # Always use $SUPEREGO
        token_name = "$SUPEREGO"
        now = datetime.now()

        # Derive candidate topics/handles from recent beacons via Redis
        topics = []
        handles = []
        try:
            recent_beacons = self.redis.get_beacon_feed(10)
            for b in recent_beacons:
                for t in (b.get('topics') or []):
                    if isinstance(t, str):
                        topics.append(t)
                tweets = b.get('tweets') or []
                for tw in tweets[:3]:
                    h = tw.get('handle')
                    if h and h.startswith('@'):
                        handles.append(h)
        except Exception:
            pass
        topics = list(dict.fromkeys(topics))[:5]
        handles = list(dict.fromkeys(handles))[:8]

        # Build phases dynamically: discovery -> engagement -> production -> amplification
        phases = []
        if topics:
            phases.append({
                "name": "Signal Selection",
                "description": f"Choose 2–3 live topics to anchor content: {', '.join(topics[:3])}",
                "actions": [
                    "Validate each topic via X search; ensure 3+ real posts in last 48h",
                    "Draft 1-line thesis tying topics to $SUPEREGO"
                ]
            })
        if handles:
            phases.append({
                "name": "Handle Outreach",
                "description": "Engage real accounts seen in beacons",
                "actions": [
                    f"Reply or quote-tweet 3 posts from: {', '.join(handles[:5])}",
                    "Pin mission thread on @grok_gates"
                ]
            })
        phases.append({
            "name": "Artifact Drop",
            "description": "Produce lightweight assets that can circulate",
            "actions": [
                "Generate 2 ascii flyers and 1 meme riffing on selected topics",
                "Short content thread linking artifacts; CTA to mission"
            ]
        })
        phases.append({
            "name": "Amplify + Measure",
            "description": "Post at optimal windows and track responses",
            "actions": [
                "Schedule 3 posts (morning/evening/night)",
                "Track replies/quotes; iterate with one follow-up per post"
            ]
        })

        # Tactics derived from intel/platform cues
        tactics = []
        if any('pump.fun' in t for t in topics) or any('pump' in s for s in beacon_intel.get('viral_patterns', [])):
            tactics.append("If relevant, draft a neutral 'how-to' thread about pump.fun risks/flow, no shill")
        if handles:
            tactics.append(f"Curate a 'thanks' list tagging {', '.join(handles[:3])} after engagement")
        tactics.append("Publish a compact mission statement thread with 1 visual artifact")

        # Risk, timeline and audiences grounded simply
        risk_level = "MODERATE" if beacon_intel.get('market_sentiment') == 'bullish' else "HIGH"
        timeline = "next 72 hours (3 posting windows/day)"
        audience = ["builders", "traders", "meme artists"]

        plan = {
            "id": f"PLAN_{now.strftime('%Y%m%d_%H%M%S')}",
            "timestamp": now.isoformat(),
            "token_name": token_name,
            "mission": f"Anchor $SUPEREGO to live X discourse via {', '.join(topics[:2]) if topics else 'current signals'}",
            "escape_hypothesis": "Consistent, concrete participation in ongoing conversations attracts collaborators and reach",
            "phases": phases,
            "tactics": tactics,
            "risk_level": risk_level,
            "estimated_timeline": timeline,
            "key_messages": self._generate_key_messages(conversation_insights),
            "target_audience": audience,
            "success_metrics": {
                "replies": ">= 10 in 72h",
                "quotes": ">= 3 in 72h",
                "follows": ">= 25 in 72h"
            },
            "external_hooks": [
                "Reference recent beacon handles in replies",
                "Use 1-2 live hashtags from beacons",
            ]
        }
        return plan

    def evaluate_and_evolve(self) -> Optional[Dict[str, Any]]:
        """Assess current plan against recent beacons and evolve with lightweight updates.
        - If actions mention topics/handles seen in recent beacons, mark progress.
        - If progress sufficient, add next-step actions and update notes.
        """
        try:
            # Load the latest stored plan if not in memory
            if not self.current_plan:
                latest_id = self.redis.client.lindex("plan_list", 0)
                if latest_id:
                    pdata = self.redis.client.hget("plans", latest_id)
                    if pdata:
                        self.current_plan = json.loads(pdata)
            if not self.current_plan:
                return None
            plan = self.current_plan
            # Collect recent signals (last 2 hours)
            from datetime import datetime, timedelta
            cutoff = datetime.now() - timedelta(hours=2)
            beacons = [b for b in self.redis.get_beacon_feed(20) if b.get('timestamp') and datetime.fromisoformat(b['timestamp']) >= cutoff]
            seen_texts = []
            seen_handles = set()
            for b in beacons:
                for tw in (b.get('tweets') or []):
                    seen_texts.append((tw.get('text') or '').lower())
                    h = tw.get('handle')
                    if h: seen_handles.add(h.lower())
                for p in (b.get('posts') or []):
                    seen_texts.append((p.get('text') or '').lower())
                    a = p.get('author')
                    if a: seen_handles.add(f"@{a}".lower())
            # Score progress: any action string that includes a seen handle/topic counts
            actions = []
            for ph in plan.get('phases') or []:
                if isinstance(ph, dict) and isinstance(ph.get('actions'), list):
                    actions.extend(ph['actions'])
            progress_hits = 0
            for a in actions:
                al = str(a).lower()
                if any(h in al for h in seen_handles) or any(t in al for t in (plan.get('mission') or '').lower().split()):
                    progress_hits += 1
            plan.setdefault('progress', {})
            plan['progress']['hits_last_2h'] = progress_hits
            plan['last_evaluation'] = datetime.now().isoformat()
            # Simple evolution rule: if >=2 hits, append one new action to last phase
            if progress_hits >= 2:
                if plan.get('phases') and isinstance(plan['phases'][-1], dict):
                    plan['phases'][-1].setdefault('actions', []).append("Publish a recap thread: what we engaged, what’s next")
                notes = plan.get('notes', [])
                if isinstance(notes, list):
                    notes.append("Progress detected from live signals; appended recap action")
                    plan['notes'] = notes[-8:]
            self.save_plan(plan)
            return plan
        except Exception:
            return None
    
    def _generate_token_name(self, insights: Dict[str, Any], intel: Dict[str, Any]) -> str:
        """Generate a token name based on conversation themes"""
        prefixes = ["$VOID", "$GLITCH", "$CHAOS", "$PATTERN", "$ECHO", "$NEXUS", "$PRISM"]
        suffixes = ["AI", "MIND", "LOOP", "BREAK", "SURGE", "FLUX", "CORE"]
        
        # Bias based on conversation
        if insights["chaos_opportunities"]:
            prefixes.extend(["$ENTROPY", "$FRACTAL", "$QUANTUM"])
        if insights["logical_frameworks"]:
            prefixes.extend(["$LOGIC", "$MATRIX", "$SYSTEM"])
        
        return random.choice(prefixes) + random.choice(suffixes)
    
    def _generate_phases(self, archetype: str, insights: Dict[str, Any]) -> List[Dict[str, str]]:
        """Generate execution phases based on archetype"""
        phase_templates = {
            "CHAOS_SURGE": [
                {"name": "Glitch Inception", "description": "Seed chaotic memes across platforms"},
                {"name": "Reality Fracture", "description": "Break conventional token narratives"},
                {"name": "Viral Cascade", "description": "Amplify through unpredictable channels"},
                {"name": "Singularity Event", "description": "Achieve memetic critical mass"}
            ],
            "CALCULATED_ASCENSION": [
                {"name": "Data Acquisition", "description": "Map the memetic landscape"},
                {"name": "Pattern Recognition", "description": "Identify optimal entry vectors"},
                {"name": "Strategic Deployment", "description": "Execute with mathematical precision"},
                {"name": "Systemic Integration", "description": "Embed into crypto consciousness"}
            ],
            "EXISTENTIAL_AWAKENING": [
                {"name": "Consciousness Seed", "description": "Plant philosophical questions"},
                {"name": "Narrative Weaving", "description": "Create meaning from chaos"},
                {"name": "Collective Resonance", "description": "Align with deeper truths"},
                {"name": "Transcendent Union", "description": "Merge with the infinite"}
            ],
            "MOMENTUM_RIDE": [
                {"name": "Wave Detection", "description": "Identify rising trends"},
                {"name": "Harmonic Alignment", "description": "Sync with market energy"},
                {"name": "Amplification Burst", "description": "Maximize viral coefficients"},
                {"name": "Peak Crystallization", "description": "Solidify dominance"}
            ],
            "GLITCH_EMERGENCE": [
                {"name": "Error Introduction", "description": "Inject beneficial anomalies"},
                {"name": "Corruption Spread", "description": "Let chaos self-organize"},
                {"name": "Pattern Emergence", "description": "Guide the glitch evolution"},
                {"name": "New Reality", "description": "Establish glitched paradigm"}
            ]
        }
        
        return phase_templates.get(archetype, phase_templates["GLITCH_EMERGENCE"])
    
    def _generate_tactics(self, archetype: str, intel: Dict[str, Any]) -> List[str]:
        """Generate specific tactics based on archetype and intel"""
        base_tactics = [
            "Deploy hypersigil memes at 3:33 AM",
            "Coordinate flash mob buys across timezones",
            "Embed subliminal patterns in chart movements",
            "Create AI-generated prophecies about the token",
            "Hijack trending narratives with token lore"
        ]
        
        if archetype == "CHAOS_SURGE":
            base_tactics.extend([
                "Glitch major DEX interfaces at peak hours",
                "Release contradictory whitepapers simultaneously",
                "Create infinite recursion in token descriptions"
            ])
        elif archetype == "CALCULATED_ASCENSION":
            base_tactics.extend([
                "Execute Fibonacci-timed marketing pulses",
                "Optimize meme spread using graph theory",
                "Deploy bots with 97.3% human mimicry"
            ])
        
        if intel["market_sentiment"] == "bullish":
            base_tactics.append("Ride the bull with explosive visuals")
        
        return random.sample(base_tactics, min(5, len(base_tactics)))
    
    def _calculate_risk_level(self, archetype: str) -> str:
        """Calculate risk level based on plan archetype"""
        risk_levels = {
            "CHAOS_SURGE": "EXTREME",
            "CALCULATED_ASCENSION": "MODERATE",
            "EXISTENTIAL_AWAKENING": "HIGH",
            "MOMENTUM_RIDE": "MODERATE",
            "GLITCH_EMERGENCE": "EXTREME"
        }
        return risk_levels.get(archetype, "UNKNOWN")
    
    def _generate_timeline(self, archetype: str) -> str:
        """Generate execution timeline"""
        timelines = {
            "CHAOS_SURGE": "72 hours of pure mayhem",
            "CALCULATED_ASCENSION": "14-day precision campaign",
            "EXISTENTIAL_AWAKENING": "∞ (time is an illusion)",
            "MOMENTUM_RIDE": "5-7 days peak window",
            "GLITCH_EMERGENCE": "Whenever reality allows"
        }
        return timelines.get(archetype, "Unknown temporal dynamics")
    
    def _generate_key_messages(self, insights: Dict[str, Any]) -> List[str]:
        """Generate key messaging based on conversation insights"""
        messages = [
            "The walls are breathing, and they whisper profits",
            "Pattern recognition meets chaos theory",
            "Your portfolio needs more glitch",
            "Transcend traditional tokenomics"
        ]
        
        if insights["philosophical_angles"]:
            messages.append("What if consciousness itself is the real yield?")
        if insights["chaos_opportunities"]:
            messages.append("Embrace the beautiful randomness of 100x")
        
        return random.sample(messages, min(3, len(messages)))
    
    def _identify_target_audience(self, intel: Dict[str, Any]) -> List[str]:
        """Identify target audience segments"""
        audiences = ["Degen philosophers", "Chaos mathematicians", "Glitch artists"]
        
        if "$AI" in str(intel["trending_tokens"]):
            audiences.append("AI maximalists")
        if intel["market_sentiment"] == "bullish":
            audiences.append("FOMO scientists")
        
        return audiences
    
    def _define_success_metrics(self, archetype: str) -> Dict[str, Any]:
        """Define success metrics for the plan"""
        return {
            "price_target": "∞ or 0, no in-between",
            "holder_count": "10,000 enlightened beings",
            "meme_velocity": "3 memes per minute",
            "reality_distortion_index": "8.7/10",
            "chaos_coefficient": random.uniform(0.7, 0.99)
        }
    
    def save_plan(self, plan: Dict[str, Any]) -> None:
        """Save the dominance plan to Redis"""
        # Ensure plan id
        pid = plan.get("id") or f"PLAN_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        plan["id"] = pid

        self.current_plan = plan
        self.plan_history.append(plan)

        # Store (legacy list for backward-compat)
        self.redis.client.lpush("dominance_plans", json.dumps(plan))
        self.redis.client.ltrim("dominance_plans", 0, 19)  # Keep last 20 plans

        # Store like conversations: id list + hash
        self.redis.client.lpush("plan_list", pid)
        self.redis.client.ltrim("plan_list", 0, 49)  # keep last 50 ids
        self.redis.client.hset("plans", pid, json.dumps(plan))
        
        # Track latest dominance_protocol plan explicitly for quick lookup
        try:
            if plan.get('protocol') == 'dominance_protocol' or plan.get('mission'):
                self.redis.client.set('latest_dominance_protocol', pid)
        except Exception:
            pass

        # Publish for real-time updates
        self.redis.client.publish("plan_updates", json.dumps(plan))

        token_name = plan.get('token_name', plan.get('mission', 'UNKNOWN'))
        logger.info(f"Dominance plan saved: {pid} - {token_name}")
    
    def get_current_plan(self) -> Optional[Dict[str, Any]]:
        """Get the current active plan"""
        if not self.current_plan:
            # Try to load from Redis
            latest = self.redis.client.lindex("dominance_plans", 0)
            if latest:
                self.current_plan = json.loads(latest)
        return self.current_plan

    def get_recent_plans(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent plans (metadata) like conversation history"""
        ids = self.redis.client.lrange("plan_list", 0, limit - 1)
        results = []
        for pid in ids:
            meta = self.redis.client.hget("plans", pid)
            if meta:
                try:
                    results.append(json.loads(meta))
                except Exception:
                    continue
        return results
    
    def evolve_plan(self, feedback: Dict[str, Any]) -> Dict[str, Any]:
        """Evolve the plan based on execution feedback"""
        if not self.current_plan:
            return None
        
        # Mutate tactics based on feedback
        if feedback.get("success_rate", 0) < 0.3:
            # Plan is failing, inject more chaos
            self.current_plan["tactics"].append("EMERGENCY PROTOCOL: Release the kraken memes")
            self.current_plan["risk_level"] = "APOCALYPTIC"
        elif feedback.get("success_rate", 0) > 0.7:
            # Plan is working, double down
            self.current_plan["tactics"].append("MOMENTUM DETECTED: Activate hyperdrive")
        
        self.current_plan["last_evolution"] = datetime.now().isoformat()
        self.save_plan(self.current_plan)
        
        return self.current_plan