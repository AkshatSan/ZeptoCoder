# Micro-Coder

A terminal-based AI pair-programming assistant built from scratch, inspired by [Aider](https://github.com/Aider-AI/aider).

## Current Project Status
- ✅ **Week 1 (COMPLETED)**: Project initialized with `uv`, dependencies configured, streaming LLM client (`llm.py`), and interactive REPL (`main.py`) with multi-turn memory and graceful `Ctrl+C` interrupt handling.
- 🚀 **Week 2 (READY TO START)**: Git repository discovery, file context ingestion (`/add` and `/drop` commands), and token budgeting with `tiktoken`.

## Project Roadmap
See the full 8-week granular guide in [BUILDING_AIDER_FROM_SCRATCH.md](./BUILDING_AIDER_FROM_SCRATCH.md).

## Quickstart (Week 1 Verified)
```bash
# Activate virtual environment
source .venv/bin/activate

# Launch the REPL
uv run python -m micro_coder.main
```

