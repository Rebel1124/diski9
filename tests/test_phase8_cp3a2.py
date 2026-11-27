"""Phase 8 CP3A-2: the Portfolio Build home, the Domestic Weekly Challenge card, the
local Research only toggle and its context-dependent default, status messaging and
the frozen-snapshot notice.

Status states are tested with stub backends (the shapes of the real round record);
the real PostgreSQL round and schedule are covered in
tests/backend/test_backend_phase8_cp3a2.py."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from dash import no_update

from diski9.app.challenge import home, pages

from .test_app import EPL_FIX, data, populated  # noqa: F401  (fixtures)
from .test_challenge_ui import jtext
from .test_phase8_cp3a1 import _app, _named

NOW = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)


def local(dt, fmt="%a %d %b, %H:%M"):
    return dt.strftime(fmt)


def view(status, deadline=NOW + timedelta(hours=5), **kw):
    base = {"code": "2026-W48", "status": status, "window_start_at": NOW,
            "window_end_at": NOW + timedelta(days=4), "deadline_at": deadline,
            "snapshot_at": NOW - timedelta(hours=2), "is_development": False}  # fmt: skip
    return SimpleNamespace(**{**base, **kw})


def service(found=None, error=False):
    backend = SimpleNamespace(published=lambda: found, error=error, engine=None,
                              show_development=False)  # fmt: skip
    return SimpleNamespace(backend=backend, now=lambda: NOW)


def status(found=None, *, error=False, target=None):
    snap = SimpleNamespace(snapshot_at=NOW - timedelta(hours=2))
    found = (found, snap) if found is not None else None
    timing = (NOW, target) if target is not None else None
    return home.challenge_status(service(found, error), local, target_fn=lambda b: timing,
                                 championship=False)  # fmt: skip


# ------------------------------------------------------------------ status
def test_open_locked_and_settling_from_the_published_round():
    st = status(view("open"))
    assert st.state == home.OPEN and st.message == "Entries close Fri 27 Nov, 15:00 SAST."
    assert st.round_code == "2026-W48" and st.deadline == NOW + timedelta(hours=5)
    assert st.frozen_at == NOW - timedelta(hours=2) and not st.default_research
    past = status(view("open", deadline=NOW - timedelta(minutes=1)))  # deadline passed
    assert past.state == home.LOCKED and past.message == home.MSG_LOCKED
    assert status(view("locked")).message == "Entries closed. Awaiting match results."
    st = status(view("settling"))
    assert st.state == home.SETTLING and st.message == "Results are being settled."
    for s in ("open", "locked", "settling"):
        assert not status(view(s)).default_research  # Research only OFF


def test_no_current_challenge_is_upcoming_until_the_scheduled_time_then_unavailable():
    target = NOW + timedelta(days=1)
    for found in (None, view("final")):  # no round yet, or the last one is final
        st = status(found, target=target)
        assert st.state == home.UPCOMING and st.target == target
        assert st.message == ("Next challenge expected to open Sat 28 Nov, 10:00 SAST, "
                              "subject to fixture availability.")  # fmt: skip
        assert st.default_research  # Research only ON
        gone = status(found, target=NOW - timedelta(hours=1))
        assert gone.state == home.UNAVAILABLE and gone.default_research
        assert gone.message == ("No Weekly Challenge available this week. You can still "
                                "research upcoming matches.")  # fmt: skip
        assert gone.reason is None  # no reason is invented
    assert status(None).state == home.UNAVAILABLE  # the schedule could not be read


def test_a_final_round_never_shows_stale_locked_messaging():
    """International break: last week's round is final and nothing new is published."""
    st = status(view("final"), target=NOW - timedelta(hours=3))
    assert st.state == home.UNAVAILABLE and "locked" not in st.message.lower()
    assert "progress" not in st.message.lower()


def test_competition_data_errors_are_explained_without_a_false_reason():
    st = status(None, error=True)
    assert st.state == home.UNAVAILABLE and st.message == home.MSG_DATA_ERROR


