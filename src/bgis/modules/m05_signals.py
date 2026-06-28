"""Module 5 — Signal Extraction.

Extract measurable, observable facts from the repository. Signals are first-class
citizens distinct from claims: claims are semantic statements, signals are numbers.

In:  Repository
Out: Signals{ signals: [ Signal{ name, value, unit, period?, source_field } ] }

Fully deterministic — no LLM, no network. Pure function over Repository.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..context import Context
from ..models import Repository, Signal, Signals


def run(inp: Repository, ctx: Context) -> Signals:
    sigs: list[Signal] = []

    # Direct counts.
    sigs.append(Signal(name="stars", value=float(inp.stars), unit="count", source_field="stars"))
    sigs.append(Signal(name="forks", value=float(inp.forks), unit="count", source_field="forks"))
    sigs.append(
        Signal(name="watchers", value=float(inp.watchers), unit="count", source_field="watchers")
    )
    sigs.append(
        Signal(name="open_issues", value=float(inp.open_issues), unit="count",
               source_field="open_issues")
    )
    sigs.append(
        Signal(name="contributors", value=float(inp.contributors_count), unit="count",
               source_field="contributors_count")
    )
    sigs.append(
        Signal(name="dependency_count", value=float(_dependency_count(inp)), unit="count",
               source_field="dependency_files")
    )

    # Release cadence (avg days between releases).
    cadence = _release_cadence_days(inp)
    if cadence is not None:
        sigs.append(
            Signal(name="release_cadence", value=cadence, unit="days", period="per_release",
                   source_field="releases")
        )

    # Commit frequency (commits per day across the captured commit window).
    freq = _commit_frequency_per_day(inp)
    if freq is not None:
        sigs.append(
            Signal(name="commit_frequency", value=freq, unit="commits", period="per_day",
                   source_field="commits_recent")
        )

    # Repository age and days since last push.
    age = _days_since(inp.created_at)
    if age is not None:
        sigs.append(
            Signal(name="repo_age", value=age, unit="days", source_field="created_at")
        )
    idle = _days_since(inp.pushed_at)
    if idle is not None:
        sigs.append(
            Signal(name="days_since_push", value=idle, unit="days", source_field="pushed_at")
        )

    # Language distribution (% of bytes per language).
    total = sum(inp.languages.values())
    if total > 0:
        for lang, byts in sorted(inp.languages.items(), key=lambda kv: -kv[1]):
            sigs.append(
                Signal(
                    name=f"language_pct:{lang}",
                    value=round(byts * 100.0 / total, 2),
                    unit="percent",
                    source_field="languages",
                )
            )

    return Signals(source_id=inp.source_id, signals=sigs)


def _dependency_count(repo: Repository) -> int:
    """Count non-empty, non-comment lines across dependency manifests (rough)."""
    n = 0
    for d in repo.dependency_files:
        for line in d.raw.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                n += 1
    return n


def _release_cadence_days(repo: Repository) -> float | None:
    dates = sorted(r.date for r in repo.releases if r.date)
    if len(dates) < 2:
        return None
    span_days = (dates[-1] - dates[0]).total_seconds() / 86400.0
    intervals = len(dates) - 1
    return round(span_days / intervals, 2) if intervals else None


def _commit_frequency_per_day(repo: Repository) -> float | None:
    dates = sorted(c.date for c in repo.commits_recent if c.date)
    if len(dates) < 2:
        return None
    span_days = (dates[-1] - dates[0]).total_seconds() / 86400.0
    if span_days <= 0:
        return None
    return round(len(dates) / span_days, 3)


def _days_since(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((now - dt).total_seconds() / 86400.0, 1)
