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
from diski9.app.views import render_detail
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
        # Previous-season league results between other clubs: Goal Model 1.0's
        # league-average prior (league level only; never a team's own statistics)
        for i in range(20):
            add(600 + i % 10, 650 + i % 10, (2, 1, 0, 3)[i % 4], (1, 1, 2, 0)[i % 4], season=2025)
            add(
                700 + i % 10,
                750 + i % 10,
                (1, 0, 2, 1)[i % 4],
                (0, 0, 1, 1)[i % 4],
                league=288,
                season=2025,
            )
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


def give_history(engine, fixtures=None) -> None:
    """Goal Model 1.1 (Phase 8 CP2A) needs >= 2 current-season matches per team. Give
    the teams of the given EXTRA fixtures two earlier meetings (varied scores) and
    refresh their cache rows, so tests that rank many *modelled* fixtures keep doing
    so (under Goal Model 1.0 these teams were modelled through the league prior)."""
    from diski9.screener import cache

    history = []
    for i, fid in enumerate(EXTRA):
        if fixtures is not None and fid not in fixtures:
            continue
        h, a = 400 + i, 500 + i
        for j, (hg, ag) in enumerate(((i % 4, 1), ((i + 1) % 3, (i + 2) % 4))):
            history.append(
                fixture_item(80_000 + 2 * i + j, h if j == 0 else a, a if j == 0 else h,
                             league=39, season=2026,
                             kickoff=T0 - (60 - 2 * i - j) * DAY, ft=(hg, ag))
            )  # fmt: skip
    with engine.begin() as conn:
        store_fixtures(conn, history, lambda: T0)
        cache.refresh(conn, [EPL_FIX, PSL_FIX, PROMOTED_FIX, *EXTRA], T0, T0)


@pytest.fixture
def data(populated):
    return ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)


def payload(
    data,
    market="1X2",
    leagues=(39, 288),
    start=None,
    end="2026-12-31",
    basis="overall",
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
        "direction",
        "threshold",
        "results-table",
        "results-cards",
        "prev",
        "next",
        "detail",
        "lab-store",
        "methodology",
    ):
        assert f'"{cid}"' in text
    assert '"basis"' not in text  # Engine 3.0: no Venue/Overall selector
    assert "DataTable" not in text  # deprecated component removed
    assert "How Diski 9 Calculates Probabilities" in text


def test_kickoff_earliest_is_the_default(data):
    assert '"value":"kickoff_earliest"' in _layout_json(data)
    for market in ("1X2", "BTTS", "OU25"):
        assert DIRECTIONS[market][0][0] == "kickoff_earliest"
        assert DIRECTIONS[market][1][0] == "kickoff_latest"


# ------------------------------------------------------------------ ranking
def _kickoffs(data, ids):
    snap = data.snapshot()
    return [datetime.fromisoformat(snap.results["overall"][i]["fixture"]["kickoff"]) for i in ids]


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
    rows = page_ids(payload(data, direction="home_win"))
    snap = data.snapshot()
    probs = [
        (snap.results["overall"][i]["goal_model"].get("probabilities") or {}).get("home")
        for i in rows
    ]
    known = [p for p in probs if p is not None]
    assert known and known == sorted(known, reverse=True)
    assert probs[len(known) :] == [None] * (len(probs) - len(known))  # unavailable after ranked


def test_market_switch_falls_back_to_kickoff():
    assert valid_direction("BTTS", "home_win") == "kickoff_earliest"
    assert valid_direction("BTTS", "kickoff_latest") == "kickoff_latest"  # kept where valid
    assert valid_direction("OU25", "over") == "over"


def test_header_sort_toggles():
    assert header_sort("1X2", "kickoff", "kickoff_earliest") == "kickoff_latest"
    assert header_sort("1X2", "kickoff", "home_win") == "kickoff_earliest"
    assert header_sort("1X2", "stat", "kickoff_earliest") == "home_win"
    assert header_sort("1X2", "stat", "home_win") == "away_win"
    assert header_sort("BTTS", "stat", "btts_yes") == "btts_no"


