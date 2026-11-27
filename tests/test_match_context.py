# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Section B match-context adjustment, its integration with Sections C and D,
right-aligned Section D inputs and the two-column Bookmaker Market Reference card."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from dash import html
from sqlalchemy import text

from diski9.app import ScreenerData, create_app
from diski9.app.app import lab_update
from diski9.app.lab import (
    CONTEXT_ADJUST_NOTE,
    baseline_rounded,
    breakdown,
    has_adjustment,
    lab_outputs,
    render_detail,
    user_estimates,
)
from diski9.screener import goal_model as gm

from .test_app import DAY, EPL_FIX, PSL_FIX, T0, _find, _free_port, _text, data, populated  # noqa: F401

CSS = (Path(__file__).parents[1] / "src/diski9/app/assets/style.css").read_text()


def _r(data, fid=EPL_FIX):
    return data.detail(fid)[0]


def _ctx(r, home=None, away=None, state=None):
    if home is not None:
        state, _ = lab_update(r, "ctx-home", home, state)
    if away is not None:
        state, _ = lab_update(r, "ctx-away", away, state)
    return state


# ---------------------------------------------------------------- Section B
def test_section_b_defaults_labels_and_education(data):
    r, ov, off = data.detail(EPL_FIX)
    d = render_detail(r, ov, off, "1X2", data)
    acc = _find(d, lambda c: isinstance(c, html.Details) and "ctx-acc" in c.className)
    assert len(acc) == 1 and not getattr(acc[0], "open", False)
    t = " ".join(_text(acc[0]).split())
    assert t.startswith("Your Match Context Adjustment Your assumptions")
    assert CONTEXT_ADJUST_NOTE in t and "partly reflected in the model's estimated goals" in t
    assert "not a validated effect size" in t and "leave them at 0.00" in t
    # static guidance replaces the former free-text reason box
    assert "Why are you making this adjustment?" not in t
    assert not _find(acc[0], lambda c: getattr(c, "id", None) == "ctx-note")
    boxes = {
        c.id: c.value
        for c in _find(acc[0], lambda c: getattr(c, "id", None) in ("ctx-home", "ctx-away"))
    }
    assert boxes == {"ctx-home": "0.00", "ctx-away": "0.00"}
    assert _find(acc[0], lambda c: getattr(c, "id", None) == "ctx-clear")
    # it sits in Section B, which stays labelled as context
    ctx_section = [
        c for c in d.children[1].children if "context" in str(getattr(c, "className", ""))
    ][0]
    assert "Context" in _text(ctx_section.children[0]) and acc[0] in _find(
        ctx_section, lambda c: isinstance(c, html.Details) and "ctx-acc" in c.className
    )


def test_section_b_positive_negative_and_signed_display(data):
    r = _r(data)
    base = baseline_rounded(r)
    st = _ctx(r, home="0.15", away="-0.20")
    b = breakdown(base, st)
    assert b["home"]["context"] == 0.15 and b["away"]["context"] == -0.20
    assert b["home"]["final"] == round(base["home"] + 0.15, 2)
    assert b["away"]["final"] == round(base["away"] - 0.20, 2)
    d = render_detail(r, *data.detail(EPL_FIX)[1:], "1X2", data, st)
    vals = {
        c.id: c.value
        for c in _find(d, lambda c: getattr(c, "id", None) in ("ctx-home", "ctx-away"))
    }
    assert vals == {"ctx-home": "+0.15", "ctx-away": "-0.20"}
    assert "Home +0.15 · Away -0.20" in _text(d)


def test_brief_example_and_direct_edit(data):
    r = _r(data)
    base = baseline_rounded(r)
    st = _ctx(r, home="+0.10")
    st, _ = lab_update(r, {"type": "cat-adj", "cat": "squad", "side": "home"}, "-0.20", st)
    target = round(base["home"] + 0.10 - 0.20 - 0.05, 2)
    st, _ = lab_update(r, "lab-home-input", f"{target:.2f}", st)
    b = breakdown(base, st)["home"]
    assert (b["context"], b["cats"], b["manual"], b["final"]) == (0.10, -0.20, -0.05, target)
    # changing Section B keeps the manual adjustment and moves the final estimate
    st2, _ = lab_update(r, "ctx-home", "0.30", st)
    b2 = breakdown(base, st2)["home"]
    assert b2["manual"] == -0.05 and b2["final"] == round(target + 0.20, 2)
    # teams are independent
    assert breakdown(base, st2)["away"]["final"] == base["away"]


