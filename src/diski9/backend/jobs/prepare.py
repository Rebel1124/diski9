"""Automated Beta draft preparation (Phase 6C.6 Stage E.1a; design ADP-01–ADP-22).

Inside ``jobs tick``, after the lifecycle steps and under the same lock, ownership
checks and time budget, the scheduler:

1. works out the **upcoming competition week** from the active ``weekend`` schedule
   (each instant belongs to exactly one week: from the end of the previous week's
   fixture window to the end of this week's);
2. **creates its Beta draft** once the creation time arrives
   (:func:`rounds.create_scheduled_draft`, scheduler-only, schedule-derived,
   idempotent, audited);
3. **evaluates readiness** of the draft every ``prepare_readiness_interval``:
   the same snapshot builder and validator as ``round readiness`` / ``round
   publish`` (:func:`rounds.publication_readiness`), read-only, against the football
   store as it is now, recorded in the step's job row.

It never publishes, never calls the football-data provider (E.1a) and never
touches a round that already exists. A readiness verdict is advisory: publication
builds, shows, confirms and publishes its own snapshot (Stage E).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select, text

from diski9.challenge.roundsheet import restrict_competitions

from ..db import db_now, transaction
from ..db.schema import job_runs, round_schedules
from ..db.schema import rounds as rounds_t
from ..services import rounds as rounds_svc
from ..services import schedules
from ..services.rounds import SYSTEM
from .config import PREPARABLE_STREAMS, SchedulerConfig
from .locking import LockLost

PREPARE_DRAFT = "scheduler.prepare_draft"
PREPARE_READINESS = "scheduler.prepare_readiness"
PREPARE_JOBS = (PREPARE_DRAFT, PREPARE_READINESS)
STREAM = "beta"
SAFETY_FACTOR = 2.0  # a readiness evaluation starts only with twice its slowest time left
MEASURE_LAST = 10  # recent evaluations used for the time estimate
WEEKDAYS = rounds_svc.WEEKDAYS

# readiness record categories (stored in the job row; parsed by monitoring)
CATEGORIES = ("opening_checks", "stale_odds", "missing_markets", "no_fixtures",
              "deadline_passed", "not_draft", "snapshot", "other")  # fmt: skip


def _now(conn) -> datetime:
    """The clock for week and state decisions: the database clock (one seam, so
    tests can place a tick on any weekday). Readiness itself always evaluates
    against the real database clock."""
    return db_now(conn)


class FootballStoreUnavailable(Exception):
    """The football store (fixtures, odds, Goal Model cache) cannot be read."""


# (round code, window start, window end, as_of, the round's ChallengeConfig) -> snapshot
SnapshotBuilder = Callable[[str, datetime, datetime, datetime, Any], Any]


# ------------------------------------------------------------------ the week
@dataclass(frozen=True)
class Week:
    iso_year: int
    iso_week: int
    code: str
    period_start: datetime  # end of the previous week's fixture window
    window_start: datetime
    window_end: datetime
    target: datetime  # publication target (schedule publish_rule)
    create_at: datetime  # when the draft is created
    schedule_id: int | None = None  # the schedule row this plan was computed from


def _shift(iso_year: int, iso_week: int, weeks: int) -> tuple[int, int]:
    d = date.fromisocalendar(iso_year, iso_week, 1) + timedelta(weeks=weeks)
    y, w, _ = d.isocalendar()
    return y, w


def publication_target(publish_rule: dict, iso_year: int, iso_week: int) -> datetime:
    """The schedule's publication target in that ISO week (e.g. Friday 08:00 SAST)."""
    day = date.fromisocalendar(iso_year, iso_week, WEEKDAYS.index(publish_rule["weekday"]) + 1)
    hh, mm = (int(x) for x in publish_rule["time"].split(":"))
    return datetime.combine(day, dtime(hh, mm), ZoneInfo(publish_rule.get("tz", "UTC")))


