# Phase 8 CP3A-R.1: architecture refinement and decision closure

*28 Nov 2026. Research and documentation only. Nothing is implemented. Supplements the CP3A-R reassessment ([`phase8_cp3ar_reassessment.md`](phase8_cp3ar_reassessment.md)) without repeating it.*

> **Closure (28 Nov 2026):** the owner approved D1, D6 and D7. §14 resolves the final technical clarifications and **governs where it differs** from §3–§12. Revised estimate: 72–99 h for CP3A-R and 103–143 h for remaining Phase 8.

**Evidence markers**
- **[S]** source code;
- **[R]** a research run in this checkpoint (§13);
- **[D]** a document already on record;
- **[A]** a judgement.

The product direction is settled (§1). This report answers how to deliver it.

## Contents

1. Recorded owner decisions
2. Corrections to the CP3A-R reassessment
3. Architecture R against Architecture L
4. Recommended architecture
5. Pricing, freshness and submission methodology
6. Sunday cutoff
7. Research fixture window
8. Homepage and navigation matrix
9. Historical compatibility, privacy and operations
10. Implementation checkpoints and acceptance criteria
11. Revised Phase 8 estimates
12. Outstanding owner decisions
13. Reproduction and evidence limits
14. Final technical clarifications (closure)

---

## 1. Recorded owner decisions (28 Nov 2026)

These are recorded in register row P8-CP3AR1 and record §15.16. They are approved requirements; implementation is not yet authorised.

**Weekly Challenge**
- Rolling Friday–Sunday participation over a Friday–Sunday competitive universe. No Monday fixtures in future rounds.
- Friday 08:00 SAST opening, as the starting assumption.
- Entry on Saturday and Sunday, subject to enough eligible fixtures and the final cutoff.
- 15-minute fixture buffer.
- Latest available eligible pricing.
- Dynamic A3 buckets from margin-adjusted market probabilities.
- Irrevocable final submission: one portfolio per participant per round, no withdrawal, replacement or resubmission. Drafts stay editable.
- Immutable submission-time analytical records, **including Your View**.
- No new per-entry operator refund or correction. Round-level invalidation, result corrections, finalisation and reopening are kept.

**Goal Model**
- 1.1 retained (`k_s` 12, `k_t` 96). The 18/90 configuration is rejected and item 7 is closed.

**User experience**
- Remove the Research only toggle, and the frozen/latest toggle for future rounds.
- An automatic experience.
- A **Home** tab.
- A two-card homepage: "Monday–Thursday: Learn & Research" and "Friday–Sunday: Apply & Compete". Side by side on desktop, stacked on small screens.
- Training Ground, My Challenge and Leaderboard available all week.
- European football stays research only.

**Privacy**
- Current-round competitors' selections and provisional performance stay private until the round has completed settlement and results are published.

---

## 2. Corrections to the CP3A-R reassessment

| # | Original statement | Correction |
|---|---|---|
| C1 | "Stale prices only become a problem if entry is extended" | **Wrong.** Under today's rule a Friday-evening entrant uses prices frozen at Friday 08:00. The trial recorded provider updates during Friday (20:55 UTC on 20 Nov) and later price moves [R]. Extending the window **increases the exposure**; it does not create the problem |
| C2 | "PSL fixtures are never challenge-eligible: no provider odds" | **Wrong.** The research-branch captures show PSL odds on 25 Nov (3 fixtures, 121 quotes) and 27 Nov (8 fixtures, 425 quotes). Replayed through the production strict consensus, **2 of 3 and 6 of 8** fixtures had all three markets eligible [R, §5.4]. The evidence shows PSL odds *can* qualify, not that they *reliably* do. PSL stays in `eligible_competitions` and is admitted per fixture by the same rules |
| C3 | "120 weeks a round could open" | These are **schedule-qualified** weeks: at least 15 fixtures and at least 3 leagues by schedule. They are not market-qualified rounds. The publication gate still requires actual eligible consensus and exact feasibility [S `structured.py:410`] |
| C4 | "No historical point-in-time odds exist locally: only 15–17 Nov" | Incomplete. The research branch holds a **49-capture trial**: EPL every 3 h from 15 to 21 Nov, PSL from 15 to 27 Nov (last capture `37b7ea7`). It now gives point-in-time eligibility and price-movement evidence (§5). It is **not** weekend-long coverage: no Sunday captures, one league at a time, a 3-hour cadence |
| C5 | "The proxy is pessimistic" | Unjustified. Fewer Foundation outcomes alone does not make the proxy pessimistic: feasibility depends on the whole distribution of buckets across distinct fixtures. The proxy is an **analytical stand-in with unknown bias**, not market eligibility |
| C6 | "The provider updates odds once a day" | Refined. EPL mid-week showed one update a day at about 03:30 UTC. Close to matchday the trial saw **several a day**: Thursday 3, Friday 4, Saturday 5 or more, including 05:02 and 09:02 [R]. This is one league over one week, not a provider guarantee |
| C7 | Option S: "no schema or methodology change", yet a migration was listed | Option S needed a **data-only** migration (a new `round_schedules` version row) with no schema change. It did change methodology (the fixture window). Not pursued |
| C8 | Privacy: competitors visible after the round locks | Superseded by the owner direction in §1 (private until settlement completes and results are published). See §9.2 |
| C9 | Sunday 12:00 SAST was proposed from the 10:00 and 15:00 results | Now assessed directly at 10:00, 12:00, 14:00 and 15:00 (§6) |

---

## 3. Architecture R against Architecture L

### 3.1 What the current implementation actually does [S]

**1. The odds store is a separate database.**
- Odds live in the **football store** (SQLite during Phase 6C: `config.py:40`, D-39). The competition data lives in PostgreSQL (`backend/db/settings.py:1-8`).
- The snapshot builder opens the football store, computes the strict consensus and writes the frozen rows into PostgreSQL (`prepare.py:278-314`, `roundsheet.py:214-337`, `snapshots.store_snapshot`).
- **No PostgreSQL transaction can include an odds read.**
- D-39a makes moving the football store to PostgreSQL **mandatory before public or production deployment**. It is planned outside Phase 8.
- After that move a same-database confirmation becomes possible under L. The reproducibility and consumer points below would still apply.

**2. The odds store cannot exactly reproduce a past pool.**
- Quotes are price episodes whose `last_seen_at`, `last_provider_updated_at` and `ended_at` are updated in place (`collect.py:98-139`).
- `bookmakers.eligible`, `is_exchange` and `affiliation_group` are mutable and unversioned (`schema.py:229-244`).
- For an episode spanning the evaluation time, the consensus uses the first provider timestamp (`consensus.py:135`).
- The CP3A-R.1 replay showed the practical effect (§5.4): recomputing an earlier time overstated staleness.
- **So the odds store is not an audit record of what was offered.** The persisted snapshot is.

**3. After confirmation, money paths read only the submission copies.**
- Settlement, scores, leaderboards, history, championships and achievements read `submission_selections`, `entry_settlements` and `score_sets` and never the snapshot (`settlement.py:214-339`, `leaderboards.py`, `championships.py`, `achievements.py`).
- Each selection already copies bucket, odds, market probability, model probability and bookmaker groups (`entries.py:316-329`).
- `submissions` carries config, calculation, model and rules versions and the engine `states` (app_0001:400-428).

**4. The snapshot is still read in about 15 places.** Notable ones:
- confirmation and draft or adoption validation against the offer pool (`entries.py:250-314`, `drafts.py:222-281`, `adoption.py:111-117`);
- the lock-time validity check, which joins `snapshot_offers` (`rounds.py:798-857`);
- results polling and correction guards, which use `snapshot_fixtures` kickoffs and membership (`results.py:90-186,313`, `corrections.py:115`);
- My Challenge and history names and evaluation (`persist.py:198-251`, `history_ui.py:550`);
- **the Match Lab, Your View and builder baseline** (`lab_context.py`, `integration.py`, `your_view._resolve`). The market-implied fit needs **every outcome** of 1X2 plus a goals market (`market_fit.py:328-355`). A submission stores one outcome per fixture (`UNIQUE(submission_id, fixture_id)`).

