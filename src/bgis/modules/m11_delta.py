"""Module 11 — Belief Delta Engine.

Convert evidence packets into belief updates. One belief per concept; the belief id is
derived from the concept id, so the same concept (across runs, after dedup) always maps
to the same belief — this is how beliefs accumulate over many sources.

In:  EvidencePackets + RelatedBeliefs
Out: BeliefDeltas{ deltas: [BeliefDelta, ...] }

Deterministic, fully explainable. No store writes here (Module 12 persists). Formula:
  authority        = clamp( log10(stars + 10) / 4 , 0..1 )   (no stars -> source-TYPE baseline)
  effective_conf   = claim.confidence * type_weight[claim.type]   (opinion weight 0 -> excluded)
  base_strength    = mean(effective_conf over fact+finding) * (0.5 + 0.5 * authority) * ceiling
  evidence_strength= clamp( base_strength + corroboration )
  cold start       : new = evidence_strength,            old = 0
  existing belief  : new = old + LR * (evidence_strength - old)
  delta            = new - old   (all clamped to [0, 1])

Gate F — richer corroboration. The reserved headroom (1 - ceiling) above the claims-only ceiling
is filled by a COMPOSITE bonus, summed then capped at the headroom:
  external_bonus   = min(ext_cap,  ext_weight  * n_external)            (independent m09 siblings)
  diversity_bonus  = div_weight * (n_distinct_source_types - 1)         (repo+paper+discourse agree)
  recency_bonus    = rec_weight * recency_term(days_since_push)         (fresh evidence)
  corroboration    = min(headroom, external_bonus + diversity_bonus + recency_bonus)
This completes the Part B-2 thesis: cross-source-TYPE agreement actually MOVES confidence past what
a single source type could reach. Source TYPE per source_id is derived from data/raw/<sid>.json.

Corroboration ratchet: for an existing belief, SUPPORTING evidence never lowers confidence —
if a weaker but still-agreeing source (e.g. low-authority discourse with no stars) yields an
evidence_strength below the prior, the belief HOLDS rather than regressing. Only CONTRADICTION
(negative-polarity claims) can move confidence down. This keeps cross-source agreement monotone:
adding an arXiv paper or HN thread that corroborates a repo belief can only hold or raise it.

Claim typing (Gate A): only FACT and FINDING claims build a belief's confidence; OPINION claims
never move it. Opinions are collected as `stance_points` (their texts) so m14 can argue them. A
concept backed ONLY by opinions still creates a belief — at a low floor (pure_opinion_confidence)
on cold start, or with confidence untouched on an existing belief — carrying just its stances.
"""

from __future__ import annotations

import json
import math

from ..context import Context
from ..models import (
    Belief,
    BeliefDelta,
    BeliefDeltas,
    EvidencePacket,
    EvidencePackets,
    RelatedBeliefs,
)
from ..config import Settings

LEARNING_RATE = 0.3


def belief_id_for_concept(concept_id: str) -> str:
    """Deterministic concept->belief mapping: concept_<h> -> bel_<h>."""
    suffix = concept_id.split("_", 1)[1] if "_" in concept_id else concept_id
    return f"bel_{suffix}"


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def source_kind(source_id: str, settings: Settings) -> str | None:
    """The SOURCE TYPE for a source_id, read from its discovery artifact data/raw/<sid>.json.

    Returns None when the artifact is missing or unreadable (e.g. synthetic test ids) — callers
    treat an unknown type as "doesn't contribute to diversity / falls back to baseline authority".
    """
    p = settings.stage_dir("raw") / f"{source_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("type")
    except (ValueError, OSError):
        return None


def _authority(packet: EvidencePacket, source_type: str | None, settings: Settings) -> float:
    """Repo authority from stars (log scale); non-repo sources use a per-TYPE baseline."""
    stars_sig = next((s for s in packet.signals if s.name == "stars"), None)
    if stars_sig is not None:
        return _clamp(math.log10(stars_sig.value + 10.0) / 4.0)
    return settings.source_type_authority.get(source_type or "", 0.25)


def _recency_term(packet: EvidencePacket, settings: Settings) -> float:
    """0..1 freshness from the days_since_push signal: full within recency_full_days, linearly
    decaying to 0 at recency_zero_days. Absent signal -> 0 (neutral, never a penalty)."""
    days = next((s.value for s in packet.signals if s.name == "days_since_push"), None)
    if days is None:
        return 0.0
    full, zero = settings.recency_full_days, settings.recency_zero_days
    if days <= full:
        return 1.0
    if days >= zero or zero <= full:
        return 0.0
    return (zero - days) / (zero - full)


def _distinct_source_types(prior: Belief | None, current_type: str | None,
                           settings: Settings) -> set[str]:
    """Distinct known SOURCE TYPES that have contributed to this belief: the current run's type
    plus the type of every source_id in the belief's history. Drives the diversity bonus."""
    types: set[str] = set()
    if current_type:
        types.add(current_type)
    if prior is not None:
        for entry in prior.history:
            t = source_kind(entry.source_id, settings)
            if t:
                types.add(t)
    return types


