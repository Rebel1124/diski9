"""Phase 6B.2: participant-state reliability (the submission-restoration bug).

Reported: submit, restart the app server, reload - the app says nothing is
confirmed; select a match and market - the old portfolio reappears.

Root cause (reproduced in a browser): the live round snapshot is pinned in server
memory and its fingerprint includes its build time, so a restarted server builds a
new fingerprint for the same round. Phase 6B.1 page renders treated a draft with a
different fingerprint as empty and matched the submission by fingerprint, while
the reducer migrated the draft lazily on the next unrelated action - so the next
click "resurrected" the portfolio (and was itself discarded).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from datetime import timedelta

import pytest

from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import pages
from diski9.app.challenge import state as st
from diski9.app.challenge.service import ChallengeService
from diski9.challenge.roundsheet import SnapshotKind

from .test_app import _free_port, data, populated  # noqa: F401  (fixtures)
from .test_challenge_ui import NOW, _Data, jtext, valid_keys


class LiveService(ChallengeService):
    """A playable live round whose snapshot is rebuilt (new fingerprint, same odds)
    whenever ``generation`` changes - exactly what a server restart does."""

    generation = 0

    def __init__(self, source=None):
        super().__init__(source or _Data())

    def now(self):
        return NOW

    def live(self):
        base = self.demo()
        return replace(
            base,
            kind=SnapshotKind.LIVE,
            round_id="2026-W47",
            snapshot_at=base.snapshot_at + timedelta(minutes=self.generation),
        )


def submitted_live(svc):
    keys = valid_keys(svc.live())
    s = None
    for k in keys:
        s, _ = cb.apply_action(svc, s, "pick", k)
    s, _ = cb.apply_action(svc, s, "submit")
    s, _ = cb.apply_action(svc, s, "close_modal")
    return s, keys


@pytest.fixture
def svc():
    LiveService.generation = 0
    yield LiveService()
    LiveService.generation = 0


def test_restart_shows_the_confirmed_portfolio_immediately(svc):
    s, keys = submitted_live(svc)
    assert s["submitted"]["mode"] == "live" and s["mode"] is None
    LiveService.generation = 1  # "server restart": same round, new fingerprint
    assert svc.live().fingerprint != s["fp"]
    _, snap, avail, sels = pages.current(svc, s)
    assert sels == keys  # the draft is shown, not an empty one
    label, _, _ = pages.round_state(pages.sync(svc, s), snap, avail, sels)
    assert label == "Confirmed"
    assert "Not started" not in jtext(pages.my_challenge(svc, s, _Data().local))


def test_next_action_neither_resurrects_nor_swallows_the_click(svc):
    s, keys = submitted_live(svc)
    LiveService.generation = 1
    shown = pages.current(svc, s)[3]
    s2, flash = cb.apply_action(svc, s, "remove", keys[0])
    assert s2["selections"] == [k for k in shown if k != keys[0]]  # the click was applied
    assert flash is None  # nothing changed, nothing to review
    assert s2["submitted"] == s["submitted"]  # a draft edit never touches the submission


def test_read_and_write_paths_agree(svc):
    s, keys = submitted_live(svc)
    LiveService.generation = 2
    assert pages.current(svc, s)[3] == cb.apply_action(svc, s, "close_modal")[0]["selections"]
    assert st.reconcile(svc, st.reconcile(svc, s)) == st.reconcile(svc, s)  # idempotent


def test_store_sync_never_writes_an_unhydrated_value(svc):
    from dash import no_update

    assert cb.store_sync(svc, None) is no_update
    assert cb.store_sync(svc, {}) is no_update
    s, _ = submitted_live(svc)
    assert cb.store_sync(svc, s) is no_update  # already reconciled: nothing to write
    LiveService.generation = 1
    new = cb.store_sync(svc, s)
    assert new["fp"] == svc.live().fingerprint and new["submitted"] == s["submitted"]


def test_demo_and_live_are_isolated(svc):
    s, keys = submitted_live(svc)
    live_sub = s["submitted"]
    s, _ = cb.apply_action(svc, s, "mode", "demo")
    assert s["submitted"] is None and s["selections"] == []
    assert s["parked"]["live"]["submitted"] == live_sub
    demo_keys = valid_keys(svc.demo())
    for k in demo_keys[:3]:
        s, _ = cb.apply_action(svc, s, "pick", k)
    s, _ = cb.apply_action(svc, s, "mode", "live")
    assert s["submitted"] == live_sub and s["selections"] == keys
    s, _ = cb.apply_action(svc, s, "mode", "demo")
    assert s["selections"] == demo_keys[:3] and s["submitted"] is None


def test_a_legacy_submission_from_the_other_mode_is_parked(svc):
    s, _ = submitted_live(svc)
    legacy = {"mode": "demo", "fp": svc.demo().fingerprint, "submitted": s["submitted"]}
    r = st.reconcile(svc, legacy)
    assert r["submitted"] is None and r["parked"]["live"]["submitted"] == s["submitted"]


def test_an_earlier_round_is_closed_not_shown_as_current(svc):
    s, _ = submitted_live(svc)
    old = dict(s["submitted"], round_id="2026-W46")
    r = st.reconcile(svc, dict(s, submitted=old, round_id="2026-W46", fp="old"))
    assert r["submitted"] is None and r["earlier"] == old and r["selections"] == []


def test_invalid_replacement_keeps_the_confirmed_portfolio(svc):
    s, keys = submitted_live(svc)
    LiveService.generation = 1
    s2, _ = cb.apply_action(svc, s, "remove", keys[0])
    s3, flash = cb.apply_action(svc, s2, "submit")
    assert "not valid" in flash["text"] and s3["submitted"] == s["submitted"]


# ------------------------------------------------------------------- withdrawal
def test_withdrawal_needs_confirmation_and_cancel_changes_nothing(svc):
    s, keys = submitted_live(svc)
    asked, flash = cb.apply_action(svc, s, "ask_withdraw")
    assert asked["confirm"] == "withdraw" and asked["submitted"] == s["submitted"]
    assert flash is None
    kept, _ = cb.apply_action(svc, asked, "cancel_withdraw")
    assert kept["confirm"] is None and kept["submitted"] == s["submitted"]
    assert kept["selections"] == keys


def test_withdrawal_clears_entry_and_draft_and_never_resurrects(svc):
    s, keys = submitted_live(svc)
    s, _ = cb.apply_action(svc, s, "ask_withdraw")
    s, flash = cb.apply_action(svc, s, "withdraw")
    assert flash["kind"] == "ok" and "withdrawn" in flash["text"]
    assert s["submitted"] is None and s["selections"] == [] and s["stage"] == "build"
    assert s["withdrawn"]["round_id"] == "2026-W47"
    LiveService.generation = 3  # a later restart / snapshot rebuild
    r = st.reconcile(svc, s)
    assert r["submitted"] is None and r["selections"] == []
    s2, _ = cb.apply_action(svc, s, "pick", keys[0])  # starting fresh
    assert s2["selections"] == [keys[0]] and s2["submitted"] is None
    label, _, _ = pages.round_state(s2, svc.live(), svc.availability("live"), s2["selections"])
    assert label == "Withdrawn"
    for k in keys[1:]:
        s2, _ = cb.apply_action(svc, s2, "pick", k)
    s3, _ = cb.apply_action(svc, s2, "submit")
    assert s3["submitted"] is not None and s3["withdrawn"] is None


def test_withdrawal_is_refused_after_the_deadline(svc):
    from diski9.challenge.roundsheet import assess_round

    s, _ = submitted_live(svc)

    class Locked(LiveService):
        def availability(self, mode):
            return assess_round(self.live(), self.live().deadline + timedelta(minutes=1))

    locked = Locked()
    s2, flash = cb.apply_action(locked, s, "ask_withdraw")
    assert "deadline has passed" in flash["text"] and s2["submitted"] == s["submitted"]
    s3, flash = cb.apply_action(locked, dict(s, confirm="withdraw"), "withdraw")
    assert s3["submitted"] == s["submitted"] and "no longer be withdrawn" in flash["text"]


def test_clear_draft_and_replace_never_touch_or_remove_the_submission(svc):
    s, keys = submitted_live(svc)
    cleared, _ = cb.apply_action(svc, s, "clear")
    assert cleared["selections"] == [] and cleared["submitted"] == s["submitted"]
    s_no, flash = cb.apply_action(svc, {"mode": None}, "ask_withdraw")
    assert "no confirmed submission" in flash["text"]


def test_withdraw_controls_on_review_and_my_challenge(svc):
    s, _ = submitted_live(svc)
    me = jtext(pages.my_challenge(svc, s, _Data().local))
    assert '"t": "askwithdraw"' in me and "Show my nine predictions" in me
    assert "browser tab" in me  # prototype, non-authoritative
    asked, _ = cb.apply_action(svc, s, "ask_withdraw")
    me = jtext(pages.my_challenge(svc, asked, _Data().local))
    assert "Withdraw your submission?" in me and '"t": "confirmwithdraw"' in me
    assert '"t": "cancelwithdraw"' in me


# ------------------------------------------------------------------- browser
SERVER_RESTART_SCRIPT = """
const { chromium } = require('playwright');
const KEYS = %(keys)s, A = 'http://127.0.0.1:%(a)d', B = 'http://127.0.0.1:%(b)d';
const sel = (o) => `[id='${JSON.stringify(o)}']`;
(async () => {
  const b = await chromium.launch(); const out = { errors: [] };
  const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  p.on('pageerror', e => out.errors.push(e.message));
  p.on('console', m => { if (m.type() === 'error') out.errors.push(m.text()); });
  const idle = async () => { await p.waitForTimeout(400); await p.waitForLoadState('networkidle'); };
  const txt = async (css) => (await p.locator(css).first().innerText()).replace(/\\s+/g, ' ');
  // server A: build and confirm a live portfolio
  await p.goto(A + '/challenge'); await p.waitForSelector(sel({ k: KEYS[0], t: 'pick' }));
  for (const k of KEYS) { await p.locator(sel({ k, t: 'pick' })).click(); await idle(); }
  await p.waitForFunction(() => (document.querySelector('.ch-total') || {}).innerText === '9/9');
  await p.locator(sel({ i: 'tracker', t: 'nav', to: 'review' })).click(); await idle();
  await p.locator(sel({ i: 0, t: 'submit' })).click(); await p.waitForSelector('.ch-modal');
  await p.locator(sel({ i: 0, t: 'modalclose' })).click(); await idle();
  const stored = await p.evaluate(() => sessionStorage.getItem('ch-session'));
  // "restart": the same tab is pointed at server B (new snapshot fingerprint, same
  // round); sessionStorage is per origin, so it is carried across explicitly
  await p.goto(B + '/leaderboards'); await p.evaluate((s) => sessionStorage.setItem('ch-session', s), stored);
  await p.goto(B + '/challenge/me'); await p.waitForSelector('.ch-page'); await idle();
  out.me = (await txt('.ch-pill'));
  out.meConfirmedCard = (await p.locator('#ch-root').innerText()).includes('Show my nine predictions');
  await p.goto(B + '/challenge'); await p.waitForSelector('.ch-page'); await idle();
  out.reviewConfirmed = (await txt(sel({ i: 0, t: 'submit' }))).includes('Confirmed');
  await p.locator(sel({ i: 'stepper', t: 'nav', to: 'build' })).click(); await p.waitForSelector('.ch-total'); await idle();
  out.builder = await txt('.ch-total');
  await p.locator('.nav-link', { hasText: 'Screener' }).click(); await idle();
  out.strip = (await txt('#ch-strip')).includes('9/9');
  out.fpRewritten = JSON.parse(await p.evaluate(() => sessionStorage.getItem('ch-session'))).fp !== JSON.parse(stored).fp;
  // a later interaction changes only what was clicked
  await p.locator('.nav-link', { hasText: 'Weekly Challenge' }).click(); await p.waitForSelector('.ch-total'); await idle();
  await p.locator(sel({ k: KEYS[0], t: 'pick' })).click(); await idle();
  out.afterClick = await txt('.ch-total');
  await p.reload(); await p.waitForSelector('.ch-total'); await idle();
  out.afterReload = await txt('.ch-total');
  await p.goto(B + '/challenge/me'); await p.waitForSelector('.ch-pill'); await idle();
  out.meAfter = await txt('.ch-pill');
  // withdrawal: cancel leaves everything; confirm removes the entry for good
  await p.locator(sel({ i: 'me', t: 'askwithdraw' })).click(); await p.waitForSelector('.ch-modal'); await idle();
  await p.locator(sel({ i: 0, t: 'cancelwithdraw' })).click(); await idle();
  out.afterCancel = await txt('.ch-pill');
  await p.locator(sel({ i: 'me', t: 'askwithdraw' })).click(); await p.waitForSelector('.ch-modal'); await idle();
  await p.locator(sel({ i: 0, t: 'confirmwithdraw' })).click(); await idle();
  out.afterWithdraw = await txt('.ch-pill');
  await p.reload(); await p.waitForSelector('.ch-pill'); await idle();
  out.withdrawnAfterReload = await txt('.ch-pill');
  out.noSubmission = !(await p.locator('#ch-root').innerText()).includes('Show my nine predictions');
  await p.goto(B + '/challenge'); await p.waitForSelector(sel({ k: KEYS[3], t: 'pick' })); await idle();
  await p.locator(sel({ k: KEYS[3], t: 'pick' })).click(); await idle();
  out.freshDraft = await txt('.ch-total');
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
def test_browser_server_restart_restores_and_never_resurrects(data, monkeypatch):  # noqa: F811
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from diski9.app import app as app_module

    class Gen0(LiveService):
        generation = 0

    class Gen1(LiveService):
        generation = 1

    monkeypatch.setattr(app_module, "ChallengeService", Gen0)
    app_a = app_module.create_app(data)
    monkeypatch.setattr(app_module, "ChallengeService", Gen1)
    app_b = app_module.create_app(data)
    keys = valid_keys(Gen0().live(), {f.fixture_id for f in Gen0().live().fixtures[:10]})
    (a, sa), (b, sb) = _serve(app_a), _serve(app_b)
    try:
        time.sleep(0.3)
        script = SERVER_RESTART_SCRIPT % {"keys": json.dumps(keys), "a": a, "b": b}
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=240)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out["errors"] == []
        assert out["me"] == "CONFIRMED" and out["meConfirmedCard"]
        assert (
            out["reviewConfirmed"]
            and out["builder"] == "9/9"
            and out["strip"]
            and out["fpRewritten"]
        )
        assert out["afterClick"] == "8/9" and out["afterReload"] == "8/9"
        assert out["meAfter"] == "CONFIRMED"  # the submission is untouched by a draft edit
        assert out["afterCancel"] == "CONFIRMED"
        assert out["afterWithdraw"] == "WITHDRAWN" and out["withdrawnAfterReload"] == "WITHDRAWN"
        assert out["noSubmission"] and out["freshDraft"] == "1/9"  # nothing resurrected
    finally:
        sa.shutdown()
        sb.shutdown()
