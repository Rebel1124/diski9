# Scheduled lifecycle reconciler (`diski9 jobs`)

Phase 6C.6 Stage C. One idempotent command, `diski9 jobs tick`, run every few
minutes by an external trigger (cron, a systemd timer, launchd or a hosted
scheduler). Each run reads the competition database and performs whatever
lifecycle step is due **now**, through the existing services, then exits. It is
not a daemon: it never loops, sleeps between rounds or schedules itself.

**Beta publication stays supervised (owner decision).** The scheduler never
publishes a round and has no switch to do so. Since Stage E.1a it can, when
`DISKI9_JOBS_PREPARE` is on, **create the upcoming week's Beta draft** and
**evaluate its readiness** read-only (see "Automated draft preparation" below);
an authenticated operator still publishes each round with `diski9 round publish
--code CODE --operator EMAIL`, which shows the exact snapshot and asks for the
round code.

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

**Never automated:** publication, round creation other than the scheduled Beta
draft (Stage E.1a), corrections, alert resolution,
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
| 0 | nothing failed (also: automation disabled, paused, another tick still running, or an earlier tick that lost its lock and may still be finishing — "indeterminate") |
| 1 | at least one retryable failure (retried by a later tick with back-off), the tick lost the scheduler lock, or the database was unavailable |
| 2 | invalid configuration, or an unsafe (transaction-pooler) lock connection: nothing was done |
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
| `DISKI9_JOBS_PROVIDER_CALLS` | off | on/off | allow results import from API-Football; off holds real-round finalisation (it needs the full re-check). Overridden to off (with refresh) while a Stage F2 **provider hold** is active after a competition-database restore, until an operator runs `ops provider-resume` ([operations_hosting.md §8](operations_hosting.md#8-postgresql-restore-and-the-recovery-gate-safeguard-d)) |
| `DISKI9_JOBS_MAX_REQUESTS_PER_TICK` | 10 | 1–100 | provider requests one tick may send (retries included) |
| `DISKI9_JOBS_MAX_REQUESTS_PER_DAY` | 100 | 1–5000 | scheduler provider requests in any rolling 24 hours |
| `DISKI9_JOBS_RESULTS_REFRESH_MINUTES` | 60 | 5–1440 | minimum gap between results imports for one round |
| `DISKI9_JOBS_SETTLE_REFRESH_MINUTES` | 60 | 5–1440 | minimum gap between routine settlement runs and finalisation attempts |
| `DISKI9_JOBS_RETRY_BASE_MINUTES` | 15 | 1–1440 | back-off after the first failure of a step |
| `DISKI9_JOBS_RETRY_MAX_MINUTES` | 240 | 1–10080 | longest back-off |
| `DISKI9_JOBS_PREPARE` | off | on/off | Stage E.1a draft creation and readiness evaluation (needs `DISKI9_JOBS_ENABLED`) |
| `DISKI9_JOBS_PREPARE_STREAMS` | (none) | `beta` | required when preparation is on; `development` and `official` are refused |
| `DISKI9_JOBS_PREPARE_CREATE_LEAD_HOURS` | 78 | 6–78 | draft created this long before the publication target (never before the previous window ends) |
| `DISKI9_JOBS_PREPARE_READINESS_MINUTES` | 30 | 5–240 | gap between successful readiness evaluations |
| `DISKI9_JOBS_PREPARE_GRACE_HOURS` | 6 | 1–24 | after the target, an unpublished week becomes "target missed" |
| `DISKI9_JOBS_PREPARE_MIN_SECONDS` | 60 | 10–600, below the tick budget | least tick time left before an evaluation starts |

The development stream cannot be automated when `DISKI9_APP_ENVIRONMENT=production`.
Development rounds never call the provider. The scheduler stores no operator
password, session or token: there is nothing to configure for identity, because
it acts as the explicit `SYSTEM` actor that the services accept only for lock,
results import, settlement and finalisation, and (Stage E.1a) the scheduler-only
`create_scheduled_draft`, which takes nothing but the ISO week.

## Automated draft preparation (Stage E.1a)

Off by default. When on, each tick — **after** the lifecycle steps, under the same
lock, ownership checks and 240-second budget — does at most two things for the
single upcoming Beta week:

| Step | When | What |
|---|---|---|
| `prepare_draft` (job `scheduler.prepare_draft`) | from the draft creation time (default: the end of the previous fixture window, Tuesday 00:00 UTC, i.e. 78 h before the Friday 08:00 SAST target) while no round has the week's code | `rounds.create_scheduled_draft`: code `{ISO year}-W{week}-weekend`, window and series taken **only** from the active `weekend` schedule; Beta only; if any round already has the code (created by an operator, published, anything) nothing is written; row, status history (`created (scheduled)`) and audit `round.create` by `system` with the job link in one transaction |
| `prepare_readiness` (job `scheduler.prepare_readiness`) | while the week's round is a draft and its window has not ended, every `DISKI9_JOBS_PREPARE_READINESS_MINUTES` since the last successful evaluation (failures retry on the normal back-off) | builds the live snapshot from the football store and runs **the same validator as `round readiness` / `round publish`**; records `ready` or `not_ready[category]` with a summary (fixtures, eligible, leagues, bucket counts, earliest kickoff, deadline, seconds) in the job row; writes nothing else; no provider call |

* **The week:** every instant belongs to exactly one competition week — from the
  end of the previous week's fixture window (Tuesday 00:00 UTC) to the end of this
  week's (the next Tuesday 00:00 UTC). Only that week is prepared.
* **Time budget:** an evaluation starts only if the tick has at least
  `max(DISKI9_JOBS_PREPARE_MIN_SECONDS, 2 × the slowest of the last 10 evaluations)`
  left; otherwise it is deferred to the next tick (never treated as ready). If an
  evaluation ever takes longer than half of (abandonment threshold − tick budget),
  it is refused as a blocking failure so the Stage D lock-recovery threshold stays
  safe. Measured cost on the real football store: about 0.1–0.2 s.
* **Cadence:** read-only evaluations run every 30 minutes from the moment the draft
  exists. Days before the target, NOT READY usually only means the football store
  has not been refreshed for publication yet; monitoring stays quiet until the
  attention window (see monitoring).
* **The football store:** the evaluation reads the same store as `round readiness`
  (`DISKI9_DATABASE_URL`). If it is missing or not set up, the step is a blocking
  failure (exit 4) and nothing is evaluated; the store is never created. Without
  automated refresh (below; off by default) run `diski9 refresh-data --with-odds`
  as before.
* **Advisory only:** a READY verdict never publishes anything and is never used as
  approval. `round publish` builds its own snapshot once, shows it, requires the
  round code and publishes exactly that snapshot (approved fingerprint).
* **Never:** publication, a draft for Development or Official, a draft for any week
  other than the upcoming one, any change to an existing round.

## Automated football-data refresh (Stage E.1b)

Off by default (`DISKI9_JOBS_PREPARE_REFRESH`); needs `DISKI9_JOBS_PREPARE` (Beta)
and `DISKI9_JOBS_PROVIDER_CALLS`. **Refresh cannot be switched on with the pre-E.1b
caps** (10 per tick, 100 per 24 h, D-1): the 24-hour cap must hold the preparation
cap plus the results reserve, so activation needs the owner-approved values set
explicitly (`DISKI9_JOBS_MAX_REQUESTS_PER_TICK=20`,
`DISKI9_JOBS_MAX_REQUESTS_PER_DAY=450`). No live activation is authorised yet.

When on, each tick — after the lifecycle steps and draft creation, before readiness,
under the same lock, ownership checks and 240-second budget — refreshes the football
store for the upcoming week with the **same functions as `refresh-data --with-odds`**
(fixtures and odds for all eight leagues; no standings), then the Screener cache.

| When (UTC) | Slot |
|---|---|
| Tue, Wed, Thu 04:15 | daily sweep (`DISKI9_JOBS_PREPARE_REFRESH_DAILY`) |
| Fri 04:15 and 05:15 | publication sweeps, before the 06:00 target (`…_PUBLICATION`) |
| Fri 06:15 … 11:15, while unpublished | grace sweeps every 60 minutes (`…_GRACE_MINUTES`) |
| after publication or after the grace | nothing (manual `refresh-data` remains) |

* **Current slot only.** Each tick works the latest slot not in the future; earlier
  slots are never replayed after an outage.
* **Sweep = one step per league** (`scheduler.prepare_refresh`, scope
  `<week>:<league>`, `args.slot`). A league is done for the slot only when its step
  **succeeded**; done leagues are not requested again in the slot. A typical sweep
  needs about 23 requests (`/status` 1, fixtures 8, odds 14), so with 20 per tick it
  spans two ticks (Friday: about 04:21 and 05:21); with 10 per tick, three.
* **Complete / partial.** A sweep is *complete* when all eight leagues are done and
  the Screener step (`scheduler.prepare_screener`) has succeeded for the slot. It
  is closed *partial* (Screener step `kind: partial`, `leagues n/8`) when the next
  slot becomes current or 30 minutes after its first league step
  (`…_PARTIAL_AFTER_MINUTES`). A closed sweep is terminal for its slot; the next slot
  refreshes every league again. A failing league backs off (within the slot only).
* **Fetch, then write.** Each league's requests run with no football-store
  transaction open; ownership is re-verified; the response is written in one short
  SQLite transaction. A failure (or a lost lock) before or during the write leaves
  that league unchanged. Another writer holding the store gives a retryable
  "football store busy".
* **Readiness coordination.** The E.1a evaluation waits while a sweep is part-way
  (at most until it closes) and runs as soon as a sweep closes; each verdict records
  `data=complete@<slot>`, `partial@<slot>(n/8)`, `none` or `refresh-off`. A completed
  sweep never means READY: the Stage E validator decides, and publication stays
  with an authenticated operator.

### Provider safety (also for results imports)

* **Request classes.** Every ledger row records `args.class`: `results` or
  `preparation` (refresh and `/status`). Rows written before E.1b count as results
  (D-2). Preparation is limited to `DISKI9_JOBS_NONESSENTIAL_REQUESTS_PER_DAY`
  (300) **and** may never use the last `DISKI9_JOBS_RESULTS_RESERVE` (150) of the
  24-hour cap; results may use the whole cap. Every attempt — retries included — is
  checked when it is reserved, so a retry can never push past a cap; a league that
  runs out part-way stops, writes nothing and stays incomplete.
* **Pacing across ticks.** Each reservation records its *send slot* — at least
  `DISKI9_JOBS_PROVIDER_MIN_INTERVAL_SECONDS` (3) after the previous scheduler
  request — in the same serialised transaction, then the caller waits for it. The
  slot is committed before anyone sleeps, so another tick, thread or restarted
  process is always placed after it; a crash after reserving leaves the slot used
  and counted. A slot more than the maximum wait away is refused (deferred).
* **Bounded waits.** No provider wait inside a tick exceeds
  `DISKI9_JOBS_PROVIDER_MAX_WAIT_SECONDS` (30): a longer `Retry-After`, an exhausted
  429 retry or a long per-minute window ends the step as *rate limited* and records
  a **cooldown** (`scheduler.provider_cooldown`) that every scheduler request —
  results included — honours. The per-minute floor keeps a tenth of the provider's
  minute allowance for other users of the key. The longest possible tick (budget +
  per-tick cap × (timeout + interval) + maximum wait) is validated against the
  20-minute abandonment threshold.
* **Provider floor (preparation only).** Before a refresh step the most pessimistic
  usable observation of the provider's daily remaining — response headers or one
  `/status` request (quota-free at the provider, reserved here as one preparation
  request) when there is no observation younger than 30 minutes from the current
  UTC day — must stay above `DISKI9_JOBS_PREPARE_PROVIDER_FLOOR` (2,000). A reported
  daily limit below `DISKI9_JOBS_PROVIDER_EXPECTED_DAILY_LIMIT` (7,500) stops
  preparation for the provider day. Results keep only the client's existing reserve
  (500). Our caps are a rolling 24 hours over our own ledger; the provider's quota is
  a calendar day (UTC) for every user of the key: both must pass.

## Provider budget and retry policy

* **Two switches before any request:** `DISKI9_JOBS_ENABLED` and
  `DISKI9_JOBS_PROVIDER_CALLS`. With provider calls off, real rounds are locked and
  settled but never finalised by the scheduler.
* **Ledger (crash- and concurrency-safe).** Every provider request — retries
  included — is recorded *before* it is sent, as a `job_runs` row with
  `job = 'scheduler.provider'` and `api_requests = 1`, in a short transaction that
  takes a transaction-level advisory lock and re-checks the per-tick and rolling
  24-hour caps. A crash after sending cannot lose the count, failed requests are
  counted, and concurrent callers cannot spend the same allowance. The count is
  conservative: a request recorded and then not sent (a crash between the two) is
  counted as spent. Abandoned or indeterminate steps do not affect it (the ledger
  is independent of step records).
* **Caps:** before each import the scheduler computes the remaining allowance from
  the ledger; an import needing more requests than remain is **not started** and is
  recorded as `deferred: provider budget exhausted …`. A cap reached part-way (for
  example by a retry) stops further requests the same way. The client's existing
  daily-reserve guard (`DISKI9_API_FOOTBALL_DAILY_RESERVE`) still applies.
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
* **E.1b additions:** request classes, the results reserve, pacing, bounded waits,
  cooldowns and quota observations apply to results imports as well (see above).
* **Proposed limits for owner approval.** The defaults (10 per tick, 100 per 24
  hours, hourly refresh) are conservative proposals, not derived from a confirmed
  plan quota: a round's import needs about 1–3 requests (relevant fixtures, 20 per
  request), roughly hourly while matches are in progress, so one weekend round
  needs well under 100 requests a day. They should be confirmed against the
  account's daily allowance before the Beta round (Stage F).

## Safety properties

* **One tick at a time (session lock, Stage D remediation).** A tick holds a
  *session-level* PostgreSQL advisory lock on a dedicated autocommit connection that
  is never inside a transaction, so database limits such as
  `idle_in_transaction_session_timeout` cannot end it while the tick waits for the
  provider. The lock is released explicitly at the end and automatically if the
  connection dies. A second tick records `skipped: another tick is still running`
  and exits 0.
* **Ownership.** Each tick has a unique run token (the lock connection's
  `application_name` is `diski9-tick:<token>`, also stored in the tick's job row).
  Before every lifecycle step and before every provider request the tick verifies
  that the same server session still holds the lock. If not, it stops starting
  work, finishes recording the step in flight, records `lock lost` on its tick row
  and exits 1; it never re-acquires the lock in the same run.
* **Abandonment.** A new tick that finds another tick's steps still `running`
  marks them abandoned only if that tick started more than
  `DISKI9_JOBS_ABANDON_AFTER_MINUTES` (20) ago — longer than any live tick can run
  (below). Otherwise the state is *indeterminate*: the old process may still be
  finishing an in-flight step, so the new tick does no lifecycle work, records
  `skipped: indeterminate …` and exits 0. A tick interrupted in-process (Ctrl-C,
  an unexpected error) records its own steps as `abandoned: interrupted`. Each
  service call is one transaction, so no step is ever half-applied.
* **Bounded duration.** No new step starts after `DISKI9_JOBS_TICK_BUDGET_SECONDS`
  (240); the remaining work continues on the next tick. The scheduler's provider
  client uses a 10-second timeout and one retry (`DISKI9_JOBS_PROVIDER_TIMEOUT_SECONDS`,
  `DISKI9_JOBS_PROVIDER_MAX_RETRIES`), so one step can make at most 10 requests of
  ≤ 22 seconds each; database statements are bounded by the statement (15 s) and
  lock (5 s) timeouts. Worst case: about 8 minutes, well inside the 20-minute
  abandonment threshold; with the suggested 5-minute trigger, an overlapping
  invocation simply skips.
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

## Database connection for the scheduler

The tick lock needs a **direct or session-mode** connection: a session-level lock
is meaningless through a transaction pooler, which hands each statement to any
server session.

* Default: the application database URL — refused if
  `DISKI9_APP_POOLER_MODE=transaction`.
* Otherwise set `DISKI9_JOBS_DATABASE_URL` (a secret, never printed) to a direct
  connection or a session-mode pooler, and `DISKI9_JOBS_DATABASE_MODE` to `direct`
  (default) or `session`. On Supabase: the direct host (`db.<ref>.supabase.co`, port
  5432) or the session pooler (port 5432), **not** the transaction pooler (port 6543).
* Refused automatically: port 6543, `pgbouncer=true`, mode `transaction`.
* **Limitation and validation.** A pooler on another port that is not labelled cannot
  be recognised from configuration alone. At every acquisition and check the tick
  verifies that the same server backend still holds the lock; through a transaction
  pooler this normally fails at once (`unsafe_connection`, exit 2). Before relying on
  a new host, also validate by hand: connect with the scheduler URL in two `psql`
  sessions; in the first run `SELECT pg_try_advisory_lock(42), pg_backend_pid();`,
  wait a minute, and run `SELECT pg_backend_pid();` again (the PID must not change);
  in the second run `SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND objid
  = 42;` (it must show the first session's PID); then `SELECT pg_advisory_unlock(42);`
  in the first. Do not weaken database timeouts for the scheduler; none is needed.

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
