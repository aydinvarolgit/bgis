"""Module 6 — Concept Extraction & Normalization (the dedup engine).

Turn claims into normalized concepts in a global, persistent concept space. The same
real-world concept must resolve to the same concept_id across runs, even when phrased
differently — this is what lets beliefs accumulate across many sources.

In:  Claims
Out: Concepts{ concepts: [ Concept{ id, name, aliases, from_claims } ] }

Pipeline per candidate phrase:
  LLM extract -> string-normalize -> embed (nomic) -> Chroma nearest-neighbor
  -> if similarity >= threshold: reuse existing concept_id (record phrase as alias)
     else: mint new concept_id, add to the global concept collection.

LLM: gemma4 (phrase extraction). Embeddings: nomic-embed-text. Store: Chroma "concepts".
"""

from __future__ import annotations

import hashlib
import re

from ..context import Context
from ..models import Claims, Concept, ConceptDraftList, Concepts

CONCEPT_COLLECTION = "concepts"

# Minimal canonical alias map (extend over time). Applied before embedding.
ALIAS_MAP = {
    "agentic ai": "multi-agent systems",
    "agent systems": "multi-agent systems",
    "llm orchestration": "orchestration",
    "large language model": "llm",
    "large language models": "llm",
}

SYSTEM = (
    "You identify the key technical CONCEPTS expressed across a set of claims about a software "
    "project. A concept is a reusable noun phrase naming a technology, method, capability, or "
    "domain (e.g. 'multi-agent systems', 'token compression', 'prompt engineering'). "
    "Return concise concept names (2-4 words, lowercase), and for each, the ids of the claims it "
    "comes from. Merge duplicates. Aim for the 5-12 most important concepts."
)

_inflect = None


def _singularize_head(name: str) -> str:
    """Singularize the last word using inflect (lazy import)."""
    global _inflect
    if _inflect is None:
        import inflect

        _inflect = inflect.engine()
    words = name.split()
    if not words:
        return name
    sing = _inflect.singular_noun(words[-1])
    if sing:
        words[-1] = sing
    return " ".join(words)


def normalize_concept(name: str) -> str:
    """lowercase -> strip punctuation/space -> alias map -> singularize head word."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s\-/+]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s in ALIAS_MAP:
        s = ALIAS_MAP[s]
    s = _singularize_head(s)
    if s in ALIAS_MAP:
        s = ALIAS_MAP[s]
    return s


def _new_concept_id(normalized: str) -> str:
    return "concept_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]


def run(inp: Claims, ctx: Context) -> Concepts:
    if not inp.claims:
        return Concepts(source_id=inp.source_id, concepts=[])

    drafts: ConceptDraftList = ctx.llm.structured(
        system=SYSTEM,
        user=_build_user_prompt(inp),
        schema=ConceptDraftList,
        temperature=0,  # deterministic extraction -> stable concept ids across runs
    )

    valid_claim_ids = {c.id for c in inp.claims}
    # concept_id -> Concept (accumulates aliases/from_claims within this run)
    resolved: dict[str, Concept] = {}

    for draft in drafts.concepts:
        normalized = normalize_concept(draft.name)
        if not normalized:
            continue
        embedding = ctx.embedder.embed(normalized)
        match = _resolve_match(normalized, embedding, ctx)

        if match is not None:
            concept_id, _sim, meta = match
            canonical = meta.get("name", normalized)
        else:
            concept_id = _new_concept_id(normalized)
            canonical = normalized
            ctx.vectors.add(
                CONCEPT_COLLECTION,
                concept_id,
                embedding,
                {"concept_id": concept_id, "name": canonical},
            )

        from_claims = [cid for cid in draft.from_claims if cid in valid_claim_ids]
        if concept_id in resolved:
            c = resolved[concept_id]
            _add_alias(c, normalized)
            for cid in from_claims:
                if cid not in c.from_claims:
                    c.from_claims.append(cid)
        else:
            aliases = [] if normalized == canonical else [normalized]
            resolved[concept_id] = Concept(
                id=concept_id,
                name=canonical,
                aliases=aliases,
                from_claims=list(dict.fromkeys(from_claims)),
            )

    return Concepts(source_id=inp.source_id, concepts=list(resolved.values()))


def _resolve_match(normalized: str, embedding, ctx):
    """Banded concept-merge decision.

    >= auto_merge_threshold      -> merge (confident, no LLM)
    <  similarity_threshold      -> no match (new concept)
    in the gray band             -> ask the LLM whether they are the same concept
    Returns the nearest hit tuple (id, sim, meta) to merge into, or None.
    """
    hits = ctx.vectors.nearest(CONCEPT_COLLECTION, embedding, n=1)
    if not hits:
        return None
    cid, sim, meta = hits[0]
    if sim >= ctx.settings.concept_auto_merge_threshold:
        return hits[0]
    if sim < ctx.settings.concept_similarity_threshold:
        return None
    # Gray zone: deterministic LLM adjudication.
    if _llm_same_concept(normalized, meta.get("name", ""), ctx):
        return hits[0]
    return None


_MERGE_SYSTEM = (
    "You decide whether two short technical phrases refer to the SAME underlying concept "
    "(a synonym/paraphrase), not merely a related one. Answer with exactly 'yes' or 'no'."
)


def _llm_same_concept(a: str, b: str, ctx) -> bool:
    if not b or a == b:
        return bool(b) and a == b
    ans = ctx.llm.text(
        system=_MERGE_SYSTEM,
        user=f"Phrase A: {a}\nPhrase B: {b}\nSame concept? Answer 'yes' or 'no'.",
        temperature=0,
    )
    return ans.strip().lower().startswith("y")


def _add_alias(c: Concept, phrase: str) -> None:
    if phrase != c.name and phrase not in c.aliases:
        c.aliases.append(phrase)


def _build_user_prompt(claims: Claims) -> str:
    lines = ["Claims:"]
    for c in claims.claims:
        lines.append(f"[{c.id}] {c.text}")
    return "\n".join(lines)
