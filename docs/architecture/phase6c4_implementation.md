# Phase 6C.4 — Settlement, voids and corrections: implementation record

**Branch:** `feature/phase-6c4-settlement`, from the v4.1.0 release commit
`45ef8c7` (tag `v4.1.0`, annotated object `e112e2d`; 1,304 tests passed, 1 hosted
Supabase test deferred; CI run 27 green; migrations `app_0001`–`app_0005`).

**Status:** Stage A assessment (§1–§21, kept as written for the record) **approved
by the product owner on 19 Nov 2026 with the decisions in §22**, which supersede
the Stage A proposals where they differ (notably: completion-based cutoff, no
closing window, owner-only reopening, explicit development result modes).
**Stages B–D implemented** (record in §23; mandatory owner checkpoint). Stages E–G
wait for separate authorisation.

**Precedence:** the decision register (D-, T-, R- series) and the approved policy
notes (`settle/v1`, D-32b) over this document. This document separates three kinds
of statement, and labels them:

* **Fact** — inspected in the repository at `45ef8c7` (file, function or schema
  object cited).
* **Policy** — approved by the owner (decision ID cited).
* **Proposal** — Claude's recommendation; not adopted until approved. Proposals that
  need an owner decision are numbered **Q-n** and collected in §19.

Related documents:

| Document | Role |
|---|---|
| [`../product/weekly_challenge_settle_v1.md`](../product/weekly_challenge_settle_v1.md) | D-08 `settle/v1`: inputs, cutoff, verdict order, market rules, corrections |
| [`../product/weekly_challenge_d32_round_invalidation.md`](../product/weekly_challenge_d32_round_invalidation.md) | D-32b round invalidation and D-32b-Q1 practice rounds |
| [`../product/weekly_challenge_decisions.md`](../product/weekly_challenge_decisions.md) | Decision register |
| [`../product/weekly_challenge_phase6c_plan.md`](../product/weekly_challenge_phase6c_plan.md) | §6C.4 objectives and acceptance criteria |
| [`phase6c_database_design.md`](phase6c_database_design.md) | §6 results and settlement tables, §9 race protection, §10 corrections |
| [`phase6c_architecture_considerations.md`](phase6c_architecture_considerations.md) | §5 job design (`challenge results`, `settle`, `finalise`) |
| [`phase6c3_closure_handover.md`](phase6c3_closure_handover.md) | 6C.3 closure, policy digest, the ten open 6C.4 questions |

---

## 1. Verified baseline and branch

| Item | Verified value |
|---|---|
| `origin/main` | `45ef8c7f3c31f0b206f1df12804e7748ca561e6a` |
| Remote tag `v4.1.0` | annotated object `e112e2d…`, resolves (`^{}`) to `45ef8c7` |
| Working tree before branching | clean |
| New branch | `feature/phase-6c4-settlement` created at `45ef8c7` |
| Live football API requests in Stage A | none |

## 2. Policy documents reviewed

`settle/v1` (D-08 and its additional requirements), the D-32b note (with D-32b-Q1),
the decision register (C-01, C-10, C-11, C-14, D-05, D-11, D-15, D-26–D-28,
D-31–D-41, T-05–T-21, R-01–R-14), the Phase 6C plan (§6C.4, §6C.5, §6C.6), the
database design (§6, §9, §10, §12, §14), the architecture considerations (§5) and
the 6C.3 closure handover (§8 policy digest, §9 open questions).

## 3. Approved policy summary (no rule reopened)

### 3.1 Inputs and cutoff (D-08, `settle/v1` §1–§2)
* Settlement uses only the round's `deadline_at` and `settle_cutoff_at` (both fixed
  at publish; set-once columns of `app.rounds`) and the fixture's insert-only
  **result observations** (provider and audited operator corrections): status code,
  actual kickoff time, 90-minute score from `score.fulltime`.
* `settle_cutoff_at` = latest `kickoff_at_publish` on the round sheet + 48 hours
  (`round_schedules.settle_cutoff_hours`). Later kickoff changes never move it.
* "Completed by the cutoff" = a final-played status (`FT`, `AET`, `PEN`) with a
  90-minute score is observed **and the actual kickoff is at or before the cutoff**.
  A match that kicks off before the cutoff and finishes after it settles normally.
* Additional D-08 requirements: completion time is distinguished from receipt
  time; delayed notifications use the correction process; original statuses, raw
  results and normalised verdicts are preserved; UTC throughout; the policy version
  is recorded per round; tests cover conflicting statuses, exact cutoff boundaries
  and repeated deliveries; **where reliable evidence is insufficient the operator
  is alerted rather than times or results invented**.

### 3.2 Verdict order (`settle/v1` §3; first match decides)
1. **V3 void** — started, or rescheduled to kick off, before `deadline_at` (any
   observation with an actual or scheduled kickoff earlier than the deadline, or an
   in-play/final status observed before the deadline).
2. **V2 void** — latest status `CANC`, `AWD` or `WO`.
3. **settle** (includes **V5**) — latest status `FT`/`AET`/`PEN`, score present,
   actual kickoff ≤ cutoff → won/lost by the market rules.
4. **V1 void** — now after the cutoff, postponed (`PST` or rescheduled after the
   cutoff) and not completed by the cutoff.
5. **V4 void** — now after the cutoff, `ABD`/`SUSP`/`INT` and not completed by the
   cutoff.
6. **catch-all void** (recorded as V1, with an operator alert) — now after the
   cutoff and nothing else decided (e.g. still `NS`, "in play beyond reason").
7. **pending** — anything else before the cutoff, or a final status with a missing
   score (alert after the cutoff; stays pending until a score or an audited
   correction arrives).

Unknown codes are pending with an alert. Extra time and penalties never count.
Markets on the 90-minute score H–A: 1X2 (H>A, H=A, H<A); BTTS yes when H≥1 and
A≥1; Over 2.5 when H+A≥3, Under when H+A≤2.

### 3.3 Payouts (D-15, D-32, D-33, R-08, C-10, C-11)
* Strict 4/3/2 picks; stakes Foundation 40, Balanced 30, Challenger 20, The
  Diski 9 (all nine) 10.
* Void leg = decimal odds 1.00; a bucket with any incorrect, non-void leg pays 0;
  each accumulator is rounded half-up to 0.01 (D-15); gross = sum; net = gross −
  100; recovery = gross ≥ 100.00.
* An all-void bucket returns its own stake (R-08).
* **D-33:** all nine void → gross 100.00, net 0.00, status "Void — Refunded",
  excluded from the weekly ranking, no recovery and no top-ten, but counts toward
  the five-valid-entry minimum at the deadline.

### 3.4 Round classification and invalidation (D-28, T-07, T-08, D-32b, D-32b-Q1)
* Base designation fixed at the deadline (lock): competitive (stored as the
  legacy value `championship`) with ≥ 5 valid locked entries, otherwise practice
  (D-28; never official membership by itself, D-38).
* **D-32b**, evaluated only when no prediction is pending, over the authoritative
  locked set and counting prediction instances (9 × locked valid entries):
  competitive only if `2 × played > total` **and** `ranked_entries ≥ 5`
  (ranked = not D-33 refunded). Practice rounds: the majority rule only.
  Exactly 50% fails. Failure voids the whole round: everyone's 100 credits back,
  net 0, no points, recoveries or top-ten finishes, no competitive ranking, the
  championship counter does not advance; all records retained.
* Result is **provisional during the R-14 24-hour correction window** and
  confirmed at finalisation.
