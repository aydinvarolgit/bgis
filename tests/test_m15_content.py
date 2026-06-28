from bgis.models import GeneratedContent, NarrativePlan
from bgis.modules import m15_content


def _plan():
    return NarrativePlan(
        source_id="src_test",
        main_belief="Coordination beats raw model power",
        supporting_beliefs=["Orchestration is winning"],
        evidence_points=["A repo trending on orchestration"],
        counterarguments=["Frontier models still matter"],
        tone="visionary",
        confidence=0.9,
    )


def test_generates_and_writes_post(ctx):
    ctx.llm.text_response = "# Hook\n\nOrchestration is the future. What do you think?"
    out = m15_content.run(_plan(), ctx)
    assert isinstance(out, GeneratedContent)
    assert out.media == "linkedin"
    assert out.source_id == "src_test"
    assert out.word_count > 0
    # File written to data/posts/<id>.md
    post = ctx.settings.stage_dir("posts") / "src_test.md"
    assert post.exists()
    assert "Orchestration" in post.read_text(encoding="utf-8")


def test_unknown_media_raises(ctx):
    import pytest

    with pytest.raises(ValueError):
        m15_content.run(_plan(), ctx, media="hologram")


def test_registry_has_linkedin():
    assert "linkedin" in m15_content.GENERATORS
    assert m15_content.GENERATORS["linkedin"].media == "linkedin"
