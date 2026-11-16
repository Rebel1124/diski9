# League Diski Form Score average and simplified team cards

*16 November 2026 · engine **2.2.0 → 2.3.0**. No database schema change and no
API requests.*

## Simplified team cards (all three markets)

| Market | Card shows | Moved or removed |
|---|---|---|
| Match Result | team · "2.86 out of 5" · comparison line | "Historical performance score…" and the match count removed. A per-team `Limited` tag appears beside the score when applicable. |
| BTTS | team · "BTTS in 3 of 9" · comparison line | "No BTTS in 6 of 9" and "current-season matches" removed. The match records stay in **Matches used**. |
| Over/Under 2.5 | team · "Over 2.5 in 1 of 9" · comparison line | "Under 2.5 in 8 of 9" and "current-season matches" removed. |

Form Scores are written "x out of 5" everywhere. A test checks the rendered
detail for "/ 5" in every market.

## League Form Score average (`engine.form_benchmark`)

Computed during Screener cache generation, once per fixture and basis (about
2 ms). It is stored in `match_result.league_benchmark`.

* **Population (point in time).** Every team that has played at least one
  eligible league match of the fixture's competition and season before the
  cutoff (`league_members`).
  * Relegated teams (last season only) and teams from other competitions are
    excluded.
  * Before the first round nobody qualifies, so the average is unavailable.
* **Score per team.** The production Diski Form Score (Model D) with exactly
  the production window: the last five eligible matches before the cutoff.
  * Earlier seasons and other divisions are used where the window needs them,
    as for the team's own score. A promoted team's window can include its
    previous-division matches.
  * Matches at or after the cutoff, including the fixture itself, are never
    used.
* **One score per team.** No weighting by matches played.
* **Only full five-match windows are averaged.** A short window cannot reach 5,
  so including it would pull the average down. Teams without one are left out,
  never counted as 0.
* **Overall form:** one average over overall windows. Each team is compared
  with it.
* **Venue-specific form:** a home average (over every team's home window) and
  an away average (over away windows). The home team is compared with the home
  average and the away team with the away average.

**Availability (configurable in `ScreenerConfig`):** each required average needs
at least **12 teams** (`form_benchmark_min_teams`) and at least **80% of league
members** (`form_benchmark_min_share`) with a full window. This is
deliberately conservative:
* 12 is three quarters of the smallest league stored (16 teams).
* The 80% share stops a few teams from standing in for the league.

These rules do not count matches. Form windows can draw on earlier seasons, so
after the first round almost every team has a full window.

**Unavailable:**
* "Not enough league data yet" appears, with "*n* of *m* league teams have a
  full five-match window".
* The comparison line is omitted.
* No 2.5 or zero is substituted.

**Comparison:**
* Uses the unrounded team score against the unrounded average.
* "Equal" allows only a floating-point tolerance of 1e-9.
* For BTTS and Over/Under, the existing exact-ratio comparison is unchanged.

**Live example** (Premier League 2026/27, 20 teams, before 21 November):
* home average 2.72 out of 5, away average 2.02, overall average 2.41
* Newcastle (home 1.94) is below the home average; Arsenal (away 3.53) is above
  the away average

## Cache and rebuild

The benchmark is part of the cached result, so the engine version is now 2.3.0:
* 2.2.0 rows are never served, and the app shows the rebuild banner until the
  cache is rebuilt.
* Verified here: 112 rows inserted, 112 retired, 0 API calls.

```bash
uv run diski9 screener-refresh --days 21
```

**Unchanged:**
* Form Score formula and windows
* team Form Scores and Form Difference
* rankings and thresholds
* BTTS and Over/Under records and their current-season league baselines
* odds and market probabilities

## Screenshots (`docs/screenshots/`)

* Desktop:
  * `ui_desktop_1x2_analysis.png`
  * `ui_desktop_btts_analysis.png`
  * `ui_desktop_ou25_analysis.png`
* Mobile:
  * `ui_mobile_1x2_analysis.png`
  * `ui_mobile_btts_analysis.png`
