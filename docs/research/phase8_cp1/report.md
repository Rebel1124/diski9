# Phase 8 CP1: offline research report

*26 Nov 2026. This is research only.*

**What was not done:**
- Goal Model 1.0 is unchanged and remains the accepted production baseline;
- no production module, dependency or lockfile was modified;
- no provider calls;
- no PostgreSQL database was accessed.

**Labels:**
- **[V]** computed or verified;
- **[A]** assumption;
- **[R]** recommendation.

**Nothing here is adopted.** Every model, threshold and parameter needs explicit owner approval.

**Reproduce:**

```bash
uv run python scripts/research_phase8_cp1.py all
```

```bash
uv run pytest tests/test_phase8_cp1_research.py
```

- The run takes about 15 s.
- Inputs: the local, git-ignored stores `data/diski9.sqlite` and `data/research_crossleague.sqlite`. They are copied to a temporary directory and never modified.
- Outputs (this folder):
  - `model_summary.json`
  - `coverage_domestic.csv`
  - `market_summary.json`
  - `market_fits.csv`
  - `pools_summary.json`
  - `weekly_pools.csv`

## 1. Baseline

**[V]**
- Branch `feature/phase-6c6-operations`, accepted baseline `de6b249`.
- The pre-registration (`preregistration.md`) was committed as `e8f987f` **before any result was computed.**
- After results were seen, the script changed only in two ways: a memory measurement fix (the market footprint) and lint-only refactors. No evaluation logic, candidate, criterion or period changed.

## 2. Pre-registered methodology (summary)

See [`preregistration.md`](preregistration.md) for the full procedure. **This is a pre-registered re-analysis of previously examined seasons, not an untouched holdout.**

| Item | Setting |
|---|---|
| Candidates | C0 (Goal Model 1.0); C0-k (C0 with both teams ≥ k matches); C1-k-L (current-season competition averages only, both teams ≥ k, competition ≥ L matches); C1-k-L-T (re-tuned shrinkage, only if calibration alone fails) |
| Grid | k ∈ {2, 3, 4, 5}; L ∈ {20, 30, 40} |
| Selection period | 2023/24–2024/25 |
| Confirmation period | 2025/26 and 2026/27 to date, evaluated once with the frozen choice |
| Leakage control | A completed match counts only if it kicked off **at least 3 hours** before the forecast kickoff, so overlapping or unfinished matches never leak. Competition averages and team records use current-season, current-competition matches only. |
| UEFA stages | Allowlist; qualifying (including the August "Play-offs") and the final excluded; **unknown labels and impossible stage orders stop the run** |
| Comparisons | Identical fixtures; withheld fixtures reported separately; 95% bootstrap CIs by ISO week |
| Production agreement | **[V]** C0 in the research code reproduces production `goal_model.estimate` to 6.7e-16 on 200 sampled fixtures. A unit test enforces 1e-12. |

## 3. Domestic results

**Rows:** 9,164 domestic fixtures across 8 leagues. 3,269 confirmation fixtures were identical for C1 and C0.

### 3.1 Selection (2023/24–2024/25)

**[V]** All 12 C1-k-L combinations passed D1–D4 (`model_summary.json → domestic_selection_grid`):
- 1X2 Δ against C0: +0.0012 to +0.0017, upper bounds ≤ +0.0027;
- BTTS and O/U upper bounds ≤ +0.0021;
- home-win slope 1.06–1.08;
- ECE within 0.0012 of C0;
- the k–5 band beats the baseline in every combination.

**Selected under the pre-registered rule** (smallest k, then smallest L): **C1-2-20**, with k_s 12 and k_t 96. Re-tuning (C1-k-L-T) was not triggered.

### 3.2 Confirmation (2025/26–2026/27): C1-2-20 against C0, identical fixtures, pooled

| Criterion | Result | Verdict |
|---|---|---|
| D1: 1X2 log-loss Δ | **+0.0023 [+0.0009, +0.0039]** | **pass:** within the +0.005 margin, but a *statistically detectable* small deterioration |
| D2: BTTS Δ | upper bound +0.0025 | pass |
| D2: O/U Δ | upper bound +0.0026 | pass |
| D3: home-win slope / ECE | 1.08; ECE 0.0102 against C0's 0.0136 | pass |
| D4: k–5 band against current-season baseline | −0.054 [−0.070, −0.036] | pass |
| D5: coverage target 85% | 90.4% of confirmation fixtures | target met |

### 3.3 Per league (confirmation, 1X2 Δ against C0)

