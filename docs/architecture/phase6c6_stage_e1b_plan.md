# Phase 6C.6 Stage E.1b — Automated API-Football Data Refresh: implementation plan

**Status:** **implementation authorised (22 Nov 2026) and delivered; awaiting owner
acceptance** — D-1 to D-3 approved; implementation record
[`phase6c6_implementation.md`](phase6c6_implementation.md) §10. Automated refresh
remains off; no live provider call, limit change, hosting selection or activation.
Original status: implementation plan for owner review (planning authorised 22 Nov
2026); implementation was not authorised at that point. No application code, migration, provider
limit, live provider call, hosting selection, activation or deployment is part of
this plan. Design: [`phase6c6_stage_e1b_design.md`](phase6c6_stage_e1b_design.md)
(approved in principle: REF-01 to REF-10, REF-15, REF-16; deferred: REF-11, REF-12
hosting, REF-13, REF-14, REF-17 live conditions retained).

Baseline: branch `feature/phase-6c6-operations` at `7ba81d7` (design, CI run 107);
application baseline `3ed0301` (CI run 104: 1,835 passed, 13 browser tests); head
`app_0007`; fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
`broad60-432-v1`; `points-150-75-v2`.

**No migration is needed.** Everything is recorded in `app.job_runs` (its `args`
JSON is written once, at insert, and the existing guard keeps it immutable), the
football store's existing `odds_fetches` / `ingestion_runs` tables, and
configuration.

---

## 1. Modules and functions

