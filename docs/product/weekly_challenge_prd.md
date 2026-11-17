# Diski 9 Weekly Challenge — Product Requirements (Phase 5C)

Status: **design for review**. Nothing here is implemented.

| | |
|---|---|
| Branch | `design/weekly-challenge-phase-5c`, from `main` at v3.2.0 (`2b4dcd7`) |
| Research basis | Phase 5B, branch `research/weekly-challenge-optimisation` (`6f5a2f9`), report `docs/research/weekly_challenge_portfolio_optimisation.md` |
| Companion documents | [UX specification](weekly_challenge_ux.md) · [technical design](../architecture/weekly_challenge_design.md) · [implementation plan](weekly_challenge_implementation_plan.md) · [decision register](weekly_challenge_decisions.md) |

## 1. Product objectives

The Weekly Challenge turns Diski 9's probabilities into a weekly game that
teaches probability, uncertainty and the trade-offs of grouping bets, without
any real money.

1. **Teach by doing.** Players pick nine outcomes. They then see how 280
   different ways of grouping them change two things: the chance of getting
   their 100 credits back, and the average return the model expects.
2. **Make one idea memorable.** Once your nine picks are fixed, the way you group
   them still matters. Some groupings are strictly better than others on both
   counts; those are the "efficient" ones.
3. **Be honest.** Every figure is labelled as a Goal Model 1.0 estimate at frozen
   reference prices. Nothing is presented as a guarantee or as advice.
4. **Build a community habit.** Players come back weekly, compare results on
   weekly and season leaderboards, and review past entries.

**Out of bounds:** no real money, no prizes with cash value, no sportsbook links
or affiliate codes, no staking advice, and no adjustable stakes.

## 2. Target users

| User | Needs | Implication |
|---|---|---|
| **Casual football fan** (primary) | Fun, quick, understandable; knows teams, not probability theory | Plain language, one central chart, a recommended choice, details on demand |
| **Engaged Diski 9 user** | Already uses the Screener and Match Lab; curious about models | Links back to Match Lab, model and market probabilities, an expandable "how it's calculated" |
| **Competitive player** | Leaderboards, history, fairness | Transparent, deterministic scoring; immutable entries; a clear deadline |
| **Operator** (the project owner) | Run rounds safely with little effort | Simple CLI round lifecycle, scheduled jobs, an audit trail, idempotent settlement |

## 3. Confirmed decisions (MVP)

These are fixed for the MVP unless a mathematical or technical contradiction is
found. None was found (§9).

| Component | Decision |
|---|---|
| Weekly allocation | 100 virtual credits |
| Selections | Exactly 9, on 9 distinct fixtures |
| Outcomes | Home / Draw / Away, BTTS Yes / No, Over / Under 2.5 |
| Structure | 3 buckets of 3 selections, plus one nine-fold of all 9 |
| Stakes | **30 / 30 / 30 / 10**, fixed; not adjustable; no allocation helper |
| Arrangements | All 280; dominated ones visible but disabled; efficient ones selectable |
| Chart | X = probability of recovering 100 credits; Y = expected gross return (credits) |
| Recommendation | The efficient portfolio with the highest recovery probability. Ties: higher expected return, then lowest canonical partition ID |
| Model | Goal Model 1.0 (k_s 12, k_t 96, m0 30), unchanged |
| Odds | Existing v3.2.0 consensus; Challenge-eligible = fresh with ≥ 3 independent bookmaker groups |
| Weekly leaderboard | Net virtual credits (gross returned − 100) |
| Real money | None |

## 4. User journeys

### 4.1 First entry: the core journey

1. **Discover.** From the Screener header, open **Weekly Challenge**. See this
   week's round, its deadline in local time, and a two-line explanation.
2. **Pick nine.** Browse the round's eligible fixtures, filtered by league and
   day. Tap an outcome chip, which shows the model probability and reference
   odds. A slip tray tracks progress (`6 of 9`). Tapping another outcome on the
   same fixture replaces the earlier pick.
