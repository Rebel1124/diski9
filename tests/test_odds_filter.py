# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Screener filter: "Only show matches with odds" (fresh or stale, per market)."""

from __future__ import annotations

import pytest

from diski9.app import ScreenerData, create_app
from diski9.app.app import NO_ODDS_MESSAGE, ODDS_ONLY, results_payload
from diski9.app.data import PAGE_SIZE

from .test_app import DAY, EPL_FIX, EXTRA, PSL_FIX, T0, _text, data, page_ids, populated  # noqa: F401

MARKETS = ("1X2", "BTTS", "OU25")


def run(
    d,
    market="1X2",
    odds_only=False,
    leagues=(39, 288),
    page=1,
    direction=None,
    thr=0,
    selected=None,
):
    return results_payload(
        d,
        market,
        list(leagues),
        None,
        "2026-12-31",
        "overall",
        direction,
        thr,
        page,
        selected,
        odds_only=odds_only,
    )


def total(p) -> int:
    return int(p[2].split(" of ")[1].split()[0]) if p[2] else 0


@pytest.mark.parametrize("market", MARKETS)
def test_default_unchecked_shows_everything(data, market):
    assert total(run(data, market)) == 15  # unchanged behaviour


@pytest.mark.parametrize("market", MARKETS)
def test_odds_only_keeps_fixtures_with_odds_for_that_market(data, market):
    p = run(data, market, odds_only=True)
    assert page_ids(p) == [EPL_FIX] and total(p) == 1
    assert p[5] == "Page 1 of 1" and p[9] == {"display": "none"}  # counted before paging
    row = data.row(market, data.detail(EPL_FIX)[0])
    assert row["odds_status"] in ("fresh", "stale") and row["odds"] not in ("No odds", "—")
    for fid in (PSL_FIX, EXTRA[0]):  # "No odds" / no price for this market
        assert data.row(market, data.detail(fid)[0])["odds_status"] == "unavailable"


def test_stale_odds_still_qualify(populated):
    stale = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0 + 2 * DAY)
    for market in MARKETS:
        p = run(stale, market, odds_only=True)
        assert page_ids(p) == [EPL_FIX]
        assert stale.row(market, stale.detail(EPL_FIX)[0])["odds_status"] == "stale"


def test_market_independence(populated):
    from diski9.api_football.markets import Market

    d = ScreenerData(populated, ttl_seconds=3600, clock=lambda: T0)  # one cached snapshot
    btts = d.snapshot().odds[EPL_FIX].markets[Market.BTTS]
    original = btts.status
    object.__setattr__(btts, "status", "unavailable")  # BTTS prices missing for this fixture
    try:
        assert page_ids(run(d, "BTTS", odds_only=True)) == []
        assert page_ids(run(d, "1X2", odds_only=True)) == [EPL_FIX]
        assert page_ids(run(d, "OU25", odds_only=True)) == [EPL_FIX]
    finally:
        object.__setattr__(btts, "status", original)


def test_friendly_message_and_combination_with_other_filters(data):
    p = run(data, odds_only=True, leagues=[288])  # PSL has no bookmaker odds
    assert p[0] is None and NO_ODDS_MESSAGE in _text(p[4])
    plain = run(data, leagues=[288])
    assert page_ids(plain) == [PSL_FIX]
    # ranking and probability threshold still apply on top
    p = run(data, odds_only=True, direction="home_win", thr=1)
    assert page_ids(p) == [EPL_FIX]
    p = run(data, odds_only=True, direction="home_win", thr=99)
    assert page_ids(p) == [] and NO_ODDS_MESSAGE in _text(p[4])
    # a selection that the filter removes is cleared; one that remains is kept
    assert run(data, odds_only=True, selected=EXTRA[0])[10] is None
    assert run(data, odds_only=True, selected=EPL_FIX)[10] == EPL_FIX


def test_pagination_without_filter_still_pages(data):
    p1, p2 = run(data, page=1), run(data, page=2)
    assert len(page_ids(p1)) == PAGE_SIZE and len(page_ids(p2)) == 5
    assert run(data, odds_only=True, page=2)[8] == 1  # page clamps to the filtered total


def test_checkbox_in_layout_and_callback_and_kept_across_markets(data):
    app = create_app(data)
    layout = app.server.test_client().get("/_dash-layout").get_data(as_text=True)
    assert '"id":"odds-only"' in layout and "Only show matches with odds" in layout
    assert '"value":[]' in layout  # unchecked by default
    cb = next(v for k, v in app.callback_map.items() if "results-table.children" in k)
    assert any(i["id"] == "odds-only" for i in cb["inputs"])
    # no callback writes the checkbox, so a market switch never resets it
    assert not any("odds-only.value" in k for k in app.callback_map)
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    func = cb["callback"].__wrapped__
    for market in MARKETS:
        context_value.set(
            AttributeDict(triggered_inputs=[{"prop_id": "market.value", "value": market}])
        )
        out = func(
            market,
            [39, 288],
            None,
            "2026-12-31",
            "kickoff_earliest",
            0,
            [ODDS_ONLY],
            1,
            1,
            [],
            [],
            1,
            None,
        )
        assert out[2] == "Showing 1–1 of 1 fixture" or "of 1 fixture" in out[2]
