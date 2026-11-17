# ruff: noqa: F811, E741  (pytest fixtures used as arguments; O follows the brief's notation)
"""Phase 5B research: Weekly Challenge portfolio mathematics (research only).

Covers partitions, the exact eight-state distribution, allocation constraints,
the three allocation strategies, recovery optimisation, Pareto frontiers,
dependence scenarios, real-data read-only loading and Goal Model invariance."""

from __future__ import annotations

import itertools
import math
import random
from fractions import Fraction as F

import numpy as np
import pytest
from sqlalchemy import func, select

from diski9.research import challenge_experiments as ce
from diski9.research import challenge_portfolio as cp

from .test_app import populated  # noqa: F401  (fixture)

# ----------------------------------------------------------------- inputs
P9 = [0.6, 0.55, 0.5, 0.45, 0.4, 0.62, 0.35, 0.58, 0.48]
O9 = [1.7, 1.9, 2.1, 2.3, 2.6, 1.65, 3.0, 1.8, 2.15]
SEL = [cp.Selection(str(i), p, o) for i, (p, o) in enumerate(zip(P9, O9, strict=True))]
PARTS = cp.partitions()


def sel_from(ps, os_):
    return [cp.Selection(str(i), p, o) for i, (p, o) in enumerate(zip(ps, os_, strict=True))]


# ------------------------------------------------------------ 1-3 partitions
def test_exactly_280_unique_partitions():
    assert len(PARTS) == 280 == math.factorial(9) // (math.factorial(3) ** 3 * math.factorial(3))
    assert len({cp.canonical(p) for p in PARTS}) == 280
    assert len({cp.partition_id(p) for p in PARTS}) == 280
    assert len(list(itertools.combinations(range(9), 3))) == 84  # not the 84 triples


def test_every_partition_uses_each_selection_once():
    for part in PARTS:
        flat = [i for g in part for i in g]
        assert sorted(flat) == list(range(9)) and all(len(g) == 3 for g in part)
        assert part == cp.canonical(part)  # canonical form: sorted groups, ordered by min


def test_partition_order_and_ids_deterministic():
    assert cp.partitions() == PARTS
    assert cp.partition_id(PARTS[0]) == "012|345|678"
    assert cp.partition_id(PARTS[-1]) == "078|156|234"
    assert [cp.partition_id(p) for p in PARTS] == sorted(cp.partition_id(p) for p in PARTS)


# ------------------------------------------------------- 4-8 eight states
@pytest.mark.parametrize("part", [PARTS[0], PARTS[137], PARTS[-1]])
def test_state_probabilities_sum_to_one_and_nine_fold_dependency(part):
    b = cp.bucket_inputs(SEL, part)
    pr = cp.state_probs(b.P)
    assert len(pr) == 8 and pr.sum() == pytest.approx(1, abs=1e-15) and (pr >= 0).all()
    assert pr[-1] == pytest.approx(b.P9) == pytest.approx(math.prod(P9))  # all nine win
    R = cp.state_returns(np.array([6.0, 6, 6]), b.O, b.O9)
    no9 = cp.state_returns(np.array([6.0, 6, 6]), b.O, b.O9, include_nine=False)
    diff = R - no9
    assert diff[-1] == pytest.approx(2 * b.O9)  # nine-fold pays only in (1,1,1)
    assert np.allclose(diff[:-1], 0)
    assert R[0] == 0  # nothing wins -> nothing returned


def test_expected_return_identity_and_ranges():
    for part in PARTS[::7]:
        b = cp.bucket_inputs(SEL, part)
        for stakes in ([6, 6, 6], [2, 2, 14], [7.3, 5.2, 5.5]):
            m = cp.metrics(stakes, b)
            assert m["expected"] == pytest.approx(cp.expected_identity(stakes, b), rel=1e-12)
            assert m["sd"] >= 0 and 0 <= m["p_recover"] <= 1
            assert m["p_any"] == pytest.approx(1 - np.prod(1 - b.P))
            assert m["p_profit"] <= m["p_recover"] <= m["p_any"] + 1e-15
            assert m["p_loss"] == pytest.approx(np.prod(1 - b.P))


