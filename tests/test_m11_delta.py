import json
import math
from datetime import datetime, timezone

import pytest

from bgis.models import (
    Belief,
    BeliefHistoryEntry,
    Claim,
    EvidencePacket,
    EvidencePackets,
    RelatedBeliefs,
    RetrievedItem,
    Signal,
)
from bgis.modules import m11_delta


def _write_source(settings, sid, type_):
    """Persist a discovery artifact so m11 can derive the source TYPE for sid."""
    p = settings.stage_dir("raw") / f"{sid}.json"
    p.write_text(json.dumps({"source_id": sid, "type": type_, "url": "x", "status": "ingested"}))


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


def _expected_strength(stars=1200, mean=0.8, ceiling=0.85):
    authority = max(0.0, min(1.0, math.log10(stars + 10.0) / 4.0))
    return mean * (0.5 + 0.5 * authority) * ceiling, authority


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


def test_corroboration_lifts_claims_maxed_belief(ctx):
    # Claims-maxed belief (mean 1.0, huge authority) sits at the ceiling without external...
    claims = [Claim(id="c1", text="x", confidence=1.0, polarity="positive")]
    pkt = EvidencePacket(concept_id="concept_ab12cd34", concept_name="c", claims=claims,
                         signals=[Signal(name="stars", value=10_000_000, unit="count",
                                         source_field="stars")])
    pkts = EvidencePackets(source_id="src_test", packets=[pkt])
    no_ext = m11_delta.run(pkts, RelatedBeliefs(source_id="src_test"), ctx).deltas[0]
    assert no_ext.evidence_strength == pytest.approx(0.85, abs=1e-5)  # ceiling, not 1.0
    # ...and 3 independent external sources lift it to 1.0 (corroboration now visible).
    pkt.external = _external(3)
    with_ext = m11_delta.run(pkts, RelatedBeliefs(source_id="src_test"), ctx).deltas[0]
    assert with_ext.evidence_strength == pytest.approx(1.0, abs=1e-5)


def test_clamp_high_authority(ctx):
    # Huge star count -> authority clamps to 1.0.
    out = m11_delta.run(_packets(stars=10_000_000), RelatedBeliefs(source_id="src_test"), ctx)
    d = out.deltas[0]
    # mean 0.8, authority 1.0, ceiling 0.85 -> strength = 0.8*1.0*0.85 = 0.68
    assert d.evidence_strength == pytest.approx(0.68, abs=1e-5)
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


# --- Gate A: claim typing -------------------------------------------------- #

def _typed_packet(claims):
    pkt = EvidencePacket(
        concept_id="concept_ab12cd34", concept_name="c", claims=claims,
        signals=[Signal(name="stars", value=1200, unit="count", source_field="stars")],
    )
    return EvidencePackets(source_id="src_test", packets=[pkt])


def test_opinions_excluded_from_confidence_and_collected_as_stances(ctx):
    # One fact (0.9) + one opinion (0.2). Confidence must come from the fact ONLY; the opinion
    # is collected as a stance, not averaged in (which would have dragged mean to 0.55).
    claims = [
        Claim(id="c1", text="orchestrates agents", confidence=0.9, type="fact"),
        Claim(id="c2", text="this approach will win", confidence=0.2, type="opinion"),
    ]
    out = m11_delta.run(_typed_packet(claims), RelatedBeliefs(source_id="src_test"), ctx)
    d = out.deltas[0]
    strength, _ = _expected_strength(mean=0.9)
    assert d.evidence_strength == pytest.approx(strength, abs=1e-5)
    assert d.stance_points == ["this approach will win"]
    assert d.supporting == ["c1"]  # opinion not counted as support
    assert d.statement == "orchestrates agents"  # fact preferred over opinion as statement


def test_finding_weight_applied(ctx):
    ctx.settings.finding_weight = 0.5
    claims = [Claim(id="c1", text="2x faster", confidence=0.8, type="finding")]
    out = m11_delta.run(_typed_packet(claims), RelatedBeliefs(source_id="src_test"), ctx)
    # effective mean = 0.8 * 0.5 = 0.4
    strength, _ = _expected_strength(mean=0.4)
    assert out.deltas[0].evidence_strength == pytest.approx(strength, abs=1e-5)


def test_pure_opinion_cold_start_uses_floor(ctx):
    claims = [Claim(id="c1", text="agents are overhyped", confidence=0.9, type="opinion")]
    out = m11_delta.run(_typed_packet(claims), RelatedBeliefs(source_id="src_test"), ctx)
    d = out.deltas[0]
    assert d.new_conf == pytest.approx(ctx.settings.pure_opinion_confidence, abs=1e-9)  # 0.3
    assert d.stance_points == ["agents are overhyped"]
    assert d.statement == "agents are overhyped"


