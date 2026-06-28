"""Module 7 — Global Belief Retrieval.

Given the concepts from the current source, retrieve existing beliefs the new evidence
might update. Two retrieval paths, unioned:
  1. direct  — beliefs whose linked_concepts contain one of these concept ids.
  2. semantic — beliefs whose statement is near a concept name (Chroma "beliefs").

In:  Concepts
Out: RelatedBeliefs{ beliefs: [Belief, ...] }

Deterministic (no LLM). On cold start the belief store is empty -> returns []. Expected.
"""

from __future__ import annotations

from ..context import Context
from ..models import Concepts, RelatedBeliefs

SEMANTIC_TOP_N = 5


def run(inp: Concepts, ctx: Context) -> RelatedBeliefs:
    found: dict[str, object] = {}  # belief_id -> Belief

    for concept in inp.concepts:
        # 1. direct concept linkage
        for b in ctx.beliefs.by_concept(concept.id):
            found[b.id] = b

        # 2. semantic match on the concept name
        emb = ctx.embedder.embed(concept.name)
        for b, _sim in ctx.beliefs.semantic_search(emb, n=SEMANTIC_TOP_N):
            found.setdefault(b.id, b)

    return RelatedBeliefs(source_id=inp.source_id, beliefs=list(found.values()))
