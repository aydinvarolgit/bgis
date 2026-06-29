"""LLM multi-backend config: loading, failover, option merge, prompt cap, embedding split."""

import json

import pytest

from bgis.config import EmbeddingConfig, LLMBackend, LLMConfig, Settings, _default_llm
from bgis.llm import LLM


# --------------------------------------------------------------------------- #
# config loading
# --------------------------------------------------------------------------- #


def test_config_loads_from_file(monkeypatch, tmp_path):
    cfg = {
        "llm": {
            "backends": [
                {"name": "a", "host": "http://h1", "model": "m1"},
                {"name": "b", "host": "http://h2", "model": "m2"},
            ],
            "options": {"temperature": 0.2, "num_ctx": 8192},
        },
        "embedding": {"host": "http://e", "model": "emb"},
    }
    f = tmp_path / "llm_config.json"
    f.write_text(json.dumps(cfg))
    monkeypatch.setenv("BGIS_LLM_CONFIG", str(f))

    s = Settings(github_token="t")
    assert [b.model for b in s.llm.backends] == ["m1", "m2"]
    assert s.llm.options.temperature == 0.2
    assert s.embedding.model == "emb" and s.embedding.host == "http://e"


def test_config_defaults_when_absent(monkeypatch):
    monkeypatch.setenv("BGIS_LLM_CONFIG", "/nonexistent/llm_config.json")
    cfg = _default_llm()
    assert cfg.backends and cfg.backends[0].model == "gemma4:31b-cloud"
    assert EmbeddingConfig().model == "nomic-embed-text"


# --------------------------------------------------------------------------- #
# failover + retry loop (no network: stub _attempt)
# --------------------------------------------------------------------------- #


def _llm(backends, **over):
    s = Settings(github_token="t")
    s.llm = LLMConfig(
        backends=backends,
        max_transient_retries=over.pop("max_transient_retries", 2),
        retry_backoff_s=0.0,  # no real sleeping in tests
        retry_jitter=0.0,
        **over,
    )
    return LLM(s)


def test_failover_to_second_backend(monkeypatch):
    llm = _llm([LLMBackend(name="a", model="m1"), LLMBackend(name="b", model="m2")])
    calls = []

    def fake_attempt(backend, *, structured, system, user, schema, kw):
        calls.append(backend.model)
        if backend.model == "m1":
            raise RuntimeError("backend down")
        return "ok-from-second"

    monkeypatch.setattr(llm, "_attempt", fake_attempt)
    out = llm.text("sys", "usr")
    assert out == "ok-from-second"
    # first backend retried (max_transient_retries=2) then failover to second
    assert calls == ["m1", "m1", "m2"]


def test_all_backends_fail_raises(monkeypatch):
    llm = _llm([LLMBackend(name="a", model="m1")])
    monkeypatch.setattr(
        llm, "_attempt",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")),
    )
    with pytest.raises(RuntimeError, match="All 1 LLM backend"):
        llm.text("s", "u")


def test_disabled_raises(monkeypatch):
    llm = _llm([LLMBackend(name="a", model="m1")], enabled=False)
    with pytest.raises(RuntimeError, match="disabled"):
        llm.text("s", "u")


# --------------------------------------------------------------------------- #
# option merge + prompt cap
# --------------------------------------------------------------------------- #


def test_gen_kwargs_merges_options_and_kwargs_win():
    llm = _llm([LLMBackend(name="a", model="m1")])
    llm.cfg.options.temperature = 0.5
    llm.cfg.options.num_ctx = 4096
    kw = llm._gen_kwargs({"temperature": 0.0})  # per-call override
    assert kw["temperature"] == 0.0  # kwargs win
    assert kw["extra_body"]["options"]["num_ctx"] == 4096  # config option forwarded


def test_prompt_truncated_to_cap():
    llm = _llm([LLMBackend(name="a", model="m1")], max_prompt_chars=10)
    assert llm._truncate("x" * 50) == "x" * 10
    assert llm._truncate("short") == "short"
