"""Goal Model 1.0 (Engine 3.0): exact agreement with the validated research
implementation, market maths, early-season behaviour and availability rules."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.stats import poisson, skellam

from diski9.research import goal_distribution as gd
from diski9.screener import goal_model as gm
from diski9.screener.engine import Match, MatchStore

T = datetime(2025, 8, 1, 15, tzinfo=UTC)


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
    assert gm.GOAL_MODEL_VERSION == "1.0"
    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.m0) == (12, 96, 30)
    with pytest.raises(AttributeError):
        gm.PARAMS.k_s = 8  # frozen dataclass
    assert len(gm.params_hash()) == 16


def test_exact_agreement_with_research_model():
    store = store_of(synthetic())
    ds = gd.build_dataset(store, (39,), (2025,))
    lh, la, av = gd.lambdas(ds, gd.Params("season", 12, gd.INF, 30.0, 96))
    mk = gd.poisson_markets(lh, la)
    assert av.all()
    for i in range(len(ds)):
        e = gm.fixture_estimate(
            store, 39, 2025, int(ds.home_id[i]), int(ds.away_id[i]), ds.kickoff[i]
        )
        assert e["lambda_home"] == pytest.approx(lh[i], abs=1e-12)
        assert e["lambda_away"] == pytest.approx(la[i], abs=1e-12)
        for k in ("home", "draw", "away", "btts_yes", "over"):
            assert e["probabilities"][k] == pytest.approx(mk[k][i], abs=1e-12)


def test_worked_example_from_research_report():
    """Aston Villa v Nottingham Forest, 3 Jan 2026 (docs/goal_distribution_research.md)."""
    cur = [SimpleNamespace(home_goals=g, away_goals=0) for g in [296] + [0] * 189]
    cur[1] = SimpleNamespace(home_goals=0, away_goals=230)
    prev = [SimpleNamespace(home_goals=575, away_goals=540)] + [
        SimpleNamespace(home_goals=0, away_goals=0) for _ in range(379)
    ]
    league = gm.league_rates(cur, prev)
    assert round(league.home, 4) == 1.5518 and round(league.away, 4) == 1.2392
    villa = gm.TeamRecord(9, 10, 15, 7, 15, 16)
    forest = gm.TeamRecord(10, 9, 12, 17, 6, 13)
    e = gm.estimate(villa, forest, league)
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


# ------------------------------------------------------- early season / priors
def test_zero_matches_gives_league_rates_and_flags():
    store = store_of(synthetic())
    first = min(
        (x for x in store.matches if x.season == 2025 and x.competition_id == 39),
        key=lambda x: x.kickoff,
    )
    e = gm.fixture_estimate(store, 39, 2025, first.home_id, first.away_id, first.kickoff)
    assert e["available"] and e["league"]["current_matches"] == 0
    assert e["lambda_home"] == pytest.approx(e["league"]["home"])
    assert e["lambda_away"] == pytest.approx(e["league"]["away"])
    assert e["league_average_only"] == ["home", "away"] and e["early_season"]
    # previous season league average only, never previous-season team results
    assert e["home_team"]["record"]["home_played"] == 0


def test_shrinkage_weights():
    H, A = 1.5, 1.2
    one_win = gm.TeamRecord(1, 0, 4, 0, 0, 0)  # an opening 4-0 home win
    s, t, _ = gm.strength_tempo(one_win, H, A)
    assert round(s, 3) == 1.107 and round(t, 3) == 1.005
    e = gm.estimate(one_win, gm.TeamRecord(), gm.LeagueRates(H, A, 0, 0, 0, 0, None, None, "x"))
    assert round(e["lambda_home"], 2) == 1.67 and e["lambda_away"] > 0


def test_previous_season_prior_and_unavailable_rule():
    store = store_of(synthetic(prev=False))
    ms = [x for x in store.matches if x.competition_id == 39]
    early = ms[10]
    e = gm.fixture_estimate(store, 39, 2025, early.home_id, early.away_id, early.kickoff)
    assert not e["available"] and e["reason"] == "league_prior_unavailable"
    later = ms[40]  # 40 current matches: current season alone
    e = gm.fixture_estimate(store, 39, 2025, later.home_id, later.away_id, later.kickoff)
    assert e["available"] and e["league"]["source"] == "current only"
    with_prev = store_of(synthetic())
    x = [y for y in with_prev.matches if y.season == 2025 and y.competition_id == 39][20]
    e = gm.fixture_estimate(with_prev, 39, 2025, x.home_id, x.away_id, x.kickoff)
    L = e["league"]
    assert L["home"] == pytest.approx(
        (L["current_home_goals"] + 30 * L["previous_home_per_match"]) / (L["current_matches"] + 30)
    )


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
    e = gm.estimate(huge, poor, gm.LeagueRates(H, A, 380, 0, 0, 0, None, None, "x"))
    p = e["probabilities"]
    assert all(math.isfinite(v) for v in p.values())
    assert p["home"] + p["draw"] + p["away"] == pytest.approx(1)
