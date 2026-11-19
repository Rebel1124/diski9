"""Phase 6C.2 (T-15): browser-tab prototype state at authentication transitions.

Runs the real ``assets/account.js`` in Chromium on minimal pages that carry the
same owner marker as the Dash shell:

* a guest who signs in with work in the tab is offered an explicit choice; keeping
  leaves the work in the tab (not on the account, nothing submitted); discarding
  clears it; refreshing before choosing asks again;
* a guest with no work in the tab is not asked;
* a different account signing in in the same tab never sees the previous account's
  state; sign-out pages clear everything.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from flask import Flask, request

from .test_app import _free_port

ASSET = Path(__file__).resolve().parents[1] / "src" / "diski9" / "app" / "assets" / "account.js"


def _app() -> Flask:
    app = Flask(__name__)

    @app.get("/account.js")
    def js():
        return ASSET.read_text(), 200, {"Content-Type": "text/javascript"}

    @app.get("/page")
    def page():
        owner = request.args.get("owner", "guest")
        clear = ' data-clear-state="1"' if request.args.get("signout") else ""
        marker = "" if clear else f'<span id="d9-owner" data-owner="{owner}" hidden></span>'
        return (
            f"<!doctype html><html><body{clear}>{marker}<p>page</p>"
            '<script src="/account.js"></script></body></html>'
        )

    return app


SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const base = 'http://127.0.0.1:%(port)d/page';
  const browser = await chromium.launch();
  const out = {};
  const errors = [];
  async function tab() {
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    p.on('pageerror', e => errors.push(String(e)));
    return p;
  }
  const draft = JSON.stringify({ picks: { "1": "HOME" } });
  const state = p => p.evaluate(() => ({
    ch: sessionStorage.getItem('ch-session'), lab: sessionStorage.getItem('lab-store'),
    owner: sessionStorage.getItem('d9-owner') }));
  const dialog = async p => { await p.waitForTimeout(400); return await p.locator('#d9-guest-choice').count(); };

  // 1. guest with work signs in, chooses Keep
  let p = await tab();
  await p.goto(base + '?owner=guest');
  await p.evaluate(d => sessionStorage.setItem('ch-session', d), draft);
  await p.goto(base + '?owner=acctA');
  out.keepAsked = await dialog(p);
  out.keepText = await p.locator('#d9-guest-choice').innerText();
  await p.reload();
  out.keepAskedAgainAfterRefresh = await dialog(p);
  await p.click('#d9-guest-keep');
  out.keepAfter = await state(p);
  out.keepDialogGone = await p.locator('#d9-guest-choice').count();
  await p.reload();
  out.keepAskedAfterChoice = await dialog(p);

  // 2. guest with work signs in, chooses Discard
  p = await tab();
  await p.goto(base + '?owner=guest');
  await p.evaluate(d => { sessionStorage.setItem('ch-session', d);
                          sessionStorage.setItem('lab-store', JSON.stringify({ "7": { home: 0.2 } })); }, draft);
  await p.goto(base + '?owner=acctA');
  out.discardAsked = await dialog(p);
  await Promise.all([p.waitForNavigation(), p.click('#d9-guest-discard')]);
  out.discardAfter = await state(p);
  out.discardAskedAfter = await dialog(p);

  // 3. guest without work: no question
  p = await tab();
  await p.goto(base + '?owner=guest');
  await p.evaluate(() => { sessionStorage.setItem('ch-session', 'null');
                           sessionStorage.setItem('lab-store', '{}'); });
  await p.goto(base + '?owner=acctA');
  out.emptyAsked = await dialog(p);
  out.emptyOwner = (await state(p)).owner;

  // 4. account A then account B in the same tab: A's state is removed
  p = await tab();
  await p.goto(base + '?owner=acctA');
  await p.waitForTimeout(300);
  await p.evaluate(d => sessionStorage.setItem('ch-session', d), draft);
  await p.goto(base + '?owner=acctB');
  await p.waitForTimeout(800);
  out.switchAfter = await state(p);
  out.switchAsked = await dialog(p);

  // 5. sign-out page clears everything
  p = await tab();
  await p.goto(base + '?owner=acctA');
  await p.evaluate(d => sessionStorage.setItem('ch-session', d), draft);
  await p.goto(base + '?signout=1');
  await p.waitForTimeout(300);
  out.signoutAfter = await state(p);

  out.errors = errors;
  await browser.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_tab_state_at_sign_in_switch_and_sign_out():
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    port = _free_port()
    server = make_server("127.0.0.1", port, _app(), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        time.sleep(0.2)
        res = subprocess.run(
            ["node", "-e", SCRIPT % {"port": port}], capture_output=True, text=True, timeout=180
        )
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()
    draft = json.dumps({"picks": {"1": "HOME"}}, separators=(",", ":"))
    assert out["errors"] == []
    # 1. keep: asked (again after a refresh), work stays in the tab, then not asked
    assert out["keepAsked"] == 1 and out["keepAskedAgainAfterRefresh"] == 1
    assert "not saved to your account" in out["keepText"]
    assert "nothing is submitted" in out["keepText"]
    assert out["keepAfter"]["ch"] == draft and out["keepAfter"]["owner"] == "acctA"
    assert out["keepDialogGone"] == 0 and out["keepAskedAfterChoice"] == 0
    # 2. discard: asked, then all prototype state removed
    assert out["discardAsked"] == 1
    assert out["discardAfter"] == {"ch": None, "lab": None, "owner": "acctA"}
    assert out["discardAskedAfter"] == 0
    # 3. nothing to keep: not asked
    assert out["emptyAsked"] == 0 and out["emptyOwner"] == "acctA"
    # 4. another account: previous account's state removed, no choice offered
    assert out["switchAfter"]["ch"] is None and out["switchAfter"]["owner"] == "acctB"
    assert out["switchAsked"] == 0
    # 5. sign-out clears
    assert out["signoutAfter"] == {"ch": None, "lab": None, "owner": None}
