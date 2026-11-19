# D-32b — Round invalidation after widespread voids (approved)

**Status: approved by the product owner (Phase 6C preparation), with the
clarifications in §3.** Nothing here is implemented yet. It is applied in Phase 6C
settlement. The partial-void settlement rules (D-32) and the fully voided entry
treatment (D-33) are approved separately and are recorded in the
[decision register](weekly_challenge_decisions.md).

This note answers one question: when are cancellations and voids so widespread
that the round as a whole stops being competitive?

## 1. What the rule must achieve

* **Simple and transparent:** one sentence a participant can check.
* **Fair:** it depends only on which predictions were tested, never on match
  *results*, so no one can benefit from how the surviving matches finish.
* **Mechanical and auditable:** computed from stored data, the same way every
  week, with no discretionary judgement.
* **Proportionate:** an ordinary weekend with a few postponements stays
  competitive. Only exceptional disruption voids a round.

## 2. The approved rule

> A round remains **competitive** only when **both** conditions hold at final
> settlement:
>
> 1. **strictly more than 50%** of all predictions belonging to the valid
>    confirmed entries at the submission deadline were settled on played results;
> 2. **at least five entries** remain eligible for the weekly ranking (that is,
>    they are not "Void — Refunded" under D-33).
>
> Exactly 50% does **not** satisfy condition 1.

**If either condition fails, the entire round is void:**
* all confirmed participants receive their original 100 virtual credits back;
* net results are zero;
* no championship points are awarded;
* no successful recoveries and no qualifying top-ten finishes are recorded;
* no competitive weekly ranking is awarded;
* the round does not advance the ten-round championship counter;
* all original submissions, fixture results, provisional settlement calculations
  and the invalidation reason are retained for history and audit.

This is the existing T-08 void-round treatment, now triggered by a defined rule
as well as by an audited operator decision.

## 3. Clarifications (approved with the rule)

| # | Clarification | How it is applied |
|---|---|---|
| 1 | Use the authoritative **locked set** of confirmed entries | The entries locked at the deadline (one per participant; the final version of any resubmission; withdrawn entries excluded). No later change alters this set |
| 2 | Count **prediction instances**, not unique fixtures | Denominator = 9 × the number of locked valid entries. A fixture picked by 40 entries contributes 40 predictions |
| 3 | A played prediction counts **whether it was correct or incorrect** | Numerator = predictions whose verdict is won or lost. Void predictions (V1–V4) are untested |
| 4 | Pending fixtures never invalidate a round | While any prediction is still pending, the rule is **not evaluated**. The settlement cutoff (`settle_cutoff_at`, D-08) bounds the wait: an unplayed match becomes void at the cutoff |
| 5 | Deterministic evaluation | Evaluated as soon as every prediction has a final verdict (won, lost or void); the result is provisional during the 24-hour correction window (R-14) and confirmed at finalisation. Integer test: competitive only if `2 × played > total` and `ranked_entries ≥ 5` |
| 6 | Exceptional operator invalidation | Requires the operator permission, an explicit written reason and an audit record (actor, time, reason, before and after designation). It is never automatic |
| 7 | Corrections trigger reassessment | A result correction re-runs settlement and re-evaluates the rule. The outcome is recorded as a new, auditable designation entry. Points and the championship counter are **derived** from the current designation, so a reassessment can never duplicate points or advance the counter twice (see §5) |

**Worked examples** (20 locked entries, so 180 predictions):

| Played | Void | Ranked entries | Test | Result |
|---|---|---|---|---|
| 120 | 60 | 20 | 240 > 180 | competitive |
| 91 | 89 | 18 | 182 > 180 | competitive |
| 90 | 90 | 17 | 180 > 180 is false | **void** (exactly 50%) |
| 150 | 30 | 4 (16 fully void) | ranked < 5 | **void** |
| 100 played, 20 pending | 60 | — | not evaluated | wait for verdicts or the cutoff |

## 4. Evidence behind the 50% threshold (simulated)

**These figures are simulated cancellation scenarios, not observed voids.**
Simulation on the real 17 Nov 2026 pool (60 fixtures; 300 random valid 4/3/2
portfolios; fixtures voided uniformly at random; void legs settle at 1.00; market
probabilities; approved payout rounding). Research script, not product code.