def test_section_b_validation_explained(data):
    r = _r(data)
    st = _ctx(r, home="0.40")
    for bad in ("1.05", "-1.5", "abc"):
        st2, msg = lab_update(r, "ctx-home", bad, st)
        assert st2 == st and "between -1.00 and +1.00" in msg[0]
    cleared, msg = lab_update(r, "ctx-home", "", st)
    assert cleared["context"]["home"] == 0.0 and msg == []


def test_clear_section_b_only_and_reset(data):
    r = _r(data)
    st = _ctx(r, home="0.25", away="-0.10")
    st, _ = lab_update(r, {"type": "cat-adj", "cat": "fitness", "side": "away"}, "0.10", st)
    st, _ = lab_update(r, "lab-home-input", "2.40", st)
    manual = st["manual"]["home"]
    cleared, _ = lab_update(r, "ctx-clear", 1, st)
    assert cleared["context"]["home"] == cleared["context"]["away"] == 0.0
    assert cleared["cats"]["fitness"]["away"] == 0.10 and cleared["manual"]["home"] == manual
    reset, _ = lab_update(r, "lab-reset", 1, st)
    assert not has_adjustment(reset)
    d = render_detail(r, *data.detail(EPL_FIX)[1:], "1X2", data, reset)
    assert "notes" not in _text(d).lower().split("clears every adjustment")[-1][:120]


def test_boundaries_zero_to_ten(data):
    r = _r(data)
    base = baseline_rounded(r)
    st = _ctx(r, away="-1.00")
    for cat in ("squad", "fitness", "tactics", "conditions"):
        st, _ = lab_update(r, {"type": "cat-adj", "cat": cat, "side": "away"}, "-2", st)
    b = breakdown(base, st)["away"]
    assert b["final"] == 0.0 and b["clipped"]
    out, _ = lab_outputs(r, "1X2", None, st)
    assert "held at 0.00" in _text(out)
    st2, msg = lab_update(r, "lab-home-input", "10.5", st)
    assert msg and breakdown(base, st2)["home"]["final"] == breakdown(base, st)["home"]["final"]


def test_all_seven_recalculated_and_baseline_untouched(data):
    r = _r(data)
    before = copy.deepcopy(r["goal_model"])
    st = _ctx(r, home="0.20", away="-0.15")
    est = user_estimates(r, st)
    mine = gm.markets(est["home"], est["away"])
    out, compare = lab_outputs(r, "OU25", data.detail(EPL_FIX)[1], st)
    t = _text(out)
    for k in ("home", "draw", "away", "btts_yes", "btts_no", "over", "under"):
        assert f"{mine[k] * 100:.1f}%" in t
    # the bookmaker card compares the model baseline; Section D uses your probability
    assert f"{before['probabilities']['over'] * 100:.1f}%" in _text(compare)
    assert f"{mine['over'] * 100:.1f}%" in _text(out.children[-1])  # Your value check
    assert r["goal_model"] == before
    eg = before["estimated_goals"]
    assert before["probabilities"] == pytest.approx(gm.markets(eg["home"], eg["away"]))


def test_per_fixture_isolation_and_market_persistence(data):
    app = create_app(data)
    # Phase 6B.2: the detail callback also fills the bookmaker reference container
    # (the Weekly Challenge panel sits between them); [0] is header + Match Lab
    detail = next(v for k, v in app.callback_map.items() if "detail.children" in k)
    f = detail["callback"].__wrapped__
    st = _ctx(_r(data), home="0.35")
    lab = {str(EPL_FIX): st}
    for market in ("1X2", "BTTS", "OU25"):
        d = f(EPL_FIX, market, "/lab", "all", lab)[0]  # route argument (CP3A-1: /lab)
        box = _find(d, lambda c: getattr(c, "id", None) == "ctx-home")[0]
        assert box.value == "+0.35"
    other = f(PSL_FIX, "1X2", "/lab", "all", lab)[0]
    assert _find(other, lambda c: getattr(c, "id", None) == "ctx-home")[0].value == "0.00"
    layout = app.server.test_client().get("/_dash-layout").get_data(as_text=True)
    assert '"storage_type":"memory"' in layout


