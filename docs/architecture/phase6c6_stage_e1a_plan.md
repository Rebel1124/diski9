# Phase 6C.6 Stage E.1a — Implementation plan and acceptance checklist

**Status:** plan for owner review (21 Nov 2026). **Implementation not authorised.**
Design: [`phase6c6_stage_e1_design.md`](phase6c6_stage_e1_design.md) (approved in
principle: ADP-01–ADP-10, ADP-14–ADP-19, ADP-21, ADP-22; ADP-11–ADP-13 and ADP-20
provisional where they concern automated API-Football refresh, i.e. E.1b).
Branch `feature/phase-6c6-operations`; application baseline `c49de86`; migration
head `app_0007`; fingerprint `88bcd717…cec4`.

**E.1a scope:** automated **Beta** draft creation, readiness evaluation on the
football store as it is, derived preparation states and monitoring. **No new
API-Football call, no migration, no new rule, no publication, no Official.** The
football store continues to be refreshed by the existing manual
`refresh-data --with-odds` until E.1b.

---

## 1. Modules and functions

| Module | Change |
|---|---|
| `backend/jobs/prepare.py` (**new**) | Pure week calculator and the preparation steps. `upcoming_week(now, schedule) -> Week(iso_year, iso_week, code, window_start, window_end, target, create_at)`; `preparation_due(...)`; `run_preparation(run, report)` called from `tick()`; `plan_preparation(...)` for `--dry-run`. Readiness outcome encoding (§6) |
| `backend/services/rounds.py` | **New** `create_scheduled_draft(engine, actor: System, *, iso_year, iso_week, job_run_id) -> ScheduledDraft(created: bool, round: RoundView)` (§2). `create_round`, `publish_round`, `publication_readiness` **unchanged** |
| `backend/jobs/config.py` | `SchedulerConfig` gains `prepare: bool = False`, `prepare_streams: tuple = ()`, `prepare_create_lead: timedelta = 78 h`, `prepare_readiness_interval: timedelta = 30 min`, `prepare_grace: timedelta = 6 h`; `load_config` reads and validates them (§4) |
| `backend/jobs/reconciler.py` | `tick()`: after the round loop and before `_attention`, call `prepare.run_preparation(run, report)` inside the same `_BudgetSpent`/`LockLost` handling; `_Run` gains an injectable `snapshot_builder` (default: a function that opens the football store and calls `build_live_snapshot`), mirroring `provider_factory`. `_attention` adds preparation notes. `plan_tick` adds planned preparation steps |
| `jobs_cli.py` | Pass the football-store engine factory; `jobs status` prints the preparation section; no new command |
| `backend/ops/snapshot.py` | `Snapshot.preparation: dict` (upcoming week, round status, latest readiness record, step streaks); `classify()` gains `draft_lapsed` for drafts (§7) |
| `backend/ops/checks.py` | New findings (§8) |
| `backend/ops/history.py` | `KNOWN_JOBS` += `scheduler.prepare_draft`, `scheduler.prepare_readiness` (so `ops jobs` and `round inspect` show them) |
| `ops_cli.py` | `ops status` "Preparation" section |
| docs | `operations_scheduler.md`, `operations_monitoring.md`, `operations_runbook.md`, `operations_guide.md`, `.env.example` |
| tests | §9 |

No change to `challenge/`, `migrations_app/`, settlement, corrections,
championships, results, authentication or the Stage D locking module.

## 2. Scheduler-only draft-creation service and its security boundary

```
create_scheduled_draft(engine, actor, *, iso_year, iso_week, job_run_id) -> ScheduledDraft
```
* **Actor:** must be `rounds.SYSTEM` (`isinstance(actor, System)`); a `Principal`
  is refused (`Forbidden("scheduled_only")`) — people use `round create`.
* **Inputs:** only the ISO year and week (validated with `date.fromisocalendar`)
  and the job-run link. **No** code, window, series, schedule or development flag
  can be supplied.
