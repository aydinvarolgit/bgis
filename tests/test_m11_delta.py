import math

import pytest

from bgis.models import (
    Belief,
    Claim,
    EvidencePacket,
    EvidencePackets,
    RelatedBeliefs,
    RetrievedItem,
    Signal,
)
from bgis.modules import m11_delta


def _external(n):
    return [
        RetrievedItem(concept_id="concept_ab12cd34", question="q",
                      source_url=f"https://github.com/o/r{i}", summary=f"r{i}")
        for i in range(n)
    ]


def _packets(stars=1200, polarities=("positive", "positive")):
    claims = [
        Claim(id="c1", text="orchestrates agents", confidence=0.9, polarity=polarities[0]),
        Claim(id="c2", text="coordination matters", confidence=0.7, polarity=polarities[1]),
    ]
    pkt = EvidencePacket(
        concept_id="concept_ab12cd34",
        concept_name="orchestration",
        claims=claims,
        signals=[Signal(name="stars", value=stars, unit="count", source_field="stars")],
    )
    return EvidencePackets(source_id="src_test", packets=[pkt])


def _expected_strength(stars=1200, mean=0.8):
    authority = max(0.0, min(1.0, math.log10(stars + 10.0) / 4.0))
    return mean * (0.5 + 0.5 * authority), authority


def test_belief_id_mapping():
    assert m11_delta.belief_id_for_concept("concept_ab12cd34") == "bel_ab12cd34"


def test_cold_start(ctx):
    out = m11_delta.run(_packets(), RelatedBeliefs(source_id="src_test"), ctx)
    d = out.deltas[0]
    strength, _ = _expected_strength()
    assert d.belief_id == "bel_ab12cd34"
    assert d.old_conf == 0.0
    assert d.new_conf == pytest.approx(strength, abs=1e-5)
    assert d.delta == pytest.approx(strength, abs=1e-5)
    assert d.evidence_strength == pytest.approx(strength, abs=1e-5)
    assert d.statement == "orchestrates agents"  # highest-confidence claim
    assert d.supporting == ["c1", "c2"]


def test_update_moves_toward_evidence(ctx):
    prior = Belief(id="bel_ab12cd34", statement="old stmt", confidence=0.5,
                   linked_concepts=["concept_ab12cd34"])
    related = RelatedBeliefs(source_id="src_test", beliefs=[prior])
    out = m11_delta.run(_packets(), related, ctx)
    d = out.deltas[0]
    strength, _ = _expected_strength()
    expected_new = 0.5 + 0.3 * (strength - 0.5)
    assert d.old_conf == 0.5
    assert d.new_conf == pytest.approx(expected_new, abs=1e-5)
    assert d.delta == pytest.approx(expected_new - 0.5, abs=1e-5)
    assert d.statement == "old stmt"  # keeps existing belief statement


def test_external_corroboration_raises_strength(ctx):
    base, _ = _expected_strength()
    pkts = _packets()
    pkts.packets[0].external = _external(2)  # 2 * 0.05 = 0.10 corroboration
    out = m11_delta.run(pkts, RelatedBeliefs(source_id="src_test"), ctx)
    d = out.deltas[0]
    assert d.evidence_strength == pytest.approx(min(1.0, base + 0.10), abs=1e-5)


def test_external_corroboration_capped(ctx):
    base, _ = _expected_strength()
    pkts = _packets()
    pkts.packets[0].external = _external(10)  # 10*0.05=0.50 -> capped at 0.15
    out = m11_delta.run(pkts, RelatedBeliefs(source_id="src_test"), ctx)
    d = out.deltas[0]
    assert d.evidence_strength == pytest.approx(min(1.0, base + 0.15), abs=1e-5)


def test_clamp_high_authority(ctx):
    # Huge star count -> authority clamps to 1.0.
    out = m11_delta.run(_packets(stars=10_000_000), RelatedBeliefs(source_id="src_test"), ctx)
    d = out.deltas[0]
    # mean 0.8, authority 1.0 -> strength = 0.8*1.0 = 0.8
    assert d.evidence_strength == pytest.approx(0.8, abs=1e-5)
    assert 0.0 <= d.new_conf <= 1.0


def test_contradiction_recorded(ctx):
    out = m11_delta.run(
        _packets(polarities=("positive", "negative")),
        RelatedBeliefs(source_id="src_test"), ctx,
    )
    d = out.deltas[0]
    assert d.supporting == ["c1"]
    assert d.contradicting == ["c2"]
    assert any("contradicting" in r for r in d.rationale)
