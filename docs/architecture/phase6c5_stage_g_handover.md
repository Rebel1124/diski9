# Phase 6C.5 — Stage G owner acceptance and closure record

**Status: Stage G closed; Phase 6C.5 complete (owner acceptance, 21 Nov 2026).**
Prepared at the end of Stage F4 as the handover and updated with the owner's Stage G
decisions (§G). Accepting Phase 6C.5 completes **no** release gate (§C.4, §D).
Nothing has been merged, tagged, released, deployed or activated; Phase 6C.6 is not
authorised.

| | |
|---|---|
| Branch | `feature/phase-6c5-leaderboards` (`Rebel1124/diski9`) |
| Accepted baseline | F4: `f0ac3c2`, CI run 81 passed (Stage G adds documentation only); application code identical to the accepted F3 baseline `c2583c3` |
| Migration head | `app_0007` |
| Quantitative fingerprint | `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4` (unchanged since before 6C.5) |
| Weekly Challenge configuration | `broad60-432-v1`: Foundation 60–95 %, Balanced 40–<60 %, Challenger 20–<40 %; picks 4/3/2; credits 40/30/20/10 |
| Scoring | `points-150-75-v2`; ten counted rounds per championship |
| Records | [`phase6c5_implementation.md`](phase6c5_implementation.md) (§1–§9), [`phase6c5_design_specification.md`](phase6c5_design_specification.md), [`../product/weekly_challenge_decisions.md`](../product/weekly_challenge_decisions.md), [`../product/weekly_challenge_phase6c_plan.md`](../product/weekly_challenge_phase6c_plan.md) |

---

## A. Phase 6C.5 delivery summary

| Stage | Outcome | Closed |
|---|---|---|
| A | Design specification approved: decisions CH-01 to CH-12 and D-30a; private mini-leagues removed from the MVP | 20 Nov 2026 |
| B | Weekly results and publication: score sets from the authoritative settlement, standard competition ranking with shared ranks, `points-150-75-v2`, provisional and official boards, practice / void / refund handling (D-32b, D-33) | 20 Nov 2026 (`ccd7c4e`) |
| C | Championship lifecycle: streams (Development, Beta, Official), stored membership and roles, ten counted rounds, start dates and naming, completion, joint and no champions, versioned standings, rollover, `app_0007` | 20 Nov 2026 (`3999974`) |
| D | Corrections: reopening (Under Review), re-finalisation, recalculation of championship versions, historical corrections including D-30a, integrity inspection and repair | 20 Nov 2026 (`65a1440`) |
| E | Leaderboards and History UI: weekly and championship boards, all round states, "=n" shared ranks, pagination with "Go to my position", podium, My Challenge Current and History, statistics and charts, drill-downs | 21 Nov 2026 (`e820790`) |
| F1 | Development tooling: development participants, bulk test entries, resumable ten-round development championships (500-participant safeguard) | 21 Nov 2026 (`8379606`) |
| F2 | Integration and security: privacy and stream-isolation tests, S-07 assessment, 12 browser journeys at three widths, Current states; four presentation defects fixed | 21 Nov 2026 (`7afc03b`) |
| F3 | Performance and concurrency: 100 / 1,000 / 10,000 datasets, §14 benchmarks, multi-worker HTTP, concurrent readers and writers; fixed F3-1 (backlog), F3-2 (deadlock), F3-3 (O(page) queries) | 21 Nov 2026 (`c2583c3`) |
| F4 | Final regression, stability and handover: Match Lab intermittent test root-caused and fixed (test synchronisation), full regression, journeys and F3 re-run, integrity tool and verification | 21 Nov 2026 (`f0ac3c2`) |
| G | Owner acceptance (decisions G-1 to G-5, §G) | 21 Nov 2026 |

No competition rule, probability bucket, scoring, settlement or championship rule was
changed after its approval.

## B. Acceptance evidence (F4 release candidate)

1. **Regression:** 1,682 passed, 0 failed, 0 skipped (real PostgreSQL 16, local
   Supabase Auth, browser tests; 28 min). Focused F3 concurrency, page-equivalence
   and Match Lab files: 26 passed. Record §9.2.
2. **Intermittent Match Lab test:** reproduced (3/15 failures with the CPUs
   saturated), diagnosed from logged Dash traffic (fixed sleeps outrun by a debounced
   callback and a late detail rebuild), fixed by waiting for the specific callback
   responses; 40/40 under saturation. Record §9.1.
3. **Browser:** 12 journeys × 3 widths, 253 checks, 0 problems; 5 Current states × 3
   widths, 0 problems; 0 server exceptions. Record §9.3.
4. **Performance:** every applicable §14 target passes except the Dash leaderboards
   page load (signed-in 704–727 ms, accepted limitation; guest 586–635 ms, at the
   boundary). Comparison with F3 in record §9.4.
5. **Concurrency:** 0 errors and 0 unexpected states for readers during publication
   and during correction / re-finalisation; same-round finalisers produce one
   finalisation; boundary races 100/100 with 0 deadlocks; cache staleness ≤ 1.93 s
   (contract 3 s).
