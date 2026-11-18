# D-32 — Recommendation: when widespread voids invalidate a whole round

**Status:** recommendation for product-owner review before Phase 6C. Nothing here
is implemented. The partial-void *settlement* rules of D-32 are approved and are
recorded in the decision register; this note covers only the remaining question:
when should cancellations and voids be so widespread that the round as a whole
stops being competitive?

## 1. What a rule must achieve

* **Simple and transparent:** one sentence a participant can check.
* **Fair:** it must not depend on match *results* (no one can benefit from how the
  surviving matches finish), only on which predictions were tested at all.
* **Mechanical and auditable:** computed once from stored data, the same way
  every week, with no discretionary judgement.
* **Proportionate:** an ordinary weekend with a few postponements must stay
  competitive; only exceptional disruption should void a round.

## 2. Evidence: what widespread voids do to a round

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
  participants predicted and recovery chances barely move.
* At about 50%, half of all entries have most of their predictions untested.
  Beyond that, results increasingly reflect *which fixtures happened to be
  cancelled* rather than prediction quality: recovery becomes easier (0.43 at 75%),
  and fully-void refunds start to appear.
* The share of void **predictions** tracks the share of void **fixtures** when
  voids are random, but not when they are concentrated: a cancelled fixture that
  many entrants picked matters far more than one nobody picked. A rule based on
  predictions measures what actually went untested.

## 3. Recommended rule: "most predictions must be tested"

> A round remains competitive only if, at final settlement, **more than half of
> all confirmed predictions in the round were settled on a played result**, and
> **at least five entries remain ranked** (that is, not "Void — Refunded").
> Otherwise the whole round is void: every participant's 100 credits are
> returned, no championship points are awarded and the championship counter does
> not advance (existing T-08 treatment).

**How it is applied**

* Counted over all valid confirmed portfolios fixed at the deadline (each entry's
  nine predictions; resubmissions count once).
* Evaluated once, automatically, when settlement becomes final (after the R-14
  correction window), and recorded with the round's settlement audit trail.
* The operator's existing audited power to void a round that was cancelled as a
  whole (T-07/T-08) is unchanged; the rule removes the need for judgement in the
  partial case.
* If the round stays competitive, everything settles under the approved D-32
  rules, and fully-void entries follow D-33.

**Why "more than half"**

* It is the natural majority point, not a tuned parameter: the competition stays
  valid while tested predictions outnumber untested ones.
* The evidence above places it where the round's character changes: below it,
  outcomes and recovery rates are close to normal; around and above it, most
  entries are decided by a minority of their own predictions.
* It tolerates realistic disruption: losing one or two leagues' entire
  programme (each league is roughly a sixth of a typical 6-league pool) keeps the
  void share well under half.

**Why "at least five ranked entries"**

* It reuses the approved five-valid-entry minimum (D-28) rather than adding a new
  number. D-33 counts fully-void entries toward that minimum at the deadline; this
  second check simply ensures a meaningful ranking still exists after settlement.

## 4. Alternatives considered

| Option | Why not recommended |
|---|---|
| Operator decision only (current MVP default) | Flexible but not transparent; identical situations could be treated differently |
| Share of **fixtures** on the round sheet void (e.g. more than half) | Ignores which fixtures were actually picked: cancelling fixtures nobody chose would void a fair round, while a few very popular cancellations would not |
| Re-run the opening checks on the surviving fixtures | Penalises small rounds: a round opened at exactly 15 fixtures would be invalidated by a single postponement |
| Per-entry thresholds (void only heavily affected entries) | Treats participants in the same round differently and complicates the ranking; D-33 already handles the extreme (fully void) case |
| A lower bar such as one third void | Would void rounds whose results are still close to normal (see the 25–40% rows), costing participants valid recoveries |

## 5. Implications to accept

* A void round returns everyone's credits, including participants who would have
  recovered or finished in the top ten. This is the cost of protecting the
  championship from results decided by cancellations.
* The rule depends on other participants' entries (popular fixtures weigh more),
  but never on results, and entries are locked at the deadline, so it cannot be
  influenced afterwards.
* Recommend confirming the frequency of triggering on the real weekly pools
  collected for D-29 (historical postponement rates) before the first official
  championship.

## 6. Decision requested

Approve the rule in §3 (with the 50% majority and the five-ranked-entry check),
or choose an alternative from §4, before Phase 6C settlement design is finalised.