| League | n | Δ 1X2 [95% CI] | Verdict | Material deterioration flag |
|---|---|---|---|---|
| EPL | 440 | +0.0015 [−0.0014, +0.0044] | pass | – |
| Championship | 684 | +0.0014 [−0.0007, +0.0034] | pass | – |
| La Liga | 459 | +0.0009 [−0.0005, +0.0025] | pass | – |
| Ligue 1 | 353 | +0.0033 [−0.0019, +0.0082] | inconclusive | – |
| Bundesliga | 337 | +0.0025 [−0.0005, +0.0057] | inconclusive | – |
| **Serie A** | 450 | +0.0026 [+0.0000, +0.0056] | deterioration (borderline) | **flagged** |
| **PSL** | 271 | **+0.0061 [+0.0027, +0.0098]** | **deterioration** | **flagged** |
| PSL 1st Division | 275 | +0.0022 [−0.0107, +0.0135] | inconclusive (wide CI) | – |

**Notes:**
- **The PSL is the clear per-league cost**, concealed by the pooled result.
- **Serie A** is borderline: its lower bound is +0.00001.
- **O/U on its own:** EPL [+0.0012, +0.0075] and Ligue 1 [+0.0006, +0.0041] are also significantly slightly worse.

### 3.4 Where the cost sits: by the smaller team's match count

| Band | n | C1 − C0 1X2 | C1 against baseline |
|---|---|---|---|
| 2–5 matches | 576 | **+0.0085 [+0.0024, +0.0149]** | −0.054 (better than baseline) |
| 6–9 | 589 | +0.0018 [−0.0012, +0.0047] | better |
| 10+ | 2,104 | +0.0007 [−0.0000, +0.0015] | better |

**Removing last season's league average costs accuracy mainly in the first 5 rounds.** After that the two models converge.

### 3.5 Withheld fixtures

- 346 confirmation fixtures (9.6%) are available to C0 but withheld by C1-2-20.
- On them, **C0 is no better than the competition baseline:** 1X2 −0.003 [−0.018, +0.008].
- **Withholding the first rounds therefore loses no demonstrated predictive value.**

### 3.6 Alternatives (as pre-registered)

| Option | Coverage (confirmation) | Quality on covered fixtures | Character |
|---|---|---|---|
| **C1-2-20** (current-season only) | 90.4% | +0.0023 1X2 against C0 (within margin); PSL worse | Owner's preferred philosophy |
| **C0-2** (Goal Model 1.0 + gate) | 91.5% | identical to C0 (beats baseline by −0.052) | Keeps the previous-season league average |
| **Goal Model 1.0 unchanged** | 100% | reference | No team-data gate; opening rounds no better than baseline |

## 4. Coverage and early-season trade-offs

**[V]** From `coverage_tradeoff` and `coverage_domestic.csv`:

| Candidate | Full seasons (2023/24–2025/26) | Partial (2026/27 to date) | Lowest league, full seasons |
|---|---|---|---|
| C0 | 98.5% | 100% | PSL 95.6% |
| C0-2 / C0-3 / C0-5 | 93.9% / 91.5% / 86.2% | 81.6% / 72.6% / 54.1% | PSL |
| **C1-2-20** | **93.8%** | **79.4%** | PSL 1st Division 91.0% |
| C1-3-20 | 91.7% | 72.6% | PSL 89.3% |
| C1-2-40 | 88.0% | 60.3% | PSL 82.6% |
| C1-5-20 | 86.2% | 54.1% | PSL 82.0% |

**Context:**
- C0 is below 100% only where a league's first stored season had no prior.
- The partial season is mid-November, so a larger share of it falls in the gated opening rounds.

**How each k translates into rounds:**
- In a 20-team league, k = 2 withholds the first **2 rounds**, about 5% of a 38-round season.
- In 16-team leagues (PSL, PSL1), L = 20 also binds in round 3, because 16 matches is below 20. PSL coverage is therefore about 91% per full season.

**South African leagues:**
- C1-2-20 withholds about 9% of PSL and PSL1 fixtures per season (the first 2–3 rounds).
- The provider has **no PSL or PSL1 odds**, so those fixtures will show the honest unavailable state (state C) with no market alternative.

## 5. Champions League

**Rows:** 312 selection and 260 confirmation main-stage fixtures (final excluded).

**Selection:**
- C1-2 (the domestic k) failed E2 (BTTS inconclusive), so E5 selected **C1-3-20 as a separate CL threshold.**
- It passed E1–E3 on selection, with slope 1.13.

**Confirmation, C1-3-20:**

