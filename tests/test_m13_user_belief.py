from bgis.models import UserBeliefs
from bgis.modules import m13_user_belief


def test_missing_file_returns_empty(ctx):
    out = m13_user_belief.run(ctx)
    assert out.beliefs == []


def test_loads_present_file(ctx):
    path = m13_user_belief.user_beliefs_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    UserBeliefs.model_validate(
        {"beliefs": [{"statement": "Frontier models are commoditizing", "confidence": 0.95}]}
    )
    path.write_text(
        '{"beliefs":[{"statement":"Frontier models are commoditizing","confidence":0.95}]}',
        encoding="utf-8",
    )
    out = m13_user_belief.run(ctx)
    assert len(out.beliefs) == 1
    assert out.beliefs[0].statement == "Frontier models are commoditizing"
    assert out.beliefs[0].confidence == 0.95
