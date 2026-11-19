# Phase 6C.2 local acceptance testing on a Mac

Step-by-step product-owner testing of authentication, accounts and permissions on
a Mac with Docker Desktop and the Phase 6C.1 PostgreSQL 17 container already
working.

**Local, not hosted.** Everything here runs on your Mac: the real Supabase Auth
server from the Supabase CLI's local stack, your existing PostgreSQL container
for Diski 9's own data, and a local email inbox. No email leaves your machine and
no hosted Supabase project is used or needed. Hosted Supabase testing (section 13)
is a separate, later step.

**How the pieces fit**

| Piece | Where it runs | Port |
|---|---|---|
| Diski 9 application data (schema `app`) | Your existing PostgreSQL 17 container (unchanged, from `.env`) | 5432 |
| Supabase Auth (accounts, passwords, email links) and its own database | Supabase CLI local stack (Docker) | 54321 (API), 54322 (its database) |
| Local email inbox (Mailpit) | Supabase CLI local stack | 54324 |
| Diski 9 | `uv run diski9 serve` | 8050 |

The Supabase stack has its own PostgreSQL on port 54322, so it never conflicts
with your container on 5432. Do not point `DISKI9_APP_DATABASE_URL` at it: Diski 9
keeps using your existing database.

Passwords are stored only by Supabase Auth, never in the Diski 9 database.
Nothing below asks you to overwrite `.env`, print a secret or commit one.

---

## 1. Switch to the Phase 6C.2 branch

```bash
cd ~/path/to/diski9
```

```bash
git status
```

Commit or stash anything you want to keep, then:

```bash
git fetch origin feature/phase-6c2-authentication
```

```bash
git checkout feature/phase-6c2-authentication
```

```bash
git pull
```

## 2. Update Python dependencies

Phase 6C.2 adds the official Supabase Auth client (`supabase-auth`) and
`cryptography`.

```bash
uv sync
```

## 3. Install the Supabase CLI

```bash
brew install supabase/tap/supabase
```

If it is already installed, update it (the project's configuration uses newer
settings):

```bash
brew upgrade supabase
```

```bash
supabase --version
```

## 4. Start local Supabase Auth

The project already contains `supabase/config.toml` (local settings: email
confirmation on, links to `http://127.0.0.1:8050/auth/confirm`, local inbox,
password minimum 10 characters) and the two email templates.

Create a local asymmetric signing key (git-ignored, never committed):

```bash
supabase gen signing-key --algorithm ES256 > supabase/signing_keys.json
```

Check that the file holds a JSON key (it starts with `[` or `{`):

```bash
head -c 40 supabase/signing_keys.json; echo
```

Start the stack (the first start downloads images and takes a few minutes):

```bash
supabase start
```

If you only want what Phase 6C.2 needs, this lighter variant skips unused
services:

```bash
supabase start -x realtime,storage-api,imgproxy,edge-runtime,logflare,vector,supavisor
```

If `supabase start` reports an unknown configuration key, your CLI is older than
the configuration: run `brew upgrade supabase` again. As a last resort, delete the
`signing_keys_path` line from `supabase/config.toml` (the legacy shared-secret
signing then applies; Diski 9 verifies those tokens with the Auth server).

Check it is running:

```bash
supabase status
```

You should see the API URL `http://127.0.0.1:54321`, the database on 54322 and
the Mailpit inbox on `http://127.0.0.1:54324`.

## 5. Add the authentication settings to your `.env` (append only)

Make a backup copy first (your existing `.env` is not changed by this):

```bash
cp .env .env.backup-before-6c2
```

Append the local Supabase Auth URL and the site URL:

```bash
printf '\n# Phase 6C.2 local Supabase Auth (development only)\nDISKI9_SUPABASE_AUTH_URL=http://127.0.0.1:54321/auth/v1\nDISKI9_APP_SITE_URL=http://127.0.0.1:8050\n' >> .env
```

