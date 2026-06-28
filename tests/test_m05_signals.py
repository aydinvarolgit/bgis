from datetime import datetime, timezone

from bgis.models import Commit, DependencyFile, Release, Repository
from bgis.modules import m05_signals


def _repo(**kw):
    base = dict(
        source_id="src_test",
        owner="o",
        name="n",
        stars=1200,
        forks=80,
        watchers=30,
        open_issues=5,
        contributors_count=7,
        languages={"Python": 9000, "Shell": 1000},
        dependency_files=[DependencyFile(path="requirements.txt", raw="requests\n# c\npydantic\n")],
        releases=[
            Release(tag="v1", date=datetime(2024, 1, 1, tzinfo=timezone.utc)),
            Release(tag="v2", date=datetime(2024, 1, 11, tzinfo=timezone.utc)),
            Release(tag="v3", date=datetime(2024, 1, 21, tzinfo=timezone.utc)),
        ],
        commits_recent=[
            Commit(sha="a", date=datetime(2024, 1, 1, tzinfo=timezone.utc)),
            Commit(sha="b", date=datetime(2024, 1, 3, tzinfo=timezone.utc)),
            Commit(sha="c", date=datetime(2024, 1, 5, tzinfo=timezone.utc)),
        ],
    )
    base.update(kw)
    return Repository(**base)


def _by(sigs, name):
    return next(s for s in sigs.signals if s.name == name)


def test_direct_counts(ctx):
    s = m05_signals.run(_repo(), ctx)
    assert _by(s, "stars").value == 1200
    assert _by(s, "forks").value == 80
    assert _by(s, "contributors").value == 7


def test_dependency_count_ignores_comments(ctx):
    s = m05_signals.run(_repo(), ctx)
    assert _by(s, "dependency_count").value == 2  # requests + pydantic, comment skipped


def test_release_cadence(ctx):
    s = m05_signals.run(_repo(), ctx)
    # 20 days span over 2 intervals = 10 days/release
    assert _by(s, "release_cadence").value == 10.0


def test_commit_frequency(ctx):
    s = m05_signals.run(_repo(), ctx)
    # 3 commits over 4-day span = 0.75/day
    assert _by(s, "commit_frequency").value == 0.75


def test_language_pct(ctx):
    s = m05_signals.run(_repo(), ctx)
    assert _by(s, "language_pct:Python").value == 90.0
    assert _by(s, "language_pct:Shell").value == 10.0


def test_cadence_absent_with_single_release(ctx):
    s = m05_signals.run(_repo(releases=[Release(tag="v1", date=datetime(2024, 1, 1))]), ctx)
    names = {x.name for x in s.signals}
    assert "release_cadence" not in names
