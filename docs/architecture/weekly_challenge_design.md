# Diski 9 Weekly Challenge — Technical Design (Phase 5C)

Status: **design for review**. No code, schema or migration has been changed.
Requirements: [PRD](../product/weekly_challenge_prd.md). Decisions:
[register](../product/weekly_challenge_decisions.md).

## 1. Current architecture (inspected)

| Area | Finding | Implication |
|---|---|---|
| App | One Dash 4.5 app (`diski9.app.create_app`), a single page (Screener + Match Lab). No navigation or routing. Flask dev server via `diski9 serve`. | Add light routing (`dcc.Location`) with the Screener unchanged at `/`. Production hosting needs a WSGI server. |
| State | Browser memory stores (`dcc.Store`); data read through `ScreenerData` (an in-memory snapshot, 5-minute TTL); callbacks are pure functions of the store plus the snapshot. | Reuse the pattern: a `ChallengeData` service; client stores hold drafts only; the server validates everything. |
| Identity | **None.** No users, sessions or authentication. The app is a local single-user tool. | Identity and hosting are prerequisites: decisions D-01 and D-02. |
| Database | SQLite through SQLAlchemy Core plus Alembic (migrations 0001–0004). `forecast_snapshots` is insert-only, enforced by triggers. | New tables go in a new migration. Reuse the trigger pattern for immutability. Hosted multi-user use needs a database decision (D-03). |
| Results | `fixtures` stores `status_short`, `kickoff_utc`, `ft_home`/`ft_away` (90-minute `score.fulltime`), plus extra-time and penalty columns. Rows are overwritten on refresh; there is no result history. | Settlement must snapshot the result values it used. |
| Odds | `challenge_consensus(conn, fixture, t)`: strict, fresh, ≥ 3 groups, no stale fallback. `implied.normalise` removes the margin. | The round sheet calls these unchanged. |
| Model | The screener cache payload holds Goal Model 1.0 probabilities, version, parameter hash and data cutoff. | Copy them into the round sheet; never recompute after publishing. |
| Research code | `diski9.research.challenge_portfolio` (branch 5B): correct and tested, but needs **numpy and scipy, which are dev-only**. It hard-codes 6/6/6/2 and 20. | Port the needed pure functions into a dependency-free production module. Cross-check against the research code in tests. |
| Dependencies | Production: dash, sqlalchemy, alembic, httpx, pydantic-settings. Dev: numpy, scipy, hypothesis, pytest, ruff. | No new production dependency is needed for the maths or the chart (Plotly ships with Dash). Hosting and identity may add one: D-01, D-02. |

## 2. Proposed architecture

```
                 ┌──────────────────────── Dash app (one process per worker) ─────────────────────┐
 browser ──HTTP──▶  routing: /  (Screener, unchanged)   /challenge   /challenge/me   /leaderboards  │
                 │      │                       │                │               │                │
                 │      ▼                       ▼                ▼               ▼                │
                 │  ScreenerData        ChallengeData (read: rounds, round sheet, entries,         │
                 │  (unchanged)         leaderboards; TTL cache)  ChallengeService (write:          │
                 │                      submit; validates; transactions)                            │
                 │                              │  uses                                             │
                 │                              ▼                                                   │
                 │                 diski9.challenge.portfolio  (pure: partitions, 8 states,         │
                 │                 metrics, Pareto, recommendation)                                 │
                 └──────────────────────────────┬───────────────────────────────────────────────────┘
                                                │ SQLAlchemy Core
                                                ▼
                                         database (existing + challenge_* tables)
                                                ▲
             scheduled CLI jobs ────────────────┘
             refresh-data --with-odds (existing) · challenge publish · challenge settle · challenge finalise
```

**New packages (proposed):**
* `diski9/challenge/portfolio.py`: pure maths. No I/O, no numpy.
* `diski9/challenge/rules.py`: eligibility, deadline, settlement rules. Pure.
* `diski9/challenge/rounds.py`: publish the round sheet (reads odds and model, writes the sheet).
* `diski9/challenge/service.py`: submission transactions.
* `diski9/challenge/settlement.py`: settlement jobs.
* `diski9/challenge/leaderboard.py`: queries.
* `diski9/app/challenge/`: Dash layouts and callbacks for the three new screens.

