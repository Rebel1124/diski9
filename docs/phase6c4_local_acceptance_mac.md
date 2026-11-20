# Phase 6C.4 local acceptance on a Mac (settlement, voids and corrections)

This guide covers:
- results recorded as evidence;
- settlement (partial and complete);
- the four accumulators and individual prediction results on **My Challenge**;
- partial voids, all-nine-void refunds and whole-round invalidation;
- audited corrections, finalisation and owner-only reopening;
- the operator command line, which asks for **your Supabase password** for every
  settlement command.

Everything runs locally:
- your PostgreSQL 17 container (Diski 9 data);
- the Supabase CLI stack (accounts and emails);
- `uv run diski9 serve`.

You do **not** need real matches, a live football API request or any waiting for
days: development rounds use deterministic synthetic results that appear minutes
after the deadline. Nothing is deployed, `.env` is not changed, no credentials are
regenerated and no Docker volume is removed.

It assumes the setup from the Phase 6C.2 and 6C.3 guides
(`docs/phase6c2_local_acceptance_mac.md`, `docs/phase6c3_local_acceptance_mac.md`):
your owner account (below `alpha@example.test`), an operator account
(`bravo@example.test`) and participant accounts. Use your own accounts' emails.

The full command reference, the scenario catalogue and the security rules are in
`docs/operator_settlement_cli.md`.

---

## 1. Switch to the branch

```bash
cd ~/Desktop/diski9
```

```bash
git status
```

Commit or stash anything you want to keep, then:

```bash
git fetch origin feature/phase-6c4-settlement
```

