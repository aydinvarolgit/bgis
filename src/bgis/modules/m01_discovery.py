"""Module 1 — Discovery.

Validate an input source and mint a stable, deterministic source_id.

In:  DiscoveryRequest{ source_type, url }
Out: Source{ source_id, type, url, status }

Deterministic (no LLM, no network). source_id is a hash of the normalized URL so the
same repo always maps to the same id (important for batch runs and belief continuity).
"""

from __future__ import annotations

import hashlib
import re

from ..context import Context
from ..models import DiscoveryRequest, Source

_GITHUB_RE = re.compile(
    r"^https?://(www\.)?github\.com/(?P<owner>[^/\s]+)/(?P<name>[^/\s#?]+)",
    re.IGNORECASE,
)


def normalize_github_url(url: str) -> str:
    """Canonicalize a GitHub repo URL to `https://github.com/<owner>/<name>`."""
    m = _GITHUB_RE.match(url.strip())
    if not m:
        raise ValueError(f"not a valid GitHub repository URL: {url!r}")
    owner = m.group("owner")
    name = m.group("name")
    if name.endswith(".git"):
        name = name[:-4]
    return f"https://github.com/{owner}/{name}"


def mint_source_id(normalized_url: str) -> str:
    digest = hashlib.sha256(normalized_url.lower().encode("utf-8")).hexdigest()[:8]
    return f"src_{digest}"


def run(inp: DiscoveryRequest, ctx: Context) -> Source:
    if inp.source_type != "github":
        raise ValueError(f"unsupported source_type in MVP: {inp.source_type!r}")
    normalized = normalize_github_url(inp.url)
    return Source(
        source_id=mint_source_id(normalized),
        type="github",
        url=normalized,
        status="discovered",
    )
