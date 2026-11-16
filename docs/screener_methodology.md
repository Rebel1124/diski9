# Diski 9 Statistical Screener — Methodology (engine 2.0.0, Milestone 5)

This is the current methodology. It supersedes the Form Score, venue-adjustment
and BTTS/O/U lookback rules in Statistical Screener Specification v1.2. Every
other rule in v1.2 still applies, including eligible matches, point-in-time
rules and consensus odds.

## Eligible matches (unchanged)

Only completed domestic league matches count. These are excluded:
* awarded, walkover, cancelled, abandoned and postponed matches
* play-off, relegation and promotion rounds
* matches at a confirmed neutral venue, in venue-specific windows

Only matches that kicked off before the calculation cutoff are used:
`cutoff = min(time of calculation, fixture kickoff)`.

## Match result: Diski Form Score (0–5)

Each team's score uses its **last five eligible matches**:
* Venue-specific (default): the home team's last five home matches and the
  away team's last five away matches.
* Overall: each team's last five matches, home or away.

These windows may reach into earlier seasons or a previous division to
complete five matches. Each match is labelled with where it came from.

| Component | Rule | Award |
|---|---|---|
| Points earned (W = 3, D = 1) | 0–2 / 3–5 / 6–8 / 9–11 / 12–14 / 15 | 0 / 0.5 / 1.0 / 1.5 / 2.0 / 2.5 |
| Goal difference (scored − conceded) | ≤ 0 / +1–2 / +3–4 / +5–6 / +7–8 / ≥ +9 | 0 / 0.5 / 1.0 / 1.5 / 2.0 / 2.5 |
| Bonus: won the **three most recent** matches | needs at least 3 matches | +0.5 |
| Bonus: scored at least 11 goals | in the window | +0.5 |
| Bonus: conceded at most 2 goals | needs a full five-match window | +0.5 |

**Diski Form Score = raw ÷ 6.5 × 5.** Full precision is kept internally, and
the score is shown to 2 dp.

**Fewer than five matches:**
* Only the matches available are used, with the same thresholds.
* Nothing is scaled up to five matches.
* The three-win bonus needs at least three matches.
* The conceded bonus needs all five.
* The score is labelled **Limited data**, with the real sample size.

The v1.2 rule of "fewer than 3 current-division matches" also still applies.
A team with no eligible matches has **no** score: it is shown as unavailable,
never as 0.

**Worked example.**
* The record, most recent first, is W W W L W: 12 points, 12 goals for and
  3 against, so the goal difference is +9.
* Awards: points 2.0, goal difference 2.5, last three won +0.5, 11+ goals
  +0.5, conceded 3 (more than 2) 0.
* Raw 5.5, so the score is 5.5 ÷ 6.5 × 5 = 4.2308, shown as **4.23**.

**Form Difference = home team's score − away team's score.** This applies
to both bases. There is no league benchmark or venue adjustment.
* Strongest home advantage ranks the largest positive differences first.
* Strongest away advantage ranks the most negative first.
* Most evenly matched ranks the smallest absolute difference first.
* Similar scores do **not** imply that a draw is likely.

## BTTS and Over/Under 2.5: current season only

Each team uses **up to its last ten eligible matches from the fixture's own
season and competition**. Earlier seasons, other divisions, play-offs, and
cancelled or awarded matches are excluded.
* Venue-specific: home matches for the home team, away matches for the away
  team.
* Overall: all current-season matches.

| Indicator | Calculation |
|---|---|
| Team BTTS rate | matches where both teams scored ÷ matches used |
| Team Over 2.5 rate | matches with ≥ 3 goals (90-minute score) ÷ matches used |
| Combined Yes / Over | (home rate + away rate) ÷ 2 |
| Combined No / Under | 1 − combined |

* Denominators are the real sample sizes, for example "3/4 (75%)".
* **Limited data** applies when either team has fewer than 6 matches.
* With 6 to 9 matches no warning is shown, just the sample size.
* With 0 matches for either team, the combined indicator is unavailable.

These are historical indicators, **not** predicted probabilities.

## Reference odds (display status)

| Status | Meaning | Shown |
|---|---|---|
| Fresh | A valid consensus now (24 h provisional freshness, eligible independent bookmaker groups, complete market) | Odds, implied probabilities, Diski 9 check time, provider feed time |
| Stale | No valid consensus now, but there was one at an earlier retrieval | That consensus, recomputed **as of that single retrieval**, labelled Stale with its age |
| Unavailable | No valid consensus has ever been observed before kickoff | A short reason |

**Challenge eligibility is separate and strict.** Only a *fresh* consensus
that meets the Challenge rules qualifies. `challenge_consensus()` has no stale
fallback.

Consensus is the median price across independent bookmaker groups (brands
under common ownership count once), rounded half-up to 2 dp, with the exact
median kept. Market-implied probabilities remove the combined margin from the
displayed prices. No betting edge, expected value or staking advice is
calculated.

## Caching

The engine version is `2.0.0`. Each refresh retires active cache rows from
other engine versions, and the app only reads current-version rows, so results
from different methodologies are never mixed. Raw fixtures and odds history are
untouched.
