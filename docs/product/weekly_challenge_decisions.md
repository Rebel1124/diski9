# Diski 9 Weekly Challenge — Decision Register (revised, Phase 6A.2.1)

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
| D-15 | Settlement precision: each accumulator rounded half-up to 0.01; state gross = sum; recovery = gross ≥ 100.00 (approved in Phase 6A) |

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
| T-07 | Round **designation** fixed at the deadline: `championship` / `practice` / `postponed` / `void`. Only an audited operator action can void a round afterwards | Designation must not depend on match results |
| T-08 | **Void round:** a round cancelled or invalidated as a whole after the deadline returns every stake and does not count (no points, counter unchanged). Partial voids settle normally under `settle/v1` | Prevents an all-void round handing every entrant 100.00, a recovery and a shared first place (150 points each) |
| T-06 | Any settlement correction re-scores the whole round; after a championship is frozen, only the audited `--reopen` path | Positions depend on all entrants |
| R-01 | Common deadline: earliest eligible kickoff minus 15 minutes | Unchanged from 5C |
| R-02 | Round sheet frozen at publish | Unchanged |
| R-03 | Picker lists only eligible outcomes, with a count of the hidden fixtures | Unchanged |
| R-04 | One entry per user per round, resubmittable until the deadline | Unchanged |
| R-06 | Dependency-free production maths with exact decimals | Unchanged |
| R-07 | Settle on the 90-minute score | Unchanged |
| R-08 | Void selection = odds 1.00; an all-void bucket returns its own stake (40 / 30 / 20) | Updated for unequal stakes |
| R-09 | Same as D-15 | Unchanged |
| R-11 | Routes `/challenge`, `/challenge/learn`, `/challenge/me`, `/leaderboards` | Adds the learn page |
| R-14 | 24-hour correction window before a round is final | Unchanged |

## Outstanding — owner decision needed

| ID | Question | Recommendation | Blocking |
|---|---|---|---|
| D-01 | Identity and sign-in | An authenticating reverse proxy | Phase 6E |
| D-02 | Hosting | A single hosted server | Phase 6E |
| D-03 | Database for hosted use | SQLite (WAL) first; PostgreSQL before multiple workers | Phase 6E |
| D-04 | Leaderboard privacy | Public display names with an opt-out | Phase 6G |
| D-05 | Display-name policy | 3–24 characters; unique; blocklist | Phase 6E |
| D-06 | Deadline buffer | 15 minutes | Phase 6C |
| D-08 | Settlement and void rules `settle/v1` | Accept as specified | Phase 6F |
| D-11 | Round calendar | Weekend window; publish Thursday 06:00 UTC; postpone when the opening checks fail | Phase 6C |
| D-12 | PSL coverage (no qualifying odds) | Accept for the MVP and state it in the UI | Phase 6C |
| D-29 | **Empirical validation (outstanding):** collect 6–8 complete real weekly pools with settled outcomes and re-run the 6A.2 / 6A.2.1 simulations before the first official championship. Runs in parallel; does not delay the engine or the Dash prototype | Yes; the odds trial supplies the pools | First official championship |
| D-32 | **Mass voids short of cancellation:** should a round where most fixtures are void at settlement (for example more than half) be reclassified as void? Today only an operator cancellation voids a round (T-08) | Keep operator-only for the MVP; review after real data | Phase 6F |
| D-31 | **Final points schedule (scoring safeguard), pending final approval:** `points-150-75-v2` = 150/135/125/120/115/110/105/100/95/90 for ranks 1–10, 75 for any other recovery, 0 without recovery, with D-26 ties (scenario D) | **Approve.** Removes the large-field variance incentive at every field size tested (P-02, P-04, P-09), keeps recovery worth half the maximum, treats identical results equally (P-08). Residual: frequent joint champions above ~500 entrants (P-10), allowed by D-27. Optional, not adopted: "most weekly first places" as a final tie-breaker | Phase 6G |

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
| C-20 (6A.2 schedule) | 150/135/120/110/100/95/90/85/80/75, 50 outside the top ten | D-31 (`points-150-75-v2`), pending final approval |
| D-26 (6A.2 proposal) | Average-points weekly ties with exact fractions (e.g. 63.75) | D-26 approved: standard competition ranking, full points, integers |
| T-03, T-04 (6A.2) | Proposed opening checks and 5-entrant minimum | D-28 approved |
| T-05 (6A.2) | Points stored as exact fractions | T-05 revised: integers |
| D-28 (6A.2) | "Confirm D-26, D-27, T-03 and T-04" | D-26, D-27, D-28 approved |
| D-30 (6A.2) | Copy for a championship cut short | D-30 approved: pause, never shorten |
| D-14 | Merge Phase 5B research | Not needed: 6A.1/6A.2 research is stdlib-only and self-contained |
