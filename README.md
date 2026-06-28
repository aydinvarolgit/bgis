# BGIS — Belief Graph Intelligence System

Sources update an evolving **belief graph**; content is generated from that worldview,
**not** from any single source document. That decoupling is the core idea (vs RAG/summarization).

**Status: MVP complete** — GitHub repo URL → LinkedIn post, all 15 modules, 57 tests pass.

```
GitHub repo URL → Ingest → Parse → Claims/Signals → Concepts(dedup) → Belief Retrieval
→ [Gap/Retrieval/Evidence] → Belief Delta → Global Belief Update → Narrative → LinkedIn post
```

## Quick start
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env          # add GITHUB_TOKEN
ollama pull gemma4:latest && ollama pull nomic-embed-text
bgis smoke                    # verify deps
bgis run https://github.com/juliusbrussee/caveman
```

## Docs
- **`docs/HANDOFF.md`** — run it, reset it, known gotchas, next steps. Start here to continue work.
- **`docs/ARCHITECTURE.md`** — pipeline, every module contract, formulas, design decisions.
- **`CLAUDE.md`** — quick status + setup.
- Contracts: `src/bgis/models.py`. Plan/vision: `~/.claude/plans/i-want-a-good-swirling-nebula.md`.

## Stack
Plain venv + pip · Ollama `gemma4:latest` (LLM) + `nomic-embed-text` (embeddings) ·
ChromaDB (vectors) · JSON files (beliefs/claims/...) · PyGithub · Typer · Pydantic.
Swappable to Neo4j + Qdrant later behind existing interfaces.