6. **Data integrity:** six isolated databases consistent on every check, including
   stored standings against version hashes, ranks, refunds and voids, audit
   attribution and stream isolation; negative control detects deliberate corruption;
   no Official stream active. Record §9.5.
7. **CI:** run 79 (`c2583c3`, F3 baseline), run 80 (`0570220`, F4 test fix) and
   run 81 (`f0ac3c2`, F4 baseline) passed.
8. **Protected baselines:** unchanged (record §9.6).

## C. Outstanding limitations

### C.0 Accepted and completed
Phase 6C.5 functionality — weekly leaderboards (provisional and official, shared
ranks, points), the championship lifecycle (streams, membership, progression,
completion, rollover, joint and no champions, versions), corrections (Under Review,
re-finalisation, historical corrections, D-30a), History, My Challenge and the
supporting read and integrity services — is **accepted and complete** (G-1).

### C.1 Accepted limitations (owner-accepted, G-2 and G-4; not blockers for 6C.5)
* **Signed-in Dash leaderboards page load** above the 600 ms target (F3 653 ms; F4
  704–727 ms). Cause: the Dash page shell fires ~17 Screener callbacks on every page;
  competition reads are ~35–40 ms of it. No Screener redesign authorised.
* **Guest Dash leaderboards page load variability** around the 600 ms target (F3
  594 ms; F4 586–635 ms). Targets unchanged; neither result is reclassified as a
  pass.
* **F3 scalability limitations:** at 10,000 participants the uncached provisional
  page (~550 ms) and History (~17–22 ms) carry whole-set work; reopening with nine
  corrections takes ~2 minutes; process-local caches grow with workers; all figures
  are from one shared 4-vCPU machine. **The local evidence does not establish
  production scalability, hosted Supabase readiness or deployment readiness (G-4).**
* Earlier-stage limitations (record §4.8, §5.10, Stage E handover §8): an operator
  invalidation cannot be reversed; membership verified structurally, not by full
  replay; round labels can coincide (codes distinguish them).

### C.2 Deferred improvements (not defects)
* History shared-rank count O(page) (the F3-3 neighbour rule); deferred by the owner
  unless needed.
