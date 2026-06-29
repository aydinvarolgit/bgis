"""Module 14 — Narrative Planner (LLM).

The pivot of BGIS: content is planned from the WORLDVIEW, not from the source. The
planner reads the global belief state (as updated by this source) blended with the
author's own beliefs, and decides the single message a LinkedIn post should make.

In:  BeliefGraphUpdate (resolved global beliefs) + UserBeliefs + EvidencePackets (this run)
Out: NarrativePlan{ main_belief, supporting_beliefs, evidence_points, counterarguments,
                    tone, confidence }

The post is planned from the WORLDVIEW but must be recognizably ABOUT the just-ingested source.
The trap (Gate I): when this source's concepts dedup onto pre-existing beliefs, those beliefs keep
their PRIOR statement (from an earlier source) and carry higher confidence — so the planner drifts
onto them and the post stops being about the new source. The fix: feed the planner THIS SOURCE's own
claim texts (from the evidence packets, routed to beliefs by concept->belief id) as the lead block,
and demote the pre-existing beliefs to a clearly-secondary CORROBORATION block.

LLM: gemma4 via instructor (structured -> _NarrativeDraft). Author voice from settings.
"""

from __future__ import annotations

from ..context import Context
from ..models import (
    BeliefGraphUpdate,
    EvidencePackets,
    NarrativePlan,
    UserBeliefs,
    _NarrativeDraft,
)
from .m11_delta import belief_id_for_concept

MAX_SOURCE_LINES = 8       # the lead block: this source's own claims
MAX_CLAIMS_PER_BELIEF = 2  # don't let one verbose concept flood the lead
MAX_CORROBORATION = 4      # the secondary block: pre-existing beliefs this source agreed with

SYSTEM_TEMPLATE = (
    "You are a content strategist planning a single LinkedIn post for an author whose voice is: "
    "{voice}. "
    "\n\nThe post MUST be recognizably ABOUT the newly ingested source. The 'THIS SOURCE' block "
    "below is what the source itself claims — the post leads with these specifics and the "
    "main_belief MUST be grounded in them. The 'CORROBORATION' block is pre-existing beliefs from "
    "OTHER sources that this source agrees with — use them ONLY as secondary support ('this also "
    "lines up with...'), and to call out cross-source convergence; NEVER let them become the "
    "subject of the post. Do not center the post on a corroboration belief just because it has "
    "higher confidence. Acknowledge honest counterarguments; lean into tension with the author's "
    "beliefs where it sharpens the point. "
    "\n\nGROUNDING RULES (critical): every evidence_point MUST be a concrete, checkable specific "
    "drawn from the blocks below — name the real project(s), the capability, or the number. NO "
    "abstractions as evidence. When a CORROBORATION belief spans multiple independent sources, call "
    "that convergence out explicitly. "
    "BANNED: metaphors and cliches (e.g. 'nervous system', 'the brain', 'industrial wave', 'holy "
    "grail', 'game-changer', 'north star', 'the moat is'), and vague grandiosity with no specifics. "
    "\n\nUSING THE THREE EVIDENCE KINDS: treat FACTS as grounding (what the projects are/do), "
    "FINDINGS as hard evidence (measured/benchmarked results), and the STANCES/DEBATE block as the "
    "opinions and tensions in the field — use them to TAKE A SIDE and argue a position, not just to "
    "report. A sharp post grounds a contested stance in facts and findings. When the OPEN "
    "CONTRADICTIONS block is non-empty, the strongest posts engage that disagreement directly — name "
    "both sides, weigh their confidences, and commit to a reasoned position rather than papering over "
    "the tension. "
    "\n\nSet tone to match the author's voice and confidence in [0,1] reflecting how strongly the "
    "evidence supports the main message."
)


def _source_claim_map(packets: EvidencePackets) -> dict[str, list[str]]:
    """belief_id -> THIS source's fact/finding claim texts (highest-confidence first)."""
    out: dict[str, list[str]] = {}
    for p in packets.packets:
        cc = sorted(
            (c for c in p.claims if c.type != "opinion"),
            key=lambda c: c.confidence,
            reverse=True,
        )
        if cc:
            out[belief_id_for_concept(p.concept_id)] = [c.text for c in cc]
    return out


