# Phase 6C.5 — Leaderboards and Championships: implementation record

Authoritative specification:
[`phase6c5_design_specification.md`](phase6c5_design_specification.md) (approved
20 Nov 2026; decisions CH-01 to CH-12 and D-30a in the
[decision register](../product/weekly_challenge_decisions.md)).

## 1. Stage A closure (20 Nov 2026)

* The owner formally approved Stage A and resolved Q-1 to Q-12. The specification
  was updated to match: §8.3 membership and §8.4 naming rewritten; §20.1 marked
  resolved; §23 records the approval and clarifications.
* The decision register gained CH-01 to CH-12 and D-30a. The database design §6.7
  and §7.2 note what is superseded. The Phase 6C plan status and roadmap were
  updated.
* Q-5 was verified against v4.2.0:
  - D-32b voids can be restored through the existing owner reopening;
  - operator invalidations cannot (no 6C.4 path), which is a documented
    limitation.
* Private mini-leagues remain off the MVP roadmap, with no foundations built.
* No Stage A business decision remains open.

## 2. Stage B: weekly results and publication (20 Nov 2026)

### 2.1 Baseline
* Branch `feature/phase-6c5-leaderboards`, in a separate worktree, so the odds-trial
  checkout is never touched.
* Stage A closure commit `1223cd1`; `main` unchanged at `06a9a6a` (v4.2.0).
* Quantitative fingerprint `88bcd717deca6c1c…` verified before and after.
* Pre-implementation suite: 1,479 passed, plus 2 upgrade-path tests that read the
  new `app_0007` file, which had been added to the shared worktree while the
  baseline was running. Both pass on a clean checkout of `1223cd1`, so the baseline
  is 1,481 passing, matching v4.2.0.

### 2.2 Delivered
| Area | Files |
|---|---|
| Migration `app_0007` | `migrations_app/versions/app_0007_competition_results.py`; mirror in `backend/db/schema.py` |
| Adapter and atomic publication | `backend/services/competition.py` (`round_result`, `locked_records`, `publish_finalised`) |
| Integration | `corrections.finalise_round`: the final settlement version id is returned and published in the same transaction (the only change to a 6C.4 service) |
| Read services | `backend/services/leaderboards.py` (`weekly_board`: provisional and official, pagination, personal position, under-review retention) |
| Privacy-safe names | `auth/accounts.leaderboard_names` (set-based; equal to `leaderboard_name` row by row, tested) |
| Performance tool | `tools/phase6c5_perf.py` |

**Migration `app_0007`:**
* `score_sets` gains `settlement_version_id` (UNIQUE, so publication is
  idempotent), `scoring_version`, `published_at` and `actor_user_id`.
  - A guard trigger requires a `final` settlement version of the same round and
    run.
  - Only final sets are allowed (`final` defaults to true).
* `round_scores` gains `display_order` (unique per set) and status `round_void`,
  with the refund rules for void rounds as CHECKs.
* New indexes for page and user lookups.
* The championship tables are created as specified (§7.3) but **not written in
  Stage B**:
  - `championships` and `championship_rounds` are guarded (no delete; identity,
    name and membership immutable);
  - versions and standings are insert-only.
* `championship_freezes` is dropped only if empty; the upgrade refuses otherwise.
* The downgrade refuses once any result or championship exists. Without them it
  restores `app_0006` exactly: columns, defaults, constraints, triggers, indexes,
  policies, grants and functions were compared.

**Adapter:**
* Inputs:
  - locked entries;
  - the latest `entry_settlements` revision of each, which must belong to the
    locked submission and be complete;
  - the current **non-provisional** designation (`championship`, `practice` or
    `void`).
* Mapping to the engine:
  - D-33 entries map to `ALL_SELECTIONS_VOID` with a 100.00 refund;
  - in a void round every entry is refunded 100.00, as settlement already presents
    it to the participant;
  - competitive rounds get the neutral label `unassigned`, because the engine
    requires a championship id. The label never reaches storage.
* `scoring.score_round` is called **unchanged**; there is no second ranking or
  points implementation.

**Publication (`publish_finalised`):**
* Called only from a successful finalisation, after the final settlement version
  is inserted, in the same transaction and under the round row lock.
* Checks:
  - the round is `final`;
  - the version is the latest and is `final`;
  - the designation is final;
  - every entry is completely settled.
* Writes the score set, its rows, a `weekly_results_published` domain event and a
  `competition.publish` audit record.
* A second call for the same settlement version is a no-op.
* Any failure rolls back the whole finalisation (tested by failure injection), and
  a retry succeeds.
