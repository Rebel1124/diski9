# Phase 6C.3 local acceptance on a Mac (complete application)

This guide covers the whole persistent Weekly Challenge:
- rounds with frozen snapshots;
- saved drafts;
- Your View in the live and frozen contexts;
- guest-work adoption;
- confirm, replace and withdraw;
- deadline enforcement and lock;
- practice versus competitive classification.

Everything runs locally:
- your PostgreSQL 17 container (Diski 9 data);
- the Supabase CLI stack (accounts and emails);
- `uv run diski9 serve`.

No live football API request is needed. Nothing is deployed, and `.env` is not changed. Commands assume the setup from the Phase 6C.2 guide (`docs/phase6c2_local_acceptance_mac.md`).

**Development data is synthetic or mirrored.** Rounds whose code starts with `dev-` are development rounds:
- they are flagged in the database;
- they are refused in production;
- they never count toward an official championship.

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

`git log --oneline -1` should show the commit named in the final report.

## 2. Start your services

```bash
docker compose up -d
```

```bash
supabase start
```

## 3. Apply the migrations

```bash
uv run diski9 app-db upgrade
```

It should report `app_0005`. The migrations only add things:
- version columns;
- Your View per analytical context;
- the Friday 08:00 SAST weekend schedule (D-11 revised);
- per-tab save ordering;
- safety triggers.

Your accounts are kept.

Any Your View rows saved earlier are kept as "unassigned" and are not applied. They can only exist from the checkpoint demonstration script.

## 4. Create a development round for testing

Use your owner (or operator) test account's email in place of `alpha@example.test`.

**Round mirroring real upcoming fixtures.** This is the best option for testing the live and frozen contexts on the same match:

```bash
uv run diski9 round dev-open --by-email alpha@example.test --mirror-upcoming --deadline-minutes 1440 --code dev-accept-1
```

This takes real upcoming fixtures and their current estimated goals from your football database:
- the odds are **synthetic**;
- the deadline is at least 24 hours away, which gives you time for manual testing;
- it needs at least 15 upcoming fixtures in 3 leagues after that time in your football database (run your usual `refresh-data` first if needed; no new API request is made by this command).

If it reports that the rules are not met, try a smaller `--deadline-minutes` value. You can also use the fully synthetic option:

```bash
uv run diski9 round dev-open --by-email alpha@example.test --deadline-minutes 1440 --code dev-accept-1
```

Check it:

```bash
uv run diski9 round list
```

## 5. Start Diski 9 showing development rounds

```bash
DISKI9_SHOW_DEVELOPMENT_ROUNDS=1 uv run diski9 serve
```

Open http://127.0.0.1:8050. Without that variable, development rounds are hidden: participants then see "No round is open" unless a real round is published. The variable is refused in production.

## 6. Test accounts

Use the accounts from Phase 6C.2, or register new ones; confirmation emails arrive in Mailpit at http://127.0.0.1:54324. You need at least two participant accounts (A and B), plus your owner account for the round commands.

**Sign-in limit:** after 20 sign-ins in 15 minutes from one address, sign-in pauses. If that happens while testing, wait, or clear the local counters:

```bash
docker exec -it <container-name> psql -U diski9 -d diski9 -c "DELETE FROM app.auth_rate_events;"
```

## 7. What to check

### A. Persistent drafts (returning participant)
1. Sign in as A → **Weekly Challenge**. The bar shows the round, its status, **Frozen** time and **Deadline**, with the note that everyone uses the same frozen odds.
2. Choose 3–4 predictions. Under the tracker: **Saved to your account**.
3. Go to the Match Lab and back, refresh, sign out and sign in: the same predictions are there.

### B. Another device or browser
1. Open a private window (or another browser), sign in as A: the same draft appears.
2. Change a prediction there.
3. Back in the first window, change a different prediction: you see "Your saved portfolio was changed in another tab or on another device…" with **Load latest saved portfolio**. Click it: the other device's draft is shown. Nothing is merged.

### G. Live versus frozen Your View (same match)
1. From the builder, click **Match Lab →** on a match. The Match Lab shows **Weekly Challenge snapshot · Frozen: …**.
2. Change Section D (or B or C) for the home team, for example +0.20.
3. In the Screener choose **All upcoming matches** with the same match selected. It now shows **Latest available data · Model updated: …**.
4. Make a different change, for example +0.10.
5. Switch back and forth: each context keeps its own numbers.
6. **Reset all adjustments** in one context: the other is unchanged.
7. Sign out and in, or use the other browser: both contexts are restored.

With a mirrored round both baselines start equal (they were frozen just now). The frozen one stays fixed when your football data is refreshed; the live one follows it.

The Weekly Challenge **Your View** probability source uses only your frozen-context adjustments.

### D. Guest-work adoption
1. Sign out (or use a private window) and, as a guest, choose some predictions and make a Match Lab adjustment from the Weekly Challenge.
2. Sign in as B (with no saved draft). The page asks **Keep the analysis you did as a guest?**
3. Choose **Keep**. A review lists what can be saved (portfolio, Your View items) and anything that cannot be saved, with the reason.
4. Choose **Save to my account**. Check on another device that the draft and the adjustment are there. Nothing is confirmed.
5. Repeat as A (who has a saved draft): the review shows the portfolio under **Different from what your account already has**. Leave **Keep my account's saved work** selected and save: A's draft is unchanged. **Replace it with my guest work** would replace it. **Discard guest work** removes the tab's guest work.

