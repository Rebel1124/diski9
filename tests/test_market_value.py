# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Model vs market enhancement: margin-normalised market probabilities, probability
edge (pp), expected value at the original odds, the Screener's edge / EV rankings
and the Match Lab's value check. Goal Model 1.0 itself is unchanged."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from diski9.api_football.markets import Market, Outcome
from diski9.app import ScreenerData
from diski9.app.app import (
    THRESHOLD_VALUE_HINT,
    columns_for,
    results_payload,
    threshold_config,
)
from diski9.app.data import DIRECTIONS, MARKET_KEYS, MARKET_OF, PAGE_SIZE
from diski9.app.lab import lab_outputs, model_comparison, new_state, user_estimates, value_check
from diski9.db.schema import forecast_snapshots
from diski9.odds.collect import OddsPage, reconcile_pages
from diski9.odds.consensus import MarketConsensus, OutcomeConsensus
from diski9.odds.implied import normalise
from diski9.odds.value import (
    compare,
    edge_pp,
    edge_text,
    ev_text,
    expected_value,
    positive_edge,
    positive_ev,
)
from diski9.screener import goal_model as gm
from diski9.screener.rank import rank_by_value

from .factories import T0, full_book, odds_item
from .test_app import DAY, EPL_FIX, EXTRA, PSL_FIX, _free_port, _text, data, page_ids, populated  # noqa: F401

D = Decimal
ONE_X_TWO = {Outcome.HOME, Outcome.DRAW, Outcome.AWAY}


def consensus(market: Market, prices: dict[Outcome, str | None]) -> MarketConsensus:
    outcomes = {
        o: OutcomeConsensus(
            o, D(p) if p else None, D(p) if p else None, 3 if p else 0, (1, 2, 3), None, None
        )
        for o, p in prices.items()
    }
    return MarketConsensus(1, market, T0, outcomes, 3, 3, {})


# ------------------------------------------------------------- pure maths
def test_1x2_normalisation_matches_the_worked_example():
    m = normalise({Outcome.HOME: "1.80", Outcome.DRAW: "3.60", Outcome.AWAY: "4.50"}, ONE_X_TWO)
    pct = {o: round(float(v) * 100, 2) for o, v in m.items()}
    assert pct == {Outcome.HOME: 52.63, Outcome.DRAW: 26.32, Outcome.AWAY: 21.05}
    assert sum(m.values()) == pytest.approx(1)
    raw = sum(1 / x for x in (1.80, 3.60, 4.50))
    assert round(raw * 100, 2) == 105.56  # the margin that is removed


@pytest.mark.parametrize(
    "market,a,b,pa,pb",
    [
        (Market.BTTS, Outcome.BTTS_YES, Outcome.BTTS_NO, "1.80", "2.00"),
        (Market.OVER_UNDER_25, Outcome.OVER_25, Outcome.UNDER_25, "1.90", "1.95"),
    ],
)
def test_two_way_normalisation(market, a, b, pa, pb):
    m = normalise({a: pa, b: pb}, {a, b})
    ra, rb = 1 / float(pa), 1 / float(pb)
    assert float(m[a]) == pytest.approx(ra / (ra + rb))
    assert float(m[b]) == pytest.approx(rb / (ra + rb))
    assert sum(m.values()) == pytest.approx(1)


@pytest.mark.parametrize(
    "prices",
    [
        {Outcome.HOME: "1.80", Outcome.DRAW: "3.60"},  # away missing
        {Outcome.HOME: "1.80", Outcome.DRAW: "3.60", Outcome.AWAY: None},
        {Outcome.HOME: "1.80", Outcome.DRAW: "3.60", Outcome.AWAY: "1.00"},  # invalid
        {Outcome.HOME: "1.80", Outcome.DRAW: "0", Outcome.AWAY: "4.50"},
        {Outcome.HOME: "1.80", Outcome.DRAW: "abc", Outcome.AWAY: "4.50"},
        {},
    ],
)
def test_incomplete_or_invalid_markets_are_never_normalised(prices):
    assert normalise(prices, ONE_X_TWO) is None  # a missing price is never zero


