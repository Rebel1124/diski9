# Phase 6C.2 implementation handover (context checkpoint)

**Written:** 19 November 2026, at the owner-requested context checkpoint.
**Purpose:** let a fresh context resume Phase 6C.2 exactly where it stopped. It
references the authoritative documents rather than repeating them. No
credentials, keys or tokens appear here.

## 1. Repository state

| Item | Value |
|---|---|
| Working branch | `feature/phase-6c2-authentication` (branched from Phase 6C.1 `9821c1e` after a 1,006-test baseline passed) |
| Phase 6C.2 commits | `eb22954` Stage A/B (adapter, harness, migration app_0002) · `f96c095` Stage C-F (accounts, sessions, permissions, CLI) · `9f02d07` Stage G/H (pages, menu, isolation, screenshots) · `ec83559` tests, Supabase compatibility, CI, docs · this handover commit |
| Other branches (do not modify) | `main` = `0286fa8` (release v4.0.0; tag still to be pushed by the owner); `feature/phase-6c1-postgres-foundation` = `9821c1e`; `research/weekly-pools` = `2f4c118`; odds trial `claude/gifted-newton-h6o5hk` |
| Not to do | No merge to main, no tag, no deployment, no Phase 6C.3 work |

## 2. Objectives and acceptance criteria

The owner's Phase 6C.2 brief (in the conversation; summarised in
[`docs/authentication.md`](../authentication.md) and the decision register) covers:
Stage A integration design; Stage B local/hosted development and Supabase
PostgreSQL compatibility; Stage C registration and account lifecycle; Stage D
usernames and privacy; Stage E sessions and security; Stage F roles and
entitlements; Stage G guest versus authenticated access; Stage H account
interface; recommended tests (section 12 of the brief); a 17-item completion report
(section 14 of the brief, reproduced in section 10 below).

Architecture confirmed by the owner: Python/Dash modular monolith, Supabase Auth,
Supabase-hosted PostgreSQL for future production, local PostgreSQL and local
Supabase for development, SQLAlchemy 2, Alembic, provider-independent identities,
roles and entitlements. Hosting undecided until Phase 10. No AWS Cognito/RDS, no
paid infrastructure, no Lucy/LiveKit/premium, no Phase 6C.3.

## 3. Status by stage

| Stage | Status | Where |
|---|---|---|
| A — integration design | **Done** | `docs/authentication.md` §1 |
| B — local/hosted development, compatibility | **Done** (hosted project not tested: needs an owner-created Free project) | `docs/authentication.md` §2; `supabase/config.toml`; `tools/local_auth/`; `tests/backend/test_backend_supabase_db.py` |
| C — registration and lifecycle | **Done** | `backend/auth/provider.py`, `accounts.py`, `web.py` |
| D — usernames and privacy | **Done** | `usernames.py`, `accounts.py` (`change_username`, `set_privacy`, `leaderboard_name`) |
| E — sessions and security | **Done** (15-minute sensitive re-auth implemented as proposed T-14) | `sessions.py`, `web.py`, `permissions.py` |
| F — roles and entitlements | **Done** | `permissions.py`, `privileged.py`, CLI `diski9 account ...` |
| G — guest/authenticated access | **Done** | `docs/authentication.md` §7; `assets/account.js`; `app/app.py` `account_menu()` |
| H — account interface | **Done**; screenshots in `docs/screenshots/phase6c2_accounts/` (17 images) | `backend/auth/templates/`, `assets/account.css` |
| Tests | **Done**: 221 backend/auth tests passing locally (incl. 10 genuine Supabase Auth and 7 compatibility tests) | `tests/backend/` |
| Full suite and CI | **Done after the checkpoint:** see section 11 | see section 11 |
| Completion report | **Delivered** to the owner after final validation | section 11 |

## 4. Key decisions (details in `docs/authentication.md`)

* **Supabase integration:** official `supabase-auth` Python client server-side,
  per-call clients; provider-neutral adapter `AuthProvider`
  (`backend/auth/provider.py`). Email links `/auth/confirm?token_hash=...&type=email|recovery`
  verified with `verify_otp` behind a confirm button; password sign-in; refresh
  rotation; sign-out scopes local/global/others.
