# D-29 — Weekly research pool collection: implementation and scheduling proposal

**Status:** approved (D-29b) and implemented in Phase 6C.0 on the
`research/weekly-pools` branch; see §12 for what was built and how it differs from
the proposal. Original status line: proposal for owner confirmation. The approach is approved (D-29,
Phase 6C architecture finalisation). **Nothing is implemented or scheduled.** The
existing odds trial (EPL and PSL, every three hours until 2026-11-21T15:00Z) is
not changed, interrupted or terminated by this proposal; the first weekly capture
would be **Thursday 26 November 2026**, after the trial has ended.

## 1. Purpose

Collect six to eight qualifying real weekly pools to validate:
* the championship scoring `points-150-75-v2` (D-29: fixture availability, round
  feasibility, scoring fairness, recovery rates, participant behaviour,
  competition size);
* the D-32b round-invalidation rule (observed voids kept separate from simulated
  scenarios);
* the `settle/v1` void rules and cutoff (D-08) against real postponements.

## 2. What is collected each week

| Step | When (SAST / UTC) | Content |
|---|---|---|
| **Capture** | Friday 08:00 SAST (06:00 UTC); Thursday until the D-11 revision, see §13 | Fixtures for the coming round window (Friday 00:00 to Monday 23:59 UTC) in all eight leagues; pre-match odds (1X2, BTTS, Over/Under 2.5) for all eight leagues; the Goal Model 1.0 probabilities for those fixtures |
| **Results** | Daily at 09:15 SAST (07:15 UTC) from Tuesday | Status, actual kickoff and 90-minute score for every pool fixture that is not yet final |
| **Close-out** | When every fixture is final under `settle/v1` (normally Thursday, after the cutoff) | Pool marked closed; validation inputs frozen |

The capture uses the same functions as production will: the eight-league
registry (`diski9.leagues`), odds reconciliation (`odds.collect.reconcile_pages`),
strict consensus and freshness (`odds.consensus`, at least three bookmaker groups,
quotes within 24 hours), margin removal (`odds.implied`), bucket classification
(`challenge.config`/`structured`) and the opening checks (15 fixtures, 3 leagues,
exact 4/3/2 matching). No rule is relaxed.

## 3. Storage

| Layer | Content | Location |
|---|---|---|
| **Raw** | Every API response exactly as received (fixtures and odds pages, trimmed to the three markets as in the trial), with retrieval time and rate-limit headers | `research/weekly_pools/<round_code>/raw/*.json.gz` |
| **Normalised** | One frozen pool file per week: fixtures, eligible outcomes with full-precision market probability, consensus odds, bookmaker-group counts, provider `update` and capture timestamps, model probabilities, bucket, ineligibility reasons, opening-check results | `research/weekly_pools/<round_code>/pool.json` |
| **Results** | Every result observation (append-only), the derived `settle/v1` verdict per fixture and outcome, void codes | `research/weekly_pools/<round_code>/results.jsonl` |
| **Manifest** | Code commit, Goal Model version and parameter hash, configuration version (`broad60-432-v1`), rules version (`settle/v1`), SHA-256 of every file, request counts, errors, status (`captured`, `partial`, `missed`, `closed`) | `research/weekly_pools/<round_code>/manifest.json` and `research/weekly_pools/runs.jsonl` |

