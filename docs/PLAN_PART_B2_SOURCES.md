# Part B-2 — Multi-source POV ingestion (implementation plan)

**Goal:** richer, human-like, *expert*, dot-connecting LinkedIn posts by ingesting **opinionated**
sources beyond GitHub. Posts take a stance (thought-leadership), grounded in facts (repos), backed by
findings (papers), sharpened by opinions/discourse (HN, blogs).

**Why this works:** GitHub repos only give *what-facts*. Expert posts need *why-opinions* + *evidence*
+ *tension*. Everything after Module 3 is already source-agnostic (`ParsedDocuments` contract), so new
sources plug in as `SourcePlugin`s and flow through the same belief engine.

**Build order (confirmed):** Gate A (claim-type) → B (HN) → C (arXiv) → D (GH Discussions) → E (RSS).
**Discipline:** one gate at a time — typed Pydantic I/O, unit test with fakes (no network), `run-module`
checkpoint on real data, review before the next gate.

---

## Gate A — claim-type upgrade  (the real unlock; do FIRST)

Without claim typing, an opinion gets averaged like a fact and the POV flattens. This gate changes the
math + planning, using existing repo sources (all typed `fact`) — no new ingestion, testable with fakes.

### Models (`src/bgis/models.py`)
- `ClaimType = Literal["fact", "opinion", "finding"]`.
- `Claim.type: ClaimType = "fact"` and `ClaimDraft.type: ClaimType = "fact"` (back-compat default).
- `BeliefDelta.stance_points: list[str] = []` — opinion claim texts that argue *about* the belief.
- `Belief.stances: list[str] = []` — accumulated stance points (capped, e.g. last 5), so m14 can argue.

### m04_claims
- SYSTEM prompt: classify each claim `fact` (verifiable capability/spec), `opinion` (a judgment/stance/
  prediction), or `finding` (empirical/benchmarked result). Repos → mostly `fact`. Keep `temperature=0`.
- Carry `type` through `ClaimDraft → Claim`.

### m11_delta  (key design)
- `evidence_strength` is computed from **facts + findings only** (opinions must NOT make a belief "true"):
  - `effective_conf(claim) = claim.confidence * type_weight[claim.type]`
  - `type_weight`: `fact=1.0`, `finding=finding_weight (cfg, default 1.0)`, `opinion=0.0` (excluded).
  - `mean_conf = mean(effective_conf over fact+finding claims)`; if none, fall back to opinions only as a
    weak signal OR skip the belief (decision below).
- Opinions are collected into `BeliefDelta.stance_points` (their texts), passed through to m12 → belief.
- Config: `finding_weight: float = 1.0`, (opinions excluded from confidence by design — no flag needed).

### m12_belief_graph
- Append `delta.stance_points` onto `belief.stances` (dedup, cap last 5).

### m14_narrative
- Belief lines already lead with NEW-from-this-source. Add a **STANCES/DEBATE** block built from
  `belief.stances` so the planner can take a side. SYSTEM: "use stances to argue a position; use findings
  as evidence; use facts as grounding."

### Tests (fakes, no network)
- m04: a draft with mixed types → `Claim.type` preserved.
- m11: opinions excluded from `evidence_strength`; `stance_points` populated; finding_weight applied.
- m12: stances accumulate + cap.
- m14: stances reach the prompt / plan.

### Open decision A1
If a concept has **only** opinion claims (no fact/finding) — skip the belief, or create it at low
confidence carrying only stances? Default proposal: **create at low confidence (e.g. 0.3) with stances**,
so pure-discourse concepts still inform posts. Confirm next session.

---

## Gate B — `SourcePlugin` interface + Hacker News (first opinion source)

### Interface (`src/bgis/sources/base.py`)
```python
class SourcePlugin(ABC):
    kind: str  # "github" | "hn" | "arxiv" | "gh_discussions" | "rss"
    def matches(self, ref: str) -> bool: ...          # URL/scheme/prefix detection
    def ingest(self, ref: str, ctx) -> ParsedDocuments: ...  # ref = URL or "kind:query"
```
- Registry `SOURCE_PLUGINS: list[SourcePlugin]`; `resolve(ref)` picks the first match.
- Refactor existing GitHub path (m01→m02→m03) behind a `GitHubSourcePlugin.ingest` (proves the interface;
  keeps `bgis run <github-url>` working). `source_id` stays `src_<sha8(ref)>`.
- CLI: `bgis run <ref>` where ref is a URL **or** `kind:query` (e.g. `bgis run "hn:agent memory"`).