Append the local stack's publishable (anon) key straight from `supabase status`,
without printing it:

```bash
supabase status -o env | grep '^ANON_KEY=' | sed 's/^ANON_KEY=/DISKI9_SUPABASE_PUBLISHABLE_KEY=/' >> .env
```

Append two newly generated local keys (session signing and token encryption),
also without printing them:

```bash
uv run diski9 account generate-keys >> .env
```

Check that each setting is now present exactly once (this prints names only):

```bash
grep -oE '^DISKI9_(SUPABASE_AUTH_URL|SUPABASE_PUBLISHABLE_KEY|APP_SITE_URL|APP_SECRET_KEY|APP_TOKEN_ENCRYPTION_KEY)=' .env | sort | uniq -c
```

Every line should show `1`. If `DISKI9_APP_SITE_URL` shows `2` (your `.env` already
had it), remove one of the two lines by hand; both say the same thing.

Notes:
* The service-role key is not used by the web app at all; do not add it.
* These local keys are for your Mac only. A hosted project or a deployment gets
  its own keys later.

## 6. Run the new application database migration

Phase 6C.2 adds migration `app_0002` (provider-linked sessions, rate-limit events,
the beta terms version, row-level security). It changes only schema `app` in
your existing database.

```bash
uv run diski9 app-db upgrade
```

```bash
uv run diski9 app-db check
```

`check` should report `"schema_revision": "app_0002"` and `"up_to_date": true`.

## 7. Start Diski 9

```bash
uv run diski9 serve
```

Open **http://127.0.0.1:8050** (use `127.0.0.1`, not `localhost`: the site URL,
the email links and the browser-origin checks all use `127.0.0.1`). The navigation
bar now shows **Sign in** and **Create account** on the right. If they are missing,
the authentication settings in `.env` are not being picked up: check step 5.

Keep this terminal open; use a second terminal for the commands below.

## 8. Registration and verification emails

1. Click **Create account**. Enter any address (for example
   `alpha@example.test`; nothing is really sent) and a password of at least 10
   characters. Submit.
2. You see "Check your email". Open the inbox at **http://127.0.0.1:54324** and
   open "Confirm your Diski 9 account".
3. Click the link. A Diski 9 page opens with a **Confirm** button. Loading this
   page does not use the link (T-17): reload it a few times to check, then click
   **Confirm**.
4. You are signed in and asked to finish set-up: choose a username, confirm you
   are 18 or over and accept the beta terms. Try first with a reserved or
   offensive name (for example `admin`) and without ticking the boxes to see the
   validation messages, then complete it.
5. Open the confirmation email link again: it is refused (single use).
6. Try signing up again with the same address: the response is the same generic
   message (no account enumeration).

## 9. Sign-in, sign-out and password recovery

1. Use the username menu (top right): **Sign out**, then confirm. You are signed
   out; the page says so.
2. **Sign in** with a wrong password: a generic "email or password is incorrect"
   message. Then sign in correctly.
3. Sign out again. Click **Sign in**, then **Forgotten your password?** Enter
   your address. Open "Reset your Diski 9 password" in Mailpit, click the link,
   click **Confirm**, set a new password. Sign in with the new password; the old
   one no longer works.
4. Password recovery for an address that has no account gives the same response
   as for a real one.
5. Sign-out from another device: sign in in a second browser (or a private
   window) as the same user, then in the first browser open **Account settings**
   and choose **Sign out everywhere**. Reload the second browser: it is signed out.

## 10. Account settings and username changes

