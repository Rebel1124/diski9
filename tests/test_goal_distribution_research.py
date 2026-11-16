"""Research only: unified goal-distribution model (probability maths and
point-in-time methodology)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.stats import poisson, skellam

from diski9.research.goal_distribution import (
    INF,
    LEAGUE_MIN,
    Params,
    build_dataset,
    dixon_coles_adjust,
    empirical_marginals,
    goal_grid,
    lambdas,
    league_rates,
    league_weight,
    markets_from_marginals,
    poisson_marginals,
    poisson_markets,
    poisson_score_logprob,
    strength_tempo,
    tune_poisson,
)
from diski9.screener.engine import Match, MatchStore

T = datetime(2025, 8, 1, 15, tzinfo=UTC)


# --------------------------------------------------------------- probability maths
@pytest.mark.parametrize("lh,la", [(1.8, 1.1), (0.3, 2.7), (4.5, 0.2), (6.0, 5.5), (1e-4, 1e-4)])
def test_markets_exact_and_normalised(lh, la):
    mk = poisson_markets([lh], [la])
    get = {k: float(v[0]) for k, v in mk.items()}
    assert get["home"] + get["draw"] + get["away"] == pytest.approx(1, abs=1e-15)
    assert get["btts_yes"] + get["btts_no"] == pytest.approx(1, abs=1e-15)
    assert get["over"] + get["under"] == pytest.approx(1, abs=1e-15)
    assert get["mass"] == pytest.approx(1, abs=1e-12)  # no truncation loss
    # independent closed forms
    assert get["draw"] == pytest.approx(skellam.pmf(0, lh, la), abs=1e-12)
    assert get["away"] == pytest.approx(skellam.cdf(-1, lh, la), abs=1e-12)
    assert get["btts_yes"] == pytest.approx((1 - math.exp(-lh)) * (1 - math.exp(-la)), abs=1e-12)
    assert get["under"] == pytest.approx(poisson.cdf(2, lh + la), abs=1e-12)


def test_grid_tail_is_negligible():
    for lam in (0.1, 1.5, 4.0, 10.0):
        G = goal_grid(lam)
        assert poisson.sf(G - 1, lam) < 1e-15
        assert poisson_marginals([lam], G).sum() == pytest.approx(1, abs=1e-14)


def test_zero_lambda_is_a_point_mass():
    mk = poisson_markets([0.0], [1.2])
    assert mk["home"][0] == 0 and mk["btts_yes"][0] == 0
    assert mk["draw"][0] == pytest.approx(math.exp(-1.2))


def test_qualitative_adjustment_recomputes_all_markets():
    base = poisson_markets([1.80], [1.10])
    adj = poisson_markets([1.55], [1.10])
    assert round(float(base["home"][0]), 4) == 0.5376 and round(float(adj["home"][0]), 4) == 0.4770
    assert adj["home"][0] < base["home"][0]
    assert adj["draw"][0] > base["draw"][0] and adj["away"][0] > base["away"][0]
    assert adj["btts_yes"][0] < base["btts_yes"][0] and adj["over"][0] < base["over"][0]


def test_dixon_coles_adjustment_preserves_totals():
    lh, la = np.array([1.4, 0.9]), np.array([1.1, 1.6])
    mk = poisson_markets(lh, la)
    same = dixon_coles_adjust(mk, lh, la, 0.0)
    for k in ("home", "draw", "away", "btts_yes"):
        assert np.allclose(same[k], mk[k])
    dc = dixon_coles_adjust(mk, lh, la, -0.1)
    assert np.allclose(dc["home"] + dc["draw"] + dc["away"], 1)
    assert np.allclose(dc["under"], mk["under"])  # all four cells have <= 2 goals
    assert (dc["draw"] > mk["draw"]).all()  # negative rho adds draws


def test_score_logprob_matches_pmf_and_clips_zero_probability():
    lp = poisson_score_logprob(np.array([1.3]), np.array([0.8]), np.array([2]), np.array([1]))
    assert lp[0] == pytest.approx(math.log(poisson.pmf(2, 1.3) * poisson.pmf(1, 0.8)))
    zero = poisson_score_logprob(np.array([0.0]), np.array([1.0]), np.array([1]), np.array([0]))
    assert zero[0] == pytest.approx(math.log(1e-12))


def test_empirical_marginals_are_distributions():
    ds = synthetic_dataset()
    ph, pa, av = empirical_marginals(ds, 4, 8, 30)
    assert np.allclose(ph[av].sum(axis=1), 1) and np.allclose(pa[av].sum(axis=1), 1)
    mk = markets_from_marginals(ph[av], pa[av])
    assert np.allclose(mk["home"] + mk["draw"] + mk["away"], 1)


# ------------------------------------------------------------------- shrinkage
def test_league_weight_schedule():
    w = league_weight(0, 12, INF)
    assert w["league_average"] == 1 and w["overall_record"] == 0
    assert league_weight(12, 12, INF)["league_average"] == pytest.approx(0.5)
    v = league_weight(10, 8, 4)  # 5 venue matches, k_v = 4
    assert v["venue_record"] == pytest.approx(5 / 9)
    assert v["venue_record"] + v["overall_record"] + v["league_average"] == pytest.approx(1)


def test_strength_tempo_equals_plain_model_when_k_equal():
    ds = synthetic_dataset()
    for k in (2.0, 12.0):
        a = lambdas(ds, Params("season", k, INF, 30))
        b = lambdas(ds, Params("season", k, INF, 30, k_t=k))
        assert np.allclose(a[0], b[0], equal_nan=True) and np.allclose(a[1], b[1], equal_nan=True)


def test_strength_tempo_identity():
    ds = synthetic_dataset()
    p = Params("season", 6, INF, 30, k_t=50)
    lh, la, av = lambdas(ds, p)
    H, A, _ = league_rates(ds, 30)
    t = ds.team["season"]
    sh, th = strength_tempo(t[:, :6], H, A, 6, 50)
    sa, ta = strength_tempo(t[:, 6:], H, A, 6, 50)
    assert np.allclose((lh * la / (H * A))[av], ((th * ta) ** 2)[av])
    assert np.allclose((lh / la * A / H)[av], ((sh / sa) ** 2)[av])


def test_no_team_history_gives_league_rates_and_raw_rates_are_unstable():
    ds = synthetic_dataset()
    H, A, av = league_rates(ds, 30)
    first = av & (ds.team["season"][:, 0] + ds.team["season"][:, 1] == 0)
    first &= ds.team["season"][:, 6] + ds.team["season"][:, 7] == 0
    assert first.any()
    lh, la, _ = lambdas(ds, Params("season", 8, 8, 30))
    assert np.allclose(lh[first], H[first]) and np.allclose(la[first], A[first])
    huge = lambdas(ds, Params("season", 1e12, INF, 30))
    assert np.allclose(huge[0][av], H[av])
    raw = lambdas(ds, Params("season", 0, 0, 30))
    smooth = lambdas(ds, Params("season", 4, 8, 30))
    assert (raw[0][av] == 0).any()  # a team that has not scored: lambda 0
    assert (smooth[0][av] > 0).all()


# --------------------------------------------------------------- point in time
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


def synthetic_matches():
    ms, fid = [], 1
    rng = np.random.default_rng(3)
    for season, offset in ((2024, -365), (2025, 0)):
        day = offset
        for rnd in range(10):
            teams = list(range(1, 11))
            for i in range(5):
                h, a = teams[(i + rnd) % 10], teams[(9 - i + rnd) % 10]
                if h == a:
                    continue
                ms.append(m(fid, day + i * 0.1, 39, season, h, a, *rng.poisson([1.5, 1.1])))
                fid += 1
            day += 7
    ms.append(m(fid, 3, 40, 2025, 1, 50, 7, 0))  # team 1 in another division
    return ms


def store_of(ms):
    return MatchStore.from_matches(ms, {i: f"T{i}" for i in range(1, 99)}, {39: "EPL", 40: "Ch"})


def synthetic_dataset():
    return build_dataset(store_of(synthetic_matches()), (39,), (2025,))


def test_team_stats_current_season_and_competition_only():
    ds = synthetic_dataset()
    first = int(np.argmin([k for k in ds.kickoff]))
    t = ds.team["season"][first]
    assert t.sum() == 0  # opening match: no previous-season or other-division history
    assert ds.prev_n[first] > 0  # but the previous season's league average is known
    assert ds.cur_n[first] == 0


def test_later_results_never_change_earlier_rows():
    ms = synthetic_matches()
    a = build_dataset(store_of(ms), (39,), (2025,))
    later = ms + [m(9000 + i, 200 + i, 39, 2025, 1, 2, 9, 0) for i in range(3)]
    b = build_dataset(store_of(later), (39,), (2025,))
    n = len(a)
    for w in a.team:
        assert np.array_equal(a.team[w], b.team[w][:n])
    assert np.array_equal(a.cur_hg, b.cur_hg[:n]) and np.array_equal(a.cats, b.cats[:n])


def test_same_kickoff_match_is_not_used():
    ms = synthetic_matches()
    ref = [x for x in ms if x.season == 2025 and x.competition_id == 39][12]
    k = ref.kickoff
    twin = m(8000, (k - T).total_seconds() / 86400, 39, 2025, 1, 2, 5, 5)
    ds = build_dataset(store_of(ms + [twin]), (39,), (2025,))
    i = list(ds.fixture_id).index(8000)
    j = list(ds.fixture_id).index(ref.fixture_id)
    assert ds.cur_n[i] == ds.cur_n[j]  # neither sees the other


def test_league_prior_availability():
    ds = build_dataset(
        store_of([x for x in synthetic_matches() if x.season == 2025]), (39,), (2025,)
    )
    H, A, av = league_rates(ds, 30)
    assert not av[ds.cur_n < LEAGUE_MIN].any()  # no previous season: wait for 30 matches
    assert np.isnan(H[~av]).all()
    full = synthetic_dataset()
    H2, _, av2 = league_rates(full, 30)
    assert av2.all()
    i = int(np.argmax(full.cur_n))
    prev = full.prev_hg[i] / full.prev_n[i]
    assert H2[i] == pytest.approx((full.cur_hg[i] + 30 * prev) / (full.cur_n[i] + 30))


def test_tuning_ignores_test_outcomes():
    ds = synthetic_dataset()
    grid = [Params("season", k, INF, 30) for k in (1, 4, 16)]
    train = ds.subset(np.arange(len(ds)) < len(ds) // 2)
    best, _ = tune_poisson(train, grid)
    shuffled = synthetic_dataset()
    rng = np.random.default_rng(0)
    half = np.arange(len(ds)) >= len(ds) // 2
    shuffled.hg[half] = rng.permutation(shuffled.hg[half])
    best2, _ = tune_poisson(shuffled.subset(~half), grid)
    assert best == best2