| Criterion | Result | Verdict |
|---|---|---|
| E1: 1X2 against competition baseline | −0.035 [−0.065, −0.008] | pass |
| E2: BTTS | upper bound +0.039 | inconclusive |
| E2: O/U | upper bound +0.0065 | inconclusive |
| E3: home-win slope | **1.42** (too cautious) | **fail** |
| E4: available confirmation fixtures | **152** of 260 (2026/27 is mid league phase) | **fail** |

- **C0 on CL confirmation:** E1 passes (−0.025), but E3 fails (slope 1.53).
- **C1-3-20 against C0 on identical fixtures:** +0.0026 [0.000, +0.0054].

**Coverage by stage [V]:** with k = 3, league-phase matchdays 1–3 are withheld and matchday 4 onward plus every knockout is available. With k = 2, matchdays 1–2 are withheld. Matchday counts are actual completed matches, not nominal.

**Conclusion:** **the CL independent model does not meet the pre-registered criteria.**
- Calibration is demonstrably poor: too cautious in both periods, consistent with the 16 Nov research.
- The confirmation sample is too small.

**[R]** CL uses market-implied starting points (state B) for the MVP. Revisit when 2026/27 completes, which would give about 260 or more available confirmation fixtures. **The criteria will not be relaxed.**

## 6. Europa League

Same run, no bespoke work. C1-2-20 passed E1–E3 on selection (slope 1.08).

**Confirmation:**

| Criterion | Result | Verdict |
|---|---|---|
| E1 | −0.038 [−0.074, +0.001] | **fail** |
| E2 | | inconclusive (both) |
| E3: home-win slope | **1.90** | **fail** |
| E4: available fixtures | 188 | **fail** |

C0 also fails E1 and E3 (slope 2.01).

**[R]** No independent EL model. Include the EL only as market-implied or unavailable, if the owner sees value.

## 7. Market-implied fit quality (cached odds; not outcome validation)

**Data [V]:** 167 snapshots of 107 unique fixtures, retrieved 15–17 Nov 2026.

| League | Fixtures |
|---|---|
| EPL | 20 |
| La Liga | 20 |
| Serie A | 20 |
| Ligue 1 | 18 |
| Bundesliga | 17 |
| Championship | 12 |

**Input rule (R-3):** fresh 1X2 plus a fresh goals market, each meeting the Challenge consensus (≥ 3 bookmaker groups, quotes ≤ 24 h).
- **131 snapshots (89 fixtures) qualify.**
- 36 were rejected: mostly no fresh market at all (21), or markets below the group or age rule.

**Fit results [V]:**

| Measure | Result |
|---|---|
| Statuses (all qualifying snapshots) | **101 good, 30 approximate, 0 poor** |
| Statuses (latest snapshot per fixture) | 71 good, 18 approximate. Approximate fits appear in every league (1–5 per league). |
| Markets used | all three in 129 snapshots; 1X2 + O/U in 2 |
| Maximum absolute residual | median 1.5 pp, p90 2.2 pp, maximum 2.5 pp |
| Mean fitted − market | draw **−1.46 pp** (known independent-Poisson draw bias); home +0.71; away +0.76; BTTS Yes −0.55; Over +0.005 pp |
| Identification | all identified; smallest singular value 0.29–0.46 |
| Boundary or convergence | 0 at a bound; **1 optimiser non-convergence**, still classified good or approximate on its residual. [R] Treat a non-converged fit as rejected in production. |
| Fitted λ | home 1.16–3.49 (median 1.64); away 0.91–2.40 (median 1.24) |

Consensus and fitted probabilities differ by up to 2.5 pp per outcome (`market_fits.csv` lists both). **The UI must show them as separate rows.**

## 8. SciPy fitter: performance and dependency assessment

**Measured locally [V]:**

| Measure | Result |
|---|---|
| Fit latency, one fixture, 3 markets | median **19 ms**, p90 25 ms; the first call is 0.36 s (warm-up) |
| Installed size | numpy 54 MiB + scipy 117 MiB ≈ **171 MiB** of disk |
| `import scipy.optimize, numpy` | 0.43 s |
| Resident memory | Dash + SQLAlchemy alone 55 MiB; with scipy and numpy 105 MiB, so **≈ +50 MiB per process** |
| Production today | imports neither numpy nor scipy; both are dev-only (`pyproject.toml`) |

**Assessment:**
- The production service runs **2 gunicorn workers** (`deploy/systemd/diski9-web.service`). Lazy import on the first Match Lab fit adds about **100 MiB of memory** and about 0.4 s to that worker's first fit.
- That is modest against the ≥ 4 GB requirement (`phase6c6_stage_f3_plan.md`).
- Per-fixture lazy fitting (only for the opened fixture, memoised per consensus snapshot) costs about 20 ms per fit.

