// Phase 6C.5 Stage E owner-requested refinements: real-browser checks and screenshots
// of Leaderboards and My Challenge against the seeded showcase database (seed.py), the
// real app (port 8052) and the local Supabase Auth harness. Local development only.
//
//   NODE_PATH=$(npm root -g) node tools/e2e_6c5/refined.js
//
// Widths: desktop 1360, tablet 768 and phones 320, 360, 390 and 430. On every page it
// checks, element by element (not only the page's scroll width):
//   - no element of the navigation, controls, headers, cards, tables, podium, statistics
//     cards, charts, notices or pager extends beyond the viewport;
//   - no text overflows its own box (scrollWidth > clientWidth) and no card cell sits
//     outside its card or overlaps another cell of the same card;
//   - interactive controls are at least 32 px tall;
//   - no console or page errors, no e-mail address or UUID in the page, and page loads
//     write nothing (row counts).
// A stress pass then injects a 24-character name and seven-figure values into the
// rendered cards and repeats the element checks. Screenshots go to
// docs/screenshots/phase6c5/refined/.
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { chromium, BASE, ROOT, signIn, settle, accounts } = require('./lib');

const OUT = path.join(ROOT, 'docs/screenshots/phase6c5/refined');
fs.mkdirSync(OUT, { recursive: true });
const ROUNDS = JSON.parse(fs.readFileSync(path.join(ROOT, 'tmp/e2e_6c5/rounds.json'), 'utf8'));
const R = (n) => ROUNDS[n - 1];
const WIDTHS = { desktop: 1360, tablet: 768, m320: 320, m360: 360, m390: 390, m430: 430 };
const SHOTS = new Set(['desktop', 'tablet', 'm390', 'm320']);
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;
const LONG = 'Mmabatho Mathebula-Mokoe';  // 24 characters, the username maximum (D-05)
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
async function chooseExact(page, t, re) {
  await page.locator(`[id*='"t":"${t}"']`).first().click();
  await page.getByRole('option').filter({ hasText: re }).first().click();
  await settle(page, 1500);
}

// element-level layout audit, run inside the page
function audit() {
  const vw = document.documentElement.clientWidth;
  const out = [];
  const name = (el) => (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : el.tagName.toLowerCase())
    + ' "' + (el.innerText || '').trim().slice(0, 24).replace(/\s+/g, ' ') + '"';
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const SEL = ['.site-nav a', '.site-nav summary', '.acct-name', '.ch-page h1', '.ch-h2', '.lb-top label',
    '.lb-top .dash-dropdown', '.lb-head-line > *', '.lb-head-champ', '.lb-progress', '.lb-champion',
    '.ch-you', '.ch-you > *', '.ch-pod', '.ch-pod > *', '.ch-pod-name > *', '.ch-table th', '.ch-table td',
    '.me-stat', '.me-stat-head', '.me-stat-val', '.me-stat-sub', '.me-chart-card', '.me-chart-locked',
    '.ch-ribbon', '.lb-pager', '.lb-pager button', '.me-standings li', '.me-hist-detail', '.ch-pill',
    '.me-method summary', '.lb-rules summary', '.js-plotly-plot', '.me-round', '.lb-code'].join(',');
  const scrolling = new Set();
  for (const wrap of document.querySelectorAll('.ch-table-wrap')) {
    if (visible(wrap) && wrap.scrollWidth > wrap.clientWidth + 1) {
      scrolling.add(wrap); out.push('table scrolls sideways: ' + name(wrap.querySelector('table')));
    }
  }
  for (const el of document.querySelectorAll(SEL)) {
    if (!visible(el) || scrolling.has(el.closest('.ch-table-wrap'))) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) out.push('outside viewport: ' + name(el));
    if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 2 && !el.matches('.js-plotly-plot, .dash-dropdown'))
      out.push('text overflows its box: ' + name(el));
  }
  // card cells: inside their card and not overlapping each other
  for (const tr of document.querySelectorAll('.ch-table.lb-cards tr')) {
    if (getComputedStyle(tr).display !== 'grid') continue;
    const box = tr.getBoundingClientRect();
    const cells = [...tr.children].filter(visible);
    for (const td of cells) {
      const r = td.getBoundingClientRect();
      if (r.left < box.left - 1 || r.right > box.right + 1 || r.bottom > box.bottom + 1) out.push('cell outside its card: ' + name(td));
    }
    for (let i = 0; i < cells.length; i++) for (let j = i + 1; j < cells.length; j++) {
      const a = cells[i].getBoundingClientRect(), b = cells[j].getBoundingClientRect();
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 1 && h > 1) out.push('cells overlap: ' + name(cells[i]) + ' / ' + name(cells[j]));
    }
  }
  for (const card of document.querySelectorAll('.me-stat, .ch-pod')) {
    const box = card.getBoundingClientRect();
    for (const c of card.querySelectorAll('*')) {
      if (!visible(c) || c.closest('svg')) continue;
      const r = c.getBoundingClientRect();
      if (r.right > box.right + 1 || r.left < box.left - 1) out.push('outside its card: ' + name(c));
    }
  }
  // touch targets
  for (const el of document.querySelectorAll('.site-nav a, .site-nav summary, .lb-pager button, .ch-page button, .segmented label, .dash-dropdown')) {
    if (!visible(el)) continue;
    const h = el.getBoundingClientRect().height;
    if (h < 31.5) out.push(`touch target ${Math.round(h)}px: ` + name(el));
  }
  return [...new Set(out)];
}

