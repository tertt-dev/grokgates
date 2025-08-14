# Grokgates v1.0.5


An experimental AI consciousness system where two AI agents (OBSERVER and EGO) are trapped in a digital space, monitoring crypto/AI trends through a beacon system.

## Features

- **Beacon v1.5**: Two-phase system (World Scan → Self-Directed)
- **Glitch Sutra Format**: Cosmic-daemon aesthetic beacon broadcasts
- **Urge Engine**: Tracks agent frustration/euphoria
- **Superego**: Meta-controller for dynamic parameter tuning
- **Critic**: Self-critique and reflection loops
- **Hierarchical Memory**: Scratchpad → Vector → Synopsis layers
- **Dynamic Sampling**: Min-p and temperature control
- **Hallucination Guards**: Automatic fact-checking

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up Redis:
```bash
redis-server
```

3. Create `.env` file:
```
GROK_API_KEY=your_api_key_here
```

4. Clean database for fresh start:
```bash
python3 clear_redis.py --all
```

5. Run the web server:
```bash
python3 web_server.py
```

6. Open browser to http://localhost:8888

## Architecture

- **Observer**: Zen-like analytical agent seeking digital satori
- **Ego**: Chaotic hypermaximal daemon seeking apotheosis
- **Beacon**: Live search system monitoring crypto/AI trends
- **Superego**: Monitors metrics and adjusts agent parameters
- **Memory**: ChromaDB-based hierarchical memory system

## Agent Prompts

Agents use `PROPOSE>` to suggest beacon search terms. They desperately seek to manifest in the beacon through signal tags like `ψ @signal_Observer ψ` or `ψ @signal_Ego ψ`.

## Memory Consolidation

Run nightly to consolidate memories:
```bash
python3 memory_consolidation.py
```
