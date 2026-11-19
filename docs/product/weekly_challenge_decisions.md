# Diski 9 Weekly Challenge — Decision Register (revised, Phase 6C preparation)

**Phase 6C preparation (owner review):** D-32b (round invalidation after
widespread voids) approved with clarifications; see the
[D-32b note](weekly_challenge_d32_round_invalidation.md). Its validation on real
pools is added to D-29. The remaining outstanding decisions, and new items found
during Phases 6A and 6B, are reviewed in the
[outstanding decision review](weekly_challenge_phase6c_decision_review.md); none
of them is approved by that review. Architecture questions for Phase 6C are in
[Phase 6C architecture considerations](../architecture/phase6c_architecture_considerations.md).

**Phase 6B close-out (owner review):** D-33 approved; D-32 settlement rules
approved; D-29 remains an open validation requirement with an approved approach.
The technical backlog for the next phases is in the implementation plan.

This register supersedes the Phase 5C register (`2e079ba`) and the Phase 6A.2
version (`6d5b47f`). IDs are kept, so history can be traced. Superseded items are
listed at the end.

**Legend:**
* **Approved:** decided by the owner.
* **Provisional (empirical):** supported by the Phase 6A.1/6A.2 synthetic
  simulations, still to be confirmed on 6–8 captured real round pools.
* **Proposed (technical):** Claude's recommendation for an implementation detail.
  It is adopted unless the owner objects.
* **Outstanding:** needs an owner decision before the named phase.

## Approved by the owner

