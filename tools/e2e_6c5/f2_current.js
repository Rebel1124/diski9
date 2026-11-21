// Phase 6C.5 Stage F2: My Challenge *Current* "Your result" cards for the state just
// prepared by f2_current.py, at desktop (1360), tablet (768) and mobile (390), against
// the viewer's authoritative settlement (tmp/f2/current_<state>.json). Local only.
//
//   E2E_DIR=tmp/f2 BASE=http://127.0.0.1:8054 E2E_DB=diski9_f2_e2e \
//     NODE_PATH=$(npm root -g) node tools/e2e_6c5/f2_current.js <state>
const fs = require('fs');
const path = require('path');
const { chromium, BASE, ROOT, DATA, signIn, settle, accounts } = require('./lib');

const OUT = path.join(ROOT, 'docs/screenshots/phase6c5/f2');
const AUDIT = fs.readFileSync(path.join(__dirname, 'refined.js'), 'utf8').match(/function audit\(\) \{[\s\S]*?\n\}\n/)[0];
const label = process.argv[2];
const E = JSON.parse(fs.readFileSync(path.join(DATA, `current_${label}.json`), 'utf8'));
const num = (s) => (s == null ? null : Number(String(s).replace(/[+,−]/g, '').replace(/^-/, '-')));

function expected() {
  const refund = E.round_void || E.entry_refunded;
  return {
    cats: ['cat-violet', refund ? 'cat-gold' : 'cat-green', 'cat-blue',
           refund ? 'cat-gold' : E.recovered ? 'cat-teal' : 'cat-slate'],
    head2: refund ? /refunded/i : /returned/i,
    recovery: refund ? 'Refund (not a recovery)' : E.recovered == null ? 'Not decided yet' : E.recovered ? 'Recovered 100+' : 'Not recovered',
    net: E.net, tone: E.net == null ? null : num(E.net) > 0 ? 'pos-val' : num(E.net) < 0 ? 'neg-val' : 'zero',
    gross: E.gross,
  };
}

(async () => {
  const want = expected();
  const browser = await chromium.launch();
  const results = [];
  for (const [wname, w] of [['desktop', 1360], ['tablet', 768], ['mobile', 390]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await signIn(page, accounts().you);
    await page.goto(BASE + '/challenge/me'); await settle(page, 3000);
    await page.waitForSelector('.ch-res-metrics .me-stat', { timeout: 20000 }).catch(() => {});
    // the current round's panel comes first; a "Most recent entry" card for an earlier
    // round may follow with its own result cards
    const cards = await page.evaluate(() => [...(document.querySelector('.ch-res-metrics')?.querySelectorAll('.me-stat') || [])].map(e => ({
      cat: e.className.replace('me-stat ', '').trim(), head: e.querySelector('.me-stat-head').innerText.trim(),
      val: e.querySelector('.me-stat-val').innerText.trim(), cls: e.querySelector('.me-stat-val').className })));
    const text = await page.evaluate(() => document.body.innerText);
    const p = [];
    if (cards.length !== 4) p.push(`${cards.length} cards`);
    else {
      cards.forEach((c, i) => { if (!c.cat.includes(want.cats[i])) p.push(`card ${i + 1} ${c.cat} (expected ${want.cats[i]})`); });
      if (!want.head2.test(cards[1].head)) p.push(`card 2 header "${cards[1].head}"`);
      if (want.gross != null && num(cards[1].val) !== num(want.gross)) p.push(`card 2 value ${cards[1].val} vs ${want.gross}`);
      if (want.net == null ? !/Not final yet/.test(cards[2].val) : num(cards[2].val) !== num(want.net)) p.push(`Net ${cards[2].val} vs ${want.net}`);
      if (want.tone && !cards[2].cls.includes(want.tone)) p.push(`Net class ${cards[2].cls} (expected ${want.tone})`);
      if (cards[3].val !== want.recovery) p.push(`Recovery "${cards[3].val}" vs "${want.recovery}"`);
    }
    if (!text.includes(E.code)) p.push('the current round code is not shown');
    if (label === 'review' && !/review|reopened/i.test(text)) p.push('no review wording');
    if (label === 'corrected' && !/correct/i.test(text)) p.push('no correction wording');
    p.push(...(await page.evaluate(`(${AUDIT})()`)));
    if (errors.length) p.push(...[...new Set(errors)].slice(0, 3));
    results.push({ wname, cards: cards.map(c => `${c.cat}: ${c.head} = ${c.val}`), problems: p });
    const box = page.locator('.ch-res-summary').first();
    if (await box.count()) {
      await box.scrollIntoViewIfNeeded();
      const bb = await box.boundingBox(); const y = await page.evaluate(() => scrollY);
      await page.screenshot({ path: path.join(OUT, `${wname}_current_${label}.png`), fullPage: true,
        clip: { x: Math.max(0, bb.x - 8), y: bb.y + y - 8, width: Math.min(w, bb.width + 16), height: Math.min(bb.height + 16, 2400) } });
    }
    await ctx.close();
  }
  await browser.close();
  for (const r of results) console.log(r.problems.length ? 'PROBLEM' : 'ok     ', `[${r.wname}] Current ${label}:`, r.cards.join(' | '), r.problems.join(' | '));
  fs.writeFileSync(path.join(DATA, `current_${label}_results.json`), JSON.stringify(results, null, 1));
  process.exit(results.some(r => r.problems.length) ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