# --------------------------------------------------------------- pagination
def test_ten_per_page_without_duplicates_or_gaps(data):
    first = payload(data)
    total = len(
        data.filtered(
            "1X2",
            [39, 288],
            None,
            datetime(2026, 12, 31).date(),
            "overall",
            "kickoff_earliest",
            None,
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

    def fake(data_, market, leagues, start, end, basis, direction, threshold, page, selected, **kw):
        captured.update(page=page, selected=selected)
        return (None,) * 11

    cb, func = _results_callback(data)
    inputs = [i["id"] if isinstance(i["id"], str) else json.dumps(i["id"]) for i in cb["inputs"]]
    assert (
        "prev" in inputs and any('"row"' in i for i in inputs) and any('"fx"' in i for i in inputs)
    )
    orig, appmod.results_payload = appmod.results_payload, fake
    try:
        args = (
            "1X2",
            [39],
            None,
            None,
            "kickoff_earliest",
            0,
            1,
            1,
            [],
            [],
            "all",
        )  # no odds toggle
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
        data, "1X2", [39, 288], None, "2026-12-31", "overall", None, 0, 1, target
    )
    assert (
        _selected_rows(on_page_1) == [] and _selected_cards(on_page_1) == []
    )  # not visible: no highlight
    assert on_page_1[10] == target  # but still selected
    on_page_2 = results_payload(
        data, "1X2", [39, 288], None, "2026-12-31", "overall", None, 0, 2, target
    )
    assert _selected_rows(on_page_2) == [target] and _selected_cards(on_page_2) == [target]
    # re-sorting keeps the selection; it is highlighted wherever it lands, never the first row by default
    latest = results_payload(
        data, "1X2", [39, 288], None, "2026-12-31", "overall", "kickoff_latest", 0, 1, target
    )
    assert latest[10] == target and _selected_rows(latest) in ([target], [])
    assert page_ids(latest)[0] not in _selected_rows(latest) or page_ids(latest)[0] == target


def test_selection_cleared_when_filtered_out(data):
    p = results_payload(data, "1X2", [288], None, "2026-12-31", "overall", None, 0, 1, EPL_FIX)
    assert p[10] is None and _selected_rows(p) == []
    kept = results_payload(data, "1X2", [39], None, "2026-12-31", "overall", None, 0, 1, EPL_FIX)
    assert kept[10] == EPL_FIX and _selected_rows(kept) == [EPL_FIX]


def test_league_and_date_filters(data):
    assert page_ids(payload(data, leagues=[288])) == [PSL_FIX]
    p = payload(data, leagues=[])
    assert p[0] is None and "Select at least one league" in _text(p[4])
    assert page_ids(payload(data, start="2026-11-18", end="2026-11-18")) == [EPL_FIX]
    empty = payload(data, start="2027-01-01", end="2027-01-31")
    assert empty[0] is None and "No fixtures match" in _text(empty[4]) and empty[2] == ""


def _meets_market(data, fid, market, minimum):
    """Independent check of the Minimum Market Probability: an outcome of the market
    with a fresh margin-adjusted consensus probability >= minimum."""
    from diski9.app.data import MARKET_OF, MARKET_OUTCOME_ORDER

    dm = data.snapshot().odds[fid].markets[MARKET_OF[market]]
    adj = dm.implied.margin_adjusted if (dm.status == "fresh" and dm.implied) else None
    return bool(adj) and any(
        float(adj[o]) >= minimum - 1e-12 for o in MARKET_OUTCOME_ORDER[MARKET_OF[market]]
    )


def test_market_threshold_is_the_same_for_every_ranking():
    """Phase 8 CP3A-3 (OD-4): one Minimum Market Probability, never disabled and with
    the same label whatever the ranking (kickoff, probability, edge, EV)."""
    for d in ("kickoff_earliest", "kickoff_latest", "home_win", "draw", "away_win", "edge", "ev"):
        c = threshold_config("1X2", d, 35)
        assert c["disabled"] is False and c["label"] == "Minimum Market Probability"
        assert c["value"] == 35 and c["tooltip"] is not None
        assert "market consensus" in c["hint"]
    assert threshold_config("BTTS", "kickoff_earliest")["value"] == 0  # default: no minimum


def test_market_threshold_applies_to_kickoff_ranking_too(data):
    for d in ("kickoff_earliest", "home_win"):
        for fid in page_ids(payload(data, direction=d, threshold=40)):
            assert _meets_market(data, fid, "1X2", 0.40), (d, fid)
    # 0 keeps every match, including those without odds or without a model
    assert payload(data, direction="kickoff_earliest", threshold=0)[2] == payload(
        data, direction="kickoff_earliest", threshold=None)[2]  # fmt: skip


def test_threshold_filters(data):
    ids = page_ids(payload(data, direction="home_win", threshold=50))
    assert ids and all(_meets_market(data, i, "1X2", 0.5) for i in ids)


# ---------------------------------------------------------- table & cards
def test_columns_alignment_and_names():
    cols = {c["id"]: c for c in columns_for("1X2")}
    assert cols["estimated_goals"]["label"] == "Est. goals"
    assert [cols[k]["label"] for k in ("p_home", "p_draw", "p_away")] == [
        "Home win",
        "Draw",
        "Away win",
    ]
    assert cols["p_home"]["align"] == "right" and cols["home"]["align"] == "left"
    assert "xG" not in json.dumps(columns_for("1X2"))
    goals = [c["label"] for c in columns_for("OU25")]
    assert goals[4:] == ["Est. goals", "Over 2.5", "Under 2.5", "Market / Edge"]
    assert all(c["label"] != "Data" for m in ("1X2", "BTTS", "OU25") for c in columns_for(m))
    assert [c["label"] for c in columns_for("BTTS")][5:7] == ["Yes", "No"]
    assert "never a model input" in cols["value"]["title"]


def test_rows_use_readable_dates_and_signed_differences(data):
    p = payload(data)
    first_row = p[0].children[1].children[0]
    kickoff = first_row.children[0].children
    assert kickoff == "Wed 18 Nov, 14:00"  # 12:00 UTC shown in SAST
    cells = [_text(c) for c in first_row.children]
    assert cells[4].count(".") == 2 and "–" in cells[4]  # "1.93 – 0.96" style
    assert all(c.endswith("%") for c in cells[5:8])
    assert sum(float(c.rstrip("%")) for c in cells[5:8]) == pytest.approx(100, abs=0.11)


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
    r, ov, official = data.detail(EPL_FIX, "overall")
    d = render_detail(r, ov, official, "1X2", data)
    text = _text(d)
    for phrase in (
        "Match analysis",  # 6B.3: the page is the Match Lab; this card analyses one match
        "A. Statistical baseline",
        "estimated goals",
        "B. Match context",
        "C. Other factors to consider",
        "D. Your adjustments",
        "Bookmaker Market Reference",
        "Recent form (Diski Form Score)",
        "Points part = 2.5 × points ÷ 3N",
        "League Form Score average",
        "How it's calculated",
        "Head-to-head",
        "League positions",
        "Consensus reference odds",
        "Avoid counting the same information twice",
        "Model vs market",
    ):
        assert phrase in text, phrase
    assert "xG" not in text.replace("not shot-based xG", "")
    # secondary sections start collapsed
    accs = _find(d, lambda c: isinstance(c, html.Details) and c.className == "acc")
    assert accs and all(getattr(a, "open", False) is False for a in accs)
    lowered = text.lower()
    # EV and edge are explained (market-edge enhancement), never oversold or staked
    banned = ("value bet", "betting edge", "stake ", "guaranteed profit", "sure bet", "risk-free")
    for phrase in banned + ("easy money", "guaranteed value", "recommended stake"):
        assert phrase not in lowered


def test_fresh_and_stale_odds_in_detail(populated):
    fresh = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    r, ov, official = fresh.detail(EPL_FIX, "overall")
    text = _text(render_detail(r, ov, official, "1X2", fresh))
    assert "Fresh" in text and "1.45" in text and "Market-implied" in text
    stale = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0 + 2 * DAY)
    r, ov, official = stale.detail(EPL_FIX, "overall")
    text = _text(render_detail(r, ov, official, "1X2", stale))
    assert "Stale" in text and "may have changed" in text and "1.45" in text
    from diski9.api_football.markets import Market

    assert ov.markets[Market.MATCH_RESULT].status == "stale"
    assert not ov.markets[Market.MATCH_RESULT].challenge_eligible
    row = stale.row("1X2", r)
    assert row["odds_status"] == "stale"