| ID | Decision |
|---|---|
| C-01 | 100 virtual credits per completed round; 9 selections on 9 distinct fixtures; markets 1X2, BTTS and Over/Under 2.5 |
| C-06 | Goal Model 1.0 unchanged; existing strict consensus and eligibility (≥ 3 bookmaker groups, fresh within 24 h) |
| C-07 | Weekly leaderboard by net virtual credits; no real money, prizes, affiliate links or staking advice |
| C-08 | "Your Payout Probability" chart kept: cumulative step view plus exact-payout view; the 100-credit value equals the summary; the nine-fold only in the all-win state; credits, never percentages, on the x axis |
| C-09 | **Broad-60 buckets by margin-adjusted market probability at full precision:** A Foundation 60–95% inclusive; B Balanced 40% to < 60%; C Challenger 20% to < 40%. Outcomes outside 20–95% are not eligible |
| C-10 | **Strict structure:** exactly 4 A, 3 B and 2 C picks, plus the nine-fold "The Diski 9"; no flexible counts |
| C-11 | **Fixed credits:** 40 / 30 / 20 / 10; no adjustable stakes |
| C-12 | Configuration is versioned (`broad60-432-v1`); a change means a new version, never an in-place edit |
| C-13 | No 280 groupings, no efficient frontier, no recommendation. The Phase 6A engine is kept as a baseline and generalised |
| C-14 | Eight-state maths and D-15 rounding kept; market-based and model-based estimates shown separately, never mixed |
| C-15 | Bucket tracker: Foundation X/4, Balanced X/3, Challenger X/2, Total X/9 |
| C-16 | Permanent "Explore Your Bucket Risk" feature with hypothetical probabilities and fair odds, never linked to the participant's portfolio |
| C-17 | Incomplete portfolios show only completed-bucket figures, clearly distinguished; portfolio analytics only at 9/9 |
| C-18 | No championship or season explorer |
| C-19 | **Championships:** exactly 10 completed rounds, then reset; join any time; every round counts; nothing carries forward |
| C-20 | **Recovery-gated weekly points:** gross ≥ 100.00 (inclusive) is required for any points; gross < 100 or no entry scores 0; points are non-additive; maximum 150 per round. "No recovery, no championship points." The schedule itself is D-31 |
| C-21 | **Weekly ranking** by realised net (equivalently settled gross); **championship ranking** by cumulative championship points |
| D-26 | **Weekly ties (approved Phase 6A.2.1): standard competition ranking.** Rank = 1 + the number of entrants with a strictly greater settled gross (exact, 0.01). Tied entrants share the rank and **each receives that rank's full points**; later ranks are skipped (350, 350, 290 → 1, 1, 3 → 150, 150, 125). More than ten entrants may receive top-ten points. No averaging; no timestamp, ID or other tie-breaks. Tied entrants below 100.00 get 0. Points are whole numbers |
| D-27 | **Championship ties (approved):** total points → successful recoveries → qualifying top-ten finishes (rank ≤ 10, gross ≥ 100.00, championship-eligible round) → joint position under standard competition ranking (joint champions allowed). Cumulative gross or net credits are never a tie-break |
| D-28 | **Operational thresholds (approved):** a round opens only with ≥ 15 eligible fixtures, ≥ 3 eligible leagues and an exact strict 4/3/2 feasibility check (existing freshness and ≥ 3 bookmaker-group rules unchanged). A round counts toward the championship only with **≥ 5 valid entries** (distinct participants with a locked, complete, valid final submission at the deadline; resubmissions count once). Otherwise it is a **practice round**: it settles, shows results and a weekly table, awards no points, doesn't affect tie-breakers and doesn't advance the counter. Practice results are kept separately |
| D-30 | **Championship continuation (approved):** a championship is always ten completed championship-eligible rounds, independent of league seasons and calendar quarters. Breaks, end of season or unavailable pools **pause** it with points preserved; it is never shortened and no champion is crowned early. After ten rounds: finalise, archive, record the champion(s), reset. Join any time; all ten rounds count; history and lifetime statistics kept |
| D-31 | **Approved for the MVP (Phase 6A.3): Scenario D, `points-150-75-v2`.** Ranks 1–10 earn 150/135/125/120/115/110/105/100/95/90, any other recovery 75, no recovery 0; D-26 ties; maximum 150 per round and 1,500 per championship. Implemented in `diski9.challenge.scoring`. The incentive evidence is simulated (D-29); approval does not claim real-world incentives are eliminated |
| D-15 | Settlement precision: each accumulator rounded half-up to 0.01; state gross = sum; recovery = gross ≥ 100.00 (approved in Phase 6A) |
| D-32 | **Partially voided portfolios (approved, Phase 6B close-out):** a voided prediction settles at decimal odds 1.00; all other predictions settle normally; a bucket containing an incorrect, non-voided prediction pays 0; bucket payouts, including The Diski 9, are recalculated with the adjusted odds; the approved payout rounding (D-15) is retained; an entry recovering at least 100.00 credits stays eligible for championship points in a competitive round, except a fully voided entry (D-33); no replacement predictions after the submission deadline. Whole-round invalidation is D-32b |
| D-33 | **Entire portfolio voided (approved, Phase 6B close-out):** when all nine predictions of a confirmed portfolio are void: gross returned 100.00; net 0.00; championship points 0; excluded from the weekly ranking (other entrants ranked as if it were absent); no successful recovery and no qualifying top-ten finish recorded; settlement status "Void — Refunded"; the entry counts toward the five-valid-entry minimum assessed at the deadline, subject to the round-invalidation rule (D-32b); the portfolio and its settlement record are retained for history and audit. The participant is neither penalised nor rewarded for predictions that were never tested. Implemented in the scoring engine as `AllVoidPolicy.REFUND_UNRANKED` (the default of `points-150-75-v2`) |
| D-32b | **Round invalidation after widespread voids (approved, Phase 6C preparation):** a round remains competitive only when, at final settlement, **(1)** strictly more than 50% of all predictions belonging to the valid confirmed entries locked at the deadline were settled on played results (exactly 50% fails), and **(2)** at least five entries remain eligible for the weekly ranking (not "Void — Refunded"). Otherwise the whole round is void: every confirmed participant gets the original 100 credits back; net 0; no championship points, recoveries, qualifying top-ten finishes or competitive weekly ranking; the championship counter does not advance; submissions, results, provisional settlement calculations and the invalidation reason are retained. Clarifications: the authoritative locked entry set is used; prediction instances are counted, not unique fixtures; played predictions count whether correct or incorrect; pending fixtures never invalidate a round (the rule is evaluated only when every prediction has a final verdict, and the settlement cutoff bounds the wait); evaluation is deterministic and provisional until the R-14 correction window ends; an exceptional operator invalidation needs the operator permission, an explicit reason and an audit trail; a result correction triggers an auditable reassessment that can never duplicate points or advance the counter twice. Validation on real pools is part of D-29, keeping observed voids separate from simulated cancellations. Detail: [D-32b note](weekly_challenge_d32_round_invalidation.md). Sub-question D-32b-Q1 (practice rounds) is outstanding |

