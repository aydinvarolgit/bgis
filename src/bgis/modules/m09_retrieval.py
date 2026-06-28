"""Module 9 — Retrieval Engine (STUB in MVP).

Future: acquire external evidence answering the gap questions via source plugins
(follow repo links / citations / topics / dependencies; optional search adapters).

In:  Gaps
Out: RetrievedEvidence{ items: [] }

MVP: passthrough — returns no external evidence. Belief updates run on the single
source's own claims + signals.
"""

from __future__ import annotations

from ..context import Context
from ..models import Gaps, RetrievedEvidence


def run(gaps: Gaps, ctx: Context) -> RetrievedEvidence:
    # STUB: no external retrieval in MVP.
    return RetrievedEvidence(source_id=gaps.source_id, items=[])
