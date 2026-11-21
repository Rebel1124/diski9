# Phase 6C.5 local acceptance on a Mac (weekly results, championships, corrections)

This guide covers the backend delivered by Stages B, C and D of Phase 6C.5:
- official weekly results and points, published at finalisation;
- championships: streams, membership in deadline order, naming, ten valid rounds,
  rollover, versioned standings;
- corrections: reopening and review, valid-to-valid recalculation, invalidation
  (L-32, L-33, D-30a), restoration within capacity (CH-05);
- the operator commands `competition status | verify | backfill | repair`.

There is **no new screen yet**: the Leaderboards and My Challenge history views are
Stage E. Acceptance at this checkpoint is done with the operator commands, the
automated scenario tests and read-only service calls.

**Safety rules for this guide**
- Nothing here touches your own Diski 9 database. Every step that writes works on
  a **scratch copy** restored from a backup into a new database
  (`diski9_6c5_acceptance`). Migrating or backfilling your own database needs your
  separate authorisation and is described only as a later, optional step (§11).
- Commands marked **writes (scratch copy)** change the scratch copy only, because
  the terminal session points `DISKI9_APP_DATABASE_URL` at it (§3). Commands marked
  **read-only** never write.
- No Docker volume is removed, no database is reset, `.env` is not edited, no
  credentials are regenerated and no live football API request is made.
- You never need to wait for real matches.

It assumes the setup of the earlier guides (`docs/phase6c4_local_acceptance_mac.md`
and its predecessors): your owner account (below `alpha@example.test`), an operator
account (`bravo@example.test`) and participant accounts. Use your own emails.

---

## 1. Check out the branch and the commit

```bash
cd ~/Desktop/diski9
```

```bash
git status
```

Commit or stash anything you want to keep, then:

```bash
git fetch origin feature/phase-6c5-leaderboards
```

```bash
git checkout feature/phase-6c5-leaderboards
```

```bash
git pull
```

```bash
uv sync
```

```bash
git log --oneline -1
```

It should show the commit named in the Stage D checkpoint report.

## 2. Start your services

```bash
docker compose up -d
```

```bash
supabase start
```

## 3. Back up your database and make a scratch copy

**Read-only for your database.** The backup is a file on your Desktop:

```bash
docker compose exec -T postgres pg_dump -U diski9 -d diski9 -Fc > ~/Desktop/diski9-before-6c5.dump
```

(Use the user and database names from your `.env` if they differ.) Create the
scratch database and restore the backup into it. This creates a **new** database;
your own is not changed:

```bash
docker compose exec -T postgres createdb -U diski9 diski9_6c5_acceptance
```

```bash
docker compose exec -T postgres pg_restore -U diski9 -d diski9_6c5_acceptance --no-owner < ~/Desktop/diski9-before-6c5.dump
```

Point **this terminal session only** at the scratch copy. Copy your
`DISKI9_APP_DATABASE_URL` from `.env` and change only the database name at the end
to `diski9_6c5_acceptance`, for example:

```bash
export DISKI9_APP_DATABASE_URL="postgresql+psycopg://diski9:YOUR_PASSWORD@127.0.0.1:5432/diski9_6c5_acceptance"
```

Check which database you are pointing at before every writing step:

```bash
echo "$DISKI9_APP_DATABASE_URL" | sed 's#//[^@]*@#//***@#'
```

It must end in `/diski9_6c5_acceptance`. A new terminal without this `export` uses
your own database again, so keep every step below in this terminal.

## 4. Check the migration revision (read-only)

```bash
uv run diski9 app-db current
```

Your database is at `app_0006` (v4.2.0), so this prints `current app_0006; head
app_0007`.

## 5. Apply `app_0007` to the scratch copy (writes: scratch copy)

```bash
uv run diski9 app-db upgrade
```

```bash
uv run diski9 app-db check
```

`"up_to_date": true`. The migration:
- adapts the empty score tables for official weekly results;
- creates the championship tables;
- removes the never-used `championship_freezes` placeholder.

It refuses to run if any of those tables unexpectedly hold rows. Your accounts,
rounds, entries and settlement history are unchanged. A downgrade below
`app_0007` is refused once any official result or championship exists.

## 6. Competition status and integrity (read-only)

Each command asks for your password (hidden; nothing is stored):

```bash
uv run diski9 competition status --operator bravo@example.test
```

```bash
uv run diski9 competition verify --operator bravo@example.test
```

What to expect on an upgraded copy. `verify` prints one header line per stream:
`<stream>: consistent` or `<stream>: N finding(s)`.
- **development**: rounds you finalised before this upgrade appear under *final
  without official results (backfill)*. Rounds published before the upgrade appear
  once as *repairable: not yet assigned to a championship … run competition
  backfill*. Both are expected after an upgrade, not corruption, and the backfill
  resolves them.
