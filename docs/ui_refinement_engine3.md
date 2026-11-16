# Engine 3.0 UI/UX refinement

*November 2026. Presentation and interaction only: Goal Model 1.0, its frozen
parameters (k_s 12, k_t 96, m0 30), the database schema, the forecast snapshots
and monitoring are unchanged.*

## Screener filter card

One compact card holds, in order: **Market**, **Leagues**, **Dates**, **Rank by**
and **Threshold**.

* **Layout:** five equal columns on desktop, three or two on tablets, stacked
  full-width on phones. Controls share the same 40 px height.
* **Market** is a dropdown that replaces the tab row: "Match Result (1X2)",
  "Both Teams to Score (BTTS)", "Over/Under 2.5 Goals".
  * Switching market keeps the selected fixture and every Match Lab input.
  * Columns, rankings, thresholds and the bookmaker market follow the market.
* **Leagues** is a multiselect (the Dash 4 dropdown) that replaces the eight
  checkboxes.
  * It has built-in **Select all** and **Clear all** actions.
  * A compact summary reads "All 8 leagues", "5 leagues selected" or
    "1 league selected".
  * It is keyboard-accessible and works on touch screens.
* The threshold slider no longer shows Dash's built-in number box.

## The Match Lab

**Role tags** keep the four kinds of information apart:

| Tag | Where |
|---|---|
| **Model estimate** | A. Statistical baseline |
| **Context** | B. Match context |
| **Your research** | C. Other factors |
| **Your assumptions** | D. Your adjustments |
| **Market** | Bookmaker card |

**Section B, Form Score.** The primary view shows:
* both Form Scores, with above or below the league average
* the league Form Score average
* recent results (W/D/L badges)

The arithmetic, venue context, explanations and match lists sit one level deeper,
under "Calculation and detail".

**Section C, Other factors to consider.** There are four collapsible categories:

| Category | Factors |
|---|---|
| Squad & Availability | injuries, suspensions, expected line-ups, transfers |
| Fitness & Scheduling | congestion, rest days, travel, rotation |
| Tactics & Management | managerial changes, tactical changes, playing style, matchups |
| Match Conditions & Motivation | weather, unusual venues or home advantage, title or relegation, other match-specific circumstances |

Each category has:
* an optional research note
* a home and an away estimated-goal adjustment, starting at 0.00 in steps of 0.05,
  with a limit of ±2 per category

Each category's header summarises its adjustment, for example "Home −0.15 · Away
0.00", and flags a saved note.

Diski 9 never assigns a value to a factor. The section explains that the factors
are not in the model and warns about counting the same information twice. No team
news is supplied.

## How Sections C and D work together

```
Your estimate = model baseline + sum of Section C adjustments + additional manual adjustment
```

* The **model baseline** is Goal Model 1.0's estimate, rounded to 0.01 as shown.
* **Section C** adjustments add up across the four categories, for each team.
* The **sliders and number boxes in Section D set the final estimate.** When you
  change one, the additional manual adjustment is worked out as
  `final − baseline − Section C total`. Nothing is counted twice.

  Example: baseline 1.80, Section C −0.15. Typing 1.50 makes the manual adjustment
  −0.15.
* A later Section C change keeps the manual adjustment and moves the final
  estimate.
* Section D shows a breakdown for each team:
  * model baseline
  * your research (Section C)
  * additional manual adjustment
  * your estimate
* It also shows model against your estimate for the selected market, with
  percentage-point changes and an "All markets" view of all seven outcomes.
* **Limits:**
  * A final estimate is kept between 0 and 10 goals. If your adjustments would go
    below zero, the estimate is held at 0.00 and a message explains why.
  * Invalid values are never silently dropped; a message says what was kept.
* **Reset to model** clears every adjustment in Sections C and D and restores the
  baseline. **Research notes are kept**, and this is stated next to the button.

**State:**
* Stored per fixture in the browser's memory (`dcc.Store`, `lab-store`):
  `{"cats": {category: {"note", "home", "away"}}, "manual": {"home", "away"}}`.
* It persists across market switches and when you leave a fixture and return in
  the same tab.
* Fixtures never share state; other users never see it.
* It never reaches the server's database or the official forecast snapshots.
* The model baseline is never modified.

## Bookmaker outcome cards

Each outcome card stacks three centred lines: the outcome label, the consensus
odds and the raw implied probability.

* **Grid:** three equal cards for Match Result; two for BTTS and for Over/Under.
* Widths, heights, padding and typography are the same everywhere.
* Odds data, freshness, margins and the model comparison are unchanged.

## Mobile

* The match header is compact: home v away, competition, kickoff and market.
* No sticky header is used, to save screen space.
* Category summaries sit under their titles, and inputs are two per row.
* There is no horizontal scrolling on phones, tablets or desktop; a browser test
  checks this.

## Screenshots

All files are in `screenshots/`:

| What | Files |
|---|---|
| Filter card | `ui_filters_desktop.png`, `ui_filters_leagues_open.png` |
| Section C | `ui_section_c_desktop.png`, `ui_section_c_mobile.png` |
| Section D with several category adjustments | `ui_section_d_desktop.png`, `ui_section_d_mobile.png` |
| Bookmaker cards | `ui_bookmaker_1x2.png`, `ui_bookmaker_btts.png`, `ui_bookmaker_ou25.png`, `ui_bookmaker_mobile.png` |
| Form Score primary view | `ui_form_score_primary.png` |
| Mobile | `ui_screener_mobile.png`, `ui_match_lab_mobile.png` |

## Known limitations

* The league summary chip ("All 8 leagues") sits next to a truncated list of
  names. That is how the Dash 4 dropdown renders a multiselect.
* Number boxes show Dash 4's own −/+ steppers, and values display without
  trailing zeros (for example 1.6).
* Adjustments are per browser tab and are lost when the tab closes, by design: no
  accounts or saved histories.
