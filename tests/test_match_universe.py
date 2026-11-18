# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Phase 6B.2: Screener match universe and one table presentation for both views.

* The "Only show matches with odds" toggle is removed (layout, callback, data layer).
* "All upcoming matches" shows every upcoming fixture, including those without odds.
* "Weekly Challenge" shows exactly the round snapshot's fixtures, with the same
  model-versus-market cell as "All upcoming matches", computed from the frozen
  snapshot's Diski 9 and market probabilities (never refreshed odds).
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from diski9.api_football.markets import Market
from diski9.app import create_app
from diski9.app.app import results_payload
from diski9.app.challenge.integration import challenge_cell, frozen_market_value
from diski9.odds.value import MARKET_ORDER, edge_pp, expected_value

from .test_app import EPL_FIX, EXTRA, PSL_FIX, T0, _text, data, page_ids, populated  # noqa: F401

MARKETS = {"1X2": Market.MATCH_RESULT, "BTTS": Market.BTTS, "OU25": Market.OVER_UNDER_25}


def run(d, market="1X2", direction="kickoff_earliest", challenge=None, leagues=(39, 288), thr=0):
    return results_payload(
        d, market, list(leagues), None, "2026-12-31", "overall", direction, thr, 1, None,
        challenge=challenge,
    )  # fmt: skip


def total(p) -> int:
    return int(p[2].split(" of ")[1].split()[0]) if p[2] else 0


def frozen(fid, market, model, mkt, odds):
    """Snapshot outcomes for one fixture and market (model, market probs, odds)."""
    m = MARKETS[market]
    return [
        SimpleNamespace(
            fixture_id=fid,
            market=m,
            outcome=o,
            model_probability=p,
            market_probability=q,
            reference_odds=Decimal(str(x)),
            key=(fid, str(m), str(o)),
        )
        for o, p, q, x in zip(MARKET_ORDER[m], model, mkt, odds, strict=True)
    ]


def challenge_for(market, values, picked=None):
    mvs = {fid: frozen_market_value(outs, market) for fid, outs in values.items()}
    return {
        "ids": set(values),
        "values": mvs,
        "picked": picked or {},
        "odds": {f: " · ".join(f"{o.odds:.2f}" for o in mv.outcomes) for f, mv in mvs.items()},
        "message": None,
        "snapshot": SimpleNamespace(snapshot_at=T0),
    }


# ------------------------------------------------------------- toggle removed
def test_odds_toggle_is_gone_from_layout_callback_and_data_layer(data):
    app = create_app(data)
    layout = app.server.test_client().get("/_dash-layout").get_data(as_text=True)
    assert "odds-only" not in layout and "Only show matches with odds" not in layout
    cb = next(v for k, v in app.callback_map.items() if "results-table.children" in k)
    assert not any(i["id"] == "odds-only" for i in cb["inputs"])
    assert any(i["id"] == "universe" for i in cb["inputs"])
    assert "odds_only" not in inspect.signature(results_payload).parameters
    assert "odds_only" not in inspect.signature(type(data).filtered).parameters
    assert '"id":"universe"' in layout
    assert '"value":"challenge"' in layout and "All upcoming matches" in layout


@pytest.mark.parametrize("market", list(MARKETS))
def test_all_upcoming_includes_fixtures_without_odds(data, market):
    p = run(data, market)
    assert total(p) == 15
    ids = page_ids(p) + page_ids(results_payload(data, market, [39, 288], None, "2026-12-31",
                                                 "overall", "kickoff_earliest", 0, 2))  # fmt: skip
    assert PSL_FIX in ids  # PSL has no bookmaker odds and is still listed
    assert data.row(market, data.detail(PSL_FIX)[0])["odds"] == "No odds"


