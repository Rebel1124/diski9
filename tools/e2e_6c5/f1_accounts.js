// F1: two throw-away accounts on the LOCAL Supabase Auth server, onboarded through the
// real sign-in flow on the F1 development app (port 8053). Passwords stay in tmp/ (git-ignored).
process.env.BASE = 'http://127.0.0.1:8053'; process.env.E2E_DB = 'diski9_f1_e2e';
const fs = require('fs');
const { chromium, createUser, signIn } = require('/home/user/diski9-6c5/tools/e2e_6c5/lib');
(async () => {
  const out = {};
  const b = await chromium.launch();
  for (const tag of ['f1own', 'f1me']) {
    const u = await createUser(tag);
    const p = await (await b.newContext()).newPage();
    await signIn(p, u);
    out[tag] = u;
  }
  await b.close();
  fs.writeFileSync('/home/user/diski9-6c5/tmp/f1/accounts.json', JSON.stringify(out));
  console.log('accounts ready');
})().catch(e => { console.error(e); process.exit(1); });
