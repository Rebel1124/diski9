# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Final UI refinement: two main detail cards (analysis / bookmaker market)."""

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


@pytest.mark.parametrize("market", MARKETS)
def test_two_titled_cards_in_every_market(data, market):
    r, ov, official = data.detail(EPL_FIX, "overall")
    d = render_detail(r, ov, official, market, data)
    analysis, market_card = cards(d)
    assert _text(analysis).startswith("Diski 9 Match Analysis Historical statistics")
    assert _text(market_card).startswith(
        "Bookmaker Market Reference Market-implied probabilities are derived from bookmaker "
        "prices, not Diski 9 predictions."
    )
    # both explanation rows live inside the analysis card, collapsed by default
    accs = _find(analysis, lambda c: isinstance(c, html.Details) and c.className == "acc")
    assert [_text(a.children[0]) for a in accs] == ["How it's calculated", "Matches used"]
    assert all(a.open is False for a in accs)
    # no separate outer cards for them any more
    outer = [_text(c.children[0]) for c in d.children[3].children]
    assert [o.split(" (")[0] for o in outer] == [
        "League positions",
        "Head-to-head",
        "Other markets",
    ]


def test_form_difference_removed_from_detail_but_kept_in_screener(data):
    r, ov, official = data.detail(EPL_FIX, "venue")
    analysis, _ = cards(render_detail(r, ov, official, "1X2", data))
    visible = [c for c in analysis.children if getattr(c, "className", "") != "acc-group"]
    assert "Form Difference" not in _text(visible)  # no headline figure or its note
    assert r["match_result"]["form_difference_display"] not in _text(visible)
    assert "do not mean a draw is likely" not in _text(analysis)
    p = payload(data, direction="home_stronger")
    assert "Form difference" in _text(p[0].children[0])
    first = p[0].children[1].children[0]
    assert first.children[6].children.startswith(("+", "-", "0"))


def test_calculation_details_preserved(data):
    r, ov, official = data.detail(EPL_FIX, "venue")
    analysis, _ = cards(render_detail(r, ov, official, "1X2", data))
    text = _text(analysis)
    for phrase in (
        "Won · drawn · lost",
        "Points part = 2.5 × points ÷ 15",
        "Goal-difference part",
        "Diski Form Score (0–5)",
        "Only matches played before kickoff",
    ):
        assert phrase in text, phrase
    b = r["teams"]["home"]["form"]["breakdown"]
    assert f"2.5 × {b['points']}/15 = {b['points_component_display']}" in text
    r, ov, official = data.detail(EPL_FIX, "overall")
    btts, _ = cards(render_detail(r, ov, official, "BTTS", data))
    t = _text(btts)
    assert "League BTTS baseline" in t and "current-season matches in this competition" in t


def test_psl_market_card_is_small_and_honest(data):
    r, ov, official = data.detail(PSL_FIX, "venue")
    for market in MARKETS:
        _, card = cards(render_detail(r, ov, official, market, data))
        assert "compact" in card.className
        assert "No bookmaker odds are available for the PSL" in _text(card)
        assert "%" not in _text(card)


BROWSER = """
const { chromium, devices } = require('playwright');
const state = (p) => p.evaluate(() =>
  [...document.querySelectorAll('.analysis details.acc')].map(d => d.open));
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
    await p.waitForSelector('.analysis', { timeout: 20000 });
    const r = {};
    r.titles = await p.evaluate(() =>
      [...document.querySelectorAll('.detail .card-head h3')].map(h => h.innerText));
    const acc = p.locator('.analysis details.acc > summary');
    r.closed = await state(p);
    await acc.nth(0).click(); r.firstOpen = await state(p);
    await acc.nth(1).click(); r.bothOpen = await state(p);
    await acc.nth(0).click(); r.secondOnly = await state(p);
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
def test_browser_cards_accordions_and_mobile(data):
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
            assert r["titles"] == ["Diski 9 Match Analysis", "Bookmaker Market Reference"]
            assert r["closed"] == [False, False]
            assert r["firstOpen"] == [True, False]
            assert r["bothOpen"] == [True, True]  # independently expandable
            assert r["secondOnly"] == [False, True]
            assert r["summaryHeight"] >= 44  # comfortable touch target
            assert r["overflow"] <= 0
    finally:
        server.shutdown()
