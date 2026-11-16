"""Research only (Milestone 5.2): Poisson and Dixon-Coles goal models.

Not used by the Screener, its cache or the Challenge. Outputs are *market-implied
goal expectations* (when fitted to odds) or *historical goal-rate estimates*
(when built from results) - never shot-based xG.

Score distribution
    P(h, a) = tau(h, a) * Pois(h; lambda_H) * Pois(a; lambda_A)
    tau = 1 everywhere for the independent Poisson model. Dixon-Coles (1997):
        tau(0,0) = 1 - lambda_H lambda_A rho     tau(0,1) = 1 + lambda_H rho
        tau(1,0) = 1 + lambda_A rho              tau(1,1) = 1 - rho
    The adjustment moves probability between the four low scores only and its
    net effect on total mass is exactly zero:
        -lH lA rho + lH lA rho (from 0-1) + lH lA rho (1-0) - lH lA rho (1-1) = 0
    (each term multiplied by e^-(lH+lA)). Validity requires every tau >= 0:
        max(-1/lH, -1/lA) <= rho <= min(1/(lH lA), 1)
    Negative rho raises 0-0 and 1-1 (more draws) and lowers 1-0 and 0-1.
    The grid is truncated where both Poisson tails are below 1e-12 and then
    renormalised; the omitted mass is reported.

Market inversion
    Fit parameters theta (lambda_H, lambda_A[, rho]) to margin-adjusted market
    probabilities. Objectives (each market enters once, equal weight, so the
    three-outcome 1X2 market does not dominate because it has more outcomes):
        kl : sum_m KL(p_m || q_m(theta))
        sq : sum_m mean_k (p_mk - q_mk(theta))^2
    Bounded L-BFGS-B from a fixed grid of starts (deterministic).
    Independent constraints: 1X2 = 2, BTTS = 1, O/U 2.5 = 1. A fit is only
    attempted when constraints >= parameters; identification is then checked
    with the singular values of the constraint Jacobian.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

LAMBDA_BOUNDS = (0.05, 6.0)
RHO_BOUNDS = (-0.3, 0.3)
TAIL = 1e-12
MARKETS = ("1x2", "btts", "ou25")
CONSTRAINTS = {"1x2": 2, "btts": 1, "ou25": 1}
GOOD_FIT = 0.02
APPROX_FIT = 0.04
# relative conditioning: smallest / largest singular value of the Jacobian
IDENTIFICATION_RATIO = 1e-3
STARTS_2 = ((1.0, 1.0), (1.6, 1.0), (1.0, 1.6), (2.4, 0.7), (0.7, 2.4), (0.6, 0.6), (3.0, 1.5))


# ------------------------------------------------------------------ model
def _grid_size(lam: float) -> int:
    """Smallest K with P(X > K) < TAIL for X ~ Poisson(lam)."""
    p = math.exp(-lam)
    cum, k = p, 0
    while 1 - cum > TAIL and k < 60:
        k += 1
        p *= lam / k
        cum += p
    return k + 1


def rho_limits(lam_h: float, lam_a: float) -> tuple[float, float]:
    """Interval of rho for which every tau is non-negative."""
    lo = max(-1 / lam_h, -1 / lam_a)
    hi = min(1 / (lam_h * lam_a), 1.0)
    return lo, hi


def tau(h: int, a: int, lam_h: float, lam_a: float, rho: float) -> float:
    if h == 0 and a == 0:
        return 1 - lam_h * lam_a * rho
    if h == 0 and a == 1:
        return 1 + lam_h * rho
    if h == 1 and a == 0:
        return 1 + lam_a * rho
    if h == 1 and a == 1:
        return 1 - rho
    return 1.0


def score_matrix(lam_h: float, lam_a: float, rho: float = 0.0) -> tuple[np.ndarray, float]:
    """Scoreline probabilities (rows = home goals) and the omitted tail mass."""
    if not (lam_h > 0 and lam_a > 0) or not all(map(math.isfinite, (lam_h, lam_a, rho))):
        raise ValueError("goal expectations must be positive and finite")
    lo, hi = rho_limits(lam_h, lam_a)
    if not lo - 1e-12 <= rho <= hi + 1e-12:
        raise ValueError(f"rho={rho:.4f} outside the valid range [{lo:.4f}, {hi:.4f}]")
    n = max(_grid_size(lam_h), _grid_size(lam_a))
    k = np.arange(n)
    lgam = np.array([math.lgamma(i + 1) for i in range(n)])
    ph = np.exp(k * math.log(lam_h) - lam_h - lgam)
    pa = np.exp(k * math.log(lam_a) - lam_a - lgam)
    M = np.outer(ph, pa)
    if rho:
        M[0, 0] *= 1 - lam_h * lam_a * rho
        M[0, 1] *= 1 + lam_h * rho
        M[1, 0] *= 1 + lam_a * rho
        M[1, 1] *= 1 - rho
    M = np.clip(M, 0, None)  # guards -1e-17 rounding at the validity boundary
    mass = float(M.sum())
    return M / mass, max(0.0, 1 - mass)


def market_probabilities(M: np.ndarray) -> dict[str, tuple[float, ...]]:
    home = float(np.tril(M, -1).sum())
    draw = float(np.trace(M))
    away = float(np.triu(M, 1).sum())
    btts_no = float(M[0, :].sum() + M[:, 0].sum() - M[0, 0])
    h, a = np.indices(M.shape)
    under = float(M[(h + a) <= 2].sum())
    return {"1x2": (home, draw, away), "btts": (1 - btts_no, btts_no), "ou25": (1 - under, under)}


def probabilities(lam_h: float, lam_a: float, rho: float = 0.0) -> dict[str, Any]:
    M, omitted = score_matrix(lam_h, lam_a, rho)
    out: dict[str, Any] = market_probabilities(M)
    h, a = np.indices(M.shape)
    out["total_goals"] = np.bincount((h + a).ravel(), weights=M.ravel())
    out["expected_home"] = float((h * M).sum())
    out["expected_away"] = float((a * M).sum())
    out["omitted_mass"] = omitted
    return out


# ----------------------------------------------------------------- fitting
@dataclass(frozen=True)
class Spec:
    """poisson | dc_fixed (rho given) | dc_free (rho estimated)."""

    model: str = "poisson"
    rho: float = 0.0
    objective: str = "kl"

    @property
    def n_params(self) -> int:
        return 3 if self.model == "dc_free" else 2

    @property
    def label(self) -> str:
        if self.model == "dc_fixed":
            return f"dc_fixed(rho={self.rho:+.3f})/{self.objective}"
        return f"{self.model}/{self.objective}"


@dataclass
class Fit:
    # good_fit | approximate_fit | poor_fit | unidentified | insufficient_market_data
    # | invalid_input | optimization_failure
    status: str
    spec: Spec
    markets: tuple[str, ...]
    lambda_home: float | None = None
    lambda_away: float | None = None
    rho: float | None = None
    market: dict[str, tuple[float, ...]] = field(default_factory=dict)
    model: dict[str, tuple[float, ...]] = field(default_factory=dict)
    abs_errors: dict[str, tuple[float, ...]] = field(default_factory=dict)
    max_abs_error: float | None = None
    mean_abs_error: float | None = None
    objective_value: float | None = None
    converged: bool | None = None
    at_bound: bool | None = None
    singular_values: tuple[float, ...] | None = None
    start_spread: float | None = None  # max |theta difference| among near-optimal starts
    message: str = ""

    @property
    def lambda_total(self) -> float | None:
        if self.lambda_home is None or self.lambda_away is None:
            return None
        return self.lambda_home + self.lambda_away

    @property
    def usable(self) -> bool:
        """Confident enough to report goal expectations."""
        return self.status in ("good_fit", "approximate_fit")


def validate(market: dict[str, tuple[float, ...]]) -> list[str]:
    problems = []
    for m, v in market.items():
        if m not in MARKETS:
            problems.append(f"unknown market {m}")
        elif len(v) != (3 if m == "1x2" else 2):
            problems.append(f"{m}: incomplete outcome set")
        elif any((not math.isfinite(x)) or x <= 0 or x >= 1 for x in v):
            problems.append(f"{m}: probabilities must be strictly between 0 and 1")
        elif abs(sum(v) - 1) > 1e-6:
            problems.append(f"{m}: probabilities sum to {sum(v):.6f} (margin not removed?)")
    return problems


def _theta(spec: Spec, x) -> tuple[float, float, float]:
    return float(x[0]), float(x[1]), float(x[2]) if spec.model == "dc_free" else spec.rho


def _loss(market, spec: Spec, x) -> float:
    lh, la, rho = _theta(spec, x)
    lo, hi = rho_limits(lh, la)
    penalty = 0.0
    if rho < lo or rho > hi:  # keep the optimiser inside the valid region
        penalty = 1e3 * (max(lo - rho, rho - hi)) ** 2
        rho = min(max(rho, lo), hi)
    q = market_probabilities(score_matrix(lh, la, rho)[0])
    total = 0.0
    for m, p in market.items():
        qm = q[m]
        if spec.objective == "kl":
            total += sum(pi * math.log(pi / max(qi, 1e-15)) for pi, qi in zip(p, qm, strict=True))
        else:
            total += sum((pi - qi) ** 2 for pi, qi in zip(p, qm, strict=True)) / len(p)
    return total + penalty


def _constraints(theta, markets) -> np.ndarray:
    lh, la, rho = theta
    q = market_probabilities(score_matrix(lh, la, rho)[0])
    out = []
    if "1x2" in markets:
        out += [q["1x2"][0], q["1x2"][2]]
    if "btts" in markets:
        out.append(q["btts"][0])
    if "ou25" in markets:
        out.append(q["ou25"][0])
    return np.array(out)


def jacobian_singular_values(theta, markets, spec: Spec, h: float = 1e-5) -> tuple[float, ...]:
    base = np.array(theta, dtype=float)
    free = [0, 1, 2] if spec.model == "dc_free" else [0, 1]
    f0 = _constraints(base, markets)
    cols = []
    for i in free:
        t = base.copy()
        t[i] += h
        cols.append((_constraints(t, markets) - f0) / h)
    return tuple(float(s) for s in np.linalg.svd(np.column_stack(cols), compute_uv=False))


def fit_market(market: dict[str, tuple[float, ...]], spec: Spec = Spec()) -> Fit:
    """Fit the model to ``market`` = {market: margin-adjusted probabilities}."""
    from scipy.optimize import minimize

    markets = tuple(m for m in MARKETS if m in market)
    problems = validate(market)
    if problems:
        return Fit("invalid_input", spec, markets, message="; ".join(problems))
    n_constraints = sum(CONSTRAINTS[m] for m in markets)
    if n_constraints < spec.n_params:
        return Fit(
            "insufficient_market_data",
            spec,
            markets,
            message=f"{n_constraints} independent constraint(s) for {spec.n_params} parameters",
        )
    if spec.model == "dc_fixed":
        lo, hi = RHO_BOUNDS
        if not lo <= spec.rho <= hi:
            return Fit("invalid_input", spec, markets, message="fixed rho outside bounds")
    bounds = [LAMBDA_BOUNDS, LAMBDA_BOUNDS] + ([RHO_BOUNDS] if spec.model == "dc_free" else [])
    starts = (
        [(*s, r) for s in STARTS_2 for r in (-0.1, 0.0, 0.1)]
        if spec.model == "dc_free"
        else list(STARTS_2)
    )
    results = []
    for s in starts:
        try:
            r = minimize(
                lambda x: _loss(market, spec, x),
                np.array(s, dtype=float),
                method="L-BFGS-B",
                bounds=bounds,
                options={"ftol": 1e-15, "gtol": 1e-11, "maxiter": 1000},
            )
        except (ValueError, FloatingPointError):
            continue
        if np.all(np.isfinite(r.x)) and math.isfinite(r.fun):
            results.append(r)
    if not results:
        return Fit("optimization_failure", spec, markets, message="no start produced a finite fit")
    best = min(results, key=lambda r: r.fun)
    near = [r for r in results if r.fun - best.fun < 1e-9 + 1e-6 * abs(best.fun)]
    spread = max(float(np.max(np.abs(r.x - best.x))) for r in near)
    lh, la, rho = _theta(spec, best.x)
    lo, hi = rho_limits(lh, la)
    rho = min(max(rho, lo), hi)
    q = market_probabilities(score_matrix(lh, la, rho)[0])
    errs = {m: tuple(abs(a - b) for a, b in zip(q[m], market[m], strict=True)) for m in markets}
    flat = [e for v in errs.values() for e in v]
    at_bound = any(abs(v - b) < 1e-3 for v, bd in zip(best.x, bounds, strict=True) for b in bd)
    sv = jacobian_singular_values((lh, la, rho), markets, spec)
    fit = Fit(
        "",
        spec,
        markets,
        lh,
        la,
        rho,
        dict(market),
        q,
        errs,
        max(flat),
        sum(flat) / len(flat),
        float(best.fun),
        bool(best.success),
        at_bound,
        sv,
        spread,
    )
    if len(sv) < spec.n_params or sv[-1] < IDENTIFICATION_RATIO * sv[0] or spread > 0.05:
        fit.status = "unidentified"
        fit.message = (
            "parameters not identified: different parameter values fit equally well "
            f"(smallest/largest singular value {sv[-1] / sv[0]:.1e}, start spread {spread:.3f})"
        )
    elif at_bound:
        fit.status, fit.message = "poor_fit", "a parameter reached its bound"
    elif not best.success and fit.max_abs_error > APPROX_FIT:
        fit.status, fit.message = "optimization_failure", str(best.message)
    elif fit.max_abs_error <= GOOD_FIT:
        fit.status = "good_fit"
    elif fit.max_abs_error <= APPROX_FIT:
        fit.status = "approximate_fit"
    else:
        fit.status, fit.message = "poor_fit", "market prices not jointly consistent with the model"
    if n_constraints == spec.n_params and fit.usable:
        fit.message = "exactly identified: no spare constraint to check the model"
    return fit


def pooled_rho(
    markets: list[dict[str, tuple[float, ...]]],
    grid: np.ndarray | None = None,
    objective: str = "kl",
) -> dict[str, Any]:
    """One shared rho for many fixtures (each with its own lambdas): profile the summed
    objective over a rho grid, then refine. Returns rho and the profile."""
    grid = np.round(np.arange(-0.25, 0.2501, 0.025), 4) if grid is None else grid
    profile = []
    for r in grid:
        fits = [fit_market(m, Spec("dc_fixed", float(r), objective)) for m in markets]
        profile.append((float(r), sum(f.objective_value or 0 for f in fits)))
    best = min(profile, key=lambda t: t[1])[0]
    fine = np.round(np.arange(best - 0.025, best + 0.02501, 0.005), 4)
    fine = fine[(fine >= RHO_BOUNDS[0]) & (fine <= RHO_BOUNDS[1])]
    fine_profile = []
    for r in fine:
        fits = [fit_market(m, Spec("dc_fixed", float(r), objective)) for m in markets]
        fine_profile.append((float(r), sum(f.objective_value or 0 for f in fits)))
    rho = min(fine_profile, key=lambda t: t[1])[0]
    return {"rho": rho, "profile": profile, "fine_profile": fine_profile}


def perturb_price(prices: tuple[float, ...], index: int, rel: float) -> tuple[float, ...]:
    """Move one decimal price by a relative amount and re-derive proportional
    margin-adjusted probabilities (the production method)."""
    p = list(prices)
    p[index] = p[index] * (1 + rel)
    inv = [1 / x for x in p]
    s = sum(inv)
    return tuple(x / s for x in inv)