- **beta**: the same, if you finalised beta rounds.
- **official**: `not started (official series, D-38)`.
- Notes such as `[pending_assignment]` or `[backfill_needed]` describe legitimate
  states, not faults. Only `repairable:` or `needs investigation:` lines are
  findings.

## 7. Historical backfill: preview (read-only), then run (writes: scratch copy)

```bash
uv run diski9 competition backfill --operator bravo@example.test --preview-only
```

The preview lists, per round:
- `publish [championship|practice|void]`;
- `already published`;
- `excluded`, with the reason. Excluded rounds are never assigned.

It also lists the championships it would create and the rounds that would still
wait for assignment, then prints a confirmation token. Nothing has changed yet.

To run it on the scratch copy:

```bash
uv run diski9 competition backfill --operator bravo@example.test --token TOKEN_FROM_PREVIEW
```

Then confirm the existing results:

```bash
uv run diski9 competition status --operator bravo@example.test
```

```bash
uv run diski9 competition verify --operator bravo@example.test
```

`verify` should print `development: consistent` (and the same for beta, if you had
beta rounds).

## 8. Corrections and recalculation

You can see every Stage D rule without waiting for matches in two ways.

### 8a. Automated scenarios (recommended; no effect on your databases)

The scenario tests build their own throw-away databases on your **test** server
(names ending in `_test`), drive the real 6C.4 services, and drop the databases
afterwards. Set the test database URL as in the earlier guides:

```bash
export DISKI9_APP_TEST_DATABASE_URL="$(grep '^DISKI9_APP_TEST_DATABASE_URL=' .env | cut -d= -f2-)"
```

| What you are accepting | Command |
|---|---|
| Reopening, review, valid-to-valid recalculation, L-33, CH-05 without capacity, D-30a historical invalidation (successor untouched), historical restoration, zero-point championship, operator invalidation not restorable, privacy across versions | `uv run pytest -v tests/backend/test_backend_championship_corrections.py` |
| Reserved slots, pending assignments, out-of-order finalisation, restoration competing with a reserved slot, rollover, concurrent restorations and invalidations | `uv run pytest -v tests/backend/test_backend_championship_capacity.py` |
| Integrity findings and the audited repair (preview, token, reason, recency, interruption, idempotency, material data refused) | `uv run pytest -v tests/backend/test_backend_championship_repair.py` |
| Generated correction sequences against PostgreSQL (seeds printed with `-s`) | `uv run pytest -v -s tests/backend/test_backend_championship_sequences.py` |
| Generated sequences on the pure model; restoration ordering | `uv run pytest -v tests/test_championship_corrections.py` |

Each test's docstring describes the scenario and the expected outcome.

### 8b. By hand on the scratch copy (optional; writes: scratch copy)

A competitive round needs five confirmed entries, so this needs five participant
accounts (Phase 6C.4 guide, journey I). With them, on the scratch copy:

1. **Build a championship quickly.** For a short trial, make championships two
   rounds long. This is a development-only setting on the scratch copy:

   ```bash
   docker compose exec -T postgres psql -U diski9 -d diski9_6c5_acceptance -c "UPDATE app.championship_series SET rounds_per_championship = 2 WHERE code = 'beta'"
   ```

   Then open two development rounds, enter them with the five accounts, and let
   them lock, settle and finalise (Phase 6C.4 guide, sections 7 and 8, journeys A
   to E). `competition status` should show the first championship
   `completed (2 of 2 rounds)`.
2. **Valid-to-valid correction.**
   - Reopen the second round as the owner with a corrected score
     (`round reopen … --fixture … --status FT --home … --away …`).
   - `competition status` shows a `[under_review]` note, and the published
     standings stay current while the round is reopened.
   - Then run `round finalise`. `competition status` shows a new standings
     version and no note.
3. **L-33 (successor not commenced).**
   - Reopen the second round and correct six of its nine fixtures to `CANC`, then
     finalise. The round fails D-32b.
   - Status shows the championship `in progress (1 of 2 rounds)` with a
     `[reopened_after_completion]` note.
   - The next development round you publish joins it.
4. **CH-05 (restoration).** Reopen the invalidated round and correct the
   cancelled fixtures back to `FT`, giving `--completed-at` and
   `--actual-kickoff-at` from your evidence, then finalise:
   - **without capacity:** the championship already has two counted rounds, so
     status shows a `[not_counted]` note; its weekly results are restored but
     they do not count;
   - **with capacity:** do this before the replacement round is final, and it
     counts again.
