"""Phase 8 CP3A-4B: ML-01, the Match Lab stale-adjustment race.

Every rebuild of the analysis (match, market or frozen/latest change) renders the Your
View inputs from the browser store as it was when the rebuild was requested, and the
rebuilt inputs then make Dash call ``adjust`` with every input listed as changed
(observed: 26 inputs). ``adjust`` used to take the first one as an edit and save it, so
a reset or edit made while the rebuild was in flight came back. Now such a call only
re-shows the stored state (never saving), and only when the store moved on since the
rebuild; saved edits raise the store revision."""

from __future__ import annotations

import json

import pytest
from dash import no_update
from dash._callback_context import context_value
from dash._utils import AttributeDict
from dash.exceptions import PreventUpdate

from diski9.app import lab, lab_context
from diski9.app.challenge import lab_persist
from diski9.app.lab import CATEGORY_KEYS

from .test_app import EPL_FIX, data, populated  # noqa: F401  (fixtures)
from .test_phase8_cp3a1 import _app, _named
from .test_phase8_cp3a3 import _live, challenge

RESEARCH = {"fixture": EPL_FIX, "ctx": "research"}
INPUTS = 13  # adjust's inputs (the gate included), before its states


@pytest.fixture(autouse=True)
def _no_leftover_trigger():
    """Direct callback calls must not see a Dash trigger left by another test."""
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    token = context_value.set(AttributeDict(triggered_inputs=[]))
    yield
    context_value.reset(token)


def _outputs_list():
    cats = [{"id": {"type": "cat-adj", "cat": k, "side": s}} for k in CATEGORY_KEYS
            for s in ("home", "away")]  # fmt: skip
    sliders = [{"id": {"type": "cat-slider", "cat": k, "side": s}} for k in CATEGORY_KEYS
               for s in ("home", "away")]  # fmt: skip
    return [None] * 7 + [cats, [{"id": {"type": "cat-sum", "cat": k}} for k in CATEGORY_KEYS],
                         None, None, None, None, None, sliders]  # fmt: skip


def _mount(rendered_home):
    """The call Dash makes when rebuilt inputs mount: every input listed as changed,
    with the values the rebuild rendered (first: Section B's home slider)."""
    return [{"prop_id": "ctx-home-slider.value", "value": rendered_home},
            {"prop_id": "ctx-home.value", "value": f"{rendered_home:+.2f}"},
            {"prop_id": "ctx-clear.n_clicks", "value": 0},
            {"prop_id": "lab-reset.n_clicks", "value": 0}]  # fmt: skip


def _call(adjust, triggered, active, store, rendered, market="1X2"):
    context_value.set(AttributeDict(triggered_inputs=triggered, outputs_list=_outputs_list()))
    return adjust(*([None] * INPUTS), active, market, store, rendered)


def _ctx_store(lc, home):
    return lab.store_adjustment({}, lc.key, lc.r,
                                lab.normalise_state({"context": {"home": home, "away": 0}}))  # fmt: skip


def _setup(data, target=RESEARCH):  # noqa: F811
    app = _app(data)
    svc = app.server.config["DISKI9_CHALLENGE"]
    lc, _ = lab_context.resolve_target(svc, data, target)
    return app, svc, lc


def test_rebuild_cannot_restore_an_adjustment_reset_meanwhile(data):  # noqa: F811
    """The ML-01 failure: a market change's rebuild was requested with Section B at
    +0.25; the participant reset while it was in flight; the rebuilt inputs mount."""
    app, _, lc = _setup(data)
    older = _ctx_store(lc, 0.25)
    body, *_, rendered = _named(app, "update_detail")(RESEARCH, "BTTS", "/lab", [], RESEARCH,
                                                      older)  # fmt: skip
    assert rendered == {"key": lc.key, "rev": 0}
    now = {**lab.store_adjustment(older, lc.key, lc.r, None), "_rev": 1, "_shown": lc.key}
    out = _call(_named(app, "adjust"), _mount(0.25), RESEARCH, now, rendered)
    assert out[0] is no_update  # the store keeps the reset (before: +0.25 written back)
    assert out[11] == out[12] == "0.00"  # and the inputs show it again


def test_rebuild_with_an_unchanged_store_changes_nothing(data):  # noqa: F811
    app, _, lc = _setup(data)
    store = {**_ctx_store(lc, 0.25), "_rev": 3}
    rendered = {"key": lc.key, "rev": 3}
    with pytest.raises(PreventUpdate):  # its late response can never hide a newer edit
        _call(_named(app, "adjust"), _mount(0.25), RESEARCH, store, rendered)


