"""Read-only operator reports for the settlement CLI (Phase 6C.4, Stage E).

Every report is authorised (``jobs.run``) and computed by the existing settlement
services inside a transaction that is always rolled back: nothing is written and
no settlement rule is reimplemented here. Reports contain fixtures, evidence,
verdicts and counts; they never contain participants' identities or emails.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, select

from ..auth.permissions import Capability, Principal
from ..db import db_now
from ..db.schema import settlement_alert_resolutions as SR  # noqa: N812
from ..db.schema import settlement_alerts as SA  # noqa: N812
from ..db.schema import snapshot_fixtures
from ..repositories import results as results_repo
from ..repositories import rounds as rounds_repo
from . import settlement as st
from .common import NotFound
from .results import actor_id, relevant_fixtures, snapshot_id_of


@dataclass(frozen=True)
class FixtureReport:
    fixture_id: int
    home: str
    away: str
    kickoff_at_publish: datetime
    relevant: bool
    observations: tuple[dict, ...]
    rule: str | None
    score: tuple[int, int] | None
    verdicts: tuple[dict, ...]
    alerts: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class RoundReport:
    round_id: UUID
    code: str
    status: str
    is_development: bool
    result_mode: str | None
    deadline_at: datetime | None
    settle_cutoff_at: datetime | None
    correction_window_hours: int | None
    evaluated_at: datetime
    phase: str
    version: int | None
    version_kind: str | None
    designation: str
    validity: str
    pending_predictions: int
    open_blocking_alerts: int
    open_informational_alerts: int
    unsettled_changes: bool
    material_unsettled: bool
    earliest_finalisation: datetime | None
    eligible_to_finalise: bool
    reasons: tuple[str, ...]


LOCKED = frozenset({"locked", "settling", "final"})


def _rollback_conn(engine: Engine):
    conn = engine.connect()
    return conn, conn.begin()


def fixture_report(
    engine: Engine, actor: Principal, round_id: UUID, fixture_id: int | None = None
) -> list[FixtureReport]:
    """Evidence (in receipt order, mode-scoped) and the current resolution for the
    round's fixtures (or one fixture), as a settlement run would see them now."""
    actor_id(actor, Capability.RUN_JOBS)
    conn, trans = _rollback_conn(engine)
    try:
        r = rounds_repo.lock_round_for_change(conn, round_id)
        if r.result_mode is None:
            plan = None
        else:
            plan = st.compute(conn, round_id, evaluated_at=db_now(conn))
        sid = snapshot_id_of(conn, round_id)
        q = select(snapshot_fixtures).where(snapshot_fixtures.c.snapshot_id == sid)
        if fixture_id is not None:
            q = q.where(snapshot_fixtures.c.fixture_id == fixture_id)
        fx = list(conn.execute(q.order_by(snapshot_fixtures.c.kickoff_at_publish)))
        if fixture_id is not None and not fx:
            raise NotFound("That fixture is not on this round's sheet.")
        relevant = relevant_fixtures(conn, round_id) if r.status in LOCKED else {}
        rows = (
            results_repo.observation_rows(
                conn, [f.fixture_id for f in fx], mode=r.result_mode, round_id=round_id
            )
            if r.result_mode
            else []
        )
        by_fixture: dict[int, list] = {}
        for row in rows:
            by_fixture.setdefault(row.fixture_id, []).append(row)
        out = []
        for f in fx:
            res = plan.resolutions.get(f.fixture_id) if plan else None
            out.append(
                FixtureReport(
                    fixture_id=f.fixture_id,
                    home=f.home_team,
                    away=f.away_team,
                    kickoff_at_publish=f.kickoff_at_publish,
                    relevant=f.fixture_id in relevant,
                    observations=tuple(
                        {
                            "id": o.id,
                            "source": o.source,
                            "observed_at": o.observed_at,
                            "status": o.status_short,
                            "score": None if o.ft_home is None else f"{o.ft_home}-{o.ft_away}",
                            "kickoff_at": o.kickoff_at,
                            "first_half_at": o.provider_first_half_at,
                            "completed_at": o.completed_at,
                            "actual_kickoff_at": o.actual_kickoff_at,
                            "corrects": o.corrects_observation_id,
                            "withdraws": o.withdraws_correction_id,
                            "reason": o.reason,
                        }
                        for o in by_fixture.get(f.fixture_id, [])
                    ),
                    rule=res.rule if res else None,
                    score=res.score if res else None,
                    verdicts=tuple(
                        {
                            "market": v.market,
                            "outcome": v.outcome,
                            "verdict": v.verdict,
                            "rule": v.rule,
                        }
                        for v in (res.verdicts if res else ())
                    ),  # fmt: skip
                    alerts=tuple(a.code for a in (res.alerts if res else ())),
                    notes=tuple(res.notes) if res else (),
                )
            )
        return out
    finally:
        trans.rollback()
        conn.close()


