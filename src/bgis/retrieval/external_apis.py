"""Backend 3 — keyless public knowledge APIs: Wikipedia + Semantic Scholar + Crossref.

For each concept (capped at `retrieval_external_max_concepts`), query three keyless APIs with the
concept's name and turn the top hits into Candidates tagged with that concept_id. m09 still embeds
each candidate and gates it against the concept's vector, so off-topic API hits are dropped.

  Wikipedia        — encyclopedic grounding / definitions / prior art
  Semantic Scholar — peer-reviewed papers (title + abstract + citation count)
  Crossref         — scholarly works metadata (broad coverage, DOIs)

All three are no-auth REST endpoints. Each getter is injectable (returns parsed JSON) so unit
tests never hit the network; any API failing is swallowed (fail-soft) and never breaks the run.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from ..context import Context
from ..models import Claims, Concepts, Gaps
from .base import Candidate, RetrievalBackend

WIKI_URL = (
    "https://en.wikipedia.org/w/api.php?action=query&list=search"
    "&srsearch={q}&srlimit={n}&format=json"
)
S2_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
    "?query={q}&limit={n}&fields=title,abstract,url,year,citationCount"
)
CROSSREF_URL = "https://api.crossref.org/works?query={q}&rows={n}"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text or "")).strip()


def _default_json_fetch(url: str) -> dict:
    import requests

    r = requests.get(url, timeout=20, headers={"User-Agent": "BGIS/1.0 (retrieval)"})
    r.raise_for_status()
    return r.json()


class ExternalApiBackend(RetrievalBackend):
    name = "external_apis"

    def __init__(
        self,
        wiki_fetch: Optional[Callable[[str], dict]] = None,
        s2_fetch: Optional[Callable[[str], dict]] = None,
        crossref_fetch: Optional[Callable[[str], dict]] = None,
    ):
        self._wiki = wiki_fetch or _default_json_fetch
        self._s2 = s2_fetch or _default_json_fetch
        self._crossref_fetch = crossref_fetch or _default_json_fetch

    def candidates(
        self, gaps: Gaps, concepts: Concepts, claims: Claims, ctx: Context
    ) -> list[Candidate]:
        n = ctx.settings.retrieval_external_per_api
        question_for: dict[str, str] = {}
        for g in gaps.gaps:
            question_for.setdefault(g.concept_id, g.question)
        out: list[Candidate] = []
        for concept in concepts.concepts[: ctx.settings.retrieval_external_max_concepts]:
            q = " ".join([concept.name, *concept.aliases[:1]]).strip()
            if not q:
                continue
            qe = q.replace(" ", "+")
            question = question_for.get(concept.id, f"Background on '{concept.name}'?")
            for fn in (self._wikipedia, self._semantic_scholar, self._crossref):
                try:
                    out += fn(qe, n, concept.id, question)
                except Exception:
                    continue  # fail-soft per API
        return out

    def _wikipedia(self, qe, n, cid, question) -> list[Candidate]:
        data = self._wiki(WIKI_URL.format(q=qe, n=n))
        out: list[Candidate] = []
        for hit in (data.get("query", {}) or {}).get("search", [])[:n]:
            title = hit.get("title", "")
            snippet = _strip(hit.get("snippet", ""))
            if not title:
                continue
            slug = title.replace(" ", "_")
            out.append(
                Candidate(
                    text=f"{title}. {snippet}",
                    summary=f"[wikipedia] {title}: {snippet[:200]}",
                    source_url=f"https://en.wikipedia.org/wiki/{slug}",
                    concept_id=cid,
                    question=question,
                )
            )
        return out

    def _semantic_scholar(self, qe, n, cid, question) -> list[Candidate]:
        data = self._s2(S2_URL.format(q=qe, n=n))
        out: list[Candidate] = []
        for p in (data.get("data") or [])[:n]:
            title = (p.get("title") or "").strip()
            if not title:
                continue
            abstract = _strip(p.get("abstract") or "")
            cites = p.get("citationCount", 0) or 0
            out.append(
                Candidate(
                    text=f"{title}. {abstract}",
                    summary=f"[semanticscholar {cites} cites] {title}: {abstract[:180]}",
                    source_url=p.get("url") or "",
                    concept_id=cid,
                    question=question,
                )
            )
        return out

    def _crossref(self, qe, n, cid, question) -> list[Candidate]:
        data = self._crossref_call(qe, n)
        out: list[Candidate] = []
        for it in ((data.get("message", {}) or {}).get("items", []) or [])[:n]:
            titles = it.get("title") or []
            title = (titles[0] if titles else "").strip()
            if not title:
                continue
            out.append(
                Candidate(
                    text=title,
                    summary=f"[crossref] {title} ({it.get('type', 'work')})",
                    source_url=it.get("URL") or "",
                    concept_id=cid,
                    question=question,
                )
            )
        return out

    def _crossref_call(self, qe, n) -> dict:
        return self._crossref_fetch(CROSSREF_URL.format(q=qe, n=n))