def test_rebuild_never_saves(data, monkeypatch):  # noqa: F811
    app, _, lc = _setup(data)
    saved = []
    monkeypatch.setattr(lab_persist, "save", lambda *a, **k: saved.append(a) or (a[1], None))
    store = {**_ctx_store(lc, -0.10), "_rev": 2}
    out = _call(_named(app, "adjust"), _mount(0.40), RESEARCH, store, {"key": lc.key, "rev": 1})
    assert out[0] is no_update and out[11] == "-0.10" and not saved  # the store, not 0.40


def test_a_click_merged_into_the_rebuild_call_is_applied(data):  # noqa: F811
    """A reset clicked while the rebuild was pending reaches adjust merged into the
    rebuilt inputs' call, listed first, with the new button's n_clicks (0)."""
    app, _, lc = _setup(data)
    store = {**_ctx_store(lc, 0.25), "_rev": 2}
    merged = [{"prop_id": "ctx-clear.n_clicks", "value": 0}, *_mount(0.25)]
    out = _call(_named(app, "adjust"), merged, RESEARCH, store, {"key": lc.key, "rev": 2})
    assert out[11] == "0.00" and out[0]["_rev"] == 3  # cleared and saved
    assert lab.stored_adjustment(out[0], lc.key, lc.r) is None


def test_an_edit_merged_into_a_rebuild_call_is_applied(data):  # noqa: F811
    """Under load the rebuilt inputs' call can still be pending when the participant
    types; Dash merges the edit into it. Rendered from the current store, every other
    input matches the store, so the differing one is the edit."""
    app, _, lc = _setup(data)
    store = {**_ctx_store(lc, 0.0), "_rev": 1}
    merged = _mount(0.0)
    merged[1] = {"prop_id": "ctx-home.value", "value": "0.25"}  # typed meanwhile
    out = _call(_named(app, "adjust"), merged, RESEARCH, store, {"key": lc.key, "rev": 1})
    assert out[11] == "+0.25" and out[0]["_rev"] == 2
    assert lab.stored_adjustment(out[0], lc.key, lc.r)["context"]["home"] == 0.25


def test_a_real_edit_raises_the_revision(data):  # noqa: F811
    app, _, lc = _setup(data)
    store = {**_ctx_store(lc, 0.0), "_rev": 4}
    out = _call(_named(app, "adjust"), [{"prop_id": "ctx-home.value", "value": "0.30"}],
                RESEARCH, store, {"key": lc.key, "rev": 4})  # fmt: skip
    new = out[0]
    assert new["_rev"] == 5 and out[11] == "+0.30"
    assert lab.stored_adjustment(new, lc.key, lc.r)["context"]["home"] == 0.3


def test_rebuild_of_one_context_never_touches_the_other(data):  # noqa: F811
    app, svc, frozen = _setup(data)
    _, snap = _live(data)
    frozen, _ = lab_context.resolve_target(svc, data, challenge(snap))
    latest, _ = lab_context.resolve_target(svc, data, {**challenge(snap), "latest": True})
    store = lab.store_adjustment(_ctx_store(frozen, 0.25), latest.key, latest.r,
                                 lab.normalise_state({"context": {"home": -0.15, "away": 0}}))  # fmt: skip
    store = {**store, "_rev": 7}
    adjust = _named(app, "adjust")
    # the latest view's rebuild, rendered from an older store (frozen 0.25 only)
    out = _call(adjust, _mount(0.25), {**challenge(snap), "latest": True}, store,
                {"key": latest.key, "rev": 6})  # fmt: skip
    assert out[0] is no_update and out[11] == "-0.15"  # its own numbers, nothing saved
    out = _call(adjust, _mount(-0.15), challenge(snap), store, {"key": frozen.key, "rev": 6})
    assert out[0] is no_update and out[11] == "+0.25"


def test_account_hydration_writes_the_store_only_when_it_changes_it(data, monkeypatch):  # noqa: F811
    app, _, lc = _setup(data)
    store = {**_ctx_store(lc, 0.25), "_rev": 2}
    monkeypatch.setattr(lab_persist, "load", lambda service, lab_, lc_: dict(lab_))
    out = _named(app, "update_detail")(RESEARCH, "1X2", "/lab", [], RESEARCH, store)
    assert out[2] is no_update and out[7] == {"key": lc.key, "rev": 2}  # nothing to write
    changed = lab.store_adjustment(store, lc.key, lc.r,
                                   lab.normalise_state({"context": {"home": 0.5, "away": 0}}))  # fmt: skip
    monkeypatch.setattr(lab_persist, "load", lambda service, lab_, lc_: changed)
    out = _named(app, "update_detail")(RESEARCH, "1X2", "/lab", [], RESEARCH, store)
    assert out[2]["_rev"] == 3 and out[7] == {"key": lc.key, "rev": 3}
    assert json.dumps(out[2]).count('"home": 0.5') >= 1


