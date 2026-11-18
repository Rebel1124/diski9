# Diski 9 Weekly Challenge — Technical Design (revised, Phase 6A.2)

Status: **revised design for review**. No production code, schema or migration has
been changed. This revision supersedes the Phase 5C design (`2e079ba`) where they
conflict:
* the 280-partition explorer, Pareto frontier and recommendation are removed;
* buckets are fixed by **market-probability bands** (`broad60-432-v1`) with
  4/3/2 picks and 40/30/20/10 credits;
* championships of 10 completed rounds with recovery-gated position points
  replace season scoring (old D-09);
* rounds open only after an exact feasibility check (§5.4).

The Phase 6A engine (`feature/weekly-challenge-engine`, `48392c1`) is the
baseline. It is reused and generalised (§3), not discarded.
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
| Engine baseline | `feature/weekly-challenge-engine` (`48392c1`, Phase 6A): dependency-free 3/3/3, 30/30/30/10 engine with D-15 rounding. Research: `risk_structure.py` (6A.1), `championship.py` (6A.2), stdlib only. | Generalise the 6A engine with a versioned config (§3.1); cross-check against the research code in tests. |
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
                 │                 diski9.challenge.portfolio  (pure: bands, 8 states, metrics,     │
                 │                 payout distribution, feasibility, points)                        │
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

### 3.1 Production module `diski9.challenge.portfolio` (generalised)

The Phase 6A engine (`48392c1`) implements 3/3/3 picks, 30/30/30/10 credits,
the eight-state distribution, D-15 rounding and the payout distribution. Phase
6A.2 generalises it through one immutable, versioned configuration:

```python
@dataclass(frozen=True)
class Band:
    low: Decimal  # inclusive
    high: Decimal  # exclusive, unless high_inclusive
    high_inclusive: bool = False


@dataclass(frozen=True)
class ChallengeConfig:  # broad60-432-v1
    version: str  # "broad60-432-v1"
    bands: tuple[Band, Band, Band]  # A [0.60, 0.95], B [0.40, 0.60), C [0.20, 0.40)
    sizes: tuple[int, int, int]  # (4, 3, 2)
    stakes: tuple[int, int, int]  # (40, 30, 20) credits
    nine_stake: int  # 10
    target: Decimal  # Decimal("100.00")
    classification_source: str  # "market" (margin-adjusted consensus)
```

Invariants checked at import: `sum(stakes) + nine_stake == target`;
`sum(sizes) == 9`; bands disjoint and ordered.

**Functions (pure, stdlib only):**
* `classify(market_prob, config) -> "A" | "B" | "C" | None`: compares the
  **full-precision** stored float; boundaries 0.60 and 0.95 belong to A, 0.40 to
  B, 0.20 to C. Never the displayed (rounded) value.
* `validate_portfolio(selections, config)`: exactly `sizes[b]` picks in each
  bucket, nine distinct fixtures, every pick eligible and in the bucket its
  market probability dictates. The bucket is **derived**, never chosen by the
  client.
* `evaluate(selections, config, source) -> PortfolioResult`: the eight-state
  distribution, metrics and payout distribution, for `source` = `"market"` or
  `"model"`. Market and model results are separate objects, never mixed.
* `bucket_summary(picks, stake, source)`: combined probability and odds, potential
  payout and "alone ≥ 100" for a single complete bucket (used before 9/9).
* `payout_distribution(result)`: unchanged from Phase 6A.
* Removed from the product path: `partitions()`, `pareto_efficient()`,
  `recommend()`.

**Numerics:** unchanged from Phase 6A (D-15): exact `Decimal` combined odds;
each accumulator payout rounded half-up to 0.01; state gross = sum; recovery =
`gross >= Decimal("100.00")`. Probabilities are floats.

**Cost:** one portfolio is 8 states, microseconds. There is no explorer, so no
per-request LRU is needed beyond the round sheet.

### 3.2 Equivalence and regression

* With `ChallengeConfig("legacy-333-v0", sizes=(3,3,3), stakes=(30,30,30), …)`
  the generalised engine must reproduce every Phase 6A test vector exactly.
* With `broad60-432-v1` it must match `diski9.research.risk_structure.evaluate`
  (Phase 6A.1) on all real-pool portfolios used in research, to 1e-12 in
  probabilities and exactly in credits.
* The research modules stay research-only.

### 3.3 Payout distribution ("Your Payout Probability")

A pure function in the same module:

