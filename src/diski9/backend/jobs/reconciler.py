"""The lifecycle reconciler (Phase 6C.6 Stage C, design §3.2).

One call of :func:`tick` reads the database state of every round in the allowlisted
streams and performs whatever lifecycle step is due **now**, in dependency order,
through the existing services as the explicit :data:`SYSTEM` actor:

==============  ===============================================  ==========================
Step            Due when (database clock)                        Service
==============  ===============================================  ==========================
lock            open round, ``now >= deadline_at``               ``rounds.lock_round``
results         locked/settling real round, provider calls on,   ``results.import_results``
                refresh interval elapsed
settle          first settlement, new evidence, cutoff passed,   ``settlement.settle_round``
                or the routine refresh interval elapsed
results (full)  before finalising a real round: a full re-check  ``results.import_results``
                after the earliest finalisation time             (``full=True``)
finalise        ``now >= earliest_finalisation`` (S-02), no      ``corrections.finalise_round``
                blocking alert                                   (championships inside)
==============  ===============================================  ==========================

It is **level-triggered**: nothing assumes an earlier tick ran, so a tick after an
outage performs every overdue step in order. Every rule (deadline, S-02, alerts,
voids, idempotency, locking) stays in the services, which re-check everything; the
reconciler only decides *when to ask*. There is deliberately **no publication or
round-creation step** (owner decision: Beta publication stays supervised).

Safety: one tick at a time (a transaction-scoped advisory lock held for the whole
tick through :func:`ops.try_job_lock`); each service call is its own transaction;
a failure in one round never stops another; failures back off exponentially from
``job_runs`` history; provider requests are capped per tick and per 24 hours.
"""

from __future__ import annotations

import json
import math
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

import httpx
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from ...api_football.errors import (
    ApiFootballAuthError,
    ApiFootballError,
    ApiFootballQuotaExceededError,
    ForbiddenEndpointError,
    QuotaGuardError,
)
from ..db import db_now, transaction
from ..db.schema import job_runs
from ..db.schema import rounds as rounds_t
from ..repositories import ops
from ..repositories import results as results_repo
from ..services import corrections, results, settlement
from ..services import rounds as rounds_svc
from ..services.common import ServiceError
from ..services.rounds import SYSTEM
from .config import AUTOMATABLE_STREAMS, SchedulerConfig

TICK = "scheduler.tick"
JOB = {
    "lock": "scheduler.lock",
    "results": "scheduler.results",
    "results_full": "scheduler.results_full",
    "settle": "scheduler.settle",
    "settle_final": "scheduler.settle",
    "finalise": "scheduler.finalise",
}
PROVIDER_JOBS = ("scheduler.results", "scheduler.results_full")
MAX_IDS_PER_REQUEST = 20  # the provider's /fixtures ``ids`` limit (results_fetch)
MAX_STEPS_PER_ROUND = 6


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"  # nothing to do now, already done, or waiting for the clock
    DEFERRED = "deferred"  # due but held back: back-off, budget, provider calls off
    RETRYABLE = "retryable_failure"  # a later tick retries (with back-off)
    BLOCKING = "blocking_failure"  # an operator must act (e.g. a blocking alert)
    PLANNED = "planned"  # dry run only


JOB_STATUS = {
    Outcome.SUCCEEDED: "succeeded",
    Outcome.SKIPPED: "skipped",
    Outcome.DEFERRED: "skipped",
    Outcome.RETRYABLE: "failed",
    Outcome.BLOCKING: "failed",
}


@dataclass
class StepReport:
    round_code: str
    stream: str
    step: str
    outcome: Outcome
    detail: str = ""
    job_run_id: int | None = None
    api_requests: int = 0

    def line(self) -> str:
        ref = f" [job {self.job_run_id}]" if self.job_run_id else ""
        req = f", {self.api_requests} provider request(s)" if self.api_requests else ""
        return (
            f"{self.stream} {self.round_code} {self.step}: {self.outcome.value}"
            f"{' - ' + self.detail if self.detail else ''}{req}{ref}"
        )


