// Helpers for the Phase 6C.5 Stage E local browser checks (development database only).
// Accounts are throw-away users on the *local* Supabase Auth server; their passwords
// live in the git-ignored tmp/e2e_6c5/accounts.json, never in the repository.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const BASE = process.env.BASE || 'http://127.0.0.1:8052';
const AUTH = 'http://127.0.0.1:9999';
const DB = process.env.E2E_DB || 'diski9_e2e_6c5';
const ROOT = path.resolve(__dirname, '../..');
function env() {
  const out = {};
  for (const line of fs.readFileSync(path.join(ROOT, 'tmp/local_auth/env'), 'utf8').split('\n')) {
    const i = line.indexOf('='); if (i > 0) out[line.slice(0, i)] = line.slice(i + 1);
  }
  return out;
}
async function createUser(tag) {
  const key = env().DISKI9_TEST_SUPABASE_SERVICE_ROLE_KEY;
  const email = `${tag}-${Date.now()}@example.test`;
  const password = 'Acceptance-' + Math.random().toString(36).slice(2, 10) + '!9';
  const r = await fetch(`${AUTH}/admin/users`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, apikey: key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, email_confirm: true }),
  });
  if (!r.ok) throw new Error('create user failed ' + r.status);
  const body = await r.json();
  return { email, password, username: (tag + Date.now().toString(36)).slice(0, 20), sub: body.id };
}
function clearRateLimits() {
  require('child_process').execSync(
    `psql -h 127.0.0.1 -p 5433 -U postgres -d ${DB} -qc "DELETE FROM app.auth_rate_events"`);
}
async function signIn(page, u) {
  clearRateLimits();
  await page.goto(`${BASE}/auth/sign-in`);
  await page.fill('input[name=email]', u.email);
  await page.fill('input[name=password]', u.password);
  await Promise.all([page.waitForNavigation(), page.click('form button[type=submit]')]);
  if (page.url().includes('/account/welcome')) {
    await page.fill('input[name=username]', u.username);
    await page.check('input[name=age_confirmed]');
    await page.check('input[name=accept_terms]');
    await Promise.all([page.waitForNavigation(), page.click('form button[type=submit]')]);
  }
}
async function settle(page, ms = 700) {
  await page.waitForTimeout(ms);
  await page.waitForFunction(() => !document.querySelector('._dash-loading-callback'), null, { timeout: 20000 }).catch(() => {});
}
function accounts() { return JSON.parse(fs.readFileSync(path.join(ROOT, 'tmp/e2e_6c5/accounts.json'), 'utf8')); }
module.exports = { chromium, BASE, ROOT, createUser, signIn, settle, accounts };
