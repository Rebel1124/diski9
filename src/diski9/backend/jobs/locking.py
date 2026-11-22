"""Scheduler tick ownership, abandonment and provider-request accounting
(Phase 6C.6 Stage D remediation R1–R6).

**Root cause of the Stage D defect.** The accepted Stage C tick held a
*transaction-scoped* advisory lock on a connection whose transaction stayed open
for the whole tick. PostgreSQL's ``idle_in_transaction_session_timeout`` (common on
hosted databases) terminated that connection during a slow provider call; the lock
vanished, a second tick took over while the first was still working, and the second
marked the first one's live steps as abandoned.

**Fix.**

* **R1** :class:`TickLock` holds a *session-level* advisory lock
  (``pg_try_advisory_lock``) on a dedicated autocommit connection that is never in a
  transaction, so idle-in-transaction limits do not apply; it is released
  explicitly, and implicitly if the connection dies.
* **R2** :func:`lock_url` refuses transaction-pooler connections (a session lock is
  meaningless through one); a separate direct or session-mode
  ``DISKI9_JOBS_DATABASE_URL`` may be given. At acquisition and at every check the
  server backend must stay the same and must show the lock, which also catches an
  incorrectly labelled pooler.
* **R3** Every tick has a unique run token (also the holder's
  ``application_name``). :meth:`TickLock.verify` runs before every step and before
  every provider request; a lost or unverifiable lock raises :class:`LockLost` and
  the tick stops starting work.
* **R4** :func:`classify_running`: a ``running`` step left by another tick is marked
  abandoned only when its tick started longer ago than ``abandon_after`` (longer
  than any live tick can run, given R5). Younger ones are *indeterminate*: the new
  tick does no lifecycle work and reports it. A tick interrupted in-process marks
  its own steps (it knows it is ending).
* **R5** a tick time budget and bounded provider timeouts/retries (reconciler).
* **R6** :meth:`TickLock.release` never raises; cleanup problems are reported
  without replacing the original outcome.

**Provider budget.** Each provider request is recorded *before* it is sent, as one
``job_runs`` row (``job = 'scheduler.provider'``, ``api_requests = 1``), in a short
transaction serialised by a transaction-level advisory lock that also re-checks the
per-tick and rolling 24-hour caps. A crash after sending cannot lose the count, a
failed or retried request is counted, and concurrent callers cannot spend the same
allowance. The count is conservative: a request recorded but never sent (for
example a crash between the two) is counted as spent.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Engine, create_engine, pool, text
from sqlalchemy.engine import make_url

from ..db import transaction
from .config import ConfigError

TICK_KEY = "diski9:scheduler.tick:global"  # the same key format as ops.try_job_lock
BUDGET_KEY = "diski9:scheduler.provider_budget:global"
APP_PREFIX = "diski9-tick:"
LEDGER_JOB = "scheduler.provider"
TRANSACTION_POOLER_PORTS = frozenset({6543})  # Supabase's transaction pooler
SCHEDULER_JOBS = (
    "scheduler.tick", "scheduler.lock", "scheduler.results", "scheduler.results_full",
    "scheduler.settle", "scheduler.finalise",
    # Stage E.1a: preparation steps get the same interruption and abandonment handling
    "scheduler.prepare_draft", "scheduler.prepare_readiness",
    # Stage E.1b: football-data refresh steps, likewise
    "scheduler.prepare_refresh", "scheduler.prepare_screener",
)  # fmt: skip
# Stage E.1b: request classes recorded on each ledger row (``args.class``). Rows
# without a class (written before E.1b) count as results traffic (owner decision D-2).
RESULTS = "results"
PREPARATION = "preparation"
COOLDOWN_JOB = "scheduler.provider_cooldown"  # provider asked us to wait (completed rows)
QUOTA_JOB = "scheduler.provider_quota"  # provider quota observations (completed rows)

_HELD = """
SELECT pg_backend_pid() AS pid, EXISTS (
  SELECT 1 FROM pg_locks
   WHERE locktype = 'advisory' AND granted AND pid = pg_backend_pid() AND objsubid = 1
     AND classid::bigint = ((hashtextextended(:k, 0) >> 32) & 4294967295)
     AND objid::bigint = (hashtextextended(:k, 0) & 4294967295)) AS held
"""
ACTIVE_TICK_SQL = """
SELECT a.pid, a.application_name, a.backend_start
  FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
 WHERE l.locktype = 'advisory' AND l.granted AND l.objsubid = 1
   AND l.classid::bigint = ((hashtextextended(:k, 0) >> 32) & 4294967295)
   AND l.objid::bigint = (hashtextextended(:k, 0) & 4294967295)