def test_hand_calculated_fair_coin_example():
    """p = 0.5, odds 2.00 everywhere: P_j = 1/8, O_j = 8, R_j = 48 at 6 credits,
    R_9 = 2 x 512 = 1024 with P_9 = 1/512. E[R] = 3 x 6 + 2 = 20 exactly;
    P(recover) = P(any bucket) = 1 - (7/8)^3 = 169/512."""
    ex = cp.exact_metrics([F(1, 2)] * 9, [F(2)] * 9, PARTS[0], [6, 6, 6])
    assert ex["expected"] == 20
    assert ex["p_recover"] == ex["p_any"] == F(169, 512)
    assert sum(pr for _, pr, _ in ex["dist"]) == 1
    assert max(r for _, _, r in ex["dist"]) == 3 * 48 + 1024
    m = cp.metrics([6, 6, 6], cp.bucket_inputs(sel_from([0.5] * 9, [2.0] * 9), PARTS[0]))
    assert m["expected"] == pytest.approx(20) and m["p_recover"] == pytest.approx(169 / 512)
    assert m["sd"] ** 2 == pytest.approx(float(ex["variance"]))


def test_hand_calculated_low_odds_two_buckets_needed():
    """p = 0.8, odds 1.20: R_j = 6 x 1.728 = 10.368 < 20 (one bucket insufficient),
    two buckets 20.736 >= 20. P(recover) = P(>= 2 of 3 buckets) with P_j = 0.512."""
    ex = cp.exact_metrics([F(4, 5)] * 9, [F(6, 5)] * 9, PARTS[0], [6, 6, 6])
    pj = F(64, 125)
    assert ex["p_recover"] == 3 * pj**2 * (1 - pj) + pj**3
    m = cp.metrics([6, 6, 6], cp.bucket_inputs(sel_from([0.8] * 9, [1.2] * 9), PARTS[0]))
    assert m["p_recover"] == pytest.approx(float(ex["p_recover"]))
    assert m["min_bucket_payout"] == pytest.approx(10.368) and not m["one_bucket_recovers"]


@pytest.mark.parametrize("seed", range(5))
def test_float_engine_matches_exact_rationals(seed):
    rnd = random.Random(seed)
    ps = [F(rnd.randint(10, 90), 100) for _ in range(9)]
    os_ = [F(rnd.randint(105, 600), 100) for _ in range(9)]
    part = PARTS[rnd.randrange(280)]
    stakes = [F(rnd.randint(20, 120), 10) for _ in range(2)]
    stakes.append(18 - sum(stakes))
    if stakes[2] < 2:
        stakes = [F(6)] * 3
    ex = cp.exact_metrics(ps, os_, part, stakes)
    m = cp.metrics([float(s) for s in stakes], cp.bucket_inputs(sel_from(
        [float(p) for p in ps], [float(o) for o in os_]), part))  # fmt: skip
    assert m["expected"] == pytest.approx(float(ex["expected"]), rel=1e-12)
    assert m["sd"] ** 2 == pytest.approx(float(ex["variance"]), rel=1e-9)
    assert m["p_recover"] == pytest.approx(float(ex["p_recover"]), abs=1e-12)