# ------------------------------------------------- delayed-response browser verification
# The analysis rebuild (update_detail) is delayed by 1.5 s whenever a market or toggle
# change triggers it, reproducing the original ML-01 window deterministically: an
# action taken while the rebuild is in flight. Waits are for the expected state or for
# the specific callback response, never fixed sleeps standing in for them.
DELAYED = r"""
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const out = { errors: [] };
  const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  p.on('pageerror', e => out.errors.push(e.message));
  const detail = () => p.evaluate(() => ((document.querySelector('#detail') || {}).innerText || '').toLowerCase());
  const until = (fn, arg) => p.waitForFunction(fn, arg, { timeout: 20000 });
  const view = () => p.evaluate(() => { const d = ((document.querySelector('#detail') || {}).innerText || '').toLowerCase();
    return { toggle: document.querySelector('#lab-latest input')?.checked,
             ctx: d.includes('model calculated') ? 'latest' : (d.includes('frozen:') ? 'frozen' : '?'),
             market: document.querySelector('#lab-market input:checked')?.value,
             panel: (document.querySelector('#lab-challenge') || {innerText: ''}).innerText.trim().length > 0 }; });
  const openB = async () => { const acc = p.locator('.ctx-acc').first();
    if (!(await acc.evaluate(e => e.open))) await acc.locator('summary').click(); };
  const isMount = (r) => { try { const d = JSON.parse(r.request().postData());
    return d.output.includes('lab-store.data') && d.output.includes('ctx-home.value') && d.changedPropIds.length > 1; } catch (e) { return false; } };
  const portfolio = () => p.evaluate(() => sessionStorage.getItem('ch-session'));

  // A. ML-01: Section B at +0.25; Section B cleared (its adjust delayed), then a market
  //    change while that is in flight - the rebuild is requested with the older store
  await p.goto(BASE + `lab?fixture=${FID}&ctx=research`);
  await until(() => !!document.querySelector('#ctx-home'));
  const before = await portfolio();
  await openB(); await p.locator('#ctx-home').fill('0.25'); await p.locator('#ctx-home').press('Tab');
  await until(() => document.querySelector('#ctx-home').value === '+0.25');
  let mounted = p.waitForResponse(isMount, { timeout: 20000 });
  await p.locator('#ctx-clear').click();
  await p.waitForTimeout(150);  // inside the delayed clear (the action under test)
  await p.locator('#lab-market label', { hasText: 'Both Teams' }).click();
  await mounted;  // the rebuilt inputs mounted and their adjust call was answered
  await until(() => ((document.querySelector('#detail') || {}).innerText || '').toLowerCase().includes('both teams'));
  await openB();
  out.afterRebuild = await p.locator('#ctx-home').inputValue();
  // and it stays cleared when the match is shown again (store, not just the inputs)
  await p.locator('#site-nav-links .nav-link', { hasText: 'Portfolio Build' }).click();
  await p.locator('#site-nav-links .nav-link', { hasText: 'Match Lab' }).click();
  await until(() => !!document.querySelector('#ctx-home')); await openB();
  out.afterReturn = await p.locator('#ctx-home').inputValue();
  // A2. a clear clicked while a rebuild is pending (Dash merges it into the rebuild's call)
  await p.locator('#ctx-home').fill('0.25'); await p.locator('#ctx-home').press('Tab');
  await until(() => document.querySelector('#ctx-home').value === '+0.25');
  mounted = p.waitForResponse(isMount, { timeout: 20000 });
  await p.locator('#lab-market label', { hasText: 'Over/Under' }).click();
  await p.waitForTimeout(150);  // inside the delayed rebuild
  await p.locator('#ctx-clear').click();
  await mounted;
  await until(() => document.querySelector('#ctx-home').value === '0.00');
  await openB(); out.mergedClear = await p.locator('#ctx-home').inputValue();
  // A3. rapid successive changes: three quick presses on Section B's slider
  await p.locator('#ctx-home-slider [role=slider]').focus();
  for (let i = 0; i < 3; i++) await p.keyboard.press('ArrowRight');
  await until(() => document.querySelector('#ctx-home').value === '+0.15');
  out.rapidEdits = await p.locator('#ctx-home').inputValue();

  // B. toggle (delayed response) with a market change sent meanwhile
  const link = BASE + `lab?fixture=${FID}&ctx=challenge&round=${ROUND}`;
  await p.goto(link); await until(() => ((document.querySelector('#detail') || {}).innerText || '').toLowerCase().includes('frozen:'));
  await p.locator('#lab-latest input').click(); await p.waitForTimeout(150);
  await p.locator('#lab-market label', { hasText: 'Over/Under' }).click();
  await until(() => document.querySelector('#lab-latest input')?.checked &&
    ((document.querySelector('#detail') || {}).innerText || '').toLowerCase().includes('model calculated') &&
    document.querySelector('#lab-market input:checked')?.value === 'OU25' &&
    (document.querySelector('#lab-challenge') || {innerText: ''}).innerText.trim() === '');
  out.overlap = await view();
  // C. rapid OFF, ON, OFF: ends frozen with the selection panel back
  for (let i = 0; i < 3; i++) { await p.locator('#lab-latest input').click(); await p.waitForTimeout(100); }
  await until(() => !document.querySelector('#lab-latest input')?.checked &&
    ((document.querySelector('#detail') || {}).innerText || '').toLowerCase().includes('frozen:') &&
    (document.querySelector('#lab-challenge') || {innerText: ''}).innerText.trim().length > 0);
  out.rapid = await view();
  // D. latest, away and back through the tab: the remembered latest view
  await p.locator('#lab-latest input').click();
  await until(() => ((document.querySelector('#detail') || {}).innerText || '').toLowerCase().includes('model calculated'));
  await p.locator('#site-nav-links .nav-link', { hasText: 'Portfolio Build' }).click();
  await p.locator('#site-nav-links .nav-link', { hasText: 'Match Lab' }).click();
  await until(() => document.querySelector('#lab-latest input')?.checked &&
    ((document.querySelector('#detail') || {}).innerText || '').toLowerCase().includes('model calculated'));
  out.tab = await view();
  // E. opening the challenge match again: frozen, toggle off
  await p.goto(link);
  await until(() => !document.querySelector('#lab-latest input')?.checked &&
    ((document.querySelector('#detail') || {}).innerText || '').toLowerCase().includes('frozen:'));
  out.reopen = await view();
  // F. picks and draft untouched by all of the above
  out.portfolioKept = (await portfolio()) === before;
  console.log(JSON.stringify(out)); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def test_browser_delayed_rebuilds_and_switches(data, monkeypatch):  # noqa: F811
    import shutil
    import subprocess
    import threading
    import time

    if (
        shutil.which("node") is None
        or subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode
    ):
        pytest.skip("node with playwright not available")
    from werkzeug.serving import make_server

    from diski9.app import app as appmod

    from .test_app import _free_port

    real, real_update = appmod.lab_want, appmod.lab_update

    def delayed(request, target, latest, trigger):  # the rebuild after a market/toggle change
        triggers = {trigger} if isinstance(trigger, str) else set(trigger or ())
        if triggers & {"lab-market", "lab-latest"}:
            time.sleep(1.5)
        return real(request, target, latest, trigger)

    def delayed_clear(r, trig, value, state):  # a Section B clear, still in flight
        if trig == "ctx-clear":
            time.sleep(1.5)
        return real_update(r, trig, value, state)

    monkeypatch.setattr(appmod, "lab_want", delayed)
    monkeypatch.setattr(appmod, "lab_update", delayed_clear)
    _, snap = _live(data)
    port = _free_port()
    server = make_server("127.0.0.1", port, _app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    head = (f"const BASE = 'http://127.0.0.1:{port}/'; const FID = {EPL_FIX}; "
            f"const ROUND = {json.dumps(snap.round_id)};\n")  # fmt: skip
    try:
        res = subprocess.run(["node", "-e", head + DELAYED], capture_output=True, text=True,
                             timeout=300)  # fmt: skip
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()
    assert out["errors"] == []
    assert out["afterRebuild"] == "0.00" and out["afterReturn"] == "0.00", out  # ML-01
    assert out["mergedClear"] == "0.00", out  # a click during a pending rebuild is kept
    assert out["rapidEdits"] == "+0.15", out  # rapid edits all applied
    assert out["overlap"] == {"toggle": True, "ctx": "latest", "market": "OU25", "panel": False}
    assert out["rapid"]["ctx"] == "frozen" and not out["rapid"]["toggle"] and out["rapid"]["panel"]
    assert out["tab"]["toggle"] and out["tab"]["ctx"] == "latest"
    assert out["reopen"]["ctx"] == "frozen" and not out["reopen"]["toggle"]
    assert out["portfolioKept"]
