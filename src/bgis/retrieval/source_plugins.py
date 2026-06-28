"""Backend 1 — reuse the existing SourcePlugins as a retriever, routed by gap KIND.

Each Module-8 gap already carries a `concept_id` AND a `kind` (competitor/adoption/research/
alternative/risk/validation). Instead of a generic web search, we fire the gap's QUESTION at
whichever existing SourcePlugin best answers that kind, and attach the results to the gap's
concept:

    research, validation     -> arXiv   (peer-reviewed findings)
    adoption, risk           -> Hacker News (practitioner discourse)
    competitor, alternative  -> GitHub repo search (sibling projects)

We reuse each plugin's own endpoint + parser (arxiv._parse_atom, hn search hits, GitHub
`search_repositories`) but DO NOT run a full ingest (no new Source/artifacts) — this is
retrieval, not ingestion. Every HTTP getter is injectable so unit tests stay offline.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..context import Context
from ..models import Claims, Concepts, Gaps
from ..sources import arxiv as arxiv_src
from ..sources import hn as hn_src
from .base import Candidate, RetrievalBackend

# gap kind -> which plugin answers it best.
KIND_TO_PLUGIN = {
    "research": "arxiv",
    "validation": "arxiv",
    "adoption": "hn",
    "risk": "hn",
    "competitor": "github",
    "alternative": "github",
}


class SourcePluginBackend(RetrievalBackend):
    name = "source_plugins"

    def __init__(
        self,
        arxiv_fetch: Optional[Callable[[str], str]] = None,
        hn_fetch: Optional[Callable[[str], dict]] = None,
        gh=None,
    ):
        self._arxiv_fetch = arxiv_fetch or arxiv_src._default_fetch
        self._hn_fetch = hn_fetch or hn_src._default_fetch
        self._gh = gh  # PyGithub-like; lazily built if needed

    def candidates(
        self, gaps: Gaps, concepts: Concepts, claims: Claims, ctx: Context
    ) -> list[Candidate]:
        concept_ids = {c.id for c in concepts.concepts}
        per_gap = ctx.settings.retrieval_plugin_per_gap
        out: list[Candidate] = []
        # One query per gap, capped; only gaps whose concept is in this run.
        queried = 0
        for gap in gaps.gaps:
            if queried >= ctx.settings.retrieval_plugin_max_gaps:
                break
            if gap.concept_id not in concept_ids:
                continue
            plugin = KIND_TO_PLUGIN.get(gap.kind)
            if not plugin:
                continue
            queried += 1
            try:
                if plugin == "arxiv":
                    out += self._arxiv(gap, per_gap)
                elif plugin == "hn":
                    out += self._hn(gap, per_gap)
                elif plugin == "github":
                    out += self._github(gap, per_gap, ctx)
            except Exception:
                continue  # fail-soft: a dead API never breaks the run
        return out

    # --- per-plugin queries (reuse the plugin's endpoint + parser) ----------------------- #
    def _arxiv(self, gap, n) -> list[Candidate]:
        url = arxiv_src.QUERY_URL.format(q=gap.question.replace(" ", "+"), n=n)
        docs = arxiv_src._parse_atom(self._arxiv_fetch(url))[:n]
        return [
            Candidate(
                text=d.text,
                summary=f"[arxiv] {d.title}: {d.text[len(d.title):].strip()[:200]}",
                source_url=d.meta.get("url", ""),
                concept_id=gap.concept_id,
                question=gap.question,
            )
            for d in docs
        ]

    def _hn(self, gap, n) -> list[Candidate]:
        data = self._hn_fetch(hn_src.SEARCH_URL.format(q=gap.question.replace(" ", "+")))
        hits = sorted(
            data.get("hits", []), key=lambda h: h.get("points") or 0, reverse=True
        )[:n]
        out: list[Candidate] = []
        for h in hits:
            title = (h.get("title") or "").strip()
            if not title:
                continue
            oid = h.get("objectID")
            url = h.get("url") or (f"https://news.ycombinator.com/item?id={oid}" if oid else "")
            out.append(
                Candidate(
                    text=title,
                    summary=f"[hn {h.get('points', 0)}pts] {title}",
                    source_url=url,
                    concept_id=gap.concept_id,
                    question=gap.question,
                )
            )
        return out

    def _github(self, gap, n, ctx) -> list[Candidate]:
        gh = self._gh or _gh_client(ctx)
        results = gh.search_repositories(query=gap.question, sort="stars", order="desc")
        out: list[Candidate] = []
        for r in _take(results, n):
            fn = getattr(r, "full_name", None)
            if not fn:
                continue
            desc = getattr(r, "description", "") or ""
            stars = getattr(r, "stargazers_count", 0) or 0
            out.append(
                Candidate(
                    text=f"{fn}. {desc}",
                    summary=f"[github {stars}★] {fn}: {desc or 'no description'}",
                    source_url=f"https://github.com/{fn}",
                    concept_id=gap.concept_id,
                    question=gap.question,
                )
            )
        return out


def _gh_client(ctx: Context):
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