### HN plugin (`src/bgis/sources/hn.py`) — no auth, no new deps (http only)
- Algolia API: `https://hn.algolia.com/api/v1/search?query=<q>&tags=story` → top N stories by points.
- Per story: fetch `https://hn.algolia.com/api/v1/items/<id>` → title + text + top-level comments.
- Build `ParsedDocuments`: story → a doc; comment thread → discourse text. Comments yield **opinion**
  claims downstream (m04 will type them).
- `source_id = src_<sha8("hn:"+query)>`. Caps: top 5 stories, top ~15 comments/story.
- Inject the HTTP getter for tests (`fetch=None` → real; fake in tests). No live calls in unit tests.

### Tests
- Fake fetch returns canned Algolia JSON → assert `ParsedDocuments` shape + that comment text is captured.
- `resolve("hn:...")` returns the HN plugin; `resolve("https://github.com/...")` returns GitHub.

### Checkpoint
- `bgis run "hn:ai agent memory"` end-to-end → opinionated post that argues a position. Compare to a
  repo-only post.

---

## Gate C — arXiv (evidence/findings layer)

- `src/bgis/sources/arxiv.py`: Atom API `http://export.arxiv.org/api/query?search_query=<q>&max_results=N`.
- Parse Atom (stdlib `xml.etree` to avoid a dep, or reuse feedparser if added in Gate E). Each paper →
  doc from title + abstract. Abstract claims → **finding** type.
- `ref = "arxiv:<query>"`. Caps: top 5 papers.
- Tests: canned Atom XML → ParsedDocuments. Checkpoint: `bgis run "arxiv:retrieval augmented generation"`.

---

## Gate D — GitHub Discussions / Issues (debate + pain; zero new deps)

- `src/bgis/sources/gh_discussions.py`: reuse the existing `GITHUB_TOKEN`.
  - Issues: `repo.get_issues(state="all")` + comments (PyGithub REST).
  - Discussions: GraphQL (PyGithub REST lacks discussions) — small GraphQL POST with the token.
- `ref = "ghd:owner/repo"`. Comments/issue bodies → **opinion** (debate) + some **fact**. Caps: top ~20
  issues by reactions/comments.
- Natural pairing: run on repos already in the graph → opinions attach to existing concepts/beliefs as
  stance. Tests: fake gh client. Checkpoint: `bgis run "ghd:mem0ai/mem0"`.

---

## Gate E — RSS expert blogs (essays/narrative)

- Add dep `feedparser`. `src/bgis/sources/rss.py`: parse a feed URL (or a configured list of curated
  feeds: simonwillison.net, latent.space, eng blogs). Each entry → doc from title + content/summary.
- If feeds are truncated, optional follow-on: article fetch + `trafilatura` (scraping path, separate gate).
- `ref = "rss:<feed-url>"` or `rss:all` (configured list). Entry claims → mostly **opinion/finding**.
- Tests: canned feed (feedparser parses a string). Checkpoint: `bgis run "rss:https://simonwillison.net/atom/everything/"`.

---

## Cross-cutting

- **Convergence across source *types*** already works via the concept store: a concept seen in a repo
  (fact) + a blog (opinion) + a paper (finding) resolves to one `concept_id` → one belief carrying
  grounding + stance + evidence. This is the dot-connecting payoff.
- **Provenance:** `BeliefHistoryEntry.source_id` already records origin. Consider adding `source_kind`
  so m14 can say "N sources across M types (repos, papers, discussions)".
- **Config:** per-source caps; `finding_weight`; curated RSS feed list; HN/arXiv default queries.
- **Caching:** new sources should respect `use_cache` like m04/m06 (cache claims/concepts per source_id).

## Open decisions — ALL SETTLED ✅ (2026-06-28)
1. **A1**: pure-opinion concept → **low-confidence 0.3 + stances** (config `pure_opinion_confidence`).
2. **finding_weight** = **1.0** (config; bump later if papers should outweigh repo facts).
3. **SourcePlugin refactor**: **wrapped** the GitHub path behind `GitHubSourcePlugin` (one clean seam).
4. **CLI surface**: **`bgis run "kind:query"`** (ref = URL or `kind:query`).
5. **`source_kind`**: **deferred** — derive on demand from `data/raw/<source_id>.json` `type` field
   (used for the "spans N source types" analysis). Add a denormalized field only if it's needed hot.

> Built: Gates A–E shipped, 97 tests, live-validated. See `CLAUDE.md` "Part B-2" + `docs/ARCHITECTURE.md`
> §2.5 (source plugins) + §4 (claim typing + corroboration ratchet).

## Status when this plan was written
- Branch `part-b-gap-retrieval-corroboration` pushed (commits: feat part-b m8/9/11, fix m11 ceiling,
  feat m14 repo-centric). 70 tests pass.
- A 30-repo full-chain rebuild was running; this plan is for the NEXT session after it completes.
