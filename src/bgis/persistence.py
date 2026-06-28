"""JSON artifact persistence, keyed by pipeline stage + source_id.

Every module output is saved to `data/<stage>/<source_id>.json` so the pipeline is
fully replayable and each module boundary is inspectable.
"""

from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel

from .config import Settings

T = TypeVar("T", bound=BaseModel)


def save_artifact(settings: Settings, stage: str, source_id: str, model: BaseModel) -> str:
    """Persist a Pydantic model as pretty JSON. Returns the file path."""
    path = settings.stage_dir(stage) / f"{source_id}.json"
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return str(path)


def load_artifact(settings: Settings, stage: str, source_id: str, model_cls: Type[T]) -> T:
    """Load and validate a persisted artifact back into its model."""
    path = settings.stage_dir(stage) / f"{source_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"no {stage} artifact for source_id={source_id} at {path}")
    return model_cls.model_validate_json(path.read_text(encoding="utf-8"))


def artifact_exists(settings: Settings, stage: str, source_id: str) -> bool:
    return (settings.stage_dir(stage) / f"{source_id}.json").exists()