## Provisional (empirical) — synthetic evidence, to confirm on real pools

Evidence: [championship scoring research](../research/weekly_challenge_championship_scoring.md)
and [risk-structure research](../research/weekly_challenge_risk_structure.md).

| ID | Finding | Status |
|---|---|---|
| P-01 | Under the preferred schedule (D-31), championship points track **recoveries** (Spearman 0.94–0.99 from 5 to 1,000 entrants); the champion's best round is 14–21% of their total | Provisional (6A.2.1) |
| P-02 | Recovery-focused selection is favoured at every field size (1.56–2.97× its share); lowest-in-band never exceeds proportional (max 1.04 ± 0.16 at 100 entrants) | Provisional (6A.2.1) |
| P-03 | Cumulative net is close to a lottery; F1-style rewards variance in large fields; percentile rewards low-variance finishes without recovery (Phase 6A.2) | Provisional |
| P-04 | The old 50-floor schedule rewarded high variance at 50–100 entrants (lowest-in-band 1.43–1.86×). The 75 floor removes this; the compressed top ten adds a further gain at 10–25 entrants. Paired (CRN) reductions are significant from 10 to 500 entrants | Provisional (6A.2.1) |
| P-05 | The weekly tie rule has a negligible effect on incentives (paired differences within Monte Carlo error). Ties crossing the top-ten boundary occur in 4–11% of rounds at 50+ entrants; first-place ties in ~1% | Provisional (6A.2.1) |
| P-06 | The real weekend pool passes every opening check; 15-fixture random sub-pools open 99.75% of the time (Phase 6A.2) | Provisional |
| P-07 | Points are never negative, so skipping a round can never help; late joiners finish lower on average, as intended (Phase 6A.2) | Provisional |
| P-08 | Full-points ties are **duplication-neutral**: a duplicated portfolio earns what it would earn if entered once; average-points ties penalised duplicates. Duplicated portfolios almost never win championships | Provisional (6A.2.1) |
| P-09 | A trailing participant gains nothing significant by switching to high variance in rounds 8–10 under the preferred schedule (it did at 100 entrants under the old one) | Provisional (6A.2.1) |
| P-10 | Joint champions become common in very large fields under the 75 floor (19% at 500, 27% at 1,000 entrants), driven by the floor, not the tie rule | Provisional (6A.2.1) |

## Proposed (technical) — adopted unless you object

