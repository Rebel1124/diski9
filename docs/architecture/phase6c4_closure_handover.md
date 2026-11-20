# Phase 6C.4 — Closure handover and Phase 6C.5 starting point

**Status (20 Nov 2026):** Phase 6C.4 (settlement, voids and corrections, Stages
A–G) is **formally accepted** by the product owner (20 Nov 2026) after local
acceptance testing on the owner's Mac, and released as the **v4.2.0** development
milestone (merged into `main`; release notes [`../releases/v4.2.0.md`](../releases/v4.2.0.md)).
The items in §5 are accepted as deferred work; D-29 and D-36 remain outstanding
requirements. **Phase 6C.5 (leaderboards and championships) is the next phase** and
has **not** started: it begins from the v4.2.0 baseline after a separate owner
authorisation.

This document is the durable starting point after context compaction. Read it with:

| Document | Role |
|---|---|
| [`phase6c4_implementation.md`](phase6c4_implementation.md) | Full implementation record: Stage A assessment (§1–§21), approved decisions (§22), Stages B–D (§23), Stages E–G and acceptance fixes (§24), owner acceptance (§25) |
| [`../product/weekly_challenge_decisions.md`](../product/weekly_challenge_decisions.md) | Decision register (authoritative); S-01 to S-11 for settlement |
| [`../product/weekly_challenge_settle_v1.md`](../product/weekly_challenge_settle_v1.md) | `settle/v1` as amended on 19 Nov 2026 |
| [`../product/weekly_challenge_phase6c_plan.md`](../product/weekly_challenge_phase6c_plan.md) | Stage plan 6C.0–6C.6 and the deferred backlog |
| [`../operator_settlement_cli.md`](../operator_settlement_cli.md) | Operator commands, scenario catalogue, security rules, operational notes |
| [`../phase6c4_local_acceptance_mac.md`](../phase6c4_local_acceptance_mac.md) | Owner's local testing guide |

## 1. Final verification

| Item | Value |
|---|---|
| Accepted feature head | `feature/phase-6c4-settlement` at `1baade7` (acceptance record on top of `a7a310c`) |
| Merge into `main` | `02f10f8` (`--no-ff`, no conflicts; tree identical to the feature head); release commit and tag `v4.2.0` follow it |
| Release baseline | full suite on the final code: **1,481 passed, 0 failed, 0 skipped** (real PostgreSQL, local Supabase Auth, browser tests) |
| CI on the final code | run 48 (`a7a310c`) passed; release-baseline results in the release notes |
| Migrations | `app_0001`–`app_0006`; `app_0006` downgrade refused once settlement data exists (deliberate) |
| Quantitative regression | `tools/phase6c3_quant_regression.py` SHA-256 `88bcd717deca6c1c…`, byte-identical to v4.1.0 |
| Protected areas | engine, ingestion, research and odds modules unchanged since v4.1.0 (two new files only: `challenge/settle.py`, `ingestion/results_fetch.py`) |
| Live provider check | 3 of 5 authorised requests; multi-ID contract confirmed (≤ 20 IDs) |

## 2. Owner's local acceptance (recorded as reported, 20 Nov 2026)

The owner tested on the Mac with the guide: upgrade `app_0005` → `app_0006` after a
backup; interactive operator password check; confirm, deadline and lock; partial
settlement; complete provisional settlement; material correction; finalisation
(development `--as-of`); owner reopening; whole-round operator invalidation. The
owner reported the results "logically consistent" and approved Phase 6C.4,
Stages A–G, noting that issues found later are addressed along the roadmap.

Two issues raised during acceptance were fixed before acceptance (§24.11 of the
record):
1. An entry fully settled while other entries were still pending showed "Partly
   settled" and a definitive net → new state **Settled · round check pending**; net,
   like recovery, waits for the round's validity check.
2. After a withdrawal the builder still showed the withdrawn predictions →
   withdrawal now clears the saved predictions in the same transaction (T-09
   clarified).

## 3. What Phase 6C.4 delivers (for 6C.5)

* **Evidence:** `result_observations` (provider, operator, synthetic; insert-only,
  mode-scoped). By-ID import (`results import`), corrections and withdrawals.
* **Settlement:** per selection `selection_verdicts` (rule, evidence, materiality),
  per entry `entry_settlements` (gross, net, legs and accumulators, `complete`,
  `basis` incl. `all_void`), per round `round_evaluations` (D-32b),
  `designations` (current designation; `provisional` false once final),
  `settlement_versions` (provisional / final / reopened), `settlement_alerts`.
