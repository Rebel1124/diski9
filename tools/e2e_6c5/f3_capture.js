// Phase 6C.5 Stage F3: record the real Dash callback requests behind the leaderboard
// and My Challenge pages (signed in as one F3 test account), so the HTTP load test
// replays exactly what browsers send. Local development only.
//   E2E_DIR=tmp/f3/n1000 BASE=http://127.0.0.1:8061 E2E_DB=diski9_f3_n1000 \
//     NODE_PATH=$(npm root -g) node tools/e2e_6c5/f3_capture.js
// Writes <E2E_DIR>/callbacks.json: [{name, path, body}] in page order.
const fs = require('fs'), path = require('path');
const { chromium, BASE, DATA, signIn, settle, accounts } = require('./lib');

(async () => {
  const acc = Object.values(accounts())[0];
  const b = await chromium.launch();
  const page = await (await b.newContext({ viewport: { width: 1360, height: 900 } })).newPage();
  await signIn(page, acc);
  const seen = [];
  let label = 'start';
  page.on('request', r => {
    if (r.method() === 'POST' && r.url().includes('_dash-update-component')) {
      const body = r.postData() || '';
      let out = '';
      try { out = JSON.parse(body).output; } catch { /* keep empty */ }
      seen.push({ name: label, output: out, body });
    }
  });
  const choose = async (t, re) => {
    await page.locator(`[id*='"t":"${t}"']`).first().click();
    await page.getByRole('option').filter({ hasText: re }).first().click();
    await settle(page, 2500);
  };
  label = 'leaderboards page'; await page.goto(BASE + '/leaderboards'); await settle(page, 3000);
  label = 'weekly development (default round)'; await choose('lb-stream', /Development/);
  label = 'weekly page 2';
  await page.locator(`[id*='"t":"lbw-goto"']`, { hasText: 'Next' }).first().click(); await settle(page, 2500);
  label = 'championship tab';
  await page.locator(`[id*='"t":"lb-tab"'] label`, { hasText: 'Championship' }).click(); await settle(page, 2500);
  label = 'my challenge page'; await page.goto(BASE + '/challenge/me'); await settle(page, 3000);
  label = 'history tab';
  await page.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' }).click(); await settle(page, 2500);
  label = 'history development'; await choose('me-hstream', /Development/);
  label = 'history drill-down';
  await page.locator(`[id*='"t":"hist-open"']`).first().click(); await settle(page, 2500);
  await b.close();
  fs.writeFileSync(path.join(DATA, 'callbacks.json'), JSON.stringify(seen, null, 1));
  const summary = {};
  for (const s of seen) summary[s.name] = (summary[s.name] || 0) + 1;
  console.log(JSON.stringify(summary));
})().catch(e => { console.error(e); process.exit(1); });
