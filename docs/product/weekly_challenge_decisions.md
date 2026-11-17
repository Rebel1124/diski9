# Diski 9 Weekly Challenge — Decision Register (Phase 5C)

**Legend:**
* **Confirmed:** decided by the owner.
* **Recommended:** Claude's recommendation, adopted in the design unless the owner
  objects.
* **Approval:** requires the owner's decision before implementation.
* **Blocking:** must be resolved before the named phase starts.

## Confirmed by the owner

| ID | Decision |
|---|---|
| C-01 | 100 virtual credits per week; 9 selections on 9 distinct fixtures; 1X2, BTTS and Over/Under 2.5 |
| C-02 | 3 buckets of 3 selections plus a nine-fold; fixed stakes 30 / 30 / 30 / 10; no adjustable stakes; no allocation helper |
| C-03 | All 280 arrangements shown; dominated ones visible but disabled; efficient ones selectable |
| C-04 | Chart: X = probability of recovering 100; Y = expected gross return |
| C-05 | Recommended = the efficient portfolio with the highest recovery probability; ties: higher expected return, then the lowest canonical ID |
| C-06 | Goal Model 1.0 unchanged; existing consensus odds and eligibility (≥ 3 groups, fresh) |
| C-07 | Weekly leaderboard by net virtual credits; no real money, prizes, affiliate links or staking advice |
| C-08 | **"Your Payout Probability"** (Phase 5C addendum), beneath the selected grouping's buckets and nine-fold. View A: X = gross payout in credits (0 to the maximum), Y = chance of at least that payout; exact eight-state downward steps, no smoothing; nine-fold only when all three buckets win; 100-credit threshold with its exact probability, equal to the summary and the frontier. View B: discrete probability-mass bars for exact payouts, with identical payouts aggregated, summing to 100%. Updated with every efficient selection from the same frozen inputs, with no API calls. Credits only, never percentages; labelled as conditional on Goal Model 1.0; the eight states hidden unless requested |

**Verified:** uniform 5× scaling preserves recovery and the efficient set, and
multiplies expected return, SD and net by 5. No contradiction with Phase 5B
(PRD §9).

## Recommended by Claude (adopted unless you object)

| ID | Recommendation | Rationale |
|---|---|---|
| R-01 | **Common deadline (Option A):** the earliest eligible kickoff in the round minus 15 minutes, fixed at publish | Same information for everyone; coherent with frozen prices and a nine-pick grouping; one simple, testable rule |
| R-02 | **Round sheet:** model probabilities and consensus odds frozen once per round at publish time, shared by all players | Fairness (everyone faces the same prices); determinism; an efficient cache; no timing games |
| R-03 | The picker lists **only eligible fixtures**, plus a disclosed count of the others with the reason | Simplest; avoids disabled clutter; the Screener still covers every fixture |
| R-04 | One entry per user per round, **resubmittable until the deadline**; every version stored; the latest counts | Forgiving for users; auditable; trivial with insert-only versions |
| R-05 | Store the inputs plus the chosen portfolio as the source of truth, plus a compact JSON of all 280 points per submission | Exact record of what the user saw, at about 10 KB |
| R-06 | Production maths as a **dependency-free port** of Phase 5B, with exact decimal payouts; equivalence tests against the research code | numpy and scipy are dev-only; exact threshold comparisons |
| R-07 | Settle on the **90-minute score**; ignore extra time and penalties | Matches stored `ft_home`/`ft_away` and the market definitions |
| R-08 | **Void selection = odds 1.00** in every accumulator containing it; probabilities at submission are not recomputed | Simple, common, explainable; all-void returns the stake |
| R-09 | Payout per accumulator computed exactly, then **rounded half-up to 0.01 credit**. The same rounded values drive every modelled figure (frontier, summary, payout chart) and settlement | One rounding step; reproducible; the chart's threshold value always equals what settlement would pay (addendum §3). Confirmation: D-15 |
| R-10 | Weekly ties **share a rank** (1, 2, 2, 4); no hidden tie-breakers | Transparent |
| R-11 | Three new routes (`/challenge`, `/challenge/me`, `/leaderboards`) plus header navigation; the Screener is unchanged at `/` | Minimum screens; natural extension |
| R-12 | Market-implied probabilities shown per pick (tooltips and review), never on chart axes | Transparency without clutter |
| R-13 | No smoothing, no jitter; ties drawn as one counted marker; an efficient list as an accessible alternative | Honest chart; works on mobile |
| R-14 | Settlement correction window of 24 hours before a round is final; later corrections only via an audited `--reopen` | Balances accuracy and finality |
| R-15 | **"Your Payout Probability"** (owner requirement, added to Phase 5C). Cumulative step chart as the default view; exact-outcome stems as the secondary view, with a table form; full payout range by default, plus an optional "Focus on buckets" zoom | The all-win payout is often 4–10× the bucket payouts, so it squeezes the steps that matter; the zoom keeps them readable without hiding the maximum |

## Requires your approval

