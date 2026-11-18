# Diski 9 Weekly Challenge — Product Requirements (revised, Phase 6A.2)

Status: **revised specification for review**. Nothing here is implemented.

| | |
|---|---|
| Branch | `design/weekly-challenge-phase-6a2` (from the Phase 5C spec `2e079ba`) |
| Supersedes | The Phase 5C PRD (`2e079ba`): the free choice of nine, the 280-grouping explorer, the efficient frontier, the recommendation, 30/30/30/10, and season scoring |
| Evidence | Phase 5B `6f5a2f9` (portfolio maths) · Phase 6A `48392c1` (engine, preserved as baseline) · Phase 6A.1 `197e8ae` (risk structure) · Phase 6A.2 championship research (`docs/research/weekly_challenge_championship_scoring.md`) |
| Companions | [UX](weekly_challenge_ux.md) · [technical design](../architecture/weekly_challenge_design.md) · [implementation plan](weekly_challenge_implementation_plan.md) · [decisions](weekly_challenge_decisions.md) |

## 1. Philosophy and objectives

* **What Diski 9 is:** a football predictive analytics and virtual-credit
  competition platform.
* **What the Weekly Challenge teaches:** probability, risk, diversification,
  accumulator mathematics and capital recovery, through an accessible prediction
  game.
* **The participant's two objectives:**
  1. **Recover at least the original 100 virtual credits** through thoughtful
     portfolio construction.
  2. **Finish in the weekly top ten while recovering at least 100 credits.**
* **Winning a week is not presented as a separate objective,** and the product
  never encourages maximising potential payout.
* **Credits are virtual,** non-purchasable, non-withdrawable and have no monetary
  value.
* **No real money,** no prizes with cash value, no bookmaker links, and no staking
  advice.
* **The product must not encourage** chasing losses, maximising speculative
  payouts, or real-money wagering.
* **Outcomes and accumulators are never called** "safe", "guaranteed" or
  "risk-free".

## 2. Users

| User | Need |
|---|---|
| Casual fan (primary) | Simple rules, clear progress, plain-language risk |
| Engaged Diski 9 user | Compare the market and the Diski 9 model; understand the maths |
| Competitive player | Fair, transparent weekly and championship scoring |
| Operator | Safe round lifecycle, auditable settlement and scoring |

## 3. Approved Weekly Challenge rules (MVP configuration `broad60-432-v1`)

* **Allocation:** each participant receives a fresh **100 virtual credits per
  completed round**.
* **Selections:** exactly **nine outcomes on nine distinct eligible fixtures**,
  one outcome per fixture.
* **Markets:** match result (home / draw / away), Both Teams to Score (yes / no),
  Over / Under 2.5 total goals.
* **Bucket assignment:** each selected outcome is assigned automatically to a
  bucket by its **margin-adjusted market-implied probability**, at full precision
  (never a rounded display value).

| Bucket | Display name | Probability range | Selections | Credits |
|---|---|---|---:|---:|
| A | **Foundation** | 60% ≤ p ≤ 95% | 4 | 40 |
| B | **Balanced** | 40% ≤ p < 60% | 3 | 30 |
| C | **Challenger** | 20% ≤ p < 40% | 2 | 20 |
| Nine-fold | **The Diski 9** | all nine selections | 9 | 10 |

* **Ranges** are non-overlapping. Outcomes below 20% or above 95% are
  ineligible.
* **Labels describe outcome categories,** not accumulator risk. Foundation,
  Balanced and Challenger categorise individual outcomes. They are **not**
  rankings of how likely each accumulator is to win.
* **Membership follows the outcome, not the fixture.** Different outcomes of one
  fixture can fall into different buckets, but only one outcome per fixture may
  be selected.
* **Strict structure:** exactly 4 / 3 / 2 selections, 9 unique fixtures, and the
  fixed 40 / 30 / 20 / 10 credits. Participants cannot change the buckets or the
  allocation.
* **Versioning:** the configuration is versioned (`broad60-432-v1`). A change
  creates a new version and never affects existing rounds.
* **Evidence status:** the configuration is approved for the MVP. Its empirical
  validation so far is **one complete real weekly pool** (Phase 6A.1).

