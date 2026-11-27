# ruff: noqa: F811  (pytest fixtures imported from other test modules are used as arguments)
"""Final UI refinements to the market edge & EV enhancement: outcome colours in the
Screener, the side-by-side Section D tables and the compact Section B / C sliders.
Presentation only - model, odds, edge and EV calculations are unchanged."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from dash import html

from diski9.app import create_app
from diski9.app.app import lab_update, results_payload
from diski9.app.data import MARKET_OF
from diski9.app.lab import (
    CATEGORY_KEYS,
    CATEGORY_MAX,
    CONTEXT_MAX,
    baseline_rounded,
    breakdown,
    lab_outputs,
    render_detail,
    slider_value,
    user_estimates,
)
from diski9.odds.value import edge_text, ev_text
from diski9.screener import goal_model as gm

from .test_app import EPL_FIX, _find, _free_port, _text, data, populated  # noqa: F401
from .test_market_value import valued  # noqa: F401
from .test_match_lab import _call, _trigger

ASSETS = Path(__file__).parents[1] / "src/diski9/app/assets"
CSS = (ASSETS / "style.css").read_text()
OUT = {"Home": "home", "Draw": "draw", "Away": "away"}


# ------------------------------------------------------- 1. outcome colours
def test_outcome_palette_defined_and_shared():
    for name, hexv in (("home", "#60a5fa"), ("draw", "#36c9a8"), ("away", "#e5ae52")):
        assert f"--out-{name}: {hexv};" in CSS
        assert f".seg-{name} {{ background: var(--out-{name}); }}" in CSS  # market bar too
        assert (
            f".value-cell.v-pos.v-out-{name} .v-main, .card-value.v-pos.v-out-{name} "
            f"{{ color: var(--out-{name}); }}" in CSS
        )


def _cells(d, market, direction, page=1):
    p = results_payload(d, market, [39, 288], None, "2026-12-31", "overall", direction, 0, page)
    return [row.children[-1] for row in p[0].children[1].children]


@pytest.mark.parametrize("direction", ["edge", "ev", "kickoff_earliest", "home_win"])
def test_positive_1x2_picks_take_their_outcome_colour(valued, direction):
    seen = set()
    for page in (1, 2):
        for td in _cells(valued, "1X2", direction, page):
            cls, text = td.className, _text(td)
            out = re.findall(r"v-out-(\w+)", cls)
            if "v-pos" in cls:
                label = text.split()[0]
                assert out == [OUT[label]], (cls, text)  # colour = the named outcome
                seen.add(out[0])
            else:  # negative, zero, missing, incomplete or stale: neutral
                assert not out, (cls, text)
    assert seen  # the test data has positive picks


def test_two_way_markets_and_neutral_states_are_not_outcome_coloured(valued, populated):
    for market in ("BTTS", "OU25"):
        for direction in ("edge", "ev"):
            assert all("v-out-" not in td.className for td in _cells(valued, market, direction))
    from datetime import timedelta

    from diski9.app import ScreenerData

    from .factories import T0

    stale = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0 + timedelta(days=2))
    cell = stale.value_cell("1X2", stale.detail(EPL_FIX)[0], "edge")
    assert cell["main"] == "Prices stale" and cell["outcome"] is None


def test_cell_values_unchanged_by_colouring(valued):
    snap = valued.snapshot()
    for r in snap.results["overall"].values():
        for direction in ("edge", "ev"):
            cell = valued.value_cell("1X2", r, direction)
            _, pick = valued.value_pick("1X2", r, direction, None)
            if pick is None:
                assert cell["outcome"] is None
                continue
            assert cell["outcome"] == pick.key  # home / draw / away
            text = edge_text(pick.edge) if direction == "edge" else ev_text(pick.ev)
            assert text in cell["main"]


def test_mobile_card_uses_outcome_colour(valued):
    from diski9.app.app import fixture_card

    r = next(
        r
        for r in valued.snapshot().results["overall"].values()
        if valued.value_pick("1X2", r, "ev", None)[1] is not None
    )
    row = valued.row("1X2", r) | {"value": valued.value_cell("1X2", r, "ev")}
    card = fixture_card("1X2", row, None)
    spans = _find(card, lambda c: "card-value" in (getattr(c, "className", "") or ""))
    assert spans and f"v-out-{row['value']['outcome']}" in spans[0].className


# ------------------------------------------------- 2. Section D side by side
def test_section_d_tables_side_by_side_with_everything_kept(data):
    r, ov, _ = data.detail(EPL_FIX)
    st, _ = lab_update(r, "lab-home-input", 2.6, None)
    out, _ = lab_outputs(r, "1X2", ov, st)
    grid = _find(out, lambda c: getattr(c, "className", None) == "lab-tables")
    assert len(grid) == 1 and len(grid[0].children) == 2
    left, right = grid[0].children
    assert _text(left.children[0]) == "Estimated goals breakdown"
    assert _text(right.children[0]) == "Match result probabilities"
    lt = _text(left)
    for label in (
        "Model baseline",
        "B · Match context",
        "C · Other factors",
        "Manual adjustment",
        "Your final estimate",
    ):
        assert label in lt
    head = [_text(th) for th in right.children[1].children[0].children.children]
    assert head == ["Outcome", "Model", "Yours", "Change"]
    est = user_estimates(r, st)
    mine = gm.markets(est["home"], est["away"])
    base = r["goal_model"]["probabilities"]
    rt = _text(right)
    for k in ("home", "draw", "away"):
        assert f"{mine[k] * 100:.1f}%" in rt and f"{base[k] * 100:.1f}%" in rt
    # flow: breakdown -> probabilities -> All markets -> Your value check
    kinds = [getattr(c, "className", None) for c in out.children]
    i = kinds.index("lab-tables")
    assert kinds[i + 1] == "acc all-markets" and kinds[i + 2] == "value-check"
    assert (
        "@media (max-width: 720px) { .lab-tables { grid-template-columns: minmax(0, 1fr); } }"
        in CSS
    )


# --------------------------------------------- 3. compact B / C sliders
def test_sliders_rendered_with_preserved_ranges(data):
    r, ov, off = data.detail(EPL_FIX)
    d = render_detail(r, ov, off, "1X2", data, None)
    for side in ("home", "away"):
        s = _find(d, lambda c, side=side: getattr(c, "id", None) == f"ctx-{side}-slider")[0]
        assert (s.min, s.max, s.step, s.value) == (-CONTEXT_MAX, CONTEXT_MAX, 0.05, 0.0)
    for k in CATEGORY_KEYS:
        for side in ("home", "away"):
            sid = {"type": "cat-slider", "cat": k, "side": side}
            s = _find(d, lambda c, sid=sid: getattr(c, "id", None) == sid)[0]
            assert (s.min, s.max, s.step, s.value) == (-CATEGORY_MAX, CATEGORY_MAX, 0.05, 0.0)
    assert (CONTEXT_MAX, CATEGORY_MAX) == (1.0, 2.0)  # existing limits, not reduced
    # each slider sits beside its precise box, inside the existing accordions
    pairs = _find(d, lambda c: getattr(c, "className", None) == "mini-adjust")
    assert len(pairs) == 2 + 2 * len(CATEGORY_KEYS)
    assert all(isinstance(p.children[1].id, str | dict) for p in pairs)
    accs = _find(d, lambda c: isinstance(c, html.Details) and "cat-acc" in (c.className or ""))
    assert all(_find(a, lambda c: getattr(c, "className", None) == "mini-adjust") for a in accs)


def _cb(data, trigger, value, lab):
    _trigger(trigger if isinstance(trigger, str) else json.dumps(trigger) + ".value", value)
    return _call(lambda *a: _ADJUST(*a), data, lab, value)


_ADJUST = None


@pytest.fixture
def adjust(data):
    global _ADJUST
    app = create_app(data)
    _ADJUST = next(v for k, v in app.callback_map.items() if k.startswith("..lab-store.data"))[
        "callback"
    ].__wrapped__
    return _ADJUST


def _slider_out(out):
    """(ctx home box, ctx away box, ctx home slider, ctx away slider, cat sliders)."""
    return out[11], out[12], out[15], out[16], out[14]


def test_context_slider_and_box_share_one_value(data, adjust):
    out = _cb(data, "ctx-home-slider.value", 0.35, {})
    box_h, box_a, sl_h, sl_a, _ = _slider_out(out)
    assert (box_h, sl_h, box_a, sl_a) == ("+0.35", 0.35, "0.00", 0.0)  # slider -> box
    lab = out[0]
    out = _cb(data, "ctx-home.value", "-0,40", lab)  # box -> slider (decimal comma)
    box_h, _, sl_h, _, _ = _slider_out(out)
    assert (box_h, sl_h) == ("-0.40", -0.4)
    r = data.detail(EPL_FIX)[0]
    b = breakdown(baseline_rounded(r), out[0][str(EPL_FIX)])
    assert b["home"]["final"] == round(b["home"]["base"] - 0.40, 2)  # counted once
    # out of range: the box value is refused, both controls keep the previous value
    out2 = _cb(data, "ctx-home.value", "1.5", out[0])
    box_h, _, sl_h, _, _ = _slider_out(out2)
    assert (box_h, sl_h) == ("-0.40", -0.4)
    assert "between -1.00 and +1.00" in _text(out2[9])


def test_category_slider_counts_once_and_reconciles_with_manual(data, adjust):
    r = data.detail(EPL_FIX)[0]
    base = baseline_rounded(r)
    key = {"type": "cat-slider", "cat": "tactics", "side": "home"}
    out = _cb(data, key, 0.5, {})
    sliders = out[14]
    idx = [
        i
        for i, k in enumerate((k, s) for k in CATEGORY_KEYS for s in ("home", "away"))
        if k == ("tactics", "home")
    ][0]
    assert sliders[idx] == 0.5 and out[7][idx] == "0.50"  # slider and its box agree
    assert out[1] == round(base["home"] + 0.5, 2)  # final estimate: once, not twice
    # a Section D override reconciles the manual part; the slider stays put
    out = _cb(data, "lab-home-input.value", 3.0, out[0])
    st = out[0][str(EPL_FIX)]
    assert st["manual"]["home"] == round(3.0 - base["home"] - 0.5, 2) and out[14][idx] == 0.5
    # moving the category slider again moves the final estimate by the same amount
    out = _cb(data, key, 0.2, out[0])
    assert out[1] == round(3.0 - 0.3, 2)
    # negative values, then zero
    out = _cb(data, key, -1.25, out[0])
    assert out[7][idx] == "-1.25" and out[14][idx] == -1.25
    out = _cb(data, key, 0, out[0])
    assert out[7][idx] == "0.00" and out[14][idx] == 0.0
    # out-of-range typed value is refused safely
    out = _cb(data, {"type": "cat-adj", "cat": "tactics", "side": "home"}, "2.5", out[0])
    assert out[7][idx] == "0.00" and out[14][idx] == 0.0


def test_reset_clears_sliders(data, adjust):
    lab = _cb(data, "ctx-away-slider.value", -0.6, {})[0]
    lab = _cb(data, {"type": "cat-slider", "cat": "squad", "side": "home"}, 1.0, lab)[0]
    out = _cb(data, "lab-reset.n_clicks", 1, lab)
    _, box_a, _, sl_a, cats = _slider_out(out)
    assert (box_a, sl_a) == ("0.00", 0.0) and all(v == 0.0 for v in cats)
    assert str(EPL_FIX) not in out[0]  # nothing left to keep: the fixture's entry is removed


FITNESS_AWAY = {"type": "cat-slider", "cat": "fitness", "side": "away"}


def test_slider_value_clamps_and_market_switch_keeps_positions(data):
    assert slider_value(1.7, 1.0) == 1.0 and slider_value(-3, 2.0) == -2.0
    assert slider_value(None, 1.0) == 0.0 and slider_value(0.35, 1.0) == 0.35
    r, ov, off = data.detail(EPL_FIX)
    st, _ = lab_update(r, "ctx-home-slider", 0.25, None)
    st, _ = lab_update(r, {"type": "cat-slider", "cat": "fitness", "side": "away"}, -0.75, st)
    for market in ("1X2", "BTTS", "OU25"):
        d = render_detail(r, ov, off, market, data, st)
        s = _find(d, lambda c: getattr(c, "id", None) == "ctx-home-slider")[0]
        box = _find(d, lambda c: getattr(c, "id", None) == "ctx-home")[0]
        assert s.value == 0.25 and box.value == "+0.25"
        assert _find(d, lambda c: getattr(c, "id", None) == FITNESS_AWAY)[0].value == -0.75


def test_mini_slider_styled_secondary():
    assert (
        ".mini-slider .dash-slider-thumb { width: 12px; height: 12px; background: var(--muted)"
        in CSS
    )
    assert (
        ".mini-slider .dash-slider-root .dash-slider-track .dash-slider-range { background-color: transparent; }"
        in CSS
    )  # centred on 0
    assert ".mini-adjust { display: grid; grid-template-columns: minmax(0, 1fr) 76px;" in CSS


def test_model_and_value_maths_unchanged(data):
    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.competition_min) == (12, 96, 20)  # GM 1.1
    r, ov, _ = data.detail(EPL_FIX)
    from diski9.odds.value import compare

    mv = compare(
        MARKET_OF["1X2"], r["goal_model"]["probabilities"], ov.markets[MARKET_OF["1X2"]].consensus
    )
    for o in mv.outcomes:
        assert o.ev == pytest.approx(o.probability * float(o.odds) - 1)


# ---------------------------------------------------------------- browser
BROWSER = """
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const res = {};
  const views = [['desktop', { viewport: { width: 1440, height: 1000 } }],
                 ['tablet', { viewport: { width: 900, height: 1100 } }],
                 ['phone', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }]];
  for (const [name, opts] of views) {
    const ctx = await b.newContext(opts);
    const p = await ctx.newPage();
    await p.goto(BASE);  // CP3A-3: the research list (Portfolio Build)
    await p.waitForSelector('#direction', { timeout: 20000 });
    await p.waitForTimeout(800);
    const r = {};
    await p.locator('#direction').click();
    await p.locator('[role=option]', { hasText: 'model vs market edge' }).dispatchEvent('click');
    await p.waitForFunction(() => {
      const th = [...document.querySelectorAll('table.results th')].pop();
      return th && th.innerText.toLowerCase().includes('best edge');
    }, null, { timeout: 15000 });
    await p.waitForTimeout(400);
    r.colours = await p.evaluate(() => [...document.querySelectorAll(
      '.value-cell.v-pos .v-main, .card-value.v-pos')].filter(e => e.offsetParent)
      .map(e => [e.innerText.split(/[ :]/).filter(Boolean).slice(0, 2).join(' '), getComputedStyle(e).color]));
    r.overflowScreener = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (SHOTS) await p.screenshot({ path: `${SHOTS}/${name}-screener.png` });
    const row = p.locator('table.results tr.row').first();
    if (await row.isVisible()) await row.click(); else await p.locator('.fx-card').first().click();
    await p.waitForSelector('.lab-tables', { timeout: 20000 });
    await p.waitForTimeout(500);
    r.panes = await p.evaluate(() => [...document.querySelectorAll('.lab-tables .lab-pane')]
      .map(e => { const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.width)]; }));
    r.summary = await p.evaluate(() => { const e = document.querySelector('.val-pos-text strong');
      return e ? [e.innerText, getComputedStyle(e).color] : null; });
    r.tableClip = await p.evaluate(() => [...document.querySelectorAll('.lab-tables table')]
      .map(t => t.scrollWidth - t.parentElement.clientWidth));
    // Section B: open, move the compact slider with the keyboard, then type in the box
    await p.locator('.ctx-acc > summary').click();
    await p.waitForTimeout(300);
    const thumb = p.locator('#ctx-home-slider [role=slider]');
    await thumb.focus();
    for (let i = 0; i < 3; i++) await p.keyboard.press('ArrowRight');
    await p.waitForFunction(() => document.querySelector('#ctx-home').value === '+0.15', null, { timeout: 10000 });
    r.boxAfterSlider = await p.locator('#ctx-home').inputValue();
    r.breakdownAfterSlider = await p.locator('.breakdown').innerText();
    const box = p.locator('#ctx-home');
    await box.fill('-0.40'); await box.press('Enter');
    await p.waitForFunction(() => document.querySelector('#ctx-home-slider [role=slider]')
      .getAttribute('aria-valuenow') === '-0.4', null, { timeout: 10000 });
    r.sliderAfterBox = await thumb.getAttribute('aria-valuenow');
    r.rangeColour = await p.evaluate(() => getComputedStyle(
      document.querySelector('#ctx-home-slider .dash-slider-range')).backgroundColor);
    r.thumbSize = await thumb.evaluate(e => Math.round(e.getBoundingClientRect().width));
    r.mainThumbSize = await p.locator('#lab-home-slider [role=slider]').evaluate(e => Math.round(e.getBoundingClientRect().width));
    r.overflowLab = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    r.miniClip = await p.evaluate(() => [...document.querySelectorAll('.mini-adjust')].filter(e => e.offsetParent)
      .map(e => e.scrollWidth - e.clientWidth));
    if (SHOTS) {
      await p.locator('.ctx-acc').scrollIntoViewIfNeeded();
      await p.screenshot({ path: `${SHOTS}/${name}-section-b.png` });
      await p.locator('.lab-tables').scrollIntoViewIfNeeded();
      await p.screenshot({ path: `${SHOTS}/${name}-section-d.png` });
    }
    res[name] = r;
    await ctx.close();
  }
  console.log(JSON.stringify(res));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""