3. **Explore groupings.** Tap **Explore groupings**. The chart shows all 280
   arrangements: grey ones are dominated, coloured ones efficient, and a star
   marks the recommended one, which is pre-selected. Tap other efficient points
   to compare; a panel shows the three buckets and the nine-fold.
4. **Review.** Tap **Review entry**. See the nine picks, the chosen grouping,
   the summary (100 credits allocated, recovery probability, expected return,
   maximum return) and the plain-language caveats.
5. **Submit.** Tick "I understand credits are virtual and these figures are
   model estimates", then **Submit entry**. A receipt shows the entry, the
   submission time and the lock time.
6. **Before the deadline:** the player may reopen, change and resubmit. Each
   submission is kept; the latest one counts.
7. **After the deadline:** the entry is locked. Matches play out.
8. **Results.** As fixtures finish, **My Challenge** shows each selection as won,
   lost, void or pending, each bucket as won or lost, and the gross and net
   credits. Leaderboards update once the round settles.

### 4.2 Returning player

Open **My Challenge**: the current round's status, the last round's result,
season position and history. Then start this week's entry.

### 4.3 Viewer without an account

They can see the explanation, this round's fixtures and the public leaderboards.
Creating an entry requires signing in (identity model: decision D-01).

### 4.4 Operator

1. Refresh data and odds (the existing workflow).
2. **Publish** the round, which freezes the round sheet of eligible picks.
3. The round locks automatically at its deadline.
4. Settlement jobs run after results refresh.
5. Review the settlement report, then finalise the round.

## 5. Functional requirements

### 5.1 Challenge rounds

* FR-R1. Rounds are configurable records with a window, publish (snapshot) time,
  deadline, settlement cutoff and status.
* FR-R2. MVP cadence: one **weekend round** per week (Friday 00:00 to Monday
  23:59, UTC window; configurable). Midweek rounds are a future extension.
* FR-R3. Fixtures in the eight supported leagues whose kickoff falls inside the
  window at publish time belong to the round.
* FR-R4. **One common deadline** (Option A), fixed when the round is published:
  the earliest kickoff among the round's eligible fixtures, minus a buffer
  (recommended 15 minutes). After the deadline, no submission or change is
  accepted.
