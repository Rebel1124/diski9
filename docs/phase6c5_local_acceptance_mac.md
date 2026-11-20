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

What to expect on an upgraded copy:
- **development**: rounds you finalised before this upgrade appear under *final
  without official results (backfill)*. That is expected: they were finalised
  before official results existed.
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
