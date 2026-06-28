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
ollama pull gemma4:latest          # already present
ollama pull nomic-embed-text       # already present
bgis smoke                         # verify ollama / embed / chroma / github
```

Prereqs assumed present: Ollama running, models `gemma4:latest` + `nomic-embed-text`.

---

## Run

```bash
bgis run https://github.com/owner/repo          # full pipeline → data/posts/<id>.md
bgis run "hn:agent memory"                       # non-GitHub source: hn:/arxiv:/ghd:/rss:
bgis run "arxiv:retrieval augmented generation"  # findings | bgis run "ghd:owner/repo" (debate)
bgis run "rss:all"                               # curated feeds (settings.rss_feeds)
bgis run <ref> --fresh                           # ignore cached claims/concepts, re-extract
bgis run-module <name> --source-id <id>          # single module from persisted input
bgis run-module discovery --url <url>            # discovery needs --url
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
8. ~~Corroboration could LOWER a belief~~ **FIXED** (ratchet): a low-authority supporting source
   (no stars→authority 0.25) no longer drags an established belief down — supporting evidence holds
   or raises, only contradiction lowers. Confidences persisted *before* this fix (e.g. bel_05e54570
   at 0.68) stay wrong until a graph rebuild repersists them.
9. **Non-GitHub sources have no `repo`** → Module 9 (sibling retrieval) is skipped for them and they
   emit no `stars` signal (authority falls back to the 0.25 baseline). By design.

---

## Suggested next steps (Part B — see ARCHITECTURE §6)

Ordered by value:

1. ~~Fix m11 corroboration saturation~~ ✅ done (base_confidence_ceiling reserves headroom).
2. ~~Module 8 (gap) real~~ ✅ done.
3. ~~Module 9 (retrieval) real~~ ✅ done (GitHub-native). Optional follow-on: search-plugin adapters
   (Tavily/Brave) behind a `SearchPlugin` interface; dependency-file candidates in m09.
4. ~~Source plugins~~ ✅ done (Part B-2): HN/arXiv/GH-Discussions/RSS behind `SourcePlugin`.
   Optional follow-on: web-article/PDF plugins; article fetch + `trafilatura` for truncated feeds.
5. **More media** — blog/report/newsletter `ContentGenerator`s (m15 interface ready).
6. **Storage migration** — `BeliefStore` → Neo4j, `VectorStore` → Qdrant, behind current interfaces.
7. **Contradiction handling** — Module 11 currently records contradicting claim ids; make
   contradictions spawn competing beliefs rather than just dampening.
8. **Richer delta** — add recency / source-diversity / agreement weighting to evidence_strength.

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