def test_edge_and_ev_formulas():
    assert edge_pp(0.55, 0.48) == pytest.approx(7.0)
    assert expected_value(0.55, 2.10) == pytest.approx(0.155)
    assert expected_value(0.55, D("2.10")) == pytest.approx(0.155)
    assert ev_text(0.155) == "+15.5%" and ev_text(-0.082) == "-8.2%" and ev_text(0) == "0.0%"
    assert ev_text(None) == "EV unavailable"
    assert (
        edge_text(7.0) == "+7.0 pp" and edge_text(-3) == "-3.0 pp" and edge_text(0.04) == ("0.0 pp")
    )
    for bad in (None, 1, "1.00", 0.5, "abc", float("nan"), float("inf")):
        assert expected_value(0.5, bad) is None
    # values that round to zero are never called positive
    assert not positive_edge(0.04) and positive_edge(0.05) and not positive_edge(-1)
    assert not positive_ev(0.0004) and positive_ev(0.0006) and not positive_ev(None)


def test_ev_uses_original_odds_and_edge_uses_normalised_market():
    probs = {"home": 0.55, "draw": 0.25, "away": 0.20}
    mv = compare(
        Market.MATCH_RESULT,
        probs,
        consensus(
            Market.MATCH_RESULT, {Outcome.HOME: "2.00", Outcome.DRAW: "3.40", Outcome.AWAY: "3.80"}
        ),
    )
    raw = {"home": 1 / 2.00, "draw": 1 / 3.40, "away": 1 / 3.80}
    total = sum(raw.values())
    for o in mv.outcomes:
        odds = float(o.odds)
        assert o.ev == pytest.approx(probs[o.key] * odds - 1)  # original price
        assert o.market_probability == pytest.approx(raw[o.key] / total)
        assert o.edge == pytest.approx((probs[o.key] - raw[o.key] / total) * 100)
        # EV at a margin-free price would differ: the two concepts stay distinct
        assert o.ev != pytest.approx(probs[o.key] / (raw[o.key] / total) - 1)
    assert mv.complete


def test_incomplete_market_keeps_ev_where_priced_but_no_edges():
    mv = compare(
        Market.MATCH_RESULT,
        {"home": 0.5, "draw": 0.3, "away": 0.2},
        consensus(Market.MATCH_RESULT, {Outcome.HOME: "2.20", Outcome.DRAW: "3.40"}),
    )
    assert not mv.complete
    by = {o.key: o for o in mv.outcomes}
    assert all(o.market_probability is None and o.edge is None for o in mv.outcomes)
    assert by["home"].ev == pytest.approx(0.1) and by["away"].ev is None
    assert mv.best_edge() is None and mv.best_ev().key == "home"
    assert compare(Market.MATCH_RESULT, {}, None) is None
    assert compare(Market.BTTS, {"btts_yes": 0.5, "btts_no": 0.5}, None) is None


def test_best_edge_and_best_ev_are_chosen_independently():
    mv = compare(
        Market.MATCH_RESULT,
        {"home": 0.60, "draw": 0.25, "away": 0.15},
        consensus(
            Market.MATCH_RESULT, {Outcome.HOME: "1.83", Outcome.DRAW: "2.57", Outcome.AWAY: "8.66"}
        ),
    )
    edges = {o.key: o.edge for o in mv.outcomes}
    evs = {o.key: o.ev for o in mv.outcomes}
    assert mv.best_edge().key == max(edges, key=edges.get) == "home"  # +8.0 pp
    assert mv.best_ev().key == max(evs, key=evs.get) == "away"  # +29.9% EV
    # the threshold restricts which outcomes are considered (minimum model probability)
    assert mv.best_ev(0.5).key == "home" and mv.best_edge(0.7) is None


def test_no_positive_edge_or_ev_is_none():
    mv = compare(
        Market.BTTS,
        {"btts_yes": 0.5, "btts_no": 0.5},
        consensus(Market.BTTS, {Outcome.BTTS_YES: "1.90", Outcome.BTTS_NO: "1.90"}),
    )
    assert all(o.edge == pytest.approx(0) for o in mv.outcomes)
    assert mv.best_edge() is None and mv.best_ev() is None  # EV -5% each


