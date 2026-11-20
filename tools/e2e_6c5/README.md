# Phase 6C.5 Stage E real-browser checks (local only)

Node Playwright scripts for the Leaderboards and My Challenge History pages, run
against the real app, PostgreSQL and the local Supabase Auth harness.

**Local development only:**
- The scripts create throw-away accounts on the *local* Supabase Auth server.
- Those accounts' passwords are kept in the git-ignored `tmp/e2e_6c5/accounts.json`.
- `seed.py` refuses any database whose name does not contain `e2e`.

## Steps
1. Create and migrate the showcase database:
   `diski9_e2e_6c5` on the test server, then `app-db upgrade`.
2. Run the local Supabase Auth harness:
   `uv run python tools/local_auth/local_auth.py run --gotrue <binary>`.
3. Start the app on port 8052 with `tmp/e2e_6c5/serve.env` loaded. That file holds
   the development keys, the showcase database URL, `DISKI9_APP_SITE_URL` set to
   port 8052, and `DISKI9_SHOW_DEVELOPMENT_ROUNDS=1`.
4. `NODE_PATH=$(npm root -g) node tools/e2e_6c5/accounts.js` creates and onboards
   the two viewer accounts through the real sign-in flow.
5. `uv run python tools/e2e_6c5/seed.py postgresql+psycopg://…/diski9_e2e_6c5`
   builds the scenario through the real services; its docstring lists it.
6. `NODE_PATH=$(npm root -g) node tools/e2e_6c5/shots.js` runs the checks.

## What `shots.js` checks
It covers the guest and signed-in views at desktop (1360), tablet (768) and mobile
(390) widths. On each page it checks:
- no page-wide horizontal overflow;
- no console or page errors;
- no e-mail address or UUID in the page text or element ids;
- that page loads wrote nothing (row counts before and after).

It writes screenshots to `docs/screenshots/phase6c5/`.

## `refined.js` (owner-requested refinements)
`NODE_PATH=$(npm root -g) node tools/e2e_6c5/refined.js`

It runs at 1360, 768, 430, 390, 360 and 320 px. Its checks are element-level, so they
do not rely on the page's scroll width alone:
- elements outside the viewport;
- text overflowing its box;
- card cells outside their card or overlapping another cell;
- tables that scroll sideways;
- touch targets under 32 px.

It also repeats the guest prompt, privacy and read-only checks above. A stress pass
injects a 24-character name, seven-figure values and the maximum points, then repeats
the element checks.

It writes screenshots to `docs/screenshots/phase6c5/refined/` and its results to the
git-ignored `tmp/e2e_6c5/refined_results.json`. The second viewer (`pat`) has a
24-character account name in the showcase database.
