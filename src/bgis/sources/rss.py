"""RSS / Atom source plugin — expert blogs, essays, narrative.

Reference forms:
  - `rss:<feed-url>`  parse one feed (e.g. `rss:https://simonwillison.net/atom/everything/`)
  - `rss:all`         parse the curated feed list in settings (`rss_feeds`)

Each entry becomes an `article` document from its title + content/summary. Module 4 types
`article` content as a mix of `opinion` (the author's thesis) and `finding`.

The raw-feed getter is injectable (`fetch` returns the feed XML string) so unit tests parse a
canned feed string and never hit the network. Parsing uses `feedparser`.
"""

from __future__ import annotations

import hashlib
import re
from typing import Callable, Optional

from ..context import Context
from ..models import Document, ParsedDocuments, Signals, Source
from ..persistence import save_artifact
from .base import IngestResult, SourcePlugin

MAX_ENTRIES_PER_FEED = 10
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(text: str) -> str:
    import html

    out = re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text or "")))
    return re.sub(r"\s+([,.;:!?])", r"\1", out).strip()  # drop space before punctuation


def _default_fetch(url: str) -> str:
    import requests

    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text


class RSSSourcePlugin(SourcePlugin):
    kind = "rss"

    def __init__(self, fetch: Optional[Callable[[str], str]] = None):
        self._fetch = fetch or _default_fetch

    def matches(self, ref: str) -> bool:
        return ref.strip().lower().startswith("rss:")

    def ingest(self, ref: str, ctx: Context) -> IngestResult:
        target = ref.split(":", 1)[1].strip()
        if target.lower() == "all":
            feeds = list(ctx.settings.rss_feeds)
            key = "rss:all"
        else:
            feeds = [target]
            key = f"rss:{target}"
        source_id = "src_" + hashlib.sha256(key.encode()).hexdigest()[:8]

        documents: list[Document] = []
        for feed_url in feeds:
            documents.extend(_feed_documents(self._fetch(feed_url)))

        source = Source(source_id=source_id, type="rss", url=ref, status="ingested")
        save_artifact(ctx.settings, "raw", source.source_id, source)

        parsed = ParsedDocuments(source_id=source_id, documents=documents)
        save_artifact(ctx.settings, "parsed", parsed.source_id, parsed)

        signals = Signals(source_id=source_id, signals=[])
        save_artifact(ctx.settings, "signals", signals.source_id, signals)

        return IngestResult(source=source, parsed=parsed, signals=signals, repo=None)


def _entry_text(entry) -> str:
    content = entry.get("content")
    if content:
        raw = content[0].get("value", "")
    else:
        raw = entry.get("summary", "")
    return _strip(raw)


def _feed_documents(xml: str) -> list[Document]:
    import feedparser

    feed = feedparser.parse(xml)
    docs: list[Document] = []
    for entry in feed.entries[:MAX_ENTRIES_PER_FEED]:
        title = _strip(entry.get("title", ""))
        if not title:
            continue
        text = _entry_text(entry)
        body = title if not text else f"{title}\n\n{text}"
        docs.append(
            Document(
                type="article",
                title=title,
                text=body,
                meta={"url": entry.get("link", "")},
            )
        )
    return docs
