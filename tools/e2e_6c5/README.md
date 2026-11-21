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

## Phase 6C.5 Stage F1 scripts (local development only)
These need a dedicated development database (`diski9_f1_e2e` on the test server, at
`app_0007`), `tmp/f1/serve.env` (as `serve.env`, but with that database and port
8053) and the local Supabase Auth harness.

| Script | What it does |
|---|---|
| `f1_env.py` | Shared settings: reads `tmp/f1/serve.env` and `tmp/f1/accounts.json` |
| `f1_accounts.js` | Creates two throw-away local accounts and onboards them through the real sign-in flow. Make the first the owner with `account bootstrap-owner` |
| `f1_real_run.py` | Runs `dev-championship run --preset ten-round-complete` in a pseudo-terminal, typing the password at the hidden prompt. It sends SIGINT (what Ctrl-C delivers) in round 9, then resumes with the same command |
| `f1_current_steps.py settle` then `... finalise` | The documented CLI steps for a populated My Challenge Current result panel |
| `f1_current.js <label>` | Browser check of that panel at 1360 and 390 px: four statistics-style cards, layout audit, screenshots `f1_*_current_result_<label>.png` |

## Stage F2 (integration, browser acceptance)
Isolated databases `diski9_f2_e2e` and `diski9_f2_e2e_nochamp`; data folder
`tmp/f2` (`E2E_DIR=tmp/f2`). Servers: 8054 (development rounds shown), 8055 (the
no-champion database) and 8056 (the same database with development rounds hidden).
1. `E2E_DIR=tmp/f2 BASE=http://127.0.0.1:8054 E2E_DB=diski9_f2_e2e node accounts.js`.
2. `E2E_DIR=tmp/f2 uv run python tools/e2e_6c5/seed.py <url>`, then
   `seed_f2.py extra <url>` and `seed_f2.py nochamp <no-champion url>`.
3. `uv run python tools/e2e_6c5/f2_expect.py <url> <no-champion url>` writes the
   authoritative expectations from the read services.
4. `node tools/e2e_6c5/journeys.js`: the twelve §17.3 journeys at 1360, 768 and 390
   px, compared with the expectations, plus crafted-callback privacy replays, stream
   visibility, navigation, browser errors and a read-only check.
5. Current result states: `uv run python tools/e2e_6c5/f2_current.py <state>` then
   `node tools/e2e_6c5/f2_current.js <state>` for `refund`, `void`, `negative`,
   `review` and `corrected` in that order (re-run `f2_expect.py` afterwards before
   repeating step 4, since the new rounds join the current championship).
