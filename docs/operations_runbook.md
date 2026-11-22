# Operational recovery runbook (Phase 6C.6 Stage D)

Weekly administration and the command overview: [`operations_guide.md`](operations_guide.md).
For one round, `uv run diski9 round inspect --code CODE --operator EMAIL` (Stage E)
gathers status, S-02 timing, alerts, jobs and audit records in one report.

Safe, limited procedures for the scheduled lifecycle. **Nothing here bypasses
authorisation, settlement, correction or finalisation rules**: there is no
force-finalise, no automatic alert resolution and no privileged shortcut. Every
competition change outside the scheduler's four steps (lock, results import,
settlement, finalisation) is made by an authenticated operator with the existing
commands (S-07). Start every investigation with:

```bash
uv run diski9 ops status
uv run diski9 ops check
uv run diski9 ops jobs --failed --limit 20
```

## 1. The scheduler is not running (heartbeat WARNING/CRITICAL)
1. `ops status`: is automation enabled and not paused? A disabled or paused
   scheduler is not an outage (INFO).
2. On the host, check the trigger: `crontab -l` / `systemctl status diski9-jobs.timer`
   / `launchctl list | grep diski9`, and the trigger's log.
3. Run one tick by hand: `uv run diski9 jobs tick`. Exit 2 means configuration
   (fix the reported variable); exit 1 means a retryable failure or the database;
   exit 4 means an operator must act (see §5).
4. Restart the trigger. The next ticks catch up from the database state (§7).

## 2. Re-running a tick
`jobs tick` is idempotent and safe at any time: it does only what is due and every
service refuses repeated or premature work. If another tick is running it records
`skipped: another tick is still running` and exits 0. Use
`uv run diski9 jobs tick --dry-run` first to see what is due.

## 3. Pausing and resuming
Pause: `touch "$DISKI9_JOBS_PAUSE_FILE"` (or `DISKI9_JOBS_PAUSED=on`). Each tick then
records itself as paused and does nothing; operators keep every manual command.
Resume: remove the file (or unset the variable). The next tick catches up; check
with `ops status` that the heartbeat recovers and no round is overdue.

## 4. An abandoned or stuck step
`step_abandoned` means a tick ended while a step was running: either it was
interrupted in-process and recorded this itself (`abandoned: interrupted`), or its
process was killed and the next tick recorded it once the tick was older than the
abandonment threshold (20 minutes). Back-off then applies.
1. `ops jobs --round CODE` shows the round's steps and audit records. Because each
   service call is one transaction, an abandoned step left nothing half-applied:
   either its transaction committed (visible in the round's status, settlement
   runs or audit) or it rolled back.
2. Nothing needs undoing; the next tick after the back-off repeats the step if it is
   still due.
3. A `step_stuck` (still `running` after 30 min) with a tick still alive points to
   a slow provider or database call; check the host process and the database's
   `pg_stat_activity`. Do not edit `job_runs` rows (they are guarded).
4. Investigate repeated abandonment (host sleeping, OOM kills, timeouts; see the
   locking review in the implementation record §5.5).

## 4a. A tick lost the scheduler lock (`tick_lock_lost`, exit 1) or is indeterminate
* `lock lost` means the tick's dedicated lock connection was ended (database
  restart, failover, network drop, an administrator's `pg_terminate_backend`, or an
  unsuitable connection). The tick stopped starting work after its in-flight step;
  nothing needs undoing.
* While that tick's in-flight step is still running, new ticks report
  `indeterminate` and do nothing (exit 0); `ops status` shows the tick under "lost
  its lock". This clears by itself when the step finishes, or after
  `DISKI9_JOBS_ABANDON_AFTER_MINUTES` (20) when the next tick records it abandoned.
* If lock loss repeats, check the database logs for terminated sessions and confirm
  the scheduler uses a direct or session-mode connection (operations_scheduler.md,
  "Database connection for the scheduler"). Do not raise database timeouts as a fix;
  the lock is not affected by idle-in-transaction limits.

## 5. Blocking settlement alerts (exit 4, `blocking_alerts`)
The scheduler never resolves alerts. An authenticated operator investigates and
resolves each with the existing audited commands:

