# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Final UI polish: league summary, exact threshold value, two-decimal goals and the
methodology layout. Presentation only - the model is unchanged."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from diski9.app import create_app
from diski9.app.app import (
    THRESHOLD_MARKS,
    _parse_adjustment,
    _parse_goals,
    league_labels,
    results_payload,
    threshold_config,
)
from diski9.app.data import DIRECTIONS
from diski9.app.lab import adjustment_text
from diski9.app.methodology import methodology_section
from diski9.screener import goal_model as gm

from .test_app import _free_port, _text, data, page_ids, populated  # noqa: F401

ASSETS = Path(__file__).parents[1] / "src/diski9/app/assets"
PROB_DIRECTIONS = {
    m: [d for d, _ in DIRECTIONS[m] if not d.startswith("kickoff") and d not in ("edge", "ev")]
    for m in DIRECTIONS
}


# ------------------------------------------------------------ league summary
def test_league_summary_labels_and_css():
    assert league_labels(8, 8)["selected_count"] == "All 8 leagues"
    assert league_labels(5, 8)["selected_count"] == "{num_selected} leagues selected"
    css = (ASSETS / "style.css").read_text()
    # with a count, the truncated name list is hidden; one league shows its own name
    assert (
        ".leagues .dash-dropdown-trigger:has(.dash-dropdown-value-count) "
        ".dash-dropdown-value { display: none; }" in css
    )
    assert ".leagues .dash-dropdown-clear { display: none; }" in css


# ----------------------------------------------------------------- threshold
@pytest.mark.parametrize("market", ["1X2", "BTTS", "OU25"])
def test_threshold_whole_percentages_and_labels(market):
    for d in PROB_DIRECTIONS[market]:
        c = threshold_config(market, d, 30)
        assert (c["min"], c["max"], c["step"], c["value"]) == (0, 100, 1, 30)
        assert c["marks"] == THRESHOLD_MARKS == {0: "Any", 50: "50%", 100: "100%"}
        assert c["tooltip"]["always_visible"] and c["tooltip"]["transform"] == "thresholdLabel"
        assert c["label"].startswith("Minimum ") and c["label"].endswith(" probability")
        assert not c["disabled"]
    for d in ("kickoff_earliest", "kickoff_latest"):
        c = threshold_config(market, d, 30)
        assert c["disabled"] and c["value"] == 0 and c["tooltip"] is None
        assert c["hint"] == "Available when ranking by a probability"
    assert threshold_config(market, PROB_DIRECTIONS[market][0], 140)["value"] == 100  # clamped


def test_threshold_label_function():
    js = (ASSETS / "diski9.js").read_text()
    assert "window.dccFunctions.thresholdLabel = function (value)" in js
    assert 'value <= 0 ? "Any" : Math.round(value) + "%"' in js


@pytest.mark.parametrize("market", ["1X2", "BTTS", "OU25"])
def test_threshold_filters_exactly_at_shown_value(data, market):
    key = {
        "home_win": "home",
        "draw": "draw",
        "away_win": "away",
        "btts_yes": "btts_yes",
        "btts_no": "btts_no",
        "over": "over",
        "under": "under",
    }
    snap = data.snapshot()
    for d in PROB_DIRECTIONS[market]:
        counts = []
        for t in (0, 30, 50, 100):
            p = results_payload(data, market, [39, 288], None, "2026-12-31", "overall", d, t, 1)
            total = int(p[2].split(" of ")[1].split()[0]) if p[2] else 0
            counts.append(total)
            for fid in page_ids(p):
                prob = snap.results["overall"][fid]["goal_model"].get("probabilities") or {}
                if t > 0:
                    assert prob[key[d]] >= t / 100 - 1e-12, (market, d, t)
        assert counts == sorted(counts, reverse=True)  # higher threshold, fewer fixtures
        assert counts[-1] == 0  # nothing reaches 100%
    # kickoff ordering never filters, whatever the slider held before
    a = results_payload(
        data, market, [39, 288], None, "2026-12-31", "overall", "kickoff_earliest", 75, 1
    )
    b = results_payload(
        data, market, [39, 288], None, "2026-12-31", "overall", "kickoff_earliest", 0, 1
    )
    assert a[2] == b[2] and page_ids(a) == page_ids(b)


def test_threshold_preference_kept_across_ranking_switches(data):
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    app = create_app(data)
    controls = next(v for k, v in app.callback_map.items() if "threshold.tooltip" in k)
    remember = next(v for k, v in app.callback_map.items() if k.startswith("threshold-pref"))
    f, r = controls["callback"].__wrapped__, remember["callback"].__wrapped__
    context_value.set(AttributeDict(triggered_inputs=[{"prop_id": "threshold.value", "value": 30}]))
    assert r(30, "home_win") == 30
    from dash.exceptions import PreventUpdate

    with pytest.raises(PreventUpdate):  # kickoff ordering does not overwrite it
        r(0, "kickoff_earliest")
    off = f("1X2", "kickoff_earliest", 30)
    assert off[3] == 0 and off[5] is True and off[6] is None  # value, disabled, tooltip
    back = f("1X2", "away_win", 30)
    assert back[3] == 30 and back[5] is False and back[7] == "Minimum away win probability"
    assert f("BTTS", "btts_yes", 30)[3] == 30  # also kept across market switches