**5. Integrity constraints that matter**
- `submission_selections` has a foreign key to `snapshot_offers(snapshot_id, fixture_id, market, outcome)` (app_0001:454).
- `submissions` has a foreign key to `round_snapshots(round_id, id)` (:423).
- `round_snapshots.round_id` is UNIQUE (:312).
- Snapshot rows are refused once the round leaves draft (app_0003:57-73).
- All of these tables are insert-only (`forbid_change`, app_0001:698-773).

**6. Confirmation**
- Lock order: round `FOR SHARE`, then entry `FOR UPDATE`.
- Idempotency is checked against `inputs_hash`, which today includes the snapshot fingerprint.
- `clock_timestamp()` checks the deadline after the locks, at READ COMMITTED (`entries.py:194-298`).
- The draft's stored fingerprint is **never compared** at confirmation.

**7. The common deadline gates five things:** the insert trigger, the draft trigger, `_check_open`, `lock_round` and settlement rule V3 (`settle.py:247-302`). V3's verdicts are per round outcome (`selection_verdicts UNIQUE(round_id, fixture_id, market, outcome, revision)`).

### 3.2 The two architectures against this code

**Architecture R: immutable editions**
- After each successful weekend sweep, the existing builder writes a new snapshot (an "edition") for the round. It contains only the published fixture universe, with fixtures that have not started.
- Submissions reference the edition they were accepted against, using the existing foreign keys.

**Architecture L: latest pricing with immutable individual submissions**
- No snapshot after publication.
- At confirmation the server computes the current consensus from the football store and validates it.
- The selection rows store the accepted values plus a lightweight revision reference.

