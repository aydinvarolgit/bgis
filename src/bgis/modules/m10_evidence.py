"""Module 10 — Evidence Packet Builder.

Group the source's evidence by concept into the packets the Belief Delta Engine
consumes. One packet per concept: the claims that produced it, the source-level signals
(authority/momentum), any external evidence (empty in MVP), and a short summary.

In:  Concepts + Claims + Signals + RelatedBeliefs + RetrievedEvidence
Out: EvidencePackets{ packets: [EvidencePacket, ...] }

Deterministic. This is a real builder (not a stub): it is what Module 11 reads.
Signals are source-wide, so the same signal list is attached to every packet — belief
authority is a property of the source, not of an individual concept.
"""

from __future__ import annotations

from ..context import Context
from ..models import (
    Claims,
    Concepts,
    EvidencePacket,
    EvidencePackets,
    RelatedBeliefs,
    RetrievedEvidence,
    Signals,
)


def run(
    concepts: Concepts,
    claims: Claims,
    signals: Signals,
    related: RelatedBeliefs,
    retrieved: RetrievedEvidence,
    ctx: Context,
) -> EvidencePackets:
    claim_by_id = {c.id: c for c in claims.claims}

    packets: list[EvidencePacket] = []
    for concept in concepts.concepts:
        pkt_claims = [claim_by_id[cid] for cid in concept.from_claims if cid in claim_by_id]
        if not pkt_claims:
            continue
        packets.append(
            EvidencePacket(
                concept_id=concept.id,
                concept_name=concept.name,
                claims=pkt_claims,
                signals=signals.signals,  # source-wide authority/momentum signals
                external=list(retrieved.items),  # empty in MVP
                summary=_summary(concept.name, pkt_claims, signals),
            )
        )

    return EvidencePackets(source_id=concepts.source_id, packets=packets)


def _summary(concept_name: str, pkt_claims, signals: Signals) -> str:
    avg_conf = sum(c.confidence for c in pkt_claims) / len(pkt_claims)
    stars = next((s.value for s in signals.signals if s.name == "stars"), 0.0)
    return (
        f"Concept '{concept_name}' supported by {len(pkt_claims)} claim(s) "
        f"(avg confidence {avg_conf:.2f}); source authority ~{int(stars)} stars."
    )
