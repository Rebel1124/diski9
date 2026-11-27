# ruff: noqa: F811  (pytest fixtures imported from other test modules are used as arguments)
"""Scenario A3, Checkpoint 3: browser checks of the educational popovers, the general
guidance and the high-risk underdog warning on desktop, tablet and phone, with mouse,
keyboard and touch. Set DISKI9_SHOTS=<dir> to save the screenshots.

The Weekly Challenge demonstration round is built under ``a3-432-v1`` (since
Checkpoint 4C also the no-database default; the test-only patch of the demo
constructor keeps that explicit)."""

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
async function until(p, fn, arg) {
  // wait for the expected state instead of a fixed pause; on timeout the caller's
  // assertion still runs on whatever state the page reached
  try { await p.waitForFunction(fn, arg, { timeout: 15000, polling: 50 }); } catch (e) {}
}
async function shot(p, name) { if (SHOTS) await p.screenshot({ path: `${SHOTS}/${name}.png` }); }
async function openTerm(p, summary, how) {
  // open one popover with the given input method and report its geometry
  await summary.scrollIntoViewIfNeeded();
  if (how === 'mouse') await summary.click();
  else if (how === 'touch') await summary.tap();
  else { await summary.focus(); await p.keyboard.press('Enter'); }
  await summary.evaluate((s) => new Promise((ok) => {
    const t0 = Date.now();
    (function poll() { if (s.parentElement.open || Date.now() - t0 > 15000) ok(); else setTimeout(poll, 50); })();
  }));
  await p.waitForTimeout(150);  // let the positioning script settle
  return await summary.evaluate((s) => {
    const d = s.parentElement, pop = d.querySelector('.info-pop').getBoundingClientRect();
    return { open: d.open, left: pop.left, right: pop.right, top: pop.top, bottom: pop.bottom,
             w: window.innerWidth, h: window.innerHeight, text: d.querySelector('.info-pop').innerText };
  });
}
async function escapeClose(p) {
  await p.keyboard.press('Escape');
  await until(p, () => !document.querySelector('details.term-info[open]'));
  return await p.evaluate(() => ({
    open: document.querySelectorAll('details.term-info[open]').length,
    focusOnIcon: document.activeElement && document.activeElement.tagName === 'SUMMARY',
  }));
}
async function targets(p, scope) {
  // rendered size of every visible educational button in scope, and the smallest
  // gap between two buttons on the same line (negative = overlap)
  return await p.evaluate((scope) => {
    const els = [...document.querySelectorAll(scope + ' details.term-info > summary')]
      .filter((e) => e.offsetParent !== null);
    const rs = els.map((e) => e.getBoundingClientRect());
    let gap = 1e9;
    for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) {
      const a = rs[i], b = rs[j];
      if (a.bottom > b.top && b.bottom > a.top) gap = Math.min(gap, Math.max(b.left - a.right, a.left - b.right));
    }
    return { n: rs.length, minW: Math.min(...rs.map((r) => r.width)), minH: Math.min(...rs.map((r) => r.height)),
             maxW: Math.max(...rs.map((r) => r.width)), maxH: Math.max(...rs.map((r) => r.height)), gap };
  }, scope);
}
async function legend(p) {
  // each label + button + colon group renders on one line; the sentence itself may wrap
  return await p.evaluate(() => {
    const el = document.querySelector('.ch-legend');
    const groups = [...el.querySelectorAll('.term-keep')];
    const lh = parseFloat(getComputedStyle(el).lineHeight) || 18;
    return { groups: groups.length, text: groups.map((g) => g.innerText.replace(/\s+/g, '')),
             split: groups.filter((g) => g.getClientRects().length !== 1).length,
             overflow: el.scrollWidth - el.clientWidth, lines: Math.round(el.getBoundingClientRect().height / lh),
             page: document.documentElement.scrollWidth - window.innerWidth };
  });
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
    await p.goto(BASE);  // CP3A-2: open the challenge list (Research only OFF)
    await p.waitForSelector('#research-only'); if (await p.locator('#research-only input').isChecked()) { await p.locator('.pb-switch-label').click(); } await p.waitForSelector('.ch-page', { state: 'visible' });
    await press(p.locator(sel({ m: 'demo', t: 'mode' })));
    await p.waitForSelector('text=Demonstration round.'); await idle();
    await p.locator('.ch-legend').scrollIntoViewIfNeeded();
    await shot(p, `${name}-builder-closed`);
    r.legendTerms = await p.locator('.ch-legend details.term-info').count();
    r.targets = await targets(p, '.ch-legend');
    r.legend = await legend(p);
    if (name === 'phone') {  // narrow-width sweep of the legend
      r.sweep = [];
      for (const w of [320, 340, 360, 375, 390, 414, 430, 480]) {
        await p.setViewportSize({ width: w, height: 844 }); await p.waitForTimeout(120);
        r.sweep.push({ w, ...(await legend(p)) });
      }
      await p.setViewportSize({ width: 390, height: 664 }); await p.waitForTimeout(150);
      await p.locator('.ch-legend').scrollIntoViewIfNeeded();
    }
    r.guidance = await p.locator('.model-guidance').count();
    r.mkt = await openTerm(p, p.locator('.ch-legend details.term-info > summary').first(), how);
    await shot(p, `${name}-builder-popover-open`);
    r.closed = await escapeClose(p);
    // the second term then the first: only one open at a time
    await press(p.locator('.ch-legend details.term-info > summary').nth(1));
    await until(p, () => document.querySelectorAll('.ch-legend details.term-info')[1].open);
    await press(p.locator('.ch-legend details.term-info > summary').nth(0));
    await until(p, () => document.querySelectorAll('.ch-legend details.term-info')[0].open
      && !document.querySelectorAll('.ch-legend details.term-info')[1].open);
    r.oneOpen = await p.locator('details.term-info[open]').count();
    await p.keyboard.press('Escape');
    await until(p, () => !document.querySelector('details.term-info[open]'));
    await press(p.locator('.model-guidance > summary'));
    await until(p, () => document.querySelector('.model-guidance').open);
    r.guidanceText = await p.locator('.model-guidance').innerText();
    await shot(p, `${name}-builder-guidance-open`);
    await press(p.locator('.model-guidance > summary'));
    // select the portfolio with two high-risk underdogs
    for (let i = 0; i < KEYS.length; i++) {
      await press(p.locator(sel({ k: KEYS[i], t: 'pick' }))); await idle();
      await until(p, (n) => (document.querySelector('.ch-total') || {}).innerText === `${n}/9`, i + 1);
    }
    await until(p, () => document.querySelectorAll('.ch-risk-panel').length === 1);
    r.total = await p.locator('.ch-total').innerText();
    r.cardTags = await p.locator('.ch-risk-tag').count();
    r.trackerPanels = await p.locator('.ch-risk-panel').count();
    r.trackerText = await p.locator('.ch-risk-panel').first().innerText();
    await p.locator('.ch-risk-panel').first().scrollIntoViewIfNeeded();
    await shot(p, `${name}-tracker-warning`);
    await press(p.locator('.ch-risk-panel details > summary').first());
    await until(p, () => document.querySelector('.ch-risk-panel details').open);
    r.whyText = await p.locator('.ch-risk-panel').first().innerText();
    await shot(p, `${name}-tracker-warning-open`);
    // deselect one high-risk pick, then the other, then select both again
    await press(p.locator(sel({ k: RISKY[0], t: 'pick' }))); await idle();
    await until(p, () => /Includes a high-risk underdog/.test((document.querySelector('.ch-risk-panel') || {}).innerText || ''));
    r.afterOne = await p.locator('.ch-risk-panel').first().innerText();
    await press(p.locator(sel({ k: RISKY[1], t: 'pick' }))); await idle();
    await until(p, () => !document.querySelector('.ch-risk-panel'));
    r.afterBoth = await p.locator('.ch-risk-panel').count();
    for (const k of RISKY) { await press(p.locator(sel({ k, t: 'pick' }))); await idle(); }
    await until(p, () => /2 high-risk underdogs/.test((document.querySelector('.ch-risk-panel') || {}).innerText || ''));
    r.reselected = await p.locator('.ch-risk-panel').count();
    r.overflowBuilder = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    // final review
    await press(p.locator(sel({ i: 'stepper', t: 'nav', to: 'review' }))); await idle();
    await p.waitForSelector('.ch-risk-review');
    r.reviewPanels = await p.locator('.ch-risk-panel').count();
    r.reviewTerms = await p.locator('.ch-table th details.term-info').count();
    r.reviewTargets = await targets(p, '.ch-table');
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
    await p.goto(BASE + 'lab'); await p.waitForSelector('#direction', { timeout: 20000 });
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
    r.labTargets = await targets(p, '#lab-compare');
    r.labHeads = await p.$$eval('#lab-compare th', (ths) => ths.map((t) => t.innerText.replace(/\s+/g, ' ').replace(/ ?i$/, '').trim()));
    // the five buttons line up: same top (spread in px) and, per column, flush right
    const geo = await p.$$eval('#lab-compare th details.term-info > summary', (ss) => ss.map((s) => {
      const r = s.getBoundingClientRect(), th = s.closest('th').getBoundingClientRect();
      const pad = parseFloat(getComputedStyle(s.closest('th')).paddingRight);
      return { top: r.top, right: th.right - pad - r.right };
    }));
    r.labIconTop = Math.max(...geo.map((g) => g.top)) - Math.min(...geo.map((g) => g.top));
    r.labIconRight = Math.max(...geo.map((g) => Math.abs(g.right)));
    r.rankTargets = await targets(p, 'label');
    r.compareScroll = await p.evaluate(() => {
      const el = document.querySelector('#lab-compare .scroll-x');
      return el.scrollWidth - el.clientWidth; });
    r.labGuidance = await p.locator('.model-guidance').count();
    await p.locator('#lab-compare').scrollIntoViewIfNeeded();
    await shot(p, `${name}-matchlab-closed`);
    const terms = p.locator('#lab-compare th details.term-info > summary');
    r.labPops = [];
    for (let i = 0; i < 5; i++) {
      r.labPops.push(await openTerm(p, terms.nth(i), how));
      if (i === 3) await shot(p, `${name}-matchlab-odds-popover-open`);  // Odds
      if (i === 4) await shot(p, `${name}-matchlab-popover-open`);  // EV
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


MIN_TARGET = 24  # CSS px, WCAG 2.2 target size (minimum)


def _target_ok(t: dict, n: int, where: str) -> None:
    """Every educational button renders at least 24 x 24 CSS px and no two overlap."""
    assert t["n"] == n, (where, t)
    assert t["minW"] >= MIN_TARGET and t["minH"] >= MIN_TARGET, (where, t)
    assert t["gap"] >= 0, (where, t)


def _run(script: str) -> dict:
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=420)
    assert res.returncode == 0, res.stderr[-3000:]
    out = json.loads(res.stdout.strip().splitlines()[-1])
    if os.environ.get("DISKI9_MEASURE"):  # optional: append the raw measurements
        with open(os.environ["DISKI9_MEASURE"], "a") as fh:
            fh.write(json.dumps(out) + "\n")
    return out


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
        _target_ok(r["targets"], 2, name)
        _target_ok(r["reviewTargets"], 2, name)
        lg = r["legend"]
        assert lg["groups"] == 2 and lg["text"] == ["Mkti:", "D9i:"], (name, lg)
        assert lg["split"] == 0 and lg["overflow"] <= 0 and lg["page"] <= 0, (name, lg)
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
    phone = out["phone"]
    assert len(phone["sweep"]) == 8
    for lg in phone["sweep"]:  # label, button and colon stay together; the text wraps
        assert lg["split"] == 0 and lg["overflow"] <= 0 and lg["page"] <= 0, lg
    assert min(lg["lines"] for lg in phone["sweep"]) >= 2  # wraps naturally on phones


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
        assert r["labTerms"] == 5 and r["labGuidance"] == 1, name
        assert r["labHeads"] == ["Outcome", "Model", "Market", "Edge", "Odds", "EV"], name
        assert r["labIconTop"] <= 1 and r["labIconRight"] <= 1, (name, r)  # aligned icons
        _target_ok(r["labTargets"], 5, name)
        _target_ok(r["rankTargets"], 1, name)
        assert r["compareScroll"] <= 0, (name, r["compareScroll"])  # every column visible
        for pop in r["labPops"]:
            assert _inside(pop), (name, pop)  # inside the scrolling table, still on screen
        assert "review the match factors on this page" in r["labGuidanceText"]
        assert r["overflow"] <= 0, name
