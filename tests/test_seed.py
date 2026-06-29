"""Seed cold-start: origin provenance, registry, m14 lead-exclusion, rebuild re-tag."""

import json

from bgis.models import (
    Belief,
    BeliefDelta,
    BeliefDeltas,
    BeliefGraphUpdate,
    BeliefHistoryEntry,
    Claim,
    EvidencePacket,
    EvidencePackets,
)
from bgis.modules import m11_delta, m12_belief_graph, m14_narrative
from bgis import pipeline
from bgis.persistence import save_artifact


# --------------------------------------------------------------------------- #
# parse_manifest
# --------------------------------------------------------------------------- #


def test_parse_manifest_skips_blanks_and_comments():
    text = "\n".join(
        [
            "# a comment",
            "https://github.com/o/r1",
            "   ",
            "hn:agent memory   ",
            "",
            "# trailing comment",
            "arxiv:retrieval",
        ]
    )
    assert pipeline.parse_manifest(text) == [
        "https://github.com/o/r1",
        "hn:agent memory",
        "arxiv:retrieval",
    ]


# --------------------------------------------------------------------------- #
# seed registry
# --------------------------------------------------------------------------- #


def test_registry_absent_is_empty(ctx):
    assert pipeline.load_seed_sources(ctx) == set()


def test_registry_add_idempotent_and_persists(ctx):
    pipeline.add_seed_source(ctx, "src_A")
    pipeline.add_seed_source(ctx, "src_A")  # dup is a no-op
    pipeline.add_seed_source(ctx, "src_B")
    assert pipeline.load_seed_sources(ctx) == {"src_A", "src_B"}
    # Survives a fresh read from disk.
    on_disk = json.loads(pipeline.seed_sources_path(ctx).read_text())
    assert sorted(on_disk) == ["src_A", "src_B"]


# --------------------------------------------------------------------------- #
# m12 origin stamp
# --------------------------------------------------------------------------- #


def _deltas(source_id, belief_id, old, new):
    return BeliefDeltas(
        source_id=source_id,
        deltas=[
            BeliefDelta(
                belief_id=belief_id, statement="s", linked_concepts=["concept_x"],
                old_conf=old, evidence_strength=new, delta=round(new - old, 6),
                new_conf=new, supporting=["c1"], rationale=["r"],
            )
        ],
    )


def test_m12_stamps_seed_when_registered(ctx):
    pipeline.add_seed_source(ctx, "src_seed")
    m12_belief_graph.run(_deltas("src_seed", "bel_s", 0.0, 0.6), ctx)
    assert ctx.beliefs.get("bel_s").origin == "seed"


def test_m12_default_source_when_not_registered(ctx):
    m12_belief_graph.run(_deltas("src_real", "bel_r", 0.0, 0.6), ctx)
    assert ctx.beliefs.get("bel_r").origin == "source"


def test_m12_origin_immutable_on_update(ctx):
    # Seed belief created, then a real (non-seed) source corroborates -> origin stays seed.
    pipeline.add_seed_source(ctx, "src_seed")
    m12_belief_graph.run(_deltas("src_seed", "bel_s", 0.0, 0.6), ctx)
    m12_belief_graph.run(_deltas("src_real", "bel_s", 0.6, 0.7), ctx)
    b = ctx.beliefs.get("bel_s")
    assert b.origin == "seed"  # never cleared
    assert len(b.history) == 2

    # A "source" belief is never flipped to seed by a later seed run touching it.
    m12_belief_graph.run(_deltas("src_real", "bel_r", 0.0, 0.6), ctx)
    pipeline.add_seed_source(ctx, "src_seed2")
    m12_belief_graph.run(_deltas("src_seed2", "bel_r", 0.6, 0.7), ctx)
    assert ctx.beliefs.get("bel_r").origin == "source"


# --------------------------------------------------------------------------- #
# m14 lead-exclusion
# --------------------------------------------------------------------------- #


def _belief(bid, statement, origin, source_ids=("s1",)):
    return Belief(
        id=bid, statement=statement, confidence=0.8, origin=origin,
        linked_concepts=["concept_x"],
        history=[
            BeliefHistoryEntry(
                ts="2026-01-01T00:00:00+00:00", conf_before=0.0, conf_after=0.8,
                delta=0.8, source_id=sid,
            )
            for sid in source_ids
        ],
    )


def test_m14_seed_belief_excluded_from_lead(ctx):
    seed_b = _belief("bel_seed", "seed worldview claim", "seed")
    real_b = _belief("bel_real", "live source claim", "source")
    # Belief ids must match the concept->belief mapping so _source_lines routes claims to them.
    seed_b.id = m11_delta.belief_id_for_concept("concept_seed")
    real_b.id = m11_delta.belief_id_for_concept("concept_real")
    update = BeliefGraphUpdate(
        source_id="src_live",
        created_belief_ids=[real_b.id],
        updated_belief_ids=[seed_b.id],
        beliefs=[seed_b, real_b],
    )
    # Both concepts carry a fact claim so both COULD lead if not for the origin gate.
    packets = EvidencePackets(
        source_id="src_live",
        packets=[
            EvidencePacket(concept_id="concept_real", concept_name="r",
                           claims=[Claim(id="c1", text="live fact", confidence=0.9)]),
            EvidencePacket(concept_id="concept_seed", concept_name="s",
                           claims=[Claim(id="c2", text="seed fact", confidence=0.95)]),
        ],
    )

    lead = m14_narrative._source_lines(update, packets)
    corro = m14_narrative._corroboration_lines(update)
    assert "live fact" in lead
    assert "seed fact" not in lead  # seed belief never leads
    assert "seed worldview claim" in corro  # but appears as corroboration


# --------------------------------------------------------------------------- #
# rebuild re-tag
# --------------------------------------------------------------------------- #


def _write_raw(ctx, sid, type_="github"):
    p = ctx.settings.stage_dir("raw") / f"{sid}.json"
    p.write_text(json.dumps({"source_id": sid, "type": type_, "url": "x", "status": "ingested"}))


def _save_evidence(ctx, sid, concept_id):
    packets = EvidencePackets(
        source_id=sid,
        packets=[
            EvidencePacket(
                concept_id=concept_id, concept_name="c",
                claims=[Claim(id="c1", text="a fact", confidence=0.9, polarity="positive")],
            )
        ],
    )
    save_artifact(ctx.settings, "beliefs", f"{sid}_evidence", packets)


def test_rebuild_retags_seed_origin(ctx):
    # One seed source + one real source, each creating a distinct belief via persisted evidence.
    _write_raw(ctx, "src_seed")
    _write_raw(ctx, "src_real")
    _save_evidence(ctx, "src_seed", "concept_seed01")
    _save_evidence(ctx, "src_real", "concept_real01")
    pipeline.add_seed_source(ctx, "src_seed")

    pipeline.rebuild_graph(ctx)

    seed_bid = m11_delta.belief_id_for_concept("concept_seed01")
    real_bid = m11_delta.belief_id_for_concept("concept_real01")
    assert ctx.beliefs.get(seed_bid).origin == "seed"   # re-applied across wipe+replay
    assert ctx.beliefs.get(real_bid).origin == "source"