def test_market_implied_probabilities(data):
    from diski9.api_football.markets import Market, Outcome

    r, ov, official = data.detail(EPL_FIX, "overall")
    ip = ov.markets[Market.MATCH_RESULT].implied
    assert sum(ip.margin_adjusted.values()) == pytest.approx(Decimal(1))
    assert ip.raw[Outcome.HOME] == Decimal(1) / Decimal("1.45")


def test_missing_odds_psl(data):
    rows = payload(data, leagues=[288])
    assert page_ids(rows) == [PSL_FIX]
    r, ov, official = data.detail(PSL_FIX, "overall")
    assert data.row("BTTS", r)["odds"] == "No odds"
    text = _text(render_detail(r, ov, official, "BTTS", data))
    assert "No bookmaker odds are available for the PSL" in text


def test_limited_data_warnings(data, populated):
    """Goal Model 1.1: the promoted team's single match gives no estimate; with a
    second match the estimate appears with the limited-data warning (below 5)."""
    from diski9.screener import cache
    from diski9.screener import goal_model as gm

    r, ov, official = data.detail(PROMOTED_FIX, "overall")
    assert not r["goal_model"]["available"] and data.row("1X2", r)["available"] is False
    with populated.begin() as conn:
        store_fixtures(
            conn,
            [fixture_item(7778, 5, 130, kickoff=T0 - 2 * DAY, ft=(1, 1), season=2026)],
            lambda: T0,
        )
        cache.refresh(conn, [PROMOTED_FIX], T0, T0)
    r, ov, official = data.detail(PROMOTED_FIX, "overall")
    text = _text(render_detail(r, ov, official, "1X2", data))
    assert gm.LIMITED_DATA_WARNING in text
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
        "available": True,
        "unavailable_reason": None,
        "estimated_goals": "1.93 – 0.96",
        "p_home": "60.1%",
        "p_draw": "21.7%",
        "p_away": "18.2%",
        "odds": "1.40 · 5.00 · 7.04",
        "odds_status": "stale",
        "limited": True,
    }
    text = _text(fixture_card("1X2", row, None))
    assert "stale odds" in text and "Early season" in text and "Est. goals 1.93 – 0.96" in text
    assert "Home win 60.1%" in text


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
          await p.goto('http://127.0.0.1:{port}/');  // CP3A-3: the research list (Portfolio Build)
          await p.waitForSelector('.fx-card', {{ timeout: 20000 }});
          const out = {{}};
          out.cards = await p.locator('.fx-card').count();
          out.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          out.tableVisible = await p.isVisible('.table-wrap');
          out.basisOn1X2 = await p.isVisible('#basis-filter');
          await p.locator('#methodology > summary').tap();
          out.tooltip = await p.isVisible('.methodology-body');
          await p.locator('#methodology > summary').tap();
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
            "basisOn1X2": False,
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

    r, ov, official = data.detail(EPL_FIX, "overall")
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
        # the only expanders are the historical context rows (no odds-details accordion)
        # Engine 3.0: positions and head-to-head moved to The Match Lab
        accs = _find(card, lambda c: isinstance(c, h.Details) and c.className == "acc")
        assert accs == []
        lab = render_detail(r, ov, official, market, data).children[1]
        assert "League positions" in _text(lab) and "Head-to-head" in _text(lab)
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
        r, ov, official = d.detail(EPL_FIX, "overall")
        card = render_detail(r, ov, official, "1X2", d).children[2]
        text = _text(card)
        assert text.startswith("Bookmaker Market Reference")
        assert "not Diski 9 predictions" in text
        assert "Market-implied probabilities" in text and status in text
        ip = ov.markets[Market.MATCH_RESULT].implied
        for o in ip.margin_adjusted:
            assert f"{float(ip.margin_adjusted[o]) * 100:.1f}%" in text
        total = sum(float(v) for v in ip.margin_adjusted.values()) * 100
        assert abs(total - 100) < 1e-6
        assert "not betting advice" in text  # comparison only, no recommendation
    d = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    r, ov, official = d.detail(PSL_FIX, "overall")
    card = render_detail(r, ov, official, "1X2", d).children[2]
    text = _text(card)
    assert "market-implied probabilities are unavailable" in text
    assert (
        "Market data unavailable: no bookmaker prices to compare with" in text
    )  # nothing invented


