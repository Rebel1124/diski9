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

## Final polish

**League multiselect.** A closed dropdown shows one clean summary:

| Selection | Display |
|---|---|
| All eight leagues | "All 8 leagues" |
| Several leagues | "5 leagues selected" |
| One league | its name, e.g. "EPL" |
| None | "Select leagues" |

* Names appear only when the dropdown is opened.
* Select all and Clear all live in the open menu.
* This uses the Dash 4 dropdown's own count label; CSS hides the duplicate name
  list and the × button.

**Exact threshold.**
* The slider moves in whole percentages from 0 to 100.
* The value floats above the thumb ("Any", "30%", "100%") and updates while
  dragging. It uses Dash's native slider tooltip, formatted by
  `window.dccFunctions.thresholdLabel` in `assets/diski9.js`.
* It equals the value used for filtering, and works with mouse, touch and
  keyboard.
* The Any / 50% / 100% marks are kept.

**Threshold behaviour.**
* The label names the outcome, for example "Minimum home win probability".
* With kickoff ordering the slider is disabled, shows Any with no floating value,
  never filters, and says "Available when ranking by a probability".
* The last probability threshold is remembered and restored when you rank by a
  probability again, including after a market switch.

**Two decimals.** Estimated-goal boxes always show two decimals (1.60, -0.15,
0.00).
* Dash's number input drops trailing zeros, so these are text inputs with numeric
  validation on the server.
* A decimal comma is accepted.
* Arrow keys still step the boxes (0.01 for final estimates, 0.05 for category
  adjustments).
* Calculations keep full precision.

**Methodology layout.**
* The content uses the full card width. Related blocks sit side by side on
  desktop: short version | worked example; what changes | settings table;
  limitations | maintenance.
* Sequential material ("How the settings were chosen and tested", the version
  table and formulas) spans the full width, and paragraphs keep a readable line
  length.
* Spacing is tighter, and everything is one column below 1,000 px.

**Wording.**
* k_s 12 and k_t 96 were chosen by comparing candidate values on earlier seasons.
* m0 30 was set to match Diski 9's 30-match league minimum and checked by
  sensitivity analysis (10, 30, 100). It was not tuned.
* None of the settings is described as optimal.

Screenshots in `screenshots/`:

| What | Files |
|---|---|
| Filter card, desktop | `polish_filters_desktop.png` |
| Threshold at 30%, desktop | `polish_threshold_30.png` |
| Phone filters | `polish_filters_mobile.png`, `polish_threshold_mobile.png` |
| Methodology | `polish_methodology_desktop.png`, `polish_methodology_tablet.png`, `polish_methodology_mobile.png` |
| Phone Screener and Match Lab | `polish_screener_mobile.png`, `polish_match_lab_adjust_mobile.png` |

## Known limitations

* Estimated-goal boxes are text inputs, so they have no −/+ spinner buttons;
  arrow keys and typing still work.
* The league summary relies on CSS `:has()`, which is supported by all current
  browsers. Very old browsers would show the name list as well.
* Adjustments are per browser tab and are lost when the tab closes, by design: no
  accounts or saved histories.

## Match Lab and bookmaker refinements

**Section D inputs.** The final-estimate boxes now show their numbers
right-aligned (two decimals, keyboard editing and validation unchanged).

**Bookmaker Market Reference.**
* On desktop the upper part is two columns:
  * left: market-implied probabilities, the consensus odds cards (equal width,
    centred) and the number of bookmaker groups
  * right: "Reading these numbers", which explains raw versus margin-adjusted
    probabilities and margin removal, plus a stale-price note when the prices are
    stale
* "Compare with Diski 9" stays underneath at full width.
* Phones (900 px and narrower) stack the sections.
* Missing-odds cards are unchanged.
* The odds calculations are untouched.

**Section B: Your Match Context Adjustment.** An optional, collapsible subsection at
the foot of Section B, labelled **Your assumptions**:
* one adjustment per team, from −1.00 to +1.00 goals in steps of 0.05, shown
  signed (+0.15, −0.20)
* a default of 0.00
* an optional note: "Why are you making this adjustment?"
* a **Clear Section B adjustments** button, which clears only these two numbers
  (the note is kept)

The explanation warns that much of Section B is already reflected in the model.
Values are never derived from the Form Score, head-to-head or positions. The range
is a guardrail, not a validated effect size.

**How the sections combine:**

```
Your final estimate = model baseline + Section B match context
                      + Section C other factors + additional manual adjustment
```

Section D's breakdown shows all five rows for each team.
* Editing the final estimate directly sets
  `manual = final − baseline − Section B − Section C`.
* Changing Section B or C keeps the manual adjustment and moves the final estimate.
* The final estimate stays within 0–10 goals, with an explanation when a limit
  applies.
* **Reset to model** clears Sections B, C and D and keeps the notes in B and C.

Section B state is stored with the fixture's other adjustments in the browser tab's
memory. It persists across market and fixture switches, stays separate per fixture
and per user, and never reaches the forecast snapshots.

Screenshots in `screenshots/`:

| What | Files |
|---|---|
| Section B | `rf_section_b.png`, `rf_section_b_mobile.png` |
| Section D | `rf_section_d.png`, `rf_section_d_mobile.png` |
| Bookmaker card, desktop | `rf_bookmaker_1x2.png`, `rf_bookmaker_btts.png`, `rf_bookmaker_ou25.png` |
| Bookmaker card, phone | `rf_bookmaker_1x2_mobile.png`, `rf_bookmaker_btts_mobile.png`, `rf_bookmaker_ou25_mobile.png` |

The odds had gone stale by the time these were captured, so the cards show the
stale-price note.

## Odds availability filter

"Only show matches with odds" is a checkbox in a slim row under the filter controls.
It is unchecked by default.

* **When checked,** the Screener lists only fixtures whose selected market has usable
  bookmaker odds, fresh or stale. It uses the same availability as the odds column
  (`ScreenerData.odds_summary`), so fixtures showing "No odds" are left out.
* **Per market:** it applies separately to Match Result, BTTS and Over/Under.
* **Before pagination:** it filters before ranking and paging, so counts, pages and
  sorting stay correct.
* **With other filters:** it combines with leagues, dates, ranking and the
  probability threshold.
* **Market switches** keep the checkbox state.
* **No results:** the message reads "No matches with bookmaker odds available for
  these filters."

Screenshots: `screenshots/odds_filter_desktop.png`, `screenshots/odds_filter_mobile.png`.