def alerts_report(
    engine: Engine, actor: Principal, round_id: UUID, *, include_resolved: bool = False
) -> list[dict]:
    """The round's settlement alerts with their resolution (if any)."""
    actor_id(actor, Capability.RUN_JOBS)
    conn, trans = _rollback_conn(engine)
    try:
        rounds_repo.lock_round_for_change(conn, round_id)
        q = (
            select(SA, SR.c.resolution, SR.c.reason.label("resolution_reason"),
                   SR.c.created_at.label("resolved_at"))
            .outerjoin(SR, SR.c.alert_id == SA.c.id)
            .where(SA.c.round_id == round_id)
            .order_by(SA.c.id)
        )  # fmt: skip
        if not include_resolved:
            q = q.where(SR.c.id.is_(None))
        return [
            {
                "id": a.id,
                "code": a.code,
                "blocking": a.blocking,
                "fixture_id": a.fixture_id,
                "detail": a.detail,
                "created_at": a.created_at,
                "resolution": a.resolution,
                "resolution_reason": a.resolution_reason,
                "resolved_at": a.resolved_at,
            }
            for a in conn.execute(q)
        ]
    finally:
        trans.rollback()
        conn.close()


def round_report(
    engine: Engine, actor: Principal, round_id: UUID, *, as_of: datetime | None = None
) -> RoundReport:
    """Status, settlement version and finalisation eligibility (S-02), computed as
    :func:`~.corrections.finalise_round` would decide it, without writing."""
    actor_id(actor, Capability.RUN_JOBS)
    conn, trans = _rollback_conn(engine)
    try:
        r = rounds_repo.lock_round_for_change(conn, round_id)
        reasons: list[str] = []
        plan = None
        at = db_now(conn)
        if r.result_mode is None and r.status in LOCKED:
            reasons.append("Choose a result mode first (dev-results set-mode).")
        elif r.status in LOCKED:
            at, override = st.evaluation_time(conn, r, as_of, actor)
            plan = st.compute(conn, round_id, evaluated_at=at, time_override=override)
        v = st.latest_version(conn, round_id)
        cur = st.current_designation(conn, round_id)
        open_alerts = results_repo.open_alerts(conn, round_id)
        blocking = sum(1 for a in open_alerts if a.blocking)
        earliest = st.earliest_finalisation(conn, r) if r.status in LOCKED else None
        pending = (
            sum(
                1
                for _, es in plan.entry_results.values()
                for _, verdict in es.legs
                if verdict == "pending"
            )
            if plan
            else 0
        )
        if r.status != "settling":
            reasons.append(
                {
                    "final": "The round is already final.",
                    "locked": "Run settlement first (settle run).",
                }.get(r.status, "Only a settling round can be finalised.")
            )
        if plan is not None:
            if plan.material:
                reasons.append(
                    "New evidence would change the settlement materially; the correction "
                    "window would restart."
                )
            if plan.validity.outcome == "not_evaluated":
                reasons.append("Some relevant predictions are still pending.")
        if blocking:
            reasons.append(f"{blocking} settlement-blocking alert(s) need an audited resolution.")
        if earliest is None or at < earliest:
            reasons.append("The correction window has not ended yet.")
        return RoundReport(
            round_id=round_id,
            code=r.code,
            status=r.status,
            is_development=r.is_development,
            result_mode=r.result_mode,
            deadline_at=r.deadline_at,
            settle_cutoff_at=r.settle_cutoff_at,
            correction_window_hours=r.correction_window_hours,
            evaluated_at=at,
            phase=plan.phase if plan else "-",
            version=v.version if v else None,
            version_kind=v.kind if v else None,
            designation=cur.designation if cur else (plan.base_designation if plan else ""),
            validity=plan.validity.outcome if plan else "not_evaluated",
            pending_predictions=pending,
            open_blocking_alerts=blocking,
            open_informational_alerts=len(open_alerts) - blocking,
            unsettled_changes=bool(plan and plan.changed),
            material_unsettled=bool(plan and plan.material),
            earliest_finalisation=earliest,
            eligible_to_finalise=not reasons,
            reasons=tuple(reasons),
        )
    finally:
        trans.rollback()
        conn.close()


__all__ = ["FixtureReport", "RoundReport", "alerts_report", "fixture_report", "round_report"]
