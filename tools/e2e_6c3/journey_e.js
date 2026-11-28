const L = require('./lib');
const { execSync } = require('child_process');
const SHOT = require('path').resolve(__dirname, '../../docs/screenshots/phase6c3') + '/';
const out = {};
function cli(args) {
  const owner = JSON.parse(require('fs').readFileSync(require('path').resolve(__dirname, 'owner.json'), 'utf8')).email;
  return execSync(`cd ${require('path').resolve(__dirname, '../..')} && set -a && . tmp/dev/serve.env && set +a && ` +
    `DISKI9_APP_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/diski9_e2e ` +
    `uv run diski9 round ${args.replace('OWNER', owner)} 2>&1 | grep -v UV_`, { shell: '/bin/bash' }).toString();
}
async function confirmFull(browser, tag) {
  const u = await L.createUser(tag);
  const c = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const p = await c.newPage();
  await L.signIn(p, u);
  await p.goto(L.BASE + '/'); await L.settle(p, 2500);
  for (let i = 0; i < 12 && (await L.total(p)) < 9; i++) await L.pickEnabled(p, 1);
  await p.locator('button[id*="\\"to\\":\\"review\\""]').first().click(); await L.settle(p, 2000);
  await p.locator('[id*="\\"t\\":\\"submit\\""]').first().click(); await L.settle(p, 2500);
  await p.locator('[id*="\\"t\\":\\"modalclose\\""]').first().click().catch(() => {}); await L.settle(p, 800);
  return p;
}
(async () => {
  out.open = cli('dev-open --by-email OWNER --deadline-minutes 9 --code dev-lock-e2e7');
  await new Promise(r => setTimeout(r, 4000));
  const browser = await L.chromium.launch();
  const pages = [];
  for (let i = 0; i < 5; i++) pages.push(await confirmFull(browser, 'je' + i));
  const p = pages[0];
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2000);
  out.beforeDeadline = await L.text(p, '.ch-round-card');
  out.lockEarly = cli('lock --code dev-lock-e2e7');
  // wait for the deadline (database clock)
  execSync(`until [ "$(psql -h 127.0.0.1 -p 5433 -U postgres -d diski9_e2e -Atc "select now() >= deadline_at from app.rounds where code='dev-lock-e2e7'")" = t ]; do sleep 2; done`, { shell: '/bin/bash' });
  await p.waitForTimeout(3500);  // the page's round cache is refreshed every few seconds
  await p.goto(L.BASE + '/'); await L.settle(p, 2500);
  out.afterDeadlineStatus = await L.text(p, '.ch-ribbon');
  await p.screenshot({ path: SHOT + 'deadline_passed_desktop.png' });
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2000);
  out.withdrawButtonAfterDeadline = await p.locator('[id*="\\"t\\":\\"askwithdraw\\""]').count();
  out.lock = cli('lock --code dev-lock-e2e7');
  out.lockAgain = cli('lock --code dev-lock-e2e7');
  await p.waitForTimeout(3500);
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2500);
  out.meLocked = await L.text(p, '.ch-round-card');
  await p.screenshot({ path: SHOT + 'my_challenge_locked_desktop.png' });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { console.log(JSON.stringify(out, null, 1)); console.error(String(e).slice(0, 400)); process.exit(1); });
