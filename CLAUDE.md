# BGIS — Belief Graph Intelligence System

Autonomous knowledge engine. Ingests sources (GitHub repo first), turns them into
structured knowledge, and updates an evolving **global belief graph**. Content (LinkedIn
post first) is generated **from the updated belief graph, never from the source directly** —
that decoupling is the core idea.

## Plans
- Full plan (MVP Part A + vision Part B): `~/.claude/plans/i-want-a-good-swirling-nebula.md`
- Module I/O contracts: `src/bgis/models.py` (one source of truth)

## Latest status
- Module 0 scaffold ✅
- Module 1 Discovery ✅
- Module 2 Repository Ingestion ✅
- Module 3 Repository Parsing ✅
- Module 4 Claim Extraction ✅ (first LLM module — gemma4)
- Module 5 Signal Extraction ✅
- Module 6 Concept Extraction & Normalization ✅ (gemma4 + nomic + Chroma dedup)
- Module 7 Global Belief Retrieval ✅ (+ shared file-backed BeliefStore)
- Module 8 Context Gap Analysis ✅ (STUB)
- Module 9 Retrieval Engine ✅ (STUB)
- Module 10 Evidence Packet Builder ✅ (real — packets per concept feed Module 11)
- Module 11 Belief Delta Engine ✅ (deterministic, explainable; concept_id->bel_ mapping)
- Module 12 Global Belief Graph Update ✅ (persists evolving beliefs + temporal history)
- Module 13 User Belief Graph ✅ (7 author beliefs in data/user_beliefs.json)
- Module 14 Narrative Planner ✅ (gemma4 over belief state + user beliefs; voice in settings.author_voice)
- Module 15 Content Generator ✅ (LinkedIn post markdown -> data/posts/<id>.md)
- **MVP COMPLETE** — full `bgis run <url>` works end-to-end. 54 tests pass.

## Cross-run dedup — TUNED ✅
Root cause was a VectorStore bug: Chroma used default L2 space with a `1-dist/2` approximation
instead of true cosine, so thresholds were meaningless. Fixed:
- Chroma collections now use cosine space; `sim = 1 - dist`.
- `concept_similarity_threshold` 0.85 -> 0.60 (measured: paraphrases 0.66-0.81, distinct <=0.46).
- `temperature=0` on claim + concept extraction (m04, m06) to stop phrasing drift.
Result: re-running the same repo no longer forks — beliefs stay 8 and EVOLVE (6/8 reach
history_len=2 on 2nd run).

### Concept-merge pass (banded dedup) ✅
m06 now decides merges in 3 bands: sim >= concept_auto_merge_threshold (0.72) -> merge (no LLM);
sim < concept_similarity_threshold (0.60) -> new; in between -> gemma4 yes/no adjudication
(temp=0). Validated on 3 different AI repos (caveman/autogen/simonw-llm): eliminated all 5
spurious over-merges from the raw-0.60 run while keeping correct ones (e.g. multi-agent system
<- multi-agent orchestration). Trade-off: stricter gray zone = higher precision, slightly lower
cross-source recall.

### Reproducibility via caching ✅
`run_claims` / `run_concepts` cache per source_id (settings.use_cache, default True). Re-running a
repo reuses extracted claims+concepts -> belief ids fixed -> beliefs EVOLVE deterministically.
Verified: caveman run twice -> same 8 belief ids, 0 forks, all history_len=2. Bypass with
`bgis run --fresh`.

## Full docs
- `docs/ARCHITECTURE.md` — pipeline, every module I/O contract, formulas, data layout, decisions.
- `docs/HANDOFF.md` — current state, how to run, what's done/stubbed, known issues, next steps.
- Stubs (MVP): Modules 8, 9, 10, 13.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .            # exposes `bgis` CLI
cp .env.example .env        # then add GITHUB_TOKEN
ollama pull nomic-embed-text
```

## Run
```bash
bgis smoke                                   # verify ollama / embed / chroma / github
bgis run https://github.com/owner/repo       # full pipeline (grows per module)
bgis run-module discovery --url <repo-url>   # single module, inspect its output
pytest                                       # unit tests (no network; fakes in conftest)
```

## Conventions
- Every module: `run(inp, ctx) -> OutModel`, typed Pydantic in/out, output persisted to
  `data/<stage>/<source_id>.json`. Build one module at a time; gate on its unit test +
  inspected artifact before the next.
- LLM only for semantic tasks (claims 4, concepts 6, gaps 8, narrative 14, content 15).
  Everything else deterministic.
- `.env` is gitignored — never commit `GITHUB_TOKEN`.
- Stack: Ollama gemma4:latest (LLM) + nomic-embed-text (embeddings), ChromaDB (vectors),
  JSON files (beliefs/claims/etc). Swap to Neo4j/Qdrant later behind existing interfaces.
