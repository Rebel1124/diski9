// Phase 6C.4 Stage G: real-browser settlement journeys (local development only).
// Real app (Dash + Flask), real PostgreSQL (diski9_e2e), real local Supabase Auth.
// Operator commands run through tools/e2e_6c4/cli.py (the real CLI in a
// pseudo-terminal, password typed at the hidden prompt). Rounds are processed one
// after another so each is the current (or most recent) round on My Challenge.
//
// Run (with tmp/dev env loaded, see README):  NODE_PATH=$(npm root -g) node tools/e2e_6c4/journeys.js
const L = require('../e2e_6c3/lib');
const fs = require('fs');
const path = require('path');
const { execFileSync, execSync } = require('child_process');
const ROOT = path.resolve(__dirname, '../..');
const SHOT = path.join(ROOT, 'docs/screenshots/phase6c4') + '/';
const TMP = path.join(ROOT, 'tmp/e2e_6c4');
const RUN = process.env.RUN || Date.now().toString(36).slice(-5);
const out = { run: RUN, journeys: {}, consoleErrors: [], pageErrors: [], overflow: {} };
fs.mkdirSync(SHOT, { recursive: true });
fs.mkdirSync(TMP, { recursive: true });

const PSQL = 'psql -h 127.0.0.1 -p 5433 -U postgres -d diski9_e2e -Atc';
const q = sql => execSync(`${PSQL} "${sql.replace(/"/g, '\\"')}"`).toString().trim();
function sh(cmd) {
  return execSync(`cd ${ROOT} && ${cmd} 2>&1 | grep -v UV_NATIVE`, { shell: '/bin/bash' }).toString();
}
function cli(role, args, confirm) {
  const a = ['run', 'python', 'tools/e2e_6c4/cli.py', role];
  if (confirm) a.push('--confirm', confirm);
  a.push('--', ...args);
  try {
    return execFileSync('uv', a, { cwd: ROOT, env: process.env, stdio: ['ignore', 'pipe', 'pipe'] }).toString();
  } catch (e) {
    return `EXIT ${e.status}\n` + (e.stdout || '').toString();
  }
}
const owner6c3 = JSON.parse(fs.readFileSync(path.join(ROOT, 'tools/e2e_6c3/owner.json'), 'utf8')).email;
function devOpen(code, minutes, fixtures = 20) {
  return sh(`uv run diski9 round dev-open --by-email ${owner6c3} --deadline-minutes ${minutes} ` +
    `--spacing-minutes 1 --fixtures ${fixtures} --code ${code}`).trim().split('\n').pop();
}
function waitDeadline(code) {
  execSync(`until [ "$(${PSQL} "select now() >= deadline_at from app.rounds where code='${code}'")" = t ]; do sleep 2; done`,
    { shell: '/bin/bash' });
}
function lock(code) { return sh(`uv run diski9 round lock --code ${code}`).trim().split('\n').pop(); }
function untilVisible(code) {  // prompt timeline: final evidence 4 minutes after the deadline
  execSync(`until [ "$(${PSQL} "select now() >= deadline_at + interval '4 minutes 5 seconds' from app.rounds where code='${code}'")" = t ]; do sleep 3; done`,
    { shell: '/bin/bash' });
}
function isoOf(text, label) {
  const m = text.match(new RegExp(label + ':\\s+(\\d{4}-\\d\\d-\\d\\d) (\\d\\d:\\d\\d:\\d\\d) UTC'));
  return m ? `${m[1]}T${m[2]}+00:00` : null;
}
const writes = () => q("select (select count(*) from app.entry_settlements) || ',' || (select count(*) from app.settlement_runs) || ',' || (select count(*) from app.selection_verdicts) || ',' || (select count(*) from app.audit_log) || ',' || (select count(*) from app.portfolio_drafts) || ',' || (select count(*) from app.entries)");