| File | Change |
|---|---|
| `src/diski9/api_football/client.py` | New optional field `max_wait_seconds: float \| None = None` (default keeps today's behaviour for every CLI command). `_backoff`: when the wait would exceed it, raise `ApiFootballRateLimitError` carrying `retry_after` instead of sleeping. |
| `src/diski9/api_football/ratelimit.py` | `RateLimiter`: optional `max_wait_seconds` (same rule for the minute-window wait) and a `minute_floor_ratio` (floor = max(2, minute limit ÷ 10)); defaults unchanged. |
| `src/diski9/api_football/errors.py` | `ApiFootballRateLimitError.retry_after: float \| None` (backwards compatible). |
| `src/diski9/ingestion/fixtures.py` | Split `ingest_fixtures` into `fetch_season_fixtures(client, cid, season) -> list[dict]` (network only) and `apply_season_fixtures(conn, items, cid, season, clock, requests=1) -> RunStats` (`require_season`, `ingestion_run`, `store_fixtures`). `ingest_fixtures` keeps its signature and calls `require_season` → fetch → apply. |
| `src/diski9/odds/collect.py` | `fetch_odds_pages(client, cid, season, max_pages=None) -> list[OddsPage]` (network only). `reconcile_pages(..., started=None)` keeps its behaviour; `collect_odds` = `reconcile_pages(conn, cid, season, fetch_odds_pages(...), clock, started=<time before fetch>)`, so `odds_fetches.retrieved_at` keeps today's meaning. |
| `src/diski9/backend/jobs/provider.py` | `ApiFootballProvider.request(endpoint, params, reserve)` and `.pages(endpoint, params, reserve)` (generic, same `_ReservingLimiter`); `fetch` unchanged in behaviour. `api_football_provider(...)` passes `max_wait_seconds`, the minute-floor ratio and the 3 s interval to the client used by **both** results imports and refresh. |
| `src/diski9/backend/jobs/locking.py` | `reserve(..., klass="results")`: request class written to the ledger row's `args`; class-aware cap checks; pacing (returns the seconds to wait since the previous scheduler reservation); provider cooldown check. `allowance(...)` gains the class. `SCHEDULER_JOBS` += `scheduler.prepare_refresh`, `scheduler.prepare_screener`. |
| `src/diski9/backend/jobs/config.py` | New settings and validation (§2). |
| `src/diski9/backend/jobs/refresh.py` (**new**) | Slots, sweep progress, quota observations, league step (fetch → verify → apply), screener step, refresh status. Imports only ingestion, odds, Screener cache, provider adapter, locking, config. |
| `src/diski9/backend/jobs/prepare.py` | `plan` / `run_preparation` call the refresh planner between draft creation and readiness; readiness due when the interval elapsed **or** a sweep finished since the last evaluation, and deferred while a sweep is in progress (§7); readiness record gains a `data=` field; `PreparationStatus` gains refresh fields; `preparation_lines` shows them. Behaviour with refresh off is unchanged. |
| `src/diski9/backend/jobs/reconciler.py` | `_classify`: `ApiFootballRateLimitError` → *retryable (rate limited)*; `tick` passes a store-engine factory (test seam, like `snapshot_builder`); `plan_tick` lists planned refresh steps. Results import passes `klass="results"`. |
| `src/diski9/backend/ops/snapshot.py`, `ops/checks.py`, `ops/config.py`, `ops/history.py` | Refresh and provider snapshot fields; findings (§8); thresholds; `KNOWN_JOBS` += new jobs. |
| `src/diski9/ops_cli.py`, `jobs_cli.py` | "Data refresh" block in `ops status` / `jobs status`; `jobs tick --dry-run` lists refresh steps. |
| `src/diski9/cli.py` (`round readiness`) | **Optional, display only (needs approval, §14 D-3):** one line "Data refresh: complete 04:21 / in progress 6 of 8 / partial" read from `job_runs`. No change to checks, snapshot or publication. |
| Docs | design, scheduler, monitoring, runbook, operator guide, `.env.example`, implementation record. |

Not changed: `challenge/roundsheet.py` (snapshot builder), `services/rounds.py`
(publication), `services/results.py`, settlement, corrections, championships,
authentication, `workflow.py` (except through the split functions, same results),
migrations.

## 2. Configuration and validation

| Variable | Default | Range / rule |
|---|---|---|
| `DISKI9_JOBS_PREPARE_REFRESH` | off | requires `DISKI9_JOBS_PREPARE`, Beta in `DISKI9_JOBS_PREPARE_STREAMS` and `DISKI9_JOBS_PROVIDER_CALLS` |
| `DISKI9_JOBS_PREPARE_REFRESH_DAILY` | `04:15` | `HH:MM` UTC; Tue–Thu |
| `DISKI9_JOBS_PREPARE_REFRESH_PUBLICATION` | `04:15,05:15` | 1–4 Friday times, all before the publication target |
| `DISKI9_JOBS_PREPARE_REFRESH_GRACE_MINUTES` | 60 | 15–240 |
| `DISKI9_JOBS_PREPARE_REFRESH_PARTIAL_AFTER_MINUTES` | 30 | 10–60: after this, an unfinished sweep is finalised as partial |
| `DISKI9_JOBS_NONESSENTIAL_REQUESTS_PER_DAY` | 300 | 1–5000 |
| `DISKI9_JOBS_RESULTS_RESERVE` | 150 | 50–5000 |
| `DISKI9_JOBS_PREPARE_PROVIDER_FLOOR` | 2000 | 600–7000; must exceed `DISKI9_API_FOOTBALL_DAILY_RESERVE` |
| `DISKI9_JOBS_PROVIDER_MIN_INTERVAL_SECONDS` | 3 | 1–30 |
| `DISKI9_JOBS_PROVIDER_MAX_WAIT_SECONDS` | 30 | 5–60 |
| `DISKI9_JOBS_PROVIDER_EXPECTED_DAILY_LIMIT` | 7500 | 100–100000 |
| `DISKI9_JOBS_PROVIDER_OBSERVATION_MAX_AGE_MINUTES` | 30 | 5–120 |
| `DISKI9_JOBS_MAX_REQUESTS_PER_TICK` | **10 (unchanged)** | 1–100 |
| `DISKI9_JOBS_MAX_REQUESTS_PER_DAY` | **100 (unchanged)** | 1–5000 |

**Defaults of the existing caps stay 10 and 100** (the approved 20 and 450 are the
planning baseline, not authorised for application). Validation, when refresh is on:
`max_per_day ≥ nonessential + results_reserve` — with the defaults (100 < 300 + 150)
turning refresh on is a `ConfigError` until the operator sets the approved
values (20/450) explicitly at activation. This makes the limit change a deliberate
live-activation step and leaves results imports' current caps untouched (§14 D-1).
Further rules: `abandon_after` > tick budget + worst refresh step (§12);
`max_wait ≤ 60`; floor > client daily reserve; publication times < target;
unknown or malformed values fail closed (existing `ConfigError` pattern).

## 3. Provider safety and budget enforcement

**Classes** (`args.class` on each `scheduler.provider` ledger row): `results`
(results and results_full), `preparation` (refresh and `/status`). Rows written
before E.1b have no class and count as `results`.

**`reserve()` — one serialised transaction, as today, plus:**

1. *Cooldown:* if the latest `scheduler.provider_cooldown` row (below) is still in
   force → `ProviderCooldown` (step deferred, no request). Applies to both classes.
2. *Caps:* per tick (all classes) and 24 h total, as today; for `preparation`
   additionally `nonessential_used + 1 ≤ nonessential` and `total_used + 1 ≤
   max_per_day − results_reserve`. Results may use the whole total; preparation can
   never use the reserve.
3. *Pacing:* the previous scheduler reservation's `started_at` is read in the same
   transaction; the function returns `wait = max(0, interval − (now − last))`. The
   caller sleeps `wait` (≤ 3 s) **after** the transaction commits, then sends. The
   ledger row is inserted with `started_at = clock_timestamp() + wait`, so the next
   reservation measures from the real send time. Because the ledger is in
   PostgreSQL, pacing holds across ticks and process restarts with no daemon or
   extra state (Clarification C).
4. *Provider floor (preparation only):* the caller checks the floor (§3.2) before
   calling `reserve()`; `reserve()` does not read provider data.

**Before each step** the existing pre-check (`allowance(...)` ≥ the step's maximum
need) decides whether the step starts at all; a league step needs ≤ 4, a results
import ⌈ids / 20⌉ as today.

### 3.1 Waits (both classes)

| Situation | Behaviour |
|---|---|
| HTTP 429 with `Retry-After` ≤ 30 s | one in-step retry after that wait (reserved first), as today but bounded |
| HTTP 429 with `Retry-After` > 30 s, or no retry left | no sleep; step ends *retryable: rate limited*; a `scheduler.provider_cooldown` row (completed insert) records `until = now + Retry-After` (or 60 s if absent); every scheduler provider step defers until then; normal back-off for the step |
| Body `errors.rateLimit` | same as 429 (wait = the client's minimum, ≤ 30 s) |
| Minute window (provider says < floor remaining this minute) | wait for the window only if ≤ 30 s; otherwise end the step as rate limited (cooldown 60 s) |
| Any rate-limit outcome in a tick | no further **refresh** steps in that tick; results imports in later ticks honour the cooldown |
| Interrupted during a wait | no transaction is open during any wait; the step row stays `running` and Stage D marks it interrupted (in-process) or abandoned after 20 min; the next tick reruns it idempotently |
| Tick budget | a step starts only if the time left ≥ its worst case (§12); waits never extend a step beyond that worst case |

### 3.2 Provider quota observations (preparation floor)

* **Recording:** after each refresh or results step, and after `/status`, the tick
  inserts a completed `scheduler.provider_quota` row: `args = {remaining, limit,
  source: header|status, observed_at}` (numbers only).
* **Usable observation:** the lowest `remaining` among observations that are (a)
  younger than 30 minutes and (b) from the **current provider day** (same UTC date;
  the provider resets at about 00:00 UTC). Anything else is stale.
* **No usable observation** at the start of a refresh step → one `/status` request
  (quota-free at the provider; **reserved as one preparation request in our ledger**,
  conservatively). If `/status` fails, preparation defers (fail closed); results are
  not gated by `/status`.
* **Header versus `/status` disagree:** the lower remaining wins; a gap over 10 % is
  noted in the step detail and in `ops check` (WARNING `provider_quota_inconsistent`).
* **Floor:** a refresh step starts only if `remaining − 4 ≥ floor (2,000)`; the
  in-memory header from each response is re-checked before every further request of
  the step. Results imports keep the client's existing reserve (500) only.
* **Other consumers** are visible only through these observations; the floor
  leaves them ≥ 5,500 requests of the provider day before preparation stops.
* **Lower daily limit** (`limit` < expected 7,500): preparation stops for the rest
  of the provider day; CRITICAL `provider_limit_mismatch`; results continue under
  their reserve.
* **Two budgets, two clocks:** our caps are a rolling 24 h over our own ledger
  (scheduler use only, exact, conservative); the provider floor is the provider's
  calendar-day remaining for all consumers of the key (approximate, lagging). Both
  must pass for preparation; neither resets the other.

## 4. Fetch-then-write

League step, all outside any SQLite transaction until step 4:

1. `fetch_season_fixtures` (1 request) and `fetch_odds_pages` (1–3 requests), every
   request reserved and paced through the provider adapter.
2. `lock.verify()` — ownership (Stage D).
3. Store engine checks (exists, tables present, setup complete); otherwise
   *blocking: football store unavailable* (fail closed, as E.1a).
4. One short SQLite transaction: `apply_season_fixtures`, venue classification for
   that league, `reconcile_pages`. Committed atomically (WAL). Typical ≈ 0.6–1 s.

A failure before step 4 writes nothing; a failure inside step 4 rolls back. SQLite
"database is locked" (another writer, 5 s busy timeout) → retryable. The CLI keeps
calling `ingest_fixtures` / `collect_odds`, which now fetch before taking the write
lock (no committed difference; existing tests plus a comparison test prove it).

## 5. Sweep identity, progress and resume (Clarification A)

* **Slot:** a scheduled time for the week, e.g. `2026-W48-weekend@2026-11-27T04:15Z`.
  The slot list for week W: Tue/Wed/Thu daily time; Friday publication times; grace
  times every `grace_minutes` from target + 15 min while target + grace has not
  passed. The **current slot** is the latest slot ≤ now.
* **League progress:** `scheduler.prepare_refresh` rows, scope `<week code>:<league
  id>`, `args = {slot, league, tick, run_token}`. League L is **done for slot S** iff
  a `succeeded` row with `args.slot = S` exists for scope `<code>:L`.
* **Resume:** each tick computes the not-done leagues for the current slot in fixed
  order (39, 40, 140, 61, 78, 135, 288, 289) and starts each while the per-tick and
  class allowance is ≥ 4, the tick has time, the floor holds and no cooldown is in
  force. Done leagues are never re-requested within the same slot.
* **Failed league:** follows the existing per-scope back-off (15 → 240 min); other
  leagues continue.
* **New slot while incomplete:** the old slot stops being current. Its sweep is
  finalised as **partial** (screener run if any of its leagues committed — §7) and
  the new slot starts from the first league: leagues refreshed for the old slot are
  refreshed again because their data predates the new slot (that is the purpose of
  the new slot).
* **Complete versus partial:**
  * **complete** — all eight leagues done for S and a `succeeded`
    `scheduler.prepare_screener` row with `args = {slot: S, kind: complete}` after
    the last league;
  * **partial** — the slot was superseded, or `partial_after` (30 min) elapsed since
    the slot's first league step, with at least one league done; a screener row with
    `kind: partial, leagues: 6/8` finalises it;
  * **in progress** — at least one league done, not yet finalised;
  * **none** — no league done.
* **Never misreported:** "complete" is derived only from the two conditions above;
  status, readiness records and `ops check` print the state and `n/8`; a partial
  sweep is a WARNING (`refresh_partial`), never INFO OK.
* **Screener follows the sweep:** the screener step is planned only when the sweep
  is complete (or being finalised as partial) and runs in the same tick when time
  allows, otherwise first in the next tick (no provider request; ≈ 1.4 s).

### 5.1 Friday timeline (trigger every 5 minutes)

With the approved planning caps (20/tick; maximum need 4 per league):

| Tick (UTC) | Work | Requests (cumulative in tick) |
|---|---|---|
| 04:15 | lifecycle (nothing live); `/status` (no fresh observation); EPL 3, Championship 3, La Liga 3, Ligue 1 3, Bundesliga 3, Serie A 3 — next league needs 4, allowance 1 → stop | 1 + 18 = 19 |
| 04:20 | PSL 2, PSL 1st Division 2 → sweep complete → screener → readiness | 4 |
| — | **04:21: READY / NOT READY on data from after Friday's provider update** | |
| 05:15 | observation fresh (headers from 04:20 are 55 min old → stale → `/status`); six leagues | 19 |
| 05:20 | two leagues, screener, readiness | 4 |
| — | **05:21: confirmation verdict; 39 minutes before the 06:00 target** | |

Worst case (every league needs 4): 04:15 four leagues, 04:20 four leagues, sweep
complete 04:21–04:25. With the **unchanged default 10/tick** the sweep spans three
ticks (04:15, 04:20, 04:25) and completes by about 04:26 / 05:26. A missed tick
moves completion by 5 minutes; a failing league is retried after 15 minutes
(04:35, 04:50 …) and the sweep becomes partial at 04:45 if still incomplete, which
`ops check` reports before the target. The 05:15 slot is the second chance; grace
slots (06:15 …) the third.

## 6. Scheduling and missed ticks

* Refresh runs only when: refresh on, provider calls on, scheduler not paused, Beta
  allowed, the week's round is absent or `draft` (stops once published or otherwise
  not a draft), now < target + grace, the store is available.
* Only the current slot is worked; earlier slots are never replayed. After an
  outage the first tick works the current slot (e.g. host back at 07:40 → slot
  07:15).
* Tue–Thu slots stay current until the next slot, so a host that was down at 04:15
  catches up at its next tick the same day.
* After target + grace: no refresh; E.1a reports *target missed* then *lapsed*; the
  operator may refresh manually.

## 7. Store consistency and readiness coordination (Clarification B)

Order and rules:

1. **Per-league refresh** commits one league atomically.
2. **Whole sweep** is complete only per §5.
3. **Screener** runs after the sweep (complete or partial-finalised), before any
   readiness evaluation that will be attributed to the sweep.
4. **E.1a readiness** (scheduler):
   * due when the 30-minute interval since the last successful evaluation has
     elapsed **or** a sweep was finalised after the last evaluation;
   * **deferred while a sweep is in progress**, but never beyond `partial_after`
     (30 min) from the sweep's first league step, after which the sweep is finalised
     as partial and readiness runs. Deferral is shorter than E.1a's freshness window
     (2 × 30 + 5 = 65 min), so no false `prepare_stale_evaluation`;
   * each record carries `data=complete@04:15` / `partial@04:15(6/8)` /
     `none` / `refresh-off`. A verdict on a partial sweep is labelled partial, never
     "refreshed".
5. **Human publication** is unchanged: `round publish` builds the snapshot once,
   shows it, requires the typed code and the fingerprint, and re-checks in its
   transaction. If an operator publishes while a sweep is in progress, the snapshot
   they confirm is exactly what is published; every quote in it still passed the
   24-hour rule. The optional `round readiness` line (§1) tells them a sweep is
   running.

**Can this be done without changing the snapshot builder? Yes.** The scheduler's
readiness never evaluates during an in-progress sweep (job-state coordination
above), and per-league atomic commits mean any reader sees whole leagues. The one
ordering hazard — fixtures of a league committed before the Screener cache is
recomputed — is resolved by step ordering, which REF-11 would not fix anyway (it is
a write-ordering issue, not a read-consistency issue). **REF-11 is therefore not
proposed.** The test matrix includes a reader-during-sweep test; if it showed a
snapshot mixing states within one league or one fixture, REF-11 would be brought
back with that evidence.

## 8. Monitoring and operator commands

* `ops status` / `jobs status` "Data refresh": current slot, sweep state and `n/8`,
  last complete sweep, last partial, failing leagues with streak, next slot,
  cooldown until, provider remaining/limit (source, age), scheduler use in 24 h by
  class against caps (results, preparation, reserve).
* `jobs tick --dry-run`: planned `prepare_refresh` leagues, `prepare_screener`, and
  readiness (with deferral reason).
* `ops jobs`: new jobs listed with existing outcome classes.
* `ops check` findings (design §10.2 without maintenance): `refresh_disabled`,
  `refresh_ok`, `refresh_partial`, `refresh_failing`, `store_not_current`,
  `provider_update_missing`, `odds_coverage_drop`, `provider_throttled`,
  `provider_quota_low`, `provider_quota_inconsistent`, `provider_limit_mismatch`,
  `budget_nonessential_exhausted`, `results_reserve_breached`; existing
  `football_store_unavailable`. Quiet before the E.1a attention window where the
  condition is normal early in the week. Webhooks stay off.
* Runbook §11 additions: Friday checklist; refresh failing / store not current
  (pause, `refresh-data --with-odds`, resume); throttled or quota low; store
  restore; "do not run bulk manual store commands Fri 03:30–12:00".

## 9. Security and static boundaries

* `refresh.py` writes only the football store and `job_runs`; it calls no
  competition service and no actor-based function.
* Static guard test (extends the E.1a one): `refresh.py` may import only
  `diski9.ingestion.*`, `diski9.odds.collect`, `diski9.screener.cache`,
  `diski9.leagues`, `diski9.db.*` (football store), `backend.jobs.{provider,locking,
  config}`, `backend.db`; it must not reference `publish_round`, `create_round`,
  `create_scheduled_draft`, `build_live_snapshot`, corrections, settlement,
  championships, accounts or authentication. `create_scheduled_draft` and
  `build_live_snapshot` remain allowed only in `prepare.py`.
* Official and Development are never refreshed (Beta only; Official not
  configurable).
* No key, header, URL or provider text in `job_runs` or output: details are
  numbers, league ids and error type names. `/status` plan name is not stored.

## 10. Failure recovery and rollback

| Failure | Result |
|---|---|
| provider error / timeout | league retryable, back-off; sweep may become partial |
| rate limit | cooldown row; no more refresh this tick; results honour cooldown |
| quota body / floor / caps | deferred, no request sent |
| auth error | blocking; WARNING/CRITICAL by proximity; a person fixes the key |
| store missing or setup incomplete | blocking (fail closed) |
| SQLite locked | retryable |
| crash after reserve / after send / during apply | counted; nothing or rolled back written; Stage D marks the step; rerun idempotent |
| lock lost | no write after the fetch; tick stops (Stage D) |

**Operational rollback:** `DISKI9_JOBS_PREPARE_REFRESH=off` (or the pause file)
stops refresh on the next tick; results and E.1a continue unchanged. **Code
rollback:** a revert restores the previous behaviour; no migration to undo; the
extra `job_runs` rows (new job names, `args.class`) are ignored by older code
(unknown jobs are not lifecycle jobs; ledger sums `api_requests` regardless of
class).

## 11. Offline test matrix

Tools: `httpx.MockTransport`, recorded fixtures/odds samples and replayed trial
files, fake clocks (wall and monotonic), fake provider, isolated PostgreSQL
(`champ_helpers.isolated_engine`), temporary SQLite stores. **No live call**
(the network is never reached: a transport that raises on any real request).

| File | Tests (≈) | Content |
|---|---|---|
| `tests/test_client_waits.py` | 8 | `max_wait_seconds`: 429 Retry-After ≤ cap waits, > cap raises with `retry_after`; minute window capped; defaults unchanged for CLI |
| `tests/test_ingest_split.py` | 6 | fetch/apply equivalence with the old combined functions; no store write lock during fetch (assert a second connection can write while the mock request blocks); `odds_fetches.retrieved_at` unchanged meaning; CLI `refresh-data` totals unchanged |
| `tests/test_refresh_slots.py` | 10 | slot lists Tue–Fri and grace; current slot; DST; ISO-year boundary; after grace none; published → none; missed ticks → current slot only |
| `tests/backend/test_backend_refresh_budget.py` | 12 | class rows; per-tick/total/nonessential/reserve; results run with nonessential exhausted; preparation never enters the reserve; pre-check of 4; pacing across two ticks and a "restart" (new process objects, same ledger); cooldown honoured by results and refresh; config validation (100 < 450 refuses refresh) |
| `tests/backend/test_backend_refresh_quota.py` | 9 | no observation → `/status` reserved as preparation; stale by age; stale across midnight UTC; lower of header/status; inconsistency noted; floor defers refresh, not results; limit mismatch stops for the provider day; `/status` failure fails closed |
| `tests/backend/test_backend_refresh_sweep.py` | 14 | sweep over 2 and 3 ticks; done leagues not re-requested (request count); failing league back-off and partial finalisation; supersession by a new slot; complete vs partial vs in-progress labels; screener after the last league; Friday timeline end-to-end with fake clock; rate limit stops remaining refresh in the tick |
| `tests/backend/test_backend_refresh_recovery.py` | 8 | crash after reserve, after send, during apply (rollback); lock lost between fetch and apply → no write; concurrent ticks; SQLite locked → retryable; interrupted during wait → Stage D marking; rerun idempotent (no duplicate fixtures or episodes) |
| `tests/backend/test_backend_refresh_readiness.py` | 8 | readiness deferred during a sweep, runs after; bounded by `partial_after`; triggered by sweep completion; `data=` labels; stale→fresh odds becomes READY only after the post-update sweep; refresh never sets READY; postponed / rescheduled / cancelled fixtures move in or out and Goal Model recomputed; refresh off → E.1a behaviour identical |
| `tests/backend/test_backend_refresh_ops.py` | 8 | findings and thresholds, quiet window, status lines, dry-run plan, `ops jobs` |
| static/security (in existing scheduler test file) | 4 | import boundary; Beta-only; no publication/round/settlement calls; no secrets in details |

≈ 87 tests. Plus the existing suites unchanged: scheduler, locking, E.1a, Stage E
admin, results, settlement, client, odds, fixtures, workflow, browser tests.

## 12. Performance and CI impact

* League step: ≤ 4 requests; worst case 4 × 2 attempts × (10 s timeout + 3 s
  pacing) + one 30 s wait = 134 s. Longest tick ≈ 240 s budget + 134 s ≈ 6.3 min,
  well below the 20-minute abandonment threshold (validated in config).
* Typical sweep: ≈ 22 requests × 3 s pacing ≈ 66 s of pacing plus ≈ 10 s of
  responses and ≈ 6 s of store writes, spread over two ticks; screener 1.4 s;
  readiness 0.15 s.
* Results imports become at most 3 s × requests slower (1–3 requests): negligible.
* CI: ≈ 87 offline tests on mocked transports and small stores; estimated **under
  60 s** added to a 29.5-minute suite (margin ≈ 9.5 min → ≈ 8.5 min). Fake clocks
  replace real sleeps (no test sleeps for pacing). The 40-minute timeout and the
  documentation-only path are unchanged.

## 13. Acceptance checklist

1. Refresh off by default; existing caps' defaults unchanged (10/tick, 100/24 h);
   enabling refresh with them is refused by validation.
2. Balanced slots exactly as approved; only the current slot runs; nothing after
   publication or the grace.
3. Fixtures and odds for all eight leagues; no standings in preparation; no
   Screener maintenance (REF-13 deferred); no thin-week rule (REF-14).
4. Existing pipeline reused; fetch-then-write; no SQLite write transaction open
   during a provider request (tested); CLI results unchanged (tested).
5. Every request (results and preparation, retries, `/status`) reserved before
   sending with its class; preparation never uses the results reserve; results run
   with preparation exhausted (tested).
6. Pacing ≥ 3 s across ticks and restarts; no wait > 30 s in a tick; cooldown
   persisted and honoured by results imports (tested).
7. Floor 2,000 with the quota-observation rules; `/status` reserved; limit mismatch
   stops preparation (tested).
8. Sweep complete/partial/in-progress derived as specified; never reported
   complete when partial; screener after the sweep; Friday timeline test passes.
9. Readiness deferred during sweeps, triggered after them, labelled with data
   state; refresh never sets READY; Stage E validator, snapshot builder and
   publication unchanged.
10. Stage D: lock, ownership checks (before every step, request and store write),
    240 s budget, 20-minute threshold, abandonment and interruption handling
    unchanged; new jobs in the recovery registry.
11. Beta only; Official impossible; Development never refreshed; static import
    boundary test passes.
12. No secrets in records or output.
13. Monitoring findings and status as specified; webhooks off.
14. Level 1 (focused), Level 2 (integration and regression on local PostgreSQL and
    the auth harness) and full GitHub CI pass with all 13 browser tests and no
    skips; migration head `app_0007`; fingerprint unchanged; configurations
    unchanged.
15. Documentation updated (scheduler, monitoring, runbook, operator guide,
    `.env.example`, implementation record); no live call made during
    implementation or tests.

## 14. Affected approved behaviour, deviations and risks

**Approved behaviour the implementation touches**

| Area | Effect | Why |
|---|---|---|
| Stage D `locking.reserve` / `allowance` | class-aware caps, pacing return value, cooldown check; lock, reservation timing and conservative counting unchanged | REF-06/07 (approved in principle) |
| Stage D `SCHEDULER_JOBS` | + two refresh jobs | recovery coverage (same as E.1a's accepted deviation) |
| Stage C/D results import | 3 s pacing; waits capped at 30 s; `Retry-After` > 30 s → retryable instead of a long sleep; honours cooldown | Clarification C requires the same protection |
| E.1a readiness | sweep-triggered and deferred during a sweep (only when refresh is on); record gains `data=` | Clarification B |
| E.1a status and `ops check` | new fields and findings | REF-15 |
| Shared ingestion functions | fetch/apply split, same committed results | REF-09 |
| Stage E `round readiness` | optional status line only (D-3) | operator awareness |

**Decisions requested with the authorisation**

* **D-1** Keep the existing cap defaults (10/100) and require explicit configuration
  of 20/450 at activation (recommended), versus changing the defaults now.
* **D-2** Ledger rows written before E.1b (no class) count as `results`
  (recommended; conservative for preparation).
* **D-3** Add the display-only refresh line to `round readiness` (recommended) or
  leave Stage E output untouched.

**Unresolved risks (unchanged from the design unless noted)**

1. Active plan, limits and at-limit billing unverified (live activation gate).
2. Provider update time measured on few days (finding `provider_update_missing`).
3. Results-import volume estimated; confirm in Stage F.
4. SQLite same-host requirement; Q-07 and the D-39 interpretation open.
5. Other consumers of the key are visible only through lagging observations.
6. CI margin narrows by about one minute.
7. A league with persistently failing odds makes Friday sweeps partial; readiness
   still decides on what is stored, and `ops check` escalates before the target.

**No migration requested.**
