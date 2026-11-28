# Phase 8 — Goal Model Refinement, Match Lab Education & European Competitions

*Phase name provisional. Record started 27 Nov 2026.*

**Status:**
- CP0 discovery, the CP0 refinement, CP1 research and the supplementary Goal Model research are **formally accepted**.
- All seven CP1 decisions are **approved** (27 Nov 2026).
- CP1-7 Step A (quota-free account check) is **complete**. Step B is **revised (27 Nov 2026, §15.6)** to a single technical verification for European Match Analysis on **Monday 7 Dec 2026** (provisionally 08:00 SAST): planning allowance about 6 counted requests, **hard maximum 12**. Execution still needs separate owner approval.
- **Owner decisions OD-1 to OD-6 are approved with refinements (27 Nov 2026, §11).** The CP2–CP4 plan (§9) is reconciled with them.
- **CP2A is formally accepted by the owner (27 Nov 2026)** (§13, §13.1, closure refinement §13.2). Goal Model 1.1 is the accepted **application** model baseline. It is an application implementation only: nothing is deployed to a hosted environment.
- **CP2A and its closure refinement are fully accepted and closed (27 Nov 2026;** `87849bb`, CI run 172: 2,378 passed, 0 failed, 0 skipped).
- **CP2B is split (owner, 27 Nov 2026):** **CP2B.1**, the market-implied model on domestic data, is **formally accepted and closed by the owner (27 Nov 2026;** `7c7cf22`, CI run 173: 2,416 passed, 0 failed, 0 skipped; §14, §15.1). **CP2B.2**, European Match Analysis (analysis only), is **not authorised**: it follows the 7 Dec verification and a separate owner decision.
- **Revised MVP scope and final navigation decisions approved (27 Nov 2026, §15).** They supersede the Challenge Mode toggle (OD-4), the Match Lab fixture picker (Appendix C) and any European participation in the Weekly Challenge. **The CP3A plan is approved with refinements (27 Nov 2026, §15.8;** `phase8_cp3a_plan.md`). **CP3A-1 (routes and navigation) is formally accepted (27 Nov 2026;** `e7c2aae`, `951a33a`; §15.9). **CP3A-2 is formally accepted (27 Nov 2026;** `2bd1e4f`, `5d63f7a`; §15.11). **CP3A-3 is formally accepted (27 Nov 2026;** `4e08e71`, `1648381`; §15.12). **CP3A-4 is formally accepted (`57d6bc9`, `8af420f`, `fb1873d`; §15.13). CP3A-4B is implemented and awaiting review.** CP3A-5 onwards each need explicit owner authorisation.
- Phase 6 stays paused.

**How to read this record:**
- §1–§8, §10, §11 and §15 record **accepted decisions**. Where §11 refines an earlier section, §11 governs; where §15 refines §11 or earlier, **§15 governs**.
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
- **Prerequisites:** the plan and the Goal Model 1.1 name are approved (OD-6, OD-1). *CP2A was authorised on 27 Nov 2026 and is implemented (§13), awaiting final owner acceptance.*
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

> **Sequencing refinement (owner, 27 Nov 2026).** CP2B runs as two controlled steps, without expanding the Phase 8 scope:
> - **CP2B.1 - market-implied model (authorised; implemented, §14):** the dependencies, the production fit, on-demand fitting and reuse, source-aware Your View identity, the complete OD-3 hierarchy and the minimum Match Lab integration for States A/B/C, all on existing domestic data. No provider requests.
> - **CP2B.2 - European integration (not authorised):** the "European data" items below, conditional on satisfactory Step B evidence (3-9 Dec 2026, ≤ 25 counted attempts) and explicit owner authorisation.
>
> The combined CP2B estimate (15-21 h, §9.3) is kept for planning; actual effort is reported separately for CP2B.1 and CP2B.2.

- **Prerequisites:**
  - CP2A accepted;
  - **CP1-7 Step B results** (European parts, CP2B.2, are gated on verified coverage);
  - the dependency change, approved in principle by CP1-5; the `uv` lockfile is updated at CP2B.1.
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
    - **Introduction:** the compact introduction (§11, OD-4), with the approved **football icon** to the left of the two headline lines (§13.2), then a collapsed **How to Play** (the existing `how_to_play` expander, extended with the markets, A3 bands and navigation) immediately above the fixtures.
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
| CP2B (CP2B.1 + CP2B.2) | 9–13 (European 4–6) | 6–8 | **15–21** | 14–20 |
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

## 12. CP2A implementation readiness (pre-authorisation assessment; CP2A since authorised and implemented, §13)

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
| 1 | **Hostinger cost basis.** USD 12.64 was the discounted first-month invoice. | **Resolved 27 Nov 2026:** the owner confirmed the renewal forecast of about USD 28.16 a month. That gives forecast infrastructure spend of about USD 53.16 and combined spend of about USD 69.16, recorded in the cost register. |
| 2 | **Threshold scope.** Do the $65 warning and $75 ceiling (F3-D3) cover infrastructure only, or the combined total? | **Resolved 27 Nov 2026:** infrastructure only, unchanged. API-Football is tracked separately as data-provider spend, with combined spend kept visible. No additional expenditure is authorised. |
| 3 | **API-Football expiry 14 Dec (no auto-renewal).** The Free plan has a much lower allowance and restricted seasons, which would block CP2B European development data and any manual refresh after 14 Dec. CP2A needs no provider data. | Owner reminder on 12 Dec. Step B finishes by 9 Dec. |
| 4 | Minimum Market Probability semantics | **Approved 27 Nov 2026 for CP3A, not implemented in CP2A.** Challenge Mode uses the accepted **frozen** consensus probabilities, with no new live freshness test and no refreshed values for a published round. *Original proposal:* All Upcoming shows a fixture when any outcome of the selected market meets the minimum; Challenge Mode filters outcomes, like the bucket filter. At a value above 0, fixtures without fresh consensus are hidden, and the slider says so. |
| 5 | Challenge Mode default OFF replaces today's default (Weekly Challenge when a round is playable) | Approved change; recorded |
| 6 | Removing the existing model threshold slider | Approved removal (OD-4); recorded |
| 7 | Your View tier 3 for frozen Challenge fixtures needs the CP2B fit | Between CP2A and CP2B, tier 4 (consensus) applies. Nothing is deployed in the interval. |
| 8 | Homepage text "previously approved": no earlier copy exists in the repository | Recorded verbatim from the OD-4 instruction (§11). The "brief introductory explanation" wording is to be drafted in CP3A and reviewed at its visual STOP. |

No blocker prevents CP2A once it is authorised.

## 13. CP2A implementation record (27 Nov 2026; formally accepted)

**Scope delivered:** §12.1 items 1–4. No market fitting, dependency, lockfile, European integration, navigation, homepage or slider change.

**Goal Model 1.1** (`src/diski9/screener/goal_model.py`):
- current-season competition rates only (`league_rates`);
- gate: both teams ≥ 2 (`TEAM_MIN`) and the competition ≥ 20 (`COMPETITION_MIN`), with reasons `team_matches_insufficient` and `competition_matches_insufficient`;
- the limited-data warning (`LIMITED_DATA_WARNING`) below 5 matches;
- `GOAL_MODEL_VERSION` "1.1" and its parameter hash `d85a3cea30e6bc9d`;
- `ENGINE_VERSION` 3.1.0, so `screener_results` recompute and supersede and `forecast_snapshots` record under 1.1.

**Goal Model 1.0 reproducibility:**
- the frozen parameters are kept as `PARAMS_1_0`, with an unchanged hash of `463105f660644ebf`, together with `league_rates_1_0`;
- stored 1.0 rows are never rewritten;
- the rounds keep `goal-model-1.0`.
- The Match Lab and methodology text no longer describe a previous-season prior.

**Weekly Challenge** (`challenge/roundsheet.py`, `backend/services/rounds.py`, `backend/jobs/prepare.py`, `cli.py`):
- **model requirement removed:** model-absent fixtures with eligible market offers enter the pool with model probability and Estimated Goals frozen as NULL;
- **`eligible_competitions` at construction:**
  - `build_live_snapshot(..., competitions)` from the CLI;
  - `restrict_competitions` after the scheduler's builder;
- **`eligible_competitions` at publication:** `_publication_problem` refuses foreign competitions, using the new `round_competitions` helper;
- no schema migration.

