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
reconciler only decides *when to ask*. There is deliberately **no publication
step** (owner decision: Beta publication stays supervised). Stage E.1a adds, after
the lifecycle steps and only when ``DISKI9_JOBS_PREPARE`` is on, the creation of the
upcoming Beta draft and read-only readiness evaluations (:mod:`.prepare`).

Safety: one tick at a time (a transaction-scoped advisory lock held for the whole
tick through :func:`ops.try_job_lock`); each service call is its own transaction;
a failure in one round never stops another; failures back off exponentially from
``job_runs`` history; provider requests are capped per tick and per 24 hours.
"""

from __future__ import annotations

import json
import math
import os
import socket
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
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
    ApiFootballRateLimitError,
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
from . import locking
from .config import AUTOMATABLE_STREAMS, SchedulerConfig
from .locking import BudgetExhausted, LockLost, PacingBacklog, ProviderCooldown

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
    # completed | disabled | paused | busy | indeterminate | lock_lost | unavailable |
    # unsafe_connection | planned
    status: str
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
        """0 nothing failed (also busy, indeterminate, paused, disabled); 1 a retryable
        failure, the lock was lost or the database was unavailable; 2 the lock
        connection is unsafe (transaction pooler); 4 an operator must act (blocking)
        and nothing retryable failed."""
        if self.status == "unsafe_connection":
            return 2
        if self.status in ("unavailable", "lock_lost") or self.count(Outcome.RETRYABLE):
            return 1
        if self.count(Outcome.BLOCKING):
            return 4
        return 0


class Provider(Protocol):
    """The results source. ``fetch(ids, reserve)`` returns ``(items, requests)`` and
    must call ``reserve()`` immediately before **every** request it sends (retries
    included); ``reserve`` records the request durably and raises when a cap is
    reached or the tick no longer owns the scheduler lock. ``requests_made`` counts
    requests sent (for reporting)."""

    requests_made: int

    def fetch(self, ids: Sequence[int], reserve: Callable[[], None]) -> tuple[list[dict], int]: ...


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
    """Scheduler provider requests recorded in the last 24 hours (the ledger)."""
    with transaction(engine) as conn:
        return locking.usage(conn, "")[1]


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
    if isinstance(exc, ProviderCooldown | PacingBacklog):
        return Outcome.DEFERRED, f"provider pacing: {exc}"
    if isinstance(exc, ApiFootballRateLimitError):
        return Outcome.RETRYABLE, "provider rate limited (ApiFootballRateLimitError)"
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


class _BudgetSpent(Exception):
    """The tick's time budget is used up: start no new step (R5)."""


