# Phase 6C.5 — Stage G owner-acceptance handover

**Status:** prepared at the end of Stage F4 (21 Nov 2026) for the owner's Stage G
review. Stage G is **not** closed by this document; Phase 6C.6 is not started.
Nothing has been merged, tagged, deployed or activated.

| | |
|---|---|
| Branch | `feature/phase-6c5-leaderboards` (`Rebel1124/diski9`) |
| Release candidate | the F4 checkpoint commit (see §B.6); application code identical to the accepted F3 baseline `c2583c3` |
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
| F4 | Final regression, stability and handover: Match Lab intermittent test root-caused and fixed (test synchronisation), full regression, journeys and F3 re-run, integrity tool and verification | checkpoint (this document) |

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
7. **CI:** run 79 (`c2583c3`, F3 baseline) and run 80 (`0570220`, F4 test fix)
   passed; the final F4 commit's run is reported in the F4 checkpoint report.
8. **Protected baselines:** unchanged (record §9.6).

## C. Outstanding limitations

### C.1 Accepted limitations (owner-accepted; not blockers for 6C.5)
* **Signed-in Dash leaderboards page load** above the 600 ms target (F3 653 ms; F4
  704–727 ms). Cause: the Dash page shell fires ~17 Screener callbacks on every page;
  competition reads are ~35–40 ms of it. No Screener redesign authorised. The guest
  page load is at the boundary (F4 586–635 ms).
* **F3 scalability limitations:** at 10,000 participants the uncached provisional
  page (~550 ms) and History (~17–22 ms) carry whole-set work; reopening with nine
  corrections takes ~2 minutes; process-local caches grow with workers; all figures
  are from one shared 4-vCPU machine. **Production performance is not established.**
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

### C.3 Known defects
* **Match Lab stale detail rebuild (low severity; found in F4, not fixed).** A detail
  rebuild still in flight after a market change can, when its response arrives last,
  restore the previous Match Lab adjustment after the participant clicked Reset or
  edited one (`update_detail` writes `lab-store` from its request-time value). Needs a
  slow server or device and an action inside that window. Browser-side what-if
  adjustments only; no effect on entries, settlement, scoring, championships or
  leaderboards. Recommended: a scoped Match Lab maintenance fix (separate approval).
* No competition-logic defect is open.

### C.4 Mandatory pre-hosting or pre-release blockers
* **S-07:** operator CLI commands that identify the operator by e-mail without a
  password (`round create/publish/lock/dev-open`, `account grant-role/...`) —
  remediation is **mandatory in Phase 6C.6** before any hosted deployment or Official
  activation (record §7.2).
* **D-38 Official activation requirements** (with D-29 real weekly pool validation).
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
| Match Lab stale-rebuild defect (C.3) | Match Lab maintenance | none (low severity) |
| Accepted signed-in page-load limitation | documented | none |
| Match Lab test stability | resolved in F4 (test synchronisation; 40/40 under load); monitor in CI | none |

Private mini-leagues remain excluded. Phase 6C.6 (administration, scheduling and
monitoring) and 6D require separate authorisation.

## E. Stage G acceptance recommendation

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

## F. Stage G acceptance checklist (for the owner)

- [ ] Review this handover and implementation record §9 (F4) and §8.13 (F3 closure).
- [ ] Confirm the F4 checkpoint commit, its CI run, and that local and remote match.
- [ ] Optionally repeat the read-only fingerprint on your machine
      (`uv run python tools/phase6c3_quant_regression.py 2>/dev/null | shasum -a 256`
      → `88bcd717deca6c1c…`).
- [ ] Optionally walk through the leaderboards, championships, History and My
      Challenge on your acceptance database (`docs/phase6c5_local_acceptance_mac.md`).
- [ ] Decide on the Match Lab stale-rebuild defect (accept as known / schedule a fix).
- [ ] Confirm the accepted limitations (§C.1) and the carried release gates (§C.4, §D).
- [ ] Decide on Stage G closure, and separately on any merge, tag or release.
