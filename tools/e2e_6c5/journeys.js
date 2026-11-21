// Phase 6C.5 Stage F2: the twelve browser acceptance journeys of the design
// specification §17.3, at desktop (1360), tablet (768) and mobile (390), against the
// real app, real PostgreSQL and the local Supabase Auth harness. Local development only.
//
//   E2E_DIR=tmp/f2 BASE=http://127.0.0.1:8054 E2E_DB=diski9_f2_e2e \
//     NODE_PATH=$(npm root -g) node tools/e2e_6c5/journeys.js
//
// Servers: 8054 (diski9_f2_e2e, development rounds shown), 8055 (diski9_f2_e2e_nochamp)
// and 8056 (diski9_f2_e2e with development rounds NOT shown, as for ordinary
// participants). Data: seed.py + seed_f2.py; expectations: f2_expect.py.
//
// Every journey compares the visible page with the authoritative read-service values
// in tmp/f2/expect.json (ranks, names, points, states, labels, the viewer's row and
// page), then runs the element-level layout audit from refined.js, the page checks
// (no horizontal overflow, no e-mail address or UUID in text or ids) and collects
// browser errors. Privacy: a third account with no entries and a guest replay crafted
// Dash callbacks built from another participant's requests. Page loads must write
// nothing (row counts before and after).
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { chromium, BASE, ROOT, DATA, signIn, settle, accounts, createUser } = require('./lib');

// F4 re-runs on isolated copies: NOCHAMP, NODEV and SHOTS_DIR override the F2 defaults
// (so the preserved F2 evidence is not overwritten)
const NOCHAMP = process.env.NOCHAMP || 'http://127.0.0.1:8055';
const NODEV = process.env.NODEV || 'http://127.0.0.1:8056';
const OUT = path.join(ROOT, process.env.SHOTS_DIR || 'docs/screenshots/phase6c5/f2');
const DB_MAIN = process.env.E2E_DB || 'diski9_f2_e2e';
const DB_NOCHAMP = process.env.E2E_DB_NOCHAMP || 'diski9_f2_e2e_nochamp';
fs.mkdirSync(OUT, { recursive: true });
const X = JSON.parse(fs.readFileSync(path.join(DATA, 'expect.json'), 'utf8'));
const R = (n) => X.codes[n - 1];
const AUDIT = fs.readFileSync(path.join(__dirname, 'refined.js'), 'utf8').match(/function audit\(\) \{[\s\S]*?\n\}\n/)[0];
const WIDTHS = { desktop: [1360, 900], tablet: [768, 1024], mobile: [390, 844] };
const SHOTS = { desktop: 'all', tablet: 'key', mobile: 'key' };
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;
const results = [];
const matrix = {};

