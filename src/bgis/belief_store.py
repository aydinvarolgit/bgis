"""File-backed global belief store (shared by Modules 7 and 12).

Each belief is one JSON file `data/beliefs/<belief_id>.json`. Belief statement
embeddings live in the Chroma "beliefs" collection for semantic retrieval. This is the
central intelligence of BGIS; swap the JSON backing for Neo4j later behind this interface.
"""

from __future__ import annotations

from .config import Settings
from .embeddings import Embedder
from .models import Belief
from .vectorstore import VectorStore

BELIEF_COLLECTION = "beliefs"


class BeliefStore:
    def __init__(self, settings: Settings, vectors: VectorStore, embedder: Embedder):
        self.settings = settings
        self.vectors = vectors
        self.embedder = embedder

    def _path(self, belief_id: str):
        return self.settings.stage_dir("beliefs") / f"{belief_id}.json"

    def get(self, belief_id: str) -> Belief | None:
        p = self._path(belief_id)
        if not p.exists():
            return None
        return Belief.model_validate_json(p.read_text(encoding="utf-8"))

    def all(self) -> list[Belief]:
        # Belief files are named bel_*.json; other *.json in this dir are pipeline
        # artifacts (deltas/update/narrative/...) and must be ignored here.
        out = []
        for p in sorted(self.settings.stage_dir("beliefs").glob("bel_*.json")):
            out.append(Belief.model_validate_json(p.read_text(encoding="utf-8")))
        return out

    def save(self, belief: Belief) -> None:
        """Persist belief JSON and (re)index its statement embedding in Chroma."""
        self._path(belief.id).write_text(belief.model_dump_json(indent=2), encoding="utf-8")
        embedding = self.embedder.embed(belief.statement)
        self.vectors.add(
            BELIEF_COLLECTION,
            belief.id,
            embedding,
            {"belief_id": belief.id, "statement": belief.statement},
        )

    def by_concept(self, concept_id: str) -> list[Belief]:
        """Beliefs directly linked to a concept id."""
        return [b for b in self.all() if concept_id in b.linked_concepts]

    def semantic_search(self, query_embedding: list[float], n: int = 5,
                        threshold: float | None = None) -> list[tuple[Belief, float]]:
        """Beliefs whose statement is semantically near the query, above threshold."""
        thr = (
            self.settings.belief_retrieval_threshold if threshold is None else threshold
        )
        hits = self.vectors.nearest(BELIEF_COLLECTION, query_embedding, n=n)
        out = []
        for belief_id, sim, _meta in hits:
            if sim < thr:
                continue
            b = self.get(belief_id)
            if b is not None:
                out.append((b, sim))
        return out
