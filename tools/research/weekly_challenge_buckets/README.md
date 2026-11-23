# Weekly Challenge probability-bucket research (read-only)

Reproduces the probability-bucket investigations (Scenarios A, B, C, D, A2 and A3) behind the
approved A3 bucket design. The findings, methodology and limitations are in
[`docs/research/weekly_challenge_bucket_review.md`](../../../docs/research/weekly_challenge_bucket_review.md).
The aggregate outputs are in
[`docs/research/weekly_challenge_buckets/`](../../../docs/research/weekly_challenge_buckets/).

This is research tooling. It does not read or change the production challenge configuration,
and it is not used by the application.

## Run

From the repository root:

```bash
uv run python tools/research/weekly_challenge_buckets/bucket_study.py all
```

* Full run: about 8–10 minutes on one core. It writes `summary.json` and `weekly.csv` to
  `docs/research/weekly_challenge_buckets/`.
* `--quick`: a smoke run (fewer draws and replicates) in under a minute. Use `--out` to write
  it somewhere else.
* `--work DIR`: where the per-fixture backtest (`hist.json`) is cached. It defaults to the
  system temporary directory and must be **outside** the repository. Delete it to force a new
  backtest.
* `backtest` alone: `... bucket_study.py backtest --work DIR`.

## Inputs

| Input | Committed? | Notes |
|---|---|---|
| `data/diski9.sqlite` (local football store) | **no** | Opened read-only (`mode=ro`). Needs the competitions, seasons and completed fixtures that `diski9 setup` and the refresh jobs store. Results only; no credentials |
| `docs/research/weekly_challenge_risk/pool_fortnight.json` | yes (Phase 6A.1) | The real strict-consensus market snapshot of 17 Nov 2026 22:00 UTC |
| `hist.json` (work directory) | **no** | Derived per-fixture data (point-in-time Goal Model probabilities and actual scores). Regenerated in seconds from the store |

## Guarantees

* No network access, no provider calls and no database writes. The store is opened with
  SQLite `mode=ro`.
* Fixed seeds throughout, so reruns on the same store and pool give identical outputs.
* Production functions are reused unchanged:
  * `screener.goal_model.fixture_estimate`: point-in-time Goal Model 1.0, using only results
    before Thursday 06:00 UTC of each round week;
  * `challenge.structured._match`: the exact 4/3/2 distinct-fixture matching used by the D-28
    opening check;
  * `challenge.structured.evaluate_groups`: payouts, D-15 rounding, eight states, recovery;
  * `challenge.scoring.score_round`: D-31 points (`points-150-75-v2`).
* Committed outputs are aggregates only. No team names, per-fixture records or provider
  payloads.

## What the run computes

| Section of `summary.json` | Content |
|---|---|
| `availability` | Per scenario: unique fixtures per bucket per week (median, p10, p25, min, max) and unplayable weeks under the full D-28 rules. Real weeks, the 6-league proxy and the 8-league proxy |
| `low_probability_band` | Real outcomes below 40% by market band (types, leagues, margin, bookmaker groups, model-versus-market gap); proxy 10–20% outcomes per week |
| `foundation_ceiling_90_95` | Proxy outcomes between 90% and 95% |
| `calibration_check_actual_results` | Predicted versus observed win rates by band, settled on actual results (indicative) |
| `strategies` | Conservative, random and aggressive completion probabilities, recovery and expected gross: exact on real weeks, median over proxy weeks, settled on actual results; difficulty-ordering counts |
| `bootstrap_challenger_minus_balanced` | Bootstrap over fixtures for the Balanced/Challenger ordering (A2 and D) |
| `leaderboard` | Paired leaderboard simulation (identical outcomes and participant noise across scenarios), D-31 points, volatility, large payouts, championships, concentration; paired differences versus A with standard errors |

`weekly.csv` has one row per proxy week (Aug 2025 – Nov 2026, 6 leagues): eligible fixtures
and, per scenario, the median Foundation, Balanced and Challenger fixtures and the playable
share across draws.
