# Milestone 5.2 — Product recommendations

*16 November 2026. A non-technical decision document. Nothing here has been
built: every "Consider" needs your approval. The evidence is in the three
research reports:*
* [Form Score](milestone5_2_form_score_research.md)
* [Goal models](milestone5_2_goal_model_research.md)
* [BTTS and Over/Under](milestone5_2_goals_market_research.md)

## 1. What we learned

1. **Recent form helps a little for match results, and how we score it matters
   less than expected.** Every version of the Form Score carries most of the
   same information.
   * The current score has two practical weaknesses. It lumps every team with
     a goal difference of zero or worse together, and it gives an ordinary
     team about 0.8 out of 5.
   * As a result, 85% of fixtures tie with another in the rankings.
2. **A simpler score works at least as well.** "Half points, half goal
   difference" (Model D) scores an average team at about 2.5 and cuts ties to
   about 20%. It is slightly better on Overall form, and that gain is
   statistically supported, though small.
3. **The three bonuses add nothing measurable.**
4. **Our current-season BTTS and Over 2.5 percentages say very little about the
   particular fixture.** Within a league they barely separate high-scoring
   games from low-scoring ones. Read as percentages, they are less accurate
   than simply quoting the league's own rate.
   * Example: PSL Over 2.5 is 32%; EPL is 55%.
   * As history ("BTTS in 6 of the last 10") they are true. As a likelihood
     they mislead.
5. **Overall form beats Venue-specific** for BTTS and Over/Under, mainly
   because venue samples are half the size. Across a season, 42% of
   venue-based fixtures involve a team with fewer than six venue matches,
   against 22% on Overall.
6. **Bookmaker odds can be turned into "expected goals for each team" reliably,
   when a goals market is included.**
   * A small draw adjustment (Dixon–Coles) makes the match-result, BTTS and
     Over/Under prices agree with each other.
   * We cannot yet say whether these figures predict real results. None of the
     fixtures with saved odds has been played yet.

## 2. Which methods performed best

| Question | Best method | How sure? |
|---|---|---|
| Recent form for match results | Model D (points + goal difference, no bonuses) | Modest. Significant on Overall form only. |
| BTTS / Over 2.5 likelihood (history only) | The league's current-season rate | Strong. Consistent in every league and sample size. |
| Goal expectations from odds | Dixon–Coles, one shared draw adjustment, 1X2 + a goals market | Strong as a description of the market. **Unvalidated against results.** |

## 3. Statistically meaningful vs. cosmetic

| Change | Meaningful? |
|---|---|
| Continuous scoring with the current zero-floor (Model B) | Cosmetic. It only breaks ties. |
| Counting negative goal difference (Models C and D) | Small but real on Overall form. Not significant on Venue form. |
| Removing the bonuses | No loss of information, so it is a simplification. |
| Shrinking BTTS / Over percentages towards the league average | No. Still worse than the league rate alone. |
| Dixon–Coles instead of Poisson for market goal expectations | Yes, for consistency with the market. Unknown for predicting results. |

## 4. What would make the Screener easier to understand

* **Match Result:** a Form Score where 2.5 means "average", with no bonus rules
  to explain. It also gives far fewer ties in "strongest home/away form".
* **BTTS / Over 2.5:** present the history as counts ("6 of 10") next to the
  league rate ("PSL: 40%") and the market-implied probability. Drop the single
  averaged team percentage as a headline number.
* **Early season:** with fewer than six matches, show the league rate and the
  counts, not a team percentage. Keep the "Limited" label.
* **Keep:**
  * Detailed methodology in tooltips and expanders.
  * No new columns.
  * No model numbers until they are validated.

## 5. Decisions

| # | Candidate improvement | Decision |
|---|---|---|
| 1 | Keep the current banded Form Score (A) for now | **Keep** until #2 is decided |
| 2 | Replace it with Model D (points + goal difference, 2.5 = average, no bonuses) | **Consider** for Milestone 5.3 |
| 3 | Model B (continuous, current zero-floor) | **Reject** |
| 4 | Model C (symmetric goal difference with bonuses) | **Reject** (same as D but harder to explain) |
| 5 | Remove the three bonuses | **Consider** (together with #2) |
| 6 | Default Match Result form to Overall | **More data needed** (slightly better, not tested formally) |
| 7 | Keep BTTS / Over 2.5 history, presented as counts | **Keep** |
| 8 | Show the league's current-season BTTS / Over 2.5 rate beside the team history | **Consider** for Milestone 5.3 |
| 9 | Make the market-implied BTTS / Over 2.5 probability the headline number | **Consider** (already shown; validate as results arrive) |
| 10 | Shrunk ("adjusted") team percentages | **Reject** |
| 11 | Overall as the BTTS / O2.5 default | **Keep** |
| 12 | Venue-specific option for BTTS / O2.5 | **Keep** as optional, with the Limited warning |
| 13 | Early-season display: league rate + counts when fewer than 6 matches | **Consider** for Milestone 5.3 |
| 14 | Market-implied expected goals per team in the UI | **More data needed** (earliest review after about 150 settled fixtures) |
| 15 | Dixon–Coles (shared draw adjustment) as the goal model behind #14 | **More data needed** (preferred research method) |
| 16 | Per-fixture Dixon–Coles draw parameter | **Reject** |
| 17 | Goal expectations from match-result odds alone | **Reject** |
| 18 | Model probabilities replacing BTTS / O2.5 indicators or market probabilities | **Reject** for now |
| 19 | Qualitative adjustment tool (YouTube workflow) built on market goal expectations | **More data needed** (design only; needs line-up and injury data) |
| 20 | Qualitative adjustments built on Form Scores | **Reject** (no link to any probability) |
| 21 | Challenge rules | **Keep** (no change: Fresh odds only) |

## 6. Ready for production consideration (Milestone 5.3, with approval)

* #2 and #5: the Model D Form Score, with no bonuses
* #8 and #13: league rate beside BTTS / Over history, and the early-season
  display
* #9: emphasise the market-implied BTTS / Over probability

These are all small, explainable changes that need no new data. Model D would
be a new engine version, which requires a cache rebuild (`refresh-data`).

## 7. Needs more evidence

* #6: Overall as the Match Result default
* #14 and #15: market goal expectations and Dixon–Coles. These need settled
  fixtures with saved odds: about 150 for a first calibration check, 400 across
  two or more leagues for comparisons.
* #19: the qualitative adjustment framework. It needs line-up and injury data
  and calibrated effect sizes.

## 8. Rejected

* #3 and #4: Models B and C
* #10: shrunk percentages
* #16 and #17: a per-fixture draw parameter, and 1X2-only inversion
* #18: model probabilities replacing the indicators
* #20: adjusting Form Scores

## 9. Recommended next milestone

**Milestone 5.3: Simpler, more honest Screener (requires approval)**

1. Model D Form Score with no bonuses (engine 3.0.0, cache rebuild), with a
   short "2.5 = average" explanation.
2. BTTS / Over 2.5: history as counts, plus the league rate, plus the
   market-implied probability. Early-season fallback to the league rate.
3. Keep collecting odds (trial plus on-demand) for EPL and PSL, so that settled
   fixtures build up.
4. Rerun the goal-model validation monthly. Review #14 and #15 once 150
   fixtures have settled.
5. No Challenge, account or leaderboard work unless separately approved.
