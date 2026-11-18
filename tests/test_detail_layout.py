# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Engine 3.0 detail layout: The Match Lab (A baseline, B context, C factors,
D adjustments) followed by the Bookmaker Market Reference card."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time

import pytest
from dash import html

from diski9.app import create_app
from diski9.app.views import render_detail

from .test_app import (  # noqa: F401
    EPL_FIX,
    PSL_FIX,
    _find,
    _free_port,
    _text,
    data,
    payload,
    populated,
)

MARKETS = ("1X2", "BTTS", "OU25")


def cards(d):
    return d.children[1], d.children[2]


def sections(lab):
    return [c for c in lab.children if "lab-section" in str(getattr(c, "className", ""))]


@pytest.mark.parametrize("market", MARKETS)
def test_match_lab_then_bookmaker_card_in_every_market(data, market):
    r, ov, official = data.detail(EPL_FIX, "overall")
    d = render_detail(r, ov, official, market, data)
    lab, market_card = cards(d)
    assert _text(lab).startswith(
        "Match analysis We calculate the probabilities. You analyse the match. You make the call."
    )
    assert [_text(s).split(" ", 2)[:2] for s in sections(lab)] == [
        ["A.", "Statistical"],
        ["B.", "Match"],
        ["C.", "Other"],
        ["D.", "Your"],
    ]
    assert _text(market_card).startswith(
        "Bookmaker Market Reference Market-implied probabilities are derived from bookmaker "
        "prices, not Diski 9 predictions."
    )
    # context lives in the Match Lab, collapsed; nothing duplicated in the odds card
    ctx = sections(lab)[1]
    titles = [
        _text(a.children[0]).split(" (")[0]
        for a in _find(ctx, lambda c: isinstance(c, html.Details) and c.className == "acc")
    ]
    assert titles[0] == "Recent form" and "Head-to-head" in titles and "League positions" in titles
    if market != "1X2":
        assert any(t.startswith("Recent ") and "record" in t for t in titles)
    assert not _find(
        market_card, lambda c: getattr(c, "className", "") == "acc-group context-group"
    )
    assert len(d.children) == 4  # heading, lab, bookmaker card, footnote


def test_baseline_shows_estimated_goals_and_selected_market(data):
    r, ov, official = data.detail(EPL_FIX, "overall")
    g = r["goal_model"]
    for market, labels in (
        ("1X2", ["Home win", "Draw", "Away win"]),
        ("BTTS", ["Yes", "No"]),
        ("OU25", ["Over 2.5", "Under 2.5"]),
    ):
        lab, _ = cards(render_detail(r, ov, official, market, data))
        base = sections(lab)[0]
        t = _text(base)
        assert f"{g['estimated_goals']['home']:.2f} estimated goals" in t
        assert f"{g['estimated_goals']['away']:.2f} estimated goals" in t
        bars = _find(base, lambda c: getattr(c, "className", "") == "bar-label")
        assert [_text(b) for b in bars] == labels


def test_calculation_details_preserved(data):
    r, ov, official = data.detail(EPL_FIX, "overall")
    lab, _ = cards(render_detail(r, ov, official, "1X2", data))
    text = _text(lab)
    for phrase in (
        "Won · drawn · lost",
        "Points part = 2.5 × points ÷ 3N",
        "Goal-difference part",
        "Diski Form Score (0–5)",
        "Only matches played before kickoff",
        "Strength (1.00 = league average)",
        "Goal tempo (1.00 = league average)",
        "Poisson distribution",
        "Goal Model 1.0",
    ):
        assert phrase in text, phrase
    b = r["teams"]["home"]["form"]["breakdown"]
    assert f"2.5 × {b['points']}/{b['max_points']} = {b['points_component_display']}" in text
    btts, _ = cards(render_detail(r, ov, official, "BTTS", data))
    t = _text(btts)
    assert "League BTTS baseline" in t and "current-season matches in this competition" in t


