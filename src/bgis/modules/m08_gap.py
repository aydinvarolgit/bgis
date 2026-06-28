"""Module 8 — Context Gap Analysis.

An LLM inspects each concept (plus the related beliefs already in the graph) and emits
targeted questions whose answers would strengthen, contradict, or contextualize the
emerging belief: competitors, adoption/growth, research, alternatives, risks, validation.
Each question is tagged with the concept_id it concerns, so Module 9 can retrieve external
evidence and Module 10 can route it back to the right concept's evidence packet.

In:  Concepts + RelatedBeliefs
Out: Gaps{ gaps: [ Gap{ concept_id, question, kind } ] }

LLM: gemma4 (temperature=0 for reproducibility). Deterministic everywhere else.
"""

from __future__ import annotations

from ..context import Context
from ..models import Concepts, Gap, GapDraftList, Gaps, RelatedBeliefs

# Bound LLM calls / question volume: only the most-supported concepts get gap questions,
# and each concept yields at most this many.
MAX_CONCEPTS = 6
MAX_QUESTIONS_PER_CONCEPT = 2

SYSTEM = (
    "You find the most useful MISSING context about a software/AI concept. Given the concept and "
    "what is already believed about it, propose questions whose answers (from external sources) "
    "would most strengthen, contradict, or contextualize that belief. Each question must be "
    "specific and answerable from public information. Classify each by kind: "
    "'competitor' (rival tools/projects), 'adoption' (usage/growth/traction), "
    "'research' (papers/benchmarks/evidence), 'alternative' (other approaches to the same problem), "
    "'risk' (limitations/failure modes/controversy), 'validation' (independent confirmation of a claim). "
    f"Return at most {MAX_QUESTIONS_PER_CONCEPT} questions. Prefer fewer, higher-value questions."
)


def run(concepts: Concepts, related: RelatedBeliefs, ctx: Context) -> Gaps:
    if not concepts.concepts:
        return Gaps(source_id=concepts.source_id, gaps=[])

    # Only concepts backed by claims anchor a belief worth enriching (mirrors m10). Most-
    # supported first, capped to bound LLM calls.
    supported = [c for c in concepts.concepts if c.from_claims]
    ranked = sorted(supported, key=lambda c: len(c.from_claims), reverse=True)
    chosen = ranked[:MAX_CONCEPTS]

    belief_by_concept = _index_beliefs(related)

    gaps: list[Gap] = []
    for concept in chosen:
        drafts: GapDraftList = ctx.llm.structured(
            system=SYSTEM,
            user=_build_user_prompt(concept, belief_by_concept.get(concept.id, [])),
            schema=GapDraftList,
            temperature=0,
        )
        for draft in drafts.gaps[:MAX_QUESTIONS_PER_CONCEPT]:
            q = draft.question.strip()
            if not q:
                continue
            gaps.append(Gap(concept_id=concept.id, question=q, kind=draft.kind))

    return Gaps(source_id=concepts.source_id, gaps=gaps)


def _index_beliefs(related: RelatedBeliefs) -> dict[str, list[str]]:
    """concept_id -> belief statements that link to it (context for the LLM)."""
    out: dict[str, list[str]] = {}
    for b in related.beliefs:
        for cid in b.linked_concepts:
            out.setdefault(cid, []).append(b.statement)
    return out


def _build_user_prompt(concept, belief_statements: list[str]) -> str:
    lines = [f"Concept: {concept.name}"]
    if concept.aliases:
        lines.append(f"Also called: {', '.join(concept.aliases)}")
    if belief_statements:
        lines.append("Already believed:")
        lines.extend(f"- {s}" for s in belief_statements)
    else:
        lines.append("Nothing is believed about this concept yet.")
    lines.append("\nWhat external context is most worth acquiring?")
    return "\n".join(lines)
