"""BGIS command-line interface (Typer).

Holistic help lives in --help: `bgis --help` (command overview + examples), `bgis run --help`
and `bgis seed --help` (full REF-scheme table). REF grammar is shared by run + seed (REF_SCHEMES);
rich_markup_mode="markdown" so fenced ``` blocks render aligned (epilog reflows, so tables go in help=).

  bgis run <REF> [--fresh]           full pipeline -> LinkedIn post (REF = github URL | kind:query)
  bgis seed <manifest> [--fresh]     cold-start the belief graph from a batch of REFs (no post)
  bgis run-module <name> [--url U]   run a single module from its persisted input
  bgis rebuild [-y]                  wipe + replay belief graph through current belief math
  bgis graph [--view V] [--belief B] read the belief graph
  bgis smoke                         verify Ollama, embeddings, Chroma, GitHub token
"""

from __future__ import annotations

import typer
from rich import print as rprint

from .context import Context
from . import pipeline

# Shared across `run` and `seed` — both take the SAME ref grammar. Kept here so --help shows it.
# rich_markup_mode="markdown" (below) renders fenced ``` blocks verbatim, preserving alignment.
REF_SCHEMES = """\
**REF schemes** — a REF names ONE source; its scheme selects the ingestion plugin:

```
https://github.com/owner/repo   GitHub repo (full ingest + sibling retrieval; needs GITHUB_TOKEN)
hn:<query>                      Hacker News story + comments   (e.g. "hn:agent memory")
arxiv:<query>                   arXiv paper (title + abstract) (e.g. "arxiv:LLM marketing")
ghd:owner/repo                  GitHub Discussions / Issues    (e.g. "ghd:langgenius/dify")
rss:<feed-url>  |  rss:all      RSS feed entries (rss:all = curated settings.rss_feeds)
url:<article-url>               Web article via trafilatura    (e.g. "url:https://blog/post")
https://<non-github-url>        Bare web URL also works (web plugin claims non-github URLs)
```

Quote any REF containing a space or ':' so the shell keeps it intact.
"""

APP_HELP = """\
**Belief Graph Intelligence System** — ingest sources into an evolving global belief graph,
then generate content FROM the graph (never from the source directly).

```
run      one source REF        -> a LinkedIn post (data/posts/<id>.md)
seed     a manifest of REFs    -> grow the graph only, NO post (beliefs tagged origin="seed")
graph    read the belief graph -> consensus / trends / momentum / pillars / fringe
rebuild  wipe + replay beliefs through current belief math (no re-ingest, no network)
smoke    check Ollama / embeddings / Chroma / GitHub are reachable
```

Typical flow: `bgis smoke` -> `bgis seed seeds.txt` -> `bgis run <url>` -> `bgis graph`.
Run `bgis run --help` (or `bgis seed --help`) for the full REF grammar.
"""

EXAMPLES = """\
**Examples**

```
bgis run https://github.com/langgenius/dify        # GitHub repo -> post
bgis run "hn:AI marketing automation"              # Hacker News thread -> post
bgis run "arxiv:LLM recommender systems"           # arXiv paper -> post
bgis run "ghd:langgenius/dify"                      # GH Discussions/Issues -> post
bgis run "url:https://www.ibm.com/think/topics/ai-agents-in-marketing"
bgis run https://github.com/owner/repo --fresh     # bypass claim/concept cache
bgis seed seeds_ai_marketing.txt                    # batch-build the graph, no posts
```
"""

# epilog ignores markdown code fences (reflows), so the schemes/examples live in the command help.
RUN_HELP = (
    "Run the full pipeline: one source REF -> a LinkedIn post (`data/posts/<id>.md`).\n\n"
    "The REF scheme picks the source plugin. The post is planned from the updated belief graph, not "
    "the source text — the source LEADS, seeded beliefs corroborate.\n\n" + REF_SCHEMES + "\n" + EXAMPLES
)
SEED_HELP = (
    "Cold-start the global belief graph from a manifest of source REFs (NO posts generated).\n\n"
    "Each non-comment line is a REF using the SAME grammar as `bgis run` (below). Refs ingest in "
    "order through m01->m12 so they cross-corroborate. Created beliefs are marked `origin=\"seed\"`: "
    "permanent provenance; m14 never leads a post on them (corroboration substrate only).\n\n"
    "TIP: open-web search (DuckDuckGo) is ON by default and fires per ref, so a large manifest makes "
    "many live queries (slower, DDG rate-limit risk). For bulk seeding run with "
    "`BGIS_RETRIEVAL_USE_WEB_SEARCH=false` — within-run cross-corroboration between the seeded refs "
    "still works; you only drop the open-web lookups.\n\n"
    + REF_SCHEMES
)

