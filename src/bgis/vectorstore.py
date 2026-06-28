"""ChromaDB wrapper — local, file-backed vector store (no server).

Holds two collections:
  - "concepts": concept canonical-name embeddings, for dedup (Module 6).
  - "beliefs":  belief-statement embeddings, for belief retrieval (Module 7/12).

Swappable for Qdrant later behind this same interface. Embeddings are supplied by the
caller (Ollama nomic-embed-text) so Chroma's own embedding fn is never used.
"""

from __future__ import annotations

from typing import Optional

from .config import Settings


class VectorStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._collections: dict = {}

    def _collection(self, name: str):
        if self._client is None:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.settings.chroma_dir))
        if name not in self._collections:
            # Cosine space so distance = 1 - cosine_similarity (matches our thresholds).
            self._collections[name] = self._client.get_or_create_collection(
                name, metadata={"hnsw:space": "cosine"}
            )
        return self._collections[name]

    def add(self, collection: str, id: str, embedding: list[float], metadata: dict) -> None:
        self._collection(collection).upsert(
            ids=[id], embeddings=[embedding], metadatas=[metadata]
        )

    def nearest(
        self, collection: str, embedding: list[float], n: int = 1
    ) -> list[tuple[str, float, dict]]:
        """Return [(id, cosine_similarity, metadata)] for the n closest items.

        Collections use cosine space, so Chroma's distance is cosine distance and
        similarity = 1 - distance.
        """
        col = self._collection(collection)
        if col.count() == 0:
            return []
        res = col.query(query_embeddings=[embedding], n_results=min(n, col.count()))
        out: list[tuple[str, float, dict]] = []
        ids = res["ids"][0]
        dists = res["distances"][0]
        metas = res["metadatas"][0]
        for i, dist, meta in zip(ids, dists, metas):
            sim = 1.0 - dist
            out.append((i, sim, meta or {}))
        return out

    def match(
        self, collection: str, embedding: list[float], threshold: Optional[float] = None
    ) -> Optional[tuple[str, float, dict]]:
        """Return the nearest item iff its similarity >= threshold, else None."""
        thr = self.settings.concept_similarity_threshold if threshold is None else threshold
        hits = self.nearest(collection, embedding, n=1)
        if hits and hits[0][1] >= thr:
            return hits[0]
        return None
