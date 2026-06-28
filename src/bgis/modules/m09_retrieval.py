"""Module 9 — Retrieval Engine (GitHub-native).

Acquire external evidence for the gap questions without leaving GitHub: find OTHER repos
related to this source (repos sharing its distinctive topics + repos linked from its README),
fetch their metadata, and attach each as corroborating evidence to the source concept it best
matches (by embedding similarity). This is what creates multi-source convergence within a
single run: a sibling project becomes external support for a shared concept.

In:  Gaps + Concepts + Claims + Repository
Out: RetrievedEvidence{ items: [ RetrievedItem{ concept_id, question, source_url, summary } ] }

GitHub via PyGithub (token reused from settings). Embeddings: nomic. No web search, no new deps.
`gh` is injectable for tests.
"""

from __future__ import annotations

import math
import re

from ..context import Context
from ..models import Claims, Concepts, Gaps, Repository, RetrievedEvidence, RetrievedItem

# A concept matches a candidate repo better when represented by its name + aliases + a few of
# its claim texts (not just the bare name). Cap claims so the rep stays focused.
MAX_CLAIMS_IN_REP = 3

# Topics too generic to find *related* (vs merely same-ecosystem) repos. Mirrors the spirit of
# m06's GENERIC_TOKENS but at the topic level.
GENERIC_TOPICS = {
    "ai", "llm", "llms", "ml", "machine-learning", "deep-learning", "python", "javascript",
    "typescript", "rust", "go", "nlp", "genai", "gpt", "chatgpt", "openai", "api", "sdk",
    "framework", "library", "tool", "tools", "application", "app", "software",
}

_GH_LINK = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
# README links that aren't repos (badges, the repo's own subpaths, etc.).
_NON_REPO = {"sponsors", "marketplace", "features", "about", "topics", "search", "settings"}


def run(
    gaps: Gaps, concepts: Concepts, claims: Claims, repo: Repository, ctx: Context, gh=None
) -> RetrievedEvidence:
    if not concepts.concepts:
        return RetrievedEvidence(source_id=concepts.source_id, items=[])

    gh = gh or _build_client(ctx)
    self_fullname = f"{repo.owner}/{repo.name}".lower()

    candidates = _candidate_repos(repo, gh, ctx, self_fullname)

    # Pre-embed a rich concept representation (name + aliases + claim texts) once for matching.
    claim_by_id = {c.id: c for c in claims.claims}
    concept_vecs = [
        (c, ctx.embedder.embed(_concept_rep(c, claim_by_id))) for c in concepts.concepts
    ]
    question_for = _first_question_by_concept(gaps)

    items: list[RetrievedItem] = []
    seen: set[str] = set()
    for full_name, description, topics, stars, url in candidates:
        if full_name in seen:
            continue
        seen.add(full_name)
        text = f"{full_name}. {description}. topics: {', '.join(topics)}"
        cand_vec = ctx.embedder.embed(text)
        concept, sim = _best_concept(cand_vec, concept_vecs)
        if concept is None or sim < ctx.settings.retrieval_match_threshold:
            continue
        items.append(
            RetrievedItem(
                concept_id=concept.id,
                question=question_for.get(
                    concept.id, f"Related project to '{concept.name}'?"
                ),
                source_url=url,
                summary=f"{full_name} ({stars}★): {description or 'no description'}",
            )
        )

    return RetrievedEvidence(source_id=concepts.source_id, items=items)


def _candidate_repos(repo: Repository, gh, ctx: Context, self_fullname: str):
    """Return (full_name, description, topics, stars, url) for related repos.

    Two GitHub-native sources: shared-topic search + README outbound repo links.
    """
    out: list[tuple] = []
    cap = ctx.settings.retrieval_max_candidates

    # 1) Shared distinctive topics -> top repos by stars.
    distinctive = [t for t in repo.topics if t.lower() not in GENERIC_TOPICS]
    for topic in distinctive[:3]:
        try:
            results = gh.search_repositories(query=f"topic:{topic}", sort="stars", order="desc")
        except Exception:
            continue
        for r in _take(results, cap):
            fn = _full_name(r)
            if not fn or fn.lower() == self_fullname:
                continue
            out.append((fn.lower(), _desc(r), _topics(r), _stars(r),
                        f"https://github.com/{fn}"))

    # 2) README outbound github repo links.
    for owner, name in _readme_repo_links(repo.readme_raw):
        fn = f"{owner}/{name}"
        if fn.lower() == self_fullname or name.lower() in _NON_REPO:
            continue
        try:
            r = gh.get_repo(fn)
        except Exception:
            continue
        out.append((fn.lower(), _desc(r), _topics(r), _stars(r), f"https://github.com/{fn}"))

    return out[: cap * 2]  # routing/threshold trims further


def _readme_repo_links(readme: str) -> list[tuple[str, str]]:
    seen, links = set(), []
    for owner, name in _GH_LINK.findall(readme or ""):
        name = name.removesuffix(".git")
        key = f"{owner}/{name}".lower()
        if key in seen:
            continue
        seen.add(key)
        links.append((owner, name))
    return links


def _concept_rep(concept, claim_by_id) -> str:
    """Richer match text: concept name + aliases + a few of its claim texts."""
    parts = [concept.name, *concept.aliases]
    for cid in concept.from_claims[:MAX_CLAIMS_IN_REP]:
        c = claim_by_id.get(cid)
        if c:
            parts.append(c.text)
    return ". ".join(parts)


def _first_question_by_concept(gaps: Gaps) -> dict[str, str]:
    out: dict[str, str] = {}
    for g in gaps.gaps:
        out.setdefault(g.concept_id, g.question)
    return out


def _best_concept(vec, concept_vecs):
    best, best_sim = None, -1.0
    for concept, cvec in concept_vecs:
        s = _cos(vec, cvec)
        if s > best_sim:
            best, best_sim = concept, s
    return best, best_sim


def _cos(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# --- PyGithub adapters (kept tiny so search/get_repo objects stay swappable in tests) ---
def _build_client(ctx: Context):
    from github import Github

    token = ctx.settings.github_token
    return Github(token) if token else Github()


def _take(results, n):
    out = []
    for r in results:
        out.append(r)
        if len(out) >= n:
            break
    return out


def _full_name(r):
    return getattr(r, "full_name", None)


def _desc(r):
    return getattr(r, "description", "") or ""


def _topics(r):
    try:
        return list(r.get_topics())
    except Exception:
        return list(getattr(r, "topics", []) or [])


def _stars(r):
    return getattr(r, "stargazers_count", 0) or 0
