"""
Dynamic Sampling Configuration
Implements Min-p sampling and other advanced decoding strategies
"""
import logging
from typing import Dict, Any, Optional
from redis_manager import RedisManager
import config

logger = logging.getLogger(__name__)

class DynamicSampling:
    """
    Manages dynamic sampling parameters for agents
    Min-p sampling has been shown to outperform temperature at high creativity settings
    """
    
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        
        # Base configurations - Grok-4 compatible
        self.base_configs = {
            'observer': {
                'temperature': 0.75,
                'min_p': 0.05,
                'top_p': 0.95
            },
            'ego': {
                'temperature': 0.95,
                'min_p': 0.05,
                'top_p': 0.9
            },
            'planner': {
                'temperature': 0.3,
                'min_p': 0.1,
                'top_p': 1.0
            }
        }
        
    def get_decoder_config(self, agent_name: str) -> Dict[str, Any]:
        """Get current decoder configuration for an agent"""
        agent_key = agent_name.lower()
        
        # Start with base config
        config = self.base_configs.get(agent_key, self.base_configs['observer']).copy()
        
        # Check for Redis overrides
        temp_override = self.redis.client.get(f"{agent_key}_temperature")
        if temp_override:
            config['temperature'] = float(temp_override)
            
        min_p_override = self.redis.client.get(f"{agent_key}_min_p")
        if min_p_override:
            config['min_p'] = float(min_p_override)
        
        top_p_override = self.redis.client.get(f"{agent_key}_top_p")
        if top_p_override:
            try:
                tp = float(top_p_override)
                # Clamp to sensible range
                config['top_p'] = max(0.1, min(1.0, tp))
            except Exception:
                pass
            
        # Adjust min_p based on temperature
        # Higher temperature → lower min_p for more diversity
        if config['temperature'] > 0.8:
            config['min_p'] = max(0.02, config['min_p'] - 0.02)
        elif config['temperature'] < 0.5:
            config['min_p'] = min(0.15, config['min_p'] + 0.05)
            
        # Add experimental parameters if supported
        config['experimental'] = {
            'mirostat_mode': 2 if agent_key == 'ego' else 0,
            'mirostat_tau': 5.0,
            'mirostat_eta': 0.1,
            'typical_p': 0.95
        }
        
        logger.debug(f"Decoder config for {agent_name}: temp={config['temperature']}, min_p={config['min_p']}")
        
        return config
        
    def update_sampling_params(self, agent_name: str, updates: Dict[str, Any]):
        """Update sampling parameters for an agent"""
        agent_key = agent_name.lower()
        
        for param, value in updates.items():
            if param in ['temperature', 'min_p', 'top_p']:
                self.redis.client.set(f"{agent_key}_{param}", value)
                logger.info(f"Updated {agent_name} {param} to {value}")
                
    def get_creativity_profile(self, agent_name: str) -> str:
        """Get a creativity profile description based on temperature + min_p"""
        config = self.get_decoder_config(agent_name)
        
        temp = config['temperature']
        min_p = config['min_p']
        
        # Enhanced creativity profiling for Grok-4
        if temp > 0.85:
            if min_p < 0.05:
                return "CHAOTIC_CREATIVE"  # High temp, low min_p = maximum chaos
            else:
                return "CONTROLLED_CREATIVE"  # High temp with higher min_p
        elif temp > 0.6:
            return "BALANCED"  # Medium creativity
        else:
            return "ANALYTICAL"  # Low temp = deterministic
            
    def apply_superego_patch(self, patch: Dict[str, Any]):
        """Apply a patch from the Superego meta-controller"""
        for key, value in patch.items():
            if key.endswith('_temperature'):
                agent = key.replace('_temperature', '')
                self.update_sampling_params(agent, {'temperature': value})
            elif key.endswith('_min_p'):
                agent = key.replace('_min_p', '')
                self.update_sampling_params(agent, {'min_p': value})
            elif key.endswith('_top_p'):
                agent = key.replace('_top_p', '')
                self.update_sampling_params(agent, {'top_p': value})
                
    def get_llm_config(self, agent_name: str) -> Dict[str, Any]:
        """Get complete LLM configuration including model and sampling"""
        decoder_config = self.get_decoder_config(agent_name)
        
        # Build config for Grok API
        llm_config = {
            "model": config.GROK_MODEL if config.USE_GROK_4 else config.GROK_MODEL_FALLBACK,
            "temperature": decoder_config['temperature'],
            "top_p": decoder_config['top_p']
        }
        
        # min_p is used for local creativity control but not sent to API
        # Grok-4 uses temperature + top_p only
        
        # Log creativity profile for monitoring
        profile = self.get_creativity_profile(agent_name)
        logger.debug(f"{agent_name} creativity: {profile} (temp={decoder_config['temperature']}, min_p={decoder_config['min_p']})")
        
        return llm_config