@dataclass
class TickReport:
    status: str  # completed | disabled | paused | busy | unavailable | planned
    steps: list[StepReport] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tick_run_id: int | None = None
    api_requests: int = 0
    day_requests: int | None = None
    detail: str = ""

    def count(self, outcome: Outcome) -> int:
        return sum(1 for s in self.steps if s.outcome == outcome)

    @property
    def exit_code(self) -> int:
        """0 nothing failed; 1 a retryable failure (or the database was unavailable);
        4 an operator must act (blocking) and nothing retryable failed."""
        if self.status == "unavailable" or self.count(Outcome.RETRYABLE):
            return 1
        if self.count(Outcome.BLOCKING):
            return 4
        return 0


class Provider(Protocol):
    """The results source: ``fetch(ids, allowance)`` returns ``(items, requests)``
    and must never send more than ``allowance`` requests; ``requests_made`` counts
    every request sent so far (retries included)."""

    requests_made: int

    def fetch(self, ids: Sequence[int], allowance: int) -> tuple[list[dict], int]: ...


class BudgetExhausted(Exception):
    def __init__(self, need: int, allowance: int, scope: str) -> None:
        super().__init__(f"needs {need} request(s), {allowance} left ({scope})")
        self.need, self.allowance, self.scope = need, allowance, scope


@dataclass
class _Budget:
    per_tick: int
    day_left: int
    spent: int = 0

    def allowance(self) -> tuple[int, str]:
        tick_left = self.per_tick - self.spent
        if tick_left <= self.day_left:
            return max(tick_left, 0), "per-tick cap"
        return max(self.day_left, 0), "24-hour cap"

    def spend(self, n: int) -> None:
        self.spent += n
        self.day_left -= n


@dataclass(frozen=True)
class _History:
    last_ok_at: datetime | None = None
    last_attempt_at: datetime | None = None
    fails: int = 0
    last_fail_at: datetime | None = None


@dataclass(frozen=True)
class _RoundState:
    id: UUID
    code: str
    stream: str
    status: str
    result_mode: str | None
    deadline_at: datetime | None
    settle_cutoff_at: datetime | None
    now: datetime
    earliest: datetime | None
    blocking_alerts: int
    history: dict[str, _History]


# ------------------------------------------------------------------ database reads
_ROUNDS = """
SELECT r.id, r.code, r.status, r.is_development, s.code AS series
  FROM app.rounds r JOIN app.championship_series s ON s.id = r.series_id
 WHERE r.status IN ('open', 'locked', 'settling')
 ORDER BY r.deadline_at NULLS LAST, r.code
"""
_DRAFTS = """
SELECT r.code, r.is_development, s.code AS series
  FROM app.rounds r JOIN app.championship_series s ON s.id = r.series_id
 WHERE r.status = 'draft' AND r.window_end_at > transaction_timestamp()
 ORDER BY r.window_start_at, r.code
"""


def _stream(is_development: bool, series: str) -> str:
    return "development" if is_development else series


def _candidates(engine: Engine, cfg: SchedulerConfig) -> list[tuple[UUID, str, str]]:
    with transaction(engine) as conn:
        rows = conn.execute(text(_ROUNDS)).all()
    out = []
    for r in rows:
        stream = _stream(r.is_development, r.series)
        # two independent checks: the configured allowlist and the hard-coded set
        if stream in cfg.streams and stream in AUTOMATABLE_STREAMS:
            out.append((r.id, r.code, stream))
    return out


def _history(conn, job: str, scope: str) -> _History:
    jr = job_runs.c
    done = (jr.job == job) & (jr.scope == scope) & (jr.status != "running")
    last_ok = conn.execute(
        select(func.max(jr.id), func.max(jr.started_at)).where(done, jr.status == "succeeded")
    ).one()
    last_attempt = conn.execute(select(func.max(jr.started_at)).where(done)).scalar_one()
    fails = conn.execute(
        select(func.count(), func.max(jr.finished_at)).where(
            done, jr.status == "failed", jr.id > (last_ok[0] or 0)
        )
    ).one()
    return _History(last_ok[1], last_attempt, fails[0], fails[1])


