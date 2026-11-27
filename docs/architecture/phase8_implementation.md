# Phase 8 — Goal Model Refinement, Match Lab Education & European Competitions

*Phase name provisional. Record started 27 Nov 2026.*

**Status:**
- CP0 discovery, the CP0 refinement, CP1 research and the supplementary Goal Model research are **formally accepted**.
- All seven CP1 decisions are **approved** (27 Nov 2026).
- CP1-7 Step A (quota-free account check) is **complete**. Step B is **authorised for 3–9 Dec 2026 only**, at most 25 counted requests (Appendix B).
- **Owner decisions OD-1 to OD-6 are approved with refinements (27 Nov 2026, §11).** The CP2–CP4 plan (§9) is reconciled with them.
- CP2A readiness is assessed in §12. **CP2A is not yet authorised**: it awaits independent review and explicit owner authorisation. Phase 6 stays paused.

**How to read this record:**
- §1–§8, §10 and §11 record **accepted decisions**. Where §11 refines an earlier section, §11 governs.
- §9, §12 and the appendices are the **approved plan structure**. Their implementation details remain subject to checkpoint review.
- Accepted research evidence is not rewritten here. The reporting qualifications and later decisions are recorded alongside it.

## 1. Governance

**Principles:** MVP first; simplicity; robustness; avoid overengineering; proportionate testing; controlled progression.

**Roles:** Claude does discovery, implementation, testing and documentation. ChatGPT reviews independently. The owner makes the final decisions.

**Approval types are separate:** implementation, provider access, protected-database execution and deployment are each approved on their own.

Where an approved requirement conflicts with the architecture or carries material risk, Claude explains it and proposes the simplest reliable resolution. Requirements are never changed silently.

## 2. Accepted research baseline

| Item | Reference |
|---|---|
| CP1 pre-registration | `e8f987f` — [`../research/phase8_cp1/preregistration.md`](../research/phase8_cp1/preregistration.md) |
| CP1 research | `535eff679f58318b43df5e42a6db78d443dfee32`; CI run 164 (2,331 passed) — [`../research/phase8_cp1/report.md`](../research/phase8_cp1/report.md) |
| Supplementary pre-registration | `3730a0d73a994220b904c1be20114172ef5d7b89` — [`../research/phase8_cp1/supplementary_preregistration.md`](../research/phase8_cp1/supplementary_preregistration.md) |
| Supplementary research | `7a39d313f1e1893374cb0bd6dcde1ca3f65889fa`; CI run 165 (2,339 passed, 0 failed) — [`../research/phase8_cp1/simplification_report.md`](../research/phase8_cp1/simplification_report.md) |

**Accepted reporting qualifications.** These are accepted reporting limitations, not outstanding research tasks:
1. Model B's BTTS and Over/Under results were significantly worse than Model A. The appropriate conclusion is that **Model B failed to establish non-inferiority**: its confidence intervals overlap the +0.003 tolerance margin. (The supplementary report's word "deterioration" should be read this way.)
2. Model C produced **60 impossible realised market outcomes across 48 distinct fixtures**.
3. Model B evaluated five common shrinkage values during selection. **Only the selected value of 12 was evaluated in confirmation**, so the findings do not establish that every common value would fail.
4. Model A's goals-market calibration remains imperfect: BTTS and Over/Under calibration slopes are about **0.63 and 0.76**.
5. The research is a **pre-registered re-analysis of previously examined seasons**, not an untouched holdout.

The domestic Goal Model research is **closed**. No further research, optimisation, tuning or calibration is authorised.

## 3. Approved CP1 decisions (27 Nov 2026)

| ID | Decision |
|---|---|
| **CP1-1 / CP1-2** | **Domestic Goal Model: Model A under C1-2-20**, final for the MVP. All eight domestic competitions. Current-season team and competition data only, with no previous-season fallback. Available when both teams have ≥ 2 eligible completed matches and the competition has ≥ 20. `k_s` 12, `k_t` 96. No cross-competition strength, Elo, alternative models or extra calibration. Shrinkage is not user-adjustable. A **limited-data warning** appears when the model is available and either team has < 5 eligible matches. The owner explicitly accepts the measured accuracy and coverage trade-offs: the model is a transparent, educational starting point, not an attempt to maximise accuracy, coverage or bookmaker-beating performance. |
| **CP1-3** | **Champions League**, subject to CP1-7 verification. Market-only. Shown in All Upcoming Fixtures and Match Lab. Qualifying rounds excluded. Excluded from the Weekly Challenge. Market-implied Estimated Goals when reliable inputs exist. Your View when a reliable starting point exists. Fixture research information otherwise. No independent Champions League model. |
| **CP1-4** | **Europa League**, under the same conditions as CP1-3, reusing the Champions League implementation. The Conference League is excluded. Independent European modelling is deferred until after the MVP, and only if justified by evidence and demand. |
| **CP1-5** | **NumPy and SciPy become production dependencies**, managed and locked through the existing `uv` process. Reuse the researched fit (`research/market_implied_xg.py`): no custom optimiser. Fit **on demand only**, never across every fixture to fill the Screener. Reuse results while the market inputs and methodology are unchanged. Reject invalid, non-converged, stale, insufficient-input and poor fits. Keep the fit-quality criteria and source labels. Local measurements (about 171 MiB on disk, about +50 MiB per worker, about 19 ms per fit) are preliminary, not hosted guarantees: validate at the hosted acceptance checkpoint. No infrastructure upgrade or extra spending. |
| **CP1-6** | **The Weekly Challenge no longer requires the independent model.** Its absence must not exclude an otherwise eligible fixture, and market-implied Estimated Goals must not become a requirement. All other eligibility, market-reliability, scheduling and 4-3-2 feasibility rules stay. The bound `eligible_competitions` is enforced in pool construction and publication, so European fixtures never enter a pool. Ship together with the C1-2-20 thresholds. Missing model values stay NULL and are never filled from market values. Model-dependent analysis is disabled appropriately. Frozen and live information stay distinct. Historical rounds, submissions, portfolios and results are preserved. A3 bands, portfolio structure, credits, settlement, scoring, corrections, leaderboards, championships and rewards are unchanged. |
| **CP1-7** | **Provider verification in two separately controlled steps.** Step A, a quota-free account check, is complete (§7). Step B allows **at most 25 chargeable requests**, counting pagination, retries and counted failures. It runs only after separate owner authorisation. No upgrade, extra spending, alternative provider or recurring refresh activation. Insufficient evidence is reported as a limitation, never as verified coverage. |

## 4. Match Lab: final functional requirements

