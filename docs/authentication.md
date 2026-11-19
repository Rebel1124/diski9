# Authentication, accounts and permissions (Phase 6C.2)

**Status:** implemented on `feature/phase-6c2-authentication`; not merged or
deployed. Supabase Auth proves who someone is; Diski 9 keeps its own user IDs,
roles, entitlements, usernames, privacy settings and server-side sessions
(D-01, D-34). Facts about Supabase were checked against the official
documentation on 19 November 2026 and against a real Supabase Auth server
(v2.198.0) in tests.

## 1. Selected flow and rationale (Stage A)

| Concern | Decision | Why |
|---|---|---|
| Client library | The official Supabase Python auth client (`supabase-auth`, part of supabase-py), server-side only, a fresh client per call (`persist_session=False`, `auto_refresh_token=False`) | A supported Supabase interface; no tokens kept in process memory between requests; the rest of Diski 9 depends only on a provider-neutral adapter (`diski9.backend.auth.provider`) |
| Registration | Email and password `sign_up` from the server; Supabase sends a confirmation email | Passwords pass through the server to Supabase over HTTPS and are never stored or logged by Diski 9 |
| Email verification and recovery links | Custom templates linking to `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email` (or `type=recovery`), verified server-side with `verify_otp` | Supabase's documented pattern for server-rendered apps. Unlike the PKCE `?code=` flow, it works when the link is opened on another device or browser (no code verifier to store). Links go to the Site URL, never to a caller-supplied address |
| Link scanners (T-17, approved) | `GET /auth/confirm` shows a "Confirm" button; only the `POST` consumes the single-use token | Email security scanners that pre-fetch links cannot use the token first |
| Sign-in | `sign_in_with_password` from the server; unverified addresses are refused (`email_not_confirmed`) | Only verified identities become Diski 9 accounts |
| Access-token validation | `get_claims` with a cached JWKS (ES256/RS256 asymmetric signing keys; at most 10 minutes, refreshed on an unknown key ID for rotation), **plus** checks `get_claims` does not make: allowed algorithm, issuer, audience `authenticated`, role `authenticated`, not anonymous, subject is a UUID | `get_claims` verifies signature and expiry only. HS256 tokens (legacy secret) are verified by the Auth server itself, never with a local secret |
| Key rotation | Standby keys appear in the JWKS before use; an unknown `kid` triggers one JWKS refresh (at most every 30 seconds) | Follows Supabase's rotation guidance (wait at least 20 minutes after creating a standby key or revoking a previous one) |
| Refresh tokens | Kept server-side, encrypted (Fernet), rotated under a row lock when the access token is within 5 minutes of expiry | Refresh tokens are single use; the lock stops two concurrent requests reusing one (tested) |
| Session revocation | Supabase `sign_out` with scope `local` (sign-out), `global` (sign out everywhere) or `others` (after a password change); the app session is revoked at the same time | Access tokens stay valid until expiry after sign-out, so the app session, not the token, is what the browser holds |
| Detecting provider-side revocation | The refresh fails (`refresh_token_not_found`, `session_not_found`, banned or deleted user) and the app session is revoked; privileged operations call `get_user` first and fail closed | Only `get_user` or a refresh can see a session ended at Supabase; `get_claims` cannot |
| Application sessions | Diski 9's own server-side sessions (`app.app_sessions`): opaque 256-bit token in an HttpOnly cookie, only its SHA-256 hash stored | Provider-independent, revocable immediately, immune to token-replay from a database leak |
| Cookies | `__Host-d9_session` with Secure, HttpOnly, SameSite=Lax, Path=/ in production (`d9_session` without Secure on http://localhost) | `__Host-` forbids Domain attributes and requires Secure |
| CSRF | A token on every form (HMAC of the session hash, or of a short-lived SameSite=Strict cookie for guests) and an Origin/Referer check on every state-changing request that carries a session cookie, including Dash callbacks | Dash callbacks are POST requests to the same server |
| Redirects | `next` accepts only same-site relative paths (`/...`, not `//`, schemes or backslashes); Supabase's redirect allow list holds exact URLs only (`/auth/confirm`) | Prevents open redirects |
| Identity mapping | `user_identities (provider, subject)` maps to an internal UUID created on first verified sign-in, under a transaction-scoped advisory lock and a unique key | Idempotent and race-free (tested with six concurrent sign-ins); internal IDs differ from provider IDs |
| Privileged keys | The publishable (anon) key is used server-side; the service-role / secret key is not used by the web app at all | Nothing privileged can reach a browser |

## 2. Local and hosted development (Stage B)

### 2.1 Recommended layout

* **Production (future):** one Supabase project. Supabase manages `auth`,
  `storage` and its other schemas; Diski 9's Alembic migrations own only schema
  `app`. The football store stays SQLite during Phase 6C (D-39).
* **Local development on a Mac:** the Supabase CLI stack (`supabase start`)
  provides Auth, its email inbox and PostgreSQL 17 on port 54322. Point
  `DISKI9_APP_DATABASE_URL` at that database so local development mirrors
  production (one database, `auth` plus `app`).
* **Docker Compose PostgreSQL (port 5432)** stays as the lightweight option for
  backend-only work and is what CI uses for the schema tests. Ports do not clash
  (Supabase uses 54320–54329). Migration ownership never overlaps: Supabase CLI
  migrations are not used for `app`, and Alembic never touches `auth`.

### 2.2 Local development on a Mac (exact commands)

For the full product-owner acceptance walkthrough (registration, emails,
recovery, account settings, guest drafts, account switching, owner bootstrap,
tests, stopping and restarting) see
[`phase6c2_local_acceptance_mac.md`](phase6c2_local_acceptance_mac.md). That guide
keeps Diski 9's data in the existing PostgreSQL container and uses the CLI stack
only for Supabase Auth; the commands below instead use the stack's database for
everything.

Prerequisites: Homebrew, a Docker-compatible runtime (OrbStack is recommended by
Supabase; Docker Desktop also works) and `uv`.

```bash
brew install supabase/tap/supabase
```

```bash
cd diski9
```

```bash
supabase gen signing-key --algorithm ES256 > supabase/signing_keys.json
```

```bash
supabase start
```

`supabase status` then shows the API URL, the database URL and the anon
(publishable) key. Put them in your untracked `.env`:

```bash
uv run diski9 account generate-keys >> .env
```

Then edit `.env` so that it contains:

```
DISKI9_APP_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres
DISKI9_SUPABASE_AUTH_URL=http://127.0.0.1:54321/auth/v1
DISKI9_SUPABASE_PUBLISHABLE_KEY=<anon key from supabase status>
DISKI9_APP_SITE_URL=http://127.0.0.1:8050
```

Create the runtime role once, migrate and run:

```bash
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres -c "CREATE ROLE diski9_app NOLOGIN"
```

```bash
uv run diski9 app-db upgrade
```

```bash
uv run diski9 serve
```

Open http://127.0.0.1:8050, create an account, and read the confirmation email in
the local inbox at http://127.0.0.1:54324. Stop the stack with `supabase stop`.

If `supabase start` rejects a configuration key, your CLI version predates it:
update the CLI (`brew upgrade supabase`) or remove that line from
`supabase/config.toml` (`signing_keys_path` and `[local_smtp]` are the newest).

**Automated genuine integration tests** read emails from files written by the
Diski 9 mail capture, so they use the harness in 2.3 (which also works on a Mac).
With the CLI stack, test the email flows by hand in the Mailpit inbox.

### 2.3 Local Supabase Auth without Docker (used in this build environment and CI)

`tools/local_auth/local_auth.py` runs the **official Supabase Auth server** (built
from the `supabase/auth` source at tag v2.198.0, or copied from the official
`supabase/gotrue` image in CI) against local PostgreSQL, with a local SMTP
capture and the same email templates. It is a genuine Supabase Auth server but
not the full CLI stack (no Studio, Data API or Realtime).

```bash
uv run python tools/local_auth/local_auth.py prepare --admin-url postgresql://postgres@127.0.0.1:5432/postgres
```

```bash
uv run python tools/local_auth/local_auth.py run --gotrue /path/to/supabase-auth-binary --auth-db-url postgres://supabase_auth_admin:local-auth-only@127.0.0.1:5432/diski9_auth_local
```

It writes the test settings to `tmp/local_auth/env` (git-ignored). Load them and
run the tests:

```bash
set -a; . tmp/local_auth/env; set +a; uv run pytest -q tests/backend
```

### 2.4 Hosted development project (optional, not yet done)

A hosted Free project is optional extra validation; nothing in Phase 6C.2 needs
it. If you want it:
1. Create a Free project in the Supabase dashboard (no payment details needed).
2. Authentication: enable email confirmations; set the Site URL to
   `http://127.0.0.1:8050`; add `http://127.0.0.1:8050/auth/confirm` to Redirect
   URLs; paste the two templates from `supabase/templates/` into the
   Confirmation and Reset password email templates; create an ES256 signing key
   and rotate to it; leave anonymous sign-ins off.
3. Keep the anon/publishable key and the session-pooler connection string in
   your local `.env` only. Do not send them to anyone, and never commit them.
4. Run `uv run diski9 app-db upgrade` against it (as the `postgres` user) after
   creating the `diski9_app` role.

The built-in email sender of a Free project sends only 2 emails an hour to team
addresses; a custom SMTP provider is needed before any beta.

### 2.5 Supabase PostgreSQL compatibility

| Area | Finding | Evidence |
|---|---|---|
| PostgreSQL version | Schema uses nothing newer than PostgreSQL 13; CI uses 17; tested on 16 and 17. Set the CLI `major_version` to match the hosted project | CI, local tests |
| Separate `app` schema | Supported; Supabase exposes only `public` (and `graphql_public`) by default. Migration `app_0002` revokes everything on `app` from `PUBLIC`, `anon` and `authenticated`, and enables row-level security on every table with a policy only for `diski9_app` | `test_backend_supabase_db.py` |
| Data API, GraphQL, Realtime | Not exposed: browser roles have no `USAGE` on `app`; GraphQL follows the same privileges; Realtime needs a table in the `supabase_realtime` publication (none are added) | same |
| Supabase-managed schemas | Never touched: migrating `app` into a database holding a real Supabase `auth` schema leaves `auth` unchanged (fingerprint compared before, after and after downgrade) | `test_migrations_coexist_with_supabase_auth_schema` |
| Roles | Supabase's `postgres` role is not a superuser but owns new objects and can create roles; triggers, row-level security and policies work. Create `diski9_app` (NOLOGIN) before migrating, then a login user granted it for the application | design |
| Insert-only triggers | Plain PL/pgSQL triggers; unaffected | 6C.1 tests |
| Runtime and migration identities | Migrations as `postgres` (owner, bypasses row-level security); the app as a login user in `diski9_app` (row-level security policy, no UPDATE/DELETE on history) | tests |
| Connection method | Use a **direct connection** or Supabase's **session pooler** (port 5432) for the long-running app; both keep session settings. The **transaction pooler** (port 6543) is supported with `DISKI9_APP_POOLER_MODE=transaction`: settings are applied per transaction and prepared statements are disabled | `test_transaction_pooler_mode_keeps_settings_and_clock` |
| Transaction-level locking | `FOR UPDATE`, `FOR SHARE` and `pg_try_advisory_xact_lock` live inside a transaction, so they work through any pooler; no session-level advisory locks are used | tests |
| Database-clock deadlines | `transaction_timestamp()` works identically | tests |

## 3. Registration and account lifecycle (Stage C)

1. **Sign up** (email, password of 10 to 72 characters). The response is the same
   whether or not the address already exists.
2. **Confirm** via the emailed link (click "Confirm email"). The first verified
   sign-in creates the Diski 9 user idempotently.
3. **Finish set-up:** username, an 18+ declaration and acceptance of the current
   terms version (`beta-2026-11`, `docs/legal/terms-beta-2026-11.md`, a draft
   pending legal review). Until then, no participant capability is available.
4. **Sign in / sign out / sign out everywhere**, **forgotten password** (generic
   response; reset link; new password; other sessions ended), **change password**
   (requires credentials within 15 minutes).
5. **Suspended or deleted accounts** cannot use any session (checked on every
   request) or sign in. Suspension is a server-side command, audited.
6. **No deletion action** yet: D-36 (retention and anonymisation policy) is
   outstanding; the settings page says so.

Personal data collected: email address (private, for sign-in and recovery), the
age declaration and the terms version accepted. Nothing else.

**Abuse controls:** Supabase's own rate limits (sign-ups and sign-ins per IP,
emails per hour, token refreshes, verifications), plus application limits
(sign-in 20 per 15 minutes per IP and 8 per email address; sign-up 5 per hour per
IP; recovery 10 per hour per IP and 3 per address; confirmation 30 per 15
minutes per IP; re-authentication 6 per 15 minutes per account), stored as keyed
hashes. CAPTCHA (hCaptcha or Turnstile, supported by Supabase) is recommended
before public launch. Behind a proxy, set `DISKI9_APP_TRUSTED_PROXIES`, and
consider Supabase's `Sb-Forwarded-For` so its per-IP limits see real client
addresses rather than the server's.