def run(inp: EvidencePackets, related: RelatedBeliefs, ctx: Context) -> BeliefDeltas:
    # Index existing beliefs by id so we can detect updates vs cold-start creations.
    existing = {b.id: b for b in related.beliefs}
    settings = ctx.settings

    type_weight = {"fact": 1.0, "finding": settings.finding_weight, "opinion": 0.0}
    current_type = source_kind(inp.source_id, settings)
    headroom = 1.0 - settings.base_confidence_ceiling

    deltas: list[BeliefDelta] = []
    for packet in inp.packets:
        if not packet.claims:
            continue

        belief_id = belief_id_for_concept(packet.concept_id)
        prior = existing.get(belief_id)
        old_conf = prior.confidence if prior else 0.0

        # Only facts + findings build confidence; opinions are excluded and kept as stances.
        confidence_claims = [c for c in packet.claims if c.type != "opinion"]
        stance_points = [c.text for c in packet.claims if c.type == "opinion"]
        supporting = [c.id for c in confidence_claims if c.polarity != "negative"]
        contradicting = [c.id for c in confidence_claims if c.polarity == "negative"]
        authority = _authority(packet, current_type, settings)
        ceiling = settings.base_confidence_ceiling

        # Composite corroboration filling the reserved headroom above the claims-only ceiling.
        external_bonus = min(
            settings.external_corroboration_cap,
            settings.external_corroboration_weight * len(packet.external),
        )
        source_types = _distinct_source_types(prior, current_type, settings)
        diversity_bonus = settings.source_diversity_weight * max(0, len(source_types) - 1)
        recency_bonus = settings.recency_weight * _recency_term(packet, settings)
        corroboration = min(headroom, external_bonus + diversity_bonus + recency_bonus)

        if confidence_claims:
            # effective_conf weights each claim by its type; mean over fact+finding only.
            effective = [c.confidence * type_weight[c.type] for c in confidence_claims]
            mean_conf = sum(effective) / len(effective)
            # The source's own claims can only carry a belief up to base_confidence_ceiling; the
            # remaining headroom is reserved for independent external corroboration. This stops the
            # corroboration term from being absorbed by the clamp on already-strong beliefs.
            base_strength = mean_conf * (0.5 + 0.5 * authority) * ceiling
            evidence_strength = _clamp(base_strength + corroboration)
            if prior is None:
                new_conf = evidence_strength
                update_note = f"cold start: new = evidence_strength = {_clamp(new_conf):.3f}"
            else:
                # Ratchet: SUPPORTING evidence never lowers an established belief — a weaker but
                # still-agreeing source (e.g. low-authority discourse with no stars) holds the line
                # rather than dragging it down. Only CONTRADICTION (negative-polarity claims) can
                # move confidence below the prior. This keeps cross-source corroboration monotone.
                step = LEARNING_RATE * (evidence_strength - old_conf)
                if contradicting or step >= 0:
                    new_conf = old_conf + step
                    update_note = (
                        f"update: new = {old_conf:.3f} + {LEARNING_RATE}*"
                        f"({evidence_strength:.3f} - {old_conf:.3f}) = {_clamp(new_conf):.3f}"
                    )
                else:
                    new_conf = old_conf  # supporting-only & weaker -> hold (no regression)
                    update_note = (
                        f"ratchet: supporting evidence_strength {evidence_strength:.3f} < prior "
                        f"{old_conf:.3f} and no contradiction -> held at {old_conf:.3f}"
                    )
            authority_src = "stars" if any(s.name == "stars" for s in packet.signals) \
                else f"{current_type or 'unknown'}-type baseline"
            rationale = [
                f"{len(confidence_claims)} fact/finding claim(s), mean effective confidence "
                f"{mean_conf:.3f}",
                f"authority {authority:.3f} from {authority_src}",
                f"base = {mean_conf:.3f} * (0.5 + 0.5*{authority:.3f}) * ceiling {ceiling:.2f} "
                f"= {base_strength:.3f}",
                f"corroboration {corroboration:.3f} = min(headroom {headroom:.2f}, external "
                f"{external_bonus:.3f} [{len(packet.external)} ext] + diversity {diversity_bonus:.3f} "
                f"[{len(source_types)} source type(s): {','.join(sorted(source_types)) or 'none'}] "
                f"+ recency {recency_bonus:.3f})",
                f"evidence_strength = base + corroboration = {evidence_strength:.3f}",
                update_note,
            ]
        else:
            # Pure-opinion concept: opinions never move confidence. New belief -> low floor;
            # existing belief -> confidence untouched. Either way it carries its stances.
            if not stance_points:
                continue
            if prior is None:
                evidence_strength = ctx.settings.pure_opinion_confidence
                new_conf = evidence_strength
                rationale = [
                    "opinion-only concept (no fact/finding claims)",
                    f"cold start: new = pure_opinion_confidence floor = {new_conf:.3f}",
                ]
            else:
                evidence_strength = old_conf
                new_conf = old_conf
                rationale = [
                    "opinion-only concept (no fact/finding claims)",
                    f"existing belief: confidence unchanged at {old_conf:.3f}; stances appended",
                ]

        new_conf = _clamp(new_conf)
        delta = round(new_conf - old_conf, 6)

        if contradicting:
            rationale.append(f"{len(contradicting)} contradicting claim(s) recorded")
        if stance_points:
            rationale.append(f"{len(stance_points)} opinion stance(s) collected")

        # Prefer a fact/finding claim as the belief statement; fall back to opinions if that's all.
        statement = (
            prior.statement
            if prior
            else _statement_from_claims(confidence_claims or packet.claims)
        )

        deltas.append(
            BeliefDelta(
                belief_id=belief_id,
                statement=statement,
                linked_concepts=[packet.concept_id],
                old_conf=round(old_conf, 6),
                evidence_strength=round(evidence_strength, 6),
                delta=delta,
                new_conf=round(new_conf, 6),
                supporting=supporting,
                contradicting=contradicting,
                stance_points=stance_points,
                rationale=rationale,
            )
        )

    return BeliefDeltas(source_id=inp.source_id, deltas=deltas)


def _statement_from_claims(claims) -> str:
    """Representative belief statement: the highest-confidence claim among the candidates."""
    best = max(claims, key=lambda c: c.confidence)
    return best.text
