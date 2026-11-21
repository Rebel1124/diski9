// Phase 6C.5 Stage F3: COUNT throw-away accounts on the LOCAL Supabase Auth server,
// onboarded through the real sign-in flow on an app pointed at an F3 benchmark
// database, for the concurrent HTTP readers. Passwords stay in the git-ignored tmp/.
//   E2E_DIR=tmp/f3/n1000 BASE=http://127.0.0.1:8060 E2E_DB=diski9_f3_n1000 COUNT=20 \
//     NODE_PATH=$(npm root -g) node tools/e2e_6c5/f3_accounts.js
const fs = require('fs'), path = require('path');
const { chromium, DATA, createUser, signIn } = require('./lib');
(async () => {
  const out = {}, b = await chromium.launch();
  for (let i = 0; i < Number(process.env.COUNT || 20); i++) {
    const u = await createUser(`r${String(i).padStart(2, '0')}`);
    const ctx = await b.newContext(); await signIn(await ctx.newPage(), u); await ctx.close();
    out[`r${i}`] = u;
  }
  await b.close();
  fs.mkdirSync(DATA, { recursive: true });
  fs.writeFileSync(path.join(DATA, 'accounts.json'), JSON.stringify(out, null, 1));
  console.log('accounts:', Object.keys(out).length);
})().catch(e => { console.error(e); process.exit(1); });
