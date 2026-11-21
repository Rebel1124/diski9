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

---

## 4. Stage D: corrections, reopening and championship recalculation (20 Nov 2026)

### 4.1 Baseline
* Branch `feature/phase-6c5-leaderboards` at `d0502ce` (Stage C closure), equal to
  the remote.
* Fingerprint `88bcd717deca6c1c…` verified.
* Pre-implementation suite on a clean detached copy of `d0502ce`: **1,560
  passed, 0 failed, 0 skipped**.
* Work done in the dedicated worktree. The odds-trial checkout stayed clean at
  `43a1773` and was not used for any sync, setup or harness operation.

### 4.2 Delivered (no schema change: `app_0007` already had the causes `round_invalidated`, `round_restored` and `repair`, the role `not_counted`, `reason` and `corrected_after_completion`)

| Area | Files |
|---|---|
| Role resolution (pure), status rule, versioned role changes, integrity inspection | `backend/services/championships.py` (`resolve_roles`, `expected_status`, `_refresh`, `inspect_stream`) |
| Audited repair; status with findings and notes | `backend/services/competition_ops.py` (`preview_repair`, `run_repair`) |
| Read services | `backend/services/leaderboards.py`: review rounds, `version=` on `championship_board`, `championship_versions_list`, disclosures, `not_counted_rounds`, `counts_toward_championship` and `championship_note` on the weekly board, `my_round_result` |
| Operator command | `settlement_cli.py`: `competition repair`; `status` / `verify` print notes, repairable and material findings |
| Tools | `tools/phase6c5_perf_corrections.py` |

**Role changes (applied under the stream lock, in the finalisation transaction).**
A member's role follows its latest official publication. A reopened round keeps its
last published role until re-finalisation, so reopening never changes standings.

| Before | Authoritative outcome | After | Rule |
|---|---|---|---|
| pending | practice / void / valid | practice / void / counted (its reserved slot) | Stage C |
| counted | void | void: contribution removed, counter −1 | L-32; L-33 when completed without a successor (back to in progress); L-34 / D-30a when the boundary is fixed (stays completed) |
| void, not_counted | valid | counted if `counted + pending < required`, else not_counted | CH-05, §23.5 |
| not_counted | void | void | — |
| practice | anything | practice | fixed at the lock |

Restored and `not_counted` members of a championship are reconsidered in deadline
order before any waiting round is assigned (§23.5 rule 4). Pending members keep
their reservations, so a restored round never takes a reserved slot or displaces a
counted round. Membership never changes (database guard). More than ten counted
rounds is an integrity error.

**Status:**
* fixed boundary → completed (D-30a, possibly with fewer rounds, even zero);
* otherwise completed at ten counted, in progress below;
* upcoming only if the championship has never published a counted round.

`completed_at` keeps the first completion (database guard): the audit record of
the original completion.

**Versions:**
* Every correction role change (invalidated, restored, not counted) writes a new
  version, even when the standings are unchanged (§23.5 rule 5).
* Causes are `round_invalidated`, `round_restored`, `round_republished` and
  `repair`.
