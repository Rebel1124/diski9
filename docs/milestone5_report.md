# Milestone 5 — Screener Simplification, Revised Form Score & Statistical Methodology

*16 November 2026. Engine version 2.0.0. Methodology reference:
[`screener_methodology.md`](screener_methodology.md).*

## 1. What changed

### Interface (Part A)
* **Ranking.** Every market defaults to **Kickoff: earliest first**, with
  latest-first as an alternative, plus the market's statistical rankings.
  * Sorting uses the UTC kickoff timestamp, after filters, with ties broken by
    kickoff and then fixture id.
  * A ranking is kept when filters change. On a market switch, an invalid
    ranking falls back to kickoff.
  * Clicking the Kickoff or indicator column header toggles the ranking.
* **Pagination.** Ten fixtures per page on desktop and phone, with
  Previous / "Page n of N" / Next and "Showing 1–10 of 28 fixtures".
  * Changing a filter, ranking or market resets to page 1.
  * Pages are slices of a single ranked list, so no fixture is missing or
    duplicated.
  * Paging makes no API calls.
* **Table.** The deprecated Dash DataTable was replaced with a styled HTML
  table rendered on the server.
  * Text is left-aligned; numbers and odds are right-aligned with tabular
  figures.
  * Headers sit over their columns and don't wrap.
  * Positive differences are teal, negative amber.
  * Stale odds are tagged.
  * Dash AG Grid was evaluated and not adopted. Its client-side sorting would
    conflict with server-side ranking and the pagination shared with the phone
    cards, and a plain table gives full control of alignment with no new
    dependency.
* **Dates** read like "Sat 21 Nov, 14:30", with the time zone in the header
  ("Times in SAST"). UTC values are unchanged.
* **Tooltips.** These use a native `<details>` "i" popover, so they work with
  mouse, keyboard and touch (verified on an emulated iPhone).
  * *Form basis* explains Venue-specific versus Overall, with the right
    lookback for each market: five matches for Match result, up to ten
    current-season matches for BTTS and Over/Under.
  * *Diski Form Score* and *Form Difference* use the wording you supplied.
* **Match detail in three levels:**
  1. Summary: headline indicator, both teams' figures, reference odds with a
     Fresh/Stale/Unavailable badge.
  2. A one-paragraph explanation with an expandable "How is Form Score
     calculated?" (or "How is the indicator calculated?").
  3. Collapsed sections: Matches used, full Reference odds and market-implied
     probabilities, League positions, Head-to-head, Other markets.
* Phones keep the fixture cards, ten per page.

### Methodology (Parts B and C)
* The new bonus-based **Diski Form Score** (0–5) replaces the previous
  formula in calculations, cache, ranking, detail, tooltips, tests and docs.
* **Form Difference = home − away** on both bases. The venue-adjusted
  difference and league benchmarks were removed from the public Screener.
  * `select_benchmark` and `pooled_benchmark` remain only as legacy helpers
    for the threshold script and regression comparisons.
  * No database structures were removed.
* **BTTS and Over/Under 2.5** now use current-season, current-competition
  matches only (up to ten).
  * Limited data applies below six matches for either team.
  * There is no fill-in from earlier seasons.
  * Zero matches means the indicator is unavailable.

### Odds (Part D)
* There are now three display statuses: **Fresh**, **Stale** and
  **Unavailable** (`src/diski9/odds/display.py`).
* A stale display is the last valid consensus, recomputed **as of one past
  retrieval**, so quotes from different collection times are never mixed.
  It shows its age, Diski 9's check time and the provider's feed time
  separately.
* **Challenge eligibility stays strict and separate.**
  * `DisplayedMarket.challenge_eligible` is true only when the status is
    `fresh` and the Challenge rules are met.
  * `challenge_consensus()` evaluates the strict rules at the snapshot time,
    with no stale fallback.
* The odds section uses the full card width, keeps the text short, and moves
  the technical notes into a collapsible "About these figures".

### Data and cache (Part E)
* The engine version is `2.0.0`. Every refresh retires active cache rows from
  other versions; the app reads only current-version rows.
* Verified on the development database: 112 old rows retired and 112 new rows
  calculated. No migration or manual database deletion is needed.
* `setup`, `refresh-data` and `serve` are unchanged.

## 2. Worked example: both teams (real data)

**Manchester City v Fulham, Sat 21 Nov, venue-specific.**

| | Manchester City (last 5 home) | Fulham (last 5 away) |
|---|---|---|
| Results (most recent first) | L W W W W | D W L D L |
| Points → award | 12 → 2.0 | 5 → 0.5 |
| Goal difference → award | 11−7 = +4 → 1.0 | 3−4 = −1 → 0.0 |
| Won last 3 | no → 0.0 | no → 0.0 |
| Scored 11+ | 11 → +0.5 | 3 → 0.0 |
| Conceded ≤ 2 | 7 → 0.0 | 4 → 0.0 |
| Raw (max 6.5) | 3.5 | 0.5 |
| **Diski Form Score** | **2.69** | **0.38** |