**Missing-model safety and OD-3** (`challenge/analysis.py`, `challenge/structured.py`, `app/challenge/{components,integration,pages,callbacks,persist}.py`):
- `ModelUnavailable`;
- per-bucket `unavailable` counts, with no partial or substituted products;
- `available()`;
- Diski 9 portfolio and analysis output only with all nine predictions;
- the Your View interim hierarchy (adjusted → Diski 9 → market consensus), with a compact source summary;
- the frozen view shows "No model" instead of an edge or EV;
- the tracker, analysis panel, review, submission and confirmed record are all None-safe;
- unavailable aggregates are stored as NULL.

**Evidence:**
- **Real stored data:** production equals the CP1 C1-2-20 reference on **9,164 domestic fixtures**, with a maximum absolute difference of **8.9e-16** and **0** availability mismatches. The script is a scratch reconciliation using temporary copies; no provider and no protected database were touched.
- **Tests:**
  - `tests/test_goal_model.py` (32): reconciliation; 1.0 replay; competition 19/20 and team 1/2 gates; warning 4/5; no previous-season input;
  - `tests/test_phase8_cp2a.py` (17): OD-3 worked example; 0, some and all missing; hierarchy; pool NULLs; competition limits at construction and publication; builder, analysis, review and submit; frozen view; fingerprints;
  - `tests/backend/test_backend_phase8_cp2a.py` (3, PostgreSQL): NULL storage, NULL submission aggregates, publication refusal.

**Legitimate expected-value changes in existing tests** (each follows from the approved methodology; no assertion was weakened):

| Change | Tests |
|---|---|
| **Version and parameter pins:** Goal Model 1.0 → 1.1, engine 3.0.0 → 3.1.0, `m0` → `competition_min` | `test_challenge_ui`, `test_challenge_engine`, `test_challenge_structured`, `test_championship_scoring`, `test_eight_league_odds`, `test_ui_polish`, `test_ui_edge_refine`, `test_market_value`, `test_form_benchmark`, `test_research_form_score`, `test_m53_screener`, `test_match_lab`, `test_detail_layout` |
| **1.0 tests kept as 1.0 reproducibility tests** (original values still asserted) | `test_goal_model` (research agreement, Villa v Forest worked example), `test_phase8_cp1_research::test_c0_reproduces_production_goal_model` |
| **Zero- or one-match teams are now unavailable, with a reason**, instead of falling back to league averages | `test_m53_screener::test_limited_and_missing_history_states`, `test_match_lab::test_early_season_extra_fixtures_flagged`, `test_app::test_limited_data_warnings` (now checks 1 match → unavailable and 2 matches → the warning) |
| **Unavailability reason renamed** (`league_prior_unavailable` → `competition_matches_insufficient`) | `test_screener_engine` |
| **Fixtures without a model may enter the pool** (model None if and only if Estimated Goals are None) | `test_challenge_ui::test_live_snapshot_reads_database_without_api` |
| **Test data:** the `EXTRA` fixtures' teams get two current-season matches via a shared `give_history` helper, so the value-ranking and frozen-ranking tests still rank modelled fixtures | `test_market_value` (`valued`), `test_match_universe` (`_conflict`) |
| **New rounds publish under `goal-model-1.1`**, so new frozen Your View stamps start with "1.1"; stored 1.0 rounds keep "1.0" | `backend/test_backend_your_view`, `backend/test_backend_refinements` |
| **The publication test double gains `eligible_competitions`** | `backend/test_backend_refinements::_problem` |

**Configuration guard:** `round_competitions` selects through the round's bound schedule join, as `round_config` does, which satisfies `test_config_version_guard`.

**Browser check:** `test_phase8_cp2a::test_browser_builder_with_missing_models` runs the demo builder journey (iPhone 13 viewport, 4 of 9 picks without a model) through the Diski 9 and Your View sources and on to review. It records no page errors and no horizontal overflow, and shows the expected notices.

**Not changed:**
- `tools/phase6c3_quant_regression.py` (a manual regression tool) will now report the new 1.1 parameter hash against its stored baseline. This is expected.
- The research weekly-pool collector runs from its own `research/weekly-pools` branch and is unaffected.

### 13.1 CP2A independent review: closure evidence (27 Nov 2026)

**Status (updated): CP2A formally accepted by the owner on 27 Nov 2026.** Implementation `270ed77` (CI run 168: 2,376 passed, 0 failed, 0 skipped); closure documentation `85092d1` (CI run 169, documentation-only path).

**1. Screener cache prerequisite** (`build_live_snapshot` skips a fixture whose Screener payload is missing, `challenge/roundsheet.py`):

*Coverage*
- A payload is produced for **every** fixture passed to `screener.cache.refresh`, whether or not the model is available. `compute_fixture` always returns a result, and `fixture_estimate` returns an "unavailable" block with a reason rather than nothing.
- **Evidence:**
  - the test-data fixtures `EXTRA` (0 matches) and `PROMOTED_FIX` (1 match) are cached with `available: false` (`test_m53_screener::test_limited_and_missing_history_states`, `test_match_lab::test_early_season_extra_fixtures_flagged`);
  - on a temporary copy of the local development store (as of 16 Nov), 243 of 243 upcoming fixtures received payloads.

*Normal paths cover the pool universe*
- **Scheduler:** every sweep, complete or partial, ends with `scheduler.prepare_screener` (`backend/jobs/refresh.py`, `_screener_step` and `run_refresh`). It refreshes `upcoming_fixture_ids(screener_competitions(), now, now + 21 days)`.
- **CLI:** `refresh-data` (`workflow._screener`) and `screener refresh` (`cli.cmd_screener_refresh`) do the same.
- `screener_competitions()` and `odds_competitions()` are the same eight leagues. The statuses match (`NS`/`TBD` = `UPCOMING_STATUSES`). The 21-day window covers the round window.

*Residual gap*
- A fixture can still be excluded for a missing payload alone, but only if the cache was not refreshed after the fixture was ingested. Examples: an operator runs `ingest` without `refresh-data`, or a fixture arrives after the sweep's Screener step.
- This prerequisite **existed before CP2A** (under Goal Model 1.0 such a fixture was also excluded). It is **not** a model-eligibility rule.
- It is currently **silent**: the snapshot diagnostics do not count it.

*Tests*
- CP2A tests distinguish "payload present, model unavailable" (admitted with NULLs).
- **No test covers "payload missing".**

*Proposed minimal correction (not implemented; awaiting approval)*
- Count `fixtures_without_screener_payload` in the snapshot diagnostics, surfaced in readiness, and add one test.
- No change to eligibility, architecture or provider calls.
- Not required for safety in the normal paths.

**2. Historical quantitative regression** (`tools/phase6c3_quant_regression.py`):
- The tool keeps no stored baseline: each comparison regenerates the baseline at its commit in a worktree.
- At the pre-CP2A commit `7a39d31` it reproduces the accepted A3 fingerprint **`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`** (1,473,435 bytes), so the baseline stays reproducible, and nothing was overwritten.
- At `270ed77` the output differs in **exactly one line**: `"params"` changes from `463105f660644ebf` (1.0) to `d85a3cea30e6bc9d` (1.1). Every portfolio, probability, payout, scoring and Poisson-grid value is byte-identical, because the tool's Goal Model inputs are only the parameter hash and the pure `markets()` grid.
- *Proposed compatibility change: **not approved, deferred** (owner, 27 Nov 2026); see §13.2.*

**3. Regression evidence:**
- **CI run 168** (full path: PostgreSQL, real Supabase Auth, browser): **2,376 passed, 0 failed, 0 skipped**, in 29 min 48 s. This is the single complete run after the last fix.
- **Local runs combined several runs:**
  - non-backend: 1,510 passed and 3 failed in one full run; the 3 were test-expectation fixes, and their three files then passed 184 of 184;
  - backend (throwaway PostgreSQL), in a sequential run after all backend fixes: 806 passed, 0 failed, 57 skipped (real Supabase Auth only).
  - Total: 1,513 + 806 + 57 = 2,376, matching CI.
- **Timing-dependent tests:** two Auth tests failed once while two suites ran concurrently on one machine: `test_backend_auth_web::test_privacy_form_rejects_unknown_modes` and `test_acct_records_lock_snapshot`. They passed in isolation (42 of 42), in the sequential run and in CI.

### 13.2 CP2A formal acceptance and closure decisions (27 Nov 2026)

**Accepted by the owner:**
- the CP2A implementation (`270ed77`, CI run 168: 2,376 passed, 0 failed, 0 skipped, 1,787.75 s);
- the model reconciliation;
- historical integrity;
- the eligibility changes;
- the OD-3 probability sources;
- the regression evidence.

