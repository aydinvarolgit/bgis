# Next session kickoff — Gates F / G / H

> **Progress:** Gate F (richer delta) ✅ and Gate G (web-article plugin) ✅ shipped — 107 tests pass.
> **Remaining: Gate H** (multi-media content, HANDOFF #5). The brief below is the original 3-gate
> plan; start the next session on Gate H only.

Paste the block below to start the next session. Goal: deliver three documented next-steps
(HANDOFF #8 richer delta, #4 web-article plugin, #5 multi-media content), gated.

---

```
Project: BGIS (Belief Graph Intelligence System) at
/Users/aydinvarol/Documents/code/Trials/Claude-Trials/bgis. Git repo, branch main, public
repo aydinvarolgit/bgis. COMMIT DIRECTLY TO MAIN — never branch, never PR. Commit only when I
ask. 97 tests pass (HEAD ~8dc5693). Keep caveman mode (full).

Read first, in order: CLAUDE.md, docs/HANDOFF.md, docs/ARCHITECTURE.md (esp §2.5 source plugins,
§4 belief math), src/bgis/models.py (contracts), src/bgis/modules/m11_delta.py,
src/bgis/modules/m15_content.py, src/bgis/sources/ (the plugin pattern). Inspect the live graph
with `bgis graph` to ground yourself (185 beliefs, 5 source kinds).

Context: Part B-2 just shipped — typed claims (fact/opinion/finding), 5 SourcePlugins
(github/hn/arxiv/gh_discussions/rss), opinions become belief.stances, and an m11 corroboration
ratchet (supporting evidence never lowers a belief; only contradiction can). Now deliver three
documented next-steps, GATED, in this order:

  Gate F — Richer belief delta (HANDOFF #8). Add recency + source-diversity + source-TYPE
    weighting to evidence_strength in m11, so cross-source-TYPE agreement (repo fact + paper
    finding + discourse) actually MOVES confidence — completing the Part B-2 thesis. Must compose
    with base_confidence_ceiling=0.85, external corroboration, the ratchet, and pure-opinion 0.3.
    Then do the one-time GRAPH REBUILD to repersist confidences lowered before the ratchet fix
    (e.g. bel_05e54570 stuck at 0.68). source_kind is derivable from data/raw/<sid>.json `type`.

  Gate G — Web-article source plugin (HANDOFF #4, web-article ONLY — not PDF). New SourcePlugin
    for a bare article URL (decide ref scheme: `url:<u>` vs bare http). Fetch + main-content
    extract via trafilatura (new dep), entry -> `article` Document. Injectable fetch, no network
    in tests. Reuses everything after m03.

  Gate H — Multi-media content (HANDOFF #5). m15 ContentGenerator beyond LinkedIn: widen
    GeneratedContent.media, add a generator/prompt per medium (e.g. blog post, newsletter, X
    thread), CLI `bgis run <ref> --media <kind>`. m14 NarrativePlan stays the shared input.

Gate discipline: typed Pydantic I/O, unit tests with conftest fakes (NO network), `run-module`/
live checkpoint on real data, then STOP for my review before the next gate. Do NOT build later
gates in an earlier gate. LLM only for semantic tasks; everything else deterministic. Run
`pytest` green before declaring each gate done.

Before writing code, settle these decisions (pick sensible defaults, ask me only what you can't):
  F1. evidence_strength reformulation — how to fold in type/recency/diversity without breaking
      the 0.85 ceiling + ratchet (propose explicit formula + weights).
  F2. source-type weights (repo vs paper vs discourse) — values?
  F3. graph rebuild — full wipe+replay of all sources, or in-place recompute from history?
  G1. web-article ref scheme: `url:<u>` vs bare URL auto-detect.
  H1. which media to ship first + whether per-media prompt files or one parametrized prompt.

Start with Gate F only.
```
