"""Module 4 — Claim Extraction (LLM).

Extract semantic claims — statements about what the repository *is, does, or asserts* —
from the parsed documents. The LLM returns drafts (text/confidence/evidence/polarity);
this module assigns deterministic claim ids and the source_id.

In:  ParsedDocuments
Out: Claims{ claims: [ Claim{ id, text, confidence, evidence, polarity } ] }

LLM: gemma4 via instructor (structured output -> ClaimDraftList).
"""

from __future__ import annotations

from ..context import Context
from ..models import Claim, ClaimDraftList, Claims, ParsedDocuments

# Per-document text budget fed to the LLM (chars) to keep the prompt bounded.
DOC_CHAR_BUDGET = 6000
MAX_CLAIMS = 15

SYSTEM = (
    "You extract semantic claims from documents about a software project, library, paper, or "
    "technology — these may be repository docs, discussion threads, articles, or papers. "
    "A claim is a concise, standalone statement about what something IS, DOES, or ASSERTS "
    "(its purpose, capabilities, approach, architecture, positioning, a judgment, or a result). "
    "Do NOT extract numeric facts/metrics (stars, forks, dates) — those are handled separately. "
    "For each claim: set confidence in [0,1] reflecting how strongly the docs support it; "
    "set evidence to the document type(s) it came from (one of: readme, architecture, "
    "dependencies, metadata); set polarity to positive, negative, or neutral; "
    "and classify its type as one of: "
    "'fact' (a verifiable capability, spec, or architectural property), "
    "'finding' (an empirical or benchmarked result — measurements, evaluations, comparisons), "
    "'opinion' (a judgment, stance, recommendation, or prediction — not directly verifiable). "
    "Each document is labeled with its [type]; let that guide claim typing: "
    "readme/architecture/dependencies/metadata are mostly 'fact'; "
    "'discussion' (forum/comment threads) is mostly 'opinion' — extract the DISTINCT viewpoints, "
    "debates, and predictions people argue, not a bland summary; "
    "'article'/'paper' mix 'opinion' (the author's thesis or stance) and 'finding' (results). "
    "Classify each claim by what it actually is. "
    f"Return at most {MAX_CLAIMS} of the most important, non-redundant claims."
)


def _build_user_prompt(parsed: ParsedDocuments) -> str:
    parts = []
    for d in parsed.documents:
        text = d.text.strip()
        if len(text) > DOC_CHAR_BUDGET:
            text = text[:DOC_CHAR_BUDGET] + "\n…(truncated)"
        parts.append(f"=== DOCUMENT [{d.type}] {d.title} ===\n{text}")
    return (
        "Extract claims from the following repository documents.\n\n"
        + "\n\n".join(parts)
    )


def _normalize_evidence(evidence: list[str]) -> list[str]:
    valid = {
        "readme", "architecture", "dependencies", "metadata", "discussion", "article", "paper"
    }
    out = [e.strip().lower() for e in evidence if e.strip().lower() in valid]
    return out or ["readme"]


def run(inp: ParsedDocuments, ctx: Context) -> Claims:
    if not inp.documents:
        return Claims(source_id=inp.source_id, claims=[])

    drafts: ClaimDraftList = ctx.llm.structured(
        system=SYSTEM,
        user=_build_user_prompt(inp),
        schema=ClaimDraftList,
        temperature=0,  # deterministic extraction -> stable concepts/beliefs across runs
    )

    claims: list[Claim] = []
    for i, d in enumerate(drafts.claims[:MAX_CLAIMS], start=1):
        text = d.text.strip()
        if not text:
            continue
        claims.append(
            Claim(
                id=f"{inp.source_id}_clm_{i:03d}",
                text=text,
                confidence=max(0.0, min(1.0, d.confidence)),
                evidence=_normalize_evidence(d.evidence),
                polarity=d.polarity,
                type=d.type,
            )
        )
    return Claims(source_id=inp.source_id, claims=claims)