def week_at(now: datetime, window_rule: dict, publish_rule: dict, create_lead: timedelta) -> Week:
    """The competition week ``now`` belongs to: the ISO week W such that the end of
    W-1's fixture window <= now < the end of W's (ADP-01)."""
    y, w, _ = now.astimezone(UTC).date().isocalendar()
    if now >= rounds_svc.weekly_window(window_rule, y, w)[1]:
        y, w = _shift(y, w, 1)
    else:
        py, pw = _shift(y, w, -1)
        if now < rounds_svc.weekly_window(window_rule, py, pw)[1]:
            y, w = py, pw
    period_start = rounds_svc.weekly_window(window_rule, *_shift(y, w, -1))[1]
    start, end = rounds_svc.weekly_window(window_rule, y, w)
    target = publication_target(publish_rule, y, w)
    return Week(
        y, w, rounds_svc.scheduled_code(y, w), period_start, start, end, target,
        max(period_start, target - create_lead),
    )  # fmt: skip


def load_schedule(conn) -> Any:
    """The weekend schedule row valid at this transaction's database timestamp (the
    row a draft created now is bound to), with its series code. Never the latest
    version; an unresolvable schedule raises ``ScheduleUnavailable``."""
    return schedules.current_schedule(conn, rounds_svc.SCHEDULED_SCHEDULE)


@dataclass(frozen=True)
class ScheduleBinding:
    """Which schedule row and configuration the week's round is (or will be) bound to.

    ``bound`` is the round's own row when the round exists, otherwise the row valid
    when the draft is due (``max(now, create_at)``). ``later`` is set only when a
    different row is valid at the publication target: the draft keeps ``bound``
    (selection is by creation time) and publishes under its rules."""

    exists: bool
    bound: Any | None
    later: Any | None = None
    published_config: str | None = None
    problem: str | None = None

    def lines(self, week: Week) -> list[str]:
        if self.bound is None:
            return [f"  configuration: unavailable ({self.problem})"]
        b = self.bound
        cfg = self.published_config or b.config_version
        how = ("frozen at publication" if self.published_config
               else "bound at creation" if self.exists
               else f"applies when the draft is created ({_iso(week.create_at)})")  # fmt: skip
        out = [f"  configuration {cfg} ({b.code} v{b.version}; {how})"]
        if self.later is not None and not self.published_config:
            n = self.later
            if self.exists:
                out.append(
                    f"  note: this draft was created under {b.code} v{b.version} "
                    f"({b.config_version}) before {n.code} v{n.version} ({n.config_version}) "
                    "takes effect at "
                    f"{_iso(n.active_from)}; it keeps v{b.version} and will publish under the "
                    "original rules"
                )
            else:
                out.append(
                    f"  note: {n.code} v{n.version} ({n.config_version}) takes effect at "
                    f"{_iso(n.active_from)}, after this draft is due; the draft will be bound to "
                    f"v{b.version} and publish under its rules"
                )
        return out

    def as_dict(self) -> dict[str, Any]:
        def row(r):
            return None if r is None else {
                "schedule_id": r.id, "code": r.code, "version": r.version,
                "config_version": r.config_version, "active_from": r.active_from,
                "active_to": r.active_to,
            }  # fmt: skip

        return {"exists": self.exists, "bound": row(self.bound), "later": row(self.later),
                "published_config": self.published_config, "problem": self.problem}  # fmt: skip


def schedule_binding(conn, week: Week, round_row: Any | None, real: datetime) -> ScheduleBinding:
    """Derived, read-only: the configuration the week's round is bound to and whether
    a different schedule row applies by its publication target."""
    try:
        if round_row is not None:
            bound = conn.execute(
                select(round_schedules).where(round_schedules.c.id == round_row.schedule_id)
            ).one()
            at = real  # the round exists: only a row taking effect from now on matters
        else:
            at = max(real, week.create_at)
            bound = schedules.schedule_at(conn, rounds_svc.SCHEDULED_SCHEDULE, at)
    except schedules.ScheduleUnavailable as exc:
        return ScheduleBinding(round_row is not None, None, problem=str(exc))
    later = None
    if week.target > at:
        try:
            nxt = schedules.schedule_at(conn, rounds_svc.SCHEDULED_SCHEDULE, week.target)
            later = nxt if nxt.id != bound.id else None
        except schedules.ScheduleUnavailable:
            later = None
    published = getattr(round_row, "config_version", None) if round_row is not None else None
    return ScheduleBinding(round_row is not None, bound, later, published)


# ------------------------------------------------------------------ readiness record
def _iso(dt: datetime | None) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ") if dt else "-"