| Fixtures void | Share of predictions void | Entries with more than 4 of 9 void | Entries fully void | Mean P(recover 100+) |
|---|---|---|---|---|
| 0% | 0% | 0% | 0% | 0.358 |
| 10% | 9.8% | 0.0% | 0.00% | 0.367 |
| 25% | 24.9% | 3.4% | 0.00% | 0.348 |
| 40% | 40.2% | 25.4% | 0.01% | 0.339 |
| 50% | 50.2% | 50.3% | 0.07% | 0.342 |
| 60% | 59.7% | 74.7% | 0.57% | 0.373 |
| 75% | 74.9% | 96.6% | 5.72% | 0.426 |

What this shows:
* Up to roughly 40% of fixtures void, the round still tests most of what
  participants predicted, and recovery chances barely move.
* At about 50%, half of all entries have most of their predictions untested.
  Beyond that, results increasingly reflect *which fixtures were cancelled*
  rather than prediction quality: recovery becomes easier (0.43 at 75%), and
  fully void refunds start to appear.
* Void **predictions** track void **fixtures** only when voids are random. A
  cancelled fixture that many entrants picked matters far more than one nobody
  picked, which is why the rule counts prediction instances.

**Why "strictly more than half":** it is the natural majority point, not a tuned
parameter. The competition stays valid while tested predictions outnumber
untested ones. Losing one or two leagues' entire programme (each league is about
a sixth of a typical six-league pool) keeps the void share well under half.

**Why "at least five ranked entries":** it reuses the approved five-valid-entry
minimum (D-28). D-33 counts fully void entries toward that minimum at the
deadline; this second check makes sure a meaningful ranking still exists after
settlement.

### Validation on real pools (part of D-29)

The rule is validated alongside the championship scoring (D-29) on six to eight
real weekly pools collected by the scheduled odds trial. The report must keep two
kinds of evidence apart:

* **Observed voids:** the actual postponements, cancellations and abandonments in
  each captured pool, with the resulting share of void predictions and whether the
  rule would have triggered.
* **Simulated scenarios:** cancellation patterns applied artificially to the same
  pools (random, whole-league, whole-day and popular-fixture cancellations) to
  estimate how often, and how close to the threshold, the rule would fire.

Simulated results must never be presented as observed frequencies.

## 5. Implementation requirements for Phase 6C

* **Evaluation input:** the locked entry set, each entry's nine prediction
  verdicts, and each entry's D-33 status. Nothing else (no results, no gross).
* **Recording:** each evaluation stores the counts (`total_predictions`,
  `played_predictions`, `void_predictions`, `ranked_entries`), the outcome, the
  basis (`d32b`, `operator` or `deadline`), the settlement run, and, for operator
  actions, the actor and reason. Records are insert-only; the latest is current.
* **No duplication:** weekly points, recoveries, top-ten finishes and the
  championship counter are computed from the *current* designation and the
  *current* settlement, never accumulated by events. A round that moves from
  competitive to void and back produces history rows, not extra points.
* **After a championship is frozen:** a correction that would change a frozen
  round's designation goes through the audited reopen path (T-06), which
  re-freezes the championship snapshot.
* **Provisional display:** while the round is in the correction window the
  outcome is shown as provisional.

## 6. Implications accepted

* A void round returns everyone's credits, including participants who would have
  recovered or finished in the top ten. This is the cost of protecting the
  championship from results decided by cancellations.
* The rule depends on other participants' entries (popular fixtures weigh more),
  but never on results, and entries are locked at the deadline, so it cannot be
  influenced afterwards.

## 7. Alternatives considered (not adopted)

| Option | Why not adopted |
|---|---|
| Operator decision only (former MVP default) | Flexible but not transparent; identical situations could be treated differently. Retained only for exceptional cases (§3, row 6) |
| Share of **fixtures** on the round sheet void | Ignores which fixtures were picked: cancelling fixtures nobody chose would void a fair round, while a few very popular cancellations would not |
| Re-run the opening checks on surviving fixtures | Penalises small rounds: a round opened at exactly 15 fixtures would be invalidated by one postponement |
| Per-entry thresholds | Treats participants in the same round differently and complicates the ranking; D-33 already handles fully void entries |
| A lower bar such as one third void | Would void rounds whose results are still close to normal (the 25–40% rows) |

## 8. Practice rounds (D-32b-Q1, approved at the Phase 6C architecture finalisation)

The **majority-played requirement applies to practice rounds**, but the
five-ranked-entry minimum does not (a practice round has fewer than five valid
entries by definition). A practice round with 50% or fewer played predictions
becomes void: stakes returned, results shown as refunded. Practice and void
rounds earn no championship points and do not advance the championship.
