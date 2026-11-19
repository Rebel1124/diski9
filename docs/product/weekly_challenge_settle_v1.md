# D-08 — Settlement rules `settle/v1`: exact definitions (for approval)

**Status: approved (D-08, Phase 6C.0/6C.1 approval), with the additional requirements recorded in the decision register; implemented in Phase 6C.4.** **Amended 19 Nov 2026 (owner approval at the Phase 6C.4 Stage A review, decisions Q-3, Q-4/Q-11 and Q-5 in the register):** the cutoff is completion-based (§2), V3 has two recorded branches (§3), and the evidence rules are in §2a. The amendment removes the earlier conflict between the kickoff-based wording here and the completion-based D-08 requirements; it does not change the cutoff, the void codes or the verdict order. Original status: proposed for final approval. The owner has accepted the 48-hour
cutoff in principle and asked for the exact void definitions and the event the
cutoff is measured from. The payout treatment of voids is already approved
(D-32 partial voids, D-33 fully void entries, D-32b whole rounds); this note only
decides **which verdict** each prediction receives.

## 1. Inputs

For each fixture on a round sheet, settlement uses only:
* the round's `deadline_at` and `settle_cutoff_at`, both fixed at publish;
* the fixture's **result observations** (insert-only; provider observations and
  audited operator corrections, D-35): status code, scheduled kickoff, the
  90-minute score (`ft_home`, `ft_away`, from the provider's `score.fulltime`),
  the time **we** recorded each observation, and, where available, the provider's
  first-half start time (supporting evidence only) and operator-verified actual
  event times (§2a).

The provider (API-Football) status codes used below:

| Group | Codes | Meaning |
|---|---|---|
| Not started | `TBD`, `NS` | Time to be defined; not started |
| In play | `1H`, `HT`, `2H`, `ET`, `BT`, `P`, `LIVE` | Live, including extra time, break and penalties |
| Interrupted | `SUSP`, `INT` | Suspended; interrupted |
| Final, played | `FT`, `AET`, `PEN` | Finished in 90 minutes; after extra time; after penalties |
| Final, not played | `PST`, `CANC`, `ABD`, `AWD`, `WO` | Postponed; cancelled; abandoned; technical loss (awarded); walkover |

Unknown or new codes are treated as **pending** and raise an operator alert.

## 2. The settlement cutoff

> **`settle_cutoff_at` = the latest scheduled kickoff among all fixtures on the
> round sheet, as recorded at publish (`kickoff_at_publish`), plus 48 hours.**

* It is computed once at publish and stored on the round; later kickoff changes
  never move it.
* It does not depend on entries, so every participant's predictions face the
  same cutoff.
* For a weekend round whose last match kicks off on Monday at 19:00 UTC, the
  cutoff is Wednesday 19:00 UTC: settlement completes before the next Friday
  08:00 SAST publication (D-11, revised 19 Nov 2026), and finalisation (24-hour
  correction window, R-14) follows on Thursday evening.
* The 48 hours, like the deadline buffer, is a value of the round schedule
  configuration (D-11), so midweek and European rounds can use their own values.

**Alternatives considered:** the end of the round window (Monday 23:59 UTC) is
fixed but adds up to two idle days after a Sunday finish; the latest kickoff of
*selected* fixtures would give different rounds different rules depending on
entries. Neither is recommended.

**"Completed by the cutoff"** (amended 19 Nov 2026) means: there is reliable
evidence that the match **genuinely completed at or before the cutoff**, namely
* an observation of a final-played status (`FT`, `AET`, `PEN`) that we recorded
  at or before `settle_cutoff_at` (our own timestamp, never a provider claim), or
* an audited operator correction stating a verified completion time at or before
  the cutoff, with its evidence source (D-35).

The 90-minute score may arrive later or be corrected later; completion is the
event, the score is the result. A match that **starts before the cutoff but
completes after it is void**, like a match that starts after the cutoff. There is
one fixed cutoff and **no grace period**.

**Late completion versus delayed notification.** A final result first received
after the cutoff does not show when the match finished. It is recorded as an
observation, the cutoff-based void verdict stands (rule 4, 5 or 6 by the status
recorded at the cutoff), and a **settlement-blocking alert** asks for an audited
resolution: either a correction proving completion at or before the cutoff (the
match then settles), or a confirmation of the void. Completion times are never
derived from kickoff, half start times, elapsed minutes or typical match length.
Because the cutoff test uses only evidence recorded by the cutoff (plus audited
corrections), running a settlement later can never make a genuine late
completion eligible.

### 2a. Evidence (amended 19 Nov 2026)

| Evidence | What it can establish |
|---|---|
| Operator-verified actual event time (audited correction with an evidence source) | Actual kickoff or completion; resolves conflicts |
| Our timestamped observation of an in-play, interrupted or final status | The match had started (or finished) by the time we recorded it |
| Provider first-half start (`periods.first`) | Supporting evidence only; never on its own a definitive early-commencement verdict |
| Revised scheduled kickoff (provider) | Rescheduling, never actual commencement |
| Original scheduled kickoff (`kickoff_at_publish`) | Fixes the deadline and the cutoff; never actual commencement |

Actual kickoff is never filled in from a scheduled kickoff. An ordinary match
with no positive sign of early commencement or rescheduling before the deadline
needs no manual review.

## 3. Verdict rules (applied in this order; the first that matches decides)

| Order | Code | Condition | Verdict |
|---|---|---|---|
| 1 | **V3** | The match **started, or was rescheduled to kick off, before `deadline_at`**, recorded as one of two branches: **started** — an in-play, interrupted or final status we recorded before the deadline, or an operator-verified actual kickoff before it; **rescheduled** — a reliable, consistent provider scheduled kickoff earlier than the deadline. A provider first-half start before the deadline without such corroboration, or contradictory schedule observations, hold the prediction pending with a settlement-blocking alert for audited resolution | **void** |
| 2 | **V2** | Latest status is `CANC`, `AWD` or `WO` (no genuine 90-minute result, including awarded or walkover results) | **void** |
| 3 | settle | Latest status is `FT`, `AET` or `PEN`, the 90-minute score is present, and the match was **completed by the cutoff** (§2). This includes **V5**: a match completed by the cutoff after an earlier postponement, suspension or interruption settles normally on its 90-minute score | **won** or **lost** by the market rules (§4) |
| 4 | **V1** | Now is after `settle_cutoff_at`, the match was not completed by the cutoff, and the status we recorded at the cutoff was postponed (`PST`, or rescheduled to kick off after the cutoff) | **void** |
| 5 | **V4** | Now is after `settle_cutoff_at`, the match was not completed by the cutoff, and the status we recorded at the cutoff was abandoned, suspended or interrupted (`ABD`, `SUSP`, `INT`) | **void** |
| 6 | catch-all | Now is after `settle_cutoff_at`, the match was not completed by the cutoff, and no other rule applies (for example still `NS`, still in play at the cutoff, or nothing recorded by the cutoff) | **void**, recorded as V1, with an operator alert |
| 7 | pending | Anything else before the cutoff, or a final-played status with a missing score | **pending** (a missing score after the cutoff alerts the operator; the verdict stays pending until a score or an audited operator correction arrives) |

Notes:
* **Extra time and penalties never count.** `AET` and `PEN` settle on the
  90-minute score.
* A match **brought forward but still after the deadline** settles normally if it
  is completed by the cutoff.
* An `ABD` match **replayed in full** by the cutoff settles on the replay
  (V5). A match **resumed** after `SUSP`/`INT` and completed by the cutoff
  settles on its 90-minute score (V5).
* A match **still in play at the cutoff** is void even if it finishes minutes
  later (completion-based cutoff).
* After the cutoff, a genuinely later completion of a voided match is recorded as
  an observation but never changes the verdict. A delayed notification of an
  earlier completion follows §2 (blocking alert, audited correction or
  confirmation).
* The status "recorded at the cutoff" is the latest observation we recorded at or
  before `settle_cutoff_at`; later observations never change which void rule
  applies.

## 4. Market rules (90-minute score H–A)

| Market | Outcome wins when |
|---|---|
| 1X2 | Home: H > A; Draw: H = A; Away: H < A |
| BTTS | Yes: H ≥ 1 and A ≥ 1; No: otherwise |
| Over/Under 2.5 | Over: H + A ≥ 3; Under: H + A ≤ 2 |

## 5. Corrections

* Provider corrections arrive as new observations; settlement re-runs and records
  new verdict revisions (T-06). Every distinct provider state is kept, including a
  return to an earlier state (A → B → A); identical repeated deliveries add
  nothing; an older fetch that commits late never becomes the latest evidence.
  A conflicting 90-minute score that would change the verdict of a selected
  outcome keeps the first final score and raises a settlement-blocking alert for
  the correction process; a score change that alters no verdict is applied and
  recorded without blocking. A regression from a final-played status to
  not-started holds the prediction pending with a blocking alert (Q-5).
* Operator corrections (D-35) are observations with source `operator`, the
  original and corrected values, the actor, the reason and timestamps; they take
  precedence over provider observations until withdrawn by another audited
  action.
* Any change of verdict re-runs entry settlement, the D-32b evaluation and the
  round's scores.

## 6. Decision requested

Approve `settle/v1` as defined above: the verdict order V3 → V2 → settle (incl.
V5) → V1 → V4 → catch-all → pending, and the cutoff measured from the latest
scheduled kickoff on the round sheet at publish plus 48 hours.
