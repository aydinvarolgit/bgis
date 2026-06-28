"""SourcePlugin interface — the seam that makes BGIS source-agnostic.

Everything after Module 3 consumes a generic `ParsedDocuments`, so a new source only has
to turn a reference (a URL, or a `kind:query` string) into one. A plugin owns one `kind`
and produces an `IngestResult`: the parsed documents (required), the signals (numeric
metadata; empty for sources that have none), and — only for GitHub — the raw `Repository`,
which Module 9's sibling-repo retrieval still needs. Non-GitHub sources leave `repo=None`
and the pipeline simply skips that GitHub-native retrieval step.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..context import Context
from ..models import ParsedDocuments, Repository, Signals, Source


@dataclass
class IngestResult:
    source: Source
    parsed: ParsedDocuments
    signals: Signals
    repo: Optional[Repository] = None  # GitHub-only; enables Module 9 sibling retrieval


class SourcePlugin(ABC):
    kind: str  # "github" | "hn" | "arxiv" | "gh_discussions" | "rss"

    @abstractmethod
    def matches(self, ref: str) -> bool:
        """True if this plugin owns the given reference (URL or `kind:query`)."""

    @abstractmethod
    def ingest(self, ref: str, ctx: Context) -> IngestResult:
        """Turn the reference into parsed documents (+ signals, + repo for GitHub)."""
