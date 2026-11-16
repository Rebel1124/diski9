// Capture Milestone 5.3 screenshots and run layout checks.
// Usage: node scripts/screenshots.js [liveUrl] [earlySeasonUrl] [outDir]
//   liveUrl:        the app on the current database (uv run diski9 serve)
//   earlySeasonUrl: optional second app evaluated early in a season (blended baselines)
const { chromium, devices } = require('playwright');
const live = process.argv[2] || 'http://127.0.0.1:8050/';
const early = process.argv[3] || '';
const out = process.argv[4] || 'docs/screenshots';

const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
async function settle(page) {
  await page.waitForSelector('table.results tr.row, .fx-card', { timeout: 30000, state: 'attached' });
  await page.waitForTimeout(800);
}
async function tab(page, name) {
  await page.click(`text=${name}`);
  await page.waitForTimeout(1200);
}
async function select(page, text) {
  await page.locator('table.results tr.row', { hasText: text }).first().click();
  await page.waitForFunction((t) => {
    const h = document.querySelector('.detail-header h2');
    return h && h.innerText.includes(t);
  }, text, { timeout: 20000 });
  await page.waitForTimeout(600);
}
async function openSection(page, title) {
  const d = page.locator('.detail details.more', { has: page.locator('summary', { hasText: title }) }).first();
  if (!(await d.evaluate((el) => el.open))) await d.locator('summary').first().click();
  await page.waitForFunction((t) => [...document.querySelectorAll('.detail details.more')]
    .some((el) => el.open && el.querySelector('summary').innerText.includes(t)), title);
  await page.waitForTimeout(300);
}
async function basis(page, value) {
  await page.locator(`#basis input[value="${value}"]`).check();
  await page.waitForTimeout(1200);
}

(async () => {
  const browser = await chromium.launch();
  const report = {};
  const desk = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 });
  await desk.goto(live);
  await settle(desk);
  report.banner = await desk.evaluate(() => [...document.querySelectorAll('.banner')].map(b => b.innerText));

  // 1-2. Match result table (Model D), ranked by home-form advantage, and detail
  await desk.click('#direction');
  await desk.getByRole('option', { name: 'Strongest home-team form advantage' }).click();
  await desk.waitForTimeout(1200);
  await desk.screenshot({ path: `${out}/m53_1x2_table.png` });
  report.desktop_overflow_px = await overflow(desk);
  await select(desk, 'Sekhukhune United');
  await openSection(desk, 'How is Form Score calculated?');
  report.form_calc_rows = await desk.evaluate(() => [...document.querySelectorAll('.form-calc tbody tr')].map(r => r.innerText.replace(/\s+/g, ' ')));
  await desk.locator('.detail').screenshot({ path: `${out}/m53_1x2_detail.png` });
  report.selected_rows = await desk.evaluate(() => document.querySelectorAll('tr.row.selected').length);

  // 3-4. BTTS table and detail (Overall by default)
  await tab(desk, 'Both teams to score');
  report.btts_basis = await desk.evaluate(() => document.querySelector('#basis input:checked').value);
  report.btts_headers = await desk.evaluate(() => [...document.querySelectorAll('table.results th')].map(t => t.innerText.replace(/[↕▲▼]/g, '').trim()));
  report.btts_directions = await desk.evaluate(async () => {
    document.querySelector('#direction').click();
    await new Promise(r => setTimeout(r, 300));
    const opts = [...document.querySelectorAll('[role=option]')].map(o => o.innerText);
    document.body.click();
    return opts;
  });
  await desk.keyboard.press('Escape');
  await desk.screenshot({ path: `${out}/m53_btts_table.png` });
  await select(desk, 'Aston Villa');
  await openSection(desk, 'How are these figures calculated?');
  await desk.locator('.detail').screenshot({ path: `${out}/m53_btts_detail.png` });
  report.market_pair = await desk.evaluate(() => [...document.querySelectorAll('.goals-summary .pair-row.compact .pair-value')].map(e => `${e.innerText} ${getComputedStyle(e).fontSize} ${getComputedStyle(e).fontWeight}`));

  // 5-6. Over/Under
  await tab(desk, 'Over/Under 2.5');
  await desk.screenshot({ path: `${out}/m53_ou25_table.png` });
  await select(desk, 'Chelsea');
  await desk.locator('.detail .summary').screenshot({ path: `${out}/m53_ou25_detail.png` });

  // 7. Limited data (venue basis: PSL teams with 4-5 current-season venue matches)
  await tab(desk, 'Both teams to score');
  await basis(desk, 'venue');
  await select(desk, 'Aston Villa');
  report.limited_summary = await desk.evaluate(() => document.querySelector('.goals-summary').innerText.replace(/\s+/g, ' '));
  await desk.locator('.detail .summary').screenshot({ path: `${out}/m53_limited_example.png` });

  // 8. League baseline explanation, early in a season (blended with last season)
  if (early) {
    const e = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 });
    await e.goto(early);
    await settle(e);
    await tab(e, 'Both teams to score');
    await e.locator('table.results tr.row').first().click();
    await e.waitForSelector('.goals-summary', { timeout: 20000 });
    await e.waitForTimeout(600);
    report.early_baseline = await e.evaluate(() => document.querySelector('.goals-summary .baseline').innerText.replace(/\s+/g, ' '));
    await e.locator('.detail .summary').screenshot({ path: `${out}/m53_league_baseline_explanation.png` });
  }

  // 9. phone
  const ctx = await browser.newContext({ ...devices['iPhone 13'] });
  const phone = await ctx.newPage();
  await phone.goto(live);
  await settle(phone);
  await tab(phone, 'Both teams to score');
  report.mobile_overflow_px = await overflow(phone);
  await phone.evaluate(() => document.querySelector('#summary').scrollIntoView());
  await phone.screenshot({ path: `${out}/m53_mobile_screener.png` });
  await phone.locator('.fx-card').nth(1).tap();
  await phone.waitForSelector('.goals-summary', { timeout: 20000 });
  await phone.waitForTimeout(900);
  report.mobile_selected_cards = await phone.evaluate(() => document.querySelectorAll('.fx-card.selected').length);
  await phone.locator('.detail-header').scrollIntoViewIfNeeded();
  await phone.screenshot({ path: `${out}/m53_mobile_detail.png` });
  report.mobile_detail_overflow_px = await overflow(phone);
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