def category(rd) -> str:
    """Why a readiness evaluation is NOT READY, from the validator's own result."""
    details = rd.details or {}
    status = str(details.get("status") or "")
    problem = rd.problem or ""
    if "deadline" in details:
        return "deadline_passed"
    if status in ("insufficient", "infeasible"):
        return "opening_checks"
    if status == "stale_odds":
        return "stale_odds"
    if status == "missing_markets":
        return "missing_markets"
    if status == "no_round" or problem.startswith("No supported fixtures"):
        return "no_fixtures"
    if problem.startswith("The round is already"):
        return "not_draft"
    if "snapshot" in problem.lower():
        return "snapshot"
    return "other"


def encode(rd, seconds: float, data: str | None = None) -> str:
    """The verdict as one line. ``data`` (Stage E.1b) says which football-data sweep
    the evaluation saw: ``complete@<slot>``, ``partial@<slot>(n/8)``, ``none`` or
    ``refresh-off`` — never a claim that a partial sweep refreshed every league."""
    rep = rd.report or {}
    have = rep.get("eligible_outcomes_by_bucket", {})
    buckets = ",".join(f"{b}{have.get(b, 0)}/{n}" for b, n in rd.required_by_bucket.items())
    summary = (
        f"fixtures={rd.fixtures} eligible={rep.get('eligible_fixtures', 0)} "
        f"leagues={rep.get('eligible_leagues', 0)} buckets={buckets} "
        f"earliest={_iso(rd.earliest_kickoff)} deadline={_iso(rd.deadline_at)} "
        f"secs={seconds:.1f}" + (f" data={data}" if data else "")
    )
    missing = (rd.diagnostics or {}).get("fixtures_without_screener_payload") or 0
    if missing:  # Phase 8 CP2A: fixtures excluded for a missing Screener payload
        summary += f" no_payload={missing}"
    if rd.ready:
        return f"ready | {summary}"[:500]
    head = f"not_ready[{category(rd)}]: "
    room = 500 - len(head) - len(summary) - 3
    return f"{head}{(rd.problem or '')[: max(room, 40)]} | {summary}"[:500]


@dataclass(frozen=True)
class Verdict:
    ready: bool
    category: str | None
    problem: str | None
    summary: dict[str, str]
    at: datetime


def decode(error: str | None, at: datetime) -> Verdict | None:
    if not error:
        return None
    head, _, tail = error.partition(" | ")
    summary = dict(p.split("=", 1) for p in tail.split() if "=" in p)
    if head == "ready":
        return Verdict(True, None, None, summary, at)
    if head.startswith("not_ready["):
        cat = head[len("not_ready[") : head.index("]")]
        return Verdict(False, cat, head.split("]: ", 1)[-1], summary, at)
    return None


# ------------------------------------------------------------------ the football store
def football_snapshot_builder(url: str | None = None) -> SnapshotBuilder:
    """Build the live snapshot from the football store exactly as ``round
    readiness`` / ``round publish`` do. Fails closed (``FootballStoreUnavailable``)
    if the store is missing or not set up; never creates it."""

    def build(code: str, window_start: datetime, window_end: datetime, as_of: datetime, config):
        from pathlib import Path

        from sqlalchemy import inspect

        from diski9.app.data import LEAGUE_SHORT
        from diski9.challenge.roundsheet import build_live_snapshot
        from diski9.config import get_settings
        from diski9.db.engine import make_engine

        target = url or get_settings().database_url
        local = target.startswith("sqlite:///") and not target.startswith("sqlite:///:memory:")
        if local and not Path(target.removeprefix("sqlite:///")).is_file():
            raise FootballStoreUnavailable("football store file not found")
        try:
            engine = make_engine(target)
        except Exception as exc:  # noqa: BLE001 - never echo the URL
            raise FootballStoreUnavailable(type(exc).__name__) from None
        try:
            try:
                names = set(inspect(engine).get_table_names())
            except Exception as exc:  # noqa: BLE001
                raise FootballStoreUnavailable(type(exc).__name__) from None
            if not {"fixtures", "screener_results", "odds_quotes"} <= names:
                raise FootballStoreUnavailable("football store is not set up")
            return build_live_snapshot(
                engine, as_of, window_start, window_end, code, LEAGUE_SHORT, config
            )
        finally:
            engine.dispose()

    return build


