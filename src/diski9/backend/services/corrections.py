"""Corrections, alert resolution, invalidation, finalisation and owner reopening
(Phase 6C.4, Stage D).

Every material operation follows the same pattern (S-06, S-07):

* **authorisation** on a server-built principal: ``result.correct`` and
  ``round.void`` (operators) and ``round.reopen`` (owner only) are sensitive, so the
  password must have been entered within 15 minutes (T-14); finalisation needs
  ``jobs.run`` or the explicit scheduled-job actor; nothing is granted by database
  access, and no general bypass exists;
* an **impact preview** computed exactly as the change would be, without writing;
  its **confirmation token** must be presented to execute, and is refused if the
  round changed in between (no stale or concurrent double changes);
* a mandatory **reason** (and evidence where facts are asserted), an immutable
  **audit record**, and **transactional recalculation** of the whole locked round
  through :mod:`diski9.backend.services.settlement`.

Finalised rounds change only through :func:`reopen_round` (owner); routine
settlement and imports never reopen them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, Engine, insert, select

from ...challenge.settle import BLOCKING_CODES, Observation
from ...ingestion.results_fetch import canonical_hash
from ..auth.permissions import Capability, Principal, authorize
from ..db import db_now, transaction
from ..db.schema import designations, settlement_alerts, settlement_versions, snapshot_fixtures
from ..repositories import ops
from ..repositories import results as results_repo
from ..repositories import rounds as rounds_repo
from . import competition
from . import settlement as st
from .common import NotFound, ServiceError
from .results import actor_id, snapshot_id_of
from .rounds import System

#: blocking alerts that an audited confirmation may resolve without a correction
CONFIRMABLE = frozenset({"late_notification"})


class CorrectionRefused(ServiceError):
    code = "correction_refused"


class ConfirmationMismatch(ServiceError):
    """The round changed after the preview; preview again before confirming."""

    code = "confirmation_mismatch"


@dataclass(frozen=True)
class CorrectionInput:
    """An operator's corrected facts for one fixture. ``completed_at``,
    ``actual_kickoff_at`` and ``kickoff_at`` are verified event times or schedules
    from the cited evidence; leave them empty unless the evidence states them."""

    fixture_id: int
    status: str
    ft_home: int | None = None
    ft_away: int | None = None
    completed_at: datetime | None = None
    actual_kickoff_at: datetime | None = None
    kickoff_at: datetime | None = None

    def payload(self) -> dict:
        return {
            k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in asdict(self).items()
        }


@dataclass(frozen=True)
class Impact:
    round_id: UUID
    action: str
    material: bool
    verdict_changes: tuple[dict, ...]
    entry_changes: int
    designation_after: str
    outcome: str
    token: str


@dataclass(frozen=True)
class FinaliseResult:
    round_id: UUID
    finalised: bool
    reason: str | None
    earliest_finalisation: datetime | None
    version: int | None


# ------------------------------------------------------------------ helpers
def _sensitive(actor: Principal | System, cap: Capability) -> UUID:
    if isinstance(actor, System):
        raise CorrectionRefused("This operation needs an authenticated person.")
    authorize(actor, cap)
    return actor.user_id


def _require_text(value: str | None, what: str) -> str:
    if not value or not value.strip():
        raise CorrectionRefused(f"A {what} is required.")
    return value.strip()


def _check_fixture(conn: Connection, round_id: UUID, fixture_id: int) -> None:
    ok = conn.execute(
        select(snapshot_fixtures.c.fixture_id).where(
            snapshot_fixtures.c.snapshot_id == snapshot_id_of(conn, round_id),
            snapshot_fixtures.c.fixture_id == fixture_id,
        )
    ).scalar_one_or_none()
    if ok is None:
        raise CorrectionRefused("That fixture is not on this round's sheet.")


def _hypothetical(c: CorrectionInput, at: datetime) -> Observation:
    return Observation(
        id=-1,
        source="operator",
        observed_at=at,
        status=c.status,
        scheduled_kickoff=c.kickoff_at,
        ft_home=c.ft_home,
        ft_away=c.ft_away,
        actual_kickoff_at=c.actual_kickoff_at,
        completed_at=c.completed_at,
    )


def _impact(action: str, plan: st.Plan, version: int | None, extra: dict) -> Impact:
    changes = tuple(
        {
            "fixture_id": w["fixture_id"],
            "market": w["market"],
            "outcome": w["outcome"],
            "verdict": w["verdict"],
            "rule": w["rule"],
            "material": w["material"],
        }
        for w in plan.verdict_writes
    )
    designation = (plan.designation_write or {}).get("designation") or plan.current_designation
    summary = {
        "action": action,
        "round": str(plan.round_id),
        "version": version,
        "changes": changes,
        "entries": sorted(
            (str(w["entry_id"]), str(w["gross"]), w["complete"], w["basis"])
            for w in plan.entry_writes
        ),
        "designation": designation,
        "outcome": plan.validity.outcome,
        "extra": extra,
    }
    token = hashlib.sha256(json.dumps(summary, sort_keys=True, default=str).encode()).hexdigest()
    return Impact(
        plan.round_id,
        action,
        plan.material,
        changes,
        len(plan.entry_writes),
        designation,
        plan.validity.outcome,
        token[:32],
    )


def _version_number(conn: Connection, round_id: UUID) -> int | None:
    v = st.latest_version(conn, round_id)
    return v.version if v else None


def _plan_with(conn: Connection, round_id: UUID, correction: CorrectionInput | None) -> st.Plan:
    now = db_now(conn)
    extra = {correction.fixture_id: (_hypothetical(correction, now),)} if correction else None
    return st.compute(conn, round_id, evaluated_at=now, extra=extra)


def _insert_correction(
    conn: Connection, r, c: CorrectionInput, *, actor: UUID, reason: str, evidence: str
) -> int:
    base = results_repo.latest_evidence_row(conn, c.fixture_id, mode=r.result_mode, round_id=r.id)
    original = None
    if base is not None:
        original = {
            "status_short": base.status_short,
            "ft_home": base.ft_home,
            "ft_away": base.ft_away,
            "kickoff_at": base.kickoff_at.isoformat() if base.kickoff_at else None,
        }
    raw = {"operator_correction": c.payload(), "round_id": str(r.id)}
    return results_repo.insert_operator_observation(
        conn,
        fixture_id=c.fixture_id,
        observed_at=db_now(conn),
        actor=actor,
        reason=reason,
        evidence=evidence,
        raw=raw,
        raw_hash=canonical_hash(raw),
        status_short=c.status,
        kickoff_at=c.kickoff_at,
        ft_home=c.ft_home,
        ft_away=c.ft_away,
        actual_kickoff_at=c.actual_kickoff_at,
        completed_at=c.completed_at,
        corrects_observation_id=base.id if base is not None else None,
        original_values=original,
        scope_round_id=r.id if r.result_mode == "synthetic" else None,
    )


def _resolve_fixture_alerts(
    conn: Connection, round_id: UUID, fixture_id: int, plan: st.Plan, *, actor, reason, obs_id
) -> None:
    """Alerts for the corrected fixture whose condition the correction removed are
    resolved by it (audited through the correction itself)."""
    current = {a.fingerprint for a in plan.alerts}
    for a in results_repo.open_alerts(conn, round_id):
        if a.fixture_id == fixture_id and a.fingerprint not in current:
            results_repo.resolve_alert(
                conn,
                a.id,
                resolution="corrected",
                reason=reason,
                actor=actor,
                observation_id=obs_id,
            )


def _round(conn: Connection, round_id: UUID):
    try:
        return rounds_repo.lock_round_for_change(conn, round_id)
    except Exception as exc:  # noqa: BLE001
        raise NotFound("No such round.") from exc


# ------------------------------------------------------------------ corrections
def preview_correction(
    engine: Engine, actor: Principal, round_id: UUID, correction: CorrectionInput
) -> Impact:
    _sensitive(actor, Capability.CORRECT_RESULT)
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            r = _round(conn, round_id)
            if r.status not in ("locked", "settling"):
                raise CorrectionRefused(
                    "Only a provisional round can be corrected; a final round needs the owner."
                )
            _check_fixture(conn, round_id, correction.fixture_id)
            plan = _plan_with(conn, round_id, correction)
            return _impact("correct", plan, _version_number(conn, round_id), correction.payload())
        finally:
            trans.rollback()


def correct_result(
    engine: Engine,
    actor: Principal,
    round_id: UUID,
    correction: CorrectionInput,
    *,
    reason: str,
    evidence: str,
    confirmation: str,
) -> st.SettlementResult:
    """Record an audited operator correction (D-35) and recalculate the round."""
    uid = _sensitive(actor, Capability.CORRECT_RESULT)
    reason = _require_text(reason, "reason")
    evidence = _require_text(evidence, "evidence source")
    with transaction(engine) as conn:
        r = _round(conn, round_id)
        if r.status not in ("locked", "settling"):
            raise CorrectionRefused(
                "Only a provisional round can be corrected; a final round needs the owner."
            )
        _check_fixture(conn, round_id, correction.fixture_id)
        expected = _impact(
            "correct",
            _plan_with(conn, round_id, correction),
            _version_number(conn, round_id),
            correction.payload(),
        )
        if expected.token != confirmation:
            raise ConfirmationMismatch("The round changed since the preview. Preview it again.")
        obs = _insert_correction(conn, r, correction, actor=uid, reason=reason, evidence=evidence)
        plan = st.compute(conn, round_id, evaluated_at=db_now(conn))
        run_id, version, new = st.apply(conn, plan, trigger="correction", actor=uid)
        _resolve_fixture_alerts(
            conn, round_id, correction.fixture_id, plan, actor=uid, reason=reason, obs_id=obs
        )
        ops.record_audit(
            conn,
            action="result.correct",
            target_type="fixture",
            target_id=f"{round_id}:{correction.fixture_id}",
            actor=uid,
            actor_role="operator",
            reason=reason,
            before={"observation": results_repo.get_observation(conn, obs).original_values},
            after={"correction": correction.payload(), "observation": obs, "evidence": evidence,
                   "material": plan.material, "version": version},
        )  # fmt: skip
        return st._result(conn, plan, run_id, version, new)


def withdraw_correction(
    engine: Engine,
    actor: Principal,
    round_id: UUID,
    observation_id: int,
    *,
    reason: str,
) -> st.SettlementResult:
    """Withdraw an operator correction by another audited action; the round is
    recalculated on the remaining evidence."""
    uid = _sensitive(actor, Capability.CORRECT_RESULT)
    reason = _require_text(reason, "reason")
    with transaction(engine) as conn:
        r = _round(conn, round_id)
        if r.status not in ("locked", "settling"):
            raise CorrectionRefused("Only a provisional round can be changed.")
        target = results_repo.get_observation(conn, observation_id)
        if target is None or target.source != "operator" or target.withdraws_correction_id:
            raise CorrectionRefused("That is not an operator correction.")
        raw = {"withdraws": observation_id}
        wid = results_repo.insert_operator_observation(
            conn, fixture_id=target.fixture_id, observed_at=db_now(conn), actor=uid,
            reason=reason, evidence=None, raw=raw, raw_hash=canonical_hash(raw),
            withdraws_correction_id=observation_id, scope_round_id=target.scope_round_id,
        )  # fmt: skip
        plan = st.compute(conn, round_id, evaluated_at=db_now(conn))
        run_id, version, new = st.apply(conn, plan, trigger="correction", actor=uid)
        ops.record_audit(
            conn, action="result.withdraw_correction", target_type="fixture",
            target_id=f"{round_id}:{target.fixture_id}", actor=uid, actor_role="operator",
            reason=reason, before={"observation": observation_id}, after={"withdrawal": wid},
        )  # fmt: skip
        return st._result(conn, plan, run_id, version, new)


# ------------------------------------------------------------------ alerts
def resolve_alert(
    engine: Engine, actor: Principal, round_id: UUID, alert_id: int, *, reason: str
) -> str:
    """Resolve an alert by audited confirmation. A ``late_notification`` alert is
    *confirmed* (the cutoff-based void stands); informational alerts are
    *acknowledged*. Every other blocking alert needs a correction instead."""
    uid = _sensitive(actor, Capability.CORRECT_RESULT)
    reason = _require_text(reason, "reason")
    with transaction(engine) as conn:
        _round(conn, round_id)
        a = conn.execute(
            select(settlement_alerts).where(
                settlement_alerts.c.id == alert_id, settlement_alerts.c.round_id == round_id
            )
        ).one_or_none()
        if a is None:
            raise NotFound("No such alert for this round.")
        if a.id not in {x.id for x in results_repo.open_alerts(conn, round_id)}:
            raise CorrectionRefused("That alert is already resolved.")
        if a.code in BLOCKING_CODES and a.code not in CONFIRMABLE:
            raise CorrectionRefused(
                "This alert needs an audited result correction, not a confirmation."
            )
        resolution = "confirmed" if a.code in CONFIRMABLE else "acknowledged"
        results_repo.resolve_alert(conn, a.id, resolution=resolution, reason=reason, actor=uid)
        ops.record_audit(
            conn, action=f"alert.{resolution}", target_type="settlement_alert",
            target_id=str(a.id), actor=uid, actor_role="operator", reason=reason,
            before={"code": a.code, "fixture": a.fixture_id}, after={"resolution": resolution},
        )  # fmt: skip
        return resolution


# ------------------------------------------------------------------ invalidation
def _invalidation_plan(conn: Connection, round_id: UUID, uid: UUID, reason: str) -> st.Plan:
    plan = st.compute(conn, round_id, evaluated_at=db_now(conn))
    cur = st.current_designation(conn, round_id)
    if cur is not None and cur.designation == "void" and cur.basis == "operator":
        raise CorrectionRefused("The round is already invalidated by an operator.")
    plan.designation_write = {
        "round_id": round_id,
        "designation": "void",
        "basis": "operator",
        "provisional": True,
        "actor_user_id": uid,
        "reason": reason,
    }
    return plan


def preview_invalidation(
    engine: Engine, actor: Principal, round_id: UUID, *, reason: str
) -> Impact:
    uid = _sensitive(actor, Capability.VOID_ROUND)
    reason = _require_text(reason, "reason")
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            r = _round(conn, round_id)
            if r.status not in ("locked", "settling"):
                raise CorrectionRefused("Only a provisional round can be invalidated.")
            plan = _invalidation_plan(conn, round_id, uid, reason)
            return _impact("invalidate", plan, _version_number(conn, round_id), {"reason": reason})
        finally:
            trans.rollback()


def invalidate_round(
    engine: Engine, actor: Principal, round_id: UUID, *, reason: str, confirmation: str
) -> st.SettlementResult:
    """Exceptional, audited operator invalidation (D-32b §3 row 6): the whole round
    becomes void; individual settlement evidence is kept."""
    uid = _sensitive(actor, Capability.VOID_ROUND)
    reason = _require_text(reason, "reason")
    with transaction(engine) as conn:
        r = _round(conn, round_id)
        if r.status not in ("locked", "settling"):
            raise CorrectionRefused("Only a provisional round can be invalidated.")
        before = st.current_designation(conn, round_id)
        plan = _invalidation_plan(conn, round_id, uid, reason)
        if (
            _impact("invalidate", plan, _version_number(conn, round_id), {"reason": reason}).token
            != confirmation
        ):
            raise ConfirmationMismatch("The round changed since the preview. Preview it again.")
        run_id, version, new = st.apply(conn, plan, trigger="invalidation", actor=uid)
        ops.record_audit(
            conn, action="round.invalidate", target_type="round", target_id=str(round_id),
            actor=uid, actor_role="operator", reason=reason,
            before={"designation": before.designation if before else None},
            after={"designation": "void", "version": version},
        )  # fmt: skip
        return st._result(conn, plan, run_id, version, new)


# ------------------------------------------------------------------ finalisation
def finalise_round(
    engine: Engine, actor: Principal | System, round_id: UUID, *, as_of: datetime | None = None
) -> FinaliseResult:
    """Finalise a provisional round when every relevant prediction is resolved, no
    settlement-blocking alert is open, the round's validity has been evaluated and
    the database clock has reached max(cutoff, last material change) + the frozen
    correction window (S-02). A final settlement run is made first; if it changes
    anything material, the window restarts and nothing is finalised."""
    uid = actor_id(actor, Capability.RUN_JOBS)
    with transaction(engine) as conn:
        r = _round(conn, round_id)
        if r.status != "settling":
            raise CorrectionRefused("Only a settling round can be finalised.")
        at, override = st.evaluation_time(conn, r, as_of, actor)
        plan = st.compute(conn, round_id, evaluated_at=at, time_override=override)
        run_id = None
        if plan.changed:
            run_id, _, _ = st.apply(conn, plan, trigger="finalise", actor=uid)
        earliest = st.earliest_finalisation(conn, r)

        def refuse(why: str) -> FinaliseResult:
            return FinaliseResult(round_id, False, why, earliest, None)

        if plan.material:
            return refuse("A material change was just recorded; the correction window restarts.")
        if plan.validity.outcome == "not_evaluated":
            return refuse("Some relevant predictions are still pending.")
        if results_repo.open_alerts(conn, round_id, blocking_only=True):
            return refuse("Settlement-blocking alerts need an audited resolution first.")
        if earliest is None or at < earliest:
            return refuse("The correction window has not ended yet.")
        if run_id is None:
            run_id = conn.execute(
                select(st.settlement_runs.c.id)
                .where(st.settlement_runs.c.round_id == round_id,
                       st.settlement_runs.c.status == "succeeded")
                .order_by(st.settlement_runs.c.id.desc()).limit(1)
            ).scalar_one()  # fmt: skip
        cur = st.current_designation(conn, round_id)
        last_eval = st._latest_evaluation(conn, round_id)
        conn.execute(
            insert(designations).values(
                round_id=round_id,
                designation=cur.designation,
                basis=cur.basis if cur.basis in ("operator", "d32b") else "d32b",
                round_evaluation_id=last_eval.id,
                actor_user_id=cur.actor_user_id,
                reason=f"confirmed at finalisation ({cur.reason or cur.basis})",
                provisional=False,
            )
        )
        fields = {} if r.finalised_at is not None else {"finalised_at": at}
        rounds_repo.set_status(conn, round_id, "final", reason="finalised", actor=uid, **fields)
        version = (_version_number(conn, round_id) or 0) + 1
        version_id = conn.execute(
            insert(settlement_versions).values(
                round_id=round_id, version=version, run_id=run_id, kind="final",
                material=False, effective_at=at, actor_user_id=uid,
            ).returning(settlement_versions.c.id)
        ).scalar_one()  # fmt: skip
        # Phase 6C.5: the official weekly results are published atomically with the
        # final settlement version; a failure rolls the finalisation back.
        competition.publish_finalised(conn, round_id, version_id, actor=uid)
        ops.record_audit(
            conn, action="round.finalise", target_type="round", target_id=str(round_id),
            actor=uid, actor_role="system" if uid is None else "operator",
            after={"version": version, "designation": cur.designation,
                   "earliest_finalisation": earliest.isoformat()},
        )  # fmt: skip
        return FinaliseResult(round_id, True, None, earliest, version)


# ------------------------------------------------------------------ owner reopening
def preview_reopen(
    engine: Engine,
    owner: Principal,
    round_id: UUID,
    *,
    correction: CorrectionInput | None = None,
) -> Impact:
    _sensitive(owner, Capability.REOPEN_ROUND)
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            r = _round(conn, round_id)
            if r.status != "final":
                raise CorrectionRefused("Only a final round can be reopened.")
            if correction is not None:
                _check_fixture(conn, round_id, correction.fixture_id)
            plan = _plan_with(conn, round_id, correction)
            payload = correction.payload() if correction else None
            return _impact("reopen", plan, _version_number(conn, round_id), {"correction": payload})
        finally:
            trans.rollback()


def reopen_round(
    engine: Engine,
    owner: Principal,
    round_id: UUID,
    *,
    reason: str,
    evidence: str,
    confirmation: str,
    correction: CorrectionInput | None = None,
) -> st.SettlementResult:
    """Owner-only reopening of a finalised round (S-06): verified owner with recent
    authentication, evidence, reason, preview token, audit, transactional
    recalculation and a new settlement version. The final version stays in history."""
    uid = _sensitive(owner, Capability.REOPEN_ROUND)
    reason = _require_text(reason, "reason")
    evidence = _require_text(evidence, "evidence source")
    with transaction(engine) as conn:
        r = _round(conn, round_id)
        if r.status != "final":
            raise CorrectionRefused("Only a final round can be reopened.")
        payload = correction.payload() if correction else None
        if correction is not None:
            _check_fixture(conn, round_id, correction.fixture_id)
        expected = _impact(
            "reopen",
            _plan_with(conn, round_id, correction),
            _version_number(conn, round_id),
            {"correction": payload},
        )
        if expected.token != confirmation:
            raise ConfirmationMismatch("The round changed since the preview. Preview it again.")
        final_version = _version_number(conn, round_id)
        rounds_repo.set_status(conn, round_id, "settling", reason=f"reopened: {reason}", actor=uid)
        conn.execute(
            insert(settlement_versions).values(
                round_id=round_id, version=final_version + 1, kind="reopened", material=False,
                effective_at=db_now(conn), actor_user_id=uid, reason=reason, evidence=evidence,
            )
        )  # fmt: skip
        obs = None
        if correction is not None:
            r = _round(conn, round_id)
            obs = _insert_correction(
                conn, r, correction, actor=uid, reason=reason, evidence=evidence
            )
        plan = st.compute(conn, round_id, evaluated_at=db_now(conn))
        run_id, version, new = st.apply(conn, plan, trigger="reopen", actor=uid)
        for a in results_repo.open_alerts(conn, round_id):
            if a.code == "post_final_change" or (
                correction is not None
                and a.fixture_id == correction.fixture_id
                and a.fingerprint not in {x.fingerprint for x in plan.alerts}
            ):
                results_repo.resolve_alert(
                    conn, a.id, resolution="corrected" if obs else "acknowledged",
                    reason=reason, actor=uid, observation_id=obs,
                )  # fmt: skip
        ops.record_audit(
            conn, action="round.reopen", target_type="round", target_id=str(round_id),
            actor=uid, actor_role="owner", reason=reason,
            before={"final_version": final_version},
            after={"evidence": evidence, "correction": payload, "version": version,
                   "material": plan.material},
        )  # fmt: skip
        return st._result(conn, plan, run_id, version, new)