app = typer.Typer(add_completion=False, rich_markup_mode="markdown", help=APP_HELP + "\n" + EXAMPLES)


@app.command(help=RUN_HELP)
def run(
    ref: str = typer.Argument(
        ...,
        help="Source REF: github URL | hn:/arxiv:/ghd:/rss:/url: query | bare web URL. See below.",
    ),
    fresh: bool = typer.Option(False, "--fresh", help="Ignore cached claims/concepts; re-extract"),
):
    ctx = Context()
    if fresh:
        ctx.settings.use_cache = False
    content = pipeline.run(ref, ctx)
    post_path = ctx.settings.stage_dir("posts") / f"{content.source_id}.md"
    rprint(f"[green]Post generated[/green] ({content.word_count} words) -> {post_path}")
    rprint("\n" + content.markdown)


@app.command(name="run-module")
def run_module(
    name: str = typer.Argument(..., help="Module name, e.g. 'discovery'"),
    url: str = typer.Option(None, help="Source URL (required for discovery)"),
    source_id: str = typer.Option(None, help="source_id (for downstream modules)"),
):
    """Run a single module from its persisted input artifact and print its output."""
    ctx = Context()
    if name == "discovery":
        if not url:
            raise typer.BadParameter("discovery needs --url")
        out = pipeline.run_discovery(url, ctx)
        rprint(out.model_dump())
    elif name == "ingest":
        if not source_id:
            raise typer.BadParameter("ingest needs --source-id (run discovery first)")
        src = pipeline.load_source(ctx, source_id)
        repo = pipeline.run_ingest(src, ctx)
        # Summarize — full Repository is large; print the key fields.
        rprint(
            {
                "source_id": repo.source_id,
                "owner": repo.owner,
                "name": repo.name,
                "stars": repo.stars,
                "forks": repo.forks,
                "language": repo.language,
                "topics": repo.topics,
                "readme_chars": len(repo.readme_raw),
                "tree_entries": len(repo.file_tree),
                "releases": len(repo.releases),
                "commits": len(repo.commits_recent),
                "dependency_files": [d.path for d in repo.dependency_files],
            }
        )
    elif name == "parse":
        if not source_id:
            raise typer.BadParameter("parse needs --source-id (run ingest first)")
        repo = pipeline.load_repository(ctx, source_id)
        parsed = pipeline.run_parse(repo, ctx)
        rprint(
            {
                "source_id": parsed.source_id,
                "documents": [
                    {"type": d.type, "title": d.title, "chars": len(d.text)}
                    for d in parsed.documents
                ],
            }
        )
    elif name == "claims":
        if not source_id:
            raise typer.BadParameter("claims needs --source-id (run parse first)")
        parsed = pipeline.load_parsed(ctx, source_id)
        claims = pipeline.run_claims(parsed, ctx)
        rprint(
            {
                "source_id": claims.source_id,
                "count": len(claims.claims),
                "claims": [
                    {"id": c.id, "confidence": c.confidence, "polarity": c.polarity,
                     "evidence": c.evidence, "text": c.text}
                    for c in claims.claims
                ],
            }
        )
    elif name == "signals":
        if not source_id:
            raise typer.BadParameter("signals needs --source-id (run ingest first)")
        repo = pipeline.load_repository(ctx, source_id)
        signals = pipeline.run_signals(repo, ctx)
        rprint(
            {
                "source_id": signals.source_id,
                "count": len(signals.signals),
                "signals": [
                    {"name": s.name, "value": s.value, "unit": s.unit, "period": s.period}
                    for s in signals.signals
                ],
            }
        )
    elif name == "concepts":
        if not source_id:
            raise typer.BadParameter("concepts needs --source-id (run claims first)")
        claims = pipeline.load_claims(ctx, source_id)
        concepts = pipeline.run_concepts(claims, ctx)
        rprint(
            {
                "source_id": concepts.source_id,
                "count": len(concepts.concepts),
                "concepts": [
                    {"id": c.id, "name": c.name, "aliases": c.aliases,
                     "from_claims": c.from_claims}
                    for c in concepts.concepts
                ],
            }
        )
    elif name == "belief_retrieval":
        if not source_id:
            raise typer.BadParameter("belief_retrieval needs --source-id (run concepts first)")
        concepts = pipeline.load_concepts(ctx, source_id)
        related = pipeline.run_belief_retrieval(concepts, ctx)
        rprint(
            {
                "source_id": related.source_id,
                "count": len(related.beliefs),
                "beliefs": [
                    {"id": b.id, "statement": b.statement, "confidence": b.confidence}
                    for b in related.beliefs
                ],
            }
        )
    elif name == "gap":
        if not source_id:
            raise typer.BadParameter("gap needs --source-id")
        concepts = pipeline.load_concepts(ctx, source_id)
        related = pipeline.load_related(ctx, source_id)
        gaps = pipeline.run_gap(concepts, related, ctx)
        rprint(
            {
                "source_id": gaps.source_id,
                "count": len(gaps.gaps),
                "gaps": [
                    {"concept_id": g.concept_id, "kind": g.kind, "question": g.question}
                    for g in gaps.gaps
                ],
            }
        )
    elif name == "retrieval":
        if not source_id:
            raise typer.BadParameter("retrieval needs --source-id")
        gaps = pipeline.load_gaps(ctx, source_id)
        concepts = pipeline.load_concepts(ctx, source_id)
        claims = pipeline.load_claims(ctx, source_id)
        repo = pipeline.load_repository(ctx, source_id)
        retrieved = pipeline.run_retrieval(gaps, concepts, claims, repo, ctx)
        rprint(
            {
                "source_id": retrieved.source_id,
                "count": len(retrieved.items),
                "items": [
                    {"concept_id": it.concept_id, "url": it.source_url, "summary": it.summary}
                    for it in retrieved.items
                ],
            }
        )
    elif name == "evidence":
        if not source_id:
            raise typer.BadParameter("evidence needs --source-id")
        concepts = pipeline.load_concepts(ctx, source_id)
        claims = pipeline.load_claims(ctx, source_id)
        signals = pipeline.load_signals(ctx, source_id)
        related = pipeline.load_related(ctx, source_id)
        retrieved = pipeline.load_retrieved(ctx, source_id)
        packets = pipeline.run_evidence(concepts, claims, signals, related, retrieved, ctx)
        rprint(
            {
                "source_id": packets.source_id,
                "count": len(packets.packets),
                "packets": [
                    {"concept": p.concept_name, "claims": len(p.claims),
                     "signals": len(p.signals), "external": len(p.external),
                     "summary": p.summary}
                    for p in packets.packets
                ],
            }
        )
    elif name == "delta":
        if not source_id:
            raise typer.BadParameter("delta needs --source-id")
        packets = pipeline.load_evidence(ctx, source_id)
        related = pipeline.load_related(ctx, source_id)
        deltas = pipeline.run_delta(packets, related, ctx)
        rprint(
            {
                "source_id": deltas.source_id,
                "count": len(deltas.deltas),
                "deltas": [
                    {"belief_id": d.belief_id, "old": d.old_conf, "delta": d.delta,
                     "new": d.new_conf, "statement": d.statement, "rationale": d.rationale}
                    for d in deltas.deltas
                ],
            }
        )
    elif name == "belief_update":
        if not source_id:
            raise typer.BadParameter("belief_update needs --source-id")
        deltas = pipeline.load_deltas(ctx, source_id)
        update = pipeline.run_belief_update(deltas, ctx)
        rprint(
            {
                "source_id": update.source_id,
                "created": update.created_belief_ids,
                "updated": update.updated_belief_ids,
                "beliefs": [
                    {"id": b.id, "confidence": b.confidence, "trend": b.trend,
                     "history_len": len(b.history), "statement": b.statement}
                    for b in update.beliefs
                ],
            }
        )
    elif name == "user_beliefs":
        user = pipeline.run_user_beliefs(ctx)
        rprint(
            {
                "count": len(user.beliefs),
                "beliefs": [
                    {"statement": b.statement, "confidence": b.confidence}
                    for b in user.beliefs
                ],
            }
        )
    elif name == "narrative":
        if not source_id:
            raise typer.BadParameter("narrative needs --source-id (run belief_update first)")
        update = pipeline.load_update(ctx, source_id)
        user = pipeline.run_user_beliefs(ctx)
        packets = pipeline.load_evidence(ctx, source_id)
        plan = pipeline.run_narrative(update, user, packets, ctx)
        rprint(
            {
                "source_id": plan.source_id,
                "main_belief": plan.main_belief,
                "supporting_beliefs": plan.supporting_beliefs,
                "evidence_points": plan.evidence_points,
                "counterarguments": plan.counterarguments,
                "tone": plan.tone,
                "confidence": plan.confidence,
            }
        )
    elif name == "content":
        if not source_id:
            raise typer.BadParameter("content needs --source-id (run narrative first)")
        plan = pipeline.load_narrative(ctx, source_id)
        content = pipeline.run_content(plan, ctx)
        post_path = ctx.settings.stage_dir("posts") / f"{content.source_id}.md"
        rprint(f"[green]Post[/green] ({content.word_count} words) -> {post_path}\n")
        rprint(content.markdown)
    else:
        raise typer.BadParameter(f"unknown/not-yet-implemented module: {name}")


