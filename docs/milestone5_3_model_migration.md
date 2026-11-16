# Milestone 5.3 — Diski Form Score migration (Model A → Model D)

*16 November 2026 · engine **2.0.0 → 2.1.0**.*

## 1. Old versus new

| | Old: Model A (engine 2.0.0) | New: Model D (engine 2.1.0) |
|---|---|---|
| Points | bands: 0–2 → 0, 3–5 → 0.5 … 15 → 2.5 | continuous: 2.5 × P ÷ 15 |
| Goal difference | bands: ≤ 0 → 0, +1–2 → 0.5 … ≥ +9 → 2.5 | continuous and symmetric: 2.5 × (clip(GD, −9, +9) + 9) ÷ 18 |
| Bonuses | +0.5 each for won last three, scored ≥ 11, conceded ≤ 2 | **none** |
| Scale | raw ÷ 6.5 × 5 | already 0–5 |
| An average team (7–8 pts, GD 0) | about 0.8 | about 2.5 |
| GD −1 against GD −8 | identical (both 0) | different (1.11 against 0.14) |

**Why the change** (from [`milestone5_2_form_score_research.md`](milestone5_2_form_score_research.md)):
* Ties in weekly lists fall from about 85% to 21%.
* Negative goal differences are distinguished.
* The score is simpler to explain.
* There is a small, statistically supported gain on Overall form (−0.0036 log
  loss, 95% CI excludes zero). The gain on Venue form was not conclusive.
* The bonuses added nothing measurable.

This is a better score design. **It is not a probability.**

## 2. Exact formula

For the last five eligible completed matches, with P = points (3 per win, 1
per draw) and GD = goals for − goals against:

```
Points component          = 2.5 × P / 15
Goal-difference component = 2.5 × (clip(GD, −9, +9) + 9) / 18
Diski Form Score          = Points component + Goal-difference component   (0 to 5)
```

**Worked example:** 10 points, GD +4. Points 2.5 × 10/15 = 1.67; goal
difference 2.5 × 13/18 = 1.81; **score 3.47**.

**Implementation:**
* `screener/calc.py` → `DiskiFormScore` / `diski_form_score`, using exact
  fractions. The result is rounded half-up to two places for display only.
* A test asserts it equals the researched Model D
  (`research/form_models.score("d")`) on 2,000 random windows.

**Kept as a legacy helper:** Model A is kept as `BandedFormScore` /
`banded_form_score`, solely so the Milestone 5.1 and 5.2 research reproduces
(both rerun with unchanged outputs). The Screener never calls it.

## 3. Windows and rules (unchanged)

* **Venue-specific:** the home team's last five eligible home matches and the
  away team's last five eligible away matches (confirmed neutral venues
  excluded).
* **Overall:** each team's last five eligible matches.
* **Same rules as before:**
  * eligibility (completed, regular season, not awarded or abandoned)
  * point in time (only matches before kickoff)
  * the existing provenance of earlier-season or other-division matches in the
    form window
* **No history:** **Unavailable**, never 0.

## 4. Partial windows

* With fewer than five matches, the actual totals of the matches available
  are used. Nothing is invented or prorated.
* **A short window cannot reach 5.** Four 5-0 wins score 2.00 + 2.50 = 4.50.
* **A short window can still score above 0.** The goal-difference component is
  symmetric, so a level goal difference is worth 1.25 even after one match: a
  single 1-1 draw scores 0.17 + 1.25 = 1.42.
* The existing **Limited data** flag (fewer than five matches, or fewer than
  three current-division matches) stays. The expanded calculation shows the
  match count and the arithmetic.

## 5. Engine version and cache invalidation

* `ENGINE_VERSION` is now `"2.1.0"`. Version 2.1.0 also adds the league
  BTTS / Over 2.5 baseline to each cached result.
* The cache (`screener_results`) is versioned:
  * Every read (`cache.cached`, the app's snapshot) selects **only** rows of
    the current engine version.
  * `cache.refresh` first **retires** (supersedes) every active row from
    another version.
  * Old rows are kept for audit, never deleted, so nothing is destroyed.
* **Model A scores can never be shown next to Model D scores.**
  * Between deploying the code and rebuilding, the app shows no results rather
    than mixed ones.
  * It shows a banner: *"The statistics were calculated with an earlier method.
    Run `uv run diski9 screener-refresh` to rebuild them (no API requests)."*
* Rankings, threshold filters, table columns, cards and expanded details all
  read from the same cached payload, so they all use Model D.
* **Data safety:**
  * There is no database migration and no schema change.
  * Raw fixtures and odds snapshots are untouched.
  * The ongoing odds trial is unaffected.
* **Verified locally:** the rebuild inserted 112 rows (56 fixtures × 2 bases)
  and retired 112 version 2.0.0 rows, with no API requests.

## 6. Effect on current rankings

This covers 56 upcoming EPL and PSL fixtures (16 November – 7 December),
comparing the cache before and after the rebuild.

| | Venue A | Venue D | Overall A | Overall D |
|---|---|---|---|---|
| Distinct Form Differences | 16 | 44 | 18 | 47 |
| Fixtures tied with another | 95% | **41%** | 95% | **30%** |

**Overlap of the top five, A against D:**

| Basis | Home advantage | Away advantage | Evenly matched |
|---|---|---|---|
| Venue | 3/5 | 4/5 | 2/5 |
| Overall | 4/5 | 4/5 | 2/5 |

**Notable movers:**
* **Sekhukhune United v Siwelele** goes from outside the top five to first on
  home advantage (Venue: +3.50). Siwelele lost all five away matches with GD
  −8, which Model A scored the same as GD −1.
* **"Most evenly matched"** under Model A was five fixtures tied at exactly
  0.00. Model D separates them (−0.03, −0.17, −0.19 …).
* The strongest fixtures stay near the top under both models (Sundowns v
  Polokwane, Orlando Pirates' home games, Newcastle v Arsenal), with smaller
  gaps. Orlando Pirates v Golden Arrows (Overall) goes from +5.00 to +3.83.

## 7. Rebuild instructions

From the repository folder, after updating:

```bash
uv run diski9 screener-refresh --days 21
```

* This recomputes the cache for the next 21 days of top-tier fixtures from
  local data only (0 API requests).
* `uv run diski9 refresh-data` does the same rebuild as part of its routine
  refresh, but it also calls API-Football for new results. Use it only when
  you want new results.
