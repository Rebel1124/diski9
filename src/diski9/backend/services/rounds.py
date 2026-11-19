"""Weekly rounds: creation, publication with frozen snapshots, and lock
(Phase 6C.3, Stage B).

Lifecycle (approved terminology): ``draft`` → ``open`` (published, accepting
entries until the deadline) → ``locked`` (the deadline has passed; the entry set
and the base designation are fixed). Settlement, voids and championship
progression belong to later phases.

All times are compared with the **database clock** inside the write transaction
(``transaction_timestamp()``), never the browser's or the application server's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, insert, select, text, update

from diski9.challenge.config import get_config
from diski9.challenge.roundsheet import RoundSnapshot, SnapshotKind, assess_round
from diski9.challenge.scoring import RoundClassification, classify_round
from diski9.screener.goal_model import GOAL_MODEL_VERSION

from ..auth.accounts import lock_snapshot
from ..auth.permissions import Capability, Principal, authorize
from ..db import db_now, read_only, transaction
from ..db.schema import (
    championship_series,
    designations,
    entries,
    round_schedules,
    round_snapshots,
    round_status_history,
    rounds,
)
from ..repositories import ops, portfolios
from ..repositories import rounds as rounds_repo
from . import snapshots
from .common import LockRefused, NotFound, PublicationRefused, ValidationFailed

MODEL_VERSION = f"goal-model-{GOAL_MODEL_VERSION}"
# Snapshot construction age (approved at the 6C.3 checkpoint): an operational
# safeguard, separate from and in addition to the odds freshness rule (every
# eligible quote verified within 24 hours before the snapshot, unchanged).
DEFAULT_MAX_SNAPSHOT_AGE = timedelta(hours=1)
MAX_SNAPSHOT_AGE_ENV = "DISKI9_SNAPSHOT_MAX_AGE_MINUTES"
SNAPSHOT_AGE_BOUNDS = (1, 180)  # minutes; server configuration only


def max_snapshot_age() -> timedelta:
    """The configured construction-age limit (server environment; default one hour).
    Values outside 1-180 minutes are refused rather than silently used."""
    import os

    raw = os.environ.get(MAX_SNAPSHOT_AGE_ENV)
    if raw in (None, ""):
        return DEFAULT_MAX_SNAPSHOT_AGE
    try:
        minutes = int(raw)
    except ValueError:
        raise ValueError(f"{MAX_SNAPSHOT_AGE_ENV} must be a whole number of minutes") from None
    lo, hi = SNAPSHOT_AGE_BOUNDS
    if not lo <= minutes <= hi:
        raise ValueError(f"{MAX_SNAPSHOT_AGE_ENV} must be between {lo} and {hi} minutes")
    return timedelta(minutes=minutes)


DESIGNATION_OF = {
    RoundClassification.COMPETITIVE: "championship",
    RoundClassification.PRACTICE: "practice",
}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class System:
    """The scheduled-job actor (no person): allowed only for lock."""


SYSTEM = System()


@dataclass(frozen=True)
class RoundView:
    id: UUID
    code: str
    status: str
    is_development: bool
    window_start_at: datetime
    window_end_at: datetime
    published_at: datetime | None
    deadline_at: datetime | None
    settle_cutoff_at: datetime | None
    config_version: str | None
    rules_version: str | None
    scoring_version: str | None
    model_version: str | None
    valid_entries: int | None
    designation: str | None
    fingerprint: str | None
    series: str = "beta"
    snapshot_at: datetime | None = None  # when the competition information was frozen

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def classification(self) -> str | None:
        """``competitive`` or ``practice`` once fixed at the deadline (D-28). The
        stored designation value ``championship`` is the legacy name for a
        competitively classified round; it does **not** mean the round counts
        toward an official championship."""
        return {"championship": "competitive", "practice": "practice"}.get(self.designation or "")

    @property
    def counts_toward_official_championship(self) -> bool:
        """Always False in Phase 6C.3. Official membership needs the ``official``
        series, a started Official Championship 1 (D-38, after D-29 validation and
        launch approval) and the derived membership of Phase 6C.5; beta and
        development rounds never count."""
        return False


@dataclass(frozen=True)
class LockResult:
    round: RoundView
    locked_entries: int
    designation: str
    already_locked: bool


def _role(principal: Principal) -> str:
    return "owner" if "owner" in principal.roles else "operator"


# ------------------------------------------------------------------ reads
def _view(conn: Connection, round_id: UUID) -> RoundView:
    r = conn.execute(select(rounds).where(rounds.c.id == round_id)).one_or_none()
    if r is None:
        raise NotFound("No such round.")
    snap = conn.execute(
        select(round_snapshots.c.fingerprint, round_snapshots.c.as_of).where(
            round_snapshots.c.round_id == round_id
        )
    ).one_or_none()
    fp, as_of = (snap.fingerprint, snap.as_of) if snap else (None, None)
    series = conn.execute(
        select(championship_series.c.code).where(championship_series.c.id == r.series_id)
    ).scalar_one()
    des = conn.execute(
        select(designations.c.designation)
        .where(designations.c.round_id == round_id)
        .order_by(designations.c.created_at.desc(), designations.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return RoundView(
        r.id,
        r.code,
        r.status,
        r.is_development,
        r.window_start_at,
        r.window_end_at,
        r.published_at,
        r.deadline_at,
        r.settle_cutoff_at,
        r.config_version,
        r.rules_version,
        r.scoring_version,
        r.model_version,
        r.valid_entries,
        des,
        fp,
        series,
        as_of,
    )


def get_round(engine: Engine, round_id: UUID) -> RoundView:
    with read_only(engine) as conn:
        return _view(conn, round_id)


def round_id_for_code(engine: Engine, code: str) -> UUID:
    with read_only(engine) as conn:
        rid = conn.execute(select(rounds.c.id).where(rounds.c.code == code)).scalar_one_or_none()
    if rid is None:
        raise NotFound(f"No round with code {code!r}.")
    return rid


def list_rounds(engine: Engine, limit: int = 20) -> list[RoundView]:
    with read_only(engine) as conn:
        ids = (
            conn.execute(select(rounds.c.id).order_by(rounds.c.created_at.desc()).limit(limit))
            .scalars()
            .all()
        )
        return [_view(conn, i) for i in ids]


def current_round(engine: Engine, *, include_development: bool = False) -> RoundView | None:
    """The round participants should see: the open round with the earliest
    deadline, otherwise the most recently locked or later round."""
    with read_only(engine) as conn:
        base = select(rounds.c.id)
        if not include_development:
            base = base.where(rounds.c.is_development.is_(False))
        rid = conn.execute(
            base.where(rounds.c.status == "open").order_by(rounds.c.deadline_at).limit(1)
        ).scalar_one_or_none()
        if rid is None:
            rid = conn.execute(
                base.where(rounds.c.status.in_(("locked", "settling", "final")))
                .order_by(rounds.c.deadline_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        return _view(conn, rid) if rid else None


def published_snapshot(engine: Engine, round_id: UUID) -> RoundSnapshot:
    """The frozen snapshot of a published round (cached per process)."""
    with read_only(engine) as conn:
        return snapshots.CACHE.get(conn, round_id)


# ------------------------------------------------------------------ schedule
def weekly_window(rule: dict[str, Any], iso_year: int, iso_week: int) -> tuple[datetime, datetime]:
    """The round window for an ISO week from a schedule's ``window_rule``: from the
    start weekday and time in that week to the next end weekday and time."""
    from zoneinfo import ZoneInfo

    def at(day: date, spec: dict) -> datetime:
        hh, mm = (int(x) for x in spec["time"].split(":"))
        return datetime.combine(day, time(hh, mm), ZoneInfo(spec.get("tz", "UTC")))

    s, e = rule["start"], rule["end"]
    start_day = date.fromisocalendar(iso_year, iso_week, WEEKDAYS.index(s["weekday"]) + 1)
    start = at(start_day, s)
    end_wd = WEEKDAYS.index(e["weekday"])
    delta = (end_wd - start_day.weekday()) % 7 or 7
    end = at(start_day + timedelta(days=delta), e)
    return start, end


def schedule_window(
    engine: Engine, iso_year: int, iso_week: int, code: str = "weekend"
) -> tuple[datetime, datetime]:
    with read_only(engine) as conn:
        rule = conn.execute(
            select(round_schedules.c.window_rule)
            .where(round_schedules.c.code == code)
            .order_by(round_schedules.c.version.desc())
            .limit(1)
        ).scalar_one()
    return weekly_window(rule, iso_year, iso_week)


# ------------------------------------------------------------------ create
def create_round(
    engine: Engine,
    principal: Principal,
    *,
    code: str,
    window_start: datetime,
    window_end: datetime,
    schedule_code: str = "weekend",
    development: bool = False,
) -> RoundView:
    """A new ``draft`` round (needs ``round.publish``)."""
    authorize(principal, Capability.PUBLISH_ROUND)
    if development != code.startswith("dev-"):
        raise ValidationFailed(
            "Development round codes start with 'dev-'; other codes must not.",
            [{"field": "code", "reason": "development_prefix"}],
        )
    if window_end <= window_start:
        raise ValidationFailed(
            "The round window must end after it starts.",
            [{"field": "window", "reason": "empty"}],
        )
    with transaction(engine) as conn:
        sched = conn.execute(
            select(round_schedules)
            .where(round_schedules.c.code == schedule_code)
            .order_by(round_schedules.c.version.desc())
            .limit(1)
        ).one()
        if conn.execute(select(rounds.c.id).where(rounds.c.code == code)).first():
            raise ValidationFailed(
                f"A round with code {code!r} already exists.",
                [{"field": "code", "reason": "duplicate"}],
            )
        rid = conn.execute(
            insert(rounds)
            .values(
                code=code,
                schedule_id=sched.id,
                series_id=sched.series_id,
                window_start_at=window_start,
                window_end_at=window_end,
                is_development=development,
            )
            .returning(rounds.c.id)
        ).scalar_one()
        conn.execute(
            insert(round_status_history).values(
                round_id=rid,
                from_status=None,
                to_status="draft",
                actor_user_id=principal.user_id,
                reason="created",
            )
        )
        ops.record_audit(
            conn,
            action="round.create",
            target_type="round",
            target_id=str(rid),
            actor=principal.user_id,
            actor_role=_role(principal),
            after={"code": code, "development": development},
        )
        return _view(conn, rid)


# ------------------------------------------------------------------ publish
def _refuse(engine: Engine, code: str, reason: str, details: dict) -> PublicationRefused:
    """Record the refused attempt (its own transaction) and build the error."""
    with transaction(engine) as conn:
        run = ops.start_job(conn, "publish", code, {"refused": True})
        ops.finish_job(conn, run, "failed", error=reason[:500])
    return PublicationRefused(reason, details=details)


def publish_round(
    engine: Engine,
    principal: Principal,
    round_id: UUID,
    snapshot: RoundSnapshot,
    *,
    source: str,
    snapshot_age_limit: timedelta | None = None,
) -> RoundView:
    """Validate the opening conditions and freeze the snapshot (needs
    ``round.publish``). Either everything is written - snapshot rows, deadline,
    settlement cutoff, versions and the ``open`` status - or nothing is, and the
    refusal explains why."""
    authorize(principal, Capability.PUBLISH_ROUND)
    with transaction(engine) as conn:
        r = rounds_repo.lock_round_for_change(conn, round_id)
        sched = conn.execute(
            select(round_schedules).where(round_schedules.c.id == r.schedule_id)
        ).one()
        now = db_now(conn)
        age_limit = snapshot_age_limit or max_snapshot_age()
        problem, details = _publication_problem(r, sched, snapshot, source, now, age_limit)
        if problem is None:
            config = get_config(sched.config_version)
            report = snapshot.opening_report(config)
            if not report.opens:
                availability = assess_round(snapshot, snapshot.snapshot_at, config)
                problem = f"{availability.title}: {availability.message}"
                details = {"report": snapshots.report_dict(report), "status": availability.status}
        if problem is None:
            deadline = snapshot.earliest_kickoff - timedelta(minutes=sched.deadline_buffer_minutes)
            if deadline <= now:
                problem = "The submission deadline for these fixtures has already passed."
                details = {"deadline": deadline.isoformat()}
        if problem is None:
            run = ops.start_job(conn, "publish", r.code, {"source": source})
            snapshots.store_snapshot(
                conn,
                round_id,
                snapshot,
                config,
                source=source,
                report=report,
                model_version=MODEL_VERSION,
                job_run_id=run,
            )
            cutoff = snapshots.latest_kickoff(snapshot) + timedelta(hours=sched.settle_cutoff_hours)
            rounds_repo.set_status(
                conn,
                round_id,
                "open",
                reason=f"published ({source})",
                actor=principal.user_id,
                job_run_id=run,
                published_at=now,
                deadline_at=deadline,
                settle_cutoff_at=cutoff,
                config_version=sched.config_version,
                rules_version=sched.rules_version,
                scoring_version=sched.scoring_version,
                model_version=MODEL_VERSION,
            )
            ops.record_audit(
                conn,
                action="round.publish",
                target_type="round",
                target_id=str(round_id),
                actor=principal.user_id,
                actor_role=_role(principal),
                after={
                    "fingerprint": snapshot.fingerprint,
                    "deadline_at": deadline.isoformat(),
                    "settle_cutoff_at": cutoff.isoformat(),
                    "source": source,
                    "eligible_fixtures": report.eligible_fixtures,
                },
            )
            ops.finish_job(conn, run, "succeeded")
            return _view(conn, round_id)
        code = r.code
    raise _refuse(engine, code, problem, details)


def _publication_problem(r, sched, snap: RoundSnapshot, source, now, max_age):
    if r.status != "draft":
        return f"The round is already {r.status}; a published snapshot never changes.", {}
    if source not in snapshots.SOURCES:
        return "Unknown snapshot source.", {}
    if (source == "development") != bool(r.is_development):
        return (
            "Development fixtures can only be published into development rounds, and "
            "real data only into real rounds.",
            {"source": source, "development_round": r.is_development},
        )
    if snap.kind is not SnapshotKind.LIVE:
        return "A demonstration snapshot cannot be published as a competition round.", {}
    if snap.round_id != r.code:
        return "The snapshot was built for a different round.", {}
    if snap.config_version != sched.config_version:
        return "The snapshot uses a different competition configuration version.", {}
    if snap.snapshot_at > now:
        return "The snapshot construction time is in the future.", {}
    if now - snap.snapshot_at > max_age:
        return (
            "The snapshot is too old to publish; build a fresh one.",
            {"snapshot_at": snap.snapshot_at.isoformat(), "max_age_minutes": max_age / 60},
        )
    if not snap.fixtures:
        return "No supported fixtures in the round window.", {}
    outside = [
        f.fixture_id
        for f in snap.fixtures
        if not (r.window_start_at <= f.kickoff < r.window_end_at) or f.kickoff <= now
    ]
    if outside:
        return (
            "Some fixtures are outside the round window or have already kicked off.",
            {"fixtures": outside[:20]},
        )
    return None, {}


# ------------------------------------------------------------------ lock
_VALID_SUBMISSIONS = text(
    """
    SELECT ss.submission_id
      FROM app.submission_selections ss
      JOIN app.snapshot_offers o
        ON o.snapshot_id = ss.snapshot_id AND o.fixture_id = ss.fixture_id
       AND o.market = ss.market AND o.outcome = ss.outcome
     WHERE ss.submission_id = ANY(:ids)
     GROUP BY ss.submission_id
    HAVING count(*) = 9
       AND count(DISTINCT ss.fixture_id) = 9
       AND bool_and(o.eligible AND o.bucket = ss.bucket)
       AND count(*) FILTER (WHERE ss.bucket = 'A') = 4
       AND count(*) FILTER (WHERE ss.bucket = 'B') = 3
       AND count(*) FILTER (WHERE ss.bucket = 'C') = 2
    """
)


def lock_round(engine: Engine, actor: Principal | System, round_id: UUID) -> LockResult:
    """Close the round at its deadline: lock every active confirmed entry and fix
    the base designation (``championship`` with at least five valid entries,
    otherwise ``practice``; D-28, T-07). Idempotent: a locked round is returned
    unchanged. Refused before the deadline (database clock)."""
    actor_id = None
    if not isinstance(actor, System):
        authorize(actor, Capability.RUN_JOBS)
        actor_id = actor.user_id
    with transaction(engine) as conn:
        r = rounds_repo.lock_round_for_change(conn, round_id)
        if r.status in ("locked", "settling", "final"):
            view = _view(conn, round_id)
            n = conn.execute(
                select(func.count())
                .select_from(entries)
                .where(entries.c.round_id == round_id, entries.c.locked_at.is_not(None))
            ).scalar_one()
            return LockResult(view, n, view.designation or "", True)
        if r.status != "open":
            raise LockRefused(f"Only an open round can be locked (this one is {r.status}).")
        now = db_now(conn)
        if now < r.deadline_at:
            raise LockRefused("The submission deadline has not been reached yet.")
        run = ops.start_job(conn, "lock", r.code)
        candidates = conn.execute(
            select(entries.c.id, entries.c.user_id, entries.c.current_submission_id)
            .where(
                entries.c.round_id == round_id,
                entries.c.state == "confirmed",
                entries.c.current_submission_id.is_not(None),
                entries.c.locked_at.is_(None),
            )
            .order_by(entries.c.created_at)
            .with_for_update()
        ).all()
        valid = set(
            conn.execute(_VALID_SUBMISSIONS, {"ids": [c.current_submission_id for c in candidates]})
            .scalars()
            .all()
        )
        locked = 0
        for c in candidates:
            if c.current_submission_id not in valid:
                continue
            name, privacy = lock_snapshot(conn, c.user_id)
            conn.execute(
                update(entries)
                .where(entries.c.id == c.id)
                .values(
                    locked_at=now,
                    locked_submission_id=c.current_submission_id,
                    public_name_at_lock=name,
                    privacy_mode_at_lock=privacy,
                )
            )
            portfolios.add_event(
                conn, c.id, "locked", submission_id=c.current_submission_id, actor=actor_id
            )
            locked += 1
        designation = DESIGNATION_OF[classify_round(locked, cancelled=False)]
        conn.execute(
            insert(designations).values(
                round_id=round_id,
                designation=designation,
                basis="deadline",
                actor_user_id=actor_id,
                reason=f"{locked} valid entries at the deadline",
            )
        )
        rounds_repo.set_status(
            conn,
            round_id,
            "locked",
            reason="deadline reached",
            actor=actor_id,
            job_run_id=run,
            valid_entries=locked,
        )
        ops.record_audit(
            conn,
            action="round.lock",
            target_type="round",
            target_id=str(round_id),
            actor=actor_id,
            actor_role="system" if actor_id is None else _role(actor),
            after={"valid_entries": locked, "designation": designation},
        )
        ops.finish_job(conn, run, "succeeded")
        return LockResult(_view(conn, round_id), locked, designation, False)