The Screener package is untouched apart from one header navigation element.

## 3. Portfolio calculation integration

### 3.1 Production module `diski9.challenge.portfolio`

A dependency-free port of the Phase 5B logic, parameterised by an immutable
allocation:

```python
@dataclass(frozen=True)
class Allocation:          # MVP constant: Allocation(30, 30, 30, 10, target=100)
    bucket: tuple[int, int, int]   # integer credits
    nine: int
    target: int
    version: str = "30-30-30-10/v1"
```

Functions:
* `partitions()`: the 280 canonical partitions, IDs as in Phase 5B
  (`012|345|678` … `078|156|234`, lexicographic).
* `evaluate(selections, allocation) -> list[PortfolioResult]`: the eight-state
  distribution for every partition.
* `pareto_efficient(results)`: recovery ↑, expected ↑.
* `recommend(results)`: maximum recovery, then maximum expected return, then the
  lowest ID.

**Numerics:**
* **Odds** are stored and used as exact 2-decimal values (`Decimal`, or integer
  hundredths).
* **Payouts are exact rationals:** stake (integer credits) × product of odds.
  Recovery compares the exact payout against 100, so it is never subject to
  floating-point error. Ties at exactly 100 are impossible for a single bucket
  (30·O = 100 needs O = 10/3, which has no finite 2-decimal factorisation), but
  are handled exactly anyway.
* **Probabilities** are binary floats, products of nine model probabilities (each
  stored at full precision in the round sheet). P(recover) is a sum of exact
  state indicators times float state probabilities.
* **Pareto comparison:** coordinates are snapped to a grid first (probability
  1e-12, credits 1e-6 × 5 = 5e-6). This is documented and deterministic, as in
  Phase 5B, with the credit grid scaled with the stakes.
* **Display rounding:** probabilities to 0.1%, credits to 0.01.

**Cost:**
* 280 partitions × 8 states is about 2,240 state evaluations, plus a Pareto pass.
* In pure Python this is a few milliseconds (a sort-based two-dimensional sweep is
  O(n log n); a 280² check is also fine).
* No background job is needed for exploration.

### 3.2 Equivalence with Phase 5B

Tests (numpy available in dev) cross-check the production module against
`diski9.research.challenge_portfolio` on all 17 Phase 5B slates, the frozen real
snapshot included:
* identical partition IDs;
* recovery equal;
* E[R], SD and payouts equal to 5× the research values;
* identical efficient sets and recommendations.

The research module stays research-only and is never imported by the app.

### 3.3 Caching

* The round sheet is cached per round (it never changes after publishing).
* Explorer results are cached in an LRU per process, keyed by
  `(round_id, sorted selection keys, allocation.version)`. Deterministic, so
  safe to share between users.
* No API calls during exploration. The database is read only for the round sheet.

## 4. Data model and schema proposal

Conventions:
* `*_at` columns are UTC.
* IDs are integers, or UUID text where client-facing.
* Odds are `NUMERIC(8,2)`; credits `NUMERIC(14,2)`; probabilities `FLOAT`
  (double).
* Insert-only tables carry triggers that block UPDATE and DELETE (the 0004
  pattern), except for documented lifecycle columns, handled with narrow
  triggers or a separate state table.

### 4.1 Tables