# ------------------------------------------------------------------ status (derived)
@dataclass
class PreparationStatus:
    enabled: bool
    week: Week | None = None
    state: str = "disabled"
    round_status: str | None = None
    created_by: str | None = None  # scheduled | operator
    verdict: Verdict | None = None
    last_evaluation_at: datetime | None = None
    next_evaluation_at: datetime | None = None
    failing: int = 0
    last_error: str | None = None
    blocked: bool = False  # football store unavailable or access refused
    lapsed_recent: list[str] = field(default_factory=list)
    now: datetime | None = None
    notes: list[str] = field(default_factory=list)
    refresh: Any = None  # Stage E.1b: refresh.RefreshStatus (derived)
    schedule: ScheduleBinding | None = None  # A3 4A: the configuration it binds to

    def as_dict(self) -> dict[str, Any]:
        w = self.week
        return {
            "enabled": self.enabled,
            "state": self.state,
            "week": None if w is None else {
                "code": w.code, "iso_year": w.iso_year, "iso_week": w.iso_week,
                "window_start": w.window_start, "window_end": w.window_end,
                "publication_target": w.target, "create_at": w.create_at,
            },
            "round_status": self.round_status,
            "created_by": self.created_by,
            "verdict": None if self.verdict is None else {
                "ready": self.verdict.ready, "category": self.verdict.category,
                "problem": self.verdict.problem, "summary": self.verdict.summary,
                "at": self.verdict.at,
            },
            "last_evaluation_at": self.last_evaluation_at,
            "next_evaluation_at": self.next_evaluation_at,
            "failing": self.failing,
            "last_error": self.last_error,
            "blocked": self.blocked,
            "lapsed_recent": self.lapsed_recent,
            "refresh": None if self.refresh is None else self.refresh.as_dict(),
            "schedule": None if self.schedule is None else self.schedule.as_dict(),
        }  # fmt: skip


def _last(conn, job: str, scope: str):
    jr = job_runs.c
    return conn.execute(
        select(jr.id, jr.status, jr.started_at, jr.finished_at, jr.error)
        .where(jr.job == job, jr.scope == scope, jr.status != "running")
        .order_by(jr.id.desc())
        .limit(1)
    ).one_or_none()


def _streak(conn, job: str, scope: str) -> tuple[int, str | None]:
    jr = job_runs.c
    rows = conn.execute(
        select(jr.status, jr.error)
        .where(jr.job == job, jr.scope == scope, jr.status != "running")
        .order_by(jr.id.desc())
        .limit(20)
    ).all()
    n = 0
    for r in rows:
        if r.status != "failed":
            break
        n += 1
    return n, (rows[0].error if n else None)