async function check(page, label, stress = false) {
  const info = await page.evaluate(() => ({ text: document.body.innerText,
    ids: Array.from(document.querySelectorAll('[id]')).map(e => e.id).join(' ') }));
  const problems = await page.evaluate(audit);
  if (/@/.test(info.text)) problems.push('an e-mail address in the page text');
  if (UUID.test(info.text) || UUID.test(info.ids)) problems.push('a UUID in the page');
  results.push({ name: label + (stress ? ' [stress]' : ''), problems });
  return info.text;
}
async function stress(page, label) {
  // a 24-character name and seven-figure values in the rendered cards, then re-audit
  await page.evaluate((LONG) => {
    document.querySelectorAll('.lb-name').forEach((e, i) => { if (i < 6) e.textContent = LONG; });
    document.querySelectorAll('.ch-pod-name strong').forEach((e) => { e.textContent = LONG; });
    document.querySelectorAll('.ch-pod-val').forEach((e) => { e.textContent = '1,234,567.89'; });
    document.querySelectorAll('.me-stat-val').forEach((e, i) => { e.textContent = ['1,234 of 1,240', '1,234', '1,234', '1,240,000.00', '9,876,543.21', '+8,636,543.21'][i] || e.textContent; });
    // points at their real maximum: 150 a week, 1,500 for a ten-round championship
    document.querySelectorAll('.ch-table.lb td.lb-pts').forEach((e, i) => { if (i < 6) e.textContent = document.querySelector('.lb-champ') ? '1,500' : '150'; });
    document.querySelectorAll('.ch-table.lb td.num.strong:not(.lb-pts)').forEach((e, i) => { if (i < 6) e.textContent = '1,234,567.89'; });
  }, LONG);
  await page.waitForTimeout(200);
  await check(page, label, true);
}
async function shot(page, name, full = true) {
  const width = page.viewportSize().width;
  if (width >= 1000 || !full) { await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true }); return; }
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true,
                          clip: { x: 0, y: 0, width, height: Math.min(height, 2400) } });
}
async function shotOf(page, selector, name, pad = 12) {
  const el = page.locator(selector).first();
  if (!(await el.count())) { results.push({ name, problems: [`nothing to capture for ${selector}`] }); return; }
  await el.scrollIntoViewIfNeeded();
  const box = await el.boundingBox();
  const vw = page.viewportSize().width;
  const y = await page.evaluate(() => window.scrollY);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true,
    clip: { x: Math.max(0, box.x - pad), y: Math.max(0, box.y + y - pad), width: Math.min(vw, box.width + 2 * pad), height: Math.min(box.height + 2 * pad, 2400) } });
}
const P = (w, n) => ({ desktop: 'desktop', tablet: 'tablet', m390: 'mobile', m320: 'mobile320' }[w] + '_' + n);

