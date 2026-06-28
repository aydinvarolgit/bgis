"""Module 8 — Context Gap Analysis (STUB in MVP).

Future: an LLM inspects concepts + related beliefs and emits questions whose answers
would strengthen/contradict the emerging beliefs (competitors, papers, growth, etc.).

In:  Concepts + RelatedBeliefs
Out: Gaps{ questions: [] }

MVP: returns an empty question list. Interface + persisted artifact present so Module 9
has a stable contract to consume.
"""

from __future__ import annotations

from ..context import Context
from ..models import Concepts, Gaps, RelatedBeliefs


def run(concepts: Concepts, related: RelatedBeliefs, ctx: Context) -> Gaps:
    # STUB: no gap questions generated in MVP.
    return Gaps(source_id=concepts.source_id, questions=[])