def preparation_status(engine: Engine, cfg: SchedulerConfig | None) -> PreparationStatus:
    """The derived preparation state of the upcoming week (no state of its own:
    rounds and job records only; ADP-14)."""
    on = bool(cfg and cfg.enabled and cfg.prepare and STREAM in cfg.prepare_streams)
    st = PreparationStatus(enabled=on)
    with transaction(engine) as conn:
        now = _now(conn)
        real = db_now(conn)
        st.now = now
        sched = load_schedule(conn)
        lead = cfg.prepare_create_lead if cfg else timedelta(hours=78)
        week = replace(
            week_at(now, sched.window_rule, sched.publish_rule, lead), schedule_id=sched.id
        )
        st.week = week
        row = conn.execute(
            select(rounds_t.c.id, rounds_t.c.status, rounds_t.c.schedule_id,
                   rounds_t.c.config_version).where(rounds_t.c.code == week.code)
        ).one_or_none()  # fmt: skip
        st.schedule = schedule_binding(conn, week, row, real)
        last = _last(conn, PREPARE_READINESS, week.code)
        fails_r, err_r = _streak(conn, PREPARE_READINESS, week.code)
        fails_d, err_d = _streak(conn, PREPARE_DRAFT, week.code)
        st.failing = max(fails_r, fails_d)
        st.last_error = err_r or err_d
        st.blocked = bool(st.last_error and "blocking_failure" in st.last_error)
        if row is not None:
            st.round_status = row.status
            creator = conn.execute(
                text(
                    "SELECT actor_role FROM app.audit_log WHERE target_type = 'round' "
                    "AND target_id = :t AND action = 'round.create' ORDER BY id LIMIT 1"
                ),
                {"t": str(row.id)},
            ).scalar_one_or_none()
            st.created_by = (
                "scheduled" if creator == "system" else ("operator" if creator else None)
            )
        lapsed = (
            conn.execute(
                text(
                    "SELECT code FROM app.rounds WHERE status = 'draft' AND is_development = false "
                    "AND window_end_at <= :now AND window_end_at > :since ORDER BY window_end_at"
                ),
                {"now": now, "since": now - timedelta(days=7)},
            )
            .scalars()
            .all()
        )
        st.lapsed_recent = list(lapsed)
        if cfg is not None and cfg.prepare_refresh:
            from . import refresh

            st.refresh = refresh.refresh_status(conn, cfg, week, now)
    if last is not None and last.status == "succeeded":
        st.verdict = decode(last.error, last.finished_at or last.started_at)
    if last is not None:
        st.last_evaluation_at = last.finished_at or last.started_at
    interval = cfg.prepare_readiness_interval if cfg else timedelta(minutes=30)
    grace = cfg.prepare_grace if cfg else timedelta(hours=6)
    if st.last_evaluation_at is not None:
        st.next_evaluation_at = st.last_evaluation_at + interval
    if row is not None and row.status != "draft":
        st.state = "published"
    elif row is None:
        st.state = "no_draft" if now >= week.create_at else "not_due"
    elif st.verdict is not None and st.verdict.category == "deadline_passed":
        st.state = "lapsed"
    elif st.blocked or (cfg is not None and st.failing >= 3):
        st.state = "intervention"
    elif now >= week.target + grace:
        st.state = "target_missed"
    elif st.verdict is None or real - st.verdict.at > fresh_for(cfg):
        st.state = "draft_not_evaluated"
    elif st.verdict.ready:
        st.state = "draft_ready"
    else:
        st.state = "draft_not_ready"
    if not on and st.state not in ("published",):
        st.notes.append("automated preparation is off (DISKI9_JOBS_PREPARE)")
    return st


# ------------------------------------------------------------------ steps
def _slowest(conn) -> float | None:
    jr = job_runs.c
    recent = (
        select((func.extract("epoch", jr.finished_at - jr.started_at)).label("s"))
        .where(jr.job == PREPARE_READINESS, jr.status == "succeeded", jr.finished_at.isnot(None))
        .order_by(jr.id.desc())
        .limit(MEASURE_LAST)
        .subquery()
    )
    v = conn.execute(select(func.max(recent.c.s))).scalar_one_or_none()
    return float(v) if v is not None else None


def needed_seconds(slowest: float | None, cfg: SchedulerConfig) -> float:
    """Tick time that must remain before an evaluation starts: the configured
    minimum or twice the slowest recent evaluation, whichever is larger."""
    return max(cfg.prepare_min_seconds, SAFETY_FACTOR * (slowest or 0.0))


def _due(cfg: SchedulerConfig, now: datetime, last_ok_at, backoff_until) -> bool:
    """Due when the back-off after a failure has passed and the interval since the
    last *successful* evaluation has elapsed (a failure is retried on back-off, not
    after a full interval)."""
    if backoff_until is not None and now < backoff_until:
        return False
    return last_ok_at is None or now - last_ok_at >= cfg.prepare_readiness_interval


TICK_SLACK = timedelta(minutes=5)  # a tick runs every few minutes


def fresh_for(cfg: SchedulerConfig | None) -> timedelta:
    """How long a verdict counts as current: two intervals plus a tick's slack."""
    interval = cfg.prepare_readiness_interval if cfg else timedelta(minutes=30)
    return 2 * interval + TICK_SLACK