def test_prototype_mode_status_and_verified_reason(data):  # noqa: F811
    from diski9.app.challenge.service import ChallengeService

    st = home.challenge_status(ChallengeService(data), data.local)
    assert st.state == home.UNAVAILABLE and st.default_research
    assert st.reason == "Not enough eligible fixtures"  # the opening assessment's verdict


def test_research_default_and_explicit_session_choice():
    open_, none = status(view("open")), status(None, target=NOW + timedelta(days=1))
    assert home.research_on(None, open_) is False and home.research_on({}, none) is True
    assert home.research_on({"research": True}, open_) is True  # the participant's choice
    assert home.research_on({"research": False}, none) is False
    assert home.research_on({"source": "model"}, none) is True  # other preferences ignored


# ------------------------------------------------------------------ layout
def test_home_wording_icon_and_no_european_card(data):  # noqa: F811
    from diski9.app.challenge.service import ChallengeService

    tree = home.portfolio_home(ChallengeService(data), data.local, None)
    text = jtext(tree)
    for words in ("Think you know football?", "Put your skills to the test!",
                  "9 picks. 100 virtual credits. One challenge.",
                  "Free to play. No real money. Just football.", "Domestic Weekly Challenge"):  # fmt: skip
        assert words in text
    assert "ic-football" in text and "pb-ball" in text
    assert "European" not in text and "Coming soon" not in text.title()


def test_card_facts_research_group_and_action(data):  # noqa: F811
    st = home.ChallengeStatus(home.OPEN, "Entries close X.", round_code="2026-W48",
                              window=(NOW, NOW + timedelta(days=4)), deadline=NOW,
                              championship="Championship Nov-26", counted=3, required=10)  # fmt: skip
    card = home.domestic_card(st, local, research=False)
    text = jtext(card)
    for words in ("Championship Nov-26", "3 of 10 rounds completed", "Round 2026-W48", "Open",
                  "Fixtures", "Fri 27 Nov", "Tue 01 Dec", "Entry deadline", "Entries close X.",
                  home.ACTION_BUILD):  # fmt: skip
        assert words in text
    group = next(k for k in card.children if getattr(k, "className", "") == "pb-research")
    switch, tip = group.children  # label + switch (one control), then the info icon
    assert switch.id == "research-only" and switch.value == []
    assert switch.options == [{"label": "Research only", "value": "on"}]
    assert home.RESEARCH_TIP in jtext(tip) and "Weekly Challenge" in home.RESEARCH_TIP
    on = home.domestic_card(st, local, research=True)
    assert home.ACTION_RESEARCH in jtext(on)
    up = home.ChallengeStatus(home.UPCOMING, "m", target=NOW)
    assert "Expected" in jtext(home.domestic_card(up, local, True))


def test_snapshot_notice_carries_the_stored_time():
    snap = SimpleNamespace(is_demo=False, snapshot_at=NOW)
    rv = SimpleNamespace(snapshot_at=NOW - timedelta(minutes=5))
    text = jtext(pages.frozen_note(snap, rv, local))
    assert "frozen when this challenge was published" in text
    assert "Fri 27 Nov, 09:55 SAST" in text and "may differ" in text
    assert pages.frozen_note(SimpleNamespace(is_demo=True, snapshot_at=NOW), rv, local) is None
    assert pages.frozen_note(snap, None, local) is None  # prototype rounds are not published


def test_research_note_and_latest_data_line(data):  # noqa: F811
    note = jtext(home.mode_note(True))
    assert "latest available data" in note and "not part of the Weekly Challenge" in note
    assert home.mode_note(False) is None
    context = _named(_app(data), "data_context")("all", "/")
    text = jtext(context)
    assert "Latest available data" in text and "Model updated" in text
    assert "own collection times" in text and "live" not in text.lower()


# ------------------------------------------------------------------ callbacks
def test_toggle_writes_only_explicit_choices(data):  # noqa: F811
    app = _app(data)
    set_research = _named(app, "set_research")
    assert set_research(["on"], {"source": "model"}) == {"source": "model", "research": True}
    assert set_research([], {"research": True}) == {"research": False}
    assert set_research([], {"research": False}) is no_update
    widgets = _named(app, "research_widgets")
    assert widgets(["on"])[0] == home.ACTION_RESEARCH and widgets(["on"])[1] is not None
    assert widgets([]) == (home.ACTION_BUILD, None)
    registered = next(v for k, v in app.callback_map.items() if "pb-go.children" in k)
    assert registered["inputs"] == [{"id": "research-only", "property": "value"}]