* **Derived:** schedule = the active `weekend` row (latest version, as
  `create_round` uses); code `f"{iso_year}-W{iso_week:02d}-weekend"`; window
  `weekly_window(rule, iso_year, iso_week)`; series = the schedule's series, which
  must be `beta` (refused otherwise); `is_development = False`.
* **Write (one transaction):** `INSERT … ON CONFLICT (code) DO NOTHING RETURNING
  id`; if a row was inserted: `round_status_history` (`None → draft`, actor NULL,
  reason `created (scheduled)`, `job_run_id`) and audit `round.create`
  (`actor_role = 'system'`, `job_run_id`, `after = {code, scheduled: true}`).
  If not inserted: return `created=False` with the existing round's view; **no
  write of any kind** to the existing row.
* **Never:** publish, build or store a snapshot, change status, touch any other
  round.
* **Static guard** (`test_backend_scheduler.py`): `create_round`,
  `publish_round`, `authenticate_operator`, `cli_principal`, `getpass`,
  `correct_result`, `resolve_alert`, `invalidate_round`, `reopen_round`,
  `set_result_mode`, `grant_role`, `bootstrap_owner`, `as_of` stay forbidden in
  `backend/jobs`. `build_live_snapshot` moves from forbidden to allowed **only in
  `prepare.py`** (read-only, needed for readiness — ADP-06), and the guard gains
  explicit assertions that `publish_round` is never referenced and that
  `create_scheduled_draft` and `publication_readiness` are the only round-service
  additions. This is a deliberate, approved change to the guard, not a weakening.

## 3. Integration within `jobs tick`

Order inside one tick (unchanged first steps):
1. lock, abandonment classification, pause check (Stage D, unchanged);
2. lifecycle round loop (lock, results, settle, finalise; unchanged);
3. **preparation** — only if `cfg.prepare` and `beta in cfg.prepare_streams`:
   1. compute the upcoming week from the schedule and the database clock;
   2. `prepare_draft` step if `now ≥ create_at` and no round has the code
      (`run.check()` first; job `scheduler.prepare_draft`, scope = code);
   3. `prepare_readiness` step if the round is a `draft` and the last readiness
      record is older than `prepare_readiness_interval` (job
      `scheduler.prepare_readiness`, scope = code): `run.check()`, build the
      snapshot from the football store (read-only), call
      `rounds.publication_readiness(..., source="football-db")`, record the
      outcome (§6). No provider call; no write to the competition database other
      than the job row;
4. attention notes, usage, tick record (unchanged, plus preparation notes).

