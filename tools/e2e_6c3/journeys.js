const L = require('./lib');
const SHOT = require('path').resolve(__dirname, '../../docs/screenshots/phase6c3') + '/';
const VP = { width: 1360, height: 900 };
async function page(browser, vp = VP) {
  const c = await browser.newContext({ viewport: vp, deviceScaleFactor: 2 });
  const p = await c.newPage(); p._errors = []; p.on('pageerror', e => p._errors.push(String(e)));
  return p;
}
async function toReview(p) {
  for (let i = 0; i < 6 && (await L.total(p)) < 9; i++) { await L.pickEnabled(p, 1); }
  await p.locator('button[id*="\\"to\\":\\"review\\""]').first().click(); await L.settle(p, 2500);
}
async function submit(p) {
  await p.locator('[id*="\\"t\\":\\"submit\\""]').first().click(); await L.settle(p, 3000);
}
const out = {};
(async () => {
  const browser = await L.chromium.launch();
  // ---------------- Journey B: cross-device conflict
  const ub = await L.createUser('jb');
  const d1 = await page(browser); await L.signIn(d1, ub);
  await d1.goto(L.BASE + '/'); await L.settle(d1, 2500);
  await L.pickEnabled(d1, 2);
  const d2 = await page(browser, { width: 390, height: 844 }); await L.signIn(d2, ub, false);
  await d2.goto(L.BASE + '/'); await L.settle(d2, 2500);
  out.B_device2Sees = (await L.selected(d2)).length;
  await L.pickLast(d2);
  await d2.screenshot({ path: SHOT + 'builder_mobile_device2.png' });
  await L.pickEnabled(d1, 1);  // stale device
  out.B_conflictFlash = await L.text(d1, '.ch-flash');
  await d1.screenshot({ path: SHOT + 'builder_conflict_desktop.png' });
  await d1.locator('button[id*="\\"t\\":\\"reload\\""]').first().click(); await L.settle(d1, 2000);
  out.B_afterReload = JSON.stringify(await L.selected(d1)) === JSON.stringify(await L.selected(d2));
  // ---------------- Journey C: confirm, edit, replace, withdraw, re-enter
  const uc = await L.createUser('jc');
  const c1 = await page(browser); await L.signIn(c1, uc);
  await c1.goto(L.BASE + '/'); await L.settle(c1, 2500);
  const nine = await L.pickEnabled(c1, 9);
  await toReview(c1);
  out.C_reviewButton = await L.text(c1, '[id*="\\"t\\":\\"submit\\""]');
  await c1.screenshot({ path: SHOT + 'review_desktop.png' });
  await submit(c1);
  out.C_modal = await L.text(c1, '.ch-modal');
  await c1.screenshot({ path: SHOT + 'confirmed_modal_desktop.png' });
  await c1.locator('[id*="\\"t\\":\\"modalclose\\""]').first().click(); await L.settle(c1, 1200);
  await c1.goto(L.BASE + '/challenge/me'); await L.settle(c1, 2500);
  out.C_meConfirmed = await L.text(c1, '.ch-round-card');
  // edit the draft: remove one pick
  await c1.goto(L.BASE + '/'); await L.settle(c1, 2500);
  await c1.locator('[id*="\\"to\\":\\"build\\""]').first().click().catch(() => {}); await L.settle(c1, 1500);
  await c1.locator('button.is-selected[id*="\\"t\\":\\"pick\\""]').first().click(); await L.settle(c1, 1500);
  await c1.goto(L.BASE + '/challenge/me'); await L.settle(c1, 2500);
  out.C_meDraftDiffers = await L.text(c1, '.ch-round-card');
  await c1.screenshot({ path: SHOT + 'my_challenge_changes_desktop.png' });
  // complete again with a different pick and replace
  await c1.goto(L.BASE + '/'); await L.settle(c1, 2500);
  await L.pickLast(c1);
  await toReview(c1);
  out.C_replaceButton = await L.text(c1, '[id*="\\"t\\":\\"submit\\""]');
  await submit(c1);
  out.C_replacedFlash = await L.text(c1, '.ch-flash');
  // withdraw from My Challenge
  await c1.goto(L.BASE + '/challenge/me'); await L.settle(c1, 2500);
  await c1.locator('[id*="\\"t\\":\\"askwithdraw\\""]').first().click(); await L.settle(c1, 1200);
  await c1.screenshot({ path: SHOT + 'withdraw_dialog_desktop.png' });
  await c1.locator('[id*="\\"t\\":\\"confirmwithdraw\\""]').first().click(); await L.settle(c1, 2500);
  out.C_meWithdrawn = await L.text(c1, '.ch-round-card');
  // re-enter
  await c1.goto(L.BASE + '/'); await L.settle(c1, 2500);
  await toReview(c1);
  await submit(c1);
  await c1.goto(L.BASE + '/challenge/me'); await L.settle(c1, 2500);
  out.C_meReentered = await L.text(c1, '.ch-round-card');
  await c1.screenshot({ path: SHOT + 'my_challenge_confirmed_desktop.png' });
  out.C_user = uc.username;
  // ---------------- Journey D: guest adoption
  const ud = await L.createUser('jd');
  const g = await page(browser);
  await g.goto(L.BASE + '/'); await L.settle(g, 2500);
  out.D_guestSave = await L.text(g, '.ch-save-state');
  const gp = await L.pickEnabled(g, 3);
  const gfid = Number(gp[0].split('|')[0]);
  await L.openFixture(g, gfid);
  const base = await L.estimate(g, 'home');
  await L.setEstimate(g, 'home', (Number(base) + 0.3).toFixed(2));
  await g.goto(L.BASE + '/'); await L.settle(g, 1500);
  await toReview(g).catch(() => {});
  await L.signIn(g, ud);
  await g.goto(L.BASE + '/'); await L.settle(g, 2000);
  out.D_dialog = await L.text(g, '#d9-guest-choice');
  await g.screenshot({ path: SHOT + 'guest_choice_desktop.png' });
  await Promise.all([g.waitForNavigation(), g.click('#d9-guest-keep')]); await L.settle(g, 3000);
  out.D_panel = await L.text(g, '.adopt-panel');
  await g.screenshot({ path: SHOT + 'adoption_review_desktop.png' });
  await g.locator('button[id*="\\"t\\":\\"adopt-save\\""]').click(); await L.settle(g, 3000);
  out.D_flash = await L.text(g, '.ch-flash');
  out.D_saved = (await L.selected(g)).length;
  const g2 = await page(browser); await L.signIn(g2, ud, false);
  await g2.goto(L.BASE + '/'); await L.settle(g2, 2500);
  out.D_otherDevice = (await L.selected(g2)).length;
  await L.openFixture(g2, gfid);
  out.D_frozenAdopted = (await L.estimate(g2, 'home')) === (Number(base) + 0.3).toFixed(2);
  // with existing account work: conflict, keep account's
  const ud2 = await L.createUser('jd2');
  const h = await page(browser); await L.signIn(h, ud2);
  await h.goto(L.BASE + '/'); await L.settle(h, 2500);
  const mine = await L.pickEnabled(h, 2);
  await L.signOut(h);
  await h.goto(L.BASE + '/'); await L.settle(h, 2500);
  await L.pickEnabled(h, 4);
  await L.signIn(h, ud2, false);
  await h.goto(L.BASE + '/'); await L.settle(h, 2000);
  await Promise.all([h.waitForNavigation(), h.click('#d9-guest-keep')]); await L.settle(h, 3000);
  out.D2_panel = await L.text(h, '.adopt-panel');
  await h.screenshot({ path: SHOT + 'adoption_conflict_desktop.png' });
  await h.locator('button[id*="\\"t\\":\\"adopt-save\\""]').click(); await L.settle(h, 3000);
  out.D2_kept = JSON.stringify(await L.selected(h)) === JSON.stringify(mine.sort());
  out.D2_flash = await L.text(h, '.ch-flash');
  // ---------------- Journey F: account isolation in one tab
  const ua = await L.createUser('jfa'); const ub2 = await L.createUser('jfb');
  const f = await page(browser);
  await L.signIn(f, ua);
  await f.goto(L.BASE + '/'); await L.settle(f, 2500);
  const ap = await L.pickEnabled(f, 3);
  const ffid = Number(ap[0].split('|')[0]);
  await L.openFixture(f, ffid);
  const fb = await L.estimate(f, 'home');
  await L.setEstimate(f, 'home', (Number(fb) + 0.25).toFixed(2));
  await L.signOut(f);
  await L.signIn(f, ub2);
  await f.goto(L.BASE + '/'); await L.settle(f, 2500);
  out.F_bSees = (await L.selected(f)).length;
  await L.openFixture(f, ffid);
  out.F_bEstimate = (await L.estimate(f, 'home')) === fb;
  await L.signOut(f);
  await L.signIn(f, ua, false);
  await f.goto(L.BASE + '/'); await L.settle(f, 2500);
  out.F_aRestored = (await L.selected(f)).length;
  await L.openFixture(f, ffid);
  out.F_aEstimate = (await L.estimate(f, 'home')) === (Number(fb) + 0.25).toFixed(2);
  out.errors = [d1, d2, c1, g, g2, h, f].flatMap(p => p._errors);
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { console.log(JSON.stringify(out, null, 1)); console.error(String(e).slice(0, 300)); process.exit(1); });