@app.command(help=SEED_HELP)
def seed(
    manifest: str = typer.Argument(
        ..., help="Path to a manifest file: one source REF per line (blanks and '#' comments skipped)."
    ),
    fresh: bool = typer.Option(False, "--fresh", help="Ignore cached claims/concepts; re-extract"),
):
    from pathlib import Path

    ctx = Context()
    if fresh:
        ctx.settings.use_cache = False
    refs = pipeline.parse_manifest(Path(manifest).read_text(encoding="utf-8"))
    if not refs:
        raise typer.BadParameter(f"No refs found in {manifest}")
    rprint(f"[cyan]Seeding[/cyan] {len(refs)} refs...")
    for ref in refs:
        update = pipeline.seed_one(ref, ctx)
        rprint(
            f"  {ref}: [green]+{len(update.created_belief_ids)}[/green] created, "
            f"{len(update.updated_belief_ids)} updated"
        )
    rprint(f"[green]Seeded[/green] — graph now {len(ctx.beliefs.all())} beliefs")


@app.command()
def rebuild(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
):
    """Wipe and replay the belief graph through the current belief math (Gate F).

    Recomputes every belief from its persisted evidence packets — no re-ingest, no network. Use
    after changing the m11 formula to repersist confidences (e.g. beliefs stuck low before a fix).
    """
    ctx = Context()
    n_before = len(ctx.beliefs.all())
    if not yes:
        typer.confirm(
            f"Rebuild will wipe and replay {n_before} beliefs from persisted evidence. Continue?",
            abort=True,
        )
    replayed, n_after = pipeline.rebuild_graph(ctx)
    rprint(f"[green]rebuilt[/green] {n_after} beliefs from {len(replayed)} replayed sources")


