from bgis.models import Claim, Claims, ConceptDraft, ConceptDraftList
from bgis.modules import m06_concepts


def test_normalize_lowercases_singularizes_aliases():
    assert m06_concepts.normalize_concept("Multi-Agent Systems") == "multi-agent system"
    assert m06_concepts.normalize_concept("Agentic AI") == "multi-agent system"  # alias
    assert m06_concepts.normalize_concept("LLMs!!!") == "llm"  # alias + punctuation


def _claims(*ids):
    return Claims(
        source_id="src_test",
        claims=[Claim(id=i, text=f"text {i}", confidence=0.9) for i in ids],
    )


def _ctx_with_orthogonal(ctx):
    # Orthogonal embeddings keyed by normalized concept name -> clean dedup behavior.
    ctx.embedder.table = {
        "multi-agent system": [1.0, 0.0, 0.0, 0.0],
        "token compression": [0.0, 1.0, 0.0, 0.0],
        "prompt engineering": [0.0, 0.0, 1.0, 0.0],
    }
    return ctx


def test_two_phrasings_collapse_to_one_concept(ctx):
    ctx = _ctx_with_orthogonal(ctx)
    ctx.llm.structured_responses["ConceptDraftList"] = ConceptDraftList(
        concepts=[
            ConceptDraft(name="agentic ai", from_claims=["c1"]),       # -> multi-agent system
            ConceptDraft(name="multi-agent systems", from_claims=["c2"]),
        ]
    )
    out = m06_concepts.run(_claims("c1", "c2"), ctx)
    assert len(out.concepts) == 1
    c = out.concepts[0]
    assert c.name == "multi-agent system"
    assert set(c.from_claims) == {"c1", "c2"}


def test_distinct_concepts_get_distinct_ids(ctx):
    ctx = _ctx_with_orthogonal(ctx)
    ctx.llm.structured_responses["ConceptDraftList"] = ConceptDraftList(
        concepts=[
            ConceptDraft(name="multi-agent systems", from_claims=["c1"]),
            ConceptDraft(name="token compression", from_claims=["c1"]),
        ]
    )
    out = m06_concepts.run(_claims("c1"), ctx)
    assert len({c.id for c in out.concepts}) == 2


def test_concept_id_stable_across_runs(ctx):
    ctx = _ctx_with_orthogonal(ctx)
    ctx.llm.structured_responses["ConceptDraftList"] = ConceptDraftList(
        concepts=[ConceptDraft(name="token compression", from_claims=["c1"])]
    )
    first = m06_concepts.run(_claims("c1"), ctx)
    second = m06_concepts.run(_claims("c1"), ctx)
    assert first.concepts[0].id == second.concepts[0].id  # matched via Chroma


def test_invalid_claim_ids_filtered(ctx):
    ctx = _ctx_with_orthogonal(ctx)
    ctx.llm.structured_responses["ConceptDraftList"] = ConceptDraftList(
        concepts=[ConceptDraft(name="prompt engineering", from_claims=["c1", "ghost"])]
    )
    out = m06_concepts.run(_claims("c1"), ctx)
    assert out.concepts[0].from_claims == ["c1"]


def test_no_claims_returns_empty(ctx):
    out = m06_concepts.run(Claims(source_id="src_test", claims=[]), ctx)
    assert out.concepts == []


def _ctx_gray_band(ctx):
    # cos([1,0],[0.65,0.7599]) = 0.65  -> inside the [0.60, 0.72) gray band
    ctx.embedder.table = {
        "alpha concept": [1.0, 0.0],
        "beta concept": [0.65, 0.7599],
    }
    return ctx


def test_gray_band_merges_when_llm_says_yes(ctx):
    ctx = _ctx_gray_band(ctx)
    ctx.llm.text_response = "yes"
    ctx.llm.structured_responses["ConceptDraftList"] = ConceptDraftList(
        concepts=[
            ConceptDraft(name="alpha concept", from_claims=["c1"]),
            ConceptDraft(name="beta concept", from_claims=["c1"]),
        ]
    )
    out = m06_concepts.run(_claims("c1"), ctx)
    assert len(out.concepts) == 1  # beta merged into alpha via LLM adjudication
    assert "beta concept" in out.concepts[0].aliases


def test_gray_band_splits_when_llm_says_no(ctx):
    ctx = _ctx_gray_band(ctx)
    ctx.llm.text_response = "no"
    ctx.llm.structured_responses["ConceptDraftList"] = ConceptDraftList(
        concepts=[
            ConceptDraft(name="alpha concept", from_claims=["c1"]),
            ConceptDraft(name="beta concept", from_claims=["c1"]),
        ]
    )
    out = m06_concepts.run(_claims("c1"), ctx)
    assert len(out.concepts) == 2  # LLM rejected the merge -> distinct concepts


def test_auto_merge_skips_llm_above_high_threshold(ctx):
    # Identical embedding -> sim 1.0 >= 0.72 -> merge without consulting the LLM.
    ctx.embedder.table = {"alpha concept": [1.0, 0.0]}
    ctx.llm.text_response = "no"  # would split if consulted; must be ignored
    ctx.llm.structured_responses["ConceptDraftList"] = ConceptDraftList(
        concepts=[
            ConceptDraft(name="alpha concept", from_claims=["c1"]),
            ConceptDraft(name="Alpha Concept", from_claims=["c1"]),  # normalizes identically
        ]
    )
    out = m06_concepts.run(_claims("c1"), ctx)
    assert len(out.concepts) == 1