* Each version has a plain-language `reason` (for example "Round X was invalidated;
  the championship returned to in progress with 9 of 10 counted rounds (L-33)").
* The audit record lists the role changes.
* `corrected_after_completion` is set by any correction version after the first
  completion.
* Domain events: `championship_reopened` (L-33) and `championship_corrected`, in
  addition to `championship_completed`.
* A pending member's first outcome is versioned only if it changes the standings,
  as in Stage C.

**Read services (for Stage E):**
* `under_review` with `review_reasons` (`reopened`; `recalculation_pending` only on
  unrepaired data) and `review_rounds` (codes); `definitive`.
* `version=` for any earlier published version, and `championship_versions_list`.
  Names are resolved at read time, so retroactive anonymity covers every version.
* `reopened_after_completion` (L-33), `corrected_with_fewer_rounds` (D-30a) and
  `disclosure`, the approved sentence of §23.4, which never implies a missing
  round.
* `not_counted_rounds`; on the weekly board, `counts_toward_championship` and
  `championship_note`, with the approved CH-05 sentence or the pending-assignment
  sentence "confirmed when Round N is final".
* `my_round_result`: the last published rank, weekly points and the championship
  points that count, next to the current settlement (CH-10); `under_review` while
  reopened.
* Personal statuses `not_counted_only` and `invalidated_only` (CH-08).
* All reads remain READ ONLY at REPEATABLE READ and write nothing.

**Integrity (`inspect_stream`; `verify_stream` returns its findings).**

*Repairable* (derived data):
* a re-finalised round without official results;
* roles behind authoritative outcomes;
* counter, slots, status, missing version, standings hash or rows, version round
  list or champion count;
* a boundary not fixed;
* rounds assignable but unassigned.

*Material* (investigate; repair refuses the stream):
* published weekly results that differ from a re-scoring of the settlement;
* results that do not reference a final version;
* a member outside the stream, or a development round in beta or official;
* name or start date not matching the first associated round;
* more than ten counted rounds;
* a counted round without a competitive score set;
* engine points that differ from the published points.

*Notes* (legitimate, not faults): `under_review`, `pending_assignment`,
`historical_correction`, `not_counted`, `reopened_after_completion` and
`backfill_needed`.

Processing and inspection use the same rules (`resolve_roles`, `expected_status`,
`_started`), so repair and verify agree.

**Repair (`competition repair`).**
* *What it does:* republishes a re-finalised round's missing results
  (`publish_finalised`, idempotent per settlement version), then runs
  `process_stream(refresh_all=True, cause='repair')`.
* *What it never does:* edit history, move a membership, set points or winners, or
  touch settlement, evidence or football results.
* *Safeguards:*
  - an operator (owners included) with a password check (S-07);
  - the password re-entered within 15 minutes for the write;
  - a reason;
  - the preview's token, refused if stale;
  - one transaction per round (round lock, then stream lock), then one per stream;
  - an audit record `competition.repair` with the before and after of each
    championship.
* *Preview:* the work in a transaction that is rolled back. It reports findings,
  rounds to publish, each championship's before and after, standings and leader
  changes, boundary implications and unrepairable findings.

### 4.3 Atomicity, locking and concurrency
* **Lock order is unchanged:** round row, then stream. Repair and backfill use it
  per round, and stream processing takes only the stream lock.
* **No operation holds two round locks.** Processing changes other rounds'
  membership rows only under the stream lock, reading their committed
  authoritative state.
* **Atomicity:** a re-finalisation (settlement version, weekly score set, role
  changes, standings version, audit) is one transaction. Failure injection in
  championship processing rolls back the whole finalisation, including the weekly
  results, and a retry succeeds.
* **Concurrent restorations** are serialised by the stream lock:
  - capacity is never exceeded;
  - restorations processed in the same step are resolved in deadline order;
  - across separate commits, the outcome is the deterministic function of the
    commit sequence that §23.5 specifies.

  A round already counted is never displaced by a later restoration.

### 4.4 Tests (new: 43)

| Suite | Tests |
|---|---|
| `tests/test_championship_corrections.py` (pure) | 13: invalidation; L-33 / D-30a status; reopened round keeps its role; restoration with and without capacity; reserved slots not taken; several restorations in deadline order (independent of input order); `not_counted` taking freed capacity; re-invalidation; practice fixed; more than ten refused. **Hypothesis state machine:** 500 derandomised sequences of up to 70 legitimate operations (publish, lock practice, finalise valid or void, re-finalise void, restore D-32b voids, operator invalidation). Invariants after every step: maximum ten, no duplicate membership, roles match outcomes, `not_counted` only at full commitment, fixed boundaries, no premature completion, immutable membership, deadline-ordered championships, waiting only at full commitment, idempotent reprocessing. Coverage measured: about 4,500 restorations, 6,300 invalidations, 530 not counted and 2,600 D-30a states. A restoration-ordering permutation test with 200 examples |
| `tests/backend/test_backend_championship_corrections.py` (own database) | 10: joint champions; two reopened rounds (no writes, published standings kept, last published personal result next to the corrected settlement); one review resolving while the other stays; valid-to-valid recalculation (whole round re-ranked, champion changes from joint to sole, shared rank removed, earlier version readable); L-33 (back to in progress, original `completed_at` kept, domain event, reason) and the replacement round recompleting it; restoration without capacity (versioned, explained); successor commencing; failure injection and retry; D-30a (`not_counted` member taking the slot, winner change, one round, then zero rounds, no champion, successor untouched); historical restoration; valid-to-valid correction to zero points; operator invalidation not restorable, with a replacement round; privacy across versions (retroactive alias, no identifiers or emails, development hidden, guest gets nothing personal, no writes, no provider client); restart and idempotent reprocessing |
| `tests/backend/test_backend_championship_capacity.py` (own database) | 6: a waiting round finalised first (published, unassigned, "confirmed when Round N is final"); invalidation releasing a slot to the waiting round; restoration refused a reserved slot; the released reservation going to the restored round before rollover in the same transaction; concurrent restorations with one slot (exactly one counts; readers never see mixed versions); concurrent invalidations with stream processing (no deadlock, `not_counted` reconsidered, L-33, fixed championship unaffected) |
| `tests/backend/test_backend_championship_repair.py` (own database) | 9: a skipped republication reported as repairable; the preview writes nothing, needs an operator and is the same for an owner; safeguards (reason, stale token, password recency, participant, unknown stream); interruption leaves nothing partial and the retry succeeds (audited, cause `repair`); a repeated repair is a no-op; a tampered counter repaired without touching membership; concurrent repair and processing; material tampering refused and reported; a membership row outside the stream never blocks processing and is reported as material |
| `tests/backend/test_backend_championship_sequences.py` (PostgreSQL) | 4 seeds (20261120, 7, 42, 2026) × 30 operations through the real services, chosen only among legitimate ones: finalisation, invalidation, restoration, valid-to-valid correction, operator invalidation, repeated finalisation (refused), failed re-finalisation and retry, reconciliation. After every operation: no finding, at most two counted, immutable membership, no champion without points, operator voids never restored, fixed championships untouched, reads write nothing. 120 operations; every operation type exercised (26 finalisations, 17 invalidations, 25 restorations, 9 corrections, 8 operator invalidations, 7 failed and retried, 17 refused repeats, 11 reconciliations). No defect found |
| `tests/backend/test_backend_operator_cli.py` | +1 genuine (pty, real Supabase Auth): repair refused for a participant; wrong password; verify reports the tampered status; preview only (no writes, no password echo); missing reason; stale token; confirmed repair (audited actor and reason, membership unchanged) |
| Existing test changed | `test_championship_tables_protect_identity_and_membership` (Stage B/C guard test) deliberately inserts an inconsistent championship whose member is a draft round. It now places it in the **official** stream, which is never processed or inspected before launch, instead of the development stream that other tests share. The assertions are unchanged |
| Existing test changed | `test_refinalised_round_changing_role_is_contained_until_stage_d` documented the temporary Stage C containment. It is replaced by `test_refinalised_round_becoming_void_is_recalculated`, which asserts the approved L-32 behaviour on the same scenario |

### 4.5 Performance (measured on this machine; 1,000 participants, 11 development rounds, ten-round championships)

| Measurement | Result |
|---|---|
| Re-finalisation, valid-to-valid, historical championship (10 rounds re-aggregated) | 1,074 ms |
| Re-finalisation, valid-to-void after the successor commenced (D-30a), with 4 reader threads | 2,419 ms; reads 119, 0 errors, median 55 ms, p95 320 ms (same process) |
| Re-finalisation, void-to-valid restoration (counted again) | 949 ms |
| Re-finalisation, valid-to-void in the active championship (pending reprocessing) | 649 ms |
| Stream processing with nothing to change | 5 ms |
| `competition verify` (11 rounds re-scored and 2 championships recomputed) | 619 ms |
| Repair preview / run of a tampered counter (the run includes its preview) | 1.8 s / 2.7 s |

These are in line with Stage C: re-finalisation re-aggregates the whole championship
from scratch, by design. The same-process reader contention observed in Stage C is
visible here too. Multi-process measurements remain Stage F.

### 4.6 Regression and verification
* Full suite (real PostgreSQL, local Supabase Auth, browser tests) on clean
  detached copies of each commit:
  - `5dd74ff`: 1,600 passed, **2 failed**. Both failures came from the shared test
    database: a Stage C guard test leaves a deliberately inconsistent membership
    row, and the first Stage D processing refused it. Fixed in `d1287c9` (§4.7).
  - `d1287c9`: 1,602 passed, 1 failed. The new repair CLI test assumed the dev
    round was assigned, but in the shared database it legitimately waits behind
    other tests' unresolved rounds. Test fixed in `29ff049`.
  - `29ff049`: 1,602 passed and 1 failed in one run. The failure was an unchanged
    Match Lab browser layout test (`tests/test_match_context.py`), outside Stage D,
    which passed 3 of 3 times when rerun alone. The **confirming run passed 1,603
    of 1,603, with 0 failed and 0 skipped** (the 1,560 baseline plus 43 new tests).
* GitHub CI run 60 (`29ff049`) passed.
* Fingerprint `88bcd717deca6c1c…` unchanged.
* Unchanged since Stage C: `challenge/` (scoring engine), settlement and correction
  services, `competition.py`, `rounds.py`, authentication, migrations and the app.
  Unchanged since v4.2.0: `ingestion/`, `api_football/`, `app/` and `screener/`.
* Lint and formatting clean.
* **10,000-participant stretch:** not run in Stage D. The tool supports it
  (`tools/phase6c5_perf_corrections.py URL 10000 11`). Stage C's 10,000-participant
  results (§3.5) remain the reference; the corrections run the same recomputation.
  Deployment-representative scale testing is Stage F.

### 4.7 Interpretations and technical deviations (no approved rule changed; recorded for owner review)

**I-1: freed capacity in a fixed championship.**
* *Situation:* a `not_counted` member of a championship whose boundary is fixed,
  when a later invalidation frees a slot there.
* *What Stage D does:* the member is reconsidered and counts, applying §23.5 rule 4
  uniformly.
* *Why it fits:*
  - the round is already that championship's own member, so nothing moves;
  - the successor is unaffected;
  - L-34's "no replacement rounds" concerns new assignments, and none occurs.
* *Test:* exercised in the D-30a test.

**I-2: concurrent restorations.**
* Capacity is never exceeded.
* Within one processing step, deadline order decides.
* Across separate commits, the outcome follows the commit sequence, as §23.5
  specifies ("depends only on the sequence of committed publications").
* A counted round is never displaced afterwards.
* A race can therefore decide which of two simultaneously restored rounds counts.
  It can never produce an invalid or over-capacity state.

**I-3: review indicator.** It also covers a reopened **void** member, whose
re-finalisation could restore it and change the standings. §8.1 named counted
members only.

**I-4: every counted round invalidated after commencement.**
* The championship stays completed with zero counted rounds, no standings and no
  champion, with the D-30a disclosure.
* This follows L-34 ("recalculate with the remaining valid rounds"), applied to
  none remaining.
* Stage E only needs suitable wording.

**I-5: no return to upcoming.** A championship that has published a counted round
never returns to `upcoming`; it shows `in_progress` with zero rounds.

**I-6: first completion time kept.** `completed_at` remains the first completion
time when L-33 reopens and then recompletes a championship (database guard).

**Data written outside the services.** A championship holding a member that is not a round of its stream is left untouched by processing, as in Stage C. It is reported as a material finding, and repair refuses that stream. It never blocks publication elsewhere in the stream. The first full run found this case: an earlier version raised an error, which stopped later publications in the shared test database. Fixed in `d1287c9`.

**Technical deviations from the specification:**
* **Membership verification.** Spec §11.6 asks `competition verify` to replay the
  assignment queue over the whole history. Stage D verifies structural invariants
  instead:
  - names and start dates against the first associated round;
  - deadline-ordered assignment of waiting rounds;
  - roles against authoritative outcomes;
  - membership in the stream.

  The reason: with corrections, the history of role changes legitimately
  influences membership, so a replay from current state alone would report false
  differences. The pure and PostgreSQL property-based sequences verify membership
  immutability and deadline order across histories instead.
* **Repair recency.** Repair uses the operator capability (`RUN_JOBS`, as backfill)
  plus an explicit 15-minute password recency for the write. No new capability or
  role was added.

### 4.8 Known limitations and deferred items
* **Operator invalidation cannot be reversed** (6C.4 limitation, unchanged): a later
  correction re-finalises the round still void, and its role stays `void`.
* **The Stage C containment is fully replaced.** Every approved validity change
  (counted → void, void → counted, void → not counted, not counted → counted or
  void) is now applied; nothing remains contained.
  - `recalculation_pending` and the corresponding repairable finding can now arise
    only from data written outside the services, for example a database from a
    pre-Stage D build or a manual intervention. `competition repair` resolves them.
* **10,000-participant stretch:** not run in Stage D (§4.6).
* **No participant-facing UI** (Stage E).
* **Multi-process performance** is Stage F.
* **Unchanged deferrals:** D-29, D-36, S-07, hosted Supabase acceptance and the
  6C.3 backlog. Private mini-leagues remain excluded.

### 4.9 Owner review of Stage D (20 Nov 2026): accepted in principle, local owner acceptance pending
**Status:** implementation complete, local owner acceptance pending. Stage D is
**not** yet formally accepted or closed, and Stage E is not authorised.

**Accepted baseline:**
* Commits: implementation `5dd74ff`, defect correction `d1287c9`, final tested
  code `29ff049`, checkpoint record `68445f5`.
* Full local suite 1,603 of 1,603 (43 new tests); CI run 60 passed.
* `app_0007`, with no Stage D migration.
* Fingerprint, scoring engine and settlement methodology unchanged.
* Nothing run on the owner's or any production database.

**Interpretations I-1 to I-5 (§4.7): all approved, with these clarifications.**

*I-1, historical restoration capacity.*
* A restored `not_counted` round may take capacity released by an invalidation in
  its own historical championship.
* Membership, identity and boundaries stay unchanged; counted rounds and reserved
  capacity are protected; never more than ten; successors are unaffected.
* When the championship returns to ten counted rounds, the reduced-round
  disclosure is withdrawn while the correction record and the
  corrected-after-completion indicator remain. This is implemented: the disclosure
  is derived from the current count, and versions are insert-only.

*I-2, concurrent restorations.*
* Independently committed restorations follow the commit-sequence rule (§23.5).
  Restorations resolved in one operation follow deadline order.
* Processing is deterministic over the **recorded** event history (the committed
  publications in order). It does not claim independence from transaction arrival
  or commit timing.
* Counted contributions and reserved capacity are protected; never more than ten.
* A retry preserves the recorded outcome: roles are persisted, and reprocessing is
  idempotent.
* The explanation is kept. Each role change is a version with a reason (for
  example "restored after the championship already had 10 counted rounds (or
  reserved slots), so its points do not count"), and the audit record lists the
  role changes.
* No priority queue or scheduler is added.

*I-3, reopened void rounds.* A reopened void member puts its championship Under
Review until authoritative re-finalisation. The published standings and points stay
current, and nothing speculative is published.

*I-4, all counted rounds invalidated.*
* The historical championship stays Completed, with identity, name, start date,
  boundaries, memberships, earlier versions and audit history preserved; it has no
  standings and no champion. Successors are unaffected.
* Stage E wording (not implemented now): "All previously counted rounds were
  subsequently invalidated. No official standings or champion remain for this
  championship. Subsequent championships are unaffected."

*I-5, no return to Upcoming.*
* Once a championship has had a counted round it has commenced and never returns
  to Upcoming.
* An unfrozen completed championship may return to In Progress (L-33); a frozen
  one follows D-30a.
* Current counted-round totals are distinct from commencement. Commencement is
  derived from the version history: any version with a counted round.

**Accepted technical deviation.** Verification checks structural membership rules
rather than replaying the full assignment history: membership depends on
chronological lifecycle and correction events, so a replay from current state
alone would report false differences. Membership decisions can be investigated
from the recorded history:
* `championship_rounds.assigned_at`;
* `championship_created` and `weekly_results_published` domain events;
* insert-only score sets per settlement version;
* insert-only championship versions with cause, reason, actor and round list;
* `championship.version` audit records listing role changes.

No replay subsystem is introduced. This limitation is also recorded in
`docs/operator_settlement_cli.md`.

**Review of the `d1287c9` safeguards (requested by the owner).**

| Safeguard | Status | Evidence |
|---|---|---|
| An inconsistent membership row does not block healthy championships | Confirmed | `test_member_outside_the_stream_never_blocks_processing` (repair module): processing succeeds. The full suite (`test_frozen_context_and_no_effect_on_the_competition` publishing into the shared database) failed before `d1287c9` and passes after it |
| `verify` reports the affected championship as material | Confirmed | Same test: a material finding "member round(s) are not in the development stream" |
| Repair refuses non-authoritative or membership-changing work | Confirmed | Any material finding refuses the stream (`_repair_work`); `test_material_inconsistency_is_refused_and_reported`. Repair never writes membership except normal deadline-order assignment |
| The affected championship cannot silently show misleading definitive standings | **Gap, fixed in `65a1440`** | Before the fix, the read service still showed its last published version as definitive. It now shows it as Under Review with the reason `integrity_review`, and `definitive` is false |
| No unsafe membership or contribution change | **Gap, fixed in `65a1440`** | Before the fix, waiting rounds could be assigned into an inconsistent open championship. Assignment is now held: no membership is created, weekly results still publish, and verify notes the held assignment. Repair still refuses the stream |

Both gaps are reachable only through data written outside the services, such as a
manual database edit. They were reported to the owner before local acceptance. A
minimal correction is proposed and awaits authorisation:
* assign no waiting rounds while the open championship is inconsistent (their
  weekly results still publish);
* mark such a championship Under Review with the reason `integrity_review`
  (`definitive = False`) in the read services;
* add tests for both.

### 4.10 Owner-authorised corrections during local acceptance (20 Nov 2026, `65a1440`)
The owner authorised the safeguard fix and four presentation corrections, found at
local acceptance Checkpoints 1 to 3.

**Safeguards:**
* While the open championship holds a member outside its stream, processing assigns
  no waiting round. Weekly results still publish.
* The inspection notes such a round as "championship assignment held" and does not
  report it as assignable.
* `championship_board` adds the reason `integrity_review`, sets `under_review` and
  clears `definitive` for any championship with such a member.
* Tests: `test_member_outside_the_stream_never_blocks_processing` (extended). It
  covers healthy championships unaffected, the inconsistent open championship shown
  as under review, a new round finalised (published, not assigned), the held note,
  and repair refusing the stream.

**Operator output (no data or behaviour change):**
* `competition verify` prints a header per stream (`<stream>: N finding(s)` or
  `<stream>: consistent`), so every finding carries its stream. The repair CLI test
  asserts it.
* The backfill lists created championships as `Name (stream)`, because names are
  unique per stream only.
* Rounds published before the upgrade and never processed are reported once, as
  "not yet assigned to a championship … run competition backfill". The status line
  "championship assignment pending" lists only rounds legitimately waiting behind
  an earlier unresolved round.
* `competition backfill --token` announces that it re-checks the preview before
  applying, instead of printing "Backfill preview".

**Local acceptance progress (scratch copy `diski9_6c5_acceptance` on the owner's Mac):**
* **Checkpoint 1, environment:** branch, commit, database target (masked) and
  `app_0006` verified.
* **Checkpoint 2, backup and scratch copy:** backup of 290 KB with 42 table-data
  sections. Restore counts identical: 3 users, 7 rounds, 10 entries, 10
  settlements, 8 settlement versions, 31 audit rows. The terminal points at the copy.
* **Checkpoint 3, migration and backfill:**
  - `app_0007` applied to the copy only, with counts preserved. The owner's
    `diski9` stays at `app_0006`.
  - The upgraded copy correctly showed its 7 published rounds as unassigned.
  - The backfill published nothing (no round was final), assigned all 7 rounds and
    created one championship per stream. `verify` then reported consistent, and a
    repeated preview did nothing.
  - Memberships were correct by stream: 6 development rounds (3 pending, 3
    practice) and 1 beta round (pending).

**Regression on `65a1440`:**
* Full suite: **1,603 passed, 0 failed, 0 skipped**. These changes extend existing
  tests; no tests were added.
* An earlier run of the same commit showed 12 failures and 15 errors, all in tests
  that need the local Supabase Auth harness. The harness had reached its
  background time limit during the run. After a restart, the full rerun passed.
* Fingerprint `88bcd717deca6c1c…` unchanged.
* No change to scoring, settlement, corrections, authentication, migrations or the
  app.

### 4.11 Local owner acceptance concluded (20 Nov 2026)
* **Checkpoint 4 (weekly results and lifecycle) passed on the owner's Mac:**
  - the 68 automated weekly-result and championship lifecycle tests passed, with
    none skipped;
  - a fresh development round `dev-6c5-p1` was taken through the real services on
    the scratch copy. It was assigned at publication (pending), became practice at
    the lock, and was settled (validity pass) and finalised.
  - The official weekly result was published in the same transaction: revision 1,
    kind practice, built from the final settlement version. Positions and names at
    lock were shown with no points. The championship stayed upcoming at 0 of 10,
    and `verify` reported consistent.
* **Checkpoints 5 and 6 waived.** The owner judged acceptance sufficient at this
  point and waived the corrections and restoration checkpoint and the repair and
  final verification checkpoint on the Mac. Those behaviours remain covered by the
  automated suite (1,603 of 1,603 on `65a1440`; CI run 63 passed on `13adf00`).
  The checkpoint 1 to 4 results are in §4.10 and above.
* **The owner's own database** (`diski9`) was never migrated or written:
  `app_0006`, 7 rounds and 10 entries throughout. All acceptance writes went to the
  scratch copy `diski9_6c5_acceptance`.
* **Status:** local owner acceptance concluded. Formal Stage D closure is recorded
  only on the owner's explicit confirmation. Stage E is not authorised.

### 4.12 Owner approval and formal closure of Stage D (20 Nov 2026)
**Stage D: complete, owner-approved and formally closed.** Stage E is awaiting
authorisation.

**Accepted baseline:**
* Code and commits on `feature/phase-6c5-leaderboards`:
  - implementation `5dd74ff`;
  - interim correction `d1287c9`;
  - test fix `29ff049`;
  - authorised acceptance fixes `65a1440`;
  - acceptance documentation `13adf00`;
  - local acceptance record `d4f6e24`.
* Evidence:
  - full regression suite 1,603 passed, 0 failed, 0 skipped (on `65a1440`);
  - GitHub CI run 63 passed (`13adf00`);
  - the owner's local lifecycle tests: 68 passed, 0 failed, 0 skipped, in 30.93 s.
* Unchanged: fingerprint `88bcd717deca6c1c…`, the scoring engine and the settlement
  methodology. Migration head `app_0007`, with no Stage D migration.
* Interpretations I-1 to I-5 and the structural membership verification deviation
  remain approved (§4.7, §4.9).
* The two acceptance fixes are accepted, with their tests and documentation
  (§4.10):
  - integrity-review containment of championships with inconsistent membership;
  - clearer operator status, verify and backfill output.

**Evidence by kind:**

| Kind | Scope |
|---|---|
| Automated regression (development environment and CI) | All Stage B, C and D behaviour, including corrections, restoration, historical invalidation (D-30a), capacity and reserved slots, concurrency, failure injection, property-based sequences, audited repair and its safeguards, privacy, genuine-terminal authentication |
| Local owner acceptance, completed and passed: Checkpoints 1 to 4 | 1, environment and Git verification. 2, backup (verified) and isolated scratch database. 3, `app_0007` migration of the scratch copy with data preserved, historical backfill, idempotency, development and beta stream isolation, status and verify. 4, the 68 lifecycle tests, then development round `dev-6c5-p1`: publication and automatic championship assignment, two authenticated participant entries, practice classification at the lock, synthetic results, settlement and validity evaluation, finalisation to settlement version 3, the official practice weekly result (revision 1) with correct ranking and recovery, no championship points, no counter advance, audit records and a final consistent `verify` |
| Owner-waived manual acceptance, not executed and not recorded as passed | Checkpoint 5 (corrections and restoration) and Checkpoint 6 (repair and final verification), waived by the owner. Those behaviours rely on the automated evidence above, a distinction the owner accepted |

**Owner's database:**
* The owner's original database stays at `app_0006`, unmodified.
* No authorisation exists to migrate it, backfill it or change its data.
* The scratch database `diski9_6c5_acceptance` and the backup
  `diski9-before-6c5.dump` are retained, unless the owner asks for their removal.

**Limitations and deferrals carried forward:**
* the operator-invalidation reversal limitation;
* structural rather than full-replay membership verification;
* same-process reader contention;
* deployment-representative multi-process testing (Stage F);
* the unexecuted 10,000-participant Stage D stretch benchmark;
* D-29, D-36, S-07, hosted Supabase acceptance and the 6C.3 backlog.

Private mini-leagues remain excluded from the MVP.

---

## 5. Stage E: Leaderboards and historical performance UI (20 Nov 2026)

### 5.1 Baseline
* `feature/phase-6c5-leaderboards` at `ea17406` (formal Stage D closure; code
  `65a1440`), equal to the remote.
* Accepted suite: 1,603 of 1,603; CI run 63 passed. Fingerprint `88bcd717deca6c1c…`.
* Local acceptance Checkpoints 1–4 were passed; 5–6 were owner-waived. This
  distinction is preserved: the waived checkpoints were not executed.

### 5.2 Interfaces

**Leaderboards** (`/leaderboards`, `app/challenge/leaderboards_ui.py`)

The page shows a **Weekly | Championship** control, a stream selector (Beta;
Development only with development rounds enabled; Official only once the official
series has started) and a round or championship selector. Selectors carry round
codes and display names. The server resolves them within the selected stream, so a
code from another stream resolves to nothing.

*Weekly:*
* **Default round:** the newest round whose standings are official or provisional,
  else the newest locked round, else the newest open one. It is never chosen by
  insertion time.
* **Header:** the round, its stream badge, its classification, and its
  championship link: counted round n of 10, practice, void, not counted
  (restored), or assignment pending with its explanation. A championship name is
  never invented.
* **Personal summary:** shown above the table, independent of the page.
* **State banners (§12.2)**, with these additions:
  - a provisionally void round is worded as provisional ("Nothing is final yet");
  - the "Final · published …" line is replaced by "Corrected · version n" after a
    correction.
* **Podium:** final and under-review rounds, page 1, at most three names per place
  ("and N others").
* **Table:** rank (shared shown as "=n"), name, returned, net, recovery, and points
  for competitive official rounds only. Practice shows no points column. Provisional
  shows returned so far, settled, pending and status.
* **Pagination:** 50 rows per page from the service, with Previous, Next and "Go to
  my position".

*Championship:*
* **Header:** name, stream badge, lifecycle pill, *Under review* and *Corrected*
  pills, and ten-segment progress of valid counted rounds.
* **Completion:** the champion or joint champions (trophy icon), or "No champion: no
  participant scored points".
* **Review reasons** in plain words: reopened, recalculation pending, integrity
  review (`integrity_review` is never shown as definitive).
* **Disclosures:**
  - the D-30a sentence plus "Subsequent championships are unaffected";
  - the approved I-4 sentence when no counted round remains;
  - the L-33 continuation sentence;
  - restored rounds that do not count.
* **Upcoming:** "Everyone starts at zero".
* **Personal summary:** the rank, or the reason there is none (not entered,
  awaiting results, refunded only, practice only, not counted only, invalidated
  only).
* **Table:** rank, name, played, recoveries, top tens, points, and a rate column
  hidden below 900 px.

*Rules:* "How points works" is built from the engine's own `POINTS_150_75_V2`
configuration, so there is no second copy of the schedule.

**My Challenge** (`/challenge/me`)

*Current | History* are separate containers, so the existing 6C.3 and 6C.4 Current
callbacks are untouched. *Current* is unchanged except that, with the competition
database, the illustrative championship block is replaced by the real championship
summary for the current round's stream.

*History* (`app/challenge/history_ui.py`):
* stream and scope selectors (all championships, or one);
* the statistics card;
* the two charts;
* the entry list, 20 per page, newest first, with every entry type included;
* **Details:** loads one entry on demand, with the last published official result
  (labelled "under review, no longer definitive" while reopened) above the reused
  6C.4 `results_ui.panel` (nine predictions, four accumulators, frozen odds,
  scores, verdicts, void reasons and refunds).

**Prototype mode:** with no competition database, the Phase 6B demonstration pages
and their ribbon remain.

### 5.3 Read services
* **New:** `backend/services/challenge_history.py` (read-only, participant-scoped
  from the server-side principal; guests get `None`):
  - `my_history`: bounded pages with one joined query and no per-row reads;
  - `my_statistics`: §9.4;
  - `my_round_code_visible`: resolves a drill-down only for the viewer's own entry
    in that stream.
* **Extended:**
  - `leaderboards.round_list`, `default_round`, `round_id_for` and `stream_options`;
  - `weekly_board.championship_round` and `championship_rounds_required`;
  - `my_round_result`, which already existed, is used by the drill-down.

No migration and no write path were added. All reads remain READ ONLY at
REPEATABLE READ.

### 5.4 Personal statistics (§9.4, as implemented)
* **Competitive population:** ranked entries in counted rounds of the scope. It
  gives played, recoveries, the recovery rate (recoveries ÷ played; none when
  nothing was played), qualifying top tens, allocated (100 per played entry),
  returned, net, and ROI as aggregate net ÷ allocated, never an average; none when
  nothing was allocated.
* **Missed:** counted rounds not entered at all. A missed round is never an
  unsuccessful entry.
* **Separate counts, never mixed in:** practice entries (with recoveries), refunded
  entries, void rounds, not-counted (restored) entries, and entries awaiting
  official results.
* **Standings:** listed per championship from its current published version.
  Points are never added across championships or streams.
* **Reopened rounds** keep their published values; the card says so.
* **Chart 1:** cumulative allocation and return over the competitive population.
* **Chart 2:** cumulative published points for exactly one championship (the
  selected one, or the most recent with participation). Missed and refunded rounds
  add 0.

### 5.5 Privacy and security
* Public rows carry display names (name at lock, with retroactive anonymity at read
  time) and approved statistics only.
* The browser checks found no e-mail address and no UUID in any page text or element
  id.
* History and drill-downs are scoped to the signed-in participant. Codes of other
  participants' entries, or of another stream, resolve to nothing.
* Development data needs the existing `DISKI9_SHOW_DEVELOPMENT_ROUNDS`, which is
  refused in production.
* No authentication or operator safeguard changed.

### 5.6 Responsive design
* **Desktop:** full league tables.
* **≤ 900 px:** the optional rate column is hidden and the charts stack.
* **≤ 640 px:** every table row becomes a labelled card. The rank and name share a
  line, followed by two label–value pairs per line, so no field is lost. Selectors
  and the pager go full width.
* No page-wide horizontal overflow at 1360, 768 or 390 px.

### 5.7 Tests
| Suite | Tests |
|---|---|
| `tests/backend/test_backend_stage_e_history.py` (PostgreSQL) | 7: §9.4 definitions (recovery denominator excludes refunds; missed; aggregate ROI; separate practice and void counts; read-only); one-championship scope; zero denominators give no percentage; history of every entry type, newest first, paginated; privacy (guest, other participant, stream isolation, drill-down codes); the weekly selector (order, default, stream-bound codes, stream options, counted-round number); a reopened round under review with published values |
| `tests/test_stage_e_ui.py` (render) | 20: every weekly state (final, corrected, under review, provisional, provisionally void, final void, practice, refunded, not entered, guest, pending assignment, open, locked); podium cap; pager and rules; championship (in progress, joint champions, no champion, D-30a, all invalidated, review reasons including integrity review, non-ranked reasons, upcoming); history status texts, table values, summary and population note with zero denominators, and charts (empty, one round, many) |
| `tools/e2e_6c5/shots.js` (real browser, real app, real Supabase Auth) | 35 checks at three widths: guest and signed-in weekly; provisional, final, corrected, under review, practice, void and refunded states; pagination to page 2; current and historical championships (joint champions, D-30a, under review); My Challenge Current and History; championship scope; drill-down of a reopened round. Each page is checked for overflow, console errors, identifiers and e-mails, and no writes. **0 problems** |
| Existing UI suites | `test_challenge_ui`, `test_playtest_refinement`, `test_challenge_state`, `test_your_view_persistence` and weekly results: 97 passed, unchanged (prototype mode keeps the demonstration pages) |

### 5.8 Performance (1,000 participants, 11 rounds; this machine; `tools/phase6c5_perf_stage_e.py`)
| Read | Median | SQL statements |
|---|---|---|
| Weekly round selector | 2.5 ms | 2 |
| Weekly board, page 1 plus viewer row | 18.0 ms | 12 |
| Weekly board, last page | 15.0 ms | 12 |
| Championship list | 2.6 ms | 2 |
| Championship board (completed, 10 rounds) | 26.8 ms | 16 |
| My statistics: all championships / one championship | 5.7 / 6.3 ms | 5 / 6 |
| My history, page of 20 | 5.3 ms | 3 |
| Drill-down (`my_round_result` plus `my_settlement`) | 10.6 ms | 15 |

The statement counts do not grow with the page size or the number of participants:
there is no N+1 pattern. These are service timings, not end-to-end page times.
Multi-process testing remains Stage F.

### 5.9 Deviations and decisions (technical; no business rule changed)
* **Chart 1** is a cumulative allocation versus return line, as the Stage E
  instruction asks, instead of the grouped per-round bars sketched in spec §12.5.
* **Tablet** keeps the Net column (spec §12.2 suggested hiding it), because the
  Stage E instruction asks that no approved information be omitted at narrow widths.
* **Default stream** is Beta, or Official once started. With no current round, the
  My Challenge summary uses the development stream in development mode.
* **Prototype mode** keeps the demonstration leaderboards and illustrative My
  Challenge blocks, labelled, and they are removed whenever the competition
  database is configured (spec §12.1).
* **Weekly selector label:** round code plus its SAST match window. The code remains
  the authoritative value.
* **History scope:** stream plus all championships or one. No date filter, to keep
  one simple control.

### 5.10 Known limitations
* No dedicated "Development" toggle on My Challenge Current. It follows the current
  round's stream.
* Charts label rounds by code. With more than six rounds the axis labels are hidden
  and the code appears on hover.
* Rounds of the same weekend share their window label; the codes distinguish them.
* The browser checks run against a seeded development database, not the owner's
  data. The owner's visual acceptance covers that (`docs/phase6c5_local_acceptance_mac.md`, §15).

### 5.11 Regression and verification
* **Full suite** on a clean copy of `b983bba`: **1,629 passed and 1 failed**. That
  is 1,603 plus 27 new tests, less one that ran but failed.
  - The failure is `tests/test_match_context.py::test_browser_section_b_alignment_and_bookmaker_layout`,
    an unchanged Match Lab browser test that is timing-sensitive. Neither it nor the
    Match Lab code changed in Stage E.
  - It also failed once at `29ff049`, before Stage E existed. Rerun alone, it passed
    2 of 3 times, failing on a different assertion each time (a value read before it
    updated).
  - It is reported as intermittent and pre-existing, not as a Stage E failure.
* **Fingerprint** `88bcd717deca6c1c…` unchanged.
* **No change** to scoring, settlement, corrections, competition publication,
  championship processing, authentication, migrations, ingestion, odds, API
  clients, the screener or Portfolio Analysis.
* **Lint and formatting** clean.

### 5.12 Owner-requested refinements (20 Nov 2026; Stage E not yet closed)
The owner and ChatGPT reviewed the Stage E screenshots. They kept the functionality
and asked for presentation and responsive refinements before formal acceptance.
Nothing below changes a business rule, a calculation, the schema, authentication or
an operator command. Build Portfolio's Foundation, Balanced and Challenger cards are
unchanged.

**Owner feedback and what changed**

| Feedback | Change |
|---|---|
| Table values not aligned with headers | Cause: the rules list's class `lb-points` (`columns: 2`) was also on the Points cells, so each Points value was split into two CSS columns and pushed left of its header. Rules list renamed `lb-points-list`; cells use `lb-pts`. Alignment convention: rank centred in a compact column, name left, numbers right (tabular figures), text left; numeric and text columns size to content, the name column takes the rest; the leaderboard column is capped at 880 px so values stay near the names. True minus sign (U+2212) so signs align |
| Statistics cards: use the Build Portfolio cards as reference | `history_ui.stat_card`: the `.ch-out` structure (surface-2 card, 1 px border, 3 px left edge in the category colour, 8 px radius), plus a tinted header in the `.ch-tag` style (category text on the category's dim tint). Header colours come only from existing tokens: Rounds played slate (#a3b1c2), Recoveries teal (`--accent`), Top-10 finishes amber (`--b-chal`), Allocated violet (`--b-nine`), Returned green (`--b-found`), Net blue (`--b-bal`). Category colour stays in the header; performance colour (`--win` green, `--loss` red, neutral at zero) goes on the Net value and the return on allocation only. Bucket names are not used |
| Podium too wide, labels too muted | Compact podium (`c.podium(value_label=…)`): cards from 230 px wide, one "Returned" label per card, bright tabular values next to the names. Shared-rank rules unchanged (1, 1, 3 shows 1st and 3rd, no 2nd) |
| Controls far apart | Tabs, stream and round selectors form one left-aligned group. The stream selector still shows only with more than one eligible stream (unchanged rule); defaults and development restrictions unchanged |
| Codes as headings | Rounds are named by their SAST match window ("Round · 19–23 Nov 2026"); the code stays visible, de-emphasised, as the identity. Read services gained a display-only `window` field (`leaderboards.window_label`) on rounds, weekly boards, history rows and chart points. Charts number rounds 1…n, with window and code on hover |
| Mobile clipping (nav, history cards) and loose cards | Navigation at ≤ 480 px: the four links in a 2 × 2 grid of 36 px targets (481–600 px: wrapping row); account name truncates with its full name as a tooltip. Leaderboard cards: fixed 2.6 rem position area, then the name (16 px), then points ("150 pts") on the first line; the other values under the name in one row (two rows of two below 380 px for championship and provisional cards). History cards (≤ 900 px, so tablets no longer scroll sideways): round heading, championship on its own line, then three values per line (two below 400 px). Entry details: tighter accumulator cells below 420 px instead of a sideways scroll |
| Charts need three rounds | `CHART_MIN_ROUNDS = 3`, applied to each chart separately (below) |
| Long methodology text | Summary line stays visible; full definitions under "How your statistics are calculated". The Under-review notice moved above the cards |
| Progress bar small | Ten wide segments (12 px high, up to 380 px). A completed championship with fewer rounds (D-30a) shows "Completed with 9 valid rounds" with its unused segments dashed, so it never looks as if it is waiting |
| Wording | "1 round played", "2 recoveries", "1 top-10 finish" (`leaderboards_ui.plural`); "Top 10s" column |

**Chart threshold (owner decision)**
* **Chart 1** (cumulative allocation and return) appears when the participant has at
  least three distinct counted competitive rounds in the selected scope.
  - The count is `PersonalStats.allocation_rounds`, the chart's own series: ranked
    entries in counted rounds, using the last published values for a round under
    review.
  - Refunded entries, practice, void, missed, uncounted restorations and unresolved
    entries never count. A counted round the participant did not recover does count.
* **Chart 2** (cumulative championship points) appears when the participant played at
  least three counted rounds of the championship it shows.
  - That championship is the selected one, or for "All championships" the most recent
    one; points are never added across championships.
  - The count is `PersonalStats.points_rounds`: the series points marked `eligible`.
  - Missed and refunded rounds are still plotted when the chart shows, but never count
    toward the threshold.
* **Below three rounds**, a compact placeholder appears instead: "Your … chart will
  become available after 3 eligible rounds", with three progress segments and "n of 3
  eligible rounds completed".
  - If only one chart qualifies, it appears alongside the other chart's placeholder.
  - The statistics cards and the entry list never depend on the threshold.

**Tests**
* `tests/test_stage_e_ui.py`: 22 tests.
  - The charts test was replaced by threshold tests: 0, 1, 2, 3 and 5 rounds; missed
    or refunded rounds not counting; one chart unlocked without the other.
  - Assertions were added for six coloured cards, the methodology disclosure and
    natural plurals.
  - Three existing assertions were updated because the approved wording changed
    ("Top 10s"; the standings line now puts the name in bold; return on allocation is
    a separately coloured value). No assertion was removed.
* `tests/backend/test_backend_stage_e_history.py`: 9 tests (PostgreSQL). Two are new:
  - the threshold counts per chart and scope, with practice, refunded and missed
    rounds excluded and a failed counted round included, plus the friendly labels;
  - a correction (invalidation of R5) that lowers both counts, with the entry still in
    the history.
* `tools/e2e_6c5/refined.js` (real browser, real app, local Supabase Auth):
  - **Widths:** 1360, 768, 430, 390, 360 and 320 px.
  - **Coverage:** 108 page checks, guest and signed in. They span every weekly state;
    in-progress and corrected, under-review championships; My Challenge Current;
    History for all championships and for one; the entry details; and a second viewer
    with a 24-character account name, negative net and both charts locked.
  - **Element-level checks:** nothing outside the viewport; no text overflowing its
    box; no card cell outside its card or overlapping another; no table scrolling
    sideways; touch targets at least 32 px.
  - **Stress pass:** a 24-character name, seven-figure values and the maximum points
    are injected into the rendered page, then the checks repeat.
  - **Result:** 0 problems.

  The first run of these checks found real problems, all fixed before the final run:
  - 31 px pager and Details buttons;
  - text overflowing in provisional and practice cards;
  - the history table scrolling sideways on tablets;
  - the accumulator table scrolling on phones;
  - overlaps with seven-figure values.

**Screenshots**
* `docs/screenshots/phase6c5/refined/` holds the refined captures and six before/after
  comparisons (`compare_*.png`). The index is in that folder's `README.md`.
* The original Stage E captures are kept for comparison.
* The zero-net card is a styling specimen: the showcase data has no zero-net
  participant, so the value was set in the rendered page. This is labelled in the
  index.

**Regression**
* **Full suite on the refinement code: 1,632 passed and 0 failed.**
  - That is 1,629 + 1 from §5.11, plus two net new UI tests.
  - The intermittent Match Lab browser test
    (`test_browser_section_b_alignment_and_bookmaker_layout`) passed in this run. It
    remains recorded as intermittent and is carried forward to Stage F.
* **The two new PostgreSQL tests** were added after that run started. They were run
  with the Stage E files: 31 passed.
* **Fingerprint** `88bcd717deca6c1c…` unchanged.
* **Protected areas:** no diff in scoring, settlement, corrections, publication,
  championship processing, schema, authentication, operator commands, ingestion,
  odds, the screener, Match Lab or Portfolio Analysis.
  - The only shared change is a `title` (tooltip) on the account menu summary in
    `app.py`, plus navigation CSS scoped to 600 px and below.
* **Lint and formatting** clean.

**Limitations**
* Names locked into entries cannot change (set once in the database). The long-name
  checks on leaderboard rows therefore inject the name into the rendered page, while
  the long account name in the navigation is real.
* The 10,000-participant stretch run is still not executed (unchanged).

### 5.13 Final owner refinements (21 Nov 2026; Stage E not yet closed)
After a local visual review, the owner asked for three small presentation changes.
These changed no calculation, settlement or scoring rule, no status classification
and no schema.

1. **Weekly Challenge: demonstration button spacing.**
   - When no live round is available, the gap below "Try the demonstration round" (or
     "Leave the demonstration") now equals the gap above it. A scoped
     `.ch-actions.ch-demo-actions { margin-bottom: 14px }` matches the 14 px above,
     where the notice's 12 px margin collapses into the actions' 14 px.
   - Measured in the browser at 1360, 768, 390 and 320 px: 14 px above and 14 px below.
     Before the change it was 14 px above and 0 px below.
   - The button itself is unchanged.
2. **Your Result cards** (the 6C.4 results panel, shown in My Challenge and in the
   History drill-down).
   - They now use the statistics-card component, moved into `components.stat_card`
     and shared with Your Statistics. The performance colour helper moved to
     `components.tone`.
   - Colours:

     | Card | Header colour |
     |---|---|
     | Allocated | violet |
     | Returned | green |
     | Refunded | amber |
     | Net | blue, with the value green when positive, red when negative and neutral at zero or "Not final yet" |
     | Recovery | teal (value also teal) for "Recovered 100+"; amber for "Refund (not a recovery)", so a refund never looks like a recovery; slate for "Not recovered" and "Not decided yet" |

   - Descriptive values wrap at 17 px.
   - Layout: four across, or two across at 900 px and below.
   - The wording and values are unchanged (the 6C.4 tests still assert them).
3. **History chart headings.** They are now `h2.ch-h2.me-chart-title`, matching "Your
   statistics" (16 px, weight 700, same font), with or without the three-round
   placeholder. They wrap on phones.

**Verification**
* `tools/e2e_6c5/final.js` ran in a real browser at 1360, 768, 390 and 320 px: 71
  checks, 0 problems. It covers:
  - the measured button spacing;
  - four cards with the expected categories in the provisional, final, corrected,
    under-review, void and refunded states;
  - green positive and red negative Net;
  - refunds in amber, distinct from a recovery;
  - headings with the same computed font, size and weight as "Your statistics";
  - the element-level layout audit from `refined.js` on every page (nothing clipped,
    overflowing or overlapping).
* My Challenge Current shows no results panel in the showcase data, because there is
  no current round. The panel is the same component as the History drill-downs that
  were checked.
* Screenshots are the `final_*.png` files in `docs/screenshots/phase6c5/refined/`
  (indexed there).
* **New and updated tests.**
  - `test_backend_participant_results.py` gains
    `test_result_cards_keep_a_refund_distinct_from_a_recovery` (PostgreSQL). For a
    refunded entry it expects violet, amber, blue and amber cards with "Refunded" and
    "Refund (not a recovery)". For a recovered entry it expects green, blue and teal,
    with a positive Net value.
  - `test_stage_e_ui.py` now checks that both chart headings are `h2.me-chart-title`,
    with and without the placeholder.
* **Regression.**
  - Full suite: **1,634 passed, 0 failed**. The intermittent Match Lab test passed
    again; it stays recorded for Stage F.
  - The new test was added after that run started. It was run with the related files
    (`test_backend_participant_results.py`, `test_backend_stage_e_history.py`,
    `test_stage_e_ui.py`): 47 passed.
  - Fingerprint `88bcd717deca6c1c…` unchanged. Lint and formatting clean.

### 5.14 Owner approval and formal closure of Stage E (21 Nov 2026)
**Stage E: complete, owner-approved and formally closed.** Stage F has not begun and
needs a separate authorisation. The closure and Stage F handover record is
[`phase6c5_stage_e_closure_handover.md`](phase6c5_stage_e_closure_handover.md).

* **Acceptance sequence.**
  1. The owner inspected the application locally on the scratch copy (§15 of the Mac
     guide) and approved the overall interface.
  2. The owner requested refinements (§5.12), then three final ones (§5.13). All were
     implemented and tested.
  3. ChatGPT independently inspected the final screenshot evidence on GitHub.
  4. The owner authorised formal closure on 21 Nov 2026.
* **Accepted baseline:**
  - commits `b983bba`, `70667e7`, `eb12eec`, `a02cb68` and `e820790`;
  - head `e820790` verified locally and on the remote, with a clean worktree;
  - CI run 68 passed on `e820790`;
  - fingerprint `88bcd717deca6c1c…` unchanged;
  - migration head `app_0007`, with no Stage E migration.
* **Evidence:**
  - full suite 1,634 passed and 0 failed on the final code;
  - the PostgreSQL refund card test, added after that run started, passed in a
    focused run of 47 tests;
  - browser checks: 108 at 6 widths (first refinements) and 71 at 4 widths (final),
    0 problems each.
* **Carried forward:**
  - the intermittent Match Lab browser test (still unresolved; passed in the latest
    runs);
  - representative multi-process testing;
  - the unexecuted 10,000-participant runs;
  - the Current-tab result panel, which has no manual test.

  The handover (§8 and §9) lists them all.
* The accepted Stage E choices (§5.9, §5.12, §5.13) change no business rule.

## 6. Stage F1: development tooling and resumable championship scenarios (21 Nov 2026)
Stage F has four checkpoints, each reviewed separately:
* F1 development tooling;
* F2 integration and security;
* F3 performance and concurrency;
* F4 regression and the Stage G handover.

Only F1 was authorised at first, and this records it. **F1 was formally closed by
the owner on 21 Nov 2026 (§6.9); F2 is recorded in §7.** Starting point: `51c28b3` (Stage E
closure), CI run 69 passed, fingerprint `88bcd717deca6c1c…`, migration head
`app_0007`.

### 6.1 Delivered (no migration, no business-rule change)
* **`backend/dev_championship.py`** (new; development only, refused in production).
  * **Development participants.**
    - Accounts `devp-0001` … with one identity each, of provider `development`
      (subject `dev-participant-0001` …). Supabase Auth never issues that provider, so
      nobody can sign in as them. They have no e-mail address and no role.
    - Created idempotently (the identity is unique), at most 500 (ordinary testing),
      by an operator, with the audit event `dev_participants_created`.
    - `participant_principal` builds a server-side principal *only* for an account
      whose sole identity is a development one.
  * **Bulk entries (`submit_all`).**
    - One confirmed entry per development participant, through the existing
      `settlement_scenarios.submit_test_entry`, so drafts, entries, deadline,
      eligibility, frozen odds, the 4/3/2 buckets and the accumulators are all
      checked as usual.
    - Variants are deterministic: `spread`, `groups` (three shared portfolios) or
      `pairs` (identical pairs).
    - Participants who already have an entry are skipped. Refused for
      non-development rounds.
  * **Plans and ten presets**, as required by §17.2. Round scenarios are limited to
    the 6C.4 scenarios that finalise without alert handling. Actions are `correct`
    (owner reopening with one valid-to-valid correction) or `invalidate` (owner
    reopening, then the operator's invalidation), at most one per round.
  * **The runner (`run_plan`).** Per round:
    1. create and publish a development round, with a real deadline
       `deadline_seconds` away (default 60);
    2. submit entries;
    3. wait for the deadline on the database clock;
    4. lock;
    5. set the synthetic result mode and record the 6C.4 scenario;
    6. settle `as_of` the cutoff;
    7. finalise `as_of` the earliest finalisation (the existing development-only
       overrides);
    8. `verify_stream("development")`.

    Every step is one existing service call. A note is printed when D-32b or the
    five-entry minimum turns a round void or practice unexpectedly.
  * **State, from the database only.**
    - Round codes are `dev-<run-id>-<plan hash>-rNN`. Before each step `inspect_run`
      reads the round's real status, entries, result mode, evidence, settlement and
      score sets, and the runner does only the next missing step.
    - No runner table, file or audit lookup is needed. A different plan under an
      existing run id is refused.
    - `stop()` is checked before every step; waits poll it each second.
  * **Authentication.**
    - Before every write the principal is re-evaluated at the database clock
      (`refresh_clock`), then authorised for the capability: operator 12 h; reopening
      and invalidation 15 min (T-14).
    - When a check has lapsed, the runner calls `reauthenticate(role)` (the CLI asks
      for the password again) or stops safely.
    - No password is stored, and there is no bypass.
* **CLI (in `settlement_cli.py`; dispatched from `cli.py`):**
  - `dev-results participants --count N [--preview-only]` (operator);
  - `dev-results test-entry --all-dev-participants [--count] [--variants] [--seed]`
    (operator; the per-participant form with the participant's own password is
    unchanged);
  - `dev-championship presets | plan | run | status`.

  `run` takes `--preset` or `--scenario-plan`, plus `--run-id`, `--rounds K` (pause),
  `--operator` and `--owner`. The first SIGINT (Ctrl-C) stops at the next safe point;
  a second aborts. `status` is read-only and needs no password.
* **Unchanged:** scoring, settlement, corrections, publication, championship
  processing, authentication, the schema, the existing operator commands and their
  safeguards.

### 6.2 Naming and interpretation (deviations from the §17.2 proposal)
* **`--rounds K`** pauses after round K instead of setting the plan's length (a plan
  defines its rounds and its fingerprint).
* **Added:** `dev-championship` gained `presets`, `plan` and `status`.
* **Operator password:** `participants` and the bulk test-entry form need one. The
  specification did not say, and creating accounts should be audited.
* **The runner's own lock** checks the operator's `RUN_JOBS` capability after a
  password check. The older `round lock` and `round dev-open` commands (S-07,
  deferred) are unchanged.
* **Defaults:** 40 fixtures, because the first real run found 20 too few (§6.4).
* **Presets** are built for the stream's rounds per championship R: real runs use 10;
  the automated tests use 3 for speed (an isolated database setting).

### 6.3 Tests
* **`tests/backend/test_backend_dev_championship.py`:** 22 tests on real PostgreSQL,
  each scenario in its own database:
  - participants: idempotent, audited, development-only, no role, no e-mail; refused
    for ordinary participants and in production; real accounts refused;
  - bulk entries: nine valid predictions in 4/3/2 buckets on nine fixtures, varied,
    deterministic, resumable, refused for beta;
  - the real ten-round preset (8 participants, 40 fixtures, 5 s deadlines), completed
    10/10;
  - with-practice, with-invalidated, rollover, both historical invalidations (L-33
    reopen; D-30a boundary kept with R-1 rounds) and reopen-and-correct
    (republication, standings recalculated);
  - championship tie (joint champions; shared weekly ranks with equal points), zero
    points (no champion) and weekly ties;
  - interruption before settle, after lock, after finalise and before entries, then
    resume and a repeated resume;
  - graceful stop; a crash in the middle of the entries step; `--rounds` pause; a
    different plan refused;
  - operator 12-hour expiry (stop, or one re-authentication); owner 15-minute recency
    before reopening; failed verification stops; plan validation.
  - Every scenario ends with integrity checks:
    - no duplicate entries, points or memberships;
    - development participants only in development rounds;
    - no championships outside development;
    - verify consistent.
* **`test_backend_operator_cli.py`:** 2 new genuine-terminal tests (real local
  Supabase Auth, password at the hidden prompt):
  - `participants`: an ordinary participant is refused, then preview, create and
    repeat as the operator;
  - `dev-championship run` with a plan file: participant refused; `--rounds 1` pause
    (deadline wait visible); `status`; resume ("already final" … "Scenario
    complete"); `presets`.
* **Result:** both files passed (22 and 2).

### 6.4 Real ten-round runs through the CLI
Run on the dedicated development database `diski9_f1_e2e` (local test server, real
local Supabase Auth, owner account onboarded through the web sign-in, password typed
at the hidden prompt, default 60 s deadlines).

1. **First run (20 fixtures, the then default):** 10 rounds in 606 s.
   - Round 4 (`entry-all-void`) cancelled matches shared by so many other entries that
     at least half of all locked predictions were void. D-32b correctly made the round
     void, so the championship ended *in progress, 9/10*.
   - This was a preset problem, not a rule problem. The default became 40 fixtures
     (the 6C.4 guidance for that scenario), and the runner now prints a note when a
     round becomes void unexpectedly.
   - Log: `tmp/f1/real10_first_20fixtures.log` (local).
2. **Second run (40 fixtures, fresh database):**
   - Rounds 1–6 ran; the process was then **killed** while waiting for round 7's
     deadline.
   - The same command resumed: rounds 1–6 "already final", round 7 locked and
     finalised, round 8 done.
   - A **SIGINT** during round 9's wait printed "Stopping after the current
     operation", then "Stopped safely … run the same command again", exit 4.
   - The same command resumed again: rounds 1–8 "already final", rounds 9–10 done.
   - **Championship Nov-26: completed 10/10, champion `devp-0001`.**
   - Integrity on that database: 0 duplicate entries, 0 duplicate round scores, 0
     duplicate memberships, 10 score sets for 10 rounds, and `verify_stream`
     consistent.
   - About one minute per round. Log: `tmp/f1/real10_resume.log` (local).

### 6.5 My Challenge Current result panel (closes a Stage E limitation)
* **Setup:** on `diski9_f1_e2e`, using only the documented CLI commands
  (`tools/e2e_6c5/f1_current_steps.py`; the operator guide lists them):
  1. `round dev-open`;
  2. the signed-in participant's own `test-entry`, with their password;
  3. `test-entry --all-dev-participants` (9 entries, so competitive);
  4. lock after the real deadline;
  5. synthetic `all-correct`;
  6. `settle run --as-of`;
  7. later, `round finalise --as-of`.
* **Check:** `tools/e2e_6c5/f1_current.js` ran at 1360 and 390 px, provisional and
  then final.
  - The Current tab's "Your result" panel shows the four statistics-style cards: violet
    Allocated, green Returned, blue Net with a green value, and teal "Recovered 100+".
  - The layout audit found 0 problems.
  - Screenshots: `docs/screenshots/phase6c5/refined/f1_*_current_result_*.png`.
* **Not covered here:** refunded and void states on the Current tab use the same
  component; they were checked in the History drill-downs (§5.13). The full browser
  journeys belong to F2.

### 6.6 Performance boundary
F1 is not the performance stage.
* **Per-round reads:** `inspect_run` makes one query per planned round (bounded by
  the plan, at most 40), and the work in each round is the services' own.
* **Participants:** each runner step loads one principal per participant (at most
  500).
* **Real-run cost:** the real ten-round run spent almost all of its time waiting for
  deadlines.
* **Not started:** no F3 multi-process or 10,000-participant work.

### 6.7 Limitations and assumptions
* **Ctrl-C under test:** the test pseudo-terminal is not the controlling terminal, so
  a typed Ctrl-C there is just a character. The real run delivered Ctrl-C as SIGINT to
  the process, as a terminal does.
* **Reopen actions** wait until the round's last synthetic evidence time has passed
  (up to 4 minutes with the default `evidence_seconds`), so a correction always comes
  after the evidence.
* **An interrupted action** (reopened, not re-finalised) is completed only by running
  the original plan again; `run` explains this.
* **Shared development stream:** a database's development stream is shared, so a new
  run continues the current development championship. Use a dedicated development
  database for clean preset expectations.
* **Development participants stay** in the database. There is no removal command;
  they are excluded by being development-only.

### 6.8 Regression and verification
* **Full suite on the F1 code: 1,658 passed, 1 failed** (25 min 52 s; real PostgreSQL,
  local Supabase Auth, browser tests). That is 1,634 + 1 from §5.13, plus the 24 new
  F1 tests.
  - The failure is the known intermittent Match Lab browser test
    `tests/test_match_context.py::test_browser_section_b_alignment_and_bookmaker_layout`.
    Neither it nor Match Lab changed.
  - Rerun alone it passed 3 of 3. It stays carried forward; it was not weakened.
* **Focused runs:** `test_backend_dev_championship.py`, 22 passed; the two new
  terminal tests, 2 passed.
* **Fingerprint** `88bcd717deca6c1c…` unchanged. Migration head `app_0007` (no
  migration). Lint and formatting clean.
* **Owner's databases:** `diski9` (`app_0006`), the scratch copy
  `diski9_6c5_acceptance` (`app_0007`) and the backup were not touched. All F1 work
  used isolated `_test` databases and the dedicated `diski9_f1_e2e` on the local test
  server.

### 6.9 Owner approval and formal closure of F1 (21 Nov 2026)
The owner reviewed the F1 checkpoint report, accepted the implementation and
**formally closed F1**. The same decision authorised **F2 (integration and security
testing)** only; F3, F4 and Stage G remain unauthorised.

* **Baseline confirmed before closure:** `8379606` on
  `feature/phase-6c5-leaderboards`, local worktree clean and equal to the remote;
  GitHub CI run 70 passed on `8379606`; fingerprint `88bcd717deca6c1c…`; migration
  head `app_0007`.
* **Acceptance evidence (as reported):**
  - 22 new development-tooling tests and 2 new genuine-terminal CLI tests passed;
  - full local regression 1,658 passed, 1 failed: the known intermittent Match Lab
    browser test, which passed 3 of 3 isolated reruns;
  - a real ten-round championship completed 10/10 through the CLI, surviving a hard
    kill and a SIGINT, with no duplicate entries, score sets or memberships on resume;
  - development-only participant restrictions tested;
  - Current-tab result panel verified provisional and final at desktop and mobile
    widths;
  - no migration and no business-rule change.
* **The first 20-fixture run** (§6.4) produced a correctly voided round under D-32b
  and a 9/10 championship; the 40-fixture run completed 10/10. Both are kept as
  evidence. The void round was correct competition behaviour, caused by the preset's
  fixture pool, not an engine defect.
* **Limitations carried forward:**
  - development participants remain in their isolated database;
  - a development stream is shared within its database;
  - clean preset runs need isolated development databases;
  - Current-tab refund and void presentations still to be tested (F2);
  - the intermittent Match Lab test is unresolved (F4 root cause);
  - the older S-07 operator commands are unchanged (assessed in F2, §7.2).

## 7. Stage F2: integration, browser acceptance and security testing (21 Nov 2026)
Authorised by the owner on 21 Nov 2026 together with the F1 closure (§6.9). F2 is a
testing, verification and security-assessment checkpoint: no migration, no
competition-rule change, no redesign. F3, F4 and Stage G are not authorised.

### 7.1 Baseline
* `feature/phase-6c5-leaderboards` at `8379606` (F1), local worktree clean and equal
  to the remote; CI run 70 passed on `8379606`; fingerprint `88bcd717deca6c1c…`;
  migration head `app_0007`. F1 closure documentation: `a8abba3`.
* Isolated databases only: the per-file `_test` databases of the test suite and a
  dedicated `diski9_f2_e2e` development database for the browser journeys.
  `diski9_f1_e2e` was not reset or overwritten. The owner's `diski9`,
  `diski9_6c5_acceptance` and the backup live on the owner's Mac and were not
  touched.

### 7.2 S-07 security assessment (first checkpoint)
**Question.** The 6C.3 commands `round lock` and `round dev-open` identify the
operator by `--by-email` and ask no password. Is that an immediate risk?

**Method.** Code inspection of every CLI entry point and its authorisation path, the
runtime database grants (migrations `app_0001`/`app_0002`), and six executed
characterisation tests through the real `diski9` CLI on an isolated `_test` database:
`tests/backend/test_backend_f2_s07_assessment.py` (6 passed).

**Affected commands (all in `src/diski9/cli.py`).**

| Command | Identity | Authorisation actually enforced | Password / recency |
|---|---|---|---|
| `round create`, `round publish` | `--by-email` | `PUBLISH_ROUND`, roles read from the database | none |
| `round dev-open` | `--by-email` | `PUBLISH_ROUND`; refused when `DISKI9_APP_ENVIRONMENT=production`; `dev-` codes only | none |
| `round lock` | `--by-email`, or none (runs as `SYSTEM`) | `RUN_JOBS` if an email is given; refused before the deadline (database clock); idempotent | none |
| `account grant-role/revoke-role/grant-feature/revoke-feature` | `--by-email` | active **owner** in the database | none; **no T-14 15-minute recency** although these are `MANAGE_ROLES`/`MANAGE_ENTITLEMENTS` |
| `account suspend/reinstate` | `--by-email` | active operator or owner | none; no T-14 recency (`SUSPEND_USER`) |
| `account bootstrap-owner` | target email + `--confirm` | only while no owner exists | none (documented break-glass) |

Not affected: every 6C.4/6C.5 settlement, correction, `competition`
(`status/verify/backfill/repair`), `dev-results` and F1 `test-entry`,
`dev-results participants` and `dev-championship run` command. They verify the
password with Supabase Auth at a hidden terminal prompt, refuse a missing terminal,
re-evaluate roles at the database clock and apply T-14 to sensitive capabilities
(existing genuine-terminal tests in `test_backend_operator_cli.py`, including
`test_database_access_alone_is_not_authority`,
`test_dev_participants_need_an_operator_password` and
`test_dev_championship_cli_pauses_resumes_and_reports`). The F1 runner's operator
and owner sessions come from `authenticate_operator`; its development participants
are built without a password only for accounts whose sole identity is
`development` (tested in F1).

**Answers.**
1. *Production.* `round dev-open` refuses `production`, but that is an
   accident guard read from an environment variable, not a security boundary.
   `round create/publish/lock` and `account …` run in any environment. Per the
   repository records no production competition database exists: hosted Supabase is
   Phase 10 and there is no production scheduler in 6C.5 (L-12).
2. *Beta / Official.* `create`/`publish` make **beta** rounds (series `beta`;
   tested); nothing can create an official round (D-38 gate; `counts_toward_official_championship`
   is always false). `lock` can lock a beta round, but only after its deadline,
   which the database trigger enforces and which the scheduled lock would do anyway;
   it is idempotent and changes no entry. `dev-open` makes development rounds only.
3. *Impersonation by a non-operator.* Over the web: **no**, these commands have no
   web route. Through the CLI: naming one's *own* non-operator address, an unknown
   address or an unverified address is refused with nothing written (tested). But a
   person who can run the CLI **with the application's database credentials** can
   name an operator's or owner's address and act as them without a password; the
   audit log then attributes the action to that operator or owner (tested for
   `dev-open` and `grant-role`).
4. *Trust boundary.* The commands rely on a trusted server shell plus
   `DISKI9_APP_DATABASE_URL`. That credential is already decisive: the runtime role
   `diski9_app` has `SELECT/INSERT/UPDATE/DELETE` on `user_roles` and the other
   projection tables (`app_0001` `_grants`, RLS policy `runtime_access` `USING (true)`
   in `app_0002`), so its holder can grant themselves any role by SQL. The email-only
   path therefore gives **no capability beyond what the credential already gives**;
   what it loses is the S-07 principle that database credentials are never proof of
   operator authority, and reliable attribution.
5. *Audit.* Every write is audited in the same transaction (`round.created`,
   `round.published`, `round.locked` jobs, `role.granted`, `account.suspended`, …),
   but the actor is whoever was named, so attribution is only as trustworthy as the
   shell user.
6. *Recency bypass.* Yes for `account` role, entitlement and status changes: they
   take no `Principal`, so the T-14 15-minute recency that the settlement path
   enforces for `MANAGE_ROLES`, `MANAGE_ENTITLEMENTS` and `SUSPEND_USER` never
   applies. `round` commands need only non-sensitive capabilities (`PUBLISH_ROUND`,
   `RUN_JOBS`); `cli_principal` stamps `authenticated_at = now`.
7. *F1 runner.* Protected: password at a terminal prompt via Supabase Auth, 12-hour
   operator session with one re-authentication, owner 15-minute recency before a
   reopen; refused in production; development participants only.
8. *Other commands sharing it.* `round create/publish` and the `account` role,
   entitlement and status commands (table above).

**Minor rough edge (not a security gap).** When `round dev-open` is refused by the
service (`Forbidden: missing_capability:round.publish`) or by the `dev-` prefix check,
the CLI prints a Python traceback (exit 1) instead of a clean `error:` line (exit 2).
The refusal happens before any write (tested). Not changed in F2.

**Severity.** *Current exposure: low.* Exploiting it needs shell access with the
application's database credentials, which already permit the same changes directly;
there is no web path, no production database, and official rounds cannot be created.
*Before any hosted or official deployment: medium* (misattributable audit records
and a T-14 bypass for role, entitlement and status changes).

**Reproduction (isolated data only).** Run
`tests/backend/test_backend_f2_s07_assessment.py` with
`DISKI9_APP_TEST_DATABASE_URL` pointing at a `_test` database; it creates throwaway
accounts with verified addresses and drives `diski9 round …` and
`diski9 account grant-role …` through a pseudo-terminal.

**Recommendation (Phase 6C.6, and a release gate before Phase 10 hosting or D-38
activation).**
* Move `round create/publish/lock/dev-open` and the `account` role, entitlement and
  status commands onto `authenticate_operator` (`--operator`, hidden password
  prompt, terminal required), with T-14 recency for `MANAGE_ROLES`,
  `MANAGE_ENTITLEMENTS` and `SUSPEND_USER`.
* Keep an explicit, separately named scheduler identity for `round lock` (the
  existing `SYSTEM` path) for the future 6C.6 scheduler, distinguished in the audit.
* Keep `bootstrap-owner` as the documented break-glass step (only while no owner
  exists).
* Consider a separate, narrower database role for the web runtime, so the web
  process's credential cannot write `user_roles` (defence in depth).
* Clean `error:` handling for `Forbidden`/`ValueError` in `cmd_round`.

**Decision boundary.** The issue cannot change genuine competition data without the
application database credential, which already allows those changes; it is limited
to a trusted server shell; no production or official data exists. **Deferral to
Phase 6C.6 is safe**, so F2 continued without remediation. Nothing was weakened.
F2's operator tests use the authenticated commands; the legacy `round` commands are
used in F2 only on isolated development databases, as in F1.

**Impact on F2.** None blocking. The browser-journey data is built with the F1
runner (authenticated) and the services directly in test databases.

### 7.3 New tests
| File | Tests | What it adds |
|---|---|---|
| `tests/backend/test_backend_f2_s07_assessment.py` | 6 | S-07 characterisation through the real CLI (§7.2) |
| `tests/backend/test_backend_f2_integration.py` | 8 | Privacy and isolation across the read services *and* the Dash components rendered from real database results; public payload inspection; deleted-account alias with preserved standings; withdrawal on each side of the five-entry boundary; provisional boards without points; practice excluded from progress; development and beta championships independent; nothing in the official stream; no cross-stream membership |
| `tests/test_callback_wildcard_outputs.py` | 1 | Regression for defect F2-2 (§7.9) |
| `tests/test_stage_e_ui.py` (`test_pager_and_rules`, extended) | — | Regression for defect F2-1: distinct pager ids, page parsing |
| `tests/backend/test_app_persistence.py` (`test_direct_visit_with_an_empty_store_shows_the_confirmed_entry`) | 1 | Regression for defect F2-3 |

Each regression test was confirmed to fail on the code before its fix.

### 7.4 Browser acceptance journeys (§17.3)
**Tool:** `tools/e2e_6c5/journeys.js` (Node Playwright) against the real app, real
PostgreSQL and the local Supabase Auth harness, at **desktop 1360, tablet 768 and
mobile 390 px**. Data: `seed.py` (the Stage E showcase: 60 participants, 14 rounds,
corrections) plus `seed_f2.py` (R15, a shared rank 31 spanning rows 31–60; and a
separate database whose championship completes with no points) on the isolated
`diski9_f2_e2e` and `diski9_f2_e2e_nochamp`, all through the real services.

**Authoritative comparison.** `tools/e2e_6c5/f2_expect.py` reads the same read
services the pages use (`weekly_board`, `championship_board`, `my_history`,
`my_statistics`) for a guest and two signed-in participants and writes the
expectations. For every journey the script compares the visible ranks (including
"=n"), names, points, viewer highlight and page, state labels and headers with them,
then runs the element-level layout audit from `refined.js` (nothing clipped,
overflowing or overlapping), checks for page-wide horizontal overflow and for any
e-mail address or UUID in page text or element ids, and collects browser errors.

| # | Journey | Verified (each at 3 widths; guest and two participants where meaningful) |
|---|---|---|
| J1 | Provisional weekly | rows and positions = service; "Returned so far / Settled / Pending" headers, no Points; "Provisional ·" banner; personal summary or sign-in prompt |
| J2 | Final weekly, highlight, page two | page 1 and page 2 rows = service; Points column; viewer highlighted on its page; "Showing 51–60 of 60" |
| J3 | Shared ranks across the boundary | page 1 ends with "=31", page 2 starts with "=31"; "Go to my position" opens page 2 with the viewer highlighted |
| J4 | Practice round | rows = service; no Points column; practice explanation |
| J5 | Void round | no table; void wording; "Round void · your 100 credits were refunded" for an entrant |
| J6 | Championship in progress | standings = service; "In progress"; counted-round progress; personal points |
| J7 | Joint champions | standings = service; "Joint champions" naming both |
| J8 | No champion | completed; "No champion: no participant scored points."; nobody named |
| J9 | Under review | weekly "last published results" banner; championship "Under review" |
| J10 | Corrected and shortened | weekly "Corrected · version 2"; championship "corrected after completion", "Completed with 9 valid rounds" (D-30a), never "Short" |
| J11 | History, filters, drill-down | every own entry listed; statistics values = service; championship filter narrows the rows; the reopened round's drill-down shows "Last published official result" and the four result cards |
| J12 | Guest | public standings only, no highlighted row, sign-in prompts, no history or statistics |

Also per width: stream visibility on a server **without** the development flag (no
development stream or round code visible), navigation (routes 200, nav links
resolve), **no uncaught page or console errors**, and **read-only** (score sets,
championship versions, competition audit rows and entries unchanged by every page
load and crafted request; account rows from the throw-away sign-ins are excluded).

**Result (final run, after the fixes in §7.9): 253 checks, 0 problems; every
journey 0 problems at every width** (`tmp/f2/journeys_final.log`, local). Earlier
runs found the defects in §7.9 and script-side mistakes (CSS upper-case text,
expected wording), which were corrected in the script, never by weakening a check.

**Screenshots:** `docs/screenshots/phase6c5/f2/` (indexed): every journey at
desktop, key states at tablet and mobile, and the Current states; earlier evidence
is untouched.

### 7.5 My Challenge Current result panel
**Tool:** `tools/e2e_6c5/f2_current.py` makes each state the live current round
through the services (the viewer's own `submit_test_entry`, five development
participants, lock after the real deadline, synthetic results, settlement and
finalisation with the development-only `as_of`, the owner's reopening with
corrections; no clock change). `f2_current.js` compares the four cards with the
participant's `my_settlement` at 1360, 768 and 390 px and runs the layout audit.

| State | Cards (Allocated · second · Net · Recovery) | Result |
|---|---|---|
| Refunded entry (all nine void, round valid) | violet 100.00 · **amber "Refunded" 100.00** · blue **0.00 (zero tone)** · **amber "Refund (not a recovery)"** | pass ×3 |
| Void round (D-32b) | violet · amber "Refunded" 100.00 · blue 0.00 · amber "Refund (not a recovery)" | pass ×3 |
| Negative (final, not recovered) | violet · green "Returned" 0.00 · blue **−100.00 (red)** · slate "Not recovered" | pass ×3 |
| Under review (owner reopened with corrections) | violet · green 5,080.83 · blue +4,980.83 (green) · teal "Recovered 100+"; review wording; the official result marked under review | pass ×3 |
| Corrected (re-finalised) | violet · green 5,080.83 · blue +4,980.83 · teal "Recovered 100+"; correction wording | pass ×3 |

With F1's provisional and final successful recoveries (§6.5), every Current state is
covered. **Zero Net** is shown through the refund states (Net 0.00, zero tone); a
*recovered* entry whose gross is exactly 100.00 cannot be produced naturally and was
not manufactured. The card styling is unchanged and identical to the History
drill-down component.

### 7.6 Privacy and participant isolation
* **Services and rendered components** (`test_backend_f2_integration.py`): another
  participant's round code reveals nothing (`my_round_code_visible` is `None`,
  `my_round_result` is `None`); history pages −3, 0, 1 and 999 return only one's own
  entry; an unknown championship or one of another stream is refused; development is
  refused unless enabled; guests get no history; statistics count only one's own
  rounds. Weekly and championship boards, and the Dash components built from them,
  contain no user UUID, e-mail address, identity subject or fixture id (so no
  selections), for a guest and for a participant; `WeeklyRow` has only public fields.
* **Crafted Dash callbacks (browser):** a captured drill-down request of one
  participant was replayed from a signed-in account with no entries and from a guest
  session, also with the stream switched to beta and official. The participant got
  "That entry is not available.", the guest an empty detail; none contained the
  other participant's name, values or detail panel. The account with no entries saw
  only its own empty history. The server derives the participant from the session;
  no callback accepts a user identifier.
* **Anonymity:** retroactive and non-retroactive anonymity and e-mail-free names are
  covered by the existing suites (`test_backend_accounts.py`,
  `test_backend_weekly_results.py`, `test_backend_championship_corrections.py`).
  **Deleted account (new):** with the account's status set to `deleted` (there is no
  deletion workflow yet; D-36), the weekly and championship boards show its alias
  instead of its username, with the same position and points, and the standings are
  otherwise unchanged.

### 7.7 Operator authentication and permissions
Covered by the existing genuine-terminal tests (real local Supabase Auth, hidden
password prompt, real PostgreSQL) in `test_backend_operator_cli.py`, run again in
F2: correct password (`test_authorised_operator_and_password_never_shown`), incorrect
password (`test_incorrect_password_fails_closed`), provider down or unconfigured,
password never an argument and no terminal refused
(`test_password_is_never_an_argument_or_piped`), non-operator
(`test_participant_cannot_run_operator_commands`), unknown address
(`test_database_access_alone_is_not_authority`), owner-only reopen and the full
lifecycle (`test_full_lifecycle_through_the_cli`), missing confirmation
(`test_declined_confirmation_changes_nothing`), stale preview token
(`test_stale_preview_is_rejected`), expired recency at confirmation
(`test_recent_authentication_boundary_at_confirmation`), `competition
status/verify/backfill/repair` (`test_competition_*`), participant test entries, and
the F1 commands. The 12-hour session expiry and the owner's 15-minute recency in the
runner are tested at service level (F1, `test_backend_dev_championship.py`); the
service-level T-14 matrix is in `test_backend_corrections.py` and
`test_backend_auth_unit.py`. Audit attribution and no partial writes are asserted in
those tests. The legacy email-identified commands are assessed in §7.2.

### 7.8 Competition integrity, corrections and failure recovery
New coverage is in `test_backend_f2_integration.py` (§7.3). The rest is the existing
PostgreSQL suites, re-run in the full regression, not replaced:
* **validity and scoring:** five-entry minimum and practice
  (`test_four_valid_entries_make_a_practice_round`,
  `test_five_valid_entries_make_a_championship_round_and_lock_is_idempotent`, F2
  withdrawal boundary), D-32b strict majority of played instances, voided
  predictions, D-33 refunds, no points without recovery (`test_settle_entry.py`,
  `test_settle_rules.py`, `test_competition_adapter.py`,
  `test_backend_weekly_results.py`), shared ranks and equal points (F1 ties, F2 J3),
  no points before finalisation (F2);
* **championships:** ten counted rounds, practice and invalid rounds excluded,
  mid-championship joining, rollover, joint champions, no champion, immutable
  membership, D-30a, no cross-stream contamination (`test_backend_championships.py`,
  `_edges.py`, `_corrections.py`, `_capacity.py`, `_sequences.py`, F1 presets, F2);
* **corrections:** reopening, corrected results, re-finalisation, updated
  standings, preserved audit, under review, no duplicate score sets, no speculative
  publication (`test_backend_corrections.py`, `_championship_corrections.py`, F1
  reopen-and-correct, F2 Current review and corrected);
* **failure and recovery:** failed publication and recalculation roll back
  (`test_failure_rolls_back_weekly_and_championship_publication`), reads never see a
  partial publication (`test_reads_are_consistent_during_publication`), idempotent
  retries (`test_repeated_processing_and_restart_change_nothing`,
  `test_repeated_backfill_is_a_no_op`, `test_repeated_repair_is_a_no_op`), interrupted
  backfill and repair (`test_interrupted_*`), interrupted F1 runs (F1), verification
  detects inconsistency (`test_tampered_counter_is_repaired_without_touching_membership`,
  `test_material_inconsistency_is_refused_and_reported`), repair needs an operator,
  a preview and a confirmation (`test_repair_preview_writes_nothing_and_needs_an_operator`,
  `test_repair_safeguards`). All fault injection ran in isolated `_test` databases.

### 7.9 Defects found and fixed in F2 (presentation layer; no competition behaviour changed)
1. **F2-1 Pager "Next" did nothing for some viewers.** When the viewer's own page was
   the next page, "Next ›" and "Go to my position" had the same Dash id
   (`{"t": "lbw-goto", "i": 2}`), so neither click reached the server. "Go to my
   position" now has its own id (`"me-<page>"`, parsed by `goto_page`). Found by J2.
2. **F2-2 HTTP 500 and console errors from wildcard callbacks.** The leaderboard,
   history and My Challenge tab callbacks returned a bare `no_update` for
   pattern-matching outputs when a pager or history button was re-rendered without a
   click; Dash rejects that. They now raise `PreventUpdate`. Found by the
   browser-error check.
3. **F2-3 My Challenge on a direct visit.** Opening My Challenge in a new tab or from
   a bookmark rendered before the session store was filled from the account, so a
   confirmed entry (and its result) showed as "The deadline has passed without a
   confirmed entry" until a reload; in-app navigation was correct. The page now
   renders from the account state (`persist.hydrate`, read-only). Found while
   preparing the Current states.
4. **F2-4 Long round codes widened the History table** on desktop (the code line did
   not wrap; seen with 30-character development codes). The code line now wraps.

### 7.10 Stream isolation
* Development rounds are hidden unless enabled: services refuse them
  (`NotFound`), and a server without the development flag shows no development
  stream or round code (J-checks at three widths); existing
  `test_development_rounds_are_hidden_unless_enabled` and the locked-entry tests.
* Development participants cannot enter beta or official rounds (F1).
* Beta and development championships progress independently with no shared
  counters, names or membership; nothing reaches the official stream, which stays
  gated (D-29, D-38; `test_official_stream_is_gated_and_beta_untouched`, F2).
* The Official series was not activated anywhere; official assertions use isolated
  test databases only.

### 7.11 Limitations and deviations for owner review
* **Beta finalisation end to end:** a genuine (beta) round can be finalised only
  after cutoff + 24 h and takes no time override (approved rule), so F2 settles a
  beta round (provisional, no points) but completes championships with development
  rounds. The paths are the same apart from the development-only `as_of`.
* **Deleted accounts** are simulated by status; there is no deletion workflow (D-36
  is a separate release requirement).
* **No-champion** data lives in a second isolated database, served separately.
* **Current "under review"** shows the provisional re-settlement with the official
  result marked under review, as designed in 6C.4.
* **Minus signs:** leaderboards use the true minus (U+2212) but the result cards
  print a hyphen-minus ("-100.00"). Presentation only; not changed (owner's call).
* **Crafted-callback coverage** replays the drill-down and history requests; other
  callbacks take no participant identifiers by design.
* **Intermittent Match Lab browser test:** see §7.12; not investigated further in F2
  (F4).
* **S-07** remains deferred to 6C.6 per §7.2 (release gate before hosting).
* **Timing data:** incidental only (a journey run takes about 8.5 minutes); no
  performance work (F3).

### 7.12 Regression and verification
* **Full local suite on the F2 code (all fixes included): 1,675 passed, 0 failed, 0
  skipped** (26 min 14 s; real PostgreSQL, local Supabase Auth, browser tests). That
  is F1's 1,659 plus the 16 new F2 tests (6 + 8 + 1 + 1).
* **Intermittent Match Lab browser test**
  (`tests/test_match_context.py::test_browser_section_b_alignment_and_bookmaker_layout`):
  passed in this run; no occurrence during F2. Still unresolved (F4).
* **Focused run:** the F2 files, `test_stage_e_ui.py`, `test_app_persistence.py`,
  `test_backend_operator_cli.py` (genuine terminal) and
  `test_backend_dev_championship.py`: **91 passed** (10 min 46 s).
* **Browser:** journeys 253 checks, 0 problems; Current states 15 checks (5 states
  × 3 widths), 0 problems.
* **Fingerprint** `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`
  unchanged. **Migration head** `app_0007` (no migration). Lint and formatting clean.
* **No business rule changed:** scoring, settlement, D-32b, D-33, championship
  processing, corrections and authentication code are untouched; the four fixes are
  in the Dash presentation layer (`callbacks.py`, `leaderboards_ui.py`, `pages.py`,
  `style.css`).
* **Databases:** F2 used isolated `_test` databases, `diski9_f2_e2e` and
  `diski9_f2_e2e_nochamp` on the local test server. `diski9_f1_e2e` was not reset or
  overwritten. The owner's `diski9` (`app_0006`), `diski9_6c5_acceptance`
  (`app_0007`) and `diski9-before-6c5.dump` are on the owner's Mac and were not
  touched. No production or Official-series operation.
* **Odds research trial:** not touched by F2 (separate checkout, branch and
  schedule).

### 7.13 Recommended F3 handover (performance and concurrency; not started)
* **Multi-process load:** run the app under a production-style WSGI server with
  several workers against one PostgreSQL, and drive concurrent readers of the
  leaderboards and My Challenge (the F2 journeys can provide realistic request
  mixes) while finalisation, corrections and championship processing run.
* **Scale data:** the F1 runner and `seed_f2.py` patterns can build 1,000 and
  10,000-participant development streams in isolated databases (the stretch runs
  of Stages D and E were never executed).
* **Hotspots to measure:** `weekly_board` provisional computation, the
  championship board with many members, `my_statistics`, the history page, and the
  extra account read now made on a direct visit to My Challenge (§7.9 F2-3).
* **Contention:** readers in the same process can contend (§4.8); the read cache
  and the 3-second published-round cache should be measured under load.
* **Then F4:** the intermittent Match Lab browser test's root cause, the full
  regression determination and the Stage G handover.
