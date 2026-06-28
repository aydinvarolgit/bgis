"""Module 12 — Global Belief Graph Update.

Apply belief deltas to the persistent global belief store. Beliefs EVOLVE, never get
overwritten: each update appends a temporal history entry recording confidence before/
after, the delta, the source, and supporting/contradicting evidence. Every belief is
therefore traceable back to the sources that shaped it (explainability requirement).

In:  BeliefDeltas
Out: BeliefGraphUpdate{ created_belief_ids, updated_belief_ids, beliefs (resolved) }

Deterministic. Writes JSON beliefs + Chroma "beliefs" index via BeliefStore.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..context import Context
from ..models import (
    Belief,
    BeliefDeltas,
    BeliefGraphUpdate,
    BeliefHistoryEntry,
)

TREND_EPS = 0.01
MAX_STANCES = 5  # keep only the most recent N opinion stances per belief


def _merge_stances(existing: list[str], new: list[str]) -> list[str]:
    """Append new stances, drop duplicates (preserve order), keep the last MAX_STANCES."""
    merged = list(existing)
    for s in new:
        if s not in merged:
            merged.append(s)
    return merged[-MAX_STANCES:]


def _trend(delta: float, is_new: bool) -> str:
    if is_new:
        return "new"
    if delta > TREND_EPS:
        return "accelerating"
    if delta < -TREND_EPS:
        return "declining"
    return "stable"


def run(inp: BeliefDeltas, ctx: Context) -> BeliefGraphUpdate:
    now = datetime.now(timezone.utc)
    created: list[str] = []
    updated: list[str] = []
    resolved: list[Belief] = []

    for d in inp.deltas:
        existing = ctx.beliefs.get(d.belief_id)
        entry = BeliefHistoryEntry(
            ts=now,
            conf_before=d.old_conf,
            conf_after=d.new_conf,
            delta=d.delta,
            source_id=inp.source_id,
            supporting=d.supporting,
            contradicting=d.contradicting,
        )

        if existing is None:
            belief = Belief(
                id=d.belief_id,
                statement=d.statement,
                confidence=d.new_conf,
                trend=_trend(d.delta, is_new=True),
                linked_concepts=list(d.linked_concepts),
                stances=_merge_stances([], d.stance_points),
                history=[entry],
            )
            created.append(d.belief_id)
        else:
            existing.confidence = d.new_conf
            existing.trend = _trend(d.delta, is_new=False)
            for cid in d.linked_concepts:
                if cid not in existing.linked_concepts:
                    existing.linked_concepts.append(cid)
            existing.stances = _merge_stances(existing.stances, d.stance_points)
            existing.history.append(entry)
            belief = existing
            updated.append(d.belief_id)

        ctx.beliefs.save(belief)
        resolved.append(belief)

    return BeliefGraphUpdate(
        source_id=inp.source_id,
        created_belief_ids=created,
        updated_belief_ids=updated,
        beliefs=resolved,
    )
