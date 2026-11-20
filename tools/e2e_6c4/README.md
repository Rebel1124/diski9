# Phase 6C.4 real-browser settlement journeys (local only)

Node Playwright scripts for the Stage G acceptance journeys, against the real app,
PostgreSQL and the local Supabase Auth harness. **Local development only**: they
create throw-away accounts on the *local* Supabase Auth server (admin API with the
local service-role key from `tmp/local_auth/env`), and keep those accounts'
passwords in the git-ignored `tmp/e2e_6c4/accounts.json`.

Operator commands run through `cli.py`, which starts the **real** `diski9` command
in a pseudo-terminal and types the account's password at the hidden prompt, exactly
as a person would (no bypass exists).

Prerequisites (as for `tools/e2e_6c3`):
1. PostgreSQL with `diski9_e2e` migrated to `app_0006` (`app-db upgrade`).
2. Local Supabase Auth: `uv run python tools/local_auth/local_auth.py run --gotrue <binary>`.
3. The app with development rounds shown, on port 8050, and the environment of
   `tmp/dev` loaded (`DISKI9_APP_DATABASE_URL=…/diski9_e2e DISKI9_SHOW_DEVELOPMENT_ROUNDS=1`).
4. `tools/e2e_6c3/owner.json` naming an owner of `diski9_e2e` (for `round dev-open`).

Run with `NODE_PATH=$(npm root -g) node tools/e2e_6c4/<script>` in a shell that has
the same `DISKI9_*` environment as the app:

* `journeys.js` — journeys 1–12 (confirm and lock; partial settlement; successful and
  unsuccessful accumulators; provisional result; individual D-33 refund; whole-round
  invalidation; correction; finalisation; owner-only reopening; a new round with the
  previous entry; sign-out and account switching; Market / Diski 9 / Your View
  analysis), with desktop, tablet and mobile captures, overflow and console checks,
  and a check that page reads write nothing. Five short rounds run one after another
  (about 35 minutes).
* `journey_current.js` — results in the current-round cards on a fresh database
  (`diski9_e2e_cur`, app on port 8051 with `DISKI9_APP_SITE_URL` set to it,
  `BASE=http://127.0.0.1:8051`), a correction shown after in-app navigation, and
  browser timings of My Challenge.

Screenshots go to `docs/screenshots/phase6c4/`.
