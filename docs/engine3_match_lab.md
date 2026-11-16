# Engine 3.0 and The Match Lab

*November 2026. "We calculate the probabilities. You analyse the match. You make
the call."*

* **Methodology for users:** [`methodology.md`](methodology.md), plus the in-app
  "How Diski 9 Calculates Probabilities" section.
* **Model versions:** [`model_changelog.md`](model_changelog.md).

## What changed

| Area | Engine 2.4.0 | Engine 3.0 |
|---|---|---|
| Probabilities | none (Form Score, historical records) | Goal Model 1.0: estimated goals → Poisson → all seven outcomes |
| Leagues | EPL, PSL (Screener) | EPL, Championship, PSL, PSL 1st Division, La Liga, Ligue 1, Bundesliga, Serie A |
| Rankings | form difference, recent occurrence | model probability of the chosen outcome (threshold = minimum probability) |
| Detail panel | analysis card + bookmaker card | The Match Lab (A–D) + bookmaker card with model comparison |
| Form basis selector | Venue / Overall | removed (one season-to-date model) |
| Forecast record | none | insert-only pre-kickoff snapshots + `model-report` |

## Goal Model 1.0

**Code:** `src/diski9/screener/goal_model.py`.
* It is a pure-Python version of the validated research model
  (`diski9.research.goal_distribution`).
* On all 4,524 predictable historical fixtures it agrees with the research code to
  1e-15: estimated goals and every probability.
* `tests/test_goal_model.py` checks agreement to 1e-12 and reproduces the
  research worked example (Aston Villa v Nottingham Forest).

**Parameters and version:**
* `GoalModelParams(k_s=12, k_t=96, m0=30)` is frozen (an immutable dataclass).
* `GOAL_MODEL_VERSION = "1.0"` is separate from `ENGINE_VERSION = "3.0.0"`.
* Each payload carries the model version, parameters and a parameter hash.

**Availability:**

| Situation | Result |
|---|---|
| UEFA competitions (ids 2, 3) | Never modelled. Message: "Diski 9 model probabilities are not yet available for European competitions." UEFA is not in the competition registry, so no UEFA fixtures appear today. |
| No previous season stored and fewer than 30 current-season league matches | Unavailable, with a reason. Nothing is substituted. |
| A team with no matches yet | Uses league averages, labelled "League average only". |
| Either team has fewer than five matches | "Early season". |

## Competition coverage and data

* **Registry:** `leagues.py`. La Liga (140), Ligue 1 (61), Bundesliga (78) and Serie A
  (135) were added with `backfill_seasons=(2025, 2026)`.
  * 2025/26 provides the previous-season league prior; 2026/27 is the current
    season.
  * `odds_enabled` is left off, so the approved odds trial keeps its scope.
* **Setup and refresh:** `setup` and `missing_requirements` use each competition's
  own backfill seasons.
* **Screener coverage:** the Screener and refresh cover all eight leagues
  (`screener_competitions()`).
* **Development backfill (this environment):**
  * 21 API requests: 4 competition records, 8 team lists, 1 bookmaker list and
    8 season fixture lists.
  * Added 2,748 fixtures. Existing rows were untouched (the ingestion is an upsert).

## The Match Lab

The panel opens when a fixture is selected (`app/lab.py`). Its sections:

* **A. Statistical baseline:** estimated goals for both teams and the selected
  market's model probabilities.
  * "How it's calculated" shows the league averages, each team's record, strength,
    tempo, estimated goals, the goal distributions and the model version.
* **B. Match context:** recent form (Form Score, league average, venue context,
  breakdown, matches used); the recent BTTS or Over 2.5 record (goals markets);
  head-to-head; league positions.
  * Reuses the Engine 2.4 calculations.
  * Never changes the model.
  * Carries the "avoid counting the same information twice" note.
* **C. Other factors to consider:** a collapsible checklist (injuries, line-ups,
  congestion, rotation, coaching changes, transfers, venue, weather, motivation).
  * Educational only: no team news is supplied or invented.
* **D. Your adjustments:** for each team, a slider in 0.05 steps with a number box
  (0–10).
  * The slider range is at least 0–5 goals and always above the baseline.
  * Shows your estimate, model versus yours for the selected market with the
    percentage-point change, and "All markets" (all seven outcomes).
  * A Reset button returns to the model.

**State:**
* Adjustments live in `dcc.Store(id="lab-store", storage_type="memory")`, keyed by
  fixture id.