* Exceptional operator invalidation: operator permission, written reason, audit
  record with before/after designation; never automatic.
* Corrections re-run settlement and D-32b; the outcome is a new designation row;
  points and counters are derived, never accumulated (T-11).

### 3.5 Corrections (D-35, T-06, R-14, `settle/v1` §5)
* Provider corrections arrive as new observations; settlement re-runs and records
  new verdict revisions.
* Operator corrections are observations with source `operator`, the original and
  corrected values, actor, reason and timestamps; they take precedence over
  provider observations until withdrawn by another audited action.
* Any change of verdict re-runs entry settlement and D-32b for the **whole round**
  (T-06). After a championship is frozen, only the audited reopen path
  (owner capability `championship.reopen`).
* After the cutoff, a later completion of a voided match is recorded for research
  but never changes the verdict.

### 3.6 Security principles (T-12, T-14, T-16, D-34)
* Permissions are checked server-side from the database; nothing is taken from the
  browser, editable profile data or provider metadata.
* Operator capabilities need authentication within 12 hours (T-12); correcting
  results, invalidating rounds, reopening championships, suspending accounts and
  role changes need the password entered within 15 minutes (T-14).
* No passwords in the application database; no privileged keys in the browser.

## 4. Existing football data and provider evidence (facts)

### 4.1 Football store (`src/diski9/db/schema.py`, table `fixtures`)
* **Latest state only.** One row per fixture, upserted by
  `ingestion.fixtures.store_fixtures`; a row is rewritten only when
  `content_hash` over `PROVIDER_FIELDS` changes. **No history of earlier states.**
* Stored: `kickoff_utc` (= provider `fixture.date`, the **scheduled** kickoff),
  `status_short`, `status_long`, `ft_home/ft_away` (`score.fulltime`, extra time
  excluded), `ht_*`, `et_*`, `pen_*`, `is_final` (FT/AET/PEN with a score),
  `updated_at` (our write time when content changed), `result_recorded_at` (our
  first observation of a final result).
* **Not stored:** the raw provider item; `fixture.periods.first` /
  `fixture.periods.second` (provider-reported half start times, Unix seconds);
  `fixture.status.elapsed`; any provider per-fixture update time.
* SQLite, separate from PostgreSQL (D-39); the competition backend never joins
  across stores.

### 4.2 Provider payload (`tests/fixtures/fixtures_sample.json`)
The `/fixtures` item contains `fixture.timestamp`, `fixture.periods.first`,
`fixture.periods.second`, `fixture.status.{short,long,elapsed,extra}` and
`score.{halftime,fulltime,extratime,penalty}`. In the stored sample,
`periods.first` **equals the scheduled `timestamp` exactly** (1787338800) — so
`periods.first` cannot be assumed to be an independently measured actual start;
it is provider-reported and may simply mirror the schedule.

### 4.3 Refresh capability (`workflow.refresh`, `ingestion.fixtures.ingest_fixtures`)
* `diski9 refresh-data` re-reads the **whole current season of each of the eight
  competitions** (`/fixtures?league&season`, one request each), then standings,
  optional odds and the screener cache.
* `ingestion.fixtures.stale_fixture_ids` identifies fixtures past kickoff that are
  not final, but no by-ID fetch exists.
* `ApiFootballClient.get(endpoint, params)` (`api_football/client.py`) is generic,
  quota-aware (`quota_requests_made`, daily reserve `DISKI9_API_FOOTBALL_DAILY_RESERVE`,
  500 by default) and never exposes the key.

### 4.4 What this means
* The football store **cannot by itself** provide settlement evidence that meets
  D-08: it overwrites history, keeps no raw payload and drops `periods`.
* The existing client and normalisation (`normalise_fixture`) are reusable.
* **Minimal additional capability needed (proposal):** a by-ID fetch that returns
  the raw provider items for the round's fixtures, so that (a) the football store
  is updated through the existing `store_fixtures` unchanged and (b) the same raw
  items are recorded as competition observations in PostgreSQL. This adds one
  function beside `ingest_fixtures`; it changes nothing existing. The provider's
  `ids` parameter (up to 20 fixtures per request, as documented by the provider) is
  to be confirmed with one request at the start of Stage B (**Q-1**).

## 5. Actual kickoff and completion evidence (assessment)

| Fact needed by `settle/v1` | Evidence available | Reliability | Proposal |
|---|---|---|---|
| Match started before `deadline_at` (V3) | (a) an in-play/final observation **recorded** (our `recorded_at`/`observed_at`) before the deadline; (b) `periods.first` earlier than the deadline; (c) a provider scheduled kickoff (`fixture.date`) earlier than the deadline in any observation | (a) strong: we saw it live; (b) provider-reported; (c) literal V3 trigger ("rescheduled to kick off before the deadline") | Apply V3 on (a), (b) or (c) as `settle/v1` states. Record which evidence fired. Alert the operator when V3 fires on (b) or (c) alone, because those are provider statements we did not observe live |
| Match did **not** start before the deadline | No direct evidence; absence of (a)–(c) | We only observe from publication onwards; a first observation after the deadline proves nothing about the start | Never infer "started after the deadline" from receipt time. Without contrary evidence, the scheduled kickoff (≥ deadline by construction, R-01) stands |
| Actual kickoff ≤ cutoff (settle vs V1) | (a) `periods.first`; (b) an in-play/final observation recorded at or before the cutoff (proves it had started by then); (c) the provider's latest scheduled kickoff | (b) strong; (a), (c) provider-reported | Settle when (a) or (b) shows ≤ cutoff, or (c) is ≤ cutoff with no contrary evidence. Pending plus alert when sources disagree across the cutoff (**Q-4**) |
| Completion time | **None.** The provider gives no completion timestamp | — | Not needed: "completed by the cutoff" is defined by actual kickoff (§3.1). Never manufacture one |
| Result receipt time | Our fetch time (`observed_at`) and database time (`recorded_at`) | exact | Stored on every observation; never treated as an event time |
| Postponed/suspended then completed (V5) | Observation sequence `PST`/`SUSP`/`INT` → `FT` with score | as provider | Settles normally when completed with actual kickoff ≤ cutoff (rule 3 precedes V1/V4) |
| Results received after the cutoff | `FT` observation with `observed_at` > cutoff | as provider | Settles if the actual kickoff was ≤ cutoff (D-08: completion distinguished from receipt), subject to the closing rule in **Q-3** |
| Conflicting observations | e.g. `FT` then `NS`, score changes after `FT` | provider quirks | Latest observation decides (`settle/v1` §5) with an alert; a regression from final-played to not-started is held pending for operator review (**Q-5**) |

**Cases the provider data cannot establish (to be handled by alert, not guess):**
1. Whether a match genuinely kicked off at the scheduled time when `periods.first`
   is absent or merely equals the schedule.
2. When a match finished (no completion timestamp).
3. Whether a match observed in play at the cutoff will finish, and whether a
   suspended match will resume (see **Q-3**).
4. Why the provider changed a status or score.

## 6. Proposed result-observation architecture

```
API-Football ──(existing ApiFootballClient)──► by-ID fetch (new function)
                                                  │ raw items + fetch time
                    ┌─────────────────────────────┴───────────────┐
                    ▼                                             ▼
   football store (SQLite) via the existing          competition observations
   store_fixtures (unchanged behaviour)              (PostgreSQL app.result_observations)
                                                                  │
                                                     fixture resolution (pure) ─► settlement
```

**Proposals:**
1. **Scope.** The results service selects the fixtures of rounds in status
   `locked`/`settling` (and finalised rounds only for alert detection, §8.4) that
   are not yet terminal for settlement; it never imports for unrelated fixtures.
