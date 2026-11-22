# Operational monitoring, alerts and job history (`diski9 ops`)

Phase 6C.6 Stage D. Read-only commands over the competition database that answer:
is the scheduler running, are rounds progressing, has anything failed or stuck,
are there unresolved settlement or integrity issues, how much of the provider
budget is used, and does an operator need to act. They reuse `job_runs`, the audit
log, settlement alerts and the championship integrity inspection; there is no new
table, dependency or service. Recovery procedures:
[`operations_runbook.md`](operations_runbook.md). Scheduler:
[`operations_scheduler.md`](operations_scheduler.md).

## Commands

```bash
uv run diski9 ops status            # overview (add --json for automation)
uv run diski9 ops check             # findings with severities; exit 0 / 1 / 2
uv run diski9 ops check --deep      # plus the full championship integrity inspection
uv run diski9 ops check --notify    # plus webhook notifications, if configured (off by default)
uv run diski9 ops jobs --limit 30   # recent job runs; --job, --round CODE, --failed, --json
```

`ops check` exit status: **0** healthy (INFO only), **1** at least one WARNING,
**2** at least one CRITICAL (including an unreachable database or invalid
configuration). `ops status` exits 1 only if the database is unavailable.

Suggested trigger: `ops check --notify` every 5–15 minutes (light checks, about
40 ms); `ops check --deep` once a day or after a manual repair. They are separate
from `jobs tick`, so monitoring or notification problems can never block or change
lifecycle processing.

## What `ops status` shows

Environment and database (server, schema revision against the expected head,
query time); scheduler configuration (enabled / disabled / paused, streams,
provider calls); the last tick and last successful tick with their ages (the
heartbeat); notification state (never the URL); scheduler provider requests in the
last 24 hours against the caps; rounds by lifecycle position — awaiting operator
publication, entries open, awaiting locking, awaiting settlement, awaiting results
(before the settlement cutoff), in the correction window, eligible for
finalisation, overdue for finalisation, blocked by settlement alerts, needing a
result mode, final in the last 7 days; recent failures (24 h); running and
abandoned steps; blocking alerts; light integrity warnings; and a summary of check
severities.

## Severity model and thresholds

Times are the competition's own: the entry deadline, the settlement cutoff (latest
kickoff + 48 h) and the S-02 earliest finalisation
(max(cutoff, last material change) + correction window). No other deadline is
invented.

| Check | INFO | WARNING | CRITICAL |
|---|---|---|---|
| Scheduler state | disabled or paused on purpose | — | — |
| Heartbeat (automation enabled, not paused) | — | no tick for 15 min | no tick for 60 min, or never |
| Failing ticks | — | — | last 3 ticks failed and none succeeded within 60 min |
| Step failures (same step, same round, in a row) | — | 3 | 6 |
| Stuck step (`running`) | — | after 30 min | — |
| Abandoned step (interrupted tick, last 24 h) | — | yes | — |
| A tick holds the scheduler lock now (trustworthy evidence it is running) | tick active | — | held for 60 min (overrunning) |
| A tick lost the scheduler lock (24 h) | — | yes | — |
| Steps of a tick that lost its lock still running | — | indeterminate (may still be finishing), or awaiting abandonment | — |
| Draft round | awaiting operator publication | — | — |
| Open round past its deadline | — | 15 min | 60 min |
| No settlement run since the cutoff | — | 6 h | 24 h |
| Failed settlement runs (24 h) | — | yes | — |
| Eligible for finalisation (S-02) but not final | first 6 h | after 6 h | after 24 h |
| Blocking settlement alerts | — | open | open 24 h past the earliest finalisation |
| Development round without a result mode | — | yes | — |
| No results import while matches are in play (provider calls on) | — | 3 h | — |
| Provider calls off | yes | — | — |
| 24-hour scheduler provider requests | — | ≥ 80 % of cap, or cap reached | above the cap |
| Repeated provider failures | — | 3 in a row | — |
| Official-stream activity before activation | — | — | yes |
| Final round without published weekly results | — | yes | — |
| Draft preparation off while automation is on (E.1a) | yes | — | — |
| Upcoming week has no draft (preparation on) | — | 1 h after the creation time | 6 h before the publication target |
| Draft NOT READY | quiet until the attention window (3 h before the target); then INFO | at the target | — |
| Draft READY, unpublished | INFO from the attention window | 2 h after the target | — |
| Publication target missed (unpublished after target + grace) | — | if READY at the last evaluation | if NOT READY |
| Readiness not evaluated recently (inside the attention window) | — | yes | — |
| Preparation failing (`blocking_failure`, e.g. football store unavailable, or 3 failures in a row) | — | yes | blocked within 6 h of the target, or the step-failure critical count |
| Draft lapsed (window ended unpublished, 7 days; or deadline passed) | — | yes | — |
| Automated data refresh off while preparation is on (E.1b `refresh_disabled`) | yes, until the target | — | — |
| Last data sweep complete (`refresh_ok`) | from the attention window | — | — |
| Sweep closed partial (`refresh_partial`) | — | yes | — |
| A league failed twice or more in the current slot (`refresh_failing`) | — | yes | within 1 h of the target |
| No sweep closed since the first Friday slot (`store_not_current`) | — | from target − 90 min | from target − 30 min |
| Today's provider odds update not seen (`provider_update_missing`) | — | from target − 60 min | — |
| A league lost the odds it had earlier this week (`odds_coverage_drop`) | — | inside the attention window | — |
| Provider rate-limited the scheduler in 24 h (`provider_throttled`) | — | once | 3 times |
| Provider daily remaining (`provider_quota_low`) | — | below the preparation floor (2,000) | below 600 |
| Provider status and headers disagree (`provider_quota_inconsistent`) | — | by more than 10 % | — |
| Provider reports a daily limit below 7,500 (`provider_limit_mismatch`) | — | — | yes |
| Preparation used its 24-hour share (`budget_nonessential_exhausted`) | — | yes | — |
| Preparation inside the results reserve (`results_reserve_breached`; impossible by construction) | — | — | yes |
| Integrity inspection (`--deep`) | — | repairable finding | material finding |
| Database | — | trivial query > 2 s | unreachable, wrong migration head, tables missing |

