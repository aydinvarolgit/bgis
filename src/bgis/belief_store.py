"""Global belief store — two interchangeable backends behind one interface.

`BeliefStore` is the default file backend: each belief is one JSON file
`data/beliefs/<belief_id>.json`. `Neo4jBeliefStore` stores the same beliefs as graph nodes
(`(:Belief)-[:ABOUT]->(:Concept)` and `(:Belief)-[:COUNTERS]->(:Belief)` relationships), so the
belief graph can be queried as an actual graph. Pick via `make_belief_store(...)` keyed on
`settings.belief_backend`. This is the central intelligence of BGIS.

Belief-statement embeddings live in the VectorStore "beliefs" collection for semantic retrieval in
BOTH backends — only the source-of-truth store for the belief records themselves differs, so
`semantic_search` is identical across backends.

Interface (all backends): get(id), all(), save(belief), by_concept(concept_id),
semantic_search(query_embedding, n, threshold).
"""

from __future__ import annotations

from .config import Settings
from .embeddings import Embedder
from .models import Belief
from .vectorstore import VectorStore

BELIEF_COLLECTION = "beliefs"


class _BeliefStoreBase:
    """Shared embedding indexing + semantic search (vector-backed, backend-agnostic)."""

    def __init__(self, settings: Settings, vectors: VectorStore, embedder: Embedder):
        self.settings = settings
        self.vectors = vectors
        self.embedder = embedder

    def _index_embedding(self, belief: Belief) -> None:
        """(Re)index a belief's statement embedding in the vector store."""
        embedding = self.embedder.embed(belief.statement)
        self.vectors.add(
            BELIEF_COLLECTION,
            belief.id,
            embedding,
            {"belief_id": belief.id, "statement": belief.statement},
        )

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

    # Subclasses provide the record store:
    def get(self, belief_id: str) -> Belief | None:  # pragma: no cover - interface
        raise NotImplementedError

    def all(self) -> list[Belief]:  # pragma: no cover - interface
        raise NotImplementedError

    def save(self, belief: Belief) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def by_concept(self, concept_id: str) -> list[Belief]:  # pragma: no cover - interface
        raise NotImplementedError


class BeliefStore(_BeliefStoreBase):
    """File backend: one JSON file per belief under data/beliefs/."""

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
        """Persist belief JSON and (re)index its statement embedding in the vector store."""
        self._path(belief.id).write_text(belief.model_dump_json(indent=2), encoding="utf-8")
        self._index_embedding(belief)

    def by_concept(self, concept_id: str) -> list[Belief]:
        """Beliefs directly linked to a concept id."""
        return [b for b in self.all() if concept_id in b.linked_concepts]


class Neo4jBeliefStore(_BeliefStoreBase):
    """Neo4j backend: each belief is a (:Belief) node carrying the full JSON for lossless
    round-trip, plus indexed props and ABOUT/COUNTERS relationships for graph queries."""

    def __init__(self, settings: Settings, vectors: VectorStore, embedder: Embedder):
        super().__init__(settings, vectors, embedder)
        self._driver = None
        self._init_done = False

    def _drv(self):
        if self._driver is None:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
        return self._driver

    def _session(self):
        return self._drv().session(database=self.settings.neo4j_database)

    def _ensure_schema(self) -> None:
        if self._init_done:
            return
        with self._session() as s:
            s.run("CREATE CONSTRAINT belief_id IF NOT EXISTS "
                  "FOR (b:Belief) REQUIRE b.id IS UNIQUE")
            s.run("CREATE CONSTRAINT concept_id IF NOT EXISTS "
                  "FOR (c:Concept) REQUIRE c.id IS UNIQUE")
        self._init_done = True

    @staticmethod
    def _to_belief(data: str | None) -> Belief | None:
        if not data:
            return None
        return Belief.model_validate_json(data)

    def get(self, belief_id: str) -> Belief | None:
        self._ensure_schema()
        with self._session() as s:
            rec = s.run("MATCH (b:Belief {id:$id}) RETURN b.data AS data",
                        id=belief_id).single()
        return self._to_belief(rec["data"]) if rec else None

    def all(self) -> list[Belief]:
        self._ensure_schema()
        with self._session() as s:
            rows = s.run("MATCH (b:Belief) RETURN b.data AS data ORDER BY b.id")
            return [b for r in rows if (b := self._to_belief(r["data"])) is not None]

    def by_concept(self, concept_id: str) -> list[Belief]:
        self._ensure_schema()
        with self._session() as s:
            rows = s.run(
                "MATCH (b:Belief)-[:ABOUT]->(:Concept {id:$cid}) "
                "RETURN b.data AS data ORDER BY b.id",
                cid=concept_id,
            )
            return [b for r in rows if (b := self._to_belief(r["data"])) is not None]

    def save(self, belief: Belief) -> None:
        """Upsert the belief node + ABOUT/COUNTERS rels, then index its statement embedding."""
        self._ensure_schema()
        data = belief.model_dump_json()
        with self._session() as s:
            s.run(
                "MERGE (b:Belief {id:$id}) "
                "SET b.statement=$statement, b.confidence=$confidence, b.origin=$origin, "
                "    b.counter_to=$counter_to, b.data=$data",
                id=belief.id, statement=belief.statement, confidence=belief.confidence,
                origin=belief.origin, counter_to=belief.counter_to, data=data,
            )
            # Rebuild ABOUT rels to exactly the current linked_concepts.
            s.run("MATCH (b:Belief {id:$id})-[r:ABOUT]->() DELETE r", id=belief.id)
            for cid in belief.linked_concepts:
                s.run(
                    "MATCH (b:Belief {id:$id}) MERGE (c:Concept {id:$cid}) MERGE (b)-[:ABOUT]->(c)",
                    id=belief.id, cid=cid,
                )
            if belief.counter_to:
                s.run(
                    "MATCH (b:Belief {id:$id}) MERGE (p:Belief {id:$pid}) "
                    "MERGE (b)-[:COUNTERS]->(p)",
                    id=belief.id, pid=belief.counter_to,
                )
        self._index_embedding(belief)

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None


def make_belief_store(settings: Settings, vectors: VectorStore, embedder: Embedder):
    """Construct the belief store for settings.belief_backend ("file" default | "neo4j")."""
    backend = (settings.belief_backend or "file").lower()
    if backend == "file":
        return BeliefStore(settings, vectors, embedder)
    if backend == "neo4j":
        return Neo4jBeliefStore(settings, vectors, embedder)
    raise ValueError(f"unknown belief_backend: {settings.belief_backend!r}")
