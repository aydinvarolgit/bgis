"""Module 2 — Repository Ingestion.

Collect all relevant repository information via the GitHub API (PyGithub).

In:  Source{ source_id, type, url, ... }
Out: Repository{ owner, name, ..., readme_raw, file_tree, releases, commits_recent, ... }

Deterministic (no LLM). Network-bound. Every field is defensively fetched so a missing
README / license / releases never aborts ingestion.
"""

from __future__ import annotations

from ..context import Context
from ..models import (
    Commit,
    DependencyFile,
    Release,
    Repository,
    Source,
    TreeEntry,
)

# Files we treat as dependency manifests (fetched raw if present at repo root).
DEPENDENCY_PATHS = [
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Gemfile",
]

MAX_TREE_ENTRIES = 2000
MAX_COMMITS = 30
MAX_RELEASES = 20


def _owner_name(url: str) -> tuple[str, str]:
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]


def _build_client(ctx: Context):
    from github import Github

    token = ctx.settings.github_token
    return Github(token) if token else Github()


def run(inp: Source, ctx: Context, gh=None) -> Repository:
    """Fetch repository data. `gh` (a PyGithub Github client) is injectable for tests."""
    gh = gh or _build_client(ctx)
    owner, name = _owner_name(inp.url)
    repo = gh.get_repo(f"{owner}/{name}")

    return Repository(
        source_id=inp.source_id,
        owner=owner,
        name=name,
        description=repo.description or "",
        default_branch=repo.default_branch or "main",
        topics=_safe(lambda: list(repo.get_topics()), []),
        stars=repo.stargazers_count or 0,
        forks=repo.forks_count or 0,
        watchers=repo.subscribers_count or 0,
        open_issues=repo.open_issues_count or 0,
        language=repo.language or "",
        languages=_safe(lambda: _languages(repo), {}),
        license=_safe(lambda: repo.get_license().license.spdx_id, ""),
        created_at=repo.created_at,
        pushed_at=repo.pushed_at,
        readme_raw=_readme(repo),
        file_tree=_file_tree(repo),
        releases=_releases(repo),
        commits_recent=_commits(repo),
        contributors_count=_safe(lambda: repo.get_contributors().totalCount, 0),
        dependency_files=_dependency_files(repo),
    )


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — any GitHub error -> use default
        return default


def _languages(repo) -> dict[str, int]:
    """Keep only {lang: byte_count} integer pairs (filter any stray metadata keys)."""
    raw = repo.get_languages()
    out: dict[str, int] = {}
    for k, v in dict(raw).items():
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out[k] = v
        elif isinstance(v, str) and v.isdigit():
            out[k] = int(v)
    return out


def _readme(repo) -> str:
    def _get():
        return repo.get_readme().decoded_content.decode("utf-8", errors="replace")

    return _safe(_get, "")


def _file_tree(repo) -> list[TreeEntry]:
    def _get():
        tree = repo.get_git_tree(repo.default_branch, recursive=True)
        entries = []
        for e in tree.tree[:MAX_TREE_ENTRIES]:
            entries.append(
                TreeEntry(path=e.path, size=e.size or 0, type=e.type if e.type in ("blob", "tree") else "blob")
            )
        return entries

    return _safe(_get, [])


def _releases(repo) -> list[Release]:
    def _get():
        out = []
        for r in repo.get_releases()[:MAX_RELEASES]:
            out.append(Release(tag=r.tag_name or "", date=r.published_at or r.created_at))
        return out

    return _safe(_get, [])


def _commits(repo) -> list[Commit]:
    def _get():
        out = []
        for c in repo.get_commits()[:MAX_COMMITS]:
            out.append(
                Commit(
                    sha=c.sha,
                    date=c.commit.author.date if c.commit and c.commit.author else None,
                    message=(c.commit.message if c.commit else "").splitlines()[0][:200],
                )
            )
        return out

    return _safe(_get, [])


def _dependency_files(repo) -> list[DependencyFile]:
    out = []
    for path in DEPENDENCY_PATHS:
        def _get(p=path):
            content = repo.get_contents(p)
            return content.decoded_content.decode("utf-8", errors="replace")

        raw = _safe(_get, None)
        if raw is not None:
            out.append(DependencyFile(path=path, raw=raw))
    return out