@app.command()
def graph(
    view: str = typer.Option(
        "summary", help="summary | consensus | trends | momentum | pillars | fringe"
    ),
    belief: str = typer.Option(None, help="Show the evidence trail for one belief id (bel_...)"),
    limit: int = typer.Option(12, help="Rows to show"),
):
    """Read the belief graph: what independent sources converge on, what's rising, and why."""
    ctx = Context()
    beliefs = ctx.beliefs.all()
    if belief:
        _graph_provenance(ctx, belief)
        return
    if not beliefs:
        rprint("[yellow]empty belief graph[/yellow] — run `bgis run <url>` first")
        return

    if view in ("summary", "consensus"):
        rprint(f"[bold]CONSENSUS[/bold] — beliefs the most independent sources agree on "
               f"({len(beliefs)} beliefs total)")
        for b in sorted(beliefs, key=lambda b: (_nsrc(b), b.confidence), reverse=True)[:limit]:
            rprint(f"  [cyan]{_nsrc(b)}src[/cyan] c{b.confidence:.2f} ({b.trend}) "
                   f"{b.id} {b.statement[:64]}")
    if view in ("summary", "trends"):
        counts: dict[str, int] = {}
        for b in beliefs:
            counts[b.trend] = counts.get(b.trend, 0) + 1
        rprint(f"\n[bold]TRENDS[/bold] {counts}")
    if view in ("summary", "momentum"):
        rprint("\n[bold]MOMENTUM[/bold] — biggest recent confidence shifts")
        for b in sorted(beliefs, key=_last_delta, reverse=True)[:limit]:
            rprint(f"  [green]+{_last_delta(b):.2f}[/green] -> c{b.confidence:.2f} "
                   f"{b.statement[:60]}")
    if view in ("summary", "pillars"):
        rprint("\n[bold]PILLARS[/bold] — concepts spanning the most sources (shared vocabulary)")
        names = _concept_names(ctx)
        spans: dict[str, set] = {}
        for b in beliefs:
            s = {h.source_id for h in b.history}
            for cid in b.linked_concepts:
                spans.setdefault(cid, set()).update(s)
        ranked = sorted(((len(v), names.get(k, k)) for k, v in spans.items()), reverse=True)
        for n, nm in [r for r in ranked if r[0] > 1][:limit]:
            rprint(f"  [cyan]{n} sources[/cyan] | {nm}")
    if view in ("summary", "fringe"):
        rprint("\n[bold]FRINGE[/bold] — lowest-confidence, single-source (edges, not the center)")
        for b in sorted(beliefs, key=lambda b: b.confidence)[:limit]:
            rprint(f"  c{b.confidence:.2f} {_nsrc(b)}src {b.statement[:64]}")