def _state(engine: Engine, rid: UUID, code: str, stream: str) -> _RoundState:
    with transaction(engine) as conn:
        r = conn.execute(select(rounds_t).where(rounds_t.c.id == rid)).one()
        now = db_now(conn)
        earliest = blocking = None
        if r.status in ("locked", "settling"):
            earliest = settlement.earliest_finalisation(conn, r)
            blocking = len(results_repo.open_alerts(conn, rid, blocking_only=True))
        hist = {job: _history(conn, job, code) for job in set(JOB.values())}
    return _RoundState(
        rid, code, stream, r.status, r.result_mode, r.deadline_at, r.settle_cutoff_at,
        now, earliest, blocking or 0, hist,
    )  # fmt: skip


def _day_requests(engine: Engine) -> int:
    with transaction(engine) as conn:
        return conn.execute(
            select(func.coalesce(func.sum(job_runs.c.api_requests), 0)).where(
                job_runs.c.job.in_(PROVIDER_JOBS),
                job_runs.c.started_at >= func.transaction_timestamp() - timedelta(hours=24),
            )
        ).scalar_one()


# ------------------------------------------------------------------ job records
def _begin(engine: Engine, job: str, scope: str, args: dict, host: str | None) -> int:
    with transaction(engine) as conn:
        return ops.start_job(conn, job, scope, args, host)


def _end(engine: Engine, run_id: int, outcome: Outcome, detail: str, requests: int = 0) -> None:
    """Complete a job record. Only status, finish time, request count and error may
    change on a running record (``app.run_guard``), so the outcome class is kept as
    the prefix of ``error`` for anything other than success (``deferred: ...``,
    ``retryable_failure: ...``, ``blocking_failure: ...``, ``skipped: ...``)."""
    with transaction(engine) as conn:
        ops.finish_job(
            conn,
            run_id,
            JOB_STATUS[outcome],
            api_requests=requests,
            error=None if outcome == Outcome.SUCCEEDED else f"{outcome.value}: {detail}"[:500],
        )


def _mark_abandoned(engine: Engine) -> int:
    """Steps left ``running`` by a tick that ended abruptly (the tick lock is held,
    so no live tick owns them) are recorded as failed, so back-off applies."""
    with transaction(engine) as conn:
        return len(
            conn.execute(
                text(
                    "UPDATE app.job_runs SET status = 'failed', finished_at = clock_timestamp(), "
                    "error = 'abandoned: the tick ended before this step finished' "
                    "WHERE status = 'running' AND job LIKE 'scheduler.%' RETURNING id"
                )
            ).all()
        )


# ------------------------------------------------------------------ decisions
def _backoff_until(h: _History, cfg: SchedulerConfig) -> datetime | None:
    if not h.fails or h.last_fail_at is None:
        return None
    delay = min(cfg.retry_base * (2 ** (h.fails - 1)), cfg.retry_max)
    return h.last_fail_at + delay


def _elapsed(since: datetime | None, now: datetime, gap: timedelta) -> bool:
    return since is None or now - since >= gap


