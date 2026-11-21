"""Scheduler tick-lock probe (Phase 6C.6 Stage D locking review and remediation).

Runs the scheduler on a **throw-away database** (created and dropped here, never a
protected database) to measure how long a tick holds its lock and to reproduce the
original defect scenario: ``idle_in_transaction_session_timeout = 2 s``, a 5 s
provider call and a second tick starting meanwhile; plus loss of the lock-holding
connection mid-tick and a transaction-pooler URL. Before the remediation the first
scenario showed overlapping ticks and false abandonment; after it, the second tick
must skip and nothing may be marked abandoned. No provider is called (a fake
provider with configurable latency is used).

    uv run python tools/ops/scheduler_lock_probe.py \
        --admin-url postgresql+psycopg://postgres@127.0.0.1:5433/postgres

The server must allow creating databases. Results are printed as JSON.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "backend"))

from settle_helpers import DEFAULT_ENTRY, provider_item, settlement_world  # noqa: E402
from svc_helpers import wait_until  # noqa: E402

from diski9.backend.db import BackendDatabaseSettings, make_app_engine, migrate  # noqa: E402
from diski9.backend.jobs import SchedulerConfig, tick  # noqa: E402

NAME = "diski9_lockprobe_test"
CFG = SchedulerConfig(enabled=True, streams=("beta",), provider_calls=True,
                      results_refresh=timedelta(0), settle_refresh=timedelta(0),
                      environment="test")  # fmt: skip


class SlowProvider:
    def __init__(self, latency: float):
        self.latency, self.requests_made, self.kickoffs = latency, 0, {}

    def add(self, w):
        for f in w["fixtures"]:
            self.kickoffs[f] = w["deadline"] + timedelta(seconds=1)

    def fetch(self, ids, reserve):
        need = math.ceil(len(set(ids)) / 20)
        for _ in range(need):
            reserve()
        time.sleep(self.latency)
        self.requests_made += need
        return [provider_item(f, "FT", ko=self.kickoffs[f], h=1, a=0)
                for f in ids if f in self.kickoffs], need  # fmt: skip


def admin(url):
    return create_engine(url, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")


def fresh_db(admin_url: str, timeout_ms: int | None):
    a = admin(admin_url)
    with a.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {NAME} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {NAME}"))
        if timeout_ms:
            c.execute(text(f"ALTER DATABASE {NAME} SET idle_in_transaction_session_timeout "
                           f"= {int(timeout_ms)}"))  # fmt: skip
    a.dispose()
    target = make_url(admin_url).set(database=NAME).render_as_string(hide_password=False)
    migrate.upgrade(target)
    eng = make_app_engine(BackendDatabaseSettings(environment="test"), url=target)
    return eng


def drop_db(admin_url: str) -> None:
    a = admin(admin_url)
    with a.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {NAME} WITH (FORCE)"))
    a.dispose()


def rounds(eng, n, provider):
    made = [settlement_world(eng, (DEFAULT_ENTRY,), lock=False, deadline_in=timedelta(seconds=2),
                             cutoff_after=timedelta(hours=1)) for _ in range(n)]  # fmt: skip
    for w in made:
        provider.add(w)
    wait_until(eng, max(w["deadline"] for w in made) + timedelta(milliseconds=300))
    return made


def scenario_duration(admin_url, n, latency):
    """Wall time of one tick = how long the lock-holding transaction is open."""
    eng = fresh_db(admin_url, None)
    try:
        p = SlowProvider(latency)
        rounds(eng, n, p)
        t0 = time.monotonic()
        r = tick(eng, CFG, provider_factory=lambda: p)
        return {
            "rounds": n,
            "provider_latency_s": latency,
            "tick_s": round(time.monotonic() - t0, 2),
            "steps": len([s for s in r.steps if s.job_run_id]),
            "status": r.status,
        }
    finally:
        eng.dispose()
        drop_db(admin_url)


def scenario_idle_timeout(admin_url, timeout_ms, latency):
    """A provider call longer than the database's idle-in-transaction timeout."""
    eng = fresh_db(admin_url, timeout_ms)
    out = {"idle_in_transaction_timeout_ms": timeout_ms, "provider_latency_s": latency}
    try:
        p = SlowProvider(latency)
        rounds(eng, 1, p)
        res = {}

        def first():
            try:
                r = tick(eng, CFG, provider_factory=lambda: p)
                res["first"] = f"{r.status} (exit {r.exit_code})"
            except Exception as exc:  # noqa: BLE001 - this is what we measure
                res["first"] = f"raised {type(exc).__name__}"

        t = threading.Thread(target=first)
        t.start()
        time.sleep(timeout_ms / 1000 + 1.0)  # the first tick is inside the slow provider call
        second = tick(eng, replace(CFG, provider_calls=False))
        out["second_tick_while_first_running"] = second.status
        if p.latency > timeout_ms / 1000:
            out["note"] = "provider call longer than the idle-in-transaction limit"
        t.join(120)
        out["first_tick"] = res.get("first")
        out.update(_facts(eng, p))
        out["overlap"] = out["second_tick_while_first_running"] == "completed"
        return out
    finally:
        eng.dispose()
        drop_db(admin_url)


