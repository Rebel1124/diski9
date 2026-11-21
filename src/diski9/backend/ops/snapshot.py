"""A bounded, read-only snapshot of operational state (Phase 6C.6 Stage D).

Every query is either indexed (``job_runs (job, scope, started_at)``,
``rounds (status)``, ``settlement_alerts (round_id, id)``, ``score_sets (round_id,
revision)``) or bounded by time or by the small set of active rounds, so the cost
does not grow with the whole history. Nothing here writes, calls the provider or
runs the expensive integrity inspection (that is :func:`.checks.deep_findings`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, bindparam, text

from ..db import read_only
from ..jobs import locking
from ..services import settlement

SCHEDULER_JOBS = (
    "scheduler.tick",
    "scheduler.lock",
    "scheduler.results",
    "scheduler.results_full",
    "scheduler.settle",
    "scheduler.finalise",
    "scheduler.prepare_draft",  # Stage E.1a
    "scheduler.prepare_readiness",
)
STEP_JOBS = SCHEDULER_JOBS[1:]
PROVIDER_JOBS = ("scheduler.results", "scheduler.results_full")
REQUIRED_TABLES = (
    "app.rounds",
    "app.job_runs",
    "app.audit_log",
    "app.settlement_runs",
    "app.settlement_alerts",
    "app.championship_series",
    "app.score_sets",
)
ACTIVE = ("open", "locked", "settling")


@dataclass
class JobRow:
    id: int
    job: str
    scope: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    api_requests: int = 0

    @property
    def outcome(self) -> str:
        """The outcome class: ``succeeded``, ``running`` or the ``error`` prefix the
        reconciler records (``deferred``, ``retryable_failure``, ...)."""
        if self.status in ("succeeded", "running"):
            return self.status
        if self.error and ":" in self.error:
            head = self.error.split(":", 1)[0]
            if head in (
                "skipped",
                "deferred",
                "retryable_failure",
                "blocking_failure",
                "abandoned",
                "paused",
            ):
                return head
        return self.status

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job": self.job,
            "scope": self.scope,
            "status": self.status,
            "outcome": self.outcome,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "api_requests": self.api_requests,
            "error": self.error,
        }


@dataclass
class RoundFact:
    id: UUID
    code: str
    stream: str
    status: str
    result_mode: str | None
    deadline_at: datetime | None
    settle_cutoff_at: datetime | None
    earliest: datetime | None
    first_kickoff: datetime | None
    blocking_alerts: int
    last_settlement_at: datetime | None
    last_import_at: datetime | None
    finalised_at: datetime | None
    category: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d.pop("id")
        return d


@dataclass
class Snapshot:
    now: datetime
    environment: str
    server_version: str | None = None
    schema_revision: str | None = None
    expected_head: str | None = None
    tables_missing: list[str] = field(default_factory=list)
    query_ms: float | None = None
    ticks: list[JobRow] = field(default_factory=list)
    last_ok_tick: JobRow | None = None
    failures: list[JobRow] = field(default_factory=list)
    running: list[JobRow] = field(default_factory=list)
    abandoned: list[JobRow] = field(default_factory=list)
    streaks: dict[tuple[str, str], tuple[int, str | None]] = field(default_factory=dict)
    rounds: list[RoundFact] = field(default_factory=list)
    official_anomalies: list[str] = field(default_factory=list)
    final_without_results: list[str] = field(default_factory=list)
    settlement_failures: dict[str, int] = field(default_factory=dict)
    provider_day_requests: int = 0
    elapsed_ms: float | None = None
    active_tick: dict | None = None  # live holder of the scheduler lock, with its tick row
    orphan_ticks: list[dict] = field(default_factory=list)  # running, not the active tick
    lock_lost: list[JobRow] = field(default_factory=list)  # ticks that lost the lock (24 h)
    preparation: Any = None  # Stage E.1a: jobs.prepare.PreparationStatus (derived)
    preparation_error: str | None = None

    @property
    def last_tick(self) -> JobRow | None:
        return self.ticks[0] if self.ticks else None


def _rows(conn, sql: str, **params) -> list:
    stmt = text(sql)
    for k, v in params.items():
        if isinstance(v, list | tuple):
            if not v:
                return []  # an empty IN list matches nothing
            stmt = stmt.bindparams(bindparam(k, expanding=True))
            params[k] = list(v)
    return conn.execute(stmt, params).all()


def _job(r) -> JobRow:
    return JobRow(
        r.id,
        r.job,
        r.scope,
        r.status,
        r.started_at,
        r.finished_at,
        r.error,
        getattr(r, "api_requests", 0) or 0,
    )


_JOB_COLS = "id, job, scope, status, started_at, finished_at, error, api_requests"


def classify(f: RoundFact, now: datetime, finalise_warning: timedelta) -> str:
    """Lifecycle position from the competition's own times (no new deadlines)."""
    if f.status == "draft":
        return "awaiting_publication"
    if f.status == "final":
        return "final"
    if f.status == "open":
        return "entries_open" if f.deadline_at and now < f.deadline_at else "awaiting_lock"
    if f.status == "locked":
        return "awaiting_settlement"
    if f.result_mode is None:
        return "needs_result_mode"
    if f.settle_cutoff_at and now < f.settle_cutoff_at:
        return "awaiting_results"
    if f.earliest is None:
        return "awaiting_settlement"
    if now < f.earliest:
        return "correction_window"
    if f.blocking_alerts:
        return "blocked"
    if now >= f.earliest + finalise_warning:
        return "overdue_for_finalisation"
    return "eligible_for_finalisation"


