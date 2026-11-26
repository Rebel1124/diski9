// Phase 7 CP3 real-browser checks against the real app, the disposable p7_e2e database
// and local Supabase Auth. Compares what the pages show with the service expectations
// written by seed.py (tmp/e2e_p7/expect.json). Usage:
//   NODE_PATH=$(npm root -g) node tools/e2e_p7/checks.js <stage> [--shots]
const fs = require('fs');
const path = require('path');
const { chromium, BASE, ROOT, DATA, signIn, settle, accounts, expectations, sql } = require('./lib');
const stage = process.argv[2];
const SHOTS = process.argv.includes('--shots');
const OUT = path.join(ROOT, 'docs/screenshots/phase7');
const HIDDEN = process.env.BASE_HIDDEN || 'http://127.0.0.1:8058';
const NAMES = { foundation_fundi: 'Foundation Fundi', balanced_brawler: 'Balanced Brawler',
  challenger_champ: 'Challenger Champ', goals_guru: 'Goals Guru', btts_bonanza: 'BTTS Bonanza',
  draw_dynamo: 'Draw Dynamo' };
const WIDTHS = { desktop: 1280, tablet: 820, mobile: 390 };
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;
const results = [];
let failures = 0;
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  if (!ok) failures++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' :: ' + detail : ''}`);
}
const rowCounts = () => sql('SELECT (SELECT count(*) FROM app.score_sets) || \',\' || ' +
  '(SELECT count(*) FROM app.entry_settlements) || \',\' || (SELECT count(*) FROM app.audit_log)');

async function tab(page, label) {
  await page.locator('.me-tabs label', { hasText: label }).click();
  await settle(page, 900);
}
async function stream(page, key, label) {
  const dd = page.locator(`[id*='"${key}"']`).first();
  if (!(await dd.isVisible())) return false;
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.keyboard.press('Escape');
    await dd.click();
    await page.waitForTimeout(400);
    const opt = page.getByRole('option', { name: label, exact: true });
    if (await opt.count()) {
      await opt.first().click();
      await settle(page, 1200);
      if ((await dd.innerText()).includes(label)) return true;
    }
  }
  await page.keyboard.press('Escape');
  return false;
}
async function pageText(page) { return page.evaluate(() => document.body.innerText); }

async function verifyAchievements(page, exp, label) {
  const t = await pageText(page);
  check(`${label}: no synthetic banner or placeholder`, !/Synthetic preview|follows here, unchanged/.test(t));
  check(`${label}: no e-mail or UUID in page`, !/@example\.test/.test(t) && !UUID.test(t));
  if (exp.unavailable) {
    check(`${label}: unavailable state`, t.includes('Achievements unavailable')
      && !/Beginner|Semi-Pro|Pro target/.test(t) && (await page.locator('.ach-card').count()) === 0);
    return;
  }
  const level = (await page.locator('.ach-level').innerText()).trim();
  check(`${label}: level ${exp.level}`, level === exp.level, level);
  const counts = (await page.locator('.ach-count').allInnerTexts()).map(x => Number(x.replace(/,/g, '')));
  check(`${label}: six counts ${exp.counts}`, JSON.stringify(counts) === JSON.stringify(exp.counts),
    JSON.stringify(counts));
  check(`${label}: total ${exp.total}`, t.includes(`${exp.total} badges earned`));
  const done = await page.locator('.ach-done').innerText();
  check(`${label}: ${exp.categories_met} of 6 categories`, done.startsWith(`${exp.categories_met} of 6`), done);
  const segs = await page.locator('.ach-seg').evaluateAll(e => e.map(x => x.classList.contains('met')));
  const want = [...Array(6)].map((_, i) => i < exp.categories_met);
  check(`${label}: bar fills left to right`, JSON.stringify(segs) === JSON.stringify(want));
}

async function verifyChips(page, name, exp) {
  const code = exp.rounds[name].code;
  const sel = `[id*='"hist-open"'][id*='"${code}"']`;
  await page.waitForSelector(sel, { timeout: 20000 }).catch(() => {});
  const btn = page.locator(sel).first();
  if (!(await btn.count())) {
    const ids = await page.evaluate(() => [...document.querySelectorAll('[id*="hist-open"]')].map(e => e.id).join(' '));
    const st = await page.locator('.me-hist-controls').innerText().catch(() => '?');
    check(`History ${name}: row present`, false, `${code} | stream: ${st} | ids: ${ids}`); return;
  }
  await btn.click();
  await settle(page, 1200);
  const detail = page.locator('.me-hist-detail');
  const chips = (await detail.locator('.ach-chip').allInnerTexts()).map(x => x.trim());
  const want = exp.rounds[name].badges;
  if (want === 'unavailable') {
    check(`History ${name}: quiet unavailable line`,
      (await detail.innerText()).includes('Badges for this round are temporarily unavailable'));
  } else {
    const names = (want || []).map(b => NAMES[b]);
    check(`History ${name}: chips ${JSON.stringify(names)}`, JSON.stringify(chips) === JSON.stringify(names),
      JSON.stringify(chips));
  }
  check(`History ${name}: results panel still shown`, (await detail.innerText()).length > 40);
  return detail;
}

(async () => {
  const exp = expectations();
  if (exp.stage !== stage) throw new Error(`expect.json is for ${exp.stage}, not ${stage}`);
  const acc = accounts();
  fs.mkdirSync(OUT, { recursive: true });
  const before = rowCounts();
  const browser = await chromium.launch();
  const errors = [];

  // ---- the viewer, development rounds shown (server setting)
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await signIn(page, acc.you);
  await page.goto(`${BASE}/challenge/me`);
  await settle(page, 1500);
  await tab(page, 'Achievements');
  check('Achievements: Development stream selected', await stream(page, 'me-astream', 'Development'));
  await verifyAchievements(page, exp.you.development, `you/development`);
  if (SHOTS) {
    for (const [w, px] of Object.entries(WIDTHS)) {
      await page.setViewportSize({ width: px, height: 900 });
      await settle(page, 500);
      await page.screenshot({ path: path.join(OUT, `${stage}-achievements-${w}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 1280, height: 900 });
  }
  if (!exp.you.development.unavailable) {
    await stream(page, 'me-astream', 'Beta');
    await verifyAchievements(page, exp.you.beta, 'you/beta (isolated)');
    const opened = await stream(page, 'me-astream', 'Official');
    if (opened) await verifyAchievements(page, exp.you.official, 'you/official');
    else check('Official stream not offered before it starts (D-38); service shows zero',
      JSON.stringify(exp.you.official.counts) === '[0,0,0,0,0,0]');
  }

  // ---- History detail chips
  await tab(page, 'History');
  check('History: Development stream selected', await stream(page, 'me-hstream', 'Development'));
  const pick = { none: [], base: ['R1', 'R2', 'R3', 'R5', 'R6'], pro: ['R7', 'R10'], reopen: ['R9'],
    republish: ['R9', 'R1'], corrupt: ['R10', 'R1'] }[stage] || [];
  for (const name of pick) {
    const detail = await verifyChips(page, name, exp);
    if (SHOTS && detail && name === pick[0]) {
      for (const [w, px] of Object.entries(WIDTHS)) {
        await page.setViewportSize({ width: px, height: 900 });
        await settle(page, 500);
        await detail.screenshot({ path: path.join(OUT, `${stage}-history-${name}-${w}.png`) });
      }
      await page.setViewportSize({ width: 1280, height: 900 });
    }
  }
  await tab(page, 'Current');
  check('Current tab still renders', (await page.locator('.ch-grid-me').count()) > 0);
  await ctx.close();

  // ---- the other participant sees only their own
  if (stage === 'none' || stage === 'base' || stage === 'republish') {
    const c2 = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const p2 = await c2.newPage();
    await signIn(p2, acc.pat);
    await p2.goto(`${BASE}/challenge/me`);
    await settle(p2, 1500);
    await tab(p2, 'Achievements');
    await stream(p2, 'me-astream', 'Development');
    await verifyAchievements(p2, exp.pat.development, 'pat/development (own data only)');
    await c2.close();

    // ---- guests get nothing
    const g = await browser.newContext();
    const gp = await g.newPage();
    await gp.goto(`${BASE}/challenge/me`);
    await settle(gp, 1500);
    if (await gp.locator('.me-tabs label', { hasText: 'Achievements' }).count()) {
      await tab(gp, 'Achievements');
    }
    const gt = await pageText(gp);
    check('guest: no achievement data', (await gp.locator('.ach-card').count()) === 0
      && !/badges earned/.test(gt), gt.includes('Sign in') ? 'sign-in prompt' : '');
    await g.close();

    // ---- development hidden by the server setting (second server)
    const c3 = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const p3 = await c3.newPage();
    await signIn(p3, acc.you, HIDDEN);
    await p3.goto(`${HIDDEN}/challenge/me`);
    await settle(p3, 1500);
    await tab(p3, 'Achievements');
    const dd = p3.locator(`[id*='"me-astream"']`).first();
    let devOffered = false;
    if (await dd.isVisible()) { await dd.click(); devOffered = await p3.getByRole('option', { name: 'Development' }).count() > 0; }
    check('dev hidden server: no Development stream offered', !devOffered);
    await verifyAchievements(p3, exp.you.beta, 'dev hidden server: beta counts');
    await c3.close();
  }
  await browser.close();
  check('no browser console or page errors', errors.length === 0, errors.slice(0, 3).join(' | '));
  check('page loads wrote nothing (score sets, settlements, audit)', rowCounts() === before,
    `${before} -> ${rowCounts()}`);
  fs.writeFileSync(path.join(DATA, `checks-${stage}.json`), JSON.stringify(results, null, 1));
  console.log(`${stage}: ${results.length - failures} passed, ${failures} failed`);
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
