// Creates and onboards the two viewer accounts ("you" and "pat") through the real
// sign-in flow of the local app (disposable p7_e2e database, local Supabase Auth).
const fs = require('fs');
const path = require('path');
const { chromium, DATA, createUser, signIn } = require('./lib');
(async () => {
  const browser = await chromium.launch();
  const out = {};
  for (const tag of ['you', 'pat']) {
    const u = await createUser(tag);
    const ctx = await browser.newContext();
    await signIn(await ctx.newPage(), u);
    out[tag] = u;
    await ctx.close();
  }
  fs.mkdirSync(DATA, { recursive: true });
  fs.writeFileSync(path.join(DATA, 'accounts.json'), JSON.stringify(out, null, 1));
  console.log('accounts:', Object.values(out).map(u => u.username).join(', '));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
