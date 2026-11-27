# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""League comparison indicator under BTTS / Over 2.5 team records (display only)."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from types import SimpleNamespace

import pytest

from diski9.app.views import (
    analysis_card,
    calculation_section,
    league_comparison,
    record_tile,
)
from diski9.screener.engine import Match, MatchStore, compute_fixture

from .test_app import EPL_FIX, _find, _free_port, _text, data, populated  # noqa: F401

T = datetime(2026, 9, 1, 15, tzinfo=UTC)


def lb(btts=None, over=None, available=True):
    return {"available": available, "btts": btts, "over_2_5": over, "matches": 40}


def rate(h, n):
    return {"hits": h, "matches": n}


def test_above_below_equal_on_unrounded_ratios():
    base = lb(btts=float(Fraction(49, 100)))
    assert league_comparison(rate(6, 10), base, "btts") == "above"
    assert league_comparison(rate(4, 10), base, "btts") == "below"
    assert league_comparison(rate(49, 100), base, "btts") == "equal"  # exactly equal
    # displayed as 50% both, but 1/2 is above 0.499... -> no rounding, no tolerance
    near = lb(btts=float(Fraction(499, 1000)))
    assert league_comparison(rate(1, 2), near, "btts") == "above"
    assert league_comparison(rate(2, 4), lb(btts=0.5), "btts") == "equal"
    assert league_comparison(rate(1, 3), lb(btts=float(Fraction(10, 30))), "btts") == "equal"
    assert league_comparison(rate(7, 21), lb(btts=float(Fraction(11, 33))), "btts") == "equal"
    # Over 2.5 uses its own baseline
    assert league_comparison(rate(3, 10), lb(btts=0.1, over=0.5), "over_2_5") == "below"


def test_comparison_unavailable_cases():
    assert league_comparison(rate(5, 10), lb(available=False), "btts") is None
    assert league_comparison(rate(5, 10), None, "btts") is None
    assert league_comparison(None, lb(btts=0.5), "btts") is None  # no eligible matches
    assert league_comparison(rate(0, 0), lb(btts=0.5), "btts") is None
    # unavailable baseline is never treated as 0: a 0-of-3 team is not "equal"/"above"
    assert league_comparison(rate(0, 3), lb(available=False, btts=None), "btts") is None


def team(h, n, limited=False, window="overall", key="btts"):
    other = "over_2_5" if key == "btts" else "btts"
    return {
        "team": "Team",
        "window": window,
        "goals": {
            key: rate(h, n) if n else None,
            other: None,
            "sample": {"limited_data": limited},
        },
    }


@pytest.mark.parametrize("market,key", [("BTTS", "btts"), ("OU25", "over_2_5")])
def test_tile_indicator_text_and_limited_stays_dominant(market, key):
    base = lb(btts=0.49, over=0.55)
    above = _text(record_tile(team(8, 10, key=key), key, market, base))
    assert "Above league average" in above
    below = _text(record_tile(team(2, 10, key=key), key, market, base))
    assert "Below league average" in below and "Above" not in below
    tile = record_tile(team(2, 3, limited=True, key=key), key, market, base)
    # Limited pill sits on the record line; the indicator is a smaller line below it
    record_row = _find(tile, lambda c: getattr(c, "className", "") == "record-row")[0]
    assert "Limited" in _text(record_row) and "league average" not in _text(record_row)
    cmp_ = _find(tile, lambda c: str(getattr(c, "className", "")).startswith("league-cmp"))
    assert len(cmp_) == 1 and "small" in cmp_[0].className
    assert tile.children.index(cmp_[0]) > tile.children.index(record_row)
    # no history / no baseline -> indicator omitted entirely
    none = record_tile(team(0, 0, key=key), key, market, base)
    assert not _find(none, lambda c: str(getattr(c, "className", "")).startswith("league-cmp"))
    unavailable = record_tile(team(8, 10, key=key), key, market, lb(available=False))
    assert "league average" not in _text(unavailable)


# ------------------------------------------------- integration with the engine
def _m(fid, days, h, a, hg, ag):
    return Match(
        fid,
        T + timedelta(days=days),
        39,
        2026,
        h,
        a,
        hg,
        ag,
        "verified",
        True,
        None,
        None,
        "FT",
        str(fid),
    )