* A re-finalisation after an owner reopening publishes revision 2; revision 1 stays
  unchanged.

**Weekly points versus championship contribution:** a score set records weekly
points only. Nothing is written to championship tables until Stage C assigns
rounds (CH-02).

**Reads (`weekly_board`):**

| State | What is shown |
|---|---|
| `open` | Nothing (entries are private until the deadline) |
| `locked` | Entry count only |
| `provisional` | Computed on read and cached per (round, latest settlement run). Returns so far and predictions settled and pending; recovery and net `None` until the entry and the round check are decided; refunds unranked; no points |
| `final` | The latest score set, paginated by `display_order`. Shared ranks marked; weekly points only for competitive rounds; practice without points; void with no table (personal refund only) |
| `under_review` | The round is reopened: the **last published** revision is returned, flagged |
| `unpublished` | A round final before `app_0007`: no official results until backfill (Stage C) |

* Reads use a READ ONLY, REPEATABLE READ transaction and never construct the
  football client.
* Development rounds are visible only when development rounds are enabled.
* Rows contain no identifiers; `is_me` and "my page" are computed on the server.

### 2.3 Tests
| Suite | Result |
|---|---|
| `tests/test_competition_adapter.py` (pure) | 17 passed: standard ranking and gaps, several first places, shared tenth (90 each, next rank 13), exactly 100.00 vs 99.99, zero returns, no recoveries, all-void refund, practice, void, incomplete settlement refused, unknown designations refused, deterministic order, 0.01 precision, classification consistency, streams |
| `tests/backend/test_backend_weekly_results.py` (real PostgreSQL, real 6C.4 services) | 22 passed: no publication before finalisation; competitive, refund, practice and void rounds equal an independent recomputation; idempotency; concurrent finalisation (3 threads, 1 score set); failure injection with rollback and retry; refusal of non-authoritative versions; database CHECKs and insert-only history; pagination with shared ranks and my position; practice and void boards; development visibility; no IDs or emails in rows; retroactive anonymity on published results; set-based names equal to `leaderboard_name`; unpublished final round; reads write nothing and never construct the football client; provisional rules; provisional cache; reopening keeps the last published results, re-finalisation publishes revision 2 with history kept; championship-table guards; runtime-role privileges |
| `tests/backend/test_backend_upgrade_paths.py` | +2: upgrade from `app_0006` with rounds, entries, submissions and evidence unchanged; downgrade before results, refused after; upgrade refused when `championship_freezes` has rows |
| Existing tests updated | Head revision `app_0007` (3 assertions). `test_points_must_come_from_the_approved_schedule` now builds the final settlement version a score set requires; its D-31 checks are unchanged. `test_runs_are_serialised_and_never_duplicate_versions` reads versions `ORDER BY id`: it had no ORDER BY and failed once with rows returned as 2, 1, 3 (intermittent; now deterministic) |

### 2.4 Full regression
* **Run on the Stage B code:** 1,521 passed, 1 failed, 0 skipped (real PostgreSQL,
  local Supabase Auth, browser tests). The single failure was the intermittent
  ordering assertion above, which was then fixed and passed repeatedly.
* **Final confirmation run on the committed code (`3f9241c`):** 1,522 passed,
  0 failed, 0 skipped. That is the 1,481-test baseline plus 41 new tests.
* The local Supabase Auth harness reached its background time limit during the run
  and was restarted; all auth-dependent tests passed.

### 2.5 Performance (measured on this machine; the targets are engineering targets)

**1,000 entries:**

| Measurement | Result |
|---|---|
| Publication alone, inside finalisation | **108 ms** (target about 400 ms) |
| Whole finalisation | 489 ms |
| Settlement run (6C.4, reference) | 410 ms |
| Official page 1 / last page | 11.6 / 12.7 ms median (target about 50 ms) |
| Page plus personal position | 12.5 ms |
| Provisional page, uncached / cached | 52 / 5 ms |
| Concurrent reads (8 threads in the same process as a finalisation) | 402 reads, 0 errors, only consistent states (`provisional`, or `final` revision 1), p95 163 ms |

Under that same-process load the publication took 2.1 s, because of contention for
the Python interpreter between reader threads and the finalising thread. In
operation, finalisation runs from the operator command, a separate process from
the web server.

**10,000 entries (stretch, no target):** see §2.6.

### 2.6 10,000-entry stretch (measured; no target)

