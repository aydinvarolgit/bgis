"""Pipeline orchestrator.

Runs modules in order, persisting each output to `data/<stage>/<source_id>.json`.
Modules are added to STAGES as they land. The discovery stage is special: its input is
a URL, not a prior on-disk artifact.

This file grows one entry per module. Until a module exists, it is simply absent here.
"""

from __future__ import annotations

from .context import Context
from .models import (
    BeliefDeltas,
    BeliefGraphUpdate,
    Claims,
    Concepts,
    DiscoveryRequest,
    EvidencePackets,
    Gaps,
    GeneratedContent,
    NarrativePlan,
    ParsedDocuments,
    RelatedBeliefs,
    Repository,
    RetrievedEvidence,
    Signals,
    Source,
    UserBeliefs,
)
from .modules import (
    m01_discovery,
    m02_ingest,
    m03_parse,
    m04_claims,
    m05_signals,
    m06_concepts,
    m07_belief_retrieval,
    m08_gap,
    m09_retrieval,
    m10_evidence,
    m11_delta,
    m12_belief_graph,
    m13_user_belief,
    m14_narrative,
    m15_content,
)
from .persistence import artifact_exists, load_artifact, save_artifact
from .sources import resolve

# Ordered stages built so far. Extended as modules land.
STAGE_ORDER = [
    "discovery",
    "ingest",
    "parse",
    "claims",
    "signals",
    "concepts",
    "belief_retrieval",
    "gap",
    "retrieval",
    "evidence",
    "delta",
    "belief_update",
    "user_beliefs",
    "narrative",
    "content",
]


def run_discovery(url: str, ctx: Context) -> Source:
    src = m01_discovery.run(DiscoveryRequest(url=url), ctx)
    save_artifact(ctx.settings, "raw", src.source_id, src)
    return src


def run_ingest(source: Source, ctx: Context) -> Repository:
    repo = m02_ingest.run(source, ctx)
    save_artifact(ctx.settings, "raw", f"{repo.source_id}_repo", repo)
    return repo


def run_parse(repo: Repository, ctx: Context) -> ParsedDocuments:
    parsed = m03_parse.run(repo, ctx)
    save_artifact(ctx.settings, "parsed", parsed.source_id, parsed)
    return parsed


def run_claims(parsed: ParsedDocuments, ctx: Context) -> Claims:
    # Cache: reuse extracted claims for this source so re-runs are reproducible.
    if ctx.settings.use_cache and artifact_exists(ctx.settings, "claims", parsed.source_id):
        return load_artifact(ctx.settings, "claims", parsed.source_id, Claims)
    claims = m04_claims.run(parsed, ctx)
    save_artifact(ctx.settings, "claims", claims.source_id, claims)
    return claims


def run_signals(repo: Repository, ctx: Context) -> Signals:
    signals = m05_signals.run(repo, ctx)
    save_artifact(ctx.settings, "signals", signals.source_id, signals)
    return signals


def run_concepts(claims: Claims, ctx: Context) -> Concepts:
    # Cache: reuse normalized concepts (and their stable ids) for this source. This keeps
    # belief ids fixed across re-runs so beliefs EVOLVE rather than fork. (Skipping m06 also
    # skips re-adding to the Chroma concept collection, which is already populated.)
    if ctx.settings.use_cache and artifact_exists(ctx.settings, "concepts", claims.source_id):
        return load_artifact(ctx.settings, "concepts", claims.source_id, Concepts)
    concepts = m06_concepts.run(claims, ctx)
    save_artifact(ctx.settings, "concepts", concepts.source_id, concepts)
    return concepts


def run_belief_retrieval(concepts: Concepts, ctx: Context) -> RelatedBeliefs:
    related = m07_belief_retrieval.run(concepts, ctx)
    save_artifact(ctx.settings, "beliefs", f"{related.source_id}_related", related)
    return related


def run_gap(concepts: Concepts, related: RelatedBeliefs, ctx: Context) -> Gaps:
    gaps = m08_gap.run(concepts, related, ctx)
    save_artifact(ctx.settings, "beliefs", f"{gaps.source_id}_gaps", gaps)
    return gaps


def run_retrieval(
    gaps: Gaps, concepts: Concepts, claims: Claims, repo: Repository, ctx: Context
) -> RetrievedEvidence:
    retrieved = m09_retrieval.run(gaps, concepts, claims, repo, ctx)
    save_artifact(ctx.settings, "beliefs", f"{retrieved.source_id}_retrieved", retrieved)
    return retrieved


def run_evidence(
    concepts: Concepts,
    claims: Claims,
    signals: Signals,
    related: RelatedBeliefs,
    retrieved: RetrievedEvidence,
    ctx: Context,
) -> EvidencePackets:
    packets = m10_evidence.run(concepts, claims, signals, related, retrieved, ctx)
    save_artifact(ctx.settings, "beliefs", f"{packets.source_id}_evidence", packets)
    return packets


def run_delta(packets: EvidencePackets, related: RelatedBeliefs, ctx: Context) -> BeliefDeltas:
    deltas = m11_delta.run(packets, related, ctx)
    save_artifact(ctx.settings, "beliefs", f"{deltas.source_id}_deltas", deltas)
    return deltas


def run_belief_update(deltas: BeliefDeltas, ctx: Context) -> BeliefGraphUpdate:
    update = m12_belief_graph.run(deltas, ctx)
    save_artifact(ctx.settings, "beliefs", f"{update.source_id}_update", update)
    return update


