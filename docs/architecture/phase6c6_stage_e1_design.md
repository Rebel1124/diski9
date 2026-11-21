# Phase 6C.6 Stage E.1 — Automated Draft Preparation: design proposal

**Status:** design **approved in principle by the owner (21 Nov 2026)** — ADP-01
to ADP-10, ADP-14 to ADP-19, ADP-21 and ADP-22 approved for E.1a; ADP-11, ADP-12,
ADP-13 and ADP-20 provisional wherever they concern automated API-Football refresh
(revisited before E.1b). **E.1a is the next implementation candidate, awaiting
authorisation**; its plan: [`phase6c6_stage_e1a_plan.md`](phase6c6_stage_e1a_plan.md).
No application code is authorised. The 78-hour preparation lead was confirmed as
consistent with the schedule (Tuesday 00:00 UTC to the Friday 08:00 SAST / 06:00
UTC target). The competition week, fixture window, publication rules, eligibility
criteria and configurations are preserved unchanged. Branch `feature/phase-6c6-operations`, baseline
`40ae07a` (Stage E closed; CI run 101). Application baseline `c49de86` (CI run 99:
1,797 passed, 0 skipped, 13 browser tests). Migration head `app_0007`; fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
`broad60-432-v1`; `points-150-75-v2`.

Notation: **[Existing]** accepted behaviour found in the code or decision
register; **[Proposed]** new behaviour needing approval; decisions are
**ADP-nn** (§13 lists them all with recommendations).

---

## 1. Current-state assessment and reusable services

### 1.1 What a "draft" is today [Existing]
A round row in `app.rounds` with `status = 'draft'`, a code, a schedule, a series
and a window — **nothing else**. There is no stored candidate pool: the snapshot
(fixtures, outcomes, prices, probabilities) is built from the football store **at
publication time** by `build_live_snapshot` and frozen by `publish_round`.
Consequences that shape this design:
* "Preparing a draft" means (a) keeping the football store fresh enough that the
  snapshot built at publication passes the rules, (b) creating the draft row, and
  (c) evaluating readiness so an operator knows what to expect.
* The 24-hour quote rule (`ConsensusRules.max_quote_age`) and the 60-minute
  snapshot construction-age limit (`DISKI9_SNAPSHOT_MAX_AGE_MINUTES`) apply at
  publication, so data must be refreshed **shortly before publication**, not when
  the draft is created.

### 1.2 Inventory
| Area | Implementation | Reuse in E.1 |
|---|---|---|
| Schedule | `app.round_schedules` `weekend` v2: timezone Africa/Johannesburg; eligible competitions 39, 40, 288, 289, 140, 61, 78, 135; window Friday 00:00 UTC → Tuesday 00:00 UTC (exclusive) of the ISO week; `publish_rule` Friday 08:00 SAST (D-11; stored, **not read by any code yet**); deadline buffer 15 min; settlement cutoff 48 h; correction window 24 h; configuration/rules/scoring versions; series `beta` | **Reuse as the authority** for windows, codes and the publication target |
| Window | `rounds.weekly_window(rule, iso_year, iso_week)`, `schedule_window(...)` | Reuse unchanged |
| Draft creation | `rounds.create_round(engine, principal, code, window_start, window_end, ...)`: needs `round.publish`; duplicate code refused; writes the row, `round_status_history` (`created`) and audit `round.create` in one transaction. CLI `round create --week` derives `{iso_year}-W{ww:02d}-weekend` | Code derivation and the transaction shape reused; **not** the human entry point (ADP-07) |
| Idempotency | `rounds.code text NOT NULL UNIQUE`; status `CHECK` includes `draft … postponed` | The idempotency key (ADP-09); no migration |
| Readiness | `rounds.publication_readiness` + `_evaluate_publication` (shared with `publish_round`; Stage E) | **The only readiness validator** (ADP-06) |
| Snapshot | `challenge.roundsheet.build_live_snapshot` (read-only; football store; strict consensus; Goal Model required; excludes kicked-off and non-`TBD/NS` fixtures) | Reuse unchanged; no second selection engine |
| Eligibility | `structured.assess_outcome`, `round_opening_report` (≥ 15 fixtures, ≥ 3 leagues, exact 4/3/2 feasibility, D-28); buckets 60–95 / 40–<60 / 20–<40 (`broad60-432-v1`); ≥ 3 bookmaker groups, quotes ≤ 24 h | Unchanged |
| Football store refresh | `workflow.refresh`: per league `ingest_fixtures` (1 request per competition-season), venue classification, `sync_standings` (tier-1 leagues, 1 each), `collect_odds` (all pages per league), then the Screener cache (`cache.refresh`, local computation) | Reuse the **same functions**, split per league into scheduler steps (ADP-11) |
| Provider client | `ApiFootballClient` (rate-limiter hook, local daily reserve 500, retryable 429/5xx); scheduler wraps it with `_ReservingLimiter` so **every request is reserved in the ledger before sending** | Reuse; same ledger and caps (ADP-12) |
| Scheduler | `jobs tick`: one-pass reconciler, session advisory lock on a dedicated connection, ownership checks before every step and request, 240 s new-step budget, 20-minute abandonment, back-off 15–240 min, streams allowlist (beta, development; Official refused), `SYSTEM` only for lock / results / settle / finalise; static test forbids `create_round`, `publish_round`, `build_live_snapshot` in `backend/jobs` | Extend with preparation steps **only after approval** (ADP-10) |
| Monitoring | `ops status/check/jobs`, `RoundFact` + `classify()` (draft → `awaiting_publication`, INFO), `job_runs` history, disabled webhook | Extend with preparation checks (ADP-17) |
| Investigation | `round readiness` (password-free, verified exposure), `round inspect`, `audit list` | Unchanged; show preparation history (ADP-15) |
| Research | D-29 collector (branch `research/weekly-pools`, captures from 26 Nov 2026, isolated from the competition database); estimate 8 fixture + ~14 odds requests per weekly capture; 7,500/day observed in the odds trial (not a confirmed entitlement) | Evidence for budgets only; **not reused as a code path** and not restarted |
| FootyStats | **no reference anywhere in the repository** (application code, tests, configuration, dependencies, documentation or commit history; searched 21 Nov 2026) | Not a provider (ADP-22) |