| State | When | Starting point | Shown | Hidden or disabled |
|---|---|---|---|---|
| **A** | Independent model available | Diski 9 Estimated Goals (automatic) | Model probabilities, actual bookmaker probabilities, Your View, edge and EV where applicable, limited-data warning below 5 matches | — |
| **B** | Model unavailable; reliable market-implied fit | Market-implied Estimated Goals (automatic), clearly labelled | Your View; actual bookmaker consensus kept **distinct** from probabilities fitted through Estimated Goals | Edge and EV, including Your View edge and EV claims. Never presented as an independent prediction. |
| **C** | Neither available | None | Fixture and team information, observed statistics, market probabilities, and an explanation of why Estimated Goals are unavailable | Quantitative Your View adjustments. No manufactured predictions or fallback models. |

**General rules:**
- One starting point, chosen automatically.
- No starting-point selector and no side-by-side competing models in the MVP.
- Your View is retained, with **source-aware adjustment identity**. Adjustments reset only when the starting-point identity or context genuinely changes, and a reset is communicated clearly.
- Frozen Weekly Challenge context is preserved, and live and frozen research information stay distinct.
- Market-implied Estimated Goals are described as **estimates derived from bookmaker probabilities**, not shot-based expected goals or independent forecasts.

## 5. Match Lab: educational requirements

Education is a central product requirement. The approach is simple first, detail on demand.

**Product philosophy:** Diski 9 gives a transparent statistical starting point for football analysis and education. It does not make definitive predictions or try to beat bookmakers. It distinguishes a user's potential analytical insight from a demonstrated predictive advantage.

- **Observed statistics,** shown where available even when the model is unavailable:
  - eligible matches per team;
  - goals scored and conceded, and their averages;
  - goal-frequency distributions;
  - home and away splits;
  - competition averages;
  - clear sample-size limitations.
- **Model explanation:**
  - strength = which team is relatively stronger;
  - tempo = the expected overall goal environment;
  - shrinkage = how strongly observed results are trusted when samples are small;
  - why strength (12) reacts quickly and tempo (96) conservatively.
  - None of these is ever presented as an adjustable dial.
- **"How probabilities are calculated"** (expandable):
  - real inputs;
  - attack and defence;
  - strength, tempo and shrinkage;
  - Estimated Goals;
  - Poisson goal distributions;
  - the scoreline matrix;
  - worked 1X2, BTTS and Over/Under examples;
  - treatment of probability tails.
  - Every figure must reconcile with production. It reuses the production calculation functions, with no separate display maths.
- **Market-only fixtures:** explain how bookmaker probabilities are converted into Estimated Goals, and the limits of the fit.

## 6. Navigation and user experience (approved)

**Five primary tabs, top of the application, in this order:**
1. **Portfolio Build** (default landing page)
2. **Match Lab**
3. **My Challenge**
4. **Leaderboards**
5. **Learn**

There is no top-level Weekly Challenge parent tab. Only the selected tab's content is shown, and navigation is consistent across the application.

**Portfolio Build** merges the existing Screener and Portfolio Build. This is consolidation, not a reduction in functionality. *Refined by OD-4 (§11): a single toggle labelled **Challenge Mode** (OFF by default = All Upcoming Fixtures; ON = published eligible Weekly Challenge fixtures), the homepage introduction, a collapsed How to Play, and one **Minimum Market Probability** slider. There is no independent-model threshold slider.* It has two fixture universes:
- **Weekly Challenge:**
  - frozen eligible fixtures;
  - research and filters;
  - bucket filters;
  - selection, credits, validation and submission;
  - Match Lab in frozen context.
- **All Upcoming Fixtures:**
  - all supported domestic and European fixtures;
  - applicable Screener filters;
  - market and model analysis where available;
  - Match Lab;
  - no portfolio controls;
  - open to guests, to users outside a round, and to users who have already submitted.

All applicable filters and features are preserved, with overlapping controls consolidated rather than duplicated. Model-dependent filters must handle missing predictions without silently excluding market-only fixtures. Market probabilities come from the existing margin-adjusted consensus, with no per-fixture fitting. **Any removal or material change requires explicit owner approval.**

**Match Lab:**
- an independent tab, with direct fixture selection;
- opens from Portfolio Build, and returns there with context preserved (selections, filters, sorting, drafts and Your View);
- respects live and frozen contexts.

**My Challenge:** Current, History and Rewards. "Achievements" becomes **"Rewards" in the user interface only**, with no internal renaming. All Phase 7 behaviour is preserved, and Rewards means virtual recognition only.

**Leaderboards** stays a separate primary tab, not under My Challenge.

**Learn:** a lightweight, practical general-concepts tab that does not duplicate the fixture-specific maths in Match Lab. It is not a content management system.

**User experience:**
- compact pages and persistent primary navigation;
- compact secondary navigation;
- expandable detail and collapsible advanced filters;
- context preservation;
- desktop and mobile layouts;
- a clear distinction between independent and market-derived analysis;
- accessible unavailable-data states.
- It reuses the existing styling. This is not a visual redesign, and the owner reviews the layout before frontend implementation is authorised.

## 7. CP1-7 Step A: quota-free account verification (27 Nov 2026)

**Method:**
- Two calls to the API-Football `/status` endpoint through the session's credential-injecting proxy. No key appeared in any command, log or file.
- The output was filtered to the subscription and request fields only. Account identity fields were not displayed or stored.

**Quota-free confirmed:** the daily request counter read **85** before and after the second call, unchanged.

| Field | Value |
|---|---|
| Plan | **Pro**, active |
| Current subscription end | **14 Dec 2026, 13:11 UTC** |
| Daily allowance | **7,500** requests (header `X-Ratelimit-Requests-Limit`) |
| Used today at check time | 85 (7,415 remaining) |
| Per-minute rate limit | 300 (header `X-Ratelimit-Limit`) |

**Billing:** auto-renewal status and billing details are not exposed by `/status`. **The owner confirmed (27 Nov 2026):** USD 16/month, **no automatic renewal**, reverts to the Free plan on expiry, and a manual renewal extends the remaining period. A reminder is set for 12 Dec (§11, OD-5).

The Step B proposal is in Appendix B.

## 8. Weekly Challenge, frozen context and historical integrity

Restated from CP1-6 for implementers. The existing app schema already allows model fields to be NULL:
- `snapshot_fixtures.estimated_goals_*`;
- `snapshot_offers.model_prob`;
- `submissions.p_recover_model` and `expected_gross_model`;
- `submission_selections.model_prob`.

So **no app-database migration is expected** for CP1-6. Historical frozen rounds are never recomputed.

## 9. CP2–CP4 implementation plan

*Plan structure and estimates approved 27 Nov 2026 (OD-6), reconciled with OD-1 to OD-6. Implementation details remain subject to checkpoint review. Appendix A has the functionality mapping, and Appendix C the wireframes.*

### 9.1 Codebase findings that shape the plan

- **The current "Screener" is the Match Lab page.**
  - `/` is labelled "Match Lab". It has a universe toggle (Weekly Challenge / All upcoming) and opens Match Lab beneath the list.
  - The builder is a separate route, `/challenge`.
  - So the approved structure is a **re-arrangement**: merge the `/` list and `/challenge` into Portfolio Build, and lift the Match Lab panel onto its own route.
