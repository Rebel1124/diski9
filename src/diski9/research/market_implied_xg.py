"""Research prototype (Milestone 5.1): market-implied expected goals.

Layer 2 (market-implied information). NOT used by the Screener or the Challenge.
Estimates home and away scoring rates (lambda_H, lambda_A) under an independent
Poisson model such that the model's market probabilities match margin-adjusted
consensus probabilities as closely as possible. These are *market-implied
expected goals*, not shot-based xG.

Model
    X_H ~ Poisson(lambda_H), X_A ~ Poisson(lambda_A), independent
    P(home) = P(X_H > X_A), P(draw) = P(X_H = X_A), P(away) = P(X_H < X_A)
    P(BTTS) = (1 - e^-lambda_H)(1 - e^-lambda_A)
    P(Over 2.5) = 1 - e^-T (1 + T + T^2/2),  T = lambda_H + lambda_A

Fitting objective
    L = sum over available markets m of KL(p_m^market || p_m^model)
Each market enters once as a full distribution (1X2: 3 outcomes; BTTS and O/U
2.5: 2), so complementary outcomes are never double-counted and every market
has equal weight. KL is the expected excess log loss of the model distribution
under the market distribution - a proper criterion for probabilities, invariant
to which side of a binary market is quoted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

LAMBDA_BOUNDS = (0.05, 6.0)
TAIL_TOLERANCE = 1e-12
INITIAL_POINTS = (
    (1.0, 1.0),
    (1.6, 1.0),
    (1.0, 1.6),
    (2.4, 0.7),
    (0.7, 2.4),
    (0.6, 0.6),
    (3.0, 1.5),
)
MARKETS = ("1x2", "btts", "ou25")

# Fit-quality thresholds on the largest absolute probability residual across all
# fitted outcomes (see docs/milestone5_1_market_implied_xg.md for the evidence):
GOOD_FIT_MAX_RESIDUAL = 0.02
APPROX_FIT_MAX_RESIDUAL = 0.04


# ------------------------------------------------------------------ model
def poisson_pmf(lam: float, tolerance: float = TAIL_TOLERANCE) -> list[float]:
    """P(X = k) for k = 0..K, with K chosen so the omitted tail is below ``tolerance``."""
    pmf = [math.exp(-lam)]
    cum = pmf[0]
    k = 0
    while 1 - cum > tolerance and k < 200:
        k += 1
        pmf.append(pmf[-1] * lam / k)
        cum += pmf[-1]
    return pmf


def model_probabilities(lam_h: float, lam_a: float) -> dict[str, Any]:
    """Model probabilities for all three markets, plus grid diagnostics."""
    ph, pa = poisson_pmf(lam_h), poisson_pmf(lam_a)
    home = draw = away = 0.0
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            p = x * y
            if i > j:
                home += p
            elif i == j:
                draw += p
            else:
                away += p
    mass = home + draw + away
    t = lam_h + lam_a
    over = 1 - math.exp(-t) * (1 + t + t * t / 2)
    btts = (1 - math.exp(-lam_h)) * (1 - math.exp(-lam_a))
    return {
        "1x2": (home / mass, draw / mass, away / mass),
        "btts": (btts, 1 - btts),
        "ou25": (over, 1 - over),
        "omitted_mass": max(0.0, 1 - mass),
    }


# ----------------------------------------------------------------- inputs
@dataclass(frozen=True)
class MarketInputs:
    """Margin-adjusted (normalised) market probabilities; any market may be missing."""

    p1x2: tuple[float, float, float] | None = None  # home, draw, away
    btts: tuple[float, float] | None = None  # yes, no
    ou25: tuple[float, float] | None = None  # over, under
    metadata: dict[str, Any] = field(default_factory=dict)

    def available(self) -> dict[str, tuple[float, ...]]:
        return {
            m: v
            for m, v in (("1x2", self.p1x2), ("btts", self.btts), ("ou25", self.ou25))
            if v is not None
        }

    def validate(self) -> list[str]:
        problems = []
        for m, v in self.available().items():
            if any((not math.isfinite(x)) or x <= 0 or x >= 1 for x in v):
                problems.append(f"{m}: probabilities must be strictly between 0 and 1")
            elif abs(sum(v) - 1) > 1e-6:
                problems.append(
                    f"{m}: probabilities sum to {sum(v):.6f}, not 1 (margin not removed?)"
                )
        return problems


# -------------------------------------------------------------- estimation
@dataclass
class FitResult:
    # good_fit | approximate_fit | poor_fit | insufficient_market_data
    # | optimization_failure | invalid_input
    status: str
    markets_used: tuple[str, ...]
    lambda_home: float | None = None
    lambda_away: float | None = None
    lambda_total: float | None = None
    model: dict[str, tuple[float, ...]] | None = None
    market: dict[str, tuple[float, ...]] | None = None
    residuals: dict[str, tuple[float, ...]] | None = None
    max_abs_residual: float | None = None
    objective: float | None = None
    converged: bool | None = None
    at_boundary: bool | None = None
    identified: bool | None = None
    exactly_identified: bool | None = None
    jacobian_singular_values: tuple[float, ...] | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _objective(lams, market: dict[str, tuple[float, ...]]) -> float:
    model = model_probabilities(float(lams[0]), float(lams[1]))
    total = 0.0
    for m, p in market.items():
        q = model[m]
        total += sum(pi * math.log(pi / max(qi, 1e-15)) for pi, qi in zip(p, q, strict=True))
    return total


def _independent_constraints(lam_h: float, lam_a: float, markets: tuple[str, ...]) -> list[float]:
    """One value per independent constraint: 1X2 -> (P(H), P(A)); BTTS -> P(yes); O/U -> P(over)."""
    mp = model_probabilities(lam_h, lam_a)
    out = []
    if "1x2" in markets:
        out += [mp["1x2"][0], mp["1x2"][2]]
    if "btts" in markets:
        out.append(mp["btts"][0])
    if "ou25" in markets:
        out.append(mp["ou25"][0])
    return out


def jacobian_singular_values(lam_h: float, lam_a: float, markets: tuple[str, ...], h: float = 1e-5):
    import numpy as np

    f0 = np.array(_independent_constraints(lam_h, lam_a, markets))
    fh = np.array(_independent_constraints(lam_h + h, lam_a, markets))
    fa = np.array(_independent_constraints(lam_h, lam_a + h, markets))
    J = np.column_stack([(fh - f0) / h, (fa - f0) / h])
    return tuple(float(s) for s in np.linalg.svd(J, compute_uv=False))


def fit(inputs: MarketInputs, bounds: tuple[float, float] = LAMBDA_BOUNDS) -> FitResult:
    """Estimate (lambda_H, lambda_A). Deterministic multi-start bounded L-BFGS-B."""
    import numpy as np
    from scipy.optimize import minimize, minimize_scalar

    market = inputs.available()
    used = tuple(m for m in MARKETS if m in market)
    problems = inputs.validate()
    if problems:
        return FitResult(
            "invalid_input", used, message="; ".join(problems), metadata=inputs.metadata
        )
    if not market:
        return FitResult(
            "insufficient_market_data",
            used,
            message="no market probabilities",
            metadata=inputs.metadata,
        )

    n_constraints = (2 if "1x2" in market else 0) + ("btts" in market) + ("ou25" in market)
    if n_constraints < 2:
        # One constraint cannot identify two rates. For O/U 2.5 alone the total is identified.
        res = FitResult(
            "insufficient_market_data", used, identified=False, metadata=inputs.metadata
        )
        if used == ("ou25",):
            target = market["ou25"][0]
            sol = minimize_scalar(
                lambda t: (1 - math.exp(-t) * (1 + t + t * t / 2) - target) ** 2,
                bounds=(2 * bounds[0], 2 * bounds[1]),
                method="bounded",
                options={"xatol": 1e-10},
            )
            res.lambda_total = float(sol.x)
            res.message = (
                "Over/Under 2.5 alone identifies only total expected goals "
                f"({res.lambda_total:.3f}), not the home/away split."
            )
        else:
            res.message = (
                "BTTS alone constrains only (1 - e^-lH)(1 - e^-lA); infinitely many "
                "(lH, lA) pairs fit equally well."
            )
        return res

    best = None
    for start in INITIAL_POINTS:
        r = minimize(
            _objective,
            np.array(start),
            args=(market,),
            method="L-BFGS-B",
            bounds=[bounds, bounds],
            options={"ftol": 1e-15, "gtol": 1e-10, "maxiter": 500},
        )
        if best is None or r.fun < best.fun - 1e-14:
            best = r
    if best is None or not np.all(np.isfinite(best.x)):
        return FitResult(
            "optimization_failure",
            used,
            message="optimiser returned no finite solution",
            metadata=inputs.metadata,
        )
    lh, la = float(best.x[0]), float(best.x[1])
    model_all = model_probabilities(lh, la)
    model = {m: model_all[m] for m in used}
    residuals = {m: tuple(q - p for q, p in zip(model[m], market[m], strict=True)) for m in used}
    max_res = max(abs(x) for v in residuals.values() for x in v)
    eps = 1e-3
    at_boundary = any(abs(x - b) < eps for x in (lh, la) for b in bounds)
    sv = jacobian_singular_values(lh, la, used)
    identified = len(sv) >= 2 and sv[-1] > 1e-4
    result = FitResult(
        status="",
        markets_used=used,
        lambda_home=lh,
        lambda_away=la,
        lambda_total=lh + la,
        model={m: model_all[m] for m in MARKETS},
        market=market,
        residuals=residuals,
        max_abs_residual=max_res,
        objective=float(best.fun),
        converged=bool(best.success),
        at_boundary=at_boundary,
        identified=identified,
        exactly_identified=n_constraints == 2,
        jacobian_singular_values=sv,
        metadata=inputs.metadata,
    )
    if not identified:
        result.status, result.message = (
            "insufficient_market_data",
            "parameters not locally identifiable",
        )
    elif not best.success and max_res > APPROX_FIT_MAX_RESIDUAL:
        result.status, result.message = "optimization_failure", str(best.message)
    elif at_boundary:
        result.status, result.message = (
            "poor_fit",
            "a rate reached its bound; market prices are extreme or inconsistent",
        )
    elif max_res <= GOOD_FIT_MAX_RESIDUAL:
        result.status = "good_fit"
    elif max_res <= APPROX_FIT_MAX_RESIDUAL:
        result.status = "approximate_fit"
    else:
        result.status, result.message = (
            "poor_fit",
            "market prices are not jointly consistent with independent Poisson",
        )
    if result.exactly_identified and result.status == "good_fit":
        result.message = (
            "exactly identified: two constraints, two parameters (no overidentifying check)"
        )
    return result


def subset(inputs: MarketInputs, markets: tuple[str, ...]) -> MarketInputs:
    a = inputs.available()
    return MarketInputs(
        p1x2=a.get("1x2") if "1x2" in markets else None,
        btts=a.get("btts") if "btts" in markets else None,
        ou25=a.get("ou25") if "ou25" in markets else None,
        metadata=inputs.metadata,
    )


def from_display(displayed: dict, fixture_id: int, include_stale: bool = False) -> MarketInputs:
    """Build inputs from production display consensus (``odds.display``).

    Each market's margin-adjusted probabilities come from one coherent consensus
    snapshot. By default only *fresh* markets are used; stale markets (the last
    pre-kickoff consensus) are excluded unless ``include_stale`` is set. Odds are
    never taken from after kickoff (the display layer only uses pre-kickoff quotes).
    """
    from diski9.api_football.markets import Market, Outcome

    def probs(market, outcomes):
        dm = displayed[market]
        if dm.status == "unavailable" or (dm.status == "stale" and not include_stale):
            return None
        if dm.implied is None or dm.implied.margin_adjusted is None:
            return None
        return tuple(float(dm.implied.margin_adjusted[o]) for o in outcomes)

    meta = {"fixture_id": fixture_id}
    for market in Market:
        dm = displayed[market]
        mc = dm.consensus
        meta[market.value] = {
            "status": dm.status,
            "sources": mc.sources if mc else None,
            "prices": {o.value: str(oc.consensus_odds) for o, oc in mc.outcomes.items()}
            if mc
            else None,
            "checked_at": mc.latest_observation.isoformat()
            if mc and mc.latest_observation
            else None,
            "provider_updated_at": mc.provider_updated_at.isoformat()
            if mc and mc.provider_updated_at
            else None,
        }
    return MarketInputs(
        p1x2=probs(Market.MATCH_RESULT, (Outcome.HOME, Outcome.DRAW, Outcome.AWAY)),
        btts=probs(Market.BTTS, (Outcome.BTTS_YES, Outcome.BTTS_NO)),
        ou25=probs(Market.OVER_UNDER_25, (Outcome.OVER_25, Outcome.UNDER_25)),
        metadata=meta,
    )
