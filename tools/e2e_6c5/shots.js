// Phase 6C.5 Stage E: real-browser checks and screenshots of Leaderboards and
// My Challenge History against the seeded showcase database (seed.py), the real
// app (port 8052) and the local Supabase Auth harness. Local development only.
//
//   NODE_PATH=$(npm root -g) node tools/e2e_6c5/shots.js
//
// For each width (desktop 1360, tablet 768, mobile 390) it checks: no page-wide
// horizontal overflow, no console or page errors, no e-mail address or UUID in the
// page text or element ids, and that page loads write nothing (row counts).
// Screenshots go to docs/screenshots/phase6c5/.
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { chromium, BASE, ROOT, signIn, settle, accounts } = require('./lib');

const OUT = path.join(ROOT, 'docs/screenshots/phase6c5');
fs.mkdirSync(OUT, { recursive: true });
const ROUNDS = JSON.parse(fs.readFileSync(path.join(ROOT, 'tmp/e2e_6c5/rounds.json'), 'utf8'));
const R = (n) => ROUNDS[n - 1];
const WIDTHS = { desktop: [1360, 900], tablet: [768, 1000], mobile: [390, 844] };
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;
const results = [];

function counts() {
  const sql = "select (select count(*) from app.score_sets)||','||(select count(*) from app.championship_versions)||','||(select count(*) from app.audit_log)";
  return execSync(`psql -h 127.0.0.1 -p 5433 -U postgres -d diski9_e2e_6c5 -Atc "${sql}"`).toString().trim();
}
async function choose(page, t, label) {
  await page.locator(`[id*='"t":"${t}"']`).first().click();
  await page.getByRole('option', { name: label, exact: false }).first().click();
  await settle(page, 1500);
}
async function check(page, name) {
  const info = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    text: document.body.innerText,
    ids: Array.from(document.querySelectorAll('[id]')).map(e => e.id).join(' '),
  }));
  const problems = [];
  if (info.overflow > 1) problems.push(`horizontal overflow ${info.overflow}px`);
  if (/@/.test(info.text)) problems.push('an e-mail address in the page text');
  if (UUID.test(info.text) || UUID.test(info.ids)) problems.push('a UUID in the page');
  results.push({ name, problems });
  return info.text;
}
async function shot(page, name) {
  // full page on desktop; tablet and phone captures keep the top 2400 CSS pixels (header,
  // summary, banners and the first rows), so long card lists do not bloat the repository
  const width = page.viewportSize().width;
  if (width >= 1000) {
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
    return;
  }
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true,
                          clip: { x: 0, y: 0, width, height: Math.min(height, 2400) } });
}

