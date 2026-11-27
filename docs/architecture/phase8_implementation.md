# Phase 8 — Goal Model Refinement, Match Lab Education & European Competitions

*Phase name provisional. Record started 27 Nov 2026.*

**Status:**
- CP0 discovery, the CP0 refinement, CP1 research and the supplementary Goal Model research are **formally accepted**.
- All seven CP1 decisions are **approved** (27 Nov 2026).
- CP1-7 Step A (quota-free account check) is **complete**. Step B (at most 25 chargeable requests) is **planned, not authorised**.
- The CP2–CP4 implementation plan (§9) is **proposed, subject to ChatGPT review and owner approval**.
- CP2 is **not authorised**. Phase 6 stays paused.

**How to read this record:**
- §1–§8 and §10 record **accepted decisions**.
- §9 and the appendices are **proposals** still under review.
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

**Portfolio Build** merges the existing Screener and Portfolio Build. This is consolidation, not a reduction in functionality. It has two fixture universes:
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

**Billing:** auto-renewal status and billing details are not exposed by `/status`. Only the dashboard shows them. **Owner action:** before Step B and before 14 Dec 2026, confirm in the API-Football dashboard whether the Pro plan renews automatically, and report only "renews: yes/no" and the renewal price. No purchase or change is authorised by this record.

The Step B proposal is in Appendix B.

## 8. Weekly Challenge, frozen context and historical integrity

Restated from CP1-6 for implementers. The existing app schema already allows model fields to be NULL:
- `snapshot_fixtures.estimated_goals_*`;
- `snapshot_offers.model_prob`;
- `submissions.p_recover_model` and `expected_gross_model`;
- `submission_selections.model_prob`.

So **no app-database migration is expected** for CP1-6. Historical frozen rounds are never recomputed.

## 9. CP2–CP4 implementation plan

*Proposed 27 Nov 2026; subject to ChatGPT review and owner approval. It will be replaced by the approved plan. Appendix A has the functionality mapping, and Appendix C the wireframes.*

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
- **The Screener's default ranking (kickoff) already keeps model-absent fixtures.** Probability, edge and EV ranks **drop them once the threshold is above 0** (`screener/rank.py:72-90`, `app/data.py:380-388`). This is acceptable by design: the threshold is an explicit model filter. It will be labelled.
- **No app-database migration is expected** (§8). European competitions need registry entries (`leagues.py`), a stage allowlist, refresh inclusion and the existing UEFA path in `goal_model.fixture_estimate`. The football store already has `round_name`, so **no football-store migration is expected** either. CP2B verifies both.
- **Builder filter values are not stored** and reset on re-render. Context preservation needs them kept in the existing session store.
- **The existing `screener-root` stays mounted and is hidden by style.** That already preserves list state across routes, and the plan reuses the pattern.
- **Nine callbacks test `path == "/"`, and several outputs use `allow_duplicate`.** These are the main regression risk of the navigation change (Appendix A, risks).

### 9.2 Checkpoints

**CP2A: domestic model, Weekly Challenge eligibility and missing-model safety (backend plus the minimal builder fixes)**
- **Objective:** C1-2-20 in production and CP1-6, shipped together.
- **Prerequisites:** owner approval of this plan; the version label (OD-1).
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
  - **Missing-model safety:** fix every path listed in §9.1. The Diski 9 source and analytics become "unavailable" (OD-3) instead of raising.
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
- **Estimate: 14–18 h. STOP:** ChatGPT review.

**CP2B: European competitions, market-implied Estimated Goals and source-aware identity**
- **Prerequisites:**
  - CP2A accepted;
  - **CP1-7 Step B results** (European parts are gated on verified coverage);
  - owner approval of the dependency change.
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
  - **Frozen context:** a market fit from the snapshot's frozen market probabilities (OD-2), deterministic and never recomputed from live odds.
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
- **Estimate: 14–20 h. STOP:** ChatGPT review.

**CP3A: navigation and the Portfolio Build consolidation**
- **Prerequisites:**
  - CP2A accepted;
  - **owner approval of the wireframes (Appendix C) and the mapping (Appendix A)**.
