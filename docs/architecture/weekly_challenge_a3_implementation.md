# Weekly Challenge Scenario A3 — implementation record

**Owner decision (approved after independent review):** Scenario A3, configuration
version `a3-432-v1`: Foundation 60%–90% (both ends included), Balanced 40% to under 60%,
Challenger 10% to under 40%, by margin-adjusted market probability. Unchanged:
* 4 / 3 / 2 selections on nine distinct fixtures;
* the nine-fold and 40 / 30 / 20 / 10 credits;
* D-31 scoring;
* consensus and quote rules;
* the D-28 opening checks;
* the existing bucket completion probabilities.

Approved alongside: general Goal Model guidance, and a high-risk underdog warning for a
**selected** outcome whose market-implied probability is 10% to under 20%. Migration
`app_0008` is accepted in principle as the activation mechanism but **not authorised for
execution**. Evidence:
[`../research/weekly_challenge_bucket_review.md`](../research/weekly_challenge_bucket_review.md).

| Checkpoint | Scope | Status |
|---|---|---|
| R | Research preservation | done (`b01e057`, CI run 145 passed) |
| 1 | Version-aware application; `broad60-432-v1` stays the only configuration | this record |
| 2 | Register `a3-432-v1` (inactive) | not started; needs owner approval |
| 3 | Guidance and underdog warning | not started |
| 4 | Activation (`app_0008`, default switch, docs) | not started; migration not authorised |
| 5 | Final verification | not started |

## Checkpoint 1: version-aware application

**Rule:** every round, snapshot, draft, entry and settlement resolves the configuration
it is bound to. Production code never falls back to `DEFAULT_CONFIG` for them.

| Resolver | Use |
|---|---|
| `RoundSnapshot.config` | `get_config(snapshot.config_version)`; unknown versions raise `ConfigError` |
| `rounds.round_config(conn, round_id)` | the version recorded at publication, else (draft) the version of the round's **own** schedule row |
| `rounds.schedule_config(conn, code)` | what a round created now would use (same selection as `create_round`, via `_current_schedule`) |
| `get_config(entry["config"])` (`pages.entry_config`) | stored entries (confirmed and locked cards) |
| `REQUIRED_SELECTIONS`, `TOTAL_CREDITS` | validated invariants of every configuration (9 selections, 100 credits) |

### Audit of `DEFAULT_CONFIG` dependencies

