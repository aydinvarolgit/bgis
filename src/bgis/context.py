"""Shared execution context passed to every module's `run(inp, ctx)`.

Bundles settings + lazily-constructed services so modules stay decoupled from how
those services are built. Tests can substitute fakes for `llm`, `embedder`, `vectors`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .belief_store import make_belief_store
from .config import Settings, load_settings
from .embeddings import Embedder
from .llm import LLM
from .vectorstore import make_vector_store


@dataclass
class Context:
    settings: Settings = field(default_factory=load_settings)
    llm: LLM = None  # type: ignore[assignment]
    embedder: Embedder = None  # type: ignore[assignment]
    vectors: object = None  # VectorStore | QdrantVectorStore (per settings.vector_backend)
    beliefs: object = None  # BeliefStore | Neo4jBeliefStore (per settings.belief_backend)

    def __post_init__(self):
        if self.llm is None:
            self.llm = LLM(self.settings)
        if self.embedder is None:
            self.embedder = Embedder(self.settings)
        if self.vectors is None:
            self.vectors = make_vector_store(self.settings)
        if self.beliefs is None:
            self.beliefs = make_belief_store(self.settings, self.vectors, self.embedder)
