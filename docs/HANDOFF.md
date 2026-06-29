# BGIS Handoff — continue in a new session

Read this first, then `docs/ARCHITECTURE.md` for detail. Quick status also in `CLAUDE.md`.

---

## Status: MVP COMPLETE ✅ + Part B ✅ + Part B-2 (multi-source POV) ✅

Source ref → LinkedIn post, end-to-end, all 15 modules. **97 unit tests pass.**
Cross-source AND cross-source-TYPE belief convergence + reproducible deterministic evolution
validated live. `bgis run <ref>` where ref = GitHub URL **or** `kind:query` (`hn:`/`arxiv:`/`ghd:`/`rss:`).

Done: Modules 1–15. **Modules 8 (gap), 9 (retrieval), 11 (corroboration) are REAL** — see "Part B".
**Part B-2 shipped**: claim typing + 5 source plugins (see below). Only Module 13 remains a stub
(user beliefs from a static file). Concept dedup tuned (cosine bands + LLM merge pass) + junk-concept
filter. Claims/concepts cached for reproducibility. Validated live: graph 164→185 beliefs, 11 span
≥2 source types (one spans 3: arxiv+github+hn), 8 carry stances.

## Part B-2 — opinionated multi-source ingestion ✅ (Gates A–E)
- **Gate A claim typing**: `Claim.type` fact/opinion/finding (m04 classifies guided by each doc's
  `[type]`). m11 builds confidence from **fact+finding only** (`effective_conf = conf*type_weight`,
  opinion weight 0); opinions → `BeliefDelta.stance_points` → `Belief.stances` (m12 dedup, cap 5);
  m14 STANCES/DEBATE block argues. Pure-opinion concept → belief at `pure_opinion_confidence` 0.3
  (cold) / confidence untouched (existing). **Corroboration ratchet**: supporting evidence never
  lowers an existing belief; only contradiction can.
- **SourcePlugin** (`src/bgis/sources/`): `resolve(ref)`; GitHub wrapped behind `GitHubSourcePlugin`
  (only one returning `repo`, so m09 stays GitHub-native). Sources: `hn:` (Algolia), `arxiv:` (Atom),
  `ghd:owner/repo` (issues+discussions), `rss:url`|`rss:all` (feedparser). All fetchers injectable.

## Part B — gap → retrieval → corroboration chain ✅

## Part B — gap → retrieval → corroboration chain ✅
- **m08 gap**: gemma4 (temp=0) per claim-backed concept → `Gap{concept_id, question, kind}` (kinds:
  competitor/adoption/research/alternative/risk/validation); ≤6 concepts × ≤2 questions.
- **m09 retrieval (GitHub-native)**: sibling repos via distinctive-topic `search_repositories` +
  README outbound repo links; routes each to its best concept via embedding of a rich concept rep
  (name + aliases + claim texts). Tune: `retrieval_match_threshold` (0.62), `retrieval_max_candidates` (6).
- **m10**: routes external evidence to its concept packet by `concept_id`.
- **m11**: claims cap a belief at `base_confidence_ceiling` (0.85); independent external
  corroboration fills the reserved 0.15 headroom (`external_corroboration_weight` 0.05, `_cap` 0.15).
  Validated: n_ext 0→0.85, 1→0.90, 7→1.00.
- **m06 junk filter**: `filter_generic_concepts` drops all-generic concept names (e.g. `llm-framework`).
- **Post voice**: `author_voice`="disciplined visionary"; m14/m15 ban cliches, force concrete specifics.

---

## Setup (fresh machine)

```bash
cd <project>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
# .env already has GITHUB_TOKEN (gitignored). Ollama must be running with:
ollama pull gemma4:latest          # local failover model
ollama pull nomic-embed-text       # embeddings
bgis smoke                         # verify ollama / embed / chroma / github
```

Prereqs assumed present: Ollama running, models `gemma4:latest` + `nomic-embed-text`.

**LLM/embedding config** = `llm_config.json` (project root, loaded by `config.py`). The `llm`
block holds an ordered `backends` list (first = default, rest = **failover**): default is the
`gemma4:31b-cloud` Ollama-cloud model, then local `gemma4:latest` if the cloud one errors. It also
carries retry/timeout/backoff and `options{temperature,num_ctx}`. The `embedding` block is SEPARATE
and stays on local `nomic-embed-text`. The cloud default needs Ollama signed in to cloud; without
it, runs transparently fall back to the local model. Repoint with `BGIS_LLM_CONFIG`; absent file →
built-in defaults. `llm.py` owns the per-backend retry + failover loop.

---

## Run

Holistic reference is in `--help`: `bgis --help` (command overview + examples), and
`bgis run --help` / `bgis seed --help` print the full REF-scheme table (github / hn / arxiv / ghd /
rss / url / bare-URL, each with an example). REF grammar is shared by `run` and `seed`.