- **Model-absent fixtures crash the builder today.** Round snapshots skip them (`challenge/roundsheet.py:254`), which hides the problem. If they are let in, these would raise:
  - `integration.frozen_market_value` (`app/challenge/integration.py:99-103`);
  - `challenge/analysis.py:52-77,151-155`;
  - `app/challenge/service.py:204`: a `ChallengeInputError` that the `except` misses, so the build stepper crashes;
  - `pages.py:652-656,723-725,1261,1274,1717`;
  - `callbacks.py:262,755-758`.
  - CP1-6 therefore has to ship with these fixes.
- **The Screener's default ranking (kickoff) already keeps model-absent fixtures.** Probability, edge and EV ranks **drop them once the model threshold is above 0** (`screener/rank.py:72-90`, `app/data.py:380-388`). *Resolved by OD-4:* the model threshold slider is removed and replaced by a **Minimum Market Probability** slider on actual consensus, so model ranks only order fixtures. Model-absent fixtures go last and are never dropped.
- **The universe toggle already exists** (`universe` RadioItems, `app/app.py:387`). Challenge Mode is that control restyled as a switch, with the default changed to OFF. **The two-tab alternative is not needed.**
- **No app-database migration is expected** (§8). European competitions need registry entries (`leagues.py`), a stage allowlist, refresh inclusion and the existing UEFA path in `goal_model.fixture_estimate`. The football store already has `round_name`, so **no football-store migration is expected** either. CP2B verifies both.
- **Builder filter values are not stored** and reset on re-render. Context preservation needs them kept in the existing session store.
- **The existing `screener-root` stays mounted and is hidden by style.** That already preserves list state across routes, and the plan reuses the pattern.
- **Nine callbacks test `path == "/"`, and several outputs use `allow_duplicate`.** These are the main regression risk of the navigation change (Appendix A, risks).

### 9.2 Checkpoints

**CP2A: domestic model, Weekly Challenge eligibility and missing-model safety (backend plus the minimal builder fixes)**
- **Objective:** C1-2-20 in production and CP1-6, shipped together.
- **Prerequisites:** the plan and the Goal Model 1.1 name are approved (OD-6, OD-1). **Explicit owner authorisation of CP2A is still required.**
- **Changes:**
  - **Goal Model** (`screener/goal_model.py`):
    - remove the prior and `m0` and every previous-season input;
    - the ≥ 2 / ≥ 20 gate and the < 5 warning flag;
    - the new version and parameter hash;
    - an engine version bump, so `screener_results` recomputes (rows are never deleted) and `forecast_snapshots` record under the new version.
  - **Weekly Challenge** (`challenge/roundsheet.py`):
    - drop the model requirement;
    - write NULL model fields;
    - enforce `eligible_competitions` in pool construction **and** at publication, with refusal on a mismatch.
  - **Missing-model safety:** fix every path listed in §9.1.
  - **OD-3 portfolio sources:**
    - Diski 9 figures per selection where a prediction exists;
    - per bucket when every selection in that bucket has one;
    - for the whole portfolio only with all nine;
    - otherwise "n of 9 (or n of 4/3/2) predictions unavailable";
    - Your View hierarchy tiers 1, 2 and 4 (adjusted → Diski 9 → market consensus), with a compact source summary.
    - Tier 3 (market-implied) arrives with CP2B.
    - Reuses `challenge/analysis.bucket_stats` and the existing evaluators.
  - **Unchanged:** A3, credits, settlement, scoring and championships.
- **Files:**
  - `screener/goal_model.py`, `engine.py`, `forecasts.py`;
  - `challenge/roundsheet.py`, `analysis.py`, `structured.py`;
  - `app/challenge/{integration,service,pages,callbacks}.py`;
  - `backend/services/rounds.py` (publication guard).
- **Tests (focused):**
  - gate boundaries (1/2 matches, 19/20 competition matches, warning at 4/5);
  - no previous-season leakage (changing the previous season changes nothing);
  - reconciliation with the accepted research reference (C1-2-20) to 1e-12;
  - a pool that admits a model-absent fixture with NULLs;
  - European fixtures refused at construction and at publication;
  - builder, review and submit with 0, some and 9 model-absent picks;
  - historical snapshot fixtures render unchanged.
  - Then the full suite.
- **Estimate: 15–20 h** (§9.3). **STOP:** ChatGPT review.

**CP2B: European competitions, market-implied Estimated Goals and source-aware identity**
- **Prerequisites:**
  - CP2A accepted;
  - **CP1-7 Step B results** (European parts are gated on verified coverage);
  - the dependency change, approved in principle by CP1-5; the `uv` lockfile is updated only at CP2B.
- **Changes:**
  - **Dependencies:** promote `numpy` and `scipy` to runtime with `uv add` (lockfile updated).
  - **Market fit:** move the `research/market_implied_xg.py` fit into `screener/market_fit.py` unchanged:
    - CP1 input rule: fresh 1X2 plus a goals market, each ≥ 3 groups, ≤ 24 h;
    - reject non-converged, failed-identification, insufficient-input, stale and poor fits;
    - statuses good and approximate;
    - an in-process LRU cache keyed by (fixture, market-input fingerprint, fit version);
    - called **only** from Match Lab.
  - **Starting point:** `starting_point()` returns `{source: model|market|none, version, λh, λa, quality, reason}`.
  - **Your View stamp:** `"{source}:{version}|{fid}|{h:.2f}|{a:.2f}"`, with a "your adjustments were reset because…" flag. It is stored in the existing `your_view_adjustments.model_context` text, so no migration is needed.
  - **Frozen context (OD-2):** a market fit from the snapshot's frozen market probabilities, deterministic and never replaced by live odds. It is fitted on demand and cached by input fingerprint. State C fixtures stay Challenge-eligible.
  - **Your View tier 3** (market-implied) is added to the OD-3 hierarchy, and the Match Lab source label reads **"Diski 9 Goal Model"** or **"Market-implied Model"**.
  - **European data:**
    - registry entries for 2 and 3, marked market-only;
    - the stage allowlist: "League Stage - n", "Knockout Round Play-offs" / "Round of 32", "Round of 16", "Quarter-finals", "Semi-finals", "Final"; qualifying rounds and the August "Play-offs" are excluded; unknown labels refused;
    - the neutral-final rule;
    - ingestion through the existing functions;
    - a refresh step on the European cadence of Appendix B, with refresh still inactive.
- **Development data:** European fixtures and odds for local development are fetched only under the Step B authorisation or a separate one. Tests use recorded fixtures.
- **Tests:**
  - fit acceptance and rejection on recorded snapshots;
  - cache keying;
  - stamp transitions (no reset on unchanged data; reset plus notice on a source or baseline change);
  - stage classification, including unknown labels;
  - European fixtures listed with no model and never in pools;
  - an import and memory smoke test.
- **Estimate: 15–21 h** (§9.3). The European part (about 4–6 h of it) proceeds only after satisfactory Step B results. **STOP:** ChatGPT review.