```python
@dataclass(frozen=True)
class PayoutOutcome:
    gross: Decimal                     # settlement-precision credits (0.01)
    probability: float                 # P(R = gross)
    states: tuple[tuple[int, int, int], ...]   # which bucket-win states give it
    at_least: float                    # P(R >= gross)

def payout_distribution(result: PortfolioResult) -> list[PayoutOutcome]   # ascending gross
def at_least(dist: list[PayoutOutcome], x: Decimal) -> float              # P(R >= x)
```

**Construction:**
* Take the eight states of the complete portfolio (the same `PortfolioResult` as
  the summary, at 40/30/20/10).
* Group them by gross payout at settlement precision. This is `Decimal` equality,
  so merging is exact and never tolerance-based. It gives 1–8 distinct outcomes.
  For example, the "nothing wins" state is always 0, and two buckets with
  identical payouts merge.
* Sort ascending.
* Set `at_least` to the suffix sum of `probability`.

**Invariants** (tested):
* Σ probability = 1, to within 1e-12.
* `at_least` is non-increasing, and the first value is 1.0 (gross 0 is always
  reached).
* `at_least(dist, Decimal("100.00"))` equals `result.p_recover` **exactly**: the
  same states are counted, compared at settlement precision.
* The nine-fold payout appears only in the (1,1,1) outcome.
* Selecting the same grouping again returns an identical distribution.
* All outcomes come from the cached `PortfolioResult`, with no I/O.
* The last outcome is the all-win payout 40·O_A + 30·O_B + 20·O_C + 10·O_9, with
  probability P_A·P_B·P_C (= P_9).
* Σ gross × probability = `result.expected_gross`.

**Chart data:**
* The step polyline (UX §4.3) is built server-side from the outcomes.
* No interpolation, no Plotly `line_shape="spline"`. Either explicit vertices,
  or `line_shape="vh"` (vertical, then horizontal) on the points (0, 1),
  (r₁, S₁), (r₂, S₂), …, (r_max, S_max), (r_max, 0), where Sₖ = P(R ≥ rₖ). This
  makes the curve drop at 0⁺ to P(R > 0), hold each level up to the next payout,
  and fall to 0 after the maximum.
* The exact view is a discrete probability-mass bar chart:
  * one narrow bar per distinct payout (Plotly `Bar` with a fixed narrow width,
    so bars do not imply ranges);
  * heights sum to 100%.
* Both are recalculated in the same callback that updates the review panel,
  keyed by `(round_id, selections, source)`. Cost: microseconds.

**Storage:**
* Nothing new is persisted. The distribution is a pure function of the stored
  inputs.
* The submission keeps the eight `(gross, market probability, model
  probability)` triples in `states_json`, so the receipt can redraw exactly what
  was shown.

### 3.4 Caching

* The round sheet is cached per round (it never changes after publishing).
* Portfolio evaluation is cheap enough to compute per request; no explorer cache.
* No API calls during building or review. The database is read only for the
  round sheet.

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
  config_version     TEXT  -- "broad60-432-v1" (bands, sizes, stakes)
  championship_id    INTEGER NULL       -- set when the round completes (§12)
  championship_round INTEGER NULL       -- 1..10 within that championship
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
  bucket              TEXT                  -- 'A'|'B'|'C' from market_prob (full precision); NULL if outside 20–95%
  ineligible_reason   TEXT                  -- incl. 'below_20' / 'above_95'

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
  p_recover_market, p_recover_model     FLOAT
  expected_gross_market, expected_gross_model  NUMERIC(14,4)
  max_gross        NUMERIC(14,2)
  states_json      TEXT              -- 8 × [state, gross, p_market, p_model] (§3.3)
  inputs_hash      TEXT              -- SHA-256 over round_id + offers + selections + config
  config_version, calc_version, model_version, rules_version

challenge_submission_selections     -- insert-only; a copy of the offer values used
  submission_id, position (0–8)  PK
  fixture_id, market, outcome, bucket ('A'|'B'|'C')
  model_prob, consensus_odds, market_prob, bookmaker_groups,
  latest_observation_at, provider_updated_at
  UNIQUE(submission_id, fixture_id)  -- no fixture twice

challenge_submission_accumulators   -- insert-only
  submission_id, leg ('A'|'B'|'C'|'NINE')  PK
  stake INTEGER, combined_odds NUMERIC(30,18), win_prob_market FLOAT, win_prob_model FLOAT,
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

