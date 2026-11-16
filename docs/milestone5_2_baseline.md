# Milestone 5.2 — Baseline and reproduction guide

*16 November 2026. Research only: production calculations, the database schema
and the UI are unchanged. No API-Football requests were made.*

## Data available

| Source | Coverage | Used for |
|---|---|---|
| Completed league fixtures | EPL, Championship, PSL, PSL 1st Division; 2023/24 to 8 Nov 2026. Eligible 2024/25–2026/27 fixtures: 3,237. | Form Score, BTTS/O2.5, historical goal-rate model |
| Saved pre-kickoff odds | 9 trial captures (15–16 Nov) of 20 EPL fixtures (21–29 Nov), plus 5 on-demand fetches | Market inversion (180 snapshots) |
| Settled fixtures with saved pre-kickoff odds | **0** | Real-result validation of the goal models (pipeline ready) |
| Historical bookmaker odds | none (deliberately not backfilled) | — |

## Milestone 5.1 findings: reproduced

`scripts/research_form_score.py` and `scripts/research_market_xg.py` were
rerun. All committed CSV and JSON outputs are byte-identical.

| Finding | Status |
|---|---|
| Banded score: 85% of fixtures tied in weekly lists; continuous B: 31% | Reproduced (84.6% / 31.4%) |
| B gives no meaningful predictive gain over A | Reproduced (walk-forward −0.0006 [−0.0016, +0.0003]) |
| Goal difference ≤ 0 (55% of windows) causes the low-score concentration | Reproduced; C and D (which use negative goal difference) cut the bottom-fifth share from 54% to 17% and 11% |
| Poisson inversion fits the market but underestimates the draw (−1.55 pp) | Reproduced (−1.55 pp) |
| 1X2-only inversion less reliable (λ shift 0.17) | Reproduced (0.17; conditioning 0.12 against 0.79 with all markets) |

## Evaluation periods

| Study | Fixtures | Test period | Method |
|---|---|---|---|
| Form Score A–D | 3,237 (distributions); 1,690 (out-of-sample common sample) | 19 Aug 2025 – 8 Nov 2026 | 14 monthly walk-forward folds |
| BTTS / O2.5 indicators | 3,121 Overall / 3,004 Venue | 16 Aug 2024 – 8 Nov 2026 | point-in-time; walk-forward for fitted models |
| Market inversion | 180 snapshots, 20 fixtures | captures 15–16 Nov 2026 | per-snapshot fits, leave-one-fixture-out |

## Reproduce on a Mac

From the repository folder, after `git pull` and `uv sync`, which installs the
dev dependencies numpy and scipy:

```bash
uv run python scripts/research_m52_form.py
```

```bash
uv run python scripts/research_m52_goals.py
```

```bash
uv run python scripts/research_m52_goal_models.py
```

```bash
uv run pytest -q tests/test_m52_form_models.py tests/test_m52_goal_models.py tests/test_m52_evaluation.py
```

* The first two take seconds; the goal-model script takes about 5 minutes.
* Outputs go to `docs/research/m52/`. Each JSON summary records its
  generation time.
* All randomness is seeded (bootstrap seed 52), and optimisers start from fixed
  grids.
* To include new results in the goal-model validation, first run
  `uv run diski9 refresh-data`. Odds captures already saved by the trial are
  replayed automatically from `monitoring/odds_trial/`.
