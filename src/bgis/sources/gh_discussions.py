"""GitHub Discussions / Issues source plugin — debate + pain points.

Reference form: `ghd:owner/repo` (e.g. `ghd:mem0ai/mem0`). Reuses the existing GITHUB_TOKEN.
Two debate streams, both turned into `discussion` documents:
  - Issues   : PyGithub REST (`repo.get_issues(state="all")`) + their comments.
  - Discussions: GitHub GraphQL (PyGithub REST has no discussions endpoint).

Natural pairing: run it on a repo already in the graph, so the opinions/pain attach to that
repo's existing concepts as stance rather than spawning new ones. Module 4 types most of this
content as `opinion`.

Both fetchers are injectable (`gh`, `graphql`) so unit tests never hit the network.
"""

from __future__ import annotations

import hashlib
import re
from typing import Callable, Optional

from ..context import Context
from ..models import Document, ParsedDocuments, Signals, Source
from ..persistence import save_artifact
from .base import IngestResult, SourcePlugin

MAX_ISSUES = 20
MAX_COMMENTS_PER_ISSUE = 8
MAX_DISCUSSIONS = 20

_DISCUSSIONS_QUERY = """
query($owner:String!, $name:String!, $n:Int!) {
  repository(owner:$owner, name:$name) {
    discussions(first:$n, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes {
        title
        body
        comments(first:8) { nodes { body } }
      }
    }
  }
}
"""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _build_gh(ctx: Context):
    from github import Github

    token = ctx.settings.github_token
    return Github(token) if token else Github()


def _default_graphql(ctx: Context, query: str, variables: dict) -> dict:
    import requests

    headers = {"Authorization": f"bearer {ctx.settings.github_token}"}
    r = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


class GHDiscussionsSourcePlugin(SourcePlugin):
    kind = "gh_discussions"

    def __init__(
        self,
        gh=None,
        graphql: Optional[Callable[[Context, str, dict], dict]] = None,
    ):
        self._gh = gh
        self._graphql = graphql

    def matches(self, ref: str) -> bool:
        return ref.strip().lower().startswith("ghd:")

    def ingest(self, ref: str, ctx: Context) -> IngestResult:
        slug = ref.split(":", 1)[1].strip().strip("/")
        owner, name = slug.split("/", 1)
        source_id = "src_" + hashlib.sha256(f"ghd:{slug}".encode()).hexdigest()[:8]

        documents = _issue_documents(self._gh or _build_gh(ctx), owner, name)
        documents += _discussion_documents(self._graphql, ctx, owner, name)

        source = Source(source_id=source_id, type="gh_discussions", url=ref, status="ingested")
        save_artifact(ctx.settings, "raw", source.source_id, source)

        parsed = ParsedDocuments(source_id=source_id, documents=documents)
        save_artifact(ctx.settings, "parsed", parsed.source_id, parsed)

        signals = Signals(source_id=source_id, signals=[])
        save_artifact(ctx.settings, "signals", signals.source_id, signals)

        return IngestResult(source=source, parsed=parsed, signals=signals, repo=None)


def _issue_documents(gh, owner: str, name: str) -> list[Document]:
    repo = gh.get_repo(f"{owner}/{name}")
    issues = list(repo.get_issues(state="all"))
    # Pull requests surface through get_issues too; prefer real issues, busiest first.
    issues = [i for i in issues if getattr(i, "pull_request", None) is None]
    issues.sort(key=lambda i: getattr(i, "comments", 0) or 0, reverse=True)

    docs: list[Document] = []
    for issue in issues[:MAX_ISSUES]:
        title = _clean(getattr(issue, "title", "") or "")
        if not title:
            continue
        parts = [_clean(getattr(issue, "body", "") or "")]
        for c in list(issue.get_comments())[:MAX_COMMENTS_PER_ISSUE]:
            parts.append(_clean(getattr(c, "body", "") or ""))
        body = "\n\n---\n\n".join(p for p in parts if p)
        docs.append(
            Document(
                type="discussion",
                title=f"Issue: {title}",
                text=f"GitHub issue '{title}' on {owner}/{name}:\n\n{body}",
                meta={"number": getattr(issue, "number", None), "kind": "issue"},
            )
        )
    return docs


def _discussion_documents(graphql, ctx: Context, owner: str, name: str) -> list[Document]:
    call = graphql or _default_graphql
    try:
        data = call(ctx, _DISCUSSIONS_QUERY, {"owner": owner, "name": name, "n": MAX_DISCUSSIONS})
    except Exception:  # noqa: BLE001 — discussions are optional; issues already cover debate
        return []
    nodes = (
        (data or {}).get("data", {}).get("repository", {}).get("discussions", {}).get("nodes", [])
    ) or []
    docs: list[Document] = []
    for node in nodes[:MAX_DISCUSSIONS]:
        title = _clean(node.get("title") or "")
        if not title:
            continue
        parts = [_clean(node.get("body") or "")]
        for c in (node.get("comments", {}).get("nodes", []) or []):
            parts.append(_clean(c.get("body") or ""))
        body = "\n\n---\n\n".join(p for p in parts if p)
        docs.append(
            Document(
                type="discussion",
                title=f"Discussion: {title}",
                text=f"GitHub discussion '{title}' on {owner}/{name}:\n\n{body}",
                meta={"kind": "discussion"},
            )
        )
    return docs
