# Phase 6C.3 checkpoint (Stages A–D): local acceptance on a Mac

What you can check at this checkpoint: persistent weekly **rounds** with frozen
snapshots, **lock** with practice/championship classification, private
**drafts** and private numerical **Your View**, all in your local PostgreSQL.

**Not yet visible in the pages.** The Weekly Challenge, My Challenge and Match Lab
pages still keep work in the browser tab, exactly as accepted. Connecting them to
these services is Stage F, after your approval. At this checkpoint you test
through the command line, a small demonstration script and the automated tests.

Everything is local. No live football API request is made, nothing is deployed,
and `.env` is not changed.

---

## 1. Switch to the branch

```bash
cd ~/path/to/diski9
```

```bash
git status
```

Commit or stash anything you want to keep, then:

```bash
git fetch origin feature/phase-6c3-competition-persistence
```

```bash
git checkout feature/phase-6c3-competition-persistence
```

```bash
git pull
```

```bash
uv sync
```

## 2. Start your services

Your PostgreSQL 17 container (as for Phases 6C.1 and 6C.2):

```bash
docker compose up -d
```

The local Supabase stack, only if you also want to sign in to the app:

```bash
supabase start
```

## 3. Apply the new migration

```bash
uv run diski9 app-db upgrade
```

It should report `app_0003`. This migration only adds columns and safety
triggers; your accounts are kept.

```bash
uv run diski9 app-db check
```

## 4. Open and inspect a development round

Use the email of your owner (or an operator) test account from Phase 6C.2 in
place of `alpha@example.test`.

```bash
uv run diski9 round dev-open --by-email alpha@example.test --deadline-minutes 10
```

This creates a `dev-…` round from **synthetic development fixtures** (20 matches
called "Dev Home 01 v Dev Away 01" and so on, in four leagues), runs every normal
opening check (15 fixtures, 3 leagues, odds rules, exact 4/3/2 feasibility) and
publishes it with a deadline 10 minutes from now. Note the round code it prints.

```bash
uv run diski9 round list
```

```bash
uv run diski9 round show --code dev-YYYYMMDD-HHMMSS
```

Try to lock it early:

```bash
uv run diski9 round lock --code dev-YYYYMMDD-HHMMSS
```

Before the deadline this says "The submission deadline has not been reached yet."

## 5. Drafts and Your View across "devices"

Use an onboarded participant account (a different test account is fine):

```bash
uv run python tools/phase6c3_demo.py --email bravo@example.test --code dev-YYYYMMDD-HHMMSS
```

You should see: a partial draft saved on the "laptop", the same draft read on the
"phone" (a separate connection pool), the phone removing a prediction, the stale
laptop being stopped with "This draft was changed in another tab or on another
device", and Your View numbers saved and read back identically. Run the same
command again: it starts by finding the draft saved by the previous run, which
shows the data persists between processes and restarts.

You can look at the stored rows directly (replace `<container-name>`; use
`docker ps` to find it):

```bash
docker exec -it <container-name> psql -U diski9 -d diski9 -c "SELECT round_id, jsonb_array_length(selections) AS picks, version, updated_at FROM app.portfolio_drafts ORDER BY updated_at DESC LIMIT 5;"
```

```bash
docker exec -it <container-name> psql -U diski9 -d diski9 -c "SELECT fixture_id, model_context, state, version FROM app.your_view_adjustments ORDER BY updated_at DESC LIMIT 5;"
```

The Your View rows hold numbers only: no notes or reasons.

## 6. Lock the round after its deadline

After the 10 minutes:

```bash
uv run diski9 round lock --code dev-YYYYMMDD-HHMMSS
```

It reports `status=locked designation=practice valid_entries=0` (there are no
confirmed entries yet: confirmation is Stage E). Run it again: "already locked;
nothing changed". The demonstration script now stops with "This round is closed"
and the saved draft is still readable.

## 7. Restart check

Stop and start your PostgreSQL container, then show the round again:

```bash
docker compose restart
```

```bash
uv run diski9 round show --code dev-YYYYMMDD-HHMMSS
```

The fingerprint and deadline are unchanged.

## 8. Run the automated tests

```bash
export DISKI9_APP_TEST_DATABASE_URL="$(grep '^DISKI9_APP_TEST_DATABASE_URL=' .env | cut -d= -f2-)"
```

The Phase 6C.3 tests only:

```bash
uv run pytest -q tests/backend/test_backend_rounds.py tests/backend/test_backend_drafts.py tests/backend/test_backend_your_view.py tests/backend/test_backend_runtime_role.py
```

Everything (the genuine Supabase Auth tests are skipped unless you run them as in
the Phase 6C.2 guide, section 14):

```bash
uv run pytest -q
```

## 9. Optional: a real-data round

Only if your football database has fresh odds for next weekend (no API request
is made by these commands):

```bash
uv run diski9 round create --week 2026-W48 --by-email alpha@example.test
```

```bash
uv run diski9 round publish --code 2026-W48-weekend --by-email alpha@example.test
```

If the data does not meet the opening rules, publication is refused with the
reason and the round stays in `draft`; nothing is relaxed. A real round you
publish locally is a local test only.

## 10. Returning to the previous branch

```bash
git checkout feature/match-lab-guidance
```

To take the database back to the Phase 6C.2 schema first (only if you need to):

```bash
uv run diski9 app-db downgrade --revision app_0002
```
