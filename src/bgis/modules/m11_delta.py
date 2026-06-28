"""Module 11 — Belief Delta Engine.

Convert evidence packets into belief updates. One belief per concept; the belief id is
derived from the concept id, so the same concept (across runs, after dedup) always maps
to the same belief — this is how beliefs accumulate over many sources.

In:  EvidencePackets + RelatedBeliefs
Out: BeliefDeltas{ deltas: [BeliefDelta, ...] }

Deterministic, fully explainable. No store writes here (Module 12 persists). Formula:
  authority        = clamp( log10(stars + 10) / 4 , 0..1 )
  evidence_strength= mean(claim.confidence) * (0.5 + 0.5 * authority)
  cold start       : new = evidence_strength,            old = 0
  existing belief  : new = old + LR * (evidence_strength - old)
  delta            = new - old   (all clamped to [0, 1])
"""

from __future__ import annotations

import math

from ..context import Context
from ..models import (
    BeliefDelta,
    BeliefDeltas,
    EvidencePacket,
    EvidencePackets,
    RelatedBeliefs,
)

LEARNING_RATE = 0.3


def belief_id_for_concept(concept_id: str) -> str:
    """Deterministic concept->belief mapping: concept_<h> -> bel_<h>."""
    suffix = concept_id.split("_", 1)[1] if "_" in concept_id else concept_id
    return f"bel_{suffix}"


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _authority(packet: EvidencePacket) -> float:
    stars = next((s.value for s in packet.signals if s.name == "stars"), 0.0)
    return _clamp(math.log10(stars + 10.0) / 4.0)


def run(inp: EvidencePackets, related: RelatedBeliefs, ctx: Context) -> BeliefDeltas:
    # Index existing beliefs by id so we can detect updates vs cold-start creations.
    existing = {b.id: b for b in related.beliefs}

    deltas: list[BeliefDelta] = []
    for packet in inp.packets:
        if not packet.claims:
            continue

        belief_id = belief_id_for_concept(packet.concept_id)
        mean_conf = sum(c.confidence for c in packet.claims) / len(packet.claims)
        authority = _authority(packet)
        # The source's own claims can only carry a belief up to base_confidence_ceiling; the
        # remaining headroom is reserved for independent external corroboration. This stops the
        # corroboration term from being absorbed by the clamp on already-strong beliefs.
        ceiling = ctx.settings.base_confidence_ceiling
        base_strength = mean_conf * (0.5 + 0.5 * authority) * ceiling
        # External corroboration: independent repos backing this concept lift strength toward 1.0,
        # bounded so external evidence can't dominate the source's own claims.
        corroboration = min(
            ctx.settings.external_corroboration_cap,
            ctx.settings.external_corroboration_weight * len(packet.external),
        )
        evidence_strength = _clamp(base_strength + corroboration)

        prior = existing.get(belief_id)
        old_conf = prior.confidence if prior else 0.0
        if prior is None:
            new_conf = evidence_strength
        else:
            new_conf = old_conf + LEARNING_RATE * (evidence_strength - old_conf)
        new_conf = _clamp(new_conf)
        delta = round(new_conf - old_conf, 6)

        supporting = [c.id for c in packet.claims if c.polarity != "negative"]
        contradicting = [c.id for c in packet.claims if c.polarity == "negative"]

        rationale = [
            f"{len(packet.claims)} claim(s), mean confidence {mean_conf:.3f}",
            f"authority {authority:.3f} from source signals (stars)",
            f"base = {mean_conf:.3f} * (0.5 + 0.5*{authority:.3f}) * ceiling {ceiling:.2f} "
            f"= {base_strength:.3f}",
            f"+ corroboration {corroboration:.3f} ({len(packet.external)} external) "
            f"-> evidence_strength = {evidence_strength:.3f}",
            (
                f"cold start: new = evidence_strength = {new_conf:.3f}"
                if prior is None
                else f"update: new = {old_conf:.3f} + {LEARNING_RATE}*"
                f"({evidence_strength:.3f} - {old_conf:.3f}) = {new_conf:.3f}"
            ),
        ]
        if contradicting:
            rationale.append(f"{len(contradicting)} contradicting claim(s) recorded")

        statement = (
            prior.statement
            if prior
            else _statement_from_packet(packet)
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
                rationale=rationale,
            )
        )

    return BeliefDeltas(source_id=inp.source_id, deltas=deltas)


def _statement_from_packet(packet: EvidencePacket) -> str:
    """Representative belief statement: the highest-confidence claim for the concept."""
    best = max(packet.claims, key=lambda c: c.confidence)
    return best.text
