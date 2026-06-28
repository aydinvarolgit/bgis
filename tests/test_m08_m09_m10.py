from bgis.models import (
    Claim,
    Claims,
    Concept,
    Concepts,
    Gaps,
    RelatedBeliefs,
    RetrievedEvidence,
    Signal,
    Signals,
)
from bgis.modules import m08_gap, m09_retrieval, m10_evidence


def _concepts():
    return Concepts(
        source_id="src_test",
        concepts=[
            Concept(id="concept_a", name="orchestration", from_claims=["c1", "c2"]),
            Concept(id="concept_b", name="token compression", from_claims=["c3"]),
            Concept(id="concept_empty", name="ghost", from_claims=[]),
        ],
    )


def _claims():
    return Claims(
        source_id="src_test",
        claims=[
            Claim(id="c1", text="orchestrates agents", confidence=0.9),
            Claim(id="c2", text="coordination matters", confidence=0.7),
            Claim(id="c3", text="compresses tokens", confidence=0.8),
        ],
    )


def _signals():
    return Signals(
        source_id="src_test",
        signals=[Signal(name="stars", value=1200, unit="count", source_field="stars")],
    )


# --- Module 8 (stub) ---
def test_gap_stub_empty(ctx):
    g = m08_gap.run(_concepts(), RelatedBeliefs(source_id="src_test"), ctx)
    assert g.source_id == "src_test"
    assert g.questions == []


# --- Module 9 (stub) ---
def test_retrieval_stub_empty(ctx):
    r = m09_retrieval.run(Gaps(source_id="src_test"), ctx)
    assert r.items == []


# --- Module 10 ---
def test_evidence_groups_by_concept(ctx):
    pkts = m10_evidence.run(
        _concepts(), _claims(), _signals(),
        RelatedBeliefs(source_id="src_test"), RetrievedEvidence(source_id="src_test"), ctx,
    )
    # concept_empty has no claims -> dropped
    names = {p.concept_name for p in pkts.packets}
    assert names == {"orchestration", "token compression"}
    orch = next(p for p in pkts.packets if p.concept_name == "orchestration")
    assert {c.id for c in orch.claims} == {"c1", "c2"}
    assert orch.signals[0].name == "stars"
    assert orch.external == []
    assert "avg confidence 0.80" in orch.summary  # (0.9+0.7)/2
    assert "1200 stars" in orch.summary


def test_evidence_external_passthrough(ctx):
    retrieved = RetrievedEvidence(source_id="src_test", items=[])
    pkts = m10_evidence.run(
        _concepts(), _claims(), _signals(),
        RelatedBeliefs(source_id="src_test"), retrieved, ctx,
    )
    assert all(p.external == [] for p in pkts.packets)
