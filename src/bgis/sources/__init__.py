"""Source plugin registry. `resolve(ref)` returns the first plugin that owns the ref."""

from __future__ import annotations

from .arxiv import ArxivSourcePlugin
from .base import IngestResult, SourcePlugin
from .gh_discussions import GHDiscussionsSourcePlugin
from .github import GitHubSourcePlugin
from .hn import HNSourcePlugin
from .rss import RSSSourcePlugin

# Order matters only when two plugins could match; today they are disjoint (each owns a
# distinct URL shape or `kind:` prefix).
SOURCE_PLUGINS: list[SourcePlugin] = [
    GitHubSourcePlugin(),
    HNSourcePlugin(),
    ArxivSourcePlugin(),
    GHDiscussionsSourcePlugin(),
    RSSSourcePlugin(),
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