# -------------------------------------------------------------- goal formatting
def test_goal_values_two_decimals_and_parsing():
    assert [adjustment_text(x) for x in (0, -0.15, 0.05, 0.1, -0.004)] == [
        "0.00",
        "-0.15",
        "0.05",
        "0.10",
        "0.00",
    ]
    assert _parse_goals("1.6") == 1.6 and _parse_goals("1,65") == 1.65
    assert _parse_goals(" 2.30 ") == 2.3 and _parse_goals("abc") is None
    assert _parse_adjustment("-0,15") == -0.15 and _parse_adjustment("  ") == 0.0
    assert _parse_adjustment("+0.05") == 0.05 and _parse_adjustment("3") is None
    js = (ASSETS / "diski9.js").read_text()
    assert 'el.closest(".goal-input")' in js and "toFixed(2)" in js  # arrow-key stepping


def test_model_unchanged():
    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.competition_min) == (12, 96, 20)  # GM 1.1
    p = gm.markets(1.93, 0.96)
    assert [round(p[k] * 100, 1) for k in ("home", "draw", "away", "btts_yes", "over")] == [
        60.0,
        21.7,
        18.2,
        52.8,
        55.2,
    ]


# ---------------------------------------------------------------- methodology
def test_methodology_wording_and_layout():
    t = _text(methodology_section())
    assert "Strength smoothing (12) and goal tempo smoothing (96) were chosen by comparing" in t
    assert "The league-average prior (30) was not tuned in the same way" in t
    assert "sensitivity check (10, 30 and 100 matches)" in t
    assert "independently validated, without any change, on 4,515 matches" in t
    assert "optimal" not in t.lower()
    for section in (
        "The short version",
        "A worked example",
        "What changes and what stays fixed",
        "The fixed settings",
        "How the settings were chosen and tested",
        "Known limitations",
        "How the model is maintained",
        "Model version",
        "Technical detail (formulas)",
    ):
        assert section in t, section
    css = (ASSETS / "style.css").read_text()
    assert ".methodology-body { padding: 4px 18px 14px; }" in css  # no 860px cap
    assert "max-width: 860px" not in css
    assert ".meth-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    doc = (Path(__file__).parents[1] / "docs/methodology.md").read_text()
    assert "The league-average prior (30)** was not tuned in the same way" in doc


BROWSER = """
const { chromium, devices } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const out = {};
  const views = [['desktop', { viewport: { width: 1400, height: 1000 } }],
                 ['tablet', { viewport: { width: 900, height: 1100 } }],
                 ['phone', devices['iPhone 13']]];
  for (const [name, opts] of views) {
    const p = await (await b.newContext(opts)).newPage();
    await p.goto(BASE + 'lab');
    await p.waitForSelector('#leagues', { timeout: 20000 });
    await p.waitForTimeout(600);
    const r = {};
    r.leagues = await p.locator('#leagues').innerText();
    await p.locator('#direction').click();
    await p.locator('[role=option]', { hasText: 'home-win' }).click();
    await p.waitForTimeout(500);
    await p.locator('#threshold [role=slider]').focus();
    for (let i = 0; i < 30; i++) await p.keyboard.press('ArrowRight');
    await p.waitForTimeout(700);
    r.tip = await p.locator('#threshold .dash-slider-tooltip').innerText();
    const tb = await p.locator('#threshold .dash-slider-tooltip').boundingBox();
    const fb = await p.locator('.filters').boundingBox();
    r.tipInside = tb.x >= fb.x && tb.x + tb.width <= fb.x + fb.width;
    for (let i = 0; i < 70; i++) await p.keyboard.press('ArrowRight');
    await p.waitForTimeout(500);
    r.tip100 = await p.locator('#threshold .dash-slider-tooltip').innerText();
    const tb2 = await p.locator('#threshold .dash-slider-tooltip').boundingBox();
    r.tip100Inside = tb2.x + tb2.width <= fb.x + fb.width;
    await p.keyboard.press('Home'); await p.waitForTimeout(500);
    r.tip0 = await p.locator('#threshold .dash-slider-tooltip').innerText();
    await p.locator('#methodology > summary').click();
    r.methOpen = await p.evaluate(() => document.querySelector('#methodology').open);
    r.methWidth = await p.evaluate(() => {
      const card = document.querySelector('#methodology').getBoundingClientRect().width;
      const body = document.querySelector('.methodology-body').getBoundingClientRect().width;
      return body / card; });
    r.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await p.locator('#methodology > summary').click();
    r.methClosed = !(await p.evaluate(() => document.querySelector('#methodology').open));
    out[name] = r;
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_threshold_label_leagues_and_methodology(data):
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
        for name in ("desktop", "tablet", "phone"):
            r = out[name]
            assert r["leagues"] == "All 2 leagues", (name, r)  # the test database: EPL + PSL
            assert r["tip"] == "30%" and r["tip100"] == "100%" and r["tip0"] == "Any", name
            assert r["tipInside"] and r["tip100Inside"], name  # never clipped
            assert r["methOpen"] and r["methClosed"], name
            assert r["methWidth"] > 0.95, name  # content uses the card width
            assert r["overflow"] <= 0, name
    finally:
        server.shutdown()