```bash
bgis run https://github.com/owner/repo          # full pipeline → data/posts/<id>.md
bgis run "hn:agent memory"                       # non-GitHub source: hn:/arxiv:/ghd:/rss:
bgis run "arxiv:retrieval augmented generation"  # findings | bgis run "ghd:owner/repo" (debate)
bgis run "rss:all"                               # curated feeds (settings.rss_feeds)
bgis run "url:https://blog.example/post"          # bare web article (trafilatura extract); bare http(s) also works
bgis run <ref> --fresh                           # ignore cached claims/concepts, re-extract
bgis run-module <name> --source-id <id>          # single module from persisted input
bgis run-module discovery --url <url>            # discovery needs --url
bgis rebuild                                     # wipe + replay belief graph through current m11 math (Gate F)
bgis seed seeds.txt                              # cold-start: bulk-ingest a manifest of refs (m01→m12, NO post);
                                                 #   created beliefs get permanent origin="seed" (never lead a post,
                                                 #   corroboration substrate only). Registry: data/seed_sources.json.
bgis graph                                       # read the belief graph (consensus/trends/momentum/pillars/fringe)
bgis graph --view consensus --limit 20           # one lens
bgis graph --belief bel_xxxxxxxx                 # evidence trail (provenance) for one belief
pytest                                           # all tests (no network; conftest fakes)
```

Module names for `run-module`: discovery, ingest, parse, claims, signals, concepts,
belief_retrieval, gap, retrieval, evidence, delta, belief_update, user_beliefs, narrative, content.

Inspect any boundary: `data/<stage>/<source_id>.json`. Beliefs: `data/beliefs/bel_*.json`.

---

## Reset the belief graph (clean demo)

```bash
rm -rf data/chroma data/beliefs data/concepts data/claims
mkdir -p data/chroma data/beliefs data/concepts data/claims
```
(Leaves user_beliefs.json intact.) Then re-run repos to repopulate. Resetting Chroma is required
if you change vector-space or thresholds.

---

## Known issues / non-obvious gotchas

1. **Chroma space is fixed at collection creation.** Collections use cosine space. If you change
   the space or want to re-measure thresholds, you must delete `data/chroma/` (collections can't be
   reconfigured in place).
2. **`data/beliefs/` mixes two things**: `bel_*.json` (the belief store) and `*_<stage>.json`
   (pipeline artifacts). `BeliefStore.all()` only reads `bel_*.json`. Don't break that glob.
3. **LLM extraction isn't bit-deterministic** even at temp=0 (Ollama). Caching (`use_cache`) is what
   makes re-runs reproducible. A truly fresh extraction may yield a slightly different concept set.
4. **Belief delta `old_conf` comes from retrieved RelatedBeliefs, not the live store.** Module 11 is
   pure; Module 12 reconciles against the store. Re-running `belief_update` alone (not full pipeline)
   can therefore look inconsistent — run the full pipeline for correct numbers.
5. **Large repos**: ingest caps tree (2000), commits (30), releases (20); docs truncated to 6000
   chars for the LLM. Fine, but be aware when reasoning about coverage.
6. ~~m11 corroboration saturates~~ **FIXED**: `base` is now scaled by `base_confidence_ceiling`
   (0.85), reserving 0.15 headroom for external corroboration, so it moves even claims-maxed beliefs.
   Side effect: a single-source belief now tops out at 0.85; reaching ~1.0 requires independent
   corroboration (intended). Re-run / rebuild the graph to repersist confidences on the new scale.
7. **m09 hits the live GitHub API** (search + get_repo) on every run — slower than the rest of the
   pipeline and counts against the rate limit. `gh` is injectable; tests use a fake.
8. ~~Corroboration could LOWER a belief~~ **FIXED** (ratchet) + **rebuilt** (Gate F): supporting
   evidence holds or raises, only contradiction lowers. The graph was rebuilt (`bgis rebuild`) so
   pre-fix confidences are repersisted — bel_05e54570 is now 0.92 stable (was 0.64 declining).
9. **Non-GitHub sources have no `repo`** → Module 9 (sibling retrieval) is skipped for them and they
   emit no `stars` signal (authority falls back to the 0.25 baseline). By design.

---

## Suggested next steps (Part B — see ARCHITECTURE §6)

Ordered by value:

