# Plan — Global Belief Seeding (`bgis seed`)

Cold-start a fresh BGIS belief graph from a curated batch of source refs, before any
"real" post-generating run. Seed beliefs are marked permanent `origin="seed"` and are
**never promoted to the lead of a post** — they are background substrate only.

This follows the Part-B2 gate style: one feature, model change + module change + CLI +
pipeline + rebuild + tests, gated on tests + a live-validated artifact.

---

## 1. Intent (settled with user)

- **Seed input** = a **manifest file** of source refs, ingested in sequence.
- **Goal** = cold-start a fresh domain: give m07/m08/m11/m14 a worldview substrate so the
  first real runs aren't thin.
- **Mark semantics** = `origin="seed"`, **provenance + m14 lead-exclusion**, and the tag
  **stays seed forever** (real sources still move confidence, but never clear the tag).
- Seeds **cross-corroborate** as they load (shared BeliefStore), and run the **full
  pipeline m01→m12** (gap + retrieval ON) — just **no m14/m15** (no post per seed ref).

---

## 2. Single source of truth for "is this a seed?"

One predicate used at BOTH belief-creation time and rebuild time, so they never diverge:

```
source_id ∈ data/seed_sources.json  ⟺  origin = "seed"
```

- `data/seed_sources.json` = JSON list of source_ids ingested via `bgis seed`.
- The `seed` command appends each ref's resolved `source_id` to this file **before** that
  ref's m12 runs.
- m12 (create path) and `rebuild_graph` both read this set to decide `origin`.
- No new `ctx` flag, no plumbing through every module. The registry IS the flag.

Helper (new), e.g. in `pipeline.py` or a small `seed.py`:

```python
def load_seed_sources(ctx) -> set[str]: ...      # [] if file missing
def add_seed_source(ctx, source_id: str) -> None: # idempotent append + save
```

Path: `ctx.settings.data_dir / "seed_sources.json"` (match how other top-level data files
like `user_beliefs.json` are located — verify exact accessor in `settings.py`).

---

## 3. Model change — `Belief.origin`

`src/bgis/models.py`, `class Belief`:

```python
origin: Literal["source", "seed"] = "source"
```

- Default `"source"` → every existing `bel_*.json` deserializes unchanged (back-compat).
- Stamped only at **creation** (m12 create branch). Corroborating an existing belief never
  changes `origin` — including a seed run hitting a pre-existing `origin="source"` belief
  (it stays `"source"`), and a real run hitting a seed belief (stays `"seed"`).

---

## 4. m12 — stamp origin on create

`src/bgis/modules/m12_belief_graph.py`, the `existing is None:` branch only:

```python
seed_ids = load_seed_sources(ctx)
...
belief = Belief(
    ...,
    origin="seed" if inp.source_id in seed_ids else "source",
    history=[entry],
)
```

The `else` (update) branch is untouched — origin is immutable after creation.

---

## 5. CLI — `bgis seed <manifest>`

`src/bgis/cli.py`, new command (mirror `run` / `rebuild`):

```
bgis seed seeds.txt
```

- Read manifest: one ref per line; strip; skip blanks and `#` comments.
- For each ref, in order:
  1. `source_id = resolve(ref).source_id_for(ref)`  ← need a cheap way to get the
     source_id WITHOUT full ingest, OR run ingest first then read `ingest.source/parsed`.
     Simplest: ingest, take `source_id` off the resulting artifacts, then `add_seed_source`
     **before** `run_belief_update`. (Decide in code — see §8 note.)
  2. Run pipeline **m01→m12 only** (new `pipeline.seed_one(ref, ctx)` — a copy of `run()`
     truncated after `run_belief_update`, returning the `BeliefGraphUpdate`).
  3. `add_seed_source(ctx, source_id)` so the tag predicate holds for this and rebuild.
- Print a per-ref summary line (created/updated counts) + final graph size.
- `--fresh` passthrough like `run` (bypass cache) is optional; default reuse cache.
- Open-web search (DuckDuckGo) is ON by default and runs per ref → a large manifest = many live
  queries. For bulk seeding, prefix `BGIS_RETRIEVAL_USE_WEB_SEARCH=false` to skip the open-web
  lookups (the seeded refs still cross-corroborate each other within the run).

`pipeline.seed_one(ref, ctx)`:

```python
def seed_one(ref: str, ctx: Context) -> BeliefGraphUpdate:
    ingest = resolve(ref).ingest(ref, ctx)
    parsed, signals, repo = ingest.parsed, ingest.signals, ingest.repo
    add_seed_source(ctx, <source_id>)          # BEFORE m12 so origin stamps seed
    claims   = run_claims(parsed, ctx)
    concepts = run_concepts(claims, ctx)
    related  = run_belief_retrieval(concepts, ctx)
    gaps     = run_gap(concepts, related, ctx)
    retrieved= run_retrieval(gaps, concepts, claims, repo, ctx)
    packets  = run_evidence(concepts, claims, signals, related, retrieved, ctx)
    deltas   = run_delta(packets, related, ctx)
    return run_belief_update(deltas, ctx)       # m12 stamps origin=seed
```

