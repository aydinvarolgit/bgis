from bgis.models import BeliefDelta, BeliefDeltas
from bgis.modules import m12_belief_graph


def _deltas(old, new, statement="orchestration rising"):
    return BeliefDeltas(
        source_id="src_A",
        deltas=[
            BeliefDelta(
                belief_id="bel_x1",
                statement=statement,
                linked_concepts=["concept_x1"],
                old_conf=old,
                evidence_strength=new,
                delta=round(new - old, 6),
                new_conf=new,
                supporting=["c1"],
                rationale=["r"],
            )
        ],
    )


def test_creates_new_belief_with_history(ctx):
    out = m12_belief_graph.run(_deltas(0.0, 0.7), ctx)
    assert out.created_belief_ids == ["bel_x1"]
    assert out.updated_belief_ids == []
    b = ctx.beliefs.get("bel_x1")
    assert b is not None
    assert b.confidence == 0.7
    assert b.trend == "new"
    assert len(b.history) == 1
    assert b.history[0].conf_before == 0.0
    assert b.history[0].source_id == "src_A"
    assert b.linked_concepts == ["concept_x1"]


def test_second_run_appends_history_and_updates(ctx):
    m12_belief_graph.run(_deltas(0.0, 0.7), ctx)
    # Second source updates the same belief.
    out2 = BeliefDeltas(
        source_id="src_B",
        deltas=[
            BeliefDelta(
                belief_id="bel_x1", statement="ignored on update",
                linked_concepts=["concept_x2"], old_conf=0.7, evidence_strength=0.9,
                delta=0.06, new_conf=0.76, supporting=["c9"], rationale=["r"],
            )
        ],
    )
    res = m12_belief_graph.run(out2, ctx)
    assert res.updated_belief_ids == ["bel_x1"]
    b = ctx.beliefs.get("bel_x1")
    assert b.confidence == 0.76
    assert b.trend == "accelerating"  # delta > 0.01
    assert len(b.history) == 2  # evolves, not overwritten
    assert b.history[1].source_id == "src_B"
    assert set(b.linked_concepts) == {"concept_x1", "concept_x2"}  # merged
    assert b.statement == "orchestration rising"  # original kept


def _delta_with_stances(belief_id, old, new, stances):
    return BeliefDeltas(
        source_id="src_S",
        deltas=[
            BeliefDelta(
                belief_id=belief_id, statement="s", linked_concepts=["concept_s"],
                old_conf=old, evidence_strength=new, delta=round(new - old, 6),
                new_conf=new, supporting=[], stance_points=stances, rationale=["r"],
            )
        ],
    )


def test_stances_accumulate_dedup_and_cap(ctx):
    m12_belief_graph.run(_delta_with_stances("bel_s1", 0.0, 0.3, ["a", "b"]), ctx)
    # Second source: one dup ("b"), three new -> total unique 6, capped to last 5.
    m12_belief_graph.run(_delta_with_stances("bel_s1", 0.3, 0.3, ["b", "c", "d", "e", "f"]), ctx)
    b = ctx.beliefs.get("bel_s1")
    assert b.stances == ["b", "c", "d", "e", "f"]  # "a" evicted by cap, "b" not duplicated


def test_counter_belief_wires_disputed_by(ctx):
    # (#7) A competing belief (counter_to set) gets persisted AND back-links the disputed primary.
    m12_belief_graph.run(_deltas(0.0, 0.8, statement="X scales well"), ctx)  # primary bel_x1
    counter = BeliefDeltas(
        source_id="src_D",
        deltas=[
            BeliefDelta(
                belief_id="bel_x1__c", statement="X does not scale",
                linked_concepts=["concept_x1"], old_conf=0.0, evidence_strength=0.4,
                delta=0.4, new_conf=0.4, supporting=["c2"], counter_to="bel_x1",
                rationale=["competing"],
            )
        ],
    )
    res = m12_belief_graph.run(counter, ctx)
    assert "bel_x1__c" in res.created_belief_ids
    c = ctx.beliefs.get("bel_x1__c")
    assert c.counter_to == "bel_x1"
    assert c.confidence == 0.4
    primary = ctx.beliefs.get("bel_x1")
    assert primary.disputed_by == ["bel_x1__c"]  # reverse link wired
    assert primary.confidence == 0.8  # primary NOT dampened by the contradiction


def test_primary_and_counter_in_one_update(ctx):
    # Primary update + its counter in the same BeliefDeltas: counter processed last, primary keeps
    # its disputed_by even though both are saved in the same run.
    m12_belief_graph.run(_deltas(0.0, 0.5, statement="X scales well"), ctx)
    batch = BeliefDeltas(
        source_id="src_E",
        deltas=[
            BeliefDelta(belief_id="bel_x1__c", statement="X does not scale",
                        linked_concepts=["concept_x1"], old_conf=0.0, evidence_strength=0.4,
                        delta=0.4, new_conf=0.4, supporting=["c2"], counter_to="bel_x1",
                        rationale=["competing"]),
            BeliefDelta(belief_id="bel_x1", statement="ignored", linked_concepts=["concept_x1"],
                        old_conf=0.5, evidence_strength=0.6, delta=0.05, new_conf=0.55,
                        supporting=["c1"], rationale=["r"]),
        ],
    )
    m12_belief_graph.run(batch, ctx)
    primary = ctx.beliefs.get("bel_x1")
    assert primary.confidence == 0.55  # its own supporting update applied
    assert primary.disputed_by == ["bel_x1__c"]  # not clobbered by the same-run primary save


def test_declining_trend(ctx):
    m12_belief_graph.run(_deltas(0.0, 0.8), ctx)
    down = BeliefDeltas(
        source_id="src_C",
        deltas=[
            BeliefDelta(
                belief_id="bel_x1", statement="s", linked_concepts=["concept_x1"],
                old_conf=0.8, evidence_strength=0.3, delta=-0.15, new_conf=0.65,
                supporting=[], rationale=["r"],
            )
        ],
    )
    m12_belief_graph.run(down, ctx)
    assert ctx.beliefs.get("bel_x1").trend == "declining"