5. **D-30a.**
   - Publish and finalise two more rounds, so a second championship starts.
   - Invalidate a counted round of the first championship as in step 3.
   - It stays `completed` with one counted round, with a `[historical_correction]`
     note, and the second championship is unchanged.

After every step, `competition verify` should print `consistent`.

## 9. Inspect official standings and published versions (read-only)

Until Stage E adds the pages, read them through the read services. This prints the
current development championship and every published version. It writes nothing
and makes no API request:

```bash
uv run python -c "
from diski9.backend.db import make_app_engine
from diski9.backend.services import leaderboards as lb
e = make_app_engine()
b = lb.championship_board(e, stream='development', include_development=True)
print(b.name, b.status, f'{b.counted_rounds} of {b.rounds_required}', 'version', b.version)
print('under review:', b.under_review, b.review_rounds, '| disclosure:', b.disclosure)
print('champions:', b.champions, '| no champion:', b.no_champion, '| not counted:', b.not_counted_rounds)
for r in b.rows: print(r.position, r.name, r.points, r.recoveries, r.qualifying_top10)
if b.name:
    for v in lb.championship_versions_list(e, stream='development', name=b.name, include_development=True):
        print('v', v.version, v.cause, v.status, v.counted_rounds, v.reason or '')
"
```

Add `name='Championship Nov-26'` to choose a championship, or `version=N` to see an
earlier published version. Names are resolved now, so later anonymity applies.

## 10. The quantitative fingerprint (read-only)

```bash
uv run python tools/phase6c3_quant_regression.py 2>/dev/null | shasum -a 256
```

It must start with `88bcd717deca6c1c`.

## 11. Later and separately authorised: your own database

This is not part of this checkpoint. Only when you authorise it:
1. Open a terminal **without** the `export` from §3.
2. Take a fresh backup.
3. Run `app-db upgrade`.
4. Run `competition backfill --preview-only`, review the preview, then run the
   backfill with its token.

Until then, keep your own database at `app_0006`.

## 12. Removing the scratch copy (optional)

The scratch copy is a separate database; your own is unaffected either way.
Keeping it is harmless. To remove only it, after closing the terminal that points
at it:

```bash
docker compose exec -T postgres dropdb -U diski9 diski9_6c5_acceptance
```

Never use `docker compose down -v`.

## 13. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `app-db current` shows `app_0007` already | You are pointing at a database that was upgraded earlier. Check §3's `echo` |
| `app_0007` refuses: tables hold rows | Unexpected rows in `score_sets`, `round_scores` or `championship_freezes`. Do not force it; report it |
| `final without official results` after the upgrade | Expected for rounds finalised before `app_0007`; preview and run the backfill (§7) |
| `excluded: ... cannot be classified` in the backfill preview | A development round without a result mode, or a real round without the real mode; it is left out on purpose |
| `The data changed since the preview` | Something changed after the preview; preview again |
| `Your password check is too old` | Repair needs the password entered within 15 minutes; run the command again |
| `needs investigation:` from `verify` | Material inconsistency, never repaired automatically; keep the output and report it |
| Restored round still void | An operator invalidation cannot be undone (6C.4); or the corrected fixtures lack `--completed-at` / `--actual-kickoff-at` |
| `pg_restore` errors about roles | Add `--no-owner` (as above); harmless warnings about extensions can be ignored |

## 14. What you can and cannot accept before Stage E

| Possible now | Waits for Stage E |
|---|---|
| Migration and backfill on a scratch copy; status and verify; corrections, restoration, D-30a and repair through the commands and the scenario tests; standings and versions via the read services | The Leaderboards (Weekly / Championship) pages, personal summaries, My Challenge history and charts, and the browser journeys |

---

## 15. Stage E visual acceptance (Leaderboards and My Challenge History)

This reuses your **scratch copy** `diski9_6c5_acceptance` from §3. It is already at
`app_0007` and holds the results from Checkpoints 3 and 4, including the practice
round `dev-6c5-p1`. Your own `diski9` database is neither needed nor touched. No
migration or backfill is run.

### 15.1 Update the code (changes your working files only)

```bash
cd ~/Desktop/diski9
```

```bash
git pull
```

```bash
git log -1 --oneline
```

```bash
uv sync
```

`git log` shows the Stage E commit named in the checkpoint report.

### 15.2 Point a terminal at the scratch copy (read-only check first)

In a new terminal (the app keeps running in it):

```bash
cd ~/Desktop/diski9
```

```bash
export DISKI9_APP_DATABASE_URL="$(grep '^DISKI9_APP_DATABASE_URL=' .env | cut -d= -f2- | sed -E 's#/diski9$#/diski9_6c5_acceptance#')"
```