function note(journey, wname, name, problems) {
  results.push({ journey, wname, name, problems });
  matrix[journey] = matrix[journey] || {};
  matrix[journey][wname] = (matrix[journey][wname] || 0) + problems.length;
}
function counts(db) {
  const sql = "select (select count(*) from app.score_sets)||','||(select count(*) from app.championship_versions)||','||(select count(*) from app.audit_log where action not like 'account.%')||','||(select count(*) from app.entries)";
  return execSync(`psql -h 127.0.0.1 -p 5433 -U postgres -d ${db} -Atc "${sql}"`).toString().trim();
}
async function choose(page, t, re) {
  await page.locator(`[id*='"t":"${t}"']`).first().click();
  await page.getByRole('option').filter({ hasText: re }).first().click();
  await settle(page, 1500);
}
async function pageChecks(page, j, wname, name) {
  const info = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    text: document.body.innerText,
    ids: Array.from(document.querySelectorAll('[id]')).map(e => e.id).join(' '),
  }));
  const p = [];
  if (info.overflow > 1) p.push(`horizontal overflow ${info.overflow}px`);
  if (/@/.test(info.text)) p.push('an e-mail address in the page text');
  if (UUID.test(info.text) || UUID.test(info.ids)) p.push('a UUID in the page');
  p.push(...(await page.evaluate(`(${AUDIT})()`)));
  note(j, wname, `${name}: layout and disclosure`, p);
  return info.text;
}
async function shot(page, wname, name, level = 'all') {
  if (SHOTS[wname] !== 'all' && level !== 'key') return;
  if (name.includes('_pat_')) return;  // the second viewer is checked, not captured (no duplicates)
  const width = page.viewportSize().width;
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.screenshot({ path: path.join(OUT, `${wname}_${name}.png`), fullPage: true,
                          clip: { x: 0, y: 0, width, height: Math.min(height, width >= 1000 ? 3200 : 2400) } });
}
function rowsOf(page) {
  return page.evaluate(() => [...document.querySelectorAll('table.lb tbody tr')].map(tr => ({
    rank: (tr.querySelector('td.rank')?.innerText || '').trim(),
    name: (tr.querySelector('.lb-name')?.innerText || '').trim(),
    pts: (tr.querySelector('td.lb-pts')?.innerText || '').trim(),
    me: tr.classList.contains('me'),
  })));
}
function compareRows(got, want, label) {
  const p = [];
  if (got.length !== want.length) p.push(`${label}: ${got.length} rows shown, ${want.length} expected`);
  want.forEach((w, i) => {
    const g = got[i];
    if (!g) return;
    if (g.rank !== w.rank) p.push(`${label} row ${i + 1}: rank "${g.rank}" vs "${w.rank}"`);
    if (g.name !== w.name) p.push(`${label} row ${i + 1}: name "${g.name}" vs "${w.name}"`);
    if (g.me !== !!w.me) p.push(`${label} row ${i + 1}: highlight ${g.me} vs ${w.me}`);
    if (w.points !== undefined && g.pts !== '' && g.pts !== (w.points === null ? '—' : w.points.toLocaleString('en-US')))
      p.push(`${label} row ${i + 1}: points "${g.pts}" vs ${w.points}`);
  });
  return p.slice(0, 8);
}
function headers(page) {
  return page.evaluate(() => [...document.querySelectorAll('table.lb thead th')].map(t => t.textContent.trim()));
}
async function lbWeekly(page, code) {
  await choose(page, 'lb-round', new RegExp(code));
}
async function goto(page, label) {
  const b = page.locator(`[id*='"t":"lbw-goto"']`, { hasText: label }).first();
  if (!(await b.count())) return false;
  await b.click(); await settle(page, 1500);
  return true;
}
async function lbChampionship(page, name) {
  const tab = page.locator(`[id*='"t":"lb-tab"'] label`, { hasText: 'Championship' });
  await tab.click(); await settle(page, 2000);
  if (name) await choose(page, 'lb-round', new RegExp(`^\\s*${name.replace(/[()]/g, '\\$&')}\\s*$`));
}
function want(cond, msg) { return cond ? [] : [msg]; }

