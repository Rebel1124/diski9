// Stage G browser performance: end-to-end latency of user actions, measured from
// the action until the last Dash callback request has finished (no request in
// flight for 400 ms). Run against: the pre-persistence app (prototype), the
// current app in prototype mode, and the current app signed in (persistent).
//   MODE=demo    BASE=http://127.0.0.1:8060 node perf.js  (prototype, demonstration round)
//   MODE=guest   BASE=http://127.0.0.1:8050 node perf.js  (accounts on, not signed in)
//   MODE=account BASE=http://127.0.0.1:8050 node perf.js  (signed in, published round)
// RUNS (default 5) repetitions; Match Lab steps run once (first run).
const L = require('./lib');
const MODE = process.env.MODE || 'demo';
const RUNS = Number(process.env.RUNS || 5);
const BASE = process.env.BASE || L.BASE;
const pickSel = 'button[id*="\\"t\\":\\"pick\\""]:not([disabled]):not(.is-selected)';
// Timing from Resource Timing entries of Dash callback requests. An action ends with
// the last callback of its continuous chain: a gap of more than GAP ms without a
// callback in flight ends the chain (so a small trailing callback that starts
// seconds later is not counted as waiting time).
const GAP = 1000;
async function entries(p) {
  return p.evaluate(() => performance.getEntriesByType('resource')
    .filter(e => e.name.includes('_dash-update-component'))
    .map(e => [e.startTime, e.responseEnd]));
}
async function quiet(p) {
  let n = (await entries(p)).length, since = Date.now(); const cap = Date.now() + 20000;
  for (;;) {
    await p.waitForTimeout(100);
    const m = (await entries(p)).length;
    if (m !== n) { n = m; since = Date.now(); }
    if (Date.now() - since >= GAP + 200 || Date.now() > cap) return;
  }
}
function chainEnd(list, t0) {
  let end = t0;
  for (const [s, e] of list.filter(x => x[0] >= t0 - 1).sort((x, y) => x[0] - y[0])) {
    if (s - end > GAP) break;
    end = Math.max(end, e);
  }
  return end;
}
function tracker(p) {
  return async function timed(fn) {
    const t0 = await p.evaluate(() => performance.now());
    await fn();
    await quiet(p);
    return Math.round(chainEnd(await entries(p), t0) - t0);
  };
}
async function timedLoad(p, url) {
  await p.goto(url); await p.waitForLoadState('load');
  await quiet(p);
  return Math.round(chainEnd(await entries(p), 0));
}
const log = m => { if (process.env.PERF_LOG) require('fs').appendFileSync(process.env.PERF_LOG, m + '\n'); };
const median = a => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
(async () => {
  const browser = await L.chromium.launch();
  const res = {};
  const add = (k, v) => (res[k] = res[k] || []).push(v);
  const errors = [];
  let user = null;
  if (MODE === 'account') user = await L.createUser('perf');
  for (let run = 0; run < RUNS; run++) {
    const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
    const p = await ctx.newPage();
    p.on('pageerror', e => errors.push(String(e)));
    const timed = tracker(p);
    if (user) { await L.signIn(p, user, run === 0); }
    log('run ' + run);
    add('challenge_load', await timedLoad(p, BASE + '/challenge'));
    if (MODE === 'demo') {
      await timed(async () => p.locator('button[id*="\\"m\\":\\"demo\\""]').first().click());
    }
    // clear any picks left from a previous run (account mode restores the draft)
    for (let i = 0; i < 9 && (await p.locator('button.is-selected[id*="\\"t\\":\\"pick\\""]').count()); i++) {
      await timed(async () => p.locator('button.is-selected[id*="\\"t\\":\\"pick\\""]').first().click());
    }
    log('picks ' + await p.locator(pickSel).count());
    add('add_pick', await timed(async () => p.locator(pickSel).first().click()));
    add('remove_pick', await timed(async () => p.locator('button.is-selected[id*="\\"t\\":\\"pick\\""]').first().click()));
    add('add_pick_2', await timed(async () => p.locator(pickSel).first().click()));
    const id = await p.locator('button.is-selected[id*="\\"t\\":\\"pick\\""]').first().getAttribute('id');
    const fid = process.env.FID || JSON.parse(id).k.split('|')[0];
    if (run === 0) {
      add('screener_load', await timedLoad(p, `${BASE}/`));
      add('match_lab_open', await timed(async () => p.locator('[id*="\\"type\\":\\"row\\""]').nth(1).click()));
      const uni = p.locator('.universe label', { hasText: 'All upcoming' });
      if (await uni.count()) add('context_switch', await timed(async () => uni.click()));
      const inp = await L.labInput(p, 'home');
      log('lab input ' + await inp.count());
      if (await inp.count()) {
        const v = Number(await inp.inputValue());
        add('your_view_adjust', await timed(async () => { await inp.fill((v + 0.1).toFixed(2)); await inp.press('Enter'); }));
        add('your_view_reset', await timed(async () => p.locator('#lab-reset').click()));
      }
    }
    add('my_challenge_load', await timedLoad(p, BASE + '/challenge/me'));
    await ctx.close();
  }
  const out = { mode: MODE, base: BASE, runs: RUNS, median_ms: {}, all_ms: res, pageErrors: errors };
  for (const [k, v] of Object.entries(res)) out.median_ms[k] = median(v);
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { console.error(String(e).slice(0, 500)); process.exit(1); });
