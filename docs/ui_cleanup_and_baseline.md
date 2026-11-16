# Final UI cleanup and current-season league baselines

*16 November 2026 · engine **2.1.0 → 2.2.0**. No database schema change and no
API requests.*

## UI changes

1. **"Other markets" removed** from the fixture detail in all three markets.
   The tabs already switch markets. The underlying data is unchanged.
2. **Bookmaker Market Reference** now shows the **selected market only**,
   with no accordion:
   * the Fresh / Stale / Unavailable badge with the Diski 9 check time and the
     provider update time
   * market-implied probabilities: the Home/Draw/Away bar, or the Yes/No or
     Over/Under pair
   * consensus reference odds, each with its **raw** implied probability
     (1 ÷ odds, before the margin is removed), so raw and market-implied
     values stay distinct and nothing is repeated
   * "*N* independent bookmaker groups · combined margin removed *x*%", from
     the consensus and `ImpliedProbabilities.overround`; nothing is invented
   * a short note: *"Bookmaker odds include a margin, so their implied
     probabilities add up to more than 100%. We remove this margin by
     proportionally adjusting the probabilities to total 100%, making the
     market's expectations easier to compare."* This matches the code in
     `odds/implied.py`: (1/odds_i) ÷ Σ(1/odds).
   * PSL (no bookmaker odds): one short line; no odds, counts or margin.
3. **Match Result team cards:**
   * They show the team, "3.81 out of 5", "Historical performance score from
     recent points and goal difference" and the match count.
   * The W/D/L badges were removed from the cards. Results appear once, in the
     Result column of each team's table under **Matches used**. A separate
     "Results used" sequence was briefly added there and then removed as a
     duplicate.
   * "How it's calculated" is unchanged. BTTS and Over/Under are unchanged.
4. **League baseline wording:**
   * Unavailable: "Not enough current-season data yet", with "*n* of 30
     eligible completed league matches before kickoff". No percentage, and
     never 0%.
   * Available: e.g. "49% — Premier League 2026/27 — 100 completed matches
     before kickoff".
   * Tooltip: *"This is the percentage of completed matches in the current
     league season where the outcome occurred. Only matches played before this
     fixture are included. A baseline is shown once at least 30 eligible
     matches are available."*

## Follow-up: match context inside the bookmaker card

League positions and Head-to-head now sit at the foot of the Bookmaker Market
Reference card:
* They come under a divider labelled "Match context — Historical results, not
  bookmaker data".
* They are collapsed rows, with the same style as "How it's calculated".
* They appear in every odds state (Fresh, Stale, Unavailable, and leagues with
  no odds).
* There are no standalone cards below the bookmaker card any more.
* Their content is unchanged. This is UI only, with the engine still 2.2.0.

## League baseline: new calculation (`engine.league_baseline`)

For a fixture in competition *c*, season *s*, with cutoff *t* (kickoff, or
"now" for an upcoming fixture):

1. Take the league matches of *c* in season *s* with kickoff **before *t***.
   These are the same eligible matches every other statistic uses:
   * completed, regular season
   * not awarded, abandoned, cancelled or postponed
   * not a play-off
   * not at a confirmed neutral venue
2. If there are **at least `ScreenerConfig.league_baseline_min` (default 30)**:
   * BTTS baseline = share with both teams scoring
   * Over 2.5 baseline = share with three or more goals
3. Otherwise the baseline is **unavailable**: `available: false`, both rates
   `None`, and the match count is kept for display.

**What it never uses:**
* previous seasons (no blending, prior or fallback of any kind)
* other competitions or divisions
* matches at or after the cutoff
* the fixture itself

Team records remain current-season, current-competition only, as before.

**Consumers:**
* The detail card and calculation text show the unavailable state.
* The table shows `—`.
* Rankings and thresholds never used the baseline, so they are unaffected.
* No code path converts a missing baseline to 0.

The Milestone 5.2 research module (`research/historical_goals.py`) keeps its
original blended prior *as research*. It is not used by the Screener.

## Cache and refresh

The baseline is stored inside each cached Screener result, so the engine
version was bumped to **2.2.0**:
* Rows from 2.1.0, which may contain blended baselines, are never served.
* The app shows the "earlier method" banner until the cache is rebuilt.
* The next refresh retires those rows; history is kept, not deleted.

Rebuild locally (no API requests):

```bash
uv run diski9 screener-refresh --days 21
```

**Verified here:** 112 rows inserted and 112 version 2.1.0 rows retired, with
0 API calls. Every live EPL and PSL fixture has at least 73 current-season
league matches, so live baselines are unchanged in value. The difference
appears early in a season: on 29 August 2026 the EPL had 11 matches and now
shows "Not enough current-season data yet".

## Screenshots (`docs/screenshots/`)

* Desktop:
  * `ui_desktop_1x2_detail.png`
  * `ui_desktop_1x2_matches_open.png` (results sequence)
  * `ui_desktop_1x2_calculation_open.png`
  * `ui_desktop_btts_detail.png`
  * `ui_desktop_btts_matches_open.png`
  * `ui_desktop_psl_market_unavailable.png`
  * `ui_desktop_baseline_not_enough_data.png`
* Mobile:
  * `ui_mobile_1x2_detail.png`
  * `ui_mobile_1x2_calculation_open.png`
  * `ui_mobile_btts_detail.png`