// ------------------------------------------------------------------ journeys
async function weeklyJourneys(page, who, wname) {
  const W = X.weekly[who];
  const signed = who !== 'guest';
  await page.goto(BASE + '/leaderboards'); await settle(page, 2500);
  await choose(page, 'lb-stream', /Development/);

  // J1 provisional
  await lbWeekly(page, R(14));
  let txt = await pageChecks(page, 'J1 provisional weekly', wname, who);
  let p = compareRows(await rowsOf(page), W.R14.rows, 'R14');
  const h1 = await headers(page);
  p.push(...want(!h1.includes('Points') && h1.includes('Returned so far'), `provisional headers ${h1.join('|')}`));
  p.push(...want(/Provisional ·/.test(txt), 'no "Provisional ·" banner'));
  if (signed) p.push(...want(txt.includes('Your result') || txt.includes('Your position'), 'no personal summary'));
  else p.push(...want(txt.includes('Sign in to see your position'), 'guest: no sign-in prompt'));
  note('J1 provisional weekly', wname, `${who}: rows, headers, banner`, p);
  await shot(page, wname, `j01_${who}_weekly_provisional`, who === 'you' ? 'key' : 'all');

  // J2 final, personal highlight, page two
  await lbWeekly(page, R(13));
  txt = await pageChecks(page, 'J2 final weekly + page two', wname, `${who} page 1`);
  p = compareRows(await rowsOf(page), W.R13.rows, 'R13 p1');
  p.push(...want((await headers(page)).includes('Points'), 'final competitive round without Points column'));
  if (signed) p.push(...want((await rowsOf(page)).some(r => r.me) === (W.R13.me_page === 1), 'viewer highlight on page 1'));
  await goto(page, 'Next');
  txt = await pageChecks(page, 'J2 final weekly + page two', wname, `${who} page 2`);
  p.push(...compareRows(await rowsOf(page), W.R13p2.rows, 'R13 p2'));
  p.push(...want(txt.includes(`Showing 51–${W.R13.total} of ${W.R13.total}`), 'page 2 range text'));
  note('J2 final weekly + page two', wname, `${who}: rows, points, highlight, page 2`, p);
  await shot(page, wname, `j02_${who}_weekly_final_page2`, who === 'you' ? 'key' : 'all');

  // J3 shared rank across the 50-row boundary; Go to my position (viewer on page 2)
  await lbWeekly(page, R(15));
  p = compareRows(await rowsOf(page), W.R15.rows, 'R15 p1');
  const last = (await rowsOf(page)).slice(-1)[0];
  p.push(...want(last && last.rank === '=31', `last row on page 1 is ${last && last.rank}`));
  if (signed && W.R15.me_page === 2) {
    p.push(...want(await goto(page, 'Go to my position'), 'no "Go to my position" button'));
  } else await goto(page, 'Next');
  txt = await pageChecks(page, 'J3 shared ranks across pages', wname, who);
  const p2 = await rowsOf(page);
  p.push(...compareRows(p2, W.R15p2.rows, 'R15 p2'));
  p.push(...want(p2[0] && p2[0].rank === '=31', 'first row on page 2 is not =31'));
  if (signed) p.push(...want(p2.some(r => r.me), 'viewer row not highlighted on page 2'));
  note('J3 shared ranks across pages', wname, `${who}: =31 spans the boundary`, p);
  await shot(page, wname, `j03_${who}_shared_rank_page2`, who === 'you' ? 'key' : 'all');

  // J4 practice
  await lbWeekly(page, R(4));
  txt = await pageChecks(page, 'J4 practice round', wname, who);
  p = compareRows(await rowsOf(page), W.R4.rows, 'R4');
  p.push(...want(!(await headers(page)).includes('Points'), 'practice round shows Points'));
  p.push(...want(/Practice round/.test(txt), 'no practice explanation'));
  note('J4 practice round', wname, `${who}: practice, no points`, p);
  await shot(page, wname, `j04_${who}_practice`);

  // J5 void
  await lbWeekly(page, R(5));
  txt = await pageChecks(page, 'J5 void round', wname, who);
  p = want((await rowsOf(page)).length === 0, 'void round shows a table');
  p.push(...want(/void/i.test(txt), 'no void wording'));
  if (signed) p.push(...want(/Round void · your 100 credits were refunded/i.test(txt), 'no personal refund line'));
  note('J5 void round', wname, `${who}: void, refunded, no table`, p);
  await shot(page, wname, `j05_${who}_void`, who === 'you' ? 'key' : 'all');

  // J9 under review weekly (R7)
  await lbWeekly(page, R(7));
  txt = await pageChecks(page, 'J9 under review', wname, `${who} weekly`);
  p = compareRows(await rowsOf(page), W.R7.rows, 'R7');
  p.push(...want(/Under review: these are the last published results/.test(txt), 'no under-review banner'));
  note('J9 under review', wname, `${who}: weekly last published results`, p);
  await shot(page, wname, `j09_${who}_weekly_under_review`);

  // J10 corrected weekly (R3)
  await lbWeekly(page, R(3));
  txt = await pageChecks(page, 'J10 corrected + shortened', wname, `${who} weekly`);
  p = compareRows(await rowsOf(page), W.R3.rows, 'R3');
  p.push(...want(new RegExp(`Corrected · version ${W.R3.revision}`).test(txt), 'no corrected version line'));
  note('J10 corrected + shortened', wname, `${who}: weekly corrected revision`, p);
  await shot(page, wname, `j10_${who}_weekly_corrected`);
}