```bash
uv run diski9 settle alerts --round CODE --operator EMAIL
uv run diski9 results show --round CODE --operator EMAIL
uv run diski9 settle resolve-alert --round CODE --alert ID --reason "..." --operator EMAIL
uv run diski9 results correct ... --operator EMAIL   # if a result is wrong (previewed, audited)
```

Late-notification alerts (results that arrived after the settlement cutoff,
for example after a scheduler outage) follow the 6C.4 confirmation rules. Once no
blocking alert remains, the scheduler (or an operator with `round finalise`)
finalises when S-02 allows.

## 6. Provider budget exhausted or provider failing
* `budget_exhausted` / `deferred: provider budget exhausted`: imports wait for the
  rolling 24-hour window; nothing is lost. Do **not** raise the caps without owner
  approval (Stage C decision). If results are urgently needed, an operator may run
  `results import --round CODE --operator EMAIL` (counts against the provider's own
  daily quota and reserve, not the scheduler's cap).
* `provider_failing`: back-off already limits retries. Check the provider status and
  the client's error type in `ops jobs --job scheduler.results --failed`. A
  `blocking_failure: provider access refused` means the key or subscription:
  fix the configuration; never paste keys into chat or tickets.
* Automated provider calls are currently **off** by decision; real rounds are then
  locked and settled by the scheduler and finalised manually or after activation.

## 7. Verifying catch-up after an outage
After the trigger is restored:
1. `jobs tick --dry-run` lists the overdue steps; then let the trigger run (or run
   `jobs tick` once).
2. `ops status`: rounds should move from "awaiting locking" / "awaiting settlement"
   to their expected positions; the heartbeat age falls below 5 minutes.
3. `ops check` should return 0, or only conditions that genuinely need an operator
   (for example late-notification alerts if the outage spanned a settlement
   cutoff).
4. No round is finalised before its S-02 earliest time: the service refuses it.

## 8. Rounds that need an operator
* **Awaiting publication** (INFO): the operator publishes with
  `round publish --code CODE --operator EMAIL`. The scheduler never publishes.
* **Needs a result mode** (development): `dev-results set-mode --round CODE --mode ...`.
* **Eligible but not final** with provider calls off: the operator runs
  `results import --round CODE --full`, `round finalise-check --code CODE`, then
  `round finalise --code CODE` (each with `--operator EMAIL`; S-02 and alert checks
  apply).
* **Open past its deadline** with automation off: `round lock --code CODE
  --operator EMAIL`.

## 9. Database problems
`database_unavailable`, `migration_head` or `tables_missing` are CRITICAL. Check the
database service and credentials on the host (never in chat); `uv run diski9
app-db check` reports connectivity and the migration head. Health checks never run
migrations; apply them only through the approved deployment procedure.

## 10. Integrity findings (`ops check --deep`)
Repairable findings: preview with `competition repair` (authenticated, previewed,
audited). Material findings: stop and investigate; do not repair automatically.

## 11. Automated draft preparation (Stage E.1a)
Check with `ops status` (Preparation section) or `jobs status`.

| Finding | What to do |
|---|---|
| `prepare_no_draft` | Is `DISKI9_JOBS_PREPARE` on with `DISKI9_JOBS_PREPARE_STREAMS=beta`, and are ticks running (heartbeat)? Run `jobs tick --dry-run` to see `prepare_draft` planned, then `jobs tick`. If needed, create it yourself: `round create --week YYYY-Www --operator EMAIL` (the scheduler then leaves it alone). |
| `prepare_not_ready` | Read the reason (`round readiness --code C`). `stale_odds` / `missing_markets`: refresh the football store (`refresh-data --with-odds`) and wait for the next evaluation (or run `round readiness`). `opening_checks` (too few fixtures or leagues, infeasible 4/3/2): a thin week such as an international break — do not publish; the week lapses. |
| `prepare_ready_unpublished` / `prepare_target_missed` | An operator reviews `round readiness --code C` and publishes with `round publish --code C --operator EMAIL` (types the code). The scheduler never publishes. |
| `prepare_failing` with "football store unavailable" | The store path (`DISKI9_DATABASE_URL`) is missing or not set up on the scheduler host; fix the host, then `jobs tick`. Nothing was evaluated or changed. |
| `prepare_failing` with "too long to run safely" | An evaluation took longer than the safe limit for the abandonment threshold; evaluate by hand with `round readiness` and review the tick budget / abandonment threshold before re-enabling. |
| `prepare_lapsed` | The week was never published; nothing to repair (the draft is inert and is not recreated). |
| `prepare_stale_evaluation` | Ticks are deferring the evaluation (not enough tick time) or failing; check `jobs status` and the heartbeat. |

## 12. Automated football-data refresh (Stage E.1b)
Off by default; not activated. Check with `ops status` / `jobs status` (the "data
refresh" lines under Preparation) and `round readiness` ("data refresh:" line).

| Finding | What to do |
|---|---|
| `refresh_partial` | A sweep closed with some leagues missing (`n/8`). Nothing to repair: the next slot refreshes every league. Before publication, if it was the last Friday slot, run `refresh-data --with-odds` by hand, then `round readiness`. |
| `refresh_failing` | One league failed twice or more in the slot. `ops jobs --job scheduler.prepare_refresh --failed` shows the error type. "football store busy": another writer (a manual command) — let it finish. "football store unavailable": fix the store on the scheduler host. |
| `store_not_current` | No sweep has closed since the first Friday slot. Pause refresh if it is misbehaving (pause file or `DISKI9_JOBS_PREPARE_REFRESH=off`), run `refresh-data --with-odds`, then `round readiness`, then resume. |
| `provider_update_missing` | The provider's daily odds update has not arrived yet for some leagues; grace sweeps retry hourly. Consider publishing later rather than with stale odds (readiness will say `stale_odds`). |
| `odds_coverage_drop` | A league returned no odds although it had them earlier this week; readiness decides whether the week is still feasible. |
| `provider_throttled` / cooldown in status | The provider rate-limited the scheduler; every scheduler request waits for the cooldown. Look for other users of the key (manual bulk commands); never raise caps as a fix. |
| `provider_quota_low` | WARNING: below the preparation floor (refresh already held back). CRITICAL: results imports are close to the client reserve — stop manual bulk commands. |
| `provider_limit_mismatch` | The provider reports a daily limit below 7,500: preparation is stopped for the day. The owner verifies the subscription. |
| `budget_nonessential_exhausted` | Preparation used its share of the 24 hours (long grace periods); it resumes as the window rolls. Results are unaffected. |
| `results_reserve_breached` | Should be impossible (enforced at reservation time): escalate to the owner. |

Rules: do not run bulk manual store commands (`setup`, `refresh-data`,
`collect-odds`) on Friday between 03:30 and 12:00 UTC while refresh is on — pause it
first; a collision is safe but wastes requests. Never clear `job_runs` rows by hand.

## 13. Backups, restores and the provider hold (Stage F2)
Full procedures: [operations_hosting.md](operations_hosting.md) (sections 4–9).

| Finding | What to do |
|---|---|
| `backup_monitoring_off` (INFO) | Backup evidence is not being checked. Turn on `DISKI9_OPS_BACKUP_EXPECTED` once the nightly backup and the off-host hook run on the host. |
| `backup_store_stale` / `backup_postgres_stale` | No verified local backup of that kind recently (or ever). Run `diski9 backup store --out …` or the `pg_dump` + `backup record --kind postgres` step; check the backup timer (`systemctl status diski9-backup`). |
| `backup_failed` | The latest attempt failed verification (the copy was deleted). Check disk space and `diski9 backup verify` on the previous backup; rerun. |
| `backup_offhost_stale` | The host's copy hook has not reported an encrypted off-host copy. A local backup does **not** count. Check the hook's own log. |
| `offhost_restore_unverified` / `restore_drill_stale` | Off-host recovery is not verified: restore an off-host copy in a drill (`restore store --purpose drill --source-origin offhost`; the PostgreSQL drill, then `backup record --kind postgres-drill`). |
| `store_restored` (INFO) | The football store was restored for recovery within 7 days; refresh sweeps before it no longer count. Make sure a sweep or `refresh-data --with-odds` ran before readiness. |
| `provider_hold_after_restore` (WARNING) | The competition database was restored: the scheduler makes no provider calls. Reconcile (operations_hosting.md §8), then `diski9 ops provider-resume --operator EMAIL --reason "…"`. |

Never copy the live SQLite file by hand, never restore over a live store or database,
and never lift the hold before reconciliation. In-place replacement of the live
football store is disabled in F2 (`--replace-live` is always refused).