def test_lab_actions_never_touch_snapshots(populated):
    d = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    with populated.connect() as conn:
        before = conn.execute(
            text("select count(*), group_concat(lambda_home) from forecast_snapshots")
        ).one()
    r = d.detail(EPL_FIX)[0]
    st = _ctx(r, home="0.5", away="-0.5")
    st, _ = lab_update(r, "lab-home-input", "3.00", st)
    render_detail(r, *d.detail(EPL_FIX)[1:], "1X2", d, st)
    with populated.connect() as conn:
        after = conn.execute(
            text("select count(*), group_concat(lambda_home) from forecast_snapshots")
        ).one()
    assert tuple(before) == tuple(after)


def test_section_b_hidden_without_model(data):
    r = copy.deepcopy(_r(data))
    r["goal_model"] = {"available": False, "message": gm.UEFA_MESSAGE}
    d = render_detail(r, None, {}, "1X2", data, None)
    assert not _find(d, lambda c: getattr(c, "id", None) == "ctx-home")


# ----------------------------------------------- Section D inputs, bookmaker card
def test_section_d_inputs_right_aligned():
    assert (
        ".adj-controls .adj-input .dash-input-element, .adj-controls .adj-input input "
        "{ text-align: right;" in CSS
    )


@pytest.mark.parametrize("market,n", [("1X2", 3), ("BTTS", 2), ("OU25", 2)])
def test_bookmaker_two_column_layout_fresh_and_stale(populated, market, n):
    for clock, stale in ((T0, False), (T0 + 2 * DAY, True)):
        d = ScreenerData(populated, ttl_seconds=0, clock=lambda c=clock: c)
        r, ov, off = d.detail(EPL_FIX)
        card = render_detail(r, ov, off, market, d).children[2]
        grid = _find(card, lambda c: getattr(c, "className", "") == "market-grid")
        assert len(grid) == 1
        main, side = grid[0].children
        assert main.className == "market-main" and side.className == "market-side"
        assert len(_find(main, lambda c: getattr(c, "className", "") == "price-cell")) == n
        assert "Market-implied probabilities" in _text(main)
        assert "independent bookmaker group" in _text(main)
        st = _text(side)
        assert "raw implied probability (1 ÷ odds)" in st and "remove this margin" in st
        assert ("no longer current" in st) is stale
        # the comparison table stays below, full width
        assert card.children[-1].id == "lab-compare"
        assert "Model vs market" in _text(card.children[-1])
    assert (
        ".market-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr)"
        in CSS
    )
    assert "@media (max-width: 900px) {\n  .market-grid { grid-template-columns: 1fr; }" in CSS


def test_missing_odds_card_unchanged(data):
    r, ov, off = data.detail(PSL_FIX)
    for market in ("1X2", "BTTS", "OU25"):
        card = render_detail(r, ov, off, market, data).children[2]
        assert "compact" in card.className
        assert not _find(card, lambda c: getattr(c, "className", "") == "market-grid")
        assert "No bookmaker odds are available" in _text(card)
        assert "Market data unavailable: no bookmaker prices to compare with" in _text(card)