async function championshipJourneys(page, who, wname) {
  const C = X.champ[who];
  const signed = who !== 'guest';
  const cur = C['Championship Nov-26 (2)'], hist = C['Championship Nov-26'];
  // J6 in progress (current by default)
  await lbChampionship(page, null);
  let txt = await pageChecks(page, 'J6 championship in progress', wname, who);
  let p = compareRows(await rowsOf(page), cur.rows, 'current');
  p.push(...want(/In progress/i.test(txt), 'no In progress status'));
  p.push(...want(txt.includes(`${cur.counted} of ${cur.required}`) || txt.includes(`${cur.counted}/${cur.required}`), `progress ${cur.counted} of ${cur.required} not shown`));
  if (signed && cur.me) p.push(...want(txt.includes(`${cur.me.points}`), 'personal points missing'));
  note('J6 championship in progress', wname, `${who}: standings, progress, personal`, p);
  await shot(page, wname, `j06_${who}_championship_in_progress`, who === 'you' ? 'key' : 'all');

  // J7 joint champions + J9 under review + J10 corrected/shortened (historical A)
  await lbChampionship(page, 'Championship Nov-26');
  txt = await pageChecks(page, 'J7 joint champions', wname, who);
  p = compareRows(await rowsOf(page), hist.rows, 'historical');
  p.push(...want(/Joint champions/.test(txt), 'no "Joint champions"'));
  for (const n of hist.champions) p.push(...want(txt.includes(n), `champion ${n} not named`));
  note('J7 joint champions', wname, `${who}: joint champions named`, p);
  note('J9 under review', wname, `${who}: championship under review`,
       want(/Under review/i.test(txt), 'no Under review status'));
  note('J10 corrected + shortened', wname, `${who}: corrected after completion, D-30a`,
       [...want(/corrected after completion/i.test(txt), 'no corrected-after-completion disclosure'),
        ...want(new RegExp(`Completed with ${hist.counted} valid rounds`).test(txt), `no "Completed with ${hist.counted} valid rounds"`),
        ...want(!/Short/.test(txt), 'the word "Short" is used')]);
  await shot(page, wname, `j07_${who}_joint_champions_review_corrected`, who === 'you' ? 'key' : 'all');
}

async function noChampion(page, who, wname) {
  await page.goto(NOCHAMP + '/leaderboards'); await settle(page, 2500);
  await choose(page, 'lb-stream', /Development/);
  await lbChampionship(page, null);
  const txt = await pageChecks(page, 'J8 no champion', wname, who);
  const p = compareRows(await rowsOf(page), X.nochamp.rows, 'no champion');
  p.push(...want(/No champion: no participant scored points\./.test(txt), 'no "No champion" line'));
  p.push(...want(/Completed/i.test(txt), 'not shown as completed'));
  p.push(...want(!/Joint champions|Champion:/.test(txt), 'a champion is named'));
  note('J8 no champion', wname, `${who}: completed, nobody scored`, p);
  await shot(page, wname, `j08_${who}_no_champion`, who === 'guest' ? 'key' : 'all');
}

async function historyJourney(page, who, wname, captured) {
  const H = X.history[who];
  await page.goto(BASE + '/challenge/me'); await settle(page, 2500);
  await page.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' }).click(); await settle(page, 2500);
  await choose(page, 'me-hstream', /Development/);
  let txt = await pageChecks(page, 'J11 history, filters, drill-down', wname, `${who} history`);
  const codes = await page.evaluate(() => [...document.querySelectorAll('.lb-code, .me-round')].map(e => e.innerText.trim()));
  let p = [];
  for (const r of H.rows) p.push(...want(codes.some(c => c.includes(r.code)), `history row ${r.code} missing`));
  p.push(...want(txt.includes('Your statistics'), 'no statistics'));
  p.push(...want(txt.includes(H.stats.allocated) && txt.includes(H.stats.returned), `statistics ${H.stats.allocated}/${H.stats.returned} not shown`));
  p.push(...want(txt.includes(`Showing 1–${Math.min(10, H.total)} of ${H.total}`) || txt.includes(`of ${H.total}`), `history total ${H.total} not shown`));
  note('J11 history, filters, drill-down', wname, `${who}: rows and statistics`, p);
  await shot(page, wname, `j11_${who}_history`, who === 'you' ? 'key' : 'all');
  // filter: one championship
  await choose(page, 'me-hscope', /^\s*Championship Nov-26 \(2\)\s*$/);
  txt = await pageChecks(page, 'J11 history, filters, drill-down', wname, `${who} filtered`);
  const after = await page.evaluate(() => document.querySelectorAll('[id*="hist-open"]').length);
  note('J11 history, filters, drill-down', wname, `${who}: championship filter narrows`, want(after > 0 && after < H.rows.length, `filtered rows ${after} of ${H.rows.length}`));
  await choose(page, 'me-hscope', /All championships/);
  // drill-down: the reopened round (R7) and, capturing the request for the privacy replay
  const reqP = page.waitForRequest(r => r.url().includes('_dash-update-component') && (r.postData() || '').includes('hist-open'));
  await page.locator(`[id*='"i":"${R(7)}"'][id*='"t":"hist-open"']`).first().click();
  const req = await reqP; await settle(page, 2500);
  if (captured) captured.body = req.postData();
  txt = await pageChecks(page, 'J11 history, filters, drill-down', wname, `${who} detail`);
  p = want(/Last published official result/.test(txt), 'no last-published label in detail');
  p.push(...want((await page.locator('.me-hist-detail .ch-res-metrics .me-stat').count()) === 4, 'detail result cards not 4'));
  note('J11 history, filters, drill-down', wname, `${who}: drill-down under review`, p);
  await shot(page, wname, `j11_${who}_detail_under_review`);
}