def test_supporting_low_authority_source_does_not_lower_belief(ctx):
    # Established belief at 0.87; a low-authority supporting source (no stars -> authority 0.25)
    # yields a weak evidence_strength. It must HOLD the belief, not drag it down.
    prior = Belief(id="bel_ab12cd34", statement="established", confidence=0.87,
                   linked_concepts=["concept_ab12cd34"])
    related = RelatedBeliefs(source_id="src_test", beliefs=[prior])
    claims = [Claim(id="c1", text="agrees", confidence=0.8, type="finding")]
    pkt = EvidencePacket(concept_id="concept_ab12cd34", concept_name="c", claims=claims,
                         signals=[])  # no stars -> low authority
    out = m11_delta.run(EvidencePackets(source_id="src_test", packets=[pkt]), related, ctx)
    d = out.deltas[0]
    assert d.new_conf == 0.87  # held, not lowered
    assert d.delta == 0.0
    assert any("ratchet" in r for r in d.rationale)


def test_stronger_supporting_source_still_raises(ctx):
    # Ratchet must not block legitimate upward moves.
    prior = Belief(id="bel_ab12cd34", statement="s", confidence=0.5,
                   linked_concepts=["concept_ab12cd34"])
    related = RelatedBeliefs(source_id="src_test", beliefs=[prior])
    out = m11_delta.run(_packets(stars=1200), related, ctx)  # strength ~0.68 > 0.5
    d = out.deltas[0]
    assert d.new_conf > 0.5


def test_contradiction_can_still_lower_belief(ctx):
    # A contradicting (negative-polarity) source IS allowed to move confidence down.
    prior = Belief(id="bel_ab12cd34", statement="s", confidence=0.9,
                   linked_concepts=["concept_ab12cd34"])
    related = RelatedBeliefs(source_id="src_test", beliefs=[prior])
    claims = [Claim(id="c1", text="fails", confidence=0.3, type="fact", polarity="negative")]
    pkt = EvidencePacket(concept_id="concept_ab12cd34", concept_name="c", claims=claims,
                         signals=[Signal(name="stars", value=10, source_field="stars")])
    out = m11_delta.run(EvidencePackets(source_id="src_test", packets=[pkt]), related, ctx)
    d = out.deltas[0]
    assert d.new_conf < 0.9  # contradiction lowers
    assert d.contradicting == ["c1"]


def test_pure_opinion_does_not_move_existing_belief(ctx):
    prior = Belief(id="bel_ab12cd34", statement="established fact", confidence=0.88,
                   linked_concepts=["concept_ab12cd34"])
    related = RelatedBeliefs(source_id="src_test", beliefs=[prior])
    claims = [Claim(id="c1", text="but is it sustainable?", confidence=0.9, type="opinion")]
    out = m11_delta.run(_typed_packet(claims), related, ctx)
    d = out.deltas[0]
    assert d.new_conf == 0.88  # unchanged — opinions never move confidence
    assert d.delta == 0.0
    assert d.stance_points == ["but is it sustainable?"]


# --- Gate F: richer delta (recency + source diversity + source-TYPE weighting) ------------ #

def test_non_repo_source_uses_type_authority_baseline(ctx):
    # An arXiv source has no `stars` signal -> authority comes from the per-TYPE baseline (0.7),
    # not the old flat 0.25. A paper now outweighs a random no-stars source.
    _write_source(ctx.settings, "src_arx", "arxiv")
    claims = [Claim(id="c1", text="empirical result", confidence=0.8, type="finding")]
    pkt = EvidencePacket(concept_id="concept_ab12cd34", concept_name="c", claims=claims, signals=[])
    out = m11_delta.run(EvidencePackets(source_id="src_arx", packets=[pkt]),
                        RelatedBeliefs(source_id="src_arx"), ctx)
    expected = 0.8 * (0.5 + 0.5 * 0.7) * 0.85  # authority 0.7, no diversity/recency/external
    assert out.deltas[0].evidence_strength == pytest.approx(expected, abs=1e-5)


def test_unknown_source_type_keeps_old_flat_authority(ctx):
    # No raw artifact for the source id -> type unknown -> 0.25 baseline (== legacy behavior).
    claims = [Claim(id="c1", text="x", confidence=0.8, type="finding")]
    pkt = EvidencePacket(concept_id="concept_ab12cd34", concept_name="c", claims=claims, signals=[])
    out = m11_delta.run(EvidencePackets(source_id="src_unknown", packets=[pkt]),
                        RelatedBeliefs(source_id="src_unknown"), ctx)
    expected = 0.8 * (0.5 + 0.5 * 0.25) * 0.85
    assert out.deltas[0].evidence_strength == pytest.approx(expected, abs=1e-5)