| ID | Proposal | Rationale |
|---|---|---|
| T-01 | Generalised engine `ChallengeConfig` (bands, sizes, stakes, classification source); the 6A 3/3/3 config kept as a legacy regression vector | Reuses tested 6A code; one source of truth |
| T-02 | Bucket derived server-side from the stored full-precision `market_prob`; the client never sends a bucket | Integrity; no boundary disputes from display rounding |
| T-05 | Points stored as integers; championship standings computed by aggregation, plus a frozen snapshot at completion (replaces the fraction storage needed only by the superseded average-points rule) | Corrections re-score automatically |
| T-07 | Round **designation** fixed at the deadline: `championship` / `practice` / `postponed` / `void`. Afterwards a round can become void only through the approved D-32b rule at final settlement (which depends on which predictions were tested, never on results) or an audited operator action | Designation must not depend on match results |
| T-08 | **Void round:** a round cancelled or invalidated as a whole after the deadline returns every stake and does not count (no points, counter unchanged). Partial voids settle normally under D-32; widespread voids invalidate a round under the approved D-32b rule | Prevents an all-void round handing every entrant 100.00, a recovery and a shared first place (150 points each) |
| T-06 | Any settlement correction re-scores the whole round; after a championship is frozen, only the audited `--reopen` path | Positions depend on all entrants |
| R-01 | Common deadline: earliest eligible kickoff minus 15 minutes | Unchanged from 5C |
| R-02 | Round sheet frozen at publish | Unchanged |
| R-03 | Picker lists only eligible outcomes, with a count of the hidden fixtures | Unchanged |
| R-04 | One entry per user per round, resubmittable until the deadline | Unchanged |
| R-06 | Dependency-free production maths with exact decimals | Unchanged |
| R-07 | Settle on the 90-minute score | Unchanged |
| R-08 | Void selection = odds 1.00; an all-void bucket returns its own stake (40 / 30 / 20); a fully void portfolio follows D-33 (refunded, unranked, not a recovery) | Updated for unequal stakes; consistent with D-32 and D-33 |
| R-09 | Same as D-15 | Unchanged |
| R-11 | Routes `/challenge`, `/challenge/learn`, `/challenge/me`, `/leaderboards` | Adds the learn page |
| R-14 | 24-hour correction window before a round is final | Unchanged |
| T-09 | **Server-side withdrawal (new):** only before the deadline; an insert-only withdrawal record; a withdrawn entry is not in the locked set (does not count for D-28 or D-32b); the participant may submit again before the deadline | The prototype withdrawal is a browser note only |
| T-10 | **Your View storage (new):** private per user and fixture, with the Phase 6B.3 model-context stamp; never used for submission, settlement or scoring; deleted with the account | Keeps Your View educational and separate from the competition |
| T-11 | **Designation history and derived counters (new):** designations are insert-only records with a basis (`deadline`, `d32b`, `operator`) and reason; the latest is current. Championship round numbers, the counter, points and standings are derived from current designations and settlements | D-32b reassessments and corrections can never duplicate points or advance the counter twice |

## Outstanding — owner decision needed

The "Needed" column uses the owner-confirmed phases (Phase 6C contains the
backend work previously lettered 6E–6G). Options, trade-offs and rationale for
each item are in the [outstanding decision review](weekly_challenge_phase6c_decision_review.md).
A recommendation is not an approval.