Preparation shares the tick's lock (`run.check()` = `TickLock.verify()` and the
240 s budget), back-off (`_backoff_until` on the step's history), pause and
`_classify` error handling; a failure in preparation never aborts the lifecycle
steps already done and never prevents the tick record. `--dry-run` lists the due
preparation steps as `planned` without writing.

## 4. Configuration and validation

| Variable | Default | Bounds / rule |
|---|---|---|
| `DISKI9_JOBS_PREPARE` | off | boolean; requires `DISKI9_JOBS_ENABLED` |
| `DISKI9_JOBS_PREPARE_STREAMS` | (empty) | required when on; only `beta` accepted; `official` and `development` refused (ConfigError) |
| `DISKI9_JOBS_PREPARE_CREATE_LEAD_HOURS` | 78 | 6–78 (78 h = Tuesday 00:00 UTC before a Friday 06:00 UTC target) |
| `DISKI9_JOBS_PREPARE_READINESS_MINUTES` | 30 | 5–240 |
| `DISKI9_JOBS_PREPARE_GRACE_HOURS` | 6 | 1–24 |

Invalid values raise `ConfigError` (exit 2, nothing done), as the existing
scheduler settings. `SchedulerConfig.__post_init__` repeats the stream checks for
configurations built in code. The values are reported by `jobs status` and
`ops status`. Preparation does not need `DISKI9_JOBS_PROVIDER_CALLS` (no provider
use in E.1a).

## 5. Duplicate prevention and concurrency

| Case | Handling |
|---|---|
| Repeated ticks | `prepare_draft` runs only when no round has the code; otherwise no step (and `jobs status` shows "exists") |
| Concurrent ticks | Stage D session lock admits one; others record `busy` |
| Concurrent human `round create` | `rounds.code UNIQUE` + `ON CONFLICT DO NOTHING`: one row; the scheduler reports `skipped: exists (created by …)` from the audit record |
| Manual creation first | as above; readiness evaluation then proceeds for the human-created draft too |
| Crash mid-creation | single transaction; Stage D interruption/abandonment marks the step; the next tick sees either no row (retries) or the row (skips) |
| Published/locked round | never modified; the service only inserts; readiness evaluated only for `draft` rows |
| Week rollover | the calculator maps every instant to exactly one week (§6 of the design: the interval from one Tuesday 00:00 UTC to the next) |

## 6. Readiness reuse and recording

* Exactly `rounds.publication_readiness(engine, round_id, snapshot,
  source="football-db")` on a snapshot from `build_live_snapshot(football_engine,
  now, window_start, window_end, code, LEAGUE_SHORT)` — the same builder and
  validator as `round readiness` and `round publish` (no second validator).
* Recorded in the step's `job_runs` row (allowed fields only: `status`,
  `finished_at`, `error`): `status = succeeded` for an evaluation that ran,
  `error` = `ready | <summary>` or `not_ready[<category>]: <problem> | <summary>`,
  where `<category>` ∈ {`opening_checks`, `stale_odds`, `no_fixtures`,
  `deadline_passed`, `snapshot`, `other`} is derived from the readiness result's
  existing fields (status from `assess_round` in `details`, the `deadline` detail,
  empty pool), and `<summary>` = `fixtures=…, leagues=…, A/B/C=…/…/…,
  earliest=<ISO>, deadline=<ISO>`. An evaluation that could not run (football
  store missing/unreadable) is `failed` with `blocking_failure: football store
  unavailable`.
* **A draft's existence never implies readiness**: the READY state requires a
  `ready` record newer than `prepare_readiness_interval`; anything older is shown
  as "readiness out of date".
* The verdict is advisory; publication still builds, shows, confirms and
  publishes its own snapshot (Stage E standing requirement).

## 7. Derived preparation states and operator exposure

Computed by `ops.snapshot` for the upcoming week (and for any unpublished draft
whose window has not ended):
| State | Rule |
|---|---|
| `no_draft` | no round with the upcoming code (before `create_at`: `not_due`) |
| `draft_not_evaluated` | draft; no readiness record yet, or the last one is out of date |
| `draft_not_ready` | latest current record `not_ready[...]` |
| `draft_ready` | latest current record `ready` |
| `target_missed` | draft (ready or not) and `now ≥ target + grace` |
| `lapsed` | draft and (`now ≥ window_end`, or the latest record is `not_ready[deadline_passed]`) |
| `published` | status ≠ `draft` |
| `intervention` | preparation step streak ≥ the existing step-failure thresholds, or a `blocking_failure` |
Exposure: `ops status` (Preparation section: week, code, state, last evaluation
and reason, next evaluation), `ops status --json`, `jobs status`, tick attention
notes, `ops jobs --job scheduler.prepare_readiness`, `round inspect` job list.

## 8. Monitoring and audit