| Measurement | Result |
|---|---|
| Publication alone, inside finalisation | 1,033 ms |
| Whole finalisation | 5.0 s (the 6C.4 settlement run alone is 4.2 s) |
| Official page 1 / last page (200) / page plus my position | 21.7 / 22.1 / 23.7 ms median |
| Provisional page, uncached / cached | 668 / 9.6 ms |
| Concurrent reads | 3,072 reads by 8 threads, 0 errors, only consistent states, p95 167 ms |

Publication grows linearly with entries (108 ms at 1,000; 1.0 s at 10,000). Paged
official reads stay around 22 ms. The uncached provisional page is the slowest read
at 10,000 entries: every locked entry is ranked in memory once per settlement run,
and later reads hit the cache. Under same-process reader load, publication took
21.9 s because of interpreter contention (see §2.5). This is acceptable for the
MVP, and a known optimisation point if populations grow.

The tool uses its own user factory with unique aliases, because random aliases
collide at 20,000 users.

### 2.7 Deviations and limitations
* **Deviations from the specification (technical, no business change):**
  - `score_sets.actor_user_id` and the score-set guard trigger were added;
  - the championship tables are *guarded* (no delete) instead of plain
    projections;
  - cause `round_assigned` was added for Stage C.
* **Limitations:** no championship assignment, standings, backfill, status or
  verification commands (Stage C/D); no UI (Stage E).
  - Rounds finalised before `app_0007` show `unpublished` until the Stage C
    backfill.
  - Re-finalisation republishes weekly results, but championship recalculation is
    Stage D.
* No new operator command in Stage B; operator security is unchanged.

### 2.8 Owner approval of Stage B (20 Nov 2026)
* Stage B was approved by the owner at `ccd7c4e`: 1,522 of 1,522 local tests
  passed, CI run 54 passed, and the fingerprint is unchanged.
* The implementation decisions and minor schema deviations in §2.7 were accepted.
* The lifecycle clarifications were accepted:
  - D-32b voids are restorable only through the existing owner reopening;
    operator invalidations are not;
  - slot reservation in deadline order;
  - naming from the first associated round's SAST publication date.
* Stage C was authorised; Stage D needs separate approval.

## 3. Stage C: championship lifecycle, membership, persistence and standings (20 Nov 2026)

### 3.1 Baseline
* Branch `feature/phase-6c5-leaderboards` at `5cbffd9`: the Stage B approval
  recorded on top of the accepted `ccd7c4e`.
* Fingerprint `88bcd717deca6c1c…` verified.
* Accepted Stage B baseline: 1,522 of 1,522.
* Work done in the dedicated worktree; the odds-trial checkout was not touched.

### 3.2 Delivered (no schema change: the `app_0007` tables are sufficient)

| Area | Files |
|---|---|
| Lifecycle, membership, naming, standings, integrity | `backend/services/championships.py` |
| Operator services: stream status, backfill | `backend/services/competition_ops.py` |
| Read services | `backend/services/leaderboards.py`: `championship_board`, `championship_list`; `weekly_board` gains `championship` and `championship_status` |
| Integration | `services/rounds.py` (publication and lock), `services/competition.py` (end of `publish_finalised`): one call each, in the same transaction |
| Operator commands | `settlement_cli.py`, `cli.py`: `competition status \| verify \| backfill` (password per command, S-07) |
| Tools | `tools/phase6c5_perf_championships.py` |

**Streams (CH-01):**
* A development round always belongs to the `development` stream; otherwise the
  stream is the series (`beta` / `official`).
* Streams never share championships, counters or points.
* The official stream is processed only once `championship_series.official.started_at`
  is set; nothing in Stage C sets it (D-29, D-38).
* Development championships are readable only with development rounds enabled.

**Membership (CH-02)** in `process_stream`, under a per-stream advisory lock taken
after the caller's round row lock:
1. Outcomes of pending members are applied: practice at the lock (releases the
   slot); counted or void at the first official publication.
2. Unassigned rounds are assigned in deadline order. A round joins the open
   championship while commitment (counted plus pending) is below ten. When the
   open championship has ten counted rounds, the next round creates the next
   championship and fixes the previous boundary. Otherwise the round waits, and so
   do all later rounds.
3. Each touched championship is refreshed: slots, counter, status and, when
   anything changed, a new insert-only version with materialised standings.

Membership is immutable from assignment (database guard). Empty rounds lock as
practice, so they release their slot at once; a published round later postponed
is `void`. Neither can reserve a slot indefinitely.

**Naming (CH-03):**
* `Championship MMM-YY` from the SAST publication date of the first associated
  round, even if it later becomes practice or void, including after a delayed
  assignment.
* Same-month collisions get ` (2)`, ` (3)`, …
* Created once, under the stream lock; immutable.

