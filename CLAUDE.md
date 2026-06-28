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
- Module 9 Retrieval Engine ✅ (REAL — GitHub-native sibling repos + opt-in `RetrievalBackend`s:
  source-plugin-reuse / local-corpus / external-APIs (wiki+S2+crossref); any source type, default off)
- Module 10 Evidence Packet Builder ✅ (real — routes external evidence to its concept by concept_id)
- Module 11 Belief Delta Engine ✅ (deterministic, explainable; concept_id->bel_ mapping; bounded external corroboration)
- Module 12 Global Belief Graph Update ✅ (persists evolving beliefs + temporal history)
- Module 13 User Belief Graph ✅ (7 author beliefs in data/user_beliefs.json)
- Module 14 Narrative Planner ✅ (gemma4 over belief state + user beliefs; voice in settings.author_voice)
- Module 15 Content Generator ✅ (LinkedIn post markdown -> data/posts/<id>.md)
- **MVP COMPLETE + Part B + Part B-2 + Gates F/G** — full `bgis run <ref>` end-to-end. 107 tests pass.

## Gate I — source-centered narrative ✅ (107 tests)
Fix for narrative drift: when a source's concepts dedup onto pre-existing higher-confidence beliefs,
m14 used to center the post on those (stale) beliefs' statements, not the ingested source. Now m14
takes the run's `EvidencePackets` and builds two prompt blocks:
- **THIS SOURCE** (lead): this run's own fact/finding claim texts, routed to beliefs by
  `belief_id_for_concept`; created beliefs first. main_belief MUST be grounded here.
- **CORROBORATION** (secondary): pre-existing beliefs (not created this run) the source agreed with,
  shown with independent-source counts — support only, never the subject. Confidence no longer
  promotes a corroboration belief into the lead.
- m14.run signature: `run(update, user, packets, ctx)`; pipeline + cli `run-module narrative` thread
  packets (`load_evidence`). Validated live on the GLM-5.2 article: post now centers on GLM-5.2
  (Pareto frontier, AA-Briefcase, AA-Omniscience), not the previously-dominant Ollama/Agent Framework.

## Gate G — web-article source plugin ✅ (107 tests)
`WebArticleSourcePlugin` (`src/bgis/sources/web.py`): bare article URL → one `article` Document.
- **ref scheme**: `url:<u>` explicit OR bare `http(s)://` (convenience). Registered LAST in
  SOURCE_PLUGINS so `GitHubSourcePlugin` keeps github URLs; kind:-prefixed plugins are disjoint.
- **extract**: `trafilatura.extract` for main content (nav/footer/boilerplate stripped); title via
  `<title>` regex (avoids trafilatura metadata API drift). New dep `trafilatura>=1.8`.
- **injectable `fetch`** (url→html); trafilatura runs offline → tests use canned HTML, no network.
- SourceType += `web`; reuses DocType `article` (m04 already types article→opinion+finding). No repo
  → m09 skipped; authority = Gate F `source_type_authority["web"]=0.5` (no stars).
- Validated live: `bgis run "url:https://simonwillison.net/2024/Dec/31/llms-in-2024/"` → 185-word
  post naming real specifics (Gemini 1.5 Pro 2M ctx, Llama 3.2 3B, M2 MacBook); graph 189→193, 5
  beliefs reference the web source.

## Gate F — richer belief delta ✅ (103 tests)
Completes the Part B-2 thesis: cross-source-TYPE agreement MOVES confidence. m11 evidence_strength's
reserved headroom (1 - ceiling = 0.15) is now a COMPOSITE bonus, summed then capped at headroom:
`corroboration = min(0.15, external + diversity + recency)`.
- **diversity** = `source_diversity_weight(0.05) * (n_distinct_source_TYPES - 1)`. Types = current
  run's type ∪ types of every source_id in the belief's history. So repo-fact + paper-finding +
  discourse agreeing lifts a belief past what one source type could.
- **source-TYPE authority** (m11 `_authority`): repos still use log10(stars); non-repo sources (no
  `stars` signal) use `source_type_authority` baseline — arxiv 0.7 / rss 0.5 / hn,gh_discussions
  0.4 / unknown 0.25 (== old flat fallback, so legacy behavior unchanged).