**CP3A: navigation and the Portfolio Build consolidation**
- **Prerequisites:**
  - CP2A accepted;
  - the layout and mapping, approved in principle by OD-4 (Appendix A and C). The visual STOP still applies.
- **Changes:**
  - **Tabs:** five tabs from the existing `NAV`, with routes `/` Portfolio Build, `/lab` Match Lab, `/challenge/me` My Challenge, `/leaderboards`, `/learn`. `/challenge` redirects to `/`, so old links keep working.
  - **Portfolio Build:**
    - **Introduction:** the compact introduction (§11, OD-4), then a collapsed **How to Play** (the existing `how_to_play` expander, extended with the markets, A3 bands and navigation) immediately above the fixtures.
    - **Challenge Mode** toggle (OFF by default).
    - **Shared filter bar:** league, market, team search, date range (a single day allowed), sort/rank, and **Minimum Market Probability** (actual consensus; frozen in Challenge Mode; default 0; kept in session).
    - **Advanced filters** are collapsed.
    - **Under the bar:**
      - **ON:** the existing builder card list with bucket filters, tracker and review.
      - **OFF:** the existing Screener table without portfolio controls.
    - Two existing renderers are reused, not one new unified list, which keeps the regression risk low.
  - **Match Lab:** the existing panel at `/lab`, with a fixture picker grouped by competition and date, and a "← Back to Portfolio Build" link.
  - **Context:** Portfolio Build stays mounted and hidden, as `screener-root` is today. The builder filters move into `ch-prefs` (session).
  - **Rewards:** "Achievements" becomes "Rewards" in user-facing strings only.
  - **Leaderboards:** unchanged content under its own tab.
  - **Learn:** route and tab only (content in CP3B).
- **Tests:**
  - update the route and label tests;
  - a navigation test (order, default, active state);
  - context preservation (filters, page, picks, Your View across Portfolio Build ↔ Match Lab);
  - guest access to All Upcoming;
  - the wildcard-output guard;
  - browser screenshots at 3 widths.
- **Estimate: 18–24 h** (§9.3). **STOP:** visual review by the owner.

**CP3B: Match Lab states and education**
- **Prerequisites:** CP2B and CP3A accepted.
- **Changes:**
  - **States A/B/C** with source labels and an availability strip;
  - the limited-data warning;
  - edge and EV hidden in state B, including Your View edge and EV;
  - Your View disabled in state C, with the reset notice;
  - observed statistics shown in every state where data exists;
  - **"How probabilities are calculated"** (inputs → attack and defence → strength, tempo and shrinkage → Estimated Goals → Poisson bars → scoreline matrix with the outside-range tail mass → worked 1X2, BTTS and O/U), built from the **production functions' intermediate values**, not separate maths;
  - the market-only explanation (consensus → fit → limits);
  - Learn content: about 5 short topics (getting started; bookmaker probabilities and margins; Estimated Goals; strength, tempo and shrinkage; goal distributions; the Weekly Challenge), reusing existing text.
- **Tests:**
  - reconciliation of displayed numbers against production values to the displayed precision;
  - a state-selection matrix;
  - gating of edge, EV and Your View;
  - screenshots of each state at 3 widths.
- **Estimate: 16–22 h. STOP:** visual review by the owner.

**CP4: integration, regression and Phase 8 acceptance**
- **Scope:**
  - local end-to-end on disposable data, extending `tools/e2e_p7`: a round with model-absent fixtures, a submission, settlement and Rewards; European fixtures in All Upcoming and Match Lab;
  - the full regression and browser journeys;
  - docs (methodology, model changelog, decisions, this record);
  - the hosted-acceptance mapping (§9.4);
  - the closure report.
- **Estimate: 8–12 h. STOP:** owner acceptance of Phase 8.

### 9.3 Effort (reassessed 27 Nov 2026 against OD-1 to OD-6)

| Checkpoint | Implementation | Testing | **Total** | Earlier |
|---|---|---|---|---|
| CP2A | 10–13 | 5–7 | **15–20** | 14–18 |
| CP2B | 9–13 (European 4–6) | 6–8 | **15–21** | 14–20 |
| CP3A | 12–16 | 6–8 | **18–24** | 20–26 |
| CP3B | 11–15 | 5–7 | **16–22** | 16–22 |
| CP4 | 3–4 (docs, closure) | 5–8 | **8–12** | 8–12 |
| **Total** | **45–61** | **27–38** | **72–99** | 72–98 |

**Why each changed:**
- **CP2A +1–2 h:** OD-3 adds per-bucket availability and the Your View hierarchy with a source summary.
- **CP2B +1 h:** Your View tier 3 and the frozen-fit cache.
- **CP3A −2 h:** single toggle, one slider, two reused renderers and no unified list.

**Why CP3A is not lower.** Reuse removes the rendering work, but this work remains:

| Work | Hours |
|---|---|
| Feeding the builder's fixture list from the shared filter bar instead of its own `{"t": "f-*"}` controls (`fixture_list`, `refresh_list` with in-place button updates, `ch-fxpage`) | 4–5 |
| Mounting the builder stage inside `/` instead of `ch-root` under `/challenge`, while keeping review, the stepper, modals and adoption working | 2–3 |
| Moving Match Lab to `/lab` (`update_detail`, `match_lab_panel`, `open_fixture`, `selected`, and 9 `path == "/"` checks; live versus frozen context in the URL) | 3–4 |
| The market slider and market-probability ranking, on live and frozen consensus | 2 |
| Introduction, How to Play, Rewards wording, Leaderboards and Learn routes | 1–2 |

**Testing (6–8 h):**
- update the route and label tests (5 files plus 2 tools);
- navigation, context-preservation and guest tests;
- the wildcard-output guard;
- browser journeys and screenshots at 3 widths.

**Not included:**
- **Owner review time:** four STOPs (CP2A, CP2B, CP3A visual, CP3B visual) plus CP4 acceptance; about 1–2 h each on the owner's side.
- **External dependencies:** the Step B window (3–9 Dec); the API-Football subscription (expires 14 Dec, no auto-renewal); ChatGPT review turnaround.

### 9.4 Hosted acceptance mapping (not activated in Phase 8)

| Requirement | Future checkpoint |
|---|---|
| numpy/scipy disk, memory per worker and fit latency on the KVM 2 host | Phase 6 F3 CP3 (install) and CP6 (soak) |
| European refresh cadence under the real scheduler and budget | Phase 6 resume (refresh configuration), then F5 |
| Screener cache recompute time under the new engine version | F3 CP3 / CP6 |
| Page timings of the merged Portfolio Build | IT-5 (CP3) |

### 9.5 Acceptance criteria (summary; each maps to tests in its checkpoint)

1. **Model:**
   - C1-2-20 exact (`k_s` 12, `k_t` 96, no `m0`);
   - gate ≥ 2 / ≥ 20 and warning < 5 at their boundaries;
   - zero previous-season influence;
   - production reconciles with the research reference to 1e-12;
   - displayed calculations reconcile with production.
