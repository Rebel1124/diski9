// Stage G screenshots: header views (frozen versus latest context), Screener data
// context, Weekly Challenge frozen information and My Challenge, at desktop (1360),
// tablet (768) and mobile (390) widths; checks for page errors and horizontal overflow.
const L = require('./lib');
const SHOT = require('path').resolve(__dirname, '../../docs/screenshots/phase6c3') + '/';
const SIZES = [[1360, 900, 'desktop'], [768, 1024, 'tablet'], [390, 844, 'mobile']];
const out = { overflow: {}, texts: {} };
const errors = [];
async function at(p, sel) {
  const el = p.locator(sel).first();
  if (!(await el.count())) return false;
  await el.scrollIntoViewIfNeeded();
  await p.evaluate(() => window.scrollBy(0, -72));  // clear the sticky navigation bar
  await p.waitForTimeout(300);
  return true;
}
async function shoot(p, name, sel) {
  for (const [w, h, size] of SIZES) {
    await p.setViewportSize({ width: w, height: h }); await L.settle(p, 900);
    if (sel) await at(p, sel); else await p.evaluate(() => window.scrollTo(0, 0));
    await p.screenshot({ path: SHOT + `${name}_${size}.png` });
    out.overflow[`${name}_${size}`] = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  }
  await p.setViewportSize({ width: 1360, height: 900 });
}
(async () => {
  const browser = await L.chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const p = await ctx.newPage();
  p.on('pageerror', e => errors.push(String(e)));
  const u = await L.createUser('shots');
  await L.signIn(p, u);
  await p.goto(L.BASE + '/challenge'); await L.settle(p, 2500);
  const picked = await L.pickEnabled(p, 4);
  out.texts.strip = await L.text(p, '.ch-status-strip');
  await shoot(p, 'challenge_frozen_info', null);
  const fid = Number(picked[0].split('|')[0]);
  // Match Lab, frozen (opened from the Weekly Challenge universe)
  await L.openFixture(p, fid);
  out.texts.frozenTag = await L.text(p, '.lab-context');
  out.texts.dataContextFrozen = await L.text(p, '#data-context');
  await shoot(p, 'screener_weekly_context', '#data-context');
  const base = Number(await L.estimate(p, 'home'));
  await L.setEstimate(p, 'home', (base + 0.15).toFixed(2));
  await p.reload(); await L.settle(p, 3000);
  out.texts.frozenAfterReload = await L.estimate(p, 'home');
  out.texts.frozenBase = base.toFixed(2);
  await shoot(p, 'match_lab_frozen_header', '.lab-context');
  // Match Lab, latest data (All Upcoming Fixtures)
  await L.universe(p, 'All upcoming');
  out.texts.liveTag = await L.text(p, '.lab-context');
  out.texts.dataContextLive = await L.text(p, '#data-context');
  out.texts.liveStart = await L.estimate(p, 'home');
  await shoot(p, 'screener_all_upcoming_context', '#data-context');
  await shoot(p, 'match_lab_live_header', '.lab-context');
  // My Challenge, current round
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 2500);
  out.texts.me = (await L.text(p, '.ch-round-card')).slice(0, 200);
  await shoot(p, 'my_challenge_current', null);
  out.pageErrors = errors;
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { out.pageErrors = errors; console.log(JSON.stringify(out, null, 1)); console.error(String(e).slice(0, 400)); process.exit(1); });
