"""Entry and round settlement (Phase 6C.4, Stage C).

One settlement run settles a whole locked round in **one transaction** with the
round row locked ``FOR UPDATE`` (plus the partial unique index on running runs):

1. read the authoritative locked set (``entries.locked_submission_id``), the frozen
   selections and odds, and the round's observations in its result mode;
2. resolve every relevant fixture with :mod:`diski9.challenge.settle` (pure);
3. settle every locked entry through the tested engine (void legs at 1.00);
4. evaluate D-32b with exact integers; change the designation only when the outcome
   changes (never the competitive/practice base designation fixed at the lock);
5. write new revisions **only when something changed**, a new settlement version
   when the change is *material* (S-02), alerts, and a run record with the
   evidence manifest.

A rerun with the same evidence in the same phase writes only the run record. A
finalised round is never changed here: a material difference raises a
``post_final_change`` alert instead (S-06). Corrections, finalisation and owner
reopening are in :mod:`diski9.backend.services.corrections` and reuse
:func:`compute` and :func:`apply`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, Engine, func, insert, select, text, update

from ...challenge.settle import (
    POLICY_VERSION,
    Alert,
    EntrySettlement,
    Leg,
    Observation,
    Resolution,
    RoundValidity,
    evaluate_round,
    resolve_fixture,
    settle_entry,
)
from ..auth.permissions import Capability, Principal
from ..db import db_now, transaction
from ..db.schema import (
    designations,
    entries,
    entry_settlements,
    round_evaluations,
    selection_verdicts,
    settlement_runs,
    settlement_versions,
    submission_selections,
    submissions,
)
from ..repositories import results as results_repo
from ..repositories import rounds as rounds_repo
from .common import ServiceError
from .results import actor_id, environment
from .rounds import System

AUTO_SUPERSEDE = frozenset({"unknown_status", "missing_score", "status_regression"})


class SettlementRefused(ServiceError):
    code = "settlement_refused"


class SettlementIntegrityError(ServiceError):
    """The settled payout disagrees with the confirmed submission's engine states."""

    code = "settlement_integrity"


# ------------------------------------------------------------------ plan
@dataclass
class Plan:
    round_id: UUID
    status: str
    mode: str
    deadline_at: datetime
    settle_cutoff_at: datetime
    correction_window_hours: int
    evaluated_at: datetime
    time_override: bool
    phase: str
    base_designation: str
    resolutions: dict[int, Resolution]
    entry_results: dict[UUID, tuple[UUID, EntrySettlement]]  # entry -> (submission, result)
    validity: RoundValidity
    verdict_writes: list[dict] = field(default_factory=list)
    entry_writes: list[dict] = field(default_factory=list)
    evaluation_write: dict | None = None
    designation_write: dict | None = None
    alerts: list[Alert] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    evidence_through_id: int | None = None
    inputs_hash: str = ""
    current_designation: str = ""

    @property
    def material(self) -> bool:
        return (
            any(w["material"] for w in self.verdict_writes)
            or bool(self.entry_writes)
            or self.designation_write is not None
        )

    @property
    def changed(self) -> bool:
        return bool(self.verdict_writes or self.entry_writes or self.evaluation_write)


@dataclass(frozen=True)
class SettlementResult:
    round_id: UUID
    run_id: int | None
    version: int | None
    material: bool
    changed_verdicts: int
    changed_entries: int
    outcome: str
    designation: str
    phase: str
    new_alerts: tuple[int, ...]
    open_blocking_alerts: int
    earliest_finalisation: datetime | None
    post_final_change: bool = False


# ------------------------------------------------------------------ reads
def _current_verdicts(conn: Connection, round_id: UUID) -> dict[tuple, object]:
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (fixture_id, market, outcome) * FROM app.selection_verdicts "
            "WHERE round_id = :r ORDER BY fixture_id, market, outcome, revision DESC"
        ),
        {"r": round_id},
    )
    return {(r.fixture_id, r.market, r.outcome): r for r in rows}


def _current_entry_settlements(conn: Connection, round_id: UUID) -> dict[UUID, object]:
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (s.entry_id) s.* FROM app.entry_settlements s "
            "JOIN app.entries e ON e.id = s.entry_id WHERE e.round_id = :r "
            "ORDER BY s.entry_id, s.revision DESC"
        ),
        {"r": round_id},
    )
    return {r.entry_id: r for r in rows}


