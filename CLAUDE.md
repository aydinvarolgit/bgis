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
- Module 8 Context Gap Analysis ✅ (REAL — gemma4 emits concept-tagged Gap{concept_id,question,kind})
- Module 9 Retrieval Engine ✅ (REAL — GitHub-native: sibling repos via topic search + README links)
- Module 10 Evidence Packet Builder ✅ (real — routes external evidence to its concept by concept_id)
- Module 11 Belief Delta Engine ✅ (deterministic, explainable; concept_id->bel_ mapping; bounded external corroboration)
- Module 12 Global Belief Graph Update ✅ (persists evolving beliefs + temporal history)
- Module 13 User Belief Graph ✅ (7 author beliefs in data/user_beliefs.json)
- Module 14 Narrative Planner ✅ (gemma4 over belief state + user beliefs; voice in settings.author_voice)
- Module 15 Content Generator ✅ (LinkedIn post markdown -> data/posts/<id>.md)
- **MVP COMPLETE + Part B in progress** — full `bgis run <url>` end-to-end. 68 tests pass.

## Part B — within-run multi-source convergence ✅ (Modules 8/9/11 real)
The gap→retrieval→corroboration chain so a single run can pull in related external evidence:
- **m08 gap**: gemma4 (temp=0) over each claim-backed concept + related beliefs -> `Gap{concept_id,
  question, kind}`, kinds = competitor/adoption/research/alternative/risk/validation; ≤6 concepts ×≤2 Q.
- **m09 retrieval (GitHub-native, no new deps)**: finds sibling repos via distinctive-topic search
  (`search_repositories`) + README outbound repo links; embeds a rich concept rep (name + aliases +
  claim texts) and routes each candidate to its best concept. `retrieval_match_threshold=0.62`
  (measured: true siblings ~0.68-0.71, off-topic <=0.60); `retrieval_max_candidates=6`.
- **m10**: routes each external item to its concept packet by `concept_id` (was a dump-all bug).
- **m11**: `base = mean_conf*(0.5+0.5*authority)*base_confidence_ceiling(0.85)`; then
  `evidence_strength = clamp(base + min(external_corroboration_cap=0.15, 0.05*n_external))`.
  Claims alone cap a belief at 0.85; the reserved 0.15 headroom is filled by independent external
  corroboration. Validated: n_ext 0→0.85, 1→0.90, 7→1.00. (Fixed the earlier saturation limit
  where corroboration was absorbed by the clamp.) Fully explainable in rationale.
- **Junk-concept filter (m06)**: drops contentless concepts (every token generic, e.g. `llm-framework`)
  via `_is_generic` + `filter_generic_concepts` (default True) — kills github-topic-tag over-merges.
- **Post quality**: `author_voice`="disciplined visionary"; m14+m15 prompts ban cliches and force
  naming real projects/numbers; m14 surfaces "N independent sources" per belief.
- **Repo-centric posts**: m14 input (`BeliefGraphUpdate.beliefs`) is only the beliefs THIS run
  touched. m14 ranks `created_belief_ids` first (they carry the just-ingested repo's own statements,
  vs `updated` beliefs that may keep a prior source's statement) and the prompt centers the post on
  them — so the post is recognizably about the provided repo, with reinforced beliefs as corroboration.
- Validated: 8-repo rebuild -> 52 beliefs, 7 cross-run convergence, 21 externally-corroborated deltas.

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
- Remaining stub: Module 13 (user beliefs seeded from a static file, not a live questionnaire).

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