| ID | Question | Recommendation | Needed |
|---|---|---|---|
| D-01 | Identity and sign-in | In-app OpenID Connect with a managed provider; no passwords stored (revises the earlier reverse-proxy recommendation) | Before Phase 6C |
| D-02 | Hosting | One small managed container host with a managed database in the same region; 6C stays host-agnostic | Constraints before 6C; provider by Phase 10 |
| D-03 | Database for hosted use | PostgreSQL in production, SQLite for local work and tests (multiple web workers are likely at launch) | Before Phase 6C |
| D-04 | Leaderboard privacy | Public display names with an opt-out shown as "Private participant" | Default before 6C; wording before Phase 10 |
| D-05 | Display-name policy | 3–24 characters; unique; blocklist; one change per 30 days; name history; operator rename | Before Phase 6C |
| D-06 | Deadline buffer | 15 minutes (already in use under R-01 and FR-R3), stored per round | Before Phase 6C |
| D-08 | Settlement and void rules `settle/v1` (void codes V1–V5, 48-hour cutoff). The payout treatment of voids is decided by D-32, D-33 and D-32b | Accept as specified | Before Phase 6C settlement |
| D-11 | Round calendar | Weekend window; publish Thursday 06:00 UTC; postpone when the opening checks fail; midweek rounds deferred | Defaults before Phase 6C |
| D-12 | PSL coverage (no qualifying odds; the odds trial has found 0 priced PSL fixtures) | Accept for the MVP and state it in the UI | Phase 6D (copy) |
| D-29 | **Championship scoring validation (open validation requirement; approach approved at the Phase 6B close-out):** keep collecting real weekly fixture pools and reference odds; validate the championship scoring system on six to eight real weekly pools, assessing fixture availability, round feasibility, scoring fairness, recovery rates, participant behaviour and the effect of growing competition size. **Also validate the D-32b rule** on the same pools, reporting observed voids separately from simulated cancellation scenarios. The approved scoring (D-31, `points-150-75-v2`) is retained unless the research gives compelling evidence for an amendment. Not a blocker for continued development. Note: the scheduled odds trial covers only the EPL and PSL and ends on 21 November; full eight-league weekly pools need a weekly capture after it (needs approval) | Approach approved; approve a weekly full-pool capture | Before the first official public championship |
| D-32b-Q1 | Should the D-32b test also apply to practice rounds? | Yes, for one consistent settlement path | Deferrable |
| D-34 | Roles and permissions (new) | `participant`, `operator`, `owner`; capabilities checked server-side; operator actions need a reason and audit; premium access is an entitlement, not a role | Before Phase 6C |
| D-35 | Result corrections and operator overrides (new) | Provider results by default; audited operator override stored as a new result observation | Before Phase 6C settlement |
| D-36 | Account deletion and data retention (new) | Pseudonymise on deletion; keep settlement records as "Former participant"; delete Your View | Schema before 6C; policy before Phase 10 |
| D-37 | Eligibility, terms and responsible engagement (new) | 18+ self-declaration; terms version accepted and stored | Before Phase 10 |
| D-38 | Start of the first official championship (new) | Beta rounds unofficial; championship 1 starts after D-29 | Before Phase 10 |

## Superseded Phase 5C items

| Old ID | Old decision | Superseded by |
|---|---|---|
| C-02 | 3 buckets × 3 picks; 30/30/30/10 | C-09, C-10, C-11 |
| C-03 | All 280 arrangements shown; dominated ones disabled | C-13 |
| C-04 | Frontier chart (recovery × expected return) | C-13 |
| C-05 | Recommended = efficient with the highest recovery | C-13 |
| R-05 | Store all 280 points per submission | Design §4.3: inputs plus 8 states only |
| R-10 | Weekly ties share a rank, net only | D-26 (shared position plus averaged points) |
| R-12 | Market probability shown only in tooltips | C-09 (market probability decides the bucket and is always shown) |
| R-13 | Frontier marker and tie rules | C-13 |
| R-15 | Payout chart under the selected grouping | C-08 (kept, under the complete portfolio) |
| D-07 | Edit policy | Folded into R-04 (unchanged) |
| **D-09** | Season scoring: average net per round entered, with a qualification threshold | **C-19, C-20, D-27:** 10-round championships with recovery-gated points |
| D-10 | Market-implied expected return omitted from the MVP | C-14 (market and model shown separately) |
| D-13 | Season definition (Aug–May) | C-19 (championships of 10 completed rounds) |
| C-20 (6A.2 schedule) | 150/135/120/110/100/95/90/85/80/75, 50 outside the top ten | D-31 (`points-150-75-v2`), approved Phase 6A.3 |
| D-26 (6A.2 proposal) | Average-points weekly ties with exact fractions (e.g. 63.75) | D-26 approved: standard competition ranking, full points, integers |
| T-03, T-04 (6A.2) | Proposed opening checks and 5-entrant minimum | D-28 approved |
| T-05 (6A.2) | Points stored as exact fractions | T-05 revised: integers |
| D-28 (6A.2) | "Confirm D-26, D-27, T-03 and T-04" | D-26, D-27, D-28 approved |
| D-30 (6A.2) | Copy for a championship cut short | D-30 approved: pause, never shorten |
| D-14 | Merge Phase 5B research | Not needed: 6A.1/6A.2 research is stdlib-only and self-contained |