| Area | Before | After |
|---|---|---|
| Backend services (rounds, entries, drafts, snapshots) | already round-aware | unchanged; `drafts.validate_selections` now **requires** a configuration |
| Draft adoption (`adoption.py`, 2 calls) | default | the published snapshot's configuration |
| Settlement (`settlement.py`) | `settle_entry` default | the round's `config_version`; `EntrySettlement` records the recovery target |
| Prepare job (`jobs/prepare.py`) | `build_live_snapshot` default | the draft's own configuration (`round_config`), passed to the snapshot builder |
| CLI `round readiness` / `publish` (`cli.py`) | default | `round_config` |
| CLI `round dev-open`, dev championship, F2 e2e tool | default | `schedule_config` (what `create_round` binds the new round to) |
| Dev data (`devdata.py`) | labelled with the default | optional `config`; the default applies only to free-standing synthetic data |
| Settlement scenarios (`settlement_scenarios.py`) | default | the snapshot's configuration |
| Dash builder, fixture list, outcome states, tracker, analysis, review, confirm (`pages`, `callbacks`, `service`, `persist`, `state`, `integration`) | `DEFAULT_CONFIG` / `CFG` | the snapshot's configuration. Confirmation no longer compares with the default; an unknown version is refused |
| Band labels and eligibility messages (`components`, `callbacks`) | hard-coded "60%–95%", "20%–95%" | derived from the configuration (`band_text`, `eligible_range_text`) |
| Confirmed and locked entry cards; results panel (`pages`, `results_ui`) | default | the entry's stored version, and the stakes from its frozen settlement |
| State labels (`charts`, payouts section) | default | bucket names carried by the evaluation (from the portfolio's configuration) |
| Phase 6C.3 tools (`phase6c3_demo.py`, `phase6c3_quant_regression.py`) | default | the snapshot's configuration |

### Remaining legitimate default uses (allowlisted in `tests/test_config_version_guard.py`)

| Where | Why |
|---|---|
| `challenge/config.py` | the definition |
| Library default parameters (`structured.py` ×7, `analysis.py` ×2, `settle.py`) | pure functions keep their defaults for tests and research; every production call passes a configuration (guarded) |
| `roundsheet.snapshot_from_research_pool` / `build_live_snapshot` defaults | constructing a **new** snapshot with no round; production callers pass one (guarded) |
| `education.illustrate` | free-standing illustration, not tied to a round |
| `devdata.dev_snapshot` / `mirror_snapshot` | free-standing synthetic data; round-creating callers pass `config=` (guarded) |
| `app/challenge/service.py` (×2) | the prototype live snapshot and the demonstration round: new snapshots with no round record |
| `pages.rules_config` | explanatory text when no round exists at all |

**Guard:** `tests/test_config_version_guard.py` fails if:
* a new `DEFAULT_CONFIG` reference appears outside the allowlist;
* `DEFAULT_CONFIG` is imported under an alias;
* a production call relies on a default `config` argument;
* a registered configuration renames a bucket (presentation uses static bucket names).

### Verification (Checkpoint 1)

* v1 behaviour unchanged:
  * the `broad60-432-v1` fingerprint is identical before and after (and pinned in a test);
  * 17 Weekly Challenge views rendered for the demonstration round are byte-identical
    before and after (builder, fixture list, outcome states, tracker, analysis, review,
    how to play, round facts, confirmed and locked cards, ineligible-outcome text);
  * the Phase 6C.3 quantitative regression output (1.47 MB) is byte-identical.
* Fail-safe: unknown snapshot, round, schedule or entry versions raise `ConfigError`.
  The published-round loader already refuses unregistered versions ("temporarily
  unavailable").
* Draft binding (PostgreSQL): a draft keeps its schedule row's configuration after a
  newer schedule version exists, and publishes normally with a snapshot built for it. A
  snapshot for another configuration is refused.

## Requirements recorded for later checkpoints (not implemented)

1. **Activation boundary (Checkpoint 4):**
   * schedule validity and activation timestamps use explicit UTC semantics
     (`timestamptz`, timestamps given with a UTC offset or `Z`, never local or naive time);
   * validity periods of one schedule code neither overlap nor leave unintended gaps
     (`active_to` of version *n* equals `active_from` of version *n + 1*), enforced by a
     test and, if approved, a database constraint;
   * `active_from` is an explicit owner-approved timestamp, not `now()`;
   * round creation selects the schedule version **valid at the creation time** (today:
     the latest version). `_current_schedule` is the single place to change, so creation
     and `schedule_config` stay identical.
2. **Rounds at activation:**

   | Round state | Effect |
   |---|---|
   | Published or completed | unaffected |
   | Draft | keeps its own schedule row and configuration (proved in Checkpoint 1) |
   | Created at or after `active_from` | A3 |

   The downgrade is refused once any round references the new schedule row.
3. **Historical reproducibility (Checkpoint 2):**
   * pin the v1 fingerprint (done);
   * the settlement regression must compare existing v1 entries against their
     **original expected results** (frozen eight-state payouts and settled gross from the
     committed fixtures), not merely compare results under two configurations.
4. **Fail safely:** unknown or unregistered round configuration versions must fail, never
   fall back to `DEFAULT_CONFIG` (implemented in Checkpoint 1 and guarded).
   `broad60-432-v1` and, once registered, `a3-432-v1` stay registered permanently.
5. **Warning on the selected outcome (Checkpoint 3):** triggered by the selected
   outcome's own market-implied probability (10% ≤ p < 20%) when that outcome is eligible
   under the round's configuration; never by fixture-level presence. Tests include a
   fixture with an in-band outcome that is not selected.

## Deferred tests (need A3 registration or activation)

* A3 exact boundaries (0.10, 0.40, 0.60, 0.90 and their neighbours), no overlap, and the
  exclusions below 10% and above 90%.
* The A3 fingerprint pinned; A3 identical to v1 except the two bands.
* The committed real pool under A3: +36 Challenger outcomes and +3 fixtures on
  20–23 Nov; opening unchanged.
* Open v1 rounds confirmable after activation; new rounds created under A3; migration
  upgrade and downgrade (Checkpoint 4).
* Warning display at the 0.10, 0.1999… and 0.20 boundaries, driven by the market
  probability (Checkpoint 3).
* The historical v1 settlement regression against original expected results
  (Checkpoint 2).