### 1.3 Genuinely missing
1. A rule for **which week is "upcoming"** and when its draft is due (§3).
2. A **scheduled, narrowly scoped draft-creation entry point** (§6).
3. **Scheduled football-store refresh** inside the reconciler with ledgered budgets
   (§5, §8).
4. **Recorded readiness evaluations** and derived preparation states (§9).
5. **Monitoring** relative to the publication target (§10).

### 1.4 Provider policy (owner clarification, 21 Nov 2026) [Existing decision, ADP-22]
**API-Football is the sole active football-data provider.** FootyStats is not
used. This design therefore:
1. uses API-Football exclusively for fixture discovery, match information, odds
   and every other football datum it needs (through the existing
   `ApiFootballClient` and ingestion functions);
2. introduces no FootyStats dependency, fallback or integration, and no other
   secondary provider;
3. treats any FootyStats reference as legacy, not as an active provider — the
   repository-wide search found **none** to flag (§1.2), so there is nothing to
   review or remove;
4. bases provider budgets, refresh scheduling and data-availability assumptions
   on API-Football only (§8).
A provider outage is therefore handled by retry, back-off and operator
escalation, never by switching providers (§10).

---

## 2. Recommended end-to-end architecture [Proposed]

```
 jobs tick (one pass, session lock, ownership checks)            human operator
 ───────────────────────────────────────────────────            ───────────────
 1 lifecycle steps (unchanged: lock, results, settle, finalise)
 2 preparation for the single upcoming beta week:
   a prepare.draft    — ensure the draft row exists (idempotent)
   b prepare.refresh  — football store, one league per step
                        (fixtures, odds; standings once), ledgered
   c prepare.screener — Screener cache for the window (local)
   d prepare.readiness— publication_readiness on a freshly built
                        snapshot; outcome recorded; never publishes
 3 attention notes: "draft READY for review / NOT READY: reason"
                                                         round readiness --code C
                                                         round publish --code C --operator E
                                                           (builds once, shows, types code,
                                                            publishes exactly that snapshot)
 existing lifecycle continues automatically from publication
```
* Preparation runs **after** the lifecycle steps in the same tick and shares the
  tick budget, lock, ownership checks and provider ledger. Lifecycle work is
  never delayed by preparation (ADP-10).
* **No new daemon, queue, table or migration** in the recommended scope.
* Phased activation (ADP-21): **E.1a** draft creation + readiness evaluation +
  monitoring with **provider calls off** (the store is refreshed by the existing
  manual `refresh-data --with-odds`); **E.1b** automated refresh, enabled only after
  the provider entitlement is confirmed.

---

## 3. Competition week and fixture window

### 3.1 Definitions [Existing unless marked]
| Term | Definition |
|---|---|
| **Competition week** | An ISO week (`iso_year`, `iso_week`) of the active `weekend` schedule. Identified by the round code `{iso_year}-W{ww:02d}-weekend` (ISO year, so 2026-W53 and 2027-W01 are handled by `date.fromisocalendar`). Stream: the schedule's series (`beta`). |
| **Fixture window** | `weekly_window(rule, iso_year, iso_week)`: Friday 00:00 UTC to Tuesday 00:00 UTC (exclusive). It spans the calendar boundary of the ISO week by design; a week is **not** Monday–Sunday. |
| **Publication target** | `publish_rule`: Friday 08:00 Africa/Johannesburg (06:00 UTC) of that ISO week. A target, not a guarantee (D-11). |
| **Entry deadline** | Earliest kickoff on the published sheet − 15 minutes (common deadline), fixed at publication. |
| **Settlement cutoff** | Latest kickoff on the sheet + 48 h. |
| **Earliest finalisation** | S-02: max(cutoff, last material change) + correction window (24 h). |