New `ops check` findings (codes, severities; thresholds from the design §10.2,
configurable, fail closed; INFO never notified; webhook unchanged and disabled):
| Code | Severity |
|---|---|
| `prepare_disabled` | INFO when lifecycle automation is on but preparation is off |
| `prepare_no_draft` | WARNING `create_at + 1 h`; CRITICAL `target − 6 h` |
| `prepare_not_ready` | INFO before the target; WARNING at the target; CRITICAL at `target + grace` |
| `prepare_ready_unpublished` | INFO until `target + 2 h`; WARNING after |
| `prepare_target_missed` | WARNING at `target + grace` (unpublished) |
| `prepare_lapsed` | WARNING (visible 7 days) |
| `prepare_failing` | WARNING / CRITICAL at the existing step-failure thresholds (3 / 6); CRITICAL immediately for `football store unavailable` within 6 h of the target |
| `prepare_stale_evaluation` | WARNING if the latest evaluation is older than 3 × the interval while a draft is due |
The existing `draft_awaiting_publication` INFO remains for drafts outside the
upcoming week. New config: `DISKI9_OPS_PREPARE_*` thresholds mirroring the table
(defaults as listed).

Audit: `round.create` by `system` with `job_run_id` (scheduled creation only);
readiness evaluations are read-only (job rows, no audit). `audit list
--action-prefix round.create` distinguishes scheduled (`SYSTEM`) from human
creation.

## 9. Tests and acceptance scenarios

| File | Scenarios |
|---|---|
| `tests/test_prepare_week.py` (new, no database) | week mapping across Tuesday 00:00 UTC; Friday 06:00 UTC target from `publish_rule` (SAST); ISO year boundaries 2026-W53 → 2027-W01 and 2027-W52; window Fri 00:00–Tue 00:00 UTC; European DST dates do not move windows; create lead bounds |
| `tests/backend/test_backend_prepare.py` (new, isolated PostgreSQL) | service: SYSTEM-only (Principal refused), schedule-derived code/window/series, beta only, no caller-supplied values possible (signature), `ON CONFLICT` idempotency, audit `round.create` by `system` with job link, status history; published/locked rounds untouched; concurrent human `round create` (threads) → one row; tick integration: disabled by default, pause, dry-run writes nothing, created once across repeated ticks, two and four concurrent ticks, crash before/after the insert, manual draft first; readiness: READY and NOT READY parity with `publication_readiness` (injected snapshots: valid, too few fixtures, stale, deadline passed), football store unavailable → blocking failure, evaluation interval respected; states and monitoring: each derived state and each `ops check` finding with negative controls; no provider requests (ledger unchanged); no premature settlement/finalisation; development and official refused |
| `tests/backend/test_backend_scheduler.py` | static guard updated (§2); existing lifecycle tests unchanged |
| `tests/backend/test_backend_scheduler_locking.py` | unchanged; plus one test: preparation steps respect `run.check()` (lock loss during preparation → `lock_lost`, no draft written after the loss) |
| `tests/backend/test_backend_ops.py` | preparation section in `ops status` JSON; history known jobs |
| `tests/backend/test_backend_stage_e_admin.py` | unchanged (readiness/publish path); plus: a scheduled draft is published only through `round publish` with the typed code and the exact snapshot |
One integration test builds a small SQLite football store with the existing test
factories (`tests/factories.py`) so the default snapshot builder is exercised once
without mocks.

## 10. Risks, open questions and deviations

| Item | Note |
|---|---|
| Football store on the scheduler host | E.1a readiness needs read access to the football store; if absent, readiness records a blocking failure (fail closed) and monitoring escalates. Hosting is Q-07 (not needed for local Beta operation) |
| Snapshot build cost per evaluation | measured during implementation; the 30-minute default interval and the 240 s budget bound it; if a build exceeds the remaining budget the step is deferred |
| Static-guard change | `build_live_snapshot` allowed in `prepare.py` only (ADP-06); explicit, tested |
| `publish_rule` read by code | first use (timing and monitoring only; meaning unchanged) |
| Lapsed drafts | stay as inert `draft` rows (ADP-04 A); a human `round postpone` remains a later option |
| Readiness record format | compact text in `job_runs.error` (no migration); parsed by `ops`; covered by tests |
| Deviations from the approved design | none. The design's `prepare_refresh` and `prepare_screener` steps, the preparation request sub-cap and `ODDS_REFRESH`/`REFRESH_LEAD` settings belong to E.1b and are omitted |

