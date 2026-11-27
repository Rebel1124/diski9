"""Phase 8 CP3A-3: Portfolio Build as the single fixture-selection entry point, the
simplified Match Lab, navigation with the originating context, direct links and
restoration, the Minimum Market Probability filter, read-only access to locked
challenges and the model wording in the footer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading

import pytest
from dash import no_update
from dash.exceptions import PreventUpdate

from diski9.app import lab_context
from diski9.app.app import footer_text, results_payload
from diski9.app.challenge import integration, pages
from diski9.app.challenge.service import ChallengeService
from diski9.app.links import lab_href

from .test_app import EPL_FIX, PSL_FIX, data, page_ids, populated  # noqa: F401  (fixtures)
from .test_challenge_ui import jtext
from .test_phase8_cp3a1 import _app, _named


def _live(data):  # noqa: F811
    svc = ChallengeService(data)
    snap = svc.snapshot("live")
    assert (
        snap is not None and not snap.is_demo and EPL_FIX in {f.fixture_id for f in snap.fixtures}
    )
    return svc, snap


def challenge(snap, fid=EPL_FIX, **kw):
    return {"fixture": fid, "ctx": "challenge", "round": snap.round_id, "fp": snap.fingerprint,
            **kw}  # fmt: skip


# ------------------------------------------------------------------ links and targets
def test_links_name_fixture_context_and_round():
    assert lab_href(9001, "research") == "/lab?fixture=9001&ctx=research"
    assert lab_href(9001, "challenge", "R1") == "/lab?fixture=9001&ctx=challenge&round=R1"
    assert lab_href(9001, "research", "R1") == "/lab?fixture=9001&ctx=research"  # no round


def test_targets_resolve_in_their_own_context(data):  # noqa: F811
    svc, snap = _live(data)
    frozen, problem = lab_context.resolve_target(svc, data, challenge(snap))
    assert (
        problem is None and frozen.kind == "round" and frozen.key == f"r:{snap.round_id}:{EPL_FIX}"
    )
    latest, _ = lab_context.resolve_target(svc, data, {"fixture": EPL_FIX, "ctx": "research"})
    assert latest.kind == "live" and latest.key == str(EPL_FIX)  # same fixture, other context
    assert frozen.key != latest.key  # separate Your View storage


def test_unavailable_frozen_context_is_never_replaced_by_latest_data(data):  # noqa: F811
    svc, snap = _live(data)
    for bad in (challenge(snap, round="another-round"), challenge(snap, fp="changed-snapshot"),
                challenge(snap, fid=PSL_FIX), challenge(snap, round=None)):  # fmt: skip
        assert lab_context.resolve_target(svc, data, bad) == (None, lab_context.CHALLENGE_GONE)
    # PSL_FIX exists in the latest data: still never shown for the challenge context
    assert lab_context.resolve_target(svc, data, {"fixture": PSL_FIX, "ctx": "research"})[0]


def test_missing_invalid_and_empty_targets_fail_safely(data):  # noqa: F811
    svc = ChallengeService(data)
    r = lab_context.resolve_target
    assert r(svc, data, None) == (None, lab_context.NO_TARGET)
    assert r(svc, data, {"invalid": True}) == (None, lab_context.INVALID)
    assert r(svc, data, {"fixture": "9001", "ctx": "research"}) == (None, lab_context.INVALID)
    assert r(svc, data, {"fixture": 9001, "ctx": "elsewhere"}) == (None, lab_context.INVALID)
    assert r(svc, data, {"fixture": 424242, "ctx": "research"}) == (None, lab_context.MISSING)


def test_open_lab_reads_the_address(data):  # noqa: F811
    app = _app(data)
    _, snap = _live(data)
    open_lab = _named(app, "open_lab")
    assert open_lab("/lab", f"?fixture={EPL_FIX}&ctx=challenge&round={snap.round_id}") == \
        challenge(snap)  # fmt: skip
    # a stale round is recorded as asked, without a fingerprint: it will fail safely
    assert open_lab("/lab", f"?fixture={EPL_FIX}&ctx=challenge&round=old")["fp"] is None
    assert open_lab("/lab", f"?fixture={EPL_FIX}")["ctx"] == "research"  # old link: latest data
    assert open_lab("/lab", "?fixture=1;drop") == {"invalid": True}
    assert open_lab("/lab", "") is None and open_lab("/leaderboards", "?fixture=1") is no_update


def test_match_lab_restores_the_last_valid_match(data):  # noqa: F811
    detail = _named(_app(data), "update_detail")
    target = {"fixture": EPL_FIX, "ctx": "research"}
    body, ref, _, saved, active = detail(target, "1X2", "/lab", None, {})
    assert "lab-empty" not in json.dumps(body, default=str) and saved == target == active
    # the tab itself (no fixture in the address): the last valid match again
    body, _, _, saved, active = detail(None, "1X2", "/lab", target, {})
    assert saved is no_update and active == target and "lab-empty" not in str(body)
    # an invalid link: an explanation; the last valid match is kept for the tab
    body, _, _, saved, active = detail({"invalid": True}, "1X2", "/lab", target, {})
    assert "This match link is not valid" in jtext(body) and saved is no_update and active is None
    # nothing at all: the empty state, never an arbitrary match
    body, _, _, saved, active = detail(None, "1X2", "/lab", None, {})
    text = jtext(body)
    assert "No match selected" in text and "Go to Portfolio Build" in text and active is None


def test_match_lab_has_no_selectors(data):  # noqa: F811
    layout = json.loads(_app(data).server.test_client().get("/_dash-layout").get_data())

    def subtree(node, wanted):
        if isinstance(node, dict):
            props = node.get("props", {})
            if props.get("id") == wanted:
                return node
            return subtree(props.get("children"), wanted)
        if isinstance(node, list):
            return next((r for n in node if (r := subtree(n, wanted)) is not None), None)
        return None

    lab = json.dumps(subtree(layout, "lab-root"))
    for cid in ("universe", "leagues", "dates", "market", "direction", "threshold",
                "results-table", "results-cards", "pager"):  # fmt: skip
        assert f'"id": "{cid}"' not in lab, cid
    for cid in ("lab-back", "detail", "lab-challenge", "detail-reference", "ch-strip"):
        assert f'"id": "{cid}"' in lab, cid
    research = json.dumps(subtree(layout, "screener-root"))
    assert '"id": "detail"' not in research and '"id": "results-table"' in research


def test_research_selection_opens_the_match_lab(data):  # noqa: F811
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    nav = _named(_app(data), "open_from_research")
    trig = {"prop_id": json.dumps({"index": EPL_FIX, "type": "row"}) + ".n_clicks", "value": 1}
    context_value.set(AttributeDict(triggered_inputs=[trig]))
    # the list's market is carried across to the Match Lab's own market control
    assert nav([1], [], "/", "BTTS") == ("/lab", f"?fixture={EPL_FIX}&ctx=research", "BTTS")
    with pytest.raises(PreventUpdate):  # only from the research list in Portfolio Build
        nav([1], [], "/lab")
    context_value.set(AttributeDict(triggered_inputs=[{**trig, "value": 0}]))
    with pytest.raises(PreventUpdate):  # re-rendered rows, not a click
        nav([0], [], "/")


def test_competitive_controls_only_for_challenge_matches(data):  # noqa: F811
    app = _app(data)
    _, snap = _live(data)
    panel, strip = _named(app, "match_lab_panel"), _named(app, "screener_strip")
    research = {"fixture": EPL_FIX, "ctx": "research"}
    assert panel(research, None, {}, None, "/lab") is None
    assert strip(None, "/lab", research) is None
    assert panel(challenge(snap), None, {}, None, "/lab") is not None  # the challenge panel


# ------------------------------------------------------------------ Minimum Market Probability
def _market_max(data, fid, market="1X2"):  # noqa: F811
    from diski9.app.data import MARKET_OF, MARKET_OUTCOME_ORDER

    dm = data.snapshot().odds[fid].markets[MARKET_OF[market]]
    adj = dm.implied.margin_adjusted if (dm.status == "fresh" and dm.implied) else None
    return max(float(adj[o]) for o in MARKET_OUTCOME_ORDER[MARKET_OF[market]]) if adj else None


def test_market_minimum_boundaries_and_missing_data(data):  # noqa: F811
    snap = data.snapshot()
    fresh = [fid for fid in snap.results["overall"] if _market_max(data, fid) is not None]
    without = [fid for fid in snap.results["overall"] if _market_max(data, fid) is None]
    assert fresh and without
    r = snap.results["overall"]
    for fid in fresh:  # inclusive at the fixture's own highest market probability
        top = _market_max(data, fid)
        assert data.meets_market("1X2", r[fid], top)
        assert not data.meets_market("1X2", r[fid], top + 0.0001)
    for fid in without:  # no fresh consensus: never qualifies above zero
        assert not data.meets_market("1X2", r[fid], 0.01)

    def total(t, direction="kickoff_earliest"):
        p = results_payload(data, "1X2", [39, 288], None, "2026-12-31", "overall", direction, t, 1)
        return int(p[2].split(" of ")[1].split()[0]) if p[2] else 0

    assert total(0) == len(snap.results["overall"])  # 0%: every match, odds or not
    assert total(100) == 0 and total(1) == len(fresh)
    for direction in ("home_win", "edge", "ev", "kickoff_latest"):  # independent of ranking
        assert total(40, direction) == total(40)


def test_all_outcomes_stay_visible_for_an_included_fixture(data):  # noqa: F811
    snap = data.snapshot()
    fid = max((f for f in snap.results["overall"] if _market_max(data, f)),
              key=lambda f: _market_max(data, f))  # fmt: skip
    top = round(_market_max(data, fid) * 100)
    p = results_payload(data, "1X2", [39, 288], None, "2026-12-31", "overall", "kickoff_earliest",
                        top - 1, 1)  # fmt: skip
    assert fid in page_ids(p)
    row = data.row("1X2", snap.results["overall"][fid])
    assert row["market"].count("%") == 3  # home, draw and away still displayed


def test_builder_minimum_filters_outcomes_on_frozen_consensus_only(data):  # noqa: F811
    svc = ChallengeService(data)
    snap = svc.demo()
    keys = [str("|".join(map(str, o.key))) for o in snap.outcomes[:2]]
    sels = [k for k in keys]
    cards, count = pages.fixture_list(svc, snap, sels, {"mmp": 0}, data.local, False)
    all_n = int(count.split(" of ")[1].split()[0])
    _, high = pages.fixture_list(svc, snap, sels, {"mmp": 70}, data.local, False)
    assert "filtered from" in high or high.startswith("0 of")
    shown = json.dumps(pages.fixture_list(svc, snap, sels, {"mmp": 70}, data.local, False)[0],
                       default=str)  # fmt: skip
    for o in snap.outcomes:  # every outcome button shown meets the frozen minimum
        bid = json.dumps({"k": "|".join(map(str, o.key)), "t": "pick"})
        if bid in shown:
            assert o.market_probability >= 0.70 - 1e-12
    assert all_n >= 1
    # the filter never changes the portfolio, eligibility or buckets
    assert sels == keys


def test_frozen_ordering_uses_frozen_market_probabilities():
    ch = {"frozen": {1: {"market": {"home": 0.62, "draw": 0.23, "away": 0.15}},
                     2: {"market": {"home": 0.40, "draw": 0.30, "away": 0.30}}}, "values": {}}  # fmt: skip
    rows = [{"fixture": {"id": i, "kickoff": "2026-11-28T12:00:00+00:00"},
             "goal_model": {"available": False, "probabilities": {}}} for i in (1, 2)]  # fmt: skip

    def ids(t, d="kickoff_earliest"):
        return [r["fixture"]["id"] for r in integration.frozen_order(ch, rows, "1X2", d, t)]

    assert ids(None) == [1, 2] and ids(0.60) == [1] and ids(0.62) == [1] and ids(0.63) == []
    assert ids(0.60, "home_win") == [1]  # model-absent: kept and ranked last, never dropped


# ------------------------------------------------------------------ locked access, wording
def test_locked_round_shows_published_fixtures_read_only(data, monkeypatch):  # noqa: F811
    from diski9.app.challenge import callbacks as cb
    from diski9.challenge.roundsheet import RoundAvailability, RoundStatus

    svc, snap = _live(data)
    locked = RoundAvailability(RoundStatus.LOCKED, "Round locked", "m", None)
    view = pages.unavailable(svc, None, "live", snap, locked, data.local)
    text = jtext(view)
    assert pages.LOCKED_NOTICE in text and "Published fixtures" in text
    picks = [b for b in _walk(json.loads(text)) if (b.get("id") or {}).get("t") == "pick"]
    assert picks and all(b.get("disabled") is True for b in picks)  # read-only picks
    assert "/lab?fixture=" in text and "ctx=challenge" in text  # frozen analysis links
    # whatever the route or link, a pick is refused once the round is locked
    monkeypatch.setattr(ChallengeService, "availability", lambda self, mode: locked)
    key = "|".join(map(str, snap.outcomes[0].key))
    state, flash = cb.apply_action(svc, {"mode": "live"}, "pick", key)
    assert "locked" in flash["text"] and key not in (state.get("selections") or [])


def test_locked_match_lab_panel_is_read_only(data, monkeypatch):  # noqa: F811
    from diski9.challenge.roundsheet import RoundAvailability, RoundStatus

    svc, snap = _live(data)
    monkeypatch.setattr(ChallengeService, "availability", lambda self, mode: RoundAvailability(
        RoundStatus.LOCKED, "Round locked", "m", None))  # fmt: skip
    text = jtext(integration.lab_panel(svc, data, None, EPL_FIX, {}, None))
    assert "entries are closed" in text and "no longer be added or changed" in text


def _walk(node):
    """Every component's props in a serialised layout."""
    if isinstance(node, dict):
        props = node.get("props", {})
        yield props
        for v in props.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for n in node:
            yield from _walk(n)