def _source_lines(update: BeliefGraphUpdate, packets: EvidencePackets) -> str:
    """The lead block: what THIS source claims, routed to the beliefs it created/touched. Created
    beliefs lead (they are wholly this source's); then the rest by recency of shift."""
    cmap = _source_claim_map(packets)
    created = set(update.created_belief_ids)

    def latest_delta(b):
        return abs(b.history[-1].delta) if b.history else 0.0

    ranked = sorted(
        update.beliefs, key=lambda b: (b.id in created, latest_delta(b)), reverse=True
    )
    lines: list[str] = []
    for b in ranked:
        # Seed beliefs are background substrate — never the subject/lead of a post. They still
        # surface in the CORROBORATION block.
        if b.origin == "seed":
            continue
        texts = cmap.get(b.id)
        if not texts:
            continue
        tag = "NEW" if b.id in created else "also corroborated an existing belief"
        for t in texts[:MAX_CLAIMS_PER_BELIEF]:
            lines.append(f"- ({tag}) {t}")
            if len(lines) >= MAX_SOURCE_LINES:
                return "\n".join(lines)
    return "\n".join(lines) if lines else "(this source produced no fact/finding claims)"


def _corroboration_lines(update: BeliefGraphUpdate) -> str:
    """The secondary block: pre-existing beliefs (not created this run) that this source agreed
    with — surfaced as cross-source support, strongest convergence first."""
    created = set(update.created_belief_ids)
    pairs = []
    for b in update.beliefs:
        # Pre-existing beliefs this run agreed with; seed beliefs always count as corroboration
        # (they're excluded from the lead, so this is their only home).
        if b.id in created and b.origin != "seed":
            continue
        n = len({h.source_id for h in b.history})
        pairs.append((n, b))
    pairs.sort(key=lambda nb: (nb[0], nb[1].confidence), reverse=True)
    lines = [
        f"- ({b.confidence:.2f}, {n} independent sources) {b.statement}"
        for n, b in pairs[:MAX_CORROBORATION]
    ]
    return "\n".join(lines) if lines else "(no pre-existing beliefs corroborated by this source)"


def _debate_lines(update: BeliefGraphUpdate) -> str:
    """Open disputes (#7): a belief and the competing belief that contradicts it, each with its own
    confidence. Lets the post argue an honestly contested point instead of reporting a settled one."""
    by_id = {b.id: b for b in update.beliefs}
    lines: list[str] = []
    for b in update.beliefs:
        for cid in b.disputed_by:
            counter = by_id.get(cid)
            counter_txt = (
                f'"{counter.statement}" (confidence {counter.confidence:.2f})'
                if counter else "a contradicting source"
            )
            lines.append(
                f'- CONTESTED: "{b.statement}" (confidence {b.confidence:.2f}) is DISPUTED by '
                f"{counter_txt}"
            )
    return "\n".join(lines) if lines else "(no open contradictions among these beliefs)"


def _stance_lines(update: BeliefGraphUpdate) -> str:
    # Opinion stances accumulated on the touched beliefs — the field's judgments/predictions/debate.
    lines = []
    for b in update.beliefs:
        for s in b.stances:
            lines.append(f"- (on: {b.statement[:60]}) {s}")
    return "\n".join(lines) if lines else "(no opinion stances on these beliefs yet)"


def _user_lines(user: UserBeliefs) -> str:
    if not user.beliefs:
        return "(no author beliefs provided)"
    return "\n".join(f"- ({b.confidence:.2f}) {b.statement}" for b in user.beliefs)


def run(
    update: BeliefGraphUpdate,
    user: UserBeliefs,
    packets: EvidencePackets,
    ctx: Context,
) -> NarrativePlan:
    system = SYSTEM_TEMPLATE.format(voice=ctx.settings.author_voice)
    user_prompt = (
        "THIS SOURCE (what the just-ingested source itself claims — LEAD the post with these, and "
        "ground the main_belief here):\n"
        f"{_source_lines(update, packets)}\n\n"
        "CORROBORATION (pre-existing beliefs from OTHER sources this source agrees with — secondary "
        "support only, never the subject):\n"
        f"{_corroboration_lines(update)}\n\n"
        "STANCES / DEBATE (opinions accumulated on these beliefs — use to argue a position):\n"
        f"{_stance_lines(update)}\n\n"
        "OPEN CONTRADICTIONS (beliefs a source has directly disputed — name the tension honestly and "
        "take a reasoned side, weighing the two confidences):\n"
        f"{_debate_lines(update)}\n\n"
        "AUTHOR BELIEFS (the author's own stance):\n"
        f"{_user_lines(user)}\n\n"
        "Plan the LinkedIn post."
    )

    draft: _NarrativeDraft = ctx.llm.structured(
        system=system, user=user_prompt, schema=_NarrativeDraft
    )

    return NarrativePlan(
        source_id=update.source_id,
        main_belief=draft.main_belief.strip(),
        supporting_beliefs=draft.supporting_beliefs,
        evidence_points=draft.evidence_points,
        counterarguments=draft.counterarguments,
        tone=draft.tone or ctx.settings.author_voice,
        confidence=max(0.0, min(1.0, draft.confidence)),
    )