* **Token verification:** `get_claims` with a cached JWKS plus issuer, audience,
  role (`authenticated`), subject, algorithm checks (`get_claims` alone checks only
  signature and expiry). HS256 is verified by the Auth server.
* **Sessions:** Diski 9 server-side sessions in `app.app_sessions` (hashed opaque
  tokens; 14-day idle; 30-day absolute; rotation; revocation reasons); provider
  tokens Fernet-encrypted and refreshed under a row lock when the access token is
  within 5 minutes of expiry; privileged checks call the provider and fail closed.
* **Protections:** CSRF tokens on forms; Origin check on every cookie-bearing
  state change (including Dash callbacks); safe relative `next`; strict CSP and
  no-store on account pages; app-side rate limits (`ratelimit.py`).
* **Authorisation:** `Principal` built per request from the database; deny by
  default; participant/operator/owner capability map; entitlements independent;
  12-hour operator recency; 15-minute re-authentication for sensitive operations.
* **Owner bootstrap:** `uv run diski9 account bootstrap-owner --email <verified> --confirm`
  works once; later changes need an existing owner via CLI; all audited.
* **Guest drafts:** retained in the tab at sign-in (not adopted), cleared at
  sign-out and on account switching (owner marker, an HMAC, never the user ID).
* **Proposals awaiting owner approval:** T-14 to T-17 in the decision register.

## 5. Database changes

Migration `migrations_app/versions/app_0002_authentication.py`: `app_sessions`
provider columns (`provider_session_id`, encrypted token columns,
`provider_access_expires_at`, `provider_checked_at`, `reauthenticated_at`,
`revoked_reason`); table `app.auth_rate_events` (append and purge); terms version
`beta-2026-11` (hash of `docs/legal/terms-beta-2026-11.md`); revoke all on `app`
from PUBLIC/anon/authenticated; row-level security on every `app` table with a
`runtime_access` policy for `diski9_app`. Mirror updated in
`backend/db/schema.py` (`APPEND_PURGE` kind). Never touches Supabase schemas.

## 6. Important files and patterns

* `src/diski9/backend/auth/`: `settings.py` (env `DISKI9_SUPABASE_*`,
  `DISKI9_APP_*`), `crypto.py`, `provider.py`, `sessions.py`, `accounts.py`,
  `usernames.py`, `permissions.py`, `privileged.py`, `ratelimit.py`, `web.py`
  (blueprint, hooks, guards `require`, `require_signed_in`, `authorize_callback`,
  `current_principal`), `templates/`.
* `src/diski9/app/app.py`: `create_app(data, auth=None)`, `account_menu()`
  (server-rendered from `flask.g`); `assets/account.css`, `assets/account.js`.
* `src/diski9/cli.py`: `serve` enables accounts when configured; `account` group.
* `src/diski9/backend/db/engine.py`: `pooler_mode` session/transaction.
* Tests: `tests/backend/auth_helpers.py` (`FakeProvider` mock, `make_settings`,
  `csrf_from`); test modules listed in `docs/authentication.md` §9.

## 7. Local services and processes at the checkpoint (this container only)

| Service | Details |
|---|---|
| PostgreSQL 16 | `127.0.0.1:5433`, data `/var/lib/postgresql/diski9-dev`, trust auth (dev only); databases `diski9_test`, `diski9_dev`, `diski9_auth_local`. Restart: `su postgres -s /bin/bash -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/diski9-dev -o '-p 5433 -k /var/run/postgresql -c listen_addresses=127.0.0.1' -l /var/lib/postgresql/diski9-dev.log start"` |
| Supabase Auth v2.198.0 | Built at `/home/user/supabase/gotrue-v2.198.0` from the `supabase/auth` source; run as a background task with `uv run python tools/local_auth/local_auth.py run --gotrue /home/user/supabase/gotrue-v2.198.0` on `127.0.0.1:9999` (SMTP capture 2500, templates 9998). Test settings in `tmp/local_auth/env` (git-ignored; local throwaway keys) |
| Diski 9 app | `uv run diski9 serve --port 8050` with `tmp/dev/serve.env` (git-ignored) loaded; accounts enabled |
| Note | Background processes do not survive a container restart; restart them with the commands above (start long-running ones as background tasks, not with `nohup &`) |