Disabled or paused automation is never reported as an outage. While a tick holds the
scheduler lock (seen in `pg_locks` with its `diski9-tick:<token>` connection), the
heartbeat checks are replaced by "tick active", so a legitimately long tick is not
reported as an outage; a tick holding it for longer than the critical heartbeat
threshold is CRITICAL. Provider use is read from the request ledger
(`scheduler.provider` rows). Thresholds are
configurable (fail closed on invalid values):

| Variable | Default |
|---|---|
| `DISKI9_OPS_TICK_INTERVAL_MINUTES` | 5 |
| `DISKI9_OPS_HEARTBEAT_WARNING_MINUTES` / `_CRITICAL_MINUTES` | 15 / 60 |
| `DISKI9_OPS_LOCK_WARNING_MINUTES` / `_CRITICAL_MINUTES` | 15 / 60 |
| `DISKI9_OPS_SETTLE_WARNING_HOURS` / `_CRITICAL_HOURS` | 6 / 24 |
| `DISKI9_OPS_FINALISE_WARNING_HOURS` / `_CRITICAL_HOURS` | 6 / 24 |
| `DISKI9_OPS_RESULTS_STALE_HOURS` | 3 |
| `DISKI9_OPS_STEP_FAILURES_WARNING` / `_CRITICAL` | 3 / 6 |
| `DISKI9_OPS_STUCK_MINUTES` | 30 |
| `DISKI9_OPS_BUDGET_WARNING_PERCENT` | 80 |
| `DISKI9_OPS_PREPARE_ATTENTION_HOURS` | 3 |
| `DISKI9_OPS_PREPARE_PUBLISH_WARNING_HOURS` | 2 |
| `DISKI9_OPS_BACKUP_EXPECTED` | off (Stage F2: backup findings on/off) |
| `DISKI9_OPS_BACKUP_WARNING_HOURS` / `_CRITICAL_HOURS` | 26 / 50 |
| `DISKI9_OPS_RESTORE_DRILL_DAYS` | 35 |

**Backup health (Stage F2).** `ops status` (and `--json`, key `backups`) lists four
evidence levels separately: (1–2) football store created and verified locally;
(1–2) PostgreSQL dump recorded (header and checksum); (3) off-host copy *reported* by
the host hook (not verified by Diski 9); (4) an off-host copy restored in a drill whose
content matched a recorded backup (origin operator-declared). With
`DISKI9_OPS_BACKUP_EXPECTED=on`, `ops check` reports each gap on its own:
`backup_store_stale`, `backup_postgres_stale`, `backup_offhost_stale` (WARNING after
26 h, CRITICAL after 50 h or never), `backup_failed` (WARNING), and
`offhost_restore_unverified` / `restore_drill_stale` (WARNING). Off: one INFO
`backup_monitoring_off`. Whatever the setting: `provider_hold_after_restore` (WARNING)
while a competition-database restore holds provider calls, and `store_restored`
(INFO) for 7 days after a football-store recovery restore. `ops jobs` lists the
records (`ops.backup_*`, `ops.restore_*`, `ops.provider_resume`).

**Preparation states (Stage E.1a)** are derived from rounds and job records (no
state of their own) and shown in `ops status` (and `--json`, key `preparation`) and
`jobs status`: `not_due`, `no_draft`, `draft_not_evaluated`, `draft_not_ready`,
`draft_ready`, `target_missed`, `lapsed`, `intervention`, `published`. A draft's
existence never means READY: READY needs a `ready` evaluation within two intervals
plus five minutes. Before the attention window a NOT READY draft raises nothing,
because the football store is normally refreshed shortly before publication.