2. **Market fit:**
   - only accepted statuses produce state B;
   - non-converged, stale, insufficient and poor fits are rejected with a reason;
   - fitted and actual probabilities are labelled distinctly;
   - no fitting in list views.
3. **European:**
   - identifiers 2 and 3, season 2026;
   - qualifying rounds absent everywhere;
   - unknown stages refused;
   - no independent European model;
   - zero European fixtures in any pool or publication (tested at both points);
   - coverage verified by Step B within 25 requests.
4. **Weekly Challenge:**
   - model-absent fixtures qualify when all other rules pass;
   - NULLs are preserved, never market-filled;
   - market rules, A3 and 4-3-2 are unchanged;
   - `eligible_competitions` is enforced;
   - historical rounds and submissions are byte-identical (fingerprints unchanged);
   - settlement, scoring, championships and Rewards are unchanged (existing suites green).
5. **Navigation and user experience:**
   - five tabs in the approved order;
   - `/` is Portfolio Build;
   - the Challenge Mode toggle defaults to OFF, and both universes are present;
   - the introduction and a collapsed How to Play sit above the fixtures;
   - one Minimum Market Probability slider (consensus; frozen in Challenge Mode; default 0; kept across Match Lab) and no model threshold slider;
   - market-only fixtures never receive model, edge or EV values;
   - every row of Appendix A is preserved or owner-approved;
   - market-only fixtures are not hidden by default filters;
   - guests and users outside a round can reach All Upcoming;
   - context is preserved across Portfolio Build ↔ Match Lab;
   - "Rewards" in the UI with internal names unchanged;
   - Leaderboards is a standalone tab;
   - layouts work at 390, 768 and 1280 px without horizontal scroll.
6. **Safety:**
   - full suite and CI green;
   - no unauthorised provider, protected-database, infrastructure or deployment action;
   - hosted items mapped (§9.4).

### 9.6 Owner decisions

OD-1 to OD-6 were **approved with refinements on 27 Nov 2026**; see §11. The remaining open points are listed in §12.4.

## 10. Deferred work and outstanding requirements (preserved)

Nothing here enters the MVP without explicit owner approval. The register in [`../product/future_enhancements.md`](../product/future_enhancements.md) ("Phase 8 deferred register") lists each item.

- **Modelling:**
  - independent European modelling, with a Champions League re-evaluation after 2026/27;
  - low-data, carry-over and cross-league models;
  - Dixon–Coles market fit;
  - additional European competitions;
  - midweek and European Weekly Challenge rounds.
- **Product:**
  - edge-based recognition;
  - user-versus-market analysis;
  - a public track record;
  - educational enhancements;
  - Personal Performance Analytics;
  - achievement threshold reassessment;
  - private mini-leagues.
- **Operations:**
  - ML-01 (required before private Beta);
  - A3 housekeeping;
  - egress reassessment after Phase 9;
  - account deletion and privacy gates;
  - the personal-MacBook administration move before Phase 11;
  - Official championship scheduling (Phase 10);
  - D-29 and D-36;
  - all remaining Phase 6 gates (F3 CP3–CP7, F4–F6, Stage G);
  - participant-dependent Beta and release requirements.
- **Roadmap:**
  - Phase 6 is paused;
  - Phase 7 is complete;
  - Phase 8 is in progress;
  - Phase 9 is Lucy and LiveKit;
  - the rest of Phase 6 follows;
  - Phase 10 is deployment and complete-MVP private Beta;
  - an extended private Beta and consolidation (about 1–3 months) follows;
  - Phase 11 is public launch and YouTube, with explicit owner approval;
  - commercialisation is off the roadmap.
- **Infrastructure carry-overs:**
  - 1 Dec 2026 maintenance check ([`phase6c6_implementation.md`](phase6c6_implementation.md), pause maintenance log);
  - Hostinger refund decision on 17 Dec 2026;
  - certificate expiry on 24 May 2027;
  - API-Football subscription end on 14 Dec 2026 (§7).

## 11. Final owner decisions OD-1 to OD-6 (approved 27 Nov 2026, with refinements)

**OD-1: Goal Model 1.1 (approved).**
- "Goal Model 1.1" is the name of C1-2-20: current season only, ≥ 2 matches per team, ≥ 20 per competition, `k_s` 12, `k_t` 96, the eight domestic competitions, and the limited-data warning below 5 matches.
- No further optimisation or research.
- **Goal Model 1.0 historical identities stay reproducible.** Existing `forecast_snapshots`, `screener_results` rows and round snapshots keep `Goal Model 1.0` and its parameter hash. 1.0 stays reconstructible from the frozen parameters (`m0` 30).

**OD-2: frozen market-implied fallback (approved).**
- When no independent prediction exists, the starting point is a market-implied fit from reliable consensus.
- Weekly Challenge fixtures use the **frozen snapshot** probabilities, never later live ones.
- States A/B/C are retained. **State C fixtures remain Challenge-eligible** when every other market and eligibility rule passes.
- Fitting is on demand, with identical inputs reused, and there is no bulk fitting in the Screener.

**OD-3: portfolio probability sources (approved with refinements).**
- **Market:** the actual frozen consensus for Challenge selections.
- **Diski 9:**
  - shown per selection where a prediction exists;
  - shown per bucket only when every selection in that bucket has one;
  - shown for the whole nine only with all nine;
  - when unavailable, the missing count is stated;
  - never mixed with market values.
  - *Example:* 4/4 Foundation and 2/2 Challenger available but 2/3 Balanced → the Foundation and Challenger estimates are shown; the Balanced and whole-portfolio Diski 9 estimates are unavailable.
- **Your View, per selection:**
  1. a valid user adjustment;
  2. the Diski 9 probability;
  3. the reliable market-implied probability;
  4. the actual consensus.
  - Adjusted selections, unadjusted starting points and market fallbacks are distinguished in a compact text summary. There are no new charts, selectors or manual configuration.
- Source-aware validation and frozen/live separation are kept. The market-only edge and EV restrictions are kept.

**OD-4: navigation, homepage and functionality (approved with refinements).**
- **Tabs:** Portfolio Build (default), Match Lab, My Challenge (Current, History, Rewards), Leaderboards, Learn. No Weekly Challenge parent.
- **Portfolio Build** has one toggle labelled **Challenge Mode**:
  - **OFF (default):** All Upcoming Fixtures.
  - **ON:** published eligible Weekly Challenge fixtures.
  - It reuses the existing table, cards, tracker and construction components.
  - Live and frozen data stay distinct, and drafts, filters and Match Lab context are preserved.
- **Homepage introduction,** recorded verbatim from the owner's instruction (no earlier copy of this text exists in the repository):
  > **Think you know football? Put your skills to the test!**
  > 9 picks. 100 virtual credits. One challenge.
  > *(brief introductory explanation)*
  > Free to play. No real money. Just football.