challenge_round_scores              -- insert-only history; latest per (round, entry) is current
  id PK, run_id, round_id, entry_id, user_id,
  gross NUMERIC(14,2), rank INTEGER,         -- standard competition rank (1 + #strictly greater)
  tie_size INTEGER,
  points INTEGER NOT NULL,                   -- whole points (D-26: full points for ties)
  recovered BOOLEAN, qualifying_top10 BOOLEAN,
  scoring_version TEXT                       -- "points-150-75-v2"

challenge_championships
  id PK, number INTEGER UNIQUE, scoring_version TEXT,
  started_round_id, completed_round_count INTEGER (0..10),
  status ('active'|'complete'), completed_at
  champions_json TEXT                        -- champion(s) at finalisation

challenge_rounds.designation TEXT            -- 'championship' | 'practice' | 'void' | 'postponed'
challenge_rounds.valid_entries INTEGER       -- distinct participants locked at the deadline
```

**Championship standings are not stored as authoritative rows.** They are a pure
aggregation over the current `challenge_round_scores` of the championship's ten
rounds (sum of points; recoveries; qualifying top-ten finishes), so a
corrected round re-scores automatically. A frozen snapshot is written when the
championship completes, for display and audit only.

### 4.2 Integrity rules

* `challenge_entries`:
  * UNIQUE(round_id, user_id) gives one entry per user per round;
  * `locked_at` and `final_submission_id` can be set only once (the trigger
    rejects changes when they are non-NULL).
* `challenge_submission_selections`: UNIQUE(submission_id, fixture_id), plus an
  application rule of exactly 4/3/2 rows by bucket, validated in the service
  transaction; each row's bucket must equal the offer's `bucket`.
* `challenge_round_scores`: rows exist only for championship-designated rounds;
  `points` ∈ {0, 75, 90, 95, 100, 105, 110, 115, 120, 125, 135, 150}.
* Offers and selections reference `(round_id, fixture_id, market, outcome)`, and
  the service checks `eligible = TRUE`.
* Round-sheet tables are insert-only once the round is published.

### 4.3 What a submission stores

* The inputs (selections with copied offer values) and the config version are the
  source of truth.
* Plus the eight states with market and model probabilities (`states_json`),
  about 1 KB, so the receipt shows exactly what was seen.
* The Phase 5C "all 280 points" JSON is **dropped**: there are no groupings.

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
5. Runs the opening checks (§5.4). If any fails, the round is **postponed**
   (status `cancelled`, reason `infeasible`), it is not counted in any
   championship, and the CLI prints why.
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
| Fit with portfolios | The portfolio of nine is decided once | A partially locked portfolio mixes known and unknown legs; buckets and the nine-fold depend on all nine picks |
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

### 5.4 Opening checks (feasibility)

A round opens only if **all three** hold on the frozen round sheet:

1. at least **15 eligible fixtures** (a fixture is eligible if at least one of its
   outcomes is eligible and falls in band A, B or C);
2. those fixtures span at least **3 leagues**;
3. a **strict 4/3/2 portfolio exists** on nine distinct fixtures.

Check 3 is exact. Counting outcomes per bucket is not enough, because one fixture
can hold outcomes in several bands but supply only one pick. The check is a
bipartite matching (max-flow): source → bucket slot (4 A, 3 B, 2 C) → fixture
(edge if the fixture has an eligible outcome in that band) → sink (capacity 1).
A portfolio exists iff all nine slots are matched. Augmenting paths on ≤ 9 slots
× ~100 fixtures cost well under a millisecond. Reference implementation and
tests: `diski9.research.championship.strict_portfolio_exists`, cross-checked
against an exact count (`risk_structure.count_portfolios`).

Thresholds 15 and 3 are **approved operational values** (D-28), not empirically
tuned; checks 1–2 protect variety, check 3 protects
completeness. The builder also warns live when the remaining unused fixtures can
no longer fill an incomplete bucket (same matching, restricted to unused
fixtures).

## 6. Submission service

`ChallengeService.submit(user, round_id, selections, idempotency_key, expected_version)`
runs in one transaction (SQLite `BEGIN IMMEDIATE`; PostgreSQL row lock on the
entry).

**Validation** (any failure aborts with a user-facing message):
1. The round is `open` and server `now < deadline_at`.
2. Exactly 9 selections, 9 distinct fixtures, one outcome each. Every
   `(fixture, market, outcome)` is an eligible offer on this round's sheet, and
   the bucket counts are exactly 4 A, 3 B, 2 C using the offers' stored buckets.
3. No selected fixture has started, or moved before the deadline, by now.
4. The portfolio is recalculated server-side from the round sheet (never from
   client values).
5. Incomplete portfolios are rejected (there is no partial entry).
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
| All legs of a bucket void | that bucket's stake back (40, 30 or 20) |
| All nine void (D-33, approved) | 100.00 returned, net 0.00, status "Void — Refunded": unranked, 0 points, no recovery or qualifying top-ten finish recorded; the record is kept for audit |

The rules above are the approved D-32 settlement: void legs at 1.00, other legs
settle normally, any incorrect non-void leg makes its bucket pay 0, payouts
(including The Diski 9) are recalculated on the adjusted odds with D-15 rounding,
and no replacement predictions are possible after the deadline.

**Settlement:**
* gross = the sum of the four accumulator payouts;
* net = gross − 100.

**Leaderboard effect:**
* voids shorten accumulators;
* an entry whose nine picks are all void is refunded and unranked (D-33);
* entries recovering at least 100.00 remain eligible for points in a competitive
  round;
* whether widespread voids invalidate the whole round is decision D-32b
  (recommendation: void the round unless more than half of all confirmed
  predictions settled on a played result and at least five entries remain ranked;
  see `docs/product/weekly_challenge_d32_round_invalidation.md`).

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
  * computed from the latest `challenge_entry_settlements` per entry, entrants
    only;
  * ranked by gross (equivalently net), descending;
  * ties share the best occupied position, shown "=2";
  * points per the approved rule (§12), shown beside gross and net;
  * status badge: provisional or final.
* **Championship:** §12.
* **Implementation:** SQL aggregation over current settlements and round scores,
  cached for 5 minutes.

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
| Portfolio evaluation (8 states, market + model) | Web request, pure Python | microseconds; no API calls |
| Opening checks (matching) | Publish job | < 1 ms |
| Round scoring + championship aggregation | Settlement job | O(entries log entries) |
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
  * a round that fails the opening checks (§5.4);
  * pending selections beyond the cutoff;
  * odds freshness at publish time.

## 12. Weekly points and championships

Rules version `points-150-75-v2` (approved for the MVP, D-31; tie, threshold and
continuation rules approved, D-26 to D-28 and D-30; implemented in
`diski9.challenge.scoring`, Phase 6A.3). Supersedes `points-150-50-v1`.

### 12.1 Weekly points

* Rank = 1 + the number of entrants with a strictly greater settled gross
  (exact `Decimal` comparison at 0.01): **standard competition ranking**.
* Gross ≥ 100.00 (inclusive): rank 1–10 earns 150/135/125/120/115/110/105/100/95/90;
  rank 11+ earns 75. Gross < 100.00: 0. Non-entrants: 0.
* **Ties (approved D-26):** every tied entrant gets the full points of the shared
  rank; later ranks are skipped. More than ten entrants can receive top-ten
  points. Points are integers; no fractions are stored.
* `qualifying_top10` = recovered and rank ≤ 10 in a championship-designated
  round.

### 12.2 Round designation and championships

* At the deadline, `valid_entries` = the number of distinct participants with a
  locked, complete, valid final submission (resubmissions count once).
* Designation:
  * opening checks failed → `postponed` (never opened);
  * `valid_entries` < 5 → `practice`: settles, weekly table, **no**
    `challenge_round_scores` rows, counter unchanged;
  * whole round cancelled or invalidated after the deadline → `void`: stakes
    returned, no scores, counter unchanged (an operator cancellation, or the
    widespread-void rule once D-32b is decided, evaluated at final settlement);
  * fully void entries count toward `valid_entries` at the deadline (D-33);
  * otherwise → `championship`: scored, counter + 1.
* A championship is exactly **10 championship-designated rounds**; there is no
  time limit, so it pauses across breaks (D-30). On the tenth round it is
  finalised, champions recorded, archived, and the next starts from zero.
* **Standings (approved D-27):** total points → recoveries → qualifying top-ten
  finishes → joint position (standard competition ranking).

### 12.3 Re-scoring on corrections

* A settlement correction re-scores **the whole round**, inserting new
  `challenge_round_scores` rows only where values changed.
* Championship standings are an aggregation, so no cascade logic is needed.
  After a championship is frozen, a correction needs the audited `--reopen` path,
  which re-freezes the snapshot.
* A correction can never change a round's designation, which is fixed at the
  deadline; only an operator void (audited) can.

### 12.4 Reference implementation

`diski9.research.championship`: `competition_ranks`, `final_points`,
`position_points`, `standings`, `ChampionshipSeries` (practice and void rounds,
the ten-round cycle). Tests: `tests/test_championship_refinement.py`.