def plan(engine: Engine, cfg: SchedulerConfig) -> tuple[list[tuple[str, str]], Week | None]:
    """The preparation steps due now, as ``(step, detail)``; writes nothing."""
    from .reconciler import _backoff_until, _history

    if not (cfg.prepare and STREAM in cfg.prepare_streams and STREAM in PREPARABLE_STREAMS):
        return [], None
    with transaction(engine) as conn:
        now = _now(conn)  # week decisions
        real = db_now(conn)  # elapsed-time decisions (interval, back-off)
        sched = load_schedule(conn)
        if sched.series not in PREPARABLE_STREAMS:
            return [("prepare_draft", "refused: the weekend schedule is not a beta schedule")], None
        week = replace(week_at(now, sched.window_rule, sched.publish_rule,
                               cfg.prepare_create_lead), schedule_id=sched.id)  # fmt: skip
        row = conn.execute(
            select(rounds_t.c.id, rounds_t.c.status).where(rounds_t.c.code == week.code)
        ).one_or_none()
        hd = _history(conn, PREPARE_DRAFT, week.code)
        hr = _history(conn, PREPARE_READINESS, week.code)
        refresh_steps, busy, swept_at = [], False, None
        if cfg.prepare_refresh:
            from . import refresh

            planned, _ = refresh.plan(conn, cfg, week, None if row is None else row.status,
                                      now, real)  # fmt: skip
            refresh_steps = [(p.step, p.detail(week.code)) for p in planned]
            busy = refresh.in_progress(conn, cfg, week, now)
            closed = refresh.latest_closed(conn, week.code)
            swept_at = closed["finished_at"] if closed else None
    steps: list[tuple[str, str]] = []
    if row is None:
        if now >= week.create_at:
            until = _backoff_until(hd, cfg)
            if until is None or real >= until:
                steps.append(("prepare_draft", f"create {week.code}"))
        return steps + refresh_steps, week
    steps += refresh_steps
    # Stage E.1b: no evaluation while a sweep is part-way (it closes as complete or
    # partial within refresh_partial_after); a newly closed sweep is evaluated at once
    new_data = swept_at is not None and (hr.last_ok_at is None or swept_at > hr.last_ok_at)
    backoff = _backoff_until(hr, cfg)
    due = _due(cfg, real, hr.last_ok_at, backoff) or (
        new_data and (backoff is None or real >= backoff)
    )
    if row.status == "draft" and now < week.window_end and due and not busy:
        steps.append(("prepare_readiness", f"evaluate {week.code}"))
    return steps, week


def run_preparation(run, report) -> None:
    """Preparation for the upcoming Beta week, inside a tick (after the lifecycle
    steps). Raises ``LockLost`` / the tick-budget signal like lifecycle steps."""
    from .reconciler import Outcome, StepReport

    steps, week = plan(run.engine, run.cfg)
    before = len(report.steps)
    if any(step == "prepare_draft" for step, _ in steps):
        rep = _draft_step(run, week)
        report.steps.append(rep)
        if rep.outcome != Outcome.SUCCEEDED and rep.outcome != Outcome.SKIPPED:
            return
    if week is not None and run.cfg.prepare_refresh:
        # Stage E.1b: refresh the football store for the current slot (between draft
        # creation and readiness; same lock, ownership checks and time budget)
        from . import refresh

        with transaction(run.engine) as conn:
            status = conn.execute(
                select(rounds_t.c.status).where(rounds_t.c.code == week.code)
            ).scalar_one_or_none()
        refresh.run_refresh(run, report, week, status)
        # Phase 8 R2: a closed competitive sweep of an open rolling round -> one edition
        from . import edition_step

        edition_step.run_editions(run, report, week, status)
    # readiness after creation and refresh, from the state they left
    more, _ = plan(run.engine, run.cfg)
    if any(step == "prepare_readiness" for step, _ in more):
        report.steps.append(_readiness_step(run, week))
    if week is not None and len(report.steps) == before:
        report.steps.append(StepReport(week.code, STREAM, "prepare", Outcome.SKIPPED,
                                       _quiet_reason(run.engine, run.cfg, week)))  # fmt: skip


def _quiet_reason(engine: Engine, cfg: SchedulerConfig, week: Week) -> str:
    with transaction(engine) as conn:
        now = _now(conn)
        row = conn.execute(
            select(rounds_t.c.status).where(rounds_t.c.code == week.code)
        ).scalar_one_or_none()
    if row is None:
        return f"draft due {_iso(week.create_at)}"
    if row != "draft":
        return f"already {row}"
    if now >= week.window_end:
        return "fixture window ended"
    if cfg.prepare_refresh:
        from . import refresh

        with transaction(engine) as conn:
            if refresh.in_progress(conn, cfg, week, now):
                return "readiness waits for the data refresh in progress"
    return "readiness evaluated recently"


