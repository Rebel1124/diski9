"""The signed-in participant's own settlement, ready for display (Phase 6C.4,
Stage F, S-11).

Read-only and owner-scoped: the entry is looked up by the **server-built**
principal's user ID and a round ID chosen on the server; nothing supplied by the
browser selects whose result is read. Every number is the authoritative stored
settlement (entry settlement revision, prediction verdicts, round designation);
no settlement mathematics is repeated here. Presentation rules (S-11):

* a pending prediction is never shown as incorrect; an accumulator with a pending
  leg and no incorrect leg has no payout (``None``, never 0.00);
* an accumulator with an incorrect leg is ``lost`` (0.00) even while others are
  pending; one whose legs are all void returns its stake and is ``refunded``;
* gross while incomplete is "settled so far"; net and recovery stay undecided
  (``None``) until the entry is complete and the round's validity is evaluated;
* an all-nine-void entry (D-33) and a void round are refunds, never recoveries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, select, text

from ..auth.permissions import Capability, Principal, can
from ..db import read_only
from ..db.schema import entries, rounds
from . import settlement as st

ZERO = Decimal("0.00")
HUNDRED = Decimal("100.00")

#: participant-facing reasons for a void prediction (settle/v1 §3)
VOID_REASON = {
    "V1": "Void: the match was postponed or not completed by the settlement cutoff.",
    "V2": "Void: the match was cancelled or awarded without a genuine result.",
    "V3": "Void: the match started (or was moved) before the submission deadline.",
    "V4": "Void: the match was abandoned or suspended and not completed by the cutoff.",
}


@dataclass(frozen=True)
class PredictionResult:
    position: int
    fixture_id: int
    market: str
    outcome: str
    bucket: str
    odds: Decimal
    verdict: str  # won | lost | void | pending
    rule: str | None
    score: str | None  # official 90-minute score "2-1" where available
    void_reason: str | None


@dataclass(frozen=True)
class AccumulatorResult:
    code: str  # A, B, C, NINE
    stake: int
    status: str  # pending | won | lost | refunded
    payout: Decimal | None  # None while pending
    effective_odds: Decimal | None
    legs: tuple[str, ...]  # verdicts of its predictions, in entry order


@dataclass(frozen=True)
class ParticipantSettlement:
    round_id: UUID
    round_code: str
    round_status: str  # open (deadline passed) | locked | settling | final
    state: str  # awaiting_lock | locked | in_progress | awaiting_round | provisional | final
    is_development: bool
    settled: bool  # a settlement exists for this entry
    complete: bool
    gross: Decimal | None  # settled so far while incomplete
    net: Decimal | None  # None until complete
    recovered: bool | None  # None until decided
    entry_refunded: bool  # D-33 all nine void
    round_void: bool
    round_void_basis: str | None  # d32b | operator
    counts: dict[str, int] = field(default_factory=dict)
    accumulators: tuple[AccumulatorResult, ...] = ()
    predictions: tuple[PredictionResult, ...] = ()
    version: int | None = None
    version_kind: str | None = None
    settled_at: datetime | None = None
    corrected_at: datetime | None = None  # a correction / reopening changed this entry
    reopened_at: datetime | None = None
    finalised_at: datetime | None = None
    earliest_finalisation: datetime | None = None


def _accumulator(a: dict, legs: list[str]) -> AccumulatorResult:
    status = a["status"]
    payout = None if a["payout"] is None else Decimal(a["payout"])
    if status == "won" and legs and all(v == "void" for v in legs):
        status = "refunded"
    return AccumulatorResult(
        code=a["code"],
        stake=int(a["stake"]),
        status=status,
        payout=payout,
        effective_odds=None if a["effective_odds"] is None else Decimal(a["effective_odds"]),
        legs=tuple(legs),
    )


def my_settlement(
    engine: Engine, principal: Principal, round_id: UUID
) -> ParticipantSettlement | None:
    """The participant's own entry in ``round_id`` (locked or past its deadline)
    with its current settlement; ``None`` for guests, for another person's round
    data (there is none to return) or when the participant has no confirmed entry."""
    if not can(principal, Capability.PERSIST_OWN_ANALYSIS):
        return None
    with read_only(engine) as conn:
        r = conn.execute(select(rounds).where(rounds.c.id == round_id)).one_or_none()
        if r is None or r.status not in ("open", "locked", "settling", "final"):
            return None
        e = conn.execute(
            select(entries).where(
                entries.c.round_id == round_id, entries.c.user_id == principal.user_id
            )
        ).one_or_none()
        if e is None:
            return None
        if r.status == "open":
            if e.current_submission_id is None:
                return None
            return ParticipantSettlement(
                round_id, r.code, r.status, "awaiting_lock", r.is_development, False, False,
                None, None, None, False, False, None,
            )  # fmt: skip
        if e.locked_submission_id is None:
            return None
        s = conn.execute(
            text(
                "SELECT * FROM app.entry_settlements WHERE entry_id = :e "
                "ORDER BY revision DESC LIMIT 1"
            ),
            {"e": e.id},
        ).one_or_none()
        cur = st.current_designation(conn, round_id)
        v = st.latest_version(conn, round_id)
        round_void = cur is not None and cur.designation == "void"
        if s is None:
            return ParticipantSettlement(
                round_id, r.code, r.status, "locked", r.is_development, False, False,
                None, None, None, False, round_void, cur.basis if round_void else None,
            )  # fmt: skip
        verdicts = {
            (row.fixture_id, row.market, row.outcome): row
            for row in conn.execute(
                text(
                    "SELECT DISTINCT ON (fixture_id, market, outcome) fixture_id, market, "
                    "outcome, verdict, rule, void_code, evidence FROM app.selection_verdicts "
                    "WHERE round_id = :r ORDER BY fixture_id, market, outcome, revision DESC"
                ),
                {"r": round_id},
            )
        }
        last_eval = st._latest_evaluation(conn, round_id)
        evaluated = last_eval is not None and last_eval.outcome != "not_evaluated"
        # when a correction or reopening last changed this entry (or its round's verdicts)
        changed = conn.execute(
            text(
                "SELECT max(es.created_at) FROM app.entry_settlements es "
                "JOIN app.settlement_runs sr ON sr.id = es.run_id "
                "WHERE es.entry_id = :e AND es.revision > 1 "
                "AND sr.trigger IN ('correction', 'reopen')"
            ),
            {"e": e.id},
        ).scalar()
        reopened = conn.execute(
            text(
                "SELECT max(created_at) FROM app.settlement_versions "
                "WHERE round_id = :r AND kind = 'reopened'"
            ),
            {"r": round_id},
        ).scalar()
        earliest = st.earliest_finalisation(conn, r) if r.status == "settling" else None
    legs_json = s.legs or {}
    preds = []
    for leg in legs_json.get("legs", []):
        row = verdicts.get((leg["fixture_id"], leg["market"], leg["outcome"]))
        verdict = leg["verdict"]
        rule = row.rule if row is not None else None
        code = (row.void_code if row is not None else None) or (rule or "")[:2]
        preds.append(
            PredictionResult(
                position=leg["position"],
                fixture_id=leg["fixture_id"],
                market=leg["market"],
                outcome=leg["outcome"],
                bucket=leg["bucket"],
                odds=Decimal(leg["odds"]),
                verdict=verdict,
                rule=rule,
                score=((row.evidence or {}).get("score") if row is not None else None),
                void_reason=VOID_REASON.get(code) if verdict == "void" else None,
            )
        )
    by_bucket: dict[str, list[str]] = {}
    for p in preds:
        by_bucket.setdefault(p.bucket, []).append(p.verdict)
    accs = tuple(
        _accumulator(a, by_bucket.get(a["code"], []) if a["code"] != "NINE"
                     else [p.verdict for p in preds])
        for a in legs_json.get("accumulators", [])
    )  # fmt: skip
    counts = {
        k: sum(1 for p in preds if p.verdict == k) for k in ("won", "lost", "void", "pending")
    }
    complete = bool(s.complete)
    entry_refunded = complete and s.basis == "all_void"
    decided = (complete and evaluated) or round_void
    if r.status == "final":
        state = "final"
    elif decided:
        state = "provisional"
    elif complete:  # this entry is settled; the round's validity check is not done yet
        state = "awaiting_round"
    else:
        state = "in_progress"
    gross = HUNDRED if round_void else s.gross
    # net is final only once the round's validity is known (a void round refunds)
    net = (ZERO if round_void else s.net) if decided else None
    recovered = None
    if decided:
        recovered = (not round_void) and (not entry_refunded) and s.gross >= HUNDRED
    return ParticipantSettlement(
        round_id=round_id,
        round_code=r.code,
        round_status=r.status,
        state=state,
        is_development=r.is_development,
        settled=True,
        complete=complete or round_void,
        gross=gross,
        net=net,
        recovered=recovered,
        entry_refunded=entry_refunded,
        round_void=round_void,
        round_void_basis=cur.basis if round_void else None,
        counts=counts,
        accumulators=accs,
        predictions=tuple(sorted(preds, key=lambda p: p.position)),
        version=v.version if v else None,
        version_kind=v.kind if v else None,
        settled_at=s.created_at,
        corrected_at=changed,
        reopened_at=reopened,
        finalised_at=r.finalised_at,
        earliest_finalisation=earliest,
    )


__all__ = ["AccumulatorResult", "ParticipantSettlement", "PredictionResult", "my_settlement"]