def test_rank_by_value_order_and_ties():
    def r(fid, hours):
        return {"fixture": {"id": fid, "kickoff": (T0 + timedelta(hours=hours)).isoformat()}}

    values = {
        1: (True, 2.0),
        2: (True, 5.0),
        3: (True, None),
        4: (False, None),
        5: (True, 5.0),
        6: (True, None),
    }
    items = [r(1, 1), r(2, 9), r(3, 5), r(4, 0), r(5, 3), r(6, 2)]
    ranked = rank_by_value(items, lambda x: values[x["fixture"]["id"]])
    # positives (ties by kickoff), then no positive value, then no market data
    assert [x["fixture"]["id"] for x in ranked] == [5, 2, 1, 6, 3, 4]


# ------------------------------------------------------------- the Screener
PRICES = ["1.30", "1.55", "1.80", "2.10", "2.40", "2.80", "3.20", "3.60", "4.20", "5.00", "6.00"]


@pytest.fixture
def valued(populated):
    """EPL odds for the main fixture and 11 of the 12 extra fixtures (varied prices;
    one extra fixture has no odds, one has an incomplete 1X2 market)."""
    books_main = {b: full_book(home=h) for b, h in ((8, "1.40"), (11, "1.45"), (4, "1.50"))}
    items = [
        odds_item(EPL_FIX, books_main, kickoff=T0 + 3 * DAY, update="2026-11-15T11:00:00+00:00")
    ]
    for i, fid in enumerate(EXTRA[:-1]):
        home = PRICES[i]
        book = full_book(home=home, away=PRICES[-1 - i], yes=PRICES[i], no=PRICES[-1 - i])
        if i == 3:
            book["1"] = [("Home", home), ("Draw", "3.40")]  # incomplete 1X2
        kickoff = T0 + 5 * DAY + i * timedelta(hours=2)
        items.append(
            odds_item(fid, {8: book, 11: book}, kickoff=kickoff, update="2026-11-15T11:00:00+00:00")
        )
    with populated.begin() as conn:
        page = OddsPage(T0 - timedelta(minutes=30), items)
        reconcile_pages(conn, 39, 2026, [page], clock=lambda: T0 - timedelta(minutes=30))
    return ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)


def run(d, market="1X2", direction="edge", thr=0, page=1, leagues=(39, 288)):
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
    )


def expected_order(d, market, direction, thr=None):
    """Independent recomputation of the ranking from the shared analytics layer."""
    snap = d.snapshot()
    pos, nopos, nodata = [], [], []
    for r in snap.results["overall"].values():
        probs = (r.get("goal_model") or {}).get("probabilities") or {}
        if thr is not None and not any(probs.get(k, 0) >= thr for k, _ in MARKET_KEYS[market]):
            continue
        dm = snap.odds[r["fixture"]["id"]].markets[MARKET_OF[market]]
        mv = compare(MARKET_OF[market], probs, dm.consensus) if dm.status == "fresh" else None
        key = (r["fixture"]["kickoff"], r["fixture"]["id"])
        if mv is None:
            nodata.append(key)
            continue
        pick = mv.best_ev(thr) if direction == "ev" else mv.best_edge(thr)
        if pick is None:
            (nopos if (mv.complete or direction == "ev") else nodata).append(key)
        else:
            pos.append((-(pick.ev if direction == "ev" else pick.edge), *key))
    ids = (
        [k[2] for k in sorted(pos)] + [k[1] for k in sorted(nopos)] + [k[1] for k in sorted(nodata)]
    )
    return ids


@pytest.mark.parametrize("market", ["1X2", "BTTS", "OU25"])
@pytest.mark.parametrize("direction", ["edge", "ev"])
def test_ranking_over_full_filtered_set_before_pagination(valued, market, direction):
    assert direction in dict(DIRECTIONS[market])
    want = expected_order(valued, market, direction)
    got = []
    for page in (1, 2):
        got += page_ids(run(valued, market, direction, page=page))
    assert got == want
    assert len(got) == len(valued.snapshot().results["overall"]) > PAGE_SIZE


