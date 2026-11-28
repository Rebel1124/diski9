// Journey G (live versus frozen contexts) and Journey A (returning participant).
const L = require('./lib');
const SHOT = require('path').resolve(__dirname, '../../docs/screenshots/phase6c3') + '/';
(async () => {
  const browser = await L.chromium.launch();
  const out = {};
  const u = await L.createUser('jg');
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 2 });
  const p = await ctx.newPage();
  const errors = []; p.on('pageerror', e => errors.push(String(e)));
  await L.signIn(p, u);
  // Journey A: partial portfolio
  await p.goto(L.BASE + '/'); await L.settle(p, 2500);
  out.A_picked = await L.pickEnabled(p, 4);
  out.A_save = await L.text(p, '.ch-save-state');
  await p.screenshot({ path: SHOT + 'builder_saved_desktop.png' });
  const fid = Number(out.A_picked[0].split('|')[0]);
  // Journey G: frozen context
  await L.openFixture(p, fid);
  out.G_frozenTag = await L.text(p, '.lab-context');
  out.G_frozenBase = await L.estimate(p, 'home');
  await L.setEstimate(p, 'home', (Number(out.G_frozenBase) + 0.20).toFixed(2));
  out.G_frozenAfter = await L.estimate(p, 'home');
  out.G_dataContextFrozen = await L.text(p, '.data-context');
  await p.screenshot({ path: SHOT + 'match_lab_frozen_desktop.png' });
  // navigate away and open the live context of the same fixture
  await p.goto(L.BASE + '/challenge/me'); await L.settle(p, 1500);
  await L.openFixture(p, fid);
  await L.universe(p, 'All upcoming');
  out.G_liveTag = await L.text(p, '.lab-context');
  out.G_liveStart = await L.estimate(p, 'home');
  await L.setEstimate(p, 'home', (Number(out.G_liveStart) + 0.10).toFixed(2));
  out.G_liveAfter = await L.estimate(p, 'home');
  out.G_dataContextLive = await L.text(p, '.data-context');
  await p.screenshot({ path: SHOT + 'match_lab_live_desktop.png' });
  // back to the frozen context: original adjustment intact
  await L.universe(p, 'Weekly Challenge');
  out.G_frozenAgain = await L.estimate(p, 'home');
  await L.universe(p, 'All upcoming');
  out.G_liveAgain = await L.estimate(p, 'home');
  // reset the live context only
  await p.locator('#lab-reset').click(); await L.settle(p, 1500);
  out.G_liveReset = await L.estimate(p, 'home');
  await L.universe(p, 'Weekly Challenge');
  out.G_frozenAfterLiveReset = await L.estimate(p, 'home');
  // sign out and back in (Journey A step 7 too)
  await L.signOut(p);
  await L.signIn(p, u, false);
  await p.goto(L.BASE + '/'); await L.settle(p, 2500);
  out.A_afterSignIn = await L.selected(p);
  await L.openFixture(p, fid);
  out.G_frozenAfterSignIn = await L.estimate(p, 'home');
  await L.universe(p, 'All upcoming');
  out.G_liveAfterSignIn = await L.estimate(p, 'home');
  out.errors = errors;
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