* They persist across market switches and other fixtures in the same tab.
* They are never written to the server or the database, never change the cached
  baseline, and other users never see them.
* The recalculation (`lab_update`, `lab_outputs`) is pure arithmetic on
  `goal_model.markets`.

**Bookmaker card:**
* Unchanged odds functionality: status, freshness, consensus odds, raw implied
  probabilities, margin, and market-implied probabilities.
* The context rows moved into The Match Lab.
* New "Compare with Diski 9" table: model, yours (when adjusted) and market,
  with a "not betting advice" note.
* Odds are never a model input; a test checks this.

## Forecast snapshots

**Table:** `forecast_snapshots` (Alembic `0004`). Columns:
* fixture, competition, season, scheduled kickoff
* `created_at`, `data_cutoff`
* engine and goal-model versions, parameter hash and JSON
* both estimated goals and the probabilities
* the league baseline at the same cutoff
* `forecast_hash`, status

**Recording** (`screener/forecasts.py`, called from `cache.refresh`):
* Only by a live refresh (calculation time equals now; never a `--as-of` replay).
* Only before kickoff, and only when the model is available.
* A new row is written only when the forecast differs from the latest one, so
  repeated refreshes add none.

**Immutability:** SQLite triggers abort any `UPDATE` or `DELETE` on the table.

**Official forecast:** the latest snapshot created strictly before the match's
actual kickoff.
* A postponed match uses the last forecast before it was really played.
* A match brought forward ignores snapshots taken after the new kickoff.

**Rollback:** `alembic downgrade 0003` drops the table and triggers.
* Export the snapshots first: they cannot honestly be recreated afterwards.

## Monitoring

```bash
uv run diski9 model-report
```

**Output:** writes `monitoring/model/model_report_YYYYMMDD.json` and prints the
overall summary.

**What it includes:**
* Only official forecasts of settled, eligible fixtures. Cancelled, postponed,
  abandoned, awarded and play-off fixtures are excluded.
* Grouped by competition, market, month of kickoff and model version, plus pooled
  totals.
* For each group:
  * settled fixtures
  * log loss and Brier score
  * the league baseline's log loss and Brier score (from the same snapshot, so no
    look-ahead)
  * the difference from the baseline
  * calibration bins
  * a "preliminary" flag below 100 fixtures

**Policy:**
* It never changes parameters.
* The annual review rule is in [`methodology.md`](methodology.md#8-maintenance-policy).

## Files

| Area | Files |
|---|---|
| Model | `src/diski9/screener/goal_model.py` (new) |
| Engine | `screener/engine.py` (version 3.0.0, `goal_model` block), `screener/rank.py` (probability rankings), `screener/cache.py` (overall basis, snapshot hook) |
| Snapshots and monitoring | `screener/forecasts.py` (new), `db/schema.py`, `migrations/versions/0004_forecast_snapshots.py` (new), `cli.py` (`model-report`, `screener-show`) |
| Competitions | `leagues.py`, `workflow.py`, `app/data.py` (labels) |
| UI | `app/app.py` (layout, callbacks), `app/lab.py` (new), `app/methodology.py` (new), `app/views.py` (reused blocks), `app/assets/style.css` |
| Tests | `tests/test_goal_model.py`, `tests/test_match_lab.py` (new); `test_app.py`, `test_detail_layout.py`, `test_m53_screener.py`, `test_screener_engine.py`, `test_setup_workflow.py` and others updated |
| Docs | `docs/methodology.md`, `docs/model_changelog.md`, this file, README |

## Screenshots

| Screen | File |
|---|---|
| Screener, desktop | `screenshots/engine3_screener_desktop.png` |
| Screener, phone | `screenshots/engine3_screener_mobile.png` |
| The Match Lab, desktop (with an adjustment and odds comparison) | `screenshots/engine3_match_lab_desktop.png` |
| The Match Lab, phone | `screenshots/engine3_match_lab_mobile.png` |
| Methodology section | `screenshots/engine3_methodology.png` |

## Known limitations

These are carried over from the research:
* draws slightly under-predicted
* cautious favourites in leagues with large talent gaps
* BTTS and Over/Under close to the league average
* no team news
* no UEFA support

In addition:
* The four new leagues have no bookmaker odds, because odds collection is off for
  them. Their comparison table shows "No current bookmaker prices to compare with".
* Monitoring has no settled official forecasts yet. The first snapshots were
  recorded on 16 November 2026, and results will be preliminary until enough
  fixtures settle.