* **Rank eligibility (D-32b, D-33):** an entry is rank-eligible when complete and not
  all-void and the round is not void; exposed by `participant_results.my_settlement`
  (owner-scoped) and computable from the tables above. **No ranks, points or
  championships exist yet** (6C.5).
* **Lifecycle:** `locked → settling → final`; owner-only reopening (`round.reopen`)
  returns a final round to `settling` and writes a new version. S-06: championship
  recalculation after a reopening belongs to 6C.5.
* **Development rounds** never join the official series; 6C.5 must keep them out of
  beta championship membership too.

## 4. Approved inputs for 6C.5 (do not reopen)

D-26 and D-31 (weekly ranks and points), D-27 and D-30 (championship membership and
standings), D-38 (beta and official series), T-07/T-08 and D-28 (competitive versus
practice), D-32b (round invalidation), D-33 (all-void refunds are not rank-eligible),
S-06 (finalised rounds; reopening; championship recalculation in 6C.5), S-09
(authoritative settlement versions feed 6C.5), T-20 (most recent entry card; full
history in 6C.5). The 6C.5 section of the Phase 6C plan lists objectives, modules,
acceptance criteria and risks.

## 5. Outstanding requirements and accepted deferred items

| Item | Target |
|---|---|
| **D-29** validation on 6–8 real weekly pools (research collector) | before Official Championship 1 |
| **D-36** data retention policy | before launch |
| **S-07** follow-up: the 6C.3 `round create / publish / lock / dev-open` commands still accept `--by-email` without a password (settlement commands require it) | 6C.6 |
| Production scheduling (publish, lock, results import with a full re-check, settle, finalise), monitoring, alerting, administration interface, backup and restore | 6C.6 |
| Hosted Supabase acceptance (the CLI and auth tests run against the local harness and, in CI, the official Supabase Auth image) | Phase 10 |
| `settle run` has no `--confirm` (deliberate: idempotent recomputation from evidence; corrections, invalidation and reopening keep preview + confirmation) | documented; revisit in 6C.6 if wanted |
| Development time overrides only for settlement runs and finalisation; corrections, alert resolutions and reopening always use the database clock; `cutoff-boundary` / `late-notification` evidence at the real cutoff needs `settle run --as-of` | documented limitation |
| Full historical entry browsing (current round and the most recent entry only) | 6C.5 |
| Post-finalisation changes are detected only when new evidence arrives (`post_final_change`); no historical monitoring | by design; 6C.6 for scheduling |
| From the 6C.3 backlog: Screener reload latency and direct fixture URLs (6D); CLI tracebacks in the 6C.3 round commands (6C.6); Your View freezing at confirmation (later decision, D-41) | unchanged |

## 6. Roadmap (approved; unchanged)

6C.0 ✓ · 6C.1 ✓ · 6C.2 ✓ · 6C.3 ✓ (v4.1.0) · **6C.4 settlement, voids and
corrections ✓ (accepted; v4.2.0)** · **6C.5 leaderboards and championships (next)** ·
6C.6 administration, scheduling and monitoring · 6D integration, optimisation and
comprehensive testing · 7 Lucy and LiveKit · 8 European competition expansion ·
9 badges and achievements · 10 deployment and private beta · 11 public launch and
YouTube.

## 7. Independent processes (not modified by this work)

| Process | Status (20 Nov 2026) |
|---|---|
| Research collector capture `trig_01R8pEXhrpsehX82xPKZcY2Z` (Fri 08:00 SAST) | enabled; first real capture Fri 27 Nov 2026 |
| Research collector results `trig_01NBMtRe7Y3WhtibZ2ah6Cdq` (daily 09:15 SAST) | enabled; starts 28 Nov 2026 |
| One-off verification `trig_01NsZ4MAkCRJt8j1YJKVDeBj` | Fri 27 Nov 2026 09:30 SAST, read-only checks of the first capture |
| Odds trial `trig_01T4GYs8Nma5ERz7NiEQpUhx` | running until 2026-11-21 15:00 UTC on `claude/gifted-newton-h6o5hk`; disables itself after the end |

## 8. Resuming

1. Start from `main` at the v4.2.0 tag; branch for 6C.5 only after the owner's
   authorisation (suggested: `feature/phase-6c5-leaderboards`).
2. Local services for tests: PostgreSQL (test database URL in
   `DISKI9_APP_TEST_DATABASE_URL`) and the local Supabase Auth harness
   (`tools/local_auth/local_auth.py`, settings in `tmp/local_auth/env`), as in the
   Phase 6C.2 guide.
3. Quantitative regression must stay byte-identical (`tools/phase6c3_quant_regression.py`).
4. Do not change approved competition mathematics or reopen S-01 to S-11.