async function guestJourney(page, wname) {
  await page.goto(BASE + '/challenge/me'); await settle(page, 2500);
  let txt = await pageChecks(page, 'J12 guest view', wname, 'my challenge');
  const tab = page.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' });
  if (await tab.count()) { await tab.click(); await settle(page, 2000); txt = await page.evaluate(() => document.body.innerText); }
  let p = want(!/Your statistics/.test(txt), 'guest sees statistics');
  p.push(...want(/Sign in/.test(txt), 'guest: no sign-in prompt on My Challenge'));
  note('J12 guest view', wname, 'guest: no personal history', p);
  await page.goto(BASE + '/leaderboards'); await settle(page, 2500);
  await choose(page, 'lb-stream', /Development/);
  await lbWeekly(page, R(13));
  txt = await pageChecks(page, 'J12 guest view', wname, 'leaderboards');
  p = want(!(await rowsOf(page)).some(r => r.me), 'guest has a highlighted row');
  p.push(...want(txt.includes('Sign in to see your position'), 'no sign-in prompt'));
  note('J12 guest view', wname, 'guest: public standings only', p);
  await shot(page, wname, 'j12_guest_leaderboard', 'key');
}

async function navigation(page, wname) {
  const p = [];
  for (const [href, want_] of [['/leaderboards', 'Leaderboards'], ['/challenge/me', 'My Challenge'], ['/challenge', 'Weekly Challenge']]) {
    const r = await page.goto(BASE + href); await settle(page, 1500);
    if (!r || r.status() !== 200) p.push(`${href} status ${r && r.status()}`);
    const t = await page.evaluate(() => document.body.innerText);
    if (!t.includes(want_)) p.push(`${href} lacks "${want_}"`);
  }
  // nav links all resolve
  const links = await page.evaluate(() => [...document.querySelectorAll('.site-nav a[href]')].map(a => a.getAttribute('href')).filter(h => h.startsWith('/')));
  for (const h of [...new Set(links)]) {
    const r = await page.request.get(BASE + h);
    if (r.status() >= 400) p.push(`nav ${h} -> ${r.status()}`);
  }
  return p;
}