def test_layout_mode_shows_the_chosen_list(data):  # noqa: F811
    mode = _named(_app(data), "layout_mode")
    shown, hidden = {"display": "block"}, {"display": "none"}
    # research list: the Screener in Portfolio Build with latest data, builder hidden
    assert mode("/", {"research": True}, "challenge") == (shown, "on-portfolio", hidden, "all")
    assert mode("/", {"research": True}, "all")[3] is no_update  # never resets the filters
    # competitive list: the builder; the Screener is hidden and its universe untouched
    assert mode("/", {"research": False}, "all") == (hidden, "", shown, no_update)
    # no explicit choice: the status default (the test data has no challenge: ON)
    assert mode("/", {}, "challenge")[1] == "on-portfolio"
    assert mode("/lab", {"research": True}, "all") == (shown, "", shown, no_update)
    for path in ("/challenge/me", "/leaderboards", "/learn"):
        assert mode(path, {"research": True}, "all")[0] == hidden


def test_no_competitive_functionality_on_the_research_list(data):  # noqa: F811
    app = _app(data)
    assert _named(app, "match_lab_panel")(EPL_FIX, None, {}, None, "/") is None
    assert _named(app, "screener_strip")(None, "/") is None
    detail = _named(app, "update_detail")
    body = detail(EPL_FIX, "1X2", "/", "all", {}, {"research": True})[0]
    assert body is not None  # analysis with the latest data, beneath the research list
    assert "Weekly Challenge snapshot" not in jtext(body)


def test_universe_control_is_no_longer_visible(data):  # noqa: F811
    layout = _app(data).server.test_client().get("/_dash-layout").get_data(as_text=True)
    blob = json.loads(layout)

    def find(node, cls):
        if isinstance(node, dict):
            props = node.get("props", {})
            if cls in str(props.get("className", "")).split():
                return props
            return find(props.get("children"), cls)
        if isinstance(node, list):
            return next((r for n in node if (r := find(n, cls)) is not None), None)
        return None

    matches = find(blob, "f-matches")
    assert matches["hidden"] is True and matches["style"] == {"display": "none"}
    assert '"pb-home"' in layout