* FR-R5. All timestamps are stored in UTC and displayed in the viewer's time zone
  (browser-detected, with the app's configured zone as fallback).
* FR-R6. A round needs at least 9 eligible fixtures to open. Otherwise it is not
  published, and the page says why.

### 5.2 Eligibility and the round sheet

* FR-E1. At publish time the system freezes a **round sheet**: for every round
  fixture and supported outcome, the Goal Model 1.0 probability, the consensus
  odds, the market-implied probability, the number of bookmaker groups and the
  observation and provider timestamps.
* FR-E2. An outcome is **Challenge-eligible** only if its market had a fresh
  consensus from ≥ 3 independent bookmaker groups at publish time
  (`challenge_consensus`, the existing strict rule) and the fixture has an
  available Goal Model 1.0 forecast.
* FR-E3. The picker shows **only fixtures with at least one eligible outcome**,
  plus a one-line count of the round's other fixtures with an expandable reason
  ("no qualifying reference odds"). Statistical analysis of every fixture stays
  in the Screener.
* FR-E4. The round sheet is never recalculated. Every player builds from the same
  frozen inputs.

### 5.3 Selection

* FR-S1. Exactly 9 selections on 9 distinct fixtures; one outcome per fixture. A
  second outcome on the same fixture **replaces** the first; it never adds.
* FR-S2. Selections can be removed or replaced before submission. The slip shows
  progress toward 9.
* FR-S3. Only eligible outcomes on the round sheet can be selected.
* FR-S4. A fixture whose kickoff moves before the deadline after publication
  becomes unselectable as soon as the change is known.

### 5.4 Portfolio explorer

* FR-P1. With 9 selections, the system evaluates all 280 canonical partitions at
  30/30/30/10, using the exact eight-state distribution.
* FR-P2. For each partition it calculates:
  * per bucket: combined odds, win probability, potential payout;
  * nine-fold: combined odds, win probability, potential payout;
  * expected gross and net return;
  * probability of recovering 100, probability of profit, probability of a
    complete loss;
  * SD (internal only);
  * efficiency.
* FR-P3. Pareto efficiency is on (recovery ↑, expected return ↑), with the
  documented tolerances.
* FR-P4. The chart shows all 280: dominated points grey and not selectable,
  efficient points selectable, the recommended point starred and pre-selected.
  Nothing is smoothed.
* FR-P5. Identical coordinates are drawn as one point labelled with the number of
  arrangements, and the player can choose among them.
* FR-P6. An accessible list of efficient arrangements mirrors the chart.
* FR-P7. Selecting a point never submits. Submission happens only on the review
  step, with explicit confirmation.

### 5.5 Recommendation

* FR-Rec1. Recommended = the efficient arrangement with the highest recovery
  probability. Ties: higher expected gross return, then the lowest canonical
  partition ID. It is always efficient (§9).
* FR-Rec2. Explanation shown: "Recommended because it has the highest modelled
  probability of recovering your 100 weekly credits." Shown with its expected
  return and the uncertainty note.

### 5.6 Submission

* FR-Sub1. Each user has one entry per round. Submissions are insert-only
  versions; the latest version before the deadline is the entry.
* FR-Sub2. Every submission stores an immutable snapshot: the round sheet values
  for its nine selections, the partition, buckets, stakes, the metrics at
  submission, the efficient set and the recommended ID, the calculation version
  and timestamps.
* FR-Sub3. Server-side validation of every rule. Client state is never trusted.
* FR-Sub4. Duplicate clicks and concurrent requests produce exactly one new
  version (an idempotency key, plus optimistic versioning).
* FR-Sub5. At the deadline the entry locks: its final submission is fixed and can
  never change.

### 5.7 Settlement

* FR-Set1. Selections settle on the **90-minute result** (regular time including
  stoppage time). Extra time and penalties are ignored.
* FR-Set2. Void rules for postponed, cancelled, abandoned, awarded and walkover
  fixtures, for a kickoff moved before the deadline, and for fixtures not
  completed by the settlement cutoff (technical design §7). A void selection
  counts as odds 1.00 in its accumulators.
* FR-Set3. Settlement is deterministic, idempotent and audited. A round stays
  *settling* until every selection is settled or void, then becomes *final*
  after a correction window.
* FR-Set4. Accumulator payouts are computed exactly and rounded half-up to 0.01
  credit.

### 5.8 Leaderboards and history

* FR-L1. **Weekly:** the round's entrants ranked by net credits, high to low. Ties
  share a rank. Provisional until the round is final.
* FR-L2. **Season:** decision D-09 (recommended: average net credits per round
  entered, qualifying at ≥ 50% of completed rounds and at least 3 entries; see
  the decision register). Columns: rounds entered, total net, average net.
* FR-L3. Non-entrants are not ranked in a weekly table.
* FR-L4. **My Challenge:** current entry, past entries with selection-level
  results, season summary.

### 5.9 Communication

* FR-C1. The fixed caveats appear on the explorer and review steps (UX §8).
* FR-C2. Banned phrasing: guaranteed, safe bet, sure win, risk-free, lock, banker,
  free money.
* FR-C3. Market-implied probability is shown per selection in details, never on
  the chart axes.

## 6. Non-functional requirements

* **Correctness:** exact eight-state maths; integer credits; exact decimal
  payouts; deterministic tie-breaks; the 20→100 scaling invariants are tested.
* **Determinism:** the same round sheet and the same nine selections always give
  the same 280 results, efficient set and recommendation.
* **Immutability:**
  * round-sheet, submission and settlement-history rows are insert-only, enforced
    by database triggers (the `forecast_snapshots` pattern);
  * locked entries never change.
* **Performance:** the 280 evaluations plus the frontier take well under 100 ms,
  in pure Python. Chart interactions make no API requests.
* **Security:**
  * authenticated submissions;
  * server-side validation and deadline checks against server time;
  * no secrets in the client.
* **Accessibility:**
  * keyboard-operable list alternative to the chart;
  * colour is never the only signal;
  * WCAG AA contrast in both themes.
* **Responsiveness:** usable at 390 px width; no horizontal page scroll.
* **Privacy:** leaderboards show display names only. Policy in decision D-04.
* **Operability:**
  * every lifecycle step is available as a CLI command with clear output;
  * jobs are idempotent and safe to rerun.
* **No regression:** the Screener, Match Lab, odds, Edge/EV and Goal Model 1.0
  are unchanged.

## 7. MVP scope and exclusions

**In scope:**
* weekend rounds;
* round sheet;
* picker;
* explorer;
* recommendation;
* review, submit and resubmit before the deadline;
* lock;
* settlement with void rules;
* weekly and season leaderboards;
* My Challenge history;
* operator CLI;
* sign-in (per the identity decision).

**Excluded from the MVP:**
* adjustable stakes or any allocation helper;
* a variable nine-fold stake;
* midweek or multiple concurrent rounds;
* per-fixture deadlines;
* private leagues or friends;
* notifications;
* prizes;
* market-implied expected return on the chart;
* social sharing images;
* admin web UI (the CLI only);
* new markets or providers;
* any change to Goal Model 1.0 or the odds methodology.

## 8. Acceptance criteria (product level)

1. A signed-in user can build, explore, review and submit a valid entry before
   the deadline, and sees it in My Challenge.
2. Invalid entries (fewer than 9, duplicate fixtures, ineligible outcomes, a
   dominated grouping, after the deadline) are impossible to submit, including
   via direct callback calls.
3. The chart shows exactly 280 arrangements, efficiency is correct, and the
   recommended point is efficient and matches the rule.
4. All displayed metrics match the reference implementation for the frozen
   inputs. Scaling to 100 credits preserves recovery, scales expected return,
   SD and net by 5, and keeps the efficient set.
5. Submissions and the round sheet are immutable. Resubmission creates a new
   version. A locked entry never changes.
6. Settlement produces the specified results for each market and void case, and
   rerunning it changes nothing.
7. Weekly and season leaderboards match hand-calculated examples, including ties
   and skipped rounds.
8. The whole existing test suite still passes. The Screener and Match Lab are
   unchanged. Goal Model 1.0 is unchanged.

## 9. Mathematical consistency check (100-credit scaling)

Phase 5B used 6 / 6 / 6 / 2 with a 20-credit threshold. The MVP uses
30 / 30 / 30 / 10 with 100, a uniform factor of 5.

* **Returns:** in every one of the eight states, R₁₀₀ = 5·R₂₀. Therefore:
  * E[R₁₀₀] = 5·E[R₂₀];
  * σ₁₀₀ = 5·σ₂₀;
  * net₁₀₀ = 5·net₂₀.
* **Recovery:** R₁₀₀ ≥ 100 ⇔ R₂₀ ≥ 20, so P(recover) is unchanged.
* **Efficiency:** the x-coordinates are unchanged and every y-coordinate is
  multiplied by the same positive constant. So dominance, and therefore the
  efficient set and the recommended portfolio, are unchanged.
* **Checked numerically** on all 17 Phase 5B slates (13 synthetic, 4 real):
  * recovery probabilities bitwise identical;
  * E[R] and SD scaled by 5 (relative error below 1e-12);
  * efficient sets identical (1–14 efficient arrangements, or all 280 for
    identical selections);
  * recommended arrangement identical in every slate.
* **The recommendation rule is always efficient.** The arrangement with the
  maximum recovery probability (ties broken by higher expected return) cannot be
  dominated: a dominator would need higher recovery, or equal recovery and higher
  expected return.
* **No contradiction found.**
* **One Phase 5B finding the product must respect:** the identity of the best
  arrangement is sensitive to small model-probability changes. The UI therefore
  frames "efficient" and "recommended" as conditional on the model (UX §8).
