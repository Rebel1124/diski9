# Phase 6C.6 Stage E.1b — Automated API-Football Data Refresh: design refinement

**Status:** **approved in principle by the owner (22 Nov 2026)**, with
clarifications. **Approved in principle:** REF-01 to REF-10, REF-15, REF-16 (Balanced
schedule; fixtures and odds for all eight leagues; no standings in preparation;
existing pipeline; fetch-then-write; resumable per-league steps in `jobs tick`;
Stage D locking preserved; class-aware budgets; planning baseline 20/tick, 450/24 h,
300 non-essential, 150 results reserve, 3 s pacing, preparation floor 2,000; refresh
off by default; human publication and competition rules unchanged). The limits are a
**planning baseline, not authorised for application or live use**. **Deferred:**
REF-11 (snapshot read transaction — only if testing justifies it), REF-12 (single-
host SQLite accepted as the proposed technical architecture for the supervised Beta
exercise; hosting Q-07 and the D-39 interpretation stay open; no host selected, D-39
not waived), REF-13 (Screener maintenance — not in the initial scope), REF-14
(simple approach, no thin-week optimisation), REF-17 (all live-activation conditions
retained; no activation authorised). **Clarifications A–D** (multi-tick sweeps,
readiness and store consistency, pacing and `Retry-After`, provider quota
observations) are resolved in the implementation plan
[`phase6c6_stage_e1b_plan.md`](phase6c6_stage_e1b_plan.md) §3, §5 and §7 (summary in
§16 below). **Implementation planning complete; implementation not authorised.**
Original status: design refinement for owner review (authorised 22 Nov 2026); no
application code, migration, provider limit, live provider call, hosting choice or
activation is part of this document.

