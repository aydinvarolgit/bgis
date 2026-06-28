from datetime import datetime, timezone

from bgis.models import (
    Belief,
    BeliefGraphUpdate,
    BeliefHistoryEntry,
    NarrativePlan,
    UserBelief,
    UserBeliefs,
    _NarrativeDraft,
)
from bgis.modules import m14_narrative


def _update():
    h = BeliefHistoryEntry(
        ts=datetime.now(timezone.utc), conf_before=0.0, conf_after=0.9, delta=0.9,
        source_id="src_test",
    )
    return BeliefGraphUpdate(
        source_id="src_test",
        created_belief_ids=["bel_1"],
        beliefs=[
            Belief(id="bel_1", statement="Orchestration is winning", confidence=0.9,
                   trend="new", linked_concepts=["concept_1"], history=[h]),
        ],
    )


def _user():
    return UserBeliefs(beliefs=[UserBelief(statement="Stars are noise", confidence=0.8)])


def test_builds_plan_from_belief_state(ctx):
    ctx.llm.structured_responses["_NarrativeDraft"] = _NarrativeDraft(
        main_belief="Coordination beats raw model power",
        supporting_beliefs=["Orchestration is winning"],
        evidence_points=["A repo trending on orchestration"],
        counterarguments=["Frontier models still matter"],
        tone="visionary",
        confidence=0.95,
    )
    plan = m14_narrative.run(_update(), _user(), ctx)
    assert isinstance(plan, NarrativePlan)
    assert plan.source_id == "src_test"
    assert plan.main_belief == "Coordination beats raw model power"
    assert plan.confidence == 0.95
    assert plan.tone == "visionary"


def test_tone_defaults_to_author_voice(ctx):
    ctx.llm.structured_responses["_NarrativeDraft"] = _NarrativeDraft(
        main_belief="X", tone="", confidence=0.5
    )
    plan = m14_narrative.run(_update(), _user(), ctx)
    assert plan.tone == ctx.settings.author_voice


def test_belief_lines_includes_state():
    text = m14_narrative._belief_lines(_update())
    assert "Orchestration is winning" in text
    assert "trend new" in text


def test_handles_empty_worldview(ctx):
    ctx.llm.structured_responses["_NarrativeDraft"] = _NarrativeDraft(
        main_belief="From user beliefs only", confidence=0.5
    )
    empty = BeliefGraphUpdate(source_id="src_test", beliefs=[])
    plan = m14_narrative.run(empty, _user(), ctx)
    assert plan.main_belief == "From user beliefs only"