def test_positive_values_lead_and_cells_never_oversell(valued):
    snap = valued.snapshot()
    for market in ("1X2", "BTTS", "OU25"):
        for direction in ("edge", "ev"):
            ranked = valued.filtered(market, [39, 288], None, None, "overall", direction, None)
            cells = [valued.value_cell(market, r, direction) for r in ranked]
            kinds = [c["cls"] for c in cells]
            n_pos = kinds.count("pos")
            assert kinds[:n_pos] == ["pos"] * n_pos  # positives first, never demoted
            assert n_pos and n_pos < len(kinds)
            for c in cells[:n_pos]:
                assert "+" in c["main"]
            for c in cells[n_pos:]:
                assert "+" not in (c["main"] or "")  # no negative / zero value highlighted
            words = {c["main"] for c in cells[n_pos:]}
            assert words <= {
                "No positive edge",
                "No positive EV",
                "Incomplete market",
                "No odds",
                "—",
            }, words
            assert len(ranked) == len(snap.results["overall"])


def test_value_cell_matches_displayed_odds(valued):
    snap = valued.snapshot()
    for market in ("1X2", "BTTS", "OU25"):
        for r in snap.results["overall"].values():
            cell = valued.value_cell(market, r, "ev")
            mv, pick = valued.value_pick(market, r, "ev", None)
            if pick is None:
                continue
            odds_text = valued.odds_summary(snap.odds[r["fixture"]["id"]], MARKET_OF[market])[1]
            assert str(pick.odds) in odds_text.split(" · ")  # the price the user sees
            assert f"at {pick.odds}" == cell["sub"] and odds_text in cell["title"]
            assert pick.ev == pytest.approx(pick.probability * float(pick.odds) - 1)
            assert ev_text(pick.ev) in cell["main"]


def test_value_rankings_keep_fixtures_without_odds_last(valued):
    # Phase 6B.2: the "only matches with odds" toggle was removed; fixtures without
    # odds stay listed (after every priced fixture) instead of being filtered out
    ranked = page_ids(run(valued, direction="edge")) + page_ids(
        run(valued, direction="edge", page=2)
    )
    assert PSL_FIX in ranked and ranked.index(PSL_FIX) > ranked.index(EPL_FIX)
    assert run(valued, direction="ev", leagues=(288,))[0].children[1].children[0].children[-1]
    psl = run(valued, direction="ev", leagues=(288,))
    assert "No odds" in _text(psl[0])  # PSL has no collected odds: shown honestly


def test_threshold_keeps_minimum_model_probability_semantics(valued):
    c = threshold_config("1X2", "edge", 40)
    assert c["label"] == "Minimum model probability" and c["hint"] is None
    assert "minimum model probability still applies" in THRESHOLD_VALUE_HINT
    assert not c["disabled"] and c["value"] == 40
    thr = 0.45
    want = expected_order(valued, "1X2", "ev", thr)
    got = page_ids(run(valued, "1X2", "ev", thr=45)) + page_ids(
        run(valued, "1X2", "ev", thr=45, page=2)
    )
    assert got == want
    snap = valued.snapshot()
    for fid in got:
        r = snap.results["overall"][fid]
        probs = r["goal_model"]["probabilities"]
        assert max(probs[k] for k in ("home", "draw", "away")) >= thr
        _, pick = valued.value_pick("1X2", r, "ev", thr)
        assert pick is None or pick.probability >= thr


def test_dynamic_final_column_and_existing_probability_columns(valued):
    for direction, label in (
        ("kickoff_earliest", "Market / Edge"),
        ("home_win", "Market / Edge"),
        ("edge", "Best edge"),
        ("ev", "Best EV"),
    ):
        cols = columns_for("1X2", direction)
        assert [c["label"] for c in cols][5:] == ["Home win", "Draw", "Away win", label]
        assert len(cols) == 9  # no extra columns: the table does not get wider


def test_stale_prices_are_not_ranked(populated):
    stale = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0 + 2 * DAY)
    r = stale.detail(EPL_FIX)[0]
    assert stale.value_pick("1X2", r, "edge", None) == (None, None)
    cell = stale.value_cell("1X2", r, "edge")
    assert cell["main"] == "Prices stale" and cell["sub"] == "Not ranked"