@dataclass
class _Run:
    engine: Engine
    cfg: SchedulerConfig
    host: str | None
    tick_id: int
    lock: locking.TickLock
    token: str
    deadline: float  # time.monotonic() after which no new step starts
    provider_factory: Callable[[], Provider] | None
    provider: Provider | None = None
    # Stage E.1a: builds the read-only live snapshot for readiness (default: the
    # football store, exactly as ``round readiness`` / ``round publish`` do)
    snapshot_builder: Callable[..., Any] | None = None
    # Stage E.1b: the football store for refresh (default: DISKI9_DATABASE_URL) and the
    # sleep used for provider pacing (tests pass a fake)
    store_factory: Callable[[], Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    rate_limited: bool = False  # a provider rate limit was hit in this tick

    def reserver(self, scope: str, klass: str = locking.RESULTS,
                 check: Callable[[], None] | None = None) -> Callable[[], None]:  # fmt: skip
        """The pre-send hook for one provider attempt: owner check, optional extra
        check (the E.1b quota floor), durable reservation with class-aware caps and a
        paced send slot, then the wait for that slot (never longer than the
        configured maximum)."""
        prep = klass == locking.PREPARATION
        caps = locking.Caps(
            self.cfg.max_requests_per_tick,
            self.cfg.max_requests_per_day,
            self.cfg.nonessential_per_day if prep else None,
            self.cfg.results_reserve if prep else 0,
        )

        def reserve() -> None:
            self.lock.verify()
            if check is not None:
                check()
            wait = locking.reserve(self.engine, token=self.token, tick_id=self.tick_id,
                                   scope=scope, per_tick=caps.per_tick, per_day=caps.per_day,
                                   klass=klass, caps=caps,
                                   interval=self.cfg.provider_min_interval,
                                   max_wait=self.cfg.provider_max_wait)  # fmt: skip
            if wait > 0:
                self.sleep(wait)

        return reserve

    def observe_quota(self, provider: Any) -> None:
        """Record the provider's latest daily figures (headers), if it reported any."""
        quota = getattr(provider, "quota", None)
        if quota and quota[0] is not None:
            locking.record_quota(self.engine, quota[0], quota[1], "header")

    def note_rate_limit(self, exc: BaseException, scope: str) -> None:
        """Persist a provider-requested pause so every later request honours it."""
        if isinstance(exc, ApiFootballRateLimitError):
            self.rate_limited = True
            seconds = exc.retry_after if exc.retry_after else 60.0
            locking.record_cooldown(self.engine, seconds, scope, "provider rate limit")

    def get_provider(self) -> Provider:
        if self.provider is None:
            if self.provider_factory is None:
                raise ServiceError("No provider client is configured for the scheduler.")
            self.provider = self.provider_factory()
        return self.provider

    def check(self) -> None:
        """Before starting any work: still the owner (R3) and within budget (R5)."""
        self.lock.verify()
        if time.monotonic() >= self.deadline:
            raise _BudgetSpent()

    def execute(self, s: _RoundState, step: str) -> tuple[StepReport, dict[str, Any]]:
        job = JOB[step]
        run_id = _begin(self.engine, job, s.code,
                        {"stream": s.stream, "round_id": str(s.id), "tick": self.tick_id,
                         "run_token": self.token, "step": step}, self.host)  # fmt: skip
        requests, info = 0, {}
        lost: LockLost | None = None
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
                allowance, scope = locking.allowance(
                    self.engine, self.token, self.cfg.max_requests_per_tick,
                    self.cfg.max_requests_per_day)  # fmt: skip
                before = provider.requests_made

                # immediately before every attempt: owner, then durable record (class
                # results: may use the whole cap, including the reserve), then pacing
                reserve = self.reserver(s.code)

                def fetch(ids: Sequence[int]) -> tuple[list[dict], int]:
                    need = math.ceil(len(set(ids)) / MAX_IDS_PER_REQUEST)
                    if need > allowance:
                        raise BudgetExhausted(need, allowance, scope)
                    return provider.fetch(ids, reserve)

                try:
                    res = results.import_results(
                        self.engine, SYSTEM, s.id, fetch, full=step == "results_full"
                    )
                finally:
                    requests = provider.requests_made - before
                    _safe(lambda: self.observe_quota(provider), [], "recording provider quota")
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
        except LockLost as exc:
            lost = exc
            outcome, detail = Outcome.RETRYABLE, f"lock lost: {exc}"
        except Exception as exc:  # noqa: BLE001 - classified, recorded, never fatal
            outcome, detail = _classify(exc)
            _safe(lambda e=exc: self.note_rate_limit(e, s.code), [], "recording a cooldown")
        _end(self.engine, run_id, outcome, detail, requests)
        if lost is not None:
            raise lost  # stop the tick: no follow-on step without ownership
        return StepReport(s.code, s.stream, step, outcome, detail, run_id, requests), info


def _process_round(run: _Run, rid: UUID, code: str, stream: str) -> list[StepReport]:
    reports: list[StepReport] = []
    try:
        return _process_round_steps(run, rid, code, stream, reports)
    except (LockLost, _BudgetSpent) as exc:
        exc.reports = reports  # keep what was done before stopping
        raise


def _process_round_steps(run: _Run, rid: UUID, code: str, stream: str,
                         reports: list[StepReport]) -> list[StepReport]:  # fmt: skip
    done: set[str] = set()
    new_evidence = new_full = False
    for _ in range(MAX_STEPS_PER_ROUND):
        s = _state(run.engine, rid, code, stream)
        want, notes = _decide(s, run.cfg, done, new_evidence, new_full)
        if not want:
            return reports + notes
        step = want[0]
        run.check()  # owner and budget, before every step
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
    extra: list[str] = []
    if cfg.prepare:
        from . import prepare

        failed: list[str] = []
        extra = _safe(lambda: prepare.attention(engine, cfg), failed, "preparation status") or []
        extra += failed
    return extra + [
        f"{_stream(r.is_development, r.series)} {r.code}: draft awaiting operator "
        f"publication (round publish --code {r.code} --operator EMAIL); the scheduler "
        "never publishes"
        for r in rows
        if _stream(r.is_development, r.series) in cfg.streams
    ]


def _safe(call, notes: list[str], what: str) -> Any:
    """Run a bookkeeping call; a failure becomes a note (never replaces the outcome)."""
    try:
        return call()
    except Exception as exc:  # noqa: BLE001
        notes.append(f"{what} failed ({type(exc).__name__})")
        return None


def tick(
    engine: Engine,
    cfg: SchedulerConfig,
    *,
    provider_factory: Callable[[], Provider] | None = None,
    host: str | None = None,
    lock_url: str | None = None,
    snapshot_builder: Callable[..., Any] | None = None,
    store_factory: Callable[[], Any] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> TickReport:
    """Run one reconciliation pass and return what happened. Never raises for an
    operational problem (database unavailable, lock lost, cleanup failure): each is
    reported with its own status and exit code. ``lock_url`` is the direct or
    session-mode connection for the tick lock (default: the engine's URL)."""
    if not cfg.enabled:
        return TickReport("disabled", detail="automation is disabled (DISKI9_JOBS_ENABLED)")
    host = host or socket.gethostname()
    url = lock_url or engine.url.render_as_string(hide_password=False)
    try:
        locking.check_lock_url(url)
    except locking.ConnectionModeError as exc:
        return TickReport("unsafe_connection", detail=str(exc))
    token = uuid.uuid4().hex
    lock = locking.TickLock(url, token)
    started = time.monotonic()
    report: TickReport | None = None
    tick_id: int | None = None
    try:
        try:
            got = lock.acquire()
        except LockLost as exc:
            report = TickReport("unsafe_connection", detail=f"the scheduler lock could not be "
                                f"verified on one server session: {exc}")  # fmt: skip
            return report
        except SQLAlchemyError as exc:
            report = TickReport(
                "unavailable", detail=f"database unavailable ({type(exc).__name__})"
            )
            return report
        if not got:
            rid = _begin(engine, TICK, "global", {"reason": "busy", "run_token": token}, host)
            _end(engine, rid, Outcome.SKIPPED, "another tick is still running")
            report = TickReport("busy", tick_run_id=rid, detail="another tick is still running")
            return report
        with transaction(engine) as conn:
            abandoned, unsure = locking.classify_running(conn, db_now(conn), cfg.abandon_after)
        n_abandoned = locking.mark_abandoned(
            engine, [i for t in abandoned for i in t.job_ids],
            f"tick {abandoned[0].tick_id} lost its lock and exceeded the maximum tick "
            "duration" if abandoned else "")  # fmt: skip
        if unsure:
            ids = ", ".join(str(t.tick_id) for t in unsure)
            detail = (
                f"indeterminate: tick {ids} lost its lock and may still be finishing; no "
                f"lifecycle work until it completes or {cfg.abandon_after} has passed"
            )
            rid = _begin(engine, TICK, "global", {"reason": "indeterminate", "run_token": token,
                                                  "waiting_for": ids}, host)  # fmt: skip
            _end(engine, rid, Outcome.SKIPPED, detail)
            report = TickReport("indeterminate", tick_run_id=rid, detail=detail)
            return report
        hold = None
        if cfg.provider_calls:  # Stage F2 safeguard D: no provider calls after a DB restore
            from diski9.backup.records import provider_hold

            with transaction(engine) as conn:
                hold = provider_hold(conn)
            if hold is not None:
                cfg = replace(cfg, provider_calls=False, prepare_refresh=False)
                provider_factory = None
        tick_id = _begin(engine, TICK, "global",
                         {"streams": list(cfg.streams), "provider_calls": cfg.provider_calls,
                          "run_token": token, "holder_pid": lock.pid, "os_pid": os.getpid(),
                          "abandoned_steps": n_abandoned}, host)  # fmt: skip
        if cfg.paused:
            _end(engine, tick_id, Outcome.SKIPPED, f"paused: {cfg.pause_reason}")
            report = TickReport("paused", tick_run_id=tick_id, detail=f"paused: {cfg.pause_reason}")
            return report
        run = _Run(engine, cfg, host, tick_id, lock, token,
                   started + cfg.tick_budget.total_seconds(), provider_factory,
                   snapshot_builder=snapshot_builder, store_factory=store_factory,
                   sleep=sleep or time.sleep)  # fmt: skip
        report = TickReport("completed", tick_run_id=tick_id)
        if hold is not None:
            report.notes.append(hold.describe())
        if n_abandoned:
            report.notes.append(f"{n_abandoned} step(s) of a tick that lost its lock more than "
                                f"{cfg.abandon_after} ago were recorded as abandoned")  # fmt: skip
        try:
            for rid, code, stream in _candidates(engine, cfg):
                try:
                    report.steps.extend(_process_round(run, rid, code, stream))
                except (LockLost, _BudgetSpent) as stop:
                    report.steps.extend(getattr(stop, "reports", []))
                    raise
                except Exception as exc:  # noqa: BLE001 - isolate rounds from each other
                    outcome, detail = _classify(exc)
                    report.steps.append(StepReport(code, stream, "round", outcome, detail))
            # Stage E.1a: draft preparation after every lifecycle step, same lock and budget
            if cfg.prepare:
                from . import prepare

                try:
                    prepare.run_preparation(run, report)
                except (LockLost, _BudgetSpent):
                    raise
                except Exception as exc:  # noqa: BLE001 - never stops the tick record
                    outcome, detail = _classify(exc)
                    report.steps.append(StepReport("-", "beta", "prepare", outcome, detail))
        except _BudgetSpent:
            report.steps.append(StepReport("-", "-", "tick", Outcome.DEFERRED,
                                           f"tick budget of {cfg.tick_budget} used; remaining "
                                           "work continues next tick"))  # fmt: skip
        lock.verify()  # still the owner when the tick's own records are completed
        report.notes.extend(_attention(engine, cfg))
        with transaction(engine) as conn:
            report.api_requests, report.day_requests = locking.usage(conn, token)
        failed = report.count(Outcome.RETRYABLE) + report.count(Outcome.BLOCKING)
        summary = {o.value: report.count(o) for o in Outcome if o != Outcome.PLANNED}
        _end(engine, tick_id, Outcome.RETRYABLE if failed else Outcome.SUCCEEDED,
             f"{failed} failed step(s); {json.dumps(summary)}", report.api_requests)  # fmt: skip
        return report
    except LockLost as exc:
        report = report or TickReport("lock_lost", tick_run_id=tick_id)
        report.status, report.detail = "lock_lost", f"lock lost: {exc}"
        if tick_id is not None:
            notes: list[str] = []
            requests = _safe(lambda: _usage_of(engine, token), notes, "reading provider usage")
            why = f"lock lost: {exc}"
            _safe(
                lambda: _end(engine, tick_id, Outcome.RETRYABLE, why, requests or 0),
                notes,
                "recording the lost lock",
            )
            report.notes.extend(notes)
        return report
    except SQLAlchemyError as exc:
        report = report or TickReport("unavailable", tick_run_id=tick_id)
        report.status = "unavailable"
        report.detail = f"database unavailable ({type(exc).__name__})"
        return report
    except BaseException as exc:
        # interrupted in-process (KeyboardInterrupt, SystemExit, an unexpected error):
        # this tick knows it is ending, so it records its own steps as abandoned
        if tick_id is not None:
            kind = type(exc).__name__
            _safe(
                lambda: locking.mark_own_interrupted(engine, tick_id, kind),
                [],
                "recording the interruption",
            )
        raise
    finally:
        note = lock.release()
        if note and report is not None:
            report.notes.append(note)


def _usage_of(engine: Engine, token: str) -> int:
    with transaction(engine) as conn:
        return locking.usage(conn, token)[0]


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
    if cfg.prepare:
        from . import prepare

        steps, week = prepare.plan(engine, cfg)
        code = week.code if week else "-"
        report.steps.extend(
            StepReport(code, prepare.STREAM, step, Outcome.PLANNED, detail)
            for step, detail in steps
        )
    report.notes.extend(_attention(engine, cfg))
    report.day_requests = _day_requests(engine)
    return report
