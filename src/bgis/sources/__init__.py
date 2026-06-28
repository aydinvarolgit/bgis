"""Source plugin registry. `resolve(ref)` returns the first plugin that owns the ref."""

from __future__ import annotations

from .arxiv import ArxivSourcePlugin
from .base import IngestResult, SourcePlugin
from .gh_discussions import GHDiscussionsSourcePlugin
from .github import GitHubSourcePlugin
from .hn import HNSourcePlugin
from .rss import RSSSourcePlugin
from .web import WebArticleSourcePlugin

# Order matters when two plugins could match. The kind:-prefixed plugins are disjoint; the only
# overlap is URL-shaped refs: GitHubSourcePlugin claims github.com URLs and MUST precede the
# web-article plugin, which catches any other bare http(s) URL (or an explicit `url:` ref).
SOURCE_PLUGINS: list[SourcePlugin] = [
    GitHubSourcePlugin(),
    HNSourcePlugin(),
    ArxivSourcePlugin(),
    GHDiscussionsSourcePlugin(),
    RSSSourcePlugin(),
    WebArticleSourcePlugin(),
]


def resolve(ref: str) -> SourcePlugin:
    for plugin in SOURCE_PLUGINS:
        if plugin.matches(ref):
            return plugin
    raise ValueError(
        f"no source plugin matches ref {ref!r}; expected a GitHub URL or a 'kind:query' "
        f"like 'hn:agent memory'"
    )


__all__ = ["IngestResult", "SourcePlugin", "SOURCE_PLUGINS", "resolve"]
