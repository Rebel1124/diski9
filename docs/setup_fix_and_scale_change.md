# First-time setup fix and Form Score scale change

*15 November 2026*

## 1. First-time setup failure

### Symptom

On a newly initialised database, `diski9 refresh-data --with-odds` failed in
`store_fixtures()` with `sqlite3.IntegrityError: FOREIGN KEY constraint failed`
while inserting fixture 1557367 (competition 39, season 2026, teams 42 v 1346,
venue 494).

### Exact cause (verified, not assumed)

The insert was repeated with SQLite foreign-key enforcement off, and then
`PRAGMA foreign_key_check(fixtures)` was run:

| Child table | Columns | Parent table | Violations |
|---|---|---|---|
| `fixtures` | `(competition_id, season)` | `seasons(competition_id, year)` | 380 of 380 |

`competitions` and `seasons` were empty. Teams (20) and venues (20) were
present, because `store_fixtures()` creates those itself. Competitions and
seasons are only created by `sync-reference`, and the historical backfill was
also a separate step. `refresh-data` assumed both had already run, and the
Milestone 4 instructions (`init-db` → `refresh-data`) skipped them.

### Fix

* **`diski9 setup`** is a new first-time command that is safe to re-run
  (`src/diski9/workflow.py`). It runs in this order:
  1. migrations
  2. config
  3. competitions and seasons, and bookmakers
  4. teams and venues per competition-season
  5. fixtures 2023–2026 for all four competitions
  6. venue classification
  7. **verification that every required competition-season loaded**
  8. standings and optional odds
  9. Screener cache, only after step 7 passes

  Each competition-season commits separately, so an interrupted run resumes.
  Completed historical seasons are skipped on re-runs; `--force` re-fetches
  them.
* **`refresh-data`** is now strictly incremental: current season, standings,
  optional odds, cache. If setup has not completed it refuses with a message
  that lists what is missing, including "database not initialised", and exits
  with code 2.
* **`ingest_fixtures()`** now checks that the `seasons` row exists *before*
  spending an API request. If it is missing, it raises `MissingReferenceData`
  naming the competition, the season and the foreign key, instead of a raw
  `IntegrityError`.

### Verified with the live API on a brand-new database

| Run | Seasons fetched | Fixtures | API requests | Result |
|---|---|---|---|---|
| `setup --with-odds` (empty database) | 16 | +5,682 | 43 | 4 competitions, 55 seasons, 95 teams, 94 venues, 975 odds quotes, 102 cache rows; 23 s |
| `setup` again | 4 (current season) | 0 new, 1,412 unchanged | 15 | all row counts identical, no duplicates |
| `refresh-data` | 4 (current season) | 0 new | 6 | cache unchanged (102 verified) |
| `refresh-data` on an empty database | — | — | 0 | clear error, exit code 2 |

### Automated integration test

`tests/test_setup_workflow.py` starts from an SQLite file with **no tables**
and a simulated API-Football covering all four competitions × 2023–2026. It
verifies:

* every reference table is populated before fixtures, and
  `PRAGMA foreign_key_check` is clean
* every competition-season is fetched once
* the cache is populated
* a re-run is idempotent and skips historical seasons, and `--force` creates
  no duplicates
* an incremental refresh fetches only the current season, with no
  leagues/teams/backfill calls, and recalculates results that depend on a
  newly played match
* refresh before setup refuses with no API calls
* an interrupted setup builds **no** cache and later resumes rather than
  restarting
* a missing `seasons` row is named precisely, before any API request

## 2. Form Score scale: 0 to 5

Form Score = **1 +** (3W + D)/N + 0.5 × clip((GF − GA)/N, −2, 2)

* The range changes from [−1, 4] to **[0, 5]**. League home and away
  benchmarks are on the same scale (pooled method unchanged), and their sum
  is now 5 − draw rate (previously 3 − draw rate).
* **Unchanged:**
  * raw difference, venue-adjusted difference and every ranking (the constant
    cancels)
  * BTTS and Over/Under 2.5 indicators
  * Limited data rules
  * a team with no eligible matches still has **no** Form Score, never 1
* The engine version is now `1.2.1`. Each refresh retires active cache rows
  from any other engine version, and the app only reads current-version rows,
  so old-scale and new-scale values are never mixed.
* The UI explanation, the breakdown table ("Scale offset +1.00"), README and
  tests were all updated.

### Verified on the live cache (51 upcoming fixtures, both bases)

The cache was snapshotted before the change and compared after a refresh:

| Check | Result |
|---|---|
| Home and away Form Scores | exactly +1 for every fixture |
| League benchmarks (home, away) | exactly +1 |
| Raw and venue-adjusted differences | identical |
| BTTS and Over 2.5 indicators | identical |
| Ranking order (home stronger, away stronger, evenly matched) | identical |
| Old-scale rows | 106 retired, 0 active |
| New Form Score range observed | 0.00 to 5.00 |

The historical sanity check still passes: 1,394 fixtures with 0 failures. Its
independent SQL Form Score adds the +1 separately.

The example Form Scores in the Milestone 3 and 4 reports use the original
scale. Add 1 to compare them; their differences are still valid as stated.
