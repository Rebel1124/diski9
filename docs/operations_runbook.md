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