```bash
echo "$DISKI9_APP_DATABASE_URL" | sed -E 's#//[^@]*@#//***@#'
```

It must end in `/diski9_6c5_acceptance`. **If it does not, stop.**

```bash
uv run diski9 app-db current
```

It should say `current app_0007; head app_0007`. If it shows `app_0006`, you are
pointing at your own database: stop.

### 15.3 Start the app on the scratch copy (sign-ins record sessions in the scratch copy only)

```bash
DISKI9_SHOW_DEVELOPMENT_ROUNDS=1 uv run diski9 serve
```

Open http://127.0.0.1:8050 and sign in with your owner account.

### 15.4 What to look at
1. **Leaderboards, Weekly.**
   - Choose **Development** in the stream selector and round `dev-6c5-p1`.
   - Expect "Practice round", positions and names at lock, Returned, Net and
     Recovery, with **no points column**.
   - Expect "Practice: no championship points" in the header, and your summary
     above the table if you entered.
   - Choose **Beta**: `2026-W47-weekend` is open, so it says "Entries are revealed
     after the deadline".
2. **Leaderboards, Championship.** Development `Championship Nov-26` is
   **Upcoming**, at 0 of 10 valid rounds, with "Everyone starts at zero" and the
   ten-segment progress empty.
3. **My Challenge, Current.** It is the 6C.4 page you know, with the
   **Championship** card now showing your real standing, or why there is none,
   instead of the illustrative block.
4. **My Challenge, History.**
   - Choose **Development**.
   - Expect your statistics with the population note, the two charts (they say
     so when no counted competitive round exists yet), and your entries newest
     first.
   - Press **Details** on an entry for the nine predictions and four accumulators.
5. **Phone and tablet widths.** Use your browser's responsive mode at 390 and
   768 px. Tables become labelled cards with no sideways scrolling.

Your scratch copy has no competitive (five-entry) round, so the competitive
states are best reviewed in the screenshots, which come from a seeded development
database:
- points, champions, D-30a, Under Review, corrections and pagination;
- see `docs/screenshots/phase6c5/README.md`.

### 15.5 When you finish
Stop the app with Ctrl-C and close that terminal. Your own database was never used.
Keep the scratch copy and the backup unless you decide otherwise.

### 15.6 After the owner-requested refinements
Pull and restart the app. No migration, backfill or data change is needed, and the
same scratch copy is used.

**15.6.1 Terminal A (repository folder):**
```bash
cd ~/Desktop/diski9
```
```bash
git pull --ff-only
```
```bash
git log -1 --oneline
```
The commit shown should match the refinement checkpoint report.

**15.6.2 Terminal B:** set `DISKI9_APP_DATABASE_URL` and check the masked address and
the revision exactly as in §15.2 (`/diski9_6c5_acceptance`, `app_0007`). Then:
```bash
DISKI9_SHOW_DEVELOPMENT_ROUNDS=1 uv run diski9 serve
```
Reload http://127.0.0.1:8050 with a hard refresh (Cmd-Shift-R) so the new styles load.

**15.6.3 What to look at:**
1. **Leaderboards.** The tabs and selectors sit together. Rounds are named by their
   dates, with the code shown small. In the tables, numbers sit under their headers.
2. **Championship.** The progress bar is larger.
3. **My Challenge, History.**
   - Six statistics cards with coloured headers, like the Build Portfolio cards. Net
     is green when positive and red when negative.
   - "How your statistics are calculated" opens the full definitions.
   - With fewer than three eligible rounds (as in your scratch copy), each chart shows
     "Your … chart will become available after 3 eligible rounds" instead of an
     almost-empty chart.
4. **Phone widths (390 px and 320 px)** in your browser's responsive mode:
   - the four page links form a 2 × 2 grid;
   - leaderboard cards show the position, the name and the points on one line;
   - nothing is cut off.

Populated competitive states (points, podium, both charts) are in
`docs/screenshots/phase6c5/refined/` (index in its `README.md`), including
before/after comparisons (`compare_*.png`).

### 15.7 After the final refinements
Pull and restart exactly as in §15.6, and hard-refresh the browser. No data change is
needed. Then check:
1. **Weekly Challenge** (when no round is open): the gap below "Try the demonstration
   round" matches the gap above it.
2. **My Challenge.** Open **Details** on an entry in History. "Your result" shows four
   cards with coloured headers:
   - Allocated in violet;
   - Returned in green, or Refunded in amber;
   - Net in blue, with the value green or red;
   - Recovery in teal when recovered, amber for a refund, neutral otherwise.
3. **History.** Both chart headings are bold and the same size as "Your statistics",
   including when a chart is still waiting for three eligible rounds.
