// F1: My Challenge Current "Your result" panel with a populated settlement (signed-in
// participant f1me, F1 development app on 8053). Usage: node current.js <label>
process.env.BASE = 'http://127.0.0.1:8053'; process.env.E2E_DB = 'diski9_f1_e2e';
const fs = require('fs'), path = require('path');
const { chromium, signIn, settle } = require('/home/user/diski9-6c5/tools/e2e_6c5/lib');
const acc = JSON.parse(fs.readFileSync('/home/user/diski9-6c5/tmp/f1/accounts.json', 'utf8'));
const OUT = '/home/user/diski9-6c5/docs/screenshots/phase6c5/refined';
const AUDIT = fs.readFileSync('/home/user/diski9-6c5/tools/e2e_6c5/refined.js', 'utf8').match(/function audit\(\) \{[\s\S]*?\n\}\n/)[0];
(async () => {
  const label = process.argv[2];
  const b = await chromium.launch();
  const res = [];
  for (const [name, w] of [['desktop', 1360], ['mobile', 390]]) {
    const p = await (await b.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: 2 })).newPage();
    await signIn(p, acc.f1me);
    await p.goto(process.env.BASE + '/challenge/me'); await settle(p, 3000); await p.waitForSelector('.ch-res-metrics .me-stat', { timeout: 20000 }).catch(() => {});
    const cards = await p.evaluate(() => [...document.querySelectorAll('.ch-res-metrics .me-stat')].map(e => e.className + ' | ' + e.innerText.replace(/\n/g, ' / ')));
    const problems = await p.evaluate(`(${AUDIT})()`);
    res.push({ name, cards, problems });
    const box = p.locator('.ch-res-summary').first();
    if (await box.count()) {
      await box.scrollIntoViewIfNeeded();
      const bb = await box.boundingBox(); const y = await p.evaluate(() => scrollY);
      await p.screenshot({ path: path.join(OUT, `f1_${name}_current_result_${label}.png`), fullPage: true,
        clip: { x: Math.max(0, bb.x - 8), y: bb.y + y - 8, width: Math.min(w, bb.width + 16), height: bb.height + 16 } });
    }
  }
  await b.close();
  console.log(JSON.stringify(res, null, 1));
  process.exit(res.every(r => r.cards.length === 4 && r.problems.length === 0) ? 0 : 1);
})().catch(e => { console.error(e); process.exit(2); });
