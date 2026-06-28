"""RetrievalBackend interface + shared concept-routing helpers for Module 9.

Module 9 acquires EXTERNAL evidence for the gap questions and attaches each piece to the
source concept it corroborates. The GitHub-native sibling search lives inline in m09; every
OTHER acquisition strategy is a `RetrievalBackend` that yields raw `Candidate`s, which m09
routes to a concept (by embedding similarity, gated by `retrieval_match_threshold`) and emits
as `RetrievedItem`s. This keeps the relevance bar identical across all backends.

A backend may set `Candidate.concept_id` when it already knows which concept it queried for
(e.g. gap-routed or per-concept backends); m09 still embeds the candidate text and gates it
against THAT concept's vector, so a hint speeds routing but never lowers the quality bar.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..context import Context
from ..models import Claims, Concepts, Gaps

# A concept matches better when represented by name + aliases + a few claim texts (mirrors m09).
MAX_CLAIMS_IN_REP = 3


@dataclass
class Candidate:
    """One raw piece of external evidence, before concept routing."""

    text: str  # embedded for concept routing / relevance gating
    summary: str  # human-readable evidence line stored on the RetrievedItem
    source_url: str
    concept_id: Optional[str] = None  # routing hint: the concept this was queried for
    question: Optional[str] = None  # the gap question it answers, if known


class RetrievalBackend(ABC):
    """Yields evidence Candidates for the run's concepts/gaps. m09 does the concept routing."""

    name: str

    @abstractmethod
    def candidates(
        self, gaps: Gaps, concepts: Concepts, claims: Claims, ctx: Context
    ) -> list[Candidate]:
        ...


# --- shared embedding / routing helpers (used by m09 and reusable by backends) ------------- #


def concept_rep(concept, claim_by_id) -> str:
    """Richer match text: concept name + aliases + a few of its claim texts."""
    parts = [concept.name, *concept.aliases]
    for cid in concept.from_claims[:MAX_CLAIMS_IN_REP]:
        c = claim_by_id.get(cid)
        if c:
            parts.append(c.text)
    return ". ".join(parts)


def cos(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def best_concept(vec, concept_vecs):
    best, best_sim = None, -1.0
    for concept, cvec in concept_vecs:
        s = cos(vec, cvec)
        if s > best_sim:
            best, best_sim = concept, s
    return best, best_sim
