// Helpers for the Phase 6C.3 local browser journeys (development database only).
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = process.env.BASE || 'http://127.0.0.1:8050';
const AUTH = 'http://127.0.0.1:9999';
function env() {
  const out = {};
  for (const line of fs.readFileSync(require('path').resolve(__dirname, '../../tmp/local_auth/env'), 'utf8').split('\n')) {
    const i = line.indexOf('='); if (i > 0) out[line.slice(0, i)] = line.slice(i + 1);
  }
  return out;
}
async function createUser(tag) {
  const e = env();
  const key = e.DISKI9_TEST_SUPABASE_SERVICE_ROLE_KEY;
  const email = `${tag}-${Date.now()}@example.test`;
  const password = 'Acceptance-' + Math.random().toString(36).slice(2, 10) + '!9';
  const r = await fetch(`${AUTH}/admin/users`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, apikey: key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, email_confirm: true }),
  });
  if (!r.ok) throw new Error('create user failed ' + r.status);
  return { email, password, username: (tag + Date.now().toString(36)).slice(0, 20) };
}
function clearRateLimits() {
  // local e2e database only: many test sign-ins from one address hit the real limit
  require('child_process').execSync(
    'psql -h 127.0.0.1 -p 5433 -U postgres -d diski9_e2e -qc "DELETE FROM app.auth_rate_events"');
}
async function signIn(page, u, onboard = true) {
  clearRateLimits();
  await page.goto(`${BASE}/auth/sign-in`);
  await page.fill('input[name=email]', u.email);
  await page.fill('input[name=password]', u.password);
  await Promise.all([page.waitForNavigation(), page.click('form button[type=submit]')]);
  if (page.url().includes('/account/welcome') && onboard) {
    await page.fill('input[name=username]', u.username);
    await page.check('input[name=age_confirmed]');
    await page.check('input[name=accept_terms]');
    await Promise.all([page.waitForNavigation(), page.click('form button[type=submit]')]);
  }
}
async function settle(page, ms = 700) {
  await page.waitForTimeout(ms);
  await page.waitForFunction(() => !document.querySelector('._dash-loading-callback'), null, { timeout: 15000 }).catch(() => {});
}
async function pickEnabled(page, n) {
  const picked = [];
  for (let i = 0; i < n; i++) {
    const sel = 'button[id*="\\"t\\":\\"pick\\""]:not([disabled]):not(.is-selected)';
    for (let k = 0; k < 3 && !(await page.locator(sel).count()); k++) {
      await page.locator('button[id*="\\"d\\":\\"next\\""]').first().click().catch(() => {});
      await settle(page, 1200);
    }
    const b = page.locator(sel).first();
    const id = await b.getAttribute('id');
    await b.click();
    await settle(page, 900);
    picked.push(JSON.parse(id).k);
  }
  return picked;
}
async function selected(page) {
  const ids = await page.locator('button.is-selected[id*="\\"t\\":\\"pick\\""]').evaluateAll(
    els => els.map(e => JSON.parse(e.id).k));
  return ids.sort();
}
async function text(page, sel) { return (await page.locator(sel).first().innerText().catch(() => '')) || ''; }
module.exports = { chromium, BASE, createUser, signIn, settle, pickEnabled, selected, text };
async function labInput(page, side) {
  const direct = page.locator(`input#lab-${side}-input`);
  return (await direct.count()) ? direct : page.locator(`#lab-${side}-input input`);
}
async function setEstimate(page, side, value) {
  const inp = await labInput(page, side);
  await inp.fill(String(value));
  await inp.press('Enter');
  await settle(page, 1200);
}
async function estimate(page, side) { return (await labInput(page, side)).inputValue(); }
async function openFixture(page, fid) {
  // Phase 8 CP3A-5: the Match Lab is /lab and every link names its context. A challenge
  // fixture opens through the builder's own Match Lab link (ctx=challenge with the
  // published round: the frozen context, as `/?fixture=` with the Weekly Challenge
  // universe selected used to); a fixture not in the builder opens with latest data.
  await page.goto(`${BASE}/`); await settle(page, 2500);
  const link = page.locator(`a[href^="/lab?fixture=${fid}&ctx=challenge"]`).first();
  const href = (await link.count()) ? await link.getAttribute('href') : `/lab?fixture=${fid}`;
  await page.goto(BASE + href);
  await settle(page, 3000);
}
async function universe(page, label) {
  // Phase 8 CP3A-5: the Challenge Mode universe control was removed (CP3A-3/4); for a
  // challenge match its role is taken by the Match Lab toggle "Use latest available
  // data" (on = 'All upcoming', the latest-data context; off = 'Weekly Challenge').
  const box = page.locator('#lab-latest input[type=checkbox]');
  if ((await box.isChecked()) !== /all upcoming/i.test(label)) await box.click();
  await settle(page, 2000);
}
async function signOut(page) {
  await page.goto(`${BASE}/auth/sign-out`);
  await Promise.all([page.waitForNavigation(), page.click('form button[type=submit]')]);
}
module.exports.labInput = labInput;
module.exports.setEstimate = setEstimate;
module.exports.estimate = estimate;
module.exports.openFixture = openFixture;
module.exports.universe = universe;
module.exports.signOut = signOut;
async function pickLast(page) {
  const b = page.locator('button[id*="\\"t\\":\\"pick\\""]:not([disabled]):not(.is-selected)').last();
  const id = await b.getAttribute('id'); await b.click(); await settle(page, 900);
  return JSON.parse(id).k;
}
module.exports.pickLast = pickLast;
async function total(page) {
  const t = await text(page, '[id*="tracker"]');
  const m = t.match(/Your portfolio\s+(\d)\/9/);
  return m ? Number(m[1]) : 0;
}
module.exports.total = total;
