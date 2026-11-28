"""Phase 8 CP3A-5: final integration and acceptance of CP3A, in a real browser, on real
PostgreSQL and a real (local) Supabase Auth server.

The whole application runs as one server: the competition database (a published
development round, drafts, entries and saved Your View), real sign-in through Supabase
Auth, and controlled football data (an analysis store built relative to now, so the
research list and the latest-data context have fresh prices). The development round's
matches take their latest-data analysis from that store (a controlled mapping; the
frozen analysis always comes from the published snapshot).

Journeys (proportionate, not every state at every width):

1. guest, at 390, 768 and 1280 px: navigation, homepage card, Research only switching
   and its tooltip, the competitive list (filters, Minimum Market Probability, Match
   Lab links), frozen/latest analysis, the research list, My Challenge, Training
   Ground and Leaderboard; no horizontal overflow and no browser errors;
2. guest to account (1280 px): picks and a frozen Your View made as a guest, sign-in
   with real Supabase Auth, the keep choice and adoption;
3. signed in (1280 px): separate frozen and latest Your View, market change, return to
   Portfolio Build with filters and page kept, a Match Lab selection, a complete
   portfolio, review and probability analysis, submission, My Challenge and
   withdrawal; latest-data analysis never changes the portfolio;
4. another device (390 and 768 px): both saved Your View contexts of the same match and
   the confirmed entry restored from the account; then the entry is withdrawn;
5. after the entry deadline: the locked round is read-only (builder and Match Lab), and
   with no challenge available research stays open with the Research only default.

Screenshots are written only when ``DISKI9_SHOTS`` names a directory.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from svc_helpers import principal, publish_dev, valid_keys, wait_until
from test_app_persistence import PinnedBackend

from diski9.backend.services import rounds as rsvc

ROOT = Path(__file__).resolve().parents[2]
AUTH_URL = os.environ.get("DISKI9_TEST_SUPABASE_AUTH_URL")
ANON = os.environ.get("DISKI9_TEST_SUPABASE_ANON_KEY")
MAIL_DIR = os.environ.get("DISKI9_TEST_SUPABASE_MAIL_DIR")


def _browser_ready() -> bool:
    return shutil.which("node") is not None and (
        subprocess.run(
            ["node", "-e", "require('playwright')"], capture_output=True, cwd=ROOT
        ).returncode
        == 0  # fmt: skip
    )


pytestmark = [
    pytest.mark.skipif(
        not (AUTH_URL and ANON and MAIL_DIR),
        reason="needs a real Supabase Auth server (see docs/authentication.md, local testing)",
    ),
    pytest.mark.skipif(not _browser_ready(), reason="node with playwright not available"),
]

EPL_FIX, PSL_FIX = 9001, 9002
EXTRA = list(range(9100, 9112))
DAY = timedelta(days=1)


# ------------------------------------------------------------------ controlled football data
def _football(tmp_path, base: datetime):
    """An analysis store like the application tests' one, built relative to ``base``
    (now): teams with history (independent model), upcoming fixtures, and fresh odds
    on some of them (Minimum Market Probability, market-implied starting points)."""
    from diski9.db import make_engine, upgrade
    from diski9.ingestion.fixtures import store_fixtures
    from diski9.odds.collect import OddsPage, reconcile_pages
    from diski9.screener import cache
    from tests.factories import fixture_item, full_book, odds_item, seed_competition

    url = f"sqlite:///{tmp_path / 'football.sqlite'}"
    upgrade(url)
    eng = make_engine(url)
    with eng.begin() as conn:
        seed_competition(conn, 39, years=(2025, 2026))
        seed_competition(conn, 288, years=(2025, 2026), name="Premier Soccer League")
        items, fid, t = [], 1, base - 200 * DAY

        def add(h, a, hg, ag, league=39, season=2026):
            nonlocal fid, t
            t += DAY
            items.append(fixture_item(fid, h, a, league=league, season=season, kickoff=t,
                                      ft=(hg, ag)))  # fmt: skip
            fid += 1

        for i in range(10):
            add(1, 100 + i, 3, 0)
            add(110 + i, 2, 1, 1)
            add(10, 200 + i, 1, 1, league=288)
            add(210 + i, 11, 0, 2, league=288)
        for i in range(20):
            add(600 + i % 10, 650 + i % 10, (2, 1, 0, 3)[i % 4], (1, 1, 2, 0)[i % 4], season=2025)
        upcoming = [(EPL_FIX, 1, 2, 39, base + 1 * DAY), (PSL_FIX, 10, 11, 288, base + 2 * DAY)]
        upcoming += [(e, 400 + i, 500 + i, 39, base + 2 * DAY + i * timedelta(hours=2))
                     for i, e in enumerate(EXTRA)]  # fmt: skip
        items += [fixture_item(f, h, a, league=lg, season=2026, kickoff=k, status="NS")
                  for f, h, a, lg, k in upcoming]  # fmt: skip
        store_fixtures(conn, items, lambda: base)
        # fresh prices: a clear favourite, and gradually less likely home sides
        priced = [(EPL_FIX, "1.40", base + DAY)]
        priced += [(e, h, base + 2 * DAY + i * timedelta(hours=2))
                   for i, (e, h) in enumerate(zip(EXTRA[:6], ("1.60", "1.90", "2.20", "2.60",
                                                             "3.10", "3.80"), strict=True))]  # fmt: skip
        page = OddsPage(base - timedelta(hours=1), [
            odds_item(f, {b: full_book(home=h) for b in (8, 11, 4)}, kickoff=k,
                      update=(base - timedelta(hours=1)).isoformat())
            for f, h, k in priced])  # fmt: skip
        reconcile_pages(conn, 39, 2026, [page], clock=lambda: base - timedelta(hours=1))
        cache.refresh(conn, [f for f, *_ in upcoming], base, base)
    return eng


class Data:
    """The application's analysis data, with each development-round match analysed as
    one of the controlled fixtures (latest data); names follow the snapshot."""

    def __init__(self, inner, snap):
        self._inner = inner
        templates = (EPL_FIX, EXTRA[0], EXTRA[11])  # model / market fit / no prices
        self._map = {f.fixture_id: (templates[i % 3], f) for i, f in enumerate(snap.fixtures)}

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def add(self, snap):
        templates = (EPL_FIX, EXTRA[0], EXTRA[11])
        self._map.update({f.fixture_id: (templates[i % 3], f) for i, f in enumerate(snap.fixtures)})

    def detail(self, fixture_id, basis="overall"):
        hit = self._map.get(int(fixture_id)) if fixture_id else None
        if hit is None:
            return self._inner.detail(fixture_id, basis)
        template, fx = hit
        r, ov, st = self._inner.detail(template, basis)
        if r is None:
            return r, ov, st
        r = copy.deepcopy(r)
        r["fixture"]["id"] = fx.fixture_id
        r["teams"]["home"]["name"], r["teams"]["away"]["name"] = fx.home, fx.away
        return r, ov, st


class SwitchableBackend(PinnedBackend):
    """The real backend pinned to one round; ``round_id = None`` means no published
    round (the unavailable week)."""

    def published(self):
        if self.round_id is None:
            return None  # as the real backend reports no current round
        return super().published()


# ------------------------------------------------------------------ accounts
def _confirmed(provider, password):
    import time
    import uuid

    addr = f"cp3a5-{uuid.uuid4().hex[:10]}@example.com"
    before = {p.name for p in Path(MAIL_DIR).glob("*.eml")}
    provider.sign_up(addr, password)
    for _ in range(100):
        new = [p for p in Path(MAIL_DIR).glob("*.eml") if p.name not in before]
        for p in new:
            text = p.read_text(errors="replace").replace("=\n", "").replace("=3D", "=")
            if addr in text and "token_hash=" in text:
                th = text.split("token_hash=", 1)[1].split("&", 1)[0].split('"', 1)[0]
                provider.verify_email_link(th.strip(), "email")
                return addr
        time.sleep(0.1)
    raise AssertionError("no confirmation email")


# ------------------------------------------------------------------ the server
@pytest.fixture
def stack(engine, tmp_path, monkeypatch):
    import uuid

    from auth_helpers import make_settings
    from werkzeug.serving import make_server

    from diski9.app import ScreenerData, create_app
    from diski9.app import app as appmod
    from diski9.backend.auth.provider import SupabaseAuthProvider
    from diski9.backend.auth.web import AuthRuntime
    from tests.test_app import _free_port

    op = principal(engine, role="operator")
    view, snap = publish_dev(engine, op, deadline_in=timedelta(hours=3), seed=8851)
    short, ssnap = publish_dev(engine, op, deadline_in=timedelta(seconds=40), seed=8852)
    base = datetime.now(UTC).replace(microsecond=0)
    data = Data(ScreenerData(_football(tmp_path, base), ttl_seconds=0), snap)
    data.add(ssnap)
    backend = SwitchableBackend(engine, view.id)
    monkeypatch.setattr(appmod, "competition_backend", lambda auth: backend)
    port = _free_port()
    settings = make_settings(supabase_auth_url=AUTH_URL, supabase_publishable_key=ANON,
                             supabase_jwt_issuer=AUTH_URL,
                             app_site_url=f"http://127.0.0.1:{port}")  # fmt: skip
    provider = SupabaseAuthProvider(settings)
    app = create_app(data, auth=AuthRuntime.create(engine, settings, provider))
    server = make_server("127.0.0.1", port, app.server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    password = "Cp3a5-Accept-9"
    users = [{"email": _confirmed(provider, password), "password": password,
              "username": f"cp{uuid.uuid4().hex[:8]}"} for _ in range(1)]  # fmt: skip
    try:
        yield {
            "base": f"http://127.0.0.1:{port}/",
            "engine": engine,
            "backend": backend,
            "view": view,
            "snap": snap,
            "short": short,
            "ssnap": ssnap,
            "users": users,
        }
    finally:
        server.shutdown()


def _keys(snap, n=9):
    return [f"{k['fixture_id']}|{k['market']}|{k['outcome']}" for k in valid_keys(snap, n)]


def _run(script: str, **consts) -> dict:
    shots = os.environ.get("DISKI9_SHOTS", "")
    head = "".join(f"const {k} = {json.dumps(v)};\n" for k, v in {**consts, "SHOTS": shots}.items())
    res = subprocess.run(["node", "-e", head + COMMON + script], capture_output=True, text=True,
                         timeout=600, cwd=ROOT)  # fmt: skip
    assert res.returncode == 0, res.stderr[-4000:]
    out = json.loads(res.stdout.strip().splitlines()[-1])
    if shots:
        with Path(shots, "cp3a5_results.json").open("a") as f:
            f.write(json.dumps(out) + "\n")
    return out


COMMON = r"""
const { chromium } = require('playwright');
const sel = (o) => `[id='${JSON.stringify(o)}']`;
const errorsOf = (p, out, tag) => {
  p.on('pageerror', e => out.errors.push(tag + ': ' + e.message));
  p.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) out.errors.push(tag + ': ' + m.text()); });
};
const idle = async (p, ms = 300) => { await p.waitForTimeout(ms); await p.waitForFunction(() => !document.querySelector('._dash-loading-callback'), null, { timeout: 20000 }).catch(() => {}); };
const overflow = (p) => p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
const txt = async (p, css) => ((await p.locator(css).first().innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim();
const shot = async (p, name, w) => { if (SHOTS) { await p.waitForTimeout(250); await p.screenshot({ path: `${SHOTS}/cp3a5_${name}_${w}.png`, fullPage: false }); } };
const until = (p, s) => p.waitForFunction((t) => ((document.querySelector('#lab-root') || {}).innerText || '').toLowerCase().includes(t), s.toLowerCase(), { timeout: 25000 });
const labHome = async (p) => (await p.locator('#ctx-home-input').inputValue().catch(() => '')) || '';
async function signIn(p, u, onboard) {
  await p.goto(BASE + 'auth/sign-in');
  await p.fill('input[name=email]', u.email); await p.fill('input[name=password]', u.password);
  await Promise.all([p.waitForNavigation(), p.click('form button[type=submit]')]);
  if (p.url().includes('/account/welcome') && onboard) {
    await p.fill('input[name=username]', u.username);
    await p.check('input[name=age_confirmed]'); await p.check('input[name=accept_terms]');
    await Promise.all([p.waitForNavigation(), p.click('form button[type=submit]')]);
  }
}
async function openPB(p) { await p.goto(BASE); await p.waitForSelector('#pb-go', { state: 'visible', timeout: 25000 }); await idle(p, 600); }
async function research(p, on) {
  const box = p.locator('#research-only input[type=checkbox]');
  if ((await box.isChecked()) !== on) { await box.click(); await idle(p, 600); }
}
const pickIn = async (p, k) => {
  // the builder shows ten matches per page: find the outcome on either page
  for (let i = 0; i < 3 && !(await p.locator(sel({ k, t: 'pick' })).count()); i++) {
    const next = p.locator(sel({ d: 'next', t: 'fxpg' }));
    const prev = p.locator(sel({ d: 'prev', t: 'fxpg' }));
    if (await next.isEnabled()) await next.click(); else await prev.click();
    await idle(p, 500);
  }
  await p.locator(sel({ k, t: 'pick' })).click(); await idle(p, 500);
};
const openLabFor = async (p, fid) => {
  for (let i = 0; i < 3 && !(await p.locator(`.ch-lab-link:visible[href*="fixture=${fid}&"]`).count()); i++) {
    const next = p.locator(sel({ d: 'next', t: 'fxpg' }));
    if (await next.isEnabled()) await next.click(); else await p.locator(sel({ d: 'prev', t: 'fxpg' })).click();
    await idle(p, 500);
  }
  await p.locator(`.ch-lab-link:visible[href*="fixture=${fid}&"]`).first().click();
  await p.waitForURL(/ctx=challenge/); await until(p, 'frozen:');
};
const ctxHome = async (p) => {
  const acc = p.locator('.ctx-acc').first();
  if (!(await acc.evaluate(e => e.open))) await acc.locator('summary').click();
  return p.locator('#ctx-home').inputValue();
};
const setHome = async (p, v, shown) => {
  await ctxHome(p); await p.locator('#ctx-home').fill(v); await p.locator('#ctx-home').press('Tab');
  await p.waitForFunction((s) => document.querySelector('#ctx-home').value === s, shown); await idle(p, 800);
};
const latest = (p) => p.locator('#lab-latest input');
const total = (p) => txt(p, '.ch-total');
const nav = async (p, label) => { await p.locator('#site-nav-links .nav-link', { hasText: label }).click(); await idle(p, 900); };
"""


# ------------------------------------------------------------------ journey 1: guest
GUEST = r"""
(async () => {
  const b = await chromium.launch(); const out = { errors: [], widths: {} };
  for (const w of [390, 768, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 900 } });
    const p = await ctx.newPage(); errorsOf(p, out, String(w)); const r = {};
    // the homepage and the domestic card
    await openPB(p);
    r.status = await txt(p, '#pb-status-line'); r.state = await txt(p, '.pb-state');
    r.go = await txt(p, '#pb-go');
    r.researchOff = !(await p.locator('#research-only input').isChecked());
    r.howToCollapsed = await p.evaluate(() => { const d = [...document.querySelectorAll('details')]
      .find(x => /how to play/i.test((x.querySelector('summary') || {}).innerText || '')); return d ? !d.open : null; });
    r.european = /european/i.test(await p.locator('#pb-home').innerText());
    r.nav = await p.locator('#site-nav-links .nav-link').allInnerTexts();
    r.activeHome = await txt(p, '#site-nav-links .nav-link.on');
    r.overflowHome = await overflow(p); await shot(p, 'home_guest', w);
    await p.locator('.pb-research-info summary').click();
    r.tip = await txt(p, '.pb-research-info .info-pop');
    await shot(p, 'research_tooltip', w);
    await p.locator('.pb-research-info summary').click();
    // the competitive list: Minimum Market Probability and pages
    await p.locator('#pb-go').click(); await idle(p, 600);
    const count = () => txt(p, sel({ i: 0, t: 'fx-count' }));
    r.countBefore = await count();
    await p.locator(`${sel({ i: 0, t: 'f-mmp' })} [role=slider]`).focus();
    for (let i = 0; i < 55; i++) await p.keyboard.press('ArrowRight');
    await p.waitForFunction((s) => document.querySelector(`[id='{"i":0,"t":"fx-count"}']`).innerText !== s, r.countBefore, { timeout: 15000 });
    r.countMmp = await count();
    await p.locator(sel({ i: 0, t: 'f-mmp' })).scrollIntoViewIfNeeded(); await shot(p, 'builder_mmp', w);
    await p.keyboard.press('Home');
    await p.waitForFunction((s) => document.querySelector(`[id='{"i":0,"t":"fx-count"}']`).innerText === s, r.countBefore, { timeout: 15000 });
    await p.locator(sel({ d: 'next', t: 'fxpg' })).click(); await idle(p, 600);
    r.page2 = await count();
    await p.locator(sel({ d: 'prev', t: 'fxpg' })).click(); await idle(p, 600);
    await p.evaluate(() => window.scrollTo(0, 0)); r.overflowBuilder = await overflow(p); await shot(p, 'builder', w);
    // a challenge match: frozen first, then the latest data (research only), then back
    const link = p.locator('.ch-lab-link:visible').first();
    r.link = await link.getAttribute('href');
    await link.click(); await p.waitForURL(/ctx=challenge/); await until(p, 'frozen:');
    r.toggleShown = await p.locator('#lab-latest-wrap').isVisible();
    r.toggleOff = !(await latest(p).isChecked());
    await p.waitForFunction(() => document.querySelector('#lab-challenge').innerText.trim().length > 0, null, { timeout: 15000 }).catch(() => {});
    r.frozenPanel = (await txt(p, '#lab-challenge')).length > 0;
    await p.waitForFunction(() => document.querySelectorAll('#detail-reference .card.market .price').length > 0, null, { timeout: 15000 }).catch(() => {});
    r.frozenCard = (await txt(p, '#detail-reference')).toLowerCase().includes('frozen bookmaker market reference');
    r.activeLab = await txt(p, '#site-nav-links .nav-link.on');
    r.overflowFrozen = await overflow(p); await shot(p, 'lab_frozen', w);
    await latest(p).click(); await until(p, 'model calculated');
    await p.waitForFunction(() => document.querySelector('#lab-challenge').innerText.trim() === '', null, { timeout: 10000 }).catch(() => {});
    r.latestPanel = await txt(p, '#lab-challenge');
    r.latestNote = (await txt(p, '#lab-root')).toLowerCase().includes('research only');
    r.overflowLatest = await overflow(p); await shot(p, 'lab_latest', w);
    await latest(p).click(); await until(p, 'frozen:');
    await p.locator('#lab-back').click(); await p.waitForSelector('.ch-lab-link:visible', { state: 'visible' });
    // Research only: the latest-data list and a research match
    await research(p, true);
    r.goResearch = await txt(p, '#pb-go');
    const item = w < 720 ? '#screener-root .fx-card' : '#screener-root tr.row';
    await p.waitForSelector(item, { state: 'visible', timeout: 20000 });
    r.researchNote = await txt(p, '#pb-mode-note');
    r.overflowResearch = await overflow(p); await shot(p, 'research_list', w);
    await p.locator(item).first().click(); await p.waitForURL(/ctx=research/); await until(p, 'model calculated');
    r.researchToggle = await p.locator('#lab-latest-wrap').isVisible();
    r.researchPanel = await txt(p, '#lab-challenge');
    r.overflowLabResearch = await overflow(p); await shot(p, 'lab_research', w);
    await p.locator('#lab-back').click(); await p.waitForSelector(item, { state: 'visible' });
    r.researchKept = await p.locator('#research-only input').isChecked();
    // the other tabs
    for (const [label, name] of [['My Challenge', 'my_challenge'], ['Training Ground', 'training'], ['Leaderboard', 'leaderboard']]) {
      await nav(p, label);
      r['active_' + name] = await txt(p, '#site-nav-links .nav-link.on');
      r['heading_' + name] = await txt(p, '#ch-root h1');
      r['overflow_' + name] = await overflow(p); await shot(p, name + '_guest', w);
    }
    if (w === 1280) {
      // old addresses and unsafe links
      await p.goto(BASE + 'challenge?src=old'); await idle(p, 600); r.legacyChallenge = p.url();
      await p.goto(BASE + `?fixture=${RFID}`); await idle(p, 600); r.legacyFixture = p.url();
      await p.goto(BASE + 'lab?fixture=abc&ctx=challenge'); await idle(p, 1200); r.invalid = await txt(p, '#lab-root');
      await p.goto(BASE + `lab?fixture=${RFID}&ctx=challenge&round=not-a-round`); await idle(p, 1200); r.gone = await txt(p, '#lab-root');
      await p.goto(BASE + 'nowhere'); await idle(p, 800); r.notFound = await txt(p, '#ch-root');
    }
    out.widths[w] = r; await ctx.close();
  }
  console.log(JSON.stringify(out)); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


# ------------------------------------------------------- journeys 2 and 3: guest to account
ACCOUNT = r"""
(async () => {
  const b = await chromium.launch(); const out = { errors: [] }; const w = 1280;
  const p = await (await b.newContext({ viewport: { width: w, height: 900 } })).newPage();
  errorsOf(p, out, 'account');
  const fid = (k) => k.split('|')[0];
  // as a guest: two picks and a frozen Your View adjustment
  await openPB(p); await p.locator('#pb-go').click(); await idle(p, 600);
  for (const k of KEYS.slice(0, 2)) await pickIn(p, k);
  out.guestTotal = await total(p);
  await openLabFor(p, fid(KEYS[0]));
  await setHome(p, '0.30', '+0.30');
  // sign in with Supabase Auth; keep the guest work and adopt it into the account
  await signIn(p, USER, true);
  await openPB(p);
  await p.waitForSelector('#d9-guest-choice', { timeout: 20000 });
  out.choice = await txt(p, '#d9-guest-choice'); await shot(p, 'guest_choice', w);
  await Promise.all([p.waitForNavigation(), p.click('#d9-guest-keep')]); await idle(p, 1500);
  await p.waitForSelector('.adopt-panel', { timeout: 20000 });
  out.adoptPanel = await txt(p, '.adopt-panel'); await shot(p, 'adoption', w);
  await p.locator(`button[id*='"t":"adopt-save"']`).click(); await idle(p, 2000);
  out.adoptFlash = await txt(p, '.ch-flash');
  await openPB(p); await p.locator('#pb-go').click(); await idle(p, 800);
  out.afterAdopt = await total(p);
  out.homeSignedIn = await txt(p, '.site-nav'); await p.evaluate(() => window.scrollTo(0, 0)); await shot(p, 'home_signed_in', w);
  // frozen and latest Your View stay separate; the market keeps the mode
  await openLabFor(p, fid(KEYS[0]));
  out.frozenAdopted = await ctxHome(p);
  await latest(p).click(); await until(p, 'model calculated');
  out.latestStart = await ctxHome(p);
  await setHome(p, '-0.20', '-0.20');
  await p.locator('#lab-market label', { hasText: 'Both Teams' }).click();
  await p.waitForFunction(() => document.querySelector('#lab-market input:checked').value === 'BTTS');
  await until(p, 'model calculated');
  out.stillLatest = await latest(p).isChecked();
  out.latestPanel = await txt(p, '#lab-challenge');
  out.totalInLatest = await txt(p, '#ch-strip');
  await shot(p, 'lab_latest_signed_in', w);
  await latest(p).click(); await until(p, 'frozen:');
  out.frozenBack = await ctxHome(p);
  out.marketKept = await p.evaluate(() => document.querySelector('#lab-market input:checked').value);
  await shot(p, 'lab_frozen_signed_in', w);
  // a selection made from the frozen Match Lab
  await p.locator('#lab-back').click(); await p.waitForSelector('.ch-lab-link:visible', { state: 'visible' });
  await openLabFor(p, fid(KEYS[2]));
  await p.locator(sel({ k: KEYS[2], t: 'labpick' })).click(); await idle(p, 1000);
  out.stripAfterLabPick = await txt(p, '#ch-strip');
  // back to Portfolio Build on page 2: the page is kept across the Match Lab
  await p.locator('#lab-back').click(); await p.waitForSelector('.ch-lab-link:visible', { state: 'visible' });
  if (!(await txt(p, '.pager:visible .muted')).startsWith('Page 2')) {
    await p.locator(sel({ d: 'next', t: 'fxpg' })).click();
    await p.waitForFunction(() => [...document.querySelectorAll('.pager')].some(e => e.offsetParent !== null && e.innerText.includes('Page 2')), null, { timeout: 15000 });
  }
  await idle(p, 400);
  out.pageBefore = await txt(p, '.pager:visible .muted');
  await p.locator('.ch-lab-link:visible').first().click(); await p.waitForURL(/ctx=challenge/); await until(p, 'frozen:');
  await p.locator('#lab-back').click(); await p.waitForSelector('.ch-lab-link:visible', { state: 'visible' });
  out.pageAfter = await txt(p, '.pager:visible .muted');
  out.totalBack = await total(p);
  // complete the portfolio, review it and submit
  for (const k of KEYS.slice(3)) await pickIn(p, k);
  out.full = await total(p);
  await p.locator(sel({ i: 'tracker', t: 'nav', to: 'review' })).click(); await idle(p, 1500);
  out.review = await txt(p, '#ch-root'); await p.evaluate(() => window.scrollTo(0, 0)); await shot(p, 'review_signed_in', w);
  await p.locator(sel({ i: 0, t: 'submit' })).click(); await p.waitForSelector('.ch-modal', { timeout: 20000 });
  out.modal = await txt(p, '.ch-modal'); await shot(p, 'submitted', w);
  await p.locator(sel({ i: 0, t: 'modalclose' })).click(); await idle(p, 800);
  await nav(p, 'My Challenge');
  out.me = await txt(p, '#ch-root'); await shot(p, 'my_challenge_signed_in', w);
  await nav(p, 'Leaderboard');
  out.leaderboard = await txt(p, '#ch-root h1'); await shot(p, 'leaderboard_signed_in', w);
  console.log(JSON.stringify(out)); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


# ------------------------------------------------------------ journey 4: another device
DEVICE = r"""
(async () => {
  const b = await chromium.launch(); const out = { errors: [], widths: {} };
  for (const w of [390, 768]) {
    const p = await (await b.newContext({ viewport: { width: w, height: 900 } })).newPage();
    errorsOf(p, out, 'device ' + w); const r = {};
    await signIn(p, USER, false);
    await openPB(p);
    r.status = await txt(p, '#pb-status-line'); r.overflowHome = await overflow(p); await shot(p, 'home_signed_in', w);
    await p.goto(BASE + `lab?fixture=${FID}&ctx=challenge&round=${ROUND}`); await until(p, 'frozen:');
    r.frozen = await ctxHome(p);
    r.overflowFrozen = await overflow(p); await shot(p, 'lab_frozen_signed_in', w);
    await latest(p).click(); await until(p, 'model calculated');
    r.latest = await ctxHome(p); r.overflowLatest = await overflow(p); await shot(p, 'lab_latest_signed_in', w);
    await nav(p, 'My Challenge'); r.me = await txt(p, '#ch-root');
    r.overflowMe = await overflow(p); await shot(p, 'my_challenge_signed_in', w);
    await nav(p, 'Portfolio Build'); await idle(p, 800);
    r.builder = await txt(p, '#ch-root'); r.overflowBuilder = await overflow(p); await shot(p, 'builder_signed_in', w);
    out.widths[w] = r;
  }
  console.log(JSON.stringify(out)); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


WITHDRAW = r"""
(async () => {
  const b = await chromium.launch(); const out = { errors: [] };
  const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  errorsOf(p, out, 'withdraw');
  await signIn(p, USER, false);
  await p.goto(BASE + 'challenge/me'); await p.waitForSelector(sel({ i: 'me', t: 'askwithdraw' }), { timeout: 20000 });
  await p.locator(sel({ i: 'me', t: 'askwithdraw' })).click(); await p.waitForSelector('.ch-modal');
  out.ask = await txt(p, '.ch-modal');
  await p.locator(sel({ i: 0, t: 'confirmwithdraw' })).click(); await idle(p, 1500);
  await p.reload(); await idle(p, 1500);
  out.me = await txt(p, '#ch-root');
  console.log(JSON.stringify(out)); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


# --------------------------------------------- journey 5: after the deadline, no challenge
AFTER = r"""
(async () => {
  const b = await chromium.launch(); const out = { errors: [] };
  const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  errorsOf(p, out, MODE);
  await openPB(p);
  out.status = await txt(p, '#pb-status-line'); out.state = await txt(p, '.pb-state');
  out.go = await txt(p, '#pb-go');
  out.research = await p.locator('#research-only input').isChecked();
  await shot(p, 'home_' + MODE, 1280);
  if (MODE === 'locked') {
    await p.locator('#pb-go').click(); await idle(p, 800);
    out.enabledPicks = await p.locator(`button[id*='"t":"pick"']:not([disabled])`).count();
    out.disabledPicks = await p.locator(`button[id*='"t":"pick"'][disabled]`).count();
    await shot(p, 'builder_locked', 1280);
    await p.locator('.ch-lab-link:visible').first().click(); await p.waitForURL(/ctx=challenge/); await until(p, 'frozen:');
    await p.waitForFunction(() => document.querySelector('#lab-challenge').innerText.trim().length > 0, null, { timeout: 15000 }).catch(() => {});
    out.panel = await txt(p, '#lab-challenge');
    out.labPicks = await p.locator(`#lab-challenge button[id*='"t":"labpick"']:not([disabled])`).count();
    out.toggle = await p.locator('#lab-latest-wrap').isVisible();
    await shot(p, 'lab_locked', 1280);
    await latest(p).click(); await until(p, 'model calculated');
    await p.waitForFunction(() => document.querySelector('#lab-challenge').innerText.trim() === '', null, { timeout: 15000 }).catch(() => {});
    out.latestPanel = await txt(p, '#lab-challenge');
  } else {
    const item = '#screener-root tr.row';
    await p.waitForSelector(item, { state: 'visible', timeout: 20000 });
    out.rows = await p.locator(item).count();
    await p.locator(item).first().click(); await p.waitForURL(/ctx=research/); await until(p, 'model calculated');
    out.researchLab = true;
    await p.goto(BASE + `lab?fixture=${FID}&ctx=challenge&round=${ROUND}`); await idle(p, 1500);
    out.oldChallengeLink = await txt(p, '#lab-root');
    await openPB(p); await research(p, false); await idle(p, 800);
    out.builderOff = await txt(p, '#ch-root');
    await shot(p, 'builder_unavailable', 1280);
  }
  console.log(JSON.stringify(out)); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def test_cp3a_integrated_journeys(stack):
    snap, user = stack["snap"], stack["users"][0]
    keys = _keys(snap)
    assert len(keys) == 9 and len({k.split("|")[0] for k in keys}) == 9

    # 1. guest, three widths
    g = _run(GUEST, BASE=stack["base"], RFID=EPL_FIX)
    assert g["errors"] == [], g["errors"]
    for w, r in g["widths"].items():
        assert r["nav"] == ["Portfolio Build", "Match Lab", "My Challenge", "Training Ground",
                            "Leaderboard"], w  # fmt: skip
        assert r["activeHome"] == "Portfolio Build" and r["activeLab"] == "Match Lab", (w, r)
        assert r["status"].startswith("Entries close") and r["researchOff"], (w, r)
        assert (
            r["go"] == "Build domestic portfolio" and r["goResearch"] == "Analyse domestic matches"
        )
        assert r["howToCollapsed"] is True and not r["european"], (w, r)
        assert "does not form part of the Weekly Challenge" in r["tip"], (w, r)
        assert r["countMmp"] != r["countBefore"] and "filtered" in r["countMmp"], (w, r)
        assert r["page2"].startswith("Matches 11"), (w, r)
        assert "ctx=challenge" in r["link"] and "round=" in r["link"], (w, r)
        assert r["toggleShown"] and r["toggleOff"] and r["frozenPanel"] and r["frozenCard"], (w, r)
        assert r["latestPanel"] == "" and r["latestNote"], (w, r)
        assert not r["researchToggle"] and r["researchPanel"] == "" and r["researchKept"], (w, r)
        assert "research only" in r["researchNote"].lower(), (w, r)
        assert (
            r["active_my_challenge"] == "My Challenge" and r["active_training"] == "Training Ground"
        )
        assert (
            r["active_leaderboard"] == "Leaderboard" and r["heading_leaderboard"] == "Leaderboard"
        )
        assert r["heading_training"] == "Training Ground", (w, r)
        overflow = [k for k in r if k.lower().startswith("overflow") and r[k] > 0]
        assert overflow == [], (w, overflow)
    big = g["widths"]["1280"]
    assert big["legacyChallenge"].endswith("/?src=old")
    assert big["legacyFixture"].endswith(f"/lab?fixture={EPL_FIX}")
    assert "This match link is not valid" in big["invalid"]
    assert "no longer" in big["gone"].lower() or "not available" in big["gone"].lower(), big["gone"]
    assert "Page not found" in big["notFound"]

    # 2 and 3. guest to account, then the signed-in journey
    a = _run(ACCOUNT, BASE=stack["base"], USER=user, KEYS=keys)
    assert a["errors"] == [], a["errors"]
    assert a["guestTotal"] == "2/9" and "Keep the analysis" in a["choice"], a
    assert a["afterAdopt"] == "2/9", a
    assert a["frozenAdopted"] == "+0.30" and a["latestStart"] == "0.00", a  # separate contexts
    assert a["stillLatest"] and a["latestPanel"] == "", a  # latest data: no selection controls
    assert a["frozenBack"] == "+0.30" and a["marketKept"] == "BTTS", a
    assert "3/9" in a["stripAfterLabPick"], a
    assert a["pageBefore"] == a["pageAfter"] == "Page 2 of 2" and a["totalBack"] == "3/9", a
    assert a["full"] == "9/9", a
    assert "Review" in a["review"] or "review" in a["review"], a["review"][:300]
    assert "Show my nine predictions" in a["me"], a["me"][:400]
    assert a["leaderboard"] == "Leaderboard"

    # 4. another device: the account's saved Your View in each context, the submission
    d = _run(DEVICE, BASE=stack["base"], USER=user, FID=int(keys[0].split("|")[0]),
             ROUND=snap.round_id)  # fmt: skip
    assert d["errors"] == [], d["errors"]
    for w, r in d["widths"].items():
        assert r["frozen"] == "+0.30" and r["latest"] == "-0.20", (w, r)
        assert "Show my nine predictions" in r["me"], (w, r["me"][:300])
        assert [k for k in r if k.startswith("overflow") and r[k] > 0] == [], (w, r)

    w = _run(WITHDRAW, BASE=stack["base"], USER=user)
    assert w["errors"] == [] and "Show my nine predictions" not in w["me"], w

    # 5. after the entry deadline the round is read-only; with no round, research only
    engine, short = stack["engine"], stack["short"]
    wait_until(engine, rsvc.get_round(engine, short.id).deadline_at)
    rsvc.lock_round(engine, rsvc.SYSTEM, short.id)
    stack["backend"].round_id = short.id
    lk = _run(AFTER, BASE=stack["base"], MODE="locked", FID=0, ROUND="")
    assert lk["errors"] == [], lk["errors"]
    assert lk["status"] == "Entries closed. Awaiting match results." and not lk["research"], lk
    assert lk["enabledPicks"] == 0 and lk["disabledPicks"] > 0, lk
    assert lk["labPicks"] == 0 and "closed" in lk["panel"].lower() and lk["toggle"], lk
    assert lk["latestPanel"] == "", lk
    stack["backend"].round_id = None
    un = _run(AFTER, BASE=stack["base"], MODE="unavailable", FID=int(keys[0].split("|")[0]),
              ROUND=snap.round_id)  # fmt: skip
    assert un["errors"] == [], un["errors"]
    assert un["research"] and un["go"] == "Analyse domestic matches", un
    assert un["rows"] > 0 and un["researchLab"], un
    assert "Weekly Challenge" in un["oldChallengeLink"], un  # safe message, never latest data