**Goal Model 1.1 is the accepted application model baseline.** It has **not** been deployed to production or any hosted environment: hosted deployment remains with Phase 6 and Phase 10.

**Closure refinement: missing Screener payload diagnostic (approved; implemented).**
- `build_live_snapshot` keeps its existing rule: a fixture with no Screener cache payload is excluded, and eligibility and publication are unchanged. It now **counts** such fixtures in the snapshot diagnostics as `fixtures_without_screener_payload`.
- That count is separate from `fixtures_without_model` (payload present, no independent prediction), and those fixtures stay eligible.
- **Visible to the operator:**
  - `round readiness` prints the with/without-model counts and, when the count is above zero, a warning line naming the offline `diski9 screener-refresh` remedy;
  - the JSON output carries it under `pool_diagnostics`;
  - the scheduler's readiness verdict line adds `no_payload=<n>`.
- No automatic refresh, retry, provider call, cache architecture, migration or dependency was added.
- *Validation note:* the first CI run of this refinement (run 170, `a2852f4`) failed 10 tests: 2,368 passed, 10 failed. In every case a readiness test double in `tests/test_prepare_week.py` lacked the `diagnostics` field that the real `PublicationReadiness` always carries. The double was corrected; production code is unchanged.
- *Validation note:* the next run (171, `05d3fef`) passed 2,377 and failed 1. The CP2A browser journey (`test_browser_builder_with_missing_models`) read the review notice after a fixed 400 ms pause, before the slower CI runner had rendered it. The test now waits for the expected review and source notices (up to 30 s); it passed 3 of 3 times locally. Test-only change; production code is unchanged.

**Historical quantitative regression tool: compatibility change deferred (not approved).** `tools/phase6c3_quant_regression.py` is unchanged.
- The accepted Goal Model 1.0 baseline remains reproducible at its original commit (fingerprint `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`).
- Goal Model 1.1 **deliberately** has a different settings fingerprint (`d85a3cea30e6bc9d` against `463105f660644ebf`).
- All portfolio, probability, payout, scoring and Poisson-grid values were byte-identical apart from that fingerprint.
- The tool must **not** silently substitute the historical fingerprint for the active one.
- No historical baseline is overwritten or regenerated with Goal Model 1.1.
- A version-aware comparison may be considered separately if ever needed.

**CP3A homepage refinement (approved; record only, implemented in CP3A):**
- **What:** a single prominent **football-themed decorative icon** to the left of the two headline lines, "Think you know football?" and "Put your skills to the test!".
- **Look:** clean and modern, consistent with the Diski 9 identity, preferably in the existing teal accent. It should not look like a separate brand logo.
- **Layout:** responsive sizing and alignment on desktop and mobile.
- **How:** reuse the existing icon and SVG capabilities, with no animation, design framework or dependency.
- The owner approved the illustrative concept, not a final asset.
- All other homepage wording, layout, How to Play behaviour and Portfolio Build functionality is unchanged.

**Learn: future educational resources (recorded; not MVP commitments).**
- Downloadable PDF guides, worked examples, probability cheat sheets and research summaries.
- Embedded YouTube videos from the owner's Diski 9 channel, linked to topics.
- Recommended books, papers, websites and football-analytics resources.
- Content that grows with user feedback and the channel.
- **Relationship:** YouTube = discover, Learn = understand, Match Lab = apply, Weekly Challenge = practise.
- **Placement:**
  - core lightweight Learn content in CP3B, unchanged;
  - YouTube integration in Phase 11 and ongoing, subject to approval;
  - downloadable resources and recommended reading as future enhancements, timing to be decided.
- No CMS, resource management, PDF generation or video hosting is introduced.
- Register: [`../product/future_enhancements.md`](../product/future_enhancements.md).

**Next (superseded 27 Nov 2026):** CP2A was fully accepted and closed, CP2B was split, and CP2B.1 was authorised (§14). The European Step B verification stays bounded to 3–9 Dec 2026 (≤ 25 counted attempts) and is not brought forward.

## 14. CP2B.1 implementation record: market-implied model (27 Nov 2026; formally accepted by the owner, §15.1)

**Scope (authorised 27 Nov 2026):** the production market-implied model on existing domestic data, the NumPy/SciPy dependencies, on-demand fitting with bounded reuse, source-aware Your View identity, the complete OD-3 Your View hierarchy and the minimum Match Lab integration for States A/B/C. **Not in scope and not done:** CP2B.2 European integration, provider requests, refresh activation, migrations, protected databases, deployment, CP3A/CP3B/CP4.

### 14.1 What was built

- **Dependencies.** `numpy>=2.5.5,<3` and `scipy>=1.18.1,<2` moved from the `dev` group to runtime dependencies. `uv lock` changed only those entries: the locked versions stay **numpy 2.5.5** and **scipy 1.18.1**, and no other package moved. Both are imported **lazily** at the first fit, so application start-up does not load them.
- **`screener/market_fit.py` (new).** The smallest production adaptation:
  - calls the accepted prototype's `fit` **unchanged** (`research/market_implied_xg.py`; its docstring now notes the production reuse);
  - adds the R-3 input rule, rejection of non-converged fits (CP1 report §7), the quality bands and the identity and reuse layer;
  - displays fitted probabilities through the production Poisson function `goal_model.markets`.
  - **Live inputs** (`live_fit`): from the display consensus already loaded for the Match Lab, only markets that are `fresh` now, Challenge-eligible and priced by ≥ 3 independent groups.
  - **Frozen inputs** (`frozen_fit`): only from the round snapshot's outcomes. Each market must be complete, priced by ≥ 3 groups and observed no more than 24 h **before the snapshot time** (never judged against today). No live odds are ever used.
  - **Statuses:** `good` (≤ 2 pp), `approximate` (≤ 4 pp) or `rejected`, with a reason. The reasons are `no_odds`, `missing_1x2`, `missing_goals_market`, `insufficient_groups`, `stale`, `invalid_input`, `not_converged`, `not_identified`, `at_boundary`, `poor_fit`, `optimisation_failure` and `error`. A raised exception becomes `error` (State C), never a crash.
  - **Identity:** SHA-256 of a **methodology fingerprint** (fit version, bounds, start points, thresholds, markets, minimum groups and maximum age), the context (live or frozen), the fixture and the exact input probabilities at full float precision.
  - **Reuse:** an in-process LRU of 512 entries (a few hundred bytes each), thread-safe, holding rejected fits too. No persistence, background job or new infrastructure.
- **States A/B/C** (`app/lab.py`, `app/lab_context.py`):
  - **A, independent model available:** always used. No fit is attempted.
  - **B, a reliable fit:** attached as `r["_starting_point"]`. Model fields are never touched.
  - **C, neither:** shows the reason.
  - **Live context:** fits from the latest fresh consensus.
  - **Frozen context:** every round fixture opened from the Weekly Challenge uses only its snapshot. Frozen estimated goals give State A; otherwise the frozen fit gives State B, or State C. The live model is no longer shown in the frozen context for a fixture frozen without one.
- **Match Lab (minimum functional integration):**
  - "Starting point: Diski 9 Goal Model / Market-implied Model" above Estimated Goals;
  - State B tiles with fitted probabilities labelled as fitted, the good or approximate fit note, and the caveat that a fit shows representation, not predictive accuracy;
  - a separate **"Bookmaker consensus (actual)" / "Market-implied Model (fitted)"** table;
  - **no edge or EV**, including Your View's value check, for State B;
  - State C shows the reason, keeps the research information, and offers no adjustments.
  - Existing components and styles are reused, with five small CSS rules on existing tokens. No navigation, homepage, slider, icon or Learn work.
- **Source-aware Your View identity:**
  - **State A stamp unchanged:** `"<version>|<fixture>|<home>|<away>"`, so existing adjustments stay valid.
  - **State B stamp:** `"mi1.0:<12-hex input identity>|<fixture>|<home>|<away>"`. It never equals a State A stamp, the other context's stamp, or a stamp from different prices.
  - **Server side:** `your_view.frozen_context` and `_resolve` compute the frozen market stamp from the stored snapshot. The existing format check already accepts it, and it is stored in the existing `model_context` text, so **no migration**.
  - **Lazy loading:** `saved_round_fixtures` lets the account load fit only the matches with a saved Your View, never the pool.
  - **Guest adoption** uses the same live stamp.
