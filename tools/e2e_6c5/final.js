// Phase 6C.5 Stage E final owner refinements: focused real-browser checks and
// screenshots (local development only; showcase database from seed.py).
//
//   NODE_PATH=$(npm root -g) node tools/e2e_6c5/final.js
//
// 1. Weekly Challenge without a live round: the gap above the demonstration button
//    equals the gap below it (measured), at 1360, 768, 390 and 320 px.
// 2. Your Result cards (the 6C.4 results panel) in the statistics-card style, for the
//    provisional, final, corrected, under-review, void and refunded states: category
//    headers, positive / negative / refund styling, and the element-level layout audit
//    from refined.js (nothing clipped, overflowing or overlapping).
// 3. History chart headings: same size and weight as "Your statistics", whether the
//    chart or its placeholder is shown, and wrapping on phones.
// Screenshots go to docs/screenshots/phase6c5/refined/ (prefix final_).
const fs = require('fs');
const path = require('path');
const { chromium, BASE, ROOT, signIn, settle, accounts } = require('./lib');

const OUT = path.join(ROOT, 'docs/screenshots/phase6c5/refined');
const ROUNDS = JSON.parse(fs.readFileSync(path.join(ROOT, 'tmp/e2e_6c5/rounds.json'), 'utf8'));
const R = (n) => ROUNDS[n - 1];
const AUDIT = fs.readFileSync(path.join(__dirname, 'refined.js'), 'utf8').match(/function audit\(\) \{[\s\S]*?\n\}\n/)[0];
const WIDTHS = { desktop: 1360, tablet: 768, mobile: 390, mobile320: 320 };
const results = [];
const note = (name, problems) => results.push({ name, problems });

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
async function audit(page, name) { note(name, await page.evaluate(`(${AUDIT})()`)); }
async function shotOf(page, locator, file, pad = 10) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  const vw = page.viewportSize().width;
  const y = await page.evaluate(() => window.scrollY);
  await page.screenshot({ path: path.join(OUT, `${file}.png`), fullPage: true,
    clip: { x: Math.max(0, box.x - pad), y: Math.max(0, box.y + y - pad), width: Math.min(vw, box.width + 2 * pad), height: Math.min(box.height + 2 * pad, 2400) } });
}
async function gaps(page) {
  return page.evaluate(() => {
    const a = document.querySelector('.ch-ribbon.warn'), b = document.querySelector('.ch-actions'), c = document.querySelector('.ch-howto');
    if (!a || !b || !c) return null;
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(), rc = c.getBoundingClientRect();
    return { above: Math.round(rb.top - ra.bottom), below: Math.round(rc.top - rb.bottom) };
  });
}
async function openDetail(page, code) {
  const open = page.locator(`[id*='"i":"${code}"'][id*='"t":"hist-open"']`).first();
  if (!(await open.count())) { note(`detail ${code}`, ['not on the first history page']); return null; }
  await open.click(); await settle(page, 2500);
  return page.locator('.me-hist-detail').first();
}
async function cards(page) {
  return page.evaluate(() => [...document.querySelectorAll('.ch-res-metrics .me-stat')]
    .map(e => ({ cat: e.className.replace('me-stat ', ''), head: e.querySelector('.me-stat-head').innerText,
                 val: e.querySelector('.me-stat-val').innerText, cls: e.querySelector('.me-stat-val').className })));
}