def test_rankings_do_not_mutate_model_or_snapshots(valued):
    snap = valued.snapshot()
    before = copy.deepcopy(snap.results)
    with valued.engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(forecast_snapshots)).scalar()
    for direction in ("edge", "ev"):
        for market in ("1X2", "BTTS", "OU25"):
            run(valued, market, direction, thr=30)
    assert snap.results == before
    with valued.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(forecast_snapshots)).scalar() == n
    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.m0) == (12, 96, 30)


# ------------------------------------------------------------- the Match Lab
def _state(home=0.0, away=0.0):
    st = new_state()
    st["manual"] = {"home": home, "away": away}
    return st


def test_bookmaker_card_full_breakdown_uses_model_baseline(data):
    r, ov, _ = data.detail(EPL_FIX)
    base = r["goal_model"]["probabilities"]
    for market in ("1X2", "BTTS", "OU25"):
        t = _text(model_comparison(market, ov, base))
        dm = ov.markets[MARKET_OF[market]]
        mv = compare(MARKET_OF[market], base, dm.consensus)
        for o in mv.outcomes:
            assert edge_text(o.edge) in t and ev_text(o.ev) in t and str(o.odds) in t
        assert "independent bookmaker group" in t and "not proof" in t
        assert "What do model, market, edge and EV mean?" in t


def test_value_check_baseline_then_recalculated_after_adjustment(data):
    r, ov, _ = data.detail(EPL_FIX)
    before = copy.deepcopy(r)
    base = r["goal_model"]["probabilities"]
    dm = ov.markets[Market.MATCH_RESULT]
    odds = {
        k: float(dm.consensus.outcomes[o].consensus_odds)
        for o, k in ((Outcome.HOME, "home"), (Outcome.DRAW, "draw"), (Outcome.AWAY, "away"))
    }
    # no adjustments: your probability = model probability, EV = model EV
    t0 = _text(value_check("1X2", ov, base, None))
    assert "No adjustments yet" in t0 and "Model EV" not in t0
    for k in odds:
        assert ev_text(base[k] * odds[k] - 1) in t0
    # an adjustment recalculates the probability and the EV immediately
    st = _state(home=0.40, away=-0.20)
    out, compare_card = lab_outputs(r, "1X2", ov, st)
    est = user_estimates(r, st)
    mine = gm.markets(est["home"], est["away"])
    vc = _text(out.children[-1])
    assert "Your final probability" in vc and "Model EV" in vc
    for k in odds:
        assert f"{mine[k] * 100:.1f}%" in vc
        assert ev_text(mine[k] * odds[k] - 1) in vc  # final EV = your p x original odds - 1
        assert ev_text(base[k] * odds[k] - 1) in vc  # the model's EV stays alongside
    assert mine["home"] != base["home"]
    # the bookmaker card keeps the model baseline; nothing in the cache changes
    assert f"{base['home'] * 100:.1f}%" in _text(compare_card)
    assert r == before


def test_value_check_without_odds_and_ev_explainer(data):
    r, ov, _ = data.detail(PSL_FIX)
    t = _text(value_check("1X2", ov, r["goal_model"]["probabilities"], None))
    assert "Market data unavailable" in t and "EV unavailable" in t
    assert "What is Expected Value (EV)?" in t and "(0.55 × 2.10) − 1 = +15.5%" in t
    assert "does not guarantee a winning bet" in t
    for banned in ("guaranteed profit", "sure bet", "risk-free", "easy money"):
        assert banned not in t.lower()