**[R]** Promote numpy and scipy to runtime dependencies in CP2 (a lockfile change) and reuse the prototype unchanged. A custom optimiser is not justified by this evidence.

## 9. Weekly Challenge season-start feasibility

**Method:**
- real schedules for the 6 leagues with odds;
- round windows Friday 00:00 to Tuesday 00:00 UTC, availability as at Friday 06:00 UTC publication;
- the opening rule (≥ 15 fixtures, ≥ 3 leagues);
- bucket feasibility simulated from the real 17 Nov strict-consensus snapshot (60 priced fixtures, A3 bands, exact 4/3/2 matching).

**[V]** First four weekend windows of each season: eligible fixtures (leagues) and whether the round opens.

| Window | No model required | C0 required | C0-2 required | C1-2-20 required |
|---|---|---|---|---|
| 2024/25 wk1 (9 Aug) | 12 (1) ✗ | 12 (1) ✗ | 0 ✗ | 0 ✗ |
| 2024/25 wk2 | **49 (5) ✓** | 49 (5) ✓ | 0 ✗ | 0 ✗ |
| 2024/25 wk3 | **61 (6) ✓** | 61 (6) ✓ | 12 (1) ✗ | 12 (1) ✗ |
| 2024/25 wk4 | 60 (6) ✓ | 60 (6) ✓ | 51 (5) ✓ | 42 (4) ✓ |
| 2025/26 wk1–4 | 12 ✗ · **40 ✓** · **60 ✓** · 60 ✓ | same | 0 ✗ · 0 ✗ · 12 ✗ · 41 ✓ | 0 ✗ · 0 ✗ · 12 ✗ · 32 ✓ |
| 2026/27 wk1–4 | 17 (2) ✗ · **50 ✓** · **60 ✓** · 59 ✓ | same | 0 ✗ · 0 ✗ · 22 (2) ✗ · 50 ✓ | 0 ✗ · 0 ✗ · 22 (2) ✗ · 42 ✓ |

Every opening window had a simulated bucket feasibility of 1.00.

**Findings:**
- **With any team-data gate, keeping the model requirement loses weeks 2 and 3 of every season.**
- **Without the model requirement, rounds open from week 2,** exactly as under C0 today.
- Week 1 fails in every treatment: only the Championship (and one other league in 2026) has started. That is unchanged.
- **C0 required = no model required** in every window, because C0 always has a prior. The requirement only bites with a gate, or with a league's first stored season (the August 2025 failures in the earlier review).

**Limitations [A]:**
- Historical odds were never stored, so the analysis assumes every fixture in those 6 leagues was fully priced at publication.
- Bucket profiles come from one mid-season snapshot. Early-season markets may differ.

**Affected paths (from the CP0 refinement, verified):**
- pool skip at `challenge/roundsheet.py:253-254`;
- research pool `:164,177`;
- `None` crashes in `app/challenge/integration.py:99-103`, `app/challenge/callbacks.py:262,755-758`, `app/challenge/pages.py:652-656,723-725`, `challenge/analysis.py:52-77,151-155`;
- the misleading "markets" message at `roundsheet.py:351-378`.
- The schema and backend already accept NULL.

**[R] Incomplete sources:**
- when any pick lacks a model probability, disable the Diski 9 and Your View portfolio analyses (tracker, 512-state view, source selector), with a short note;
- market-source analysis stays available;
- NULLs are never filled with market values.

## 10. Recommendations

### Domestic model

**[R] Option 1, recommended if the owner accepts the measured cost:** **C1-2-20** as a new version (for example "Goal Model 1.1").
- current-season competition averages only;
- available when both teams have ≥ 2 eligible completed matches **and** the competition has ≥ 20;
- k_s 12, k_t 96 unchanged.

**Why:**
- It meets every pre-registered pooled criterion in both periods.
- Coverage is 93.8% of full seasons.
- The withheld opening rounds carried no demonstrated value.

**Costs to accept explicitly:**
- a small, statistically detectable 1X2 deterioration (+0.0023), concentrated in rounds 3–5;
- the **PSL** (+0.006) and, borderline, Serie A.

**[R] Option 2, if accuracy should win:** **C0-2** (Goal Model 1.0 with the same 2-match gate).
- Similar coverage (93.9%) with no loss on covered fixtures.
- It keeps the previous-season league average, so it is not current-season-only.

**Not recommended:** Goal Model 1.0 unchanged. The owner wants a minimum-data policy, and the first rounds add no value.