- **Visible explanations (no silent reset).** When stored numbers no longer match, the Match Lab header says why:
  - the model has no prediction now;
  - the model now has one;
  - the bookmaker prices changed;
  - the Goal Model version changed;
  - the estimated goals changed;
  - no starting point exists.
  - The earlier numbers are never reinterpreted. Adjusting again starts from the current starting point.
  - Account copies keep the stored stamp under `_was` so that the explanation also appears for signed-in participants.
- **Complete OD-3 hierarchy** (`challenge/analysis.py`): Your View is valid adjustment → Diski 9 → **frozen market-implied** → actual frozen consensus.
  - The fitted probabilities travel as an explicit `implied` mapping (`pages.implied_for`), fitted only for **selected** model-absent picks.
  - The **Market** and **Diski 9** sources never use them, and Diski 9 keeps the CP2A availability rules.
  - **Source summary:** for example "Your View: 2 your adjustment · 5 Diski 9 · 1 market-implied · 1 market consensus". Unadjusted fallbacks are never shown as "You".
  - Portfolio mathematics, credits and submission rules are unchanged.
  - Market-only fixtures still get no edge or EV in the frozen view (`frozen_market_value` returns None).
  - Eligibility never depends on a fit: pool construction does not call `market_fit`.

### 14.2 Evidence

- **Reconciliation with the accepted CP1 fits** (`docs/research/phase8_cp1/market_fits.csv`, all 131 qualifying snapshots):
  - rates bit-identical (maximum difference **0**; tolerance 1e-9 goals);
  - 101 good and 29 approximate, as CP1;
  - the one CP1 non-converged fit is **rejected** (`not_converged`), as CP1 recommended;
  - fitted probabilities through `goal_model.markets` differ from the prototype grid by at most **7.4e-13** (tolerance 1e-9: grid truncation below 1e-12 plus floating-point differences between CPUs).
  - Synthetic round trips recover the generating rates to 1e-4.
- **Goal Model 1.1 unchanged:** no Goal Model file changed, and the existing reconciliation and version tests pass. The 9,164-fixture reconciliation was not repeated because independent model calculations are unchanged.
- **Focused tests:**
  - `tests/test_phase8_cp2b1.py`, 37 tests including one browser test:
    - reconciliation;
    - quality bands at 2 and 4 pp;
    - every gating branch;
    - exceptions;
    - live and frozen input rules (groups, freshness, an observation after the snapshot, incomplete markets);
    - historical snapshots unaffected by present age;
    - frozen fits unaffected by live odds and snapshots unchanged;
    - reuse, invalidation (input, context, fixture, methodology) and the cache bound;
    - no fitting from lists or pools;
    - eligibility without fits;
    - States A/B/C;
    - every adjustment transition;
    - the complete hierarchy with mixed sources.
  - `tests/backend/test_backend_phase8_cp2b1.py`, PostgreSQL: the server-side frozen market stamp, Your View save/read, State C refusal and the unchanged stored snapshot.
- **CP2A tests updated (legitimate behaviour extension):** the interim hierarchy counts now include `implied`, and the tracker and browser source notes assert the exact tier counts. With the demo snapshot, model-absent picks now show "market-implied" where a reliable frozen fit exists. No assertion was weakened.
- **Browser (desktop 1280 px):**
  - State B source label, the separate consensus and fitted table, no value check;
  - an adjustment to 2.50 from the market-implied start kept across B → A → B navigation;
  - State C reason, with no adjustments.
  - The CP2A mobile builder journey now checks the mixed-source Your View note.
  - Condition-based waits only.

### 14.3 Performance and dependencies (local; preliminary, not hosted guarantees)

| Measure | CP2B.1 (local) | CP1 research (§3, CP1-5) |
|---|---|---|
| Installed size: numpy, scipy and their bundled libraries | 179 MiB (numpy 34, numpy.libs 23, scipy 92, scipy.libs 30) | about 171 MiB |
| Application start-up | unchanged: `import diski9.app` loads neither library (about 0.55–0.68 s, 66 MiB peak RSS in both runs) | — |
| First fit in a process (includes the lazy imports) | 0.4–0.6 s, +51 MiB peak RSS per worker | about +50 MiB per worker |
| Warm new fit | 200 synthetic fits: median 20.7, p90 30.7, max 40.8 ms (CP1 snapshots: median 20.4, p90 26.3 ms) | about 19 ms |
| Reused fit (cache hit) | median about 17 µs, p99 78 µs | — |
| Cache memory | ≤ 512 entries of a few hundred bytes (about 0.5 KiB pickled) | — |

The +51 MiB applies once per worker that actually fits, against the existing VPS assumptions (Phase 6 F3). No infrastructure change, upgrade or spending is implied. Hosted validation stays with the hosted acceptance checkpoint (§9.4).

### 14.4 Limitations and deviations

- **Frozen context change:** a Weekly Challenge fixture frozen **without** independent estimated goals now opens in the frozen context (State B or C) instead of falling back to the live Match Lab. A fixture frozen **with** them now uses the frozen context even when the live model is currently unavailable. Both follow OD-2 (frozen inputs only).
- **State A stamps** keep their Phase 6C.3 format (version, fixture, rounded estimated goals). A Goal Model parameter change is always a new version (maintenance policy), and a version change already invalidates the stamp.
- **Fits are per process:** each worker has its own LRU, so a cold worker fits again on first use. That is deterministic and cheap.
- **List views** show no market-implied estimated goals, by design. This is recorded in the deferred register.
- The in-app methodology text and the broader Match Lab education stay for CP3B.

### 14.5 Effort

- **CP2B.1 actual:** about 1.5 h of active implementation and testing in this session, against the combined CP2B estimate of 15–21 h. The estimate is retained for planning.
- **CP2B.2 remaining estimate:** about 4–6 h of European work plus its tests, as planned, once authorised after Step B.

## 15. CP2B.1 acceptance, revised MVP scope and final navigation decisions (owner, 27 Nov 2026)

Agreed by the owner after review with ChatGPT; recorded with the updated Master Roadmap of 27 Nov 2026. **Where this section differs from earlier sections, it governs.**

### 15.1 CP2B.1 formally accepted and closed

- **Accepted:** the implementation, testing and CI evidence (`7c7cf22`, CI run 173: 2,416 passed, 0 failed, 0 skipped, 1,811.52 s). No further production change is authorised for CP2B.1.
- **Independent Goal Model adjustment identity: kept as it is** (decision on the closure question A1).
  - The State A stamp stays `"<version>|<fixture>|<home>|<away>"`. No new identity mechanism is introduced, so historical saved adjustments stay valid.
  - The frozen Weekly Challenge path compares the stamp **without** its version field (`app/challenge/integration.py`, `personal_probabilities`). This behaviour predates CP2B.1 (Phase 6B.1 and 6C.3) and is retained for compatibility. Frozen adjustments are stored under a round-specific key, and a round's frozen estimated goals and model version never change, so a frozen stamp cannot refer to another model version.
  - The live (All Upcoming) path compares the whole stamp, including the Goal Model version.
  - **Requirement (recorded in [`../methodology.md`](../methodology.md) §8 and [`../model_changelog.md`](../model_changelog.md)):** any change to Goal Model parameters or methodology must come with a **new Goal Model version**. That version change is what invalidates live adjustments made against the old model.
  - **The stricter market-implied identity is retained:** it covers the methodology fingerprint, the live or frozen context, the fixture and the exact input probabilities.
  - **Remaining limitations (transparent):**
    - a parameter change made **without** a version bump, whose rounded estimated goals do not change, would keep an existing live adjustment. Policy and the per-version hash tests prevent this; the code does not enforce it;
    - movements below 0.005 goals keep an adjustment by design, because adjustments are deltas on the **rounded** baseline and the result is identical.
- **Frozen market data completeness (closure question A2): confirmed complete, no defect.**
  - `build_live_snapshot` freezes every outcome of every Challenge-eligible market, including outcomes outside the A3 bands.
  - `snapshot_rows` stores all of them (`eligible`/`bucket` flags), and `load_snapshot` rebuilds them exactly.
  - Evidence: `tests/backend/test_backend_rounds.py` (stored offers equal snapshot outcomes, exact float round trip, ineligible outcomes kept) and the CP2B.1 PostgreSQL test, which fits from the reloaded snapshot.
  - The frozen fit never reads live data.

### 15.2 Domestic Weekly Challenge design confirmed (frozen snapshot architecture retained)

