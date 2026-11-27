"""Goal Model 1.1 (Engine 3.1): exact agreement with the accepted Phase 8 research
reference (C1-2-20), Goal Model 1.0 reproducibility, market maths, the availability
gate and the limited-data warning."""

from __future__ import annotations

import dataclasses
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.stats import poisson, skellam

from diski9.research import goal_distribution as gd
from diski9.screener import goal_model as gm
from diski9.screener.engine import Match, MatchStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_phase8_cp1 as r8  # noqa: E402  (accepted CP1 research reference)

T = datetime(2025, 8, 1, 15, tzinfo=UTC)
C1_2_20 = r8.Candidate("C1-2-20", None, 2, 20)


def m(fid, days, comp, season, h, a, hg, ag, eligible=True):
    return Match(
        fid,
        T + timedelta(days=days),
        comp,
        season,
        h,
        a,
        hg,
        ag,
        "verified",
        eligible,
        None,
        None,
        "FT",
        str(fid),
    )


def synthetic(comp=39, prev=True, rounds=12, teams=12, seed=4):
    rng = np.random.default_rng(seed)
    ms, fid = [], 1
    seasons = ((2024, -365), (2025, 0)) if prev else ((2025, 0),)
    for season, offset in seasons:
        for r in range(rounds):
            for i in range(teams // 2):
                h, a = 1 + (i + r) % teams, 1 + (teams - 1 - i + r) % teams
                if h == a:
                    continue
                hg, ag = rng.poisson([1.5, 1.1])
                ms.append(m(fid, offset + r * 7 + i * 0.01, comp, season, h, a, int(hg), int(ag)))
                fid += 1
    ms.append(m(fid, 3, 40, 2025, 1, 77, 9, 0))  # team 1 in another division
    return ms


def store_of(ms):
    return MatchStore.from_matches(ms, {i: f"T{i}" for i in range(1, 99)}, {39: "EPL", 40: "Ch"})


# ------------------------------------------------------------ research equivalence
def test_parameters_frozen_and_versioned():
    assert gm.GOAL_MODEL_VERSION == "1.1"
    p = gm.PARAMS
    assert (p.k_s, p.k_t, p.team_min, p.competition_min) == (12, 96, 2, 20)
    assert not hasattr(p, "m0")  # no previous-season prior in 1.1
    with pytest.raises(AttributeError):
        gm.PARAMS.k_s = 8  # frozen dataclass
    assert len(gm.params_hash()) == 16
    # Goal Model 1.0 identity is preserved exactly (stored forecasts and snapshots)
    assert (gm.PARAMS_1_0.k_s, gm.PARAMS_1_0.k_t, gm.PARAMS_1_0.m0) == (12, 96, 30)
    assert gm.params_hash(gm.PARAMS_1_0) == "463105f660644ebf"
    assert gm.params_hash() != gm.params_hash(gm.PARAMS_1_0)


def _reference(store, comp=39, season=2025):
    """The accepted CP1 research reference with production's cutoff (kickoff, no lag)."""
    rows = r8.build_rows(store, {}, {comp}, {season}, lag=timedelta(0))
    mk, lh, la, ok = r8.predict(rows, C1_2_20)
    return rows, mk, lh, la, ok


def _ids(store, rows):
    by_id = {x.fixture_id: x for x in store.matches}
    return [by_id[int(f)] for f in rows.fixture]


def test_exact_agreement_with_accepted_research_reference():
    """Goal Model 1.1 = CP1 candidate C1-2-20, fixture by fixture, to 1e-12 (estimates,
    every market and the availability decision)."""
    store = store_of(synthetic())
    rows, mk, lh, la, ok = _reference(store)
    assert ok.sum() > 50 and (~ok).sum() > 0  # both available and gated fixtures checked
    for i, x in enumerate(_ids(store, rows)):
        e = gm.fixture_estimate(store, 39, 2025, x.home_id, x.away_id, x.kickoff)
        assert e["available"] == bool(ok[i])
        if not ok[i]:
            assert "lambda_home" not in e
            continue
        assert e["lambda_home"] == pytest.approx(lh[i], abs=1e-12)
        assert e["lambda_away"] == pytest.approx(la[i], abs=1e-12)
        for k in ("home", "draw", "away", "btts_yes", "over"):
            assert e["probabilities"][k] == pytest.approx(mk[k][i], abs=1e-12)


def test_goal_model_1_0_reproducible_from_frozen_parameters():
    """Stored 1.0 forecasts stay reproducible: the frozen 1.0 rule (previous-season
    prior, m0 30) still equals the validated 1.0 research implementation to 1e-12."""
    store = store_of(synthetic())
    ds = gd.build_dataset(store, (39,), (2025,))
    lh, la, av = gd.lambdas(ds, gd.Params("season", 12, gd.INF, 30.0, 96))
    assert av.all()
    for i in range(len(ds)):
        cut = ds.kickoff[i]
        rates = gm.league_rates_1_0(
            store.league_matches(39, 2025, cut), store.league_matches(39, 2024, cut)
        )
        recs = [
            gm.TeamRecord.of(store.team_window(int(t), cut, None, 10_000, 39, 2025))
            for t in (ds.home_id[i], ds.away_id[i])
        ]
        e = gm.estimate(*recs, rates, gm.PARAMS_1_0)
        assert e["lambda_home"] == pytest.approx(lh[i], abs=1e-12)
        assert e["lambda_away"] == pytest.approx(la[i], abs=1e-12)


def test_worked_example_from_research_report_goal_model_1_0():
    """Aston Villa v Nottingham Forest, 3 Jan 2026 (docs/goal_distribution_research.md),
    reproduced with the frozen Goal Model 1.0 rule."""
    cur = [SimpleNamespace(home_goals=g, away_goals=0) for g in [296] + [0] * 189]
    cur[1] = SimpleNamespace(home_goals=0, away_goals=230)
    prev = [SimpleNamespace(home_goals=575, away_goals=540)] + [
        SimpleNamespace(home_goals=0, away_goals=0) for _ in range(379)
    ]
    league = gm.league_rates_1_0(cur, prev)
    assert round(league[0], 4) == 1.5518 and round(league[1], 4) == 1.2392
    villa = gm.TeamRecord(9, 10, 15, 7, 15, 16)
    forest = gm.TeamRecord(10, 9, 12, 17, 6, 13)
    e = gm.estimate(villa, forest, league, gm.PARAMS_1_0)
    assert round(e["lambda_home"], 3) == 1.933 and round(e["lambda_away"], 3) == 0.962
    p = e["probabilities"]
    assert [round(p[k], 4) for k in ("home", "draw", "away", "btts_yes", "over")] == [
        0.6006,
        0.2170,
        0.1824,
        0.5284,
        0.5529,
    ]
    assert round(e["home_team"]["strength"], 4) == 1.0884
    # Goal Model 1.1 uses the current season alone: H = 296/190, A = 230/190
    rates = gm.league_rates(cur)
    assert rates.home == pytest.approx(296 / 190) and rates.away == pytest.approx(230 / 190)


# ----------------------------------------------------------------- markets
@pytest.mark.parametrize("lh,la", [(1.8, 1.1), (0.3, 2.7), (4.5, 0.2), (7.0, 6.5), (1e-4, 3.0)])
def test_markets_exact_and_normalised(lh, la):
    p = gm.markets(lh, la)
    assert p["home"] + p["draw"] + p["away"] == pytest.approx(1, abs=1e-15)
    assert p["btts_yes"] + p["btts_no"] == 1 and p["over"] + p["under"] == 1
    assert all(0 <= v <= 1 and math.isfinite(v) for v in p.values())
    assert p["draw"] == pytest.approx(skellam.pmf(0, lh, la), abs=1e-12)
    assert p["away"] == pytest.approx(skellam.cdf(-1, lh, la), abs=1e-12)
    assert p["under"] == pytest.approx(poisson.cdf(2, lh + la), abs=1e-12)
    assert p["btts_yes"] == pytest.approx((1 - math.exp(-lh)) * (1 - math.exp(-la)), abs=1e-12)


def test_markets_edge_cases_and_validation():
    p = gm.markets(0.0, 0.0)
    assert p["draw"] == 1 and p["under"] == 1 and p["btts_yes"] == 0
    for bad in (-0.1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            gm.markets(bad, 1.0)
    d = gm.goal_distribution(1.5)
    assert len(d) == 7 and sum(d) == pytest.approx(1)


def test_adjustment_example():
    base, adj = gm.markets(1.80, 1.10), gm.markets(1.55, 1.10)
    assert round(base["home"], 4) == 0.5376 and round(adj["home"], 4) == 0.4770
    assert adj["draw"] > base["draw"] and adj["over"] < base["over"]


# ------------------------------------------------------- availability gate
class _Store:
    """Minimal store: a competition with ``n`` current-season matches and two teams with
    given home/away records (the gate reads only counts and goals)."""

    def __init__(self, n_comp, home_rec, away_rec, prev=()):
        self.cur = [SimpleNamespace(home_goals=1, away_goals=1)] * n_comp
        self.prev = list(prev)
        self.recs = {1: home_rec, 2: away_rec}

    def league_matches(self, comp, season, cutoff):
        return self.cur if season == 2025 else self.prev

    def team_window(self, team, cutoff, n, limit, competition_id=None, season=None):
        rec = self.recs[team]
        h = [SimpleNamespace(is_home=True, goals_for=1, goals_against=1)] * rec[0]
        a = [SimpleNamespace(is_home=False, goals_for=1, goals_against=1)] * rec[1]
        return h + a


def _est(n_comp, home=(3, 3), away=(3, 3), prev=()):
    return gm.fixture_estimate(_Store(n_comp, home, away, prev), 39, 2025, 1, 2, T)


@pytest.mark.parametrize("n,ok", [(0, False), (1, False), (19, False), (20, True), (21, True)])
def test_competition_gate_boundary(n, ok):
    e = _est(n)
    assert e["available"] is ok
    if not ok:
        assert e["reason"] == "competition_matches_insufficient" and "lambda_home" not in e
        assert f"{n} of 20" in e["message"]


@pytest.mark.parametrize(
    "home,away,ok",
    [
        ((0, 0), (3, 3), False),
        ((1, 0), (3, 3), False),
        ((0, 1), (3, 3), False),
        ((3, 3), (1, 0), False),
        ((1, 1), (3, 3), True),  # 2 = minimum, home and away combined
        ((2, 0), (0, 2), True),
    ],
)
def test_team_gate_boundary(home, away, ok):
    e = _est(30, home, away)
    assert e["available"] is ok
    if not ok:
        assert e["reason"] == "team_matches_insufficient" and "lambda_home" not in e
        assert e["team_matches"] == {"home": sum(home), "away": sum(away)}


@pytest.mark.parametrize(
    "home,away,warn",
    [
        ((2, 2), (3, 2), True),
        ((2, 3), (2, 2), True),
        ((3, 2), (2, 3), False),
        ((1, 1), (9, 9), True),
    ],
)
def test_limited_data_warning_boundary(home, away, warn):
    """Warning when either team has fewer than 5 matches: 4 warns, 5 does not."""
    e = _est(30, home, away)
    assert e["available"] and e["early_season"] is warn
    assert "league_average_only" not in e


def test_no_previous_season_input():
    """Changing or deleting every previous-season match leaves 1.1 estimates identical,
    including the competition baseline."""
    base = store_of(synthetic())
    no_prev = store_of([x for x in synthetic() if x.season != 2024])
    other = synthetic()
    altered = store_of(
        [
            dataclasses.replace(x, home_goals=x.home_goals + 3, away_goals=0)
            if x.season == 2024
            else x
            for x in other
        ]
    )
    ms = [x for x in base.matches if x.season == 2025 and x.competition_id == 39]
    checked = 0
    for x in ms:
        es = [
            gm.fixture_estimate(s, 39, 2025, x.home_id, x.away_id, x.kickoff)
            for s in (base, no_prev, altered)
        ]
        assert es[0] == es[1] == es[2]
        checked += es[0]["available"]
    assert checked > 50


def test_shrinkage_weights():
    H, A = 1.5, 1.2
    one_win = gm.TeamRecord(1, 0, 4, 0, 0, 0)  # an opening 4-0 home win
    s, t, _ = gm.strength_tempo(one_win, H, A)
    assert round(s, 3) == 1.107 and round(t, 3) == 1.005
    e = gm.estimate(one_win, gm.TeamRecord(), gm.LeagueRates(H, A, 0, 0, 0))
    assert round(e["lambda_home"], 2) == 1.67 and e["lambda_away"] > 0


def test_league_rates_current_season_only():
    cur = [SimpleNamespace(home_goals=2, away_goals=1)] * 19
    assert gm.league_rates(cur) is None and gm.league_frequencies(cur) is None
    cur = cur + [SimpleNamespace(home_goals=0, away_goals=0)]
    L = gm.league_rates(cur)
    assert (L.home, L.away, L.current_matches) == (38 / 20, 19 / 20, 20)
    f = gm.league_frequencies(cur)
    assert f["home"] == pytest.approx(19 / 20) and f["draw"] == pytest.approx(1 / 20)
    assert gm.league_rates([SimpleNamespace(home_goals=0, away_goals=0)] * 25) is None


def test_uefa_never_modelled():
    store = store_of(synthetic())
    e = gm.fixture_estimate(store, 2, 2025, 1, 2, T + timedelta(days=100))
    assert not e["available"] and e["message"] == gm.UEFA_MESSAGE
    assert "lambda_home" not in e


def test_no_future_leakage_and_other_division_excluded():
    ms = synthetic()
    store = store_of(ms)
    x = [y for y in ms if y.season == 2025 and y.competition_id == 39][30]
    a = gm.fixture_estimate(store, 39, 2025, x.home_id, x.away_id, x.kickoff)
    later = store_of(ms + [m(9000 + i, 200 + i, 39, 2025, x.home_id, 5, 9, 0) for i in range(3)])
    b = gm.fixture_estimate(later, 39, 2025, x.home_id, x.away_id, x.kickoff)
    assert a == b
    # the 9-0 Championship match of team 1 never enters its EPL record
    e = gm.fixture_estimate(store, 39, 2025, 1, 2, T + timedelta(days=200))
    assert e["home_team"]["record"]["home_scored"] < 100
    assert all(
        t.match.competition_id == 39
        for t in store.team_window(
            1, T + timedelta(days=200), None, 999, competition_id=39, season=2025
        )
    )


def test_numerical_stability_extremes():
    H, A = 1.5, 1.2
    huge = gm.TeamRecord(19, 19, 80, 0, 70, 0)
    poor = gm.TeamRecord(19, 19, 0, 60, 0, 70)
    e = gm.estimate(huge, poor, gm.LeagueRates(H, A, 380, 0, 0))
    p = e["probabilities"]
    assert all(math.isfinite(v) for v in p.values())
    assert p["home"] + p["draw"] + p["away"] == pytest.approx(1)