def _store():
    """40 league matches (20 BTTS 1-1, 20 not 2-0) -> BTTS baseline 50%, Over 0%.
    Team 1: home 3/3 BTTS, away 0/3; team 2: away 1/4 BTTS."""
    ms = [_m(i, i * 0.1, 100 + i, 200 + i, *((1, 1) if i < 20 else (2, 0))) for i in range(40)]
    ms += [_m(100 + i, 5 + i, 1, 300 + i, 2, 2) for i in range(3)]  # team 1 home, BTTS, over
    ms += [_m(110 + i, 9 + i, 310 + i, 1, 1, 0) for i in range(3)]  # team 1 away, no BTTS
    ms += [_m(120 + i, 5 + i, 320 + i, 2, *((1, 1) if i == 0 else (0, 1))) for i in range(4)]
    names = {i: f"T{i}" for i in range(1, 400)}
    return MatchStore.from_matches(ms, names, {39: "EPL"})


def _card(basis, market):
    fx = SimpleNamespace(
        id=999,
        competition_id=39,
        season=2026,
        home_team_id=1,
        away_team_id=2,
        kickoff_utc=T + timedelta(days=30),
    )
    r = compute_fixture(_store(), fx, fx.kickoff_utc, basis)
    return r, analysis_card(r, market)


def _states(card):
    return [
        c.className.split()[1]
        for c in _find(card, lambda c: str(getattr(c, "className", "")).startswith("league-cmp"))
    ]


def test_overall_and_venue_basis_use_their_own_records():
    r, card = _card("venue", "BTTS")
    # the league baseline counts every league match before kickoff, the two teams'
    # own included: 20 + 3 + 1 BTTS of 50 = 48%
    assert r["league_baseline"]["btts"] == pytest.approx(24 / 50)
    # venue: team 1 home 3/3 (above), team 2 away 1/4 (below)
    assert _states(card) == ["above", "below"]
    r, card = _card("overall", "BTTS")
    g = r["teams"]["home"]["goals"]["btts"]
    assert (g["hits"], g["matches"]) == (3, 6)  # overall record differs from venue
    # 3/6 = 50% > 48%; team 2 1/4 below
    assert _states(card) == ["above", "below"]


def test_over_under_market_uses_its_own_baseline():
    r, card = _card("venue", "OU25")
    # league Over 2.5: the three 2-2 matches of 50 = 6%; team 1 home 3/3 (above),
    # team 2 away 0/4 (below)
    assert r["league_baseline"]["over_2_5"] == pytest.approx(3 / 50)
    assert _states(card) == ["above", "below"]


def test_unavailable_baseline_shows_no_indicator_in_app(data):
    r, ov, official = data.detail(EPL_FIX, "overall")
    assert r["league_baseline"]["available"] is False  # 21 of 30 matches in the fixture
    for market in ("BTTS", "OU25"):
        card = analysis_card(r, market)
        assert _states(card) == []
        assert "Not enough current-season data yet" in _text(card)
        tiles = _find(card, lambda c: getattr(c, "className", "") == "tiles")[0]
        assert "league average" not in _text(tiles)


def test_explanation_in_how_its_calculated():
    r, _ = _card("overall", "BTTS")
    for market in ("BTTS", "OU25"):
        text = _text(calculation_section(r, market))
        assert "above or below the current-season league average" in text
        assert "not a prediction of the upcoming match" in text
    assert "league average" not in _text(calculation_section(r, "1X2"))


BROWSER = """
const { chromium, devices } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const out = {};
  for (const [name, opts] of [['desktop', { viewport: { width: 1400, height: 1000 } }],
                              ['phone', devices['iPhone 13']]]) {
    const ctx = await b.newContext(opts);
    const p = await ctx.newPage();
    await p.goto(BASE);  // CP3A-3: the research list (Portfolio Build)
    await p.waitForSelector('tr.row, .fx-card', { timeout: 20000, state: 'attached' });
    await p.locator('#market').click(); await p.locator('.dash-dropdown-option', { hasText: 'Both Teams' }).click();
    await p.waitForTimeout(800);
    if (name === 'desktop') await p.locator('tr.row').first().click();
    else await p.locator('.fx-card').first().tap();
    await p.waitForSelector('.lab', { timeout: 20000 });
    await p.locator('.lab .context .acc-group > details.acc > summary').nth(1).click();  // open the BTTS record
    out[name] = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await ctx.close();
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_no_overflow(data):
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    import json

    from werkzeug.serving import make_server

    from diski9.app import create_app

    port = _free_port()
    server = make_server("127.0.0.1", port, create_app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        time.sleep(0.5)
        script = f"const BASE = 'http://127.0.0.1:{port}/';\n" + BROWSER
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=120)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out["desktop"] <= 0 and out["phone"] <= 0
    finally:
        server.shutdown()
