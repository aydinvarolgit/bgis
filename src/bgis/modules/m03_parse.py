"""Module 3 — Repository Parsing.

Convert a raw Repository into structured, text documents the downstream semantic
modules consume. Source-specific knowledge ends here: everything after Module 3 sees
only generic Documents.

In:  Repository
Out: ParsedDocuments{ documents: [readme, architecture, dependencies, metadata] }

Deterministic (no LLM in MVP). An LLM code-summary hook can be added to the architecture
doc later without changing the contract.
"""

from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath

from ..context import Context
from ..models import Document, ParsedDocuments, Repository

# Tree entries below this many top-level dirs are summarized individually.
TOP_DIR_LIMIT = 25
EXT_LIMIT = 15


def run(inp: Repository, ctx: Context) -> ParsedDocuments:
    docs: list[Document] = []

    readme = _readme_doc(inp)
    if readme:
        docs.append(readme)

    docs.append(_architecture_doc(inp))

    deps = _dependencies_doc(inp)
    if deps:
        docs.append(deps)

    docs.append(_metadata_doc(inp))

    return ParsedDocuments(source_id=inp.source_id, documents=docs)


def _readme_doc(repo: Repository) -> Document | None:
    text = repo.readme_raw.strip()
    if not text:
        return None
    return Document(
        type="readme",
        title=f"{repo.owner}/{repo.name} README",
        text=text,
        meta={"chars": len(text)},
    )


def _architecture_doc(repo: Repository) -> Document:
    """Summarize layout: top-level dirs, file-extension distribution, languages."""
    blobs = [e for e in repo.file_tree if e.type == "blob"]
    top_dirs: Counter[str] = Counter()
    exts: Counter[str] = Counter()
    for e in blobs:
        parts = PurePosixPath(e.path).parts
        top = parts[0] if len(parts) > 1 else "(root)"
        top_dirs[top] += 1
        suffix = PurePosixPath(e.path).suffix.lower() or "(none)"
        exts[suffix] += 1

    lines = [f"Repository {repo.owner}/{repo.name} architecture overview.", ""]
    lines.append(f"Total files: {len(blobs)}.")
    if repo.languages:
        total = sum(repo.languages.values()) or 1
        lang_str = ", ".join(
            f"{k} {v * 100 // total}%"
            for k, v in sorted(repo.languages.items(), key=lambda kv: -kv[1])
        )
        lines.append(f"Languages by bytes: {lang_str}.")
    lines.append("")
    lines.append("Top-level structure (files per directory):")
    for name, n in top_dirs.most_common(TOP_DIR_LIMIT):
        lines.append(f"- {name}: {n} files")
    lines.append("")
    lines.append("File types:")
    for ext, n in exts.most_common(EXT_LIMIT):
        lines.append(f"- {ext}: {n}")

    return Document(
        type="architecture",
        title=f"{repo.owner}/{repo.name} architecture",
        text="\n".join(lines),
        meta={"file_count": len(blobs), "top_dirs": dict(top_dirs.most_common(TOP_DIR_LIMIT))},
    )


def _dependencies_doc(repo: Repository) -> Document | None:
    if not repo.dependency_files:
        return None
    chunks = []
    for d in repo.dependency_files:
        chunks.append(f"### {d.path}\n{d.raw.strip()}")
    text = (
        f"Dependency manifests for {repo.owner}/{repo.name}.\n\n" + "\n\n".join(chunks)
    )
    return Document(
        type="dependencies",
        title=f"{repo.owner}/{repo.name} dependencies",
        text=text,
        meta={"files": [d.path for d in repo.dependency_files]},
    )


def _metadata_doc(repo: Repository) -> Document:
    lines = [
        f"Repository {repo.owner}/{repo.name} metadata.",
        f"Description: {repo.description or '(none)'}.",
        f"Primary language: {repo.language or '(unknown)'}.",
        f"Topics: {', '.join(repo.topics) if repo.topics else '(none)'}.",
        f"Stars: {repo.stars}. Forks: {repo.forks}. Watchers: {repo.watchers}. "
        f"Open issues: {repo.open_issues}. Contributors: {repo.contributors_count}.",
        f"License: {repo.license or '(none)'}.",
        f"Releases: {len(repo.releases)}. Recent commits captured: {len(repo.commits_recent)}.",
        f"Created: {repo.created_at}. Last push: {repo.pushed_at}.",
    ]
    return Document(
        type="metadata",
        title=f"{repo.owner}/{repo.name} metadata",
        text="\n".join(lines),
        meta={"stars": repo.stars, "forks": repo.forks, "topics": repo.topics},
    )