### Availability policy

- Withhold the independent estimate below the gate and show the actual reason.
- Fall back to the market-implied starting point (state B) where R-3 inputs exist, otherwise state C.
- **The gate must ship together with the Weekly Challenge model-optional change.**

### European competitions

- CL and EL get no independent model in the MVP. Both are **market-implied only** (CL league matchdays, knockouts and the final), subject to odds coverage.
- The CL independent model can be re-evaluated after 2026/27 with the same frozen criteria.
- EL inclusion is the owner's choice. Its incremental cost is small; its value is market-implied only.

## 11. Limitations, inconclusive findings and residual risks

| # | Item |
|---|---|
| 1 | **Re-analysis, not a holdout.** Seasons were examined before. Prospective forecast monitoring after launch is the real test. |
| 2 | 2026/27 is partial (to mid-November). Domestic confirmation still has 3,269 identical fixtures; CL and EL confirmation are small (14–16 week clusters). |
| 3 | Inconclusive per-league results: Ligue 1, Bundesliga, PSL1 (wide CIs). CL and EL BTTS and O/U are inconclusive. |
| 4 | Market fits cover 89 fixtures from one 3-day window in 6 European leagues. **There are no CL odds and no PSL odds at all.** |
| 5 | Weekly Challenge feasibility assumes full pricing and mid-season bucket composition. |
| 6 | The SciPy footprint was measured in this development environment, not on the VPS. |
| 7 | The prototype accepts a non-converged fit on its residual. CP2 should reject it. |
| 8 | Draw bias (−1.46 pp) in market fits. Consensus and fitted probabilities must be shown separately. |

## 12. Decisions for the owner

| ID | Decision | Recommendation |
|---|---|---|
| CP1-1 | Domestic model: C1-2-20 (new version) / C0-2 / unchanged | C1-2-20, accepting the PSL cost explicitly; or C0-2 if accuracy should win |
| CP1-2 | Gate parameters k = 2, L = 20; shrinkage unchanged | Approve with CP1-1 |
| CP1-3 | CL: market-implied only for the MVP; re-evaluate after 2026/27 | Approve |
| CP1-4 | EL: include as market-implied only, or defer | Owner's value judgement |
| CP1-5 | numpy and scipy promoted to runtime dependencies (a CP2 lockfile change); the prototype reused; non-converged fits rejected | Approve |
| CP1-6 | Weekly Challenge model-optional pools, NULL model fields, incomplete-source analyses disabled, `eligible_competitions` enforced in construction and publication | Approve, shipped with the gate |
| CP1-7 | CP2 provider verification ceiling (§13) | Approve at CP2 |

## 13. Revised CP2–CP4 scope and active hours

**CP2 provider verification (needs separate approval):**
- quota-free `/status` to confirm the plan and the 7,500/day limit;
- then **at most 25 requests** for:
  - `leagues?id=2` (and `3`);
  - teams and fixtures for 2026;
  - one odds page set per competition, to measure bookmaker-group depth.
- **Ongoing:** CL about 1 fixtures request plus 2–3 odds pages per refresh sweep; EL the same again. That is +4–8 requests per sweep, under 1% of the daily quota.

| CP | Scope | Hours |
|---|---|---|
| **CP2: backend** | Approved gate and model version (agreement tests keep 1.0 reproducible for history); `goal_counts` payload; runtime numpy/scipy and the prototype fitter as a production module with rejection rules; `starting_point` provenance and stamp; Weekly Challenge model-optional and None-safe paths, analysis disabling, message fix; `eligible_competitions` in construction and publication; CL (and EL) registry kind, stage rules, neutral final, ingestion and refresh; tests | **22–30** |
| **CP3: interface** | States A/B/C; availability strip; edge/EV gating; reset notice; **"How probabilities are calculated"** (observed distributions, records and averages, model calculation, Poisson bars and worked example, scoreline matrix with the outside-range mass, reconciliation); Screener probability-source selector (market or model) with ranking and threshold; copy and methodology; screenshots; **visual review (STOP)** | **22–30** |
| **CP4: validation and closure** | Local end-to-end on disposable data; full regression; docs (methodology, model changelog, decisions, plus the queued items: 26 Nov maintenance, extended private Beta, architecture correction); closure report | **8–12** |

**Total:** about **52–72 active hours.**

**Possible reductions:**
- defer the EL (about 2 h plus operations);
- if CP1-1 is "unchanged" (no new version), the gate work disappears (−3 h);
- a CL independent model is no longer in scope, which already saves model integration work.
