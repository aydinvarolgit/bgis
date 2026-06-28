from datetime import datetime, timezone

from bgis import cli
from bgis.models import Belief, BeliefHistoryEntry


def _belief(conf, deltas_sources):
    h = [
        BeliefHistoryEntry(ts=datetime.now(timezone.utc), conf_before=0.0, conf_after=conf,
                           delta=d, source_id=s)
        for d, s in deltas_sources
    ]
    return Belief(id="bel_x", statement="s", confidence=conf, history=h)


def test_nsrc_counts_distinct_sources():
    b = _belief(0.9, [(0.5, "src_a"), (0.2, "src_b"), (0.1, "src_a")])  # a twice
    assert cli._nsrc(b) == 2


def test_last_delta_uses_latest_history_entry():
    b = _belief(0.9, [(0.5, "src_a"), (0.07, "src_b")])
    assert cli._last_delta(b) == 0.07


def test_last_delta_empty_history_is_zero():
    assert cli._last_delta(Belief(id="b", statement="s", confidence=0.5)) == 0.0