def _draft_step(run, week: Week):
    from .reconciler import Outcome, StepReport, _begin, _classify, _end

    run.check()  # owner and budget before starting
    run_id = _begin(run.engine, PREPARE_DRAFT, week.code,
                    {"stream": STREAM, "iso_year": week.iso_year, "iso_week": week.iso_week,
                     "tick": run.tick_id, "run_token": run.token, "step": "prepare_draft"},
                    run.host)  # fmt: skip
    try:
        # pinned to the schedule row the week was planned from (A3 4B): if a schedule
        # change committed in between, nothing is written and the next tick replans
        res = rounds_svc.create_scheduled_draft(
            run.engine, SYSTEM, iso_year=week.iso_year, iso_week=week.iso_week, job_run_id=run_id,
            expected_schedule_id=week.schedule_id,
        )  # fmt: skip
        if res.created:
            r = res.round  # the created round's own window, never the plan's
            outcome, detail = (
                Outcome.SUCCEEDED,
                (
                    f"draft created for {_iso(r.window_start_at)} to {_iso(r.window_end_at)}; "
                    "readiness is evaluated separately; publication stays with an operator"
                ),
            )
        else:
            outcome, detail = Outcome.SKIPPED, f"exists ({res.round.status}); not changed"
    except rounds_svc.ScheduleChanged as exc:
        outcome, detail = Outcome.RETRYABLE, f"{exc.message} (replanned on the next tick)"
    except Exception as exc:  # noqa: BLE001 - classified, recorded, never fatal
        outcome, detail = _classify(exc)
    _end(run.engine, run_id, outcome, detail)
    return StepReport(week.code, STREAM, "prepare_draft", outcome, detail, run_id)


def _readiness_step(run, week: Week):
    from ..repositories import ops
    from .reconciler import JOB_STATUS, Outcome, StepReport, _begin, _classify, _end

    with transaction(run.engine) as conn:
        slowest = _slowest(conn)
        rid = conn.execute(
            select(rounds_t.c.id).where(rounds_t.c.code == week.code)
        ).scalar_one_or_none()
    need = needed_seconds(slowest, run.cfg)
    # the lock-recovery threshold must exceed the longest possible tick: never start
    # an evaluation whose measured cost could push a tick past it
    limit = (run.cfg.abandon_after - run.cfg.tick_budget).total_seconds() / SAFETY_FACTOR
    if slowest is not None and slowest > limit:
        return StepReport(week.code, STREAM, "prepare_readiness", Outcome.BLOCKING,
                          f"readiness evaluation takes {slowest:.0f} s, too long to run safely "
                          f"inside a tick (limit {limit:.0f} s); evaluate with round readiness "
                          "and review the abandonment threshold")  # fmt: skip
    left = run.deadline - time.monotonic()
    if left < need:
        return StepReport(week.code, STREAM, "prepare_readiness", Outcome.DEFERRED,
                          f"needs about {need:.0f} s of tick time, {max(left, 0):.0f} s left; "
                          "the next tick evaluates")  # fmt: skip
    run.check()
    run_id = _begin(run.engine, PREPARE_READINESS, week.code,
                    {"stream": STREAM, "round_id": str(rid), "tick": run.tick_id,
                     "run_token": run.token, "step": "prepare_readiness",
                     "needed_seconds": round(need, 1)}, run.host)  # fmt: skip
    started = time.monotonic()
    lost: LockLost | None = None
    try:
        with transaction(run.engine) as conn:
            as_of = db_now(conn)
            config = rounds_svc.round_config(conn, rid)  # the draft's own schedule (never default)
            competitions = rounds_svc.round_competitions(conn, rid)
            data = "refresh-off"
            if run.cfg.prepare_refresh:
                from . import refresh

                data = refresh.data_label(refresh.latest_closed(conn, week.code))
        builder = run.snapshot_builder or football_snapshot_builder()
        snap = restrict_competitions(
            builder(week.code, week.window_start, week.window_end, as_of, config), competitions
        )
        rd = rounds_svc.publication_readiness(run.engine, rid, snap, source="football-db")
        seconds = time.monotonic() - started
        run.lock.verify()  # still the owner before recording the verdict
        with transaction(run.engine) as conn:
            ops.finish_job(conn, run_id, JOB_STATUS[Outcome.SUCCEEDED],
                           error=encode(rd, seconds, data))  # fmt: skip
        verdict = "READY for operator review" if rd.ready else f"NOT READY: {rd.problem}"
        return StepReport(week.code, STREAM, "prepare_readiness", Outcome.SUCCEEDED,
                          f"{verdict} ({seconds:.1f} s; data {data}; advisory, nothing "
                          "published)", run_id)  # fmt: skip
    except LockLost as exc:
        lost = exc
        outcome, detail = Outcome.RETRYABLE, f"lock lost: {exc}"
    except FootballStoreUnavailable as exc:
        outcome, detail = Outcome.BLOCKING, f"football store unavailable ({exc})"
    except Exception as exc:  # noqa: BLE001 - classified, recorded, never fatal
        outcome, detail = _classify(exc)
    _end(run.engine, run_id, outcome, detail)
    if lost is not None:
        raise lost
    return StepReport(week.code, STREAM, "prepare_readiness", outcome, detail, run_id)