// crafted Dash callbacks: another participant's drill-down request, replayed from a
// session with no entries and from a guest session
async function crafted(page, label, body, wname, otherName) {
  let hdr = null;
  const reqP = page.waitForRequest(r => r.url().includes('_dash-update-component'), { timeout: 20000 }).catch(() => null);
  await page.goto(BASE + '/challenge/me'); await settle(page, 2000);
  const tab = page.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' });
  if (await tab.count()) { await tab.click(); }
  const req = await reqP; await settle(page, 1500);
  hdr = req ? req.headers() : {};
  const send = async (b) => page.evaluate(async ([b, h]) => {
    const keep = {}; for (const k of Object.keys(h)) if (/^(content-type|x-csrf|x-requested|accept)/i.test(k)) keep[k] = h[k];
    const r = await fetch('/_dash-update-component', { method: 'POST', headers: keep, body: b, credentials: 'same-origin' });
    return { status: r.status, text: await r.text() };
  }, [b, hdr]);
  const p = [];
  const res = await send(body);
  const leaks = (t) => [otherName, '2,744.60', 'Official result', 'me-hist-detail'].filter(s => t.includes(s));
  if (res.status === 200) {
    if (leaks(res.text).length) p.push(`drill-down replay leaked: ${leaks(res.text).join(', ')}`);
    // a signed-in participant gets the explicit refusal; a guest gets an empty detail
    if (label !== 'guest' && !res.text.includes('That entry is not available.')) p.push('no refusal text in the response');
    if (label === 'guest' && !/"children":\s*\[?null/.test(res.text)) p.push(`guest response not empty: ${res.text.slice(0, 120)}`);
  } else if (res.status !== 204 && res.status !== 403 && res.status !== 400) p.push(`unexpected status ${res.status}`);
  // the same request with the stream switched to beta and to official
  for (const s of ['beta', 'official']) {
    const r2 = await send(body.replace(/"development"/g, `"${s}"`));
    if (r2.status === 200 && leaks(r2.text).length) p.push(`${s} replay leaked`);
  }
  note('Privacy: crafted callbacks', wname, `${label}: replayed another participant's drill-down (status ${res.status})`, p);
}

(async () => {
  const acc = accounts();
  const browser = await chromium.launch();
  const before = counts(DB_MAIN), beforeN = counts(DB_NOCHAMP);
  const eve = await createUser('eve');  // a third participant with no entries (throw-away)
  for (const [wname, [w, h]] of Object.entries(WIDTHS)) {
    const errors = [];
    const ctxFor = async () => {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
      const pg = await ctx.newPage();
      pg.on('pageerror', e => errors.push(e.message));
      pg.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
      return [ctx, pg];
    };
    // guest
    let [ctx, page] = await ctxFor();
    await weeklyJourneys(page, 'guest', wname);
    await championshipJourneys(page, 'guest', wname);
    await noChampion(page, 'guest', wname);
    await guestJourney(page, wname);
    // stream visibility for ordinary viewers (development rounds not enabled)
    await page.goto(NODEV + '/leaderboards'); await settle(page, 2500);
    const nodev = await page.evaluate(() => document.body.innerText);
    await page.locator(`[id*='"t":"lb-stream"']`).first().click().catch(() => {});
    const opts = await page.getByRole('option').allInnerTexts().catch(() => []);
    note('Stream visibility', wname, 'development hidden without the development flag',
         [...want(!opts.some(o => /Development/.test(o)), `stream options ${opts.join('|')}`),
          ...want(!X.codes.some(c => nodev.includes(c)), 'a development round code is visible')]);
    await page.keyboard.press('Escape').catch(() => {});
    note('Navigation', wname, 'guest navigation', await navigation(page, wname));
    await ctx.close();

    // signed-in viewers
    const captured = {};
    for (const who of ['you', 'pat']) {
      [ctx, page] = await ctxFor();
      await signIn(page, acc[who]);
      await weeklyJourneys(page, who, wname);
      await championshipJourneys(page, who, wname);
      if (who === 'you') {
        await historyJourney(page, who, wname, captured);
        await noChampion(page, who, wname);
        note('Navigation', wname, 'signed-in navigation', await navigation(page, wname));
      }
      await ctx.close();
    }
    // privacy: eve (no entries) and a guest replay you's drill-down request
    [ctx, page] = await ctxFor();
    await signIn(page, eve);
    if (captured.body) await crafted(page, 'participant without entries', captured.body, wname, X.names.you);
    await page.goto(BASE + '/challenge/me'); await settle(page, 2000);
    await page.locator(`[id*='"t":"me-tab"'] label`, { hasText: 'History' }).click(); await settle(page, 2000);
    const et = await page.evaluate(() => document.body.innerText);
    note('Privacy: crafted callbacks', wname, 'participant without entries: own empty history only',
         [...want(!X.codes.some(c => et.includes(c)), 'another participant\'s round code shown'),
          ...want(!et.includes(X.names.you), 'another participant\'s name in My Challenge')]);
    await ctx.close();
    [ctx, page] = await ctxFor();
    if (captured.body) await crafted(page, 'guest', captured.body, wname, X.names.you);
    await ctx.close();
    const errs = [...new Set(errors)].filter(e => !/favicon/.test(e));
    note('Browser errors', wname, 'no uncaught errors or console errors', errs.slice(0, 5));
  }
  await browser.close();
  const after = counts(DB_MAIN), afterN = counts(DB_NOCHAMP);
  note('Read-only', 'all', 'page loads and crafted callbacks wrote nothing',
       [...want(before === after, `rows changed ${before} -> ${after}`), ...want(beforeN === afterN, 'no-champion rows changed')]);
  for (const r of results) console.log(r.problems.length ? 'PROBLEM' : 'ok     ', `[${r.wname}] ${r.journey} — ${r.name}`, r.problems.join(' | '));
  console.log('\nJourney matrix (problems per width):');
  for (const [j, m] of Object.entries(matrix)) console.log(`  ${j.padEnd(36)} ${Object.entries(m).map(([k, v]) => `${k}:${v}`).join('  ')}`);
  const bad = results.filter(r => r.problems.length);
  console.log(`${results.length} checks, ${bad.length} with problems`);
  fs.writeFileSync(path.join(DATA, 'journeys_results.json'), JSON.stringify({ results, matrix }, null, 1));
  process.exit(bad.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