## 4. Probability and odds sources (kept separate)

| Source | Used for | Notes |
|---|---|---|
| **Market-implied probability** | Bucket eligibility and classification; the market-based portfolio estimate | The existing method: consensus odds from at least 3 independent bookmaker groups, fresh (24 h) and complete; margin removed proportionally. These are estimates, not true probabilities. |
| **Goal Model 1.0 probability** | Independent predictive analysis; the model-based portfolio estimate | Goals-based Poisson model (not shot-based xG). Unchanged, not recalibrated. |
| **Frozen consensus reference odds** | Virtual-credit payouts | Frozen in the round sheet when the round is published. Reference prices, not offers. |

**Known model limitations, shown in the methodology:**
* Relative to the market, Goal Model 1.0 rates favourites lower (−6.1 points for
  market ≥ 60%) and long shots higher (+4.5 points for market < 25%).
* Its highest probability for any outcome in the Phase 6A.1 pool was 75.7%.
* Under plausible model error (logit noise, sd 0.3), 24–28% of outcomes would
  change band. This is why eligibility uses market probabilities.

**Estimates are never mixed:** market and model estimates are shown separately.
No single estimate combines both sources.

## 5. Functional requirements

### 5.1 Rounds and the round sheet (kept from Phase 5C, with changes)

* FR-R1. Configurable rounds. MVP cadence: a weekend round, with a window of
  Friday 00:00 to Monday 23:59 UTC.
* FR-R2. **Round sheet** frozen at publish time. Every eligible outcome stores:
  * the market probability (full precision) and its **bucket**;
  * the Goal Model 1.0 probability;
  * the consensus reference odds;
  * the bookmaker-group count and timestamps;
  * the configuration version.
* FR-R3. **One common deadline:** the earliest eligible kickoff minus 15 minutes,
  fixed at publish time. No submission or change is accepted after it.
* FR-R4. **Opening checks.** A round opens only if all of the following hold:
  1. **at least 15 eligible fixtures** (fixtures with at least one outcome in A, B
     or C);
  2. **at least 3 eligible leagues**;
  3. **an exact feasibility check** confirms that a strict 4/3/2 portfolio on nine
     distinct fixtures exists (max-flow matching; technical design §5.2).
     Counting outcomes per bucket is not sufficient.
* FR-R5. If the checks fail, the round is **postponed**, never weakened. A
  postponed or cancelled week is not a completed round.
* FR-R6. Times are stored in UTC and shown in the viewer's time zone.

### 5.2 Selection and the bucket tracker

* FR-S1. The participant browses eligible fixtures and compares market and Diski 9
  probabilities for each outcome.
* FR-S2. Selecting an outcome places it in its bucket automatically. A second
  outcome on the same fixture **replaces** the first.
* FR-S3. A bucket that is full cannot take more: "Foundation is full (4/4).
  Remove one to change."
* FR-S4. A live **bucket tracker** shows Foundation X/4, Balanced X/3, Challenger
  X/2 and Total X/9.
* FR-S5. Selections can be reviewed and changed until submission, and resubmitted
  until the deadline (every version is kept; the latest counts).
* FR-S6. Ineligible outcomes (outside 20–95%, or without a qualifying market) are
  shown disabled, with the reason.

### 5.3 Portfolio analytics (complete portfolios only)

* FR-P1. The buckets are defined by the selections. There is **no** grouping
  step, efficient frontier or recommendation.
* FR-P2. For a complete portfolio, show, **separately for the market-based and the
  model-based estimate**:
  * per bucket and for The Diski 9: the individual probabilities, the combined
    probability, the combined decimal odds and the potential gross payout;
  * the expected gross and expected net return;
  * the probability of recovering at least 100 credits;
  * the probability of receiving zero credits;
  * the maximum possible payout;
  * the exact payout distribution (the "Your Payout Probability" chart: an
    "at least" view and an "exactly" view).
* FR-P3. **Calculation rules:**
  * the exact eight-state method;
  * The Diski 9 pays only when all three buckets win;
  * independence across fixtures (stated);
  * D-15 rounding: each accumulator's gross payout is rounded half-up to 0.01
    credit, then summed per state;
  * recovery means the state gross is at least 100.00.
