# Milestone 5.3 — Completion report

*16 November 2026 · branch `claude/gifted-newton-h6o5hk` · engine 2.1.0.*

## 1. Summary

| Workstream | Result |
|---|---|
| **A. Model D** | Implemented exactly as researched: 2.5 × P/15 + 2.5 × (clip(GD, −9, 9) + 9)/18, no bonuses, Unavailable when there is no history. Used for every Form Score, Form Difference, ranking, threshold, card and detail. The "How it's calculated" expander shows each team's actual arithmetic. Details: [`milestone5_3_model_migration.md`](milestone5_3_model_migration.md). |
| **B. BTTS / O2.5 presentation** | Three labelled layers: historical records as counts, the league baseline, and market-implied Yes/No (Over/Under) with equal typography. The averaged team percentage is no longer a headline. Details: [`milestone5_3_screener_ux.md`](milestone5_3_screener_ux.md). |
| **C. League baselines** | Point in time, the exact Milestone 5.2 method: current season from 30 matches; otherwise blended with the previous season by weight n/30; Unavailable when no prior exists. Blending is labelled. |
| **D. Limited data** | Threshold still 6. True counts are shown with a per-team `Limited` tag. "No current-season history" replaces any 0 of 0 or 0%. A baseline is never presented as a team rate. |
| **E. Market-implied probabilities** | BTTS Yes/No and Over/Under 2.5 now appear in the summary card and in a table column, with Fresh/Stale/Unavailable states and the same numbers as the odds table. |
| **Rankings** | Relabelled "Highest / Lowest recent BTTS (Over 2.5) occurrence", with matching threshold labels. The algorithm is unchanged. |
| **Cache safety** | Old-version rows are never served. A banner asks for `screener-refresh` until the cache is rebuilt. |

No Layer 3 output (model probabilities or market-implied expected goals)
reached the UI. The Challenge is unchanged.

## 2. Files

**Production:**
* `src/diski9/screener/calc.py`: Model D (`DiskiFormScore`); Model A kept as
  the legacy `BandedFormScore`.
* `src/diski9/screener/engine.py`: `ENGINE_VERSION = "2.1.0"`;
  `league_baseline()`; baseline added to each result.
* `src/diski9/screener/sanity.py`: the independent form check now re-derives
  Model D.
* `src/diski9/app/views.py`:
  * Model D explanation and calculation table
  * records, baseline and market blocks
  * `goals_market_probabilities`
  * goals breakdown
  * other-markets text
* `src/diski9/app/data.py`: ranking labels; record, baseline and market
  columns; outdated-row count.
* `src/diski9/app/app.py`: columns with tooltips, threshold labels and hint,
  legend, cards, outdated-cache banner.
* `src/diski9/app/assets/style.css`: record, baseline and compact pair
  styles.

**Research (unchanged behaviour):** `research/form_models.py` and
`research/form_score_comparison.py` import the legacy Model A explicitly. Both
the 5.1 and 5.2 scripts rerun with unchanged outputs.

**Tests:**
* `tests/test_m53_screener.py` (new, 31 tests)
* updated: `test_screener_engine.py`, `test_app.py`, `test_diski_form_score.py`
  (now the legacy Model A), `test_m52_form_models.py`,
  `test_research_form_score.py`

**Docs and scripts:**
* `docs/milestone5_3_*.md`
* `scripts/screenshots.js`
* `README.md`

## 3. Tests and lint

```
uv run pytest -q
uv run ruff check .
```

* **354 passed** (322 before, plus 32 new: 31 in the new file and 1 Model D
  identity test in the research tests).
* Ruff check and format: clean.

**New coverage:**
* **Model D:** exact formula and the worked example (3.47), bounds, positive /
  zero / negative goal difference and clipping, linear points, no bonuses,
  partial windows, missing history, Venue and Overall windows, Form
  Difference, ranking consistency, no lookahead.
* **Engine and cache:** version bump; old rows never served; the banner until
  the rebuild.
* **League baselines:** current-season rule, n/30 blend, previous season only,
  Unavailable, future / awarded / other-competition / the fixture itself
  excluded, postponed, cancelled and abandoned fixtures excluded, equality
  with the 5.2 research, team records still current-season only.