**Durability:** files are small (the trial's captures are about 10 KB each) and
are committed to git, exactly as the odds trial does, so they survive ephemeral
cloud containers. **Proposed branch:** a new research branch
`research/weekly-pools` (needs your approval; the odds-trial branch is not reused
so the trial's record stays intact).

**Working database:** the collector computes model probabilities and consensus in
a separate, disposable SQLite file (`data/research_weekly.sqlite`). It is rebuilt
from the API when missing (reference data and the four-season backfill, about 60
to 80 requests, once per fresh container) and updated incrementally otherwise.

## 4. Isolation from production competition records

* The collector has **no access to the competition database**: it reads only its
  own SQLite file and writes only files under `research/weekly_pools/`.
* It refuses to start if its configured database URL is a PostgreSQL URL or the
  production SQLite path (a guard in the command, tested).
* It never imports the competition persistence modules (`diski9.backend.*`,
  planned in Phase 6C); a test enforces the import boundary.
* In production, the competition database user used by the app has no
  credentials for research storage, and the research job has no competition
  credentials.

## 5. API usage estimate

API-Football daily allowance observed in the trial: 7,500 requests per day.

| Job | Requests | Frequency | Per week |
|---|---|---|---|
| Capture: fixtures (8 leagues, current season, date window) | 8 | weekly | 8 |
| Capture: odds (8 leagues, all pages; measured in Phase 5A) | about 14 | weekly | 14 |
| Results check (only leagues with unresolved fixtures, date window) | up to 8 | daily from Tuesday until closed (typically Tue, Wed, Thu) | about 16–24 |
| Working-database rebuild (only in a fresh container) | about 60–80 | occasional | 0–80 |
| **Total** | | | **about 40–50 per week (up to about 125 with a rebuild)** |

That is under 0.1% of the weekly allowance (52,500), or about 400 requests for
eight weeks without rebuilds. The client keeps its existing 500-request daily
reserve and pacing. No historical odds are backfilled and `/predictions` is never
called.

## 6. Failure handling

| Failure | Handling |
|---|---|
| Network or rate-limit errors | Existing client retries with backoff; a page that still fails is recorded in the manifest |
| Partial capture (a league failed) | Status `partial`; one automatic retry 30 minutes later; a later complete capture for the same round replaces it only if made before 12:00 SAST, otherwise the partial capture is kept and flagged. A partial pool does not count as qualifying |
| Missed Friday capture | A late capture is allowed until the round's computed deadline (earliest eligible kickoff minus 15 minutes) and is flagged `late`; after that the week is recorded as `missed`. No retrospective odds |
| Results still pending at the cutoff | `settle/v1` voids them (V1/V4); the actual later outcome is still recorded as an observation |
| Unknown status codes or missing scores | Kept pending and reported in the daily one-line report |
| Quota below the reserve | The job stops and reports; nothing is partially written without a manifest entry |
| Git push failure | Retried with backoff; files stay in the container for the next run |

Each run replies with a one-line report (as the trial does): round, step,
fixtures, eligible outcomes, feasibility, requests, errors.

## 7. Reproducibility

* Raw responses plus the pinned code commit reproduce the normalised pool exactly
  (consensus, eligibility, buckets and opening checks); a replay command and a
  test verify the hash.
* Model probabilities are stored as frozen values with the Goal Model version,
  parameter hash and data cutoff (as a production round sheet does); the
  historical data behind them is recorded by row counts and a fingerprint of
  results up to the cutoff.
* Validation scripts take only the committed files as input, use fixed random
  seeds, and record their own version in their reports.

## 8. Qualifying pools and feasibility

* A **qualifying pool** is: captured on time (or `late` before the deadline),
  complete for all eight leagues, every fixture final under `settle/v1`, and
  passing the opening checks.
* Weeks that **fail the opening checks** (for example winter breaks) are recorded
  in full and reported as infeasible weeks; they do not count toward the six to
  eight but are part of the evidence (the PRD asks for "an international break and
  small rounds").
* Expected calendar: weekly from 26 November 2026; with the Bundesliga, Ligue 1
  and PSL winter breaks around late December and early January, eight qualifying
  pools may need until about mid to late January 2027.

## 9. Validation reports (D-29 and D-32b)

Run once six qualifying pools exist, and again at eight:
1. **Availability and feasibility:** eligible fixtures, leagues and outcomes per
   bucket per week; opening-check margins; infeasible weeks.
2. **Scoring:** re-run the Phase 6A.2.1 simulations using the real pools and real
   results (synthetic entrant populations of 5 to 1,000), reporting recovery
   rates, points concentration, the incentive measures and ties.
3. **D-32b**, in three separately labelled sections:
   * **Observed voids (fact):** void fixtures per week and their void codes.
   * **Observed voids applied to simulated entrants:** the share of void
     predictions and whether D-32b would have fired, using synthetic entrant
     populations on the real pool with the real voids.
   * **Simulated cancellation scenarios:** random, whole-league, whole-day and
     popular-fixture cancellations applied artificially, showing how close to the
     50% threshold rounds come.
   Simulated results are never presented as observed frequencies.
4. **settle/v1:** postponements, rescheduling within the cutoff, abandoned
   matches and late completions.

## 10. Proposed commands and scheduling (not activated)

* `diski9 research-pool capture` (Thursday), `diski9 research-pool results`
  (daily), `diski9 research-pool replay` and `diski9 research-pool report`.
* Two scheduled tasks, created only after your confirmation:
  * capture: `CRON_TZ=Africa/Johannesburg 0 8 * * 4`;
  * results: `CRON_TZ=Africa/Johannesburg 15 9 * * *` (exits immediately when no
    pool is open).
* Both end automatically after the eighth qualifying pool is closed, or on a date
  you set.

## 11. Decisions needed before activation

1. Approve the branch `research/weekly-pools` as the storage location.
2. Approve the two schedules above (or adjust the times).
3. Approve building the collector commands (a small Phase 6C.0 task, separate
   from the backend, touching no engine, model, odds or UI code).

## 12. Implementation notes (Phase 6C.0)

* **Code:** `src/diski9/research/weekly_pool.py`, CLI `diski9 research-pool
  capture|results|replay|report`, tests `tests/test_weekly_pool.py` (43 offline
  tests, including replay of a real capture kept as a fixture).
* **One builder for capture and replay:** the normalised pool is always built from
  the stored raw files by the production round-sheet code in a scratch SQLite file,
  so a replay reproduces the fingerprint and content exactly (verified on a live
  capture made during validation).
* **Validated request budget (live dry run on 19 November, not part of the
  dataset):** a capture in a fresh container rebuilds the working database: 77
  requests in 35 seconds (reference data, four-season backfill, standings, the
  current season and 14 odds pages). Results use `fixtures?ids=` with up to 20
  fixtures per request: 4 requests for the 68 fixtures of that window. Weekly
  total with daily results checks Tuesday to Thursday: about 90 requests (0.2% of
  the weekly allowance). The client keeps its 500-request daily reserve.
* **Every scheduled run starts in a fresh session,** so the capture always
  rebuilds its working database (the "occasional rebuild" in §5 happens every
  week). This is still within budget and makes every capture independent.
* **Partial captures:** a later complete capture replaces an accepted partial one
  until the round deadline (flagged `late` after 12:00 SAST Friday, the capture
  day since the D-11 revision); after the
  deadline no capture is accepted (`after_deadline`), and a complete capture is
  never repeated.
* **Results** are fetched from the start of the round window, only for fixtures
  without a final verdict; a pool closes when every round-sheet fixture is final.
  Repeated deliveries add nothing (content hash). A fixture whose provider status
  is unknown, or final without a score, stays pending with an alert.
* **Storage size:** about 350 KB per week (raw files plus the normalised pool).
* **Missing weeks** are listed by the report as gaps; no record is created for
  them.

### Stopping safely (Phase 6C.2 review)

* **Capture stops** when eight qualifying pools exist (a qualifying pool is
  already closed, so its results are complete) or after 31 March 2027. Only the
  capture schedule is disabled at that point.
* **Results continue** for every pool still open, so a pool captured before the
  stop (including a ninth) is fully evaluated. The results schedule disables
  itself only when the capture schedule has stopped and `report` shows no open
  rounds (`collection_finished`).
* **Hard end:** if a pool is still open on 21 April 2027 (three weeks after the
  last possible capture), it is marked with `research-pool mark-incomplete --round
  <code> --reason "..."`. All its data is kept, its pending fixtures stay listed,
  it never counts as qualifying, and the report lists it under
  `incomplete_rounds`.
* **Observability and recovery:** every run appends to `runs.jsonl` and replies
  with a one-line report; a failed or missed run can be repeated by hand with the
  same commands (`capture` is refused once a complete capture exists; `results`
  only adds changed observations).

## 13. Schedule revision: Friday capture (D-11 revision, 19 November 2026)

The product owner moved the standard Weekly Challenge publication target from
Thursday 08:00 SAST to Friday 08:00 SAST (D-11 revision). The weekly capture
follows it so the research pools stay representative of the competition.

* **Capture schedule:** `CRON_TZ=Africa/Johannesburg 0 8 * * 5` (was `* * 4`).
  The first capture is Friday 27 November 2026, 08:00 SAST (06:00 UTC); no capture
  runs on Thursday 26 November. The results schedule is unchanged (daily 09:15
  SAST) and makes no requests until the first pool exists.
* **Round window unchanged:** Friday 00:00 UTC to Tuesday 00:00 UTC (exclusive).
  A Friday capture maps to the same weekend and round code as before (the Friday
  itself), so no fixture window, eligibility rule or exclusion changes. The
  capture now runs six hours after the window opens; none of the eight leagues
  schedules a match between 00:00 and 06:00 UTC on a Friday, and the existing
  round deadline (earliest eligible kickoff minus 15 minutes) still decides
  whether a capture is accepted.
* **Code (labels only):** the scheduled capture day used for `timeliness` is now
  the Friday (on time before 12:00 SAST Friday; a capture made before Friday is
  also on time), and the report counts a week as missing once its Friday has begun
  instead of its Thursday. Timeliness does not affect whether a pool qualifies.
  Nothing else changed: odds freshness, consensus, Broad60 boundaries, 4/3/2
  feasibility, fingerprints, raw files, replay and the stop conditions in the
  Phase 6C.2 section are as before.

