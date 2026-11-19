// Journey H (Stage G): most recent locked entry beside another open round.
// A participant confirms nine predictions in a short round; after its deadline the
// mirrored round (deadline ahead) becomes current and My Challenge shows the entry
// as "Most recent locked entry" (first "Deadline passed", then "Locked"), read-only,
// unchanged by current-round draft changes, invisible to another account.
const L = require('./lib');
const { execSync } = require('child_process');
const SHOT = require('path').resolve(__dirname, '../../docs/screenshots/phase6c3') + '/';
const CODE = process.env.CODE || 'dev-lock-e2e8';
const out = {};
const errors = [];
function cli(args) {
  const owner = JSON.parse(require('fs').readFileSync(require('path').resolve(__dirname, 'owner.json'), 'utf8')).email;
  return execSync(`cd ${require('path').resolve(__dirname, '../..')} && set -a && . tmp/dev/serve.env && set +a && ` +
    `DISKI9_APP_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/diski9_e2e ` +
    `uv run diski9 round ${args.replace('OWNER', owner)} 2>&1 | grep -v UV_`, { shell: '/bin/bash' }).toString();
}
const card = '.ch-locked-entry';
async function cardText(p) { return (await p.locator(card).count()) ? p.locator(card).first().innerText() : ''; }
(async () => {
  out.open = cli(`dev-open --by-email OWNER --deadline-minutes 4 --code ${CODE}`).trim().split('\n').pop();
  await new Promise(r => setTimeout(r, 4000));
  const browser = await L.chromium.launch();
  const u = await L.createUser('jh');
  const c = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const p = await c.newPage();
  p.on('pageerror', e => errors.push(String(e)));
  await L.signIn(p, u);
  await p.goto(L.BASE + '/challenge'); await L.settle(p, 2500);
  out.roundShown = (await L.text(p, '.ch-status-strip')).slice(0, 160);
  for (let i = 0; i < 12 && (await L.total(p)) < 9; i++) await L.pickEnabled(p, 1);
  await p.locator('button[id*="\\"to\\":\\"review\\""]').first().click(); await L.settle(p, 2000);
  await p.locator('[id*="\\"t\\":\\"submit\\""]').first().click(); await L.settle(p, 2500);
  await p.locator('[id*="\\"t\\":\\"modalclose\\""]').first().click().catch(() => {}); await L.settle(p, 800);
  const stored = execSync(`psql -h 127.0.0.1 -p 5433 -U postgres -d diski9_e2e -Atc "select ss.consensus_odds from app.rounds r join app.entries e on e.round_id=r.id join app.submissions s on s.id=e.current_submission_id join app.submission_selections ss on ss.submission_id=s.id join app.profiles pr on pr.user_id=e.user_id where r.code='${CODE}' and pr.username='${u.username}' order by ss.position"`).toString().trim().split('\n');
  out.storedOdds = stored;
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2000);
  out.beforeDeadlineCard = await p.locator(card).count();  // current round is the short round itself
  execSync(`until [ "$(psql -h 127.0.0.1 -p 5433 -U postgres -d diski9_e2e -Atc "select now() >= deadline_at from app.rounds where code='${CODE}'")" = t ]; do sleep 2; done`, { shell: '/bin/bash' });
  await p.waitForTimeout(3500);
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2500);
  out.currentAfterDeadline = (await L.text(p, '.ch-round-card')).slice(0, 200);
  out.pendingCard = await cardText(p);
  await p.locator(card).first().scrollIntoViewIfNeeded(); await p.evaluate(() => window.scrollBy(0, -72));
  await p.screenshot({ path: SHOT + 'locked_entry_pending_desktop.png', fullPage: false });
  out.lock = cli(`lock --code ${CODE}`).trim().split('\n').pop();
  await p.waitForTimeout(3500);
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2500);
  out.lockedCard = await cardText(p);
  await p.locator(`${card} summary`).click(); await L.settle(p, 600);
  const expanded = await cardText(p);
  out.oddsShown = stored.every(o => expanded.includes(o));
  out.buttonsInCard = await p.locator(`${card} button`).count();
  await p.locator(card).first().scrollIntoViewIfNeeded(); await p.evaluate(() => window.scrollBy(0, -72));
  await p.screenshot({ path: SHOT + 'locked_entry_desktop.png' });
  // current-round draft change must not alter the locked card
  await p.goto(L.BASE + '/challenge'); await L.settle(p, 2500);
  out.currentRound = (await L.text(p, '.ch-status-strip')).slice(0, 160);
  await L.pickEnabled(p, 2);
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2500);
  await p.locator(`${card} summary`).click(); await L.settle(p, 600);
  out.unchangedAfterDraft = (await cardText(p)) === expanded;
  out.mainCardAfterDraft = (await L.text(p, '.ch-round-card')).slice(0, 160);
  for (const [w, h, name] of [[768, 1024, 'tablet'], [390, 844, 'mobile']]) {
    await p.setViewportSize({ width: w, height: h }); await L.settle(p, 900);
    await p.locator(card).first().scrollIntoViewIfNeeded(); await p.evaluate(() => window.scrollBy(0, -72));
    await p.screenshot({ path: SHOT + `locked_entry_${name}.png` });
    out[`overflow_${name}`] = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  }
  // another account sees nothing of it
  await L.signOut(p);
  await p.setViewportSize({ width: 1360, height: 900 });
  const v = await L.createUser('jh2');
  await L.signIn(p, v);
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2500);
  out.otherAccountCard = await p.locator(card).count();
  out.otherAccountSeesCode = (await p.locator('body').innerText()).includes(CODE);
  out.pageErrors = errors;
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { out.pageErrors = errors; console.log(JSON.stringify(out, null, 1)); console.error(String(e).slice(0, 400)); process.exit(1); });
