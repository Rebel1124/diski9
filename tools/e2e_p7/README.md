# Phase 7 CP3 end-to-end checks (local only)

These checks run the achievements lifecycle through the real services and the real app.
Everything is local and disposable.

**Safety:**
- `seed.py` refuses any database whose name does not contain `p7_e2e`.
- Accounts are throw-away users on the local Supabase Auth harness. Their passwords and the
  server environment files live in the git-ignored `tmp/e2e_p7/`.

## Setup

1. **Database:** create a separate PostgreSQL cluster (not the shared development server).
   Create `diski9_p7_e2e` on it and run `diski9 app-db upgrade`.
2. **Local auth:**
   - `local_auth.py prepare --admin-url <that cluster>/postgres`;
   - then `local_auth.py run --gotrue <binary> --auth-db-url <that cluster>/diski9_auth_local
     --site-url http://127.0.0.1:8057`.
3. **App servers:**
   - port 8057 with `DISKI9_SHOW_DEVELOPMENT_ROUNDS=1`;
   - port 8058 with it off;
   - both use the same database and keys (`diski9 serve --port N`).
4. **Accounts:** `NODE_PATH=$(npm root -g) node tools/e2e_p7/accounts.js` creates and
   onboards the viewers "you" and "pat".

## Run the stages

Run each stage in order, then its checks:

```bash
uv run python tools/e2e_p7/seed.py <url> none
NODE_PATH=$(npm root -g) node tools/e2e_p7/checks.js none --shots
```

Repeat for `base`, `pro`, `reopen`, `republish` and `corrupt`.

`seed.py` writes the service's own expectations to `tmp/e2e_p7/expect.json`. `checks.js`
compares the pages with them:
- level, counts, total, categories met and the bar;
- History chips per round;
- privacy: the second participant and guests;
- stream isolation, including the server with development hidden;
- the integrity-error state;
- no synthetic banner;
- no browser errors;
- read-only page loads.

With `--shots` it writes screenshots to `docs/screenshots/phase7/`.

Remove the cluster, the auth data and `tmp/e2e_p7/` afterwards.