def test_footer_distinguishes_the_two_models():
    text = footer_text()
    assert "never used by the model" not in text
    assert "results and goals, not bookmaker odds" in text
    assert "market-implied model may estimate expected goals from market probabilities" in text


def test_challenge_strip_shows_portfolio_progress_for_challenge_matches(data, monkeypatch):  # noqa: F811
    from .test_challenge_state import LiveService, submitted_live

    svc = LiveService()
    state, _ = submitted_live(svc)
    app = _app(data)
    strip = _named(app, "screener_strip")
    import diski9.app.challenge.callbacks as cbm

    original = integration.progress_strip
    monkeypatch.setattr(cbm.integration, "progress_strip", lambda service, st: original(svc, st))
    shown = strip(state, "/lab", {"fixture": 1, "ctx": "challenge"})
    assert shown is not None and "9/9" in jtext(shown)
    assert strip(state, "/lab", {"fixture": 1, "ctx": "research"}) is None


# ------------------------------------------------------------------- browser
BROWSER = r"""
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const out = { errors: [], widths: {} };
  for (const w of [390, 768, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 900 } });
    const p = await ctx.newPage();
    p.on('pageerror', e => out.errors.push(w + ': ' + e.message));
    const r = {};
    const shot = async (n) => { if (SHOTS) await p.screenshot({ path: `${SHOTS}/cp3a3_${n}_${w}.png` }); };
    const overflow = () => p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    const item = w < 720 ? '#screener-root .fx-card' : '#screener-root tr.row';
    const summary = () => p.locator('#summary').innerText();
    // the Match Lab tab before anything is chosen: the empty state
    await p.goto(BASE + 'lab'); await p.waitForSelector('#lab-empty', { state: 'visible' });
    r.empty = await p.locator('#lab-empty h2').innerText();
    r.overflowEmpty = await overflow(); await shot('lab_empty');
    // the research list (Portfolio Build): Minimum Market Probability under kickoff ranking
    await p.goto(BASE); await p.waitForSelector(item, { state: 'visible', timeout: 20000 });
    r.label = await p.locator('#threshold-label').innerText();
    const before = await summary();
    await p.locator('#threshold [role=slider]').focus();
    for (let i = 0; i < 40; i++) await p.keyboard.press('ArrowRight');
    await p.waitForFunction((s) => document.querySelector('#summary').innerText !== s, before);
    r.filtered = [before, await summary()];
    r.rank = await p.locator('#ranked-by').innerText();
    await p.locator('#threshold').scrollIntoViewIfNeeded(); await shot('mmp_kickoff');
    await p.keyboard.press('Home');
    await p.waitForFunction((s) => document.querySelector('#summary').innerText === s, before);
    // page 2, open a match: the Match Lab alone, with its own market control
    await p.locator('#next').click();
    await p.waitForFunction(() => document.querySelector('#summary').innerText.startsWith('Showing 11'));
    const page = await p.locator('#page-label').innerText();
    await p.locator(item).first().click();
    await p.waitForURL(/\/lab\?fixture=\d+&ctx=research/);
    await p.waitForFunction(() => (document.querySelector('#detail') || {}).innerText.length > 50);
    r.listHidden = await p.locator('#screener-root').isHidden();
    r.selectors = await p.evaluate(() => ['#market', '#leagues', '#dates', '#universe', '#direction']
      .filter(s => { const e = document.querySelector(s); return e && e.offsetParent !== null; }));
    r.labMarket = await p.locator('#lab-market').isVisible();
    r.panel = (await p.locator('#lab-challenge').innerText()).trim();
    const title = await p.locator('.detail-header h2').innerText();
    r.overflowLab = await overflow(); await shot('lab_research');
    // back to Portfolio Build: the same list and page
    await p.locator('#lab-back').click(); await p.waitForSelector(item, { state: 'visible' });
    r.pageKept = (await p.locator('#page-label').innerText()) === page;
    r.overflowBack = await overflow(); await shot('research_return');
    // the Match Lab tab restores the last valid match
    await p.locator('#site-nav-links .nav-link', { hasText: 'Match Lab' }).click();
    await p.waitForFunction((t) => document.querySelector('.detail-header h2') &&
      document.querySelector('.detail-header h2').innerText === t, title);
    r.restored = true;
    out.widths[w] = r;
    await ctx.close();
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_portfolio_build_to_match_lab_at_three_widths(data):  # noqa: F811
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
        assert r["empty"] == "No match selected", w
        assert r["label"].lower() == "minimum market probability" and "Kickoff" in r["rank"], w
        assert r["filtered"][0] != r["filtered"][1], w  # it filters under kickoff ranking
        assert r["listHidden"] and r["selectors"] == [] and r["labMarket"], w
        assert r["panel"] == "", w  # research: no competitive controls
        assert r["pageKept"] and r["restored"], w
        assert r["overflowEmpty"] == r["overflowLab"] == r["overflowBack"] == 0, (w, r)