Form Difference = 2.69 − 0.38 = **+2.31**. Under the previous method it was
+1.22 (venue-adjusted).

The specification's own example (W W W L W, 12 points, 12–3) gives **4.23**,
and a perfect window gives **5.00**. Both are automated tests.

## 3. BTTS and Over/Under with incomplete current-season samples (real data)

| Fixture (venue-specific) | Home team | Away team | Combined | Complement |
|---|---|---|---|---|
| PSL Stellenbosch v TS Galaxy, Over 2.5 | 1/4 (25%) | 3/5 (60%) | 42.5% | Under 57.5% |
| EPL Man City v Fulham, BTTS | 3/5 (60%) | 2/5 (40%) | 50% | No 50% |
| EPL Aston Villa v Sunderland, BTTS | 4/5 (80%) | 4/5 (80%) | 80% | No 20% |

All three are **Limited data**: fewer than six current-season matches. The
real denominators are shown, never "3/10".

## 4. Fresh, stale and unavailable odds (real data)

| Case | Status | Shown | Challenge-eligible |
|---|---|---|---|
| Man City v Fulham, 06:55 UTC, before collecting | **Stale**: 1.40 / 5.00 / 7.04 (10 bookmaker groups). Diski 9 last checked 15 Nov 11:05 UTC (19.8 h); provider update 15 Nov 03:24 UTC (27.5 h, beyond 24 h) | "Prices may have changed" | **No**, despite 10 sources |
| Same fixture after `refresh-data --with-odds` | **Fresh**: 1.40 / 5.00 / **7.08** (the away price moved and was preserved as a new episode); provider update 16 Nov 03:25 UTC | Fresh badge, check and provider times | Yes |
| PSL Stellenbosch v TS Galaxy | **Unavailable** | "API-Football does not currently provide bookmaker odds for the PSL" | No |

Screenshots: `docs/screenshots/desktop_1x2_detail_stale_odds.png` (stale)
and `docs/screenshots/desktop_1x2_detail.png` (fresh).

## 5. How rankings changed (`scripts/compare_methodologies.py`)

The comparison uses 56 upcoming fixtures on the same day and the same data,
venue basis. Raw output is in
[`methodology_comparison.json`](methodology_comparison.json).

| | Result |
|---|---|
| Match result: rank correlation (old venue-adjusted vs new Form Difference) | **0.93** |
| Top-5 home advantage, overlap | 3 of 5 (new entries: Brighton v Newcastle, Chelsea v Leeds) |
| Top-5 away advantage, overlap | 4 of 5 |
| Mean rank shift | 5.0 places |
| Direction flips | 6 fixtures (e.g. Brentford v Arsenal, Stellenbosch v TS Galaxy) |
| BTTS: rank correlation old vs new | 0.75; top-5 overlap 3 of 5; mean change 9.4 points |
| Over 2.5: rank correlation old vs new | 0.68; **top-5 overlap 0 of 5**; mean change 10.3 points |
| BTTS/O2.5 Limited data (venue basis) | old 0 of 56 → **new 56 of 56** |

**Ranking distortions to be aware of** (reported, not changed):
1. **Form Scores bunch at the low end.** Of 112 team scores, 46 are exactly
   **0.38** (raw 0.5) and 57% are 0.77 or below; the median is 0.77.
   * The bands give 0.5 for 3–5 points and 0 for any goal difference ≤ 0, so
     a typical mediocre run (especially away) always lands at 0.38.
   * As a result there are only 16 distinct Form Difference values across 56
     fixtures, with 40 exact ties. These are broken deterministically by
     kickoff, but the "strongest advantage" rankings are coarse.
2. **Venue-specific goals windows are short early on.** By mid-November each
   team has played about five current-season home or away matches.
   * Every venue-specific BTTS/O2.5 indicator is therefore Limited data.
   * Historically this affects about the first 120 fixtures (roughly 12
     matchdays) of an EPL season.
   * The Overall basis reaches ten matches sooner.

## 6. Feasibility notes (no implementation)

**Market-implied expected goals.**
* *Is 1X2 plus Over/Under 2.5 enough?* Under an independent-Poisson
  assumption, home and away goal rates are two unknowns. Margin-removed 1X2
  probabilities supply two independent equations, so they alone identify both
  rates. The Over/Under 2.5 price adds a third, overdetermined equation. That
  can serve as a consistency check, or be fitted by least squares.