2. **One observation per distinct provider state.** Each raw item is canonicalised
   (sorted keys, no whitespace) and hashed (SHA-256, `raw_hash`). A row is inserted
   only when the hash differs from the **latest** provider observation of that
   fixture, checked under a transaction-scoped advisory lock per fixture. This
   makes repeated deliveries idempotent **and** records a genuine return to an
   earlier state (A→B→A), which the current unique index forbids (§9 gap G1).
3. **Provenance on every row:** `source`, `observed_at` = our fetch time (the
   response), `recorded_at` = database clock, `kickoff_at` = provider scheduled
   kickoff, `actual_kickoff_at` = `periods.first` when present (labelled
   provider-reported), status, 90-minute score, the full `raw` item, `raw_hash`,
   `job_run_id`.
4. **Stale evidence cannot win.** The "current" provider observation is the one
   with the greatest `observed_at` (then `id`). An import whose fetch completed
   earlier but committed later is stored as evidence but does not become current.
5. **Evidence watermark per run.** Each settlement run records the highest
   observation ID it read (proposed column, §10), so the exact evidence of every
   settlement version can be reconstructed from the insert-only table. Future
   football-store updates never touch PostgreSQL history.
6. **Cadence.** Manual in 6C.4 (no scheduler, 6C.6). Service functions take a
   principal or the `System` actor so a future scheduled job calls the same code.
   **Budget estimate** for the approved provisional 15-minute target: a 60-fixture
   round needs 3 requests per poll (20 IDs each). Polling only unresolved fixtures
   from 30 minutes before the first kickoff until the cutoff (≈ 5 days) is at most
   ≈ 1,440 requests per round, far fewer once fixtures finish; comfortably inside the
   daily allowance alongside the odds trial and research collector. A narrower
   window (kickoff − 30 min to kickoff + 3 h per fixture, plus a daily check) cuts
   this to a few hundred.
7. **No `/predictions`, no historical odds, no change to the research collector,
   odds trial or existing ingestion behaviour.**

## 7. Fixture resolution and settlement lifecycle (proposal)

### 7.1 Pure functions (new module `src/diski9/challenge/settle.py`)
* `resolve_fixture(observations, deadline_at, settle_cutoff_at, evaluated_at,
  close_at) -> Resolution` — applies §3.2 exactly, returning `won/lost` per
  outcome (via the market rules), or `void` with the code, or `pending` with a
  reason, plus the **rule** that decided, the evidence used (observation IDs) and
  any alerts. Operator corrections take precedence (latest non-withdrawn).
* `outcome_wins(market, outcome, ft_home, ft_away) -> bool` — §3.2 market table,
  using the stored outcome keys (`home`, `draw`, `away`, `btts_yes`, `btts_no`,
  `over`, `under`; `odds.value.OUTCOME_KEY`).
* `settle_entry(selections, verdicts) -> EntryResult` — adapter over the existing
  engine (§11): void legs at 1.00, bucket wins only if no lost and no pending leg.

### 7.2 Round lifecycle

| Round status | Meaning (proposal) | Set by |
|---|---|---|
| `locked` | Deadline passed, locked set stamped, base designation written (6C.3) | lock |
| `settling` | First settlement run has started; verdicts may be partial; once nothing is pending the D-32b outcome is **provisional** | first settlement run |
| `final` | Correction window elapsed with nothing pending and no open alert; designation confirmed | finalisation |

* **Before the cutoff:** each run settles every fixture whose outcome is already
  certain under `settle/v1` (rule 3 does not depend on the cutoff). Early provisional
  settlement of the whole round is therefore permitted when every prediction has
  a final verdict before the cutoff; nothing is voided for lateness before the
  cutoff.
* **At and after the cutoff:** V1/V4/catch-all apply as written, subject to the
  closing-time question for matches in play or interrupted at the cutoff (**Q-3**).
* **D-32b** is evaluated in every run with no pending prediction; while anything is
  pending a `not_evaluated` evaluation is recorded (the table's CHECK enforces this).
* **Finalisation** (round settlement only; score sets and championship freezes are
  6C.5): requires nothing pending, no unresolved alert, and the correction window
  elapsed (**Q-2** defines when it starts). Writes status `final`, `finalised_at`,
  and a confirming designation row (`provisional = false`).

### 7.3 Settlement run (one transaction per round)
1. Lock the round row `FOR UPDATE`; insert a `settlement_runs` row (`running`);
   the partial unique index forbids a second running run.
2. Read the locked set (`entries.locked_submission_id`; withdrawn entries are never
   in it), the frozen selections and odds (`submission_selections`), and the
   observations up to the watermark.
3. Resolve each fixture; insert a `selection_verdicts` revision **only for changed
   verdicts**.
4. Settle each locked entry; insert an `entry_settlements` revision only when
   values change (`basis = all_void` for D-33).
5. Evaluate D-32b; insert `round_evaluations`; insert a `designations` row only when
   the outcome changes (void, or restoring the base designation).
6. Record alerts; complete the run with `changed_verdicts`, `changed_entries` and
   `inputs_hash`. Any error rolls the whole transaction back (run row included) and
   a failed-run record is written in a separate transaction.
7. A rerun with no new evidence and no change of time phase (before cutoff / after
   cutoff / after closing) writes only the run record (plan acceptance criterion).

## 8. Correction window, finalisation and late results

### 8.1 What the approved documents say (exact)
* **R-14:** "24-hour correction window before a round is final" (stored as
  `round_schedules.correction_window_hours = 24`).
* **`settle/v1` §2 (example):** cutoff Wednesday 19:00 UTC; "finalisation (24-hour
  correction window, R-14) follows" — i.e. 24 hours after the cutoff.
* **D-32b clarification 5:** evaluated as soon as every prediction has a final
  verdict; provisional during the 24-hour window; confirmed at finalisation.
* **Architecture considerations §5 (job table):** `challenge finalise` "acts 24
  hours after the last change once nothing is pending".
* **T-06:** any correction re-scores the whole round; after a championship is
  frozen, only the audited reopen path.
* **Database design §10:** a correction affecting a frozen championship stops the
  run with an alert.

### 8.2 Conflicts and gaps (owner decisions, not resolved here)
* **When the window starts (Q-2):** three readings — after the cutoff (`settle/v1`
  example), after the last change (architecture §5), or from the first complete
  evaluation (D-32b wording). **Recommendation:** final when nothing is pending, no
  alert is open, and at least `correction_window_hours` have passed since **both**
  the cutoff and the last settlement change (verdict, settlement or designation).
  This satisfies all three readings; a late correction restarts the 24 hours.
* **Corrections after round finalisation but before any championship freeze
  (Q-6):** policy defines reopen only for frozen championships. **Recommendation:**
  routine provider imports never reopen a final round; a changed provider result
  for a final round raises an alert only; an audited operator correction (T-14)
  may reopen it (status `final` → `settling`, run trigger `reopen`), re-run
  settlement and D-32b, then re-finalise after a new window. Championship freezes
  are unaffected in 6C.4 (none exist before 6C.5).
* **Matches in play or interrupted at the cutoff (Q-3):** `settle/v1` settles a
  match that kicks off before the cutoff and finishes after it, but also voids
  `SUSP`/`INT` "after the cutoff" (V4) and anything "in play beyond reason"
  (catch-all), and says a voided verdict never changes. Without a defined moment,
  the verdict depends on when a run happens to execute. **Recommendation:** a
  per-round **closing time** = cutoff + a fixed grace (proposed 4 hours, a round
  schedule value frozen at publish). Fixtures with actual kickoff after the cutoff
  (or still `PST`/`NS`) are voided at the cutoff; fixtures that kicked off by the
  cutoff and are in play/suspended stay pending until the closing time, then V4 or
  catch-all applies using evidence recorded by then; from then on the void is
  final ("never changes").
