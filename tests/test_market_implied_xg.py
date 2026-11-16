"""Independent-Poisson market-implied expected goals (research prototype)."""

from __future__ import annotations

import math
from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diski9.research.market_implied_xg import (
    MarketInputs,
    fit,
    from_display,
    model_probabilities,
    poisson_pmf,
    subset,
)

ALL = ("1x2", "btts", "ou25")


def inputs_for(lh, la):
    m = model_probabilities(lh, la)
    return MarketInputs(m["1x2"], m["btts"], m["ou25"])


@given(st.floats(0.05, 5.0), st.floats(0.05, 5.0))
@settings(max_examples=60)
def test_probabilities_normalised_and_complementary(lh, la):
    m = model_probabilities(lh, la)
    assert sum(m["1x2"]) == pytest.approx(1, abs=1e-12)
    assert sum(m["btts"]) == pytest.approx(1) and sum(m["ou25"]) == pytest.approx(1)
    assert m["omitted_mass"] < 1e-11
    assert sum(poisson_pmf(lh)) == pytest.approx(1, abs=1e-11)


def test_closed_forms_match_score_grid():
    lh, la = 1.85, 0.85
    ph, pa = poisson_pmf(lh), poisson_pmf(la)
    btts = sum(ph[i] * pa[j] for i in range(1, len(ph)) for j in range(1, len(pa)))
    over = sum(ph[i] * pa[j] for i in range(len(ph)) for j in range(len(pa)) if i + j >= 3)
    m = model_probabilities(lh, la)
    assert m["btts"][0] == pytest.approx(btts, abs=1e-10)
    assert m["ou25"][0] == pytest.approx(over, abs=1e-10)
    t = lh + la
    assert m["ou25"][0] == pytest.approx(1 - math.exp(-t) * (1 + t + t * t / 2))


@pytest.mark.parametrize("lh,la", [(1.85, 0.85), (0.9, 1.6), (1.3, 1.3), (2.8, 0.6)])
@pytest.mark.parametrize("combo", [("1x2",), ("1x2", "ou25"), ("1x2", "btts"), ALL])
def test_recovers_known_parameters(lh, la, combo):
    r = fit(subset(inputs_for(lh, la), combo))
    assert r.status == "good_fit" and r.converged
    assert r.lambda_home == pytest.approx(lh, abs=2e-4) and r.lambda_away == pytest.approx(
        la, abs=2e-4
    )
    assert r.max_abs_residual < 1e-5


def test_single_market_is_insufficient():
    inp = inputs_for(1.85, 0.85)
    ou = fit(subset(inp, ("ou25",)))
    assert ou.status == "insufficient_market_data" and ou.lambda_home is None
    assert ou.lambda_total == pytest.approx(2.7, abs=1e-4)  # only the total is identified
    btts = fit(subset(inp, ("btts",)))
    assert (
        btts.status == "insufficient_market_data"
        and btts.lambda_home is None
        and btts.lambda_total is None
    )
    assert fit(MarketInputs()).status == "insufficient_market_data"


def test_one_x_two_alone_is_weakly_identified():
    r = fit(subset(inputs_for(1.85, 0.85), ("1x2",)))
    full = fit(inputs_for(1.85, 0.85))
    assert (
        r.exactly_identified
        and r.jacobian_singular_values[-1] < full.jacobian_singular_values[-1] / 3
    )


def test_contradictory_markets_flagged_not_forced():
    strong_home = model_probabilities(2.6, 0.5)
    low_scoring = model_probabilities(0.5, 0.4)
    r = fit(MarketInputs(strong_home["1x2"], low_scoring["btts"], low_scoring["ou25"]))
    assert r.status == "poor_fit" and r.max_abs_residual > 0.04


def test_invalid_inputs_rejected():
    assert fit(MarketInputs(p1x2=(0.6, 0.3, 0.2))).status == "invalid_input"  # margin not removed
    assert fit(MarketInputs(ou25=(1.0, 0.0))).status == "invalid_input"
    assert fit(MarketInputs(btts=(float("nan"), 0.5))).status == "invalid_input"


def test_boundary_solution_reported():
    r = fit(inputs_for(5.9999, 0.05))
    assert r.at_boundary and r.status == "poor_fit"


def test_deterministic():
    inp = MarketInputs((0.55, 0.25, 0.20), (0.52, 0.48), (0.55, 0.45))
    a, b = fit(inp), fit(inp)
    assert (a.lambda_home, a.lambda_away, a.objective) == (
        b.lambda_home,
        b.lambda_away,
        b.objective,
    )


def test_inputs_from_display_never_use_post_kickoff_odds(conn):
    from diski9.odds.collect import OddsPage, reconcile_pages
    from diski9.odds.display import display_consensus

    from .factories import T0, full_book, odds_item
    from .test_odds_collect import KICK, setup

    setup(conn)
    item = odds_item(
        1,
        {b: full_book() for b in (8, 11, 4)},
        kickoff=KICK,
        update=(T0 - timedelta(hours=1)).isoformat(),
    )
    reconcile_pages(conn, 39, 2026, [OddsPage(T0, [item])], clock=lambda: T0)
    before = from_display(display_consensus(conn, 1, T0 + timedelta(hours=1)), 1)
    assert set(before.available()) == set(ALL)
    assert before.metadata["1X2"]["sources"] == 3 and before.metadata["1X2"]["status"] == "fresh"
    assert fit(before).status in ("good_fit", "approximate_fit", "poor_fit")
    disp_after = display_consensus(conn, 1, KICK + timedelta(minutes=1))
    after = from_display(disp_after, 1)
    assert after.available() == {}  # fixture started: no fresh market, stale excluded by default
    stale = from_display(disp_after, 1, include_stale=True)
    # opt-in stale inputs are the last *pre-kickoff* snapshot, never post-kickoff quotes
    assert set(stale.available()) == set(ALL)
    assert stale.metadata["1X2"]["checked_at"] < KICK.isoformat()