The owner considered dynamic pricing and submission-time analytical snapshots and **explicitly retained the existing frozen snapshot architecture.** Unchanged:
- the eight domestic competitions;
- the Friday–Tuesday half-open window [Fri 00:00 UTC, Tue 00:00 UTC);
- publication Friday 08:00 SAST;
- the common deadline 15 minutes before the earliest eligible kickoff;
- the A3 eligibility and probability bands;
- nine distinct fixtures (4 Foundation, 3 Balanced, 2 Challenger);
- 100 virtual credits and the accumulator allocations;
- submission, replacement, settlement, correction and void rules;
- the ten-valid-round championship;
- recovery-gated points and the leaderboard rules;
- the six badges and three profile levels (Beginner, Semi-Pro, Pro).

Frozen at publication: market odds, market probabilities, bucket classifications and independent model estimates. Weekly Challenge market-implied Estimated Goals come **only** from the frozen snapshot.

**No** dynamic repricing, dynamic bucket classification or submission-time pricing redesign. The seven-day window (Options B and C of the window research) and extended domestic midweek coverage are **closed** for the current scope.

### 15.3 European football: analysis only (replaces any European competitive role)

- **Champions League and Europa League main-stage fixtures are included for analysis only.** This is an intended MVP feature, subject to the technical verification of §15.6, and is delivered by CP2B.2.
- **European fixtures never take part in:** portfolio construction or submission, Weekly Challenge eligibility, championship points, leaderboards, badges or profile progression, competitive settlement or virtual-credit payouts. No European championship, schedule, rewards system or competitive portfolio architecture is built.
- **Filtering:** main stage only. Qualifying rounds and the Conference League stay excluded.
- **Display:** a dedicated, analysis-only European fixture list with the available market odds and probabilities.
- **Analysis:**
  - no independent Goal Model estimate;
  - Match Lab uses the **latest** market data;
  - market-implied Estimated Goals are calculated on demand where a reliable fit exists (State B), otherwise State C;
  - Your View is available from a reliable market-implied baseline;
  - **no** edge or EV from market-implied estimates;
  - no freezing of European market data.
- **European Bonus Challenges** are moved to the future enhancements register, with no committed date. They are reconsidered only if participant demand justifies the complexity.

### 15.4 Final navigation and UI decisions (supersede OD-4's Challenge Mode toggle and Appendix C's Match Lab picker)

- **Tabs (unchanged):** Portfolio Build, Match Lab, My Challenge, Leaderboards, Learn.
- **Portfolio Build** is the single primary entry point for fixture selection. **The Challenge Mode toggle is removed.**
  - It keeps the agreed homepage wording ("Think you know football? / Put your skills to the test! / 9 picks. 100 virtual credits. One challenge. / Free to play. No real money. Just football."), with one prominent football icon beside the two headline lines, in the existing visual language and without animation or new dependencies.
  - **Two-card homepage (approved direction):**
    - **Domestic Weekly Challenge (teal):** the championship, round and challenge status, and a **Build domestic portfolio** action that opens the domestic challenge fixture list (construction plus detailed analysis).
    - **European Match Analysis (gold):** identifies the Champions League and Europa League, with an **Analyse European matches** action that opens an analysis-only list inside Portfolio Build. It states clearly that European fixtures are not part of the Weekly Challenge.
    - **No non-functional European feature is exposed before CP2B.2 is accepted.**
  - Existing fixture-list components and all approved domestic functionality are kept: filters, market selection, probability filtering, bucket selection, tracking, review, submission, replacement, withdrawal and guest adoption.
- **Match Lab:**
  - detailed analysis of the fixture selected in Portfolio Build. **No competition or fixture selectors**, and no duplicate selection;
  - opened from the tab: it restores the last selected fixture if its context is still valid, otherwise shows an empty state pointing to Portfolio Build;
  - returning to Portfolio Build preserves the originating list, filters, selections, draft and valid adjustments.
- **Frozen / latest toggle ("Use latest available data")**, only for fixtures opened from a published Weekly Challenge with a valid frozen snapshot. It does not depend on whether an independent model exists.
  - **Off (default):**
    - frozen odds and probabilities;
    - the frozen independent model or a reliable frozen market-implied model;
    - the actual snapshot publication timestamp and a note that current prices and estimates may differ;
    - frozen Your View.
  - **On:**
    - latest market and analytical data with their timestamps;
    - clearly marked research only;
    - never changes the competitive portfolio, accepted odds, buckets or frozen baseline.
  - Frozen and latest Your View stay separate. Switching back restores the valid frozen adjustments, and nothing is silently transferred between baselines.
  - European and other non-challenge fixtures use latest data only, with no toggle and no frozen disclaimer.
  - **Inputs are never mixed:** when latest data is unavailable or stale, the latest view says so, falls back to State C or the stale-data display it already uses, and never substitutes frozen inputs.
- **Analytical states:**
  - A/B/C are retained and determined from the applicable frozen or latest context;
  - the source is shown above Estimated Goals;
  - all probability-source, Your View, edge and EV rules are unchanged;
  - European fixtures use States B and C only.
- **Snapshot transparency:**
  - unobtrusive frozen-snapshot messaging on the domestic fixture list and in the frozen Match Lab context, using stored timestamps and never hard-coded days. It explains that odds, probabilities and model estimates were fixed at publication for consistent competitive conditions;
  - latest-data views show their observation or calculation time and never imply real-time bookmaker prices.

### 15.5 International breaks and domestic research access

- **Data-driven opening rules are retained.** There is no international-break calendar, manual championship pause or extra schedule.
- **Confirmed from the implementation (window research, 27 Nov 2026):**
  - an insufficient pool cannot be published (publication guard; publication is operator-run);
  - the draft lapses (reported as `lapsed`) and is never assigned;
  - championship slots are taken only at publication (CH-02);
  - there are no streak badges;
  - preparation resumes automatically for the next week.
- **Gap (for CP3A):** with no new round, the challenge view can show the previous round's "Round locked" message. CP3A adds explicit messaging for the upcoming, unavailable, open, locked and settling states.
- **Domestic research access (decided, §15.8):** a compact **Research only** toggle inside the domestic card replaces the proposed secondary link. Research stays available all week.

### 15.6 European provider verification: revised protocol (not executed; needs separate approval)

- **When:** Monday **7 Dec 2026**, provisionally 08:00 SAST (06:00 UTC). It covers Champions League matchday 6 (8–9 Dec) and Europa League matchday 6 (10 Dec).
- **Scope:** technical verification for **European Match Analysis**. A3 bucket distribution, minimum competition counts and European portfolio feasibility are no longer assessed.
- **Requests:** planning allowance about **6 counted requests**; **hard maximum 12** counted attempts, including pagination, retries and failures:
  - `/status` before and after (quota-free);
  - 2 × `/fixtures` (league 2 and league 3, season 2026: matchday 6 kickoffs, statuses and stage labels; cached identifiers and stage list reused);
  - `/odds` for each competition, expected 2 pages each;
  - the rest as an allowance for an extra page or a retry;
  - use the smallest sufficient number.
- **Assessed with production code** (`fixture_consensus`, `challenge_eligible`, `screener.market_fit`):
  - main-stage coverage;
  - bookmaker and independent-group depth;
  - completeness across 1X2, BTTS and Over/Under 2.5;
  - freshness;
  - reliable-fit quality (good, approximate or rejected, with reasons);
  - pagination and counted consumption.
  - The report also gives a recommended future centralised refresh frequency.
- **Not planned:** a Friday capture, close-to-kickoff captures, a recurring schedule or subscription changes. CP3A and CP3B do not wait for this verification.
- **Supersedes** the request table and timing in Appendix B. Appendix B's isolation and safeguard rules still apply.

### 15.7 Revised Phase 8 sequence and estimates

1. CP2B.1 formal closure: **accepted** (§15.1).
2. **CP3A:** Portfolio Build, navigation and context management.
3. **CP3B:** Match Lab presentation, education and Learn.
4. European provider verification, 7 Dec (separately approved).
5. **CP2B.2:** European Match Analysis integration, subject to the verification.
6. **CP4:** final Phase 8 integration, regression and acceptance.