# --------------------------------------------- 9-14 allocations, strategies
@pytest.mark.parametrize("step,count", [("0.1", 7381), ("0.5", 325), ("1.0", 91)])
def test_allocation_grids_exact_totals_minimums_and_increments(step, count):
    t = cp.allocations(cp.INCREMENTS[step])
    assert len(t) == count == math.comb((180 - 60) // cp.INCREMENTS[step] + 2, 2)
    assert (t.sum(axis=1) == 180).all()  # 18 credits for buckets, + 2 nine-fold = 20
    assert (t >= 20).all() and (t % cp.INCREMENTS[step] == 0).all()
    assert len({tuple(r) for r in t}) == count
    assert cp.to_credits(t).sum(axis=1) + cp.NINE_STAKE == pytest.approx(20.0, abs=1e-9)


def test_equal_stakes_is_6_6_6_2():
    assert (cp.EQUAL_STAKES_TICKS == 60).all() and cp.EQUAL_STAKES_TICKS.sum() + 20 == 200
    rows = ce.analyse_slate(SEL[:9], steps=("1.0",), continuous=False)
    assert all(r["equal_stakes"]["bucket_payouts"] == pytest.approx(
        [6 * o for o in r["O"]]) for r in rows)  # fmt: skip


def test_equal_payout_formula_when_feasible():
    O = np.array([6.783, 9.867, 11.61])
    s, feas = cp.equal_payout_continuous(O)
    q = 18 / np.sum(1 / O)
    assert feas and s == pytest.approx(q / O) and s.sum() == pytest.approx(18)
    assert np.ptp(s * O) == pytest.approx(0, abs=1e-12) and (s >= 2).all()


def test_equal_payout_infeasible_water_filling_is_minimax_and_feasible():
    from scipy.optimize import linprog

    for O in (np.array([1.4, 2.0, 40.0]), np.array([1.2, 30.0, 45.0]), np.array([1.5, 1.6, 9.5])):
        s, feas = cp.equal_payout_continuous(O)
        assert not feas
        assert s.sum() == pytest.approx(18) and (s >= 2 - 1e-12).all()  # never just clipped
        # LP: min t - u  s.t. u <= s_j O_j <= t, sum s = 18, s >= 2
        c = [0, 0, 0, 1, -1]
        A = [[O[0], 0, 0, -1, 0], [0, O[1], 0, -1, 0], [0, 0, O[2], -1, 0],
             [-O[0], 0, 0, 0, 1], [0, -O[1], 0, 0, 1], [0, 0, -O[2], 0, 1]]  # fmt: skip
        res = linprog(c, A_ub=A, b_ub=[0] * 6, A_eq=[[1, 1, 1, 0, 0]], b_eq=[18],
                      bounds=[(2, None)] * 3 + [(None, None)] * 2, method="highs")  # fmt: skip
        assert np.ptp(s * O) == pytest.approx(res.fun, abs=1e-7)


def test_discrete_equal_payout_and_recovery_respect_grid():
    b = cp.bucket_inputs(SEL, PARTS[42])
    for step, k in cp.INCREMENTS.items():
        t = cp.allocations(k)
        for idx in (cp.best_equal_payout(b, t), cp.best_equal_payout(b, t, "squares"),
                    cp.best_recovery(b, t)):  # fmt: skip
            row = t[idx]
            assert row.sum() == 180 and (row >= 20).all() and (row % k == 0).all(), step


# ----------------------------------------------------- 15 global maximum
@pytest.mark.parametrize("seed", range(8))
def test_recovery_optimisation_is_global_on_enumerable_grids(seed):
    rnd = random.Random(100 + seed)
    sel = sel_from([rnd.uniform(0.6, 0.9) for _ in range(9)],
                   [round(rnd.uniform(1.05, 1.6), 2) for _ in range(9)])  # fmt: skip
    part = PARTS[rnd.randrange(280)]
    b = cp.bucket_inputs(sel, part)
    t = cp.allocations(10)
    # brute force with exact rationals over all 91 whole-credit allocations
    best = max(
        cp.exact_metrics(
            [F(s.p) for s in sel], [F(str(s.odds)) for s in sel], part, [F(int(x), 10) for x in row]
        )["p_recover"]  # fmt: skip
        for row in t
    )
    i = cp.best_recovery(b, t)
    assert cp.metrics(cp.to_credits(t[i]), b)["p_recover"] == pytest.approx(float(best), abs=1e-12)
    # the continuous optimum is never below any grid optimum
    rc = cp.recovery_continuous(b)
    assert rc["p_recover"] >= float(best) - 1e-12
    assert rc["stakes"].sum() == pytest.approx(18) and (rc["stakes"] >= 2 - 1e-7).all()
    m = cp.metrics(rc["stakes"], b)
    assert m["p_recover"] == pytest.approx(rc["p_recover"], abs=1e-9)  # achieved, not just claimed


# ------------------------------------------------------- 16-18 frontiers
def test_pareto_dominance_basic_and_ties():
    x = [0.5, 0.4, 0.5, 0.3, 0.5, 0.6]
    y = [10, 20, 10, 5, 9, 1]
    m = cp.pareto_mask(x, y)
    # (0.5,10) twice: identical coordinates, both efficient; (0.5,9) dominated by (0.5,10)
    assert m.tolist() == [True, True, True, False, False, True]
    # floating-point noise within the grid counts as equal
    m2 = cp.pareto_mask([0.5, 0.5 + 1e-15], [10.0, 10.0 - 1e-9])
    assert m2.tolist() == [True, True]
    # lower-is-better x (mean-variance)
    assert cp.pareto_mask([1, 2, 3], [5, 5, 6], x_high=False).tolist() == [True, False, True]


def test_frontier_invariant_to_enumeration_order():
    rows = [{"equal_stakes": cp.metrics([6, 6, 6], cp.bucket_inputs(SEL, p))} for p in PARTS]
    base = ce.frontier(rows, "equal_stakes", "recovery_vs_min_payout")
    perm = np.random.default_rng(7).permutation(280)
    shuffled = ce.frontier([rows[i] for i in perm], "equal_stakes", "recovery_vs_min_payout")
    assert (shuffled == base[perm]).all()
    assert base.any() and not base.all()


def test_dominated_points_have_a_dominator():
    rows = [{"equal_stakes": cp.metrics([6, 6, 6], cp.bucket_inputs(SEL, p))} for p in PARTS]
    m = ce.frontier(rows, "equal_stakes", "recovery_vs_min_payout")
    x = np.array([r["equal_stakes"]["p_recover"] for r in rows])
    y = np.array([r["equal_stakes"]["min_bucket_payout"] for r in rows])
    for i in np.flatnonzero(~m):
        assert (
            (x >= x[i] - 1e-12) & (y >= y[i] - 1e-6) & ((x > x[i] + 1e-12) | (y > y[i] + 1e-6))
        ).any()
    for i in np.flatnonzero(m):
        assert not ((x > x[i] + 1e-12) & (y >= y[i] - 1e-6)).any()


# ------------------------------------------------- 19-20 symmetry, extremes
def test_identical_selections_collapse_to_one_point():
    sel = sel_from([0.5] * 9, [2.0] * 9)
    rows = ce.analyse_slate(sel, steps=("1.0",), continuous=False)
    for key in ("equal_stakes", "equal_payout_1.0", "recovery_1.0"):
        assert ce.distinct_coords(rows, key, "recovery_vs_min_payout") == 1
        assert ce.frontier(rows, key, "recovery_vs_min_payout").all()  # all tie: all efficient


@pytest.mark.parametrize("p,o", [(0.999, 1.01), (0.001, 500.0), (0.5, 1.01), (1e-6, 1000.0)])
def test_extreme_probabilities_and_odds_are_safe(p, o):
    b = cp.bucket_inputs(sel_from([p] * 9, [o] * 9), PARTS[0])
    m = cp.metrics([6, 6, 6], b)
    assert all(np.isfinite(v) for v in (m["expected"], m["sd"], m["p_recover"]))
    assert 0 <= m["p_recover"] <= 1 and m["sd"] >= 0
    s, _ = cp.equal_payout_continuous(b.O)
    assert s.sum() == pytest.approx(18) and (s >= 2 - 1e-9).all()
    rc = cp.recovery_continuous(b)
    assert 0 <= rc["p_recover"] <= 1


# ------------------------------------------------------- dependence model
def test_factor_model_preserves_marginals_and_reduces_to_independence():
    groups = [[P9[i] for i in g] for g in PARTS[5]]
    ind = cp.factor_state_probs(groups, 0.0)
    assert ind == pytest.approx(cp.state_probs([math.prod(g) for g in groups]))
    for rho in (0.05, 0.2):
        pr = cp.factor_state_probs(groups, rho)
        assert pr.sum() == pytest.approx(1, abs=1e-10)
        mc = cp.simulate_state_probs(groups, rho, 400_000, seed=11)
        assert pr == pytest.approx(mc, abs=4e-3)  # quadrature vs Monte Carlo
    # a single fixture's marginal is preserved under the factor model
    one = cp.factor_state_probs([[0.37], [0.99999999], [0.99999999]], 0.3)
    assert one[4:].sum() == pytest.approx(0.37, abs=1e-6)


def test_monte_carlo_validates_exact_independence():
    groups = [[P9[i] for i in g] for g in PARTS[0]]
    mc = cp.simulate_state_probs(groups, 0.0, 400_000, seed=3)
    assert mc == pytest.approx(cp.state_probs([math.prod(g) for g in groups]), abs=3e-3)


# ---------------------------------------------- 21-22 data and model safety
def test_real_data_loading_is_read_only(populated):
    from datetime import timedelta

    from diski9.db.schema import forecast_snapshots, odds_quotes, screener_results
    from diski9.research import challenge_data as cd

    from .factories import T0

    def counts():
        with populated.connect() as c:
            return [c.execute(select(func.count()).select_from(t)).scalar()
                    for t in (forecast_snapshots, odds_quotes, screener_results)]  # fmt: skip

    before = counts()
    cands = cd.eligible_candidates(populated, T0, T0, T0 + timedelta(days=30))
    assert counts() == before  # nothing written
    assert all(len(c["markets"]) >= 1 for c in cands)
    for c in cands:  # only Challenge-eligible markets (>= 3 independent groups)
        assert all(m["groups"] >= 3 for m in c["markets"].values())
    slate = cd.build_slate(cands, cd.rule_model_favourite)
    assert len(slate) < 9  # the test database cannot supply nine: reported, not padded


def test_goal_model_unchanged():
    from diski9.screener import goal_model as gm

    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.m0, gm.GOAL_MODEL_VERSION) == (
        12,
        96,
        30,
        "1.0",
    )