def _latest_evaluation(conn: Connection, round_id: UUID):
    return conn.execute(
        select(round_evaluations)
        .where(round_evaluations.c.round_id == round_id)
        .order_by(round_evaluations.c.id.desc())
        .limit(1)
    ).one_or_none()


def current_designation(conn: Connection, round_id: UUID):
    return conn.execute(
        select(designations)
        .where(designations.c.round_id == round_id)
        .order_by(designations.c.created_at.desc(), designations.c.id.desc())
        .limit(1)
    ).one_or_none()


def base_designation(conn: Connection, round_id: UUID) -> str:
    d = conn.execute(
        select(designations.c.designation).where(
            designations.c.round_id == round_id, designations.c.basis == "deadline"
        )
    ).scalar_one_or_none()
    if d is None:
        raise SettlementRefused("The round has no designation from its lock.")
    return d


def latest_version(conn: Connection, round_id: UUID):
    return conn.execute(
        select(settlement_versions)
        .where(settlement_versions.c.round_id == round_id)
        .order_by(settlement_versions.c.version.desc())
        .limit(1)
    ).one_or_none()


def last_material_change(conn: Connection, round_id: UUID) -> datetime | None:
    return conn.execute(
        select(func.max(settlement_versions.c.effective_at)).where(
            settlement_versions.c.round_id == round_id, settlement_versions.c.material
        )
    ).scalar_one()


def earliest_finalisation(conn: Connection, r) -> datetime | None:
    """S-02: max(fixed cutoff, last material settlement change) + correction window.
    ``None`` before the round has been settled at all."""
    last = last_material_change(conn, r.id)
    if last is None:
        return None
    return max(r.settle_cutoff_at, last) + timedelta(hours=r.correction_window_hours)


def locked_legs(conn: Connection, round_id: UUID) -> dict[UUID, tuple[UUID, list[Leg], dict]]:
    rows = conn.execute(
        select(
            entries.c.id.label("entry_id"),
            entries.c.locked_submission_id,
            submission_selections.c.position,
            submission_selections.c.fixture_id,
            submission_selections.c.market,
            submission_selections.c.outcome,
            submission_selections.c.bucket,
            submission_selections.c.consensus_odds,
            submissions.c.states,
        )
        .join(
            submission_selections,
            submission_selections.c.submission_id == entries.c.locked_submission_id,
        )
        .join(submissions, submissions.c.id == entries.c.locked_submission_id)
        .where(entries.c.round_id == round_id, entries.c.locked_submission_id.is_not(None))
        .order_by(entries.c.id, submission_selections.c.position)
    )
    out: dict[UUID, tuple[UUID, list[Leg], dict]] = {}
    for r in rows:
        sub, legs, states = out.setdefault(r.entry_id, (r.locked_submission_id, [], r.states))
        legs.append(Leg(r.position, r.fixture_id, r.market, r.outcome, r.bucket, r.consensus_odds))
    return out


# ------------------------------------------------------------------ compute
def _legs_json(es: EntrySettlement) -> dict:
    return {
        "legs": [
            {
                "position": leg.position,
                "fixture_id": leg.fixture_id,
                "market": leg.market,
                "outcome": leg.outcome,
                "bucket": leg.bucket,
                "odds": str(leg.odds),
                "verdict": verdict,
            }
            for leg, verdict in es.legs
        ],
        "accumulators": [
            {
                "code": a.code,
                "stake": a.stake,
                "status": a.status,
                "effective_odds": None if a.effective_odds is None else str(a.effective_odds),
                "payout": None if a.payout is None else str(a.payout),
            }
            for a in es.accumulators
        ],
    }


def _check_against_states(entry_id: UUID, es: EntrySettlement, states) -> None:
    """With no void leg, the realised gross must equal the confirmed submission's
    engine state for the same win vector (the same arithmetic, D-15)."""
    if not es.complete or any(v == "void" for _, v in es.legs):
        return
    market = (states or {}).get("market") if isinstance(states, dict) else None
    if not market:
        return
    wins = list(es.win_vector)
    stored = next((Decimal(s["gross"]) for s in market if list(s["wins"]) == wins), None)
    if stored is not None and stored != es.gross:
        raise SettlementIntegrityError(
            "A settled payout disagrees with the confirmed submission.",
            details={"entry": str(entry_id), "stored": str(stored), "settled": str(es.gross)},
        )