| Checkpoint | Agreed planning estimate | Reassessed against §15 | Why |
|---|---|---|---|
| CP3A | 14–20 h | **19–26 h** (§15.8) | The toggle removal saves time, but the frozen/latest toggle, Match Lab tab restore and empty state, two-card homepage, status messaging and research access add some (16–22 h); ML-01 as CP3A-4B adds 2–3 h; the Research only toggle adds about 1 h over the link it replaces. |
| CP3B | 14–20 h | **14–20 h** | The States A/B/C mechanics already exist from CP2B.1. |
| CP2B.2 | 6–9 h | **7–10 h** (corrected, §15.8) | The 6–9 h already covered the European data work and showing European fixtures in a list and in Match Lab. Only the gold card and separating them into their own analysis-only list (reusing the research list) are new, about +1 h. The earlier +2 h partly double-counted the list. |
| CP4 | 8–12 h | **8–12 h** | — |
| **Total remaining** | 42–61 h | **48–68 h** (§15.8) | Planning estimates, not commitments. |

**Master Roadmap (unchanged in sequence):** complete Phase 8 → Phase 9 (Lucy and LiveKit) → resume outstanding Phase 6 infrastructure and operations → Phase 10 (MVP deployment and initial private Beta) → extended private Beta and consolidation → Phase 11 (public launch and YouTube). Infrastructure acceptance gates, security requirements, protected-database restrictions, the personal-Mac migration, the operational backlog and deferred enhancements are all preserved. Commercialisation stays outside the committed roadmap.

### 15.8 CP3A plan approval and refinements (owner, 27 Nov 2026)

The owner approved the CP3A plan ([`phase8_cp3a_plan.md`](phase8_cp3a_plan.md)) and its five decisions, with these refinements.

- **D1: competitive selection controls.**
  - Hidden whenever Match Lab shows latest data, which is research only.
  - Switching back to frozen restores them and the valid frozen Your View.
  - The existing status and deadline restrictions still apply.
- **D2: domestic research access.**
  - The secondary text link is **rejected**. A compact **Research only** toggle sits inside the domestic card: the label, switch and information icon are adjacent and grouped on the left, never at the far right.
  - **OFF:** "Build domestic portfolio", the published challenge list, frozen data and competitive functionality.
  - **ON:** "Analyse domestic matches", the upcoming domestic research list, latest data and no competitive functionality.
  - Selections, filters, drafts and valid adjustments are preserved when switching. Research is available all week.
  - The default when no challenge is available is to be confirmed at CP3A-2. The recommendation is in plan §6.
  - It is a local control, not the old global Challenge Mode toggle.
- **D3: status wording.**

  | State | Message |
  |---|---|
  | Upcoming | "Next challenge expected to open at the scheduled date and time, subject to fixture availability." |
  | Unavailable | "No Weekly Challenge available this week. You can still research upcoming matches." |
  | Open | "Entries close at the displayed deadline." |
  | Locked | "Entries closed. Awaiting match results." |
  | Settling | "Results are being settled." |

  - Stored dates and times are used.
  - A reason is given only when verified.
  - No message implies that matches are already in progress after entries lock.
- **D4: ML-01 included** as the separate focused checkpoint **CP3A-4B**:
  - a regression test first;
  - the smallest sufficient correction;
  - historical compatibility preserved;
  - no broad refactor.
- **D5: the European card stays fully hidden** until CP2B.2 is accepted:
  - no "coming soon" and no dead button;
  - registry presence alone does not expose it;
  - no feature-flag framework.
- **Safeguards C1–C4:**
  - **C1:** the frozen/latest toggle's visibility depends on the valid **originating** snapshot, so it stays visible in latest mode;
  - **C2:** Match Lab restoration keeps the fixture, list, context, round and snapshot identity, and fails safely otherwise;
  - **C3:** guest **and** signed-in journeys are tested (browser and account persistence);
  - **C4:** Match Lab has no selectors, restores the last valid fixture or shows an empty state, and returning keeps the list, filters, page, selections, drafts and adjustments.
- **Tab names (owner, 27 Nov 2026):**
  - Learn is renamed **Training Ground** and Leaderboards **Leaderboard**, and the two swap positions. The order is now Portfolio Build, Match Lab, My Challenge, Training Ground, Leaderboard;
  - all functionality is kept: the approved Learn content and future enhancements, and the leaderboards, championship standings and history;
  - the routes `/learn` and `/leaderboards` and the internal identifiers are unchanged;
  - "Learn" and "Leaderboards" elsewhere in this record mean these tabs.
- **Checkpoints:** CP3A-1 routes and navigation; CP3A-2 homepage, domestic card, research access and status; CP3A-3 Match Lab navigation and state; CP3A-4 frozen/latest toggle and isolation; CP3A-4B ML-01; CP3A-5 integration, browser, full CI and docs. Each is reviewed and accepted separately.
- **CI frequency (owner, 27 Nov 2026):**
  - CP3A-1 to CP3A-4: focused local tests, regressions, lint, formatting and browser checks, committed with `[skip ci]`;
  - full CI at CP3A-4B and CP3A-5;
  - intermediate acceptance is not CP3A acceptance;
  - the workflow and assertions are unchanged.
- **Estimates (planning, not commitments):**

  | Checkpoint | Estimate | Note |
  |---|---|---|
  | CP3A | **19–26 h** | 16–22 h, plus ML-01 2–3 h, plus about 1 h for the Research only toggle over the link it replaces |
  | CP3B | 14–20 h | |
  | CP2B.2 | **7–10 h**, corrected from 8–11 h | See below |
  | CP4 | 8–12 h | |
  | **Total remaining Phase 8** | **48–68 h** | |

  **Why CP2B.2 is 7–10 h:**
  - the original 6–9 h (the European share of CP2B) already covered the registry entries, the stage allowlist, the neutral-final rule, ingestion and showing European fixtures in a list and in Match Lab;
  - §15.4 replaced "European fixtures in the shared list" with a separate analysis-only list and a gold card;
  - the list reuses the research list built in CP3A-2, filtered to competitions 2 and 3, so the new work is the card and the filtering, about +1 h;
  - the earlier +2 h partly counted the list twice;
  - nothing in CP2B.2 is also counted in CP3A or CP3B.

### 15.9 CP3A-1 acceptance and Research only defaults (owner, 27 Nov 2026)

- **CP3A-1 formally accepted:**
  - implementation `e7c2aae` and navigation naming `951a33a`, both independently verified by ChatGPT;
  - CI run 174 (successful: PostgreSQL, real Supabase Auth, browser tests, migration checks, lint and formatting) validates the **pre-CP3A-1 baseline**, not the new navigation;
  - the reported local testing and focused re-runs are accepted as proportionate evidence;
  - full cumulative CI remains deferred to CP3A-4B.
- **Outstanding items kept:**
  - direct Match Lab deep-link fixture restoration (CP3A-3);
  - Training Ground content (CP3B);
  - legacy acceptance script routes (CP3A-5);
  - signed-in participant browser acceptance (CP3A-5).
- **Estimates accepted:** CP3A 19–26 h (including ML-01), CP3B 14–20 h, CP2B.2 7–10 h, CP4 8–12 h; Phase 8 planning baseline 48–68 h before deducting completed work. The CP2B.2 correction is accepted.
- **Research only initial defaults** (no session choice yet):
  - OFF for an open, locked or settling challenge;
  - ON for an upcoming or unavailable one.
  - These are initial values, not continuous overrides. An explicit change is kept for the browser session, including Match Lab and back. There is no account-level preference or new persistence layer.
  - An unavailable challenge never exposes invalid competitive functionality to honour a preference.
  - Locked and settling challenges stay viewable with frozen data; entry restrictions are unchanged.
- **CP3A-2 authorised** (implemented; plan §10.3).

### 15.10 CP3A-2 closure refinements (owner, 27 Nov 2026)

- **Homepage, in this order:**
  1. "Think you know football?"
  2. "Put your skills to the test!"
  3. "Analyse upcoming football matches, compare probabilities and develop your own predictions. Put your skills into practice by participating in the Weekly Challenge."
  4. The Domestic Weekly Challenge card.
  5. "100 Credits. 9 Picks. 1 Challenge."
  - The old tagline and the "Free to play…" footnote are removed. The builder's "Virtual credits only · no real money" disclosure stays.
- **Card:**
  - full content width;
  - no technical round code and no separate deadline or expected-time fields, since the status sentence carries them;
  - championship name and progress, fixture window and status are kept.
  - With CP2B.2, two equal cards side by side on wide screens, stacked on mobile; no space is reserved now.
- **Main action, Research only OFF:**

  | Challenge | Button |
  |---|---|
  | Open | Build domestic portfolio |
  | Locked, settling | View domestic challenge |
  | Upcoming, unavailable | View challenge information |

  With Research only ON: "Analyse domestic matches". This is wording only; entry restrictions are unchanged.