async function me(p) {
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2500);
  return p.locator('body').innerText();
}
async function shot(p, name, selector) {
  if (selector && await p.locator(selector).count()) {
    await p.locator(selector).first().scrollIntoViewIfNeeded();
    await p.evaluate(() => window.scrollBy(0, -72));
  }
  await p.screenshot({ path: SHOT + name + '.png' });
}
async function layouts(p, base, selector) {
  for (const [w, h, name] of [[1360, 900, 'desktop'], [768, 1024, 'tablet'], [390, 844, 'mobile']]) {
    await p.setViewportSize({ width: w, height: h }); await L.settle(p, 900);
    await shot(p, `${base}_${name}`, selector);
    out.overflow[`${base}_${name}`] = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    out.overflow[`${base}_${name}_clipped`] = await p.evaluate(() => [...document.querySelectorAll('.ch-res-table td, .ch-metric-val')]
      .filter(e => e.scrollWidth > e.clientWidth + 1).length);
  }
  await p.setViewportSize({ width: 1360, height: 900 });
}
function watch(p) {
  p.on('pageerror', e => out.pageErrors.push(String(e).slice(0, 200)));
  p.on('console', m => { if (m.type() === 'error') out.consoleErrors.push(m.text().slice(0, 200)); });
}
async function account(browser, tag, role) {
  const u = await L.createUser(tag);
  const c = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const p = await c.newPage(); watch(p);
  await L.signIn(p, u);
  if (role) sh(`uv run diski9 account grant-role --email ${u.email} --role ${role} --by-email ${owner6c3} --reason "6C.4 e2e"`);
  return { u, c, p };
}