def test_form_tiles_and_results_in_matches_used(data):
    r, ov, official = data.detail(EPL_FIX, "overall")
    lab, _ = cards(render_detail(r, ov, official, "1X2", data))
    form = [
        a
        for a in _find(lab, lambda c: isinstance(c, html.Details) and c.className == "acc")
        if _text(a.children[0]).startswith("Recent form")
    ][0]
    tiles = _find(form, lambda c: getattr(c, "className", "") == "tiles")[0].children
    for tile in tiles:
        assert "out of 5" in _text(tile) and "/ 5" not in _text(tile)
    matches = [
        a
        for a in _find(form, lambda c: isinstance(c, html.Details))
        if _text(a.children[0]) == "Matches used"
    ][0]
    tables = _find(matches, lambda c: isinstance(c, html.Table))
    assert len(tables) == 2
    for side, table in zip(("home", "away"), tables, strict=True):
        badges = [
            _text(b)
            for b in _find(table, lambda c: str(getattr(c, "className", "")).startswith("res res-"))
        ]
        assert badges == r["teams"][side]["form"]["sequence"].split("-")


def test_psl_market_card_is_small_and_honest(data):
    r, ov, official = data.detail(PSL_FIX, "overall")
    for market in MARKETS:
        _, card = cards(render_detail(r, ov, official, market, data))
        assert "compact" in card.className
        assert "No bookmaker odds are available for the PSL" in _text(card)
        odds_part = _text(card.children[:-1])  # everything above the model comparison
        assert "%" not in odds_part and "bookmaker group" not in odds_part
        assert "Market data unavailable: no bookmaker prices to compare with" in _text(
            card.children[-1]
        )


BROWSER = """
const { chromium, devices } = require('playwright');
const state = (p) => p.evaluate(() =>
  [...document.querySelectorAll('.lab .context .acc-group > details.acc')].map(d => d.open));
(async () => {
  const b = await chromium.launch();
  const out = {};
  const views = [['desktop', { viewport: { width: 1400, height: 1000 } }],
                 ['phone', devices['iPhone 13']]];
  for (const [name, opts] of views) {
    const ctx = await b.newContext(opts);
    const p = await ctx.newPage();
    await p.goto(BASE);
    await p.waitForSelector('tr.row, .fx-card', { timeout: 20000, state: 'attached' });
    if (name === 'desktop') await p.locator('tr.row').first().click();
    else await p.locator('.fx-card').first().tap();
    await p.waitForSelector('.lab', { timeout: 20000 });
    const r = {};
    r.titles = await p.evaluate(() =>
      [...document.querySelectorAll('.detail .card-head h3')].map(h => h.innerText));
    r.steps = await p.evaluate(() =>
      [...document.querySelectorAll('.lab .lab-step')].map(h => h.innerText));
    const acc = p.locator('.lab .context .acc-group > details.acc > summary');
    r.closed = (await state(p)).every(x => !x);
    await acc.nth(0).click(); r.firstOpen = (await state(p))[0];
    await acc.nth(2).focus(); await p.keyboard.press('Enter');
    r.keyboardOpen = (await state(p))[2];
    r.summaryHeight = await acc.first().evaluate(e => e.getBoundingClientRect().height);
    r.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    out[name] = r;
    await ctx.close();
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_lab_accordions_and_mobile(data):
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    port = _free_port()
    server = make_server("127.0.0.1", port, create_app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        time.sleep(0.5)
        script = f"const BASE = 'http://127.0.0.1:{port}/';\n" + BROWSER
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=180)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        for name in ("desktop", "phone"):
            r = out[name]
            assert r["titles"] == ["Match analysis", "Bookmaker Market Reference"]  # 6B.3 rename
            assert [s.split(".")[0] for s in r["steps"]] == ["A", "B", "C", "D"]
            assert r["closed"] and r["firstOpen"] and r["keyboardOpen"]
            assert r["summaryHeight"] >= 44  # comfortable touch target
            assert r["overflow"] <= 0
    finally:
        server.shutdown()