```bash
git checkout feature/phase-6c4-settlement
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

## 3. Upgrade the database from `app_0005` to `app_0006` (safely)

Check where you are:

```bash
uv run diski9 app-db current
```

It should say `current app_0005; head app_0006`. Take a backup first (a file on
your Desktop; nothing in the container changes):

```bash
docker compose exec -T postgres pg_dump -U diski9 -d diski9 -Fc > ~/Desktop/diski9-before-6c4.dump
```

(Use the user and database names from your `.env` if they differ.) Then upgrade:

```bash
uv run diski9 app-db upgrade
```

It reports `app_0006`. Check it:

```bash
uv run diski9 app-db check
```

`"up_to_date": true`. The migration only adds things (result evidence, settlement
versions, alerts, a frozen 24-hour correction window and a result mode per round).
Your accounts, rounds, drafts and entries are unchanged. Published rounds get the
24-hour window; existing **development** rounds get no result mode until you
choose one (section 7).

**Downgrade is deliberately restricted.** Once any settlement data exists,
`app-db downgrade` below `app_0006` (including to `base`) is refused and changes
nothing, so settlement history is never destroyed. If you ever need the old schema,
restore the backup above into a separate database rather than downgrading.

## 4. Start Diski 9 showing development rounds

In a separate terminal (leave it running):

```bash
cd ~/Desktop/diski9
```

```bash
DISKI9_SHOW_DEVELOPMENT_ROUNDS=1 uv run diski9 serve
```

Open http://127.0.0.1:8050.

## 5. Check the operator password prompt

Every settlement command asks for **your own Supabase password** (hidden while you
type; never put it on the command line). Try one that changes nothing:

```bash
uv run diski9 settle status --round dev-accept-1 --operator alpha@example.test
```

Expected:

```
Supabase password for alpha@example.test:
Verified alpha (roles: owner).
dev-accept-1: status open, result mode not chosen
...
```

Also check the refusals (each says "Nothing was changed"):
- a wrong password: `Sign-in failed: the email or password is incorrect.`;
- a participant account's email: `Your account does not have permission for this operation.`;
- with `supabase stop` (then `supabase start` again): `Supabase Auth is unavailable ...`.

If `dev-accept-1` no longer exists, use any round code from `uv run diski9 round list`.

## 6. Accounts you need

| Who | Used for | How |
|---|---|---|
| Owner (`alpha@example.test`) | `round dev-open`, reopening | from Phase 6C.2 |
| Operator (`bravo@example.test`) | settlement commands; checking that reopening is owner-only | from Phase 6C.2 (`account grant-role ... --role operator`) |
| Participant **A** | the account you look at in the browser | register in the app; emails in Mailpit http://127.0.0.1:54324 |
| Participants **B**, **C** | other entries (refund and privacy checks) | register in the app |
| Participants **D**, **E** | only for the competitive round (section 8 I) | register in the app |

The owner can run every operator command too; the operator account is only needed
to see that reopening is refused for operators.

**Several entries without five browsers.** `dev-results test-entry` confirms a
deterministic nine-prediction portfolio for a participant **after asking for that
participant's password**, through the same checks as the app. `--variant 0`, `1`,
`2` give portfolios on different matches (with `--fixtures 40`).

**Sign-in limit:** after 20 sign-ins in 15 minutes from one address, sign-in pauses.
If that happens while testing, wait, or clear the local counters:

```bash
docker compose exec postgres psql -U diski9 -d diski9 -c "DELETE FROM app.auth_rate_events;"
```

## 7. How a test round works (read once)

Each journey below uses its own short development round:

1. `round dev-open ... --deadline-minutes 4 --spacing-minutes 1 --fixtures 40`
   creates a synthetic round whose deadline is 4 minutes away and whose 40 matches
   kick off a minute apart from 15 minutes later.
2. Entries are confirmed (in the browser and/or with `test-entry`) before the
   deadline.
3. After the deadline, `round lock` locks it (no password: this is the scheduled
   lock job's action, as in Phase 6C.3).
4. `dev-results set-mode --mode synthetic` (once per round), then
   `dev-results scenario --name ...` records synthetic results. With the default
   *prompt* timeline the results are timed 1 to 4 minutes after the deadline, so
   **wait until 4 minutes after the deadline** before settling.
5. `settle run` settles; reload **My Challenge** to see the result.

The newest round (latest deadline) is shown as the current round on My Challenge;
the previous one appears as **Most recent entry**. Do the journeys in order so the
round you are checking is the newest.

In the commands below replace the round codes if you repeat a journey (codes are
unique), and `alpha@...`/`bravo@...`/`a@...` with your accounts.

## 8. Journeys

### A. Confirm and lock (prerequisite: participant A signed in)

```bash
uv run diski9 round dev-open --by-email alpha@example.test --deadline-minutes 6 --spacing-minutes 1 --fixtures 40 --code dev-6c4-a
```

1. As A, **Weekly Challenge** → choose nine predictions → **Review & Submit** →
   **Confirm entry**. **My Challenge** shows **Confirmed** for `dev-6c4-a`.
2. Add two more entries (you are asked for each participant's password):

```bash
uv run diski9 dev-results test-entry --round dev-6c4-a --participant b@example.test --variant 0
```

```bash
uv run diski9 dev-results test-entry --round dev-6c4-a --participant c@example.test --variant 2
```

3. After the deadline My Challenge says **Deadline passed**. Lock:

```bash
uv run diski9 round lock --code dev-6c4-a
```

4. Reload: **Locked** ("Results appear here as the matches are settled"), practice
   round (fewer than five entries). Your nine predictions and frozen odds are
   unchanged.

### B. Partial settlement (same round)

```bash
uv run diski9 dev-results set-mode --round dev-6c4-a --mode synthetic --operator bravo@example.test
```

```bash
uv run diski9 dev-results scenario --round dev-6c4-a --name pending --operator bravo@example.test
```

Wait until 4 minutes after the deadline, then:

```bash
uv run diski9 settle run --round dev-6c4-a --operator bravo@example.test
```

Reload My Challenge. Expected:
- pill **Partly settled**; "Returned so far" with "settled so far";
- **Net: Not final yet**, **Recovery: Not decided yet**;
- prediction counts Correct / Incorrect / Void / **Pending** (icon and word each);
- in **Accumulators**, an accumulator still waiting shows **Pending** in the
  Returned column, never 0.00;
- your predictions show the 90-minute score where settled and "Score not available
  yet" where pending; a pending prediction is never shown as incorrect;
- the **Confirmed portfolio** card above still shows the Market / Diski 9 / Your
  View estimates, now labelled **Pre-match estimates** (expectations, not results).

Optional, to inspect the evidence:

```bash
uv run diski9 results show --round dev-6c4-a --operator bravo@example.test
```

### C. Successful and unsuccessful accumulators; complete provisional result

```bash
uv run diski9 round dev-open --by-email alpha@example.test --deadline-minutes 4 --spacing-minutes 1 --fixtures 40 --code dev-6c4-b
```

```bash
uv run diski9 dev-results test-entry --round dev-6c4-b --participant a@example.test --variant 1
```

```bash
uv run diski9 dev-results test-entry --round dev-6c4-b --participant b@example.test --variant 0
```

After the deadline:

```bash
uv run diski9 round lock --code dev-6c4-b
```

```bash
uv run diski9 dev-results set-mode --round dev-6c4-b --mode synthetic --operator bravo@example.test
```

```bash
uv run diski9 dev-results scenario --round dev-6c4-b --name one-bucket-wins --operator bravo@example.test
```

Wait until 4 minutes after the deadline:

```bash
uv run diski9 settle run --round dev-6c4-b --operator bravo@example.test
```

As A, My Challenge: **Provisional result**; Foundation **Successful** with its
actual return; Balanced, Challenger and The Diski 9 **Unsuccessful** with 0.00; a
net figure; **Recovery: Not recovered** (unless Foundation alone reached 100); the
notice "Provisional: results can still be corrected until the correction window
ends (final from ... at the earliest)".

### D. Correction (same round)

Find a fixture in A's Foundation bucket (`results show` lists every relevant
fixture; the browser shows A's matches):

```bash
uv run diski9 results show --round dev-6c4-b --operator bravo@example.test
```

Correct its score so A's prediction loses (for a home-win pick use 0–0):

```bash
uv run diski9 results correct --round dev-6c4-b --fixture <FIXTURE_ID> --status FT --home 0 --away 0 --reason "official report corrected the score" --evidence "league match report" --operator bravo@example.test
```

You see the **impact preview** (which predictions change, entries recalculated,
material change yes/no) and then `Type the round code (dev-6c4-b) to apply this
change`. Type the code. Reload My Challenge: a **Corrected** pill and notice, and
the revised figures (Foundation now Unsuccessful). Pressing Enter instead of typing
the code changes nothing.

**Stale preview:** run the same command with `--preview-only` (prints a token),
make another correction, then run it with `--token <that token>`: refused with
"The round changed since the preview. Preview it again."

**Recent authentication:** if you wait more than 15 minutes at the "Type the round
code" prompt, the change is refused ("Your password check is too old ...").

### E. Finalisation and owner-only reopening (same round)

```bash
uv run diski9 round finalise-check --code dev-6c4-b --operator bravo@example.test
```

"can finalise not yet ... The correction window has not ended yet" with the
earliest finalisation time and, below it, the exact value to use, for example
`(development rounds: --as-of 2026-11-28T14:05:08+00:00)`. Development rounds may
finalise at that time without waiting 24 hours; copy that value:

```bash
uv run diski9 round finalise --code dev-6c4-b --as-of <EARLIEST_FINALISATION> --operator bravo@example.test
```

`Finalised: settlement version N (final).` My Challenge: **Final result**, "Final
since ...". Reopening as the operator is refused:

```bash
uv run diski9 round reopen --code dev-6c4-b --reason "league review" --evidence "league letter" --operator bravo@example.test
```

`Your account does not have permission for this operation.` As the owner (preview,
then type the round code):

```bash
uv run diski9 round reopen --code dev-6c4-b --reason "league review of a result" --evidence "league letter" --operator alpha@example.test
```

My Challenge: **Provisional result** with "This round was reopened for review on
...". (The final version stays in the history.)

### F. Individual entry voided and refunded (D-33)

```bash
uv run diski9 round dev-open --by-email alpha@example.test --deadline-minutes 4 --spacing-minutes 1 --fixtures 40 --code dev-6c4-c
```

```bash
uv run diski9 dev-results test-entry --round dev-6c4-c --participant a@example.test --variant 1
```

```bash
uv run diski9 dev-results test-entry --round dev-6c4-c --participant b@example.test --variant 0
```

```bash
uv run diski9 dev-results test-entry --round dev-6c4-c --participant c@example.test --variant 2
```

After the deadline: `round lock --code dev-6c4-c`, `dev-results set-mode ... --mode
synthetic`, then:

```bash
uv run diski9 dev-results scenario --round dev-6c4-c --name entry-all-void --operator bravo@example.test
```

Wait 4 minutes after the deadline, `settle run --round dev-6c4-c ...` (the output
shows `round validity: pass`). As A (variant 1 shares the fewest matches): **Void ·
refunded**, gross 100.00 (**Refunded**), net 0.00, **Recovery: Refund (not a
recovery)**, every prediction **Void** with its reason, accumulators **Refunded**.
B and C see normal results.

(With a single entry, `all-nine-void` makes the whole round void instead, because
then no prediction in the round was played.)

### G. Whole-round invalidation

```bash
uv run diski9 round dev-open --by-email alpha@example.test --deadline-minutes 4 --spacing-minutes 1 --code dev-6c4-d
```

```bash
uv run diski9 dev-results test-entry --round dev-6c4-d --participant a@example.test --variant 0
```

After the deadline: lock, set mode synthetic, `scenario --name all-correct`, wait,
`settle run`. A sees **Recovered 100+**. Then:

```bash
uv run diski9 round invalidate --code dev-6c4-d --reason "floodlight failure across venues" --operator bravo@example.test
```

Preview, type the code. My Challenge: **Round void**, "An operator invalidated this
round. Every entry is refunded its 100 credits. A refund is not a recovery."
The Accumulators card says **Not paid** (no accumulator returns in a void round);
the prediction results are shown for information only.

(The D-32b automatic invalidation: `scenario --name round-invalid-majority` on a
fresh round gives **Round void** with the D-32b explanation.)

### H. A new round while keeping the previous entry

```bash
uv run diski9 round dev-open --by-email alpha@example.test --deadline-minutes 600 --code dev-6c4-e
```

My Challenge shows `dev-6c4-e` as the current round and, below, **Most recent
entry** for `dev-6c4-d` with its result (Round void) and predictions. On **Weekly
Challenge** build a portfolio: the Portfolio analysis with **Market**, **Diski 9**
and **Your View** works as before.

### I. Competitive round (five entries) — optional

```bash
uv run diski9 round dev-open --by-email alpha@example.test --deadline-minutes 6 --spacing-minutes 1 --fixtures 40 --code dev-6c4-f
```

Confirm five entries (participants A–E, variants 0–4), lock after the deadline:
`designation=championship` (competitive). Then set mode synthetic, `scenario --name
all-correct`, wait, `settle run`: `round validity: pass`, with the competitive rule
(at least five rank-eligible entries). The five-entry minimum is not changed; with
four entries the round is practice.

### J. Sign out and switch accounts

Sign out: My Challenge shows no result. Sign in as B: only B's own entry and result
appear; nothing of A's predictions or figures. Sign in as A again: A's results.

### K. Layout

Narrow the window (or the browser's device mode at 768 and 390 px): cards stack,
the accumulator table hides the per-prediction icons on phones (the predictions
list below still shows each result), and nothing scrolls sideways.

## 9. Run the automated tests

```bash
export DISKI9_APP_TEST_DATABASE_URL="$(grep '^DISKI9_APP_TEST_DATABASE_URL=' .env | cut -d= -f2-)"
```

```bash
uv run pytest -q
```

The new genuine CLI tests (`tests/backend/test_backend_operator_cli.py`) type
passwords into the real command and need the local Supabase Auth harness from the
Phase 6C.2 guide, section 14; without it they are skipped. One recent-authentication
test waits about a minute on purpose. One test always skips: it needs a hosted
Supabase `auth` schema.

## 10. Cleaning up or keeping the test records

Development rounds and their entries, results and settlements are flagged as
development data, are hidden unless `DISKI9_SHOW_DEVELOPMENT_ROUNDS=1`, and never
count toward an official championship. Keeping them is safe. Settlement history is
insert-only by design, so there is no delete command; to start completely fresh,
restore `~/Desktop/diski9-before-6c4.dump` into a **new** database rather than
removing anything (and never `docker compose down -v`).

## 11. Known limitations

- Results, rankings, points and leaderboards: the championship panel and
  Leaderboards are still demonstration data (Phase 6C.5).
- Full history of past entries: only the current and the most recent entry are shown
  (Phase 6C.5).
- Corrections, alert resolutions and reopening always use the real clock (no time
  override, also in development); the prepared rounds above are timed so this works
  within minutes. Scenarios `cutoff-boundary` and `late-notification` place evidence
  at the real settlement cutoff (48 hours after the last kickoff) and are only
  visible with `settle run --as-of` after it.
- The 6C.3 commands `round create / publish / lock / dev-open` keep their existing
  `--by-email` form without a password; the settlement commands require it.
- Results for real rounds need `results import` (one live provider request per 20
  relevant fixtures); none is needed for this guide.

## 12. Going back

```bash
git checkout feature/match-lab-guidance
```

The `app_0006` schema stays (it is additive and harmless on other branches).