def _decide(s: _RoundState, cfg: SchedulerConfig, done: set[str], new_evidence: bool,
            new_full_evidence: bool) -> tuple[list[str], list[StepReport]]:  # fmt: skip
    """The steps due now (in order) and the notes explaining what is not."""
    want: list[str] = []
    notes: list[StepReport] = []

    def note(step: str, outcome: Outcome, detail: str) -> None:
        notes.append(StepReport(s.code, s.stream, step, outcome, detail))

    def ready(step: str) -> bool:
        until = _backoff_until(s.history[JOB[step]], cfg)
        if until is not None and s.now < until:
            note(step, Outcome.DEFERRED, f"retry back-off until {until:%Y-%m-%d %H:%M} UTC")
            return False
        return True

    if s.status == "open":
        if s.deadline_at is not None and s.now >= s.deadline_at:
            if "lock" not in done and ready("lock"):
                want.append("lock")
        elif s.deadline_at is not None:
            note("lock", Outcome.SKIPPED, f"entries open until {s.deadline_at:%Y-%m-%d %H:%M} UTC")
        return want, notes
    if s.status not in ("locked", "settling"):
        return want, notes
    if s.result_mode is None:
        note("settle", Outcome.BLOCKING, "choose a result mode first (dev-results set-mode)")
        return want, notes
    real = s.result_mode == "real"
    provider_round = real and s.stream != "development"

    if provider_round and "results" not in done:
        h = s.history[JOB["results"]]
        if not cfg.provider_calls:
            note("results", Outcome.DEFERRED, "provider calls are off (DISKI9_JOBS_PROVIDER_CALLS)")
        elif _elapsed(h.last_attempt_at, s.now, cfg.results_refresh) and ready("results"):
            want.append("results")

    if "settle" not in done:
        h = s.history[JOB["settle"]]
        cutoff_unsettled = (
            s.settle_cutoff_at is not None
            and s.now >= s.settle_cutoff_at
            and (h.last_ok_at is None or h.last_ok_at < s.settle_cutoff_at)
        )
        if (
            s.status == "locked"
            or new_evidence
            or cutoff_unsettled
            or _elapsed(h.last_attempt_at, s.now, cfg.settle_refresh)
        ) and ready("settle"):
            want.append("settle")
    if want:
        return want, notes  # finalisation is judged on the state after these steps

    if s.status != "settling" or s.earliest is None or s.now < s.earliest:
        if s.status == "settling" and s.earliest is not None:
            note("finalise", Outcome.SKIPPED,
                 f"earliest finalisation {s.earliest:%Y-%m-%d %H:%M} UTC (S-02)")  # fmt: skip
        return want, notes
    if s.blocking_alerts:
        note("finalise", Outcome.BLOCKING,
             f"{s.blocking_alerts} settlement-blocking alert(s) need an operator")  # fmt: skip
        return want, notes
    if real:
        if s.stream == "development":
            note("finalise", Outcome.DEFERRED, "development rounds never call the provider; "
                 "finalise a real-mode development round manually")  # fmt: skip
            return want, notes
        full = s.history[JOB["results_full"]]
        # a full re-check after the earliest finalisation time, made this tick or
        # within the refresh interval (so a long-blocked round is re-checked again)
        fresh = (
            full.last_ok_at is not None
            and full.last_ok_at >= s.earliest
            and ("results_full" in done or s.now - full.last_ok_at <= cfg.results_refresh)
        )
        if not fresh:
            if "results_full" in done:
                return want, notes
            if not cfg.provider_calls:
                note("finalise", Outcome.DEFERRED, "the final results re-check needs provider "
                     "calls (DISKI9_JOBS_PROVIDER_CALLS)")  # fmt: skip
                return want, notes
            last_was_ok = full.last_attempt_at is None or (
                full.last_ok_at is not None and full.last_attempt_at <= full.last_ok_at
            )
            if (last_was_ok or _elapsed(full.last_attempt_at, s.now, cfg.results_refresh)) \
                    and ready("results_full"):  # fmt: skip
                want.append("results_full")
            return want, notes
        if new_full_evidence and "settle_final" not in done and ready("settle_final"):
            return ["settle_final"], notes
    if "finalise" in done:
        return want, notes
    h = s.history[JOB["finalise"]]
    if not _elapsed(h.last_attempt_at, s.now, cfg.settle_refresh):
        note("finalise", Outcome.SKIPPED, "finalisation was attempted recently")
    elif ready("finalise"):
        want.append("finalise")
    return want, notes


# ------------------------------------------------------------------ execution
def _classify(exc: BaseException) -> tuple[Outcome, str]:
    """A user-safe outcome for a failed step (exception messages from outside the
    services are reduced to their type name, so nothing sensitive is logged)."""
    if isinstance(exc, BudgetExhausted):
        return Outcome.DEFERRED, f"provider budget exhausted: {exc}"
    if isinstance(exc, QuotaGuardError | ApiFootballQuotaExceededError):
        return Outcome.DEFERRED, f"provider quota guard ({type(exc).__name__})"
    if isinstance(exc, ApiFootballAuthError | ForbiddenEndpointError):
        return Outcome.BLOCKING, f"provider access refused ({type(exc).__name__})"
    if isinstance(exc, ApiFootballError | httpx.HTTPError):
        return Outcome.RETRYABLE, f"provider error ({type(exc).__name__})"
    if isinstance(exc, results.ResultsRefused):
        return Outcome.RETRYABLE, exc.message
    if isinstance(exc, ServiceError):
        return Outcome.BLOCKING, exc.message
    if isinstance(exc, SQLAlchemyError):
        return Outcome.RETRYABLE, f"database error ({type(exc).__name__})"
    return Outcome.RETRYABLE, f"unexpected error ({type(exc).__name__})"