## 4. Usernames and leaderboard privacy (Stage D)

* 3 to 24 characters: letters, digits, spaces, dots, underscores or hyphens;
  starts and ends with a letter or digit; no repeated separators; ASCII only (so
  no look-alike characters).
* Unique ignoring case (database `UNIQUE (username_key)`; concurrent claims:
  exactly one wins, tested).
* Reserved names (Diski 9, admin, owner, operator, Lucy, anonymous, ...) and an
  offensive-word list, with common character substitutions; strong slurs match
  anywhere, other words only as whole words (so "Grapes" is fine). The full
  moderation list belongs outside the code before launch; operators can rename
  with a reason.
* One normal change every 30 days (the set-up choice does not count); every name
  kept in `username_history`.
* A stable random alias ("Anonymous 123456") is created at set-up, never derived
  from account data, and can never be claimed as a username.
* **Anonymity:** public or anonymous display. "Also hide my past entries"
  applies anonymity retroactively to entries locked before that moment; switching
  back to public affects only later entries, so historical anonymity is never
  removed. Leaderboards will use `leaderboard_name()`, which returns only the
  name recorded at lock or the alias, never an email address or ID. Persistent
  leaderboards themselves come in Phase 6C.5.

## 5. Sessions and re-authentication (Stage E)

| Rule | Value | Enforcement |
|---|---|---|
| Idle lifetime (participants) | 14 days | Database clock on every request; extended at most every 5 minutes |
| Absolute lifetime | 30 days | Fixed at sign-in; rotation keeps it |
| Operator recency | Sign-in (or re-authentication) within 12 hours | `authorize()` for every operator capability |
| Sensitive operations (T-14, approved) | Password re-entered within **15 minutes** | `authorize()` for: changing roles or entitlements, overriding results, invalidating rounds, reopening frozen championships, suspending accounts; also changing the password |
| Provider compatibility | Access tokens last 1 hour; the app refreshes them when within 5 minutes of expiry (so a provider-side revocation ends the app session within about an hour), and checks the provider directly before any privileged operation (fail closed) | `SessionManager.resolve`, `verify_with_provider` |
| Rotation | New session token at sign-in, re-authentication and password change; the old token stops working immediately | tests |
| Fixation | A cookie presented before sign-in is never promoted | tests |
| Logout | App session revoked, provider session signed out, cookie removed, `Clear-Site-Data: "storage"` and a script clear the tab's prototype state | tests |