# ------------------------------------------------------------------- browser
BROWSER = r"""
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const out = { errors: [], widths: {} };
  const sel = (o) => `[id='${JSON.stringify(o)}']`;
  for (const w of [390, 768, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 900 } });
    const p = await ctx.newPage();
    p.on('pageerror', e => out.errors.push(w + ': ' + e.message));
    const r = {};
    const shot = async (name) => { if (SHOTS) await p.screenshot({ path: `${SHOTS}/cp3a2_${name}_${w}.png` }); };
    const visible = (s) => p.locator(s).first().isVisible();
    await p.goto(BASE); await p.waitForSelector('#research-only');
    // no challenge in the test data: Research only starts ON (unavailable)
    await p.waitForFunction(() => document.querySelector('#pb-go').innerText === 'Analyse domestic matches');
    r.defaultOn = await p.locator('#research-only input').isChecked();
    r.state = await p.locator('.pb-state').innerText();
    await p.waitForSelector(w < 720 ? '#screener-root .fx-card' : '#screener-root tr.row', { state: 'visible' });
    r.researchListShown = await visible('#screener-root');
    r.builderHidden = await p.locator('#ch-root').isHidden();
    r.note = await p.locator('#pb-mode-note').innerText();
    // label, switch and information icon grouped together on the left of the card
    r.group = await p.evaluate(() => {
      const card = document.querySelector('.pb-domestic').getBoundingClientRect();
      const label = document.querySelector('.pb-switch-label').getBoundingClientRect();
      const sw = document.querySelector('.pb-switch-input').getBoundingClientRect();
      const tip = document.querySelector('.pb-research-info summary').getBoundingClientRect();
      return { order: label.right <= sw.left && sw.right <= tip.left,
               adjacent: sw.left - label.right <= 12 && tip.left - sw.right <= 12,
               left: tip.right <= card.left + card.width * 0.6,
               sameRow: Math.abs((label.top + label.bottom) / 2 - (sw.top + sw.bottom) / 2) < 6 };
    });
    // the information tooltip opens on click/tap (native <details>)
    await p.locator('.pb-research-info summary').click();
    r.tip = await p.locator('.pb-research-info .info-pop').innerText();
    await p.locator('.pb-research-info summary').click();
    r.overflowResearch = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await shot('unavailable_research_on');
    // switch OFF: the competitive list (builder); the research list is hidden
    await p.locator('.pb-switch-label').click();
    await p.waitForFunction(() => document.querySelector('#pb-go').innerText === 'Build domestic portfolio');
    await p.waitForSelector('#ch-root .ch-page', { state: 'visible' });
    r.screenerHiddenOff = await p.locator('#screener-root').isHidden();
    await shot('unavailable_research_off');
    // a demonstration pick survives switching modes and navigating
    await p.locator(sel({ m: 'demo', t: 'mode' })).click();
    await p.waitForSelector('text=Demonstration round.');
    const picks = p.locator("[id*='\"t\":\"pick\"']");
    await picks.first().waitFor();
    await picks.nth(0).click();
    await p.waitForFunction(() => (document.querySelector('.ch-total') || {}).innerText === '1/9');
    await p.locator('.pb-switch-label').click();  // ON
    await p.waitForSelector('#screener-root', { state: 'visible' });
    await p.locator('.pb-switch-label').click();  // OFF again
    await p.waitForSelector('#ch-root .ch-page', { state: 'visible' });
    r.totalAfterSwitch = await p.locator('.ch-total').first().innerText();
    // the explicit choice (OFF) is kept across Match Lab and back, and a reload
    await p.locator('#site-nav-links .nav-link', { hasText: 'Match Lab' }).click();
    await p.waitForURL(/\/lab$/);
    await p.locator('#site-nav-links .nav-link', { hasText: 'Portfolio Build' }).click();
    await p.waitForSelector('#research-only');
    await p.waitForSelector('#ch-root .ch-page', { state: 'visible' });
    r.keptAfterNav = await p.locator('#research-only input').isChecked();
    r.totalAfterNav = await p.locator('.ch-total').first().innerText();
    await p.reload(); await p.waitForSelector('#research-only');
    await p.waitForSelector('#ch-root .ch-page', { state: 'visible' });
    r.keptAfterReload = await p.locator('#research-only input').isChecked();
    r.overflowOff = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    out.widths[w] = r;
    await ctx.close();
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_portfolio_home_at_three_widths(data):  # noqa: F811
    """Guest journey with no challenge available (prototype data): Research only ON by
    default with the research list; OFF shows the builder; a pick survives switching
    and navigation; the explicit choice persists for the session. ``DISKI9_SHOTS``
    saves screenshots."""
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    from .test_app import _free_port

    port = _free_port()
    server = make_server("127.0.0.1", port, _app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    head = (f"const BASE = 'http://127.0.0.1:{port}/'; "
            f"const SHOTS = {json.dumps(os.environ.get('DISKI9_SHOTS', ''))};\n")  # fmt: skip
    try:
        res = subprocess.run(["node", "-e", head + BROWSER], capture_output=True, text=True,
                             timeout=400)  # fmt: skip
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()
    assert out["errors"] == []
    for w, r in out["widths"].items():
        assert r["defaultOn"] and r["state"] == "Not available", w
        assert r["researchListShown"] and r["builderHidden"], w
        assert "not part of the Weekly Challenge" in r["note"], w
        assert r["group"] == {"order": True, "adjacent": True, "left": True, "sameRow": True}, w
        assert home.RESEARCH_TIP in r["tip"], w
        assert r["screenerHiddenOff"], w
        assert r["totalAfterSwitch"] == r["totalAfterNav"] == "1/9", w
        assert r["keptAfterNav"] is False and r["keptAfterReload"] is False, w
        assert r["overflowResearch"] == r["overflowOff"] == 0, (w, r)
