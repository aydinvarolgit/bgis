"""Shared execution context passed to every module's `run(inp, ctx)`.

Bundles settings + lazily-constructed services so modules stay decoupled from how
those services are built. Tests can substitute fakes for `llm`, `embedder`, `vectors`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .belief_store import BeliefStore
from .config import Settings, load_settings
from .embeddings import Embedder
from .llm import LLM
from .vectorstore import VectorStore


@dataclass
class Context:
    settings: Settings = field(default_factory=load_settings)
    llm: LLM = None  # type: ignore[assignment]
    embedder: Embedder = None  # type: ignore[assignment]
    vectors: VectorStore = None  # type: ignore[assignment]
    beliefs: BeliefStore = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.llm is None:
            self.llm = LLM(self.settings)
        if self.embedder is None:
            self.embedder = Embedder(self.settings)
        if self.vectors is None:
            self.vectors = VectorStore(self.settings)
        if self.beliefs is None:
            self.beliefs = BeliefStore(self.settings, self.vectors, self.embedder)