Scheduled processes (do not modify): odds trial (`trig_01T4GYs8Nma5ERz7NiEQpUhx`,
ends 21 Nov); weekly research capture `trig_01R8pEXhrpsehX82xPKZcY2Z` and results
`trig_01NBMtRe7Y3WhtibZ2ah6Cdq` in collector session `session_01G8XHfLBvJ245ZvKEBSqCJL`;
follow-up `trig_01NsZ4MAkCRJt8j1YJKVDeBj` on 26 Nov 07:30 UTC to verify the first
real capture and push.

## 8. Tests and open items

* Passing locally: 221 backend/auth tests (`tests/backend`, with
  `DISKI9_APP_TEST_DATABASE_URL`, `DISKI9_TEST_SUPABASE_*` from
  `tmp/local_auth/env`, `DISKI9_TEST_SUPABASE_DB_URL` = the `diski9_auth_local`
  database). Unit 63; accounts/sessions/privileged 27; web 39; Supabase DB 7;
  genuine Supabase Auth 10; plus the 6C.1 backend tests.
* **To confirm on resume:** the full suite result (`scratchpad/6c2_full.txt`, or
  rerun), and CI run 3 (`ec83559`): if CI fails, read the job log
  (`mcp__github__get_job_logs`) and fix. The CI Supabase step extracts the binary
  from `supabase/gotrue:v2.198.0` (path found with `command -v auth || command -v gotrue`);
  if the image layout differs, build from source with Go instead.
* Hosted Supabase Free project: not tested (needs the owner, section 9).

## 9. Known limitations and owner actions

* Google sign-in deferred; no account deletion until D-36; CAPTCHA recommended
  before launch; legal review of terms/age; provider-side revocation reaches
  ordinary browsing within about an hour (privileged checks immediate).
* **Owner actions:** (1) push the v4.0.0 tag (commands given earlier); (2) in the
  collector session, tell it directly to apply the stop-condition update (it
  refused a request from this session, correctly); (3) optionally create a hosted
  Free Supabase project (`docs/authentication.md` §2.4); (4) on the Mac, follow
  `docs/authentication.md` §2.2; (5) approve or amend T-14 to T-17.

## 10. Resume instructions

1. Read this file, `docs/authentication.md`, the decision register and the Phase
   6C plan (6C.2 notes).
2. `git fetch origin feature/phase-6c2-authentication && git checkout feature/phase-6c2-authentication && git pull`;
   confirm the head is this handover commit.
3. Check services (section 7); restart if needed.
4. Confirm the full suite and CI run 3; fix anything failing.
5. Then write the completion report covering the brief's 17 items: branch and
   commits; selected flow and rationale; local setup commands; hosted project
   requirements; compatibility findings; migrations; registration and account
   management; roles/entitlements/authorisation; session and re-auth policies;
   access matrix; screenshots; security and isolation test results; mock/local/
   hosted test distinctions; full test count and CI status; limitations and
   outstanding decisions; owner manual steps; readiness for 6C.3.
6. Return the local checkout to `claude/gifted-newton-h6o5hk` at the end, and stop
   for owner review.

## 11. Resolution after the checkpoint (19 November 2026)

* Full local suite at the checkpoint: 1,152 passed (PostgreSQL and real Supabase
  Auth). CI failures fixed: run 4 (the CI PostgreSQL image has no `postgres`
  role, which a Supabase Auth migration grants to; the harness now creates it);
  run 5 (all tests passed, but the background Auth server held uv's cache lock
  during the cache clean-up; it now runs with the project interpreter and is
  stopped at the end of the job).
* Owner decisions: T-14 to T-17 approved (T-15 and T-16 with additional
  requirements). Implemented: the T-15 keep/discard choice for guest work in the
  tab (`assets/account.js`, `tests/test_account_tab_state.py`, screenshot 18);
  explicit T-16 tests for role/entitlement revocation and suspension; T-17 check
  against the real server. Register, `docs/authentication.md` and the Phase 6C
  plan updated. The v4.0.0 tag was pushed by the owner.
* Local acceptance guide for the owner's Mac: `docs/phase6c2_local_acceptance_mac.md`.