**Standings:**
* `scoring.aggregate_championship` (unchanged) over the counted rounds' latest
  competitive score sets, with participants as users. Refunded entries are not
  counted; refunded-only participants are not listed.
* The engine's weekly points must equal the published ones, or the transaction is
  refused (integrity).
* Champions are rank-1 participants with points above zero, and only once the
  championship is completed; joint champions are supported; when everyone has zero
  points there is no champion.
* Display names come from the latest counted entry's name at lock, resolved at read
  time, so retroactive anonymity applies to every version.

**Versions:**
* `round_assigned`: creation, empty and upcoming.
* `round_published` / `round_republished`: standings changed.
* `backfill`.

A version is written only when the status, the counted rounds or the standings
hash change. Every version is audited; completion writes a domain event.

**Read services:**
* The current championship is the latest of the stream; any other is chosen by
  display name.
* `championship_board` returns:
  - status, progress (n of 10) and indicators: under review (`reopened`,
    `recalculation_pending`), corrected after completion, D-30a disclosure;
  - champions or `no_champion`, and the stream's pending assignments;
  - 50-row pages and the personal row (independent of the page), with
    `me_status` ∈ ranked / refunded_only / awaiting_results / practice_only /
    not_entered;
  - the selector list.
* Rows hold names and statistics only. Reads are READ ONLY, REPEATABLE READ and
  write nothing.

**Backfill:**
* The preview does all the work in a rolled-back transaction.
* Execution needs an operator principal and the preview token, and refuses if
  anything changed.
* It works in deadline order, one transaction per round: round lock, then weekly
  publication, then stream processing. It then processes every stream and writes
  an audit record.
* Excluded with a reason (never assigned):
  - development rounds without a result mode, or real rounds without the real
    mode;
  - unknown series;
  - official rounds while the series has not started;
  - a missing final settlement version or a provisional designation;
  - any publication refusal.

**Integrity (`verify_stream`, Stage C foundations):**
* Membership within the stream; counter equal to the counted members and at most
  ten; slots 1..n in deadline order; status.
* Standings recomputed and compared by hash, with the row count.
* Boundaries fixed before a successor; no development rounds in beta or official.
* Re-finalised rounds awaiting Stage D.
* Repair is Stage D.

### 3.3 Stage C boundary (Stage D dependencies)
* A determined member whose outcome changes on a re-finalisation (counted → void,
  or void → valid) keeps its role and the last published standings. The
  championship shows *under review: recalculation pending*, and `verify` reports
  it. Not yet applied: D-30a, L-32, L-33, CH-05 capacity restoration.
* A counted round re-finalised as still valid is re-aggregated from its latest
  valid score set (the same recomputation).
* Repair, property-based correction sequences and owner-facing correction flows
  are Stage D.
* No command starts the official series (a launch decision, D-38).

### 3.4 Tests
| Suite | Result |
|---|---|
| `tests/test_championship_lifecycle.py` (pure) | 14: SAST naming and month boundaries, collisions, roles, deadline-order assignment, reservation and waiting, practice and void releasing slots, the last slot becoming counted or void, a later round finalising first, naming from a practice first round, more than ten weeks, idempotent planning; engine tie-breakers (equal points split by recoveries, then by top tens, then shared) and joint champions |
| `tests/backend/test_backend_championships.py` (own database, 14 rounds) | 7: assignment at lock with reservation; completion after ten valid rounds with practice and void not counted; C11 final before C10 waits, then starts championship 2; slots; standings (mid-championship joiner, one-round participant, refunded-only and practice-only excluded, shared ranks); champion; versions and history; restart and repeated processing change nothing; boards (pagination, personal row, statuses, hidden development, no identifiers); recomputation equality |
| `tests/backend/test_backend_championship_edges.py` (own database, two-round championships) | 8: practice first round names "Oct-26" (23:30 SAST) and the next "Nov-26" (00:30 SAST); no champion when all zero; joint champions and the `(2)` suffix; reserved last slot released by a void round with the later round final first; concurrent finalisations and processing (no deadlock, no duplicates); failure injection rolls back weekly and championship publication, then a retry succeeds; consistent reads (never mixed versions); official stream gated |
| `tests/backend/test_backend_championship_backfill.py` (two own databases) | 7: legacy rounds unpublished; preview writes nothing and needs an operator; wrong token refused; interrupted run resumes; repeated run is a no-op (audit only); backfill equals normal processing on a twin database; unclassifiable rounds reported; Stage D containment of a counted round re-finalised as void |
| `tests/backend/test_backend_operator_cli.py` | +2 genuine (pty, real Supabase Auth): participant refused; wrong password; no terminal; status, verify, backfill preview, wrong token, confirmed backfill |
| Existing tests adjusted | `test_championship_tables_protect_identity_and_membership` now uses a draft round (processing assigns published rounds itself). `settle_helpers.make_settlement_round` gained an optional `published_at` |

