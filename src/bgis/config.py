"""Runtime settings and filesystem paths.

All configuration is read from the environment (and `.env`) via pydantic-settings.
Paths default to a `data/` tree under the project root and are created on demand.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = three levels up from this file (src/bgis/config.py -> project root).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Optional JSON config for LLM backends + embedding (see llm_config.json at the project root).
# If absent, the built-in defaults below apply. Env vars (BGIS_LLM_CONFIG) can repoint it.
LLM_CONFIG_FILE = PROJECT_ROOT / "llm_config.json"

# Stage -> data subdirectory. Each module persists its output artifact here.
STAGE_DIRS = {
    "raw": "raw",
    "parsed": "parsed",
    "claims": "claims",
    "signals": "signals",
    "concepts": "concepts",
    "beliefs": "beliefs",
    "posts": "posts",
}


class LLMBackend(BaseModel):
    """One LLM endpoint. Backends are tried in list order (first = default, rest = failover)."""

    name: str
    host: str = "http://localhost:11434"
    model: str


class LLMOptions(BaseModel):
    """Per-request generation options. Merged into every call; per-call kwargs override these."""

    temperature: float = 0.0
    num_ctx: int = 32768


class LLMConfig(BaseModel):
    """LLM transport config (mirrors the `llm` block of llm_config.json). Backends provide
    failover; the timeout/retry/backoff fields bound each attempt; `options` set generation params."""

    enabled: bool = True
    max_retries: int = 5  # transient-error retries per backend before failing over to the next
    request_timeout_s: float = 120.0
    request_timeout_max_s: float = 240.0
    retry_backoff_s: float = 2.0
    max_transient_retries: int = 8
    max_backoff_s: float = 60.0
    retry_jitter: float = 0.3
    max_prompt_chars: int = 40000
    options: LLMOptions = Field(default_factory=LLMOptions)
    backends: list[LLMBackend] = Field(
        default_factory=lambda: [LLMBackend(name="local", model="gemma4:31b-cloud")]
    )


class EmbeddingConfig(BaseModel):
    """Embedding endpoint — deliberately SEPARATE from the LLM backends so embeddings always
    stay on the local nomic model regardless of which LLM backend serves generation."""

    host: str = "http://localhost:11434"
    model: str = "nomic-embed-text"


def _load_llm_file() -> dict:
    """Read llm_config.json if present (else {}). Path overridable via BGIS_LLM_CONFIG."""
    import os

    path = Path(os.environ.get("BGIS_LLM_CONFIG", LLM_CONFIG_FILE))
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _default_llm() -> LLMConfig:
    return LLMConfig.model_validate(_load_llm_file().get("llm", {}))


def _default_embedding() -> EmbeddingConfig:
    return EmbeddingConfig.model_validate(_load_llm_file().get("embedding", {}))


class Settings(BaseSettings):
    """Central config object passed around via Context."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="BGIS_",
        extra="ignore",
    )

    # Secrets / external services. GITHUB_TOKEN has no prefix (read directly).
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # LLM generation: multi-backend with failover, loaded from llm_config.json (`llm` block).
    llm: LLMConfig = Field(default_factory=_default_llm)
    # Embeddings: kept on a separate local endpoint (`embedding` block) so the embedding model
    # never changes when the LLM backend does.
    embedding: EmbeddingConfig = Field(default_factory=_default_embedding)
    # General Ollama host (used by `bgis smoke`'s /api/tags reachability check).
    ollama_base_url: str = "http://localhost:11434"

    data_dir: Path = PROJECT_ROOT / "data"
    # Cosine-similarity thresholds (measured: paraphrases ~0.66-0.81, distinct <=0.46).
    # Concept dedup is banded: >= auto_merge -> merge; < similarity -> new;
    # in between -> LLM adjudicates (the concept-merge pass).
    concept_similarity_threshold: float = 0.60  # lower bound to even consider a merge
    concept_auto_merge_threshold: float = 0.72  # at/above this, merge without asking the LLM
    # Drop contentless concept names (every token generic, e.g. "llm-framework"). These are
    # github-topic-tag-style buckets that over-merge across unrelated repos. See m06.
    filter_generic_concepts: bool = True
    belief_retrieval_threshold: float = 0.50  # looser: surface related (not identical) beliefs

    # Module 9 (GitHub-native retrieval): how many external related repos to fetch per source,
    # and the min cosine sim to attach a fetched repo to one of the source's concepts.
    retrieval_max_candidates: int = 6
    # Measured (richer name+claims concept rep): true siblings ~0.68-0.71, off-topic <=0.60.
    retrieval_match_threshold: float = 0.62

    # Module 9 — pluggable retrieval BACKENDS beyond the GitHub-native sibling search. Each is a
    # `RetrievalBackend` (see bgis.retrieval). web_search (DuckDuckGo) is ON by default so EVERY run
    # — including non-repo sources (web/arxiv/hn/rss...) — pulls external corroboration; the other
    # three stay OPT-IN. Every backend's HTTP getter is injectable -> tests offline.
    retrieval_use_source_plugins: bool = False  # reuse arxiv/hn/github plugins, routed by gap.kind
    retrieval_use_local_corpus: bool = False  # embed-search previously-ingested parsed documents
    retrieval_use_external_apis: bool = False  # Wikipedia + Semantic Scholar + Crossref (keyless)
    retrieval_use_web_search: bool = True  # open-web DuckDuckGo search (keyless `ddgs` lib) — ON by
    #                                       default: gives ANY source (incl. non-repo) corroboration
    # Per-backend fan-out caps (keep runs bounded + within free API rate limits).
    retrieval_plugin_max_gaps: int = 4  # source-plugin backend: gaps queried per run
    retrieval_plugin_per_gap: int = 2  # results kept per queried gap
    retrieval_corpus_max_docs: int = 40  # local-corpus backend: max past docs scanned per run
    retrieval_external_max_concepts: int = 4  # external-API backend: concepts queried per run
    retrieval_external_per_api: int = 2  # results kept per API per concept
    retrieval_websearch_max_concepts: int = 4  # web-search backend: concepts queried per run
    retrieval_websearch_per_concept: int = 3  # web results kept per concept
    retrieval_max_per_concept: int = 4  # global: cap external items attached to one concept
    # Module 11: a belief from the source's own claims maxes at this ceiling; the remaining
    # headroom (1 - ceiling) is reserved for independent external corroboration. This keeps the
    # corroboration term from being absorbed by the [0,1] clamp on already-strong beliefs.
    base_confidence_ceiling: float = 0.85
    # Each external corroboration nudges evidence_strength up by this much, capped.
    external_corroboration_weight: float = 0.05
    external_corroboration_cap: float = 0.15

    # Gate F — richer delta. The reserved headroom (1 - base_confidence_ceiling) is filled by a
    # COMPOSITE of three corroboration signals, summed then capped at the headroom so claims alone
    # still top out at the ceiling and full corroboration reaches 1.0:
    #   external   — independent m09 sibling repos (weight/cap above)
    #   diversity  — distinct SOURCE TYPES (repo fact + paper finding + discourse) backing the belief
    #   recency    — how fresh the evidence is (from the days_since_push signal)
    # This completes the Part B-2 thesis: cross-source-TYPE agreement MOVES confidence, not just
    # cross-source. Each extra distinct source type adds this much (3 types -> 0.10):
    source_diversity_weight: float = 0.05
    # Per-source-TYPE authority baseline, used when a source emits no `stars` signal (non-repo
    # sources). Repos keep the log10(stars) formula. unknown -> 0.25 (== the old flat fallback, so
    # existing behavior is unchanged). A peer-reviewed paper outweighs a random comment.
    source_type_authority: dict[str, float] = Field(
        default_factory=lambda: {
            "github": 0.4,  # fallback only; repos normally use the stars formula
            "arxiv": 0.7,
            "rss": 0.5,
            "web": 0.5,
            "hn": 0.4,
            "gh_discussions": 0.4,
        }
    )
    # Recency: evidence pushed within recency_full_days counts full; decays linearly to 0 at
    # recency_zero_days; older or absent -> 0 (never a penalty — respects the ratchet).
    recency_weight: float = 0.05
    recency_full_days: float = 30.0
    recency_zero_days: float = 365.0

    # Claim-type weighting (m11). Facts and findings build a belief's confidence; opinions are
    # excluded (weight 0) and collected as stances instead. finding_weight 1.0 = papers count the
    # same as repo facts; bump >1 to make empirical findings outweigh repo self-description.
    finding_weight: float = 1.0
    # A concept backed ONLY by opinion claims (no fact/finding) still creates a belief, at this
    # low floor confidence, carrying its stances so pure-discourse sources inform posts. On an
    # EXISTING belief, opinions never move confidence (up or down) — they only append stances.
    pure_opinion_confidence: float = 0.3

    # Curated expert feeds for `bgis run "rss:all"` (RSS/Atom). Override via BGIS_RSS_FEEDS.
    rss_feeds: list[str] = Field(
        default_factory=lambda: [
            "https://simonwillison.net/atom/everything/",
        ]
    )

    # Author voice for narrative/content. "Disciplined visionary": big-picture framing, but every
    # abstraction must cash out in a concrete, specific example — no metaphors, no LinkedIn cliches.
    author_voice: str = (
        "a disciplined visionary — frames the big picture, but anchors every claim to a concrete, "
        "specific example (real project names, capabilities, numbers); avoids metaphors and hype"
    )

    # Cache LLM-extraction artifacts (claims, concepts) per source_id and reuse them on
    # re-runs, so the belief graph is reproducible despite LLM non-determinism. Set False
    # (or `bgis run --fresh`) to force re-extraction.
    use_cache: bool = True

    def stage_dir(self, stage: str) -> Path:
        """Return (creating if needed) the directory for a pipeline stage."""
        if stage not in STAGE_DIRS:
            raise ValueError(f"unknown stage: {stage!r}")
        d = self.data_dir / STAGE_DIRS[stage]
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def chroma_dir(self) -> Path:
        d = self.data_dir / "chroma"
        d.mkdir(parents=True, exist_ok=True)
        return d


def load_settings() -> Settings:
    return Settings()