BROWSER = """
const { chromium, devices } = require('playwright');
(async () => {
  const b = await chromium.launch(); const out = {};
  for (const [name, opts] of [['desktop', { viewport: { width: 1400, height: 1000 } }],
                              ['phone', devices['iPhone 13']]]) {
    const p = await (await b.newContext(opts)).newPage();
    const errors = []; p.on('pageerror', e => errors.push(String(e)));
    // F4: wait for the Dash callback a step triggers (identified by its changed
    // property), its response, and any follow-on callbacks, instead of fixed sleeps.
    // On a loaded machine the debounced Section B callback was sent ~0.4-1.1 s after
    // Tab, so a fixed 900 ms read sometimes ran before the update arrived (F4 record).
    const isDash = (q) => q.url().includes('_dash-update-component');
    let inflight = 0, quietSince = Date.now();
    const recent = [];  // the last callbacks, reported only when a check fails
    p.on('request', q => { if (isDash(q)) { inflight++; quietSince = Date.now();
      let ch = []; try { ch = (JSON.parse(q.postData()).changedPropIds || []).slice(0, 3); } catch (e) {}
      recent.push({ t: Date.now(), ch }); if (recent.length > 12) recent.shift(); } });
    p.on('response', x => { if (isDash(x.request()) && x.status() !== 200 && x.status() !== 204)
      recent.push({ t: Date.now(), status: x.status() }); });
    const finished = q => { if (isDash(q)) { inflight--; quietSince = Date.now(); } };
    p.on('requestfinished', finished); p.on('requestfailed', finished);
    const settled = async () => {
      const t0 = Date.now();
      while (Date.now() - t0 < 30000) {
        const loading = await p.evaluate(() => !!document.querySelector('[data-dash-is-loading="true"]'));
        if (inflight === 0 && !loading && Date.now() - quietSince > 400) return;
        await p.waitForTimeout(50);
      }
      throw new Error('Dash callbacks did not settle within 30 s');
    };
    // The request that carries this step's own input: Dash also fires `adjust` for the
    // newly rendered inputs when a fixture opens (every input listed as changed), and
    // on a loaded machine that request can be dispatched late, so matching the changed
    // property alone is not enough; the request must carry the value just entered.
    const carries = (q, prop, ok) => {
      if (!isDash(q)) return false;
      try {
        const body = JSON.parse(q.postData());
        if (!(body.changedPropIds || []).includes(prop)) return false;
        const [id, property] = prop.split('.');
        const v = (body.inputs || []).find(i => i.id === id && i.property === property);
        return !!v && ok(v.value);
      } catch (e) { return false; }
    };
    const roundTrip = async (prop, ok, action) => {
      const t0 = Date.now();
      const resp = p.waitForResponse(x => carries(x.request(), prop, ok), { timeout: 30000 });
      await action(); await resp; await settled();
      return Date.now() - t0;
    };
    // A market change rebuilds the match detail (update_detail); the rebuilt inputs then
    // fire `adjust`, which restores the stored adjustment. Both responses must have
    // arrived before the next step: on a starved browser the rebuild was dispatched
    // seconds after the market callbacks, in a gap with nothing in flight.
    const newMarket = async (value, action) => {
      const rebuilt = p.waitForResponse(x => carries(x.request(), 'market.value', v => v === value) &&
        String(JSON.parse(x.request().postData()).output).includes('detail.children'), { timeout: 30000 });
      const restored = p.waitForResponse(x => carries(x.request(), 'lab-reset.n_clicks', () => true), { timeout: 30000 });
      await action(); await rebuilt; await restored; await settled();
    };
    await p.goto(BASE + 'lab');
    const sel = name === 'phone' ? '.fx-card' : 'tr.row';
    await p.waitForSelector(sel, { timeout: 20000, state: 'visible' });
    await p.locator(sel, { hasText: 'Team 1' }).first().click();
    await p.waitForSelector('#lab-home-input');
    const r = {};
    r.align = await p.evaluate(() => getComputedStyle(document.querySelector('#lab-home-input')).textAlign);
    const base = parseFloat(await p.locator('#lab-home-input').inputValue());
    await p.locator('.ctx-acc summary').click();
    r.ctxMs = await roundTrip('ctx-home.value', v => v === '0.25', async () => {
      await p.locator('#ctx-home').fill('0.25'); await p.locator('#ctx-home').press('Tab'); });
    r.shown = await p.locator('#ctx-home').inputValue();
    r.delta = Math.round((parseFloat(await p.locator('#lab-home-input').inputValue()) - base) * 100) / 100;
    r.layout = {};
    for (const [label, key] of [['Both Teams', 'btts'], ['Over/Under', 'ou25'], ['Match Result', '1x2']]) {
      await p.evaluate(() => window.scrollTo(0, 0));  // the menu opens beside the control
      await p.locator('#market').click(); await p.waitForSelector('[role=option]:visible');
      await p.waitForTimeout(300);  // let the menu finish opening
      const value = { btts: 'BTTS', ou25: 'OU25', '1x2': '1X2' }[key];  // each step changes it
      await newMarket(value, () => p.locator('[role=option]', { hasText: label }).dispatchEvent('click'));
      await p.waitForFunction((l) => document.querySelector('#market').innerText.includes(l), label);
      const m = await p.locator('.market-main').boundingBox();
      const s = await p.locator('.market-side').boundingBox();
      r.layout[key] = { side: s.x > m.x + m.width - 1, kept: await p.locator('#ctx-home').inputValue() };
    }
    r.resetMs = await roundTrip('lab-reset.n_clicks', v => !!v, () => p.locator('#lab-reset').click())
      .catch(e => { r.resetError = String(e).slice(0, 200); });
    await p.waitForFunction(() => document.querySelector('#lab-output').innerText.includes('Showing the model baseline'), null, { timeout: 15000 }).catch(async () => {
      r.debug = await p.locator('#lab-output').innerText();
      r.recent = recent.map(x => ({ ...x, t: x.t - recent[0].t })); });
    r.reset = parseFloat(await p.locator('#lab-home-input').inputValue()) === base;
    r.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    r.errors = errors.length;
    out[name] = r;
  }
  console.log(JSON.stringify(out)); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_section_b_alignment_and_bookmaker_layout(data):
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    port = _free_port()
    server = make_server("127.0.0.1", port, create_app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        time.sleep(0.5)
        script = f"const BASE = 'http://127.0.0.1:{port}/';\n" + BROWSER
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=240)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        for name, side_by_side in (("desktop", True), ("phone", False)):
            r = out[name]
            assert r["align"] == "right", name
            assert r["shown"] == "+0.25" and r["delta"] == 0.25, (name, r)
            for key in ("btts", "ou25", "1x2"):
                assert r["layout"][key]["side"] is side_by_side, (name, key)
                assert r["layout"][key]["kept"] == "+0.25", (name, key)
            assert r["reset"] and r["overflow"] <= 0 and r["errors"] == 0, (name, r)
    finally:
        server.shutdown()


def test_timedelta_import_used():
    assert timedelta(days=1) == DAY


def test_section_b_guidance_comes_before_inputs_like_section_c(data):
    r, ov, off = data.detail(EPL_FIX)
    d = render_detail(r, ov, off, "1X2", data)
    for acc_cls in ("ctx-acc", "cat-acc"):
        acc = _find(d, lambda c, k=acc_cls: isinstance(c, html.Details) and k in c.className)[0]
        split = _find(acc, lambda c: getattr(c, "className", None) == "cat-split")[0]
        left, right = split.children  # guidance column, then the stacked controls
        assert left.className == "cat-guide-col" and _find(
            left, lambda c: "cat-guide" in str(getattr(c, "className", ""))
        ), acc_cls
        assert right.className == "cat-inputs" and len(right.children) == 2, acc_cls
        sides = [
            c.id["side"] if isinstance(c.id, dict) else c.id
            for c in _find(
                right,
                lambda c: (
                    isinstance(getattr(c, "id", None), (str, dict)) and "slider" not in str(c.id)
                ),
            )
        ]
        assert [x.replace("ctx-", "") for x in sides] == ["home", "away"], acc_cls


def test_recent_form_summary_two_columns(data):
    r, ov, off = data.detail(EPL_FIX)
    d = render_detail(r, ov, off, "1X2", data)
    grid = _find(d, lambda c: getattr(c, "className", "") == "form-summary-grid")
    assert len(grid) == 1
    left, right = grid[0].children
    assert "League Form Score average" in _text(left) and "baseline" in left.className
    assert right.className == "recent-summary" and "Recent results" in _text(right)
    assert (
        ".form-summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr))"
        in CSS
    )
    assert (
        "@media (max-width: 760px) {\n  .form-summary-grid { grid-template-columns: 1fr; }" in CSS
    )
