# Milestone 5.1 — Completion report

*16 November 2026 · branch `claude/gifted-newton-h6o5hk`. The engine version
is unchanged at 2.0.0. There are no schema changes and no new API usage.*

## 1. Summary of changes

| Area | Change |
|---|---|
| **A1 About these figures** | Now the first item directly under "Reference odds and market-implied probabilities", collapsed by default. It is a short bullet list covering consensus odds, raw implied, market-implied, Fresh/Stale, and market versus history. |
| **A2 Selected-row highlight** | Selection is owned by the results callback. Root cause: the selection was State, so the table never re-rendered on click. The highlight follows the fixture ID through clicks, sorting, pagination and filtering. If filters remove the fixture, the selection is cleared and the detail panel empties. Mobile cards behave the same. A click keeps the current page. |
| **A3 Rank By / Threshold** | Explicit filter grid columns, so there is no overlap or truncation from 721 px to wide screens. Threshold is enabled only for strongest home/away (1X2) and the BTTS/OU indicator rankings. It is disabled for kickoff time and Most evenly matched, with the hint "Available for strongest home/away rankings". A disabled threshold has no effect. The threshold resets to Any when the ranking changes. |
| **A4 Paired outcomes** | BTTS Yes/No and Over/Under use one component (`paired_outcomes`). Both values render at 30px / 700, which the browser check confirms. |
| **Compact Limited marker** | The table shows a small "Limited" pill with a tooltip explaining the per-market reason. |
| **C Form basis defaults** | BTTS and O/U default to **Overall**. Match Result stays **Venue-specific**. Each market's choice is remembered for the browser session (`dcc.Store`, session storage). |
| **D Market-implied 1X2 summary** | The 1X2 detail summary shows a "Market-implied probabilities" bar and "Home x% \| Draw y% \| Away z%". It uses the same figures as the expanded odds table and follows Fresh/Stale/Unavailable. Stale probabilities are labelled with their retrieval time. Unavailable shows a short message. It is never presented as Challenge-eligible unless Fresh. |
| **B Form Score research** | Offline comparison of banded Method A (production) with continuous Method B: [`milestone5_1_form_score_comparison.md`](milestone5_1_form_score_comparison.md). No production change. |
| **E Market-implied goals research** | Independent-Poisson λ fitted to market probabilities: [`milestone5_1_market_implied_xg.md`](milestone5_1_market_implied_xg.md). Not in the app. |

The Layer 1 (historical indicators), Layer 2 (market-implied) and Layer 3
(model estimates, research only) separation is preserved. Nothing from
Layer 3 reaches the UI, rankings or the Challenge.

## 2. Files

**App:**
* `src/diski9/app/app.py`: selection in the results callback; basis defaults
  and memory; threshold configuration and hint; compact Limited marker.
* `src/diski9/app/views.py`: about-first odds section, `paired_outcomes`,
  `market_probabilities`, freshness wording.
* `src/diski9/app/assets/style.css`: filter grid, hint, pairs, probability
  bar, about list.

**Research (new, isolated from the app):**
* `src/diski9/research/__init__.py`
* `src/diski9/research/form_score_comparison.py`
* `src/diski9/research/market_implied_xg.py`
* `scripts/research_form_score.py`
* `scripts/research_market_xg.py`
* `docs/research/*` (CSV and JSON outputs)

**Tests:**
* `tests/test_app.py` (updated and extended)
* `tests/test_research_form_score.py` (new)
* `tests/test_market_implied_xg.py` (new)

**Other:**
* `scripts/screenshots.js`
* `pyproject.toml` / `uv.lock`: numpy and scipy added to the **dev** group
  only. The app does not import them.
* `README.md`

## 3. Tests and lint

```
uv run pytest -q
uv run ruff check .
```

* `pytest`: 273 passed. That includes a Playwright browser test that clicks
  rows, pages forward and back, and checks that exactly one row is
  highlighted and that it is the selected fixture. Sorting and filtering are
  covered by callback tests.
* `ruff check`: clean.

New tests cover:
* page and selection transitions, highlight by fixture ID, and selection
  cleared when filtered out
* basis defaults and per-market memory
* threshold enabled only where meaningful, and a disabled threshold having
  no effect
* the about expander position, equal typography for pairs, the market-implied
  1X2 summary (Fresh/Stale/Unavailable), and the compact Limited marker
* Method B formula and partial-window cases, point-in-time windows, and
  ranking ties
* Poisson probabilities, synthetic λ recovery, identifiability, invalid
  input, fit categories, and stale exclusion and pre-kickoff guarantees

