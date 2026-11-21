// Phase 6C.5 Stage F3: Dash leaderboards page load in a real browser (Chromium), the
// §14 target "Leaderboards page load (Dash), 1,000: <= 600 ms". Local development only.
//   E2E_DIR=tmp/f3/n1000 BASE=http://127.0.0.1:8061 E2E_DB=diski9_f3_n1000 ITER=15 \
//     NODE_PATH=$(npm root -g) node tools/e2e_6c5/f3_pageload.js <label>
// For a signed-in participant (session reused) and a guest, after 3 warm-up loads,
// ITER measured loads each of:
//  * "shell": navigation to /leaderboards until the leaderboard controls and body are
//    rendered (the default stream);
//  * "board": from choosing the Development stream until its weekly table is shown
//    (the data callback);
//  * "page load" = shell + board (what a participant waits for to see standings).
// performance.now() in the page; median and p95 in ms; writes tmp/f3/pageload_<label>.json.
const fs = require('fs'), path = require('path');
const { chromium, BASE, ROOT, signIn, accounts } = require('./lib');
const ITER = Number(process.env.ITER || 15);
const p95 = (xs) => { const s = [...xs].sort((a, b) => a - b); return s[Math.max(0, Math.ceil(0.95 * s.length) - 1)]; };
const med = (xs) => { const s = [...xs].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

async function once(page) {
  const t0 = Date.now();
  await page.goto(BASE + '/leaderboards', { waitUntil: 'commit' });
  await page.waitForSelector(`[id*='"t":"lb-stream"']`, { timeout: 30000 });
  await page.waitForFunction(() => !document.querySelector('._dash-loading-callback'), null, { timeout: 30000 }).catch(() => {});
  const shell = Date.now() - t0;
  await page.locator(`[id*='"t":"lb-stream"']`).first().click();
  const t1 = Date.now();
  await page.getByRole('option').filter({ hasText: /Development/ }).first().click();
  await page.waitForSelector('table.lb tbody tr', { timeout: 30000 });
  const board = Date.now() - t1;
  return { shell, board, total: shell + board };
}

(async () => {
  const label = process.argv[2] || 'run';
  const b = await chromium.launch();
  const out = {};
  for (const who of ['participant', 'guest']) {
    const ctx = await b.newContext({ viewport: { width: 1360, height: 900 } });
    const page = await ctx.newPage();
    if (who === 'participant') await signIn(page, Object.values(accounts())[1]);
    for (let i = 0; i < 3; i++) await once(page);
    const xs = [];
    for (let i = 0; i < ITER; i++) xs.push(await once(page));
    const s = (k) => ({ median: med(xs.map(x => x[k])), p95: p95(xs.map(x => x[k])), n: xs.length });
    out[who] = { shell: s('shell'), board: s('board'), page_load: s('total') };
    await ctx.close();
  }
  await b.close();
  fs.mkdirSync(path.join(ROOT, 'tmp/f3'), { recursive: true });
  fs.writeFileSync(path.join(ROOT, `tmp/f3/pageload_${label}.json`), JSON.stringify(out, null, 1));
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