```
challenge_users
  id                 TEXT PK            -- stable internal UUID
  identity_subject   TEXT UNIQUE NOT NULL  -- from the identity provider (D-01)
  display_name       TEXT NOT NULL      -- unique, case-insensitive (index on lower())
  leaderboard_public BOOLEAN NOT NULL DEFAULT TRUE   -- D-04
  created_at, updated_at

challenge_rounds
  id                 INTEGER PK
  code               TEXT UNIQUE        -- e.g. "2026-W47"
  name               TEXT               -- "Weekend 20–23 Nov"
  season             INTEGER
  window_start_at, window_end_at        -- fixture assignment window
  published_at       -- round sheet snapshot time (NULL while draft)
  deadline_at        -- common lock time (Option A), fixed at publish
  settle_cutoff_at   -- later completions are void (default window_end + 48 h)
  finalised_at
  status             TEXT  -- draft | open | locked | settling | final | cancelled
  allocation_version TEXT  -- "30-30-30-10/v1"
  rules_version      TEXT  -- settlement and void rules version
  calc_version       TEXT  -- portfolio module version
  model_version      TEXT  -- "goal-model-1.0" (+ params_hash)

challenge_round_fixtures            -- insert-only after publish
  round_id, fixture_id  PK
  competition_id, kickoff_at_publish, home_team, away_team
  forecast_cutoff_at, params_hash   -- Goal Model 1.0 provenance

challenge_round_offers              -- the round sheet; insert-only
  round_id, fixture_id, market, outcome   PK
  model_prob          FLOAT NOT NULL
  consensus_odds      NUMERIC(8,2)          -- NULL if no consensus
  market_prob         FLOAT                 -- margin-adjusted
  bookmaker_groups    INTEGER
  latest_observation_at, provider_updated_at
  eligible            BOOLEAN NOT NULL      -- ≥3 groups, fresh at published_at, model available
  ineligible_reason   TEXT

challenge_entries                    -- one per user per round
  id TEXT PK, round_id, user_id      UNIQUE(round_id, user_id)
  current_submission_id   TEXT       -- latest version (NULL before first submit)
  version                 INTEGER NOT NULL DEFAULT 0   -- optimistic concurrency
  locked_at               -- set once at the deadline; then immutable (trigger)
  final_submission_id     -- = current at lock; immutable after set

challenge_submissions                -- insert-only, one row per version
  id TEXT PK (UUID), entry_id, round_id, user_id, version
  idempotency_key  TEXT UNIQUE       -- client token per Submit click
  submitted_at
  partition_id     TEXT              -- e.g. "024|158|367"
  recommended_partition_id TEXT, chose_recommended BOOLEAN
  p_recover, p_profit, p_loss  FLOAT
  expected_gross   NUMERIC(14,4), max_gross NUMERIC(14,2)
  efficient_ids    TEXT              -- JSON list of efficient partition IDs
  portfolio_points TEXT              -- compact JSON of all 280 [id, x, y, efficient] (§4.3)
  inputs_hash      TEXT              -- SHA-256 over round_id + offers + selections + allocation
  allocation_version, calc_version, model_version, rules_version

challenge_submission_selections     -- insert-only; a copy of the offer values used
  submission_id, position (0–8)  PK
  fixture_id, market, outcome, bucket ('A'|'B'|'C')
  model_prob, consensus_odds, market_prob, bookmaker_groups,
  latest_observation_at, provider_updated_at
  UNIQUE(submission_id, fixture_id)  -- no fixture twice

challenge_submission_accumulators   -- insert-only
  submission_id, leg ('A'|'B'|'C'|'NINE')  PK
  stake INTEGER, combined_odds NUMERIC(20,8), win_prob FLOAT,
  potential_gross NUMERIC(14,2), recovers_alone BOOLEAN

challenge_fixture_results           -- insert-only result observations used for settlement
  id PK, fixture_id, observed_at, status_short, kickoff_utc, ft_home, ft_away,
  source ('api-football'), result_hash

challenge_settlement_runs           -- audit
  id PK, round_id, started_at, finished_at, trigger ('scheduled'|'manual'),
  status, changed_entries INTEGER, notes

challenge_selection_settlements     -- insert-only history; latest per key is current
  id PK, run_id, round_id, fixture_id, market, outcome,
  verdict ('won'|'lost'|'void'|'pending'), void_reason, result_id, settled_at

challenge_entry_settlements         -- insert-only history; latest per entry is current
  id PK, run_id, entry_id, submission_id,
  gross NUMERIC(14,2), net NUMERIC(14,2),
  legs_json   -- per leg: verdict, effective odds, payout
  status ('provisional'|'final'), inputs_hash
```

### 4.2 Integrity rules

* `challenge_entries`:
  * UNIQUE(round_id, user_id) gives one entry per user per round;
  * `locked_at` and `final_submission_id` can be set only once (the trigger
    rejects changes when they are non-NULL).
