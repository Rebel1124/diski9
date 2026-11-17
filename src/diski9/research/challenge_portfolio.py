# ruff: noqa: E741  (O, O_j and P_j follow the Phase 5B brief's notation)
"""Research only (Phase 5B): Weekly Challenge portfolio mathematics.

Nine selections (one outcome on each of nine distinct fixtures) are grouped into
three disjoint three-fold accumulators ("buckets" A, B, C) plus one nine-fold that
always contains all nine. The weekly allocation is 20 virtual credits: the nine-fold
stake is fixed at 2, so the buckets share 18 with at least 2 each.

Everything here is pure and deterministic - no database, network or plotting - so
it can be tested exhaustively. Nothing is wired into the app.

Conventions
-----------
* **Credits are integer ticks of 0.1** (``TICK``): the buckets share exactly
  ``BUCKET_TICKS = 180`` ticks, each at least ``MIN_TICKS = 20``, so allocation sums
  are exact integers and can never drift. Coarser increments (0.5, 1.0) are
  multiples of the tick.
* **Independence across fixtures** is the primary assumption: a bucket wins with
  ``P_j = prod p_i`` and the nine-fold wins exactly when all three buckets win
  (``I_9 = I_A I_B I_C``), with ``P_9 = P_A P_B P_C``. :func:`factor_state_probs`
  relaxes it with a hypothetical one-factor Gaussian copula that keeps every
  fixture's marginal probability.
* **Exact distribution**: three binary bucket outcomes give 2^3 = 8 states; every
  metric is computed from these eight states, not by simulation.
* **Tolerances** (documented, deterministic): a state "recovers" when
  ``R >= 20 - RECOVER_TOL`` (1e-9 credits); profit needs ``R > 20 + RECOVER_TOL``.
  Pareto comparisons first snap coordinates to a grid (probability 1e-12, credits
  1e-6), so values equal up to floating-point noise are treated as equal.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

TICK = 0.1  # credits per tick
TOTAL_CREDITS = 20
NINE_STAKE = 2.0
BUCKET_TICKS = 180  # 18 credits shared by the three buckets
MIN_TICKS = 20  # each bucket >= 2 credits
TARGET = 20.0  # recover the weekly allocation
RECOVER_TOL = 1e-9
PROB_GRID = 1e-12
CREDIT_GRID = 1e-6
INCREMENTS = {"0.1": 1, "0.5": 5, "1.0": 10}  # credit increment -> ticks
STATES = tuple(itertools.product((0, 1), repeat=3))  # (a, b, c), a = bucket A wins
_STATE_ARR = np.array(STATES, dtype=float)  # (8, 3)
_ALL_WIN = _STATE_ARR.prod(axis=1)  # 1 only for (1, 1, 1)


# --------------------------------------------------------------- partitions
def partitions(n: int = 9) -> list[tuple[tuple[int, int, int], ...]]:
    """All partitions of ``range(n)`` into unordered groups of three, canonical:
    each group sorted, groups ordered by their smallest element, list in
    lexicographic order. For n = 9 there are 9! / ((3!)^3 3!) = 280."""
    if n % 3:
        raise ValueError("n must be a multiple of 3")

    def rec(items: tuple[int, ...]):
        if not items:
            yield ()
            return
        first, rest = items[0], items[1:]
        for pair in itertools.combinations(rest, 2):
            group = (first, *pair)
            remaining = tuple(x for x in rest if x not in pair)
            for tail in rec(remaining):
                yield (group, *tail)

    return list(rec(tuple(range(n))))


def partition_id(part: Sequence[Sequence[int]]) -> str:
    """Stable identifier, e.g. '012|345|678' (selections numbered 0-8)."""
    return "|".join("".join(str(i) for i in g) for g in part)


def canonical(part: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    return tuple(sorted(tuple(sorted(g)) for g in part))


# ------------------------------------------------------------- slate inputs
@dataclass(frozen=True)
class Selection:
    label: str
    p: float  # Goal Model 1.0 probability of the selected outcome
    odds: float  # consensus decimal odds (2 dp) of that outcome
    meta: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Buckets:
    """Bucket win probabilities and combined odds for one partition."""

    P: np.ndarray  # (3,)
    O: np.ndarray  # (3,)
    P9: float
    O9: float


def bucket_inputs(sel: Sequence[Selection], part) -> Buckets:
    P = np.array([math.prod(sel[i].p for i in g) for g in part])
    O = np.array([math.prod(sel[i].odds for i in g) for g in part])
    return Buckets(P, O, float(P.prod()), float(math.prod(s.odds for s in sel)))


# ------------------------------------------------------ eight-state engine
def state_probs(P: Sequence[float]) -> np.ndarray:
    """P(a, b, c) for the eight states, independence across buckets."""
    P = np.asarray(P, dtype=float)
    return np.prod(np.where(_STATE_ARR == 1, P, 1 - P), axis=1)


def state_returns(stakes: np.ndarray, O: np.ndarray, O9: float, include_nine=True) -> np.ndarray:
    """Gross return in each state for one or many allocations.

    ``stakes`` has shape (3,) or (n, 3) in credits; result (8,) or (n, 8).
    R(a,b,c) = a R_A + b R_B + c R_C + abc * 2 * O_9."""
    payouts = np.asarray(stakes, dtype=float) * O  # R_j
    r = payouts @ _STATE_ARR.T
    if include_nine:
        r = r + _ALL_WIN * NINE_STAKE * O9
    return r


def metrics_batch(
    stakes: np.ndarray,
    b: Buckets,
    probs: np.ndarray | None = None,
    include_nine: bool = True,
) -> dict[str, np.ndarray]:
    """All portfolio metrics for allocations ``stakes`` (n, 3) in credits.

    ``probs`` overrides the eight state probabilities (dependence scenarios)."""
    stakes = np.atleast_2d(np.asarray(stakes, dtype=float))
    pr = state_probs(b.P) if probs is None else np.asarray(probs, dtype=float)
    R = state_returns(stakes, b.O, b.O9, include_nine)  # (n, 8)
    mean = R @ pr
    var = np.maximum(((R - mean[:, None]) ** 2) @ pr, 0.0)
    rec = R >= TARGET - RECOVER_TOL
    payouts = stakes * b.O
    return {
        "p_recover": rec.astype(float) @ pr,
        "p_profit": (R > TARGET + RECOVER_TOL).astype(float) @ pr,
        "expected": mean,
        "expected_net": mean - TOTAL_CREDITS,
        "sd": np.sqrt(var),
        "p_loss": np.full(len(stakes), pr[0]),  # (0,0,0): nothing returned
        "p_any": np.full(len(stakes), 1 - pr[0]),
        "max_payout": R[:, -1],
        "min_bucket_payout": payouts.min(axis=1),
        "max_bucket_payout": payouts.max(axis=1),
        "payout_range": payouts.max(axis=1) - payouts.min(axis=1),
        "one_bucket_recovers": payouts.min(axis=1) >= TARGET - RECOVER_TOL,
    }


def metrics(stakes, b: Buckets, probs=None, include_nine=True) -> dict[str, float]:
    """Metrics for a single allocation (plain floats), plus per-bucket detail."""
    m = {k: v[0].item() for k, v in metrics_batch(stakes, b, probs, include_nine).items()}
    s = np.asarray(stakes, dtype=float)
    m["bucket_payouts"] = (s * b.O).tolist()
    m["bucket_probs"] = b.P.tolist()
    m["nine_payout"] = NINE_STAKE * b.O9
    m["nine_prob"] = b.P9
    return m


def expected_identity(stakes, b: Buckets, include_nine=True) -> float:
    """E[R] = sum_j P_j s_j O_j + P_9 (2 O_9): independent check of the 8 states."""
    e = float(np.dot(b.P, np.asarray(stakes, dtype=float) * b.O))
    return e + (b.P9 * NINE_STAKE * b.O9 if include_nine else 0.0)


def exact_metrics(p: Sequence[Fraction], o: Sequence[Fraction], part, stakes) -> dict:
    """Rational (exact) reference implementation for hand-checked examples."""
    P = [math.prod((p[i] for i in g), start=Fraction(1)) for g in part]
    O = [math.prod((o[i] for i in g), start=Fraction(1)) for g in part]
    O9 = math.prod(o, start=Fraction(1))
    s = [Fraction(x) for x in stakes]
    dist = []
    for st in STATES:
        pr = math.prod((P[j] if st[j] else 1 - P[j] for j in range(3)), start=Fraction(1))
        r = sum((s[j] * O[j] for j in range(3) if st[j]), start=Fraction(0))
        if all(st):
            r += 2 * O9
        dist.append((st, pr, r))
    mean = sum(pr * r for _, pr, r in dist)
    var = sum(pr * (r - mean) ** 2 for _, pr, r in dist)
    return {
        "dist": dist,
        "expected": mean,
        "variance": var,
        "p_recover": sum(pr for _, pr, r in dist if r >= 20),
        "p_any": 1 - math.prod((1 - x for x in P), start=Fraction(1)),
    }


# ------------------------------------------------------------- allocations
def allocations(step_ticks: int) -> np.ndarray:
    """Every feasible bucket allocation (n, 3) in ticks for an increment of
    ``step_ticks`` ticks: multiples of the step, each >= 20 ticks, sum 180."""
    if MIN_TICKS % step_ticks or BUCKET_TICKS % step_ticks:
        raise ValueError("increment must divide 2 and 18 credits")
    vals = range(MIN_TICKS, BUCKET_TICKS - 2 * MIN_TICKS + 1, step_ticks)
    out = [(a, b_, BUCKET_TICKS - a - b_) for a in vals for b_ in vals
           if BUCKET_TICKS - a - b_ >= MIN_TICKS]  # fmt: skip
    return np.array(out, dtype=np.int64)


def to_credits(ticks: np.ndarray) -> np.ndarray:
    return np.asarray(ticks, dtype=float) * TICK


EQUAL_STAKES_TICKS = np.array([60, 60, 60])


def equal_payout_continuous(O: np.ndarray) -> tuple[np.ndarray, bool]:
    """Equal-payout stakes (credits) and whether the unconstrained solution is
    feasible. Infeasible cases use the minimax-range solution: buckets whose
    equal-payout stake would fall below 2 are held at 2 (their payout is then
    above the common level) and the remaining credits equalise the others
    ("water-filling"); this minimises max_j R_j - min_j R_j exactly."""
    O = np.asarray(O, dtype=float)
    q = 18.0 / np.sum(1 / O)
    s = q / O
    if s.min() >= 2 - 1e-12:
        return s, True
    fixed = np.zeros(3, dtype=bool)
    while True:
        free = ~fixed
        budget = 18.0 - 2.0 * fixed.sum()
        q = budget / np.sum(1 / O[free])
        s = np.where(fixed, 2.0, q / O)
        low = free & (s < 2 - 1e-12)
        if not low.any():
            return s, False
        fixed |= low


def _lexkey(ticks: np.ndarray) -> np.ndarray:
    return ticks[:, 0] * 10**6 + ticks[:, 1] * 10**3 + ticks[:, 2]


def choose(order_keys: list[np.ndarray]) -> int:
    """Index of the row minimising ``order_keys`` lexicographically (np.lexsort
    takes the last key as primary, so the list is reversed)."""
    return int(np.lexsort(tuple(reversed(order_keys)))[0])


def _snap(x: np.ndarray, grid: float) -> np.ndarray:
    return np.round(np.asarray(x, dtype=float) / grid).astype(np.int64)


def best_equal_payout(b: Buckets, ticks: np.ndarray, objective: str = "range") -> int:
    """Index into ``ticks`` (an :func:`allocations` grid) of the most balanced
    allocation. ``range``: minimise max-min payout, then squared deviation;
    ``squares``: minimise squared deviation, then range. Remaining ties: higher
    E[R], then lexicographically smallest (A, B, C) stakes."""
    pay = to_credits(ticks) * b.O
    rng = _snap(pay.max(1) - pay.min(1), CREDIT_GRID)
    sq = _snap(((pay - pay.mean(1, keepdims=True)) ** 2).sum(1), CREDIT_GRID)
    er = _snap(to_credits(ticks) @ (b.P * b.O), CREDIT_GRID)
    first, second = (rng, sq) if objective == "range" else (sq, rng)
    return choose([first, second, -er, _lexkey(ticks)])


def best_recovery(b: Buckets, ticks: np.ndarray, m: dict | None = None) -> int:
    """Index of the allocation with the highest recovery probability. Sequential
    tie-breaks: higher E[R], lower SD, smaller payout range, lexicographic stakes."""
    m = m or metrics_batch(to_credits(ticks), b)
    return choose(
        [
            -_snap(m["p_recover"], PROB_GRID),
            -_snap(m["expected"], CREDIT_GRID),
            _snap(m["sd"], CREDIT_GRID),
            _snap(m["payout_range"], CREDIT_GRID),
            _lexkey(ticks),
        ]
    )


def recovery_continuous(b: Buckets, include_nine: bool = True) -> dict:
    """Exact continuous maximum of P(R >= 20).

    P(R >= 20) only depends on *which* states reach 20. The recovering states form
    an up-set (a state with more winning buckets pays at least as much), and for a
    given up-set the stakes achieving it form a convex polygon (linear constraints
    R(s) >= 20 on the allocation simplex). Every up-set is enumerated, its
    feasibility decided by a linear programme, and the most probable feasible
    up-set wins. Among stakes achieving it, the one with the highest E[R] is
    reported (an LP; further tie-breaks are not applied in the continuous case).
    """
    from scipy.optimize import linprog

    pr = state_probs(b.P)
    nine = NINE_STAKE * b.O9 if include_nine else 0.0
    nonzero = [i for i, s in enumerate(STATES) if any(s)]
    best = None
    for mask in range(1 << len(nonzero)):
        chosen = {nonzero[k] for k in range(len(nonzero)) if mask >> k & 1}
        if not all(
            j in chosen
            for i in chosen
            for j in nonzero
            if all(STATES[j][t] >= STATES[i][t] for t in range(3))
        ):
            continue  # not an up-set
        prob = float(sum(pr[i] for i in chosen))
        if best is not None and prob < best[0] - PROB_GRID:
            continue
        # variables s_A, s_B, s_C; constraints -R(s) <= -20 + nine*abc
        A_ub, b_ub = [], []
        for i in chosen:
            st = np.array(STATES[i], dtype=float)
            A_ub.append(-(st * b.O))
            b_ub.append(-TARGET + (nine if all(STATES[i]) else 0.0))
        res = linprog(
            c=-(b.P * b.O),
            A_ub=np.array(A_ub) if A_ub else None,
            b_ub=np.array(b_ub) if b_ub else None,
            A_eq=np.ones((1, 3)),
            b_eq=[18.0],
            bounds=[(2.0, None)] * 3,
            method="highs",
        )
        if res.status != 0:
            continue
        cand = (prob, float(-res.fun), res.x, sorted(chosen))
        if (
            best is None
            or prob > best[0] + PROB_GRID
            or (abs(prob - best[0]) <= PROB_GRID and cand[1] > best[1] + CREDIT_GRID)
        ):
            best = cand
    prob, er, x, states = best
    return {"p_recover": prob, "stakes": x, "recovering_states": [STATES[i] for i in states]}


# ---------------------------------------------------------------- frontiers
def pareto_mask(x: Sequence[float], y: Sequence[float], x_high=True, y_high=True,
                x_grid=PROB_GRID, y_grid=CREDIT_GRID) -> np.ndarray:  # fmt: skip
    """True where a point is Pareto-efficient (no other point at least as good on
    both axes and strictly better on one). Coordinates are snapped to grids first;
    points with identical snapped coordinates never dominate each other, so a
    shared efficient coordinate keeps all its points. Order-independent."""
    xs = _snap(x, x_grid) * (1 if x_high else -1)
    ys = _snap(y, y_grid) * (1 if y_high else -1)
    ge = (xs[None, :] >= xs[:, None]) & (ys[None, :] >= ys[:, None])
    gt = (xs[None, :] > xs[:, None]) | (ys[None, :] > ys[:, None])
    return ~(ge & gt).any(axis=1)


# --------------------------------------------------- dependence sensitivity
def factor_state_probs(
    p_groups: Sequence[Sequence[float]], rho: float, nodes: int = 96
) -> np.ndarray:
    """Eight bucket-state probabilities under a *hypothetical* one-factor Gaussian
    copula: fixture i wins when sqrt(rho) F + sqrt(1 - rho) e_i < Phi^-1(p_i), with
    a common factor F and independent e_i, all standard normal. Each fixture keeps
    its marginal probability p_i; rho = 0 is independence. Integrated over F with
    Gauss-Hermite quadrature (exact up to quadrature error)."""
    from scipy.special import ndtr, ndtri

    if rho <= 0:
        return state_probs([math.prod(g) for g in p_groups])
    z, w = np.polynomial.hermite_e.hermegauss(nodes)
    w = w / w.sum()
    out = np.zeros(8)
    for f, wt in zip(z, w, strict=True):
        P = [
            math.prod(float(ndtr((ndtri(p) - math.sqrt(rho) * f) / math.sqrt(1 - rho))) for p in g)
            for g in p_groups
        ]
        out += wt * state_probs(P)
    return out


def simulate_state_probs(p_groups, rho: float, n: int, seed: int) -> np.ndarray:
    """Monte Carlo estimate of the eight state probabilities (validation only)."""
    from scipy.special import ndtri

    rng = np.random.default_rng(seed)
    thr = np.array([[ndtri(p) for p in g] for g in p_groups])  # (3, 3)
    f = rng.standard_normal((n, 1, 1))
    e = rng.standard_normal((n, 3, 3))
    win = (math.sqrt(rho) * f + math.sqrt(1 - rho) * e) < thr
    bucket = win.all(axis=2).astype(int)  # (n, 3)
    idx = bucket[:, 0] * 4 + bucket[:, 1] * 2 + bucket[:, 2]
    return np.bincount(idx, minlength=8) / n
