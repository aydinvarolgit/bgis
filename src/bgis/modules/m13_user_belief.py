"""Module 13 — User Belief Graph (STUB in MVP).

Represents the author's own opinions, merged at narrative time (Module 14). The user
graph NEVER modifies the global belief graph — it is a separate, read-only input to
content generation.

In:  (none) — reads optional `data/user_beliefs.json`
Out: UserBeliefs{ beliefs: [...] }

MVP: hand-written JSON file, loaded if present, else empty. Future: derived from the
author's posts/documents.

File format (data/user_beliefs.json):
    { "beliefs": [
        { "statement": "Frontier models are commoditizing",
          "confidence": 0.95,
          "supporting_evidence": ["my LinkedIn post 2026-05"] }
    ] }
"""

from __future__ import annotations

from ..context import Context
from ..models import UserBeliefs


def user_beliefs_path(ctx: Context):
    return ctx.settings.data_dir / "user_beliefs.json"


def run(ctx: Context) -> UserBeliefs:
    path = user_beliefs_path(ctx)
    if not path.exists():
        return UserBeliefs(beliefs=[])
    return UserBeliefs.model_validate_json(path.read_text(encoding="utf-8"))