(async () => {
  const acc = accounts();
  const browser = await chromium.launch();
  for (const [wname, w] of Object.entries(WIDTHS)) {
    const ctx = await browser.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await signIn(page, acc.you);

    // 1. demonstration button spacing (before = the same page without the new class)
    await page.goto(BASE + '/challenge'); await settle(page, 2500);
    const after = await gaps(page);
    if (!after) note(`${wname} demo spacing`, ['no notice / button / How to play on the page']);
    else {
      if (Math.abs(after.above - after.below) > 1) note(`${wname} demo spacing`, [`above ${after.above}px, below ${after.below}px`]);
      else note(`${wname} demo spacing (${after.above}px above and below)`, []);
      if (wname !== 'tablet') {
        await page.evaluate(() => document.querySelector('.ch-actions').classList.remove('ch-demo-actions'));
        const before = await gaps(page);
        // capture notice + button + top of How to play
        const clip = async (file) => {
          const r = await page.evaluate(() => { const a = document.querySelector('.ch-ribbon.warn').getBoundingClientRect(); const c = document.querySelector('.ch-howto').getBoundingClientRect(); return { y: a.top + window.scrollY - 10, h: c.top - a.top + 70 }; });
          await page.screenshot({ path: path.join(OUT, `${file}.png`), fullPage: true, clip: { x: 0, y: Math.max(0, r.y), width: w, height: r.h } });
        };
        await clip(`final_${wname}_demo_spacing_before`);
        await page.evaluate(() => document.querySelector('.ch-actions').classList.add('ch-demo-actions'));
        await clip(`final_${wname}_demo_spacing_after`);
        note(`${wname} demo spacing before: ${before.above}px above, ${before.below}px below`, []);
      }
    }
    await audit(page, `${wname} weekly challenge page`);

    // 2. Your Result cards: Current (provisional R14) and the History drill-downs
    await page.goto(BASE + '/challenge/me'); await settle(page, 2500);
    const cur = await cards(page);
    // the showcase has no current round, so Current shows no results panel; the panel is the
    // same component as the History drill-downs below (provisional state: R14)
    if (cur.length && cur.length !== 4) note(`${wname} current result cards`, [`expected 4 cards, found ${cur.length}`]);
    await audit(page, `${wname} my challenge current`);
    const resCard = page.locator('.ch-res-metrics').first();
    if ((wname === 'desktop' || wname === 'mobile') && await resCard.count())
      await shotOf(page, page.locator('.ch-res-summary, .ch-res-metrics').first(), `final_${wname}_result_cards_provisional`);
    await page.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' }).click(); await settle(page, 2500);
    await choose(page, 'me-hstream', 'Development');
    // chart headings vs "Your statistics"
    const hs = await page.evaluate(() => {
      const st = [...document.querySelectorAll('h2')].find(h => h.innerText.trim() === 'Your statistics');
      const f = (e) => { const c = getComputedStyle(e); return `${c.fontFamily}|${c.fontSize}|${c.fontWeight}`; };
      return { stats: st ? f(st) : null, charts: [...document.querySelectorAll('.me-chart-title')].map(e => ({ t: e.innerText, f: f(e), over: e.scrollWidth > e.clientWidth + 1 })) };
    });
    if (hs.charts.length !== 2) note(`${wname} chart headings`, [`expected 2, found ${hs.charts.length}`]);
    for (const c of hs.charts) {
      if (c.f !== hs.stats) note(`${wname} chart heading "${c.t.slice(0, 30)}"`, [`style ${c.f} differs from Your statistics ${hs.stats}`]);
      if (c.over) note(`${wname} chart heading`, ['overflows its box']);
    }
    if (hs.charts.length === 2) note(`${wname} chart headings match Your statistics (${hs.stats.split('|').slice(1).join(' ')})`, []);
    if (wname === 'desktop' || wname === 'mobile320' || wname === 'mobile') await shotOf(page, page.locator('.me-charts').first(), `final_${wname}_chart_headings`);
    const states = [['provisional', R(14), null], ['final', R(13), 'pos'], ['corrected', R(3), null], ['under_review', R(7), null], ['void', R(5), 'refund']];
    for (const [label, code, expect] of states) {
      const d = await openDetail(page, code);
      if (!d) continue;
      const cs = await cards(page);
      const probs = [];
      if (cs.length !== 4) probs.push(`expected 4 cards, found ${cs.length}`);
      if (expect === 'refund') {
        if (!/refunded/i.test(cs[1]?.head) || !cs[1]?.cat.includes('cat-gold')) probs.push('refund card not amber "Refunded"');
        if (!/Refund \(not a recovery\)/.test(cs[3]?.val) || !cs[3]?.cat.includes('cat-gold')) probs.push('recovery card does not show the refund distinctly');
      }
      if (expect === 'pos' && !/pos-val/.test(cs[2]?.cls)) probs.push('positive net not green');
      note(`${wname} result cards ${label}`, probs);
      await audit(page, `${wname} history detail ${label}`);
      if (wname === 'desktop' || wname === 'mobile') await shotOf(page, page.locator('.me-hist-detail .ch-res-metrics').first(), `final_${wname}_result_cards_${label}`);
    }
    // negative net: a lost round
    const lost = await openDetail(page, R(10));
    if (lost) {
      const cs = await cards(page);
      note(`${wname} result cards negative`, /neg-val/.test(cs[2]?.cls) ? [] : [`net class ${cs[2]?.cls}`]);
      if (wname === 'desktop') await shotOf(page, page.locator('.me-hist-detail .ch-res-metrics').first(), 'final_desktop_result_cards_negative');
    }
    if (errors.length) note(`${wname} console`, [...new Set(errors)].slice(0, 5));
    await ctx.close();

    // refunded entry (all nine void): the second viewer's R8
    const c2 = await browser.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: 2 });
    const p2 = await c2.newPage();
    await signIn(p2, acc.pat);
    await p2.goto(BASE + '/challenge/me'); await settle(p2, 2500);
    await p2.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' }).click(); await settle(p2, 2500);
    await choose(p2, 'me-hstream', 'Development');
    if (wname === 'mobile320') {
      await chooseExact(p2, 'me-hscope', /Championship Nov-26 \(2\)/);
      await shotOf(p2, p2.locator('.me-charts').first(), 'final_mobile320_chart_headings_placeholders');
      await choose(p2, 'me-hscope', 'All championships');
    }
    const d = await openDetail(p2, R(8));
    if (d) {
      const cs = await cards(p2);
      const ok = /refunded/i.test(cs[1]?.head) && cs[1]?.cat.includes('cat-gold') && /Refund \(not a recovery\)/.test(cs[3]?.val);
      note(`${wname} result cards refunded entry`, ok ? [] : ['refund styling missing']);
      await audit(p2, `${wname} history detail refunded`);
      if (wname !== 'tablet') await shotOf(p2, p2.locator('.me-hist-detail .ch-res-metrics').first(), `final_${wname}_result_cards_refunded`);
    }
    await c2.close();
  }
  await browser.close();
  const bad = results.filter(r => r.problems.length);
  for (const r of results) console.log(r.problems.length ? 'PROBLEM' : 'ok     ', r.name, r.problems.join(' | '));
  console.log(`${results.length} checks, ${bad.length} with problems`);
  process.exit(bad.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