RGB = {"Home": "rgb(96, 165, 250)", "Draw": "rgb(54, 201, 168)", "Away": "rgb(229, 174, 82)"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_outcome_colours_section_d_and_sliders(valued):
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

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
            assert r["colours"], name
            for text, colour in r["colours"]:
                label = text.replace("Edge", "").split()[0]
                assert colour == RGB[label], (name, text, colour)
            left, right = r["panes"]
            if name == "phone":  # stacked
                assert left[0] == right[0] and right[1] > left[1], (name, r["panes"])
            else:  # side by side, similar widths
                assert left[1] == right[1] and right[0] > left[0], (name, r["panes"])
                assert abs(left[2] - right[2]) <= 2
            assert all(c <= 0 for c in r["tableClip"]), (name, r["tableClip"])
            if r["summary"]:  # Section D positive-EV outcome in its identity colour
                label = r["summary"][0].split()[0]
                assert r["summary"][1] == RGB[label], (name, r["summary"])
            assert r["boxAfterSlider"] == "+0.15" and r["sliderAfterBox"] == "-0.4", name
            assert "+0.15" in r["breakdownAfterSlider"], name
            assert r["thumbSize"] < r["mainThumbSize"], name  # visually secondary
            assert r["rangeColour"] in ("rgba(0, 0, 0, 0)", "transparent"), name  # no fill
            assert r["overflowScreener"] <= 0 and r["overflowLab"] <= 0, name
            assert all(c <= 0 for c in r["miniClip"]), (name, r["miniClip"])
    finally:
        server.shutdown()


def test_outcome_class_rules_for_every_state():
    from diski9.app.app import outcome_class

    for o in ("home", "draw", "away"):
        assert outcome_class({"outcome": o, "cls": "pos"}) == f" v-out-{o}"
        for neutral in ("neg", "zero", "na"):  # never looks like an opportunity
            assert outcome_class({"outcome": o, "cls": neutral}) == ""
    assert outcome_class({"outcome": None, "cls": "pos"}) == ""  # BTTS / Over-Under
    assert outcome_class({"cls": "pos"}) == ""


def test_draw_and_away_picks_are_coloured_too(valued):
    seen = set()
    for direction in ("edge", "ev"):
        for r in valued.snapshot().results["overall"].values():
            cell = valued.value_cell("1X2", r, direction)
            if cell["outcome"]:
                seen.add(cell["outcome"])
    assert {"home", "away"} <= seen


# ------------------------------------- Section D positive-EV summary colour
@pytest.mark.parametrize("key", ["home", "draw", "away"])
def test_value_check_summary_takes_outcome_colour(data, key):
    from diski9.app.lab import value_check

    r, ov, _ = data.detail(EPL_FIX)
    base = r["goal_model"]["probabilities"]
    mine = {k: (0.8 if k == key else 0.1) for k in ("home", "draw", "away")}
    vc = value_check("1X2", ov, base, mine)
    summary = _find(vc, lambda c: "val-pos-text" in (getattr(c, "className", "") or ""))
    strong = _find(summary[0], lambda c: isinstance(c, html.Strong))
    assert len(strong) == 1 and strong[0].className == f"out-{key}"
    label = {"home": "Home win", "draw": "Draw", "away": "Away win"}[key]
    assert _text(strong[0]).startswith(label)
    # the table's EV values keep their positive/negative formatting
    cells = _find(vc, lambda c: "val-pos" in (getattr(c, "className", "") or "").split())
    assert cells


def test_value_check_summary_two_way_markets_stay_neutral(data):
    from diski9.app.lab import value_check

    r, ov, _ = data.detail(EPL_FIX)
    vc = value_check(
        "BTTS", ov, r["goal_model"]["probabilities"], {"btts_yes": 0.9, "btts_no": 0.1}
    )
    strong = _find(vc, lambda c: isinstance(c, html.Strong))
    assert strong and not strong[0].className
    for name in ("home", "draw", "away"):
        assert f".val-pos-text strong.out-{name} {{ color: var(--out-{name}); }}" in CSS
