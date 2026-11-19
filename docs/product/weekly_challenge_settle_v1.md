# D-08 — Settlement rules `settle/v1`: exact definitions (for approval)

**Status:** proposed for final approval. The owner has accepted the 48-hour
cutoff in principle and asked for the exact void definitions and the event the
cutoff is measured from. The payout treatment of voids is already approved
(D-32 partial voids, D-33 fully void entries, D-32b whole rounds); this note only
decides **which verdict** each prediction receives.

## 1. Inputs

For each fixture on a round sheet, settlement uses only:
* the round's `deadline_at` and `settle_cutoff_at`, both fixed at publish;
* the fixture's **result observations** (insert-only; provider observations and
  audited operator corrections, D-35): status code, actual kickoff time and the
  90-minute score (`ft_home`, `ft_away`, from the provider's `score.fulltime`).

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
  cutoff is Wednesday 19:00 UTC: settlement completes before the next Thursday
  publication, and finalisation (24-hour correction window, R-14) follows on
  Thursday evening.
* The 48 hours, like the deadline buffer, is a value of the round schedule
  configuration (D-11), so midweek and European rounds can use their own values.

**Alternatives considered:** the end of the round window (Monday 23:59 UTC) is
fixed but adds up to two idle days after a Sunday finish; the latest kickoff of
*selected* fixtures would give different rounds different rules depending on
entries. Neither is recommended.

**"Completed by the cutoff"** means: a final-played status with a 90-minute score
is observed, and the match's **actual kickoff is at or before the cutoff**. A
match that kicks off before the cutoff and finishes shortly after it is settled
normally; a match that kicks off after the cutoff is void.

## 3. Verdict rules (applied in this order; the first that matches decides)

| Order | Code | Condition | Verdict |
|---|---|---|---|
| 1 | **V3** | The match **started, or was rescheduled to kick off, before `deadline_at`**: any observation with an actual or scheduled kickoff earlier than the deadline, or an in-play or final status observed before the deadline | **void** |
| 2 | **V2** | Latest status is `CANC`, `AWD` or `WO` (no genuine 90-minute result, including awarded or walkover results) | **void** |
| 3 | settle | Latest status is `FT`, `AET` or `PEN`, the 90-minute score is present, and the actual kickoff is at or before `settle_cutoff_at`. This includes **V5**: a match completed by the cutoff after an earlier postponement, suspension or interruption settles normally on its 90-minute score | **won** or **lost** by the market rules (§4) |
| 4 | **V1** | Now is after `settle_cutoff_at` and the match was postponed (`PST`, or rescheduled to kick off after the cutoff) without being completed by the cutoff | **void** |
| 5 | **V4** | Now is after `settle_cutoff_at` and the match was abandoned, suspended or interrupted (`ABD`, `SUSP`, `INT`) without being completed by the cutoff | **void** |
| 6 | catch-all | Now is after `settle_cutoff_at` and no other rule produced a final verdict (for example still `NS`, or in play beyond reason) | **void**, recorded as V1, with an operator alert |
| 7 | pending | Anything else before the cutoff, or a final-played status with a missing score | **pending** (a missing score after the cutoff alerts the operator; the verdict stays pending until a score or an audited operator correction arrives) |

Notes:
* **Extra time and penalties never count.** `AET` and `PEN` settle on the
  90-minute score.
* A match **brought forward but still after the deadline** settles normally if it
  is completed by the cutoff.
* An `ABD` match **replayed in full** by the cutoff settles on the replay
  (V5). A match **resumed** after `SUSP`/`INT` and completed by the cutoff
  settles on its 90-minute score (V5).
* After the cutoff, a later completion of a voided match is recorded as an
  observation for research but never changes the verdict.

## 4. Market rules (90-minute score H–A)

| Market | Outcome wins when |
|---|---|
| 1X2 | Home: H > A; Draw: H = A; Away: H < A |
| BTTS | Yes: H ≥ 1 and A ≥ 1; No: otherwise |
| Over/Under 2.5 | Over: H + A ≥ 3; Under: H + A ≤ 2 |

## 5. Corrections

* Provider corrections arrive as new observations; settlement re-runs and records
  new verdict revisions (T-06).
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