@dataclass
class _Run:
    engine: Engine
    cfg: SchedulerConfig
    host: str | None
    tick_id: int
    budget: _Budget
    provider_factory: Callable[[], Provider] | None
    provider: Provider | None = None

    def get_provider(self) -> Provider:
        if self.provider is None:
            if self.provider_factory is None:
                raise ServiceError("No provider client is configured for the scheduler.")
            self.provider = self.provider_factory()
        return self.provider

    def execute(self, s: _RoundState, step: str) -> tuple[StepReport, dict[str, Any]]:
        job = JOB[step]
        run_id = _begin(self.engine, job, s.code,
                        {"stream": s.stream, "round_id": str(s.id), "tick": self.tick_id,
                         "step": step}, self.host)  # fmt: skip
        requests, info = 0, {}
        try:
            if step == "lock":
                res = rounds_svc.lock_round(self.engine, SYSTEM, s.id)
                outcome = Outcome.SKIPPED if res.already_locked else Outcome.SUCCEEDED
                detail = (
                    "already locked"
                    if res.already_locked
                    else f"{res.locked_entries} valid entries, {res.designation}"
                )
            elif step in ("results", "results_full"):
                provider = self.get_provider()
                allowance, scope = self.budget.allowance()
                before = provider.requests_made

                def fetch(ids: Sequence[int]) -> tuple[list[dict], int]:
                    need = math.ceil(len(set(ids)) / MAX_IDS_PER_REQUEST)
                    if need > allowance:
                        raise BudgetExhausted(need, allowance, scope)
                    return provider.fetch(ids, allowance)

                try:
                    res = results.import_results(
                        self.engine, SYSTEM, s.id, fetch, full=step == "results_full"
                    )
                finally:
                    requests = provider.requests_made - before
                    self.budget.spend(requests)
                outcome = Outcome.SUCCEEDED
                detail = (f"polled {len(res.polled)}, not due {len(res.skipped)}, "
                          f"new observations {res.recorded}")  # fmt: skip
                info["new_evidence"] = res.recorded > 0
            elif step in ("settle", "settle_final"):
                res = settlement.settle_round(self.engine, SYSTEM, s.id, job_run_id=run_id)
                outcome = Outcome.SUCCEEDED
                detail = f"version {res.version}" if res.version else "no material change"
                detail += f", {res.open_blocking_alerts} blocking alert(s) open"
            elif step == "finalise":
                res = corrections.finalise_round(self.engine, SYSTEM, s.id)
                if res.finalised:
                    outcome, detail = Outcome.SUCCEEDED, f"final (version {res.version})"
                elif res.reason and "alert" in res.reason:
                    outcome, detail = Outcome.BLOCKING, res.reason
                else:
                    outcome, detail = Outcome.SKIPPED, res.reason or "not finalised"
            else:  # pragma: no cover - the step table is closed
                raise ValueError(step)
        except Exception as exc:  # noqa: BLE001 - classified, recorded, never fatal
            outcome, detail = _classify(exc)
        _end(self.engine, run_id, outcome, detail, requests)
        return StepReport(s.code, s.stream, step, outcome, detail, run_id, requests), info


def _process_round(run: _Run, rid: UUID, code: str, stream: str) -> list[StepReport]:
    reports: list[StepReport] = []
    done: set[str] = set()
    new_evidence = new_full = False
    for _ in range(MAX_STEPS_PER_ROUND):
        s = _state(run.engine, rid, code, stream)
        want, notes = _decide(s, run.cfg, done, new_evidence, new_full)
        if not want:
            return reports + notes
        step = want[0]
        rep, info = run.execute(s, step)
        reports.append(rep)
        done.add(step)
        if step == "results":
            new_evidence = bool(info.get("new_evidence"))
        if step == "results_full":
            new_full = bool(info.get("new_evidence"))
        # do not build on a failed step this tick (a failed import must not be
        # followed by a finalisation that relies on it)
        held = rep.outcome in (Outcome.RETRYABLE, Outcome.BLOCKING, Outcome.DEFERRED)
        if held and step in ("lock", "results_full", "settle_final"):
            return reports
    return reports


