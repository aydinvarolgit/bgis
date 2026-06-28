# BGIS Handoff — continue in a new session

Read this first, then `docs/ARCHITECTURE.md` for detail. Quick status also in `CLAUDE.md`.

---

## Status: MVP COMPLETE ✅

GitHub repo URL → LinkedIn post, end-to-end, all 15 modules. **57 unit tests pass.**
Cross-source belief convergence + reproducible deterministic evolution both validated live.

Done: Modules 1–15 (8/9/10-external/13 are stubs by design). Concept dedup tuned (cosine bands +
LLM merge pass). Claims/concepts cached for reproducibility. User belief graph seeded (7 author
beliefs). Validated on 3 repos: caveman, microsoft/autogen, simonw/llm.

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
bgis run <url> --fresh                           # ignore cached claims/concepts, re-extract
bgis run-module <name> --source-id <id>          # single module from persisted input
bgis run-module discovery --url <url>            # discovery needs --url
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

---

## Suggested next steps (Part B — see ARCHITECTURE §6)

Ordered by value:

1. **Cross-source recall tuning** — validate concept merges across many AI repos; tune
   `concept_auto_merge_threshold`. Current bias is precision (few false merges, some missed links).
2. **Module 8 (gap) real** — LLM generates questions (competitors? papers? growth?).
3. **Module 9 (retrieval) real** — follow repo links/deps/topics; optional search-plugin adapters
   (Tavily/Brave) behind a `SourcePlugin`/`SearchPlugin` interface. Then Module 10 gets external
   evidence → multi-source convergence per single run.
4. **Source plugins** — web article / PDF / arXiv ingestion feeding the same `ParsedDocuments`
   contract (everything after Module 3 is already source-agnostic).
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