def attention(engine: Engine, cfg: SchedulerConfig) -> list[str]:
    """One note for the upcoming week, for ``jobs tick`` / ``jobs status``."""
    if not (cfg.prepare and STREAM in cfg.prepare_streams):
        return []
    st = preparation_status(engine, cfg)
    w = st.week
    if w is None:
        return []
    msg = {
        "not_due": f"draft due {_iso(w.create_at)}",
        "no_draft": "draft due but not created yet",
        "draft_not_evaluated": "draft prepared; readiness not evaluated recently",
        "draft_ready": "draft READY for operator review (round readiness, then round publish)",
        "draft_not_ready": f"draft NOT READY: {st.verdict.problem if st.verdict else ''}",
        "target_missed": "publication target passed without publication",
        "lapsed": "the week can no longer be published (deadline passed)",
        "intervention": f"preparation needs an operator ({st.last_error or 'repeated failures'})",
        "published": "published",
    }.get(st.state, st.state)
    return [f"{STREAM} {w.code} preparation: {msg}; publication target {_iso(w.target)}; the "
            "scheduler never publishes"]  # fmt: skip


STATE_LABELS = {
    "disabled": "automated preparation off",
    "not_due": "draft not due yet",
    "no_draft": "no draft (due)",
    "draft_not_evaluated": "draft prepared; readiness not evaluated recently",
    "draft_not_ready": "draft prepared but NOT READY",
    "draft_ready": "draft READY for operator review",
    "target_missed": "publication target missed",
    "lapsed": "lapsed (can no longer be published)",
    "intervention": "needs an operator",
    "published": "published",
}


def preparation_lines(st: PreparationStatus) -> list[str]:
    """Human-readable preparation status for ``ops status`` and ``jobs status``."""
    w = st.week
    if w is None:
        return ["preparation: unavailable"]
    lines = [
        f"preparation ({'on' if st.enabled else 'off'}): {w.code} - "
        f"{STATE_LABELS.get(st.state, st.state)}",
        f"  window {_iso(w.window_start)} to {_iso(w.window_end)}; draft due "
        f"{_iso(w.create_at)}; publication target {_iso(w.target)}",
    ]
    if st.schedule is not None:
        lines.extend(st.schedule.lines(w))
    if st.round_status:
        lines.append(f"  round status {st.round_status}"
                     + (f" (created by {st.created_by})" if st.created_by else ""))  # fmt: skip
    if st.verdict is not None:
        v = st.verdict
        what = "READY" if v.ready else f"NOT READY [{v.category}] {v.problem}"
        s = v.summary
        lines.append(f"  last evaluation {_iso(v.at)}: {what}")
        if s:
            lines.append(f"    fixtures {s.get('fixtures', '-')}, "
                         f"eligible {s.get('eligible', '-')}, "
                         f"leagues {s.get('leagues', '-')}, buckets {s.get('buckets', '-')}, "
                         f"deadline {s.get('deadline', '-')}"
                         + (f", data {s['data']}" if s.get("data") else ""))  # fmt: skip
    if st.next_evaluation_at and st.state not in ("published", "lapsed"):
        lines.append(f"  next evaluation from {_iso(st.next_evaluation_at)}")
    if st.failing:
        lines.append(f"  failing {st.failing} time(s) in a row: {st.last_error}")
    for c in st.lapsed_recent:
        lines.append(f"  lapsed (last 7 days): {c}")
    if st.refresh is not None:
        from .refresh import refresh_lines

        lines.extend(refresh_lines(st.refresh))
    lines.append("  readiness is advisory: publish with round readiness / round publish "
                 "(an authenticated person); the scheduler never publishes")  # fmt: skip
    return lines