| ID | Question | Options | Recommendation | Blocking |
|---|---|---|---|---|
| D-01 | **Identity and sign-in.** The app has no authentication today. | (a) Hosted behind an authenticating reverse proxy that passes a verified user identity; the app stores only a stable subject and a display name. (b) In-app accounts (email and password, or magic links; needs a session library and an email sender). (c) A third-party OAuth sign-in (needs an OAuth library and a provider choice). | (a): the least code and the smallest attack surface in the app. Provider to be chosen by you. | Phase 4 |
| D-02 | **Hosting.** Today it is a local, single-user Flask dev server. | A small cloud VM or PaaS with a WSGI server (for example gunicorn), TLS and scheduled jobs; or keep it local only (no shared leaderboard). | Hosted single server, one process to start | Phase 4 |
| D-03 | **Database for hosted use** | SQLite (WAL, one server process) or PostgreSQL | Start on SQLite if single-process; move to PostgreSQL before scaling to several workers | Phase 4 |
| D-04 | **Leaderboard privacy** | Public by default with an opt-out to hide, or opt-in | Public display names by default, with an opt-out (hidden users excluded from public tables but shown their own rank) | Phase 6 |
| D-05 | **Display-name policy** | Free text; unique; moderation level | 3–24 characters; unique case-insensitive; basic blocklist; operator can rename | Phase 4 |
| D-06 | **Deadline buffer** | 0, 15 or 60 minutes before the earliest kickoff | 15 minutes | Phase 2 |
| D-07 | **Edit policy** | Resubmit until the deadline, or a single final submission | Resubmit until the deadline (R-04) | Phase 4 |
| D-08 | **Settlement and void rules** `settle/v1` (design §7): 90-minute score; void codes V1–V5; settlement cutoff = window end + 48 h; void = odds 1.00 | Accept, or adjust the cutoff or awarded-match handling | Accept as specified | Phase 5 |
| D-09 | **Season scoring** | (a) Cumulative net with skipped rounds = 0. (b) Cumulative net with a skipped round = −100 ("unused credits are lost"). (c) Average net per round entered, qualifying at ≥ 50% of completed rounds and ≥ 3 entries. | (c). (a) rewards not playing, because expected net is negative at market prices (about −18 per round); (b) is simple but harsh on late joiners | Phase 6 |
| D-10 | **Market-implied expected return** next to the model's | Show in details, or omit from the MVP | Omit from the MVP; per-pick market probability only (R-12) | Phase 3 |
| D-11 | **Round calendar** | Weekend window Fri 00:00 – Mon 23:59 UTC; publish Thursday 06:00 UTC after the odds refresh; no round when fewer than 9 eligible fixtures | As stated | Phase 2 |
| D-12 | **PSL coverage** | API-Football currently has no qualifying odds for the PSL or PSL 1st Division, so they cannot appear in rounds. Accept, or pursue another odds source (a separate project) | Accept for the MVP; state it in the UI ("PSL fixtures will join when reference odds are available") | Phase 2 |
| D-13 | **Season definition** | Calendar-based (European season Aug–May) or a rolling year; PSL and European calendars differ | Aug–May season matching the leagues with odds | Phase 6 |
| D-15 | **Settlement-precision policy for modelled figures.** The addendum requires threshold probabilities to follow "the agreed settlement-precision policy" | (a) R-09 everywhere: each accumulator rounded half-up to 0.01; state gross = sum of the rounded payouts; recovery = gross ≥ 100.00 (modelled = settled, to the cent). (b) Exact unrounded payouts for modelled figures, with rounding only at settlement (may differ from the settled amount by a cent, and in rare knife-edge cases flip recovery) | (a). No recovery flips occurred in 8,960 real or 640,000 random state comparisons, but (a) guarantees agreement by construction. Note it shows R1's maximum as 1,162.92 (sum of rounded payouts), not 1,162.91 | Phase 1 |
| D-14 | **Phase 5B merge** | Merge the research branch into `main`, or keep it separate and copy the reference into tests | Merge the research branch (code is research-only and tested) before Phase 1 | Phase 1 |

## Issues to resolve before implementation

1. **Identity, hosting and database** (D-01, D-02, D-03): no multi-user feature can
   ship without them. Phases 1–3 can proceed meanwhile.
2. **Season scoring (D-09):** plain cumulative net with skips scored 0 creates a
   perverse incentive not to play. Choose a rule before the first season starts.
3. **PSL coverage (D-12):** Diski 9 has a South African focus, but the PSL cannot
   currently feature in the Challenge. This is a product-positioning decision.
4. **Model-based expected returns:**
   * Goal Model 1.0 is more cautious than the market on favourites. Underdog-heavy
     picks can show large modelled expected returns (Phase 5B slate R3: about
     350–450 credits at 100-credit scale under 30/30/30/10).
   * The recommendation uses recovery, not expected return, and the copy labels
     expected return as a model estimate.
   * Please confirm this framing is acceptable before launch.
5. **Scheduling:** hosted operation needs scheduled jobs (odds refresh, publish,
   settle). Confirm the operator will run, or automate, the CLI lifecycle.
