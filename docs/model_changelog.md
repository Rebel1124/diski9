# Goal Model changelog

Each model version has fixed parameters and an evidence report. Parameters are
never changed in place; a change is a new version, approved only under the annual
review rule in [`methodology.md`](methodology.md#8-maintenance-policy).

| Version | Engine | Released | Parameters | Evidence |
|---|---|---|---|---|
| **Goal Model 1.1** | 3.1.0 | Phase 8 CP2A (accepted 27 Nov 2026; application baseline, not yet deployed) | `k_s` 12, `k_t` 96, team ≥ 2, competition ≥ 20, current season only | [`research/phase8_cp1/`](research/phase8_cp1/report.md) |
| **Goal Model 1.0** | 3.0.0 | November 2026 | `k_s` 12, `k_t` 96, `m0` 30 | [`goal_distribution_research.md`](goal_distribution_research.md), [`goal_model_crossleague_validation.md`](goal_model_crossleague_validation.md) |

## Goal Model 1.1 (Phase 8; accepted application baseline, not yet deployed)

Approved by the owner on 27 Nov 2026 (Phase 8 CP1-1/CP1-2), **out of the annual review
cycle** by explicit owner decision. **Named Goal Model 1.1** (owner decision OD-1, 27 Nov
2026). **Implemented in CP2A** (commit `270ed77`, CI run 168, 27 Nov 2026) and **formally accepted by the owner on 27 Nov 2026 as the application model baseline; **not deployed** to any hosted environment**. Goal Model 1.0's historical forecasts, cache rows and round
snapshots keep their 1.0 identity and stay reproducible from its frozen parameters
(`PARAMS_1_0`, hash `463105f660644ebf`).

* **Method (C1-2-20, "Model A"):** the same strength/tempo Poisson model with `k_s` 12
  and `k_t` 96, using **current-season data only** for both team and competition
  inputs. The league prior (`m0`) and every previous-season input are removed.
* **Availability:** both teams have **≥ 2** eligible completed matches and the
  competition has **≥ 20**. Below that, no independent estimate is shown.
* **Limited-data warning:** shown when the model is available and either team has
  fewer than 5 eligible completed matches.
* **Not changed:** no cross-competition strength, Elo, alternative model or added
  calibration; shrinkage is not user-adjustable; European competitions stay
  unsupported by the independent model (market-only).
* **Evidence:** [`research/phase8_cp1/report.md`](research/phase8_cp1/report.md) and
  [`research/phase8_cp1/simplification_report.md`](research/phase8_cp1/simplification_report.md),
  with the accepted reporting qualifications in
  [`architecture/phase8_implementation.md`](architecture/phase8_implementation.md) §2.

## Market-implied Model 1.0 (Phase 8 CP2B.1; implemented, awaiting review)

Not a Goal Model version: the **State B** starting point used only when Goal Model 1.1
has no independent prediction (OD-2, CP1-5). It never changes Goal Model parameters,
fields, forecasts or snapshots.

* **Method:** the accepted CP1 prototype fit (`research/market_implied_xg.fit`, KL
  objective, multi-start bounded L-BFGS-B, bounds 0.05-6.0, SVD identifiability),
  reused unchanged by `screener/market_fit.py` (`FIT_VERSION` "1.0").
* **Production rules:** R-3 inputs (1X2 plus a goals market, each ≥ 3 independent
  bookmaker groups, quotes ≤ 24 h; frozen inputs judged at the snapshot time);
  good ≤ 2 pp, approximate ≤ 4 pp; non-converged, unidentified, boundary, poor and
  invalid fits rejected.
* **Reconciliation:** identical rates on all 131 qualifying CP1 snapshots (maximum
  difference 0), the same 101 good / 29 approximate statuses, and the one non-converged
  CP1 fit rejected as CP1 recommended.
* **Methodology fingerprint:** every cached result and every Your View stamp carries a
  fingerprint of the method's constants; any change is a new identity.
* **Record:** [`architecture/phase8_implementation.md`](architecture/phase8_implementation.md) §14.

## Goal Model 1.0

**Method:** a season-to-date independent Poisson model with strength/tempo
shrinkage and a league home/away prior.

**Calibration data:** EPL, Championship, PSL and PSL 1st Division.
* Tuning seasons: 2023/24–2025/26.
* Out-of-sample test: 3,237 matches.

**Independent validation:** La Liga, Ligue 1, Bundesliga and Serie A, 4,515
matches.

**Not supported:** the Champions League and Europa League. They were tested and
do not meet the bar.

**Next review:** after the 2026/27 domestic seasons end (planned July 2027). The
held-out season will be 2026/27.
* Candidate to examine: slightly lower strength smoothing (`k_s`), pooled across
  all eight leagues.
* Adopt it only if it meets the rule.