| Criterion | R | L |
|---|---|---|
| Participant experience | Prices up to one sweep old (≤ about 3 h). The builder, Match Lab and review read one coherent pool | Prices equally fresh (both read the same sweeps). The builder pool is recomputed from the football store per request or cache |
| Integrity | Database foreign keys tie every accepted selection to a stored offer row. The pool shown is the pool validated | No foreign key: the odds live in another database. Integrity rests on application code and copied values |
| Atomicity | Validation reads PostgreSQL edition rows inside the confirm transaction, alongside the locks | The odds read happens **outside** the PostgreSQL transaction (separate SQLite store). Safe only through a value-binding digest. Atomic in effect, not in the database |
| Reproducibility | Exact: the full pool at each edition is stored and fingerprinted. Disputes like "was this available on Saturday at 10:00?" can be answered | Accepted values only. The pool cannot be reconstructed: episodes are mutable, bookmaker flags unversioned, the replay caveat applies |
| Settlement and corrections | Unchanged paths. The lock re-check works as is (it joins on the submission's own `snapshot_id`). Kickoffs and membership come from snapshot fixtures | Lock re-check rewritten. The foreign key dropped. Results polling needs kickoffs copied per selection |
| Your View records | The frozen baseline exists per edition (estimated goals and full markets), so a submission can record its baseline and the fit is reproducible | Full-market probabilities or fit lambdas must be copied per selected fixture. Otherwise the market-implied baseline is lost |
| Schema | `round_snapshots`: edition number, `UNIQUE(round_id, edition)` instead of `UNIQUE(round_id)`. Snapshot guard allows editions while open. A submission Your View table (both) | Drop the selection→offer foreign key. Add per selection: kickoff, observation and as-of times, consensus digest, estimated goals or fit lambdas and identity, full-market probabilities. A submission Your View table (both) |
| Migration | One migration: constraint swap and guard update, with downgrade. Historical rows untouched | One migration: dropped foreign key, about 8 new columns, guard changes |
| Application | Change the about 6 "by round_id" snapshot lookups to "current edition" or "the submission's edition". The cache becomes keyed by snapshot id. Add an edition builder in the weekend refresh path | Replace every `RoundSnapshot` consumer before confirmation (builder, integration, Match Lab, drafts, adoption) with a live pool object. Rewrite confirmation, lock validity and results kickoff sourcing |
| Operations | One automatic edition write per successful sweep: about 15 per weekend, a few seconds each | No edition writes. Every confirmation and draft check reads the football store |
| Storage | About 500 offer rows per edition: about 7,500 per weekend, about 0.4 M rows a year (tens of MB) | Marginal: wider selection rows |
| Testing | The existing snapshot, lock and settlement tests mostly apply per edition. New: edition sequencing, current-edition resolution, stale pause | New cross-store confirmation tests, digest and race tests, lock rewrite, reproducibility limits. More existing tests change |
| Failure recovery | If a sweep or build fails, the last edition stays while fresh (§5.3), then entry pauses. Editions survive football-store loss | Behaviour depends on the live store at every confirmation; a store problem halts entry immediately |
| Maintainability | One concept, the snapshot, used everywhere, as today | Two concepts: a frozen snapshot for history and a live pool for current rounds |
| Effort (CP R2 equivalent, §10) | **24–32 h** | **30–40 h** (more consumers change; the cross-store design) |

### 3.3 Can L reuse the copied submission values?

- **Partly.**
  - Settlement and every post-confirmation path would work unchanged from the copies.
  - What L cannot avoid: replacing the pre-confirmation pool consumers, dropping a foreign key, copying several more fields per selection, and confirming across two databases.
- **The minimum extra evidence for L** would be, per selection:
  - kickoff at acceptance;
  - consensus as-of time and latest observation;
  - a consensus digest;
  - estimated goals or market-fit lambdas and input identity;
  - full-market probabilities.
- **The lightweight revision identifier L would need is, in practice, the fingerprint of the pool**: `build_live_snapshot` already produces it (`roundsheet.py:86-107`). Computing that pool each sweep and **not** persisting it saves only about 500 small rows per sweep. It gives up foreign keys, reproducibility and the unchanged settlement and lock paths.

## 4. Recommended architecture: R, implemented as "a snapshot per successful sweep"

**Recommendation: Architecture R.**
- L is not simpler in this codebase. The odds live in a separate store with mutable, unversioned evidence, and about 15 consumers are built on the persisted snapshot.
- R reuses the builder, the foreign keys, the lock check, settlement and the Your View baseline. It needs one constraint change.

### 4.1 The hybrid that falls out

R is **not** a separate "edition" system. It is the existing snapshot builder, run automatically:
1. **Publication is manual, as today.** Snapshot 1 (edition 1) fixes the round's fixture universe, rules and configuration.
2. **After each successful weekend sweep,** the scheduler rebuilds the snapshot for the published universe and stores it as the next edition. It reuses `build_live_snapshot` and `store_snapshot`, plus `restrict_competitions`. The edition:
   - adds no new fixtures and changes no rules;
   - drops fixtures that have started.
3. **One edition per successful sweep**, even when prices are unchanged.
   - This keeps freshness simple: the current edition's `snapshot_at` is the last confirmed retrieval.
   - Deduplication logic is avoided.
   - Unchanged prices never trigger re-review: the review digest uses values, not edition ids.
4. **The current edition** is the latest stored one. It is usable for submission while it meets §5.3; otherwise entry pauses.
5. **Submissions** reference their edition through the existing `snapshot_id` foreign keys. History, settlement and corrections read the submission's edition, or only the copies.

### 4.2 What this does not need

- no streaming;
- no participant-triggered provider requests;
- no new service;
- no automated publication of rounds;
- no future-dated activation framework;
- no moving the football store to PostgreSQL. That is still required before public or production deployment under D-39a, as separate work; R does not depend on it.

---

## 5. Pricing, freshness and submission methodology

### 5.1 Four separate times

| Time | What it is | Where recorded |
|---|---|---|
| Provider update | The provider's league- or fixture-level `update` stamp. Not a bookmaker price-change time | `odds_quotes.first/last_provider_updated_at` [S] |
| Our retrieval | When a sweep fetched and stored the price | `odds_fixture_observations.retrieved_at`, `odds_quotes.last_seen_at` [S] |
| Consensus | Computed **on read** from stored quotes (median per bookmaker group, margin-adjusted). It is not a scheduled batch | `fixture_consensus` [S `consensus.py:273`] |
| Competitive availability | The moment a page or a confirmation reads the consensus. Under L that is immediately after a retrieval is stored | read path |

### 5.2 Weekend refresh schedule (reusing the E.1b refresh job)

**Schedule [A]:** sweeps on Friday, Saturday and Sunday at **04:15, 07:15, 10:15, 13:15 and 16:15 UTC** (06:15–18:15 SAST).
- Each sweep covers only leagues that still have fixtures in the round. Sunday sweeps therefore shrink.
- The scheduled slot list gains an "open round" series (`refresh.slots` [S `refresh.py:106`]). The "refresh stops at publication" rule becomes "refresh stops at entry close" (`refresh.plan` [S :287]).

**Why every 3 hours, not hourly**
- On matchdays the trial saw provider updates several hours apart, so a 3-hour cadence keeps us within about 3 h of the provider during the day.
- Hourly polling roughly triples requests for little gain.
- No participant-triggered requests, no streaming, no new service.

**Requests [A]**
- About 22–24 requests per full sweep [D e1b §5].
- 5 sweeps × 3 days, tapering on Sunday: about **300–360 per weekend**, about 120 on the peak day. With results imports, about 165 on the peak day.
- That stays within the approved activation caps (450 per 24 h; 300 preparation) and is about 2% of the 7,500-a-day plan.

### 5.3 Freshness policy

**Rules for competitive submission**
- **Provider timestamp age ≤ 24 h:** existing rule, unchanged.
- **Quote observation age ≤ 6 h, new [A]:** the price must have been seen by one of our sweeps within 6 hours.
  - Today both ages share one 24 h limit (`ConsensusRules.max_quote_age` [S `consensus.py:49`]).
  - A separate `max_observation_age` for competitive use is a small, contained change.
  - With 3-hourly sweeps, one failed sweep is tolerated; two consecutive failures pause the affected fixtures.
- **At least 3 independent bookmaker groups and complete markets:** unchanged.

**Failure behaviour**
- Outcomes that fail these rules are not selectable, and a draft selection on them is flagged (§5.5).
- If too few eligible outcomes remain for a feasible portfolio, entry shows "Prices are being updated — entries are temporarily unavailable".
- Research pages keep showing the latest displayable data with their existing stale labels (`display_consensus` [S]).

**Publication gate (unchanged):** actual eligible consensus, at least 15 fixtures, at least 3 leagues and exact feasibility (D-28).

### 5.4 What the captured evidence shows

Replay of the 49 captures with the production collector and strict consensus, evaluated live after each capture [R]:

- **EPL (20 pre-kickoff fixtures, 15–21 Nov):**
  - all 20 fixtures had all three markets eligible at every capture;
  - 9 could fill a Foundation slot.
- **EPL price movement on the same 140 eligible outcomes:**

| Between | Median move | 90th percentile | Max | Outcomes > 2 pp | Bucket changes |
|---|---|---|---|---|---|
| Friday 06:14 and Friday 12:16 UTC | 0 | 0 | 0 | 0 | 0 |
| Friday 06:14 and Saturday 06:14 | 0.18 pp | 1.14 pp | 3.15 pp | 6 | **2** |
| Friday 06:14 and Saturday 12:14 | 0.15 pp | 1.69 pp | 4.6 pp | 13 | 0 |
| Tuesday and Friday | 0.16 pp | 0.82 pp | 2.07 pp | 1 | 0 |

- **PSL:**
  - 15–21 Nov: odds returned for no fixture.
  - 25 Nov: 3 fixtures; 2 fully eligible. Exclusions: too few sources; one market below the minimum groups.
  - 27 Nov: 8 fixtures; 6 fully eligible. Exclusion: stale provider update on 2 fixtures.
- **Replay caution:** evaluating an earlier time *after* replaying later captures overstates staleness. The episode-level store uses an episode's **first** provider timestamp when the episode spans the evaluation time [S `consensus.py:135`]. So **a past consensus cannot always be reconstructed exactly from the odds store.** This matters for §3.

**Limits:**
- one league per period, 3-hourly sampling, no Sunday captures;
- no Saturday-afternoon to Sunday-evening coverage;
- EPL Friday updates seen once.

**Evidence needed:** a full weekend of captured sweeps across all eligible leagues. Collect it in a separately authorised operational checkpoint, or passively once weekend sweeps run in the dev environment. No new provider trial now.

### 5.5 Drafts, review and confirmation

**Drafts**
- Selections are stored as (fixture, market, outcome), as today.
- They are never modified automatically.
- On every render the builder evaluates each selection against the current consensus and marks one of:
  - **OK**;
  - **Bucket changed** (now X);
  - **Not available** (stale, ineligible or out of band);
  - **Kicked off**.
- The tracker counts only OK selections. Review is blocked until the issues are resolved.

**Review token**
- Opening Review computes the nine selections' current accepted values: odds, market probability and bucket.
- It hands the client a **review digest**: a SHA-256 over those nine tuples. No server state is needed.

**Confirmation (one transaction, extending today's `confirm_entry`)**
1. Lock the round `FOR SHARE` and the entry `FOR UPDATE`. Idempotency key and `UNIQUE(round_id, user_id)`, as today.
2. Check the round is open and before entry close (`clock_timestamp()`), as today.
3. For each selection:
   - kickoff > now + 15 min;
   - *(superseded by §14.2–§14.3: validate against the current edition's stored offers and their stored observation and provider timestamps; confirmation never reads the football store)*;
   - require it in band.
4. Validate A3: exactly 4-3-2 and nine distinct fixtures.
5. Recompute the digest from the current values. If it differs from the reviewed digest, refuse with **"Prices changed for N of your picks — please review again"**, naming the picks. Only the participant's own nine selections count, so changes elsewhere never force a re-review.
6. Insert the submission and its selections with the accepted values (§3) and lock the entry. Commit.

**Edge cases**
- **A fixture kicks off between review and confirmation:** it fails step 3, with "This match has started; replace this pick".
- **A refresh concurrent with confirmation:** see §3.

---

## 6. Sunday cutoff

**Method [R]**
- Friday–Sunday SAST universe, 15-minute buffer, 120 schedule-qualified weeks (six odds leagues, August 2023 to November 2026).
- Proxy: point-in-time Goal Model 1.1 buckets with the production matching. **It is not market eligibility.**

| Sunday arrival (SAST) | Median fixtures left | 10th / 25th percentile | Weeks < 9 fixtures | Weeks proxy-assessable | Weeks proxy-feasible | Conditional (of assessable) | Of all 120 qualified |
|---|---|---|---|---|---|---|---|
| 10:00 | 19 | 14 / 17 | 4 | 108 | 94 | 87.0% | 78.3% |
| **12:00** | 19 | 14 / 17 | 4 | 108 | 94 | **87.0%** | **78.3%** |
| **14:00** | 17 | 13 / 15 | 4 | 108 | 91 | **84.3%** | **75.8%** |
| 15:00 | 14 | 10 / 11.75 | 6 | 106 | 80 | 75.5% | 66.7% |
| 16:00 (reference) | 11 | 8 / 9 | 20 | 92 | 61 | 66.3% | 50.8% |
| 18:00 (reference) | 6 | 4 / 4.75 | 108 | 10 | 4 | — | 3.3% |

**PSL scenario**
- Upper bound: every PSL fixture assumed to qualify.
- Schedule-qualified weeks rise from 120 to 122, and Sunday 14:00 conditional feasibility from 84.3% to 89.0%.
- The real gain lies between the two figures, because only some PSL fixtures qualify (§5.4).

**How to read the table**
- 10:00 and 12:00 are identical: no fixture in these leagues kicks off on Sunday between 08:15 and 10:15 UTC.
- The pool erodes slowly to 14:00, then sharply after 15:00, when the Sunday 13:00–14:00 UTC kickoffs pass.
- Real market feasibility could differ either way. The proxy has unknown bias (C5).

**Fixed cutoff or feasibility-determined close?** A feasibility-only close ("entries stay open while a valid portfolio can still be built") is technically possible, because the matching runs per request. It is not recommended:
- **Unpredictable:** the close time is unknown in advance, so the homepage cannot state it.
- **Lock and privacy timing depend on it:** the round's designation (5+ entries), privacy and championship membership are fixed when entries close.
- **Fragile:** by late Sunday the pool can flip between feasible and infeasible as prices refresh.
- **Thin:** the pool drops below 9 fixtures in most weeks after about 17:00 SAST anyway.

**Recommendation [A]: a fixed close at Sunday 14:00 SAST.**
- Entry continues only while a feasible portfolio exists before then. Otherwise the existing feasibility check shows "Not enough eligible matches remain this weekend".
- 14:00 adds Sunday lunchtime at a cost of about 3 points of proxy feasibility against 12:00.
- 15:00 costs about 12 points.
- One fixed rule, with no special Sunday rules, relaxed thresholds or partial portfolios.

**Time-zone methodology (applies to all rules)**
- Every participant-facing rule is defined in **SAST** (`Africa/Johannesburg`, UTC+2, no daylight saving): window Friday 00:00 to Monday 00:00 SAST, opening Friday 08:00 SAST, entry close Sunday 14:00 SAST.
- Stored times stay UTC.
- The schedule's `window_rule` already accepts a `tz` per boundary [S `rounds.py:271-286`], so the change is a new schedule version, not new code.
- Today's v3 window boundaries are UTC. No fixture in the stored leagues kicks off in the two-hour gaps [R].

---

## 7. Research fixture window

**Midweek coverage, Monday–Thursday SAST, 147 season weeks [R]**

| Approach | Median fixtures per week | Weeks with 0 | Weeks with < 10 |
|---|---|---|---|
| Domestic only (all eight leagues) | 12 | 34 | 68 |
| UEFA CL and EL main stage (schedule only) | 0 (present in 54 weeks) | 93 | 106 |
| **A** Monday–Thursday, domestic + UEFA | 16 | 34 | 58 |
| **B** rolling 7 days (from Monday 08:00) | 76 | 19 | 21 |
| **C** Monday–Thursday, falling back to the coming weekend when < 10 | 31 | 19 | 21 (fallback in 58 weeks) |

- **UEFA rows are schedule availability only.** European market-implied coverage needs live odds that are not stored historically.
- The European provider verification (7 Dec, separately approved) is the evidence step.
- The 19 weeks with no football in seven days are summer edges and the deepest gaps, the same under B and C.

**Assessment**
- **A** is often empty or thin, in 40% of weeks with fewer than 10 fixtures, even with UEFA. A strict window makes the Learn card look broken in breaks and quiet weeks.
- **C** matches B's coverage but needs switching logic and a threshold to explain.
- **B** is the simplest: one rule, always populated whenever football exists, no switching. It also fits the provider: odds appear about one round ahead [D].

**Recommendation [A]: Approach B, a rolling "next 7 days" research list** (domestic eight leagues, plus UEFA main stage after CP2B.2).
- No date picker and no mode toggle.
- During an open round the list includes weekend challenge fixtures in research form (analysis only).
- Selection happens only in the Apply & Compete builder, so there is one place to pick.
- The card name "Monday–Thursday: Learn & Research" describes the *emphasis of the week*. Both cards are visible and usable all week (§8), so the label needs no strict window.
- Ingestion and the cache keep their longer horizons (21 days).
- Research stays available after submission, after entries close, when no challenge exists and while the previous round is settling.

---

## 8. Homepage and navigation matrix

**Layout**
- Two cards, always visible: side by side at 768 px and wider, stacked on phones with Apply & Compete first on Friday–Sunday and Learn first otherwise.
- Tabs: **Home** · Training Ground · My Challenge · Leaderboard · (Match Lab opened from lists).
- The ML-01 gates, Match Lab restoration and the persistence safeguards from CP3A are kept.

```
┌ MONDAY–THURSDAY · Learn & Research ┐ ┌ FRIDAY–SUNDAY · Apply & Compete ┐
│ status line                         │ │ 100 Credits. 9 Picks. 1 Challenge.│
│ [primary/secondary action]          │ │ status line                       │
│ Training Ground ▸                   │ │ [primary/secondary action]        │
└─────────────────────────────────────┘ └───────────────────────────────────┘
```

| State | Learn & Research card | Apply & Compete card |
|---|---|---|
| Monday–Thursday | "N matches in the next 7 days" · **Analyse matches** | "Next challenge opens Friday 08:00" · How to play |
| Friday before publication | "N matches in the next 7 days" · **Analyse matches** | "This weekend's challenge opens at 08:00" · How to play |
| Friday, open | "Research any match" · Analyse matches | "Open until Sunday 14:00 — N matches available" · **Build your portfolio** (or **Continue your portfolio** if a draft exists) |
| Saturday, open | as Friday | "Open until Sunday 14:00 — N matches still available" · **Build your portfolio** |
| Sunday, open | as Friday | "Closes today at 14:00 — N matches still available" · **Build your portfolio** |
| Already submitted | as Friday | "Your portfolio is in" · **View my portfolio** (My Challenge). No submit action |
| Too few eligible fixtures remain | **Analyse matches** | "Not enough eligible matches remain for a full portfolio this weekend" · View leaderboard |
| Stale or unavailable pricing | **Analyse matches** (latest data, labelled) | "Prices are being updated — entries are temporarily unavailable" · none |
| Entries closed | **Analyse matches** | "Entries closed — results after settlement" · My Challenge (if entered) |
| No challenge this weekend | **Analyse matches** | "No challenge this weekend" (neutral; no assumed reason) · How to play |
| Previous round awaiting settlement | unchanged | the current week's state; settlement progress shows in My Challenge |

**Rules**
- The primary action always matches the participant's eligibility.
- No disabled button without a reason line.
- No inferred "international break" wording.

---

## 9. Historical compatibility, privacy and operations

### 9.1 Methodology transition (simple, using what exists)

- **New schedule version (v4):**
  - window Friday 00:00 to Monday 00:00 SAST;
  - opening Friday 08:00 SAST;
  - entry close Sunday 14:00 SAST, held in the schedule's `window_rule` and `publish_rule` JSON, so no schema change;
  - a new `rules_version` (rolling entry with editions).
  - It is activated with the existing `active_from` versioning and contiguity guards [S app_0008] from a chosen Friday.
- **Behaviour switches on the round's `rules_version`,** the same pattern as the version-aware A3 change. v1–v3 rounds keep the common deadline, a single snapshot, replace and withdraw, and their original prices and buckets.
- **No future-dated activation or cancellation framework.**
- **`config_version` stays `a3-432-v1`:** buckets, sizes, credits and scoring are unchanged.

### 9.2 Locking, settlement, corrections, privacy

- **`rounds.deadline_at` becomes the entry close** for v4 rounds. It is still set once at publication and enforced by the existing insert and draft triggers.
- **New per-selection kickoff guard (service and database).**
  - An insert trigger on `submission_selections` requires the selection's fixture, **in its own edition's** `snapshot_fixtures`, to kick off more than 15 minutes after `transaction_timestamp()`.
  - **R makes this enforceable in the database:** the edition carries kickoffs.
- **Entries become final at confirmation.**
  - No withdraw or replace paths for v4 rounds.
  - `lock_round` still runs at entry close to fix the designation (5+ entries), names and privacy.
  - Its validity join works unchanged because it uses each submission's `snapshot_id`.
- **Settlement rule V3 needs a per-entry reference.**
  - Today a leg is void if its fixture started before the round deadline.
  - Under rolling entry the reference must be **that entry's `submitted_at`**: a fixture that kicked off on Friday is valid for a Thursday-night entrant and impossible for a Saturday entrant.
  - Proposal: keep the per-outcome verdicts (result, postponement) and add an **entry-level V3 check** in settlement (`settlement.compute`): a leg is void if the observed actual kickoff precedes that submission's `submitted_at`.
  - Contained, but it touches settlement, so it needs focused property tests. About 4–6 h.
- **Privacy (owner direction).**
  - No service exposes other participants' selections at any stage [S `leaderboards.py:15-16`].
  - Today, locked and settling rounds show **provisional** gross and pending counts on the board (`leaderboards.py:153-226`).
  - To keep provisional competitive performance private, the round board for a v4 round shows only the participant's own provisional row until a `score_sets` row is published (the existing final marker, app_0007).
  - A filter, not a permissions system: about 2–3 h.
  - Earlier published results and championships stay visible.
- **Corrections, finalisation, reopening and invalidation are unchanged.** They work per round and read the copies. Correction guards use the snapshot's fixture membership; the universe is the same in every edition.
- **Practice, Beta and Official isolation, authentication and participant isolation are unchanged.**

### 9.3 Your View at submission (owner requirement)

**Today**
- A Your View row is keyed by (user, fixture, context kind, snapshot). Its validity stamp ties the adjustment to the model version and rounded estimated goals, or to the market-fit input identity (`your_view.py:253-258`, `market_fit.py:150-178`).
- With editions or latest pricing, **every refresh would change the stamp** (estimated goals move after each match; fit inputs move with prices), and adjustments would become "incompatible".
- Unadjusted fallback is distinguishable in storage (no row, or an all-zero row) but not in computed outputs (`integration.py:543-546`).

**Proposal [A]**
- **Identity for v4 rounds:** Your View is keyed by (user, fixture, round), not by edition.
  - The adjustment stays a delta on the current baseline.
  - When the baseline moves, the adjustment carries forward with a "baseline updated" notice instead of being discarded.
  - Historical round-context rows and their stamps are untouched.
- **New insert-only table `submission_views`,** one row per submission position, written in the confirm transaction:
  - `baseline_source`: goal_model, market_implied or none;
  - baseline estimated goals and their identity: the model version plus the edition's `snapshot_fixtures`, or the market-fit `input_id`, version and lambdas;
  - `adjusted` (true only when a non-zero participant adjustment exists);
  - the adjustment state (the stored deltas);
  - the resulting Your View probability for the selected outcome, or null when `adjusted` is false;
  - the fallback probability actually used for evaluation, and its source.
- **Already recorded elsewhere:**
  - accepted odds, market probability, bucket, groups and model probability, in `submission_selections`;
  - observation time and edition time, through the `snapshot_offers` and `round_snapshots` joins;
  - submission time and versions, in `submissions`.
- **Fallback is never labelled as a prediction:** `adjusted = false` rows store no Your View probability.
- **No analytics interface is added** (Personal Performance Analytics stays deferred).

### 9.4 Operations

| Item | Assessment |
|---|---|
| Publication | **Manual, unchanged** (edition 1). Editions 2+ are automatic, but only reprice the published universe under the published rules. This is a new automated behaviour and needs owner approval (§12) |
| Weekend refresh | 3-hourly, Friday to Sunday 06:15–18:15 SAST, only leagues with remaining fixtures (§5.2) |
| Provider requests | About 300–360 per weekend; peak day about 120 (+45 results). Within the approved caps (450 per 24 h; preparation 300) and about 2% of the 7,500-a-day plan |
| Scheduler workload | One edition build per sweep. The builder already runs at publication within the 1 h snapshot-age limit. Expect seconds per build; to be measured in implementation |
| Freshness | Provider age ≤ 24 h (unchanged), observation ≤ 6 h for competitive use (new), groups and markets unchanged (§5.3) |
| Failure | A failed sweep or build means no new edition. The previous edition stays usable until it breaches §5.3, then entry pauses with a message. Research continues. Monitoring adds a "current edition age" line to the existing readiness and ops checks |
| Storage | About 500 offer rows per edition, about 15 editions per weekend: about 0.4 M rows a year, tens of MB. Small next to existing tables. `submission_views` adds 9 rows per submission |
| Backup and recovery | The existing PostgreSQL backups cover editions. Restore needs no new step. Editions survive loss of the football store |
| Incremental cost | **$0** within the existing API-Football Pro plan and infrastructure. **Depends on renewing Pro before 14 Dec 2026** (no automatic renewal; not purchased here) |
| European verification (7 Dec) | Unchanged and separately controlled |

---

## 10. Implementation checkpoints and acceptance criteria

**Shared principles**
- Each checkpoint uses focused tests.
- The full suite and full CI run at **R5** (integration gate), plus one intermediate full CI after R2 because it carries the migration.
- The accepted baseline (CI #179, 2514 tests) must stay green, except tests whose requirement legitimately changes. Those are listed per checkpoint and need owner approval.

| CP | Scope | Depends on | Principal components | Schema / migration | Historical obligations | Focused tests | Acceptance criteria | Active h |
|---|---|---|---|---|---|---|---|---|
| **R1 Rolling lifecycle** | Schedule v4 (SAST Friday–Sunday window, Sunday 14:00 close, new `rules_version`). `deadline_at` = entry close. Per-selection kickoff check (service and trigger). Final at confirmation: no withdraw or replace for v4. `lock_round` at close. Entry-level V3. Provisional board limited to self until published | approval of §12 | `rounds.py`, `schedules.py`, `entries.py`, `settle.py` / `settlement.py`, `leaderboards.py`, `persist.py`, `callbacks.py`, `pages.py` | Data row (schedule v4). Trigger on `submission_selections` (kickoff guard) | v1–v3 keep the common deadline, replace, withdraw, round V3 and the board | Schedule resolution and contiguity. Confirmation before and after the kickoff buffer. Irrevocability and concurrency (two devices, idempotency). V3 property tests (entry-level vs round-level). Privacy board states. The existing withdraw and replace tests stay for v3 rounds | A v4 round accepts entries Friday 08:00 to Sunday 14:00 SAST. No selection within 15 min of kickoff is accepted. A confirmed entry cannot change. v3 behaviour unchanged | 14–20 |
| **R2 Price editions and freshness** | Edition migration. Edition build after each successful weekend sweep (refresh slots and plan to entry close; restrict to the published universe; drop started fixtures). Current-edition resolution. Snapshot cache by id. Observation-age rule (≤ 6 h). Stale pause. Review digest and re-review. Draft flags (server validation plus the client `reconcile`, reused). Adoption re-validates instead of refusing on a fingerprint mismatch. Ops line | R1 | `snapshots.py`, `roundsheet.py`, `refresh.py`, `prepare.py`, `entries.py`, `drafts.py`, `adoption.py`, `consensus.py` (observation age), `state.py`, ops checks | `round_snapshots`: edition column, `UNIQUE(round_id, edition)`; guard allows editions while open; downgrade | Single-snapshot rounds load unchanged (edition 1). Fingerprints re-verified | Migration (fresh, upgrade, downgrade, refusal). Edition sequencing. Concurrent edition write and confirmation (the lock order is unchanged; the confirmation reads the current edition under `FOR SHARE`). Digest mismatch causes re-review. Unrelated price changes don't. Stale pause and recovery. Draft flags never mutate a draft | Prices refresh into editions. A participant never confirms values different from those reviewed. Stale prices pause entry safely. Full CI green | 24–32 |
| **R3 Analytical records and Match Lab** | Your View keyed by round for v4, with carry-forward and notice. `submission_views` written at confirmation. The frozen/latest toggle removed for v4 (the challenge context resolves to the current edition; research stays live). ML-01 gates kept | R2 | `your_view.py`, `lab_context.py`, `lab.py`, `app.py`, `integration.py`, `entries.py` | `submission_views` table (insert-only); Your View context key for v4 | Historical round-context rows and stamps intact; the frozen view for old rounds kept | Adjusted vs fallback recorded correctly. Records match what was reviewed. ML-01 regression tests unchanged. The CP3A-4/4B toggle tests retired for v4 (replaced), kept where they test history | Each submission stores baseline, adjustment and resulting probability; fallback never appears as a prediction | 10–14 |
| **R4 Experience** | Two-card Home. Home tab. Research only removed. Rolling 7-day research list without the date picker. §8 state matrix and wording | R1–R3 (states) | `home.py`, `callbacks.py`, `app.py`, `pages.py` | none | Locked and historical views unchanged | State matrix unit tests. CP3A-2 Research-only tests replaced. Browser at 390, 768 and 1280 px | Every §8 state renders correctly; no toggles; research is available in every state | 10–14 |
| **R5 Integration and acceptance** | Update the CP3A-5 integrated test to a simulated weekend (publication, editions on Saturday and Sunday, re-review, stale pause, close, lock, settle, privacy), screenshots, full suite, CI, docs | R1–R4 | tests, docs | — | Historical regression suite unchanged | Full local suite and CI | CI green; owner acceptance | 8–10 |
| **Total** | | | | | | | | **66–90** (revised to **72–99**, §14.10) |

**Reuse**
- Builder, consensus, implied probabilities, matching, feasibility, A3 configuration, snapshot storage and fingerprint, lock validity join, settlement and scoring, championships, achievements, results import, the ML-01 gates, draft keys and client `reconcile`, refresh job and budget ledger.

**Legitimate test changes** (requirements change, needs owner approval)
- the v4 behaviour of withdraw and replace;
- the frozen/latest toggle;
- Research only;
- the homepage card;
- the common-deadline assertions for v4 rounds.

**Kept unchanged** (historical regression): every test exercising v1–v3 rounds, A3 and Goal Model 1.1.

**Against the CP3A-R Option R estimate (55–75 h):** now **66–90 h**, about +11–15 h. Main reasons:
- Your View preservation is now required (R3: about +6–8 h). It was deferred before.
- Entry-level V3 was found during inspection (+4–6 h).
- Privacy until published scores (+2–3 h).
- A separate observation-age freshness rule (+1–2 h).
- Partly offset by not needing the Option R "draft and adoption" redesign: the client `reconcile` exists.

Nothing was cut to make R look cheaper. L's equivalent of R2 is estimated at 30–40 h.

---

## 11. Revised Phase 8 estimates

| Item | Active h | Notes |
|---|---|---|
| CP3A-R reassessment | about 6–7 (done) | `539b4de` |
| CP3A-R.1 refinement | about 5–6 (done) | this report |
| **CP3A-R implementation (R1–R5)** | **72–99** (was 66–90; §14.10) | §10 |
| CP3B | 14–20 | Education must explain latest pricing, editions, re-review and rolling entry; the toggle explanations are removed |
| CP2B.2 | 6–9 | European analysis in the rolling research list and the Learn card |
| CP4 | 11–15 | Revised lifecycle and edition journeys |
| **Remaining after CP3A-R.1** | **103–143** (was 97–134) | Planning estimates, not commitments |

**Automated test time:** about 43 min per full local suite and about 35 min per CI run, with 3–5 runs expected across R2 and R5. It is not included in active hours.

**External dependencies**
- API-Football Pro renewal by 14 Dec 2026.
- The European verification on 7 Dec (CP2B.2).
- Owner design approval of the §8 wording.
- Moving the football store to PostgreSQL before public or production deployment (D-39a; separate, not in Phase 8; R does not depend on it).

---

## 12. Outstanding owner decisions

**Must be approved together**

| # | Decision | Recommendation | Trade-off |
|---|---|---|---|
| **D1** | Architecture | **R: a snapshot (edition) per successful weekend sweep** | Stronger integrity and reproducibility and less application change in this codebase. Costs about 0.4 M small rows a year. L would avoid the rows but needs a cross-database confirmation and a parallel live-pool concept |
| **D2** | Automatic editions after manual publication | **Approve.** Editions only reprice the published universe and never add fixtures or change rules | A new automated behaviour. The alternative (manual repricing) is not operable at weekends |
| **D3** | Freshness for competitive use | **Provider ≤ 24 h (unchanged), plus our observation ≤ 6 h** | Pauses entry after two missed sweeps. A longer limit would accept staler prices |
| **D4** | Weekend refresh | **3-hourly, Friday–Sunday 06:15–18:15 SAST, leagues with remaining fixtures** | Hourly roughly triples requests for a small freshness gain. 6-hourly risks stale pauses |
| **D5** | Review and confirmation | **A value digest over the participant's nine selections; re-review only if one of them changed; kickoff and A3 re-validated at confirmation** | Simple and stateless. A participant may occasionally be asked to re-review after a price update |

**Can be approved independently**

| # | Decision | Recommendation | Trade-off |
|---|---|---|---|
| **D6** | Sunday close | **Sunday 14:00 SAST, fixed**, with the feasibility message before it | 12:00 is about 3 points more feasible by the proxy; 15:00 about 9 points less. A feasibility-only close is unpredictable |
| **D7** | Research window | **Rolling next 7 days**, no date picker | Strict Monday–Thursday is thin in about 40% of weeks; the fallback approach adds switching logic |
| **D8** | Your View for v4 rounds | **Keyed by round; adjustments carry forward with a "baseline updated" notice; `submission_views` records baseline, adjustment, result, adjusted flag** | Carrying a delta to a moved baseline is a judgement. The alternative (invalidate on each refresh) discards participant work every few hours |
| **D9** | Settlement rule V3 under rolling entry | **Entry-level reference = submission time** | Required for correctness: a round-level reference would void valid legs |
| **D10** | Privacy | **Round board shows only the participant's own provisional row until the final score set is published** | Matches the owner direction; a small filter |
| **D11** | PSL | **Stays in `eligible_competitions`; each fixture admitted only by the same strict consensus.** Coverage monitored, not assumed | Some weekends add PSL fixtures, others none. No special rules |
| **D12** | Transition | **Schedule v4 plus a new `rules_version`, active from the first Friday after R5 acceptance**; v1–v3 rounds unchanged | Uses existing versioning; no activation framework |
| **D13** | Homepage wording (§8) | **Approve the matrix as the basis**; final copy at R4 | — |
| **D14** | Legitimate test replacements (§10) | **Approve** the listed replacements; historical tests stay | — |

**Evidence gaps (none blocks the recommendation)**
1. Weekend-long, multi-league point-in-time odds, including Sunday, to confirm the refresh cadence and the observation-age limit. Collect in a separately authorised operational checkpoint, or passively once weekend sweeps run in development.
2. Real market feasibility for late Sunday arrivals (the proxy has unknown bias).
3. PSL eligibility reliability over several weekends.
4. European market-implied coverage (7 Dec verification).
5. Edition build time and storage on the hosted infrastructure (measure in R2).

---

## 13. Reproduction and evidence limits

**Commands**

The odds captures come from the research branch, which is **not merged**:

```bash
git archive origin/claude/gifted-newton-h6o5hk monitoring/odds_trial | tar -x -C "$DIR"
```

```bash
uv run python tools/research/cp3ar/odds_trial_replay.py "$DIR/monitoring/odds_trial"
```

```bash
uv run python tools/research/cp3ar/sunday_and_midweek.py
```

Outputs are in `docs/research/phase8_cp3ar/` (`odds_trial_replay.json`, `sunday_and_midweek.json`).

**What was not done:** no provider requests, no protected databases, no new dependencies, no production or test changes, no application CI run.

**Evidence limits**
- The proxy has unknown bias.
- Market evidence covers one EPL week and two PSL captures.
- There is no Sunday odds evidence.
- European coverage is schedule only.

---

## 14. Final technical clarifications (CP3A-R.1 closure, 28 Nov 2026)

*Owner approvals: D1 (Architecture R), D6 (Sunday 14:00 SAST) and D7 (rolling 7-day research). D2–D5 and D8–D14 are supported subject to the clarifications below.*

**This section governs where it differs from §3–§12.**

### 14.1 Overnight freshness: refresh throughout the entry window

**Schedule**
- Competitive refresh sweeps run **every 3 hours for the whole entry window, overnight included.**
- First slot Friday 06:15 SAST, which is also the existing pre-publication sweep. Last slot Sunday 12:15 SAST.
- The owner's illustrative slots are adopted:

| Day | Slots (SAST) | Count |
|---|---|---|
| Friday | 06:15, 09:15, 12:15, 15:15, 18:15, 21:15 | 6 |
| Saturday | 00:15, 03:15, 06:15, 09:15, 12:15, 15:15, 18:15, 21:15 | 8 |
| Sunday | 00:15, 03:15, 06:15, 09:15, 12:15 | 5 |

- **Stop at entry close:** no competitive sweep or edition after Sunday 14:00 SAST (`refresh.plan`: "refresh stops at entry close").
- Results imports and the research list continue under their own schedules.
- **Infrastructure:** the existing slot generator (`refresh.slots`) gains the "open round" series at the configured interval. Same job, ledger and pacing.
- **Overnight value:** EPL provider updates were observed at about 02:30 and 05:30 SAST (00:30 and 03:30 UTC) [R], so overnight sweeps also pick up genuine changes.

**Requests**
- Using the documented E.1b figure of about 22 requests per full sweep, with Sunday sweeps tapering as leagues finish:
  - 19 sweeps ≈ **about 380–420 per weekend**;
  - about **520** in the worst case (+25% retries).
- **Peak rolling 24 h:** 8 sweeps (about 176) + 25% retries ≈ **220 preparation**, plus results imports (peak about 45) ≈ **265 in total**.

**Fit with existing caps (unchanged, not increased)**

| Cap | Limit | Peak use |
|---|---|---|
| Preparation (nonessential) per 24 h | 300 | about 220; about 280 even at the E.1b high-cost factor (×28/22, +25%) |
| Total per 24 h (preparation + 150 results reserve) | 450 | about 265 |
| Per tick | 20 | a 22-request sweep spans two ticks, as today |
| Provider plan | 7,500 a day | about 3.5% |

- The budget ledger (`locking.reserve` / `allowance`) is unchanged.
- **High-cost caveat:** if a weekend's odds paging exceeds the E.1b high-cost factor, the preparation cap (300) is the binding limit. The ledger defers the excess rather than overspending. Prices then age, and §14.3 decides eligibility. Observed in R5 and the operational validation.

**Failure tolerance**
- With a 6-hour observation limit and a 3-hour cadence, **one failed sweep is absorbed without effect.**
- Two consecutive failures make affected outcomes ineligible about 6 hours after their last genuine observation (§14.3). Entry pauses only if a feasible portfolio no longer exists.

**Cost:** no incremental cost within the API-Football Pro plan. Renewal by 14 Dec 2026 remains the dependency.

**Freshness limits are retained:** provider timestamp ≤ 24 h and our observation ≤ 6 h.

### 14.2 Confirmation against one immutable edition (corrects §5.5 step 3)

**Confirmation never reads the SQLite football store.**
- Editions are the only competitive price source after publication.
- The builder computes consensus once, when writing an edition. Confirmation validates against **that edition's PostgreSQL rows**.

**Edition writer** (scheduler, after a successful sweep)
- Builds the snapshot from the football store **outside** any lock. This is the slow part.
- Then, in one short PostgreSQL transaction:
  1. lock the round row `FOR NO KEY UPDATE` (the lock `lock_round` already uses);
  2. check the round is open, before entry close, and is the same round and universe;
  3. insert `round_snapshots` (next edition number), `snapshot_fixtures` and `snapshot_offers`;
  4. commit.

**Confirmation** (extends `confirm_entry`, same lock order as today)
1. Round `FOR SHARE`. This blocks while an edition insert holds `FOR NO KEY UPDATE`, and vice versa.
2. Entry `FOR UPDATE`.
3. **Resolve the current edition** inside the transaction: the highest edition number for the round, read **after** the share lock.
   - Under READ COMMITTED each statement sees committed data. A writer cannot commit a new edition while this transaction holds the share lock.
   - **The edition is stable for the rest of the transaction.**
4. Idempotency key lookup and `UNIQUE(round_id, user_id)`, as today.
5. Validate the nine selections against **that edition's** offers: present, eligible and in band, plus the §14.3 freshness check at the actual time.
6. Validate A3 (4-3-2, nine distinct fixtures) and compare the review fingerprint (§14.4).
7. Insert `submissions` (`snapshot_id` = current edition), `submission_selections` (foreign key to that edition's `snapshot_offers`, **unchanged**) and `submission_views` (§14.5). Mark the entry final. Commit.

**Properties**
- A new edition published mid-confirmation is either:
  - fully committed before step 1, so the confirmation sees it; or
  - waiting until the confirmation commits, so the confirmation used the previous edition consistently.
- The **existing foreign keys** guarantee every accepted value exists in a stored edition.
- **One final submission:** `UNIQUE(round_id, user_id)` on entries plus the entry lock. For v4, a second confirmation for an entry that already holds a submission is refused (no replace path).
- **Idempotency:** a retried request with the same key and the same inputs hash returns the existing result.
  - The inputs hash for v4 is computed over the selections and the review fingerprint, **not** the edition fingerprint.
  - So a retry across an edition change with unchanged values is still idempotent.
- **Lock duration:** the edition writer holds the round lock only for the insert (milliseconds to about a second for about 500 rows). Confirmations wait at most that long, within the existing `lock_timeout`.

### 14.3 Genuine freshness

| Time | Source | Use |
|---|---|---|
| Edition creation | `round_snapshots.as_of` | Ordering and audit only. **Never used for freshness** |
| Quote observation | Our retrieval that saw the price: consensus `_observed_at`, from `odds_fixture_observations` / `last_seen_at` | Observation age ≤ 6 h |
| Provider update | `first/last_provider_updated_at` on the contributing quotes | Provider age ≤ 24 h |
| Successful retrieval | `odds_fixture_observations.retrieved_at` (per fixture, only when that fixture's data was stored) | Feeds the observation time. A league or fixture not retrieved in a sweep gets **no** new observation |

**Per-offer evidence stored in each edition**
- **`oldest_observation_at`**: the oldest observation among the quotes that formed the consensus. A new nullable column; historical rows stay null and are never evaluated.
- **`provider_updated_at`**: the oldest contributing provider timestamp. The column exists but is not populated today [S `snapshots.py:86-100`].
- The existing `latest_observation_at` is kept for display.
- Using the **oldest** contributing values means an edition built after a partial sweep cannot make an un-refreshed price look fresh.

**At build:** the builder applies the competitive rules (observation ≤ 6 h, provider ≤ 24 h, at least 3 groups, complete market) at build time. Stale outcomes and incomplete markets are not offered, as today (`challenge_eligible`, `implied`).

**At confirmation, using the actual clock (§14.7):** an offer is usable only if
- `now − oldest_observation_at ≤ 6 h`, and
- `now − provider_updated_at ≤ 24 h`.

**As time passes:** outcomes in the current edition **age out individually**, even if no new edition is built.

**Failures**

| Failure | Behaviour |
|---|---|
| Failed or partial sweep | Leagues not retrieved get no new observations. A new edition may still be built from what was retrieved; outcomes whose evidence is too old are excluded |
| Failed edition build | The previous edition remains current. Its offers stay usable only while their own timestamps pass |
| No feasible portfolio from usable offers | The card shows "Prices are being updated — entries are temporarily unavailable". Drafts are untouched |
| Throughout | Research continues on the latest displayable data with stale labels |

### 14.4 Review fingerprint

**Item fingerprint** for each of the participant's nine selections: a canonical JSON array with fixed field order and fixed text formats:

| Field | Format |
|---|---|
| fixture_id, market, outcome | as stored |
| accepted odds | 2-decimal string (as stored, `numeric(8,2)`) |
| market probability | percentage string with 1 decimal, the precision shown in Review |
| bucket | A, B or C |
| baseline source | `goal_model`, `market_implied` or `none` |
| baseline identity | Goal Model: model version and estimated goals as 2-decimal strings (the existing stamp format). Market-implied: fit version, `input_id` and lambdas as 2-decimal strings |
| Your View | `adjusted` true or false; the stored adjustment deltas exactly as stored; the resulting probability as a 1-decimal percentage string (only when adjusted) |
| fallback | source and its probability as a 1-decimal percentage string (when not adjusted) |

**Review fingerprint** = SHA-256 over the nine item fingerprints, ordered by position.

**Comparison at confirmation**
- The server recomputes the item fingerprints from the current edition and the participant's current Your View state.
- If the combined value differs, it refuses and **names the positions whose item fingerprint changed** ("Prices or analysis changed for 2 of your picks — please review again").
- Equal strings mean equal displayed information. That is the whole comparison: **no tolerance framework.** A sub-display change that does not move a displayed value or bucket does not trigger re-review.
- **Not included:** the edition number and data on any other fixture. An edition change alone never triggers re-review.
- **Drafts are never modified:** re-review only re-presents the same selections with their new values and flags (OK, bucket changed, not available, kicked off).

### 14.5 Your View identity and carry-forward rules (v4 rounds)

**Storage**
- The stored adjustment (deltas) is keyed by (user, fixture, round).
- It is **never rewritten automatically.**
- Carry-forward is a **read-time decision**, so the ML-01 rule (no write to another match, context or earlier value) is unaffected.

| Change since the participant last saved the adjustment | Treatment |
|---|---|
| Same source, same model or fit version, estimated goals each within ±0.20 of the saved baseline | **Carry forward** with a "Baseline updated" notice showing old and new baseline |
| Same source and version, a change > 0.20 in either estimated-goals value | **Needs review:** shown, but not counted in Review until the participant confirms it ("Keep my adjustment") or edits it |
| Source changed (Goal Model ↔ market-implied) | **Not applied:** "Your earlier view was based on a different model". The stored row is kept; the fallback is shown as not adjusted |
| Model or methodology version changed | **Not applied** (as today: historical identity rules) |
| Baseline unavailable | **Not applied;** Your View unavailable; fallback |

**Why 0.20 goals:** a single fixed judgement. Within a weekend the Goal Model baseline barely moves, because the teams in an upcoming fixture have not played since. Larger moves come from market-implied baselines after a real price change.

**At confirmation, `submission_views` records**
- the exact baseline (source, identity, estimated goals);
- the adjustment deltas;
- `adjusted`;
- the resulting probability (only when adjusted);
- the fallback source and value when not adjusted.

**Fallback is never stored or shown as a participant prediction.** Historical round-context rows and stamps are unchanged.

### 14.6 The published universe

**Edition 1 (the publication snapshot) is the authoritative universe.** A trigger refuses any later edition fixture that is not in edition 1. No separate subsystem.

| Reads | Consumers |
|---|---|
| **Edition 1 (universe)** | Results polling list and timing; synthetic-result and correction fixture-membership guards; operator fixture report; ops monitoring; fixture names and metadata for history |
| **Current edition** | Builder; Match Lab challenge context; draft flags; adoption validation; Review; confirmation |
| **The submission's own edition** | Lock-time validity (the existing join on `ss.snapshot_id`); My Challenge and history outcome text and evaluation; `submission_views` baseline; the per-selection kickoff guard |
| **Copies only (unchanged)** | Settlement, scores, leaderboards, championships, achievements |

- **Code change:** the about 6 "by round_id `scalar_one`" lookups become `universe(round)`, `current_edition(round)` or `load_snapshot(snapshot_id)`. The snapshot cache is keyed by snapshot id.
- Omitting started or ineligible fixtures from later editions affects nothing above except what new entrants can pick.

### 14.7 Deadline enforcement and time references

**The authoritative submission time is `clock_timestamp()` at the submission row insert.**
- A v4 trigger sets `submitted_at := clock_timestamp()`. Today it uses `transaction_timestamp()`, the transaction start.
- Every v4 database check uses that value:
  - **round:** `submitted_at < rounds.deadline_at` (Sunday 14:00 SAST, set once at publication);
  - **fixture:** a trigger on each `submission_selections` row requires the fixture's kickoff **in the submission's own edition** to be later than `submitted_at + 15 min`. It reads `submitted_at` from the parent row inserted moments earlier in the same transaction.

**Ordering**
- All locks are taken **before** the submission insert. After it come only inserts and an update of the already-locked entry, so there are no further lock waits.
- Lock contention or a slow start therefore **cannot** let a late transaction use an early timestamp: the time is taken at insert, after any waiting.
- `statement_timeout` and `lock_timeout` (existing session settings) bound the remaining window.

**Service-level validation**
- Uses `clock_timestamp()` after the locks, as `_check_open` already does, for user-facing messages.
- The database triggers are the final authority.

**Settlement V3 (v4 rounds)**
- A leg is void only if the observed actual kickoff is earlier than **that entry's `submitted_at`** (the match had started when the participant entered).
- A Friday submission on a Friday fixture is valid: its kickoff was more than 15 minutes after its own `submitted_at`. The Sunday 14:00 deadline plays no part in V3.
- Postponement and rescheduling verdicts stay per outcome, as today.

**Historical rounds:** v1–v3 rounds keep `transaction_timestamp()`, the common deadline and round-level V3. All of this is selected by `rules_version`.

### 14.8 Methodology transition

**Dormant until activated**
- All v4 behaviour is selected by the round's `rules_version`, which comes from its schedule row.
- No v4 schedule row will exist in any hosted database until a **separately authorised activation**.
- So R1–R4 code is inert there: existing rounds and drafts follow v3. Tests create v4 rows only in disposable databases.

**Schema migration (one, in R2)**
- Additive and backward compatible:
  - edition number, with existing snapshots as edition 1;
  - `UNIQUE(round_id, edition)`;
  - the snapshot guard allows editions while open;
  - the universe-subset trigger;
  - `oldest_observation_at`;
  - the v4 submission and selection triggers, active only for v4 rounds;
  - `submission_views`.
- It has a downgrade and changes no historical row.
- Applying it to any hosted or protected database is a separate authorisation.

**Activation: an immediate data migration, not a future-dated one**
- It mirrors the A3 `app_0009` pattern: insert schedule v4 (`active_from` = now) and close v3.
- Run on a Monday–Thursday, before the week's draft is created (78 h before Friday 08:00, i.e. by Tuesday about 02:00 SAST). That week's round is then the first v4 round.
- Activation requires R5 acceptance and explicit owner authorisation.
- **No activation or cancellation framework:** if not wanted, simply do not run it.

**Preserved:** all historical rounds keep their deadlines, single snapshot, prices, buckets, submission rules, round-level V3 and published results.

### 14.9 Countdown (R4, optional, included)

**Design**
- One reusable component: the server supplies `{state, target_utc}`.
- A **client-side** callback updates the text every 60 seconds (`dcc.Interval` with a clientside callback). There are no recurring server calls and no provider requests.
- When the target passes, the client triggers **one** card refresh, so the backend's real state replaces the countdown.

| State | Text | Colour (existing theme tokens) |
|---|---|---|
| Upcoming | "Scheduled to open in 2d 14h 32m" ("scheduled", because publication is manual) | `--info` #79a8ff |
| Open | "Time remaining: 1d 08h 24m" | `--accent` #2dd4bf |
| Closing soon (< 2 h) | "Time remaining: 1h 24m" | `--warn` #f2b84b |
| Submitted | "Your portfolio is in!" (no countdown) | `--accent` |
| Closed, too few eligible fixtures, prices unavailable, no challenge | The state message from §8 (no countdown) | neutral |

**Colours**
- The suggested #3B82F6, #0D9488 and #D97706 reach only about 4.6–5.4:1 on the card surface (#151b23).
- The existing tokens reach about 6.8–9.7:1 and match the interface. They are recommended, subject to the R4 UI review.

**Effort:** about +1–2 h within R4. No separate checkpoint.

### 14.10 Dependency adjustments and estimates

**Dependency adjustments**
- **R1 has no schema change.** It delivers v4 lifecycle *services* (deadline, irrevocability, per-fixture check in the service, entry-level V3, privacy filter, schedule v4 handling in tests) against a single snapshot. A single snapshot is simply edition 1, so nothing in R1 is replaced later.
- **R2 carries the one migration** (§14.8), including the v4 database triggers, and runs the intermediate full CI.
- **The R2 review fingerprint is built complete** (§14.4), including the Your View fields from the current Your View resolution. R3 then changes only how Your View is keyed and carried forward, and writes `submission_views`. The fingerprint is not replaced.
- **R3 depends on R2's editions** for baselines. R4 depends on R1–R3 states. R5 is unchanged.

**Acceptance criteria additions**

| Checkpoint | Added criterion |
|---|---|
| R1 | A Friday entry with a Friday fixture settles as valid under entry-level V3. v3 rounds unchanged |
| R2 | An edition written during a confirmation never produces a mixed confirmation (a concurrency test). An edition after a partial sweep does not refresh un-retrieved observations. Offers age out at confirmation using stored evidence. Overnight slots are generated and stop at Sunday 14:00 |
| R3 | The carry-forward table (§14.5) behaves as specified. Fallback is never recorded as adjusted |
| R4 | Countdown states and the one-shot refresh at zero (if delivered) |
| R5 | Weekend simulation includes overnight slots, a failed sweep, a stale pause and recovery |

**Operational validation obligations** (not research checkpoints)

| When | Obligation |
|---|---|
| R2 and R5 (dev data) | Edition build time and storage |
| First supervised hosted weekend, after separate authorisation | Multi-league weekend and Sunday odds coverage, PSL reliability, request use against the caps, actual Sunday feasibility |
| CP2B.2 | European coverage (7 Dec verification) |

The Goal Model proxy is not treated as verified market feasibility.

**Estimates (material change only)**

| Checkpoint | Change |
|---|---|
| R2 | +3–4 h (evidence columns, partial-sweep correctness, overnight slots, universe trigger, the complete fingerprint) |
| R3 | +2–3 h (carry-forward rules) |
| R4 | +1–2 h (countdown) |
| **CP3A-R implementation** | **72–99 h** (was 66–90) |
| **Remaining Phase 8** | **103–143 h** (was 97–134) |

### 14.11 Remaining owner decisions

| # | Decision | Recommendation |
|---|---|---|
| a | The ±0.20 estimated-goals carry-forward threshold (§14.5) | Approve; reviewable after Beta |
| b | Countdown colours | Use the existing theme tokens, subject to R4 UI review |

- No other open decision.
- **No blocker to starting R1.** R1 needs no migration, no provider access and no API-Football renewal. The renewal (by 14 Dec) matters only for hosted operation.
