"""Backend 4 — open-web search via DuckDuckGo (keyless `ddgs` library).

For each concept (capped at `retrieval_websearch_max_concepts`), run a DuckDuckGo text search for
the concept name (+ its first alias) and turn the top hits into Candidates tagged with that
concept_id. m09 still embeds each candidate and gates it against the concept's vector, so off-topic
web results are dropped — the relevance bar is identical to every other backend.

DuckDuckGo needs no API key and no account (Microsoft retired the Bing Search APIs ~Aug 2025, so
it is the keyless open-web option here). The `search` callable is injectable — it takes
(query, n) and returns a list of {title, href, body} dicts — so unit tests never touch the network;
any failure is swallowed (fail-soft) and never breaks the run. To use a self-hosted SearXNG
meta-search instead, inject a `search` that hits its JSON endpoint and maps results to the same
three keys — no other change needed.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from ..context import Context
from ..models import Claims, Concepts, Gaps
from .base import Candidate, RetrievalBackend

_TAG_RE = re.compile(r"<[^>]+>")


def _strip(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text or "")).strip()


def _default_search(query: str, n: int) -> list[dict]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=n))


class WebSearchBackend(RetrievalBackend):
    name = "web_search"

    def __init__(self, search: Optional[Callable[[str, int], list[dict]]] = None):
        self._search = search or _default_search

    def candidates(
        self, gaps: Gaps, concepts: Concepts, claims: Claims, ctx: Context
    ) -> list[Candidate]:
        n = ctx.settings.retrieval_websearch_per_concept
        question_for: dict[str, str] = {}
        for g in gaps.gaps:
            question_for.setdefault(g.concept_id, g.question)

        out: list[Candidate] = []
        for concept in concepts.concepts[: ctx.settings.retrieval_websearch_max_concepts]:
            query = " ".join([concept.name, *concept.aliases[:1]]).strip()
            if not query:
                continue
            question = question_for.get(concept.id, f"What does the web say about '{concept.name}'?")
            try:
                results = self._search(query, n)
            except Exception:
                continue  # fail-soft: a search failure never breaks the run
            for r in (results or [])[:n]:
                title = (r.get("title") or "").strip()
                body = _strip(r.get("body") or "")
                url = r.get("href") or r.get("url") or ""
                if not title and not body:
                    continue
                out.append(
                    Candidate(
                        text=f"{title}. {body}",
                        summary=f"[web] {title}: {body[:180]}",
                        source_url=url,
                        concept_id=concept.id,
                        question=question,
                    )
                )
        return out