1. ~~Fix m11 corroboration saturation~~ ✅ done (base_confidence_ceiling reserves headroom).
2. ~~Module 8 (gap) real~~ ✅ done.
3. ~~Module 9 (retrieval) real~~ ✅ done (GitHub-native). **Pluggable backends added** ✅
   (`src/bgis/retrieval/`, `RetrievalBackend` interface, 117 tests): GitHub-native sibling search
   stays default-on/inline; three OPT-IN backends (all `retrieval_use_*` settings default False) now
   let ANY source type pull corroboration, not just repos —
   `SourcePluginBackend` (reuse arxiv/hn/github plugins, routed by gap KIND),
   `LocalCorpusBackend` (embed-search past `data/parsed/*.json`, zero network),
   `ExternalApiBackend` (keyless Wikipedia + Semantic Scholar + Crossref). Every candidate is
   embedded + gated at `retrieval_match_threshold`, dedup by url, capped `retrieval_max_per_concept`.
   Pipeline now always calls m09 (repo optional). Live: web article `src_df63a983` went 0 → 8
   external items (1 corpus + 3 wikipedia + 4 crossref), correctly concept-routed.
   **Open-web `SearchBackend`** ✅ **done** — `WebSearchBackend` (`src/bgis/retrieval/web_search.py`):
   DuckDuckGo via the keyless `ddgs` lib, per-concept text search, `retrieval_use_web_search`
   **defaults ON** (every run pulls open-web corroboration; tests pin it OFF in the conftest fixture).
   Injectable `search(query,n)->[{title,href,body}]` → offline tests; fail-soft per
   query; routed + threshold-gated by m09 like every backend. Inject a SearXNG-backed `search` for
   self-hosted meta-search (same contract). Bing was NOT an option (MS retired the Bing Search APIs
   ~Aug 2025). Still open: dependency-file candidates in the GitHub path.
4. ~~Source plugins~~ ✅ done (Part B-2): HN/arXiv/GH-Discussions/RSS behind `SourcePlugin`.
   ~~web-article plugin~~ ✅ **done (Gate G)**: `WebArticleSourcePlugin` — `url:<u>` or bare http(s)
   URL → `trafilatura` main-content extract → one `article` doc (type `web`, authority baseline 0.5,
   no repo → m09 skipped). Injectable `fetch`; registered last so GitHub keeps its URLs. Live:
   `bgis run "url:https://simonwillison.net/2024/Dec/31/llms-in-2024/"` → post + 5 web beliefs.
   Optional follow-on still open: PDF plugin.
5. **More media** — blog/report/newsletter `ContentGenerator`s (m15 interface ready).
6. **Storage migration** — `BeliefStore` → Neo4j, `VectorStore` → Qdrant, behind current interfaces.
7. ~~**Contradiction handling**~~ ✅ **done** — m11 no longer just dampens. A source's contradicting
   (negative-polarity fact/finding) claims against an EXISTING belief now spawn a COMPETING belief
   `bel_<h>__c` (`Belief.counter_to` → primary; primary's `disputed_by` ← counter, wired in m12). The
   counter accrues its own confidence from the contradicting evidence (`_support_delta`, no
   external/diversity/recency bonus); the primary HOLDS (ratchet) instead of being dragged down — the
   disagreement is represented structurally, not averaged. m12 applies primaries before counters so
   the back-link survives a same-run primary save. m14 gets an OPEN CONTRADICTIONS block (`_debate_lines`)
   pairing each disputed belief with its counter + both confidences, and is told to take a reasoned
   side. Cold start (no prior belief) keeps negatives in the belief's own negative statement.
8. ~~**Richer delta**~~ ✅ **done (Gate F)** — evidence_strength's reserved headroom is now a
   COMPOSITE bonus: `min(headroom, external + diversity + recency)`. diversity = `0.05 *
   (n_distinct_source_TYPES - 1)` so repo-fact + paper-finding + discourse agreeing MOVES
   confidence; recency = `0.05 * term(days_since_push)`; non-repo sources get a per-TYPE authority
   baseline (arxiv 0.7 / rss 0.5 / hn,ghd 0.4 / unknown 0.25) instead of the flat 0.25. Source TYPE
   per source_id derived from `data/raw/<sid>.json`. Composes with ceiling/ratchet/pure-opinion.
   **Graph rebuilt** via `bgis rebuild` (wipe + chronological evidence-packet replay, no re-ingest):
   bel_05e54570 0.64 declining → 0.92 stable; no `declining` beliefs remain.
9. ~~**Source-centered narrative**~~ ✅ **done (Gate I)** — m14 drifted onto pre-existing
   higher-confidence beliefs when a source's concepts deduped onto them (post stopped being about the
   ingested source). m14 now consumes `EvidencePackets` and splits the prompt into a THIS SOURCE lead
   block (this run's own claim texts, routed by `belief_id_for_concept`) and a secondary CORROBORATION
   block (deduped pre-existing beliefs, support only). Validated on the GLM-5.2 article: post centers
   on GLM-5.2, not the previously-dominant Ollama/Agent Framework.

---

## Where things live (cheat sheet)

| want to change | edit |
|--|--|
| thresholds / model names / voice / cache | `src/bgis/config.py` |
| any data contract | `src/bgis/models.py` |
| belief math | `src/bgis/modules/m11_delta.py` |
| dedup bands / merge pass | `src/bgis/modules/m06_concepts.py` |
| belief persistence | `src/bgis/belief_store.py` |
| add a module to the chain | `src/bgis/pipeline.py` + a `cli.py` run-module case |
| author beliefs | `data/user_beliefs.json` |
| plan / vision | `~/.claude/plans/i-want-a-good-swirling-nebula.md` |
