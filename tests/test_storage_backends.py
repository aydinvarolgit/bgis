"""Backend selection behind the BeliefStore / VectorStore interfaces.

Verifies the factories dispatch on settings without constructing remote clients (the
neo4j/qdrant deps are lazy-imported, so selection must not touch the network).
"""

from __future__ import annotations

import pytest

from bgis.belief_store import BeliefStore, Neo4jBeliefStore, make_belief_store
from bgis.config import Settings
from bgis.vectorstore import QdrantVectorStore, VectorStore, make_vector_store


def _settings(tmp_path, **kw):
    return Settings(github_token="test", data_dir=tmp_path / "data",
                    retrieval_use_web_search=False, **kw)


def test_default_backends(tmp_path):
    s = _settings(tmp_path)
    assert isinstance(make_vector_store(s), VectorStore)
    vs = make_vector_store(s)
    assert type(make_belief_store(s, vs, embedder=None)) is BeliefStore


def test_qdrant_and_neo4j_selected_without_connecting(tmp_path):
    s = _settings(tmp_path, vector_backend="qdrant", belief_backend="neo4j")
    vs = make_vector_store(s)
    assert isinstance(vs, QdrantVectorStore)
    assert vs._client is None  # lazy: no client built at construction
    bs = make_belief_store(s, vs, embedder=None)
    assert isinstance(bs, Neo4jBeliefStore)
    assert bs._driver is None  # lazy: no driver built at construction


def test_unknown_backends_raise(tmp_path):
    with pytest.raises(ValueError):
        make_vector_store(_settings(tmp_path, vector_backend="bogus"))
    s = _settings(tmp_path, belief_backend="bogus")
    with pytest.raises(ValueError):
        make_belief_store(s, make_vector_store(_settings(tmp_path)), embedder=None)
