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
from sqlalchemy.dialects.postgresql import insert as pg_insert

from diski9.challenge.config import ChallengeConfig, get_config
from diski9.challenge.roundsheet import RoundSnapshot, SnapshotKind, assess_round
from diski9.challenge.scoring import RoundClassification, classify_round
from diski9.screener.goal_model import GOAL_MODEL_VERSION

from ..auth.accounts import lock_snapshot
from ..auth.permissions import Capability, Forbidden, Principal, authorize
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
from . import championships, snapshots
from .common import LockRefused, NotFound, PublicationRefused, ValidationFailed
from .schedules import (  # noqa: F401
    ScheduleUnavailable,
    current_schedule,
    lock_for_round_creation,
    schedule_at,
)

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
    """The scheduled-job actor (no person): allowed for lock and the other scheduled
    lifecycle steps, and (Stage E.1a) only for :func:`create_scheduled_draft`."""


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
    """The round participants should see: the open round whose deadline is still
    ahead (earliest first); otherwise the most recent round past its deadline
    (open but not yet locked, or locked and later), so "deadline passed" and
    "locked" states stay visible. Database clock. When several open rounds share the
    earliest deadline (only with several test rounds open at once), the most recently
    published one is shown, so the choice is deterministic."""
    with read_only(engine) as conn:
        now = db_now(conn)
        base = select(rounds.c.id)
        if not include_development:
            base = base.where(rounds.c.is_development.is_(False))
        rid = conn.execute(
            base.where(rounds.c.status == "open", rounds.c.deadline_at > now)
            .order_by(rounds.c.deadline_at, rounds.c.published_at.desc(), rounds.c.id)
            .limit(1)
        ).scalar_one_or_none()
        if rid is None:
            rid = conn.execute(
                base.where(rounds.c.status.in_(("open", "locked", "settling", "final")))
                .order_by(rounds.c.deadline_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        return _view(conn, rid) if rid else None


def round_config(conn: Connection, round_id: UUID) -> ChallengeConfig:
    """The configuration a round is bound to: the version recorded at publication,
    or (for a draft) the version of the round's own schedule row. Never the global
    default; an unknown or unregistered version raises ``ConfigError``."""
    r = conn.execute(
        select(rounds.c.config_version, round_schedules.c.config_version.label("schedule_cfg"))
        .select_from(rounds.join(round_schedules, rounds.c.schedule_id == round_schedules.c.id))
        .where(rounds.c.id == round_id)
    ).one_or_none()
    if r is None:
        raise NotFound("No such round.")
    return get_config(r.config_version or r.schedule_cfg)


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


@dataclass(frozen=True)
class PlannedWindow:
    """A round window planned from the schedule row valid now, with that row's id so
    creation can confirm the same row still applies (see ``expected_schedule_id``)."""

    start: datetime
    end: datetime
    schedule_id: int
    schedule_version: int
    config_version: str


def plan_window(
    engine: Engine, iso_year: int, iso_week: int, code: str = "weekend"
) -> PlannedWindow:
    """The window of an ISO week under the ``code`` schedule valid now (database
    clock). Raises :class:`ScheduleUnavailable` when no single row is valid."""
    with read_only(engine) as conn:
        sched = current_schedule(conn, code)
    start, end = weekly_window(sched.window_rule, iso_year, iso_week)
    return PlannedWindow(start, end, sched.id, sched.version, sched.config_version)


def schedule_window(
    engine: Engine, iso_year: int, iso_week: int, code: str = "weekend"
) -> tuple[datetime, datetime]:
    """The window of an ISO week under the ``code`` schedule valid now."""
    w = plan_window(engine, iso_year, iso_week, code)
    return w.start, w.end


# ------------------------------------------------------------------ create
class ScheduleChanged(ScheduleUnavailable):
    """The schedule row valid at creation differs from the one the caller planned
    with (a schedule boundary passed in between). Nothing was created; plan again."""

    code = "schedule_changed"


def schedule_config(conn: Connection, code: str = "weekend") -> ChallengeConfig:
    """The configuration a round created in this transaction under schedule ``code``
    would use: the row valid at the transaction timestamp (development snapshots are
    built before their round exists; pass ``expected_schedule_id`` to
    :func:`create_round` to keep the two consistent). Unknown versions raise
    ``ConfigError`` and an unresolvable schedule :class:`ScheduleUnavailable`; never
    the global default or the latest version."""
    return get_config(current_schedule(conn, code).config_version)


def _check_expected(sched, expected_schedule_id: int | None) -> None:
    if expected_schedule_id is not None and sched.id != expected_schedule_id:
        raise ScheduleChanged(
            f"The {sched.code!r} schedule that applies now (version {sched.version}) is "
            "not the one this round was planned with; nothing was created. Plan again."
        )


def create_round(
    engine: Engine,
    principal: Principal,
    *,
    code: str,
    window_start: datetime,
    window_end: datetime,
    schedule_code: str = "weekend",
    development: bool = False,
    expected_schedule_id: int | None = None,
) -> RoundView:
    """A new ``draft`` round (needs ``round.publish``), bound to the ``schedule_code``
    row valid at this transaction's database timestamp (the round's ``created_at``).
    ``expected_schedule_id``: the row the caller planned the window or snapshot with;
    if another row applies now, :class:`ScheduleChanged` is raised and nothing is
    written."""
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
        lock_for_round_creation(conn)  # before resolving: waits for a schedule change
        sched = current_schedule(conn, schedule_code)
        _check_expected(sched, expected_schedule_id)
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


# ------------------------------------------------------------------ scheduled draft
SCHEDULED_SCHEDULE = "weekend"  # the only schedule the scheduler prepares (Stage E.1a)
SCHEDULED_SERIES = frozenset({"beta"})


@dataclass(frozen=True)
class ScheduledDraft:
    created: bool
    round: RoundView


def scheduled_code(iso_year: int, iso_week: int) -> str:
    """The canonical round code of a weekend-schedule week (same as ``round create``)."""
    return f"{iso_year}-W{iso_week:02d}-{SCHEDULED_SCHEDULE}"


def create_scheduled_draft(
    engine: Engine,
    actor: System,
    *,
    iso_year: int,
    iso_week: int,
    job_run_id: int | None = None,
    expected_schedule_id: int | None = None,
) -> ScheduledDraft:
    """Create the Beta draft for one ISO week of the weekend schedule (Phase 6C.6
    Stage E.1a, ADP-07). **Scheduler only**: the actor must be :data:`SYSTEM`; a
    person uses :func:`create_round` (``round create``). Nothing but the ISO week is
    taken from the caller: the code, window, schedule and series come from the
    active schedule, which must belong to the Beta series. Idempotent: if any round
    already has the code (draft, published, locked or final, created by anyone),
    nothing is written and ``created`` is False. The row, its status history and the
    audit record are written in one transaction. A draft has no snapshot, is not
    visible to participants and is published only by a person (``round publish``).
    ``expected_schedule_id``: the row the caller planned the week with; if another
    row applies at creation, :class:`ScheduleChanged` is raised and nothing is written
    (the scheduler replans on its next tick)."""
    if not isinstance(actor, System):
        raise Forbidden("scheduled_only")
    if isinstance(iso_year, bool) or isinstance(iso_week, bool):
        raise ValidationFailed("Invalid ISO week.", [{"field": "week", "reason": "type"}])
    try:
        date.fromisocalendar(int(iso_year), int(iso_week), 1)
    except (TypeError, ValueError):
        raise ValidationFailed(
            "Invalid ISO week.", [{"field": "week", "reason": "invalid"}]
        ) from None
    code = scheduled_code(iso_year, iso_week)
    with transaction(engine) as conn:
        # one row, at the transaction timestamp: window, series and (at publication)
        # configuration all come from the row the draft is bound to
        lock_for_round_creation(conn)  # before resolving: waits for a schedule change
        sched = current_schedule(conn, SCHEDULED_SCHEDULE)
        _check_expected(sched, expected_schedule_id)
        if sched.series not in SCHEDULED_SERIES:
            raise ValidationFailed(
                "Scheduled drafts are created only for the beta series.",
                [{"field": "series", "reason": "not_beta"}],
            )
        start, end = weekly_window(sched.window_rule, iso_year, iso_week)
        rid = conn.execute(
            pg_insert(rounds)
            .values(
                code=code,
                schedule_id=sched.id,
                series_id=sched.series_id,
                window_start_at=start,
                window_end_at=end,
                is_development=False,
            )
            .on_conflict_do_nothing(index_elements=["code"])
            .returning(rounds.c.id)
        ).scalar_one_or_none()
        if rid is None:  # already exists: never touched
            existing = conn.execute(select(rounds.c.id).where(rounds.c.code == code)).scalar_one()
            return ScheduledDraft(False, _view(conn, existing))
        conn.execute(
            insert(round_status_history).values(
                round_id=rid,
                from_status=None,
                to_status="draft",
                actor_user_id=None,
                job_run_id=job_run_id,
                reason="created (scheduled)",
            )
        )
        ops.record_audit(
            conn,
            action="round.create",
            target_type="round",
            target_id=str(rid),
            actor=None,
            actor_role="system",
            after={"code": code, "development": False, "scheduled": True},
            job_run_id=job_run_id,
        )
        return ScheduledDraft(True, _view(conn, rid))


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
    expected_fingerprint: str | None = None,
) -> RoundView:
    """Validate the opening conditions and freeze the snapshot (needs
    ``round.publish``). Either everything is written - snapshot rows, deadline,
    settlement cutoff, versions and the ``open`` status - or nothing is, and the
    refusal explains why. ``expected_fingerprint`` (Stage E): the fingerprint the
    operator approved; any other snapshot is refused. Every check runs again here,
    under the round's row lock and on the database clock, so nothing validated
    earlier is trusted at publication time."""
    authorize(principal, Capability.PUBLISH_ROUND)
    with transaction(engine) as conn:
        r = rounds_repo.lock_round_for_change(conn, round_id)
        sched = conn.execute(
            select(round_schedules).where(round_schedules.c.id == r.schedule_id)
        ).one()
        now = db_now(conn)
        age_limit = snapshot_age_limit or max_snapshot_age()
        check = _evaluate_publication(r, sched, snapshot, source, now, age_limit)
        problem, details = check.problem, check.details
        config, report, deadline = check.config, check.report, check.deadline
        if expected_fingerprint is not None and snapshot.fingerprint != expected_fingerprint:
            problem = "The snapshot differs from the one approved; nothing was published."
            details = {"approved": expected_fingerprint, "snapshot": snapshot.fingerprint}
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
            # Phase 6C.5: assign the round to its championship when that is already
            # certain (CH-02, CH-03); same transaction, round lock then stream lock
            championships.on_round_event(
                conn, round_id, actor=principal.user_id, cause="round_assigned"
            )
            return _view(conn, round_id)
        code = r.code
    raise _refuse(engine, code, problem, details)


@dataclass(frozen=True)
class _PublicationCheck:
    problem: str | None
    details: dict
    config: Any = None
    report: Any = None  # RoundOpeningReport once the basic checks pass
    deadline: datetime | None = None


def _evaluate_publication(r, sched, snap: RoundSnapshot, source, now, max_age) -> _PublicationCheck:
    """Every publication check, in order, shared by :func:`publish_round` (inside its
    write transaction) and :func:`publication_readiness` (read-only), so the
    readiness preview can never disagree with publication itself."""
    problem, details = _publication_problem(r, sched, snap, source, now, max_age)
    if problem is not None:
        return _PublicationCheck(problem, details)
    config = get_config(sched.config_version)
    report = snap.opening_report(config)
    if not report.opens:
        availability = assess_round(snap, snap.snapshot_at, config)
        return _PublicationCheck(
            f"{availability.title}: {availability.message}",
            {"report": snapshots.report_dict(report), "status": availability.status},
            config,
            report,
        )
    deadline = snap.earliest_kickoff - timedelta(minutes=sched.deadline_buffer_minutes)
    if deadline <= now:
        return _PublicationCheck(
            "The submission deadline for these fixtures has already passed.",
            {"deadline": deadline.isoformat()},
            config,
            report,
            deadline,
        )
    return _PublicationCheck(None, {}, config, report, deadline)


@dataclass(frozen=True)
class PublicationReadiness:
    """What :func:`publish_round` would decide for this snapshot now, without
    writing anything (Phase 6C.6 Stage E). ``issues`` counts the existing
    per-outcome eligibility issues (odds, freshness, bucket bands); no rule is
    added or changed here."""

    round: RoundView
    ready: bool
    problem: str | None
    details: dict
    evaluated_at: datetime
    snapshot_at: datetime
    max_snapshot_age: timedelta
    source: str
    fingerprint: str
    config_version: str
    fixtures: int
    outcomes: int
    leagues: int
    earliest_kickoff: datetime | None
    latest_kickoff: datetime | None
    deadline_at: datetime | None
    settle_cutoff_at: datetime | None
    report: dict | None
    required_by_bucket: dict
    issues: dict
    oldest_observation_at: datetime | None
    newest_observation_at: datetime | None
    max_quote_age_hours: float
    diagnostics: dict


def publication_readiness(
    engine: Engine,
    round_id: UUID,
    snapshot: RoundSnapshot,
    *,
    source: str,
    snapshot_age_limit: timedelta | None = None,
) -> PublicationReadiness:
    """Read-only publication readiness for a draft round: the same checks as
    :func:`publish_round` against the database clock, plus the evidence an operator
    needs to approve publication (pool size, bucket feasibility, odds freshness,
    exclusions). Writes nothing (no job record, audit entry or lock)."""
    from diski9.challenge.structured import assess_outcome

    with read_only(engine) as conn:
        r = conn.execute(select(rounds).where(rounds.c.id == round_id)).one_or_none()
        if r is None:
            raise NotFound("No such round.")
        sched = conn.execute(
            select(round_schedules).where(round_schedules.c.id == r.schedule_id)
        ).one()
        now = db_now(conn)
        view = _view(conn, round_id)
    age_limit = snapshot_age_limit or max_snapshot_age()
    check = _evaluate_publication(r, sched, snapshot, source, now, age_limit)
    config = check.config or get_config(sched.config_version)
    issues: dict[str, int] = {}
    seen: list[datetime] = []
    for o in snapshot.outcomes:
        a = assess_outcome(o, snapshot.snapshot_at, config)
        for i in a.issues:
            issues[str(i.code)] = issues.get(str(i.code), 0) + 1
        if a.eligible and o.latest_observation_at is not None:
            seen.append(o.latest_observation_at)
    latest = snapshots.latest_kickoff(snapshot)
    cutoff = (
        latest + timedelta(hours=sched.settle_cutoff_hours)
        if latest is not None and check.problem is None
        else None
    )
    max_age = config.odds.max_quote_age.total_seconds() / 3600
    return PublicationReadiness(
        round=view,
        ready=check.problem is None,
        problem=check.problem,
        details=check.details,
        evaluated_at=now,
        snapshot_at=snapshot.snapshot_at,
        max_snapshot_age=age_limit,
        source=source,
        fingerprint=snapshot.fingerprint,
        config_version=sched.config_version,
        fixtures=len(snapshot.fixtures),
        outcomes=len(snapshot.outcomes),
        leagues=len({f.league_id for f in snapshot.fixtures}),
        earliest_kickoff=snapshot.earliest_kickoff,
        latest_kickoff=latest,
        deadline_at=check.deadline,
        settle_cutoff_at=cutoff,
        report=snapshots.report_dict(check.report) if check.report is not None else None,
        required_by_bucket=dict(zip(config.bucket_codes, config.sizes, strict=True)),
        issues=dict(sorted(issues.items())),
        oldest_observation_at=min(seen, default=None),
        newest_observation_at=max(seen, default=None),
        max_quote_age_hours=max_age,
        diagnostics=dict(snapshot.diagnostics or {}),
    )


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
        # Phase 6C.5: a practice classification releases a reserved championship slot
        championships.on_round_event(conn, round_id, actor=actor_id, cause="round_assigned")
        return LockResult(_view(conn, round_id), locked, designation, False)
