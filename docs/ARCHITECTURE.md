# BGIS Architecture

> Belief Graph Intelligence System. Sources update an evolving global **belief graph**;
> content is generated **from that worldview, never from a single source document**.
> That decoupling is the core differentiator vs RAG/summarization.

---

## 1. Core idea

```
Source (GitHub repo)
   │  ingest → structured knowledge
   ▼
Claims + Signals + Concepts
   │  normalize into a GLOBAL concept space (dedup)
   ▼
Belief Delta → Global Belief Graph (evolving, temporal, explainable)
   │  content consumes the WORLDVIEW, blended with the author's own beliefs
   ▼
Narrative Plan → LinkedIn post
```

Three knowledge layers:
- **Global Belief Graph** (Layer 1): the system's evolving understanding. `data/beliefs/bel_*.json` + Chroma `beliefs` collection.
- **Source Knowledge** (Layer 2): per-source claims/signals/concepts. `data/{claims,signals,concepts}/<id>.json`. Immutable per run.
- **User Belief Graph** (Layer 3): the author's opinions. `data/user_beliefs.json`. Read-only; never mutates Layer 1.

---

## 2. Pipeline (Modules 1–15)

`bgis run <url>` chains these. Each is `run(inp, ctx) -> OutModel`, output persisted, inspectable via
`bgis run-module <name> --source-id <id>`. **D** = deterministic, **L** = LLM (gemma4), **S** = stub.

| # | Module | Type | In → Out | Notes |
|--|--|--|--|--|
| 1 | discovery | D | `DiscoveryRequest` → `Source` | URL validate; `source_id = src_<sha8(url)>` (stable) |
| 2 | ingest | D | `Source` → `Repository` | PyGithub; defensive (missing readme/license ok) |
| 3 | parse | D | `Repository` → `ParsedDocuments` | readme/architecture/dependencies/metadata docs. **Source-specific knowledge ends here.** |
| 4 | claims | L | `ParsedDocuments` → `Claims` | semantic statements; temp=0; cached |
| 5 | signals | D | `Repository` → `Signals` | stars/forks/cadence/lang% — measurable facts, no LLM |
| 6 | concepts | L | `Claims` → `Concepts` | **dedup engine**: normalize→embed→Chroma banded match; temp=0; cached |
| 7 | belief_retrieval | D | `Concepts` → `RelatedBeliefs` | direct concept-link + semantic; cold start → empty |
| 8 | gap | L | `Concepts+RelatedBeliefs` → `Gaps{Gap{concept_id,question,kind}}` | gemma4 gap questions per concept; temp=0 |
| 9 | retrieval | D+API | `Gaps+Concepts+Claims+Repository` → `RetrievedEvidence` | GitHub-native: sibling repos (topic search + README links) → `RetrievedItem{concept_id,...}` |
| 10 | evidence | D | `Concepts+Claims+Signals+...` → `EvidencePackets` | **real**; one packet/concept; routes external by `concept_id`; feeds Module 11 |
| 11 | delta | D | `EvidencePackets+RelatedBeliefs` → `BeliefDeltas` | explainable belief-update math + bounded external corroboration (see §4) |
| 12 | belief_update | D | `BeliefDeltas` → `BeliefGraphUpdate` | persists beliefs; appends temporal history; never overwrites |
| 13 | user_beliefs | **S** | (file) → `UserBeliefs` | loads `data/user_beliefs.json` |
| 14 | narrative | L | `BeliefGraphUpdate(beliefs)+UserBeliefs` → `NarrativePlan` | **plans from worldview, not source** |
| 15 | content | L | `NarrativePlan` → `GeneratedContent` | LinkedIn markdown → `data/posts/<id>.md` |

All contracts live in `src/bgis/models.py` (single source of truth).

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
authority         = clamp( log10(stars + 10) / 4 , 0..1 )
base              = mean(claim.confidence) * (0.5 + 0.5 * authority) * base_confidence_ceiling=0.85
corroboration     = min( external_corroboration_cap=0.15 , 0.05 * n_external )
evidence_strength = clamp( base + corroboration )
cold start (no prior belief): new = evidence_strength, old = 0
existing belief:              new = old + 0.3 * (evidence_strength - old)
delta = new - old   (all clamped to [0,1])
```
> Claims alone cap a belief at the 0.85 ceiling; the reserved 0.15 headroom is filled only by
> independent external corroboration (so reaching ~1.0 requires multiple sources). Validated:
> n_external 0→0.85, 1→0.90, 7→1.00.
Every `BeliefDelta` carries a `rationale` list spelling out these inputs. Module 12 appends a
`BeliefHistoryEntry{ts, conf_before, conf_after, delta, source_id, supporting, contradicting}` —
so any belief traces back to the sources that shaped it. Trend: new / accelerating / declining / stable.

---

## 5. Code layout

```
src/bgis/
  config.py        Settings (env, paths, thresholds, voice, cache flag)
  models.py        ALL Pydantic contracts
  context.py       Context: settings + llm + embedder + vectors + beliefs (passed to every module)
  persistence.py   save/load/exists artifact JSON by stage+source_id
  llm.py           Ollama OpenAI-compat + instructor (structured()) + text()
  embeddings.py    Ollama nomic-embed-text
  vectorstore.py   ChromaDB wrapper (cosine collections: concepts, beliefs)
  belief_store.py  BeliefStore: file-backed beliefs + Chroma index (shared by M7, M12)
  pipeline.py      orchestrator: run() + run_<stage>() + load_<stage>()
  cli.py           Typer: run / run-module / smoke
  modules/m01..m15 one file per module

data/                    (gitignored, replayable)
  raw/ parsed/ claims/ signals/ concepts/ posts/
  beliefs/   bel_*.json = belief store; *_<stage>.json = pipeline artifacts (related/gaps/deltas/update/narrative/...)
  chroma/    persistent vector store
  user_beliefs.json      author's Layer-3 beliefs

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
