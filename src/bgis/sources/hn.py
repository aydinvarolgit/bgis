"""Hacker News source plugin — the first opinion source.

Reference form: `hn:<query>` (e.g. `hn:agent memory`). Uses the public Algolia HN API
(no auth, http only):
  - search:  https://hn.algolia.com/api/v1/search?query=<q>&tags=story  -> top stories
  - item:    https://hn.algolia.com/api/v1/items/<id>                   -> text + comments

Each story becomes an `article` document (the post itself) and its comment thread a
`discussion` document. Comments are discourse -> Module 4 will type most of them as
`opinion`, which Gate A routes into belief stances rather than confidence.

The HTTP getter is injectable (`fetch`) so unit tests never hit the network.
"""

from __future__ import annotations

import hashlib
import html
import re
from typing import Callable, Optional

from ..context import Context
from ..models import Document, ParsedDocuments, Signals, Source
from ..persistence import save_artifact
from .base import IngestResult, SourcePlugin

SEARCH_URL = "https://hn.algolia.com/api/v1/search?query={q}&tags=story"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"

MAX_STORIES = 5
MAX_COMMENTS = 15
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    out = re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text or "")))
    return re.sub(r"\s+([,.;:!?])", r"\1", out).strip()  # drop space before punctuation


def _default_fetch(url: str) -> dict:
    import requests

    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


class HNSourcePlugin(SourcePlugin):
    kind = "hn"

    def __init__(self, fetch: Optional[Callable[[str], dict]] = None):
        self._fetch = fetch or _default_fetch

    def matches(self, ref: str) -> bool:
        return ref.strip().lower().startswith("hn:")

    def ingest(self, ref: str, ctx: Context) -> IngestResult:
        query = ref.split(":", 1)[1].strip()
        source_id = "src_" + hashlib.sha256(f"hn:{query}".encode()).hexdigest()[:8]

        search = self._fetch(SEARCH_URL.format(q=query.replace(" ", "+")))
        hits = sorted(
            search.get("hits", []),
            key=lambda h: h.get("points") or 0,
            reverse=True,
        )[:MAX_STORIES]

        documents: list[Document] = []
        for hit in hits:
            item = self._fetch(ITEM_URL.format(id=hit.get("objectID")))
            documents.extend(_story_documents(item))

        source = Source(source_id=source_id, type="hn", url=ref, status="ingested")
        save_artifact(ctx.settings, "raw", source.source_id, source)

        parsed = ParsedDocuments(source_id=source_id, documents=documents)
        save_artifact(ctx.settings, "parsed", parsed.source_id, parsed)

        # HN has no authority signal (no stars); leave signals empty -> Module 11 uses its
        # baseline authority. Opinions are excluded from confidence anyway.
        signals = Signals(source_id=source_id, signals=[])
        save_artifact(ctx.settings, "signals", signals.source_id, signals)

        return IngestResult(source=source, parsed=parsed, signals=signals, repo=None)


def _story_documents(item: dict) -> list[Document]:
    """A story -> an `article` doc (the post) + a `discussion` doc (top comments)."""
    title = (item.get("title") or "").strip()
    if not title:
        return []
    docs: list[Document] = []

    story_text = _strip_html(item.get("text") or "")
    body = title if not story_text else f"{title}\n\n{story_text}"
    docs.append(
        Document(
            type="article",
            title=title,
            text=body,
            meta={"points": item.get("points") or 0, "hn_id": item.get("id")},
        )
    )

    comments = []
    for child in (item.get("children") or []):
        txt = _strip_html(child.get("text") or "")
        if txt:
            comments.append(txt)
        if len(comments) >= MAX_COMMENTS:
            break
    if comments:
        joined = "\n\n---\n\n".join(comments)
        docs.append(
            Document(
                type="discussion",
                title=f"Discussion: {title}",
                text=f"Hacker News discussion of '{title}':\n\n{joined}",
                meta={"n_comments": len(comments), "hn_id": item.get("id")},
            )
        )
    return docs