- **recency** = `recency_weight(0.05) * term(days_since_push)`; full ≤30d, linear→0 at 365d, absent→0
  (neutral, never a penalty — respects ratchet). Only github emits the signal today.
- Source TYPE per source_id derived from `data/raw/<sid>.json` `type` (m11.source_kind helper).
- Existing external corroboration term unchanged → all prior m11 tests pass. Composes with ceiling,
  ratchet, pure-opinion 0.3.
- **Graph rebuild** `bgis rebuild` (pipeline.rebuild_graph): wipe bel_*.json + chronologically
  replay every `*_evidence.json` through current m11+m12 (no re-ingest, no network). Validated live:
  bel_05e54570 (spans github+hn+arxiv) 0.64 declining → 0.92 stable; 0 declining beliefs remain;
  cross-type belief shows diversity 0.100 → strength 0.674→0.786 in rationale.

## Part B-2 — opinionated multi-source ingestion ✅ (Gates A–E shipped; 94 tests)
Goal: expert, stance-taking posts by ingesting OPINIONATED sources beyond GitHub. Plan:
`docs/PLAN_PART_B2_SOURCES.md`. Decisions settled: A1=pure-opinion→low-conf 0.3+stances;
finding_weight=1.0; wrap GitHub behind SourcePlugin; CLI `bgis run "kind:query"`; source_kind
deferred (derive from data/raw/<sid>.json `type`).
- **Gate A — claim typing**: `Claim.type` fact/opinion/finding (m04 classifies per doc [type]:
  readme/etc→fact, discussion→opinion, article/paper→opinion+finding). m11: confidence built from
  fact+finding only (`effective_conf=conf*type_weight`, fact 1.0/finding `finding_weight`/opinion 0);
  opinions→`BeliefDelta.stance_points`→`Belief.stances` (m12 dedup+cap 5). Pure-opinion concept →
  new belief at `pure_opinion_confidence`(0.3); on EXISTING belief opinions NEVER move confidence,
  only append stances. m14 has STANCES/DEBATE block → argues a position.
- **SourcePlugin interface** (`src/bgis/sources/`): `matches(ref)`+`ingest(ref,ctx)->IngestResult`
  {source,parsed,signals,repo?}. `repo` set only by GitHub → m09 sibling-retrieval stays
  GitHub-native; other sources skip it (pipeline guards `if repo is not None`). Registry+`resolve`.
  GitHub path wrapped behind `GitHubSourcePlugin` (m01/02/03/05). `bgis run` ref = URL or `kind:query`.
- **Gate B HN** (`hn:<q>`): Algolia API, no auth/deps, injectable fetch. story→`article` doc,
  comments→`discussion`. caps 5 stories/15 comments.
- **Gate C arXiv** (`arxiv:<q>`): Atom API, stdlib xml.etree (no dep). paper→`paper` doc (title+abstract).
- **Gate D GH Discussions/Issues** (`ghd:owner/repo`): PyGithub issues (busiest first, PRs excluded) +
  GraphQL discussions (optional, fails-soft). injectable gh+graphql. caps 20 issues/8 comments.
- **Gate E RSS** (`rss:<feed-url>` or `rss:all`): feedparser dep, injectable fetch. entry→`article` doc.
  curated feeds in `settings.rss_feeds`.
- **DocType** widened: +discussion/article/paper. **SourceType** widened: +hn/arxiv/gh_discussions/rss.
- Validated live: graph 164→185 beliefs; 11 span ≥2 source TYPES, one spans 3 (arxiv+github+hn on
  agent memory), 8 beliefs carry stances (was 0). HN/arXiv/ghd/RSS posts take a stance w/ counterargument.
- **Corroboration ratchet (m11)** ✅: SUPPORTING evidence never lowers an existing belief — a weaker
  but agreeing low-authority source (no stars→authority 0.25) HOLDS confidence instead of dragging it
  down; only CONTRADICTION (negative-polarity claims) can move it below the prior. Fixed the earlier
  bug where adding an HN/arXiv corroboration dropped a repo belief (bel_05e54570 0.87→0.76→0.68).
  Already-persisted lowered confidences from before the fix need a graph rebuild to correct.

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
