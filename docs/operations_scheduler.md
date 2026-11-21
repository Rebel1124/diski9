# Scheduled lifecycle reconciler (`diski9 jobs`)

Phase 6C.6 Stage C. One idempotent command, `diski9 jobs tick`, run every few
minutes by an external trigger (cron, a systemd timer, launchd or a hosted
scheduler). Each run reads the competition database and performs whatever
lifecycle step is due **now**, through the existing services, then exits. It is
not a daemon: it never loops, sleeps between rounds or schedules itself.

**Beta publication stays supervised (owner decision).** The scheduler never creates
or publishes a round, never builds a snapshot and has no switch to do so. Draft
rounds are reported ("awaiting operator publication") and an authenticated
operator publishes each round with `diski9 round publish --code CODE --operator
EMAIL`, as before.

## What it does

| Step | Due when (database clock, UTC) | Service (unchanged rules) |
|---|---|---|
| lock | an open round whose `deadline_at` has passed | `rounds.lock_round` |
| results | a locked or settling **real** round, provider calls switched on, the results refresh interval elapsed since the last attempt | `results.import_results` (relevant fixtures only, ≤ 20 IDs per request; fixtures not yet near kickoff or stable for 6 hours are not fetched) |
| settle | first settlement after the lock; new evidence this tick; the settlement cutoff has passed since the last run; or the settle refresh interval elapsed | `settlement.settle_round` (idempotent; alerts raised by the service; `trigger = scheduled`) |
| results (full re-check) | a real round has reached its earliest finalisation time and has no fresh full re-check | `results.import_results(full=True)` |
| finalise | `now ≥ earliest_finalisation = max(settlement cutoff, last material settlement change) + correction window` (S-02), no settlement-blocking alert, and for real rounds a full re-check after that time | `corrections.finalise_round` (which makes a final settlement run, refuses on any remaining condition, publishes the weekly results and processes championships) |

The settlement cutoff is the latest scheduled kickoff + 48 hours; the correction
window is the round's frozen value (24 hours for real rounds). The scheduler
decides only *when to ask*; every rule is re-checked by the service, which uses the
database clock and refuses time overrides for the scheduler.

Rounds are processed one at a time, oldest deadline first, each step in its own
transaction. After every step the round is re-read and the next step decided, so
one tick can take a round from open to settling, or from settling to final.

**Never automated:** publication, round creation, corrections, alert resolution,
withdrawal of corrections, invalidation, reopening, result-mode choice, role or
entitlement changes. Blocking alerts are reported, never resolved.

## Commands

```bash
uv run diski9 jobs tick            # one pass (for the trigger)
uv run diski9 jobs tick --dry-run  # what is due now; writes nothing, calls no provider
uv run diski9 jobs status          # configuration, provider use, recent runs (read-only)
```

Output is one line per step, for cron logs, for example:

