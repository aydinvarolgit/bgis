"""Module 9 — Retrieval Engine.

Acquire EXTERNAL evidence for the gap questions and attach each piece to the source concept it
corroborates. Two layers:

  1. GitHub-native sibling search (always on, only when the source is a repo): find OTHER repos
     related to this one — repos sharing its distinctive topics + repos linked from its README —
     and route each to its best-matching concept by embedding similarity. This creates multi-source
     convergence within a single run: a sibling project becomes external support for a concept.

  2. Pluggable `RetrievalBackend`s (opt-in via `retrieval_use_*` settings; see bgis.retrieval):
     reuse-the-SourcePlugins (gap-kind routed), local-corpus embed-search, and keyless external
     APIs (Wikipedia/Semantic Scholar/Crossref). These work for ANY source type, so a web/arxiv/hn
     run can finally pull corroboration instead of skipping retrieval. All default OFF.

In:  Gaps + Concepts + Claims + (optional) Repository
Out: RetrievedEvidence{ items: [ RetrievedItem{ concept_id, question, source_url, summary } ] }

Every candidate — GitHub sibling, plugin hit, corpus doc, or API result — is embedded and gated
against a concept at `retrieval_match_threshold`, so the relevance bar is identical across layers.
GitHub via PyGithub; embeddings via nomic; backends inject their own HTTP getters for offline tests.
"""

from __future__ import annotations

import re
from typing import Optional

from ..context import Context
from ..models import (
    Claims,
    Concepts,
    Gaps,
    Repository,
    RetrievedEvidence,
    RetrievedItem,
)
from ..retrieval import RetrievalBackend, best_concept, concept_rep, cos, default_backends

# Topics too generic to find *related* (vs merely same-ecosystem) repos.
GENERIC_TOPICS = {
    "ai", "llm", "llms", "ml", "machine-learning", "deep-learning", "python", "javascript",
    "typescript", "rust", "go", "nlp", "genai", "gpt", "chatgpt", "openai", "api", "sdk",
    "framework", "library", "tool", "tools", "application", "app", "software",
}

_GH_LINK = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
# README links that aren't repos (badges, the repo's own subpaths, etc.).
_NON_REPO = {"sponsors", "marketplace", "features", "about", "topics", "search", "settings"}


def run(
    gaps: Gaps,
    concepts: Concepts,
    claims: Claims,
    repo: Optional[Repository],
    ctx: Context,
    gh=None,
    backends: Optional[list[RetrievalBackend]] = None,
) -> RetrievedEvidence:
    if not concepts.concepts:
        return RetrievedEvidence(source_id=concepts.source_id, items=[])

    # Pre-embed a rich concept representation (name + aliases + claim texts) once for matching.
    claim_by_id = {c.id: c for c in claims.claims}
    concept_vecs = [(c, ctx.embedder.embed(concept_rep(c, claim_by_id))) for c in concepts.concepts]
    by_id = {c.id: v for c, v in concept_vecs}
    question_for = _first_question_by_concept(gaps)
    threshold = ctx.settings.retrieval_match_threshold

    items: list[RetrievedItem] = []
    seen_urls: set[str] = set()
    per_concept: dict[str, int] = {}

    def _add(text, summary, url, hint, question_default):
        """Embed -> route to a concept -> threshold-gate -> append (dedup + per-concept cap)."""
        if url and url in seen_urls:
            return
        vec = ctx.embedder.embed(text)
        if hint and hint in by_id:
            concept_id, sim = hint, cos(vec, by_id[hint])
        else:
            concept, sim = best_concept(vec, concept_vecs)
            concept_id = concept.id if concept else None
        if concept_id is None or sim < threshold:
            return
        if per_concept.get(concept_id, 0) >= ctx.settings.retrieval_max_per_concept:
            return
        if url:
            seen_urls.add(url)
        per_concept[concept_id] = per_concept.get(concept_id, 0) + 1
        items.append(
            RetrievedItem(
                concept_id=concept_id,
                question=question_for.get(concept_id, question_default),
                source_url=url,
                summary=summary,
            )
        )

    # 1) GitHub-native sibling search (only when the source is a repo).
    if repo is not None:
        gh = gh or _build_client(ctx)
        self_fullname = f"{repo.owner}/{repo.name}".lower()
        for full_name, description, topics, stars, url in _candidate_repos(
            repo, gh, ctx, self_fullname
        ):
            text = f"{full_name}. {description}. topics: {', '.join(topics)}"
            _add(
                text,
                f"{full_name} ({stars}★): {description or 'no description'}",
                url,
                hint=None,
                question_default=f"Related project?",
            )

    # 2) Pluggable backends (opt-in; default_backends reads the retrieval_use_* settings).
    for backend in (backends if backends is not None else default_backends(ctx)):
        try:
            cands = backend.candidates(gaps, concepts, claims, ctx)
        except Exception:
            continue  # a misbehaving backend never breaks the run
        for cand in cands:
            _add(
                cand.text,
                cand.summary,
                cand.source_url,
                hint=cand.concept_id,
                question_default=cand.question or "Relevant external evidence?",
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


def _first_question_by_concept(gaps: Gaps) -> dict[str, str]:
    out: dict[str, str] = {}
    for g in gaps.gaps:
        out.setdefault(g.concept_id, g.question)
    return out


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
