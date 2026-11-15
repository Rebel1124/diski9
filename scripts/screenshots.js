// Capture screenshots of the running Dash app and check for horizontal page overflow.
// Usage: node scripts/screenshots.js [baseUrl] [outDir]
const { chromium, devices } = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8050/';
const out = process.argv[3] || 'docs/screenshots';

async function settle(page) {
  await page.waitForSelector('.dash-spreadsheet td', { timeout: 20000, state: 'attached' });
  await page.waitForTimeout(600);
}
async function overflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}
async function clickRow(page, text, selector = '.dash-spreadsheet td') {
  const cell = page.locator(selector, { hasText: text }).first();
  await cell.click();
  await page.waitForSelector('.detail-header', { timeout: 20000 });
  await page.waitForTimeout(500);
}

(async () => {
  const browser = await chromium.launch();
  const report = {};

  // Desktop
  const desk = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
  await desk.goto(base);
  await settle(desk);
  await desk.screenshot({ path: `${out}/desktop_1x2_table.png` });
  report.desktop_overflow_px = await overflow(desk);
  await clickRow(desk, 'Manchester City');
  await desk.locator('.detail').screenshot({ path: `${out}/desktop_1x2_detail.png` });
  await desk.click('text=Both teams to score');
  await desk.waitForTimeout(800);
  await desk.screenshot({ path: `${out}/desktop_btts_table.png` });
  await desk.click('text=Over/Under 2.5');
  await desk.waitForTimeout(800);
  await clickRow(desk, 'Orlando Pirates');
  await desk.locator('.detail').screenshot({ path: `${out}/desktop_ou25_psl_detail.png` });

  // Phone
  const ctx = await browser.newContext({ ...devices['iPhone 13'] });
  const phone = await ctx.newPage();
  await phone.goto(base);
  await settle(phone);
  await phone.screenshot({ path: `${out}/mobile_table.png`, fullPage: false });
  report.mobile_overflow_px = await overflow(phone);
  await phone.evaluate(() => document.querySelector('.count').scrollIntoView());
  await phone.screenshot({ path: `${out}/mobile_table_rows.png`, fullPage: false });
  await clickRow(phone, 'Liverpool', '.fx-card');
  await phone.waitForTimeout(800);
  await phone.locator('.detail-header').scrollIntoViewIfNeeded();
  await phone.screenshot({ path: `${out}/mobile_detail.png`, fullPage: false });
  report.mobile_detail_overflow_px = await overflow(phone);

  console.log(JSON.stringify(report));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