# ------------------------------------------------------- Weekly Challenge view
@pytest.mark.parametrize("market", list(MARKETS))
def test_challenge_view_shows_exactly_the_snapshot_fixtures(data, market):
    n = len(MARKET_ORDER[MARKETS[market]])
    model, mkt = [0.6, 0.25, 0.15][:n], [0.5, 0.3, 0.2][:n]
    if n == 2:
        model, mkt = [0.62, 0.38], [0.55, 0.45]
    odds = [round(1 / q * 0.95, 2) for q in mkt]
    ch = challenge_for(market, {EPL_FIX: frozen(EPL_FIX, market, model, mkt, odds),
                                EXTRA[0]: frozen(EXTRA[0], market, mkt, mkt, odds)})  # fmt: skip
    p = run(data, market, challenge=ch)
    assert set(page_ids(p)) == {EPL_FIX, EXTRA[0]} and total(p) == 2
    table = _text(p[0])
    assert "Challenge odds" not in table  # the raw odds sequence row label is gone
    top = MARKET_ORDER[MARKETS[market]][0]
    cell = challenge_cell(ch, market, EPL_FIX, "edge", None)
    label = {"1X2": "Home", "BTTS": "Yes", "OU25": "Over 2.5"}[market]
    want = edge_pp(model[0], mkt[0])
    assert cell["main"] == f"{label} {want:+.1f} pp" and cell["sub"] == f"Market {mkt[0]:.1%}"
    assert cell["cls"] == "pos" and "not expected value" in cell["title"]
    flat = challenge_cell(ch, market, EXTRA[0], "edge", None)  # model == market
    assert flat["main"] == "No positive edge"
    ev = challenge_cell(ch, market, EPL_FIX, "ev", None)
    best = max(range(n), key=lambda i: expected_value(model[i], Decimal(str(odds[i]))))
    assert ev["main"].endswith("EV") and f"at {Decimal(str(odds[best]))}" == ev["sub"]
    assert top in MARKET_ORDER[MARKETS[market]]


def test_challenge_view_uses_frozen_values_not_live_odds(data):
    """The test database has live consensus odds for EPL_FIX; the Challenge cell and
    the edge ranking must come from the snapshot values only."""
    live = data.value_cell("1X2", data.detail(EPL_FIX)[0], "edge")
    ch = challenge_for("1X2", {EPL_FIX: frozen(EPL_FIX, "1X2", [0.3, 0.3, 0.4], [0.3, 0.3, 0.4],
                                               [3.2, 3.2, 2.4]),
                               EXTRA[0]: frozen(EXTRA[0], "1X2", [0.7, 0.2, 0.1], [0.5, 0.3, 0.2],
                                                [1.9, 3.2, 4.8])})  # fmt: skip
    cell = challenge_cell(ch, "1X2", EPL_FIX, "edge", None)
    assert cell["main"] == "No positive edge" and cell != live
    p = run(data, "1X2", direction="edge", challenge=ch)
    assert page_ids(p) == [EXTRA[0], EPL_FIX]  # ranked by the frozen edge


def test_pick_marker_and_incomplete_market(data):
    outs = frozen(EPL_FIX, "1X2", [0.6, 0.25, 0.15], [0.5, 0.3, 0.2], [1.9, 3.2, 4.8])
    ch = challenge_for("1X2", {EPL_FIX: outs[:2]}, picked={EPL_FIX: "Home win"})
    cell = challenge_cell(ch, "1X2", EPL_FIX, "edge", None)
    assert cell["main"] == "Incomplete market" and cell["picked"] == "Home win"
    assert "Your pick: Home win" in _text(run(data, challenge=ch)[0])
    missing = challenge_cell({**ch, "values": {EPL_FIX: None}}, "1X2", EPL_FIX, "edge", None)
    assert missing["main"] == "Not in this market"


def test_universe_switch_resets_page_and_dates(data):
    app = create_app(data)
    keys = [k for k in app.callback_map if "dates.start_date" in k and "universe" in str(
        app.callback_map[k]["inputs"])]  # fmt: skip
    assert keys, "switching universe must update the date range"
    from diski9.app.app import universe_dates
    from diski9.app.challenge.service import ChallengeService

    svc = ChallengeService(data)
    today = data.clock().astimezone(data.tz).date()
    assert universe_dates(data, svc, None, "all") == (today, today + timedelta(days=14))
    demo = svc.demo()
    start, end = universe_dates(data, svc, {"mode": "demo"}, "challenge")
    days = {f.kickoff.astimezone(data.tz).date() for f in demo.fixtures}
    assert (start, end) == (min(days), max(days))
    # no playable round: the date range is left alone
    assert universe_dates(data, svc, None, "challenge") in (None, (start, end))
