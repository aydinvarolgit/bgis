"""LLM access via Ollama's OpenAI-compatible endpoint, wrapped with instructor.

`structured()` returns a validated Pydantic instance — used by claim extraction (4),
concept normalization (6), narrative planning (14) and content generation (15).
Content generation also has a plain `text()` helper for freeform markdown.

Transport is driven by `settings.llm` (LLMConfig, loaded from llm_config.json): a list of
backends tried in order — the first is the default, the rest are failover. Each backend gets
up to `max_transient_retries` attempts with exponential backoff before falling through to the
next. Generation `options` (temperature, num_ctx) are applied to every call; per-call kwargs
override them. Embeddings are NOT handled here — they use their own endpoint (see embeddings.py).
"""

from __future__ import annotations

import random
import time
from typing import Type, TypeVar

from pydantic import BaseModel

from .config import LLMBackend, Settings

T = TypeVar("T", bound=BaseModel)


class LLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cfg = settings.llm
        self._clients: dict[str, tuple] = {}  # host -> (openai_client, instructor_client)

    def _client_for(self, backend: LLMBackend):
        # Lazy import/connect so tests can construct Context without Ollama running, and so each
        # distinct host gets its own cached client pair.
        if backend.host not in self._clients:
            import instructor
            from openai import OpenAI

            client = OpenAI(
                base_url=f"{backend.host.rstrip('/')}/v1",
                api_key="ollama",  # Ollama ignores the key but the client requires one.
                timeout=self.cfg.request_timeout_s,
                max_retries=0,  # we own the retry/failover loop below
            )
            instr = instructor.from_openai(client, mode=instructor.Mode.JSON)
            self._clients[backend.host] = (client, instr)
        return self._clients[backend.host]

    def _gen_kwargs(self, kw: dict) -> dict:
        """Merge configured generation options with per-call kwargs (kwargs win). num_ctx is an
        Ollama-specific option, passed through extra_body so the OpenAI-compat endpoint forwards it."""
        merged = {"temperature": self.cfg.options.temperature, **kw}
        extra = merged.pop("extra_body", {}) or {}
        opts = {"num_ctx": self.cfg.options.num_ctx, **extra.get("options", {})}
        merged["extra_body"] = {**extra, "options": opts}
        return merged

    def _truncate(self, text: str) -> str:
        cap = self.cfg.max_prompt_chars
        return text if len(text) <= cap else text[:cap]

    def _attempt(self, backend: LLMBackend, *, structured: bool, system: str, user: str,
                 schema, kw: dict):
        client, instr = self._client_for(backend)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": self._truncate(user)},
        ]
        if structured:
            return instr.chat.completions.create(
                model=backend.model, response_model=schema, messages=messages, **kw
            )
        resp = client.chat.completions.create(model=backend.model, messages=messages, **kw)
        return resp.choices[0].message.content or ""

    def _run(self, *, structured: bool, system: str, user: str, schema, kw: dict):
        if not self.cfg.enabled:
            raise RuntimeError("LLM is disabled (settings.llm.enabled = false)")
        if not self.cfg.backends:
            raise RuntimeError("No LLM backends configured")

        gen_kw = self._gen_kwargs(kw)
        last_err: Exception | None = None
        for backend in self.cfg.backends:
            for attempt in range(self.cfg.max_transient_retries):
                try:
                    return self._attempt(
                        backend, structured=structured, system=system, user=user,
                        schema=schema, kw=gen_kw,
                    )
                except Exception as e:  # noqa: BLE001 — retry/failover on any transport error
                    last_err = e
                    if attempt + 1 < self.cfg.max_transient_retries:
                        backoff = min(
                            self.cfg.retry_backoff_s * (2 ** attempt), self.cfg.max_backoff_s
                        )
                        backoff += random.uniform(0, self.cfg.retry_jitter * backoff)
                        time.sleep(backoff)
            # backend exhausted -> fall through to the next backend in the list
        raise RuntimeError(
            f"All {len(self.cfg.backends)} LLM backend(s) failed; last error: {last_err}"
        ) from last_err

    def structured(self, system: str, user: str, schema: Type[T], **kw) -> T:
        return self._run(structured=True, system=system, user=user, schema=schema, kw=kw)

    def text(self, system: str, user: str, **kw) -> str:
        return self._run(structured=False, system=system, user=user, schema=None, kw=kw)
