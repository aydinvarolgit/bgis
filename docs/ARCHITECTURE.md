# BGIS Architecture

> Belief Graph Intelligence System. Sources update an evolving global **belief graph**;
> content is generated **from that worldview, never from a single source document**.
> That decoupling is the core differentiator vs RAG/summarization.

---

## 1. Core idea

```
Source  (GitHub repo · Hacker News · arXiv · GH Discussions · RSS)
   │  SourcePlugin.ingest → ParsedDocuments (source-agnostic from here)
   ▼
Claims (typed fact/opinion/finding) + Signals + Concepts
   │  normalize into a GLOBAL concept space (dedup)
   ▼
Belief Delta → Global Belief Graph (evolving, temporal, explainable)
   │  facts+findings build confidence; opinions become belief STANCES
   ▼
Narrative Plan (argues from worldview + stances) → LinkedIn post
```

Sources are pluggable (`bgis.sources`): a repo gives *what-facts*, HN/discussions give *opinions*,
arXiv gives *findings*. They converge on shared `concept_id`s, so one belief can carry repo facts +
paper findings + discourse stances at once (the dot-connecting payoff).

Three knowledge layers:
- **Global Belief Graph** (Layer 1): the system's evolving understanding. `data/beliefs/bel_*.json` + Chroma `beliefs` collection.
- **Source Knowledge** (Layer 2): per-source claims/signals/concepts. `data/{claims,signals,concepts}/<id>.json`. Immutable per run.
- **User Belief Graph** (Layer 3): the author's opinions. `data/user_beliefs.json`. Read-only; never mutates Layer 1.

---

## 2. Pipeline (Modules 1–15)

`bgis run <ref>` (ref = GitHub URL **or** `kind:query`, e.g. `hn:agent memory`) chains these. Each is
`run(inp, ctx) -> OutModel`, output persisted, inspectable via `bgis run-module <name> --source-id <id>`.
**D** = deterministic, **L** = LLM (gemma4), **S** = stub. Modules 1–3+5 (GitHub ingestion) now run
behind a `SourcePlugin` (§2.5); non-GitHub sources produce `ParsedDocuments` directly.