* `challenge_submission_selections`: UNIQUE(submission_id, fixture_id), plus a
  CHECK (or an application rule) of exactly 9 rows, validated in the service
  transaction.
* Offers and selections reference `(round_id, fixture_id, market, outcome)`, and
  the service checks `eligible = TRUE`.
* Round-sheet tables are insert-only once the round is published.

### 4.3 Store all 280 portfolios?

**Recommendation: store the inputs and the chosen portfolio as the source of
truth, plus a compact JSON of all 280 points.**

* The 280 points can be regenerated deterministically from the immutable inputs
  plus `calc_version`.
* Storing them as well (about 280 × 3 numbers, roughly 10 KB per submission)
  preserves exactly what the player saw, even if the calculation code changes
  later. That makes disputes and audits trivial.
* Per-portfolio rows are not needed (280 × 15 fields × submissions).

### 4.4 Research vs submission snapshots

**Phase 5B research snapshots** (`docs/research/weekly_challenge/*.json`):
* files in git;
* used for analysis only;
* never read by the app.

**Round sheets and submission snapshots:**
* database rows;
* immutable;
* the only inputs the Challenge ever uses;
* they record their own provenance: model version, parameter hash and odds
  timestamps.

## 5. Rounds and eligibility

### 5.1 Lifecycle

```
draft ──publish──▶ open ──(deadline passes)──▶ locked ──first settle run──▶ settling ──finalise──▶ final
   └──────────────────────── cancel (only before any locked entry exists) ───────────────▶ cancelled
```

**Publish** (`diski9 challenge publish --round 2026-W47`):
1. Requires a recent `refresh-data --with-odds`. Collect after about 04:00 UTC
   (the provider updates about 02:00–03:30 UTC; see Phase 5A).
2. Selects fixtures with kickoff in the window, among the eight supported leagues,
   with status NS or TBD.
3. For each fixture, market and outcome: copies the model probability from the
   screener cache, and calls `challenge_consensus(conn, fixture, published_at)`
   (unchanged) plus `implied.normalise` for the market probability.
4. Sets `deadline_at` = earliest `kickoff_at_publish` among the round's
   **eligible** fixtures, minus 15 minutes (configurable).
5. Refuses to publish with fewer than 9 eligible fixtures, and prints why.
6. Writes everything in one transaction.

**Lock:**
* Time-based: every write path checks `now < deadline_at` against server time
  inside the transaction. No job is needed for correctness.
* A `challenge lock` job (or the first settlement run) stamps `locked_at` and
  `final_submission_id` on each entry, for clarity and auditing.

### 5.2 Deadline options

| | Option A — one common deadline (recommended) | Option B — per-fixture locks |
|---|---|---|
| Rule | All entries lock before the earliest kickoff | Each selection locks at its own kickoff |
| Information fairness | Everyone decides with the same information and the same frozen prices | Later submitters see earlier results and team news against **stale frozen prices**: unfair |
| Fit with portfolios | The grouping of nine is decided once | A partially locked portfolio cannot be regrouped coherently: the 280 arrangements depend on all nine picks |
| Implementation | One timestamp check | Per-selection locks, partial edits, more states and tests |
| User clarity | "Submit by Fri 20:45" | Several moving deadlines |

**Downside of A:** players must decide before Friday's first match, even for
Monday games. Mitigations:
* show the deadline prominently, with a countdown;
* a future "Sunday round" can be a separate round, with its own sheet and
  deadline.

### 5.3 Fixture changes after publishing

* **Kickoff moves after the deadline, still inside the window:** settles normally.
* **Kickoff moves before the deadline:**
  * the fixture becomes unselectable immediately (the picker reads current
    `fixtures.kickoff_utc`);
  * any submitted selection on it is **void** at settlement (rule V3), so a
    started match can never inform an entry.
* **Kickoff moves after `settle_cutoff_at`, or the match is not played by then:**
  void.

## 6. Submission service

`ChallengeService.submit(user, round_id, selections, partition_id, idempotency_key, expected_version)`
runs in one transaction (SQLite `BEGIN IMMEDIATE`; PostgreSQL row lock on the
entry).