- **How to Play:** a **collapsed** expander immediately above the fixtures. It covers:
  - the three markets;
  - nine selections from distinct fixtures;
  - 4 Foundation, 3 Balanced and 2 Challenger;
  - the A3 bands (Foundation 60–90% inclusive, Balanced 40% to < 60%, Challenger 10% to < 40%);
  - 40/30/20/10 credits;
  - recovering 100 credits while aiming for a positive return;
  - championship points and Rewards;
  - navigation.
  - It uses the existing bucket colours, keeps the page short, and extends the existing `how_to_play` component.
- **Filters:**
  - shared league, market, team and date-range filters (a single date allowed);
  - bucket filters in Challenge Mode;
  - advanced filters collapsed;
  - **one Minimum Market Probability slider** in both modes. It defaults to no filtering, uses actual consensus (frozen in Challenge Mode, never fitted values), and keeps its value across Match Lab.
  - **No independent Diski 9 threshold slider in the MVP.** This supersedes the earlier two-filter proposal and removes the existing model threshold.
- **Ranking:** kickoff, market probability, Diski 9 probability, edge and EV. Market-only fixtures never get fabricated model, edge or EV values.
- **Match Lab:**
  - one automatic starting point, labelled **"Diski 9 Goal Model"** or **"Market-implied Model"** above Estimated Goals;
  - no side-by-side display or selector;
  - Your View only with a valid starting point;
  - state C keeps research information.
- **Learn:** lightweight general concepts, with no CMS, course structure or gamification.

**OD-5: provider verification (approved).**
- **Owner-confirmed:** API-Football Pro, **USD 16/month**, 7,500 requests a day, expiring **14 Dec 2026**, **no automatic renewal**.
  - On expiry the account reverts to the Free plan.
  - A manual renewal before expiry extends the remaining period.
  - The owner will consider a longer term in December, with a reminder on 12 Dec.
- **Step B is authorised for 3–9 Dec 2026 only:**
  - at most 25 counted attempts across both competitions, including retries, failures and pagination;
  - known identifiers and cached data are reused;
  - an initial assessment, then a second one about 24–48 h before the respective fixtures;
  - report by competition, fixture and market;
  - no claim of success on insufficient evidence;
  - stop at the cap;
  - no spending, upgrades or refresh activation.
- European integration remains conditional on satisfactory results and checkpoint acceptance. **CP2A does not depend on Step B.**
- Costs are recorded in [`../operations_f3_cost_log.md`](../operations_f3_cost_log.md) ("Recurring cost register").

**OD-6: plan and estimates (approved).** The structure CP2A → CP2B → CP3A → CP3B → CP4 is retained. The reassessed estimates are in §9.3.

**Other confirmations:**
- The employer-device reassessment happens before participant-dependent testing.
- The personal-Mac migration is mandatory within Phase 10, before wider MVP participation.
- Commercialisation stays deferred.
- No accepted research or closed Phase 6 and Phase 7 decision is reopened.

## 12. CP2A implementation readiness (assessment; CP2A not authorised)

### 12.1 Scope
1. **Goal Model 1.1** in `screener/goal_model.py`:
   - current-season rates only (remove `m0`, `LEAGUE_MIN` 30 and the previous-season paths);
   - a gate of ≥ 2 matches per team and ≥ 20 per competition (`EARLY_SEASON_MATCHES` stays 5 as the warning);
   - the new version string and parameter hash;
   - an `ENGINE_VERSION` bump.
   - The UEFA path is unchanged: market-only, no model.
2. **Cache and forecasts:** new `screener_results` rows supersede old ones, which are never deleted. `forecast_snapshots` records under 1.1. 1.0 rows are untouched.
3. **Weekly Challenge pool** (`challenge/roundsheet.py`):
   - remove the model requirement (line 254);
   - make `float(gm["probabilities"]…)` (line 283) None-safe;
   - write NULL `estimated_goals_*` and `model_prob`;
   - read `eligible_competitions` from the bound schedule, filter on it at construction and refuse at publication (`backend/services/rounds.py`).
4. **Missing-model safety and the OD-3 sources:**
   - `app/challenge/integration.py:99-103`;
   - `challenge/analysis.py:52-77,122-155`;
   - `challenge/structured.py:118-122` / `app/challenge/service.py:204`;
   - `app/challenge/pages.py:652-656,723-725,1261,1274,1717`;
   - `app/challenge/callbacks.py:262,755-758`;
   - plus the Your View tiers 1, 2 and 4 with a compact source summary.
5. **Out of scope:** the market fit, numpy/scipy, European data, navigation and Match Lab states (CP2B and CP3).

### 12.2 Acceptance criteria
- **Parameters:** exactly `k_s` 12 and `k_t` 96, with no `m0`. The fixture estimates equal the accepted research reference (`scripts/research_phase8_cp1.py`, C1-2-20) to 1e-12 on stored data.
- **Gate boundaries:** a team with 1 match → unavailable, 2 → available. A competition with 19 matches → unavailable, 20 → available. Warning at 4 matches, none at 5.
- **No leakage:** changing or deleting every previous-season match leaves every 1.1 estimate identical.
- **1.0 reproducibility:** stored 1.0 forecasts and snapshots are unchanged, and the 1.0 calculation is reproducible from its frozen parameters.
- **Weekly Challenge:**
  - a model-absent fixture with eligible market offers enters the pool with NULL model fields;
  - market-implied values are never written into model fields;
  - a fixture outside `eligible_competitions` (for example league 2) is excluded at construction and refused at publication;
  - the A3 buckets, 4-3-2 feasibility, D-28 thresholds, credits and settlement are unchanged.
- **Builder, review and submission** work with 0, some and all 9 picks model-absent:
  - per-bucket and whole-portfolio Diski 9 availability follows OD-3, including the worked example;
  - `p_recover_model` and `expected_gross_model` are NULL when they are unavailable;
  - no exception is raised.
- **Historical integrity:** existing snapshots, submissions and settled rounds render and settle identically (fingerprints and stored values unchanged).

### 12.3 Regression strategy
- **Focused new tests:** the model gate, leakage, reconciliation, the pool and publication guards, OD-3 availability, the Your View tiers, and builder, review and submit with missing models.
- **Existing suites run unchanged first:**
  - Goal Model and Screener: `test_goal_model.py`, `test_screener_engine.py`, `test_m53_screener.py`;
  - Challenge: `test_challenge_*`, `test_playtest_refinement.py`, `test_a3_guidance.py`;
  - settlement, scoring, championships and achievements.
  - Changes to expected values are allowed only where 1.1 legitimately changes a domestic estimate, and each is explained in the checkpoint report.
- **The full local suite (about 2,340 tests) and full CI**, not the documentation-only path.
- **PostgreSQL integration** runs on a disposable local cluster only, never a protected database.
- **No provider calls**: stored data and recorded fixtures only.
- **Estimate:** 15–20 h (implementation 10–13, testing 5–7).

### 12.4 Contradictions, blockers and open points