(async () => {
  const acc = accounts();
  const browser = await chromium.launch();
  const before = counts();
  for (const [wname, [w, h]] of Object.entries(WIDTHS)) {
    // ---------------- guest
    const gctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
    const g = await gctx.newPage();
    const errors = [];
    g.on('pageerror', e => errors.push(e.message));
    g.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await g.goto(BASE + '/leaderboards'); await settle(g, 2500);
    await choose(g, 'lb-stream', 'Development');
    let txt = await check(g, `${wname} guest weekly`);
    if (!txt.includes('Sign in to see your position')) results.push({ name: `${wname} guest`, problems: ['no sign-in prompt'] });
    await shot(g, `${wname}_guest_weekly`);
    await gctx.close();

    // ---------------- signed in
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await signIn(page, acc.you);
    await page.goto(BASE + '/leaderboards'); await settle(page, 2500);
    await choose(page, 'lb-stream', 'Development');
    await check(page, `${wname} weekly provisional`);
    await shot(page, `${wname}_weekly_provisional`);
    const weekly = [['final', R(13)], ['corrected', R(3)], ['under_review', R(7)], ['practice', R(4)],
                    ['void', R(5)], ['refunded', R(8)]];
    for (const [label, code] of weekly) {
      if (wname !== 'desktop' && !['final', 'under_review'].includes(label)) continue;
      await choose(page, 'lb-round', code);
      await check(page, `${wname} weekly ${label}`);
      await shot(page, `${wname}_weekly_${label}`);
    }
    // pagination: page 2 of the final round
    await choose(page, 'lb-round', R(13));
    const next = page.locator(`[id*='"t":"lbw-goto"']`, { hasText: 'Next' }).first();
    if (await next.count()) { await next.click(); await settle(page, 1500); }
    txt = await check(page, `${wname} weekly page 2`);
    if (!txt.includes('Showing 51')) results.push({ name: `${wname} pagination`, problems: ['page 2 not shown'] });
    if (wname === 'desktop') await shot(page, `${wname}_weekly_page2`);

    // championship tab
    await page.locator(`[id*='"t":"lb-tab"'] label`, { hasText: 'Championship' }).click();
    await settle(page, 2000);
    await check(page, `${wname} championship current`);
    await shot(page, `${wname}_championship_in_progress`);
    // the first option is the current one; pick the historical (non-suffixed) one exactly
    await page.locator(`[id*='"t":"lb-round"']`).first().click();
    await page.getByRole('option').filter({ hasText: /^\s*Championship Nov-26\s*$/ }).first().click();
    await settle(page, 1500);
    txt = await check(page, `${wname} championship historical`);
    for (const want of ['Joint champions', 'corrected after completion', 'Under review']) {
      if (!txt.toLowerCase().includes(want.toLowerCase())) results.push({ name: `${wname} historical championship`, problems: [`missing "${want}"`] });
    }
    await shot(page, `${wname}_championship_completed_d30a_review`);

    // My Challenge: Current and History
    await page.goto(BASE + '/challenge/me'); await settle(page, 2500);
    await check(page, `${wname} my challenge current`);
    await shot(page, `${wname}_my_challenge_current`);
    await page.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' }).click();
    await settle(page, 2500);
    await choose(page, 'me-hstream', 'Development');
    txt = await check(page, `${wname} history`);
    if (!txt.includes('Your statistics')) results.push({ name: `${wname} history`, problems: ['no statistics'] });
    await shot(page, `${wname}_history`);
    if (wname === 'desktop') {
      await page.locator(`[id*='"t":"me-hscope"']`).first().click();
      await page.getByRole('option').filter({ hasText: /^\s*Championship Nov-26\s*$/ }).first().click();
      await settle(page, 2000);
      await check(page, `${wname} history championship scope`);
      await shot(page, `${wname}_history_championship_scope`);
    }
    // drill-down of the reopened round (current settlement next to the last published result)
    const open = page.locator(`[id*='"i":"${R(7)}"'][id*='"t":"hist-open"']`).first();
    if (await open.count()) {
      await open.click(); await settle(page, 2500);
      txt = await check(page, `${wname} history detail`);
      if (!txt.includes('Last published official result')) results.push({ name: `${wname} detail`, problems: ['no last-published label'] });
      const box = await page.locator('.me-hist-detail').first().boundingBox();
      const vw = page.viewportSize().width;
      await page.screenshot({ path: path.join(OUT, `${wname}_history_detail_under_review.png`), fullPage: true,
                              clip: { x: 0, y: Math.max(0, box.y - 20), width: vw, height: Math.min(box.height + 40, 2400) } });
    } else {
      results.push({ name: `${wname} detail`, problems: ['reopened round not on the first history page'] });
    }
    if (errors.length) results.push({ name: `${wname} console`, problems: errors.slice(0, 5) });
    await ctx.close();
  }
  const after = counts();
  if (before !== after) results.push({ name: 'read-only', problems: [`rows changed ${before} -> ${after}`] });
  await browser.close();
  const bad = results.filter(r => r.problems.length);
  console.log(`${results.length} checks, ${bad.length} with problems`);
  for (const r of bad) console.log(' -', r.name, ':', r.problems.join('; '));
  process.exit(bad.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
