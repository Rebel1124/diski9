// Screenshots of the two-card fixture detail (Diski 9 Match Analysis + Bookmaker
// Market Reference) on desktop and phone, with layout checks.
// Usage: node scripts/screenshots_detail.js [baseUrl] [outDir]
const { chromium, devices } = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8050/';
const out = process.argv[3] || 'docs/screenshots';

async function tab(page, name) {
  await page.click(`text=${name}`);
  await page.waitForTimeout(1200);
}
async function pick(page, text, phone) {
  const loc = phone ? page.locator('.fx-card', { hasText: text }).first()
                    : page.locator('table.results tr.row', { hasText: text }).first();
  await (phone ? loc.tap() : loc.click());
  await page.waitForFunction((t) => {
    const h = document.querySelector('.detail-header h2');
    return h && h.innerText.includes(t) && document.querySelector('.analysis');
  }, text, { timeout: 20000 });
  await page.waitForTimeout(600);
}
async function openAcc(page, title) {
  await page.locator('.analysis details.acc > summary', { hasText: title }).click();
  await page.waitForTimeout(300);
}
const checks = (page) => page.evaluate(() => ({
  overflow: document.documentElement.scrollWidth - window.innerWidth,
  cards: [...document.querySelectorAll('.detail .card-head h3')].map(h => h.innerText),
  headline: !!document.querySelector('.detail .headline'),
  accordions: [...document.querySelectorAll('.analysis details.acc')].map(d => d.open),
}));

(async () => {
  const browser = await chromium.launch();
  const report = {};
  for (const [name, opts] of [
    ['desktop', { viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 }],
    ['mobile', { ...devices['iPhone 13'] }],
  ]) {
    const phone = name === 'mobile';
    const ctx = await browser.newContext(opts);
    const page = await ctx.newPage();
    await page.goto(base);
    await page.waitForSelector('table.results tr.row, .fx-card', { timeout: 30000, state: 'attached' });
    await page.waitForTimeout(800);
    // Match result (collapsed, then with "How it's calculated" open)
    await pick(page, 'Manchester City', phone);
    report[`${name}_1x2_collapsed`] = await checks(page);
    await page.locator('.detail').screenshot({ path: `${out}/ui_${name}_1x2_detail.png` });
    await openAcc(page, "How it's calculated");
    report[`${name}_1x2_open`] = await checks(page);
    await page.locator('.analysis').screenshot({ path: `${out}/ui_${name}_1x2_calculation_open.png` });
    if (!phone) {
      await openAcc(page, "How it's calculated");
      await openAcc(page, 'Matches used');
      report.results_used = await page.locator('.results-used').first().innerText();
      await page.locator('.analysis').screenshot({ path: `${out}/ui_desktop_1x2_matches_open.png` });
    }
    // BTTS (collapsed, then with "Matches used" open)
    await tab(page, 'Both teams to score');
    await pick(page, 'Manchester City', phone);
    report[`${name}_btts_collapsed`] = await checks(page);
    await page.locator('.detail').screenshot({ path: `${out}/ui_${name}_btts_detail.png` });
    await openAcc(page, 'Matches used');
    report[`${name}_btts_open`] = await checks(page);
    if (!phone) {
      await page.locator('.analysis').screenshot({ path: `${out}/ui_desktop_btts_matches_open.png` });
      // PSL: no bookmaker odds -> small unavailable card (show PSL fixtures only)
      await page.locator('#leagues label', { hasText: 'EPL' }).click();
      await page.waitForTimeout(1200);
      await pick(page, 'Orlando Pirates', phone);
      await page.locator('.market').screenshot({ path: `${out}/ui_desktop_psl_market_unavailable.png` });
      report.psl_market = await page.locator('.market').innerText();
    }
    await ctx.close();
  }
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