The privileged recency requirement is deliberately separate from participant
sessions: a participant can stay signed in for up to 30 days, but nothing
privileged or sensitive works on an old sign-in.

**Provider-side versus application-side revocation (T-16, approved with
safeguards).** Diski 9 holds its own server-side session, so there are two
places a session can be ended:

| Revocation | Where it happens | When it takes effect | Tested in |
|---|---|---|---|
| Sign-out (this device) | Application session revoked, then the Supabase session signed out | Immediately: the cookie no longer resolves, even if replayed | `test_sign_out_revokes_session_clears_cookie_and_browser_state` |
| Sign out everywhere; password change | All application sessions revoked; Supabase `global` / `others` sign-out | Immediately on every device | `test_sign_out_everywhere_ends_other_devices`, `test_password_change_requires_recent_reauthentication_and_rotates` |
| Account suspension by an operator or owner | Application (`users.status`, sessions revoked) | Next request | `test_operator_suspension_ends_the_session_immediately`, `test_suspended_account_session_stops_working` |
| Role or entitlement revoked | Application (`user_roles`, `entitlement_grants`) | Next protected operation, same session, no re-sign-in needed: permissions are loaded from the database on every request | `test_role_and_entitlement_revocations_apply_to_the_next_request` |
| Revoked at Supabase (ban, deleted user, sign-out from another Supabase client) | Provider | Privileged operations: immediately (the provider is checked first and the check fails closed). Ordinary participant browsing: at the next provider refresh, within about an hour (accepted in T-16) | `test_operator_route_and_sensitive_reauth`, `test_privileged_check_fails_closed_when_provider_is_down`, `test_full_web_flow_against_real_supabase_auth` |

