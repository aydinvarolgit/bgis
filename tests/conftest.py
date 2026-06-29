"""Shared test fixtures.

Provides a Context backed by a temp data dir and fake LLM/embedder/vectorstore so unit
tests never touch Ollama, Chroma, or the network.
"""

from __future__ import annotations

import pytest

from bgis.config import Settings
from bgis.context import Context


class FakeLLM:
    """Returns canned responses keyed by the response schema."""

    def __init__(self):
        self.structured_responses = {}  # schema_name -> instance
        self.text_response = "fake text"

    def structured(self, system, user, schema, **kw):
        return self.structured_responses[schema.__name__]

    def text(self, system, user, **kw):
        return self.text_response


class FakeEmbedder:
    """Deterministic tiny embeddings: hash text into a small vector."""

    def __init__(self, table=None):
        self.table = table or {}

    def embed(self, text):
        if text in self.table:
            return self.table[text]
        # Deterministic pseudo-embedding from char codes (unit-ish).
        import math

        vals = [((ord(c) % 17) + 1) for c in text[:8].ljust(8, "x")]
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        return [v / norm for v in vals]

    def embed_batch(self, texts):
        return [self.embed(t) for t in texts]


class FakeVectorStore:
    """In-memory cosine-match store mirroring VectorStore's interface."""

    def __init__(self, settings):
        self.settings = settings
        self.data = {}  # collection -> list[(id, emb, meta)]

    def add(self, collection, id, embedding, metadata):
        self.data.setdefault(collection, [])
        self.data[collection] = [r for r in self.data[collection] if r[0] != id]
        self.data[collection].append((id, embedding, metadata))

    @staticmethod
    def _cos(a, b):
        import math

        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(y * y for y in b)) or 1.0
        return dot / (na * nb)

    def nearest(self, collection, embedding, n=1):
        rows = self.data.get(collection, [])
        scored = sorted(
            ((i, self._cos(embedding, e), m) for i, e, m in rows),
            key=lambda r: r[1],
            reverse=True,
        )
        return scored[:n]

    def match(self, collection, embedding, threshold=None):
        thr = self.settings.concept_similarity_threshold if threshold is None else threshold
        hits = self.nearest(collection, embedding, n=1)
        if hits and hits[0][1] >= thr:
            return hits[0]
        return None


@pytest.fixture
def settings(tmp_path) -> Settings:
    # web_search defaults ON in prod, but unit tests must stay offline — pin it off here. Tests that
    # exercise the web-search backend pass an injected `search`/backend or flip the flag explicitly.
    return Settings(github_token="test", data_dir=tmp_path / "data",
                    retrieval_use_web_search=False)


@pytest.fixture
def ctx(settings) -> Context:
    return Context(
        settings=settings,
        llm=FakeLLM(),
        embedder=FakeEmbedder(),
        vectors=FakeVectorStore(settings),
    )