**Validation** (any failure aborts with a user-facing message):
1. The round is `open` and server `now < deadline_at`.
2. Exactly 9 selections, 9 distinct fixtures, one outcome each. Every
   `(fixture, market, outcome)` is an eligible offer on this round's sheet.
3. No selected fixture has started, or moved before the deadline, by now.
4. The portfolio is recalculated server-side from the round sheet (never from
   client values).
5. `partition_id` is in the recalculated efficient set.
6. `idempotency_key`:
   * unused → continue;
   * already used by this user → return the existing submission (duplicate
     click);
   * used by anyone else → reject.
7. The entry is upserted. `expected_version` must equal `entry.version`; on a
   mismatch, return a conflict and ask the client to reload (simultaneous edits).

**Write:** the submission, selections and accumulators (insert-only); then
`entry.current_submission_id` and `entry.version += 1`.

**Edit policy (recommended, D-07):**
* unlimited resubmissions before the deadline;
* every version is kept;
* the latest counts;
* no edits after the deadline, ever.

## 7. Settlement

### 7.1 Rules (rules_version `settle/v1`; requires approval, D-08)

| Market | Wins when (90-minute score H–A) |
|---|---|
| Home / Draw / Away | H > A / H = A / H < A |
| BTTS Yes / No | H ≥ 1 and A ≥ 1 / otherwise |
| Over 2.5 / Under 2.5 | H + A ≥ 3 / H + A ≤ 2 |

**Final statuses:**
* `FT`, `AET` and `PEN` settle on `ft_home`/`ft_away`, which hold the 90-minute
  score. Extra time and penalties never count. Domestic league matches rarely
  have them; play-off rounds can.
* A final status with a missing score stays **pending**: retry, then flag for the
  operator.