def _attention(engine: Engine, cfg: SchedulerConfig) -> list[str]:
    with transaction(engine) as conn:
        rows = conn.execute(text(_DRAFTS)).all()
    return [
        f"{_stream(r.is_development, r.series)} {r.code}: draft awaiting operator "
        f"publication (round publish --code {r.code} --operator EMAIL); the scheduler "
        "never publishes"
        for r in rows
        if _stream(r.is_development, r.series) in cfg.streams
    ]


def tick(
    engine: Engine,
    cfg: SchedulerConfig,
    *,
    provider_factory: Callable[[], Provider] | None = None,
    host: str | None = None,
) -> TickReport:
    """Run one reconciliation pass and return what happened (never raises for an
    operational problem: database unavailability is reported, step failures are
    recorded and classified)."""
    if not cfg.enabled:
        return TickReport("disabled", detail="automation is disabled (DISKI9_JOBS_ENABLED)")
    host = host or socket.gethostname()
    try:
        holder = engine.connect()
    except SQLAlchemyError as exc:
        return TickReport("unavailable", detail=f"database unavailable ({type(exc).__name__})")
    try:
        holder.begin()
        if not ops.try_job_lock(holder, TICK, "global"):
            rid = _begin(engine, TICK, "global", {"reason": "busy"}, host)
            _end(engine, rid, Outcome.SKIPPED, "another tick is still running")
            return TickReport("busy", tick_run_id=rid, detail="another tick is still running")
        abandoned = _mark_abandoned(engine)
        tick_id = _begin(engine, TICK, "global",
                         {"streams": list(cfg.streams), "provider_calls": cfg.provider_calls,
                          "abandoned_steps": abandoned}, host)  # fmt: skip
        if cfg.paused:
            _end(engine, tick_id, Outcome.SKIPPED, f"paused: {cfg.pause_reason}")
            return TickReport("paused", tick_run_id=tick_id, detail=f"paused: {cfg.pause_reason}")
        day_used = _day_requests(engine)
        run = _Run(engine, cfg, host, tick_id,
                   _Budget(cfg.max_requests_per_tick, cfg.max_requests_per_day - day_used),
                   provider_factory)  # fmt: skip
        report = TickReport("completed", tick_run_id=tick_id)
        if abandoned:
            report.notes.append(f"{abandoned} step(s) left running by an earlier tick were "
                                "recorded as failed (abandoned)")  # fmt: skip
        for rid, code, stream in _candidates(engine, cfg):
            try:
                report.steps.extend(_process_round(run, rid, code, stream))
            except Exception as exc:  # noqa: BLE001 - isolate rounds from each other
                outcome, detail = _classify(exc)
                report.steps.append(StepReport(code, stream, "round", outcome, detail))
        report.notes.extend(_attention(engine, cfg))
        report.api_requests = run.budget.spent
        report.day_requests = day_used + run.budget.spent
        failed = report.count(Outcome.RETRYABLE) + report.count(Outcome.BLOCKING)
        summary = {o.value: report.count(o) for o in Outcome if o != Outcome.PLANNED}
        _end(engine, tick_id, Outcome.RETRYABLE if failed else Outcome.SUCCEEDED,
             f"{failed} failed step(s); {json.dumps(summary)}", run.budget.spent)  # fmt: skip
        return report
    except SQLAlchemyError as exc:
        return TickReport("unavailable", detail=f"database unavailable ({type(exc).__name__})")
    finally:
        try:
            holder.rollback()  # releases the tick lock
        finally:
            holder.close()


def plan_tick(engine: Engine, cfg: SchedulerConfig) -> TickReport:
    """Dry run: what a tick would ask for first in each round, from the current
    state. Writes nothing, makes no provider call and records no job run. (A real
    tick re-evaluates after each step, so later steps may also run.)"""
    report = TickReport("planned")
    for rid, code, stream in _candidates(engine, cfg):
        s = _state(engine, rid, code, stream)
        want, notes = _decide(s, cfg, set(), False, False)
        report.steps.extend(StepReport(code, stream, w, Outcome.PLANNED, "due now") for w in want)
        report.steps.extend(notes)
    report.notes.extend(_attention(engine, cfg))
    report.day_requests = _day_requests(engine)
    return report