Supabase's access tokens last an hour and cannot be recalled, which is why the
application session, not the token, is what the browser holds.

## 6. Roles and entitlements (Stage F)

* **Roles:** participant (implicit for every active, onboarded account), operator,
  owner (`app.user_roles`). **Entitlements:** independent features
  (`app.entitlement_grants`), seeded as `lucy.research`, `lucy.voice`,
  `lucy.presenter`; a premium participant could hold one without any role.
* **Deny by default:** capabilities come only from database rows loaded for the
  server-side session. Browser input, profile fields and provider metadata (for
  example `user_metadata` or `app_metadata`) are never consulted.
* **Checks** (`diski9.backend.auth.permissions` and `web`): `authorize()` and
  `requires()` for services and future agent tools; `require()` for Flask routes;
  `authorize_callback()` for Dash callbacks; `require_feature()` for entitlements.
* **Owner bootstrap:** `uv run diski9 account bootstrap-owner --email <verified address> --confirm`
  on the server; it works only while no owner exists, for an active account that
  has finished set-up, and grants the Lucy entitlements. Afterwards only an
  existing owner can grant or revoke roles and entitlements
  (`grant-role`, `revoke-role`, `grant-feature`, `revoke-feature`, each with
  `--by-email` and `--reason`); the last owner cannot be removed. There is no web
  route for any of this. Every change is audited in `app.audit_log`.