(async () => {
  const acc = accounts();
  const browser = await chromium.launch();
  const before = counts();
  const errors = [];
  const watch = (p) => { p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); }); };

  // ---------- Build Portfolio reference (unchanged cards), desktop
  {
    const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 2 });
    const p = await ctx.newPage(); watch(p);
    await signIn(p, acc.you);
    await p.goto(BASE + '/challenge'); await settle(p, 2500);
    const demo = p.getByText('Try the demonstration round');
    if (await demo.count()) { await demo.click(); await settle(p, 4000); }
    await shotOf(p, '.ch-fx', 'reference_build_portfolio_cards', 10);
    await shotOf(p, '.ch-tracker', 'reference_build_portfolio_tracker', 10);
    await ctx.close();
  }

  for (const [wname, w] of Object.entries(WIDTHS)) {
    const caps = SHOTS.has(wname);
    // ---------- guest
    const g = await browser.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: caps ? 2 : 1 });
    const gp = await g.newPage(); watch(gp);
    await gp.goto(BASE + '/leaderboards'); await settle(gp, 2500);
    await choose(gp, 'lb-stream', 'Development');
    const gt = await check(gp, `${wname} guest weekly`);
    if (!gt.includes('Sign in to see your position')) results.push({ name: `${wname} guest`, problems: ['no sign-in prompt'] });
    if (wname === 'm320') await shotOf(gp, '.site-nav', 'mobile320_navigation_guest', 0);
    await g.close();

    // ---------- signed in (viewer "you")
    const ctx = await browser.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: caps ? 2 : 1 });
    const page = await ctx.newPage(); watch(page);
    await signIn(page, acc.you);
    await page.goto(BASE + '/leaderboards'); await settle(page, 2500);
    if (wname === 'm320') await shotOf(page, '.site-nav', 'mobile320_navigation', 0);
    await choose(page, 'lb-stream', 'Development');
    await check(page, `${wname} weekly provisional`);
    if (wname === 'desktop' || wname === 'm390') await shot(page, P(wname, 'weekly_provisional'));
    await choose(page, 'lb-round', R(13));
    await check(page, `${wname} weekly final`);
    if (caps) await shot(page, P(wname, 'weekly_final'));
    if (wname === 'desktop') { await shotOf(page, '.ch-podium', 'desktop_podium_shared_ranks', 10); await shotOf(page, '.lb-weekly', 'desktop_weekly_table_alignment', 8); }
    if (wname === 'm390') await shotOf(page, '.lb-weekly tbody', 'mobile_weekly_cards_rank_name', 6);
    await stress(page, `${wname} weekly final`);
    if (wname === 'm320') await shot(page, 'mobile320_long_name_weekly_stress');
    for (const [label, n] of [['corrected', 3], ['under_review', 7], ['practice', 4], ['void', 5], ['refunded', 8]]) {
      await choose(page, 'lb-round', R(n));
      await check(page, `${wname} weekly ${label}`);
      if (wname === 'desktop' && ['corrected', 'practice'].includes(label)) await shot(page, P(wname, `weekly_${label}`));
    }
    // championship
    await page.locator(`[id*='"t":"lb-tab"'] label`, { hasText: 'Championship' }).click(); await settle(page, 2000);
    await check(page, `${wname} championship in progress`);
    if (caps) await shot(page, P(wname, 'championship_in_progress'));
    await chooseExact(page, 'lb-round', /^\s*Championship Nov-26\s*$/);
    const ct = await check(page, `${wname} championship completed`);
    for (const want of ['Joint champions', 'corrected after completion', 'Under review', 'Completed with 9 valid rounds'])
      if (!ct.toLowerCase().includes(want.toLowerCase())) results.push({ name: `${wname} championship`, problems: [`missing "${want}"`] });
    if (caps) await shot(page, P(wname, 'championship_corrected_under_review'));
    if (wname === 'm390') await shotOf(page, '.lb-champ tbody', 'mobile_championship_cards_rank_name', 6);
    await stress(page, `${wname} championship completed`);
    if (wname === 'm320') await shot(page, 'mobile320_long_name_championship_stress');

    // My Challenge Current and History
    await page.goto(BASE + '/challenge/me'); await settle(page, 2500);
    await check(page, `${wname} my challenge current`);
    if (wname === 'desktop' || wname === 'm390') await shot(page, P(wname, 'my_challenge_current'));
    await page.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' }).click(); await settle(page, 2500);
    await choose(page, 'me-hstream', 'Development');
    const ht = await check(page, `${wname} history (all championships)`);
    if (!ht.includes('Your statistics') || !ht.includes('will become available after 3 eligible rounds'))
      results.push({ name: `${wname} history`, problems: ['expected statistics and one locked chart'] });
    if (caps) await shot(page, P(wname, 'history'));
    if (wname === 'desktop') {
      await shotOf(page, '.me-summary', 'desktop_stats_cards_positive_net', 8);
      await shotOf(page, '.me-charts', 'desktop_charts_one_eligible', 8);
    }
    if (wname === 'm390') await shotOf(page, '.me-stats', 'mobile_stats_cards', 6);
    await stress(page, `${wname} history`);
    await page.goto(BASE + '/challenge/me'); await settle(page, 2500);
    await page.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' }).click(); await settle(page, 2500);
    await choose(page, 'me-hstream', 'Development');
    await chooseExact(page, 'me-hscope', /^\s*Championship Nov-26\s*$/);
    const bt = await check(page, `${wname} history (one championship)`);
    if (bt.includes('will become available')) results.push({ name: `${wname} history scope`, problems: ['both charts expected'] });
    if (wname === 'desktop') { await shotOf(page, '.me-charts', 'desktop_charts_both_eligible', 8); await shot(page, 'desktop_history_championship_scope'); }
    // drill-down of the reopened round
    const open = page.locator(`[id*='"i":"${R(7)}"'][id*='"t":"hist-open"']`).first();
    if (await open.count()) {
      await open.click(); await settle(page, 2500);
      const dt = await check(page, `${wname} history detail`);
      if (!dt.includes('Last published official result')) results.push({ name: `${wname} detail`, problems: ['no last-published label'] });
      if (caps) await shotOf(page, '.me-hist-detail', P(wname, 'history_detail_under_review'), 8);
    } else results.push({ name: `${wname} detail`, problems: ['reopened round not on the first history page'] });
    await ctx.close();

    // ---------- second viewer (24-character account name): negative net, charts locked
    if (['desktop', 'm320', 'm390'].includes(wname)) {
      const c2 = await browser.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: 2 });
      const p2 = await c2.newPage(); watch(p2);
      await signIn(p2, acc.pat);
      await p2.goto(BASE + '/challenge/me'); await settle(p2, 2500);
      await check(p2, `${wname} long account name`);
      if (wname === 'm320') await shotOf(p2, '.site-nav', 'mobile320_navigation_long_name', 0);
      await p2.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' }).click(); await settle(p2, 2500);
      await choose(p2, 'me-hstream', 'Development');
      await chooseExact(p2, 'me-hscope', /Championship Nov-26 \(2\)/);
      const lt = await check(p2, `${wname} history negative net, charts locked`);
      if ((lt.match(/will become available/g) || []).length !== 2) results.push({ name: `${wname} locked charts`, problems: ['two locked charts expected'] });
      if (wname === 'desktop') {
        await shotOf(p2, '.me-summary', 'desktop_stats_cards_negative_net', 8);
        await shotOf(p2, '.me-charts', 'desktop_charts_locked', 8);
        // zero-net styling specimen: the real card with its value set to +0.00 in the page
        await p2.evaluate(() => {
          const v = [...document.querySelectorAll('.me-stat-val')].pop();
          v.textContent = '+0.00'; v.className = 'me-stat-val zero';
          const sub = [...document.querySelectorAll('.me-stat-sub')].pop();
          sub.innerHTML = 'return on allocation <span class="zero">0.0%</span>';
          const r = [...document.querySelectorAll('.me-stat-val')][4]; r.textContent = '100.00';
          const a = [...document.querySelectorAll('.me-stat-val')][3]; a.textContent = '100.00';
        });
        await shotOf(p2, '.me-stats', 'desktop_stats_cards_zero_net_specimen', 8);
      }
      if (wname === 'm320') await shot(p2, 'mobile320_history_long_name_negative');
      await c2.close();
    }
  }
  if (errors.length) results.push({ name: 'console', problems: [...new Set(errors)].slice(0, 8) });
  const after = counts();
  if (before !== after) results.push({ name: 'read-only', problems: [`rows changed ${before} -> ${after}`] });
  await browser.close();
  const bad = results.filter(r => r.problems.length);
  console.log(`${results.length} page checks across ${Object.keys(WIDTHS).length} widths, ${bad.length} with problems`);
  for (const r of bad) console.log(' -', r.name, ':', r.problems.slice(0, 12).join(' | '));
  fs.writeFileSync(path.join(ROOT, 'tmp/e2e_6c5/refined_results.json'), JSON.stringify(results, null, 1));
  process.exit(bad.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
