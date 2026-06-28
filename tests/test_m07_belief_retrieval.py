from bgis.models import Belief, Concept, Concepts
from bgis.modules import m07_belief_retrieval


def _concepts(*pairs):
    # pairs: (concept_id, name)
    return Concepts(
        source_id="src_test",
        concepts=[Concept(id=cid, name=name) for cid, name in pairs],
    )


def test_cold_start_returns_empty(ctx):
    out = m07_belief_retrieval.run(_concepts(("concept_a", "orchestration")), ctx)
    assert out.beliefs == []


def test_direct_concept_linkage(ctx):
    ctx.beliefs.save(
        Belief(id="bel_1", statement="Orchestration is rising", confidence=0.8,
               linked_concepts=["concept_a"])
    )
    out = m07_belief_retrieval.run(_concepts(("concept_a", "orchestration")), ctx)
    assert [b.id for b in out.beliefs] == ["bel_1"]


def test_semantic_retrieval(ctx):
    # Make concept name and belief statement embed identically -> high similarity.
    ctx.embedder.table = {
        "orchestration": [1.0, 0.0, 0.0],
        "Orchestration dominates": [1.0, 0.0, 0.0],
    }
    ctx.beliefs.save(
        Belief(id="bel_2", statement="Orchestration dominates", confidence=0.7,
               linked_concepts=["concept_other"])
    )
    out = m07_belief_retrieval.run(_concepts(("concept_a", "orchestration")), ctx)
    assert "bel_2" in {b.id for b in out.beliefs}


def test_dedups_when_direct_and_semantic_overlap(ctx):
    ctx.embedder.table = {
        "orchestration": [1.0, 0.0, 0.0],
        "Orchestration is rising": [1.0, 0.0, 0.0],
    }
    ctx.beliefs.save(
        Belief(id="bel_1", statement="Orchestration is rising", confidence=0.8,
               linked_concepts=["concept_a"])
    )
    out = m07_belief_retrieval.run(_concepts(("concept_a", "orchestration")), ctx)
    assert [b.id for b in out.beliefs] == ["bel_1"]  # appears once