def run(ref: str, ctx: Context | None = None) -> GeneratedContent:
    """Full BGIS pipeline: a source reference -> LinkedIn post (Modules 1-15).

    `ref` is a GitHub repo URL or a `kind:query` string (e.g. `hn:agent memory`). The
    matching SourcePlugin handles ingestion into ParsedDocuments (+ signals, + repo for
    GitHub); everything after is source-agnostic. The post markdown is also written to
    data/posts/<source_id>.md.
    """
    ctx = ctx or Context()
    ingest = resolve(ref).ingest(ref, ctx)
    parsed, signals, repo = ingest.parsed, ingest.signals, ingest.repo
    claims = run_claims(parsed, ctx)
    concepts = run_concepts(claims, ctx)
    related = run_belief_retrieval(concepts, ctx)
    gaps = run_gap(concepts, related, ctx)
    # Module 9 retrieval is GitHub-native (sibling repos); only run it when we have a repo.
    if repo is not None:
        retrieved = run_retrieval(gaps, concepts, claims, repo, ctx)
    else:
        retrieved = RetrievedEvidence(source_id=parsed.source_id, items=[])
    packets = run_evidence(concepts, claims, signals, related, retrieved, ctx)
    deltas = run_delta(packets, related, ctx)
    update = run_belief_update(deltas, ctx)
    user = run_user_beliefs(ctx)
    narrative = run_narrative(update, user, ctx)
    content = run_content(narrative, ctx)
    return content


def run_user_beliefs(ctx: Context) -> UserBeliefs:
    return m13_user_belief.run(ctx)


def run_narrative(
    update: BeliefGraphUpdate, user: UserBeliefs, ctx: Context
) -> NarrativePlan:
    plan = m14_narrative.run(update, user, ctx)
    save_artifact(ctx.settings, "beliefs", f"{plan.source_id}_narrative", plan)
    return plan


def run_content(plan: NarrativePlan, ctx: Context) -> GeneratedContent:
    content = m15_content.run(plan, ctx)
    save_artifact(ctx.settings, "posts", f"{content.source_id}_content", content)
    return content


def rebuild_graph(ctx: Context) -> tuple[list[str], int]:
    """One-time graph rebuild: wipe the belief store and chronologically replay every source's
    persisted evidence packets through the CURRENT m11 (Gate F formula + corroboration ratchet) +
    m12. This repersists confidences that were computed under an older formula (e.g. beliefs stuck
    low before the ratchet fix) without re-ingesting any source or hitting the network.

    Sources are replayed in evidence-artifact mtime order (their original ingest order) so beliefs
    evolve exactly as they did, but under today's math. Returns (replayed_source_ids, belief_count).
    """
    beliefs_dir = ctx.settings.stage_dir("beliefs")
    # Wipe only the belief store (bel_*.json); pipeline artifacts (*_evidence.json, ...) stay.
    for p in beliefs_dir.glob("bel_*.json"):
        p.unlink()

    suffix = "_evidence.json"
    ev_files = sorted(beliefs_dir.glob(f"*{suffix}"), key=lambda p: p.stat().st_mtime)
    replayed: list[str] = []
    for p in ev_files:
        source_id = p.name[: -len(suffix)]
        packets = load_evidence(ctx, source_id)
        # Pass the current (rebuilding) store as RelatedBeliefs; m11 indexes priors by belief_id.
        related = RelatedBeliefs(source_id=source_id, beliefs=ctx.beliefs.all())
        deltas = m11_delta.run(packets, related, ctx)
        m12_belief_graph.run(deltas, ctx)
        replayed.append(source_id)

    return replayed, len(ctx.beliefs.all())


def load_evidence(ctx: Context, source_id: str) -> EvidencePackets:
    return load_artifact(ctx.settings, "beliefs", f"{source_id}_evidence", EvidencePackets)


def load_deltas(ctx: Context, source_id: str) -> BeliefDeltas:
    return load_artifact(ctx.settings, "beliefs", f"{source_id}_deltas", BeliefDeltas)


def load_update(ctx: Context, source_id: str) -> BeliefGraphUpdate:
    return load_artifact(ctx.settings, "beliefs", f"{source_id}_update", BeliefGraphUpdate)


def load_narrative(ctx: Context, source_id: str) -> NarrativePlan:
    return load_artifact(ctx.settings, "beliefs", f"{source_id}_narrative", NarrativePlan)


def load_source(ctx: Context, source_id: str) -> Source:
    return load_artifact(ctx.settings, "raw", source_id, Source)


def load_repository(ctx: Context, source_id: str) -> Repository:
    return load_artifact(ctx.settings, "raw", f"{source_id}_repo", Repository)


def load_parsed(ctx: Context, source_id: str) -> ParsedDocuments:
    return load_artifact(ctx.settings, "parsed", source_id, ParsedDocuments)


def load_claims(ctx: Context, source_id: str) -> Claims:
    return load_artifact(ctx.settings, "claims", source_id, Claims)


def load_concepts(ctx: Context, source_id: str) -> Concepts:
    return load_artifact(ctx.settings, "concepts", source_id, Concepts)


def load_signals(ctx: Context, source_id: str) -> Signals:
    return load_artifact(ctx.settings, "signals", source_id, Signals)


def load_related(ctx: Context, source_id: str) -> RelatedBeliefs:
    return load_artifact(ctx.settings, "beliefs", f"{source_id}_related", RelatedBeliefs)


def load_gaps(ctx: Context, source_id: str) -> Gaps:
    return load_artifact(ctx.settings, "beliefs", f"{source_id}_gaps", Gaps)


def load_retrieved(ctx: Context, source_id: str) -> RetrievedEvidence:
    return load_artifact(ctx.settings, "beliefs", f"{source_id}_retrieved", RetrievedEvidence)