def test_compact_limited_marker_in_table(data):
    p = payload(data, end="2026-12-31", page=2)
    cells = _find(p[0], lambda c: "pill" in str(getattr(c, "className", "")))
    assert cells and all(_text(c) in ("Early season", "No model") for c in cells)
    assert all("fewer than five" in c.title for c in cells if _text(c) == "Early season")
    # the flag sits in the Est. goals cell (column 5); there is no separate Data column
    for row in p[0].children[1].children:
        assert len(row.children) == len(columns_for("1X2"))
        flagged = _find(row, lambda c: "pill" in str(getattr(c, "className", "")))
        if flagged:
            assert flagged[0] in _find(row.children[4], lambda c: True)


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
          // CP3A-3: the research list lives in Portfolio Build; selecting a match opens
          // it in the Match Lab, and the list keeps the selection when you come back
          await p.goto('http://127.0.0.1:{port}/');
          await p.waitForSelector('tr.row', {{ timeout: 20000, state: 'visible' }});
          const out = {{}};
          const rows = await ids(p);
          out.initial = await sel(p);
          await p.locator('tr.row').nth(2).click();
          await p.waitForURL(/\/lab\?/);
          await p.waitForSelector('.detail-header h2', {{ state: 'visible' }});
          const thirdTitle = await p.locator('.detail-header h2').innerText();
          await p.locator('#lab-back').click();
          await p.waitForSelector('tr.row', {{ state: 'visible' }});
          await p.waitForFunction(() => document.querySelectorAll('tr.row.selected').length === 1);
          out.afterThird = await sel(p); out.third = rows[2];
          await p.locator('tr.row').nth(4).click();
          await p.waitForURL(/\/lab\?/);
          await p.waitForFunction((t) => document.querySelector('.detail-header h2') && document.querySelector('.detail-header h2').innerText !== t, thirdTitle);
          out.detail = await p.locator('.detail-header h2').innerText();
          await p.locator('#lab-back').click();
          await p.waitForSelector('tr.row', {{ state: 'visible' }});
          await p.waitForFunction((id) => document.querySelector('tr.row.selected') && JSON.parse(document.querySelector('tr.row.selected').id).index === id, rows[4]);
          out.afterFifth = await sel(p); out.fifth = rows[4];
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
        snap = data.snapshot().results["overall"][out["fifth"]]["fixture"]
        assert out["detail"] == f"{snap['home']} v {snap['away']}"
    finally:
        server.shutdown()