* **No new correction window is invented here.**

### 8.3 Late provider results
Recorded as observations whenever imported. Before finalisation they re-run
settlement (subject to Q-3); after finalisation they only raise an alert (Q-6).

### 8.4 Operator override requirements (approved)
D-35 (reason, original and corrected values, actor, timestamps, immutable),
T-14 re-authentication for overriding results and invalidating rounds, D-32b §3
row 6 for exceptional invalidation.

## 9. Existing database schema assessment (facts, `app_0001`–`app_0005`)

| Requirement | Existing support | Gap |
|---|---|---|
| Observation provenance | `result_observations`: `source` (`api-football`, `operator`), `observed_at`, `recorded_at` (DB clock), `kickoff_at`, `actual_kickoff_at`, `raw jsonb`, `raw_hash`, `job_run_id`; operator CHECK (actor, reason, corrects/withdraws); insert-only trigger | — |
| Multiple observations per fixture | yes (`ix_results_fixture`) | **G1:** `uq_results_provider_hash (fixture_id, raw_hash)` forbids recording a return to an earlier state (A→B→A) |
| Synthetic development results | none | **G2:** no `synthetic` source and no round scoping; mirrored development rounds use **real fixture IDs** (`devdata.mirror_snapshot`), so synthetic rows keyed by fixture alone would affect real rounds |
| Operator result without a provider row | CHECK requires `corrects_observation_id` or `withdraws_correction_id` | **G3:** an operator cannot record a result for a fixture the provider never reported |
| Frozen policy version | `rounds.rules_version` (set-once; `settle/v1`), `config_version`, `scoring_version` | — |
| Frozen correction window | only on `round_schedules` (a mutable projection table) | **G4:** `correction_window_hours` (and any Q-3 grace) is not frozen on the round |
| Fixture resolution decisions | `selection_verdicts` (verdict, `void_code` V1–V4, one `result_observation_id`, revision, `UNIQUE (round, fixture, market, outcome, revision)`) | **G5:** no record of the deciding rule (settle vs V5, catch-all vs V1, pending reason) or the evidence set |
| Immutable verdicts and versions | insert-only trigger; revisions | — |
| Accumulator returns, gross, net | `entry_settlements.legs jsonb`, `gross`, `net` (CHECK `net = gross − 100.00`), `complete` | — |
| All-nine-void | `basis = 'all_void'` with CHECK `gross = 100.00` | — |
| Round-wide invalidation | `round_evaluations` (CHECKs: pending ⇒ `not_evaluated`; pass ⇒ `2·played > total`; `fail_ranked` only competitive) and `designations` (basis `d32b`/`operator`, operator needs actor and reason) | — |
| Current authoritative settlement | highest revision per entry/offer; latest designation | derived by query (no pointer needed) |
| Correction and override audit | `audit_log` (insert-only, before/after JSON); operator observation rows | — |
| Provisional / final | `designations.provisional`, `rounds.status` (`settling`, `final`), set-once `finalised_at`, `score_sets.final` (6C.5) | — |
| Concurrent and repeated runs | `uq_settlement_running` partial unique index; `run_guard()` lets only a running run complete | **G6:** no evidence watermark or evaluation phase on the run |
| Atomic rollback | single transaction (tested pattern, `test_failed_transaction_leaves_nothing_behind`) | — |
| Account isolation | row-level security on every `app` table, access only for the runtime role (`app_0002`); services key every query by the principal | — |
| Operator access | capabilities `jobs.run`, `result.correct`, `round.void` (`auth/permissions.py`); `result.correct` and `round.void` are in `SENSITIVE` | **G7 (code, not schema):** `services.common.cli_principal` sets `authenticated_at = now` from shell access and `reauthenticated_at = None`, so CLI operators currently satisfy T-12 by database access alone and can never satisfy T-14 |
| Alerts | `domain_events` (insert-only, `kind`, `round_id`, `payload`) | usable without a migration |
| Future championship recomputation | designations and score sets are insert-only and derived | 6C.5 adds the `championship_rounds` view |

## 10. Proposed migration (not implemented; smallest additive set)

**`app_0006_settlement_evidence`** (Stage B, with the C/D parts applied in the
same revision or a follow-up if the owner prefers):

1. `result_observations`
   * replace the unique index `uq_results_provider_hash` with a plain index
     `(fixture_id, raw_hash)`; deduplicate against the latest provider row in the
     service under an advisory lock (G1);
   * allow `source = 'synthetic'` with a new nullable `scope_round_id uuid`
     referencing `rounds`; CHECK `(source = 'synthetic') = (scope_round_id IS NOT
     NULL)`; a trigger refuses a synthetic row unless the scoped round
     `is_development` (G2);
   * allow an operator **assertion** without `corrects_observation_id` (actor and
     reason still required) (G3).
2. `rounds`: set-once `correction_window_hours` (and `close_grace_minutes` if Q-3 is
   approved), copied from the schedule at publish; existing published rounds
   back-filled from their schedule (G4).
3. `selection_verdicts`: nullable `rule text` (CHECK in `V1`…`V4`, `V1-catch-all`,
   `settle`, `settle-V5`, `pending-…`) and `evidence jsonb` (observation IDs and the
   kickoff evidence used) (G5).
4. `settlement_runs`: `evidence_through_id bigint`, `phase text` (`before_cutoff`,
   `after_cutoff`, `closed`), `evaluated_at timestamptz` (DB clock) (G6).
5. Grants and row-level security for the new columns follow the `app_0002` pattern;
   downgrade removes only what the revision added and refuses if synthetic rows
   exist.

No change to Supabase-managed schemas, the football store or the engine.

## 11. Quantitative engine reuse (facts and proposal)

* **Reused unchanged:** `challenge.structured.evaluate_groups` (exact
  per-accumulator payouts with `round_credits`, half-up to 0.01; gross per joint
  state; nine-fold pays only when every bucket wins), `challenge.portfolio.round_credits`,
  `challenge.config.DEFAULT_CONFIG` (`broad60-432-v1`: 4/3/2, 40/30/20/10),
  `challenge.scoring.classify_round` (designation at the deadline) and, in 6C.5,
  `challenge.scoring.score_round` with `AllVoidPolicy.REFUND_UNRANKED` (D-33).
* **Settlement adapter (new, pure):** call `evaluate_groups` with each leg's frozen
  `consensus_odds` from `submission_selections`, replacing void legs by
  `Decimal("1.00")` (D-32); the realised gross is the `JointState` whose win vector
  equals the actual bucket results. Probabilities are irrelevant to the realised
  value. No new arithmetic.
* **Regression guarantees:**
  * with no void leg, the realised gross equals the gross stored in the confirmed
    submission's eight states (`submissions.states`) for the same win vector;
  * all nine void gives exactly 100.00 through the same code (40 + 30 + 20 + 10);
  * `tools/phase6c3_quant_regression.py` output stays byte-identical to v4.0.0/v4.1.0
    (SHA-256 `88bcd717…`).
* **Engine code change required:** none identified.
* **Naming map:** database `all_void` ↔ engine `SettlementBasis.ALL_SELECTIONS_VOID`.

## 12. Operator CLI and authentication (proposal)

