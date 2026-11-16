"""Dash application tests (Milestone 5 interface)."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from dash import html
from sqlalchemy import update

from diski9.app import ScreenerData, create_app
from diski9.app.app import (
    columns_for,
    fixture_card,
    header_sort,
    results_payload,
    threshold_config,
)
from diski9.app.data import DIRECTIONS, PAGE_SIZE, paginate, valid_direction
from diski9.app.views import basis_help, render_detail
from diski9.db.schema import fixtures
from diski9.ingestion.fixtures import store_fixtures
from diski9.odds.collect import OddsPage, reconcile_pages
from diski9.screener import cache

from .factories import T0, fixture_item, full_book, odds_item, seed_competition

DAY = timedelta(days=1)
EPL_FIX, PSL_FIX, PROMOTED_FIX = 9001, 9002, 9003
EXTRA = list(range(9100, 9112))  # 12 extra upcoming EPL fixtures for pagination


def _text(component) -> str:
    if component is None:
        return ""
    if isinstance(component, str | int | float):
        return str(component)
    if isinstance(component, list | tuple):
        return " ".join(_text(c) for c in component)
    return _text(getattr(component, "children", None))


@pytest.fixture
def populated(engine):
    with engine.begin() as conn:
        seed_competition(conn, 39, years=(2025, 2026))
        seed_competition(conn, 288, years=(2025, 2026), name="Premier Soccer League")
        seed_competition(conn, 40, years=(2025, 2026), name="Championship")
        items, fid, t = [], 1, T0 - 200 * DAY

        def add(h, a, hg, ag, league=39, season=2026):
            nonlocal fid, t
            t += DAY
            items.append(
                fixture_item(fid, h, a, league=league, season=season, kickoff=t, ft=(hg, ag))
            )
            fid += 1

        for i in range(10):
            add(1, 100 + i, 3, 0)  # EPL team 1 strong at home (current season)
            add(110 + i, 2, 1, 1)  # EPL team 2 draws away
            add(10, 200 + i, 1, 1, league=288)  # PSL team 10
            add(210 + i, 11, 0, 2, league=288)  # PSL team 11 wins away
            add(300 + i, 5, 2, 2, league=40, season=2025)  # team 5: Championship last season
        add(120, 5, 0, 1)  # one top-flight away match this season for team 5 (promoted)
        items += [
            fixture_item(EPL_FIX, 1, 2, league=39, season=2026, kickoff=T0 + 3 * DAY, status="NS"),
            fixture_item(
                PSL_FIX, 10, 11, league=288, season=2026, kickoff=T0 + 4 * DAY, status="NS"
            ),
            fixture_item(
                PROMOTED_FIX, 1, 5, league=39, season=2026, kickoff=T0 + 30 * DAY, status="NS"
            ),
        ]
        items += [
            fixture_item(
                e,
                400 + i,
                500 + i,
                league=39,
                season=2026,
                kickoff=T0 + 5 * DAY + i * timedelta(hours=2),
                status="NS",
            )
            for i, e in enumerate(EXTRA)
        ]
        store_fixtures(conn, items, lambda: T0)
        books = {b: full_book(home=h) for b, h in ((8, "1.40"), (11, "1.45"), (4, "1.50"))}
        page = OddsPage(
            T0 - timedelta(hours=1),
            [odds_item(EPL_FIX, books, kickoff=T0 + 3 * DAY, update="2026-11-15T10:00:00+00:00")],
        )
        reconcile_pages(conn, 39, 2026, [page], clock=lambda: T0 - timedelta(hours=1))
        cache.refresh(conn, [EPL_FIX, PSL_FIX, PROMOTED_FIX, *EXTRA], T0, T0)
    return engine


@pytest.fixture
def data(populated):
    return ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)


def payload(
    data,
    market="1X2",
    leagues=(39, 288),
    start=None,
    end="2026-12-31",
    basis="venue",
    direction=None,
    threshold=0,
    page=1,
):
    return results_payload(
        data, market, list(leagues), start, end, basis, direction, threshold, page
    )


def page_ids(p) -> list[int]:
    table = p[0]
    if table is None:
        return []
    body = table.children[1].children
    return [row.id["index"] for row in body]


def _layout_json(data) -> str:
    return create_app(data).server.test_client().get("/_dash-layout").get_data(as_text=True)


# ------------------------------------------------------------------ startup
def test_app_starts_and_serves_layout(data):
    client = create_app(data).server.test_client()
    assert client.get("/").status_code == 200
    text = _layout_json(data)
    for cid in (
        "market",
        "leagues",
        "dates",
        "basis",
        "direction",
        "threshold",
        "results-table",
        "results-cards",
        "prev",
        "next",
        "detail",
    ):
        assert f'"{cid}"' in text
    assert "DataTable" not in text  # deprecated component removed


def test_kickoff_earliest_is_the_default(data):
    assert '"value":"kickoff_earliest"' in _layout_json(data)
    for market in ("1X2", "BTTS", "OU25"):
        assert DIRECTIONS[market][0][0] == "kickoff_earliest"
        assert DIRECTIONS[market][1][0] == "kickoff_latest"


# ------------------------------------------------------------------ ranking
def _kickoffs(data, ids):
    snap = data.snapshot()
    return [datetime.fromisoformat(snap.results["venue"][i]["fixture"]["kickoff"]) for i in ids]


def test_kickoff_ranking_uses_timestamps(data):
    all_ids = []
    for page in (1, 2):
        all_ids += page_ids(payload(data, page=page))
    ks = _kickoffs(data, all_ids)
    assert ks == sorted(ks)
    latest = page_ids(payload(data, direction="kickoff_latest"))
    assert _kickoffs(data, latest) == sorted(_kickoffs(data, latest), reverse=True)
    assert latest[0] == PROMOTED_FIX


def test_statistical_rankings_and_unavailable_last(data):
    rows = page_ids(payload(data, direction="home_stronger"))
    assert rows[0] == EPL_FIX or rows[0] == PROMOTED_FIX
    snap = data.snapshot()
    diffs = [snap.results["venue"][i]["match_result"]["form_difference"] for i in rows]
    known = [d for d in diffs if d is not None]
    assert known == sorted(known, reverse=True)
    assert diffs[len(known) :] == [None] * (len(diffs) - len(known))  # unavailable after ranked


def test_market_switch_falls_back_to_kickoff():
    assert valid_direction("BTTS", "home_stronger") == "kickoff_earliest"
    assert valid_direction("BTTS", "kickoff_latest") == "kickoff_latest"  # kept where valid
    assert valid_direction("OU25", "over") == "over"


def test_header_sort_toggles():
    assert header_sort("1X2", "kickoff", "kickoff_earliest") == "kickoff_latest"
    assert header_sort("1X2", "kickoff", "home_stronger") == "kickoff_earliest"
    assert header_sort("1X2", "stat", "kickoff_earliest") == "home_stronger"
    assert header_sort("1X2", "stat", "home_stronger") == "away_stronger"
    assert header_sort("BTTS", "stat", "btts_yes") == "btts_no"


# --------------------------------------------------------------- pagination
def test_ten_per_page_without_duplicates_or_gaps(data):
    first = payload(data)
    total = len(
        data.filtered(
            "1X2", [39, 288], None, datetime(2026, 12, 31).date(), "venue", "kickoff_earliest", None
        )
    )
    assert total == 15
    ids1, ids2 = page_ids(first), page_ids(payload(data, page=2))
    assert len(ids1) == PAGE_SIZE and len(ids2) == total - PAGE_SIZE
    assert not set(ids1) & set(ids2) and len(set(ids1) | set(ids2)) == total
    assert first[2] == "Showing 1–10 of 15 fixtures"
    assert first[5] == "Page 1 of 2" and first[6] is True and first[7] is False
    second = payload(data, page=2)
    assert second[2] == "Showing 11–15 of 15 fixtures" and second[7] is True
    assert payload(data, page=9)[8] == 2  # clamped to the last page


def test_paginate_pure():
    rows = [{"i": i} for i in range(23)]
    p = paginate(rows, 3)
    assert (p.page, p.pages, p.first, p.last, len(p.results)) == (3, 3, 21, 23, 3)
    assert paginate([], 1).summary == "" and paginate([], 1).pages == 1


def _results_callback(data):
    app = create_app(data)
    cb = next(v for k, v in app.callback_map.items() if "results-table.children" in k)
    return cb, cb["callback"].__wrapped__


def _trigger(prop_id: str, value=1):
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    context_value.set(AttributeDict(triggered_inputs=[{"prop_id": prop_id, "value": value}]))


def test_page_and_selection_transitions(data):
    """Clicks select by fixture id and keep the page; prev/next page; filters reset to page 1."""
    import diski9.app.app as appmod

    captured = {}

    def fake(data_, market, leagues, start, end, basis, direction, threshold, page, selected):
        captured.update(page=page, selected=selected)
        return (None,) * 11

    cb, func = _results_callback(data)
    inputs = [i["id"] if isinstance(i["id"], str) else json.dumps(i["id"]) for i in cb["inputs"]]
    assert (
        "prev" in inputs and any('"row"' in i for i in inputs) and any('"fx"' in i for i in inputs)
    )
    orig, appmod.results_payload = appmod.results_payload, fake
    try:
        args = ("1X2", [39], None, None, "venue", "kickoff_earliest", 0, 1, 1, [], [])
        for prop, page, expected_page in (
            ("next.n_clicks", 1, 2),
            ("prev.n_clicks", 2, 1),
            ("leagues.value", 3, 1),
            ("direction.value", 2, 1),
        ):
            _trigger(prop)
            func(*args, page, 77)
            assert captured == {"page": expected_page, "selected": 77}, prop
        _trigger(json.dumps({"index": 9001, "type": "row"}, separators=(",", ":")) + ".n_clicks")
        func(*args, 2, 77)
        assert captured == {"page": 2, "selected": 9001}  # page kept, selection follows the id
        _trigger(json.dumps({"index": 9002, "type": "fx"}, separators=(",", ":")) + ".n_clicks")
        func(*args, 2, 9001)
        assert captured == {"page": 2, "selected": 9002}  # mobile cards behave the same
        from dash.exceptions import PreventUpdate

        _trigger(json.dumps({"index": 9001, "type": "row"}, separators=(",", ":")) + ".n_clicks", 0)
        with pytest.raises(PreventUpdate):  # re-rendered rows (n_clicks 0) never select
            func(*args, 1, 9002)
    finally:
        appmod.results_payload = orig


def _selected_rows(p) -> list[int]:
    table = p[0]
    if table is None:
        return []
    return [row.id["index"] for row in table.children[1].children if "selected" in row.className]


def _selected_cards(p) -> list[int]:
    return [c.id["index"] for c in p[1] if "selected" in c.className]


def test_highlight_follows_selected_fixture_id(data):
    second_page = page_ids(payload(data, page=2))
    target = second_page[1]
    on_page_1 = results_payload(
        data, "1X2", [39, 288], None, "2026-12-31", "venue", None, 0, 1, target
    )
    assert (
        _selected_rows(on_page_1) == [] and _selected_cards(on_page_1) == []
    )  # not visible: no highlight
    assert on_page_1[10] == target  # but still selected
    on_page_2 = results_payload(
        data, "1X2", [39, 288], None, "2026-12-31", "venue", None, 0, 2, target
    )
    assert _selected_rows(on_page_2) == [target] and _selected_cards(on_page_2) == [target]
    # re-sorting keeps the selection; it is highlighted wherever it lands, never the first row by default
    latest = results_payload(
        data, "1X2", [39, 288], None, "2026-12-31", "venue", "kickoff_latest", 0, 1, target
    )
    assert latest[10] == target and _selected_rows(latest) in ([target], [])
    assert page_ids(latest)[0] not in _selected_rows(latest) or page_ids(latest)[0] == target


def test_selection_cleared_when_filtered_out(data):
    p = results_payload(data, "1X2", [288], None, "2026-12-31", "venue", None, 0, 1, EPL_FIX)
    assert p[10] is None and _selected_rows(p) == []
    kept = results_payload(data, "1X2", [39], None, "2026-12-31", "venue", None, 0, 1, EPL_FIX)
    assert kept[10] == EPL_FIX and _selected_rows(kept) == [EPL_FIX]


def test_form_basis_defaults_and_memory(data):
    from diski9.app.app import DEFAULT_BASIS

    assert DEFAULT_BASIS == {"1X2": "venue", "BTTS": "overall", "OU25": "overall"}
    app = create_app(data)
    apply_cb = next(v for k, v in app.callback_map.items() if k.startswith("basis.value"))[
        "callback"
    ].__wrapped__
    remember = next(v for k, v in app.callback_map.items() if k.startswith("basis-pref.data"))[
        "callback"
    ].__wrapped__
    assert apply_cb("1X2", {}) == "venue"
    assert apply_cb("BTTS", {}) == "overall" and apply_cb("OU25", None) == "overall"
    prefs = remember("venue", "BTTS", {})  # user explicitly picks venue for BTTS
    assert apply_cb("BTTS", prefs) == "venue" and apply_cb("OU25", prefs) == "overall"
    assert apply_cb("1X2", remember("overall", "1X2", prefs)) == "overall"
    assert '"value":"venue"' in _layout_json(data)  # initial Match result view


def test_league_and_date_filters(data):
    assert page_ids(payload(data, leagues=[288])) == [PSL_FIX]
    p = payload(data, leagues=[])
    assert p[0] is None and "Select at least one league" in _text(p[4])
    assert page_ids(payload(data, start="2026-11-18", end="2026-11-18")) == [EPL_FIX]
    empty = payload(data, start="2027-01-01", end="2027-01-31")
    assert empty[0] is None and "No fixtures match" in _text(empty[4]) and empty[2] == ""


def test_threshold_enabled_only_where_meaningful():
    for d in ("kickoff_earliest", "kickoff_latest", "evenly_matched"):
        c = threshold_config("1X2", d)
        assert c["disabled"] is True and c["hint"] == "Available for strongest home/away rankings"
    for d in ("home_stronger", "away_stronger"):
        assert threshold_config("1X2", d)["disabled"] is False
    assert threshold_config("1X2", "home_stronger")["label"] == "Minimum form difference"
    assert threshold_config("BTTS", "btts_no")["label"] == "Minimum recent no-BTTS occurrence"
    assert threshold_config("OU25", "over")["label"] == "Minimum recent Over 2.5 occurrence"
    assert threshold_config("OU25", "kickoff_latest")["hint"] == (
        "Available for recent-occurrence rankings"
    )
    assert threshold_config("BTTS", "kickoff_earliest")["disabled"] is True


def test_disabled_threshold_has_no_effect(data):
    for d in ("kickoff_earliest", "kickoff_latest", "evenly_matched"):
        assert page_ids(payload(data, direction=d, threshold=4.5)) == page_ids(
            payload(data, direction=d, threshold=0)
        )
    assert page_ids(payload(data, direction="home_stronger", threshold=4.5)) != page_ids(
        payload(data, direction="home_stronger", threshold=0)
    )


def test_threshold_filters(data):
    ids = page_ids(payload(data, direction="home_stronger", threshold=1))
    snap = data.snapshot()
    assert ids and all(
        snap.results["venue"][i]["match_result"]["form_difference"] >= 1 for i in ids
    )


# ---------------------------------------------------------- table & cards
def test_columns_alignment_and_names():
    cols = {c["id"]: c for c in columns_for("1X2")}
    assert cols["indicator"]["label"] == "Form difference" and cols["indicator"]["align"] == "right"
    assert cols["home"]["align"] == "left" and cols["odds"]["align"] == "right"
    assert "venue" not in json.dumps(columns_for("1X2")).lower()
    goals = [c["label"] for c in columns_for("OU25")]
    assert goals[4:] == [
        "Home record",
        "Away record",
        "Recent Over 2.5",
        "League",
        "Market Over · Under",
        "Data",
    ]
    assert "Under 2.5" not in goals  # the historical complement is no longer a headline column
    assert "not a probability" in columns_for("BTTS")[6]["title"]


def test_rows_use_readable_dates_and_signed_differences(data):
    p = payload(data)
    first_row = p[0].children[1].children[0]
    kickoff = first_row.children[0].children
    assert kickoff == "Wed 18 Nov, 14:00"  # 12:00 UTC shown in SAST
    diff_cell = first_row.children[6]
    assert diff_cell.children.startswith("+") and "pos" in diff_cell.className


def test_mobile_cards_match_page(data):
    p = payload(data)
    cards = p[1]
    assert len(cards) == PAGE_SIZE and all(isinstance(c, html.Button) for c in cards)
    assert [c.id["index"] for c in cards] == page_ids(p)
    css = (Path(__file__).parents[1] / "src/diski9/app/assets/style.css").read_text()
    mobile = css[css.index("@media (max-width: 720px)") :]
    assert ".table-wrap { display: none; }" in mobile and ".cards { display: block; }" in mobile


# ------------------------------------------------------------ detail / odds
def test_detail_levels_and_form_breakdown(data):
    r, ov, official = data.detail(EPL_FIX, "venue")
    d = render_detail(r, ov, official, "1X2", data)
    text = _text(d)
    for phrase in (
        "Diski 9 Match Analysis",
        "Bookmaker Market Reference",
        "Diski Form Score",
        "How it's calculated",
        "Points earned",
        "Points part = 2.5 × points ÷ 15",
        "Goal-difference part = 2.5 × (GD + 9) ÷ 18",
        "No bonuses are added",
        "Matches used",
        "Head-to-head",
        "League positions",
        "Consensus reference odds",
        "not predicted probabilities",
    ):
        assert phrase in text, phrase
    # the redundant Form Difference headline is gone from the detail (kept in the table)
    assert not _find(d, lambda c: "headline" in str(getattr(c, "className", "")))
    assert "do not mean a draw is likely" not in text
    assert "Venue-adjusted" not in text and "benchmark" not in text.lower()
    assert "Raw total" not in text and "bonus" not in text.replace("No bonuses", "").lower()
    # secondary sections start collapsed
    sections = [c for c in d.children[3].children]
    assert all(getattr(s, "open", False) is False for s in sections)
    lowered = text.lower()
    for banned in ("expected value", "value bet", "betting edge", "stake "):
        assert banned not in lowered


def test_tooltips_present_and_contextual():
    assert "five" in _text(basis_help("1X2")) and "ten" in _text(basis_help("BTTS"))
    assert "current-season" in _text(basis_help("OU25"))


def test_fresh_and_stale_odds_in_detail(populated):
    fresh = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    r, ov, official = fresh.detail(EPL_FIX, "venue")
    text = _text(render_detail(r, ov, official, "1X2", fresh))
    assert "Fresh" in text and "1.45" in text and "Market-implied" in text
    stale = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0 + 2 * DAY)
    r, ov, official = stale.detail(EPL_FIX, "venue")
    text = _text(render_detail(r, ov, official, "1X2", stale))
    assert "Stale" in text and "may have changed" in text and "1.45" in text
    from diski9.api_football.markets import Market

    assert ov.markets[Market.MATCH_RESULT].status == "stale"
    assert not ov.markets[Market.MATCH_RESULT].challenge_eligible
    row = stale.row("1X2", r)
    assert row["odds_status"] == "stale"


def test_market_implied_probabilities(data):
    from diski9.api_football.markets import Market, Outcome

    r, ov, official = data.detail(EPL_FIX, "venue")
    ip = ov.markets[Market.MATCH_RESULT].implied
    assert sum(ip.margin_adjusted.values()) == pytest.approx(Decimal(1))
    assert ip.raw[Outcome.HOME] == Decimal(1) / Decimal("1.45")


def test_missing_odds_psl(data):
    rows = payload(data, leagues=[288])
    assert page_ids(rows) == [PSL_FIX]
    r, ov, official = data.detail(PSL_FIX, "venue")
    assert data.row("BTTS", r)["odds"] == "No odds"
    text = _text(render_detail(r, ov, official, "BTTS", data))
    assert "No bookmaker odds are available for the PSL" in text


def test_limited_data_warnings(data):
    r, ov, official = data.detail(PROMOTED_FIX, "venue")
    text = _text(render_detail(r, ov, official, "1X2", data))
    assert "Limited data" in text
    assert data.row("1X2", r)["limited"] is True


def test_detail_prompt_when_nothing_selected(data):
    assert "Select a fixture" in _text(render_detail(None, None, {}, "1X2", data))


# ------------------------------------------------------------ cache / API
def test_stale_banner_until_cache_refreshed(populated):
    from diski9.app.app import build_layout

    data = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    assert "New results" not in _text(build_layout(data))
    later = T0 + timedelta(hours=2)
    with populated.begin() as conn:
        store_fixtures(
            conn,
            [fixture_item(7777, 1, 150, kickoff=T0 - timedelta(hours=3), ft=(0, 1), season=2026)],
            lambda: later,
        )
    assert "New results" in _text(build_layout(data))
    with populated.begin() as conn:
        counts = cache.refresh(conn, [EPL_FIX, PSL_FIX, PROMOTED_FIX, *EXTRA], later, later)
    assert counts["superseded"] >= 1  # results using the new match were recalculated
    assert "New results" not in _text(build_layout(data))


def test_snapshot_ttl_caches_in_memory(populated):
    data = ScreenerData(populated, ttl_seconds=300, clock=lambda: T0)
    first = data.snapshot()
    with populated.begin() as conn:
        conn.execute(update(fixtures).where(fixtures.c.id == EPL_FIX).values(status_short="NS"))
    assert data.snapshot() is first and data.snapshot(force=True) is not first


def test_ui_interactions_never_call_api(data, monkeypatch):
    import diski9.api_football.client as client_mod

    def boom(*a, **k):
        raise AssertionError("API call attempted")

    monkeypatch.setattr(client_mod.ApiFootballClient, "get", boom)
    client = create_app(data).server.test_client()
    assert client.get("/_dash-layout").status_code == 200
    for market in ("1X2", "BTTS", "OU25"):
        for direction in [d for d, _ in DIRECTIONS[market]]:
            for page in (1, 2):
                payload(data, market, direction=direction, page=page)
        r, ov, off = data.detail(EPL_FIX, "overall")
        render_detail(r, ov, off, market, data)


def test_fixture_card_shows_stale_and_limited():
    row = {
        "id": 1,
        "kickoff": "Sat 21 Nov, 14:30",
        "league": "EPL",
        "home": "A",
        "away": "B",
        "home_metric": "3.00",
        "away_metric": "1.00",
        "indicator": 2.0,
        "indicator_display": "+2.00",
        "complement_display": None,
        "odds": "1.40 · 5.00 · 7.04",
        "odds_status": "stale",
        "limited": True,
    }
    text = _text(fixture_card("1X2", row, None))
    assert "stale odds" in text and "Limited data" in text and "+2.00" in text


# ------------------------------------------------------------ browser (phone)
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_phone_viewport_cards_tooltip_and_pager(data):
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode != 0:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    port = _free_port()
    server = make_server("127.0.0.1", port, create_app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        script = f"""
        const {{ chromium, devices }} = require('playwright');
        (async () => {{
          const b = await chromium.launch();
          const ctx = await b.newContext({{ ...devices['iPhone 13'] }});
          const p = await ctx.newPage();
          await p.goto('http://127.0.0.1:{port}/');
          await p.waitForSelector('.fx-card', {{ timeout: 20000 }});
          const out = {{}};
          out.cards = await p.locator('.fx-card').count();
          out.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          out.tableVisible = await p.isVisible('.table-wrap');
          await p.locator('#basis-label details.info > summary').tap();
          out.tooltip = await p.isVisible('#basis-label .info-pop');
          await p.locator('#basis-label details.info > summary').tap();
          await p.locator('#next').tap();
          await p.waitForFunction(() => document.querySelector('#summary').innerText.startsWith('Showing 11'));
          out.page2 = await p.locator('.fx-card').count();
          await p.locator('.fx-card').first().tap();
          await p.waitForSelector('.detail-header', {{ timeout: 20000 }});
          out.after = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          console.log(JSON.stringify(out));
          await b.close();
        }})().catch(e => {{ console.error(e); process.exit(1); }});
        """
        time.sleep(0.5)
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=120)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out == {
            "cards": 10,
            "overflow": 0,
            "tableVisible": False,
            "tooltip": True,
            "page2": 4,
            "after": 0,
        }
        # default range is today + 14 days, so the fixture 30 days out is not listed (14 fixtures)
    finally:
        server.shutdown()


# ------------------------------------------------------------- Milestone 5.1
def _find(component, pred):
    out = []
    if pred(component):
        out.append(component)
    children = getattr(component, "children", None)
    for c in (
        children
        if isinstance(children, list | tuple)
        else ([children] if children is not None else [])
    ):
        if not isinstance(c, str | int | float):
            out += _find(c, pred)
    return out


def test_market_card_selected_market_only_with_sources_and_margin(data):
    from dash import html as h

    r, ov, official = data.detail(EPL_FIX, "venue")
    for market, own, others, margin in (
        ("1X2", "1.45", ("1.80", "1.90"), "24.7%"),  # 1/1.45 + 1/3.40 + 1/3.80 - 1
        ("BTTS", "1.80", ("1.45", "1.90"), "5.6%"),  # 1/1.80 + 1/2.00 - 1
    ):
        card = render_detail(r, ov, official, market, data).children[2]
        text = _text(card)
        assert own in text and not any(o in text for o in others)  # this market only
        assert "3 independent bookmaker groups" in text
        assert f"combined margin removed {margin}" in text
        assert "proportionally adjusting the probabilities to total 100%" in text
        assert "raw " in text  # raw implied kept distinct from market-implied
        assert not _find(card, lambda c: isinstance(c, h.Details) and c.className == "acc")
        assert "Odds details" not in text and "other markets" not in text.lower()


def test_paired_outcomes_equal_typography(data):
    for market in ("BTTS", "OU25"):
        r, ov, official = data.detail(EPL_FIX, "overall")
        d = render_detail(r, ov, official, market, data)
        values = _find(d, lambda c: getattr(c, "className", "") == "pair-value")
        assert len(values) == 2  # both outcomes share exactly the same class
        # no percentage is rendered in the larger headline style
        assert not _find(
            d,
            lambda c: getattr(c, "className", "") in ("headline", "headline-2") and "%" in _text(c),
        )


def test_market_implied_probabilities_in_1x2_summary(populated):
    from diski9.api_football.markets import Market

    for clock, status in ((T0, "Fresh"), (T0 + 2 * DAY, "Stale")):
        d = ScreenerData(populated, ttl_seconds=0, clock=lambda c=clock: c)
        r, ov, official = d.detail(EPL_FIX, "venue")
        card = render_detail(r, ov, official, "1X2", d).children[2]
        text = _text(card)
        assert text.startswith("Bookmaker Market Reference")
        assert "not Diski 9 predictions" in text
        assert "Market-implied probabilities" in text and status in text
        ip = ov.markets[Market.MATCH_RESULT].implied
        for o in ip.margin_adjusted:
            assert (
                f"{float(ip.margin_adjusted[o]) * 100:.1f}%" in text
            )  # same values as the full table
        total = sum(float(v) for v in ip.margin_adjusted.values()) * 100
        assert abs(total - 100) < 1e-6
        for banned in ("prediction:", "win prediction", "model probabilit", "confidence"):
            assert banned not in text.lower()
    d = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    r, ov, official = d.detail(PSL_FIX, "venue")
    card = render_detail(r, ov, official, "1X2", d).children[2]
    text = _text(card)
    assert "market-implied probabilities are unavailable" in text
    assert "%" not in text and "compact" in card.className  # nothing invented, small card


def test_compact_limited_marker_in_table(data):
    p = payload(data, end="2026-12-31", page=2)
    cells = _find(p[0], lambda c: getattr(c, "className", "") == "pill warn subtle")
    assert cells and all(_text(c) == "Limited" and "fewer than" in c.title for c in cells)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_selection_highlight(data):
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode != 0:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    port = _free_port()
    server = make_server("127.0.0.1", port, create_app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        script = f"""
        const {{ chromium }} = require('playwright');
        const sel = (p) => p.evaluate(() => [...document.querySelectorAll('tr.row.selected')].map(r => JSON.parse(r.id).index));
        const ids = (p) => p.evaluate(() => [...document.querySelectorAll('tr.row')].map(r => JSON.parse(r.id).index));
        (async () => {{
          const b = await chromium.launch();
          const p = await b.newPage({{ viewport: {{ width: 1400, height: 1000 }} }});
          await p.goto('http://127.0.0.1:{port}/');
          await p.waitForSelector('tr.row', {{ timeout: 20000 }});
          const out = {{}};
          const rows = await ids(p);
          out.initial = await sel(p);
          await p.locator('tr.row').nth(2).click();
          await p.waitForFunction(() => document.querySelectorAll('tr.row.selected').length === 1);
          out.afterThird = await sel(p); out.third = rows[2];
          await p.waitForSelector('.detail-header h2');
          const thirdTitle = await p.locator('.detail-header h2').innerText();
          await p.locator('tr.row').nth(4).click();
          await p.waitForFunction((id) => document.querySelector('tr.row.selected') && JSON.parse(document.querySelector('tr.row.selected').id).index === id, rows[4]);
          out.afterFifth = await sel(p); out.fifth = rows[4];
          await p.waitForFunction((t) => document.querySelector('.detail-header h2').innerText !== t, thirdTitle);
          out.detail = await p.locator('.detail-header h2').innerText();
          await p.locator('#next').click();
          await p.waitForFunction(() => document.querySelector('#summary').innerText.startsWith('Showing 11'));
          out.page2 = await sel(p);
          await p.locator('#prev').click();
          await p.waitForFunction(() => document.querySelector('#summary').innerText.startsWith('Showing 1–'));
          out.backToPage1 = await sel(p);
          console.log(JSON.stringify(out));
          await b.close();
        }})().catch(e => {{ console.error(e); process.exit(1); }});
        """
        time.sleep(0.5)
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=120)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out["initial"] == []
        assert out["afterThird"] == [out["third"]]
        assert out["afterFifth"] == [out["fifth"]]  # highlight moved; previous row cleared
        assert out["page2"] == []  # selection off-page: nothing unrelated highlighted
        assert out["backToPage1"] == [out["fifth"]]
        snap = data.snapshot().results["venue"][out["fifth"]]["fixture"]
        assert out["detail"] == f"{snap['home']} v {snap['away']}"
    finally:
        server.shutdown()
