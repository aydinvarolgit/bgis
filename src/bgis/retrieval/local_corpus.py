"""Backend 2 — embed-search the local corpus of previously-ingested documents.

Every prior run persisted its `ParsedDocuments` to `data/parsed/<source_id>.json`. This backend
treats that on-disk corpus as a retrieval index: each past document (from a DIFFERENT source)
becomes a Candidate, which m09 embeds and routes to the best-matching current concept above the
similarity threshold. So a belief can be corroborated by something BGIS already read — zero
network, fully deterministic, on-thesis (multi-source convergence across runs).

No persistent vector index is maintained for documents (only concepts/beliefs live in Chroma);
the corpus is small, so m09 embeds the candidates inline. `retrieval_corpus_max_docs` bounds the
scan. The current run's own source is excluded (it can't corroborate itself).
"""

from __future__ import annotations

import json

from ..context import Context
from ..models import Claims, Concepts, Gaps
from .base import Candidate, RetrievalBackend

SNIPPET_CHARS = 400


class LocalCorpusBackend(RetrievalBackend):
    name = "local_corpus"

    def candidates(
        self, gaps: Gaps, concepts: Concepts, claims: Claims, ctx: Context
    ) -> list[Candidate]:
        parsed_dir = ctx.settings.stage_dir("parsed")
        exclude = concepts.source_id
        cap = ctx.settings.retrieval_corpus_max_docs
        out: list[Candidate] = []
        for path in sorted(parsed_dir.glob("*.json")):
            sid = path.stem
            if sid == exclude:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for doc in data.get("documents", []):
                title = (doc.get("title") or "").strip()
                text = (doc.get("text") or "").strip()
                if not text:
                    continue
                snippet = text[:SNIPPET_CHARS]
                url = (doc.get("meta") or {}).get("url") or f"local:{sid}"
                out.append(
                    Candidate(
                        text=f"{title}. {snippet}" if title else snippet,
                        summary=f"[corpus {doc.get('type', 'doc')}] {title or sid}: "
                        f"{snippet[:160]}",
                        source_url=url,
                        concept_id=None,  # routed by embedding to the best current concept
                    )
                )
                if len(out) >= cap:
                    return out
        return out