**Baseline verified (22 Nov 2026):** branch `feature/phase-6c6-operations` at
`4612f46` (E.1a closure, documentation CI run 106 passed); E.1a application
`3ed0301` (CI run 104: 1,835 passed, 0 failed, 0 skipped, 13 browser tests);
migration head `app_0007`; quantitative fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`; configurations
`broad60-432-v1` and `points-150-75-v2`. API-Football is the sole provider (ADP-22);
no FootyStats reference exists in the repository.

**Relationship to earlier decisions.** This document refines the E.1 design
(`phase6c6_stage_e1_design.md`) where ADP-11, ADP-12, ADP-13 and ADP-20 were left
provisional for automated refresh. It does **not** overwrite them: where a REF
decision below differs from an ADP proposal (notably the 03:00 UTC refresh start in
ADP-13 and the 60/24 h preparation sub-cap in ADP-12), the REF entry says so and
the ADP text stands until the owner approves the change. All approved E.1a
behaviour (ADP-01 to ADP-10, ADP-14 to ADP-19, ADP-21, ADP-22 and the accepted
E.1a deviations) is unchanged.

**Evidence labels.** **[Code]** confirmed in the current source; **[Observed]**
measured from recorded provider responses, the football store (read on a scratchpad
copy only) or earlier verification reports; **[Assumption]** not yet verified;
**[Proposal]** new design for approval.

**Contents.** §1 current-state ingestion architecture · §2 reusable services and
gaps · §3 refresh lifecycle · §4 request costs · §5 budget scenarios · §6 rate
limits and reserves · §7 scheduler integration and recovery · §8 football store and
hosting · §9 freshness and validation · §10 monitoring and operator procedures ·
§11 security · §12 tests · §13 implementation sequencing · §14 risks, assumptions
and open questions · §15 REF decision register.

---

## 1. Current-state ingestion architecture

### 1.1 The manual refresh today [Code]

`uv run diski9 refresh-data --with-odds` → `cli.cmd_refresh_data` →
`workflow.refresh(engine, client, with_odds=True)`:

1. `missing_requirements` (refuses if `setup` has not completed; local reads only).
2. Load neutral-venue overrides and approved home grounds (repository CSV files; no
   provider request).
3. **Fixtures**, for each of the eight competitions: `ingest_fixtures(conn, client,
   cid, 2026)` — one `/fixtures?league&season` request returns the whole season;
   rows upserted with a content hash (unchanged rows untouched). One transaction per
   league.
4. Venue classification for every league (local computation, one transaction).
5. **Standings**, tier-1 leagues (39, 288, 140, 61, 78, 135): `sync_standings` — one
   `/standings` request each, all six in **one** transaction.
6. **Odds** (only with `--with-odds`), for each odds-enabled league: `collect_odds`
   — `/odds?league&season`, all pages (≈10 fixtures per page), reconciled into price
   episodes. One transaction per league. A league failure is rolled back and the
   next league continues; quota or authentication errors (`FATAL_ERRORS`) stop the
   remaining leagues.
7. **Screener cache** (`workflow._screener`): Goal Model results for fixtures in the
   next 21 days (`cache.refresh`, local computation; also records insert-only
   forecast snapshots). One transaction.

The command prints the total requests; it has no budget other than the client's own
guards (below).

### 1.2 Component audit

| Component | Purpose | Endpoint | Requests | Writes (football store) | Idempotency | Failure handling | Tests | Scheduler reuse |
|---|---|---|---|---|---|---|---|---|
| `ApiFootballClient` (`api_football/client.py`) [Code] | One HTTP client: envelope parsing, pagination, retries, quota guard, key protection | any (blocks `/predictions`) | 1 per page + retries | none | n/a | 429/5xx retried with exponential back-off and `Retry-After`; `errors.rateLimit` retried; auth, quota, response errors typed; transport errors retried; local daily-reserve guard (provider-reported remaining ≤ 500 → `QuotaGuardError`); optional per-instance request budget | `tests/test_client.py` (21) | **Yes** — already wrapped by the scheduler (`_ReservingLimiter`) |
| `RateLimiter` (`api_football/ratelimit.py`) [Code] | Client-side pacing | — | — | — | — | min 0.25 s between requests; waits for the minute window when per-minute remaining ≤ 2 | in `test_client.py` | Yes, with a slower scheduler setting (§6) |
| `ingest_fixtures` (`ingestion/fixtures.py`) [Code] | Season fixtures and results | `/fixtures?league&season` | 1 per league-season | `fixtures` upsert, `ingestion_runs` row | Yes (content hash) | exception propagates; caller's transaction rolls back | `test_fixture_ingestion.py` (12) | **Yes, after a fetch/apply split** (§2.2 G1) |
| `refresh_venue_classification` [Code] | Derived venue flags | none | 0 | `fixtures`, `team_seasons` | Yes | — | as above | Yes |
| `sync_standings` (`ingestion/reference.py`) [Code] | Display standings | `/standings?league&season` | 1 per tier-1 league | `standings_snapshots` (new snapshot only when changed), `ingestion_runs` | Yes | propagates | `test_setup_workflow.py` | Yes (optional, priority 4 — readiness never reads standings; only `app/data.py` displays them) |
| `collect_odds` / `reconcile_pages` (`odds/collect.py`) [Code] | Pre-match odds as price episodes | `/odds?league&season` (paginated) | pages per league: 1–3 observed | `odds_fetches`, `odds_fixture_observations`, `odds_quotes`, `bookmakers` | Yes: unchanged price extends the episode; an older provider snapshot never moves prices backwards (`stale_item`); duplicate items across inconsistent pages keep the newest; whole-fixture disappearance only inferred from a complete, consistent walk | propagates; per-league rollback in the workflow | `test_odds_collect.py` (13), `test_eight_league_odds.py` (9) | **Yes** — `reconcile_pages` already accepts pre-fetched pages (used for replaying saved files) |
| Screener cache (`screener/cache.py`, `workflow._screener`) [Code] | Goal Model payloads used by the Screener, Match Lab **and the live snapshot builder** | none | 0 | `screener_results` (supersede-on-change), `forecast_snapshots` (insert-only, deduplicated) | Yes (content hash) | propagates | screener tests | **Yes — required after fixtures change**: the snapshot builder excludes a fixture without an available Goal Model payload |
| `build_live_snapshot` (`challenge/roundsheet.py`) [Code] | Read-only round snapshot for readiness and publication | none | 0 | none | read-only | — | E/E.1a tests | Unchanged; authoritative validator stays Stage E |
| `results_fetch.fetch_fixtures_by_ids` [Code] | Settlement evidence by fixture ID | `/fixtures?ids=` (≤ 20 IDs) | ⌈fixtures / 20⌉ | none in the scheduler path (the scheduler passes no `football_store`) | Yes | classified by the reconciler | backend tests | Already scheduled (Stage C) |
| Scheduler ledger (`backend/jobs/locking.reserve`) [Code] | Pre-send request accounting and caps | — | — | PostgreSQL `job_runs` (`scheduler.provider`, 1 row per request) | conservative: a reserved-but-unsent request counts | `BudgetExhausted` → step deferred | scheduler tests | **Yes, unchanged in principle**; class-aware caps proposed (REF-06) |
| `monitor-odds` (`odds/monitor.py`) [Code] | Completed D-29 odds trial capture | `/odds` | 3–4 per run | files only | — | — | trial tests | **No** — not restarted, not reused |
| Match Lab / Screener web app (`app/data.py`) [Code] | Display | none | **0** | none (read-only; 5-minute in-memory TTL) | — | — | browser tests | Consumer only |

**Existing scheduling of refresh:** none. The only scheduled provider use is the
Stage C results import. E.1a preparation reads the store and never calls the
provider.

### 1.3 Provider facts on record

* **[Observed, 15 Nov 2026, `milestone1_api_football_verification.md`]** `/status`
  (quota-free): plan **Pro**, active, `limit_day` 7,500. Per-minute header
  `X-RateLimit-Limit` **300**. The daily-remaining header and `/status` usage lag by
  a few minutes; they are a safety guard, not a meter.
* **[Observed, odds trial `monitoring/odds_trial/runs.jsonl`]** the daily-remaining
  header went from 7,102 (16 Nov 21:14 UTC) to 7,497 (17 Nov 00:15 UTC): the provider
  day resets at about **00:00 UTC** (calendar day, not rolling). 16 trial runs, 3–4
  requests each, no errors.
* **[Observed, `odds_coverage_phase5a.md`]** the provider's odds `update` timestamp is
  league-wide and moved **once a day, about 02:00–03:30 UTC**. Odds appear about one
  round (≤ 7 days) ahead; the following round is patchy or stale. PSL (288) has no
  odds coverage; PSL 1st Division (289) is flagged but returned no fixtures.
  Fresh markets had 5–10 independent bookmaker groups.
* **[Assumption]** The active subscription is still Pro at 7,500/day and 300/min;
  behaviour at the limit (hard stop versus overage) is unverified; per-league odds
  update frequency beyond EPL is inferred, not measured over a full week.

---

## 2. Reusable services and identified gaps

### 2.1 Reuse (no second pipeline)

E.1b schedules the **same functions** `refresh-data --with-odds` runs: fixture
ingestion and venue classification, odds reconciliation, the Screener cache, and
(optionally) standings. It adds a scheduling layer in `backend/jobs/prepare.py`
beside the E.1a steps, the existing provider adapter and ledger, and monitoring in
the existing `ops` modules. The CLI command stays as the manual fallback and keeps
its behaviour.

### 2.2 Gaps found

| ID | Gap | Evidence | Proposed remedy |
|---|---|---|---|
| **G1** | The ingestion functions take the SQLite **write lock before their network requests**: `ingest_fixtures` inserts its `ingestion_runs` row and then calls the provider inside the caller's transaction; `collect_odds` inserts `odds_fetches` and then pages through `/odds`. A slow provider holds the store's single write lock for up to the full retry time. | [Code] `ingestion/common.ingestion_run`, `odds/collect.reconcile_pages` (`list(pages)` after the insert) | **Fetch, then apply** (REF-09): the scheduler fetches outside any transaction, verifies ownership, then applies the response in one short write transaction using the existing `store_fixtures` and `reconcile_pages` (a behaviour-preserving split; the CLI keeps calling the combined functions) |
| **G2** | A provider `Retry-After` value is honoured **without an upper bound** (`_backoff`: `delay = max(delay, float(retry_after))`). One large value would make a tick sleep past the 20-minute abandonment threshold. Pre-existing; it also affects the Stage C results import. | [Code] `client._backoff` | Cap the in-tick wait (scheduler only, e.g. 30 s); a longer requested wait ends the step as *rate limited* with back-off (REF-07) |
| **G3** | Scheduler caps are global (10/tick, 100/24 h); nothing reserves capacity for results imports against other scheduler work. | [Code] `locking.reserve` | Class-aware caps in the same serialised reservation (REF-06) |
| **G4** | No knowledge of other consumers of the shared key: the ledger counts only scheduler requests; the client's daily-reserve guard knows the provider's remaining figure only after a first response in that process. | [Code] | Preparation-specific provider floor using the most pessimistic of header, `/status` and ledger (REF-08) |
| **G5** | The snapshot builder reads the store in several statements without an explicit read transaction, so a build overlapping a refresh commit may mix pre- and post-refresh leagues. Each fixture's quotes are still consistent (one league per transaction) and freshness is checked per quote, so the result is valid but not a single point in time. | [Code] `build_live_snapshot` uses `engine.connect()` | Optional hardening: one SQLite read transaction for the build (REF-11); readiness waits for a sweep to finish (§7.3) |
| **G6** | After a fixtures update, the Screener cache must be recomputed before readiness, or a rescheduled fixture keeps a Goal Model payload computed for its old kickoff until the next cache refresh. | [Code] `cache.refresh`, `build_live_snapshot` | Screener step runs after every completed sweep and before readiness (§7.2) |
| **G7** | No refresh visibility: last successful sweep, per-league status, provider remaining, throttling. | [Code] `ops/*` | Derived refresh status and new `ops check` findings (§10), no migration |
| **G8** | Odds coverage is uneven (PSL none; Championship and some leagues patchy beyond 7 days). | [Observed] | Report coverage per league; no rule change (§9) |

No gap requires a migration: `job_runs` (PostgreSQL) plus the store's own
`odds_fetches` and `ingestion_runs` tables hold everything the design needs.

---

## 3. Proposed automated refresh lifecycle

### 3.1 What drives the timing

* **Publication freshness.** A quote is challenge-eligible only if **we observed it
  and the provider updated it within 24 hours** of the snapshot time [Code,
  `ConsensusRules`]. Because the provider updates once a day at about 02:00–03:30
  UTC [Observed], Thursday's update (≈ 03:25) is already about 26.5 hours old at
  the Friday 06:00 UTC target. **Publication therefore needs a refresh after
  Friday's provider update.** A refresh at 03:00 UTC (the ADP-13 proposal of
  target − 3 h) would usually fetch Thursday's data and leave the round NOT READY
  (`stale_odds`). The first publication refresh should run **after about 04:00
  UTC**.
* **Early warning.** A thin week (international break, cup weekend, missing odds) is
  visible from Tuesday once fixtures and odds for the window are in the store; E.1a
  readiness already evaluates every 30 minutes but has nothing current to evaluate
  until the store is refreshed.
* **Cost is small** relative to the allowance (§5), so reliability, not quota,
  sets the schedule; caps exist to stop runaway use and protect results imports.
* **Deadlines are separate.** The refresh schedule never changes the entry deadline
  (earliest kickoff − 15 min), the settlement cutoff (latest kickoff + 48 h) or the
  correction window. Refresh stops when the round is published; the published
  snapshot is immutable.

### 3.2 Recommended schedule (Balanced, REF-01/REF-03)

All times UTC; "sweep" = fixtures + odds for every odds-enabled league, then the
Screener cache, then readiness.

| When | What | Purpose |
|---|---|---|
| Tue 00:00 | E.1a draft creation (unchanged) | — |
| **Tue, Wed, Thu 04:15** | daily sweep (fixtures + odds) | fixture discovery, odds as they appear, early readiness signal (NOT READY stays quiet until the attention window, E.1a) |
| **Fri 04:15** (target − 1 h 45) | **publication sweep** | first data after Friday's provider update |
| **Fri 05:15** (target − 45 min) | confirmation sweep | picks up a late provider update; newest observations at publication |
| Fri 06:00–12:00 (grace), only while unpublished | sweep every 60 minutes (06:15 … 11:15) | late provider data, delayed publication |
| after publication | **no further preparation refresh** for that week | snapshot immutable |
| after the grace (12:00) if still unpublished | automated refresh stops; E.1a reports *target missed* then *lapsed* | prevents open-ended spend; the operator may still run `refresh-data --with-odds` and publish manually while the deadline allows |

Standings are **not** part of a preparation sweep (readiness never reads them).
They belong to the optional Screener maintenance refresh (REF-13).

### 3.3 Answers to the lifecycle questions

* **Fixture discovery:** Tuesday 04:15 (after draft creation and the day's provider
  update); fixtures are refreshed in every sweep (8 requests) so kickoff changes and
  postponements are picked up up to the last sweep before publication.
* **Full versus incremental:** each sweep is "full" for what readiness needs
  (current-season fixtures for 8 leagues + all odds pages). True incrementality is
  already in the storage layer (content-hash upserts, price episodes); requesting
  fewer endpoints would save little (§4) and risk missed changes (REF-02).
* **Odds cadence and intensification:** once a day Tue–Thu (the provider updates
  once a day, so more would mainly re-read identical data); twice before the
  target on Friday; hourly in the grace. More frequent refresh (Intensive, §5) is
  available by configuration but not recommended for the first Beta week.
* **Grace period:** hourly sweeps while unpublished; readiness after each sweep and
  every 30 minutes.
* **After publication:** none for preparation. Screener and Match Lab freshness
  after publication is a separate, optional maintenance refresh (REF-13).
* **Delayed publication:** covered until the grace ends; afterwards manual.
* **Limited fixtures or odds:** no special rule; readiness reports the existing
  reason (`opening_checks`, `missing_markets`, `stale_odds`). Optional economy
  (REF-14): skip grace sweeps when the window has fewer fixtures than the existing
  opening minimum, since odds cannot add fixtures.
* **Missed ticks:** schedule *slots* are evaluated against the clock each tick; only
  the **latest due slot** runs (no backlog replay). If the host was down from 04:00
  to 07:00 on Friday, the 07:15 grace slot is the next one run.

---

## 4. Provider request-cost analysis

### 4.1 Observed costs per endpoint [Observed unless marked]

| Operation | Requests | Source |
|---|---|---|
| Fixtures, one league-season | 1 | `ingestion_runs` (50 runs, 1 request each); verification report |
| Fixtures, 8 leagues (current season) | **8** | as above |
| Odds, one league | 1–3 pages (10 fixtures per page) | `odds_fetches`: EPL 2–3, Championship 2, La Liga 2, Ligue 1 2, Bundesliga 2, Serie A 2, PSL 1 (empty), PSL 1st Div 1 (empty) |
| Odds, 8 leagues | **14** typical (measured 17 Nov 2026 21:12; 5 s elapsed) | `odds_fetches`, `odds_coverage_phase5a.md` |
| Standings, 6 tier-1 leagues | 6 | `ingestion_runs` |
| Screener cache (252 fixtures) | 0 (1.2–1.4 s local) | measured on a scratchpad copy of the store, 22 Nov 2026 |
| Readiness evaluation | 0 (0.11–0.16 s) | E.1a measurement |
| `/status` | 0 against the provider quota (counted as 1 in our ledger, conservatively) | verification report |
| Results import, one round | ⌈relevant fixtures / 20⌉ = 1–3 | Stage C design and code |

### 4.2 Derived sweep costs

| Sweep | Typical | High [Assumption] | Worst [Assumption] |
|---|---|---|---|
| Fixtures (8) + odds | **22** (8 + 14) | 28 (odds 20: two rounds listed in several leagues, EPL 3 pages) | 32 (odds 24: PSL and PSL 1st Division gain coverage, 2 pages each) |
| Per-league step (fixtures + odds of one league) | 2–3 | 4 | 4 |
| Standings (maintenance only) | 6 | 6 | 6 |

### 4.3 By league (typical sweep)

| League | Fixtures | Odds pages | Step total |
|---|---:|---:|---:|
| EPL (39) | 1 | 2 (3 when ≥ 21 fixtures listed) | 3 (4) |
| Championship (40) | 1 | 2 | 3 |
| La Liga (140) | 1 | 2 | 3 |
| Ligue 1 (61) | 1 | 2 | 3 |
| Bundesliga (78) | 1 | 2 | 3 |
| Serie A (135) | 1 | 2 | 3 |
| PSL (288) | 1 | 1 (empty) | 2 |
| PSL 1st Division (289) | 1 | 1 (empty) | 2 |
| **Total** | **8** | **14** | **22** |

### 4.4 Retry overhead

The trial and the eight-league collection recorded **no errors** [Observed]. The
scheduler's client allows one retry per request (each attempt reserved), so the
budget allows **25 %** retry overhead; a provider outage that would exceed it is
stopped by back-off and caps (it must not turn into a retry storm).

### 4.5 Results imports (for the reserve)

A weekend round polls only fixtures selected in locked entries, from 30 minutes
before kickoff until stable 6 hours after the final whistle, at most hourly per
round [Code]. Estimate: Friday evening ~6 imports, Saturday and Sunday ~14 each,
Monday ~6, plus the full re-check before finalisation; at ≤ 3 requests each:
**≈ 45 on the peak day, ≈ 125 per week** [Assumption, to confirm in Stage F]. Manual
`results import` / `results correct` by an operator use their own client and do not
spend the scheduler ledger, but they do spend the provider allowance (covered by the
provider floors in §6).

---

## 5. Budget scenarios

All figures are **preparation** requests at typical cost unless stated; "worst
Friday" assumes publication is delayed through the whole grace. Results imports are
shown separately.

| | **Conservative** | **Balanced (recommended)** | **Intensive** |
|---|---|---|---|
| Tue–Thu | Wed 04:15 only | 04:15 daily | 04:15 and 16:15 daily |
| Friday before target | 04:15, 05:15 | 04:15, 05:15 | 03:45, 04:15, 04:45, 05:15, 05:45 |
| Grace (unpublished) | every 2 h (07:15, 09:15, 11:15) | every 60 min (06:15–11:15) | every 30 min (06:15–11:45) |
| Tue–Thu requests | 22 | 66 | 132 |
| Friday, normal (published on time) | 44 | 44 | 110 |
| Friday, worst (full grace) | 110 | 176 | 374 |
| **Peak daily (worst Friday, +25 % retries)** | 138 | **220** | 468 |
| **Weekly, normal** | 66 | **110** | 242 |
| Weekly, worst | 132 | 242 | 506 |
| Peak per tick (20/tick cap) | ≤ 20 | ≤ 20 | ≤ 20 |
| Worst Friday at high cost (×28/22, +25 %) | 175 | 280 | 595 |
| Results imports, peak day / week | 45 / 125 | 45 / 125 | 45 / 125 |
| Screener maintenance (optional, REF-13) | 0 | ≤ 50/day | ≤ 50/day |
| Worst rolling 24 h, all scheduler use (+25 %) | ≈ 190 | **≈ 300** | ≈ 560 |
| **Headroom against 7,500/day** | 97.5 % | **96 %** | 92.5 % |
| Freshness at publication | one sweep after the provider update, one confirmation | same, plus hourly grace | many re-reads of identical data |
| Risk | a late provider update is caught only every 2 h | balanced | spend without a freshness gain (daily provider update) |

**Impact of Screener and Match Lab.** The web app makes **no** provider requests;
it reads the store. Its freshness is a by-product of preparation sweeps Tue–Fri. If
the owner wants Screener odds kept fresh Saturday–Monday, the optional maintenance
refresh (REF-13: one sweep plus standings per day, ≈ 28/day, capped at 50) is a
separate, lower-priority class.

**Other consumers of the same key.** Manual CLI use (`setup` ≈ 400 requests from
scratch [Observed: 7,102 remaining after the initial setup day], `refresh-data`
≈ 28, `collect-odds` 14, manual results commands 1–3), the approved but inactive
D-29b research collector (≈ 40–50/week per its proposal) and development work. The
D-29 odds trial is complete and is not restarted.

**Behaviour when the provider reports less remaining than expected** (e.g. 1,500
remaining on Friday 04:00 while our ledger shows 30 used): another consumer used the
key. Preparation defers (WARNING, §10); results imports continue down to the
existing client reserve; CRITICAL if the remaining figure could not cover the
projected results need of an active round (§6.3).

### 5.1 Recommended caps (REF-05, Balanced)

| Cap | Current (Stage C, provisional) | Proposed | Basis |
|---|---|---|---|
| Scheduler total, rolling 24 h | 100 | **450** | worst rolling 24 h ≈ 300 + margin; 6 % of 7,500 |
| Non-essential (preparation + maintenance), rolling 24 h | — (shares 100) | **≤ 300** | worst Friday at high cost with retries ≈ 280 |
| of which Screener maintenance | — | ≤ 50 | REF-13 |
| **Results reserve** (never available to non-essential work) | — | **≥ 150** (= 450 − 300) | ≈ 3 × the estimated peak results day incl. retries |
| Per tick | 10 | **20** | a sweep completes in two ticks; in-flight bound stays well under 20 min (§7.4) |
| Pacing (scheduler requests) | 0.25 s minimum interval | **≥ 3 s** (≤ 20/min) | 7 % of the observed 300/min; a 22-request sweep paces in ≈ 66 s |
| Provider floor for preparation (reported daily remaining) | client reserve 500 | **≥ 2,000** | leaves 5,500/day to every other consumer before preparation stops |
| Provider floor for results | client reserve 500 | **unchanged (500)** | do not weaken |

These numbers are **proposals**. The earlier hypothesis in the E.1a plan (Appendix
A: 600/day, 30/tick, 300 preparation, ≥ 300 results, ≤ 10/min) is superseded only
if the owner approves REF-05; the Intensive scenario corresponds to it.

---

## 6. Rate-limit and reserve strategy

### 6.1 Existing client behaviour [Code]

| Situation | Behaviour today |
|---|---|
| HTTP 429 | retried (scheduler: 1 retry) after `max(2 s × 2^attempt, Retry-After)` — **unbounded** (G2); then `ApiFootballRateLimitError` → reconciler *retryable* with back-off |
| Body `errors.rateLimit` (HTTP 200) | retried after ≥ 60/minute-limit × 10 s (2 s at 300/min); then rate-limit error |
| Rate-limit headers | daily limit/remaining kept across responses; per-minute remaining ≤ 2 → wait for the minute window (≤ 60 s) |
| Daily remaining ≤ reserve (500) | `QuotaGuardError` before sending → reconciler *deferred* |
| Body `errors.requests` (quota) | `ApiFootballQuotaExceededError` → *deferred*; stops remaining leagues in the CLI |
| Timeout / transport error | retried; then *retryable* |
| 5xx / maintenance | retried; then *retryable* with back-off (15 → 240 min) |
| Authentication / subscription error | `ApiFootballAuthError` → *blocking* (needs a person) |
| Messages | reduced to the error type in `job_runs`; no provider text, key or URL is logged |

### 6.2 Proposed pacing (REF-07)

* The scheduler's refresh requests use a **3-second minimum interval** and a
  per-minute floor of **30** (wait for the window when the provider says fewer than
  30 remain this minute), so other users of the key keep most of the minute
  allowance. This does not rely on the unverified 300/min figure: at 20/min the
  scheduler stays below any plausible paid-plan limit, and the 429 path remains the
  backstop.
* **Bounded waits.** Inside a tick the client never sleeps more than **30 s** for one
  retry (`Retry-After` above that ends the step as *rate limited*, no retry in the
  tick, normal back-off). This keeps the in-flight bound (§7.4) and also fixes G2
  for results imports.
* A rate-limit outcome on any refresh step stops **all further refresh steps in that
  tick** (not results imports, which keep their own handling).

### 6.3 Quota protection and priorities (REF-06, REF-08)

Priorities, enforced at reservation time in the existing serialised ledger
transaction:

1. **Results imports and settlement-critical checks** (`results`, `results_full`):
   may use the whole scheduler cap; only the existing client reserve (500) applies.
2. **Corrections and recovery:** human commands outside the scheduler ledger; their
   capacity is protected by the provider floors (preparation stops at 2,000
   remaining, leaving ≥ 1,500 above the results reserve for people).
3. **Weekly Challenge preparation:** allowed only while (a) non-essential use in 24 h
   + need ≤ 300, (b) total + need ≤ 450 − 150 reserve, (c) the provider-reported
   remaining (most pessimistic source) ≥ 2,000 + need.
4. **Optional Screener maintenance:** as 3, plus its own ≤ 50 sub-cap; never runs on
   Friday 03:00–12:00 (the publication window).

A preparation step needing more than the remaining allowance is **not started**
(*deferred: provider budget*), exactly as the Stage C results import behaves. It
never borrows from the reserve.

**Why partitions rather than shared limits.** With one shared cap, a grace period of
hourly sweeps could consume the cap just before Friday-evening kickoffs and defer
the first results imports. A reserve enforced inside `reserve()` (the request class
recorded in each new ledger row's existing `args` JSON, and one extra `FILTER` on it
in the cap check; no migration) makes
starvation impossible by construction. It changes the ledger's cap check, not the
lock, the reservation timing or the conservative counting (REF-06 needs explicit
approval because it touches a Stage D function).

### 6.4 Conflicting and shared quota information

| Source | Strength | Use |
|---|---|---|
| Scheduler ledger | exact for the scheduler, blind to others | caps |
| Response header `x-ratelimit-requests-remaining` | all consumers, lags minutes, only after a request | floors, after each response |
| `/status` (quota-free) | all consumers, lags minutes | one pre-flight per sweep (REF-08) |

Rule: use the **lowest** remaining figure available; if the reported **daily limit**
is below the expected 7,500 (plan change), preparation stops for the day and `ops
check` raises CRITICAL; if header and `/status` disagree by more than 10 %, record a
WARNING and continue with the lower value.

### 6.5 Crash cases

| Case | Outcome |
|---|---|
| Reserved, crashed before sending | counted as spent (conservative, unchanged); the step row is marked interrupted/abandoned by the Stage D rules; the next due tick reruns it |
| Sent, crashed before processing the response | counted; nothing written to the store (the apply transaction never started); rerun is idempotent |
| Crashed during the apply transaction | SQLite rolls the transaction back (WAL); the league is unchanged and rerun later |
| Lock lost between fetch and apply | ownership re-verified before applying; on failure the response is discarded, nothing is written, `LockLost` stops the tick (Stage D behaviour) |
| Two ticks overlap | impossible to run steps concurrently (session advisory lock); a second tick records *another tick is running* |

---

## 7. Scheduler integration and recovery

### 7.1 Placement [Proposal, REF-10]

No new daemon. Refresh runs inside `diski9 jobs tick`, in E.1a's preparation phase,
after the lifecycle loop (so results imports for live rounds get first use of the
tick's requests) and after draft creation:

```
tick (session advisory lock, ownership verified before every step and request)
 ├─ lifecycle: lock → results → settle → finalise           (unchanged)
 └─ preparation (E.1a + E.1b), Beta only, when enabled
     ├─ draft creation                                         (E.1a, unchanged)
     ├─ refresh: one step per league while the slot is due     (E.1b)
     ├─ screener: after the last league of a sweep             (E.1b, no provider)
     └─ readiness: after a completed sweep, or every 30 min    (E.1a, refined)
```

### 7.2 Steps and records (no migration)

| Job (`job_runs.job`) | Scope | Provider | Writes |
|---|---|---|---|
| `scheduler.prepare_refresh` | `<week code>:<league id>` | 2–4 requests (fixtures + odds of one league) | football store: one short transaction per league |
| `scheduler.prepare_screener` | `<week code>` | none | football store: Screener cache |
| `scheduler.prepare_readiness` | `<week code>` | none (unchanged) | none |
| `scheduler.provider` (ledger) | step scope; `args.class` = `results` / `preparation` / `maintenance` | — | PostgreSQL, before every request |

Both new jobs join the Stage D interruption/abandonment registry (as the E.1a jobs
did). Step details use E.1a's compact encoding in the existing column (league,
fixtures inserted/updated, odds pages, fixtures collected, provider update seen,
daily remaining/limit, elapsed). A **sweep** is complete when every odds-enabled
league has a successful `prepare_refresh` after the slot time and the screener step
has succeeded after the last of them.

### 7.3 Slot logic

* Slots are computed from the configured schedule and the week (E.1a week
  calculator). A slot is due when `now ≥ slot` and no complete sweep started after
  the slot. Only the latest due slot counts; an unfinished earlier slot is
  superseded.
* Leagues are processed in a fixed order; a league already refreshed after the slot
  is skipped (resumable across ticks).
* A league step that fails (retryable) follows the existing back-off; the sweep
  continues with the other leagues; readiness then evaluates what the store holds
  (a *partial sweep* is reported, §10).
* Readiness runs when its 30-minute interval has elapsed **or** a sweep has
  completed since the last evaluation; while a sweep is in progress it waits (up to
  30 minutes after the sweep started), so it does not evaluate a half-refreshed
  store.
* Preparation refresh is skipped when: refresh is off, provider calls are off, the
  week is published, the grace has ended, the stream is not Beta, the scheduler is
  paused, or the football store is unavailable (fail closed, as E.1a).

### 7.4 Timing within a tick

* Network work is small: a league step is ≤ 4 requests at ≥ 3 s pacing ≈ 12–20 s;
  a whole sweep ≈ 66–90 s plus ≈ 5 s of store writes and 1.4 s of Screener cache. It
  would fit one tick's time, but the per-tick cap (20) splits it over **two ticks**
  (≈ 5 minutes with the suggested trigger), which is intended: it bounds each tick.
* Like E.1a readiness, a refresh step starts only if the tick has enough time left
  (configured minimum, default 60 s, or twice the slowest recent league step).
* **In-flight bound** (must stay below the 20-minute abandonment threshold): worst
  league step = 4 requests × 2 attempts × (10 s timeout + 3 s pacing) + one capped
  30 s retry wait + 60 s minute-window wait ≈ 3.5 min; with the 240 s budget the
  longest tick is ≈ 7.5 min. No change to the Stage D thresholds is needed.
* No database write transaction is open during a network request: PostgreSQL
  (ledger) transactions are per request and short; SQLite writes happen after the
  fetch (REF-09).

### 7.5 Preserved

One-pass execution; session-level advisory lock on a direct/session connection;
ownership checks before every step, request and store write; 240 s budget; 20-minute
abandonment; pause and disabled-by-default switches; Development/Beta/Official
isolation (refresh is Beta-only, Official impossible by configuration); pre-send
reservation; back-off. **No Stage D locking change is proposed.**

### 7.6 Configuration (proposed names; all off or conservative by default)

| Variable | Default | Meaning |
|---|---|---|
| `DISKI9_JOBS_PREPARE_REFRESH` | off | E.1b master switch; requires `DISKI9_JOBS_PREPARE` and `DISKI9_JOBS_PROVIDER_CALLS` |
| `DISKI9_JOBS_PREPARE_REFRESH_DAILY` | `04:15` | Tue–Thu daily sweep time (UTC) |
| `DISKI9_JOBS_PREPARE_REFRESH_PUBLICATION` | `04:15,05:15` | Friday sweeps before the target (UTC) |
| `DISKI9_JOBS_PREPARE_REFRESH_GRACE_MINUTES` | 60 | grace sweep interval (15–240) |
| `DISKI9_JOBS_MAX_REQUESTS_PER_DAY` | 100 → **450** (REF-05) | total scheduler cap |
| `DISKI9_JOBS_MAX_REQUESTS_PER_TICK` | 10 → **20** (REF-05) | per tick |
| `DISKI9_JOBS_NONESSENTIAL_REQUESTS_PER_DAY` | 300 | preparation + maintenance |
| `DISKI9_JOBS_MAINTENANCE_REQUESTS_PER_DAY` | 50 | optional Screener maintenance |
| `DISKI9_JOBS_PREPARE_PROVIDER_FLOOR` | 2000 | least provider-reported daily remaining for preparation |
| `DISKI9_JOBS_PROVIDER_MIN_INTERVAL_SECONDS` | 3 | scheduler pacing |
| `DISKI9_JOBS_MAINTENANCE` | off | REF-13 |

Validation follows the existing fail-closed `ConfigError` pattern; the caps must
satisfy reserve ≥ 100 and the in-flight bound against `abandon_after`.

---

## 8. Football-store consistency and hosting

### 8.1 Findings [Code]

* **Technology:** SQLite file at `DISKI9_DATABASE_URL` (default
  `sqlite:///data/diski9.sqlite`; 37 MB today), opened with `foreign_keys=ON` and
  `journal_mode=WAL`; Python's default 5-second busy timeout; alembic migrations
  separate from the competition database. D-39: stays SQLite throughout Phase 6C;
  migration to PostgreSQL is a separate approved task before hosted deployment.
* **Web app:** read-only (`ScreenerData`, 5-minute in-memory cache); never writes.
* **Writers:** manual CLI commands; with E.1b, the scheduler. The scheduler's results
  import does **not** write the store.
* **Concurrency:** WAL lets readers proceed during a write; one writer at a time. A
  second writer waits up to 5 s and then fails with *database is locked*.
* **Atomicity:** each league's fixtures or odds update is one transaction; the
  Screener cache is one transaction. A crash leaves complete leagues or none.
* **Partial refresh visibility:** readers see each committed league as soon as it is
  committed. Mixed leagues are valid data (each quote carries its own freshness),
  but a reader can see new fixtures before the Screener cache is recomputed (G6).
  E.1b orders screener before readiness and makes readiness wait for a sweep;
  REF-11 optionally makes the snapshot build a single point-in-time read.
* **Same host required:** SQLite WAL needs the processes on **one machine with a
  local disk** (shared memory index; network file systems are unsafe). The
  scheduler (writer), the web app (reader) and `round readiness/publish` (readers)
  must therefore run where the file is. The competition database (PostgreSQL) can be
  remote.
* **Corruption and recovery:** WAL with local disk is robust to process crashes;
  risks are disk loss and copying a live file without the WAL. The store can be
  rebuilt with `setup` (≈ 400 requests) and a sweep, except historical odds
  episodes (never backfilled) — those matter for research, not for published
  rounds, whose snapshots live in PostgreSQL.

### 8.2 Requirements for the genuine Beta week (REF-12)

1. Scheduler trigger, web app and football store on **one always-on host** with a
   persistent local disk; PostgreSQL reachable over a direct or session connection
   for the tick lock.
2. Manual store writers (`refresh-data`, `collect-odds`, `setup`) are not run during
   Friday 03:30–12:00 while automated refresh is on; if one must run, pause refresh
   first (`DISKI9_JOBS_PAUSE_FILE` or turn the switch off). A collision is safe
   (one side gets *database is locked* → retryable) but wastes requests.
3. Daily online backup (`sqlite3 … ".backup"` or `VACUUM INTO`) before Tuesday's
   sweep, kept 7 days; restore drill as part of Stage F.
4. Disk space: ≈ 40 MB today, growing with odds episodes (≈ 1,000 quotes per league
   sweep, mostly *unchanged* updates, so growth is slow).

### 8.3 Practical hosting options (comparison only; Q-07 stays open)

| Option | Fit | Concerns |
|---|---|---|
| A. One small always-on VM (systemd timer every 5 min, web app, SQLite on local disk; hosted PostgreSQL) | meets every requirement directly; closest to the documented cron example | OS patching and backups are ours |
| B. Container platform with one instance and an attached persistent volume, cron in the same instance | workable if strictly one instance and the volume is local block storage | platform restarts, scheduled-job support and single-instance guarantees vary |
| C. Migrate the football store to PostgreSQL first | removes the same-host constraint; aligns with D-39 before *launch* | a separate approved project (schema, migrations, ingestion, tests); not needed for one Beta week |
| D. The owner's own always-on computer | zero cost; acceptable for a supervised exercise | uptime, sleep, network; not a production pattern |
| (Not suitable) Claude Code cloud sessions | — | ephemeral containers; the trial-style scheduled task is not a host |

Recommendation: the existing SQLite approach is **sufficient** for the Beta week on
a single host (A, B or D); no migration or storage replacement is needed for E.1b.
Whether a hosted Beta week counts as the "hosted deployment" that D-39 ties to the
PostgreSQL migration is an owner decision (REF-12, Q-07).

---

## 9. Data freshness and validation

* **Authoritative:** the Stage E readiness validator and `round publish`'s in-
  transaction re-check. A completed sweep is **never** treated as READY; it only
  triggers an evaluation.
* **Unchanged rules:** 24-hour quote rule (our observation and provider update),
  ≥ 3 bookmaker groups, snapshot construction age ≤ 60 min, bucket bands, 4/3/2
  feasibility, ≥ 15 fixtures and ≥ 3 leagues, fixture window and statuses.
* **Kickoff changes / postponements / cancellations:** fixtures are refreshed in
  every sweep; a postponed or cancelled fixture leaves `UPCOMING_STATUSES` and drops
  out of the snapshot; a moved kickoff inside or outside the window changes
  membership; the screener step recomputes affected Goal Model payloads before
  readiness. After publication, the existing settlement rules apply (no change).
* **Missing bookmaker groups / missing or stale odds:** reported by the existing
  exclusion reasons (`no_prices`, `stale_provider_update`, too few groups …).
* **Inconsistent provider data:** existing handling (inconsistent pagination →
  status `inconsistent`, no whole-fixture disappearance inferred; older provider
  snapshots never move prices backwards). Reported per league.
* **Store currency (new, derived, read-only):** per league — last successful
  fixtures ingest, last complete odds fetch, newest provider `update` seen and
  whether it is from **today** (UTC), fixtures in the window, fixtures with odds,
  challenge-eligible fixtures; for the store — last complete sweep and last screener
  refresh. The store is *current for publication* when a sweep completed after
  today's provider update for every league that has window fixtures and odds
  coverage.
* **League coverage:** PSL and PSL 1st Division currently contribute no odds; the
  opening checks already require ≥ 3 leagues from the remaining six.

---

## 10. Monitoring and operator procedures

### 10.1 Status (`ops status`, `jobs status`, `jobs tick --dry-run`)

A "data refresh" block under the E.1a preparation section: next slot, current sweep
(n of 8 leagues), last complete sweep, last failure, provider remaining/limit (most
pessimistic, with source and age), scheduler use by class in 24 h against caps, and
store currency per league. `ops jobs` already lists the new job types with outcome
classes.

### 10.2 Proposed `ops check` findings (REF-15)

Quiet before the E.1a attention window (3 h before the target) for anything that is
normal early in the week.

| Finding | Severity | Condition | Operator action |
|---|---|---|---|
| `refresh_disabled` | INFO | preparation on, refresh off | refresh manually before publication |
| `refresh_ok` | INFO | last sweep complete | — |
| `refresh_partial` | WARNING | a sweep incomplete 30 min after its slot | `ops jobs --failed`; wait for the next slot or refresh manually |
| `refresh_failing` | WARNING; **CRITICAL** inside 60 min of the target | same league step failed twice in a row | check provider status, network, store availability |
| `store_not_current` | WARNING at target − 90 min; **CRITICAL** at target − 30 min | no complete sweep after today's provider update | manual `refresh-data --with-odds`, then `round readiness` |
| `provider_update_missing` | WARNING at target − 60 min | today's provider `update` not seen for leagues with window fixtures | wait for a grace sweep; consider delaying publication |
| `odds_coverage_drop` | WARNING | a league with provider coverage and ≥ 3 window fixtures returned no odds fixtures | inspect `odds-coverage`; readiness decides |
| `provider_throttled` | WARNING; CRITICAL after 3 consecutive sweeps | 429 or rate-limit body in the last 24 h | check other consumers of the key |
| `provider_quota_low` | WARNING below the preparation floor (2,000); **CRITICAL** below 500 + projected results need while a round is live | lowest reported remaining | stop manual bulk commands; preparation already deferred |
| `provider_limit_mismatch` | CRITICAL | reported daily limit < expected 7,500 | verify the subscription (owner) |
| `budget_nonessential_exhausted` | WARNING | non-essential cap reached | expected only in long grace periods |
| `results_reserve_breached` | CRITICAL | results deferred while non-essential use > 0 in 24 h | should be impossible; escalate |
| `football_store_unavailable` | WARNING; CRITICAL inside the attention window | store missing/unreadable (existing E.1a check) | restore from backup or rebuild |

Webhook notifications stay **off** (Q-08). No finding resolves an alert or changes a
round automatically.

### 10.3 Runbook additions (to write at implementation)

1. **Friday morning checklist:** `ops check` → `round readiness` → publish (Stage E)
   — unchanged; the store is now refreshed for you.
2. **Refresh failing / store not current:** pause refresh, run `refresh-data
   --with-odds` manually, resume.
3. **Throttled / quota low:** identify other consumers; never raise caps as a fix
   without owner approval.
4. **Store damaged:** restore the latest backup; else `setup` (≈ 400 requests) and a
   manual refresh.

---

## 11. Security boundaries

* Refresh writes **only football data** (the SQLite store) and its own `job_runs`
  rows. It calls **no competition service**: no round creation beyond E.1a's
  `create_scheduled_draft`, no publication, entry, account, role, correction,
  settlement override or Official path. The static guard test is extended so the
  refresh code may import only the ingestion, odds, Screener cache and provider
  modules (plus E.1a's allowed services), never `publish_round`, `create_round`,
  corrections or account services.
* `SYSTEM` gains **no new permission**: football-store writes are not competition
  state and need no actor; the step rows identify the scheduler and its run token.
* Credentials: the API key comes from the environment or the network proxy; the
  client never logs it (`__repr__` masks it); error details are reduced to type
  names; the store path and database URLs are never printed by the new code.
  `/status` responses (plan name and usage) may be logged as numbers only.
* S-07 protections, audit attribution and the human publication requirement are
  unchanged; `round readiness` stays password-free (no new exposure: it may show
  store currency, which is public football data).

---

## 12. Test strategy

All offline: `httpx.MockTransport` (as `tests/test_client.py`), recorded responses
(`tests/fixtures/fixtures_sample.json`, `odds_fixture_sample.json`, replayed odds
trial files), fake providers, clock injection, isolated PostgreSQL databases
(`champ_helpers.isolated_engine`) and temporary SQLite stores. **No live API call.**

| Area | Tests |
|---|---|
| Scheduling | slot computation Tue–Fri and grace; DST (Europe) does not move UTC slots; ISO-year boundary; latest-due-slot only after missed ticks; no refresh after publication, after the grace, when paused, disabled, provider calls off, non-Beta |
| Accounting | every attempt reserved before sending, with class; retries counted; reserved-unsent counted; ledger matches mock request count |
| Budgets and priority | non-essential cap; maintenance cap; results still run with non-essential exhausted; preparation deferred rather than borrowing the reserve; per-tick cap splits a sweep over ticks |
| Pacing | minimum interval honoured (fake clock); minute-floor wait; `Retry-After` > cap ends the step without sleeping |
| Provider failures | 429, rate-limit body, quota body, auth error (blocking), 5xx, timeout, invalid JSON; a rate limit stops the remaining refresh steps of the tick but not results |
| Quota floors | lowest of header/`/status`/ledger wins; limit mismatch stops preparation; floor reached defers preparation, results continue |
| Partial refresh and retries | one league failing leaves others committed; sweep resumes; back-off; readiness evaluates and reports partial |
| Crash recovery | crash after reserve, after send, during apply (rollback); step marked interrupted/abandoned; rerun idempotent (no duplicate fixtures or episodes) |
| Concurrency | concurrent ticks (one runs); lock lost between fetch and apply → nothing written; manual writer holding the store → *database is locked* → retryable |
| Store consistency | no write transaction open during a mocked slow request (assert lock-free store during fetch); reader during a sweep sees whole leagues only; screener before readiness |
| Freshness and readiness | refresh after the provider update makes a stale round READY; before it stays NOT READY (`stale_odds`); refresh never sets READY by itself |
| Fixtures | postponed, cancelled and rescheduled fixtures move in or out of the snapshot; Goal Model payload recomputed |
| Isolation and safety | Development and Official never refreshed; no publication, no round change, no settlement or finalisation triggered by refresh; static import guard; competition rules, fingerprint and configurations unchanged |
| Behaviour preservation | `refresh-data`, `setup`, `collect-odds` outputs identical before/after the fetch/apply split (existing tests plus a comparison test) |

Acceptance for the implementation: Level 1 focused tests, Level 2 integration and
regression, full GitHub CI with **all 13 browser tests and no skips**, migration
head `app_0007` unchanged, fingerprint unchanged. Expected CI cost: under one minute
added (mocked transport, small stores), keeping the 40-minute timeout and the ≈ 9.5
minute margin.

---

## 13. Implementation sequencing (after approval)

| Step | Content | Approval needed |
|---|---|---|
| E.1b-1 | Provider safety: bounded in-tick waits (G2), scheduler pacing, class-aware ledger caps and reserve (REF-06), provider floors and `/status` pre-flight (REF-08), configuration and validation | REF-05/06/07/08 |
| E.1b-2 | Behaviour-preserving fetch/apply split of fixtures and odds ingestion (REF-09); CLI unchanged | REF-09 |
| E.1b-3 | Refresh slots, league steps, screener step, readiness trigger refinement in `prepare.py`; tick integration | REF-01–04, REF-10 |
| E.1b-4 | Status, `ops check` findings, `jobs status`, dry-run plan | REF-15 |
| E.1b-5 | Optional: read-consistent snapshot build (REF-11), maintenance refresh (REF-13), thin-week economy (REF-14) | each separately |
| E.1b-6 | Documentation, runbook, Level 1/2/3 verification, checkpoint | — |
| Live activation (Stage F) | subscription verification (one quota-free `/status`), host chosen (Q-07), backups, supervised first sweep on a Beta week, then unattended | owner, separately |

E.1b implementation leaves `DISKI9_JOBS_PREPARE_REFRESH` **off**; switching it on
anywhere real is a live-activation decision.

---

## 14. Risks, assumptions and open questions

| # | Item | Type | Mitigation / decision |
|---|---|---|---|
| 1 | Active plan and limits (7,500/day, 300/min) not re-verified since 15 Nov | Assumption | one quota-free `/status` before activation (owner-authorised live call) or owner checks the dashboard |
| 2 | Behaviour at the daily limit (hard stop or overage charge) unknown | Unknown | floors keep us far away; owner to confirm billing terms |
| 3 | Provider update time (02:00–03:30 UTC) measured on EPL over a few days | Observed, limited | `provider_update_missing` finding; grace sweeps; confirm in Stage F |
| 4 | Odds coverage varies by league and week (PSL none) | Observed | readiness decides; coverage reporting |
| 5 | Results-import volume is an estimate | Assumption | reserve 3× estimate; confirm in Stage F |
| 6 | SQLite same-host constraint | Code fact | REF-12; hosting Q-07 |
| 7 | D-39 ties PostgreSQL migration to hosted deployment | Decision tension | owner ruling (REF-12) |
| 8 | Other consumers of the shared key | Operational | floors, runbook, no bulk commands Friday morning |
| 9 | Unbounded `Retry-After` (pre-existing) | Code gap | REF-07 (also protects results imports) |
| 10 | Mixed-league reads during a sweep | Low | readiness waits for sweeps; REF-11 optional |
| 11 | CI margin ≈ 9.5 min | Existing | keep new tests fast; measure in E.1b-6 |
| 12 | Provider terms on caching/displaying odds-derived values (ADP-20 item 6) | Unknown | owner to confirm before public Beta |

**Owner decisions needed:** REF-01, REF-03, REF-05, REF-06, REF-07, REF-08, REF-09,
REF-12 (and Q-07), REF-13; optional REF-11 and REF-14. **Blocking implementation:**
REF-05/06/07/08/09/10 and the schedule (REF-01/03). **Blocking only live
activation:** subscription verification (risk 1–2), hosting and backups (REF-12),
Stage F authorisation.

---

## 15. REF decision register

"Blocks" = what cannot proceed without the decision: **impl** (implementation) or
**live** (activation only).

| ID | Decision | Options | Advantages / disadvantages | Recommendation | Owner approval | Blocks |
|---|---|---|---|---|---|---|
| **REF-01** | Refresh schedule | (a) ADP-13: first sweep target − 3 h (03:00), hourly after; (b) daily 04:15 Tue–Thu, Fri 04:15 and 05:15, hourly grace; (c) provider-update-aware polling | (a) usually before the daily provider update → stale at publication; (b) aligned with observed update time, simple, cheap; (c) cheapest freshness but more logic and depends on update detection | **(b)**; supersedes ADP-13's 03:00 default if approved; (c) later if evidence supports it | Yes | impl |
| **REF-02** | Full versus incremental | (a) fixtures + odds every sweep; (b) odds only after Tuesday; (c) by-ID fixture refresh for window fixtures only | (a) catches kickoff changes for 8 extra requests; (b) misses Friday postponements; (c) new code path, saves ~6 | **(a)**; standings excluded from preparation | Yes (with REF-01) | impl |
| **REF-03** | Odds cadence and grace | Conservative / Balanced / Intensive (§5) | freshness versus spend; provider updates daily | **Balanced**: daily Tue–Thu, two Friday sweeps, hourly grace, stop at publication or grace end | Yes | impl |
| **REF-04** | Behaviour after grace and after publication | (a) stop; (b) continue at a slower interval until deadline − 2 h | (a) bounded spend, manual path remains; (b) more automation, more spend | **(a)** | Yes | impl |
| **REF-05** | Scheduler budgets | keep 10/tick, 100/day; Balanced 20/tick, 450/day; Intensive 30/tick, 600/day | 100/day cannot cover a worst Friday plus results; 450 covers Balanced at high cost; 600 needed only for Intensive | **20/tick; 450/24 h; non-essential ≤ 300; maintenance ≤ 50; results reserve ≥ 150** | Yes | impl |
| **REF-06** | Priority enforcement | (a) shared caps; (b) class-aware caps in the existing serialised `reserve()` | (a) a long grace can starve Friday-evening results; (b) starvation impossible; small change to a Stage D function (cap check only; lock, timing and counting unchanged) | **(b)** | Yes (Stage D function) | impl |
| **REF-07** | Pacing and rate-limit waits | (a) client defaults (0.25 s, unbounded Retry-After); (b) 3 s interval, minute floor 30, in-tick wait ≤ 30 s; (c) 6 s interval (10/min) | (a) bursty, G2 risk; (b) safe without relying on 300/min, sweep ≈ 66 s; (c) sweep ≈ 2–3 min of sleeping per tick | **(b)** (fixes G2 for results too) | Yes | impl |
| **REF-08** | Provider floors and shared-key policy | (a) client reserve 500 only; (b) preparation floor 2,000 using the lowest of header, `/status`, ledger; results floor 500 unchanged | (a) preparation could consume capacity people need; (b) leaves ≥ 1,500 for corrections and manual work | **(b)**, plus runbook rule: no bulk manual commands Fri 03:30–12:00 | Yes | impl |
| **REF-09** | Store write pattern | (a) call existing functions inside one transaction (write lock during network); (b) fetch, verify ownership, apply in a short transaction via `store_fixtures` / `reconcile_pages` | (a) blocks other writers for up to a minute; (b) no lock during I/O, crash-safe, behaviour-preserving split | **(b)** | Yes (refactor of shared ingestion code) | impl |
| **REF-10** | Scheduler integration | (a) inside `jobs tick`, one league per step, resumable; (b) one long refresh step; (c) separate daemon | (a) bounded, uses all Stage D protections; (b) longer in-flight, coarser recovery; (c) second scheduler, new locking | **(a)**; no Stage D locking change | Yes | impl |
| **REF-11** | Snapshot read consistency | (a) as today; (b) one SQLite read transaction for `build_live_snapshot` | (a) valid per fixture, mixed in time during a sweep; (b) single point in time; touches the publication read path (no logic change) | **(b)** as optional hardening | Yes (publication path) | neither (optional) |
| **REF-12** | Football store and hosting for the Beta week | single host with SQLite (VM / single-instance container / owner computer) versus PostgreSQL migration first | SQLite sufficient with co-location; migration is a separate project (D-39) | **single host, SQLite, daily backups**; owner to rule whether the Beta week is the "hosted deployment" in D-39; host choice stays Q-07 | Yes | live |
| **REF-13** | Screener maintenance refresh | (a) none; (b) one sweep + standings daily outside Friday 03:00–12:00, ≤ 50/day, off by default | (a) Screener odds stale after Friday; (b) fresher Screener at ≈ 28/day | **(b) built but off**; owner decides activation | Yes | neither |
| **REF-14** | Thin-week economy | (a) always sweep; (b) skip grace sweeps when window fixtures < the existing opening minimum | (a) simple; (b) saves up to 132 requests when the week cannot open; uses the existing threshold, no new rule | **(a)** for the first Beta; (b) optional | Yes | neither |
| **REF-15** | Monitoring | findings in §10.2 with the E.1a attention window | early-week quiet, escalation near the target | **as §10.2**; webhooks stay off | Yes | impl |
| **REF-16** | Failure handling | per-league retryable with back-off; rate limit stops refresh for the tick; quota/floor defers; auth blocks; store unavailable fails closed | consistent with Stage C/E.1a classification | **as §6–§7** | Yes | impl |
| **REF-17** | Beta activation conditions | — | — | all of: owner approval of E.1b implementation acceptance; subscription verified (plan, daily and minute limits, billing at limit); host and backups in place (Q-07, REF-12); caps configured as approved; `jobs tick --dry-run` reviewed; first sweep supervised on a real Beta week (Stage F) | Yes | live |

---

*Prepared under the E.1b design-refinement authorisation of 22 Nov 2026. No
application code, migration, provider limit, live provider call, hosting selection,
webhook or activation changed. Stage F and Stage G remain unauthorised.*

---

## 16. Owner review (22 Nov 2026) and resolution of clarifications

| Clarification | Resolution (plan section) |
|---|---|
| **A** Sweeps spanning ticks | Sweep = (week, slot); league done iff a succeeded `scheduler.prepare_refresh` row with `args.slot`; resumed in fixed order each tick while allowance ≥ 4; done leagues never re-requested in the slot; a new slot supersedes and finalises the old sweep as partial; complete only with all eight leagues and a `complete` screener row; Friday 04:15/05:15 sweeps complete by about 04:21/05:21 (20/tick) or 04:26/05:26 (10/tick) — plan §5 |
| **B** Readiness and consistency | Per-league atomic commits → sweep → screener → readiness; scheduler readiness deferred during a sweep (≤ 30 min), triggered after it, labelled `data=complete/partial/none`; publication unchanged; handled by job-state coordination without changing the snapshot builder; REF-11 not proposed — plan §7 |
| **C** Pacing and `Retry-After` | Pacing from the last ledger reservation time in PostgreSQL (holds across ticks and restarts, no daemon); waits ≤ 30 s; longer `Retry-After`, 429 without retries and minute-window waits > 30 s end the step and write a persisted cooldown honoured by results and refresh; no transaction open during waits; worst step 134 s, longest tick ≈ 6.3 min < 20 min; results get the same protection — plan §3.1, §12 |
| **D** Quota observations | Observations recorded as completed `scheduler.provider_quota` rows; usable only if < 30 min old and from the current UTC provider day; otherwise one `/status` (quota-free at the provider, reserved as one preparation request in our ledger); lower value wins on disagreement; floor 2,000 for preparation only; lower daily limit stops preparation for the provider day; rolling 24 h internal caps versus provider calendar-day quota explained — plan §3.2 |