def _nsrc(b) -> int:
    return len({h.source_id for h in b.history})


def _last_delta(b) -> float:
    return b.history[-1].delta if b.history else 0.0


def _concept_names(ctx) -> dict[str, str]:
    """concept_id -> name, read from persisted concept artifacts."""
    import json

    out: dict[str, str] = {}
    for f in ctx.settings.stage_dir("concepts").glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        for c in d.get("concepts", []):
            out[c["id"]] = c["name"]
    return out


def _graph_provenance(ctx, belief_id: str) -> None:
    """Trace one belief: its evidence trail across sources."""
    b = ctx.beliefs.get(belief_id)
    if b is None:
        rprint(f"[red]no such belief[/red]: {belief_id}")
        return
    rprint(f"[bold]{b.id}[/bold]  c{b.confidence:.2f}  trend={b.trend}  ({_nsrc(b)} sources)")
    rprint(f"  {b.statement}")
    rprint(f"  concepts: {', '.join(b.linked_concepts) or '(none)'}")
    rprint("  evidence trail:")
    for h in b.history:
        ts = getattr(h.ts, "date", lambda: h.ts)()
        rprint(f"    {ts} {h.source_id}: {h.conf_before:.2f} -> {h.conf_after:.2f} "
               f"({h.delta:+.2f}); +{len(h.supporting)} support, -{len(h.contradicting)} contra")


@app.command()
def smoke():
    """Check external dependencies are reachable."""
    ctx = Context()
    ok = True

    # Ollama tags
    import requests

    try:
        r = requests.get(f"{ctx.settings.ollama_base_url}/api/tags", timeout=10)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        rprint(f"[green]ollama up[/green] models={models}")
    except Exception as e:  # noqa: BLE001
        ok = False
        rprint(f"[red]ollama FAIL[/red] {e}")

    # Embedding
    try:
        v = ctx.embedder.embed("hello world")
        rprint(f"[green]embed ok[/green] dim={len(v)}")
    except Exception as e:  # noqa: BLE001
        ok = False
        rprint(f"[red]embed FAIL[/red] {e}")

    # Chroma round-trip
    try:
        v = ctx.embedder.embed("smoke test concept")
        ctx.vectors.add("concepts", "smoke_test", v, {"name": "smoke test concept"})
        hit = ctx.vectors.match("concepts", v, threshold=0.5)
        rprint(f"[green]chroma ok[/green] match={hit[0] if hit else None}")
    except Exception as e:  # noqa: BLE001
        ok = False
        rprint(f"[red]chroma FAIL[/red] {e}")

    # GitHub token
    try:
        from github import Github

        gh = Github(ctx.settings.github_token) if ctx.settings.github_token else Github()
        login = gh.get_user().login if ctx.settings.github_token else "(anonymous)"
        rl = gh.get_rate_limit()
        core = getattr(rl, "core", None) or rl.resources.core
        rprint(f"[green]github ok[/green] user={login} rate_remaining={core.remaining}")
    except Exception as e:  # noqa: BLE001
        ok = False
        rprint(f"[red]github FAIL[/red] {e}")

    raise typer.Exit(code=0 if ok else 1)


if __name__ == "__main__":
    app()
