// Creates and onboards the two viewer accounts used by the Stage E browser checks.
const fs = require('fs');
const path = require('path');
const { chromium, ROOT, createUser, signIn } = require('./lib');
(async () => {
  const browser = await chromium.launch();
  const out = {};
  for (const tag of ['you', 'pat']) {
    const u = await createUser(tag);
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await signIn(page, u);
    out[tag] = u;
    await ctx.close();
  }
  fs.mkdirSync(path.join(ROOT, 'tmp/e2e_6c5'), { recursive: true });
  fs.writeFileSync(path.join(ROOT, 'tmp/e2e_6c5/accounts.json'), JSON.stringify(out, null, 1));
  console.log('accounts:', Object.values(out).map(u => u.username).join(', '));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