(No m13/m14/m15.) Reuse existing `run_*` helpers verbatim so behavior matches a real run.

---

## 6. m14 — seed beliefs never lead

`src/bgis/modules/m14_narrative.py`. Gate I already splits THIS-SOURCE (lead) vs
CORROBORATION (secondary). Add one rule:

- When choosing the lead / main_belief and building the THIS-SOURCE block, **exclude any
  belief with `origin == "seed"`** — even if this run touched it. Seeds may still appear in
  the CORROBORATION block (with their independent-source counts) but are never the subject.
- Find where m14 partitions `update.beliefs` / `created_belief_ids` vs corroboration and add
  the `origin != "seed"` filter to the lead set. Confirm a created-this-run *seed* belief
  (possible if a real run first-creates a concept already... no — seed beliefs are created
  during seed runs, so in a real run they're pre-existing) lands in corroboration.

---

## 7. Rebuild — re-apply seed tag

`src/bgis/pipeline.py::rebuild_graph`. After the wipe+replay loop reconstructs beliefs, the
m12 create path already consults `load_seed_sources` — so replay **re-stamps origin
automatically**, because the creating `source_id` is still in `seed_sources.json` (the
sidecar is NOT wiped; only `bel_*.json` is). 

✅ No extra rebuild code needed IF m12 reads the registry on every create. Just confirm the
replay's first-touch source_id for a seed belief is the seed source_id (it is — replay is in
mtime/ingest order, and the seed ran before any real source). Add a test to lock it.

---

## 8. Build-time details to settle in code

- **source_id derivation**: confirm the field name on `ingest`/`Source`/`parsed` that gives
  the canonical `source_id` (m11/m12 use `inp.source_id`; trace back to where it's set).
  `add_seed_source` must use the SAME id m12 sees as `inp.source_id`.
- **settings data dir accessor**: confirm exact path helper for top-level `data/*.json`
  (look at how `user_beliefs.json` / `data/raw/` are located in `settings.py`).
- **`Literal` import** already present in models.py (used by SourceType) — reuse.

---

## 9. Tests (extend existing suite; no network — use conftest fakes)

1. `seed_sources` registry: `add_seed_source` idempotent append + survives reload;
   `load_seed_sources` returns `set()` when file absent.
2. m12 origin stamp: create with source_id in registry → `origin=="seed"`; not in registry
   → `"source"`; updating an existing belief never changes origin (both directions).
3. `seed_one`: ingests + builds graph, writes NO post artifact, registers the source_id.
4. m14 lead-exclusion: given an update whose touched beliefs include a seed belief, the
   chosen lead/main_belief is a non-seed belief; seed belief only in corroboration block.
5. Rebuild re-tag: seed a fake source + a real source, `rebuild_graph`, assert the seed
   belief still has `origin=="seed"` and the real one `"source"`.

Target: all current tests pass (107) + ~5 new. Back-compat: old `bel_*.json` load with
default `origin="source"`.

---

## 10. Live validation (after green tests)

- Author a small `seeds.txt` (e.g. 3–5 refs in one domain: a couple github repos + an
  arxiv query + an HN query).
- Fresh graph (or note current count), `bgis seed seeds.txt`, confirm:
  - graph grows, every newly-created belief has `origin=="seed"`,
  - `data/seed_sources.json` lists the seed source_ids,
  - NO files under `data/posts/` for seed refs.
- Then a **real** `bgis run <new ref>` in the same domain → post leads on the real source's
  beliefs; any seed belief it agrees with shows up only as corroboration (check the
  narrative artifact + post text).
- `bgis rebuild` → seed beliefs keep `origin=="seed"`.

---

## 11. Docs

- `CLAUDE.md`: add a "Seed — cold-start global beliefs ✅" status block (style of Gate G/I),
  noting `Belief.origin`, `data/seed_sources.json`, m14 lead-exclusion, rebuild-safe.
- `docs/ARCHITECTURE.md`: note the `origin` field + seed predicate + `bgis seed` flow.
- `docs/HANDOFF.md`: how to seed, where the manifest lives.

---

## 12. Out of scope (explicit)

- Generative seeding (LLM invents beliefs from a topic) — NOT this. Seeds come from real
  refs through the real pipeline.
- Confidence capping of seed beliefs — NOT doing; seeds enter at normal computed confidence.
  The only behavioral constraint is m14 lead-exclusion.
- Per-belief multi-origin (a belief that is "both") — origin is single, set once at create,
  permanent.
