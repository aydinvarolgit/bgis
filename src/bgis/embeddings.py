"""Text embeddings via Ollama (`nomic-embed-text`).

Single dependency-light wrapper over the Ollama REST embeddings endpoint. Used by the
concept dedup engine (Module 6) and belief retrieval (Module 7/12).
"""

from __future__ import annotations

import requests

from .config import Settings


class Embedder:
    def __init__(self, settings: Settings):
        self.settings = settings

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts. Ollama's /api/embed accepts batched input."""
        if not texts:
            return []
        resp = requests.post(
            f"{self.settings.ollama_base_url.rstrip('/')}/api/embed",
            json={"model": self.settings.embed_model, "input": texts},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]