* **Records:** "BTTS in k of n" with its complement; Over/Under; denominators;
  Limited per team; "No current-season history" (never 0%); Overall versus
  Venue.
* **Market:** values identical to the odds table; the pair sums to 100%;
  equal typography; Stale and Unavailable; table and card values; Challenge
  eligibility unchanged.
* **Interface regression:** the existing selection-highlight browser test,
  phone viewport, pagination, sorting, threshold states and basis defaults all
  still pass.

**Browser checks** (`node scripts/screenshots.js`):
* one selected row; one selected card on mobile
* BTTS defaults to Overall
* market pair 22px / 700 on both sides
* 0 px horizontal overflow on desktop (1440) and iPhone 13 (list and detail)
* table headers: Home record · Away record · Recent BTTS · League · Market
  Yes · No · Data

## 4. Migrations, cache and API

* **Database:** no schema change and no migration. Raw fixtures and odds are
  untouched.
* **Cache:** `uv run diski9 screener-refresh --days 21` rebuilt it locally:
  112 inserted, 112 version 2.0.0 rows retired, **0 API requests**.
* **API-Football requests used by Milestone 5.3: 0.** The odds-monitoring
  trial continued separately on its unchanged schedule.

## 5. Effect on current rankings (56 upcoming fixtures)

* Ties fall from 95% to 41% (Venue) and 30% (Overall).
* Top-five overlap with Model A is 3–4 of 5 for home and away advantage, and
  2 of 5 for "most evenly matched".
* Model A's five-way tie at 0.00 is gone.

See the migration document, section 6.

## 6. Screenshots (`docs/screenshots/`)

| # | View | File |
|---|---|---|
| 1 | Match Result table (Model D, ranked by home advantage) | `m53_1x2_table.png` |
| 2 | Expanded Match Result detail with the calculation | `m53_1x2_detail.png` |
| 3 | BTTS table | `m53_btts_table.png` |
| 4 | Expanded BTTS detail | `m53_btts_detail.png` |
| 5 | Over/Under table | `m53_ou25_table.png` |
| 6 | Expanded Over/Under summary | `m53_ou25_detail.png` |
| 7 | Limited data (Venue basis) | `m53_limited_example.png` |
| 8 | League baseline, early season (blended) | `m53_league_baseline_explanation.png` |
| 9 | Mobile list and detail | `m53_mobile_screener.png`, `m53_mobile_detail.png` |

Screenshot 8 comes from a scratch copy of the database evaluated on 29 August
2026. No live fixture is currently early in its season.

## 7. Known limitations

* **Venue-specific goals records are Limited for most fixtures** (5 venue
  matches by mid-November). This is correct under the threshold of 6, but it
  makes the tag common on the Venue basis. Overall remains the default.
* **The league baseline is "current season only"** for every live fixture
  today. The blended path is exercised by tests and the scratch screenshot.
* **Model D's improvement on Venue form was not statistically conclusive**
  (Milestone 5.2). The change is justified mainly by design (ties, negative
  goal difference, simplicity).
* **The "recent occurrence" rankings remain,** although Milestone 5.2 found
  little within-league signal in them (see section 8).
* **Market-implied BTTS / O2.5 still lack outcome validation.** 0 settled
  fixtures have saved pre-kickoff odds yet.

## 8. Recommendations

* **Recent-occurrence rankings: keep for now, consider replacing later.**
  * They are honest after the relabelling.
  * A future option is a "Market-implied BTTS / Over 2.5" ranking, which sorts
    by bookmaker expectations, clearly labelled as such. It should be
    considered only once outcome validation of market probabilities has
    begun.
  * Removing the history rankings entirely is premature while some users rely
    on them.
* **No further modelling changes before the Challenge.** The Challenge relies
  on Fresh market odds, which are unchanged. Model and goal-expectation work
  should continue offline only.
* **Next:**
  1. Keep collecting odds. After 21 November, run `refresh-data` and the
     Milestone 5.2 validation pipeline monthly.
  2. Review the market-implied ranking idea and goal expectations after about
     150 settled fixtures.
  3. Start Challenge design only with your approval.