- **Changes:**
  - **Tabs:** five tabs from the existing `NAV`, with routes `/` Portfolio Build, `/lab` Match Lab, `/challenge/me` My Challenge, `/leaderboards`, `/learn`. `/challenge` redirects to `/`, so old links keep working.
  - **Portfolio Build:** one shared filter bar (universe, market, leagues, dates). Under it:
    - **Weekly Challenge** universe: the existing builder card list, tracker and review, plus the Screener's rank and threshold controls as an "Advanced" collapsible.
    - **All Upcoming** universe: the existing Screener table without portfolio controls.
    - Two existing renderers are reused, not one new unified list, which keeps the regression risk low.
  - **Match Lab:** the existing panel at `/lab`, with a fixture picker grouped by competition and date, and a "← Back to Portfolio Build" link.
  - **Context:** Portfolio Build stays mounted and hidden, as `screener-root` is today. The builder filters move into `ch-prefs` (session).
  - **Rewards:** "Achievements" becomes "Rewards" in user-facing strings only.
  - **Leaderboards:** unchanged content under its own tab.
  - **Learn:** a shell holding the existing methodology, how-to-play, rules and glossary content.
- **Tests:**
  - update the route and label tests;
  - a navigation test (order, default, active state);
  - context preservation (filters, page, picks, Your View across Portfolio Build ↔ Match Lab);
  - guest access to All Upcoming;
  - the wildcard-output guard;
  - browser screenshots at 3 widths.
- **Estimate: 20–26 h. STOP:** visual review by the owner.

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

### 9.3 Effort

| Checkpoint | Earlier provisional | Revised |
|---|---|---|
| CP2A + CP2B (backend) | 22–30 | **28–38** |
| CP3A + CP3B (interface) | 22–30 | **36–48** |
| CP4 | 8–12 | **8–12** |
| **Total** | **52–72** | **72–98 active hours** |

**Why higher:**
- The approved navigation consolidation (merging two pages, a standalone Match Lab route, context preservation, five tabs, Learn) adds about 14–18 h.
- Missing-model safety reaches more builder and review paths than CP1 assumed: about +3–4 h.
- Filter mapping and preservation tests: about +2–3 h.
- European work is unchanged in size, but is now gated on Step B.

The estimate excludes owner review time and any re-work after visual review.

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
   - both universes are present;
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

### 9.6 Open owner decisions

| ID | Decision | Recommendation |
|---|---|---|
| OD-1 | Version label for C1-2-20 | **Goal Model 1.1** |
| OD-2 | Frozen Weekly Challenge context for a model-absent fixture: state B from the snapshot's frozen market probabilities, or state C | **State B from frozen probabilities.** It is deterministic, uses no live data, and gives Your View a starting point. |
| OD-3 | Builder and review "Diski 9" source when some picks have no model | **Show Diski 9 portfolio figures only when all 9 picks have the model; otherwise "Diski 9 estimate unavailable for n of 9 picks".** Your View falls back per pick to its starting point, else to the market consensus, labelled. This keeps market and model separate (C-14). |
| OD-4 | Approve the wireframes and the mapping before CP3A | Review Appendix A and Appendix C |
| OD-5 | Authorise CP1-7 Step B (Appendix B) and confirm plan renewal (§7) | Authorise for about 3–6 Dec 2026 |
| OD-6 | Approve the plan and the revised estimate, and authorise CP2A | — |

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

## Appendix B. CP1-7 Step B: controlled provider verification plan (proposed; not authorised)

**Hard ceiling: 25 chargeable requests.** Every attempt counts toward it: pagination, retries and failed requests. `/status` is quota-free (§7) and is not counted, but is used as an independent check.

**Cached first:**
- The git-ignored research store `data/research_crossleague.sqlite` (built 16 Nov 2026, 67 requests) already holds the Champions League (`league=2`) and Europa League (`league=3`) for seasons 2022–2026.
- It includes 2026/27 stage labels: four qualifying rounds, including the August "Play-offs", and "League Stage - 1…8". Matchdays 5–8 were still not started when it was built (72 fixtures per competition).
- It holds **no** European odds.
- So **no `/leagues` discovery requests are needed**, because the identifiers, season and stage labels are known.

**Window:**
- Champions League matchday 6 is 8–9 Dec 2026 (18 fixtures); Europa League matchday 6 is 10 Dec (18 fixtures).
- Pre-match odds are normally published only days before kickoff. **Proposed execution: about 3–6 Dec 2026, with the second odds pass about 24–48 h before kickoff.**
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
  - That is about 7 × 2 × 8 ≈ **110 requests in a European week** at most, about 15 a day, or **0.2% of 7,500**.
  - Weeks without European fixtures cost 0.
- **Knockout rounds** (8 ties per leg) need 1 odds page each.
- **The existing domestic sweep** (about 22 requests each) is unchanged.
- **Hosted refresh stays inactive until Phase 6 resumes.** In development, European data is refreshed manually under the existing request budget and caps.

