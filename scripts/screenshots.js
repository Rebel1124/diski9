// Capture screenshots of the running Dash app and check for horizontal page overflow.
// Usage: node scripts/screenshots.js [baseUrl] [outDir]
const { chromium, devices } = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8050/';
const out = process.argv[3] || 'docs/screenshots';

async function settle(page) {
  await page.waitForSelector('table.results tr.row, .fx-card', { timeout: 30000, state: 'attached' });
  await page.waitForTimeout(700);
}
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
async function openDetail(page, selector, text) {
  await page.locator(selector, { hasText: text }).first().click();
  await page.waitForSelector('.detail-header', { timeout: 20000 });
  await page.waitForTimeout(600);
}
async function tab(page, name) {
  await page.click(`text=${name}`);
  await page.waitForTimeout(900);
}

(async () => {
  const browser = await chromium.launch();
  const report = {};
  const desk = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 });
  await desk.goto(base);
  await settle(desk);
  await desk.screenshot({ path: `${out}/desktop_1x2_table.png` });
  report.desktop_overflow_px = await overflow(desk);
  report.desktop_rows_page1 = await desk.locator('table.results tr.row').count();
  report.summary = await desk.locator('#summary').innerText();
  await openDetail(desk, 'table.results tr.row', process.env.DETAIL_TEAM || 'Manchester City');
  await desk.locator('.detail').screenshot({ path: `${out}/desktop_1x2_detail.png` });
  await desk.locator('details.more > summary', { hasText: 'How is Form Score calculated?' }).click();
  await desk.waitForTimeout(300);
  await desk.locator('.detail .card').nth(1).screenshot({ path: `${out}/desktop_1x2_form_breakdown.png` });
  await tab(desk, 'Both teams to score');
  await desk.screenshot({ path: `${out}/desktop_btts_table.png` });
  await tab(desk, 'Over/Under 2.5');
  await desk.screenshot({ path: `${out}/desktop_ou25_table.png` });
  // league filter: PSL only (EPL unchecked), then open a PSL fixture
  await desk.locator('#leagues label', { hasText: 'EPL' }).click();
  await desk.waitForTimeout(900);
  report.psl_only_summary = await desk.locator('#summary').innerText();
  await openDetail(desk, 'table.results tr.row', process.env.PSL_TEAM || 'Stellenbosch');
  await desk.locator('.detail').screenshot({ path: `${out}/desktop_ou25_psl_detail.png` });
  await desk.locator('#leagues label', { hasText: 'EPL' }).click();
  await desk.waitForTimeout(600);
  // tooltip open
  await tab(desk, 'Match result');
  await desk.locator('#basis-label details.info > summary').click();
  await desk.waitForTimeout(300);
  await desk.evaluate(() => window.scrollTo(0, 0));
  await desk.screenshot({ path: `${out}/desktop_basis_tooltip.png`, clip: { x: 0, y: 0, width: 1440, height: 520 } });

  const ctx = await browser.newContext({ ...devices['iPhone 13'] });
  const phone = await ctx.newPage();
  await phone.goto(base);
  await settle(phone);
  report.mobile_overflow_px = await overflow(phone);
  report.mobile_cards_page1 = await phone.locator('.fx-card').count();
  await phone.evaluate(() => document.querySelector('#summary').scrollIntoView());
  await phone.screenshot({ path: `${out}/mobile_fixture_list.png` });
  await phone.locator('#basis-label details.info > summary').tap();
  report.mobile_tooltip_visible = await phone.isVisible('#basis-label .info-pop');
  await phone.locator('#basis-label details.info > summary').tap();
  await openDetail(phone, '.fx-card', process.env.MOBILE_TEAM || 'Liverpool');
  await phone.waitForTimeout(800);
  await phone.locator('.detail-header').scrollIntoViewIfNeeded();
  await phone.screenshot({ path: `${out}/mobile_detail.png` });
  report.mobile_detail_overflow_px = await overflow(phone);
  console.log(JSON.stringify(report));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