def _facts(eng, p) -> dict:
    with eng.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(text(
            "SELECT id, job, status, error FROM app.job_runs WHERE job LIKE 'scheduler.%' "
            "ORDER BY id"))]  # fmt: skip
    return {
        "tick_rows": [r for r in rows if r["job"] == "scheduler.tick"],
        "false_abandonment": any((r["error"] or "").startswith("abandoned") for r in rows),
        "results_steps": sum(r["job"] == "scheduler.results" for r in rows),
        "ledger_requests": sum(r["job"] == "scheduler.provider" for r in rows),
        "requests_sent": p.requests_made,
    }


def scenario_holder_terminated(admin_url, latency):
    """The lock-holding connection is terminated during a slow provider call."""
    eng = fresh_db(admin_url, None)
    out = {"provider_latency_s": latency}
    try:
        p = SlowProvider(latency)
        rounds(eng, 1, p)
        res = {}

        def first():
            try:
                r = tick(eng, CFG, provider_factory=lambda: p)
                res["first"] = f"{r.status} (exit {r.exit_code})"
            except Exception as exc:  # noqa: BLE001
                res["first"] = f"raised {type(exc).__name__}"

        t = threading.Thread(target=first)
        t.start()
        time.sleep(1.0)
        with eng.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                           "WHERE application_name LIKE 'diski9-tick:%'"))  # fmt: skip
            c.commit()
        second = tick(eng, replace(CFG, provider_calls=False))
        out["second_tick_after_termination"] = f"{second.status} (exit {second.exit_code})"
        t.join(120)
        out["first_tick"] = res.get("first")
        out.update(_facts(eng, p))
        return out
    finally:
        eng.dispose()
        drop_db(admin_url)


def scenario_pooler_refused():
    r = tick(None, CFG, lock_url="postgresql+psycopg://u:secret@db.example.invalid:6543/x")
    return {"status": r.status, "exit_code": r.exit_code, "secret_in_message": "secret" in r.detail}


def scenario_session_lock(admin_url, timeout_ms):
    """A session-level advisory lock held on a connection that is idle (not in a
    transaction) is unaffected by idle_in_transaction_session_timeout."""
    eng = fresh_db(admin_url, timeout_ms)
    try:
        holder = eng.connect().execution_options(isolation_level="AUTOCOMMIT")
        got = holder.execute(
            text("SELECT pg_try_advisory_lock(hashtextextended('probe', 0))")
        ).scalar()
        time.sleep(timeout_ms / 1000 + 1.5)
        alive = holder.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                                    "AND pid = pg_backend_pid()")).scalar()  # fmt: skip
        with eng.connect() as other:
            other_got = other.execute(text(
                "SELECT pg_try_advisory_lock(hashtextextended('probe', 0))")).scalar()  # fmt: skip
        holder.execute(text("SELECT pg_advisory_unlock(hashtextextended('probe', 0))"))
        holder.close()
        return {
            "acquired": got,
            "still_held_after_timeout": bool(alive),
            "second_session_acquired": other_got,
        }
    finally:
        eng.dispose()
        drop_db(admin_url)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--admin-url", required=True)
    a = ap.parse_args()
    report = {
        "duration": [
            scenario_duration(a.admin_url, n, lat) for n, lat in ((1, 0.0), (5, 0.0), (5, 1.0))
        ],  # fmt: skip
        "idle_in_transaction_timeout": scenario_idle_timeout(a.admin_url, 2000, 5.0),
        "holder_terminated": scenario_holder_terminated(a.admin_url, 3.0),
        "pooler_refused": scenario_pooler_refused(),
        "session_level_lock": scenario_session_lock(a.admin_url, 2000),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
