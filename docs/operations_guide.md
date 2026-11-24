# Operator guide: weekly administration (Phase 6C.6 Stage E)

How an operator runs a Diski 9 week from the server CLI without editing the
database. This guide is the entry point; the detail lives in:

| Topic | Reference |
|---|---|
| Scheduler (`jobs tick`, configuration, pause, provider budget, locking) | [`operations_scheduler.md`](operations_scheduler.md) |
| Monitoring (`ops status / check / jobs`), thresholds, notifications | [`operations_monitoring.md`](operations_monitoring.md) |
| Recovery procedures (stuck steps, lock loss, alerts, outages) | [`operations_runbook.md`](operations_runbook.md) |
| Results, settlement, corrections, finalisation, championships | [`operator_settlement_cli.md`](operator_settlement_cli.md) |
| Accounts, roles, entitlements, bootstrap, owner recovery | [`authentication.md`](authentication.md) §6 |

**Ground rules.** Every command that changes competition state, and the settlement
reports, `round inspect` and the audit viewer, ask for **your own** password in a real
terminal (`--operator you@example.com`; S-07). Never pass a password as an
argument or variable. Database credentials are not proof of authority. The
scheduler (`SYSTEM`) only locks, imports results, settles and finalises; it never
creates or publishes a round and cannot run any command in this guide that needs a
person. There is no force-finalise, no override of S-02 and no automatic alert
resolution. Official remains disabled.

Exit codes for the administrative commands: **0** done (or nothing to do), **1**
database unavailable or busy (one line; check the state before retrying) — and for
`round readiness`, *not ready*, **2** usage error, invalid configuration or refused
operation (nothing changed), **3** authentication or permission refused (nothing
changed), **130** stopped with Ctrl-C (nothing changed).

## 1. The normal week

| When | What | Command |
|---|---|---|
| Any time | Is anything wrong? | `uv run diski9 ops check` (exit 0 healthy, 1 warning, 2 critical) |
| Any time | Which schedule version and configuration apply now, or at a given UTC instant (read-only, no password) | `uv run diski9 round schedules --schedule weekend --at 2026-12-01T00:00:00Z` |
| Before publication | Create the draft (once per week) — automatic when `DISKI9_JOBS_PREPARE` is on (Stage E.1a; Tuesday 00:00 UTC) | `uv run diski9 round create --week 2026-W48 --operator EMAIL` (manual) |
| Tuesday–Friday | Watch preparation: draft state and the latest readiness verdict (advisory) | `uv run diski9 ops status` / `uv run diski9 jobs status` |
| Tue–Fri (E.1b, when on) | Football data refreshed automatically: daily 04:15 UTC, Friday 04:15 and 05:15, hourly in the grace | scheduler; manual fallback `uv run diski9 refresh-data --with-odds` |
| Publication day | Check readiness (read-only, no password); the "data refresh" line says which sweep the store reflects | `uv run diski9 round readiness --code 2026-W48-weekend` |
| Publication day | Publish (shows readiness again, asks you to type the code) | `uv run diski9 round publish --code 2026-W48-weekend --operator EMAIL` |
| Deadline → final | Automatic: lock, results, settlement, S-02 finalisation, championships | scheduler (`jobs tick` on the host trigger) |
| During the week | Follow one round | `uv run diski9 round inspect --code CODE --operator EMAIL` |
| After finalisation | Verify the championship | `uv run diski9 competition status --operator EMAIL`, then `competition verify` |

Without the scheduler (or while it is paused) every lifecycle step has a manual
command (`round lock`, `results import`, `settle run`, `round finalise`), each with
the same rules; see [`operator_settlement_cli.md`](operator_settlement_cli.md).

## 2. Draft preparation and publication approval

The initial Beta operating model is **automated preparation and validation, then
authenticated human approval**. Preparation today: the football-store refresh
(`refresh-data --with-odds`; automated by Stage E.1b when
`DISKI9_JOBS_PREPARE_REFRESH` is on — implemented, off and not yet authorised for live
use) and — with
`DISKI9_JOBS_PREPARE` on — automatic creation of the upcoming Beta draft and
read-only readiness evaluations every 30 minutes (Stage E.1a; see the scheduler
document). The scheduler's verdict is advisory; approval is always the steps
below.

`round readiness --code CODE` builds the live snapshot exactly as publication would
(read-only, from the football store, no provider request) and runs **the same
checks as `round publish`** against the database clock. It writes nothing: no
snapshot, job record or audit entry. It reports:

* **Fixture pool:** fixtures in the window, with a Goal Model forecast, and markets
  with strict consensus; market exclusions by reason (missing prices, stale
  provider updates and so on).
* **Sheet:** fixtures, outcomes and leagues; eligible fixtures and leagues against
  the opening rules (≥ 15 fixtures, ≥ 3 leagues), eligible outcomes per bucket
  against the picks needed (A 4, B 3, C 2) and the strict-portfolio feasibility
  check (`broad60-432-v1`, unchanged).
* **Data quality:** ineligible outcomes by reason (stale quote, too few bookmaker
  groups, probability outside every bucket band).
* **Freshness:** the newest and oldest eligible quote against the 24-hour quote
  rule, and the snapshot construction-age limit (default 60 minutes).
* **Timing:** kickoffs, the entry deadline (earliest kickoff − 15 min) and the
  settlement cutoff (latest kickoff + 48 h).
