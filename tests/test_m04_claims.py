from bgis.models import (
    ClaimDraftList,
    Document,
    ParsedDocuments,
    _ClaimDraft,
)
from bgis.modules import m04_claims


def _parsed():
    return ParsedDocuments(
        source_id="src_test",
        documents=[
            Document(type="readme", title="R", text="Caveman talks terse. Saves tokens."),
            Document(type="metadata", title="M", text="Stars: 1200."),
        ],
    )


def test_assigns_ids_and_source(ctx):
    ctx.llm.structured_responses["ClaimDraftList"] = ClaimDraftList(
        claims=[
            _ClaimDraft(text="Tool compresses LLM output", confidence=0.9, evidence=["readme"]),
            _ClaimDraft(text="Reduces token usage", confidence=0.8, evidence=["readme"]),
        ]
    )
    out = m04_claims.run(_parsed(), ctx)
    assert len(out.claims) == 2
    assert out.claims[0].id == "src_test_clm_001"
    assert out.claims[1].id == "src_test_clm_002"
    assert out.source_id == "src_test"


def test_clamps_confidence_and_normalizes_evidence(ctx):
    ctx.llm.structured_responses["ClaimDraftList"] = ClaimDraftList(
        claims=[
            _ClaimDraft(text="X", confidence=1.0, evidence=["bogus", "architecture"]),
        ]
    )
    out = m04_claims.run(_parsed(), ctx)
    assert out.claims[0].confidence == 1.0
    assert out.claims[0].evidence == ["architecture"]  # bogus dropped


def test_empty_evidence_defaults_to_readme(ctx):
    ctx.llm.structured_responses["ClaimDraftList"] = ClaimDraftList(
        claims=[_ClaimDraft(text="Y", confidence=0.5, evidence=[])]
    )
    out = m04_claims.run(_parsed(), ctx)
    assert out.claims[0].evidence == ["readme"]


def test_skips_blank_claims(ctx):
    ctx.llm.structured_responses["ClaimDraftList"] = ClaimDraftList(
        claims=[_ClaimDraft(text="  ", confidence=0.5), _ClaimDraft(text="real", confidence=0.5)]
    )
    out = m04_claims.run(_parsed(), ctx)
    assert len(out.claims) == 1
    assert out.claims[0].text == "real"


def test_no_documents_returns_empty(ctx):
    out = m04_claims.run(ParsedDocuments(source_id="src_test", documents=[]), ctx)
    assert out.claims == []