### 12.1 Commands (Stage E)

| Command | Capability | Sensitive (T-14) | Material change |
|---|---|---|---|
| `diski9 results import --round CODE` | `jobs.run` | no | observations only |
| `diski9 results show --round CODE [--fixture ID]` | `jobs.run` | no | none |
| `diski9 settle preview --round CODE` | `jobs.run` | no | none (read-only transaction) |
| `diski9 settle run --round CODE --confirm` | `jobs.run` | no | settlement revisions |
| `diski9 settle alerts --round CODE` | `jobs.run` | no | none |
| `diski9 results correct --round CODE --fixture ID ...` | `result.correct` | **yes** | operator observation, re-settlement |
| `diski9 results withdraw-correction --id N` | `result.correct` | **yes** | operator observation, re-settlement |
| `diski9 round invalidate --round CODE` | `round.void` | **yes** | operator designation |
| `diski9 round finalise --round CODE` | `jobs.run` | no | status `final` |
| `diski9 round reopen --round CODE` | **Q-7** | **yes** | status back to `settling` |
| `diski9 dev-results scenario ...` | `jobs.run`, development rounds and non-production only | no | synthetic observations |

Every material command: a **preview** first (what would change, for whom, by
username, never email), an explicit confirmation (`--confirm` or an interactive
"type the round code"), a mandatory **reason** for corrections, invalidations and
reopening, and an immutable `audit_log` row in the same transaction.

### 12.2 Authentication for CLI operators (G7)
* **Recommendation (Q-8, option A):** the CLI asks for the operator's password
  with `getpass` (never an argument, environment variable, log line or shell
  history) and verifies it with Supabase Auth through the existing provider
  adapter. A successful check yields a principal for **that one command** with
  `authenticated_at = reauthenticated_at = now`; roles and capabilities are loaded
  from the database (`account()`), never from the command line or provider
  metadata. Nothing is stored; the provider tokens are discarded.
* **Option B:** a one-time action code issued in the web app after
  `/auth/reauthenticate`, bound to user, capability and 15 minutes, typed into the
  CLI. Avoids passwords on the server shell but needs a small web feature.
* **Option C (not recommended):** keep `--by-email` with shell access as authority.
  Conflicts with "database access alone is not operator authority".
* Routine automated jobs (future 6C.6) act as `System`; corrections, invalidation
  and reopening are **never** available to `System`.
* The existing `round publish/lock` commands keep working; whether they adopt the
  password check too is part of Q-8.

## 13. Development-only settlement scenarios (proposal)

* **Data:** synthetic observations (`source = 'synthetic'`, `scope_round_id` = a
  development round) in PostgreSQL only. Never written to the football SQLite store
  or to real rounds (database trigger, §10). Development rounds already cannot join
  the official series (`development_round_guard`, `app_0004`); 6C.5 must also keep
  them out of beta championship membership.
* **Resolution rule for development rounds (Q-9):** a development round settles
  from its synthetic observations when any exist for that fixture, otherwise from
  real observations (useful for mirrored rounds after the real matches finish).
* **Deterministic scenarios** (named, seeded, generated from the round's own locked
  entries): `all-correct`, `all-incorrect`, `one-bucket-wins`, `partial-void`
  (void legs at 1.00), `bucket-all-void`, `all-nine-void` (D-33), `round-invalid-
  majority` (exactly 50% played), `round-invalid-ranked` (competitive, < 5 ranked),
  `pending`, `cutoff-boundary` (kickoff exactly at the cutoff and one second after),
  `late-result`, `provider-correction` (score change after FT), `status-regression`,
  `repeat` (same evidence twice), `conflict` (operator vs provider).
* **Time control:** cutoff scenarios need an evaluation time other than now. Proposal:
  `settle run --as-of` accepted **only for development rounds**, recorded on the run
  (`evaluated_at`, `phase`), refused for real rounds.
* **Owner's Mac:** `round dev-open` → submit entries → `round lock` →
  `dev-results scenario …` → `settle preview` → `settle run` → view My Challenge.
  Practice rounds suffice for one participant; competitive scenarios need five
  test accounts (local Supabase), documented in the Stage G guide.
* **Scope:** a test utility only, not a participant feature; no probabilities, no
  Monte Carlo, no hypothetical payouts.

## 14. My Challenge settlement experience (UX proposal; not implemented)

Placement: inside the existing My Challenge page and its existing cards; **no new
tab or route**, same theme, typography, card sizes and responsive breakpoints. The
existing estimate cards (Market, Diski 9, Your View) and the Portfolio Analysis
are kept unchanged; **no new charts, no probabilities in the results panel**.

```
┌ Weekend round 2026-W48 · Competitive · PROVISIONAL RESULT ──────────────┐
│ Settled 25 Nov 21:10 SAST · final after the correction window (26 Nov)   │
│                                                                          │
│ Foundation (40)   ✓ ✓ ✓ void      odds 2.31 → 1.84 (void at 1.00)  73.60 │
│ Balanced (30)     ✓ ✗ ✓                                             0.00 │
│ Challenger (20)   ✓ pending                                       pending│
│ The Diski 9 (10)  needs all nine — lost (one incorrect)             0.00 │
│                                                                          │
│ Gross 73.60 settled so far · 1 prediction pending · Net not final yet    │
│ Recovery: not decided yet                                                │
└──────────────────────────────────────────────────────────────────────────┘
 Predictions: match · your pick · frozen odds · 90-minute score · verdict
 (Correct / Incorrect / Void – postponed / Pending)
```

* **Status labels:** Results pending (locked, nothing settled) · Partly settled ·
  Provisional result · Final result · Corrected (notice with date and plain reason
  category, e.g. "a score was corrected by the provider") · Void — Refunded (D-33,
  entry) · Round void — all entries refunded (D-32b, with the one-sentence rule).
* **Never misleading:** a pending leg is never shown as incorrect; a bucket with a
  pending leg and no incorrect leg shows "pending", not 0; a bucket with an incorrect
  leg shows 0.00 (that is already certain); totals while incomplete are labelled
  "settled so far" and net/recovery "not decided yet".
* **Recovery vs ranking:** "Recovered 100+" / "Not recovered" for the entry; rank
  eligibility appears only as the D-33 refunded state; no ranks or points (6C.5).