"""


class LockLost(Exception):
    """The tick no longer provably owns the scheduler lock: stop starting work."""


class ConnectionModeError(ConfigError):
    """The lock connection would go through a transaction pooler (unsafe)."""


def check_lock_url(url: str, mode: str = "direct") -> str:
    """Refuse known transaction-pooler connections. Messages never contain the URL."""
    if mode not in ("direct", "session"):
        raise ConnectionModeError(
            "DISKI9_JOBS_DATABASE_MODE must be direct or session: the scheduler lock "
            "cannot be held through a transaction pooler"
        )
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001 - never echo the URL
        raise ConnectionModeError("the scheduler database URL is not a valid URL") from None
    if parsed.port in TRANSACTION_POOLER_PORTS:
        raise ConnectionModeError(
            "the scheduler database URL uses port 6543 (a transaction pooler); use a direct "
            "connection or the session pooler (port 5432) in DISKI9_JOBS_DATABASE_URL"
        )
    if str(parsed.query.get("pgbouncer", "")).lower() in ("1", "true"):
        raise ConnectionModeError("the scheduler database URL is marked as a PgBouncer pooler")
    return url


def lock_url(env: Mapping[str, str] | None = None, settings=None) -> str:
    """The URL for the tick-lock holder: ``DISKI9_JOBS_DATABASE_URL`` (direct or
    session mode) or else the application URL, which must not be in transaction
    pooler mode. Raises :class:`ConnectionModeError` / ``ConfigError``."""
    env = os.environ if env is None else env
    mode = env.get("DISKI9_JOBS_DATABASE_MODE", "direct").strip().lower() or "direct"
    explicit = env.get("DISKI9_JOBS_DATABASE_URL", "").strip()
    if explicit:
        from ..db.settings import _check_postgres

        try:
            _check_postgres(explicit, "DISKI9_JOBS_DATABASE_URL")
        except ValueError as exc:
            raise ConfigError(str(exc)) from None
        return check_lock_url(explicit, mode)
    if settings is None:
        from ..db.settings import BackendDatabaseSettings

        settings = BackendDatabaseSettings()
    if settings.pooler_mode == "transaction":
        raise ConnectionModeError(
            "the application database uses a transaction pooler "
            "(DISKI9_APP_POOLER_MODE=transaction); set DISKI9_JOBS_DATABASE_URL to a direct "
            "or session-mode connection for the scheduler"
        )
    return check_lock_url(settings.url(), mode)


class TickLock:
    """A session-level advisory lock on a dedicated autocommit connection."""

    def __init__(self, url: str, token: str, *, statement_timeout_ms: int = 15_000) -> None:
        self.token = token
        self.pid: int | None = None
        self._conn = None
        self._engine = create_engine(
            url,
            poolclass=pool.NullPool,  # the connection is never shared or reused
            isolation_level="AUTOCOMMIT",  # never inside a transaction
            hide_parameters=True,
            connect_args={
                "application_name": f"{APP_PREFIX}{token}",
                "options": f"-c statement_timeout={int(statement_timeout_ms)} -c timezone=UTC",
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 3,
                "connect_timeout": 10,
            },
        )

    def acquire(self) -> bool:
        """True if this tick now owns the lock. Raises :class:`LockLost` if the lock
        was granted but cannot be verified on the same server session (for example
        through an incorrectly labelled transaction pooler)."""
        self._conn = self._engine.connect()
        got = self._conn.execute(
            text("SELECT pg_try_advisory_lock(hashtextextended(:k, 0))"), {"k": TICK_KEY}
        ).scalar_one()
        if not got:
            return False
        self.pid = self._conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
        self.verify()
        return True

    def verify(self) -> None:
        """Raise :class:`LockLost` unless this tick still owns the lock on the same
        server session."""
        if self._conn is None or self.pid is None:
            raise LockLost("the tick does not hold the scheduler lock")
        try:
            row = self._conn.execute(text(_HELD), {"k": TICK_KEY}).one()
        except Exception as exc:  # noqa: BLE001 - any failure means unverifiable
            raise LockLost(f"the lock connection was lost ({type(exc).__name__})") from None
        if row.pid != self.pid:
            raise LockLost("the lock connection moved to another server session "
                           "(a transaction pooler?)")  # fmt: skip
        if not row.held:
            raise LockLost("the scheduler lock is no longer held by this tick")

    def release(self) -> str | None:
        """Release and close; never raises. Returns a note if cleanup failed."""
        note = None
        try:
            if self._conn is not None and self.pid is not None:
                self._conn.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": TICK_KEY}
                )
        except Exception as exc:  # noqa: BLE001 - the lock ends with the connection
            note = f"lock release failed ({type(exc).__name__}); closing the connection releases it"
        finally:
            try:
                if self._conn is not None:
                    self._conn.close()
            except Exception as exc:  # noqa: BLE001
                note = note or f"lock connection close failed ({type(exc).__name__})"
            self._engine.dispose()
            self._conn = None
        return note


# ------------------------------------------------------------------ abandonment (R4)
@dataclass(frozen=True)
class RunningTick:
    tick_id: int | None
    started_at: datetime
    run_token: str | None
    job_ids: tuple[int, ...]


def running_ticks(conn, now: datetime) -> list[RunningTick]:
    """Scheduler rows still ``running``, grouped by the tick that started them."""
    rows = conn.execute(
        text(
            "SELECT id, job, started_at, args FROM app.job_runs WHERE job = ANY(:jobs) "
            "AND status = 'running' AND started_at >= :since ORDER BY id"
        ),
        {"jobs": list(SCHEDULER_JOBS), "since": now - timedelta(days=30)},
    ).all()
    groups: dict[object, list] = {}
    for r in rows:
        tid = r.id if r.job == "scheduler.tick" else (r.args or {}).get("tick")
        groups.setdefault(tid if tid is not None else ("orphan", r.id), []).append(r)
    ticks = conn.execute(
        text("SELECT id, started_at, args FROM app.job_runs WHERE id = ANY(:ids)"),
        {"ids": [k for k in groups if isinstance(k, int)]},
    ).all()
    tick_of = {t.id: t for t in ticks}
    out = []
    for key, members in groups.items():
        t = tick_of.get(key) if isinstance(key, int) else None
        started = t.started_at if t is not None else min(m.started_at for m in members)
        token = (t.args or {}).get("run_token") if t is not None else None
        out.append(RunningTick(key if isinstance(key, int) else None, started, token,
                               tuple(m.id for m in members)))  # fmt: skip
    return out


def classify_running(conn, now: datetime, abandon_after: timedelta
                     ) -> tuple[list[RunningTick], list[RunningTick]]:  # fmt: skip
    """``(abandoned, indeterminate)`` among other ticks' running rows. Called only
    while holding the scheduler lock, so their tick no longer owns it; but its
    process may still be finishing an in-flight step until ``abandon_after``."""
    abandoned, indeterminate = [], []
    for t in running_ticks(conn, now):
        (abandoned if now - t.started_at >= abandon_after else indeterminate).append(t)
    return abandoned, indeterminate


def mark_abandoned(engine: Engine, ids: list[int], reason: str) -> int:
    if not ids:
        return 0
    with transaction(engine) as conn:
        return len(conn.execute(
            text("UPDATE app.job_runs SET status = 'failed', finished_at = clock_timestamp(), "
                 "error = :e WHERE id = ANY(:ids) AND status = 'running' RETURNING id"),
            {"e": f"abandoned: {reason}"[:500], "ids": ids},
        ).all())  # fmt: skip


def mark_own_interrupted(engine: Engine, tick_id: int, reason: str) -> int:
    """Best effort, by a tick that is itself ending abnormally."""
    with transaction(engine) as conn:
        return len(conn.execute(
            text("UPDATE app.job_runs SET status = 'failed', finished_at = clock_timestamp(), "
                 "error = :e WHERE status = 'running' AND (id = :t OR (job = ANY(:jobs) "
                 "AND (args->>'tick') = CAST(:t AS text))) RETURNING id"),
            {"e": f"abandoned: interrupted ({reason})"[:500], "t": tick_id,
             "jobs": list(SCHEDULER_JOBS)},
        ).all())  # fmt: skip


def active_tick(conn) -> dict | None:
    """The live holder of the scheduler lock (trustworthy evidence a tick runs)."""
    row = conn.execute(text(ACTIVE_TICK_SQL), {"k": TICK_KEY}).first()
    if row is None:
        return None
    name = row.application_name or ""
    token = name[len(APP_PREFIX) :] if name.startswith(APP_PREFIX) else None
    return {"pid": row.pid, "run_token": token, "connected_at": row.backend_start}


# ------------------------------------------------------------------ provider ledger
class BudgetExhausted(Exception):
    def __init__(self, need: int, allowance: int, scope: str) -> None:
        super().__init__(f"needs {need} request(s), {allowance} left ({scope})")
        self.need, self.allowance, self.scope = need, allowance, scope


class ProviderCooldown(Exception):
    """The provider asked for a pause (rate limit) that has not ended yet."""

    def __init__(self, until: datetime) -> None:
        super().__init__(f"provider cooldown until {until:%Y-%m-%dT%H:%M:%SZ}")
        self.until = until


class PacingBacklog(Exception):
    """The next paced send slot is further away than the longest allowed wait."""

    def __init__(self, wait: float) -> None:
        super().__init__(f"next provider send slot is {wait:.0f} s away")
        self.wait = wait


_USAGE = (
    "SELECT coalesce(sum(api_requests) FILTER (WHERE args->>'run_token' = :t), 0) AS tick,"
    " coalesce(sum(api_requests), 0) AS day,"
    " coalesce(sum(api_requests) FILTER (WHERE args->>'class' = 'preparation'), 0) AS prep"
    " FROM app.job_runs WHERE job = :j "
    "AND started_at >= transaction_timestamp() - interval '24 hours'"
)


def usage(conn, token: str) -> tuple[int, int]:
    """(requests recorded by this tick, scheduler requests in the last 24 hours)."""
    row = conn.execute(text(_USAGE), {"t": token, "j": LEDGER_JOB}).one()
    return int(row.tick), int(row.day)


def usage_by_class(conn, token: str) -> tuple[int, int, int]:
    """(this tick, all classes in 24 h, preparation in 24 h). Rows without a class
    count as results (D-2), so they never reduce what preparation is charged."""
    row = conn.execute(text(_USAGE), {"t": token, "j": LEDGER_JOB}).one()
    return int(row.tick), int(row.day), int(row.prep)


@dataclass(frozen=True)
class Caps:
    """The caps one reservation is checked against (Stage C caps plus E.1b classes)."""

    per_tick: int
    per_day: int
    nonessential: int | None = None  # preparation cap in 24 h (None: no class cap)
    results_reserve: int = 0  # never available to preparation


def _left(caps: Caps, klass: str, tick_used: int, day_used: int, prep_used: int
          ) -> tuple[int, str]:  # fmt: skip
    options = [
        (caps.per_tick - tick_used, "per-tick cap"),
        (caps.per_day - day_used, "24-hour cap"),
    ]
    if klass == PREPARATION:
        options.append((caps.per_day - caps.results_reserve - day_used, "results reserve"))
        if caps.nonessential is not None:
            options.append((caps.nonessential - prep_used, "non-essential cap"))
    left, scope = min(options, key=lambda o: o[0])
    return max(left, 0), scope


def allowance(engine: Engine, token: str, per_tick: int, per_day: int, *,
              klass: str = RESULTS, caps: Caps | None = None) -> tuple[int, str]:  # fmt: skip
    caps = caps or Caps(per_tick, per_day)
    with transaction(engine) as conn:
        tick_used, day_used, prep_used = usage_by_class(conn, token)
    return _left(caps, klass, tick_used, day_used, prep_used)


def cooldown_until(conn) -> datetime | None:
    """The end of the latest provider cooldown, if it is still in force."""
    return conn.execute(
        text(
            "SELECT max((args->>'until')::timestamptz) FROM app.job_runs WHERE job = :j "
            "AND started_at >= transaction_timestamp() - interval '2 days' "
            "HAVING max((args->>'until')::timestamptz) > clock_timestamp()"
        ),
        {"j": COOLDOWN_JOB},
    ).scalar_one_or_none()


def reserve(engine: Engine, *, token: str, tick_id: int, scope: str, per_tick: int,
            per_day: int, klass: str = RESULTS, caps: Caps | None = None,
            interval: float = 0.0, max_wait: float | None = None) -> float:  # fmt: skip
    """Record one provider request before it is sent, or raise.

    Serialised by a transaction-level advisory lock, so concurrent callers cannot
    exceed a cap or share a send slot. Checks, in order: a provider cooldown
    (:class:`ProviderCooldown`), the caps for the request's class
    (:class:`BudgetExhausted`), and pacing. **Pacing (E.1b):** the row's
    ``started_at`` is the request's *send slot* — at least ``interval`` seconds after
    the previous slot of any scheduler request, possibly in the future. The caller
    waits the returned number of seconds before sending. Because the slot is
    committed before anyone sleeps, a second caller is always placed after it, also
    across ticks and process restarts; a crash after reserving simply leaves the slot
    used and counted (conservative). A slot further away than ``max_wait`` is refused
    (:class:`PacingBacklog`) without recording anything. A previous slot implausibly
    far in the future (the database clock moved back) is treated as "now", so the
    wait stays bounded. Returns the wait in seconds (0 without pacing)."""
    caps = caps or Caps(per_tick, per_day)
    with transaction(engine) as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                     {"k": BUDGET_KEY})  # fmt: skip
        until = cooldown_until(conn)
        if until is not None:
            raise ProviderCooldown(until)
        tick_used, day_used, prep_used = usage_by_class(conn, token)
        left, why = _left(caps, klass, tick_used, day_used, prep_used)
        if left < 1:
            raise BudgetExhausted(1, 0, why)
        now = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
        send_at, wait = now, 0.0
        if interval > 0:
            last = conn.execute(
                text("SELECT max(started_at) FROM app.job_runs WHERE job = :j"),
                {"j": LEDGER_JOB},
            ).scalar_one_or_none()
            if last is not None:
                horizon = now + timedelta(seconds=(max_wait or 60.0) + interval)
                if last > horizon:  # the clock went backwards: keep the wait bounded
                    last = now
                send_at = max(now, last + timedelta(seconds=interval))
            wait = (send_at - now).total_seconds()
            if max_wait is not None and wait > max_wait:
                raise PacingBacklog(wait)
        conn.execute(
            text(
                "INSERT INTO app.job_runs (job, scope, args, status, started_at, finished_at, "
                "api_requests) VALUES (:j, :s, CAST(:a AS jsonb), 'succeeded', :at, :at, 1)"
            ),
            {
                "j": LEDGER_JOB,
                "s": scope,
                "a": json.dumps({"run_token": token, "tick": int(tick_id), "class": klass}),
                "at": send_at,
            },
        )
    return wait


def record_cooldown(engine: Engine, seconds: float, scope: str, reason: str) -> datetime:
    """Persist a provider-requested pause; every scheduler request waits for it."""
    seconds = max(float(seconds), 1.0)
    with transaction(engine) as conn:
        return conn.execute(
            text(
                "INSERT INTO app.job_runs (job, scope, args, status, started_at, finished_at, "
                "api_requests, error) VALUES (:j, :s, jsonb_build_object('until', "
                "clock_timestamp() + make_interval(secs => :n)), 'succeeded', "
                "clock_timestamp(), clock_timestamp(), 0, :e) "
                "RETURNING (args->>'until')::timestamptz"
            ),
            {"j": COOLDOWN_JOB, "s": scope, "n": seconds, "e": reason[:200]},
        ).scalar_one()


@dataclass(frozen=True)
class QuotaObservation:
    remaining: int
    limit: int | None
    source: str  # header | status
    observed_at: datetime


def record_quota(engine: Engine, remaining: int, limit: int | None, source: str,
                 scope: str = "provider") -> None:  # fmt: skip
    """Record what the provider reported (numbers only)."""
    with transaction(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO app.job_runs (job, scope, args, status, started_at, finished_at, "
                "api_requests) VALUES (:j, :s, jsonb_build_object('remaining', CAST(:r AS int), "
                "'limit', CAST(:l AS int), 'source', CAST(:src AS text), 'observed_at', "
                "clock_timestamp()), 'succeeded', clock_timestamp(), clock_timestamp(), 0)"
            ),
            {
                "j": QUOTA_JOB,
                "s": scope,
                "r": int(remaining),
                "l": None if limit is None else int(limit),
                "src": source,
            },  # fmt: skip
        )


def quota_observations(conn, max_age: timedelta) -> list[QuotaObservation]:
    """Usable observations: younger than ``max_age`` and from the provider's current
    day (UTC; the provider resets its daily quota at about midnight UTC)."""
    rows = conn.execute(
        text(
            "SELECT (args->>'remaining')::int AS remaining, (args->>'limit')::int AS lim, "
            "args->>'source' AS source, started_at FROM app.job_runs WHERE job = :j "
            "AND started_at >= clock_timestamp() - make_interval(secs => :age) "
            "AND (started_at AT TIME ZONE 'UTC')::date = (clock_timestamp() AT TIME ZONE "
            "'UTC')::date ORDER BY id DESC LIMIT 50"
        ),
        {"j": QUOTA_JOB, "age": max_age.total_seconds()},
    ).all()
    return [QuotaObservation(r.remaining, r.lim, r.source, r.started_at) for r in rows]


def limit_today(conn) -> int | None:
    """The lowest daily limit the provider reported today (UTC), if any."""
    return conn.execute(
        text(
            "SELECT min((args->>'limit')::int) FROM app.job_runs WHERE job = :j "
            "AND (started_at AT TIME ZONE 'UTC')::date = (clock_timestamp() AT TIME ZONE "
            "'UTC')::date"
        ),
        {"j": QUOTA_JOB},
    ).scalar_one_or_none()