- **Locked builder notice:** "Entries are closed for this Weekly Challenge. You can still view the published fixtures or switch to Research only to analyse upcoming matches." The demonstration invitation and button are removed here only; the demonstration round itself is unchanged.
- **How to play** is collapsed by default, with its content unchanged.
- **Technical checks:**
  - **A. Minimum Market Probability:** the research list's slider is still the pre-OD-4 *minimum model probability* threshold, disabled under kickoff ranking. The approved filter (consensus, independent of ranking, default 0, no model threshold; §11 OD-4, Appendix row 4) was approved for CP3A but never implemented. Replacing it changes the ranking filter (`screener/rank.py`), the edge and EV eligible-outcome rule (`best_edge`/`best_ev`) and the frozen challenge ordering, and the existing threshold semantics are pinned in 14 test files. This is beyond a narrow correction, so it is **reported for owner approval** rather than changed (proposal: CP3A-3, with the filters moving into Portfolio Build, about 2–3 h).
  - **B. Goal Model wording:** the "Goal Model 1.0" labels were outdated application wording, not historical data.
    - The research-list legend, column tooltip and footer now read the current version from the code (1.1).
    - The builder labels, which can describe a round frozen under an earlier version, and the glossary now say "the Diski 9 Goal Model".
    - The methodology changelog's historical 1.0 entry and the stored data are unchanged.
  - **C. Championship stream:** the card now reuses `championships.stream_of_round` (the round's own `development`, `beta` or `official` stream). With no round, it uses the weekend schedule's series. An official stream that has not started is simply not shown. Official challenges are not enabled.
  - **D. Schedule failure:** an unreadable schedule now gives "Challenge information is temporarily unavailable. You can still research upcoming matches." (Research only ON). "No Weekly Challenge available this week" appears only when the schedule was read and its publication time passed without a published round.

### 15.11 CP3A-2 acceptance and CP3A-3 (owner, 27 Nov 2026)

- **CP3A-2 formally accepted:**
  - implementation `2bd1e4f` and closure refinements `5d63f7a`;
  - accepted items: the final homepage design and wording, the full-width domestic card, the Research only defaults and session preference, the button wording, status and snapshot messaging, How to play collapsed, and the Goal Model wording, championship stream and schedule-failure corrections;
  - the final regression results (534 passed, 0 failed, 10 Auth-related skips) are accepted as proportionate evidence;
  - ChatGPT reviewed the commits and screenshots but did not run the tests;
  - full local testing and CI remain deferred to CP3A-4B;
  - the domestic homepage is final for the MVP: no further cosmetic redesign unless a functional or responsive issue requires it.
- **CP3A-3 authorised and implemented** (plan §10.4):
  - Portfolio Build as the single selection entry point, the simplified Match Lab, originating context, direct links and restoration;
  - the **Minimum Market Probability filter**, carried forward with owner approval and confirmed within the approved OD-4 decision;
  - read-only locked and settling access;
  - the footer model wording.
- **Estimates:**
  - the filter restores work counted in the original CP3A estimate but omitted from the rebuilt step list;
  - CP3A-3 5–7 h, CP3A 21–29 h, Phase 8 planning baseline 50–71 h, before deducting completed work. Planning estimates, not commitments.
- **CP3A-3 closure refinements (owner, 27 Nov 2026; plan §10.5):**
  - the snapshot-resolution race found in independent review is corrected: each Match Lab resolution uses one published round-view and snapshot pair (`ChallengeService.published_pair()`), with a round-identity check that fails safely;
  - the Match Lab market selector (1X2, BTTS, Over/Under 2.5) is approved as a product decision;
  - slider spacing and locked-card readability corrected;
  - carried to CP3A-4: All Upcoming Fixtures wording in the Match Lab, frozen versus latest timestamps, compact frozen-data source information for locked and settling analysis, and the frozen/latest toggle.

## Appendix B. CP1-7 Step B: controlled provider verification plan (**timing and request table superseded by §15.6**, 27 Nov 2026; safeguards still apply)

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

### 15.12 CP3A-3 acceptance and CP3A-4 (owner, 27 Nov 2026)

- **CP3A-3 formally accepted** after ChatGPT's independent review: implementation `4e08e71`, closure `1648381`.
- **Intermittent browser test** (`test_ui_edge_refine.py::test_browser_outcome_colours_section_d_and_sliders`): one failure in the closure regression run, three successful isolated reruns; suspected, unconfirmed CPU contention from concurrent screenshot jobs. Carried forward for explicit verification at CP3A-4B; screenshot jobs are not run alongside the regression suite.
- **CP3A-4 authorised and implemented** (plan §10.6): the "Use latest available data" toggle for challenge-origin matches, context and Your View isolation, competitive mutation protection, per-context source and time information, and the display-only published-pair correction.
- **CP3A-4 closure refinements (owner, 27 Nov 2026; plan §10.7):** the bookmaker reference follows the analytical context (frozen: snapshot values only, never latest prices); the supplementary latest-data statistics are disclosed in Section B of the frozen analysis; source information left-aligned. The stale-event investigation found the screenshot inconsistency to be a pre-response capture, confirmed that competitive selections and Your View cannot cross contexts, and found one minor defect (a toggle switch lost when a market change overlapped it), corrected with owner approval in `lab_want` with regression tests. The toggle also inherits the existing ML-01 race: the CP3A-4B ML-01 work must cover it, verify both recorded intermittent browser tests (investigating whether either is ML-01) and complete the full suite and CI, including real Supabase Auth coverage.

### 15.13 CP3A-4 acceptance and CP3A-4B (owner, 28 Nov 2026)

- **CP3A-4 formally accepted** after ChatGPT's independent review: `57d6bc9`, `8af420f`, `fb1873d`.
- **CP3A-4B authorised and implemented** (plan §10.8): ML-01 corrected at its causes (a rebuild's mount call no longer acts as an edit; Your View edits run one at a time; a moved slider is not written back; store revision marker; no persistence or architecture change), regression and delayed-response browser coverage, both intermittent browser tests investigated (the slider test's cause established and corrected; the CP2B.1 test's not conclusively established, its known mechanisms corrected), the full local suite and full CI including real Supabase Auth.
- **ML-01 backlog item (6C.5 Stage G, G-3): resolved in CP3A-4B.**
- **Cumulative local verification (CP3A-1 to CP3A-4B), one clean run:** disposable PostgreSQL 16, a real local Supabase Auth server (GoTrue v2.198.0, the CI version) on a disposable auth database, browser tooling required, the football API pointed at a closed port: **2513 collected, 2513 passed, 0 failed, 0 skipped, 0 errors** (38 min 11 s); lint and formatting clean; migrations upgrade, re-upgrade, check, downgrade to base and upgrade on a fresh disposable database.
- **Full GitHub CI (cumulative CP3A gate):** run #175, run ID 46098815977, job `checks` 140836319929, commit `1c68238`, conclusion **success** (32 min 50 s). Lint, formatting, competition-schema migrations from an empty database, a real Supabase Auth server (official image), PostgreSQL 17, pinned Playwright/Chromium and the full suite: **2513 passed, 0 failed, 0 skipped**, 2 warnings (31 min 23 s). The previously skipped real Supabase Auth tests ran. The 2 warnings are one `SyntaxWarning` (an unescaped `\/` in a browser-test JavaScript string, `tests/test_app.py`, added in CP3A-3): harmless; a one-line fix is proposed for CP3A-5.
- **Repeated runs with four CPUs saturated (corrected code):** slider test 10/10 (pre-fix code: 6 of 10 failed), CP2B.1 test 10/10, delayed-response test 5/5, Your View persistence journey 5/5.

### 15.14 CP3A-4B acceptance and CP3A-5 (owner, 28 Nov 2026)

- **CP3A-4B formally accepted** after ChatGPT's independent code review and verification of GitHub CI: implementation `1c68238819cdde16cc4b5750604481bcf13665c7`, documentation `d06efac`.
- **Accepted baseline:** CI run #175 (run ID 46098815977, job `checks` 140836319929), independently verified: **2513 passed, 0 failed, 0 skipped**, real Supabase Auth, PostgreSQL 17, pinned Playwright/Chromium. The full local suite (2513/2513, one clean run) and the saturated-CPU repetitions are Claude-reported.
- **ML-01 closed as resolved.** Not to be reopened without new evidence.
- **Residual uncertainty (accepted by the owner):** the precise cause of the second intermittent browser test (`test_phase8_cp2b1.py::test_browser_match_lab_states_and_adjustments`) is not conclusively established; both identified mechanisms are corrected and it passed 10/10 under load. Monitored during CP3A-5 final regression only; no indefinite investigation unless it recurs or new evidence identifies a defect.
- **Carried into CP3A-5:** the one-line correction of the `SyntaxWarning` (unescaped `\/` in a browser-test JavaScript string, `tests/test_app.py`), authorised without changing the regular expression's behaviour.
- **CP3A-5 authorised** (plan §10.9): final integration and acceptance of CP3A-1 to CP3A-4B, the legacy acceptance script routes, guest and signed-in browser journeys at 390, 768 and 1280 px on disposable PostgreSQL and a real local Supabase Auth server, the challenge lifecycle and research integration, responsive evidence, the full local suite and full CI. An integration checkpoint, not feature development.
- **Documentation correction:** `docs/product/future_enhancements.md` (the register cited in §10) was emptied by mistake in `d382aa4`; restored from `7c7cf22` with the items that commit intended to add, and ML-01 marked resolved.
- **CP3A-5 implemented** (plan §10.9): no application code changed. One permanent integrated acceptance test on real PostgreSQL and a real local Supabase Auth server (guest at 390, 768 and 1280 px; guest-to-account adoption; signed-in frozen/latest Your View, Match Lab selection, review, submission, My Challenge, withdrawal; a second device at 390 and 768 px; locked and unavailable rounds); legacy acceptance script routes; the warning fix; screenshots (`docs/screenshots/phase8_cp3a5/`).
- **Cumulative local verification (CP3A-1 to CP3A-5), one clean run** (Claude-reported): disposable PostgreSQL 16, real local Supabase Auth (GoTrue v2.198.0) on a disposable auth database, browser tooling required, the football API pointed at a closed port: **2514 collected, 2514 passed, 0 failed, 0 skipped, 0 errors, 0 warnings** (42 min 41 s); lint and formatting clean. +1 test against the CP3A-4B baseline (2513): the new integrated acceptance test. The `SyntaxWarning` no longer appears. Both previously intermittent browser tests (`test_ui_edge_refine.py::test_browser_outcome_colours_section_d_and_sliders`, `test_phase8_cp2b1.py::test_browser_match_lab_states_and_adjustments`) passed; no recurrence.
- **CI run #177 — failed (kept as history).** Run ID 46110855431, job `checks` 140873839797, commit `dddc5f4`: 1 failed, 2513 passed (test step 33 min 45 s); every other gate passed, the new CP3A-5 test and both previously intermittent tests passed, no `SyntaxWarning`. Failure: `tests/test_f2_backup_restore.py::test_restore_refuses_the_live_store_and_every_alias` (Phase 6 F2): the live store's `-wal`/`-shm` disappeared between the test's snapshots. **Root cause (test only):** the test opened its WAL consumer inline (`make_engine(...).connect().close()`) and never disposed of the engine; the garbage collector can free it at any moment, its last SQLite connection then closes and SQLite deletes `-wal`/`-shm`. The production restore refuses before any file operation. **Evidence:** a standalone probe shows the files present after the connection closes and deleted after `gc.collect()`; forcing a collection inside each refusal reproduces the exact CI assertion with the old test and passes with the corrected one. **Correction** (owner-authorised test maintenance, not a resumption of Phase 6): `26428ee` holds the engine for the whole test and disposes of it in `finally`; assertions unchanged. F2 tests: 95 passed.
- **CI run #178 — failed (kept as history).** Run ID 46127119195, job `checks` 140924071261, commit `26428ee`: 1 failed, 2513 passed (34 min 01 s); the corrected F2 test passed. Failure: `tests/test_phase8_cp3a1.py::test_browser_navigation_at_three_widths` timed out waiting for the pick total to survive the Match Lab round trip. **Root cause (test only):** after the demo pick the script waited a fixed 300 ms and for `networkidle` (which returns at once on a loaded page), so a slow runner recorded the total before the pick's response (`0/9`); the builder correctly showed `1/9` after the round trip, so the wait for `0/9` could never succeed. **Evidence:** 9 instrumented runs (27 width passes, with and without full CPU load) recorded `1/9`; with 800 ms delayed responses the old test recorded `0/9` and the builder showed `1/9` on return (the pick was never lost). **Correction** (owner-authorised): `e3d77f9` waits for the expected `1/9` before recording it; assertions unchanged. Verified by running the real test with 800 ms delayed responses (passes) and with a simulated lost pick (fails at the survival wait, so genuine loss is still detected); focused tests (CP3A-1, CP3A-2, CP3A-3, challenge state): 69 passed.
- **Future enhancements register reconciled** line by line against its last intact version (`7c7cf22`, 155 lines; now 170): every earlier line is present unchanged except the two ML-01 lines, deliberately struck through and marked resolved in CP3A-4B; additions are only the restoration note, European Bonus Challenges (a future enhancement, §15.3) and a "considered and closed for the current scope" list (dynamic pricing and submission-time snapshots, the seven-day window and extended midweek coverage, §15.2; listed as closed rather than deferred because §15.2 rejects them). Both release dependencies (Official championship scheduling; administration device migration) and every other deferred item are unchanged; nothing else was removed, changed or marked complete.
- **Outstanding UI correction for CP3B** (owner-approved deferral; plan §10.9.2): at 390 px the Your View value box can clip the last character of a signed value (`+0.30` shown as `+0.3`); presentation only (value, calculations and persistence verified correct).
- **CI run #179 — success (the CP3A-5 CI gate).** Run ID 46131672124, job `checks` 140937979204, commit `e3d77f9`: lint, formatting, competition-schema migrations from an empty database, a real Supabase Auth server (official image), PostgreSQL 17, pinned Playwright/Chromium and the full suite: **2514 passed, 0 failed, 0 skipped, no pytest warnings** (test step 33 min 34 s; job 34 min 59 s). Against the CP3A-4B baseline (2513 passed, 2 warnings): +1 test (the CP3A-5 integrated acceptance test) and the `SyntaxWarning` gone. The only warnings in the job log are Node.js deprecation notices from the runner's tooling, outside pytest. CI #177 and #178 remain on record as failed runs (above).
- **Status at implementation:** CP3A-5 implemented and verified; awaiting ChatGPT's independent review and owner acceptance. CP3B not started.

### 15.15 CP3A formally accepted and closed; CP3A-R reassessment authorised (owner, 28 Nov 2026)

- **CP3A-5 formally accepted** after ChatGPT's independent review; **CP3A is closed in its entirety** (CP3A-1 to CP3A-5 all formally accepted). Accepted checkpoints are not reopened without new evidence.
- **Accepted testing baseline:** CI run #179 (run ID 46131672124, job 140937979204), tested commit `e3d77f9`, documentation `6b8acb7`: **2514 passed, 0 failed, 0 skipped, 0 pytest warnings**, test step 33 min 34 s; independently verified by ChatGPT. Supersedes #175. CI #177 and #178 stay on record as failed runs with their causes and test-only corrections (§15.14).
- ML-01 remains closed as resolved. Previously accepted limitations and deferrals stay on record: the 390 px Your View clipping (CP3B), the unconfirmed cause of the CP2B.1 intermittent test, legacy scripts syntax-checked only, performance not re-measured, hosted infrastructure and Beta acceptance open.
- **CP3A-R authorised:** a coordinated, read-only product simplification and technical reassessment of twelve items (latest pricing, dynamic buckets, irrevocable submissions, rolling Friday–Sunday entry, removing the frozen/latest toggle, per-entry submission records, Goal Model 96/12 vs 90/18 sensitivity, removing Research only, an automatic weekday/weekend experience, a restricted fixture window, Friday–Sunday vs Friday–Monday coverage, a two-card homepage). Research, source inspection, historical analysis and isolated research scripts only; **no production change is authorised.**
- **Reopened for investigation (historical rejections preserved):** dynamic pricing, dynamic bucket classification and submission-time analytical snapshots were rejected on 27 Nov 2026 (§15.2, register P8-FROZEN). That decision stands until the owner decides otherwise; the proposals are **under investigation, not approved**. Findings: [`phase8_cp3ar_reassessment.md`](phase8_cp3ar_reassessment.md).
- **Revised sequence:** CP3A-R reassessment → ChatGPT review and owner decisions → implement only approved CP3A-R items → CP3B → CP2B.2 → CP4 → Phase 9. A Phase 8 product scope freeze follows the agreed CP3A-R scope. Phase 6 remains paused.

