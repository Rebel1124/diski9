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
from diski9.app.challenge.integration import (
    challenge_cell,
    frozen_market_value,
    frozen_probabilities,
)
from diski9.challenge.roundsheet import RoundFixture
from diski9.odds.value import MARKET_ORDER, edge_pp, expected_value

from .test_app import (  # noqa: F401
    EPL_FIX,
    EXTRA,
    PSL_FIX,
    T0,
    _text,
    data,
    give_history,
    page_ids,
    populated,
)

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


def challenge_for(market, values, picked=None, eg=None):
    """A Weekly Challenge view over a small frozen snapshot (fixtures in league 39)."""
    mvs = {fid: frozen_market_value(outs, market) for fid, outs in values.items()}
    fixtures = [
        RoundFixture(fid, 39, "EPL", f"Home {fid}", f"Away {fid}", T0 + timedelta(days=1),
                     (eg or {}).get(fid))
        for fid in values
    ]  # fmt: skip
    return {
        "ids": set(values),
        "values": mvs,
        "picked": picked or {},
        "odds": {f: " · ".join(f"{o.odds:.2f}" for o in mv.outcomes) for f, mv in mvs.items()},
        "frozen": {fid: frozen_probabilities(outs) for fid, outs in values.items()},
        "message": None,
        "snapshot": SimpleNamespace(snapshot_at=T0, fixtures=fixtures),
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


# ------------------------------------------- Phase 6B.3: frozen probability ranking
def _conflict(data):
    """Frozen snapshot probabilities chosen to rank opposite to the live cache."""
    give_history(data.engine, {EXTRA[0], EXTRA[1]})  # Goal Model 1.1: live model needs matches
    live = {fid: data.detail(fid)[0]["goal_model"]["probabilities"]["home"]
            for fid in (EPL_FIX, EXTRA[0], EXTRA[1])}  # fmt: skip
    by_live = sorted(live, key=lambda f: -live[f])
    frozen_home = {fid: 0.30 + 0.15 * i for i, fid in enumerate(by_live)}  # reversed
    values = {
        fid: frozen(fid, "1X2", [p, 0.25, 0.75 - p], [p - 0.02, 0.27, 0.75 - p],
                    [round(1 / (p - 0.02), 2), 3.6, round(1 / (0.75 - p), 2)])
        for fid, p in frozen_home.items()
    }  # fmt: skip
    eg = {fid: (1.0 + i, 0.5) for i, fid in enumerate(by_live)}
    return live, by_live, frozen_home, challenge_for("1X2", values, eg=eg)


def test_frozen_probabilities_rank_differently_from_the_live_cache(data):
    live, by_live, frozen_home, ch = _conflict(data)
    live_order = page_ids(run(data, direction="home_win", leagues=(39,)))
    assert [f for f in live_order if f in frozen_home] == by_live  # live ranking
    p = run(data, direction="home_win", challenge=ch)
    assert page_ids(p) == list(reversed(by_live))  # frozen ranking: the opposite
    table = _text(p[0])
    for fid, ph in frozen_home.items():  # the displayed values are the frozen ones
        assert f"{ph * 100:.1f}%" in table
        assert f"{live[fid] * 100:.1f}%" not in table or abs(live[fid] - ph) < 0.0005


def test_frozen_minimum_probability_filter_uses_the_displayed_values(data):
    live, by_live, frozen_home, ch = _conflict(data)
    # 50% keeps only fixtures whose *frozen* home probability is at least 50%
    keep = {f for f, ph in frozen_home.items() if ph >= 0.5}
    p = run(data, direction="home_win", challenge=ch, thr=50)
    assert set(page_ids(p)) == keep and total(p) == len(keep)


def test_frozen_estimated_goals_and_market_columns(data):
    live, by_live, frozen_home, ch = _conflict(data)
    p = run(data, direction="kickoff_earliest", challenge=ch)
    table = _text(p[0])
    assert "1.00 – 0.50" in table and "3.00 – 0.50" in table
    cards = _text(p[1])
    fid = by_live[0]
    assert ch["odds"][fid] in cards  # frozen reference odds on the cards


def test_missing_frozen_market_is_explicit_not_filled_from_live(data):
    outs = frozen(EPL_FIX, "1X2", [0.6, 0.25, 0.15], [0.5, 0.3, 0.2], [1.9, 3.2, 4.8])
    ch = challenge_for("1X2", {EPL_FIX: outs, EXTRA[0]: outs[:2]})  # EXTRA[0]: incomplete
    p = run(data, direction="home_win", challenge=ch)
    assert page_ids(p) == [EPL_FIX, EXTRA[0]]  # unavailable listed last
    assert "Not in snapshot" in _text(p[0]) and "Not in the round snapshot" in str(p[0])
    # Phase 8 CP3A-3: the minimum applies to the frozen *market* probability of any
    # outcome in the snapshot; EXTRA[0]'s frozen home outcome (60%) qualifies, and the
    # incomplete model still ranks it last (never filled in from live data)
    assert page_ids(run(data, direction="home_win", challenge=ch, thr=10)) == [EPL_FIX, EXTRA[0]]
    assert page_ids(run(data, direction="home_win", challenge=ch, thr=61)) == []
    # BTTS is not in this snapshot at all: no fixture is ranked with live values
    btts = run(data, market="BTTS", direction="btts_yes", challenge=ch, thr=10)
    assert page_ids(btts) == []


def test_frozen_universe_ignores_the_live_cache_entirely(data, monkeypatch):
    live, by_live, frozen_home, ch = _conflict(data)
    calls = []
    monkeypatch.setattr(type(data), "filtered", lambda *a, **k: calls.append(1) or [])
    assert set(page_ids(run(data, direction="home_win", challenge=ch))) == set(frozen_home)
    assert calls == []  # never consulted for the Weekly Challenge universe
