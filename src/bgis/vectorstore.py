"""Vector store — two interchangeable backends behind one interface.

Holds two collections:
  - "concepts": concept canonical-name embeddings, for dedup (Module 6).
  - "beliefs":  belief-statement embeddings, for belief retrieval (Module 7/12).

`VectorStore` is the embedded ChromaDB backend (local, file-backed, no server — the default).
`QdrantVectorStore` is the same interface against a Qdrant vector DB. Pick via
`make_vector_store(settings)` keyed on `settings.vector_backend`. Embeddings are supplied by the
caller (Ollama nomic-embed-text) so neither backend's own embedding fn is ever used.

Interface (all backends): add(collection, id, embedding, metadata),
nearest(collection, embedding, n) -> [(id, cosine_sim, meta)], match(collection, embedding, thr).
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


class QdrantVectorStore:
    """Qdrant-backed vector store with the same interface as VectorStore.

    Collections use cosine distance so similarity = 1 - distance, identical to the Chroma backend.
    A collection is created lazily on the first `add`, sized from that embedding's dimension.
    Qdrant point ids must be int/UUID, but our ids are strings (bel_*, concept ids); each string id
    is mapped to a deterministic UUIDv5 point id and the original id is preserved in the payload.
    """

    _ID_NAMESPACE = __import__("uuid").UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._ensured: set = set()

    def _conn(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(
                url=self.settings.qdrant_url,
                api_key=self.settings.qdrant_api_key or None,
                prefer_grpc=self.settings.qdrant_prefer_grpc,
            )
        return self._client

    def _point_id(self, id: str) -> str:
        import uuid

        return str(uuid.uuid5(self._ID_NAMESPACE, id))

    def _ensure(self, collection: str, size: int) -> None:
        if collection in self._ensured:
            return
        from qdrant_client import models as qm

        client = self._conn()
        if not client.collection_exists(collection):
            client.create_collection(
                collection,
                vectors_config=qm.VectorParams(size=size, distance=qm.Distance.COSINE),
            )
        self._ensured.add(collection)

    def add(self, collection: str, id: str, embedding: list[float], metadata: dict) -> None:
        from qdrant_client import models as qm

        self._ensure(collection, len(embedding))
        payload = dict(metadata)
        payload["_id"] = id  # original string id; point id is a derived UUID
        self._conn().upsert(
            collection,
            points=[qm.PointStruct(id=self._point_id(id), vector=embedding, payload=payload)],
        )

    def nearest(
        self, collection: str, embedding: list[float], n: int = 1
    ) -> list[tuple[str, float, dict]]:
        """Return [(id, cosine_similarity, metadata)] for the n closest items."""
        client = self._conn()
        if not client.collection_exists(collection):
            return []
        res = client.query_points(collection, query=embedding, limit=n, with_payload=True).points
        out: list[tuple[str, float, dict]] = []
        for p in res:
            payload = p.payload or {}
            oid = payload.get("_id", str(p.id))
            # Qdrant returns cosine SIMILARITY as the score (higher = closer), already in [-1, 1].
            out.append((oid, float(p.score), payload))
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


def make_vector_store(settings: Settings):
    """Construct the vector store for settings.vector_backend ("chroma" default | "qdrant")."""
    backend = (settings.vector_backend or "chroma").lower()
    if backend == "chroma":
        return VectorStore(settings)
    if backend == "qdrant":
        return QdrantVectorStore(settings)
    raise ValueError(f"unknown vector_backend: {settings.vector_backend!r}")
