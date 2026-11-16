"""Milestone 5.2 research: Poisson and Dixon-Coles goal models (research only)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from diski9.research import goal_models as gm
from diski9.research.goal_models import (
    LAMBDA_BOUNDS,
    Spec,
    fit_market,
    market_probabilities,
    perturb_price,
    probabilities,
    rho_limits,
    score_matrix,
)


def markets_of(lh, la, rho=0.0, keys=("1x2", "btts", "ou25")):
    p = probabilities(lh, la, rho)
    return {k: p[k] for k in keys}


@pytest.mark.parametrize(
    "lh,la,rho", [(0.3, 0.2, 0), (1.5, 1.1, 0), (4.5, 0.4, 0), (1.4, 1.2, -0.12), (1.0, 0.9, 0.2)]
)
def test_scoreline_matrix_is_a_valid_distribution(lh, la, rho):
    M, omitted = score_matrix(lh, la, rho)
    assert (M >= 0).all()
    assert M.sum() == pytest.approx(1, abs=1e-12)
    assert omitted < 1e-11
    p = market_probabilities(M)
    assert sum(p["1x2"]) == pytest.approx(1, abs=1e-12)
    assert sum(p["btts"]) == pytest.approx(1, abs=1e-12)
    assert sum(p["ou25"]) == pytest.approx(1, abs=1e-12)
    full = probabilities(lh, la, rho)
    assert full["total_goals"].sum() == pytest.approx(1, abs=1e-12)


def test_poisson_closed_forms():
    lh, la = 1.7, 0.9
    p = probabilities(lh, la)
    assert p["btts"][0] == pytest.approx((1 - math.exp(-lh)) * (1 - math.exp(-la)), abs=1e-10)
    t = lh + la
    assert p["ou25"][0] == pytest.approx(1 - math.exp(-t) * (1 + t + t * t / 2), abs=1e-10)
    assert p["expected_home"] == pytest.approx(lh, abs=1e-9)


def test_dixon_coles_adjusts_only_low_scores_and_preserves_mass():
    lh, la, rho = 1.4, 1.1, -0.1
    P, _ = score_matrix(lh, la)
    D, _ = score_matrix(lh, la, rho)
    assert D[0, 0] > P[0, 0] and D[1, 1] > P[1, 1]  # negative rho: more 0-0 and 1-1
    assert D[1, 0] < P[1, 0] and D[0, 1] < P[0, 1]
    mask = np.ones_like(P, dtype=bool)
    mask[:2, :2] = False
    assert np.allclose(D[mask], P[mask], atol=1e-15)  # no other score changes
    # tau terms cancel exactly: the four cells keep their total mass
    assert D[:2, :2].sum() == pytest.approx(P[:2, :2].sum(), abs=1e-15)
    assert probabilities(lh, la, rho)["1x2"][1] > probabilities(lh, la)["1x2"][1]
    assert probabilities(lh, la, 0.1)["1x2"][1] < probabilities(lh, la)["1x2"][1]
    assert np.allclose(score_matrix(lh, la, 0.0)[0], P)


def test_dixon_coles_validity_constraints():
    lo, hi = rho_limits(2.0, 1.5)
    assert lo == pytest.approx(-0.5) and hi == pytest.approx(1 / 3)
    M, _ = score_matrix(2.0, 1.5, hi)  # boundary: tau(0,0) = 0, still valid
    assert M[0, 0] == pytest.approx(0, abs=1e-15) and (M >= 0).all()
    with pytest.raises(ValueError):
        score_matrix(2.0, 1.5, hi + 0.01)
    with pytest.raises(ValueError):
        score_matrix(0.0, 1.0)
    with pytest.raises(ValueError):
        score_matrix(1.0, float("nan"))


def test_poisson_fit_recovers_known_rates_with_each_configuration():
    lh, la = 1.65, 1.05
    for keys in (("1x2",), ("1x2", "ou25"), ("1x2", "btts"), ("1x2", "btts", "ou25")):
        f = fit_market(markets_of(lh, la, keys=keys))
        assert f.status == "good_fit", (keys, f.message)
        assert f.lambda_home == pytest.approx(lh, abs=2e-4)
        assert f.lambda_away == pytest.approx(la, abs=2e-4)
        assert f.max_abs_error < 1e-6
        assert f.converged


def test_dixon_coles_fit_fixed_and_free():
    lh, la, rho = 1.5, 1.2, -0.1
    mk = markets_of(lh, la, rho)
    fixed = fit_market(mk, Spec("dc_fixed", rho))
    assert fixed.status == "good_fit"
    assert fixed.lambda_home == pytest.approx(lh, abs=2e-4) and fixed.rho == rho
    free = fit_market(mk, Spec("dc_free"))
    assert free.status == "good_fit"
    assert free.rho == pytest.approx(rho, abs=5e-3)
    assert free.lambda_home == pytest.approx(lh, abs=5e-3)
    # rho always respects bounds and the validity interval
    lo, hi = rho_limits(free.lambda_home, free.lambda_away)
    assert max(gm.RHO_BOUNDS[0], lo) <= free.rho <= min(gm.RHO_BOUNDS[1], hi)


def test_unidentified_and_insufficient_inputs_are_flagged():
    mk = markets_of(1.5, 1.2)
    assert fit_market({"btts": mk["btts"]}).status == "insufficient_market_data"
    assert fit_market({"ou25": mk["ou25"]}).status == "insufficient_market_data"
    # three parameters cannot come from two constraints
    assert fit_market({"1x2": mk["1x2"]}, Spec("dc_free")).status == "insufficient_market_data"
    assert fit_market({}, Spec()).status == "insufficient_market_data"
    # 1X2 + O/U with free rho is exactly identified (no spare constraint), never over-claimed
    f = fit_market({"1x2": mk["1x2"], "ou25": mk["ou25"]}, Spec("dc_free"))
    assert f.status in ("good_fit", "unidentified")
    if f.status == "good_fit":
        assert "exactly identified" in f.message


def test_invalid_market_inputs_rejected():
    assert fit_market({"1x2": (0.5, 0.3, 0.3)}).status == "invalid_input"  # margin not removed
    assert fit_market({"1x2": (0.6, 0.4)}).status == "invalid_input"  # incomplete outcome set
    assert fit_market({"1x2": (1.0, 0.0, 0.0)}).status == "invalid_input"
    assert fit_market({"1x2": (0.5, float("nan"), 0.5)}).status == "invalid_input"
    assert fit_market({"btts": (0.5, 0.5), "corners": (0.5, 0.5)}).status == "invalid_input"
    assert fit_market({"1x2": (0.5, 0.25, 0.25)}, Spec("dc_fixed", 0.9)).status == "invalid_input"


def test_estimates_stay_within_bounds_and_extremes_flagged():
    f = fit_market({"1x2": (0.996, 0.003, 0.001)})
    assert LAMBDA_BOUNDS[0] <= f.lambda_home <= LAMBDA_BOUNDS[1]
    assert LAMBDA_BOUNDS[0] <= f.lambda_away <= LAMBDA_BOUNDS[1]
    assert f.status in ("poor_fit", "unidentified") and not f.usable


def test_optimisation_failure_reported(monkeypatch):
    import scipy.optimize

    def broken(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(scipy.optimize, "minimize", broken)
    f = fit_market(markets_of(1.4, 1.0))
    assert f.status == "optimization_failure" and not f.usable


def test_inconsistent_market_is_not_reported_as_good():
    # draw far above anything independent Poisson can produce with these goals markets
    mk = {"1x2": (0.35, 0.45, 0.20), "btts": (0.70, 0.30), "ou25": (0.75, 0.25)}
    f = fit_market(mk)
    assert f.status in ("poor_fit", "approximate_fit") and f.max_abs_error > 0.02


def test_fits_are_reproducible():
    mk = markets_of(1.3, 1.6, -0.05)
    a, b = fit_market(mk, Spec("dc_free")), fit_market(mk, Spec("dc_free"))
    assert (a.lambda_home, a.lambda_away, a.rho) == (b.lambda_home, b.lambda_away, b.rho)


def test_squared_error_objective_also_recovers():
    f = fit_market(markets_of(1.2, 0.8), Spec("poisson", objective="sq"))
    assert f.lambda_home == pytest.approx(1.2, abs=1e-3) and f.status == "good_fit"


def test_price_perturbation_renormalises():
    p = perturb_price((1.40, 5.00, 7.00), 1, 0.01)
    assert sum(p) == pytest.approx(1)
    base = perturb_price((1.40, 5.00, 7.00), 1, 0.0)
    assert p[1] < base[1]  # a longer draw price means a lower draw probability
