"""Dash application tests: startup, filters, ranking, detail rendering, odds, cache."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from dash import html
from sqlalchemy import update

from diski9.app import ScreenerData, create_app
from diski9.app.app import (
    columns_for,
    selected_fixture,
    table_payload,
    threshold_config,
)
from diski9.app.data import DIRECTIONS
from diski9.app.views import render_detail
from diski9.db.schema import fixtures
from diski9.ingestion.fixtures import store_fixtures
from diski9.odds.collect import OddsPage, reconcile_pages
from diski9.screener import cache

from .factories import T0, fixture_item, full_book, odds_item, seed_competition

DAY = timedelta(days=1)
EPL_FIX, PSL_FIX, PROMOTED_FIX = 9001, 9002, 9003


def _text(component) -> str:
    """Flatten a Dash component tree into its text."""
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

        def add(h, a, hg, ag, league=39, season=2025):
            nonlocal fid, t
            t += DAY
            items.append(
                fixture_item(fid, h, a, league=league, season=season, kickoff=t, ft=(hg, ag))
            )
            fid += 1

        for i in range(10):
            add(1, 100 + i, 3, 0)  # EPL team 1 strong at home
            add(110 + i, 2, 1, 1)  # EPL team 2 draws away
            add(10, 200 + i, 1, 1, league=288)  # PSL team 10
            add(210 + i, 11, 0, 2, league=288)  # PSL team 11 wins away
            add(300 + i, 5, 2, 2, league=40)  # team 5: Championship last season (promoted)
        add(120, 5, 0, 1, season=2026)  # one top-flight away match this season for team 5
        items += [
            fixture_item(EPL_FIX, 1, 2, league=39, season=2026, kickoff=T0 + 3 * DAY, status="NS"),
            fixture_item(
                PSL_FIX, 10, 11, league=288, season=2026, kickoff=T0 + 4 * DAY, status="NS"
            ),
            fixture_item(
                PROMOTED_FIX, 1, 5, league=39, season=2026, kickoff=T0 + 30 * DAY, status="NS"
            ),
        ]
        store_fixtures(conn, items, lambda: T0)
        books = {b: full_book(home=h) for b, h in ((8, "1.40"), (11, "1.45"), (4, "1.50"))}
        page = OddsPage(
            T0 - timedelta(hours=1),
            [odds_item(EPL_FIX, books, kickoff=T0 + 3 * DAY, update="2026-11-15T10:00:00+00:00")],
        )
        reconcile_pages(conn, 39, 2026, [page], clock=lambda: T0 - timedelta(hours=1))
        cache.refresh(conn, [EPL_FIX, PSL_FIX, PROMOTED_FIX], T0, T0)
    return engine


@pytest.fixture
def data(populated):
    return ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)


def payload(
    data,
    market="1X2",
    leagues=(39, 288),
    start=None,
    end=None,
    basis="venue",
    direction=None,
    threshold=0,
):
    direction = direction or DIRECTIONS[market][0][0]
    return table_payload(data, market, list(leagues), start, end, basis, direction, threshold)


# ------------------------------------------------------------------ startup
def test_app_starts_and_serves_layout(data):
    app = create_app(data)
    client = app.server.test_client()
    assert client.get("/").status_code == 200
    layout = client.get("/_dash-layout")
    assert layout.status_code == 200
    body = json.loads(layout.data)
    text = json.dumps(body)
    for component_id in (
        "market",
        "leagues",
        "dates",
        "basis",
        "direction",
        "threshold",
        "table",
        "detail",
    ):
        assert f'"{component_id}"' in text
    assert "Statistical Screener" in text


def _layout_json(data) -> str:
    return create_app(data).server.test_client().get("/_dash-layout").get_data(as_text=True)


def test_layout_defaults(data):
    text = _layout_json(data)
    assert '"value":"1X2"' in text and '"value":"venue"' in text
    assert "2026-11-15" in text and "2026-11-29" in text  # 14-day default range


# ---------------------------------------------------------- market switching
def test_market_switch_changes_columns_and_directions():
    assert [c["id"] for c in columns_for("1X2", "venue")][6] == "indicator"
    assert columns_for("1X2", "venue")[6]["name"] == "Venue-adj. difference"
    assert columns_for("1X2", "overall")[6]["name"] == "Raw difference"
    assert columns_for("BTTS", "venue")[6]["name"] == "BTTS Yes"
    assert columns_for("OU25", "venue")[7]["name"] == "Under 2.5"
    assert [d for d, _ in DIRECTIONS["BTTS"]] == ["btts_yes", "btts_no"]
    assert threshold_config("1X2", "evenly_matched")["label"] == "Maximum difference"
    assert threshold_config("BTTS", "btts_no")["label"] == "Minimum BTTS No indicator"


def test_each_market_returns_rows(data):
    for market in ("1X2", "BTTS", "OU25"):
        rows, cols, *_ = payload(data, market)
        assert len(rows) == 3 and {c["id"] for c in cols} >= set(rows[0]) - {"id"}


# ------------------------------------------------------------------ filters
def test_league_filter(data):
    rows, *_ = payload(data, leagues=[288])
    assert [r["id"] for r in rows] == [PSL_FIX]
    rows, _, _, _, count, empty, cards = payload(data, leagues=[])
    assert rows == [] and "Select at least one league" in _text(empty) and cards == []


def test_date_filter_and_empty_state(data):
    rows, *_ = payload(data, start="2026-11-18", end="2026-11-18")
    assert [r["id"] for r in rows] == [EPL_FIX]
    rows, _, _, _, count, empty, _ = payload(data, start="2027-01-01", end="2027-01-31")
    assert rows == [] and "No fixtures match" in _text(empty) and count == ""


def test_threshold_filter(data):
    rows, *_ = payload(data, threshold=3)
    assert all(r["indicator"] >= 3 for r in rows)


# --------------------------------------------------------- sorting / ranking
def test_ranking_directions(data):
    home = [r["indicator"] for r in payload(data, direction="home_stronger")[0]]
    away = [r["indicator"] for r in payload(data, direction="away_stronger")[0]]
    assert home == sorted(home, reverse=True) and away == sorted(away)
    assert home[0] == away[-1] and len(home) == len(away) == 3
    rows = payload(data, direction="evenly_matched")[0]
    assert [abs(r["indicator"]) for r in rows] == sorted(abs(r["indicator"]) for r in rows)
    yes = [r["indicator"] for r in payload(data, "BTTS", direction="btts_yes")[0]]
    assert yes == sorted(yes, reverse=True)
    under = [r["indicator"] for r in payload(data, "OU25", direction="under")[0]]
    assert under == sorted(under)


def test_table_is_natively_sortable(data):
    assert '"sort_action":"native"' in _layout_json(data)


def test_selected_fixture_from_active_cell():
    rows = [{"id": 5}, {"id": 7}]
    assert selected_fixture({"row": 1, "column": 0}, rows) == 7
    assert selected_fixture({"row": 0, "row_id": 7}, rows) == 7


# ------------------------------------------------------------ detail / odds
def test_epl_detail_renders_indicators_and_odds(data):
    r, ov, official = data.detail(EPL_FIX, "venue")
    text = _text(render_detail(r, ov, official, "1X2", data))
    for phrase in (
        "Form Score",
        "Venue-adjusted difference",
        "League home benchmark",
        "Matches used",
        "Consensus reference odds — not an offer from any bookmaker",
        "Market-implied",
        "Head-to-head",
        "League positions",
        "not predicted probabilities",
        "Calculated from Diski 9's eligible results (not the official table)",
        "provisional",
        "Provider feed update",
        "Prices last verified",
    ):
        assert phrase in text, phrase
    assert "1.45" in text  # median of 1.40 / 1.45 / 1.50
    lowered = text.lower()
    for banned in ("expected value", "value bet", "betting edge", "stake"):
        assert banned not in lowered
    # BTTS and O/U sections still reachable from the 1X2 view
    assert "Both teams to score" in text and "Over/Under 2.5 goals" in text


def test_market_implied_probabilities_shown_when_complete(data):
    r, ov, official = data.detail(EPL_FIX, "venue")
    from diski9.api_football.markets import Market, Outcome

    ip = ov.implied[Market.MATCH_RESULT]
    assert ip.margin_adjusted is not None
    assert sum(ip.margin_adjusted.values()) == pytest.approx(Decimal(1))
    assert ip.raw[Outcome.HOME] == Decimal(1) / Decimal("1.45")


def test_missing_odds_psl(data):
    rows, *_ = payload(data, leagues=[288])
    assert rows[0]["odds"] == "No odds"
    r, ov, official = data.detail(PSL_FIX, "venue")
    text = _text(render_detail(r, ov, official, "BTTS", data))
    assert "provides no bookmaker odds for the PSL" in text
    assert "BTTS" in text and "Combined BTTS Yes" in text


def test_official_standings_preferred_when_available(populated, data):
    from diski9.ingestion.reference import store_standings

    def row(team_id, rank):
        return {
            "rank": rank,
            "team": {"id": team_id, "name": f"Team {team_id}"},
            "points": 30 - rank,
            "goalsDiff": 3,
            "all": {
                "played": 10,
                "win": 9,
                "draw": 0,
                "lose": 1,
                "goals": {"for": 9, "against": 6},
            },
            "update": "2026-11-11T00:00:00+00:00",
        }

    with populated.begin() as conn:
        store_standings(conn, 39, 2026, [{"league": {"standings": [[row(1, 1), row(2, 2)]]}}], T0)
    data.snapshot(force=True)
    r, ov, official = data.detail(EPL_FIX, "venue")
    text = _text(render_detail(r, ov, official, "1X2", data))
    assert "Official standings from API-Football, updated 11 Nov 2026" in text


def test_detail_prompt_when_nothing_selected(data):
    assert "Select a fixture" in _text(render_detail(None, None, {}, "1X2", data))


# ------------------------------------------------------------ limited data
def test_limited_data_warning_for_promoted_team(data):
    rows, *_ = payload(data, end="2026-12-31")
    promoted = next(r for r in rows if r["id"] == PROMOTED_FIX)
    assert promoted["limited"] == "⚠ Limited data"
    r, ov, official = data.detail(PROMOTED_FIX, "venue")
    text = _text(render_detail(r, ov, official, "1X2", data))
    assert "Limited data: fewer than 3 current division matches" in text
    assert "previous-division/other-competition" in text


# ------------------------------------------------------------ cache refresh
def test_stale_banner_until_cache_refreshed(populated):
    from diski9.app.app import build_layout

    data = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    assert "New fixture results" not in _text(build_layout(data))
    later = T0 + timedelta(hours=2)
    with populated.begin() as conn:
        store_fixtures(
            conn,
            [fixture_item(7777, 1, 150, kickoff=T0 - timedelta(hours=3), ft=(0, 1), season=2026)],
            lambda: later,
        )
    assert "New fixture results" in _text(build_layout(data))
    with populated.begin() as conn:
        counts = cache.refresh(conn, [EPL_FIX, PSL_FIX, PROMOTED_FIX], later, later)
    assert counts["superseded"] >= 1  # team 1's home form changed
    assert "New fixture results" not in _text(build_layout(data))


def test_snapshot_ttl_caches_in_memory(populated):
    data = ScreenerData(populated, ttl_seconds=300, clock=lambda: T0)
    first = data.snapshot()
    with populated.begin() as conn:
        conn.execute(update(fixtures).where(fixtures.c.id == EPL_FIX).values(status_short="NS"))
    assert data.snapshot() is first
    assert data.snapshot(force=True) is not first


def test_app_never_calls_api(data, monkeypatch):
    import diski9.api_football.client as client_mod

    def boom(*a, **k):
        raise AssertionError("API call attempted")

    monkeypatch.setattr(client_mod.ApiFootballClient, "get", boom)
    app = create_app(data)
    client = app.server.test_client()
    assert client.get("/_dash-layout").status_code == 200
    for market in ("1X2", "BTTS", "OU25"):
        payload(data, market)
        r, ov, off = data.detail(EPL_FIX, "venue")
        render_detail(r, ov, off, market, data)


# ------------------------------------------------------------ mobile layout
def test_mobile_cards_and_css(data):
    _, _, _, _, _, _, cards = payload(data)
    assert len(cards) == 3 and all(isinstance(c, html.Button) for c in cards)
    assert cards[0].id["type"] == "fx"
    assert any("No odds" in _text(c) for c in cards)
    css = (Path(__file__).parents[1] / "src/diski9/app/assets/style.css").read_text()
    assert "@media (max-width: 720px)" in css
    mobile = css[css.index("@media (max-width: 720px)") :]
    assert ".table-wrap { display: none; }" in mobile and ".cards { display: block; }" in mobile


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_phone_viewport_has_no_horizontal_scroll(data):
    probe = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    app = create_app(data)
    port = _free_port()
    server = make_server("127.0.0.1", port, app.server, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = f"""
        const {{ chromium, devices }} = require('playwright');
        (async () => {{
          const b = await chromium.launch();
          const ctx = await b.newContext({{ ...devices['iPhone 13'] }});
          const p = await ctx.newPage();
          await p.goto('http://127.0.0.1:{port}/');
          await p.waitForSelector('.fx-card', {{ timeout: 20000 }});
          const before = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          const tableVisible = await p.isVisible('.table-wrap');
          await p.locator('.fx-card').first().click();
          await p.waitForSelector('.detail-header', {{ timeout: 20000 }});
          const after = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          console.log(JSON.stringify({{ before, after, tableVisible }}));
          await b.close();
        }})().catch(e => {{ console.error(e); process.exit(1); }});
        """
        time.sleep(0.5)
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=90)
        assert out.returncode == 0, out.stderr
        result = json.loads(out.stdout.strip().splitlines()[-1])
        assert result == {"before": 0, "after": 0, "tableVisible": False}
    finally:
        server.shutdown()