def test_recency_bonus_from_fresh_push(ctx):
    _write_source(ctx.settings, "src_gh", "github")
    claims = [Claim(id="c1", text="x", confidence=0.8, type="fact")]
    pkt = EvidencePacket(
        concept_id="concept_ab12cd34", concept_name="c", claims=claims,
        signals=[Signal(name="stars", value=1200, source_field="stars"),
                 Signal(name="days_since_push", value=10, source_field="pushed_at")],
    )
    out = m11_delta.run(EvidencePackets(source_id="src_gh", packets=[pkt]),
                        RelatedBeliefs(source_id="src_gh"), ctx)
    base, _ = _expected_strength(mean=0.8)  # stars 1200
    # days_since_push 10 <= recency_full_days 30 -> term 1.0 -> +recency_weight 0.05
    assert out.deltas[0].evidence_strength == pytest.approx(base + 0.05, abs=1e-5)


def test_recency_decays_linearly(ctx):
    _write_source(ctx.settings, "src_gh", "github")
    claims = [Claim(id="c1", text="x", confidence=0.8, type="fact")]
    midpoint = (30.0 + 365.0) / 2  # term = 0.5
    pkt = EvidencePacket(
        concept_id="concept_ab12cd34", concept_name="c", claims=claims,
        signals=[Signal(name="stars", value=1200, source_field="stars"),
                 Signal(name="days_since_push", value=midpoint, source_field="pushed_at")],
    )
    out = m11_delta.run(EvidencePackets(source_id="src_gh", packets=[pkt]),
                        RelatedBeliefs(source_id="src_gh"), ctx)
    base, _ = _expected_strength(mean=0.8)
    assert out.deltas[0].evidence_strength == pytest.approx(base + 0.05 * 0.5, abs=1e-5)


def test_cross_source_type_diversity_raises_belief(ctx):
    # The Part B-2 thesis: a belief first built from a GitHub repo, now corroborated by an arXiv
    # paper, gains a diversity bonus (2 distinct source TYPES) that MOVES confidence up — beyond
    # what the single low-authority paper's claims alone would have reached.
    _write_source(ctx.settings, "src_gh", "github")
    _write_source(ctx.settings, "src_arx", "arxiv")
    prior = Belief(
        id="bel_ab12cd34", statement="s", confidence=0.6, linked_concepts=["concept_ab12cd34"],
        history=[BeliefHistoryEntry(ts=datetime.now(timezone.utc), conf_before=0.0,
                                    conf_after=0.6, delta=0.6, source_id="src_gh")],
    )
    related = RelatedBeliefs(source_id="src_arx", beliefs=[prior])
    claims = [Claim(id="c1", text="agrees", confidence=0.8, type="finding")]
    pkt = EvidencePacket(concept_id="concept_ab12cd34", concept_name="c", claims=claims, signals=[])
    out = m11_delta.run(EvidencePackets(source_id="src_arx", packets=[pkt]), related, ctx)
    d = out.deltas[0]
    base = 0.8 * (0.5 + 0.5 * 0.7) * 0.85  # arxiv authority 0.7
    assert d.evidence_strength == pytest.approx(base + 0.05, abs=1e-5)  # +diversity (2 types)
    assert d.new_conf > 0.6  # moved up
    assert any("2 source type(s)" in r for r in d.rationale)


def test_single_source_type_gives_no_diversity_bonus(ctx):
    # Same GitHub type on both prior history and current run -> 1 distinct type -> no bonus.
    _write_source(ctx.settings, "src_gh", "github")
    _write_source(ctx.settings, "src_gh2", "github")
    prior = Belief(
        id="bel_ab12cd34", statement="s", confidence=0.5, linked_concepts=["concept_ab12cd34"],
        history=[BeliefHistoryEntry(ts=datetime.now(timezone.utc), conf_before=0.0,
                                    conf_after=0.5, delta=0.5, source_id="src_gh")],
    )
    related = RelatedBeliefs(source_id="src_gh2", beliefs=[prior])
    pkts = _packets()  # has stars signal
    pkts.source_id = "src_gh2"
    out = m11_delta.run(pkts, related, ctx)
    base, _ = _expected_strength()
    assert out.deltas[0].evidence_strength == pytest.approx(base, abs=1e-5)  # no diversity bonus
