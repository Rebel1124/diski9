"""Phase 8 CP3A-1: routes and navigation.

Portfolio Build (the Weekly Challenge builder, the fixture-selection entry point) is
the home page ``/``; the Match Lab (with the Screener list, unchanged in CP3A-1) moved
to ``/lab``; Training Ground (route ``/learn``) has a route and tab. Old addresses keep working: ``/challenge`` is
redirected to ``/`` by the server and aliased by the router, and old Match Lab deep
links ``/?fixture=<id>`` are redirected to ``/lab?fixture=<id>``. Every callback that
renders only while the Match Lab shows now checks ``/lab``."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from dash import no_update

from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import pages

from .test_app import data, populated  # noqa: F401  (fixtures)
from .test_challenge_ui import jtext


def _named(app, name):
    """The (undecorated) server callback registered under ``name``."""
    funcs = [v["callback"].__wrapped__ for v in app.callback_map.values() if "callback" in v]
    found = [f for f in funcs if f.__name__ == name]
    assert len(found) == 1, name
    return found[0]


SRC = Path(__file__).resolve().parents[1] / "src" / "diski9" / "app"


def _app(data):  # noqa: F811
    from diski9.app import create_app

    return create_app(data)


def test_five_tabs_in_the_approved_order():
    assert cb.NAV == (
        ("/", "Portfolio Build"),
        ("/lab", "Match Lab"),
        ("/challenge/me", "My Challenge"),
        ("/learn", "Training Ground"),
        ("/leaderboards", "Leaderboard"),
    )


def test_path_normalisation_and_active_tab():
    assert cb.norm_path(None) == cb.norm_path("") == cb.norm_path("/") == "/"
    assert cb.norm_path("/challenge") == cb.norm_path("/challenge/") == "/"
    assert cb.norm_path("/lab/") == "/lab" and cb.is_lab("/lab") and not cb.is_lab("/")
    assert cb.norm_path("/challenge/me") == "/challenge/me"  # not the legacy alias
    for path, active in (("/", "/"), ("/challenge", "/"), ("/lab", "/lab"),
                         ("/learn", "/learn"), ("/challenge/me", "/challenge/me")):  # fmt: skip
        on = [link.href for link in cb.nav_links(path) if link.className.endswith(" on")]
        assert on == [active], path
    assert not any(link.className.endswith(" on") for link in cb.nav_links("/nowhere"))


def test_server_redirects_old_addresses(data):  # noqa: F811
    client = _app(data).server.test_client()
    for old, new in (("/challenge", "/"), ("/challenge/", "/"), ("/challenge?x=1", "/?x=1"),
                     ("/?fixture=42", "/lab?fixture=42"),
                     ("/?fixture=42&m=1", "/lab?fixture=42&m=1")):  # fmt: skip
        r = client.get(old)
        assert r.status_code == 302, old
        assert r.headers["Location"] in (new, "http://localhost" + new), old
    for path in ("/", "/?list=challenge", "/lab", "/lab?fixture=42", "/learn",
                 "/challenge/me", "/leaderboards", "/_dash-layout"):  # fmt: skip
        assert client.get(path).status_code == 200, path
    assert client.post("/challenge").status_code != 302  # only page loads are redirected


def test_router_shows_each_page(data):  # noqa: F811
    """Route content (CP3A-2: the first output is the Portfolio Build home section; which
    list is visible is decided by ``layout_mode``, tested in test_phase8_cp3a2)."""
    route = _named(_app(data), "route")
    # CP3A-3: the Match Lab leaves the page beneath (the builder) mounted and untouched
    home, content, nav, sig, mounted = route("/lab", None, None, None, "/")
    assert home is None and content is no_update and sig is no_update and mounted is no_update
    for path in ("/", "/challenge"):  # Portfolio Build, and the legacy alias
        home, content, nav, sig, mounted = route(path, None, None, None, None)
        assert "Domestic Weekly Challenge" in jtext(home)
        assert "Weekly Challenge" in jtext(content) and sig is not None and mounted == "/"
        assert [x.href for x in nav if x.className.endswith(" on")] == ["/"]
    # back from the Match Lab: the builder is kept exactly as it was (not re-rendered)
    _, content, _, sig, _ = route("/", None, None, None, "/")
    assert content is no_update and sig is no_update
    for path, words in (("/challenge/me", "My Challenge"), ("/leaderboards", "Leaderboard"),
                        ("/learn", "Training Ground")):  # fmt: skip
        home, content, _, sig, mounted = route(path, None, None, None, "/")
        assert home is None and words in jtext(content) and sig is None and mounted == path
    home, content, _, _, _ = route("/nowhere", None, None, None, None)
    text = jtext(content)
    assert home is None and "Page not found" in text and "Back to Portfolio Build" in text


def test_screener_is_hidden_until_the_router_shows_it(data):  # noqa: F811
    """No flash of the Match Lab on the Portfolio Build home page before routing."""
    layout = json.loads(_app(data).server.test_client().get("/_dash-layout").get_data())

    def find(node):
        if isinstance(node, dict):
            props = node.get("props", {})
            if props.get("id") == "screener-root":
                return props
            return find(props.get("children"))
        if isinstance(node, list):
            return next((r for n in node if (r := find(n)) is not None), None)
        return None

    assert find(layout)["style"] == {"display": "none"}


def test_layout_component_ids_are_unique(data):  # noqa: F811
    layout = _app(data).server.test_client().get("/_dash-layout").get_data(as_text=True)
    ids = re.findall(r'"id":\s*("[^"]+")', layout)
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes


def test_match_lab_only_callbacks_follow_the_lab_route(data):  # noqa: F811
    app = _app(data)
    open_lab = _named(app, "open_lab")  # CP3A-3: the address names fixture and context
    assert open_lab("/lab", "?fixture=7&ctx=research") == {"fixture": 7, "ctx": "research"}
    assert open_lab("/", "?fixture=7&ctx=research") is no_update  # not the Match Lab
    assert open_lab("/lab", "?fixture=x") == {"invalid": True}
    assert open_lab("/lab", "") is None  # the tab itself: restore the last valid match
    strip = _named(app, "screener_strip")  # challenge matches in the Match Lab only
    assert strip(None, "/") is None and strip(None, "/learn") is None
    assert strip(None, "/lab", {"fixture": 7, "ctx": "research"}) is None
    context = _named(app, "data_context")  # above the research list only
    assert context("all", "/learn") is no_update and context("all", "/lab") is no_update
    assert context("all", "/") is not no_update
    sync = _named(app, "sync_round_views")
    assert sync("/lab", {}, None) is no_update and sync("/leaderboards", {}, None) is no_update


def test_portfolio_round_views_load_on_portfolio_build(data, monkeypatch):  # noqa: F811
    """The saved frozen Your View for the published round is loaded when Portfolio
    Build (formerly /challenge) or My Challenge opens, exactly as before."""
    from diski9.app.challenge import lab_persist

    calls = []
    monkeypatch.setattr(lab_persist, "load_round", lambda service, lab: calls.append(1) or None)
    sync = _named(_app(data), "sync_round_views")
    for path in ("/", "/challenge", "/challenge/me"):
        sync(path, {}, None)
    assert len(calls) == 3
    sync("/", {}, "pending")  # never while a guest-work decision is pending
    assert len(calls) == 3


def test_internal_links_use_the_new_routes():
    sources = "\n".join(p.read_text() for p in SRC.rglob("*.py"))
    assert 'href="/challenge"' not in sources and "next=/challenge" not in sources
    assert 'href=f"/?fixture=' not in sources and 'href=f"/lab?fixture=' not in sources
    # CP3A-3: every Match Lab link names its context (builder card and guidance panel)
    assert sources.count("CHALLENGE if round_id else RESEARCH, round_id)") == 2
    # the rendered risk-panel links are checked in test_a3_guidance


def test_learn_page_is_a_plain_page():
    text = jtext(pages.learn_page())
    assert "Training Ground" in text and "Go to Portfolio Build" in text
    assert "coming soon" not in text.lower()


# ------------------------------------------------------------------- browser
BROWSER = r"""
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch();
  const out = { errors: [], widths: {} };
  const sel = (o) => `[id='${JSON.stringify(o)}']`;
  for (const w of [390, 768, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 900 } });
    const p = await ctx.newPage();
    p.on('pageerror', e => out.errors.push(w + ': ' + e.message));
    const r = {};
    const overflow = () => p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    const active = () => p.locator('.nav-link.on').allInnerTexts();
    const shot = async (name) => { if (SHOTS) await p.screenshot({ path: `${SHOTS}/cp3a1_${name}_${w}.png`, fullPage: false }); };
    // Portfolio Build is the home page; the Match Lab stays hidden there
    await p.goto(BASE);  // CP3A-2: no challenge in the test data, Research only starts ON
    await p.waitForSelector('#research-only'); if (await p.locator('#research-only input').isChecked()) { await p.locator('.pb-switch-label').click(); } await p.waitForSelector('.ch-page', { state: 'visible' });
    r.homeActive = await active();
    r.labHiddenOnHome = await p.locator('#screener-root').isHidden();
    r.tabs = await p.locator('#site-nav-links .nav-link').allInnerTexts();
    r.overflowHome = await overflow();
    await shot('portfolio');
    // demonstration picks survive a trip to the Match Lab and back
    await p.locator(sel({ m: 'demo', t: 'mode' })).click();
    await p.waitForSelector('text=Demonstration round.');
    const picks = p.locator("[id*='\"t\":\"pick\"']");
    await picks.first().waitFor();
    await picks.nth(0).click(); await p.waitForTimeout(300); await p.waitForLoadState('networkidle');
    r.totalBefore = await p.locator('.ch-total').first().innerText();
    // the Match Lab tab (client-side navigation)
    await p.locator('#site-nav-links .nav-link', { hasText: 'Match Lab' }).click();
    await p.waitForURL(/\/lab$/);
    // CP3A-3: the Match Lab alone; with nothing chosen yet, its empty state
    await p.waitForSelector('#lab-empty', { state: 'visible', timeout: 20000 });
    r.labActive = await active();
    r.overflowLab = await overflow();
    await shot('matchlab');
    await p.locator('#site-nav-links .nav-link', { hasText: 'Portfolio Build' }).click();
    await p.waitForSelector('.ch-page');
    await p.waitForFunction((t) => document.querySelector('.ch-total') && document.querySelector('.ch-total').innerText === t, r.totalBefore);
    r.totalAfter = await p.locator('.ch-total').first().innerText();
    // Training Ground (route /learn): the longer label stays on one line, inside the bar
    r.navFit = await p.evaluate(() => {
      const links = [...document.querySelectorAll('#site-nav-links .nav-link')];
      const tg = links.find(a => a.innerText === 'Training Ground');
      const lh = parseFloat(getComputedStyle(tg).lineHeight) || 20;
      const bar = document.querySelector('.site-nav');
      return { oneLine: tg.getBoundingClientRect().height < 2 * lh,
               inside: tg.getBoundingClientRect().right <= bar.getBoundingClientRect().right + 0.5
                       || getComputedStyle(document.querySelector('#site-nav-links')).overflowX !== 'visible' };
    });
    await p.locator('#site-nav-links .nav-link', { hasText: 'Training Ground' }).click();
    await p.waitForSelector('text=Go to Portfolio Build');
    r.learnActive = await active();
    r.overflowLearn = await overflow();
    await shot('learn');
    // old addresses (full page loads)
    await p.goto(BASE + 'challenge'); await p.waitForSelector('.ch-page');
    r.legacyUrl = new URL(p.url()).pathname;
    r.legacyActive = await active();
    await p.goto(BASE + '?fixture=' + FID);  // old deep link: redirected to the Match Lab
    // CP3A-3: a full page load now opens the match (latest data: the link names no context)
    await p.waitForSelector('#lab-home-input', { state: 'visible', timeout: 20000 });
    const u = new URL(p.url()); r.deepLink = u.pathname + u.search;
    r.deepLinkActive = await active();
    // in-app Match Lab link (what the cards render), from Portfolio Build
    await p.locator('#site-nav-links .nav-link', { hasText: 'Portfolio Build' }).click();
    await p.waitForSelector('.ch-page');
    await p.evaluate((fid) => { window.history.pushState({}, '', '/lab?fixture=' + fid + '&ctx=research');
      window.dispatchEvent(new CustomEvent('_dashprivate_pushstate')); }, FID);
    await p.waitForSelector('#lab-home-input', { state: 'visible', timeout: 20000 });
    r.linkOpened = new URL(p.url()).pathname;
    out.widths[w] = r;
    await ctx.close();
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_navigation_at_three_widths(data):  # noqa: F811
    """Guest navigation through the five tabs at 390, 768 and 1280 px: Portfolio Build
    is home, the Match Lab is at /lab, Training Ground opens, picks survive the round trip, old
    addresses land on the right page, and nothing scrolls horizontally. Set
    ``DISKI9_SHOTS`` to a directory to save screenshots for visual review."""
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    from .test_app import EPL_FIX, _free_port

    port = _free_port()
    server = make_server("127.0.0.1", port, _app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    shots = os.environ.get("DISKI9_SHOTS", "")
    head = (f"const BASE = 'http://127.0.0.1:{port}/'; const FID = {EPL_FIX}; "
            f"const SHOTS = {json.dumps(shots)};\n")  # fmt: skip
    try:
        res = subprocess.run(["node", "-e", head + BROWSER], capture_output=True, text=True,
                             timeout=300)  # fmt: skip
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()
    assert out["errors"] == []
    for w, r in out["widths"].items():
        assert r["tabs"] == ["Portfolio Build", "Match Lab", "My Challenge", "Training Ground",
                             "Leaderboard"], w  # fmt: skip
        assert r["homeActive"] == ["Portfolio Build"] and r["labHiddenOnHome"], w
        assert r["labActive"] == ["Match Lab"] and r["learnActive"] == ["Training Ground"], w
        assert r["navFit"] == {"oneLine": True, "inside": True}, (w, r["navFit"])
        assert r["totalBefore"] == r["totalAfter"] and r["totalBefore"].startswith("1"), w
        assert r["legacyUrl"] == "/" and r["legacyActive"] == ["Portfolio Build"], w
        assert r["deepLink"] == f"/lab?fixture={EPL_FIX}" and r["deepLinkActive"] == ["Match Lab"]
        assert r["linkOpened"] == "/lab", w  # the in-app link reached the Match Lab callback
        assert r["overflowHome"] == r["overflowLab"] == r["overflowLearn"] == 0, (w, r)
