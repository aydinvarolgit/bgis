"""Module 14 — Narrative Planner (LLM).

The pivot of BGIS: content is planned from the WORLDVIEW, not from the source. The
planner reads the global belief state (as updated by this source) blended with the
author's own beliefs, and decides the single message a LinkedIn post should make.

In:  BeliefGraphUpdate (resolved global beliefs) + UserBeliefs
Out: NarrativePlan{ main_belief, supporting_beliefs, evidence_points, counterarguments,
                    tone, confidence }

LLM: gemma4 via instructor (structured -> _NarrativeDraft). Author voice from settings.
"""

from __future__ import annotations

from ..context import Context
from ..models import (
    BeliefGraphUpdate,
    NarrativePlan,
    UserBeliefs,
    _NarrativeDraft,
)

MAX_BELIEFS = 12

SYSTEM_TEMPLATE = (
    "You are a content strategist planning a single LinkedIn post for an author whose voice is: "
    "{voice}. "
    "Plan the post from the beliefs below — the worldview as just updated by a newly ingested "
    "source. CENTER the post on what THIS source contributes: lead with the beliefs marked 'NEW "
    "from this source' (they are the just-ingested repo's own claims). Use beliefs marked "
    "'reinforced' as cross-source corroboration and the author's beliefs for stance — but the post "
    "must be recognizably ABOUT the new source, not a generic essay. Choose ONE clear main message "
    "(main_belief) that is insightful and worth the author's reputation, grounded in the NEW "
    "beliefs. Acknowledge honest counterarguments. Where the beliefs and the author's beliefs "
    "tension, lean into that tension — it makes the post sharper. "
    "\n\nGROUNDING RULES (critical): every evidence_point MUST be a concrete, checkable specific "
    "drawn from the beliefs below — name the real project(s), the capability, or the number. NO "
    "abstractions as evidence. When several beliefs are corroborated by multiple independent "
    "sources, call that convergence out explicitly (it is the strongest evidence you have). "
    "BANNED: metaphors and cliches (e.g. 'nervous system', 'the brain', 'industrial wave', 'holy "
    "grail', 'game-changer', 'north star', 'the moat is'), and vague grandiosity with no specifics. "
    "\n\nSet tone to match the author's voice and confidence in [0,1] reflecting how strongly the "
    "evidence supports the main message."
)


def _belief_lines(update: BeliefGraphUpdate) -> str:
    # Beliefs NEWLY asserted by the just-ingested source carry that source's own statements, so
    # they lead — that keeps the post centered on the provided repo. Then strongest/most-shifted.
    def latest_delta(b):
        return abs(b.history[-1].delta) if b.history else 0.0

    created = set(update.created_belief_ids)
    ranked = sorted(
        update.beliefs,
        key=lambda b: (b.id in created, b.confidence, latest_delta(b)),
        reverse=True,
    )[:MAX_BELIEFS]
    lines = []
    for b in ranked:
        d = b.history[-1].delta if b.history else 0.0
        n_sources = len({h.source_id for h in b.history})
        if b.id in created:
            tag = "NEW from this source"
        elif n_sources > 1:
            tag = f"reinforced, {n_sources} independent sources"
        else:
            tag = f"trend {b.trend}"
        lines.append(f"- ({b.confidence:.2f}, {tag}, last_delta {d:+.2f}) {b.statement}")
    return "\n".join(lines) if lines else "(no global beliefs yet)"


def _user_lines(user: UserBeliefs) -> str:
    if not user.beliefs:
        return "(no author beliefs provided)"
    return "\n".join(f"- ({b.confidence:.2f}) {b.statement}" for b in user.beliefs)


def run(update: BeliefGraphUpdate, user: UserBeliefs, ctx: Context) -> NarrativePlan:
    system = SYSTEM_TEMPLATE.format(voice=ctx.settings.author_voice)
    user_prompt = (
        "GLOBAL BELIEFS (the system's current worldview, just updated by a new source):\n"
        f"{_belief_lines(update)}\n\n"
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
