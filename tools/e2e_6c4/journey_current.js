// Phase 6C.4 Stage G: results in the CURRENT-round cards (no other round open) and
// browser timings, on a separate fresh database (diski9_e2e_cur) and app (port 8051).
// Also: a correction applied while the page is open is shown after in-app navigation.
const L = require('../e2e_6c3/lib');
const fs = require('fs');
const path = require('path');
const { execFileSync, execSync } = require('child_process');
const ROOT = path.resolve(__dirname, '../..');
const SHOT = path.join(ROOT, 'docs/screenshots/phase6c4') + '/';
const TMP = path.join(ROOT, 'tmp/e2e_6c4');
const DB = 'diski9_e2e_cur';
const PSQL = `psql -h 127.0.0.1 -p 5433 -U postgres -d ${DB} -Atc`;
const RUN = Date.now().toString(36).slice(-5);
const out = { run: RUN, checks: {}, timings: {}, overflow: {}, pageErrors: [], consoleErrors: [] };
const q = sql => execSync(`${PSQL} "${sql.replace(/"/g, '\\"')}"`).toString().trim();
const ENV = { ...process.env, DISKI9_APP_DATABASE_URL: `postgresql+psycopg://postgres@127.0.0.1:5433/${DB}` };
function sh(cmd) { return execSync(`cd ${ROOT} && ${cmd} 2>&1 | grep -v UV_NATIVE`, { shell: '/bin/bash', env: ENV }).toString(); }
function cli(role, args, confirm) {
  const a = ['run', 'python', 'tools/e2e_6c4/cli.py', role];
  if (confirm) a.push('--confirm', confirm);
  a.push('--', ...args);
  try { return execFileSync('uv', a, { cwd: ROOT, env: ENV, stdio: ['ignore', 'pipe', 'pipe'] }).toString(); }
  catch (e) { return `EXIT ${e.status}\n` + (e.stdout || '').toString(); }
}
const wait = cond => execSync(`until [ "$(${PSQL} "${cond}")" = t ]; do sleep 2; done`, { shell: '/bin/bash' });
async function me(p) { await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2500); return (await p.locator('body').innerText()).toLowerCase(); }  // pills are styled uppercase
async function timeMe(p, selector, runs = 5) {
  const t = [];
  for (let i = 0; i < runs; i++) {
    const s = Date.now();
    await p.goto(L.BASE + '/challenge/me');
    await p.locator(selector).first().waitFor({ timeout: 30000 });
    await p.waitForFunction(() => !document.querySelector('._dash-loading-callback'), null, { timeout: 15000 }).catch(() => {});
    t.push(Date.now() - s);
  }
  t.sort((a, b) => a - b);
  return t[Math.floor(t.length / 2)];
}
(async () => {
  const browser = await L.chromium.launch();
  const mk = async (tag) => {
    const u = await L.createUser(tag);
    const c = await browser.newContext({ viewport: { width: 1360, height: 900 } });
    const p = await c.newPage();
    p.on('pageerror', e => out.pageErrors.push(String(e).slice(0, 200)));
    p.on('console', m => { if (m.type() === 'error') out.consoleErrors.push(m.text().slice(0, 200)); });
    // the lib clears the e2e database's sign-in counters; do the same here
    execSync(`${PSQL} "DELETE FROM app.auth_rate_events"`);
    await L.signIn(p, u);
    return { u, p };
  };
  const pat = await mk('cpat'); const alex = await mk('calex'); const boss = await mk('cboss');
  sh(`uv run diski9 account bootstrap-owner --email ${boss.u.email} --confirm`);
  fs.writeFileSync(path.join(TMP, 'accounts.json'), JSON.stringify({ pat: pat.u, alex: alex.u, owner: boss.u, operator: boss.u }));
  const R = `dev-e2e4c-${RUN}`;
  out.open = sh(`uv run diski9 round dev-open --by-email ${boss.u.email} --deadline-minutes 3 --spacing-minutes 1 --code ${R}`).trim().split('\n').pop();
  const p = pat.p;
  await p.waitForTimeout(3500);
  await p.goto(L.BASE + '/challenge'); await L.settle(p, 2500);
  for (let i = 0; i < 14 && (await L.total(p)) < 9; i++) await L.pickEnabled(p, 1);
  await p.locator('button[id*="\\"to\\":\\"review\\""]').first().click(); await L.settle(p, 2000);
  await p.locator('[id*="\\"t\\":\\"submit\\""]').first().click(); await L.settle(p, 2500);
  await p.locator('[id*="\\"t\\":\\"modalclose\\""]').first().click().catch(() => {}); await L.settle(p, 800);
  cli('alex', ['dev-results', 'test-entry', '--round', R, '--variant', '1']);
  wait(`select now() >= deadline_at from app.rounds where code='${R}'`);
  sh(`uv run diski9 round lock --code ${R}`);
  await p.waitForTimeout(3500);
  out.timings.locked_no_results_ms = await timeMe(p, '.ch-round-card');
  cli('owner', ['dev-results', 'set-mode', '--round', R, '--mode', 'synthetic']);
  cli('owner', ['dev-results', 'scenario', '--round', R, '--name', 'pending']);
  wait(`select now() >= deadline_at + interval '4 minutes 5 seconds' from app.rounds where code='${R}'`);
  cli('owner', ['settle', 'run', '--round', R]);
  out.timings.partial_results_ms = await timeMe(p, '.ch-res-summary');
  let t = await me(p);
  out.checks.current_partial = t.includes('partly settled') && (await p.locator('.ch-round-card .ch-pill').first().innerText()).toUpperCase().includes('PARTLY');
  await p.screenshot({ path: SHOT + 'current_partial_desktop.png', fullPage: true });
  // complete the pending fixtures with operator corrections (full time, verified completion)
  const pend = q(`select string_agg(distinct fixture_id::text, ' ') from app.selection_verdicts v where v.round_id=(select id from app.rounds where code='${R}') and verdict='pending'`).split(' ').filter(Boolean);
  const now = q('select to_char(now() at time zone \'utc\', \'YYYY-MM-DD"T"HH24:MI:SS"+00:00"\')');
  const t0 = Date.now();
  for (const f of pend)
    cli('owner', ['results', 'correct', '--round', R, '--fixture', f, '--status', 'FT', '--home', '1', '--away', '1',
      '--completed-at', now, '--reason', 'official result', '--evidence', 'league report'], R);
  out.timings.corrections_cli_total_ms = Date.now() - t0;
  out.corrections = pend.length;
  // the page stays open; in-app navigation must show the authoritative result
  await p.locator('a[href="/challenge"]').first().click(); await L.settle(p, 1500);
  const s = Date.now();
  await p.locator('a[href="/challenge/me"]').first().click();
  await p.locator('.ch-res-summary').first().waitFor();
  await L.settle(p, 1500);
  out.timings.corrected_refresh_ms = Date.now() - s;
  t = (await p.locator('body').innerText()).toLowerCase();
  out.checks.current_complete_after_navigation = t.includes('provisional result') && t.includes('corrected') && !t.includes('still pending');
  out.timings.complete_results_ms = await timeMe(p, '.ch-res-summary');
  for (const [w, h, name] of [[1360, 900, 'desktop'], [768, 1024, 'tablet'], [390, 844, 'mobile']]) {
    await p.setViewportSize({ width: w, height: h }); await L.settle(p, 900);
    await p.screenshot({ path: SHOT + `current_complete_${name}.png`, fullPage: true });
    out.overflow[name] = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  }
  out.checks.alex_private = await (async () => { const tt = await me(alex.p); return !tt.includes(pat.u.username) && tt.includes('Your result'); })();
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { console.log(JSON.stringify(out, null, 1)); console.error(String(e).slice(0, 600)); process.exit(1); });