### C. Confirm, replace, withdraw, re-enter
1. As A, complete 4 Foundation, 3 Balanced and 2 Challenger predictions → **Review & Submit** → **Confirm entry**. You see "Your entry has been confirmed".
2. **My Challenge** shows **Confirmed**, with published, frozen and deadline times.
3. In the builder remove one prediction: My Challenge says your saved portfolio has changes that are not confirmed. The confirmed entry is unchanged.
4. Choose a different prediction → Review → **Replace my confirmed entry**.
5. **My Challenge → Withdraw submission** → confirm: **Withdrawn** (history kept).
6. Review → **Confirm entry** again: confirmed, version 3.

A guest sees **Sign in to confirm** instead of a confirm button.

### F. Account isolation
1. In one window, as A, make a draft and an adjustment, then sign out.
2. Sign in as B in the same window: none of A's predictions or adjustments are visible.
3. Sign out, sign in as A: A's work is back.

### E. Deadline and lock (short round, safe)
Published deadlines cannot be changed, so create a separate short round:

```bash
uv run diski9 round dev-open --by-email alpha@example.test --deadline-minutes 10 --code dev-lock-1
```

The open round with the earliest deadline still ahead is shown, so this short round now appears in the app.

Have 5 accounts confirm entries within the 10 minutes (or fewer, for a practice round).

After the deadline:
- predictions, Confirm and Withdraw are refused for the short round;
- the app shows the open round whose deadline is still ahead again (`dev-accept-1`), so the short round moves to the **Most recent locked entry** card on My Challenge (section H), marked **Deadline passed** until it is locked;
- the builder shows **Deadline passed** for the short round only when no other open round has a deadline ahead.

Then lock it:

```bash
uv run diski9 round lock --code dev-lock-1
```

- With 5 or more entries: `designation=championship`, which is the stored name for a **competitive** round. My Challenge says "competitive round (unofficial beta: no official championship yet)".
- With fewer: **practice**.
- Running the command again changes nothing.

Before the deadline, `round lock` is refused.

After the lock the card says **Locked** and shows the classification.

### H. Most recent locked entry
Use the account that confirmed an entry in the short round of section E (or repeat section E with a single account; a practice round is fine).

1. While `dev-accept-1` is open, open **My Challenge**. Below the cards for the current round there is a card **Most recent locked entry** with the short round's code.
2. Before `round lock` it says **Deadline passed**: "this entry can no longer change. The round is waiting to be locked." After `round lock` it says **Locked**: "It cannot be edited, replaced or withdrawn."
3. Check the facts: deadline, frozen-odds time, confirmation time (and version if you replaced), classification after the lock, credits 100 virtual (40 / 30 / 20 / 10), maximum payout, and "Results: not available yet".
4. Open **Show the nine predictions in …**: your nine confirmed predictions with their frozen odds and market probabilities. The card has no buttons.
5. Change predictions in the current round (Weekly Challenge): the locked card does not change.
6. Sign out and sign in as another account (one that did not enter the short round, or withdrew before its deadline): no locked card appears.
7. Narrow the window (or use the browser's device mode at 390 px): the card stacks without horizontal scrolling.

The card shows only the most recent round whose deadline has passed. Full history, results and settlement come in later phases.

## 8. Run the automated tests

```bash
export DISKI9_APP_TEST_DATABASE_URL="$(grep '^DISKI9_APP_TEST_DATABASE_URL=' .env | cut -d= -f2-)"
```

```bash
uv run pytest -q tests/backend
```

```bash
uv run pytest -q
```

The genuine Supabase Auth tests run only with a local Supabase Auth server, as in the Phase 6C.2 guide, section 14. One test always skips: it needs a hosted Supabase `auth` schema.

One Stage G test module (`tests/backend/test_backend_upgrade_paths.py`) creates and drops its own database `diski9_upgrade_test` on the same PostgreSQL server as your test database, to check the upgrade paths. It never touches `diski9_test`'s data or your development database. Your test database user needs permission to create databases (the default `postgres` user in your container has it).

## 9. Known limitations to keep in mind
- Settlement, results, leaderboards and championship points are not built yet (later phases). The championship panel and Leaderboards are demonstration data.
- In a mirrored development round the odds are synthetic; only fixtures, teams, kickoffs and estimated goals are real.
- Automated Friday publication is Phase 6C.6. Rounds are published with the commands above.
- My Challenge shows the current round and the single most recent locked entry; older entries and results are not shown yet.
- With Friday-evening fixtures, Friday 08:00 SAST publication leaves about 10–13 hours before the deadline.
- About every 5 minutes one page load is slower (1–3 s) while the Screener refreshes its football data; this is unchanged from before Phase 6C.3.
- Opening a match by typing `/?fixture=<id>` in the address bar does not select it; use the Match Lab links in the builder or click the row.

## 10. Going back

```bash
git checkout feature/match-lab-guidance
```

Only if you need the earlier schema:

```bash
uv run diski9 app-db downgrade --revision app_0002
```

Downgrading below `app_0004` removes frozen-context Your View rows (that schema cannot hold them).
