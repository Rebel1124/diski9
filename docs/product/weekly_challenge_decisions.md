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
| C-20 | **Weekly points:** top ten 150/135/120/110/100/95/90/85/80/75 *if gross ≥ 100*; outside the top ten with gross ≥ 100: 50; gross < 100 or no entry: 0. "No recovery, no championship points." |
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
| P-01 | With up to 25 entrants, the proposed points track **recoveries** (Spearman 0.93–0.96), not one big week. The champion's best round is about 20% of their total, against 96–114% under cumulative net | Provisional |
| P-02 | With up to 25 entrants, recovery-focused selection wins 1.7–2.4× its share of championships, and lowest-in-band selection 0.4–0.7×. This matches the product goal | Provisional |
| P-03 | Cumulative net (the old baseline) is close to a lottery, decided by a single round. F1-style rewards variance in larger fields; percentile rewards low-variance mid-table finishes without recovery | Provisional |
| P-04 | **Large fields reward variance under the 50 floor:** at 100 entrants, lowest-in-band wins 1.94× its share. A 75 floor restores the intended incentive (recovery-focused 1.90×); a 25 floor worsens it. With 10 or fewer entrants the floor never applies; at 25 it matters little | Provisional; see D-31 |
| P-05 | Exact weekly gross ties among recoverers grow with field size: about 0.03 groups per round at N = 10, 0.14 at 25 and 1.18 at 100 (herding on popular favourites). The top two are level on points in 2–4% of championships | Provisional |
| P-06 | The real weekend pool (60 eligible fixtures, 6 leagues) passes every opening check. 15-fixture random sub-pools open 99.75% of the time; 10-fixture pools contain a portfolio 96.5% of the time but fail the minimum | Provisional |
| P-07 | Points are never negative, so skipping a round can never help (the old D-09 perverse incentive is gone). Late joiners finish lower on average (relative position 0.64 vs 0.49), as intended by "all rounds count" | Provisional |

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
| D-31 | **Large-field safeguard.** The 50 floor rewards high-variance play once fields reach roughly 50–100 entrants (P-04) | Keep 50 for launch (small fields are expected). Revisit if a round exceeds about 50 entrants: raise the floor to 75 (simulated), or define "top ten" as a share of entrants (not simulated) | Before fields exceed ~50 |

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
| D-14 | Merge Phase 5B research | Not needed: 6A.1/6A.2 research is stdlib-only and self-contained |