def collect(
    engine: Engine, *, environment: str, finalise_warning: timedelta, jobs: Any = None
) -> Snapshot:
    """Read everything the checks need. ``jobs`` (the scheduler configuration, if
    valid) adds the derived Stage E.1a preparation status of the upcoming week."""
    snap = _collect(engine, environment=environment, finalise_warning=finalise_warning)
    if not snap.tables_missing:
        from ..jobs.prepare import preparation_status

        try:
            snap.preparation = preparation_status(engine, jobs)
        except Exception as exc:  # noqa: BLE001 - reported by the checks, never fatal here
            snap.preparation_error = type(exc).__name__
    return snap


def _collect(engine: Engine, *, environment: str, finalise_warning: timedelta) -> Snapshot:
    from ..db.migrate import head

    t0 = time.monotonic()
    with read_only(engine) as conn:
        q0 = time.monotonic()
        now = conn.execute(text("SELECT transaction_timestamp()")).scalar_one()
        snap = Snapshot(now=now, environment=environment)
        snap.query_ms = round((time.monotonic() - q0) * 1000, 1)
        snap.server_version = conn.execute(text("SHOW server_version")).scalar_one()
        snap.schema_revision = conn.execute(
            text(
                "SELECT version_num FROM public.app_alembic_version "
                "WHERE to_regclass('public.app_alembic_version') IS NOT NULL"
            )
        ).scalar_one_or_none()
        snap.expected_head = head()
        for t in REQUIRED_TABLES:
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar_one() is None:
                snap.tables_missing.append(t)
        if snap.tables_missing:
            return snap
        day = now - timedelta(hours=24)
        week = now - timedelta(days=7)
        snap.ticks = [
            _job(r)
            for r in _rows(
                conn,
                f"SELECT {_JOB_COLS} FROM app.job_runs "
                "WHERE job = 'scheduler.tick' AND scope = 'global' "
                "ORDER BY started_at DESC LIMIT 10",
            )
        ]
        ok = _rows(
            conn,
            f"SELECT {_JOB_COLS} FROM app.job_runs WHERE job = 'scheduler.tick' "
            "AND scope = 'global' AND status = 'succeeded' ORDER BY started_at DESC LIMIT 1",
        )
        snap.last_ok_tick = _job(ok[0]) if ok else None
        snap.failures = [
            _job(r)
            for r in _rows(
                conn,
                f"SELECT {_JOB_COLS} FROM app.job_runs "
                "WHERE job IN :jobs AND status = 'failed' AND started_at >= :day "
                "ORDER BY started_at DESC LIMIT 20",
                jobs=STEP_JOBS,
                day=day,
            )
        ]
        snap.running = [
            _job(r)
            for r in _rows(
                conn,
                f"SELECT {_JOB_COLS} FROM app.job_runs "
                "WHERE job IN :jobs AND status = 'running' AND started_at >= :week "
                "ORDER BY started_at LIMIT 50",
                jobs=SCHEDULER_JOBS,
                week=week,
            )
        ]
        snap.abandoned = [j for j in snap.failures if (j.error or "").startswith("abandoned")]
        snap.lock_lost = [
            _job(r)
            for r in _rows(
                conn,
                f"SELECT {_JOB_COLS} FROM app.job_runs "
                "WHERE job = 'scheduler.tick' AND scope = 'global' AND status = 'failed' "
                "AND started_at >= :day AND error LIKE '%lock lost%' "
                "ORDER BY started_at DESC LIMIT 10",
                day=day,
            )
        ]
        active = locking.active_tick(conn)
        if active is not None:
            row = conn.execute(
                text(
                    "SELECT id, started_at FROM app.job_runs WHERE job = 'scheduler.tick' "
                    "AND scope = 'global' AND started_at >= :week AND args->>'run_token' = :t "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"week": week, "t": active["run_token"] or ""},
            ).first()
            active["tick_id"] = row.id if row else None
            active["started_at"] = row.started_at if row else active["connected_at"]
        snap.active_tick = active
        for t in locking.running_ticks(conn, now):
            if active is not None and t.run_token and t.run_token == active["run_token"]:
                continue
            snap.orphan_ticks.append(
                {"tick_id": t.tick_id, "started_at": t.started_at, "jobs": list(t.job_ids)}
            )
        snap.provider_day_requests = conn.execute(
            text(
                "SELECT coalesce(sum(api_requests), 0) FROM app.job_runs "
                "WHERE job = 'scheduler.provider' AND started_at >= :day"
            ),
            {"day": day},
        ).scalar_one()

        rows = _rows(
            conn,
            """
            SELECT r.id, r.code, r.status, r.is_development, r.result_mode, r.deadline_at,
                   r.settle_cutoff_at, r.correction_window_hours, r.finalised_at,
                   s.code AS series, s.started_at AS series_started
              FROM app.rounds r JOIN app.championship_series s ON s.id = r.series_id
             WHERE r.status IN ('open', 'locked', 'settling')
                OR (r.status = 'draft' AND r.window_end_at > :day)
                OR (r.status = 'final' AND r.finalised_at >= :week)
             ORDER BY r.deadline_at NULLS LAST, r.code LIMIT 500""",
            day=day,
            week=week,
        )
        for r in rows:
            stream = "development" if r.is_development else r.series
            if stream == "official" and r.status != "draft" and r.series_started is None:
                snap.official_anomalies.append(
                    f"official round {r.code} is {r.status} before the official series started"
                )
            earliest = blocking = None
            last_settle = last_import = first_ko = None
            if r.status in ACTIVE:
                if r.status in ("locked", "settling"):
                    earliest = settlement.earliest_finalisation(conn, r)
                blocking = conn.execute(
                    text(
                        "SELECT count(*) FROM app.settlement_alerts a WHERE a.round_id = :r "
                        "AND a.blocking AND NOT EXISTS (SELECT 1 FROM "
                        "app.settlement_alert_resolutions x WHERE x.alert_id = a.id)"
                    ),
                    {"r": r.id},
                ).scalar_one()
                last_settle = conn.execute(
                    text(
                        "SELECT max(started_at) FROM app.settlement_runs WHERE round_id = :r "
                        "AND status = 'succeeded'"
                    ),
                    {"r": r.id},
                ).scalar_one()
                last_import = conn.execute(
                    text(
                        "SELECT max(started_at) FROM app.job_runs WHERE job = 'results-import' "
                        "AND scope = :s"
                    ),
                    {"s": str(r.id)},
                ).scalar_one()
                first_ko = conn.execute(
                    text(
                        "SELECT min(f.kickoff_at_publish) FROM app.snapshot_fixtures f JOIN "
                        "app.round_snapshots s ON s.id = f.snapshot_id WHERE s.round_id = :r"
                    ),
                    {"r": r.id},
                ).scalar_one()
                failed = conn.execute(
                    text(
                        "SELECT count(*) FROM app.settlement_runs WHERE round_id = :r "
                        "AND status = 'failed' AND started_at >= :day"
                    ),
                    {"r": r.id, "day": day},
                ).scalar_one()
                if failed:
                    snap.settlement_failures[r.code] = failed
            f = RoundFact(
                r.id,
                r.code,
                stream,
                r.status,
                r.result_mode,
                r.deadline_at,
                r.settle_cutoff_at,
                earliest,
                first_ko,
                blocking or 0,
                last_settle,
                last_import,
                r.finalised_at,
            )
            f.category = classify(f, now, finalise_warning)
            snap.rounds.append(f)

        codes = [f.code for f in snap.rounds if f.status in ACTIVE]
        hist = _rows(
            conn,
            "SELECT id, job, scope, status, error FROM app.job_runs "
            "WHERE job IN :jobs AND scope IN :codes AND started_at >= :week "
            "AND status <> 'running' ORDER BY id",
            jobs=STEP_JOBS,
            codes=codes,
            week=week,
        )
        for h in hist:
            key = (h.job, h.scope)
            n, err = snap.streaks.get(key, (0, None))
            snap.streaks[key] = (n + 1, h.error) if h.status == "failed" else (0, None)
        snap.streaks = {k: v for k, v in snap.streaks.items() if v[0]}

        official = [r.code for r in rows if not r.is_development and r.series == "official"]
        if official:
            hits = _rows(
                conn,
                "SELECT DISTINCT scope FROM app.job_runs WHERE job IN :jobs "
                "AND scope IN :codes LIMIT 5",
                jobs=STEP_JOBS,
                codes=official,
            )
            snap.official_anomalies += [
                f"scheduler job recorded for official round {h.scope}" for h in hits
            ]
        snap.final_without_results = [
            r.code
            for r in _rows(
                conn,
                """
            SELECT r.code FROM app.rounds r WHERE r.status = 'final'
               AND NOT EXISTS (SELECT 1 FROM app.score_sets ss WHERE ss.round_id = r.id)
             ORDER BY r.code LIMIT 20""",
            )
        ]
    snap.elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    return snap
