"""Runtime settings and filesystem paths.

All configuration is read from the environment (and `.env`) via pydantic-settings.
Paths default to a `data/` tree under the project root and are created on demand.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = three levels up from this file (src/bgis/config.py -> project root).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

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


class Settings(BaseSettings):
    """Central config object passed around via Context."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="BGIS_",
        extra="ignore",
    )

    # Secrets / external services. GITHUB_TOKEN has no prefix (read directly).
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "gemma4:latest"
    embed_model: str = "nomic-embed-text"

    data_dir: Path = PROJECT_ROOT / "data"
    # Cosine-similarity thresholds (measured: paraphrases ~0.66-0.81, distinct <=0.46).
    # Concept dedup is banded: >= auto_merge -> merge; < similarity -> new;
    # in between -> LLM adjudicates (the concept-merge pass).
    concept_similarity_threshold: float = 0.60  # lower bound to even consider a merge
    concept_auto_merge_threshold: float = 0.72  # at/above this, merge without asking the LLM
    belief_retrieval_threshold: float = 0.50  # looser: surface related (not identical) beliefs

    # Author voice for narrative/content (from the user-belief questionnaire).
    author_voice: str = "visionary, big-picture, future-oriented"

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

    @property
    def ollama_openai_url(self) -> str:
        """OpenAI-compatible endpoint exposed by Ollama (for instructor/openai client)."""
        return f"{self.ollama_base_url.rstrip('/')}/v1"


def load_settings() -> Settings:
    return Settings()
