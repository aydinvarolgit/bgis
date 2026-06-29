from datetime import datetime, timezone

from bgis.models import (
    Belief,
    BeliefGraphUpdate,
    BeliefHistoryEntry,
    Claim,
    EvidencePacket,
    EvidencePackets,
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


def _packets(source_id="src_test", claims_by_concept=None):
    # concept_1 -> bel_1 (belief_id_for_concept). Default: one fact claim for bel_1.
    cbc = claims_by_concept or {
        "concept_1": [Claim(id="c1", text="Orchestrator coordinates 5 agents", confidence=0.9,
                            type="fact")]
    }
    return EvidencePackets(
        source_id=source_id,
        packets=[EvidencePacket(concept_id=cid, concept_name=cid, claims=cl)
                 for cid, cl in cbc.items()],
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
    plan = m14_narrative.run(_update(), _user(), _packets(), ctx)
    assert isinstance(plan, NarrativePlan)
    assert plan.source_id == "src_test"
    assert plan.main_belief == "Coordination beats raw model power"
    assert plan.confidence == 0.95
    assert plan.tone == "visionary"


def test_tone_defaults_to_author_voice(ctx):
    ctx.llm.structured_responses["_NarrativeDraft"] = _NarrativeDraft(
        main_belief="X", tone="", confidence=0.5
    )
    plan = m14_narrative.run(_update(), _user(), _packets(), ctx)
    assert plan.tone == ctx.settings.author_voice


def test_source_lines_lead_with_this_sources_claims():
    # The lead block carries THIS source's own claim text, labeled NEW (bel_1 is created).
    text = m14_narrative._source_lines(_update(), _packets())
    assert "Orchestrator coordinates 5 agents" in text
    assert "(NEW)" in text


def test_corroboration_block_demotes_preexisting_high_conf_beliefs():
    # Gate I: a deduped-onto high-confidence belief (from OTHER sources) must NOT be in the lead
    # block; it belongs in CORROBORATION. Only this source's own claims lead.
    now = datetime.now(timezone.utc)
    h_new = BeliefHistoryEntry(ts=now, conf_before=0.0, conf_after=0.6, delta=0.6, source_id="src_b")
    h_old = BeliefHistoryEntry(ts=now, conf_before=0.0, conf_after=0.95, delta=0.95, source_id="src_a")
    h_reinforce = BeliefHistoryEntry(ts=now, conf_before=0.95, conf_after=0.95, delta=0.0,
                                     source_id="src_b")
    upd = BeliefGraphUpdate(
        source_id="src_b",
        created_belief_ids=["bel_new"],
        updated_belief_ids=["bel_conv"],
        beliefs=[
            Belief(id="bel_conv", statement="Ollama runs open models locally", confidence=0.95,
                   trend="stable", linked_concepts=["concept_conv"], history=[h_old, h_reinforce]),
            Belief(id="bel_new", statement="GLM-5.2 leads the open-weights index", confidence=0.6,
                   trend="new", linked_concepts=["concept_new"], history=[h_new]),
        ],
    )
    pkts = _packets(source_id="src_b", claims_by_concept={
        "concept_new": [Claim(id="c1", text="GLM-5.2 leads the open-weights index", confidence=1.0,
                              type="fact")],
        "concept_conv": [Claim(id="c2", text="GLM-5.2 is an open model", confidence=0.9,
                               type="fact")],
    })
    lead = m14_narrative._source_lines(upd, pkts)
    corr = m14_narrative._corroboration_lines(upd)
    # Lead leads with the NEW source claim, NOT the high-confidence prior statement.
    assert lead.splitlines()[0] == "- (NEW) GLM-5.2 leads the open-weights index"
    assert "Ollama runs open models locally" not in lead          # prior statement stays out of lead
    assert "Ollama runs open models locally" in corr              # demoted to corroboration
    assert "2 independent sources" in corr


def test_stances_reach_the_prompt(ctx):
    upd = _update()
    upd.beliefs[0].stances = ["coordination is overrated", "memory is the real bottleneck"]

    captured = {}

    def capturing(system, user, schema, **kw):
        captured["user"] = user
        captured["system"] = system
        return _NarrativeDraft(main_belief="X", confidence=0.5)

    ctx.llm.structured = capturing
    m14_narrative.run(upd, _user(), _packets(), ctx)

    assert "THIS SOURCE" in captured["user"]
    assert "CORROBORATION" in captured["user"]
    assert "STANCES / DEBATE" in captured["user"]
    assert "memory is the real bottleneck" in captured["user"]
    assert "TAKE A SIDE" in captured["system"]


def test_stance_lines_empty_when_no_stances():
    assert "no opinion stances" in m14_narrative._stance_lines(_update())


def test_debate_lines_surface_contradiction():
    # (#7) A disputed belief + its competing counter belief render as a CONTESTED line.
    now = datetime.now(timezone.utc)
    h = BeliefHistoryEntry(ts=now, conf_before=0.0, conf_after=0.8, delta=0.8, source_id="s")
    upd = BeliefGraphUpdate(
        source_id="src_test",
        beliefs=[
            Belief(id="bel_1", statement="X scales well", confidence=0.8,
                   linked_concepts=["concept_1"], disputed_by=["bel_1__c"], history=[h]),
            Belief(id="bel_1__c", statement="X does not scale", confidence=0.4,
                   linked_concepts=["concept_1"], counter_to="bel_1", history=[h]),
        ],
    )
    lines = m14_narrative._debate_lines(upd)
    assert "CONTESTED" in lines
    assert "X scales well" in lines and "X does not scale" in lines
    assert "0.80" in lines and "0.40" in lines


def test_debate_block_reaches_prompt(ctx):
    now = datetime.now(timezone.utc)
    h = BeliefHistoryEntry(ts=now, conf_before=0.0, conf_after=0.8, delta=0.8, source_id="s")
    upd = BeliefGraphUpdate(
        source_id="src_test", created_belief_ids=["bel_1"],
        beliefs=[
            Belief(id="bel_1", statement="X scales well", confidence=0.8,
                   linked_concepts=["concept_1"], disputed_by=["bel_1__c"], history=[h]),
            Belief(id="bel_1__c", statement="X does not scale", confidence=0.4,
                   linked_concepts=["concept_1"], counter_to="bel_1", history=[h]),
        ],
    )
    captured = {}

    def capturing(system, user, schema, **kw):
        captured["user"] = user
        return _NarrativeDraft(main_belief="X", confidence=0.5)

    ctx.llm.structured = capturing
    m14_narrative.run(upd, _user(), _packets(), ctx)
    assert "OPEN CONTRADICTIONS" in captured["user"]
    assert "X does not scale" in captured["user"]


def test_debate_lines_empty_when_no_disputes():
    assert "no open contradictions" in m14_narrative._debate_lines(_update())


def test_handles_empty_worldview(ctx):
    ctx.llm.structured_responses["_NarrativeDraft"] = _NarrativeDraft(
        main_belief="From user beliefs only", confidence=0.5
    )
    empty = BeliefGraphUpdate(source_id="src_test", beliefs=[])
    plan = m14_narrative.run(empty, _user(), EvidencePackets(source_id="src_test"), ctx)
    assert plan.main_belief == "From user beliefs only"