**Void rules (a void selection's odds = 1.00):**

| Code | Situation | Verdict |
|---|---|---|
| V1 | `PST` and not completed (final status) by `settle_cutoff_at` | void |
| V2 | `CANC`, `AWD`, `WO` (no genuine 90-minute result) | void |
| V3 | Kickoff moved to before `deadline_at`, or the match started before the deadline | void |
| V4 | `ABD`, `SUSP` or `INT` not completed by `settle_cutoff_at` | void |
| V5 | Completed by the cutoff after an earlier postponement or suspension | settle normally on the 90-minute score |
| — | Live or not-yet-started statuses before the cutoff | pending |

### 7.2 Accumulator payouts with voids

For each accumulator, the effective odds are the product of the odds of
non-void legs, with void legs = 1.00. The probabilities recorded at submission
are historical and are never recomputed.

| Situation | Payout |
|---|---|
| Any leg lost | 0 |
| Otherwise | stake × effective odds, computed exactly, then rounded half-up to 0.01 |
| All three legs of a bucket void | 30 (the stake back) |
| All nine void | 30 + 30 + 30 + 10 = 100 (net 0) |

**Settlement:**
* gross = the sum of the four accumulator payouts;
* net = gross − 100.

**Leaderboard effect:**
* voids shorten accumulators;
* a round where every pick is void scores net 0;
* there is no other adjustment.

### 7.3 Process, idempotency and audit

**Trigger:**
* `diski9 challenge settle --round R` runs after `refresh-data` (scheduled hourly
  during match windows, plus manually);
* `--all-open` settles every non-final round.

**Steps** (one transaction per round):
1. Read the current fixture rows for the round's fixtures. Insert a
   `challenge_fixture_results` row only if `result_hash` changed since the last
   observation.
2. Compute every selection verdict from the latest observation plus the rules
   (pure function). Insert a `challenge_selection_settlements` row only where the
   verdict or result changed.
3. Recompute each locked entry's legs, gross and net from its
   `final_submission_id` snapshot plus the current verdicts. Insert a
   `challenge_entry_settlements` row only where the values changed.
4. Record the run in `challenge_settlement_runs`, with counts.

**Properties:**
* **Idempotent:** a rerun with no new information inserts nothing except the run
  record.
* **Deterministic:** results are a pure function of the snapshot and the result
  observations.

**Round status:**
* *settling* while any selection is pending;
* finalisation is allowed when nothing is pending and at least 24 hours have
  passed since the last change (the correction window).

**Corrections:**
* before finalisation, a corrected score simply produces new history rows on the
  next run;
* after finalisation, results are frozen. A later correction needs
  `challenge settle --round R --reopen --reason "..."`, which is audited.

**Delayed API updates:** pending selections stay pending. The page shows
"waiting for official result". The cutoff rule bounds the wait.

## 8. Leaderboards

* **Weekly:**
  * computed from the latest `challenge_entry_settlements` per entry, for
    entrants only;
  * rank by net, descending;
  * ties share a rank (1, 2, 2, 4), and tied rows are listed by display name;
  * status badge: provisional or final.
* **Season** (recommended rule, D-09):
  * average net per entered round;
  * a player qualifies once they have entered at least 50% of the season's
    completed rounds and at least 3 rounds;
  * columns: rank, name, rounds entered, total net, average net;
  * non-qualifiers are listed below, unranked;
  * ties share a rank.
* **Why not plain cumulative net with skipped rounds scored 0:**
  * at market prices the expected net is negative (about −18 credits per round in
    Phase 5B's market-implied runs);
  * so not playing would beat most players.
  * The alternative "a missed round counts as −100" also fixes the incentive, but
    penalises late joiners. Both are in D-09.
* **Implementation:** SQL aggregation over final, plus provisional, settlements,
  cached for 5 minutes. A materialised table is optional later.

## 9. Security and concurrency

* **Authentication:** every write callback requires an authenticated user (D-01).
  Read pages are public, apart from My Challenge.
* **Server-side validation:**
  * Dash callbacks are public HTTP endpoints, so they never trust `dcc.Store`
    values or client-computed metrics;
  * the service recomputes everything from the round sheet.
* **Time:** deadline checks use the server clock inside the transaction, never the
  client's.
* **Concurrency:**
  * UNIQUE constraints (entry per user per round; idempotency key);
  * `BEGIN IMMEDIATE` (SQLite) or `SELECT … FOR UPDATE` (PostgreSQL) on the entry;
  * optimistic `version`.
* **Immutability:** triggers on the insert-only tables; lifecycle columns can be
  set once.
* **Abuse:**
  * rate-limit submissions per user (for example, 10 per minute);
  * display-name validation (3–24 characters; letters, digits, spaces, `-_.`;
    unique; a basic blocklist);
  * report and rename by the operator (D-05).
* **Privacy:**
  * store only the identity subject and the display name;
  * no email on leaderboards;
  * an option to hide from public tables (D-04).
* **Secrets:** API keys stay in the environment (existing); session or identity
  secrets come from the hosting configuration.

## 10. Performance and scalability

| Operation | Where | Cost |
|---|---|---|
| Round-sheet publish | CLI or scheduled job | about 60–160 fixtures × 3 consensus queries; seconds; weekly |
| Picker data | Web, cached per round | one query, then memory |
| 280 evaluations + Pareto + recommendation | Web request, pure Python, LRU cache | a few ms; no API calls |
| Submit | Web, one transaction | about 15 inserts |
| Settlement | Scheduled CLI | O(entries × 4 legs); thousands of entries in seconds |
| Leaderboards | Web, SQL aggregate, 5-minute cache | indexed by round_id and user_id |
| Odds and results refresh | Existing scheduled CLI | unchanged (about 14 odds requests plus fixture requests) |

**Concurrency limits:**
* **SQLite** in WAL mode handles many readers and serialised writers. That is
  adequate for a small community on one server process.
* **Multiple hosted worker processes, or heavier write load,** need PostgreSQL.
  SQLAlchemy Core keeps the move small (D-03).

## 11. Observability and operations

* The CLI prints a summary for every lifecycle step (publish, lock, settle,
  finalise). Settlement runs are recorded.
* **Scheduled jobs** (cron or systemd timers on the host):
  * odds and data refresh, daily after 04:00 UTC and before publish;
  * publish, weekly (for example Thursday 06:00 UTC);
  * settle, hourly from the round window start until finalisation.
* **Health checks:**
  * a round with fewer than 9 eligible fixtures;
  * pending selections beyond the cutoff;
  * odds freshness at publish time.