* **Where:** the current-round confirmed card once its round is locked, and the
  T-20 "most recent entry" card when another round is current (it becomes "Most
  recent entry" with results). Full history browsing stays deferred.
* **Privacy:** only the signed-in participant's own entry; guests see nothing; no
  other participant's results.

## 15. Stage boundaries and future-phase dependencies

| In 6C.4 | Deferred |
|---|---|
| Observations, resolution, verdicts, entry settlements, D-33, D-32b evaluations and designations, provisional/final round settlement, corrections, operator invalidation, reopen of a final round (Q-6), CLI, development scenarios, personal results in My Challenge | **6C.5:** score sets, weekly ranks and points (D-26, D-31), leaderboards, championship membership/progression/freezes, history pages. **6C.6:** admin web interface, scheduled results/settle/finalise jobs, monitoring |

* **Dependency for 6C.5:** score sets need the current designation and entry
  settlements; they are derived, so 6C.4 data is sufficient. Frozen championships do
  not exist until 6C.5, so the "stop with an alert when a championship is frozen"
  branch is written in 6C.5.
* **D-32b needs rank eligibility, not ranks:** `ranked_entries` = locked entries not
  D-33 refunded; no ranking is computed in 6C.4.
* **Plan adjustment:** the plan places `jobs/finalise.py` in 6C.5; this assessment
  proposes round-settlement finalisation in 6C.4 (needed for "Provisional/Final"
  in My Challenge) and score-set finalisation and freezes in 6C.5.

## 16. Implementation plan (Stages B–G; not started)

| Stage | Content | Exit evidence |
|---|---|---|
| **B — Result ingestion and fixture resolution** | `app_0006` part 1 (G1–G3); by-ID fetch beside `ingest_fixtures` (football store updated through the unchanged `store_fixtures`); observation recorder with canonical hash, advisory lock and stale protection; pure `resolve_fixture` and market rules; alerts as `domain_events` | status table tests, observation idempotency, no change to existing ingestion tests |
| **C — Entry and round settlement** | `app_0006` part 2 (G4–G6); `challenge/settle.py` adapter over `evaluate_groups`; `services/settlement.py` run transaction; D-33; D-32b competitive/practice; designations; provisional status; deterministic scenario builders as a test library | engine-equivalence property tests, D-32b examples, concurrency |
| **D — Corrections and audit** | operator corrections, assertions and withdrawals; operator invalidation; finalisation and reopen (Q-2, Q-6); whole-round re-settlement; audit rows | correction sequences crossing D-32b both ways; no duplicate effects |
| **Owner checkpoint** | settlement report on replayed data (plan §6C.4 "stop for review"), labelled synthetic where synthetic | |
| **E — Operator CLI and development scenarios** | commands §12.1, CLI authentication (Q-8), `dev-results`, `--as-of` for development rounds | CLI tests, secret-handling tests |
| **F — My Challenge integration** | results panel §14 in the existing cards | browser journeys |
| **G — Regression, browser, performance, documentation, local guide** | full suite, quantitative regression, migration paths, restart, screenshots, Mac guide | final report |

**Sequence adjustment recommended:** build the deterministic scenario builders as a
test library in Stage C (they are needed to test C and D), and expose them through
the CLI in Stage E. Otherwise the order is kept.

## 17. Testing strategy

| Area | Existing tests (at `45ef8c7`) | To add |
|---|---|---|
| Status mapping and verdict order | — | table tests per code and per rule, including unknown codes, `AET`/`PEN` on 90-minute score |
| Early commencement (V3) | — | in-play recorded before deadline; `periods.first` before deadline; rescheduled earlier; first observation after deadline proves nothing |
| Cutoff boundaries | — | kickoff exactly at cutoff, +1 s; closing time (Q-3); result received after cutoff |
| Delayed / missing / conflicting evidence | — | late FT; missing score after FT; FT→NS regression; score change after FT; out-of-order imports |
| 90-minute scores and markets | `test_challenge_engine.py`, `test_challenge_structured.py` (payout maths) | market rule tables for all seven outcomes |
| Pending vs resolved | `test_d32b_pending_predictions_mean_not_evaluated` (schema) | pending never shown as lost; buckets pending vs 0 |
| Exact payouts | `test_half_up_rounding_and_recovery_threshold`, structured engine tests | hypothesis: settlement = engine state gross for every win vector; void legs at 1.00 |
| Partial and complete voids | `test_entry_settlement_net_and_all_void_refund`, scoring D-33 tests | per-bucket void; all-void bucket returns stake; all nine void = 100.00 |
| D-32b thresholds | `test_d32b_exactly_half_played_cannot_pass`, `test_d32b_practice_rounds_have_no_ranked_entry_rule` (schema CHECKs) | service-level examples from the D-32b note, incl. 4 ranked of 20 |
| Practice vs competitive | scoring tests | practice majority-only; competitive both |
| Corrections changing validity | `test_corrected_settlement_recomputes_deterministically` (engine) | competitive→void→competitive; no duplicate rows |
| Idempotency | — | rerun writes only a run row; repeated deliveries |
| Concurrency | `test_one_running_settlement_per_round` | parallel run vs run; run vs correction; lock vs late submission unchanged |
| Rollback | `test_failed_transaction_leaves_nothing_behind`, `test_rollback_on_application_error` | failure mid-run leaves no revisions |
| Immutable history | `test_runtime_role_cannot_rewrite_history` | new columns covered; synthetic guard |
| Cross-account access | 6C.3 owner-scope tests | settlement reads are owner-scoped; preview needs `jobs.run` |
| Operator authorisation | `test_backend_auth_unit.py` (capabilities, recency) | CLI password verification; T-14 for correct/invalidate/reopen; no secrets in argv/logs |
| Development isolation | `development_round_guard` tests | synthetic rows refused for real rounds; real rounds ignore synthetic rows |
| Restart and reconstruction | 6C.3 restart check | rebuild every current settlement from observations up to each run's watermark |
| Migration compatibility | `test_backend_migrations.py`, `test_backend_upgrade_paths.py` | `app_0006` up/down from `app_0005` with data |
| Quantitative regression | `tools/phase6c3_quant_regression.py` | unchanged fingerprint |
| Browser journeys | 6C.3 journeys A–H | results states on desktop, tablet, mobile |

No live football API request is needed for any test; provider payloads are
recorded fixtures.

## 18. Risks, limitations and uncertainties

1. **Actual kickoff evidence is weak** (§5): `periods.first` may mirror the schedule;
   alerts and operator review cover the gap.
2. **Provider quirks:** status regressions, late score changes, unknown codes —
   alerts, pending, never guessed.
3. **Run-timing dependence at the cutoff** until Q-3 is decided.
4. **Quota:** shared with the odds trial and research collector; the by-ID fetch and
   a narrow polling window keep usage small; manual runs in 6C.4.
5. **Mirrored development rounds share real fixture IDs** — handled by the
   synthetic scope (G2); until then, no synthetic data may be written.
6. **CLI authentication** needs the auth server reachable from the operator's shell
   (option A).
7. **Football store remains SQLite (D-39)**; settlement evidence lives in
   PostgreSQL, so the later migration does not affect settlement history.
8. **D-29** (real-pool validation of scoring and D-32b) and **D-36** (retention)
   stay outstanding; neither blocks 6C.4.

## 19. Decisions for the product owner

| ID | Question | Recommendation |
|---|---|---|
| **Q-1** | Add a by-ID fixture fetch (raw items) beside the existing ingestion, feeding both the football store (unchanged `store_fixtures`) and PostgreSQL observations; confirm the `ids` parameter with one request in Stage B | Approve |
| **Q-2** | When the 24-hour correction window starts (three readings in §8.1) | Final when nothing pending, no open alert, and 24 h since both the cutoff and the last settlement change |
| **Q-3** | Closing time for matches in play or interrupted at the cutoff | Cutoff + 4 h grace (a schedule value frozen per round); voids final after that |
| **Q-4** | Actual-kickoff evidence hierarchy at the cutoff | `periods.first` or an in-play/final observation recorded by the cutoff; else the provider's scheduled kickoff with no contrary evidence; disagreement → pending + alert |
| **Q-5** | Conflicting provider observations | Latest decides with an alert; a regression from final-played to not-started is held pending for operator review |
| **Q-6** | Corrections after round finalisation (no championship frozen yet) | Imports alert only; an audited operator correction (T-14) reopens and re-finalises |
| **Q-7** | Capability for reopening a final round | `result.correct` (operator, sensitive) for round reopen; `championship.reopen` (owner) stays for frozen championships in 6C.5 |
| **Q-8** | CLI operator authentication | Option A: password via `getpass`, verified with Supabase Auth, per command; apply to all settlement commands |
| **Q-9** | Development round results | Synthetic (scoped) when present for a fixture, otherwise real; `--as-of` only for development rounds |
| **Q-10** | Finalisation in 6C.4 | Round-settlement finalisation in 6C.4; score sets and championship freezes in 6C.5 |
| **Q-11** | V3 on a provider-reported scheduled kickoff earlier than the deadline that we never observed live | Apply V3 literally as `settle/v1` says, with an operator alert |
| **Q-12** | Migration `app_0006` (§10) | Approve the additive set |
| **Q-13** | Interim display while settling: show "settled so far" totals from resolved accumulators | Approve, labelled as not final |

Carried from the closure handover and still open: T-07 `postponed` designation has
no defined trigger — **no new postponement rule is introduced**; designation
`postponed` stays unused in 6C.4. Recorded but unchanged: the D-29b register text
says the research capture runs on Thursdays, whereas the activated schedule runs on
Fridays (research record; not edited here).

## 20. Portfolio Analysis retained; no new simulation

The existing Portfolio Analysis (exact eight-state and 512-state analysis, recovery
probabilities, expected payouts, payout distributions, conditional analysis, Market,
Diski 9 and Your View perspectives, charts and explanations) is kept unchanged. This
assessment proposes **no** participant-facing settlement simulator, Monte Carlo,
hypothetical payout calculator, duplicate charts, predictive model, optimisation or
championship forecast. The development scenario facility (§13) is a test utility
for development rounds only.

## 21. Documentation consistency (done in Stage A)

Active product and architecture documents updated from the old Thursday
publication examples to the approved Friday 08:00 SAST target (D-11 revision):
`settle/v1` §2 example, `docs/backend.md` seed description, the database design
§4.1 and the architecture considerations §5. Historical records are unchanged: the
decision review, research proposal, D-29a/D-29b research entries, the Phase 6A.2
design and release notes.

## 22. Approved decisions (19 Nov 2026) and superseded Stage A proposals

The owner approved the assessment after a targeted clarification. The register
records them as **S-01 to S-11**; `settle/v1` was amended (§2, §2a, rules 1 and
3–6, notes, §5).

| Stage A item | Approved decision | Effect on this document |
|---|---|---|
| Q-1 by-ID fetch | S-01 approved | §6 stands |
| Q-2 window start | S-02: max(cutoff, last **material** change) + 24 h; nothing relevant pending; no unresolved blocking alert; database clock; materiality defined across the whole locked round | §8.2 recommendation adopted with the S-02 definitions |
| Q-3 closing window | **Rejected.** S-03: completion-based cutoff, no grace period | §5 rows on actual kickoff ≤ cutoff, §8.2 closing time and the `close_grace_minutes` column in §10 are **superseded** |
| Q-4 / Q-11 kickoff evidence and V3 | S-04: two V3 branches (started / rescheduled), `periods.first` supporting only, blocking alerts for unverified or contradictory evidence | §5 V3 row refined |
| Q-5 conflicts | S-05: A → B → A kept; idempotent repeats; late commits never override; material conflicts via correction | §6 stands |
| Q-6 / Q-7 reopening | S-06: no automatic reopening; **owner-only** reopening with T-14, evidence, reason, preview, confirmation, audit, recalculation, new version | §12.1 "Q-7 → `result.correct`" **superseded**: a new owner capability |
| Q-8 CLI authentication | S-07: interactive password via Supabase Auth in Stage E; service boundaries in B–D | §12.2 option A |
| Q-9 development rounds | S-08: explicit frozen `synthetic` / `real` mode, no fallback or mixing | §13 "synthetic when present, otherwise real" **superseded** |
| Q-10 finalisation | S-09: in 6C.4 | §15 stands |
| Q-12 migration | S-10: approved in principle, no grace column | §10 as amended |
| Q-13 interim display | S-11: approved for Stage F | §14 stands |

---

## 23. Stages B–D implementation record (19 Nov 2026)

**Commits:** decisions and policy amendment `182966b`; Stage B `dee7bf4`; Stage C
`55ac667`; Stage D `ffe1fba`; this record and the checkpoint documentation follow.

### 23.1 Policy amendments (S-01 to S-11)
* `docs/product/weekly_challenge_settle_v1.md`: completion-based cutoff (§2),
  late completion versus delayed notification, the evidence table (§2a), V3
  branches (rule 1), rules 3–6 using the status *recorded at the cutoff*, notes,
  conflicting results (§5).
* `docs/product/weekly_challenge_decisions.md`: S-01 to S-11; D-08 and R-14 notes.
* Consequential wording: closure handover digest (§8), this document (§22).

### 23.2 Migration `app_0006_settlement_evidence` (Stage B)
| Object | Change |
|---|---|
| `result_observations` | unique `(fixture_id, raw_hash)` replaced by an index (A → B → A recordable); source `synthetic` with `scope_round_id` (trigger: development round in synthetic mode only; corrections keep fixture and scope); operator rows need actor, reason and evidence (assertions without a provider row allowed); `actual_kickoff_at` / `completed_at` only on operator rows; `provider_first_half_at` (supporting only); `observed_at <= recorded_at` except synthetic |
| `rounds` | set-once `correction_window_hours` and `result_mode`; a publish trigger copies the schedule's window and sets `real` for real rounds whatever code path publishes; existing published rounds back-filled; development rounds start with no mode and cannot be settled until one is chosen |
| `selection_verdicts` | `rule`, `evidence` (score used, observation IDs, notes, policy), `material`; CHECK that rule, verdict and void code agree |
| `settlement_runs` | `evaluated_at`, `phase`, `time_override` (trigger: development rounds only), `actor_user_id`, `manifest`, `evidence_through_id`, `material`; triggers `invalidation`, `finalise` |
| `settlement_versions` (new, insert-only) | consecutive versions; `provisional` / `final` / `reopened` lifecycle enforced by trigger (`final` → only `reopened`; `reopened` only after `final`; reopened needs actor, reason, evidence) |
| `settlement_alerts`, `settlement_alert_resolutions` (new, insert-only) | alerts unique per round and fingerprint; one resolution per alert; human resolutions need an actor; `corrected` needs the correction observation |

Row-level security and runtime-role grants follow `app_0002`. **Downgrade**
refuses (`object_in_use`, nothing changed) once any 6C.4 data exists, because the
earlier schema cannot represent it; with no such data it restores `app_0005`
exactly. A downgrade to `base` on a database with settlement history is therefore
also refused — deliberate: settlement history is never discarded silently.

### 23.3 Result evidence (Stage B)
* `ingestion/results_fetch.py` (new; existing ingestion untouched):
  `fetch_fixtures_by_ids` batches IDs 20 per request (`ids=a-b-c`);
  `canonical_hash`; `evidence_fields` reads `score.fulltime` exactly as the
  football store and keeps `periods.first` separately. The provider's `ids`
  parameter is used as documented by the provider; **no live request was made**
  (not authorised); confirming it is a one-request task when live access is
  authorised.
* `repositories/results.py`: `record_evidence` deduplicates against the
  observation **preceding** it in receipt order for the same fixture and scope,
  under a transaction-scoped advisory lock; reads per result mode never mix
  (`real`: provider + unscoped operator rows; `synthetic`: rows scoped to the
  round).
* `services/results.py`: `import_results` (real mode only; locked/settling/final
  rounds; only fixtures selected in locked entries; skips fixtures more than 30
  minutes ahead and those final or cancelled for 6 hours unless `full`; refuses
  responses older than 30 minutes at recording; optional hand-off of the same
  items to the unchanged `store_fixtures`); `set_result_mode` (development only,
  set once, audited); `record_synthetic_observation` (development round in
  synthetic mode, never production).

### 23.4 Fixture resolution (Stage B, `challenge/settle.py`)
Pure functions. Only observations recorded at or before the evaluation time are
considered. Order: V3 (*started*: our in-play/interrupted/final observation before
the deadline, or an operator-verified kickoff; *rescheduled*: a consistent provider
schedule before the deadline) → ambiguity holds (unverified `periods.first`,
contradictory schedules) → V2 → regression hold → unknown status → settle (completion
evidence: a final observation **recorded at or before the cutoff**, or an operator
`completed_at` at or before it; score from the latest scored final, or the first
one when a later score would change a selected verdict) → after the cutoff, the void
rule from the status recorded at the cutoff (V1 for `PST` or a schedule beyond the
cutoff, V4 for `ABD`/`SUSP`/`INT`, otherwise `V1-catch-all`) plus a blocking
`late_notification` when a final arrived only after the cutoff → pending. A live
operator correction (latest not withdrawn) is authoritative for status, score and
any verified times.

### 23.5 Settlement (Stage C, `services/settlement.py`)
One transaction per round with the round locked; `compute` (read-only plan) and
`apply` (writes). Entry payouts through `challenge.settle.settle_entry`, which calls
the unchanged `structured.evaluate_groups` with void legs at 1.00; complete entries
take the engine state for their win vector; partial entries count only resolved
winning accumulators ("settled so far"); a pending accumulator has no payout (never
0). Every complete entry without voids is checked against the confirmed
submission's stored states (`SettlementIntegrityError` otherwise). D-32b counts
prediction instances of the locked set; designation rows are written only when the
outcome changes, never touching the lock's base classification; an operator void
is not undone by D-32b. Revisions only on change; verdict revisions are material
when verdict, void code or rule changes (score-only revisions are recorded as
non-material); every entry change is material; a settlement version is written for
the first run and every material run. Alerts are deduplicated by fingerprint;
only unknown-status, missing-score and regression alerts are superseded
automatically when the evidence clears them. Development time overrides are
refused for real rounds, production and the scheduled-job actor (service **and**
database trigger). A finalised round is never changed: a material difference
raises `post_final_change`. `personal_result` is owner-scoped; recovery and rank
eligibility stay `None` until the entry is complete and the round's validity has
been evaluated; a void round shows the refund (gross 100.00, net 0).

### 23.6 Corrections, finalisation, reopening (Stage D, `services/corrections.py`)
| Operation | Capability | T-14 | Preview + token | Reason / evidence | Effect |
|---|---|---|---|---|---|
| `correct_result` | `result.correct` | yes | yes | both | operator observation (correcting the latest evidence, original values kept), whole-round recalculation, alerts it resolves marked `corrected` |
| `withdraw_correction` | `result.correct` | yes | — | reason | withdrawal row, recalculation |
| `resolve_alert` | `result.correct` | yes | — | reason | `late_notification` → `confirmed` (void stands); informational → `acknowledged`; other blocking alerts refused (need a correction) |
| `invalidate_round` | `round.void` | yes | yes | reason | operator `void` designation, material version |
| `finalise_round` | `jobs.run` or scheduled actor | — | — | — | final run first; refuses on material change, pending, open blocking alert or before max(cutoff, last material change) + window; then status `final`, confirming designation (`provisional = false`), `final` version |
| `reopen_round` | `round.reopen` (**owner only**, new) | yes | yes | both | status back to `settling`, `reopened` version, optional correction, recalculation, new version; the `final` version stays |

Tokens summarise the exact impact and the current version, so a stale or
concurrent confirmation is refused. Audit payloads hold reasons, evidence sources
and values, never credentials.

### 23.7 Evidence
* Tests added: `tests/test_settle_rules.py` (45), `tests/test_settle_entry.py`
  (11, including hypothesis properties), `tests/backend/test_backend_results.py`
  (17), `test_backend_settlement.py` (16), `test_backend_scenarios.py` (15),
  `test_backend_corrections.py` (17), `test_backend_settlement_security.py` (6),
  one upgrade-path test and one auth unit case.
* Full suite (real PostgreSQL + local Supabase Auth): **1,433 passed, 1 skipped**
  (the deferred hosted Supabase test). The first full run had one failure: a 6C.3
  migration test downgraded the shared session database to `app_0003`, which the
  new downgrade guard refused because earlier modules had written settlement data.
  The test now runs on its own fresh database (as does the full-downgrade test);
  the guard is unchanged.
* CI: runs 29–30 (decisions, Stage B) passed; runs 31–33 failed on a timing race
  in one test helper (provider evidence recorded before its receipt time had
  passed, correctly refused by the database) and, in run 32, the shared-database
  downgrade test described above; both fixed (`38d2081`); **run 34 passed**
  (1,421 passed, 13 skipped: browser tests without Playwright on the runner and the
  hosted Supabase test).
* Quantitative regression: engine files unchanged from v4.1.0; fingerprint
  `88bcd717…` identical. Source changes against v4.1.0 are additions only.
* Performance (`tools/phase6c4_perf.py`, local PostgreSQL, median ms):

| Locked entries | Settle (first) | Rerun | Preview | Correction (preview + execute) | Own result | Import 18 fixtures |
|---|---|---|---|---|---|---|
| 50 | 68 | 45 | 33 | 101 | 3.7 | 42 |
| 200 | 103 | 90 | 93 | 330 | 3.7 | 50 |
| 1,000 | 480 | 462 | 479 | 1,317 | 4.3 | 72 |

### 23.8 Deviations from the Stage A design (with reasons)
1. **No closing window** (S-03); the void rule comes from the status recorded at the
   cutoff.
2. **Alerts in dedicated tables** instead of `domain_events`: blocking alerts need
   audited resolutions with state, which `domain_events` cannot hold.
3. **`settlement_versions` table** added (S-10 "authoritative settlement version
   references and lifecycle integrity").
4. **Publish trigger** fills the frozen window and real mode, so every publication
   path (service, tests, future jobs) freezes them.
5. **Operator full-time corrections need `completed_at`** when no provider final was
   recorded by the cutoff — a direct consequence of S-03.
6. **Material score conflicts keep the first final score** pending an audited
   correction (S-05 "rather than silently replacing authoritative verdicts").

### 23.9 Limitations and open items
* The provider's multi-ID request is implemented to its documented contract but not
  exercised live (no live calls authorised).
* Development corrections, alert resolutions and reopening evaluate at the database
  clock (only settlement runs and finalisation accept the development time
  override); development scenarios for those flows use short real cutoffs.
* `personal_result` is the service boundary for Stage F; no UI yet.
* CLI commands (and the interactive Supabase password check that will build the
  principal with fresh `authenticated_at` / `reauthenticated_at`) are Stage E; until
  then the existing `cli_principal` is unchanged and no settlement command exists.
* Score sets, ranks, points, championships: 6C.5. Scheduling and admin UI: 6C.6.
* D-29 and D-36 remain outstanding.

### 23.10 Remaining work (Stages E–G, not started)
* **E:** CLI commands for import, show, preview, settle, alerts, correct, withdraw,
  resolve, invalidate, finalise, reopen (owner), `set-mode`, `dev-results
  scenario`; interactive `getpass` password verification through Supabase Auth per
  command (S-07); no secrets in argv, logs or audit.
* **F:** My Challenge results panel per §14 and S-11.
* **G:** full regression, browser journeys, performance on the owner's machine,
  documentation and the Mac acceptance guide.
