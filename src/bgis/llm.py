"""LLM access via Ollama's OpenAI-compatible endpoint, wrapped with instructor.

`structured()` returns a validated Pydantic instance — used by claim extraction (4),
concept normalization (6), narrative planning (14) and content generation (15).
Content generation also has a plain `text()` helper for freeform markdown.
"""

from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel

from .config import Settings

T = TypeVar("T", bound=BaseModel)


class LLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._instructor = None

    def _ensure(self):
        # Lazy import/connect so tests can construct Context without Ollama running.
        if self._client is None:
            import instructor
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self.settings.ollama_openai_url,
                api_key="ollama",  # Ollama ignores the key but the client requires one.
            )
            self._instructor = instructor.from_openai(
                self._client, mode=instructor.Mode.JSON
            )

    def structured(self, system: str, user: str, schema: Type[T], **kw) -> T:
        self._ensure()
        return self._instructor.chat.completions.create(
            model=self.settings.llm_model,
            response_model=schema,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kw,
        )

    def text(self, system: str, user: str, **kw) -> str:
        self._ensure()
        resp = self._client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kw,
        )
        return resp.choices[0].message.content or ""
