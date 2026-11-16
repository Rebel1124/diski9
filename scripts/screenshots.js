// Capture Milestone 5.1 screenshots of the running Dash app and run layout checks.
// Usage: node scripts/screenshots.js [baseUrl] [outDir]
const { chromium, devices } = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8050/';
const out = process.argv[3] || 'docs/screenshots';

const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
async function settle(page) {
  await page.waitForSelector('table.results tr.row, .fx-card', { timeout: 30000, state: 'attached' });
  await page.waitForTimeout(800);
}
async function tab(page, name) {
  await page.click(`text=${name}`);
  await page.waitForTimeout(1000);
}
async function rank(page, label) {
  await page.click('#direction');
  await page.getByRole('option', { name: label }).click();
  await page.waitForTimeout(800);
}
async function select(page, selector, text) {
  await page.locator(selector, { hasText: text }).first().click();
  await page.waitForSelector('.detail-header', { timeout: 20000 });
  await page.waitForFunction((t) => document.querySelector('.detail-header h2').innerText.includes(t), text);
  await page.waitForTimeout(500);
}

(async () => {
  const browser = await chromium.launch();
  const report = {};
  const desk = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 });
  await desk.goto(base);
  await settle(desk);
  // 1. main Match result screener
  await desk.screenshot({ path: `${out}/desktop_1x2_table.png` });
  report.desktop_overflow_px = await overflow(desk);
  // 7. selected-row highlighting on a non-first row
  const third = await desk.locator('table.results tr.row').nth(2).locator('td').nth(2).innerText();
  await select(desk, 'table.results tr.row', third);
  report.selected_rows = await desk.evaluate(() => [...document.querySelectorAll('tr.row.selected')].length);
  report.first_row_selected = await desk.evaluate(() => document.querySelector('tr.row').classList.contains('selected'));
  await desk.screenshot({ path: `${out}/desktop_selected_row.png`, clip: { x: 0, y: 380, width: 1440, height: 520 } });
  // 2. 1X2 summary with market-implied probabilities
  await select(desk, 'table.results tr.row', 'Manchester City');
  await desk.locator('.detail .summary').screenshot({ path: `${out}/desktop_1x2_summary_market_probabilities.png` });
  await desk.locator('.detail').screenshot({ path: `${out}/desktop_1x2_detail.png` });
  // 3. reference odds section with the expander directly below the heading
  await desk.locator('details.more > summary', { hasText: 'Reference odds and market-implied probabilities' }).click();
  await desk.waitForTimeout(400);
  report.about_first = await desk.evaluate(() => {
    const sec = [...document.querySelectorAll('details.more')].find(d => d.querySelector('summary').innerText.startsWith('Reference odds'));
    const first = sec.querySelector('.section-body > *');
    return first.querySelector('summary').innerText + ' / open=' + first.open;
  });
  const oddsSection = desk.locator('details.more', { hasText: 'Reference odds and market-implied probabilities' }).first();
  await oddsSection.screenshot({ path: `${out}/desktop_odds_section.png` });
  // 4/5. BTTS and O/U summaries (Overall by default)
  await tab(desk, 'Both teams to score');
  report.btts_basis = await desk.evaluate(() => document.querySelector('#basis input:checked').value);
  await desk.screenshot({ path: `${out}/desktop_btts_table.png` });
  await desk.locator('.detail .summary').screenshot({ path: `${out}/desktop_btts_summary.png` });
  await tab(desk, 'Over/Under 2.5');
  await desk.locator('.detail .summary').screenshot({ path: `${out}/desktop_ou25_summary.png` });
  report.pair_sizes = await desk.evaluate(() => [...document.querySelectorAll('.pair-value')].map(e => getComputedStyle(e).fontSize + ' ' + getComputedStyle(e).fontWeight));
  await tab(desk, 'Match result');
  report.match_basis = await desk.evaluate(() => document.querySelector('#basis input:checked').value);
  // 6. Rank By / Threshold controls: enabled (home advantage) and disabled (evenly matched)
  await desk.evaluate(() => window.scrollTo(0, 0));
  await rank(desk, 'Strongest home-team form advantage');
  await desk.locator('.filters').screenshot({ path: `${out}/desktop_controls_enabled.png` });
  await rank(desk, 'Most evenly matched');
  report.threshold_disabled_for_even = await desk.evaluate(() => document.querySelector('#threshold-label').innerText);
  await desk.locator('.filters').screenshot({ path: `${out}/desktop_controls_disabled.png` });

  // 8. phone
  const ctx = await browser.newContext({ ...devices['iPhone 13'] });
  const phone = await ctx.newPage();
  await phone.goto(base);
  await settle(phone);
  report.mobile_overflow_px = await overflow(phone);
  await phone.evaluate(() => document.querySelector('#summary').scrollIntoView());
  await phone.screenshot({ path: `${out}/mobile_fixture_list.png` });
  await phone.locator('.fx-card').nth(1).tap();
  await phone.waitForSelector('.detail-header', { timeout: 20000 });
  await phone.waitForTimeout(900);
  report.mobile_selected_cards = await phone.evaluate(() => [...document.querySelectorAll('.fx-card.selected')].length);
  await phone.locator('.detail-header').scrollIntoViewIfNeeded();
  await phone.screenshot({ path: `${out}/mobile_detail.png` });
  report.mobile_detail_overflow_px = await overflow(phone);
  console.log(JSON.stringify(report));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