## 4. Browser checks (`node scripts/screenshots.js`)

| Check | Result |
|---|---|
| Rows highlighted after selecting the 3rd row / first row still highlighted | 1 / no |
| First item in the odds section | "About these figures", collapsed |
| Default basis: BTTS / Match Result | overall / venue |
| BTTS and O/U pair value font | 30px 700 / 30px 700 |
| Threshold with Most evenly matched | disabled, hint shown |
| Mobile: cards highlighted after tap | 1 |
| Horizontal overflow (desktop 1440, iPhone 13 list and detail) | 0 px |

**Screenshots** (in `docs/screenshots/`):
* `desktop_1x2_table.png`
* `desktop_selected_row.png`
* `desktop_1x2_summary_market_probabilities.png`
* `desktop_1x2_detail.png`
* `desktop_odds_section.png`
* `desktop_btts_table.png`
* `desktop_btts_summary.png`
* `desktop_ou25_summary.png`
* `desktop_controls_enabled.png`
* `desktop_controls_disabled.png`
* `mobile_fixture_list.png`
* `mobile_detail.png`

## 5. Research findings (short)

### Form Score

The data covers 3,237 fixtures across EPL, Championship, PSL and 1st Division
from 2024 to 2026.

**How the two methods compare:**
* B removes A's spikes. A has 14 distinct values, and 26% of team scores sit
  at 0.38; B has 94 distinct values.
* B cuts weekly-list ties from 85% to 31% of fixtures.
* B ranks fixtures almost identically to A (ρ = 0.987).
* B gives no significant out-of-sample gain. The log-loss difference B − A is
  about −0.0005, and every 95% confidence interval includes 0.
* Both still put about 53% of scores in the bottom fifth of the scale. The
  cause is that every goal difference ≤ 0, which covers 55% of windows, scores
  zero.

**Exploratory finding:** a symmetric goal-difference variant was consistently,
slightly better. This was not tested formally.

**Recommendation:** keep A. Consider a pre-registered test of symmetric goal
difference.

### Market-implied goals

The data is 180 Fresh pre-kickoff snapshots of 20 EPL fixtures.
* With all three markets: 70% good fits and 30% approximate. The maximum
  residual is 2.3 pp.
* The draw is under-priced by 1.55 pp on average, the classic
  independent-Poisson bias.
* 1X2 alone understates λ by about 0.17, so a goals market should be required.
* **0 settled fixtures**, so outcome validation is not yet possible.

**Recommendation:** keep this as research. Prototype pooled-ρ Dixon–Coles
offline.

## 6. API requests

**Milestone 5.1 used 0 API-Football requests.** All research ran on
committed or cached data.

The separate odds monitoring trial continues on its unchanged schedule and
commits its own captures. `/predictions` was not used. There was no
historical odds backfill.

## 7. Limitations

* The Form Score research covers three seasons, the current one partial. The
  outcome model is a one-feature diagnostic.
* The market-implied goals prototype uses one matchweek and one league, with
  near-static prices and no outcome validation.
* Basis memory lasts for the browser session only. That is by design: it is
  not persisted across sessions or devices.
* Market-implied probabilities in the 1X2 summary are only as current as the
  last odds refresh. Stale values are labelled.

## 8. Decisions requiring your approval (recommendations only; nothing implemented)

| Decision | Recommendation |
|---|---|
| Replace the Form Score with Method B | **Not now.** B has no predictive gain. Approve only if tie-breaking in rankings matters. A pre-registered symmetric goal-difference test is the better next step. |
| Model 1X2 probabilities in production | **No.** No outcome validation yet. |
| Market-implied xG in the UI | **No.** Revisit once settled fixtures allow validation. A goals market must be required, and it should be labelled "market-implied goal expectation", not xG. |
| Dixon–Coles in production | **No.** Prototype offline first, using pooled ρ per league. |
| Challenge rule changes | **None recommended.** Strict Fresh-only eligibility stays. |
| Replace BTTS/OU indicators with model probabilities | **No.** Keep the historical indicators (Layer 1) separate from model estimates (Layer 3). |

## 9. Suggested next milestone (needs approval)

1. Keep the odds trial and on-demand captures running so that settled
   fixtures with pre-kickoff Fresh odds accumulate.
2. Offline: Dixon–Coles (pooled ρ) and a pre-registered symmetric
   goal-difference Form Score test on new fixtures.
3. When you are ready: design (not build) the Challenge and accounts, using
   the strict Fresh-only odds eligibility already in place.
