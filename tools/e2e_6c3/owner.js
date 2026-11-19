const L = require('./lib'); const fs = require('fs');
(async () => {
  const browser = await L.chromium.launch();
  const u = await L.createUser('owner');
  const p = await (await browser.newContext()).newPage();
  await L.signIn(p, u);
  fs.writeFileSync(require('path').resolve(__dirname, 'owner.json'), JSON.stringify(u));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
