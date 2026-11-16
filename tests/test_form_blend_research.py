"""Research only: venue / overall / blended Form Score dataset."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from diski9.research.form_blend import WEIGHTS, BlendRow, build_rows
from diski9.screener.engine import Match, MatchStore

T = datetime(2026, 9, 1, 15, tzinfo=UTC)


def _row(**kw):
    base = dict(
        fixture_id=1,
        competition_id=39,
        season=2026,
        kickoff=T,
        outcome=0,
        home_venue=3.8,
        home_overall=2.2,
        away_venue=1.0,
        away_overall=2.0,
        n_home_venue=5,
        n_home_overall=5,
        n_away_venue=5,
        n_away_overall=5,
        bench_home=2.7,
        bench_away=2.0,
        bench_overall=2.4,
        shared_home=2,
        shared_away=2,
    )
    base.update(kw)
    return BlendRow(**base)


def test_blend_arithmetic_and_benchmarks_use_same_weights():
    r = _row()
    assert WEIGHTS == {
        "venue": 1.0,
        "blend_75v": 0.75,
        "blend_50": 0.5,
        "blend_25v": 0.25,
        "overall": 0.0,
    }
    assert r.home(1.0) == 3.8 and r.home(0.0) == 2.2
    assert r.home(0.5) == pytest.approx(3.0)
    assert r.rel_home(1.0) == pytest.approx(3.8 - 2.7)  # venue vs home-form average
    assert r.rel_home(0.0) == pytest.approx(2.2 - 2.4)  # overall vs overall average
    assert r.rel_home(0.5) == pytest.approx(3.0 - (0.5 * 2.7 + 0.5 * 2.4))
    assert r.rel_away(0.25) == pytest.approx((0.25 * 1.0 + 0.75 * 2.0) - (0.25 * 2.0 + 0.75 * 2.4))
    assert r.diff(0.5) == pytest.approx(r.home(0.5) - r.away(0.5))
    assert not _row(n_away_venue=4).complete


def _m(fid, days, h, a, hg, ag):
    return Match(
        fid,
        T + timedelta(days=days),
        39,
        2026,
        h,
        a,
        hg,
        ag,
        "verified",
        True,
        None,
        None,
        "FT",
        str(fid),
    )


def test_rows_are_point_in_time_and_need_benchmarks():
    ms, fid, day = [], 1, 0.0
    for h in range(1, 15):
        for a in range(1, 15):
            if h != a:
                ms.append(_m(fid, day, h, a, *((2, 0) if h < a else (1, 1))))
                fid += 1
                day += 0.05
    store = MatchStore.from_matches(ms, {i: str(i) for i in range(1, 99)}, {39: "EPL"})
    rows, skipped = build_rows(store, (39,), (2026,))
    assert rows and skipped["no_benchmark"] + skipped["no_score"] > 0  # early fixtures dropped
    later = MatchStore.from_matches(
        ms + [_m(9_000 + i, 500 + i, 1, 2, 0, 9) for i in range(5)],
        {i: str(i) for i in range(1, 99)},
        {39: "EPL"},
    )
    rows2, _ = build_rows(later, (39,), (2026,))
    by_id = {r.fixture_id: r for r in rows2}
    for r in rows:  # adding later results never changes an earlier fixture's row
        assert by_id[r.fixture_id] == r
    assert all(0 <= r.shared_home <= 5 for r in rows)
