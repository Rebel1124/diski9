"""Research only: window length and venue adjustments (form_adjust)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from diski9.research.form_adjust import ADJUST_WEIGHTS, WINDOWS, AdjustRow

T = datetime(2026, 9, 1, 15, tzinfo=UTC)


def _row(bench=True):
    return AdjustRow(
        fixture_id=1,
        competition_id=39,
        season=2026,
        kickoff=T,
        home_id=1,
        away_id=2,
        outcome=0,
        days_into_season=30.0,
        venue=(3.8, 1.2),
        overall={n: (2.2 + 0.1 * (n - 5), 2.0) for n in WINDOWS},
        bench_venue=(2.7, 2.0) if bench else (None, 2.0),
        bench_overall={n: 2.4 for n in WINDOWS},
        window_len={"venue": (5, 5), "o5": (5, 5)},
        reaches_back={n: (False, False) for n in WINDOWS},
        oldest_days={n: (40.0, 40.0) for n in WINDOWS},
    )


def test_predeclared_weights_and_windows():
    assert ADJUST_WEIGHTS == (0.0, 0.25, 0.5) and WINDOWS == (5, 6, 7, 8)


def test_raw_and_league_relative_adjustments():
    r = _row()
    oh, oa = r.overall[8]
    assert r.adjustment(8, "raw") == pytest.approx((3.8 - oh, 1.2 - oa))
    rel = r.adjustment(8, "rel")
    assert rel[0] == pytest.approx((3.8 - 2.7) - (oh - 2.4))  # home: vs league home average
    assert rel[1] == pytest.approx((1.2 - 2.0) - (oa - 2.4))  # away: vs league away average
    assert _row(bench=False).adjustment(8, "rel") is None  # never invented
    assert _row(bench=False).adjusted_diff(8, "rel", 0.25) is None


def test_team_level_and_match_level_adjustment_are_identical():
    r = _row()
    for kind in ("raw", "rel"):
        for w in ADJUST_WEIGHTS:
            ah, aa = r.adjustment(8, kind)
            team_level = (r.overall[8][0] + w * ah) - (r.overall[8][1] + w * aa)
            assert r.adjusted_diff(8, kind, w) == pytest.approx(team_level)
    assert r.adjusted_diff(8, "raw", 0.0) == pytest.approx(r.diff(8))