| # | Module | Type | In → Out | Notes |
|--|--|--|--|--|
| 1 | discovery | D | `DiscoveryRequest` → `Source` | URL validate; `source_id = src_<sha8(url)>` (stable) |
| 2 | ingest | D | `Source` → `Repository` | PyGithub; defensive (missing readme/license ok) |
| 3 | parse | D | `Repository` → `ParsedDocuments` | readme/architecture/dependencies/metadata docs. **Source-specific knowledge ends here.** |
| 4 | claims | L | `ParsedDocuments` → `Claims` | semantic statements, each **typed** fact/opinion/finding (guided by doc `[type]`); temp=0; cached |
| 5 | signals | D | `Repository` → `Signals` | stars/forks/cadence/lang% — measurable facts, no LLM |
| 6 | concepts | L | `Claims` → `Concepts` | **dedup engine**: normalize→embed→Chroma banded match; temp=0; cached |
| 7 | belief_retrieval | D | `Concepts` → `RelatedBeliefs` | direct concept-link + semantic; cold start → empty |
| 8 | gap | L | `Concepts+RelatedBeliefs` → `Gaps{Gap{concept_id,question,kind}}` | gemma4 gap questions per concept; temp=0 |
| 9 | retrieval | D+API | `Gaps+Concepts+Claims+Repository?` → `RetrievedEvidence` | GitHub-native sibling repos (topic search + README links) **+ opt-in `RetrievalBackend`s** (§2.6) for any source type → `RetrievedItem{concept_id,...}`; embed-gated at `retrieval_match_threshold` |
| 10 | evidence | D | `Concepts+Claims+Signals+...` → `EvidencePackets` | **real**; one packet/concept; routes external by `concept_id`; feeds Module 11 |
| 11 | delta | D | `EvidencePackets+RelatedBeliefs` → `BeliefDeltas` | explainable math; confidence from fact+finding only, opinions→`stance_points`; corroboration ratchet (see §4) |
| 12 | belief_update | D | `BeliefDeltas` → `BeliefGraphUpdate` | persists beliefs; appends temporal history; never overwrites |
| 13 | user_beliefs | **S** | (file) → `UserBeliefs` | loads `data/user_beliefs.json` |
| 14 | narrative | L | `BeliefGraphUpdate+UserBeliefs+EvidencePackets` → `NarrativePlan` | **plans from worldview, not source**; THIS SOURCE block (this run's claims) leads, CORROBORATION block (deduped pre-existing beliefs) is secondary (Gate I); STANCES/DEBATE argues a position |
| 15 | content | L | `NarrativePlan` → `GeneratedContent` | LinkedIn markdown → `data/posts/<id>.md` |

All contracts live in `src/bgis/models.py` (single source of truth).

---

## 2.5 Source plugins (`src/bgis/sources/`)

Everything after Module 3 consumes a generic `ParsedDocuments`, so a source only has to produce one.
`SourcePlugin`: `matches(ref) -> bool` + `ingest(ref, ctx) -> IngestResult{source, parsed, signals,
repo?}`. `resolve(ref)` returns the first matching plugin. `bgis run <ref>` and `pipeline.run` drive it.

| plugin | ref | kind | notes |
|--|--|--|--|
| `GitHubSourcePlugin` | `https://github.com/o/r` | github | wraps m01→m02→m03+m05; **only** plugin that returns `repo` |
| `HNSourcePlugin` | `hn:<query>` | hn | Algolia API (no auth/deps); story→`article` doc, comments→`discussion` |
| `ArxivSourcePlugin` | `arxiv:<query>` | arxiv | Atom API, stdlib `xml.etree`; paper→`paper` doc (title+abstract) |
| `GHDiscussionsSourcePlugin` | `ghd:owner/repo` | gh_discussions | PyGithub issues + GraphQL discussions (fails-soft) |
| `RSSSourcePlugin` | `rss:<url>` \| `rss:all` | rss | `feedparser`; entry→`article` doc; curated `settings.rss_feeds` |
| `WebArticleSourcePlugin` | `url:<u>` \| bare `http(s)://` | web | `trafilatura` main-content extract; page→`article` doc; **registered last** so GitHub keeps its URLs |

`repo` is set **only** by GitHub because Module 9's sibling-repo retrieval is GitHub-native. The
pipeline now **always** runs m09 (`repo` is optional): the sibling search fires only with a repo,
while the §2.6 backends serve any source type. All HTTP getters are injectable
(`fetch`/`gh`/`graphql`) so unit tests never touch the network. `DocType` += discussion/article/paper;
`SourceType` += hn/arxiv/gh_discussions/rss/web.

## 2.6 Retrieval backends (`src/bgis/retrieval/`)

Module 9's GitHub-native sibling search is always-on and inline. Every OTHER way of acquiring
external evidence is a `RetrievalBackend`: `candidates(gaps, concepts, claims, ctx) -> [Candidate]`.
m09 embeds each `Candidate.text`, routes it to a concept (the candidate's `concept_id` hint, else
best cosine match), gates at `retrieval_match_threshold`, dedups by url, caps `retrieval_max_per_concept`,
and emits `RetrievedItem`s — so the relevance bar is identical across the GitHub path and all backends.

| backend | flag (default **off**) | source | notes |
|--|--|--|--|
| `SourcePluginBackend` | `retrieval_use_source_plugins` | reuse arxiv/hn/github plugins | routed by gap **kind** (research/validation→arxiv, adoption/risk→hn, competitor/alternative→github); no new dep |
| `LocalCorpusBackend` | `retrieval_use_local_corpus` | past `data/parsed/*.json` | embed-search previously-ingested docs (excl. current source); **zero network**, deterministic |
| `ExternalApiBackend` | `retrieval_use_external_apis` | Wikipedia + Semantic Scholar + Crossref | keyless REST; per-concept; injectable getters; fail-soft per API |

All default OFF, so GitHub-native remains the only default behavior (and non-repo sources still
emit no external evidence) until a flag is set. Fan-out is bounded by `retrieval_plugin_max_gaps`,
`retrieval_corpus_max_docs`, `retrieval_external_max_concepts`, etc. (see `config.py`). Enabling a
backend lets a single run pull corroboration for **any** source type — e.g. a web article goes from
0 → N external items feeding the §4 belief math.

**Deferred** (user undecided 2026-06-28): a general open-web `SearchBackend` — DuckDuckGo (keyless
`ddgs` lib) or self-hosted SearXNG — drops in via the same `candidates()` contract; the seam is ready.
Bing is **not** an option (Microsoft retired the Bing Search APIs ~Aug 2025).

---

## 3. Concept dedup (the hinge)

Belief continuity depends on the **same real-world concept → same `concept_id` across runs**.
`concept_<h>` maps deterministically to `bel_<h>` (Module 11), so a stable concept id ⇒ a belief
that evolves instead of forking.

Module 6 per candidate phrase:
1. normalize: lowercase → strip punct → alias map → singularize head word.
2. embed (nomic-embed-text).
3. **banded match** against Chroma `concepts` (cosine space):
   - `sim ≥ 0.72` (`concept_auto_merge_threshold`) → merge, no LLM.
   - `sim < 0.60` (`concept_similarity_threshold`) → new concept.
   - in between → gemma4 yes/no adjudication (temp=0): the **concept-merge pass**.

Measured nomic cosine: paraphrases 0.66–0.81, distinct ≤0.46 → bands chosen with margin.

**Caching** (`settings.use_cache`): `run_claims`/`run_concepts` reuse `data/{claims,concepts}/<id>.json`
on re-run ⇒ belief ids fixed ⇒ deterministic evolution. `bgis run --fresh` bypasses.

---

## 4. Belief delta math (Module 11, deterministic & explainable)

```
type_weight       = { fact: 1.0, finding: finding_weight=1.0, opinion: 0.0 }   # opinions excluded
effective_conf(c) = c.confidence * type_weight[c.type]
authority         = clamp( log10(stars + 10) / 4 , 0..1 )                       # repos (stars signal)
                  = source_type_authority[type]                                 # non-repo, no stars
base              = mean(effective_conf over fact+finding) * (0.5 + 0.5*authority) * ceiling=0.85
# Gate F — reserved headroom (1 - ceiling = 0.15) filled by a COMPOSITE bonus, summed then capped:
external_bonus    = min( external_corroboration_cap=0.15 , 0.05 * n_external )
diversity_bonus   = source_diversity_weight=0.05 * (n_distinct_source_TYPES - 1)
recency_bonus     = recency_weight=0.05 * recency_term(days_since_push)         # 0..1, 0 if absent
corroboration     = min( headroom=0.15 , external_bonus + diversity_bonus + recency_bonus )
evidence_strength = clamp( base + corroboration )
cold start (no prior belief): new = evidence_strength, old = 0
existing belief:              new = old + 0.3 * (evidence_strength - old)
delta = new - old   (all clamped to [0,1])
```
> Claims alone cap a belief at the 0.85 ceiling; the reserved 0.15 headroom is filled by a composite
> of **external** corroboration (m09: GitHub siblings + any enabled §2.6 backend — corpus/wiki/S2/
> crossref/plugins), **source-TYPE diversity** (repo-fact + paper-finding
> + discourse agreeing), and **recency**, so reaching ~1.0 requires either many sources or
> cross-TYPE agreement. external-only validated: n_external 0→0.85, 1→0.90, 7→1.00.

> **Source-TYPE weighting (Gate F).** Non-repo sources have no `stars`, so authority comes from a
> per-TYPE baseline: `arxiv 0.7 / rss 0.5 / hn,gh_discussions 0.4 / unknown 0.25` (== the old flat
> fallback). A peer-reviewed paper outweighs a random no-stars comment. Source TYPE per source_id is
> derived from `data/raw/<sid>.json` `type` (`m11.source_kind`). Diversity counts distinct TYPES in
> the current run ∪ the belief's history — completing the thesis that cross-TYPE agreement *moves*
> confidence, not just cross-source. Repersist after formula changes with `bgis rebuild` (§ below).

**Claim typing (Gate A).** Only `fact` + `finding` claims build confidence; `opinion` claims are
excluded and collected into `BeliefDelta.stance_points` → `Belief.stances` (Module 12 dedups, caps
last 5) so Module 14 can argue them. A concept backed **only** by opinions still creates a belief at
`pure_opinion_confidence=0.3` (cold start); on an existing belief, opinions never move confidence —
they only append stances.

**Corroboration ratchet.** For an existing belief, *supporting* evidence never lowers it: if a weaker
but agreeing source (e.g. low-authority discourse with no stars → authority 0.25) yields an
`evidence_strength` below the prior, the belief **holds** instead of regressing. Only *contradiction*
(negative-polarity claims) can move confidence down. This keeps cross-source agreement monotone — an
HN thread or arXiv paper corroborating a repo belief can only hold or raise it.

Every `BeliefDelta` carries a `rationale` list spelling out these inputs. Module 12 appends a
`BeliefHistoryEntry{ts, conf_before, conf_after, delta, source_id, supporting, contradicting}` —
so any belief traces back to the sources that shaped it. Trend: new / accelerating / declining / stable.

**Graph rebuild (`bgis rebuild` → `pipeline.rebuild_graph`).** After a formula change, repersist the
whole graph without re-ingesting: wipe `data/beliefs/bel_*.json`, then replay every persisted
`*_evidence.json` (in mtime = original ingest order) through the current Module 11 + 12. Deterministic,
no network. Used to repersist confidences computed under an older formula (e.g. pre-ratchet erosion).

**Seeding (`bgis seed <manifest>` → `pipeline.seed_one`).** Cold-start a fresh graph from a curated
batch of refs before any post-generating run. Each ref runs the full pipeline m01→m12 (gap + retrieval
ON, so seeds cross-corroborate) but **no m13/m14/m15** — seeding builds the graph, never a post.
`Belief.origin ∈ {source, seed}` (default `source`, so old `bel_*.json` load unchanged) is stamped at
m12 **create** time and is **permanent**. The single predicate is the sidecar `data/seed_sources.json`
(source_ids registered by `bgis seed` *before* each ref's m12); m12 and `rebuild` both read it, so the
seed tag is re-applied across a wipe+replay automatically (the sidecar isn't wiped). Module 14 excludes
`origin="seed"` beliefs from the lead/THIS-SOURCE block — seeds are corroboration substrate only.

---

## 5. Code layout

```
src/bgis/
  config.py        Settings (env, paths, thresholds, voice, cache flag) + LLMConfig/EmbeddingConfig (llm_config.json)
  models.py        ALL Pydantic contracts
  context.py       Context: settings + llm + embedder + vectors + beliefs (passed to every module)
  persistence.py   save/load/exists artifact JSON by stage+source_id
  llm.py           Ollama OpenAI-compat + instructor; multi-backend failover + retry/backoff (structured()/text())
  embeddings.py    Ollama nomic-embed-text (settings.embedding — separate endpoint from the LLM backends)
  vectorstore.py   ChromaDB wrapper (cosine collections: concepts, beliefs)
  belief_store.py  BeliefStore: file-backed beliefs + Chroma index (shared by M7, M12)
  pipeline.py      orchestrator: run() (resolves SourcePlugin) + run_<stage>() + load_<stage>()
  cli.py           Typer: run / run-module / seed / rebuild / graph / smoke
  sources/         SourcePlugin interface + registry (github, hn, arxiv, gh_discussions, rss, web)
  modules/m01..m15 one file per module

llm_config.json          LLM backends (failover) + retry/options + separate embedding endpoint

data/                    (gitignored, replayable)
  raw/ parsed/ claims/ signals/ concepts/ posts/
  beliefs/   bel_*.json = belief store; *_<stage>.json = pipeline artifacts (related/gaps/deltas/update/narrative/...)
  chroma/    persistent vector store
  user_beliefs.json      author's Layer-3 beliefs
  seed_sources.json      source_ids ingested via `bgis seed` (origin="seed" predicate)

tests/   one test_mNN_*.py per module + conftest fakes (FakeLLM/FakeEmbedder/FakeVectorStore)
```

Note: `BeliefStore.all()` globs only `bel_*.json` — other `*.json` in `data/beliefs/` are pipeline
artifacts, not beliefs.

---

## 6. Key design decisions

- Typed Pydantic I/O between every module; every artifact persisted ⇒ full replay + per-module inspection.
- Source-agnostic after Module 3, media-agnostic after Module 14 (`ContentGenerator` interface in m15).
- LLM only for semantic tasks (4, 6, 8, 14, 15); everything else deterministic.
- File/Chroma backing now; swap to Neo4j (`BeliefStore` iface) + Qdrant (`VectorStore` iface) later
  without touching the belief engine.
- Stubs (8/9/10-external/13) keep full contracts so future work is drop-in.
- Belief confidence (Gate F): claims-only caps at 0.85; the reserved 0.15 headroom is a *composite*
  of external + source-TYPE-diversity + recency, so cross-TYPE agreement (repo+paper+discourse) moves
  confidence. Source TYPE derived from `data/raw/<sid>.json`, not stored on the belief. Ratchet keeps
  supporting evidence monotone; only contradiction lowers. Repersist via `bgis rebuild`.
