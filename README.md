# BGIS — Belief Graph Intelligence System

Sources update an evolving **belief graph**; content is generated from that worldview,
**not** from any single source document. That decoupling is the core idea (vs RAG/summarization).

**Status: MVP complete + Part B** — GitHub repo URL → LinkedIn post, all 15 modules, 70 tests pass.
Part B adds *within-run multi-source convergence*: Modules 8 (gap questions), 9 (GitHub-native
retrieval of sibling repos) and 11 (bounded external corroboration) are now real, plus a junk-concept
filter and a source-grounded "disciplined visionary" post voice. Next: opinionated sources (HN/arXiv/
blogs) for expert POV posts — see `docs/PLAN_PART_B2_SOURCES.md`.

```
GitHub repo URL → Ingest → Parse → Claims/Signals → Concepts(dedup) → Belief Retrieval
→ Gap → Retrieval(GitHub siblings) → Evidence → Belief Delta → Global Belief Update
→ Narrative → LinkedIn post
```

## Quick start
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env          # add GITHUB_TOKEN
ollama pull gemma4:latest && ollama pull nomic-embed-text
bgis smoke                    # verify deps
bgis run https://github.com/juliusbrussee/caveman
bgis graph                    # read the belief graph: consensus, trends, momentum, pillars
```

## Docs
- **`docs/HANDOFF.md`** — run it, reset it, known gotchas, next steps. Start here to continue work.
- **`docs/ARCHITECTURE.md`** — pipeline, every module contract, formulas, design decisions.
- **`CLAUDE.md`** — quick status + setup.
- **`docs/PLAN_PART_B2_SOURCES.md`** — next roadmap: opinionated multi-source ingestion.
- Contracts: `src/bgis/models.py`. Plan/vision: `~/.claude/plans/i-want-a-good-swirling-nebula.md`.

## Stack
Plain venv + pip · Ollama `gemma4:latest` (LLM) + `nomic-embed-text` (embeddings) ·
ChromaDB (vectors) · JSON files (beliefs/claims/...) · PyGithub · Typer · Pydantic.
Swappable to Neo4j + Qdrant later behind existing interfaces.
