"""arXiv source plugin — the evidence / findings layer.

Reference form: `arxiv:<query>` (e.g. `arxiv:retrieval augmented generation`). Uses the
public arXiv Atom API (no auth, no new dependency — parsed with stdlib xml.etree):
  http://export.arxiv.org/api/query?search_query=all:<q>&max_results=N

Each paper becomes a `paper` document from its title + abstract. Module 4 types `paper`
content as a mix of `finding` (results) and `opinion` (the authors' thesis) — so papers
feed hard evidence into beliefs while still contributing stance.

The HTTP getter is injectable (`fetch` returns the raw Atom XML string) so unit tests
never hit the network.
"""

from __future__ import annotations

import hashlib
import re
from typing import Callable, Optional
from xml.etree import ElementTree as ET

from ..context import Context
from ..models import Document, ParsedDocuments, Signals, Source
from ..persistence import save_artifact
from .base import IngestResult, SourcePlugin

QUERY_URL = (
    "http://export.arxiv.org/api/query?search_query=all:{q}"
    "&start=0&max_results={n}&sortBy=relevance"
)
MAX_PAPERS = 5
_ATOM = "{http://www.w3.org/2005/Atom}"


def _default_fetch(url: str) -> str:
    import requests

    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


class ArxivSourcePlugin(SourcePlugin):
    kind = "arxiv"

    def __init__(self, fetch: Optional[Callable[[str], str]] = None):
        self._fetch = fetch or _default_fetch

    def matches(self, ref: str) -> bool:
        return ref.strip().lower().startswith("arxiv:")

    def ingest(self, ref: str, ctx: Context) -> IngestResult:
        query = ref.split(":", 1)[1].strip()
        source_id = "src_" + hashlib.sha256(f"arxiv:{query}".encode()).hexdigest()[:8]

        xml = self._fetch(QUERY_URL.format(q=query.replace(" ", "+"), n=MAX_PAPERS))
        documents = _parse_atom(xml)[:MAX_PAPERS]

        source = Source(source_id=source_id, type="arxiv", url=ref, status="ingested")
        save_artifact(ctx.settings, "raw", source.source_id, source)

        parsed = ParsedDocuments(source_id=source_id, documents=documents)
        save_artifact(ctx.settings, "parsed", parsed.source_id, parsed)

        signals = Signals(source_id=source_id, signals=[])
        save_artifact(ctx.settings, "signals", signals.source_id, signals)

        return IngestResult(source=source, parsed=parsed, signals=signals, repo=None)


def _parse_atom(xml: str) -> list[Document]:
    root = ET.fromstring(xml)
    docs: list[Document] = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = _clean(entry.findtext(f"{_ATOM}title") or "")
        abstract = _clean(entry.findtext(f"{_ATOM}summary") or "")
        url = (entry.findtext(f"{_ATOM}id") or "").strip()
        if not title:
            continue
        body = title if not abstract else f"{title}\n\n{abstract}"
        docs.append(
            Document(
                type="paper",
                title=title,
                text=body,
                meta={"url": url},
            )
        )
    return docs