## Notifications (one webhook, off by default)

| Variable | Default | Meaning |
|---|---|---|
| `DISKI9_OPS_NOTIFY` | off | send notifications from `ops check --notify` |
| `DISKI9_OPS_WEBHOOK_URL` | (none) | https endpoint (http only for localhost); a **secret**, never printed, logged or stored |
| `DISKI9_OPS_NOTIFY_MIN_SEVERITY` | warning | `warning` or `critical` |
| `DISKI9_OPS_RENOTIFY_WARNING_HOURS` | 24 | repeat an ongoing WARNING |
| `DISKI9_OPS_RENOTIFY_CRITICAL_HOURS` | 4 | repeat an ongoing CRITICAL |
| `DISKI9_OPS_NOTIFY_RETRY_MINUTES` | 15 | retry a failed delivery |

Each finding has a fingerprint (`code:subject`, e.g. `lock_overdue:2026-W48`). A
notification is sent as **new** when a WARNING/CRITICAL condition first appears (or
reappears after resolving), **ongoing** when it persists past the re-notification
interval or escalates from WARNING to CRITICAL, and **resolved** once when it
disappears. INFO is never sent. The payload is JSON:
`{source, environment, state, severity, category, code, subject, message,
fingerprint, detected_at}` — no account, provider or credential data.

**Ledger without a migration.** Each attempt is a `job_runs` row (`job =
'ops.notify'`, `scope` = fingerprint, `args` = state and severity written at
insert, `status` = delivered or failed). The latest row per fingerprint is read
through the existing `(job, scope, started_at)` index, bounded to 30 days. A failed
delivery (HTTP error, timeout, refused connection) is recorded and retried after
the retry interval; it never raises and never affects the competition. Trade-off:
`job_runs` is an operational table, so notification history shares it with job
history (filtered by `job`); a dedicated alerts table (with acknowledgement) would
need a migration and is not proposed now.

**Activation:** no real destination is configured. Activation needs the owner's
approval of the provider and destination (decision Q-08). Tests use a local
webhook server on 127.0.0.1 only.

When the database itself is unreachable, `ops check` exits 2 with a CRITICAL
`database_unavailable` finding but cannot de-duplicate notifications (the ledger is
in the database), so it sends none; the trigger's own failure reporting (exit
status, cron mail, systemd `OnFailure=`) covers that case.

## Job history

`ops jobs` lists recent runs (at most 200) of the scheduler steps, the services'
own job records (`lock`, `publish`, `results-import`) and notifications, with
start, duration, outcome class (`succeeded`, `skipped`, `deferred`,
`retryable_failure`, `blocking_failure`, `abandoned`, `running`), provider
requests, the error, and for scheduled settlement the linked settlement run. With
`--round CODE` it also lists that round's audit records (action, actor role, job
link), read through the audit index. Account identities and provider payloads are
never shown.

## Performance

Light checks use indexed or bounded queries only: `job_runs (job, scope,
started_at)` for ticks, steps, provider use and the notification ledger (always
with a job list and a time bound), `rounds (status)` for active rounds,
`settlement_alerts (round_id, id)` and `score_sets (round_id, revision)`, plus a few
per-round queries over the active rounds (at most 500). Measured on PostgreSQL 16
with 150,000 `job_runs` rows (about a year of five-minute ticks with their steps):
`ops status`/`ops check` data collection and evaluation 40–47 ms, job history
(200 rows) under 50 ms. The full championship inspection (`--deep`) is never run by
the light check (tested); it recomputes championship standings, so its cost grows
with rounds and entries and it belongs on a slow schedule. Measured read-only on the
F4 performance datasets (PostgreSQL 16, warm): light checks 31 ms (1,000 players,
11,401 entries) and 22 ms (10,000 players, 110,750 entries); the deep inspection
1.2 s and 11.0 s respectively. No new index was needed; `settlement_runs` and
`audit_log.job_run_id` have no index on the columns used for per-round settlement
times and job links, which is fine at current volumes and is noted for review if
history grows by orders of magnitude.

**Data refresh (Stage E.1b)** is derived from job records only and shown under
Preparation in `ops status` (`--json`: `preparation.refresh`) and `jobs status`:
current slot and sweep state (`none`, `in_progress`, `complete`, `partial`, with
`n/8` leagues), last complete and last partial sweep, failing leagues, next slot,
provider cooldown, the lowest usable provider quota observation (source and time)
and scheduler requests in 24 hours by class against the caps. `jobs tick --dry-run`
lists the planned `prepare_refresh` leagues and `prepare_screener`. Webhook
notifications stay off.
