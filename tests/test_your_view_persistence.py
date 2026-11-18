"""Phase 6B.3: Your View (Match Lab adjustments) in browser session storage.

* survives navigation, a refresh and a server restart in the same tab;
* each fixture's adjustments are stamped with their model context (Goal Model
  version and rounded baseline estimated goals) and never reapplied to a
  different baseline;
* reset removes them; a confirmed portfolio never changes when Your View does.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time

import pytest

from diski9.app import lab
from diski9.app.app import lab_update
from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import integration

from .test_app import EPL_FIX, _free_port, data, populated  # noqa: F401  (fixtures)
from .test_challenge_ui import (  # noqa: F401
    _DataWithResults,
    _lab_state,
    snap,  # noqa: F401
    svc,
    valid_keys,
)


def _result(data, fid=EPL_FIX):  # noqa: F811
    return data.detail(fid)[0]


def test_layout_uses_session_storage_for_your_view(data):  # noqa: F811
    from diski9.app import create_app

    layout = create_app(data).server.test_client().get("/_dash-layout").get_data(as_text=True)
    compact = layout.replace(" ", "")
    i = compact.index('"id":"lab-store"')
    assert '"storage_type":"session"' in compact[i - 200 : i + 200]


def test_adjustments_are_stamped_and_ignored_on_another_baseline(data):  # noqa: F811
    r = _result(data)
    state, _ = lab_update(r, "lab-home-input", 2.9, None)
    store = lab.store_adjustment({}, EPL_FIX, r, state)
    assert store[str(EPL_FIX)] == state
    assert store[lab.CONTEXT_KEY][str(EPL_FIX)] == lab.model_context(r)
    assert lab.stored_adjustment(store, EPL_FIX, r) == state
    # the model was recalculated: a different baseline means the deltas are stale
    moved = json.loads(json.dumps(r))
    moved["goal_model"]["estimated_goals"]["home"] += 0.4
    assert lab.stored_adjustment(store, EPL_FIX, moved) is None
    # another fixture never sees this fixture's adjustments
    assert lab.stored_adjustment(store, EPL_FIX + 1, r) is None


def test_reset_removes_adjustment_and_stamp(data):  # noqa: F811
    r = _result(data)
    state, _ = lab_update(r, "lab-home-input", 2.9, None)
    store = lab.store_adjustment({}, EPL_FIX, r, state)
    cleared = lab.store_adjustment(store, EPL_FIX, r, None)
    assert cleared == {}  # back to the original Diski 9 estimates


def test_personal_probabilities_skip_stale_context(svc, snap):  # noqa: F811
    fake = _DataWithResults(snap)
    fid = snap.fixtures[0].fixture_id
    store = {str(fid): _lab_state(0.6)}
    assert integration.personal_probabilities(fake, snap, store)  # legacy entry: applied
    store[lab.CONTEXT_KEY] = {str(fid): "1.0|other|9.99|9.99"}
    assert integration.personal_probabilities(fake, snap, store) == {}


def test_confirmed_portfolio_is_immutable_when_your_view_changes(svc, snap):  # noqa: F811
    fake = _DataWithResults(snap)
    keys = valid_keys(snap)
    fid = int(keys[0].split("|")[0])
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    for k in keys:
        s, _ = cb.apply_action(svc, s, "pick", k)
    first = integration.personal_probabilities(fake, snap, {str(fid): _lab_state(0.5)})
    s, _ = cb.apply_action(svc, s, "submit", None, first)
    frozen = json.loads(json.dumps(s["submitted"]))
    later = integration.personal_probabilities(fake, snap, {str(fid): _lab_state(-0.5)})
    assert later != first
    for action in ("close_modal", "clear", "dismiss_notes"):
        s2, _ = cb.apply_action(svc, s, action, None, later)
        assert s2["submitted"] == frozen  # never recalculated with the new view
    # a replacement captures the view current at that time
    s3, _ = cb.apply_action(svc, s, "remove", keys[0])
    s3, _ = cb.apply_action(svc, s3, "pick", keys[0])
    s3["submitted"] = dict(s3["submitted"], selections=[])  # force a "different" draft
    s4, _ = cb.apply_action(svc, s3, "submit", None, later)
    pick = next(p for p in s4["submitted"]["picks"] if p["key"] == keys[0])
    assert pick["personal"] == later[tuple(next(o.key for o in snap.outcomes
                                                if "|".join(map(str, o.key)) == keys[0]))]  # fmt: skip


PERSIST_SCRIPT = """
const { chromium } = require('playwright');
const A = 'http://127.0.0.1:%(a)d', B = 'http://127.0.0.1:%(b)d', FID = %(fid)d;
const row = `[id='${JSON.stringify({ index: FID, type: 'row' })}']`;
(async () => {
  const b = await chromium.launch(); const out = { errors: [] };
  const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  p.on('pageerror', e => out.errors.push(e.message));
  p.on('console', m => { if (m.type() === 'error') out.errors.push(m.text()); });
  const idle = async () => { await p.waitForTimeout(400); await p.waitForLoadState('networkidle'); };
  const open = async (base) => { await p.waitForSelector(row); await p.locator(row).click();
    await p.waitForSelector('#lab-home-input'); await idle(); };
  await p.goto(A + '/'); await open(A);
  out.base = await p.locator('#lab-home-input').inputValue();
  await p.locator('#lab-home-input').fill('3.10'); await p.locator('#lab-home-input').press('Enter'); await idle();
  // navigation away and back
  await p.locator('.nav-link', { hasText: 'Weekly Challenge' }).click(); await idle();
  await p.locator('.nav-link', { hasText: 'Match Lab' }).click(); await open(A);
  out.afterNav = await p.locator('#lab-home-input').inputValue();
  // refresh
  await p.reload(); await open(A);
  out.afterRefresh = await p.locator('#lab-home-input').inputValue();
  out.pill = (await p.locator('.detail-header').innerText()).includes('Adjusted by you');
  // server restart: same tab, new server (sessionStorage carried across origins)
  const saved = await p.evaluate(() => JSON.stringify(Object.assign({}, sessionStorage)));
  await p.goto(B + '/leaderboards');
  await p.evaluate((s) => { for (const [k, v] of Object.entries(JSON.parse(s))) sessionStorage.setItem(k, v); }, saved);
  await p.goto(B + '/'); await open(B);
  out.afterRestart = await p.locator('#lab-home-input').inputValue();
  // reset to the Diski 9 estimates, then refresh
  await p.locator('#lab-reset').click(); await idle();
  await p.reload(); await open(B);
  out.afterReset = await p.locator('#lab-home-input').inputValue();
  console.log(JSON.stringify(out)); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def _serve(app):
    from werkzeug.serving import make_server

    port = _free_port()
    server = make_server("127.0.0.1", port, app.server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port, server


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_your_view_survives_navigation_refresh_and_restart(data):  # noqa: F811
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from diski9.app import create_app

    (a, sa), (b, sb) = _serve(create_app(data)), _serve(create_app(data))
    try:
        time.sleep(0.3)
        script = PERSIST_SCRIPT % {"a": a, "b": b, "fid": EPL_FIX}
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=240)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out["errors"] == []
        assert out["base"] != "3.10"
        assert out["afterNav"] == out["afterRefresh"] == out["afterRestart"] == "3.10"
        assert out["pill"] and out["afterReset"] == out["base"]
    finally:
        sa.shutdown()
        sb.shutdown()