(async () => {
  const browser = await L.chromium.launch();
  // ---------------------------------------------------------------- accounts
  const pat = await account(browser, 'pat');
  const alex = await account(browser, 'alex');
  const sam = await account(browser, 'sam');
  const opA = await account(browser, 'op', 'operator');
  const boss = await account(browser, 'boss', 'owner');
  const accts = { pat: pat.u, alex: alex.u, sam: sam.u, operator: opA.u, owner: boss.u };
  fs.writeFileSync(path.join(TMP, 'accounts.json'), JSON.stringify(accts));
  const p = pat.p;

  // ---------------------------------------------------------------- R1: J1 lock, J2 partial
  const R1 = `dev-e2e4-${RUN}-a`;
  out.R1open = devOpen(R1, 4, 40);
  await p.waitForTimeout(3500);
  await p.goto(L.BASE + '/challenge'); await L.settle(p, 2500);
  for (let i = 0; i < 14 && (await L.total(p)) < 9; i++) await L.pickEnabled(p, 1);
  await p.locator('button[id*="\\"to\\":\\"review\\""]').first().click(); await L.settle(p, 2000);
  await p.locator('[id*="\\"t\\":\\"submit\\""]').first().click(); await L.settle(p, 2500);
  await p.locator('[id*="\\"t\\":\\"modalclose\\""]').first().click().catch(() => {}); await L.settle(p, 800);
  out.R1alex = cli('alex', ['dev-results', 'test-entry', '--round', R1, '--variant', '0']).trim().split('\n').pop();
  out.R1sam = cli('sam', ['dev-results', 'test-entry', '--round', R1, '--variant', '2']).trim().split('\n').pop();
  let t = await me(p);
  out.journeys.J1_confirmed = t.includes('Confirmed') && t.includes(R1);
  waitDeadline(R1); await p.waitForTimeout(3500);
  t = await me(p);
  out.journeys.J1_deadline_passed = t.includes('Deadline passed');
  out.R1lock = lock(R1); await p.waitForTimeout(3500);
  t = await me(p);
  out.journeys.J1_locked = t.includes('Locked') && !t.includes('Your result');
  await shot(p, 'j1_locked_desktop', '.ch-round-card');
  out.R1mode = cli('operator', ['dev-results', 'set-mode', '--round', R1, '--mode', 'synthetic']).trim().split('\n').pop();
  out.R1scenario = cli('operator', ['dev-results', 'scenario', '--round', R1, '--name', 'pending']).trim().split('\n').pop();
  untilVisible(R1);
  out.R1settle = cli('operator', ['settle', 'run', '--round', R1]).includes('version 1');
  t = await me(p);
  out.journeys.J2_partial = t.includes('Partly settled') && t.includes('Returned so far') && t.includes('Pending')
    && t.includes('Not decided yet') && /Correct\s*\d/.test(t);
  const w0 = writes();
  for (let i = 0; i < 3; i++) await me(p);
  out.journeys.reads_write_nothing = writes() === w0;
  await layouts(p, 'j2_partial', '.ch-res-summary');
  await shot(p, 'j2_partial_accumulators_desktop', '.ch-res-accs');

  // ---------------------------------------------------------------- R2: J3, J4, J7, J8, J9
  const R2 = `dev-e2e4-${RUN}-b`;
  out.R2open = devOpen(R2, 3, 40);
  for (const [who, v] of [['pat', '1'], ['alex', '0'], ['sam', '2']])
    out[`R2${who}`] = cli(who, ['dev-results', 'test-entry', '--round', R2, '--variant', v]).trim().split('\n').pop();
  waitDeadline(R2); out.R2lock = lock(R2);
  cli('operator', ['dev-results', 'set-mode', '--round', R2, '--mode', 'synthetic']);
  cli('operator', ['dev-results', 'scenario', '--round', R2, '--name', 'one-bucket-wins']);
  untilVisible(R2);
  const s2 = cli('operator', ['settle', 'run', '--round', R2]);
  out.R2settled = s2.includes('version 1');
  t = await me(p);
  out.journeys.J3_success_and_failure = t.includes('Successful') && t.includes('Unsuccessful');
  out.journeys.J4_provisional = t.includes('Provisional result') && t.includes('Not recovered')
    && t.includes('Pre-match estimates');
  await layouts(p, 'j4_provisional', '.ch-res-summary');
  await shot(p, 'j3_accumulators_desktop', '.ch-res-accs');
  const before = await p.locator('.ch-res-summary').innerText();
  // J7: correct a Foundation result so the participant's Foundation accumulator loses
  const fid = q(`select (s.legs->'legs'->0->>'fixture_id') from app.entry_settlements s join app.entries e on e.id=s.entry_id join app.rounds r on r.id=e.round_id join app.profiles pr on pr.user_id=e.user_id where r.code='${R2}' and pr.username='${pat.u.username}' order by s.revision desc limit 1`);
  const corr = cli('operator', ['results', 'correct', '--round', R2, '--fixture', fid, '--status', 'FT',
    '--home', '0', '--away', '0', '--reason', 'official report corrected the score',
    '--evidence', 'league match report'], R2);
  out.R2correction = corr.includes('Correction recorded');
  t = await me(p);
  const after = await p.locator('.ch-res-summary').innerText();
  out.journeys.J7_corrected = t.includes('Corrected') && before !== after;
  await layouts(p, 'j7_corrected', '.ch-res-summary');
  const status = cli('operator', ['settle', 'status', '--round', R2]);
  const asOf = isoOf(status, 'earliest finalisation');
  out.R2finalise = cli('operator', ['round', 'finalise', '--code', R2, '--as-of', asOf]).trim().split('\n').slice(-1)[0];
  t = await me(p);
  out.journeys.J8_final = t.includes('Final result') && t.includes('Final since');
  await shot(p, 'j8_final_desktop', '.ch-res-summary');
  const refused = cli('operator', ['round', 'reopen', '--code', R2, '--reason', 'review', '--evidence', 'note'], R2);
  out.journeys.J9_operator_refused = refused.includes('does not have permission');
  const reopened = cli('owner', ['round', 'reopen', '--code', R2, '--reason', 'league review of a result',
    '--evidence', 'league letter'], R2);
  out.R2reopen = reopened.includes('Round reopened');
  t = await me(p);
  out.journeys.J9_reopened = t.includes('reopened for review') && t.includes('Provisional result');
  await shot(p, 'j9_reopened_desktop', '.ch-res-summary');

  // ---------------------------------------------------------------- R3: J5 individual D-33 refund
  const R3 = `dev-e2e4-${RUN}-c`;
  out.R3open = devOpen(R3, 3, 40);
  for (const [who, v] of [['pat', '1'], ['alex', '0'], ['sam', '2']])
    out[`R3${who}`] = cli(who, ['dev-results', 'test-entry', '--round', R3, '--variant', v]).trim().split('\n').pop();
  waitDeadline(R3); lock(R3);
  cli('operator', ['dev-results', 'set-mode', '--round', R3, '--mode', 'synthetic']);
  cli('operator', ['dev-results', 'scenario', '--round', R3, '--name', 'entry-all-void']);
  untilVisible(R3);
  out.R3settle = cli('operator', ['settle', 'run', '--round', R3]).match(/round validity:\s+(\w+)/)?.[1];
  t = await me(p);
  out.journeys.J5_entry_refunded = t.includes('Void · refunded') && t.includes('Refund (not a recovery)')
    && !t.includes('Recovered 100+');
  await layouts(p, 'j5_entry_refunded', '.ch-res-summary');

  // ---------------------------------------------------------------- R4: J6 whole-round invalidation
  const R4 = `dev-e2e4-${RUN}-d`;
  out.R4open = devOpen(R4, 3, 20);
  for (const [who, v] of [['pat', '0'], ['alex', '1']])
    cli(who, ['dev-results', 'test-entry', '--round', R4, '--variant', v]);
  waitDeadline(R4); lock(R4);
  cli('operator', ['dev-results', 'set-mode', '--round', R4, '--mode', 'synthetic']);
  cli('operator', ['dev-results', 'scenario', '--round', R4, '--name', 'all-correct']);
  untilVisible(R4);
  cli('operator', ['settle', 'run', '--round', R4]);
  t = await me(p);
  out.journeys.J6_before_recovered = t.includes('Recovered 100+');
  out.R4invalidate = cli('operator', ['round', 'invalidate', '--code', R4, '--reason', 'floodlight failure across venues'], R4).includes('Round invalidated');
  t = await me(p);
  out.journeys.J6_round_void = t.includes('Round void') && t.includes('An operator invalidated this round')
    && t.includes('Refund (not a recovery)');
  await layouts(p, 'j6_round_void', '.ch-res-summary');

  // ---------------------------------------------------------------- R5: J10 new round, J12 analysis
  const R5 = `dev-e2e4-${RUN}-e`;
  out.R5open = devOpen(R5, 600, 20);
  await p.waitForTimeout(3500);
  t = await me(p);
  out.journeys.J10_previous_entry = t.includes('Most recent entry') && t.includes(R4) && t.includes(R5)
    && t.includes('Round void');
  await layouts(p, 'j10_previous_entry', '.ch-prev-entry');
  await p.goto(L.BASE + '/challenge'); await L.settle(p, 2500);
  for (let i = 0; i < 14 && (await L.total(p)) < 9; i++) await L.pickEnabled(p, 1);
  const wc = await p.locator('body').innerText();
  out.journeys.J12_analysis = ['Market', 'Diski 9', 'Your View'].every(x => wc.includes(x));
  await shot(p, 'j12_analysis_desktop', 'text=Portfolio analysis');

  // ---------------------------------------------------------------- J11: sign out, switch accounts
  const patPreds = await (async () => { await me(p); return p.locator('.ch-prev-entry').innerText(); })();
  await L.signOut(p);
  t = await me(p);
  out.journeys.J11_signed_out = !t.includes('Your result') && !t.includes(pat.u.username);
  await L.signIn(p, alex.u);
  t = await me(p);
  const alexPreds = await p.locator('.ch-prev-entry').innerText().catch(() => '');
  out.journeys.J11_switched = !t.includes(pat.u.username) && alexPreds !== patPreds && t.includes('Round void');
  out.journeys.no_emoji = !/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(t);
  out.decimals_ok = (t.match(/\d+\.\d+/g) || []).filter(x => /^\d+\.\d$/.test(x)).length === 0;
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { console.log(JSON.stringify(out, null, 1)); console.error(String(e).slice(0, 600)); process.exit(1); });