1. Open **Account settings** from the username menu.
2. **Change username:** you will see "You can change your username again from
   <date>": usernames can change once every 30 days, counted from set-up.
   To test a successful change locally, backdate the last change in your local
   database (find your container's name with `docker ps`):

   ```bash
   docker ps --format '{{.Names}}\t{{.Ports}}'
   ```

   ```bash
   docker exec -it <container-name> psql -U diski9 -d diski9 -c "UPDATE app.profiles SET username_changed_at = now() - interval '31 days' WHERE username = '<your username>';"
   ```

   (Use the user and database names from your `.env` if they differ from
   `diski9`.) Reload the page and change the username; try a name another account
   already uses and see it refused.
3. **Leaderboard privacy:** switch between public username and anonymous alias
   ("Anonymous" followed by digits) and save. Leaderboards still show
   demonstration data in this phase; persistent leaderboards come later.
4. **Change password:** if you signed in more than 15 minutes ago you are asked
   to re-enter your password first (T-14), then you can change it.

## 11. Guest versus signed-in access, account switching and privacy

**Guest access.** In a private window (signed out), check that Match Lab, the
Weekly Challenge (build and analyse a draft, prototype confirm, replace and
withdraw), Your View adjustments, My Challenge and Leaderboards all work exactly
as before. Visiting `/account` as a guest goes to the sign-in page.

**Guest draft at sign-in (T-15).**
1. Still signed out in a private window, build a draft in the Weekly Challenge or
   make a Your View adjustment in Match Lab.
2. Sign in (or create an account) in that same window and return to Match Lab.
3. A box asks **"Keep the analysis you did as a guest?"** with **Keep in this
   tab** and **Discard**. It states that keeping does not save anything to your
   account and submits nothing.
4. Reload before choosing: it asks again. Choose **Keep**: your draft and
   adjustments are still there in this tab. Repeat with a fresh guest draft and
   choose **Discard**: they are gone.
5. With no guest work in the tab, signing in asks nothing.

**Sign-out clears the tab.** Signed in, build a draft, then sign out: return to
the Weekly Challenge and the draft is gone.

**Account switching in one browser.**
1. Create a second account (`bravo@example.test`) the same way as in section 8.
2. In tab 1, sign in as alpha and build a draft.
3. Open a new tab by typing `http://127.0.0.1:8050` in the address bar, sign out
   there, and sign in as bravo.
4. Go back to tab 1 and reload: alpha's draft and Your View adjustments are gone,
   and the menu shows bravo. Bravo's **Account settings** never show alpha's
   email address, username or privacy setting.

## 12. Bootstrap the initial owner account (securely)

Ownership is granted only from the command line on the machine that holds the
database; there is no web page for it, and it works only while no owner exists.
Use an account you have already confirmed and set up in section 8:

```bash
uv run diski9 account bootstrap-owner --email alpha@example.test --confirm
```

```bash
uv run diski9 account list-privileged
```

Running `bootstrap-owner` a second time is refused because an owner now exists.
Later changes need the existing owner and a reason, for example:

```bash
uv run diski9 account grant-role --by-email alpha@example.test --email bravo@example.test --role operator --reason "acceptance test"
```

```bash
uv run diski9 account revoke-role --by-email alpha@example.test --email bravo@example.test --role operator --reason "acceptance test finished"
```

```bash
uv run diski9 account suspend --by-email alpha@example.test --email bravo@example.test --reason "acceptance test"
```

Bravo is signed out on the next page load. Reinstate:

```bash
uv run diski9 account reinstate --by-email alpha@example.test --email bravo@example.test --reason "acceptance test finished"
```

Run `uv run diski9 account --help` for the exact options. Every change is written
to the audit log (`app.audit_log`). Operator and owner screens arrive in later
phases; in Phase 6C.2 the roles control server-side permission checks only.

## 13. Local versus hosted Supabase testing

| | Local (this guide) | Hosted Free project (deferred) |
|---|---|---|
| Supabase Auth | CLI stack on your Mac | Supabase's servers |
| Emails | Mailpit inbox, nothing sent | Real emails (built-in sender: 2 per hour, team addresses only) |
| Keys | Local throwaway keys in `.env` | The project's own keys, kept only in your local `.env` |
| Diski 9 data | Your PostgreSQL container | Your container, or the project's PostgreSQL later |
| What it proves | The integration and all flows | Hosted configuration (Site URL, redirect list, templates, signing key) |

Hosted testing is optional extra validation after local acceptance; the steps are
in `docs/authentication.md` §2.4. Do not create one until you decide to.

## 14. Run the local authentication tests

**All tests except the genuine Supabase Auth ones** (they use your PostgreSQL
test database and a mock identity provider where marked):

```bash
export DISKI9_APP_TEST_DATABASE_URL="$(grep '^DISKI9_APP_TEST_DATABASE_URL=' .env | cut -d= -f2-)"
```

```bash
uv run pytest -q
```

The genuine Supabase Auth tests are reported as skipped in this run.

**Genuine Supabase Auth integration tests** read the emails from files, so they
use the repository's small harness (`tools/local_auth/local_auth.py`) running the
official Supabase Auth server, rather than the CLI stack. It runs beside the CLI
stack without conflict (ports 9999, 2500 and 9998). One-time set-up: build the
official server from source (needs Go):

```bash
brew install go
```

```bash
git clone --depth 1 --branch v2.198.0 https://github.com/supabase/auth ~/supabase-auth-src
```

```bash
cd ~/supabase-auth-src && go build -o ~/supabase-auth-src/supabase-auth . && cd -
```

Prepare a separate `diski9_auth_local` database (and the standard Supabase roles)
in your PostgreSQL container. Use your container's superuser and password from
`.env` (typed locally, not shared):

```bash
uv run python tools/local_auth/local_auth.py prepare --admin-url "postgresql://diski9:<your local password>@127.0.0.1:5432/postgres"
```

Start the harness in a separate terminal and leave it running:

```bash
uv run python tools/local_auth/local_auth.py run --gotrue ~/supabase-auth-src/supabase-auth --auth-db-url "postgres://supabase_auth_admin:local-auth-only@127.0.0.1:5432/diski9_auth_local"
```

(`local-auth-only` is the fixed password of a role that exists only in your
local test database.) Back in the first terminal, load the harness's test
settings (it writes throwaway local keys to the git-ignored `tmp/local_auth/env`)
and run the authentication tests:

```bash
set -a; . tmp/local_auth/env; set +a
```

```bash
export DISKI9_APP_TEST_DATABASE_URL="$(grep '^DISKI9_APP_TEST_DATABASE_URL=' .env | cut -d= -f2-)"
```

```bash
DISKI9_REQUIRE_SUPABASE_AUTH=1 uv run pytest -q -rs tests/backend
```

Expect every test in `tests/backend` to pass, with none skipped. Then run the
whole suite the same way:

```bash
DISKI9_REQUIRE_SUPABASE_AUTH=1 uv run pytest -q -rs
```

Stop the harness with Ctrl+C in its terminal.

## 15. Stopping and restarting

Stop Diski 9: Ctrl+C in its terminal. Stop the Supabase stack (your accounts and
emails are kept for next time):

```bash
supabase stop
```

To start again later:

```bash
supabase start
```

```bash
uv run diski9 serve
```

To wipe the local Supabase accounts and start from scratch:

```bash
supabase stop --no-backup
```

After a wipe, the Diski 9 database still holds the old accounts' profiles (they
are linked to Supabase user IDs that no longer exist). They are harmless, but the
old usernames stay taken; use new usernames, or reset your local Diski 9 database
the way you did for Phase 6C.1.

Your PostgreSQL container is untouched by all of this; stop and start it as
before.

**If sign-up stops working after many attempts:** Diski 9 limits sign-ups to 5 an
hour per network address (and other actions similarly). Wait an hour, or clear the
local counters:

```bash
docker exec -it <container-name> psql -U diski9 -d diski9 -c "DELETE FROM app.auth_rate_events;"
```

## 16. Returning to the previous state

```bash
supabase stop
```

```bash
git checkout main
```

The appended lines in `.env` are harmless on other branches (they are ignored
where accounts are not built). To remove them, restore your backup:

```bash
cp .env.backup-before-6c2 .env
```