def compute(
    conn: Connection,
    round_id: UUID,
    *,
    evaluated_at: datetime,
    time_override: bool = False,
    extra: dict[int, tuple[Observation, ...]] | None = None,
) -> Plan:
    """Everything a settlement run would write, without writing it. ``extra``
    (fixture -> observations) lets a preview include a hypothetical operator
    correction that is never stored."""
    r = rounds_repo.lock_round_for_change(conn, round_id)
    if r.result_mode is None:
        raise SettlementRefused("Choose this development round's result mode before settling it.")
    if r.correction_window_hours is None or r.settle_cutoff_at is None:
        raise SettlementRefused("This round was never published.")
    base = base_designation(conn, round_id)
    locked = locked_legs(conn, round_id)
    selected: dict[int, set[tuple[str, str]]] = {}
    for _, legs, _ in locked.values():
        for leg in legs:
            selected.setdefault(leg.fixture_id, set()).add((leg.market, leg.outcome))
    rows = results_repo.observation_rows(conn, selected, mode=r.result_mode, round_id=round_id)
    by_fixture: dict[int, list[Observation]] = {}
    for row in rows:
        by_fixture.setdefault(row.fixture_id, []).append(results_repo.to_observation(row))
    for fid, extra_obs in (extra or {}).items():
        by_fixture.setdefault(fid, []).extend(extra_obs)
    resolutions = {
        fid: resolve_fixture(
            fid,
            by_fixture.get(fid, []),
            sorted(outcomes),
            deadline_at=r.deadline_at,
            settle_cutoff_at=r.settle_cutoff_at,
            evaluated_at=evaluated_at,
        )
        for fid, outcomes in sorted(selected.items())
    }
    verdicts = {
        (fid, v.market, v.outcome): v.verdict
        for fid, res in resolutions.items()
        for v in res.verdicts
    }
    entry_results = {}
    for entry_id, (sub, legs, states) in locked.items():
        es = settle_entry(legs, verdicts)
        _check_against_states(entry_id, es, states)
        entry_results[entry_id] = (sub, es)
    validity = evaluate_round(
        [es for _, es in entry_results.values()], competitive=(base == "championship")
    )
    phase = "after_cutoff" if evaluated_at > r.settle_cutoff_at else "before_cutoff"
    cur = current_designation(conn, round_id)
    plan = Plan(
        round_id=round_id,
        status=r.status,
        mode=r.result_mode,
        deadline_at=r.deadline_at,
        settle_cutoff_at=r.settle_cutoff_at,
        correction_window_hours=r.correction_window_hours,
        evaluated_at=evaluated_at,
        time_override=time_override,
        phase=phase,
        base_designation=base,
        resolutions=resolutions,
        entry_results=entry_results,
        validity=validity,
        current_designation=cur.designation if cur else base,
    )
    # verdict revisions (material: verdict, void code or rule; score-only: not material)
    current_v = _current_verdicts(conn, round_id)
    for fid, res in resolutions.items():
        score = None if res.score is None else f"{res.score[0]}-{res.score[1]}"
        for v in res.verdicts:
            old = current_v.get((fid, v.market, v.outcome))
            material = old is None or (old.verdict, old.void_code, old.rule) != (
                v.verdict,
                v.void_code,
                v.rule,
            )
            old_score = (old.evidence or {}).get("score") if old is not None else None
            if not material and old_score == score:
                continue
            plan.verdict_writes.append(
                {
                    "round_id": round_id,
                    "fixture_id": fid,
                    "market": v.market,
                    "outcome": v.outcome,
                    "verdict": v.verdict,
                    "void_code": v.void_code,
                    "rule": v.rule,
                    "result_observation_id": res.deciding_observation_id
                    if res.deciding_observation_id and res.deciding_observation_id > 0
                    else None,
                    "revision": (old.revision + 1) if old is not None else 1,
                    "material": material,
                    "evidence": {
                        "score": score,
                        "observations": [i for i in res.evidence_ids if i > 0],
                        "notes": list(res.notes),
                        "policy": POLICY_VERSION,
                    },
                }
            )
    # entry settlement revisions (every change here is material)
    current_e = _current_entry_settlements(conn, round_id)
    for entry_id, (sub, es) in entry_results.items():
        legs = _legs_json(es)
        basis = "all_void" if es.all_void and es.complete else "settled"
        old = current_e.get(entry_id)
        if old is not None and (
            old.gross == es.gross
            and old.complete == es.complete
            and old.basis == basis
            and old.legs == legs
        ):
            continue
        plan.entry_writes.append(
            {
                "entry_id": entry_id,
                "submission_id": sub,
                "revision": (old.revision + 1) if old is not None else 1,
                "gross": es.gross,
                "net": es.net,
                "legs": legs,
                "basis": basis,
                "complete": es.complete,
            }
        )
    # D-32b evaluation and designation
    last = _latest_evaluation(conn, round_id)
    counts = (
        validity.outcome,
        validity.total,
        validity.played,
        validity.void,
        validity.pending,
        validity.ranked,
    )
    if (
        last is None
        or (
            last.outcome,
            last.total_predictions,
            last.played_predictions,
            last.void_predictions,
            last.pending_predictions,
            last.ranked_entries,
        )
        != counts
    ):
        plan.evaluation_write = {
            "round_id": round_id,
            "rule": validity.rule,
            "total_predictions": validity.total,
            "played_predictions": validity.played,
            "void_predictions": validity.void,
            "pending_predictions": validity.pending,
            "ranked_entries": validity.ranked,
            "outcome": validity.outcome,
        }
    operator_void = cur is not None and cur.basis == "operator" and cur.designation == "void"
    if not operator_void:
        desired = "void" if validity.outcome in ("fail_majority", "fail_ranked") else base
        if desired != plan.current_designation:
            plan.designation_write = {
                "round_id": round_id,
                "designation": desired,
                "basis": "d32b",
                "provisional": True,
                "reason": f"D-32b {validity.outcome}: {validity.played} of {validity.total} "
                f"predictions played, {validity.ranked} rank-eligible entries",
            }
    plan.alerts = [a for res in resolutions.values() for a in res.alerts]
    plan.manifest = {
        str(fid): [i for i in res.evidence_ids if i > 0] for fid, res in resolutions.items()
    }
    ids = [i for v in plan.manifest.values() for i in v]
    plan.evidence_through_id = max(ids) if ids else None
    plan.inputs_hash = hashlib.sha256(
        json.dumps(
            {
                "policy": POLICY_VERSION,
                "mode": r.result_mode,
                "phase": phase,
                "manifest": plan.manifest,
                "extra": sorted(o.id for v in (extra or {}).values() for o in v),
                "locked": sorted(str(s) for s, _, _ in locked.values()),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return plan


# ------------------------------------------------------------------ apply
def apply(
    conn: Connection,
    plan: Plan,
    *,
    trigger: str,
    actor: UUID | None,
    job_run_id: int | None = None,
) -> tuple[int, int | None, list[int]]:
    """Write the plan (run record, revisions, evaluation, designation, version,
    alerts). Returns ``(run_id, version or None, new alert IDs)``."""
    run_id = conn.execute(
        insert(settlement_runs)
        .values(
            round_id=plan.round_id,
            job_run_id=job_run_id,
            trigger=trigger,
            inputs_hash=plan.inputs_hash,
            evaluated_at=plan.evaluated_at,
            phase=plan.phase,
            time_override=plan.time_override,
            actor_user_id=actor,
            manifest=plan.manifest,
            evidence_through_id=plan.evidence_through_id,
            material=plan.material,
        )
        .returning(settlement_runs.c.id)
    ).scalar_one()
    if plan.verdict_writes:
        conn.execute(
            insert(selection_verdicts), [dict(w, run_id=run_id) for w in plan.verdict_writes]
        )
    if plan.entry_writes:
        conn.execute(insert(entry_settlements), [dict(w, run_id=run_id) for w in plan.entry_writes])
    eval_id = None
    if plan.evaluation_write:
        eval_id = conn.execute(
            insert(round_evaluations)
            .values(run_id=run_id, **plan.evaluation_write)
            .returning(round_evaluations.c.id)
        ).scalar_one()
    if plan.designation_write:
        if eval_id is None:
            last = _latest_evaluation(conn, plan.round_id)
            eval_id = last.id
        conn.execute(
            insert(designations).values(round_evaluation_id=eval_id, **plan.designation_write)
        )
    version = None
    prev = latest_version(conn, plan.round_id)
    if plan.material or prev is None:
        version = (prev.version + 1) if prev is not None else 1
        conn.execute(
            insert(settlement_versions).values(
                round_id=plan.round_id,
                version=version,
                run_id=run_id,
                kind="provisional",
                material=True,
                effective_at=plan.evaluated_at,
                actor_user_id=actor,
            )
        )
    if plan.status == "locked":
        rounds_repo.set_status(
            conn, plan.round_id, "settling", reason="first settlement run", actor=actor
        )
    new_alerts = results_repo.raise_alerts(conn, plan.round_id, run_id, plan.alerts)
    current = {a.fingerprint for a in plan.alerts}
    for a in results_repo.open_alerts(conn, plan.round_id):
        if a.code in AUTO_SUPERSEDE and a.fingerprint not in current:
            results_repo.resolve_alert(
                conn,
                a.id,
                resolution="superseded",
                reason="the condition is no longer present in the evidence",
                actor=None,
            )
    conn.execute(
        update(settlement_runs)
        .where(settlement_runs.c.id == run_id)
        .values(
            status="succeeded",
            finished_at=func.clock_timestamp(),
            changed_verdicts=len(plan.verdict_writes),
            changed_entries=len(plan.entry_writes),
        )
    )
    return run_id, version, new_alerts


def _record_failure(engine: Engine, round_id: UUID, trigger: str, actor, error: str) -> None:
    try:
        with transaction(engine) as conn:
            rid = conn.execute(
                insert(settlement_runs)
                .values(round_id=round_id, trigger=trigger, actor_user_id=actor)
                .returning(settlement_runs.c.id)
            ).scalar_one()
            conn.execute(
                update(settlement_runs)
                .where(settlement_runs.c.id == rid)
                .values(status="failed", finished_at=func.clock_timestamp(), error=error[:500])
            )
    except Exception:  # noqa: BLE001 - recording the failure must never mask it
        pass


def evaluation_time(conn: Connection, r, as_of: datetime | None, actor) -> tuple[datetime, bool]:
    """The database clock, or a development-only override (never for real rounds,
    never in production, never for the scheduled-job actor)."""
    if as_of is None:
        return db_now(conn), False
    if isinstance(actor, System):
        raise SettlementRefused("Time overrides need an authenticated operator.")
    if not r.is_development:
        raise SettlementRefused("Time overrides are only for development rounds.")
    if environment() == "production":
        raise SettlementRefused("Time overrides are disabled in production.")
    return as_of, True


def _result(conn, plan: Plan, run_id, version, new_alerts, post_final=False) -> SettlementResult:
    r = rounds_repo.lock_round_for_change(conn, plan.round_id)
    cur = current_designation(conn, plan.round_id)
    return SettlementResult(
        round_id=plan.round_id,
        run_id=run_id,
        version=version,
        material=plan.material,
        changed_verdicts=len(plan.verdict_writes),
        changed_entries=len(plan.entry_writes),
        outcome=plan.validity.outcome,
        designation=cur.designation if cur else plan.base_designation,
        phase=plan.phase,
        new_alerts=tuple(new_alerts),
        open_blocking_alerts=len(results_repo.open_alerts(conn, plan.round_id, blocking_only=True)),
        earliest_finalisation=earliest_finalisation(conn, r),
        post_final_change=post_final,
    )


# ------------------------------------------------------------------ public API
def settle_round(
    engine: Engine,
    actor: Principal | System,
    round_id: UUID,
    *,
    as_of: datetime | None = None,
    job_run_id: int | None = None,
) -> SettlementResult:
    """Run settlement for a locked or settling round (``jobs.run``, or the explicit
    scheduled-job actor). A finalised round is never changed: a material
    difference raises a ``post_final_change`` alert. ``job_run_id`` links the
    settlement run to the scheduler's job record (Phase 6C.6 Stage C)."""
    uid = actor_id(actor, Capability.RUN_JOBS)
    trigger = "scheduled" if isinstance(actor, System) else "manual"
    try:
        with transaction(engine) as conn:
            r = rounds_repo.lock_round_for_change(conn, round_id)
            if r.status not in ("locked", "settling", "final"):
                raise SettlementRefused("Only a locked round can be settled.")
            at, override = evaluation_time(conn, r, as_of, actor)
            plan = compute(conn, round_id, evaluated_at=at, time_override=override)
            if r.status == "final":
                new = []
                if plan.material:
                    new = results_repo.raise_alerts(
                        conn,
                        round_id,
                        None,
                        [
                            Alert(
                                "post_final_change",
                                None,
                                plan.inputs_hash[:16],
                                {
                                    "verdicts": len(plan.verdict_writes),
                                    "entries": len(plan.entry_writes),
                                    "designation": (plan.designation_write or {}).get(
                                        "designation"
                                    ),
                                },
                            )
                        ],
                    )
                return _result(conn, plan, None, None, new, post_final=plan.material)
            run_id, version, new = apply(
                conn, plan, trigger=trigger, actor=uid, job_run_id=job_run_id
            )
            return _result(conn, plan, run_id, version, new)
    except ServiceError:
        raise
    except Exception as exc:
        _record_failure(engine, round_id, trigger, uid, type(exc).__name__)
        raise


def preview_settlement(
    engine: Engine, actor: Principal, round_id: UUID, *, as_of: datetime | None = None
) -> Plan:
    """What a run would change now, without writing anything (``jobs.run``): the
    whole computation runs in a transaction that is always rolled back."""
    actor_id(actor, Capability.RUN_JOBS)
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            r = rounds_repo.lock_round_for_change(conn, round_id)
            at, override = evaluation_time(conn, r, as_of, actor)
            return compute(conn, round_id, evaluated_at=at, time_override=override)
        finally:
            trans.rollback()


# ------------------------------------------------------------------ participant read
@dataclass(frozen=True)
class PersonalResult:
    round_id: UUID
    round_status: str
    version: int | None
    version_kind: str | None
    designation: str
    complete: bool
    gross: Decimal
    net: Decimal
    basis: str
    legs: dict
    recovered: bool | None
    rank_eligible: bool | None
    round_void: bool


def personal_result(engine: Engine, principal: Principal, round_id: UUID) -> PersonalResult | None:
    """The signed-in participant's own current settlement (no one else's). The
    round-level designation is applied: a D-32b or operator void round is
    refunded. Recovery and rank eligibility stay undecided (``None``) until the
    entry is complete **and** the round's validity has been evaluated (S-11)."""
    if not principal.is_authenticated:
        return None
    with transaction(engine) as conn:
        e = conn.execute(
            select(entries.c.id).where(
                entries.c.round_id == round_id,
                entries.c.user_id == principal.user_id,
                entries.c.locked_submission_id.is_not(None),
            )
        ).scalar_one_or_none()
        if e is None:
            return None
        s = conn.execute(
            select(entry_settlements)
            .where(entry_settlements.c.entry_id == e)
            .order_by(entry_settlements.c.revision.desc())
            .limit(1)
        ).one_or_none()
        if s is None:
            return None
        status = conn.execute(
            text("SELECT status FROM app.rounds WHERE id = :r"), {"r": round_id}
        ).scalar_one()
        cur = current_designation(conn, round_id)
        last = _latest_evaluation(conn, round_id)
        v = latest_version(conn, round_id)
        evaluated = last is not None and last.outcome != "not_evaluated"
        round_void = cur is not None and cur.designation == "void"
        decided = s.complete and (evaluated or round_void)
        recovered = None
        eligible = None
        if decided:
            eligible = (s.basis != "all_void") and not round_void
            recovered = eligible and s.gross >= Decimal("100.00")
        return PersonalResult(
            round_id=round_id,
            round_status=status,
            version=v.version if v else None,
            version_kind=v.kind if v else None,
            designation=cur.designation if cur else "",
            complete=s.complete,
            gross=Decimal("100.00") if round_void else s.gross,
            net=Decimal("0.00") if round_void else s.net,
            basis=s.basis,
            legs=s.legs,
            recovered=recovered,
            rank_eligible=eligible,
            round_void=round_void,
        )