| # | Item | Status / proposal |
|---|---|---|
| 1 | **Hostinger cost basis.** The owner's USD 12.64/month is the discounted **first-month** invoice. The cost log forecasts about USD 28.16 a month from renewal. The combined recurring figure is then about USD 69.16, not 53.64. | Both recorded in the cost register. **Owner to confirm** the Hostinger term or price. |
| 2 | **Threshold scope.** The $65 warning and $75 ceiling (F3-D3) were approved for the **infrastructure** log (Hostinger, Supabase, Backblaze). Including API-Football would put a renewal-price month above $65. | Scope recorded as **infrastructure only, unchanged**, with API-Football tracked separately as data-provider spend. **Owner decision** if the thresholds should cover both. |
| 3 | **API-Football expiry 14 Dec (no auto-renewal).** The Free plan has a much lower allowance and restricted seasons, which would block CP2B European development data and any manual refresh after 14 Dec. CP2A needs no provider data. | Owner reminder on 12 Dec. Step B finishes by 9 Dec. |
| 4 | Minimum Market Probability semantics | **Proposed technical detail (adopted unless the owner objects):** All Upcoming shows a fixture when any outcome of the selected market meets the minimum; Challenge Mode filters outcomes, like the bucket filter. At a value above 0, fixtures without fresh consensus are hidden, and the slider says so. |
| 5 | Challenge Mode default OFF replaces today's default (Weekly Challenge when a round is playable) | Approved change; recorded |
| 6 | Removing the existing model threshold slider | Approved removal (OD-4); recorded |
| 7 | Your View tier 3 for frozen Challenge fixtures needs the CP2B fit | Between CP2A and CP2B, tier 4 (consensus) applies. Nothing is deployed in the interval. |
| 8 | Homepage text "previously approved": no earlier copy exists in the repository | Recorded verbatim from the OD-4 instruction (§11). The "brief introductory explanation" wording is to be drafted in CP3A and reviewed at its visual STOP. |

No blocker prevents CP2A once it is authorised.

## Appendix B. CP1-7 Step B: controlled provider verification plan (**authorised for 3–9 Dec 2026 only**, OD-5)

**Hard ceiling: 25 chargeable requests.** Every attempt counts toward it: pagination, retries and failed requests. `/status` is quota-free (§7) and is not counted, but is used as an independent check.

**Cached first:**
- The git-ignored research store `data/research_crossleague.sqlite` (built 16 Nov 2026, 67 requests) already holds the Champions League (`league=2`) and Europa League (`league=3`) for seasons 2022–2026.
- It includes 2026/27 stage labels: four qualifying rounds, including the August "Play-offs", and "League Stage - 1…8". Matchdays 5–8 were still not started when it was built (72 fixtures per competition).
- It holds **no** European odds.
- So **no `/leagues` discovery requests are needed**, because the identifiers, season and stage labels are known.

**Authorised window: 3–9 Dec 2026.** No chargeable request outside it, and none during documentation checkpoints.

**Window:**
- Champions League matchday 6 is 8–9 Dec 2026 (18 fixtures); Europa League matchday 6 is 10 Dec (18 fixtures).
- Pre-match odds are normally published only days before kickoff. **Planned execution within the authorised 3–9 Dec window:** first pass about 3–6 Dec, second pass about 24–48 h before each competition's fixtures.
- Both passes fall before the subscription end on 14 Dec.
- If the plan does not renew, or the window is missed, the next opportunity is matchday 7 (19–21 Jan 2027).

| # | Request | Purpose | Max requests |
|---|---|---|---|
| 0 | `/status` before (quota-free) | Record the counter baseline | 0 |
| 1–2 | `/fixtures?league=2&season=2026`, `/fixtures?league=3&season=2026` | Confirm the identifiers, season and current stage labels (league phase, no knockout labels yet), and that qualifying rounds are identifiable and excluded; refresh matchday 5 statuses | 2 |
| 3–12 | `/odds?league=2&season=2026` and `league=3`, all pages (first pass, ~5–7 days before matchday 6) | Main-stage odds coverage; 1X2 (bet 1), BTTS (bet 8) and Over/Under 2.5 (bet 5); independent bookmaker groups per fixture; `update` timestamps; pagination consistency (`paging.total`) | ≤ 10 (≤ 5 pages each; expected 2 each) |
| 13–18 | The same odds requests, second pass (~24–48 h before kickoff) | Freshness and depth close to kickoff, which is the state the consensus rule actually sees | ≤ 6 (≤ 3 pages each) |
| — | Reserve | Retries, or an unexpected extra page | 7 |
| — | `/status` after (quota-free) | Reconcile the counter against the local count | 0 |
| | **Total** | | **≤ 25** (expected about 10–12) |

**Execution safeguards:**
- **Hard stop:** a local counter refuses request 26. A rate-limit or error response does not trigger an automatic retry beyond the reserve.
- **Isolation:** raw responses are saved to a git-ignored directory and written only to a git-ignored research store. No protected database, no production football store and no scheduler are involved. Refresh stays disabled.
- **Analysis reuses production code:** `odds.consensus` for the ≥ 3 bookmaker-group and ≤ 24 h rules, `challenge_eligible`, and the CP1 market-fit prototype. No new methodology.

**Report:**
- coverage per fixture and market;
- group depth;
- freshness;
- the share of fixtures that would reach state B or state C;
- pagination behaviour;
- request counts before and after;
- any limitation, including "insufficient evidence" if odds are not yet published.

**Ongoing request consumption (reconciled estimate):**
- **Earlier estimates differed in scope:**
  - CP0: 9–12 per sweep, for **three** competitions including the Conference League.
  - CP0 refinement: 3–4, for the **Champions League alone**.
  - CP1: "+4–8", where the lower bound wrongly allowed only 2 per competition.
