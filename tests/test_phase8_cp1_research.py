"""Research only (Phase 8 CP1): UEFA stage safeguards, the availability lag, the
team / competition gates and agreement of C0 with production Goal Model 1.0."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import research_phase8_cp1 as r8  # noqa: E402

from diski9.screener import goal_model as gm  # noqa: E402
from diski9.screener.engine import Match, MatchStore  # noqa: E402

T0 = datetime(2025, 8, 1, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    "label,expected",
    [
        ("1st Qualifying Round", ("qualifying", None)),
        ("Preliminary Round", ("qualifying", None)),
        ("Play-offs", ("qualifying", None)),  # the August qualifying play-off
        ("Group C - 4", ("group", 4)),
        ("League Stage - 7", ("league", 7)),
        ("Knockout Round Play-offs", ("knockout", None)),
        ("Round of 32", ("knockout", None)),  # 2025/26 knockout play-off label
        ("Round of 16", ("knockout", None)),
        ("Semi-finals", ("knockout", None)),
        ("Final", ("final", None)),
    ],
)
def test_uefa_stage(label, expected):
    assert r8.uefa_stage(label) == expected


def test_unknown_uefa_label_stops_the_run():
    with pytest.raises(r8.StageError):
        r8.uefa_stage("Round of 64")


def test_knockout_before_main_stage_stops_the_run():
    rows = [(2, 2025, "league", T0 + timedelta(days=30)), (2, 2025, "knockout", T0)]
    with pytest.raises(r8.StageError):
        r8.check_stage_order(rows)
    r8.check_stage_order([(2, 2025, "league", T0), (2, 2025, "knockout", T0 + timedelta(1))])


def _m(fid, k, h, a, hg, ag, comp=39, season=2025):
    return Match(fid, k, comp, season, h, a, hg, ag, "home_ground", True, "Regular Season - 1",
                 "x", "FT", "h")  # fmt: skip


def _store(ms):
    return MatchStore.from_matches(ms, {}, {})


def test_availability_lag_excludes_overlapping_matches():
    """A match that kicked off 2 hours earlier is not yet complete: never a feature."""
    ms = [_m(1, T0, 10, 11, 3, 0), _m(2, T0 + timedelta(hours=2), 10, 12, 1, 1),
          _m(3, T0 + timedelta(hours=5), 10, 13, 0, 0)]  # fmt: skip
    rows = r8.build_rows(_store(ms), {}, {39}, {2025})
    played_home = rows.played[0]
    assert list(played_home) == [0, 0, 1]  # fixture 2 sees nothing; fixture 3 sees only 1
    assert list(rows.cur_n) == [0, 0, 1]


def _rows(team, cur_n=40, cur_hg=60, cur_ag=44, prev_n=0):
    n = len(team)
    z = np.zeros(n)
    return r8.Rows(
        fixture=np.arange(n), comp=np.full(n, 39), season=np.full(n, 2025), kickoff=[T0] * n,
        stage=["league"] * n, matchday=z, hg=z, ag=z, cur_n=np.full(n, cur_n),
        cur_hg=np.full(n, cur_hg), cur_ag=np.full(n, cur_ag), cur_res=np.ones((n, 5)),
        prev_n=np.full(n, prev_n), prev_hg=np.full(n, 1.5 * prev_n),
        prev_ag=np.full(n, 1.2 * prev_n), prev_res=np.ones((n, 5)), team=np.array(team, float),
    )  # fmt: skip


def test_team_and_competition_gates():
    one = [1, 1, 2, 1, 0, 1] + [1, 0, 1, 1, 0, 0]  # home team 2 matches, away team 1
    two = [1, 1, 2, 1, 0, 1] + [1, 1, 1, 1, 0, 0]
    r = _rows([one, two])
    assert list(r8.predict(r, r8.Candidate("x", None, k=2, L=20))[3]) == [False, True]
    assert not r8.predict(r, r8.Candidate("x", None, k=2, L=41))[3].any()
    assert r8.predict(r, r8.Candidate("x", r8.M0, k=0))[3].all()


def test_current_season_only_uses_no_previous_season():
    rec = [3, 2, 7, 3, 2, 4] + [2, 3, 3, 5, 4, 6]
    a = r8.predict(_rows([rec], prev_n=0), r8.Candidate("x", None))[1]
    b = r8.predict(_rows([rec], prev_n=380), r8.Candidate("x", None))[1]
    assert a[0] == pytest.approx(b[0], abs=1e-15)


def test_c0_reproduces_production_goal_model():
    rec = [3, 2, 7, 3, 2, 4] + [2, 3, 3, 5, 4, 6]
    r = _rows([rec], cur_n=50, cur_hg=70, cur_ag=55, prev_n=380)
    mk, lh, la, ok = r8.predict(r, r8.C0)
    H = (70 + 30 * 1.5) / (50 + 30)
    A = (55 + 30 * 1.2) / (50 + 30)
    e = gm.estimate(gm.TeamRecord(*rec[:6]), gm.TeamRecord(*rec[6:]),
                    gm.LeagueRates(H, A, 0, 0, 0, 0, None, None, "x"))  # fmt: skip
    assert ok[0]
    assert lh[0] == pytest.approx(e["lambda_home"], abs=1e-12)
    assert la[0] == pytest.approx(e["lambda_away"], abs=1e-12)
    assert mk["home"][0] == pytest.approx(e["probabilities"]["home"], abs=1e-12)