## 7. Guest and account access (Stage G)

| Capability | Guest | Signed in (set-up incomplete) | Participant |
|---|---|---|---|
| Match Lab and statistics | Yes | Yes | Yes |
| Your View analysis (this browser tab) | Yes | Yes | Yes |
| Browse the Weekly Challenge; build and analyse a draft | Yes | Yes | Yes |
| Prototype confirm, replace, withdraw (this browser tab only) | Yes | Yes | Yes |
| Public leaderboard information (demonstration data today) | Yes | Yes | Yes |
| Account settings, privacy, password, sign out everywhere | No | Set-up page only | Yes |
| Persist Your View and drafts; competitive entries; history | Phase 6C.3 | Phase 6C.3 | Phase 6C.3 (needs participant capabilities) |

**Guest drafts at sign-in and sign-out (shared-device safety):**
* Prototype state (`ch-session`, `ch-prefs`, `lab-store`) lives only in the
  browser tab and is never sent to the server or attached to an account.
* **Sign-in or registration (T-15, approved):** if the tab holds guest work (a
  Weekly Challenge draft or prototype entry, or Your View adjustments), the first
  Diski 9 page after signing in asks **"Keep the analysis you did as a guest?"**
  with **Keep in this tab** and **Discard**. Keeping leaves the work in this tab
  only: it is not saved to the account and nothing is submitted. Discarding
  clears it. Until a choice is made the question returns on every page load.
  With no guest work, nothing is asked. Screenshot `18_guest_draft_choice.png`.
* **Sign-out:** the tab state is **cleared**.
* **Account switching:** each page carries an opaque owner marker (an HMAC of the
  user ID, never the ID itself). If a different account signs in in the same tab,
  the previous account's tab state is cleared before the page reloads.
* The prototype wording ("kept only in this browser tab", "not an official
  entry") is unchanged, so a signed-in user's prototype entry is never presented
  as a persistent competitive submission.

**What Phase 6C.3 adds (not built in 6C.2):** a "save this draft to my account"
action for kept work (adoption); never overwriting a portfolio the account
already stores without an explicit choice; revalidating an adopted draft against
the current eligible round and its frozen snapshot (dropping or flagging
selections that are no longer eligible); no automatic submission; and private
server-side Your View storage (T-10). Phase 6C.2 has no stored portfolios, so
there is nothing that could be overwritten yet.

## 8. Account interface (Stage H)

Server-rendered pages on the same Flask server as Dash, in the existing design
language, with no emojis: sign up, sign in, check email, confirm, finish set-up,
account settings (username, privacy, password, sign out everywhere), forgotten
password, new password, re-authentication, sign-out confirmation, and the draft
beta terms. The site navigation shows "Sign in" and "Create account" for guests
and a username menu for members. Screenshots:
`docs/screenshots/phase6c2_accounts/` (desktop and iPhone; no horizontal
scrolling).

## 9. Tests: what is mocked and what is real

| Module | Database | Identity provider |
|---|---|---|
| `test_backend_auth_unit.py` | none | none (pure logic) |
| `test_backend_accounts.py` | real PostgreSQL | **mock** (`FakeProvider`) |
| `test_backend_auth_web.py` | real PostgreSQL | **mock** (`FakeProvider`) |
| `test_backend_supabase_db.py` | real PostgreSQL, plus a database holding a real Supabase `auth` schema when configured | none |
| `test_backend_supabase_local.py` | real PostgreSQL | **real Supabase Auth server** (local harness or CLI stack) |
| `tests/test_account_tab_state.py` (browser tab state: guest choice, account switching, sign-out) | none | none (the real `account.js` in Chromium) |
| Browser walkthrough (screenshots) | real PostgreSQL | **real Supabase Auth server** |
| Hosted Supabase | not run (needs a project created by the product owner) | |

## 10. Known limitations

* Google sign-in is deferred (configuration placeholder only).
* No account deletion until D-36 is decided.
* A provider-side revocation (ban, password change elsewhere) reaches ordinary
  browsing within about an hour; privileged operations check immediately.
* No CAPTCHA yet; recommended before public launch.
* The final terms, age requirements and privacy wording need legal review before
  launch.
* The application development server (`diski9 serve`) is not a production
  server; deployment is Phase 10.
