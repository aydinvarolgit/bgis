"""Web-article source plugin — a single bare article URL (blog post, essay, news piece).

Reference forms:
  - `url:<u>`            explicit (e.g. `url:https://example.com/post`)
  - `https://...`        bare http(s) URL (convenience; GitHub URLs are claimed by the GitHub
                         plugin, which is registered earlier, so they never reach here)

Fetches the page and extracts its main content with `trafilatura` (boilerplate/nav stripped),
producing one `article` Document. Module 4 types `article` content as a mix of `opinion` (the
author's thesis) and `finding`. No `Repository`, no signals -> Module 9 is skipped and authority
falls back to the per-TYPE baseline (`web` = 0.5).

The page getter is injectable (`fetch` returns the raw HTML string) so unit tests extract from a
canned HTML string and never hit the network; trafilatura's extraction itself runs offline.
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

_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _strip(text: str) -> str:
    out = re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text or "")))
    return re.sub(r"\s+([,.;:!?])", r"\1", out).strip()


def _default_fetch(url: str) -> str:
    import requests

    r = requests.get(url, timeout=30, headers={"User-Agent": "bgis/1.0"})
    r.raise_for_status()
    return r.text


def _title_from_html(raw: str) -> str:
    m = _TITLE_RE.search(raw or "")
    return _strip(m.group(1)) if m else ""


def _extract(raw_html: str, url: str) -> tuple[str, str]:
    """(title, main_text) for a page. trafilatura strips nav/boilerplate; title from <title>."""
    import trafilatura

    text = trafilatura.extract(raw_html, url=url, include_comments=False) or ""
    return _title_from_html(raw_html), _strip(text)


class WebArticleSourcePlugin(SourcePlugin):
    kind = "web"

    def __init__(self, fetch: Optional[Callable[[str], str]] = None):
        self._fetch = fetch or _default_fetch

    def matches(self, ref: str) -> bool:
        s = ref.strip().lower()
        return s.startswith("url:") or s.startswith(("http://", "https://"))

    def _url(self, ref: str) -> str:
        s = ref.strip()
        return s.split(":", 1)[1].strip() if s.lower().startswith("url:") else s

    def ingest(self, ref: str, ctx: Context) -> IngestResult:
        url = self._url(ref)
        source_id = "src_" + hashlib.sha256(f"url:{url}".encode()).hexdigest()[:8]

        title, text = _extract(self._fetch(url), url)
        title = title or url
        body = title if not text else f"{title}\n\n{text}"
        documents = [Document(type="article", title=title, text=body, meta={"url": url})]

        source = Source(source_id=source_id, type="web", url=ref, status="ingested")
        save_artifact(ctx.settings, "raw", source.source_id, source)

        parsed = ParsedDocuments(source_id=source_id, documents=documents)
        save_artifact(ctx.settings, "parsed", parsed.source_id, parsed)

        signals = Signals(source_id=source_id, signals=[])
        save_artifact(ctx.settings, "signals", signals.source_id, signals)

        return IngestResult(source=source, parsed=parsed, signals=signals, repo=None)