# ---------------------------------------------------------------- browser
BROWSER = """
const { chromium, devices } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const res = {};
  const views = [['desktop', { viewport: { width: 1400, height: 1000 } }],
                 ['tablet', { viewport: { width: 900, height: 1100 } }],
                 ['phone', devices['iPhone 13']]];
  for (const [name, opts] of views) {
    const ctx = await b.newContext(opts);
    const p = await ctx.newPage();
    await p.goto(BASE);
    await p.waitForSelector('#direction', { timeout: 20000 });
    await p.waitForTimeout(800);
    const r = {};
    for (const [mode, text] of [['edge', 'model vs market edge'], ['ev', 'expected value']]) {
      await p.evaluate(() => window.scrollTo(0, 0));
      await p.locator('#direction').click();
      await p.locator('[role=option]', { hasText: text }).dispatchEvent('click');
      await p.waitForFunction((m) => {
        const th = [...document.querySelectorAll('table.results th')].pop();
        return th && th.innerText.toLowerCase().includes(m);
      }, mode === 'ev' ? 'best ev' : 'best edge', { timeout: 15000 });
      await p.waitForTimeout(500);
      r[mode] = {
        overflow: await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
        head: await p.evaluate(() => [...document.querySelectorAll('table.results th')].pop().innerText),
        cells: await p.evaluate(() => [...document.querySelectorAll('table.results td.value-cell')]
          .slice(0, 3).map(t => t.innerText.replace(/\\n/g, ' | '))),
        cards: await p.evaluate(() => [...document.querySelectorAll('.card-value')]
          .slice(0, 3).map(t => t.innerText)),
        tableVisible: await p.locator('table.results').isVisible(),
      };
      if (SHOTS) await p.screenshot({ path: `${SHOTS}/${name}-${mode}.png` });
    }
    const row = p.locator('table.results tr.row').first();
    if (await row.isVisible()) await row.click(); else await p.locator('.fx-card').first().click();
    await p.waitForSelector('.value-check table', { timeout: 20000 });
    await p.waitForTimeout(500);
    r.labOverflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    r.before = await p.locator('.value-check').innerText();
    r.compare = await p.locator('#lab-compare').innerText();
    r.compareScroll = await p.evaluate(() => {
      const el = document.querySelector('#lab-compare .scroll-x');
      return el.scrollWidth - el.clientWidth; });
    const inp = p.locator('input#lab-home-input, #lab-home-input input').first();
    await inp.fill('3.00'); await inp.press('Enter');
    await p.waitForFunction(() => document.querySelector('.value-check').innerText.includes('Model EV'),
      null, { timeout: 15000 });
    r.after = await p.locator('.value-check').innerText();
    r.labOverflowAfter = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    r.checkScroll = await p.evaluate(() => {
      const el = document.querySelector('.value-check .scroll-x');
      return el.scrollWidth - el.clientWidth; });
    if (SHOTS) {
      await p.locator('.value-check').scrollIntoViewIfNeeded();
      await p.screenshot({ path: `${SHOTS}/${name}-valuecheck.png` });
      await p.locator('#lab-compare').scrollIntoViewIfNeeded();
      await p.screenshot({ path: `${SHOTS}/${name}-compare.png` });
    }
    res[name] = r;
    await ctx.close();
  }
  console.log(JSON.stringify(res));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_value_rankings_and_lab(valued):
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    from diski9.app import create_app

    port = _free_port()
    server = make_server("127.0.0.1", port, create_app(valued).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    shots = os.environ.get("DISKI9_SHOTS", "")
    try:
        time.sleep(0.5)
        script = f"const BASE = 'http://127.0.0.1:{port}/'; const SHOTS = {json.dumps(shots)};\n"
        res = subprocess.run(
            ["node", "-e", script + BROWSER], capture_output=True, text=True, timeout=300
        )
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        for name in ("desktop", "tablet", "phone"):
            r = out[name]
            for mode in ("edge", "ev"):
                assert r[mode]["overflow"] <= 0, (name, mode)  # no horizontal page scroll
            assert r["edge"]["head"].lower().startswith("best edge")
            assert r["ev"]["head"].lower().startswith("best ev")
            if r["ev"]["tableVisible"]:
                assert "pp" in r["edge"]["cells"][0] and "Market" in r["edge"]["cells"][0]
                assert "EV" in r["ev"]["cells"][0] and "at " in r["ev"]["cells"][0]
            else:  # phone: cards
                assert r["ev"]["cards"] and r["ev"]["cards"][0].startswith("Best EV:")
            assert r["labOverflow"] <= 0 and r["labOverflowAfter"] <= 0, name
            assert "No adjustments yet" in r["before"] and "Model EV" not in r["before"]
            assert "Model EV" in r["after"] and r["after"] != r["before"]
            assert "MODEL VS MARKET" in r["compare"].upper() and "EV" in r["compare"]
            assert r["compareScroll"] <= 0, (name, r["compareScroll"])  # every column visible
            assert r["checkScroll"] <= 0, (name, r["checkScroll"])
    finally:
        server.shutdown()
