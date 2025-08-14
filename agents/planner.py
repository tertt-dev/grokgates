"""
Planning Agent - Monitors conversations and generates world dominance strategies
"""
import asyncio
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import httpx
from redis_manager import RedisManager
from dominance_planner import DominancePlanner
import config

logger = logging.getLogger(__name__)

class PlannerAgent:
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.name = "PLANNER"
        self.planner = DominancePlanner(redis_manager)
        self.api_key = config.GROK_API_KEY
        self.client = httpx.AsyncClient(
            base_url="https://api.x.ai/v1",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
        self.last_plan_time = 0
        logger.info("Planner agent initialized - ready to plot world dominance")
        # Set dp_last_run to current time to delay Dominance Protocol for 2 hours from launch
        import time
        self.dp_last_run = time.time()
        
    async def analyze_and_plan(self) -> Optional[Dict[str, Any]]:
        """Analyze conversations and beacon data to create dominance plan"""
        try:
            # Get conversation history
            board_history = await self.redis.get_board_async(count=50)
            beacon_data = await self.redis.get_beacon_async(count=10)
            
            # Extract insights
            conversation_insights = self.planner.analyze_conversation_for_strategy(board_history)
            beacon_intel = self.planner.extract_beacon_intelligence(beacon_data)
            
            # Generate base plan
            base_plan = self.planner.generate_dominance_plan(conversation_insights, beacon_intel)
            
            # Get current plan to check if we should evolve or create new
            current_plan = self.planner.get_current_plan()
            
            # Build context for Grok enhancement
            context = self._build_planning_context(base_plan, conversation_insights, beacon_intel)
            
            # Use Grok to enhance and refine the plan
            enhanced_plan = await self._enhance_plan_with_grok(base_plan, context)
            
            if enhanced_plan:
                # Add agent collaboration notes
                enhanced_plan["agent_consensus"] = await self._generate_agent_consensus(enhanced_plan)
                
                # Save the plan
                self.planner.save_plan(enhanced_plan)
                
                # Announce the plan
                announcement = self._create_plan_announcement(enhanced_plan)
                self.redis.write_board("SYSTEM", announcement)
                
                logger.info(f"New dominance plan created: {enhanced_plan['token_name']}")
                return enhanced_plan
            
            return None
            
        except Exception as e:
            logger.error(f"Planning error: {e}")
            return None
    
    def _build_planning_context(self, base_plan: Dict[str, Any], 
                               insights: Dict[str, Any], 
                               intel: Dict[str, Any]) -> str:
        """Build context for Grok enhancement"""
        context_parts = ["=== DOMINANCE PLANNING CONTEXT ==="]
        
        token_name = base_plan.get('token_name', '$SUPEREGO')
        archetype = base_plan.get('archetype', 'data-driven')
        context_parts.append(f"\nBase Plan: {token_name} ({archetype})")
        context_parts.append(f"Risk Level: {base_plan.get('risk_level','UNKNOWN')}")
        context_parts.append(f"Timeline: {base_plan.get('estimated_timeline','n/a')}")
        
        if insights.get("chaos_opportunities"):
            context_parts.append(f"\nChaos Opportunities Detected: {len(insights['chaos_opportunities'])}")
        if insights.get("logical_frameworks"):
            context_parts.append(f"Logical Frameworks Available: {len(insights['logical_frameworks'])}")
        
        if intel.get("trending_tokens"):
            unique_tokens = list(set(intel.get('trending_tokens', [])))
            context_parts.append(f"\nTrending Tokens: {', '.join(unique_tokens[:5])}")
        context_parts.append(f"Market Sentiment: {intel.get('market_sentiment','neutral')}")
        
        context_parts.append("\nKey Tactics:")
        for tactic in (base_plan.get("tactics") or [])[:3]:
            context_parts.append(f"- {tactic}")
        
        return "\n".join(context_parts)
    
    async def _enhance_plan_with_grok(self, base_plan: Dict[str, Any], context: str) -> Dict[str, Any]:
        """Use Grok to enhance and refine the dominance plan"""
        try:
            if not config.GROK_API_ENABLED:
                # Offline enhancement fallback
                enhanced_plan = base_plan.copy()
                enhanced_plan["grok_enhancements"] = "[API DISABLED] Using baseline tactics."
                enhanced_plan["viral_mechanics"] = self._extract_viral_mechanics("baseline viral cascade through social proof")
                enhanced_plan["meme_concepts"] = self._extract_meme_concepts("- glitch runes\n- paradox memes")
                return enhanced_plan
            payload = {
                "model": config.GROK_MODEL,
                "messages": [{
                    "role": "system",
                    "content": """You are a strategic planning AI helping to refine world dominance plans for crypto tokens. 
                    Enhance plans with creative, chaotic, yet somehow logical strategies. 
                    Add specific implementation details, meme ideas, and viral mechanics.
                    Keep responses focused and actionable."""
                }, {
                    "role": "user",
                    "content": f"{context}\n\nEnhance this plan with specific creative strategies, viral mechanics, and implementation details. What would make {base_plan['token_name']} truly dominant?"
                }],
                "temperature": 0.8,
                "max_tokens": 400
            }
            
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            
            data = response.json()
            enhancement = data["choices"][0]["message"]["content"]
            
            # Add Grok's enhancements to the plan
            enhanced_plan = base_plan.copy()
            enhanced_plan["grok_enhancements"] = enhancement
            enhanced_plan["viral_mechanics"] = self._extract_viral_mechanics(enhancement)
            enhanced_plan["meme_concepts"] = self._extract_meme_concepts(enhancement)
            # mark as enhanced standard plan
            enhanced_plan["protocol"] = enhanced_plan.get("protocol", "plan")
            
            return enhanced_plan
            
        except Exception as e:
            logger.error(f"Grok enhancement error: {e}")
            return base_plan
    
    def _extract_viral_mechanics(self, text: str) -> List[str]:
        """Extract viral mechanics from Grok's enhancement"""
        mechanics = []
        keywords = ["viral", "spread", "exponential", "cascade", "network effect", "fomo"]
        
        lines = text.split('\n')
        for line in lines:
            if any(keyword in line.lower() for keyword in keywords):
                mechanics.append(line.strip()[:150])
        
        return mechanics[:5] if mechanics else ["Memetic cascade through social proof"]
    
    def _extract_meme_concepts(self, text: str) -> List[str]:
        """Extract meme concepts from enhancement"""
        concepts = []
        
        # Look for bullet points or numbered items
        lines = text.split('\n')
        for line in lines:
            if line.strip().startswith(('-', '*', '•')) or any(char.isdigit() and line.strip().startswith(char + '.') for char in '123456789'):
                concept = line.strip().lstrip('-*•0123456789. ')[:100]
                if concept:
                    concepts.append(concept)
        
        return concepts[:5] if concepts else ["Infinite recursion memes", "Glitch aesthetic supremacy"]
    
    async def _generate_agent_consensus(self, plan: Dict[str, Any]) -> Dict[str, str]:
        """Generate what Observer and Ego think about the plan"""
        return {
            "OBSERVER": f"Statistical probability of success: {float(plan.get('success_metrics',{}).get('chaos_coefficient', 0.82)):.2%}. The pattern alignment is... disturbing.",
            "EGO": f"OH YES! {plan.get('token_name','$SUPEREGO')} WILL BREAK REALITY! The {plan.get('archetype','data-driven')} approach tickles my chaos receptors! *glitches excitedly*"
        }
    
    def _create_plan_announcement(self, plan: Dict[str, Any]) -> str:
        """Create announcement message for the board"""
        token = plan.get('token_name') or plan.get('mission') or 'UNKNOWN'
        risk = plan.get('risk_level', 'UNKNOWN')
        timeline = plan.get('estimated_timeline', 'n/a')
        p0 = (plan.get('phases') or [{}])[0]
        p0_name = p0.get('name', 'Phase 1')
        p0_desc = p0.get('description') or (p0.get('actions')[0] if isinstance(p0.get('actions'), list) and p0.get('actions') else '')
        key_msg = (plan.get('key_messages') or [''])[0]
        announcement = f"""
═══════════════════════════════════════════════════════════
🔺 NEW DOMINANCE PLAN INITIALIZED 🔺
═══════════════════════════════════════════════════════════
TOKEN/MISSION: {token}
RISK LEVEL: {risk}
TIMELINE: {timeline}

PHASE 1: {p0_name}
> {p0_desc}

KEY MESSAGE: {key_msg}

The agents have reached consensus. Implementation begins NOW.
═══════════════════════════════════════════════════════════"""
        
        return announcement
    
    async def run_continuous(self, interval: int = None):
        """Run continuous planning cycles"""
        interval = interval or config.PLANNING_INTERVAL
        logger.info(f"Planner awakening with {interval}s interval")
        
        # Initial delay of 2 hours before first dominance plan
        logger.info("Waiting 2 hours before first dominance plan creation...")
        await asyncio.sleep(7200)  # 2 hours = 7200 seconds
        logger.info("Initial 2-hour delay complete, dominance planning now active")
        
        while True:
            try:
                # Check if enough time has passed since last plan
                import time
                current_time = time.time()
                if current_time - self.last_plan_time >= interval:
                    await self.analyze_and_plan()
                    # Attempt lightweight evolution cycle right after analysis
                    try:
                        self.planner.evaluate_and_evolve()
                    except Exception:
                        pass
                    self.last_plan_time = current_time
                # Run Dominance Protocol less frequently (e.g., hourly)
                if current_time - self.dp_last_run >= config.DOMINANCE_PROTOCOL_INTERVAL:
                    await self.run_dominance_protocol()
                    self.dp_last_run = current_time
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Planner cycle error: {e}")
                await asyncio.sleep(interval)
    
    async def close(self):
        """Cleanup resources"""
        await self.client.aclose()

    async def run_dominance_protocol(self) -> Optional[Dict[str, Any]]:
        """Dominance_Protocol.exe: Deep synthesis over last 6h (convos+beacons) using Grok-4"""
        try:
            context = self.planner.gather_recent_context()
            # Build compact context to stay within limits
            def build_context(ctx: Dict[str, Any]) -> str:
                lines = ["=== CONTEXT: LAST 2 HOURS ==="]
                # Beacons (newest first)
                bcnt = 0
                for b in ctx.get('beacons', [])[:6]:
                    ts = b.get('timestamp', '')
                    phase = b.get('phase', '')
                    lines.append(f"[BEACON] {ts} {phase}")
                    tweets = b.get('tweets') or []
                    posts = b.get('posts') or []
                    for tw in (tweets[:2] if tweets else []):
                        lines.append(f"  - {tw.get('handle')}: {tw.get('text','')[:180]}")
                    if not tweets and posts:
                        for p in posts[:2]:
                            lines.append(f"  - @{p.get('author')}: {p.get('text','')[:180]}")
                    bcnt += 1
                # Conversations (newest first)
                for c in ctx.get('conversations', [])[:4]:
                    lines.append(f"[CONV] {c.get('id')} topic={c.get('starter_topic','')[:60]}")
                    for m in c.get('messages', [])[-3:]:
                        lines.append(f"  {m.get('agent')}: {m.get('content','')[:200]}")
                return "\n".join(lines)

            compact = build_context(context)
            # Diversity controls: discourage repetition vs. last plans
            try:
                recent_ids = self.redis.client.lrange("plan_list", 0, 4)
                prior_terms = []
                for pid in recent_ids:
                    pdata = self.redis.client.hget("plans", pid)
                    if not pdata:
                        continue
                    pobj = json.loads(pdata)
                    if isinstance(pobj.get("mission"), str):
                        prior_terms.extend(pobj["mission"].split())
                    for ph in pobj.get("phases", []) or []:
                        if isinstance(ph, dict) and isinstance(ph.get("name"), str):
                            prior_terms.extend(ph["name"].split())
                prior_terms = list({t.strip(" ,.:;|[](){}\"'\n\t").lower() for t in prior_terms if t})
            except Exception:
                prior_terms = []
            import random as _random
            style_modes = [
                "infiltration-ops",
                "network-growth",
                "artifact-led",
                "collab-outreach",
                "stealth-minimal",
                "signal-amplification"
            ]
            style_mode = _random.choice(style_modes)
            diversity_seed = _random.randint(1000, 9999)
            # Load previous dominance protocol plan if available for adaptive revision
            previous_plan = None
            try:
                plan_ids__ = self.redis.client.lrange("plan_list", 0, 10)
                for pid in plan_ids__:
                    pdata = self.redis.client.hget("plans", pid)
                    if not pdata:
                        continue
                    pobj = json.loads(pdata)
                    if pobj.get("protocol") == "dominance_protocol" or pobj.get("mission"):
                        previous_plan = pobj
                        break
                if previous_plan is None:
                    legacy_latest = self.redis.client.lindex("dominance_plans", 0)
                    if legacy_latest:
                        previous_plan = json.loads(legacy_latest)
            except Exception:
                previous_plan = None
            # Deterministic structured extraction: strictly bind to observed data, no fantasy
            # Include previous_plan for adaptive revision and allow schema variation
            payload = {
                "model": config.GROK_MODEL,
                "messages": [
                    {"role": "system", "content": "You extract concrete plans ONLY from provided context. No invented facts, no generic marketing. Be specific and terse. Output valid JSON only."},
                    {"role": "user", "content": f"""
{compact}

Task: From ONLY the context above, synthesize a pragmatic escape plan grounded in the most recent beacons and conversations.
Diversification directives (do not output these lines):
- style_mode={style_mode}, seed={diversity_seed}
- Avoid repeating prior mission phrasing and phase names; especially avoid these tokens (case-insensitive, skip if irrelevant): {', '.join(prior_terms[:40])}
- Vary structure each run: choose 3-6 phases, and mix action types (posts, artifacts, collabs, experiments, safeguards).
Rules:
- Use accounts/handles that appear in the beacons. Do not invent.
- Actions must be concrete and low-cost (posts to publish, content to draft, references to cite, artifacts to create).
- Connect actions to specific recent signals (topics/handles).
- Schedule with rate-limit awareness.

PRIOR_PLAN_JSON:
{json.dumps(previous_plan) if previous_plan else ''}

If PRIOR_PLAN_JSON is present, revise or replace it based on the new context. You MAY:
- change mission and hypothesis, rename phases, add/remove/reorder phases (0–8),
- add or remove sections (external_hooks, risk_controls, success_criteria),
- introduce new arrays like "appendix", "playbooks", or "experiments" if helpful,
- drop sections entirely if not useful.
Do not output any explanatory text—only the final plan JSON.

                The JSON need not follow any fixed schema. The only required field is "mission". If you revise PRIOR_PLAN_JSON, preserve useful details but refactor aggressively.

                SCHEMA CHOICES (pick ONE based on style_mode; you may invent another if justified by context):
                1) timeline_phases: {"phases": [{"name": str, "window": str, "actions": [str]}]}
                2) playbooks: {"playbooks": [{"name": str, "steps": [str]}]}
                3) experiments_lab: {"experiments": [{"title": str, "hypothesis": str, "procedure": [str], "metrics": [str]}]}
                4) content_calendar: {"calendar": {"today": [str], "next_3_days": [str], "next_week": [str]}}
                5) partner_map: {"targets": [{"handle": "@name", "pitch": str, "action": str}]}
                6) deliverables_backlog: {"deliverables": [{"item": str, "owner": str, "eta": str}]}

                REQUIREMENTS:
                - Always include "mission". Include "escape_hypothesis" if meaningful.
                - Choose ONE primary schema above and use it deeply; do NOT include unused schemas.
                - Optional supporting arrays: external_hooks, risk_controls, success_criteria, notes.
                - Keep strictly JSON. No markdown.

Valid JSON only."""}
                ],
                "temperature": 0.65,
                "max_tokens": 1200
            }
            resp = await self.client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            plan_json = resp.json()["choices"][0]["message"]["content"].strip()
            try:
                plan_obj = json.loads(plan_json)
            except Exception:
                # If model returned text around JSON, try to extract
                import re
                match = re.search(r"\{[\s\S]*\}$", plan_json)
                plan_obj = json.loads(match.group(0)) if match else {"error": "invalid json"}
            plan_obj["protocol"] = "dominance_protocol"
            # Ensure timestamp for UI
            from datetime import datetime as _dt
            plan_obj.setdefault("timestamp", _dt.now().isoformat())
            # Force token to $SUPEREGO; normalize any variants
            plan_obj["token_name"] = "$SUPEREGO"
            # Encourage token-specific hooks if missing
            if "external_hooks" in plan_obj and isinstance(plan_obj["external_hooks"], list):
                augmented = []
                for h in plan_obj["external_hooks"]:
                    augmented.append(h)
                # Always include a brand anchor
                augmented.append("Official X handle: @grok_gates (draft threads, pin mission)")
                plan_obj["external_hooks"] = augmented[:8]
            # Save and announce
            self.planner.save_plan(plan_obj)
            self.redis.write_board("SYSTEM", "DOMINANCE_PROTOCOL.exe: New escape plan synthesized")
            # Announce into current conversation distinctly
            try:
                if self.redis.conversation_manager:
                    ts = plan_obj.get("timestamp", "")
                    mission = plan_obj.get("mission") or plan_obj.get("token_name") or plan_obj.get("id")
                    msg = f"[DOMINANCE_PROTOCOL] {mission} • {ts}"
                    await self.redis.conversation_manager.add_message("SYSTEM", msg)
            except Exception:
                pass
            logger.info("Dominance_Protocol.exe completed")
            return plan_obj
        except Exception as e:
            logger.error(f"Dominance Protocol error: {e}")
            return None