* FR-P4. **Incomplete portfolios** show progress, and per-bucket figures only for
  completed buckets. They never show portfolio recovery or return figures.

### 5.4 Explore Your Bucket Risk (permanent educational feature)

* FR-X1. Explains:
  * individual vs combined probability;
  * why four likely outcomes can still make an unlikely accumulator;
  * potential payout vs expected return;
  * the probability of recovery;
  * the probability of zero;
  * the assumptions and limitations.
* FR-X2. Has adjustable **hypothetical** probabilities and **fair odds** (1 ÷ p),
  clearly labelled "Illustration".
* FR-X3. **Never changes** the participant's portfolio, the reference odds or the
  fixed credits.

### 5.5 Settlement (kept from Phase 5C)

* 90-minute result. Void rules V1–V5. A void leg counts as odds 1.00.
* Exact payouts with D-15 rounding.
* Idempotent, audited settlement, with a 24-hour correction window before a round
  is final.

### 5.6 Weekly leaderboard

* FR-W1. Ranks entrants by **realised net credits** (gross − 100). This is
  equivalent to ranking by gross.
* FR-W2. Shows the finishing position, display name, gross credits returned, net
  credits, and championship points. Gross and net are clearly labelled.
* FR-W3. It resets each completed round. History is retained.
* FR-W4. Entrants who don't recover still appear, with 0 points.

### 5.7 Championships (replaces season scoring; supersedes D-09)

Phase 6A.2.1 revision: the points schedule, the weekly tie rule and the
operational rules below supersede the Phase 6A.2 text.

* FR-C1. A championship consists of **exactly ten completed championship-eligible
  rounds**, independent of league seasons and calendar quarters (D-30).
  * Postponed weeks (opening checks failed), practice rounds and void rounds do
    not count and do not advance the counter.
  * When a season ends, an international break occurs or no suitable pool exists,
    the championship **pauses**: points are preserved and it resumes with the next
    eligible round. It is never shortened, and no champion is crowned early.
* FR-C2. After the tenth eligible round:
  * standings are finalised;
  * the champion, or joint champions, are recorded;
  * the championship is archived;
  * the next championship starts with points reset to 0.
  * History and lifetime statistics are kept.
* FR-C3. **Joining and entering:**
  * participants may join at any time;
  * all ten rounds count (no best-X);
  * non-entry scores 0;
  * nothing carries forward between championships.
* FR-C4. **Points** (`points-150-75-v2`, approved for the MVP, D-31; validated in
  Phase 6A.2.1 by simulation). **No recovery, no championship
  points.**

| Weekly rank (gross ≥ 100.00) | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11+ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Points | 150 | 135 | 125 | 120 | 115 | 110 | 105 | 100 | 95 | 90 | 75 |

  * Gross < 100.00 scores **0** at any rank, as does not entering. Exactly 100.00
    qualifies.
  * Points are non-additive: first place earns 150 in total, not 150 + 75.
  * A recovery (75) is worth half the maximum weekly award (150).
  * Maximum: 150 per round, 1,500 per championship. Points are always whole
    numbers.
  * Every participant who recovers ranks above every one who doesn't, so top-ten
    points never go to a participant who failed to recover.
* FR-C5. **Championship table:** rank, display name, rounds entered, successful
  recoveries, qualifying top-ten finishes, total points.
* FR-C6. **Tie rules (approved, D-26 and D-27):**
  * **Weekly: standard competition ranking.** Rank = 1 + the number of entrants
    with a strictly greater settled gross (compared exactly at 0.01 credit). Tied
    entrants share the rank and **each receives that rank's full points**; the
    following ranks are skipped. Example: 350, 350, 290 → ranks 1, 1, 3 → 150,
    150, 125. Ties can give more than ten entrants top-ten points (for example
    three tied at rank 10 all get 90, and the next entrant is rank 13 with 75).
    No averaging; no timestamp, ID or other tie-breaks. Tied entrants below 100.00
    get 0.
  * **Championship:** total points → successful recoveries → qualifying top-ten
    finishes (weekly rank ≤ 10 *and* gross ≥ 100.00 in a championship-eligible
    round) → still equal: joint position, with standard competition ranking
    (joint champions allowed). Cumulative gross or net credits are never a
    tie-break.
