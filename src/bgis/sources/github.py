"""GitHub source plugin — the original m01→m02→m03(+m05) path behind the SourcePlugin seam.

Proves the interface: `bgis run <github-url>` is unchanged, but ingestion now flows through
`GitHubSourcePlugin.ingest`. It is the only plugin that returns a `Repository`, because
Module 9's sibling-repo retrieval is GitHub-native.
"""

from __future__ import annotations

from ..context import Context
from ..modules import m01_discovery, m02_ingest, m03_parse, m05_signals
from ..models import DiscoveryRequest
from ..persistence import save_artifact
from .base import IngestResult, SourcePlugin


class GitHubSourcePlugin(SourcePlugin):
    kind = "github"

    def matches(self, ref: str) -> bool:
        try:
            m01_discovery.normalize_github_url(ref)
            return True
        except ValueError:
            return False

    def ingest(self, ref: str, ctx: Context) -> IngestResult:
        source = m01_discovery.run(DiscoveryRequest(url=ref), ctx)
        save_artifact(ctx.settings, "raw", source.source_id, source)

        repo = m02_ingest.run(source, ctx)
        save_artifact(ctx.settings, "raw", f"{repo.source_id}_repo", repo)

        parsed = m03_parse.run(repo, ctx)
        save_artifact(ctx.settings, "parsed", parsed.source_id, parsed)

        signals = m05_signals.run(repo, ctx)
        save_artifact(ctx.settings, "signals", signals.source_id, signals)

        return IngestResult(source=source, parsed=parsed, signals=signals, repo=repo)