## Appendix A. Screener and Portfolio Build functionality mapping (proposed)

Inventory taken from the code on 27 Nov 2026. "WC" means the Weekly Challenge universe and "AU" means All Upcoming.

| Existing functionality (location) | Proposed location in Portfolio Build | Universe | Change needed | Preserved? |
|---|---|---|---|---|
| Universe toggle `universe` (`app/app.py:387`) | Top of the shared filter bar | Both | Default logic kept (WC when a round is playable, else AU) | Yes |
| Market `market` (402) and builder `f-market` | One market control in the shared bar | Both | Merge; one default (1X2) | Yes (consolidated) |
| Leagues `leagues` (416) and builder `f-league` | One multi-select in the shared bar | Both (AU adds European competitions) | Merge on competition id | Yes (consolidated) |
| Date range `dates` (434) and builder `f-date` (single day) | Date range in the shared bar; the WC default covers the round window | Both | The builder's single day becomes a range (a range can still be one day) | Yes (consolidated) |
| Rank by `direction`: kickoff, model probability, edge, EV (446) | "Sort / rank" in the shared bar | Both (edge and EV only where a model exists) | Label model-dependent ranks "(Diski 9 model)" | Yes |
| Minimum model probability `threshold` (464) | "Advanced" collapsible | Both | Label "hides fixtures without a model"; default off | Yes |
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

**Cannot be preserved without extra complexity:** none identified. Two judgement calls are flagged for the owner, via OD-4:
- the builder's single-day date filter becomes a range;
- the WC universe keeps card rendering, not the AU table.

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

## Appendix C. Navigation and layout wireframes (structural; proposed)

**Desktop: Portfolio Build, Weekly Challenge universe**
```
┌───────────────────────────────────────────────────────────────────────────┐
│ DISKI 9   [Portfolio Build] [Match Lab] [My Challenge] [Leaderboards] [Learn]  Account │
├───────────────────────────────────────────────────────────────────────────┤
│ (•) Weekly Challenge  ( ) All Upcoming Fixtures     Round 48 · closes Fri 13:45 (frozen) │
│ Market [1X2 ▾]  Leagues [All ▾]  Dates [Sat–Sun]  Search [____]  Sort [Kickoff ▾]  ▸ Advanced │
│ Buckets [A Foundation][B Balanced][C Challenger]  ☐ Available only          │
├──────────────────────────────────────────────┬────────────────────────────┤
│ Fixture cards (10/page)                      │ Tracker  A 2/4 B 1/3 C 0/2 │
│  Arsenal v Spurs   Sat 18:30   [1][X][2]      │ Source [Market|D9|You]     │
│   Mkt 52% · D9 49% · You —   Match Lab →      │ picks… [remove]            │
│  …                                            │ [Clear]       [Review →]   │
│ ‹ 1 2 3 ›                                     │ Risk panel (collapsible)   │
└──────────────────────────────────────────────┴────────────────────────────┘
```

**Desktop: Portfolio Build, All Upcoming Fixtures** (no tracker; the table takes the full width)
```
│ ( ) Weekly Challenge  (•) All Upcoming Fixtures                              │
│ Market [BTTS ▾] Leagues [All + UCL + UEL ▾] Dates [next 14 d] Search Sort [Market prob ▾] ▸ Advanced │
│ Kickoff | League | Home | Away | Est. goals | Yes | No | Market / Edge        │
│ Tue 21:00 | UCL | Inter | PSG | — [Market only] | — | — | Mkt 61% / 39%  → │
```

**Match Lab tab**
```
│ ← Back to Portfolio Build      Fixture [ Search or choose ▾ grouped by competition/date ] │
│ Inter v PSG · UCL League Stage 6 · Tue 21:00     Source: Estimated from bookmaker odds (B) │
│ [Probabilities] [Your View] [Statistics] [How probabilities are calculated]  ← compact secondary tabs │
│  Content of the selected secondary tab only; details in expandable sections        │
```

**My Challenge** · secondary tabs `[Current] [History] [Rewards]`. **Leaderboards** · `[Weekly] [Championship]` (existing). **Learn** · a list of expandable topics.

**Mobile (390 px):** the primary tabs become a horizontally scrollable tab strip, with the active tab kept visible. The filter bar collapses to "Filters (3) ▾". In WC the tracker becomes a sticky bottom bar ("A 2/4 · B 1/3 · C 0/2 — Review"). Match Lab's secondary tabs scroll horizontally.
