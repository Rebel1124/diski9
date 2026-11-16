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


def test_page_resets_on_filter_change(data):
    """The results callback resets to page 1 for any trigger other than prev/next."""
    import diski9.app.app as appmod

    captured = {}

    def fake(data_, market, leagues, start, end, basis, direction, threshold, page, selected):
        captured["page"] = page
        return (None,) * 10

    app = create_app(data)
    cb = next(v for k, v in app.callback_map.items() if "results-table.children" in k)
    assert "prev.n_clicks" in [i["id"] + "." + i["property"] for i in cb["inputs"]]
    orig = appmod.results_payload
    appmod.results_payload = fake
    try:
        func = cb["callback"].__wrapped__
        from dash._callback_context import context_value
        from dash._utils import AttributeDict

        for trig, start, expected in (
            ("next", 1, 2),
            ("prev", 2, 1),
            ("leagues", 3, 1),
            ("direction", 2, 1),
        ):
            context_value.set(
                AttributeDict(triggered_inputs=[{"prop_id": f"{trig}.value", "value": 1}])
            )
            func("1X2", [39], None, None, "venue", "kickoff_earliest", 0, 1, 1, start, None)
            assert captured["page"] == expected, trig
    finally:
        appmod.results_payload = orig


# ------------------------------------------------------------------ filters
def test_league_and_date_filters(data):
    assert page_ids(payload(data, leagues=[288])) == [PSL_FIX]
    p = payload(data, leagues=[])
    assert p[0] is None and "Select at least one league" in _text(p[4])
    assert page_ids(payload(data, start="2026-11-18", end="2026-11-18")) == [EPL_FIX]
    empty = payload(data, start="2027-01-01", end="2027-01-31")
    assert empty[0] is None and "No fixtures match" in _text(empty[4]) and empty[2] == ""


def test_threshold_only_for_statistical_rankings():
    assert threshold_config("1X2", "kickoff_earliest")["disabled"] is True
    assert threshold_config("1X2", "home_stronger")["label"] == "Minimum form difference"
    assert threshold_config("1X2", "evenly_matched")["max"] == 5
    assert threshold_config("BTTS", "btts_no")["label"] == "Minimum BTTS No indicator"


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
    assert columns_for("OU25")[7]["label"] == "Under 2.5"


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
        "Form Difference",
        "Diski Form Score",
        "How it's calculated",
        "How is Form Score calculated?",
        "Points earned",
        "Raw total (max 6.5)",
        "Matches used",
        "Head-to-head",
        "League positions",
        "Reference odds",
        "do not mean a draw is likely",
        "not predicted probabilities",
    ):
        assert phrase in text, phrase
    assert "Venue-adjusted" not in text and "benchmark" not in text.lower()
    # Level 3 sections start collapsed
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
    assert "does not currently provide bookmaker odds for the PSL" in text


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
