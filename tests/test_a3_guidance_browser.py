# ruff: noqa: F811  (pytest fixtures imported from other test modules are used as arguments)
"""Scenario A3, Checkpoint 3: browser checks of the educational popovers, the general
guidance and the high-risk underdog warning on desktop, tablet and phone, with mouse,
keyboard and touch. Set DISKI9_SHOTS=<dir> to save the screenshots.

The Weekly Challenge demonstration round is built under the REGISTERED (inactive)
``a3-432-v1`` configuration by a test-only patch of the demo constructor; nothing is
activated, DEFAULT_CONFIG and every schedule are unchanged."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time

import pytest

from diski9.app.challenge import service as service_mod
from diski9.challenge.config import A3_432_V1

from .test_a3_guidance import a3_keys
from .test_app import _free_port, data, populated  # noqa: F401
from .test_market_value import valued  # noqa: F401

NODE = shutil.which("node") is not None


def _node_ok() -> bool:
    return (
        NODE
        and not subprocess.run(
            ["node", "-e", "require('playwright')"], capture_output=True
        ).returncode
    )


def _serve(app):
    from werkzeug.serving import make_server

    port = _free_port()
    server = make_server("127.0.0.1", port, app.server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.4)
    return server, port


COMMON = r"""
const { chromium, devices } = require('playwright');
const VIEWS = [
  ['desktop', { viewport: { width: 1366, height: 900 } }, 'mouse'],
  ['tablet', { ...devices['iPad Mini'] }, 'keyboard'],
  ['phone', { ...devices['iPhone 13'] }, 'touch'],
];
async function shot(p, name) { if (SHOTS) await p.screenshot({ path: `${SHOTS}/${name}.png` }); }
async function openTerm(p, summary, how) {
  // open one popover with the given input method and report its geometry
  await summary.scrollIntoViewIfNeeded();
  if (how === 'mouse') await summary.click();
  else if (how === 'touch') await summary.tap();
  else { await summary.focus(); await p.keyboard.press('Enter'); }
  await p.waitForTimeout(250);
  return await summary.evaluate((s) => {
    const d = s.parentElement, pop = d.querySelector('.info-pop').getBoundingClientRect();
    return { open: d.open, left: pop.left, right: pop.right, top: pop.top, bottom: pop.bottom,
             w: window.innerWidth, h: window.innerHeight, text: d.querySelector('.info-pop').innerText };
  });
}
async function escapeClose(p) {
  await p.keyboard.press('Escape'); await p.waitForTimeout(150);
  return await p.evaluate(() => ({
    open: document.querySelectorAll('details.term-info[open]').length,
    focusOnIcon: document.activeElement && document.activeElement.tagName === 'SUMMARY',
  }));
}
"""

CHALLENGE = r"""
const sel = (o) => `[id='${JSON.stringify(o)}']`;
(async () => {
  const b = await chromium.launch();
  const res = {};
  for (const [name, opts, how] of VIEWS) {
    const ctx = await b.newContext(opts);
    const p = await ctx.newPage();
    const r = { errors: [] };
    p.on('pageerror', e => r.errors.push(e.message));
    const idle = async () => { await p.waitForTimeout(350); await p.waitForLoadState('networkidle'); };
    const press = async (loc) => { if (how === 'touch') await loc.tap(); else await loc.click(); };
    await p.goto(BASE + 'challenge'); await p.waitForSelector('.ch-page');
    await press(p.locator(sel({ m: 'demo', t: 'mode' })));
    await p.waitForSelector('text=Demonstration round.'); await idle();
    await p.locator('.ch-legend').scrollIntoViewIfNeeded();
    await shot(p, `${name}-builder-closed`);
    r.legendTerms = await p.locator('.ch-legend details.term-info').count();
    r.guidance = await p.locator('.model-guidance').count();
    r.mkt = await openTerm(p, p.locator('.ch-legend details.term-info > summary').first(), how);
    await shot(p, `${name}-builder-popover-open`);
    r.closed = await escapeClose(p);
    // the second term then the first: only one open at a time
    await press(p.locator('.ch-legend details.term-info > summary').nth(1)); await p.waitForTimeout(150);
    await press(p.locator('.ch-legend details.term-info > summary').nth(0)); await p.waitForTimeout(150);
    r.oneOpen = await p.locator('details.term-info[open]').count();
    await p.keyboard.press('Escape');
    await press(p.locator('.model-guidance > summary')); await p.waitForTimeout(200);
    r.guidanceText = await p.locator('.model-guidance').innerText();
    await shot(p, `${name}-builder-guidance-open`);
    await press(p.locator('.model-guidance > summary'));
    // select the portfolio with two high-risk underdogs
    for (const k of KEYS) { await press(p.locator(sel({ k, t: 'pick' }))); await idle(); }
    r.total = await p.locator('.ch-total').innerText();
    r.cardTags = await p.locator('.ch-risk-tag').count();
    r.trackerPanels = await p.locator('.ch-risk-panel').count();
    r.trackerText = await p.locator('.ch-risk-panel').first().innerText();
    await p.locator('.ch-risk-panel').first().scrollIntoViewIfNeeded();
    await shot(p, `${name}-tracker-warning`);
    await press(p.locator('.ch-risk-panel details > summary').first()); await p.waitForTimeout(200);
    r.whyText = await p.locator('.ch-risk-panel').first().innerText();
    await shot(p, `${name}-tracker-warning-open`);
    // deselect one high-risk pick, then the other, then select both again
    await press(p.locator(sel({ k: RISKY[0], t: 'pick' }))); await idle();
    r.afterOne = await p.locator('.ch-risk-panel').first().innerText();
    await press(p.locator(sel({ k: RISKY[1], t: 'pick' }))); await idle();
    r.afterBoth = await p.locator('.ch-risk-panel').count();
    for (const k of RISKY) { await press(p.locator(sel({ k, t: 'pick' }))); await idle(); }
    r.reselected = await p.locator('.ch-risk-panel').count();
    r.overflowBuilder = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    // final review
    await press(p.locator(sel({ i: 'stepper', t: 'nav', to: 'review' }))); await idle();
    await p.waitForSelector('.ch-risk-review');
    r.reviewPanels = await p.locator('.ch-risk-panel').count();
    r.reviewTerms = await p.locator('.ch-table th details.term-info').count();
    await p.locator('.ch-risk-review').scrollIntoViewIfNeeded();
    await shot(p, `${name}-review-closed`);
    r.reviewPop = await openTerm(p, p.locator('.ch-table th details.term-info > summary').first(), how);
    await shot(p, `${name}-review-popover-open`);
    await p.keyboard.press('Escape');
    r.overflowReview = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    res[name] = r;
    await ctx.close();
  }
  console.log(JSON.stringify(res));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""

LAB = r"""
(async () => {
  const b = await chromium.launch();
  const res = {};
  for (const [name, opts, how] of VIEWS) {
    const ctx = await b.newContext(opts);
    const p = await ctx.newPage();
    const r = { errors: [] };
    p.on('pageerror', e => r.errors.push(e.message));
    await p.goto(BASE); await p.waitForSelector('#direction', { timeout: 20000 });
    await p.waitForTimeout(800);
    r.rankTerms = await p.locator('label details.term-info').count();
    await shot(p, `${name}-screener-closed`);
    r.rank = await openTerm(p, p.locator('label details.term-info > summary').first(), how);
    await shot(p, `${name}-screener-popover-open`);
    r.rankClosed = await escapeClose(p);
    const row = p.locator('table.results tr.row').first();
    if (await row.isVisible()) await row.click(); else await p.locator('.fx-card').first().click();
    await p.waitForSelector('#lab-compare table', { timeout: 20000 });
    await p.waitForTimeout(500);
    r.labTerms = await p.locator('#lab-compare th details.term-info').count();
    r.labGuidance = await p.locator('.model-guidance').count();
    await p.locator('#lab-compare').scrollIntoViewIfNeeded();
    await shot(p, `${name}-matchlab-closed`);
    const terms = p.locator('#lab-compare th details.term-info > summary');
    r.labPops = [];
    for (let i = 0; i < 4; i++) {
      r.labPops.push(await openTerm(p, terms.nth(i), how));
      if (i === 3) await shot(p, `${name}-matchlab-popover-open`);
      await p.keyboard.press('Escape'); await p.waitForTimeout(100);
    }
    await p.locator('.model-guidance > summary').click(); await p.waitForTimeout(200);
    r.labGuidanceText = await p.locator('.model-guidance').innerText();
    await shot(p, `${name}-matchlab-guidance-open`);
    r.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    res[name] = r;
    await ctx.close();
  }
  console.log(JSON.stringify(res));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def _inside(pop) -> bool:
    return (
        pop["open"]
        and pop["left"] >= 0
        and pop["right"] <= pop["w"]
        and pop["top"] >= 0
        and (pop["bottom"] <= pop["h"])
    )


def _run(script: str) -> dict:
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=420)
    assert res.returncode == 0, res.stderr[-3000:]
    return json.loads(res.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="node not available")
def test_browser_challenge_guidance_terms_and_underdog_warning(data, monkeypatch):
    if not _node_ok():
        pytest.skip("playwright for node not available")
    from diski9.app import create_app
    from diski9.app.challenge.service import ChallengeService

    monkeypatch.setattr(service_mod, "DEFAULT_CONFIG", A3_432_V1)  # demo round only (test)

    snap = ChallengeService(data).demo()
    assert snap.config is A3_432_V1
    keys, risky = a3_keys(snap, 2, {f.fixture_id for f in snap.fixtures[:10]})
    risky_keys = [f"{o.fixture_id}|{o.market}|{o.outcome}" for o in risky]
    server, port = _serve(create_app(data))
    shots = os.environ.get("DISKI9_SHOTS", "")
    try:
        head = (
            f"const BASE = 'http://127.0.0.1:{port}/'; const SHOTS = {json.dumps(shots)};\n"
            f"const KEYS = {json.dumps(keys)}; const RISKY = {json.dumps(risky_keys)};\n"
        )
        out = _run(head + COMMON + CHALLENGE)
    finally:
        server.shutdown()
    for name in ("desktop", "tablet", "phone"):
        r = out[name]
        assert r["errors"] == [], (name, r["errors"])
        assert r["legendTerms"] == 2 and r["guidance"] == 1, name
        assert _inside(r["mkt"]), (name, r["mkt"])  # never clipped, mouse/keyboard/touch
        assert "Market Probability" in r["mkt"]["text"]
        assert r["closed"] == {"open": 0, "focusOnIcon": True}, name  # Escape returns focus
        assert r["oneOpen"] == 1, name
        assert "explore the Match Lab" in r["guidanceText"]
        assert r["total"] == "9/9", name
        assert r["cardTags"] >= 2, name
        assert r["trackerPanels"] == 1 and "2 high-risk underdogs" in r["trackerText"], name
        assert "often assigned higher probabilities to underdogs" in r["whyText"]
        assert "a high-risk underdog" in r["afterOne"] and r["afterBoth"] == 0, name
        assert r["reselected"] == 1, name
        assert r["reviewPanels"] == 1 and r["reviewTerms"] == 2, name
        assert _inside(r["reviewPop"]), (name, r["reviewPop"])
        assert r["overflowBuilder"] <= 0 and r["overflowReview"] <= 0, name


@pytest.mark.skipif(not NODE, reason="node not available")
def test_browser_screener_and_match_lab_terms(valued):
    if not _node_ok():
        pytest.skip("playwright for node not available")
    from diski9.app import create_app

    server, port = _serve(create_app(valued))
    shots = os.environ.get("DISKI9_SHOTS", "")
    try:
        head = f"const BASE = 'http://127.0.0.1:{port}/'; const SHOTS = {json.dumps(shots)};\n"
        out = _run(head + COMMON + LAB)
    finally:
        server.shutdown()
    for name in ("desktop", "tablet", "phone"):
        r = out[name]
        assert r["errors"] == [], (name, r["errors"])
        assert r["rankTerms"] == 1, name
        assert (
            _inside(r["rank"])
            and "Edge" in r["rank"]["text"]
            and "Expected Value" in r["rank"]["text"]
        ), (name, r["rank"])
        assert r["rankClosed"]["open"] == 0, name
        assert r["labTerms"] == 4 and r["labGuidance"] == 1, name
        for pop in r["labPops"]:
            assert _inside(pop), (name, pop)  # inside the scrolling table, still on screen
        assert "review the match factors on this page" in r["labGuidanceText"]
        assert r["overflow"] <= 0, name
