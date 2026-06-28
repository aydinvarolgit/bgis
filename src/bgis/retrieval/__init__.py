"""Module 9 retrieval BACKENDS — pluggable strategies for acquiring external evidence.

Module 9 attaches external evidence to the run's concepts. The GitHub-native sibling-repo search
is built into m09 and always on (when the source is a repo). Everything else is a
`RetrievalBackend` here, each toggled by a `retrieval_use_*` setting (all default OFF so default
behavior is unchanged):

    SourcePluginBackend  (retrieval_use_source_plugins) — reuse arxiv/hn/github plugins, routed by
                          gap KIND. Works for ANY source type, no new dependency.
    LocalCorpusBackend   (retrieval_use_local_corpus)   — embed-search previously-ingested docs on
                          disk. Zero network, deterministic, cross-run convergence.
    ExternalApiBackend   (retrieval_use_external_apis)  — keyless Wikipedia + Semantic Scholar +
                          Crossref lookups per concept.

DEFERRED (user undecided, 2026-06-28): a general open-web `SearchBackend` — DuckDuckGo (via the
keyless `ddgs` library) or a self-hosted SearXNG meta-search — would drop in here as one more
RetrievalBackend with the same `candidates()` contract. Not implemented yet; the seam is ready.
"""

from __future__ import annotations

from ..context import Context
from .base import Candidate, RetrievalBackend, best_concept, concept_rep, cos
from .external_apis import ExternalApiBackend
from .local_corpus import LocalCorpusBackend
from .source_plugins import SourcePluginBackend


def default_backends(ctx: Context) -> list[RetrievalBackend]:
    """The enabled backends for this run, per `retrieval_use_*` settings (real getters)."""
    backends: list[RetrievalBackend] = []
    if ctx.settings.retrieval_use_source_plugins:
        backends.append(SourcePluginBackend())
    if ctx.settings.retrieval_use_local_corpus:
        backends.append(LocalCorpusBackend())
    if ctx.settings.retrieval_use_external_apis:
        backends.append(ExternalApiBackend())
    return backends


__all__ = [
    "Candidate",
    "RetrievalBackend",
    "SourcePluginBackend",
    "LocalCorpusBackend",
    "ExternalApiBackend",
    "default_backends",
    "best_concept",
    "concept_rep",
    "cos",
]