* **Verdict:** READY, or NOT READY with the exact reason `round publish` would give.
  `--json` prints the same data for automation; exit 0 ready, 1 not ready.

`round readiness` needs no password because it shows only the round fields that
`round show` shows plus public football data (fixtures, odds-derived counts,
timing); it never shows participants, entries, accounts or credentials.

`round publish` builds the snapshot **once**, shows its readiness summary and asks
you to **type the round code** to confirm; exactly that snapshot (checked by its
fingerprint) is then published, never a rebuilt one. Any other answer stops with
"Not confirmed; nothing changed." The service then repeats every check in its own
transaction, so a round that became invalid in the meantime is still refused. A
NOT READY snapshot is not offered for confirmation; the service refuses it and
records the refused attempt (as before). Published snapshots never change.

**Approve only when:** the verdict is READY; the deadline and cutoff are the
expected week; the exclusions and ineligible counts look normal for the leagues in
play (a sudden rise in stale quotes or missing prices means the football store was
not refreshed — refresh it and check again rather than publishing); and `ops check`
shows no CRITICAL finding.

## 3. Scheduler status and health
`ops status` (overview) and `ops check` (findings with severities). A disabled or
paused scheduler is reported as INFO, never as an outage. "tick active" means a
tick holds the scheduler lock now. Details and every finding:
[`operations_monitoring.md`](operations_monitoring.md).

## 4. Investigating a round or a failed job
1. `round inspect --code CODE --operator EMAIL` — one report with the lifecycle
   position, deadline, cutoff, entries, result mode, settlement version, round
   validity, pending predictions, unsettled evidence, correction window, **earliest
   finalisation (S-02)** and whether it can be finalised now (with the reasons if
   not), relevant fixtures and their resolution, open alerts, weekly results
   revision, championship assignment, recent jobs and audit records. Read-only (the
   settlement figures are computed in a transaction that is always rolled back).
2. `ops jobs --round CODE` / `ops jobs --failed` — job history with outcome classes.
3. `results show --round CODE --operator EMAIL` — per-fixture evidence.
4. `audit list --round CODE --operator EMAIL` — who did what (usernames or
   `SYSTEM`; never email addresses). Filters: `--action-prefix round.`, `--since`,
   `--limit` (≤ 200), `--json`.

## 5. Settlement, corrections and blocking alerts
* Status and S-02 timing: `settle status --round CODE` (or `round inspect`).
* Blocking alerts hold finalisation for a person: list with `settle alerts`,
  investigate the fixture with `results show`, then either correct the result
  (`results correct`, preview first) or confirm the alert with a reason
  (`settle resolve-alert`). Runbook §5.
* A correction restarts the correction window when it changes the settlement
  materially; finalisation waits for the new earliest time. Nothing shortens it.

## 6. Safe retry and recovery
* `jobs tick` is idempotent; `--dry-run` shows what is due. Runbook §2.
* Pause / resume: runbook §3. Lock loss or indeterminate ticks: runbook §4a (wait
  up to 20 minutes; never clear `job_runs` rows by hand).
* Manual commands repeat safely: `round lock` on a locked round, `settle run` with
  no new evidence and `results import` are all idempotent.
* A failed command prints one line and exits non-zero; the failing transaction is
  rolled back. Re-check with `round inspect` before retrying.
* Backups, restores and recovery (Stage F2): [`operations_hosting.md`](operations_hosting.md)
  and runbook §13. A competition-database restore holds provider calls until an
  operator reconciles and runs `ops provider-resume`; live football-store
  replacement is disabled (restore to a new path, then the offline switch).

## 7. Championship verification
`competition status` (each stream's current championship and waiting rounds) and
`competition verify` (read-only integrity) after finalisations; `ops check --deep`
runs the full inspection. Repairs and backfills are preview-first and audited
(`competition repair`, `competition backfill`); see
[`operator_settlement_cli.md`](operator_settlement_cli.md).

## 8. Account administration
`account list-privileged`; `grant-role` / `revoke-role` and `grant-feature` /
`revoke-feature` (owner); `suspend` / `reinstate` (operator or owner). Each needs
`--email` (the account to change), `--reason` and `--operator` (you), and checks
its arguments **before** asking for your password (`--role` for role commands,
`--feature` for feature commands; an option that does not apply is refused).
Recency rules: 12 hours for operator actions, 15 minutes for sensitive ones. The
last owner cannot be removed; you cannot change your own status. There is no
emergency owner recovery, impersonation or bypass; if no owner can act, follow
[`authentication.md`](authentication.md) §6.1. Review changes with
`audit list --action-prefix role` (or `entitlement`, `account.`).

## 9. Escalation and stop conditions
Stop and escalate to the owner (do not improvise) when:

* `ops check` reports **Official-stream activity**, a **wrong migration head** or
  missing tables (CRITICAL);
* `competition verify` or `ops check --deep` reports a **material** finding;
* a round is **overdue for finalisation** with no blocking alert or obvious cause;
* the same step fails 6 times in a row, or the provider fails repeatedly with the
  budget exhausted;
* a tick shows **lock lost** repeatedly (connection mode or host timeouts; see the
  scheduler document) or a step stays indeterminate beyond 20 minutes;
* a fix would need a direct database edit, a force-finalise, a change to a
  competition rule or a credential you do not hold.