* *Would more goal lines help?* Yes. Lines at 1.5, 3.5 and Asian handicaps
  (already in the API's bet 5 data) would constrain the total-goals
  distribution and expose overdispersion.
* *Poisson or Dixon–Coles?* Plain Poisson is a reasonable first model.
  Dixon–Coles adds a low-score correlation parameter that the 1X2 draw price
  is sensitive to. With limited lines, the extra parameter is only weakly
  identified, so it should be fixed from historical results rather than
  fitted per fixture.
* *Validation:* fit on prices collected before kickoff (we now keep these),
  then check calibration against results using reliability curves and the
  Brier or log score by goal line. Compare against a constant-rate baseline
  and check stability across leagues.
* *Labelling:* "market-implied goal expectation", never "xG". Observed xG is
  a shot-quality statistic, a different thing.

**Calibrated goals model for BTTS/O2.5.** If revisited, a Poisson or
Dixon–Coles model fitted to point-in-time results could produce probabilities.
It would need to be validated with log loss and calibration on held-out
seasons, and kept visually distinct from the historical indicators. Nothing
was built.

## 7. Testing and validation

* **Automated:** 228 tests pass (previously 174), and ruff is clean. New
  coverage includes:
  * every points band and goal-difference band
  * each bonus alone and all together
  * three most recent wins versus wins elsewhere in the window
  * normalisation and the 0/5 bounds (property-based)
  * missing history and partial windows
  * the 4.23 and 5.00 examples
  * Form Difference ranking with ties and unavailable values
  * the current-season-only rule (previous season, other division,
    relegation round and awarded matches excluded)
  * 4-, 5-, 6-, 9-, 10- and 12-match samples, and zero observations
  * the 57.5% / 42.5% example
  * Fresh, Stale and Unavailable odds; a coherent, never-mixed stale
    snapshot; stale never Challenge-eligible; independent groups
  * pagination with no gaps or duplicates and reset on filter change
  * kickoff ranking on timestamps; header sort
  * detail levels; tooltips
  * no API calls across every market, ranking and page
  * a Playwright phone test: 10 cards, touch tooltip, pager, no horizontal
    scroll
* **Historical sanity check:** 1,394 EPL/PSL fixtures (2024–2026) under the
  new engine, with **0 failures**.
  * Checks: no future matches; independent reconstruction; an independent SQL
    re-implementation of the Diski Form Score; bounds; determinism; and a new
    check that every goals-market match is from the fixture's season and
    competition and matches an SQL count.
* **Live checks:**
  * a clean first-time `setup --with-odds` on a brand-new database (42
    requests, 5,682 fixtures, only 2.0.0 cache rows)
  * cache invalidation on the development database (112 old rows retired)
  * `refresh-data --with-odds` (9 requests)
* **Browser (Playwright, Chromium):** desktop screenshots of all three markets,
  the form breakdown, the tooltip, the PSL detail and both odds states; phone
  list and detail.
  * 10 rows / 10 cards per page; the league filter works (PSL only: 8).
  * The tooltip opens by tap; no horizontal overflow at either size.
* **Not verified:** real Safari or Android browsers (emulation only) and
  screen-reader behaviour.

## 8. API quota (Milestone 5)

57 requests: 6 (baseline refresh), 9 (refresh with odds) and 42 (clean setup
test). The odds trial's scheduled captures are counted separately; it is
unchanged and still running until 21 Nov.

## 9. Decisions made, and items for your review

1. **Form Score Limited data** follows your "fewer than five matches" rule. I
   also kept the v1.2 "fewer than 3 current-division matches" rule (not
   superseded), so a promoted club with five Championship matches is still
   flagged. Please confirm.
2. **Thresholds** apply only to the statistical rankings. With a kickoff
   ranking the slider is disabled ("Off for kickoff ranking"), because no
   single threshold fits the 1X2 directions.
3. **Column-header sorting** is kept but drives the Rank by control, so
   sorting and pagination never disagree.
4. **The draw-rate context line** was removed along with the league
   benchmarks.
5. **The Form Score compression and the universal venue-specific Limited data
   for goals markets** (section 5) are material. Possible responses, for you
   to decide, nothing implemented:
   * adjust the bands, for example give credit to small negative goal
     differences or raise the points granularity
   * make Overall the default basis for BTTS/O2.5
   * lower the goals-market Limited threshold early in the season

## 10. Updating a local installation

```bash
git pull origin claude/gifted-newton-h6o5hk
uv sync
uv run diski9 refresh-data --with-odds   # retires old-methodology results, recalculates
uv run diski9 serve
```

No database reset is needed. A brand-new computer uses `uv run diski9 setup
--with-odds` instead of `refresh-data`.

## 11. Recommended next milestone

1. Decide on the scoring-band and goals-basis questions in section 9.5, then
   re-run `compare_methodologies.py`.
2. Analyse the completed odds trial (ends 21 Nov) and the PSL checks (25 and
   27 Nov). Finalise the freshness window and the Challenge snapshot timing.
3. Build the Challenge snapshot service on `challenge_consensus()`, the
   strict path only.
4. Run a short usability check of the simplified Screener with a few football
   fans before starting the Challenge interface.