- **Consistent figure:** each competition costs 1 fixtures request plus 1–3 odds pages (10 fixtures per page; a league-phase matchday has 18), so **3–4 requests per competition per refresh, or 6–8 for both.**
- **Cadence:**
  - European fixtures are midweek, so they do **not** need to join every domestic sweep.
  - Proposed: refresh each European competition only when it has a fixture within the next 7 days, at most twice a day, plus one fixtures-only request after the matchday for statuses.
  - **Post-match results and status** (needed for display, statuses and the next stage's fixtures): 1 fixtures request per competition the morning after each matchday, plus 1 confirmation request the following day. That is about **4 a week** for both.
- **Total:** about 7 × 2 × 8 pre-match (≈ 112) + about 4 post-match ≈ **116 requests in a European week** at most, about 17 a day, or **0.2% of 7,500**.
  - Weeks without European fixtures cost 0.
- **Knockout rounds** (8 ties per leg) need 1 odds page each.
- **The existing domestic sweep** (about 22 requests each) is unchanged.
- **Hosted refresh stays inactive until Phase 6 resumes.** In development, European data is refreshed manually under the existing request budget and caps.

## Appendix A. Screener and Portfolio Build functionality mapping (approved in principle by OD-4)

Inventory taken from the code on 27 Nov 2026. "WC" means Challenge Mode ON and "AU" means Challenge Mode OFF (All Upcoming Fixtures).

| Existing functionality (location) | Proposed location in Portfolio Build | Universe | Change needed | Preserved? |
|---|---|---|---|---|
| Universe toggle `universe` (`app/app.py:387`) | **Challenge Mode** switch above the filter bar | Both | Relabelled; **default OFF (AU)** by OD-4 | Yes (relabelled) |
| Market `market` (402) and builder `f-market` | One market control in the shared bar | Both | Merge; one default (1X2) | Yes (consolidated) |
| Leagues `leagues` (416) and builder `f-league` | One multi-select in the shared bar | Both (AU adds European competitions) | Merge on competition id | Yes (consolidated) |
| Date range `dates` (434) and builder `f-date` (single day) | Date range in the shared bar; the WC default covers the round window | Both | The builder's single day becomes a range (a range can still be one day) | Yes (consolidated) |
| Rank by `direction`: kickoff, model probability, edge, EV (446) | "Sort / rank" in the shared bar | Both (edge and EV only where a model exists) | Label model-dependent ranks "(Diski 9 model)" | Yes |
| Minimum model probability `threshold` (464) | — | — | **Removed by owner decision OD-4.** Replaced by **Minimum Market Probability** (actual consensus; frozen in Challenge Mode; default 0) in the shared bar | **Owner-approved removal** |
| Sort headers (1081) | AU table headers | AU | — | Yes |
| Est. goals, model probability columns, Market / Edge / EV cell | AU table | AU | Market-only fixtures show "—" plus a "Market only" pill; no fitting in the list | Yes |
| Market probability ranking (CP1 requirement) | Rank by "Market probability (consensus)" | Both | **New option** from the existing margin-adjusted consensus; no fitting | Added |
| Pager (`prev`/`next`, `page`) and builder pager (`fxpg`) | One pager per renderer, unchanged | Both | — | Yes |
| Bucket filter `f-bucket` (A/B/C, A3) | WC filter row | WC | — | Yes |
| Team search `f-search` | Shared bar | Both | Extended to AU (cheap; it is a text filter) | Yes (extended) |
| "Available only" `f-avail` | WC filter row | WC | — | Yes |
| Fixture cards with outcome pick buttons (Mkt, D9, You) | WC list | WC | D9 shows "—" when the model is absent | Yes |
| Tracker (remove, clear, review), risk panel, save status | WC side or bottom panel | WC | — | Yes |
| Probability source (Market / Diski 9 / Your View) `T("source")` | WC tracker header | WC | OD-3 behaviour | Yes |
| Choose matches / Portfolio analysis view | WC | WC | — | Yes |
| Review, submit, replace, withdraw, confirmation modals | WC step 2 (Build / Review stepper kept) | WC | — | Yes |
| Guest-work adoption after sign-in | Unchanged | WC | — | Yes |
| Frozen status strip and frozen note | WC header | WC | — | Yes |
| "Your pick" marker in the WC table | WC cards (already shown as the selected state) | WC | — | Yes |
| Match Lab beneath the list (`selected` → `update_detail`) | **Match Lab tab** (`/lab?fixture=`), opened from any row or card | Both | Panel moved to its own route; context kept | Yes (moved) |
| Methodology section on `/` (`app/methodology.py:254`) | **Learn** tab | — | Moved | Yes (moved) |

**Cannot be preserved without extra complexity:** none identified. **Approved by OD-4:**
- the date range, which allows a single date;
- the WC cards and AU table both reused;
- removal of the model threshold.

**Main risks:**
- callbacks keyed to `path == "/"` (9 sites);
- outputs written by several callbacks (`lab-store`, `ch-session`, `selected`, `universe`, `ch-rendered`);
- the wildcard-output rule (`tests/test_callback_wildcard_outputs.py`);
- the performance comments in `refresh_list` and `refresh_buttons`.

**Mitigation:**
- keep both renderers and the existing stores;
- change routing in one place;
- run the existing tests first, then update the route and label tests;
- take browser journeys at 3 widths.

## Appendix C. Navigation and layout wireframes (structural; updated for OD-4)

**Desktop: Portfolio Build, Challenge Mode ON**
```
┌───────────────────────────────────────────────────────────────────────────┐
│ DISKI 9  [Portfolio Build] [Match Lab] [My Challenge] [Leaderboards] [Learn]   Account │
├───────────────────────────────────────────────────────────────────────────┤
│ Think you know football? Put your skills to the test!                      │
│ 9 picks. 100 virtual credits. One challenge.  (one-line explanation)       │
│ Free to play. No real money. Just football.                                │
│ ▸ How to Play (collapsed)                                                  │
│ Challenge Mode [●ON]   Round 48 · closes Fri 13:45 · frozen odds           │
│ Leagues [All▾] Market [1X2▾] Team [____] Dates [Sat–Sun] Sort [Kickoff▾]   │
│ Minimum Market Probability ──○──────── 0%           ▸ Advanced             │
│ Buckets [A Foundation][B Balanced][C Challenger]  ☐ Available only         │
├──────────────────────────────────────────────┬────────────────────────────┤
│ Fixture cards (10/page)                      │ Tracker A 2/4 B 1/3 C 0/2  │
│  Arsenal v Spurs  Sat 18:30  [1][X][2]        │ Source [Market|Diski 9|You]│
│   Mkt 52% · D9 49% · You —   Match Lab →      │ "D9: 2 of 9 unavailable"   │
│ ‹ 1 2 3 ›                                     │ [Clear]       [Review →]   │
└──────────────────────────────────────────────┴────────────────────────────┘
```

**Challenge Mode OFF (default):** the same introduction, How to Play and filter bar (no bucket row, no tracker), and the table at full width:
```
│ Kickoff | League | Home | Away | Est. goals | 1 | X | 2 | Market / Edge     │
│ Tue 21:00 | UCL | Inter | PSG | — [Market only] | — | — | — | Mkt 48/27/25 → │
```

**Match Lab**
```
│ ← Back to Portfolio Build    Fixture [ Search / choose ▾ grouped by competition, date ] │
│ Inter v PSG · UCL League Stage 6 · Tue 21:00                                │
│ Starting point: Market-implied Model   (or: Diski 9 Goal Model)            │
│ Estimated Goals 1.42 – 1.18                                                │
│ [Probabilities] [Your View] [Statistics] [How probabilities are calculated]│
```

**My Challenge** · `[Current] [History] [Rewards]`. **Leaderboards** · `[Weekly] [Championship]`. **Learn** · expandable topics.

**Mobile (390 px):**
- the tabs become a horizontally scrollable strip;
- the introduction shrinks to two lines;
- the filters collapse to "Filters (n) ▾", with the slider kept visible;
- in Challenge Mode, the tracker becomes a sticky bottom bar.
