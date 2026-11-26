// Helpers for the Phase 7 CP3 local browser checks (disposable p7_e2e database only).
// Accounts are throw-away users on the *local* Supabase Auth server; their passwords
// live in the git-ignored tmp/e2e_p7/accounts.json, never in the repository.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const BASE = process.env.BASE || 'http://127.0.0.1:8057';
const AUTH = 'http://127.0.0.1:9999';
const PG = { host: '127.0.0.1', port: process.env.PGPORT_E2E || '55437', db: 'diski9_p7_e2e' };
const ROOT = path.resolve(__dirname, '../..');
const DATA = path.join(ROOT, 'tmp/e2e_p7');
function env() {
  const out = {};
  for (const line of fs.readFileSync(path.join(ROOT, 'tmp/local_auth/env'), 'utf8').split('\n')) {
    const i = line.indexOf('='); if (i > 0) out[line.slice(0, i)] = line.slice(i + 1);
  }
  return out;
}
function sql(q) {
  return execFileSync('psql', ['-h', PG.host, '-p', PG.port, '-U', 'postgres', '-d', PG.db,
    '-Atc', q]).toString().trim();
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
async function signIn(page, u, base = BASE) {
  sql('DELETE FROM app.auth_rate_events');
  await page.goto(`${base}/auth/sign-in`);
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
  await page.waitForFunction(() => !document.querySelector('._dash-loading-callback'), null,
    { timeout: 20000 }).catch(() => {});
}
function accounts() { return JSON.parse(fs.readFileSync(path.join(DATA, 'accounts.json'), 'utf8')); }
function expectations() { return JSON.parse(fs.readFileSync(path.join(DATA, 'expect.json'), 'utf8')); }
module.exports = { chromium, BASE, ROOT, DATA, createUser, signIn, settle, accounts, expectations, sql };