```text
[tick 812] beta 2026-W48 lock: succeeded - 37 valid entries, championship [job 813]
[tick 812] beta 2026-W48 results: succeeded - polled 9, not due 23, new observations 9, 1 provider request(s) [job 814]
[tick 812] beta 2026-W48 settle: succeeded - version 1, 0 blocking alert(s) open [job 815]
[tick 812] beta 2026-W48 finalise: skipped - earliest finalisation 2026-12-02 19:00 UTC (S-02)
tick 812 completed: 3 succeeded, 1 skipped, 0 deferred, 0 retryable failure, 0 blocking failure; provider requests 1 (24 h 14/100)
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | nothing failed (also: automation disabled, paused, or another tick still running) |
| 1 | at least one retryable failure (retried by a later tick with back-off), or the database was unavailable |
| 2 | invalid configuration: nothing was done |
| 4 | an operator must act (for example a settlement-blocking alert) and nothing retryable failed |

### Outcomes

| Outcome | `job_runs.status` | Meaning |
|---|---|---|
| succeeded | succeeded | the service did its work |
| skipped | skipped | nothing to do now, already done, or waiting for the clock |
| deferred | skipped | due but held back: back-off, provider budget, provider calls off |
| retryable_failure | failed | provider or database error; retried after back-off |
| blocking_failure | failed | needs an operator (blocking alert, provider access refused, a service refusal) |

Non-success rows keep the outcome as the prefix of `job_runs.error` (`deferred: …`).

## Configuration reference

Environment variables (the same `.env` as the application). **Fail closed:** any
invalid value is a configuration error (exit 2, nothing done).

| Variable | Default | Allowed | Meaning |
|---|---|---|---|
| `DISKI9_JOBS_ENABLED` | off | on/off | master switch; off means a tick does nothing and touches no database |
| `DISKI9_JOBS_STREAMS` | (none) | `beta`, `development` | required when enabled; **`official` is refused** and cannot be configured |
| `DISKI9_JOBS_PAUSED` | off | on/off | emergency pause: a tick records itself as paused and stops |
| `DISKI9_JOBS_PAUSE_FILE` | (none) | a path | pause while this file exists (`touch` to pause, `rm` to resume) |
| `DISKI9_JOBS_PROVIDER_CALLS` | off | on/off | allow results import from API-Football; off holds real-round finalisation (it needs the full re-check) |
| `DISKI9_JOBS_MAX_REQUESTS_PER_TICK` | 10 | 1–100 | provider requests one tick may send (retries included) |
| `DISKI9_JOBS_MAX_REQUESTS_PER_DAY` | 100 | 1–5000 | scheduler provider requests in any rolling 24 hours |
| `DISKI9_JOBS_RESULTS_REFRESH_MINUTES` | 60 | 5–1440 | minimum gap between results imports for one round |
| `DISKI9_JOBS_SETTLE_REFRESH_MINUTES` | 60 | 5–1440 | minimum gap between routine settlement runs and finalisation attempts |
| `DISKI9_JOBS_RETRY_BASE_MINUTES` | 15 | 1–1440 | back-off after the first failure of a step |
| `DISKI9_JOBS_RETRY_MAX_MINUTES` | 240 | 1–10080 | longest back-off |

The development stream cannot be automated when `DISKI9_APP_ENVIRONMENT=production`.
Development rounds never call the provider. The scheduler stores no operator
password, session or token: there is nothing to configure for identity, because
it acts as the explicit `SYSTEM` actor that the services accept only for lock,
results import, settlement and finalisation.

## Provider budget and retry policy

* **Two switches before any request:** `DISKI9_JOBS_ENABLED` and
  `DISKI9_JOBS_PROVIDER_CALLS`. With provider calls off, real rounds are locked and
  settled but never finalised by the scheduler.
* **Caps:** before each import the scheduler computes its allowance as the smaller
  of the per-tick remainder and the rolling 24-hour remainder (the sum of
  `api_requests` on `scheduler.results*` job runs). An import needing more requests
  than the allowance is **not started** and is recorded as `deferred: provider
  budget exhausted …`. The allowance is also set as the client's request budget, so
  even retries cannot exceed it; the client's existing daily-reserve guard
  (`DISKI9_API_FOOTBALL_DAILY_RESERVE`, from the provider's remaining-requests
  header) still applies and a refusal there is also `deferred`. Every request sent,
  including failed ones, is counted.
* **Frequency:** at most one import per round per results refresh interval; the
  service fetches only fixtures selected in locked entries, only from 30 minutes
  before kickoff, and skips fixtures that have been final (or cancelled) for 6
  hours, unless it is the full re-check before finalisation.
* **Errors:** HTTP errors, time-outs and rate limits (after the client's own
  retries) are retryable failures; refused access (invalid key, forbidden endpoint)
  is blocking; quota exhaustion is deferred. Messages are reduced to the error type,
  so no provider text or key reaches logs or the database.
* **Back-off:** after `n` consecutive failures of a step for a round, the next
  attempt waits `min(base × 2^(n−1), max)` from the last failure (15, 30, 60, 120,
  240 minutes by default). A success resets it. There is no retry loop inside a
  tick.
* **Proposed limits for owner approval.** The defaults (10 per tick, 100 per 24
  hours, hourly refresh) are conservative proposals, not derived from a confirmed
  plan quota: a round's import needs about 1–3 requests (relevant fixtures, 20 per
  request), roughly hourly while matches are in progress, so one weekend round
  needs well under 100 requests a day. They should be confirmed against the
  account's daily allowance before the Beta round (Stage F).

## Safety properties

* **One tick at a time.** A tick holds a transaction-scoped PostgreSQL advisory lock
  (`ops.try_job_lock("scheduler.tick", "global")`) on a dedicated connection for
  its whole run; a second tick records `skipped: another tick is still running`
  and exits 0. A crash closes the connection and releases the lock.
* **Crash recovery.** Steps left `running` by a tick that ended abruptly are marked
  `failed` (`abandoned …`) by the next tick, so back-off applies, then the work
  resumes from the database state. Each service call is one transaction, so a crash
  never leaves a half-applied step.
* **Missed ticks.** Nothing assumes earlier ticks ran: after an outage the next tick
  performs every overdue step in order. A missed tick never bypasses a safeguard:
  results that arrive after the settlement cutoff raise the existing
  late-notification alerts, which hold finalisation for an operator.
* **Isolation.** A failure in one round is recorded and the tick continues with
  the next round; a failed lock, full re-check or final settlement stops further
  steps for that round in that tick.
* **Streams.** Only allowlisted streams, checked twice (configuration and a fixed
  set in code). Official is not automatable by any setting.
* **Audit.** Every tick and every attempted step is a `job_runs` row (`job`
  `scheduler.<step>`, `scope` the round code, host, provider requests, outcome).
  Service writes are audited as `actor_role = system` with no user; scheduled
  settlement runs carry `trigger = scheduled` and the scheduler's `job_run_id`.

## Running it on a host (examples)

The trigger is the only host-specific piece (hosting decision Q-07 belongs to
Stage F planning). Every five minutes is the suggested interval; the command is
safe at any interval because work is decided from the database state.

**cron** (`crontab -e`):

```text
*/5 * * * * cd /srv/diski9 && /usr/local/bin/uv run diski9 jobs tick >> /var/log/diski9/jobs.log 2>&1
```

**systemd** (`diski9-jobs.service` + `diski9-jobs.timer`):

```ini
[Service]
Type=oneshot
WorkingDirectory=/srv/diski9
ExecStart=/usr/local/bin/uv run diski9 jobs tick

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

**launchd** (macOS, `~/Library/LaunchAgents/za.diski9.jobs.plist`): a
`ProgramArguments` of `uv run diski9 jobs tick`, `WorkingDirectory` the checkout,
`StartInterval` 300. A sleeping laptop does not run it; the next run catches up.

Keep `.env` readable only by the account that runs the trigger. The scheduler
needs only the competition database URL and, if provider calls are on, the
provider key; it needs no Supabase key or operator credentials.

## Pausing in an emergency

`touch "$DISKI9_JOBS_PAUSE_FILE"` (or set `DISKI9_JOBS_PAUSED=on`) stops all
automated lifecycle work at the next tick; operators keep every manual command.
Remove the file to resume; the next tick catches up.