* Screener callbacks on non-Screener pages (the page-load limitation).
* `inspect_stream` could also compare stored standing rows with the version hash
  (F4's integrity tool does; a candidate for 6C.6 monitoring).
* Leaderboards use U+2212 minus, result cards a hyphen-minus (cosmetic).

### C.3 Known defects scheduled for remediation (G-3)
* **ML-01 Match Lab stale-adjustment race — low severity; fix required before
  private beta.**
  - *Failure scenario:* a match-detail rebuild (`update_detail`, after a market
    change) is still in flight when the participant clicks Reset or edits a Section
    B, C or D adjustment; its response arrives last, writes `lab-store` from its
    request-time value, and the rebuilt inputs restore the earlier adjustment.
    Needs a slow server, network or device and an action inside that window.
  - *Impact:* browser-side what-if adjustments and the saved Your View only (no
    effect on entries, settlement, scoring, championships or leaderboards), but a
    removed adjustment can reappear, which undermines user confidence and the
    accuracy of the displayed what-if figures.
  - *Requirement:* a narrowly scoped fix with deterministic regression coverage of
    the late-response ordering; **target: completed before private beta testing
    with real users**; not implemented in Stage G. Register: Phase 6C plan,
    "Outstanding work accepted at the 6C.5 closure".
* No competition-logic defect is open.

### C.4 Mandatory security, operational, hosting and release gates (all open, G-5)
* **S-07:** operator CLI commands that identify the operator by e-mail without a
  password (`round create/publish/lock/dev-open`, `account grant-role/...`) —
  remediation is **mandatory in Phase 6C.6** before any hosted deployment or Official
  activation (record §7.2).
* **D-38 Official activation requirements** (with D-29 real weekly pool validation).
  **No Official competition stream is authorised for activation.**
* **Genuine Beta finalisation** under the real deadline-plus-24-hour rule
  (development time overrides do not prove it).
* **Hosted Supabase authentication acceptance.**
* **D-36 account deletion workflow** (retention and pseudonymisation) before
  hosting real participants.

## D. Outstanding roadmap and release gates (carried forward; none completed by 6C.5 testing)

| Item | Where | Gate |
|---|---|---|
| S-07 CLI operator-authentication remediation | Phase 6C.6 | before hosted deployment or Official activation |
| Genuine Beta finalisation (deadline + 24 h) | later acceptance | before relying on Beta results |
| D-29 real weekly pool validation | before the official series (the separate odds trial ends 21 Nov 2026 15:00 UTC; its result is evidence for D-29, not a substitute) | before Official |
| D-36 account deletion workflow | before hosting real participants | before hosting |
| D-38 Official activation requirements | Official series start | before Official |
| Hosted Supabase authentication acceptance | hosting | before hosting |
| Relevant Phase 6C.3 backlog items | 6C.6 / later | per backlog |
| ML-01 Match Lab stale-adjustment race (C.3) | targeted maintenance fix | **before private beta** |
| Accepted signed-in page-load limitation | documented | none |
| Match Lab test stability | resolved in F4 (test synchronisation; 40/40 under load); monitor in CI | none |

Private mini-leagues remain excluded. Phase 6C.6 (administration, scheduling and
monitoring) and 6D require separate authorisation.

## E. Stage G acceptance recommendation (as submitted at F4; accepted, §G)

**Recommendation: Phase 6C.5 is ready for owner acceptance (Stage G), with the
qualifications below.**

Justification: every approved requirement of Stages A–E is implemented and covered;
the integrated application passes the full regression with no failures or skips,
the repeated browser journeys with no problems, the F3 performance and concurrency
re-run with no errors or inconsistent states, and a negative-controlled integrity
verification; the one intermittent test is root-caused and fixed without weakening;
the fingerprint, migration head and competition rules are unchanged.

Qualifications:
1. Acceptance covers the local, single-machine evidence only; production performance
   and hosted operation are not established.
2. The signed-in page-load miss is accepted as a limitation; the guest page load is at
   the target boundary.
3. The Match Lab stale-rebuild defect (C.3) is open at low severity.
4. The release gates in §C.4 and §D remain open and must not be treated as satisfied
   by 6C.5 acceptance; in particular S-07 before any hosted deployment or Official
   activation, and no Official series activation.

## F. Stage G acceptance checklist

- [x] Handover and implementation record §9 (F4) and §8.13 (F3 closure) reviewed by
      the owner.
- [x] F4 baseline confirmed: `f0ac3c2`, CI run 81, local and remote equal.
- [ ] *Optional, owner's machine:* read-only fingerprint
      (`uv run python tools/phase6c3_quant_regression.py 2>/dev/null | shasum -a 256`
      → `88bcd717deca6c1c…`).
- [ ] *Optional, owner's machine:* walkthrough on the acceptance database
      (`docs/phase6c5_local_acceptance_mac.md`).
- [x] ML-01 decided: known low-severity defect, fix scheduled before private beta.
- [x] Accepted limitations (§C.1) and open release gates (§C.4, §D) confirmed.
- [x] Stage G closed and Phase 6C.5 complete (21 Nov 2026).
- [ ] Merge, tag or release: **not authorised** (separate owner decision).

## G. Owner decisions at Stage G (21 Nov 2026)

* **F4 formally closed** at `f0ac3c2` (CI run 81; 1,682 passed, 0 failed, 0 skipped;
  12 journeys, 253 checks, 0 problems; Match Lab test 40/40 under CPU saturation;
  `app_0007`; fingerprint unchanged). Application code unchanged from `c2583c3`; no
  rule, bucket or scoring change.
* **G-1 Functional acceptance** of the Phase 6C.5 functionality (§C.0).
* **G-2 Performance limitations** accepted (§C.1); targets and measurements retained,
  misses not reclassified as passes.
* **G-3 ML-01** accepted as a known low-severity defect; targeted fix with regression
  coverage before private beta; not implemented in Stage G (§C.3).
* **G-4** Local evidence accepted; production scalability, hosted Supabase readiness
  and deployment readiness not established.
* **G-5** All release gates remain open (§C.4, §D); S-07 mandatory in 6C.6 before any
  hosted deployment or Official activation; no Official stream authorised.
* **Unchanged technical baseline:** `broad60-432-v1` (Foundation 60–95 %, Balanced
  40–<60 %, Challenger 20–<40 %), picks 4/3/2, credits 40/30/20/10,
  `points-150-75-v2` and the championship rules, Development / Beta / Official
  isolation, `app_0007`, the fingerprint.
* **Not authorised:** Phase 6C.6 implementation, the ML-01 fix, merge or tag,
  deployment or hosted activation, Official activation, rule or configuration
  changes, changes to protected databases.

## H. Recommended Phase 6C.6 priorities (planning only; not authorised)

1. **S-07 operator-authentication remediation (first, release gate).** Bring the
   e-mail-identified commands (`round create/publish/lock/dev-open`, `account
   grant-role/revoke-role/grant-feature/revoke-feature/suspend/reinstate`) under
   `authenticate_operator` with password and T-14 recency; remove or restrict
   `--by-email`; tests through the real CLI (the F2 characterisation tests become
   the regression baseline).
2. **Production scheduling.** Publish, lock, `results import --full` before
   finalisation, settle, finalise (after the real deadline + 24 h) and championship
   processing as idempotent, locked, audited jobs with retries; this also provides
   the genuine Beta finalisation evidence.
3. **Monitoring and alerting.** Job health, settlement alerts, `inspect_stream` and
   the F4 integrity checks (including stored standings against version hashes) on a
   schedule, with alerts for failed or stuck rounds and Under Review championships.
4. **Operational administration.** An authorised operator interface or hardened CLI
   for reopenings, corrections, role and feature management, with clear one-line
   errors (6C.3 backlog: CLI tracebacks) and complete audit.
5. **Readiness work feeding later gates:** D-38 Official activation checklist, D-29
   pool-validation reporting, D-36 deletion workflow design, and a hosted Supabase
   acceptance plan (Phase 10).
6. **Maintenance before private beta:** ML-01 (separately authorised, as decided).