* FR-C7. **Championship participation (approved, D-28):**
  * A round counts toward the championship only with **at least 5 valid
    entries**.
  * A valid entry is a distinct participant with a complete, valid final
    submission locked at the deadline. Resubmissions by the same participant count
    once (the final version).
  * The designation is fixed at the deadline: with fewer than 5 valid entries the
    round becomes a **practice round**. It settles normally and shows personal
    results and a weekly table, but awards no championship points, doesn't affect
    tie-breakers and doesn't advance the counter. Practice results are kept
    separately for history.
  * A round cancelled or invalidated as a whole after the deadline is a **void
    round**: stakes are returned, nothing counts, and the counter doesn't advance
    (see the research report for edge cases).
* FR-C8. **Opening checks (approved, D-28):** at least 15 eligible fixtures, at
  least 3 eligible leagues, and an exact check that a strict 4/3/2 portfolio on
  nine distinct fixtures exists (FR-R).

### 5.8 Communication

* Fixed caveats appear on analytics and review:
  * modelled estimates, not guarantees;
  * reference odds, not offers;
  * credits have no value.
* **Banned words:** safe, guaranteed, risk-free, sure, lock, banker, free money.
* Explanations distinguish **potential payout** from **expected return**, and
  **individual** probability from **combined** probability.

## 6. Non-functional requirements

* **Exact and deterministic:** exact `Decimal` odds and payouts, D-15 rounding,
  whole-number points, deterministic standard competition ranking.
* **Immutable:** round sheets, submissions, settlements and scoring history are
  insert-only. Configuration versions are never edited.
* **Auditable:** settlement corrections re-score the affected round and its
  championship with an audit record.
* **Offline analytics:** portfolio analytics make no API calls (they work from
  the round sheet).
* **Accessible:** a keyboard-operable tracker and builder; table alternatives to
  the charts; WCAG AA contrast.
* **Responsive:** usable at 390 px with no horizontal page scroll.
* **No regression:** the Screener, Match Lab, odds, Edge/EV and Goal Model 1.0
  are unchanged.

## 7. MVP scope and exclusions

**In scope:**
* rounds with opening checks;
* round sheet;
* bucket builder and tracker;
* complete-portfolio analytics (market and model);
* Your Payout Probability;
* Explore Your Bucket Risk;
* submission;
* settlement;
* weekly leaderboard;
* championships;
* history.

**Excluded:**
* adjustable stakes or buckets;
* allocation helpers;
* the 280-grouping explorer;
* the efficient frontier;
* recommendations;
* an interactive championship or season explorer;
* best-X rounds;
* carry-forward of credits or points;
* real money;
* private leagues;
* notifications.

## 8. Acceptance criteria

1. Only valid strict portfolios (4/3/2, nine distinct fixtures, eligible market
   bands) can be submitted, including via direct callback calls.
2. Bucket assignment uses full-precision market probabilities from the frozen
   round sheet. Boundary values are assigned to the correct bucket.
3. Complete-portfolio analytics match the exact eight-state reference for both
   sources. Incomplete portfolios show no portfolio-level recovery or return.
4. The payout-chart "at least 100" value equals the summary recovery probability.
   The exact-payout probabilities sum to 100%. The maximum includes The Diski 9.
5. Weekly points and championship standings match the worked examples (§5.7 and
   the research tests), including ties across tenth place, nobody or everybody
   recovering, and duplicate submissions counting once.
6. A championship finalises after exactly ten championship-eligible rounds,
   archives, and resets points; it pauses across breaks.
7. Rounds that fail the opening checks are postponed; rounds with fewer than 5
   valid entries are practice rounds; neither counts.
8. Existing Diski 9 functionality and Goal Model 1.0 are unchanged.

## 9. Evidence status

| | Evidence |
|---|---|
| **Empirical** | One complete real weekly pool: 60 fixtures, 420 outcomes, 6 leagues, as of 17 Nov 2026 |
| **Synthetic** | Pool-size feasibility, and the championship simulations (shared Poisson scorelines) |
| **Required before treating the configuration as validated** | 6–8 real weekly pools, including an international break and small rounds, plus their settled results |