All stored times are UTC. The window rule is in UTC (no daylight-saving shifts);
SAST has no daylight saving; European kickoffs move by an hour in UTC across DST
but remain inside a Friday–Monday UTC window (latest Monday evening kickoffs are
around 20:00 UTC). No schedule change is proposed.

### 3.2 "Upcoming week" [Proposed, ADP-01]
The upcoming week is the earliest ISO week of the active `weekend` schedule whose
**publication target has not yet passed by more than the grace period** *and*
whose window has not started — in practice, from Tuesday 00:00 UTC (the previous
window's end) until Friday 00:00 UTC, the upcoming week is the current ISO week;
from Friday onwards preparation continues for that week until it is published or
lapses (§3.5), and the following week becomes upcoming on Tuesday 00:00 UTC.
Exactly **one** week is prepared at a time; never more than one ahead.

### 3.3 When preparation may start [Proposed, ADP-02]
| Option | Draft created | Trade-off |
|---|---|---|
| A (recommended) | when the previous window ends (Tuesday 00:00 UTC), ~78 h before the target | Visible early in `ops status`; no data dependency (a draft has no snapshot); duplicates prevented by the code |
| B | a configurable lead before the target (e.g. 24 h) | Less "empty draft" time; later warning if creation fails |
| C | only when data is fresh and readiness passes | Couples creation to provider health; a failed refresh hides the week entirely |

Recommendation **A**, with `DISKI9_JOBS_PREPARE_CREATE_LEAD_HOURS` (default 78,
bounded 6–96) so B is a configuration choice. Data refresh timing is separate
(§5.3).

### 3.4 Overlap with the previous week [Existing semantics, ADP-03]
Rounds are independent: week W may be drafted, refreshed and published while
W−1 is still settling or in its correction window (manual publication already
allows this; championship assignment waits until certain, CH-02/CH-03). The
scheduler processes lifecycle steps first in each tick, so W−1 is never delayed.
**Recommendation:** allow overlap; no new dependency.

### 3.5 Postponed, cancelled, rescheduled fixtures; thin weeks [Existing + ADP-04]
* Before publication: the builder includes only fixtures in `TBD`/`NS` with a
  kickoff inside the window and after the snapshot time; postponed (`PST`),
  cancelled and abandoned fixtures are excluded; a rescheduled fixture is judged
  by its current kickoff. **[Existing]**
* After publication: `settle/v1` (cutoff voids, D-32 rules) — unchanged.
* International breaks and thin weeks: the opening checks (≥ 15 fixtures, ≥ 3
  leagues, 4/3/2 feasibility) fail, readiness is NOT READY, nothing is published.
  **[Existing]** What happens to the draft (ADP-04):
  * **Option A (recommended for E.1): derived "lapsed".** The draft row stays
    `draft`; once the publication grace period has passed and the earliest
    in-window kickoff minus the deadline buffer is in the past (or the window has
    started with no publishable pool), monitoring reports the week as **lapsed**;
    the scheduler moves on to the next week. No state change, no migration.
  * Option B: a **human** `round postpone --code` command using the existing
    `postponed` status and `round.postpone` capability (schema already allows
    `draft → postponed` with designation basis `opening_checks`). A new
    state-changing command — separate approval; useful for a clean history.
  * Option C: the scheduler postpones automatically. **Not recommended** (a new
    `SYSTEM` state change beyond creating drafts).

### 3.6 Multiple leagues [Existing]
The schedule's `eligible_competitions` and `leagues.odds_competitions()` are the
same eight leagues today. The builder reads `odds_competitions()`. **Observation
(ADP-05):** two lists can drift; recommend that preparation refreshes exactly the
schedule's `eligible_competitions` and a startup check refuses preparation if the
two lists differ (fail closed), without changing the builder.

---

## 4. Candidate pool construction and validation

### 4.1 Existing requirements (unchanged) [Existing]
* Pool = `build_live_snapshot` output: supported leagues, upcoming fixtures in the
  window, a Goal Model forecast, strict consensus per market (1X2, BTTS, O/U 2.5;
  ≥ 3 bookmaker groups; quotes ≤ 24 h before the snapshot; margin removed).
* Buckets: Foundation 60–95 % (4 picks), Balanced 40–<60 % (3), Challenger
  20–<40 % (2); nine picks; existing virtual-credit allocation; one pick per
  fixture.
* Opening: ≥ 15 eligible fixtures, ≥ 3 eligible leagues, exact strict-portfolio
  feasibility (`round_opening_report`), D-28.
* Duplicates: the builder emits one item per fixture (odds pages deduplicated in
  `reconcile_pages`, inconsistent pagination flagged); outcomes are keyed
  (fixture, market, outcome) and validated by `assess_outcome`.
* Participants build their own nine picks; the system never selects a portfolio.

### 4.2 Validation (ADP-06)
**Recommendation:** the scheduler calls `publication_readiness` on a snapshot built
by `build_live_snapshot` — the same pair `round readiness` and `round publish` use
— and records the verdict. No second validator, no new selection rule, no AI or
model-driven selection.

### 4.3 Avoiding a technically valid but impractically narrow pool
The existing rules already prevent the narrowest cases: feasibility is an **exact
matching** (four distinct fixtures for Foundation, three for Balanced, two for
Challenger, all distinct), plus the 15-fixture and 3-league minimums. Beyond that:
* **[Proposed, monitoring only, ADP-08]** readiness records per-bucket eligible
  counts and leagues; monitoring raises an INFO/WARNING "thin pool" note when a
  bucket's eligible count is below a configurable multiple of its picks. **This
  never blocks publication**; thresholds would be owner decisions informed by D-29
  evidence (first capture 26 Nov 2026). No new minimum, quota or diversity rule is
  introduced without owner approval.

---

## 5. Scheduler integration

### 5.1 Where preparation runs [Proposed, ADP-10]
Inside `jobs tick`, after the lifecycle steps, as new steps with their own
`job_runs` jobs: `scheduler.prepare_draft`, `scheduler.prepare_refresh`,
`scheduler.prepare_screener`, `scheduler.prepare_readiness` (scope = round code,
or `football:<league>` for refresh). Same lock, ownership checks
(`TickLock.verify` before each step and each provider request), tick budget
(no new step after 240 s), back-off, pause file and stream allowlist. A separate
daemon is rejected (duplicates the Stage D guarantees).

### 5.2 Configuration [Proposed, ADP-13]
| Variable | Default | Meaning |
|---|---|---|
| `DISKI9_JOBS_PREPARE` | off | master switch, independent of lifecycle automation |
| `DISKI9_JOBS_PREPARE_STREAMS` | (empty) | allowlist; only `beta` accepted (development uses `dev-open`; `official` always refused) |
| `DISKI9_JOBS_PREPARE_CREATE_LEAD_HOURS` | 78 | when the draft row is created (§3.3) |
| `DISKI9_JOBS_PREPARE_REFRESH_LEAD_MINUTES` | 180 | first full data refresh before the publication target |
| `DISKI9_JOBS_PREPARE_ODDS_REFRESH_MINUTES` | 60 | odds-only refresh interval while the week is unpublished and inside the refresh period |
| `DISKI9_JOBS_PREPARE_MAX_REQUESTS_PER_DAY` | 60 | preparation share of the existing 24-hour cap (the global caps still apply) |
| `DISKI9_JOBS_PREPARE_GRACE_HOURS` | 6 | after the target, how long preparation keeps refreshing before the week can lapse |

Invalid values fail closed (as `load_config`); preparation needs the lifecycle
scheduler enabled; production refuses development streams.

### 5.3 Timeline for a normal week (defaults) [Proposed]
| When (UTC) | Step |
|---|---|
| Tue 00:00 | `prepare_draft`: ensure `{year}-W{ww}-weekend` exists |
| Tue–Thu, every tick | readiness not evaluated (data not yet refreshed for publication); `ops status` shows "draft prepared, refresh due Fri 03:00" |
| Fri 03:00 (target − 3 h) | `prepare_refresh` per league across consecutive ticks (≈ 4 requests per league step: fixtures 1 + odds 1–3), standings once, then `prepare_screener` |
| after refresh, each tick | `prepare_readiness` (no provider call): READY / NOT READY + reason |
| Fri 06:00 (target) | operator reviews (`round readiness`) and publishes (`round publish`) |
| Fri 06:00–12:00 (grace) if unpublished | odds-only refresh every 60 min; readiness each tick; escalation (§10) |
| after grace and earliest kickoff − 15 min passed | week **lapsed** (ADP-04); next week prepared from Tue 00:00 |

### 5.4 Retry, pause, intervention, missed ticks, crashes, concurrency
* Retry/back-off: existing `_backoff_until` per (job, scope) — 15 → 240 min.
* Pause: the existing pause file/variable stops preparation as well; operators
  keep every manual command (including `refresh-data` and `round create`).
* Operator intervention: an operator may create the draft by hand at any time;
  the scheduler then sees the code exists and records `skipped: exists (created
  by operator)`.
* Missed ticks: level-triggered — each tick recomputes what is due from the
  database and the clock; a late tick simply performs the overdue step.
* Crashes: each step is one transaction (draft) or idempotent upserts (football
  store); interrupted steps follow Stage D (`abandoned: interrupted`, 20-minute
  abandonment of other ticks' rows); provider requests already reserved stay
  counted (conservative accounting).
* Concurrency: the session tick lock admits one tick; a second is `busy`. The
  database `UNIQUE(code)` is the final guard against a concurrent human
  `round create` (§7).

The scheduler's current prohibition on creating rounds changes only with
implementation approval (ADP-07/ADP-10).

---

## 6. SYSTEM actor security design [Proposed, ADP-07]

**Problem:** `create_round` requires a person with `round.publish` (the same
capability as publication). Giving `SYSTEM` that capability, or passing `SYSTEM`
to `create_round`, would widen its powers.

| Option | Description | Assessment |
|---|---|---|
| A (recommended) | New service `rounds.create_scheduled_draft(engine, actor: System, *, schedule_code, iso_year, iso_week, job_run_id)`; accepts **only** `SYSTEM`; derives code and window from the schedule (no caller-supplied code, window, series or development flag); refuses any series other than `beta` and any `dev-` code; `INSERT … ON CONFLICT (code) DO NOTHING`; writes `round_status_history` (`created (scheduled)`, actor NULL, job link) and audit `round.create` with `actor_role = 'system'` and `job_run_id`, in one transaction | Narrowest surface; no capability granted; human `create_round` unchanged |
| B | Let `create_round` accept `SYSTEM` | Broadens a human entry point; arbitrary codes/windows reachable by the scheduler |
| C | A capability object for `SYSTEM` (`round.create_scheduled`) in the permission model | Introduces capabilities for a non-person; extends the human role model |

Guarantees of A:
* `SYSTEM` still cannot publish, lock early, correct, resolve alerts, invalidate,
  reopen, manage accounts or sign in; `publish_round`, `create_round`,
  `authenticate_operator` stay forbidden in `backend/jobs` (static test kept and
  extended: only `create_scheduled_draft`, `publication_readiness` and
  `build_live_snapshot` are newly allowed there).
* `create_scheduled_draft` refuses a `Principal` (a person uses `round create`),
  so the scheduled path cannot be used to impersonate an operator, and no password
  or token is stored for the scheduler.
* Stream isolation: series fixed by the schedule (`beta`); the existing
  `rounds_development_series` trigger and the Official refusal remain; no Official
  schedule exists (D-38).
* A draft is inert: no snapshot, not visible to participants (`current_round`,
  leaderboards and history exclude drafts), cannot accept entries.

---

## 7. Idempotency and database consistency [Proposed, ADP-09]

| Threat | Protection |
|---|---|
| Duplicate drafts for a week | Idempotency key = **round code** derived from (schedule, ISO year, ISO week); `rounds.code UNIQUE` (existing) + `ON CONFLICT DO NOTHING` |
| Concurrent workers | Session tick lock (one tick) + the unique constraint |
| Repeated ticks | Step checks "row exists" first; recorded as `skipped: exists` |
| Crash during creation | Row, status history and audit in one transaction: all or nothing |
| Existing published/locked round | Never touched: the scheduled path only inserts; any existing row (any status) means "exists" |
| Manual creation first | Same code → exists; scheduler records who created it (audit) |
| Operator "rejects" a draft | There is no reject state today. Recommended: the operator simply does not publish; the week lapses (ADP-04 A) and is never recreated (code exists). Optional later: human `round postpone` (ADP-04 B) |
| "Edits" to a draft | A draft holds no editable content (window and code are schedule-derived). Nothing to overwrite |

**No migration is required:** the existing unique constraint, status `CHECK`,
history triggers and audit constraints suffice. A published round is never
overwritten (status guard plus insert-only path).

---

## 8. Provider dependencies and proposed budgets

### 8.1 Endpoints and data [Existing functions]
| Purpose | Endpoint | Requests | Function |
|---|---|---|---|
| Fixtures and results (form inputs) | `/fixtures?league&season` | 1 per league (8) | `ingest_fixtures` |
| Pre-match odds 1X2/BTTS/O-U 2.5 | `/odds?league&season` (all pages) | ≈ 14 for 8 leagues (Phase 5A measurement) | `collect_odds` |
| Official standings (tier-1) | `/standings` | 1 per tier-1 league (6: 39, 288, 140, 61, 78, 135) | `sync_standings` |
| Results after publication | `/fixtures?ids=` (≤ 20 ids/request) | unchanged (Stage C) | `fetch_fixtures_by_ids` |
All from API-Football (ADP-22). No `/predictions`; no historical odds; no other provider.

### 8.2 Consumption per week (estimates to confirm with recorded responses)
| Step | Requests |
|---|---|
| Full refresh (fixtures 8 + odds ≈ 14 + standings 6) | ≈ 28 |
| Odds-only refresh during grace (each) | ≈ 14 |
| Worst normal Friday (full + 1 odds refresh) | ≈ 42 |
| Worst Friday with full grace (full + 6 odds refreshes) | ≈ 112 → **capped** |

### 8.3 Budgets [Proposed, ADP-12]
* All preparation requests go through the existing pre-send ledger
  (`scheduler.provider` rows) under the global caps (Stage C provisional: 10 per
  tick, 100 per rolling 24 h), plus a preparation sub-cap (default **60/24 h**) so
  results imports always keep at least 40.
* Per-tick 10 → one league step per ~4 requests, two league steps per tick; a full
  refresh takes ~4–5 ticks (~25 minutes at a 5-minute interval) — within the
  3-hour refresh lead.
* Retries: the scheduler client's 10 s timeout and 1 retry (each attempt
  reserved). Rate limits (429) and provider outages → retryable failure with
  back-off; quota exhaustion (`ApiFootballQuotaError`) stops all provider steps
  for the tick.
* Caching/reuse: the football store is the cache; a league refreshed within the
  odds refresh interval is skipped; Screener cache reused when inputs unchanged.
* These caps are **provisional** and are not a verified entitlement.

### 8.4 Provider information needed before live Beta activation (ADP-20)
1. Subscription plan name and its **daily request allowance** — owner review (21
   Nov 2026): the **Pro plan advertises 7,500 requests/day at $16/month**; confirm
   it is the active plan.
2. Per-minute rate limit and burst behaviour; behaviour when the allowance is
   exhausted (hard stop or overage charges).
3. Confirmation that **odds** (pre-match 1X2, BTTS, O/U 2.5) are included for all
   eight leagues, which bookmakers, and how far ahead of kickoff odds appear.
4. Odds update frequency (how often `update` changes) — determines the useful
   refresh interval.
5. Coverage flags for fixtures, standings and odds per league and season.
6. Terms on storing, caching and **displaying odds-derived values** to users.
7. Whether quota-free endpoints (e.g. `/status`) may be used for health checks.
8. Contact/SLA for outages (for the escalation runbook).

Design and tests use **mocked or recorded responses** (existing fake providers
and `tests/test_client.py` mock transport). No live calls; the D-29 trial is not
restarted.

### 8.5 Data-quality monitoring [Proposed]
Recorded per refresh: fixtures updated, odds fixtures collected, quotes seen,
inconsistent pagination, exclusions by reason (from the builder diagnostics).
Monitoring flags: odds collection returned zero fixtures for a league with
fixtures in the window; stale-quote exclusions dominate (the builder's existing
`stale_odds` classification); inconsistent pagination.

---

## 9. Preparation status and human publication workflow

### 9.1 Derived states (no migration) [Proposed, ADP-14]
| State | Derived from |
|---|---|
| Not prepared | no round with the upcoming code |
| Preparation in progress | a `running` `scheduler.prepare_*` row for the code (or its leagues) |
| Prepared, refresh pending | draft exists; no readiness evaluation since the refresh period began |
| Prepared, not ready | latest `scheduler.prepare_readiness` row outcome `not_ready: <problem>` |
| Ready for human review | latest readiness outcome `ready` within the last odds-refresh interval |
| Awaiting intervention | repeated failures (step streak) or NOT READY at the target |
| Lapsed | ADP-04 A conditions |
| Published | round status ≠ `draft` |
Readiness outcomes are stored in the existing `job_runs.error` prefix convention
(`ready`, `not_ready: …`) with counts in `args` at insert — allowed by
`app.run_guard`; no new columns.

### 9.2 Operator discovery and handover
* `ops status`: a "preparation" section — upcoming week, state, last refresh,
  last readiness verdict and reason, requests used.
* `jobs tick` attention notes: `beta 2026-W49-weekend: draft READY for review
  (round readiness / round publish)` or `NOT READY: <reason>`.
* `round readiness --code C` and `round inspect --code C` (unchanged commands;
  the preparation jobs appear in inspect's job list once added to the history's
  known jobs).

### 9.3 Publication boundary and revalidation (ADP-16)
* The scheduler **never publishes**; `publish_round` remains forbidden in
  `backend/jobs`.
* The scheduler's readiness verdict is **advisory**. At publication the operator's
  `round publish` builds the snapshot once from the store as it is then, shows the
  readiness summary for that snapshot, requires the round code, and publishes
  exactly that snapshot (`expected_fingerprint`); `publish_round` repeats every
  check under the round lock (Stage E standing requirement unchanged).
* Freshness: quotes must be ≤ 24 h old **at publication**; the automated refresh
  runs from target − 3 h and hourly odds refreshes continue during the grace
  period, so a publication up to the end of the grace period uses quotes well
  inside the rule. If the operator publishes much later, readiness reports stale
  quotes and refuses; the operator refreshes (`refresh-data --with-odds`) or waits
  for the next scheduled refresh.
* No path can bypass readiness, the deadline check (`deadline > now`), operator
  authentication or recency, or change a frozen snapshot.

Rejected alternative (ADP-16 B): freeze a candidate snapshot at preparation time
for later approval — needs a new table (migration), conflicts with the 60-minute
construction-age limit and creates two snapshots to reconcile.

---

## 10. Failure handling, monitoring and recovery

### 10.1 Fail-closed behaviour [Proposed]
| Failure | Behaviour | Class |
|---|---|---|
| No valid pool | readiness NOT READY with the builder's reason; nothing published | intervention at the target (WARNING); lapses if unresolved |
| Missing/stale odds | NOT READY (`stale_odds` / `missing_markets`); odds refresh retried on schedule | retryable until the grace ends |
| Provider outage / 429 | step `retryable_failure`, back-off; lifecycle unaffected; no fallback provider (ADP-22) | retryable |
| Budget exhausted (global or preparation cap) | provider steps `deferred`; no request sent; readiness still evaluated on existing data | retryable next window; WARNING |
| Database unavailable | tick exits 1 (existing); nothing written | retryable; trigger reporting |
| Lock lost | Stage D: step recorded, no further step, exit 1 | retryable; existing check |
| Conflicting manual change (operator created/published first) | `skipped: exists` / `published`; preparation stops for that week | none |
| Draft data stale before publication | readiness flips to NOT READY; hourly odds refresh during grace | retryable |
| Missed preparation deadline | escalation (§10.2); week lapses after grace and kickoff | intervention |

### 10.2 Monitoring additions to `ops check` [Proposed, ADP-17]
All relative to the schedule's own times (publication target, earliest kickoff),
configurable, fail closed; INFO is never notified; the webhook stays disabled.
| Check | INFO | WARNING | CRITICAL |
|---|---|---|---|
| Upcoming week has no draft | — | after the create lead + 1 h | 6 h before the target |
| Refresh failing (same league, consecutive) | — | 3 | 6 |
| Not ready | before the target | at the target | target + grace / 3 h before the earliest kickoff |
| Ready but unpublished | before the target + 2 h | after target + 2 h | 3 h before the earliest kickoff |
| Week lapsed | — | yes (7 days visible) | — |
| Preparation requests (24 h) | — | ≥ 80 % of the preparation cap | above the cap |
| Thin pool (ADP-08) | per-bucket margin below the configured multiple | — | — |

---

## 11. Testing and acceptance strategy (for the implementation stage)

| Area | Tests |
|---|---|
| Week identification | ISO-year boundaries (2026-W53 → 2027-W01), Tuesday/Friday transitions, one week at a time, schedule version selection, publication target from `publish_rule` (SAST), UTC window independent of European DST |
| Window boundaries | fixtures at Friday 00:00 UTC (included) and Tuesday 00:00 UTC (excluded); kickoffs before the snapshot excluded |
| Eligibility and feasibility | readiness parity with `round readiness` / `publish_round` on recorded store data; insufficient fixtures/leagues; infeasible 4/3/2; stale and missing odds |
| Provider failures | mock transport: 429, 5xx, timeouts, quota errors, inconsistent pages; each attempt reserved before sending; no request after a cap |
| Budgets | per-tick, 24 h and preparation sub-cap under concurrency; results imports keep their share |
| Idempotency/concurrency | two and four ticks; tick + concurrent human `round create`; repeated ticks; crash before/after the insert transaction |
| Crash recovery | interrupted refresh step, killed tick (Stage D abandonment), resumed next tick |
| Pause and configuration | pause file stops preparation; invalid configuration fails closed; `official` and development refused; production guard |
| Publication boundary | static test: `publish_round` and `create_round` never referenced in `backend/jobs`; publication only via `round publish` with the exact snapshot; scheduler verdict never used as approval |
| Stream isolation | beta only; no Official rows; development trigger intact |
| Audit and linkage | `round.create` by `system` with `job_run_id`; status history `created (scheduled)`; job outcomes in history and `round inspect` |
| Regression | Stage D locking suite, provider ledger tests, no premature settlement/finalisation, migration head unchanged, fingerprint unchanged |
| Acceptance | Level 1, Level 2, full GitHub CI with all 13 browser tests and zero unexpected skips |

---

## 12. Proposed implementation sequence (after approval)

1. **E.1a-1** Week calculator (pure function on the schedule) + configuration
   (`prepare_*`, fail closed) + tests.
2. **E.1a-2** `create_scheduled_draft` service (SYSTEM-only, schedule-derived,
   idempotent, audited) + static-guard update + tests.
3. **E.1a-3** Reconciler preparation steps: `prepare_draft`, `prepare_readiness`
   (no provider), attention notes; derived states in `ops status`; `ops check`
   preparation checks; history known jobs + tests.
4. **E.1a-4** Operator documentation (guide, scheduler, monitoring, runbook);
   Level 2; full CI; checkpoint.
5. **E.1b** (separate authorisation after the provider entitlement, ADP-20/21):
   `prepare_refresh` per league + `prepare_screener` through the ledger with the
   preparation sub-cap; recorded-response tests; data-quality monitoring;
   checkpoint.

Estimated scope: E.1a medium (no migration); E.1b medium.

---

## 13. Risks, assumptions and owner decisions

### 13.1 Decision register
| ID | Decision | Options | Recommendation |
|---|---|---|---|
| ADP-01 | Upcoming-week definition | §3.2 | One week at a time: the ISO week whose window has not started (from the previous window's end), continued until published or lapsed |
| ADP-02 | When the draft is created | A previous window end / B lead before target / C only when ready | **A** (configurable lead, default 78 h) |
| ADP-03 | Overlap with the previous week's settlement | allow / wait for final | **Allow** (independent rounds; lifecycle first in each tick) |
| ADP-04 | Unpublishable week | A derived "lapsed" / B human `round postpone` / C scheduler postpones | **A** in E.1; B as a later optional human command; never C |
| ADP-05 | League list authority | schedule list / leagues module | Refresh the schedule's `eligible_competitions`; refuse preparation if it differs from `odds_competitions()` |
| ADP-06 | Validator | reuse `publication_readiness` / new validator | **Reuse** (no second validator) |
| ADP-07 | SYSTEM authorisation | A dedicated SYSTEM-only service / B widen `create_round` / C SYSTEM capability | **A** |
| ADP-08 | Thin-pool safeguard | none / monitoring note / blocking rule | **Monitoring note only**; thresholds later from D-29 evidence |
| ADP-09 | Idempotency key | round code + `UNIQUE` / new key table | **Round code** (no migration) |
| ADP-10 | Integration | inside `jobs tick` after lifecycle / separate daemon | **Inside `jobs tick`** |
| ADP-11 *(provisional, E.1b)* | Refresh granularity | one league per step / whole refresh in one step | **One league per step** (fits the 10-per-tick cap and 240 s budget) |
| ADP-12 *(provisional, E.1b)* | Budgets | shared caps + preparation sub-cap 60/24 h / shared only / raise caps | **Sub-cap within the provisional caps**; revisit after ADP-20 |
| ADP-13 *(E.1a settings approved via the plan; refresh settings provisional)* | Configuration and defaults | §5.2 | As listed, off by default, `beta` only |
| ADP-14 | Preparation state | derived / new status or table | **Derived** from rounds and job runs |
| ADP-15 | Operator discovery | `ops status`, attention notes, existing `round readiness/inspect` | As proposed (no new command) |
| ADP-16 | Publication revalidation | A build at publication (existing) / B freeze at preparation | **A** |
| ADP-17 | Monitoring thresholds | §10.2 | As proposed (configurable) |
| ADP-18 | Development stream | include / exclude | **Exclude** (`dev-open` remains for development) |
| ADP-19 | Official | — | Always refused (D-38) |
| ADP-20 | Provider entitlement | §8.4 | **Recorded:** API-Football Pro plan advertises 7,500 requests/day at $16/month; no hourly or per-minute limit stated in the pricing reviewed — subject to confirmation against the active subscription and any rate-limit conditions; internal limits are not raised to 7,500 (E.1b budgets: plan Appendix A). Provisional |
| ADP-21 | Phasing | E.1a (no provider calls) then E.1b / all at once | **Phased** |
| ADP-22 | Football-data provider | API-Football only (owner clarification) | **API-Football exclusively**; no FootyStats or fallback provider; no legacy references found to review |

### 13.2 Risks and assumptions
| Item | Note |
|---|---|
| Short entry period | With Friday evening fixtures the deadline can be ~13 h after a 08:00 SAST publication (accepted D-11 semantics; unchanged). A delayed publication shortens it further; monitoring escalates. |
| Football store host | The scheduler must run where the football store (SQLite) lives and where the screener cache is computed; depends on Q-07 (host). SQLite write/read concurrency with the web app must be confirmed on the host. |
| Screener cache cost | Computing the cache inside a tick must fit the 240 s budget; to be measured in E.1b (fallback: a dedicated step per league). |
| Provider limits | Provisional; ADP-20 information required. |
| D-29 evidence | First real pools from 26 Nov 2026; thin-pool thresholds and refresh timing should be revisited once 6–8 pools exist. |
| `publish_rule` | Becomes read by code for the first time (monitoring and timing only; the rule's meaning is unchanged). |
| Lapsed drafts | Remain as `draft` rows (inert); a later `round postpone` (ADP-04 B) would tidy history. |
| Abandonment threshold | Preparation steps are bounded like lifecycle steps; the 20-minute threshold must still exceed the maximum in-flight duration (unchanged requirement). |

### 13.3 Blocking unknowns
* **For E.1a: none** (no provider calls; existing schema suffices).
* **For E.1b:** the provider entitlement (ADP-20) and the host decision (Q-07).
