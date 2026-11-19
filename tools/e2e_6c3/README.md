# Phase 6C.3 real-browser journeys (local only)

Node Playwright scripts used for the Phase 6C.3 acceptance journeys. **Local
development only**: they create throw-away accounts on the *local* Supabase Auth
server (admin API with the local service-role key from `tmp/local_auth/env`, never
committed) and clear the sign-in rate-limit counters of the local e2e database
(`diski9_e2e`) before each sign-in, because many test sign-ins from one address
reach the real limit (20 per 15 minutes).

Prerequisites:
1. PostgreSQL with a migrated `diski9_e2e` database (`app-db upgrade` with
   `DISKI9_APP_DATABASE_URL` pointing at it).
2. Local Supabase Auth: `.venv/bin/python tools/local_auth/local_auth.py run --gotrue <binary>`.
3. The app: `DISKI9_APP_DATABASE_URL=…/diski9_e2e DISKI9_SHOW_DEVELOPMENT_ROUNDS=1 uv run diski9 serve`
   (with the keys in `tmp/dev/serve.env`). Run long-lived servers with a long
   background limit: a 30-minute limit stopped the server once mid-journey.
4. `node owner.js`, then `diski9 account bootstrap-owner --email <owner.json email> --confirm`
   and `diski9 round dev-open --by-email … --mirror-upcoming --deadline-minutes 600`.

Run with `NODE_PATH=$(npm root -g) node <script>`:
* `journey_g.js` — Journeys G (live versus frozen Your View) and A (returning participant);
* `journeys.js` — Journeys B (cross-device conflict), C (confirm, replace, withdraw,
  re-enter), D (guest adoption, with and without existing account work), F (account isolation);
* `journey_e.js` — Journey E (short round, five confirmations through the UI, early
  lock refused, lock → competitive, idempotent). Only one open round should have a
  deadline ahead earlier than the mirrored round, or the short round's timing
  interferes.

Screenshots go to `docs/screenshots/phase6c3/`.
