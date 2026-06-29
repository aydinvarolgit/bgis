# BGIS — Belief Graph Intelligence System

Sources update an evolving **belief graph**; content is generated from that worldview,
**not** from any single source document. That decoupling is the core idea (vs RAG/summarization).

**Status: MVP + Part B + Part B-2 + Gates F/G** — any source ref → LinkedIn post, all 15 modules,
**107 tests pass**. Part B added *within-run multi-source convergence* (real Modules 8 gap, 9
GitHub-native sibling retrieval, 11 corroboration). Part B-2 added opinionated, typed sources behind
a `SourcePlugin` seam: **GitHub, HN, arXiv, GitHub Discussions/Issues, RSS, and bare web articles**
(claims typed fact/opinion/finding; opinions become belief *stances*). Gate F made the belief delta
richer — confidence moves on cross-source-**TYPE** agreement (recency + source-diversity + per-TYPE
authority). Gate G added the web-article plugin (`trafilatura` extraction).

```
source ref → Ingest → Parse → Claims/Signals → Concepts(dedup) → Belief Retrieval
→ Gap → Retrieval(GitHub siblings + opt-in backends: corpus/wiki/S2/crossref/plugins) → Evidence → Belief Delta → Global Belief Update
→ Narrative → LinkedIn post

ref = GitHub URL | hn:<q> | arxiv:<q> | ghd:owner/repo | rss:<url>|rss:all | url:<article>|http(s)://…
```

## Quick start
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env          # add GITHUB_TOKEN
ollama pull gemma4:latest && ollama pull nomic-embed-text
bgis smoke                    # verify deps
bgis run https://github.com/juliusbrussee/caveman   # or: bgis run "hn:agent memory" | "url:https://blog/post"
bgis seed seeds.txt           # cold-start: bulk-ingest a manifest of refs (no post); beliefs marked origin="seed"
bgis graph                    # read the belief graph: consensus, trends, momentum, pillars
bgis rebuild                  # repersist the graph through current belief math (after a formula change)
```

LLM backends + embedding model are set in `llm_config.json` (project root): an ordered
`backends` list (first = default `gemma4:31b-cloud` cloud, then local `gemma4:latest` failover)
plus a separate `embedding` block kept on local `nomic-embed-text`.

## Docs
- **`docs/HANDOFF.md`** — run it, reset it, known gotchas, next steps. Start here to continue work.
- **`docs/ARCHITECTURE.md`** — pipeline, every module contract, formulas, design decisions.
- **`CLAUDE.md`** — quick status + setup.
- **`docs/PLAN_PART_B2_SOURCES.md`** — next roadmap: opinionated multi-source ingestion.
- Contracts: `src/bgis/models.py`. Plan/vision: `~/.claude/plans/i-want-a-good-swirling-nebula.md`.

## Stack
Plain venv + pip · Ollama (LLM, multi-backend failover via `llm_config.json`) + `nomic-embed-text` (embeddings) ·
ChromaDB (vectors) · JSON files (beliefs/claims/...) · PyGithub · Typer · Pydantic.
Swappable to Neo4j + Qdrant later behind existing interfaces.