**Owner decisions needed before implementation:** none beyond the implementation
authorisation itself. (Monitoring threshold defaults in §8 are proposals; they can
be adjusted at the checkpoint without design changes.)

## 11. Acceptance checklist

- [ ] **Level 1:** new week-calculator and preparation tests pass twice; updated
      static guard passes; ruff check and format clean.
- [ ] **Level 2** (local PostgreSQL + Supabase Auth harness): preparation,
      scheduler, scheduler locking, ops, rounds, Stage E admin, S-07, operator CLI,
      results, settlement (incl. ops/security), corrections, championships,
      integrity, concurrency, migrations — 0 failures, 0 skips.
- [ ] **Full GitHub CI** on the final application-code candidate: 0 failures,
      0 unexpected skips, **all 13 browser tests executed**, migration from empty,
      real Supabase Auth integration, lint and formatting.
- [ ] **Migration head** `app_0007` unchanged; **fingerprint**
      `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`
      unchanged; `broad60-432-v1` / `points-150-75-v2` unchanged; no diff under
      `src/diski9/challenge/` or `migrations_app/`.
- [ ] **Rules and security:** no change to buckets, opening checks, eligibility,
      settlement, S-02, championship scoring; `SYSTEM` cannot publish or create
      arbitrary rounds (tests); human publication with confirmation and exact
      snapshot (tests); no new provider request (ledger unchanged in tests);
      Development/Official refused.
- [ ] **Locking and recovery:** Stage D locking suite unchanged and passing;
      lock loss during preparation tested; crash/abandonment of a preparation step
      tested; dry-run writes nothing.
- [ ] Documentation updated; checkpoint report.

---

## Appendix A. API-Football allowance and preliminary E.1b budget considerations

**Recorded (ADP-20):** the owner reviewed API-Football pricing (21 Nov 2026): the
**Pro plan advertises 7,500 requests per day at $16/month**; the reviewed pricing
information does not mention an hourly or per-minute limit. This is the
**advertised allowance, subject to confirmation against the active subscription**
(the provider's `x-ratelimit-requests-limit` header reported 7,500 during the odds
trial). Still to confirm: per-minute/burst limits (the provider's
`x-ratelimit-*` minute headers, if present), behaviour at exhaustion, odds
coverage and lead time per league, update frequency, and storage/display terms.

**Advertised allowance vs internal limits.** The 7,500/day figure is the
provider's ceiling for **all** consumers of the key (web app refreshes, the D-29
research collector, manual commands and the scheduler). The scheduler's limits
are internal safety limits and stay at the provisional 10 per tick / 100 per 24 h
until E.1b is authorised; they are **not** raised to 7,500.

**Preliminary proposal for E.1b planning (not for approval now):**
| Consumer | Proposed internal budget | Basis |
|---|---|---|
| Client-level reserve (existing `daily_reserve`) | 500 left untouched | provider protection for every consumer |
| Scheduler total | 600 / 24 h, 30 / tick | ≈ 8 % of the advertised allowance |
| — of which preparation (refresh) | 300 / 24 h | full refresh ≈ 28 + up to 12 odds refreshes ≈ 170, + retries and verification headroom |
| — reserved for lifecycle (results, full re-checks, corrections) | ≥ 300 / 24 h | results ≈ 1 request per 20 fixtures per refresh; generous margin for correction weeks |
| Research collector (D-29) | separate, ≈ 50 / week | its own estimate; same key |
| Manual / web refreshes | remainder | monitored via the provider headers |
| Pacing | ≤ 10 requests per minute until a minute limit is confirmed | conservative; adjustable |
Fail-closed behaviour: each request reserved before sending (existing ledger);
stop provider steps when any internal cap, the client reserve or a provider quota
error is hit; WARNING at 80 % of each internal cap; CRITICAL when the provider's
remaining daily count falls below the reserve; retries counted. These figures will
be re-estimated from recorded responses before E.1b is authorised.