### 3.5 Performance (measured on this machine)

**1,000 participants entering 11 development rounds:**

| Measurement | Result |
|---|---|
| Stage B weekly publication | 87–144 ms per round |
| Stage C championship processing | 115 ms (round 1) rising to 395 ms (round 10); standings are rebuilt from every counted round |
| Finalisation | 620–920 ms |
| Rollover (round 11) | 2.4 s, measured with 4 reader threads in the same process; 281 reads, 0 errors, p95 68 ms |
| Cumulative standings, 10 rounds × 1,000 | 292 ms |
| Championship page 1 / last page / page plus my position | 21.8 / 22.7 / 22.2 ms median |
| Backfill of 2 rounds | preview 0.5 s; run 1.1 s (including its preview) |
| Integrity check after the run | consistent |

**10,000 participants, 3 rounds (stretch):**

| Measurement | Result |
|---|---|
| Weekly publication | 1.2–1.3 s |
| Championship processing | 0.9–1.9 s |
| Finalisation | 6.2–7.1 s (settlement included) |
| Standings, 3 rounds | 1.0 s |
| Pages | 27–34 ms |
| Backfill of 1 round | preview 2.9 s; run 6.2 s |
| Integrity check | consistent |

Championship processing scales with counted rounds × participants, because every
change re-aggregates from scratch (no incremental points, by design).

### 3.6 Regression and verification
* Full suite on the committed Stage C code (`9a74d13`): **1,560 passed, 0 failed,
  0 skipped** (real PostgreSQL, local Supabase Auth, browser tests). That is the
  1,522 baseline plus 38 new tests.
* Fingerprint `88bcd717deca6c1c…` unchanged. No change since v4.2.0 under
  `challenge/`, `ingestion/`, `api_football/`, `app/` or `screener/`. Lint and
  formatting clean.

### 3.7 Deviations from the specification (technical, no business change)
* Per-stream advisory lock instead of the series row lock: a development stream
  spans series, and the lock is narrower. Lock order is unchanged: round row, then
  stream.
* A version is written only when the status, the counted rounds or the standings
  change (assignments alone are recorded in `championship_rounds` with
  `assigned_at`).
* The development stream uses the beta series' configuration (rounds per
  championship, scoring version).
* Championships are selected by display name (unique per stream); no identifiers
  are exposed.
* A counted round re-finalised as still valid is re-aggregated in Stage C;
  role-changing transitions are contained for Stage D (§3.3).

### 3.8 Owner approval of Stage C (20 Nov 2026)
* Stage C was formally approved by the owner at `3999974` (implementation
  `9a74d13`; Stage B closure `5cbffd9`; migration `app_0007`, with no further
  schema change).
  - Full local suite: 1,560 of 1,560 (38 new tests).
  - CI run 57 passed.
  - Fingerprint, scoring engine and protected areas unchanged.
  - No migration or backfill was run on the owner's or any production database.
* The implementation decisions in §3.2 and the deviations in §3.7 were accepted:
  per-stream locks, conditional version creation, development stream settings,
  and selection by display name.
* The performance results in §3.5 were accepted with no further optimisation.
  Two items carry over to Stage F, which also covers multi-process concurrency
  testing:
  - the same-process reader-thread contention;
  - the uncached provisional page.
* **Stage D dependencies (preserved):**
  - valid-to-valid re-finalisation already re-aggregates;
  - validity changes stay contained (under review: recalculation pending);
  - still to build: D-30a, L-32, L-33 and CH-05 restoration; full historical
    invalidation and restoration; audited repair; property-based correction
    sequences;
  - interactions between historical corrections, reserved slots, pending
    assignments and rollover;
  - the operator-invalidation reversal limitation is unchanged.
* **Operational observation:** the 09:14 UTC odds-trial firing arrived while this
  session was busy and ran at 09:45:49 UTC (11:45:49 SAST): EPL 20 fixtures,
  1,136 quotes, PSL 0, 3 requests, 7,485 remaining, no errors, commit `43a1773`.
  The trial continues until 21 Nov 2026 15:00 UTC.
* Deferred, unchanged: D-29, D-36, S-07, hosted Supabase acceptance and the 6C.3
  backlog. Private mini-leagues remain excluded.
