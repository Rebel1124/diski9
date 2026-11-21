"""Phase 6C.6 Stage D remediation (R1–R6): scheduler lock ownership, abandonment,
tick budget, cleanup and crash/concurrency-safe provider accounting, on isolated
PostgreSQL databases with mocked providers (no live calls)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from champ_helpers import drop, isolated_engine
from test_backend_scheduler import BASE, FakeProvider, after, status, world

from diski9.api_football.client import ApiFootballClient
from diski9.api_football.errors import ApiFootballHTTPError
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import job_runs
from diski9.backend.jobs import locking, tick
from diski9.backend.jobs.config import ConfigError, load_config
from diski9.backend.jobs.provider import ApiFootballProvider
from diski9.backend.ops import OpsConfig, Severity, collect, evaluate


@pytest.fixture
def db(pg_url, request):
    name = f"diski9_lock_{request.node.name[:32].lower()}_test"
    eng, url = isolated_engine(pg_url, name)
    try:
        yield eng, url
    finally:
        eng.dispose()
        drop(pg_url, name)


def rows(eng, job=None):
    q = sa.select(job_runs).order_by(job_runs.c.id)
    if job:
        q = q.where(job_runs.c.job == job)
    with transaction(eng) as conn:
        return list(conn.execute(q))


def ledger(eng):
    return sum(r.api_requests for r in rows(eng, "scheduler.provider"))


def lock_holders(eng):
    with transaction(eng) as conn:
        return conn.execute(sa.text(locking.ACTIVE_TICK_SQL), {"k": locking.TICK_KEY}).all()


def terminate_holder(eng):
    with transaction(eng) as conn:
        return conn.execute(sa.text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE application_name LIKE 'diski9-tick:%'")).all()  # fmt: skip


def wait_for(cond, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def snap(eng, ops=None):
    ops = ops or OpsConfig()
    return collect(eng, environment="test", finalise_warning=ops.finalise_warning)


def codes(findings, sev=None):
    return {f.code for f in findings if sev is None or f.severity == sev}


class Gated(FakeProvider):
    """Blocks inside the provider call (after recording the request) until released."""

    def __init__(self):
        super().__init__(gate=threading.Event())


def background_tick(eng, cfg, provider):
    out = {}

    def run():
        try:
            out["report"] = tick(eng, cfg, provider_factory=lambda: provider)
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            out["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    return t, out


# ------------------------------------------------------------------ R1: session lock
def test_single_tick_holds_a_session_lock_outside_any_transaction(db):
    eng, _ = db
    w = world(eng, deadline_in=2)
    p = Gated()
    p.add(w)
    after(eng, w["deadline"])
    t, out = background_tick(eng, BASE, p)
    assert wait_for(lambda: p.calls)
    with transaction(eng) as conn:
        holder = conn.execute(sa.text(
            "SELECT state, xact_start FROM pg_stat_activity "
            "WHERE application_name LIKE 'diski9-tick:%'")).one()  # fmt: skip
    assert holder.xact_start is None and holder.state == "idle"  # not "idle in transaction"
    assert len(lock_holders(eng)) == 1
    p.gate.set()
    t.join(60)
    assert out["report"].status == "completed" and out["report"].exit_code == 0
    assert lock_holders(eng) == []  # released explicitly
    tick_row = rows(eng, "scheduler.tick")[-1]
    assert tick_row.status == "succeeded" and tick_row.args["run_token"]


def test_idle_in_transaction_timeout_no_longer_breaks_ownership(db, pg_url):
    """The original defect: 2 s idle-in-transaction limit, a 5 s provider call and a
    second tick starting meanwhile."""
    eng, url = db
    name = eng.url.database
    with transaction(eng) as conn:
        conn.execute(
            sa.text(f"ALTER DATABASE {name} SET idle_in_transaction_session_timeout = 2000")
        )
    eng.dispose()
    w = world(eng, deadline_in=2)
    p = Gated()
    p.add(w)
    after(eng, w["deadline"])
    t, out = background_tick(eng, BASE, p)
    assert wait_for(lambda: p.calls)
    time.sleep(3.0)  # longer than the database's idle-in-transaction limit
    second = tick(eng, BASE, provider_factory=lambda: FakeProvider())
    time.sleep(2.0)
    p.gate.set()
    t.join(60)
    assert "error" not in out
    assert second.status == "busy"  # the first tick still owned the lock
    assert out["report"].status == "completed"
    assert not [r for r in rows(eng) if (r.error or "").startswith("abandoned")]
    assert len(rows(eng, "scheduler.results")) == 1  # no duplicate lifecycle operation
    assert ledger(eng) == 1 and p.requests_made == 1


# ------------------------------------------------------------------ competing ticks
def test_two_and_four_competing_ticks_only_one_owns_the_lock(db):
    eng, _ = db
    w = world(eng, deadline_in=2)
    p = Gated()
    p.add(w)
    after(eng, w["deadline"])
    t, out = background_tick(eng, BASE, p)
    assert wait_for(lambda: p.calls)
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        tick(eng, BASE, provider_factory=lambda: FakeProvider()))) for _ in range(4)]  # fmt: skip
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    p.gate.set()
    t.join(60)
    assert [r.status for r in results] == ["busy"] * 4
    assert out["report"].status == "completed"
    assert len(rows(eng, "scheduler.lock")) == 1 and len(rows(eng, "scheduler.results")) == 1


# ------------------------------------------------------------------ R3/R4: lock loss
def test_lock_holder_terminated_mid_tick_controlled_failure_no_false_abandonment(db):
    eng, _ = db
    w = world(eng, deadline_in=2)
    p = Gated()
    p.add(w)
    after(eng, w["deadline"])
    t, out = background_tick(eng, BASE, p)
    assert wait_for(lambda: p.calls)
    live = snap(eng).active_tick
    assert live and live["tick_id"]  # trustworthy evidence the tick is running
    assert terminate_holder(eng)
    second = tick(eng, BASE, provider_factory=lambda: FakeProvider())
    f = evaluate(snap(eng), OpsConfig(), BASE)
    assert "tick_indeterminate" in codes(f, Severity.WARNING)  # visible, not abandoned
    p.gate.set()
    t.join(60)
    assert "error" not in out  # no traceback
    first = out["report"]
    assert first.status == "lock_lost" and first.exit_code == 1 and "lock lost" in first.detail
    assert second.status == "indeterminate" and second.exit_code == 0
    assert not [r for r in rows(eng) if (r.error or "").startswith("abandoned")]
    imp = rows(eng, "scheduler.results")[-1]
    assert imp.status == "succeeded"  # the in-flight step finished and was recorded
    assert rows(eng, "scheduler.settle") == []  # no follow-on step without ownership
    tick_row = [r for r in rows(eng, "scheduler.tick") if r.id == first.tick_run_id][0]
    assert tick_row.status == "failed" and "lock lost" in tick_row.error
    assert ledger(eng) == 1
    f = evaluate(snap(eng), OpsConfig(), BASE)
    assert "tick_lock_lost" in codes(f, Severity.WARNING)
    third = tick(eng, BASE, provider_factory=lambda: FakeProvider(kickoffs=p.kickoffs))
    assert third.status == "completed"
    assert status(eng, w["round"]) == "settling"  # recovery resumes from the database


def test_genuinely_abandoned_and_uncertain_ticks(db):
    eng, _ = db

    def ghost(age, token):
        """Rows left by a tick whose process was killed (no clean-up ran)."""
        with transaction(eng) as conn:
            now = db_now(conn)
            tid = conn.execute(sa.insert(job_runs).values(
                job="scheduler.tick", scope="global", args={"run_token": token}, status="running",
                started_at=now - age).returning(job_runs.c.id)).scalar_one()  # fmt: skip
            sid = conn.execute(sa.insert(job_runs).values(
                job="scheduler.settle", scope="R", args={"tick": tid, "run_token": token},
                status="running", started_at=now - age).returning(job_runs.c.id)).scalar_one()  # fmt: skip
        return tid, sid

    old = ghost(timedelta(hours=1), "dead")  # older than any live tick can run
    r = tick(eng, replace(BASE, provider_calls=False))
    assert r.status == "completed" and any("abandoned" in n for n in r.notes)
    assert {x.status for x in rows(eng) if x.id in old} == {"failed"}
    young = ghost(timedelta(minutes=2), "maybe-alive")  # its process may still be finishing
    r = tick(eng, replace(BASE, provider_calls=False))
    assert r.status == "indeterminate" and "may still be finishing" in r.detail
    assert r.exit_code == 0
    assert {x.status for x in rows(eng) if x.id in young} == {"running"}  # untouched
    f = evaluate(snap(eng), OpsConfig(), BASE)
    assert "tick_indeterminate" in codes(f, Severity.WARNING)


# ------------------------------------------------------------------ R5: tick budget
def test_tick_budget_stops_new_work_and_the_next_tick_continues(db):
    eng, _ = db
    a = world(eng, deadline_in=2, cutoff_after=600)
    b = world(eng, deadline_in=2, cutoff_after=600)

    class Slow(FakeProvider):
        def fetch(self, ids, reserve):
            time.sleep(1.2)
            return super().fetch(ids, reserve)

    p = Slow()
    p.add(a)
    p.add(b)
    after(eng, max(a["deadline"], b["deadline"]))
    r = tick(eng, replace(BASE, tick_budget=timedelta(seconds=1)), provider_factory=lambda: p)
    assert r.status == "completed" and r.exit_code == 0
    assert any(s.step == "tick" and "budget" in s.detail for s in r.steps)
    assert len({s.round_code for s in r.steps if s.job_run_id}) == 1, [x.line() for x in r.steps]
    r = tick(eng, BASE, provider_factory=lambda: p)
    assert {status(eng, a["round"]), status(eng, b["round"])} == {"settling"}


def test_configuration_bounds_for_budget_and_abandonment():
    env = {"DISKI9_JOBS_ENABLED": "1", "DISKI9_JOBS_STREAMS": "beta"}
    cfg = load_config(env, environment="test")
    assert cfg.tick_budget == timedelta(seconds=240) and cfg.abandon_after == timedelta(minutes=20)
    assert (cfg.provider_timeout_seconds, cfg.provider_max_retries) == (10.0, 1)
    with pytest.raises(ConfigError):
        load_config({**env, "DISKI9_JOBS_TICK_BUDGET_SECONDS": "5"}, environment="test")
    with pytest.raises(ConfigError):
        replace(cfg, abandon_after=timedelta(minutes=2))


# ------------------------------------------------------------------ R6: cleanup
def test_cleanup_failure_is_reported_not_raised(db, monkeypatch):
    eng, _ = db
    original = locking.TickLock.release

    def broken(self):
        with transaction(eng) as conn:  # the lock connection dies just before release
            conn.execute(sa.text("SELECT pg_terminate_backend(:p)"), {"p": self.pid})
        return original(self)

    monkeypatch.setattr(locking.TickLock, "release", broken)
    r = tick(eng, replace(BASE, provider_calls=False))
    assert r.status == "completed" and r.exit_code == 0
    assert any("release failed" in n for n in r.notes)
    assert lock_holders(eng) == []  # the dead connection released it


# ------------------------------------------------------------------ R2: connections
def test_transaction_pooler_connections_are_refused_and_direct_ones_accepted(db):
    eng, url = db
    for bad in ("postgresql+psycopg://u:pw-secret@db.example.invalid:6543/postgres",
                "postgresql+psycopg://u:pw-secret@h:5432/db?pgbouncer=true"):  # fmt: skip
        with pytest.raises(locking.ConnectionModeError) as e:
            locking.check_lock_url(bad)
        assert "pw-secret" not in str(e.value)
    with pytest.raises(locking.ConnectionModeError):
        locking.lock_url({}, SimpleNamespace(pooler_mode="transaction", url=lambda: url))
    with pytest.raises(locking.ConnectionModeError):
        locking.lock_url(
            {"DISKI9_JOBS_DATABASE_URL": url, "DISKI9_JOBS_DATABASE_MODE": "transaction"}
        )
    assert locking.lock_url({"DISKI9_JOBS_DATABASE_URL": url,
                             "DISKI9_JOBS_DATABASE_MODE": "session"}) == url  # fmt: skip
    assert locking.lock_url({}, SimpleNamespace(pooler_mode="session", url=lambda: url)) == url
    r = tick(eng, BASE, lock_url="postgresql+psycopg://u:pw-secret@h.invalid:6543/db")
    assert r.status == "unsafe_connection" and r.exit_code == 2 and "pw-secret" not in r.detail
    assert rows(eng) == []  # nothing was done
    lock = locking.TickLock(url, "probe")
    try:
        assert lock.acquire()
        lock.verify()
        lock.pid += 1  # as if a pooler had moved the session
        with pytest.raises(locking.LockLost):
            lock.verify()
    finally:
        lock.release()


# ------------------------------------------------------------------ provider budget
def test_concurrent_reservations_cannot_exceed_a_cap(db):
    eng, _ = db
    outcomes = []

    def go():
        try:
            locking.reserve(eng, token="t1", tick_id=1, scope="R", per_tick=100, per_day=5)
            outcomes.append("ok")
        except locking.BudgetExhausted:
            outcomes.append("refused")

    threads = [threading.Thread(target=go) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert outcomes.count("ok") == 5 and ledger(eng) == 5


def test_requests_survive_crashes_failures_and_abandonment(db):
    eng, _ = db
    w = world(eng, deadline_in=2, cutoff_after=600)
    after(eng, w["deadline"])

    class Crash(FakeProvider):
        def fetch(self, ids, reserve):
            reserve()
            raise KeyboardInterrupt  # the process dies after sending

    c = Crash()
    c.add(w)
    with pytest.raises(KeyboardInterrupt):
        tick(eng, BASE, provider_factory=lambda: c)
    assert ledger(eng) == 1  # recorded before sending: a crash cannot reset it
    with transaction(eng) as conn:
        assert locking.usage(conn, "x")[1] == 1
    with transaction(eng) as conn:  # wait out the back-off of the interrupted step
        after(eng, db_now(conn) + timedelta(seconds=2.2))
    broken = FakeProvider(fail=ApiFootballHTTPError(503, "down"))
    broken.add(w)
    rb = tick(eng, BASE, provider_factory=lambda: broken)
    assert ledger(eng) == 2, (
        [x.line() for x in rb.steps],
        [(x.job, x.scope, x.status, x.args) for x in rows(eng)],
    )
    r = tick(eng, replace(BASE, max_requests_per_day=2), provider_factory=lambda: broken)
    assert ledger(eng) == 2 and r.exit_code == 0  # the cap holds across ticks and crashes


def test_real_client_retries_are_each_recorded_before_sending():
    calls, reserved = [], []

    def handler(request):
        calls.append(request.url.params.get("ids"))
        if len(calls) == 1:
            return httpx.Response(500, json={})
        body = {"response": [], "errors": [], "results": 0, "paging": {"current": 1, "total": 1}}
        return httpx.Response(200, json=body, headers={"x-ratelimit-requests-remaining": "7000"})

    client = ApiFootballClient(base_url="http://provider.test/", api_key="test-key",
                               transport=httpx.MockTransport(handler), max_retries=1,
                               backoff_seconds=0, sleep=lambda s: None)  # fmt: skip
    ApiFootballProvider(client).fetch([1, 2, 3], lambda: reserved.append(1))
    assert len(calls) == 2 and len(reserved) == 2  # the retry was recorded too

    def refuse():
        raise locking.BudgetExhausted(1, 0, "24-hour cap")

    calls.clear()
    with pytest.raises(locking.BudgetExhausted):
        ApiFootballProvider(client).fetch([4], refuse)
    assert calls == []  # nothing is sent once the cap is reached


def test_monitoring_distinguishes_a_long_running_tick_from_an_outage(db):
    eng, _ = db
    w = world(eng, deadline_in=2)
    p = Gated()
    p.add(w)
    after(eng, w["deadline"])
    t, out = background_tick(eng, BASE, p)
    assert wait_for(lambda: p.calls)
    time.sleep(1.2)
    tight = OpsConfig(heartbeat_warning=timedelta(seconds=1), heartbeat_critical=timedelta(hours=1))
    f = evaluate(snap(eng, tight), tight, BASE)
    assert "tick_active" in codes(f, Severity.INFO)
    assert not codes(f) & {"heartbeat_delayed", "heartbeat_missing", "no_heartbeat"}
    over = OpsConfig(heartbeat_warning=timedelta(milliseconds=500),
                     heartbeat_critical=timedelta(seconds=1))  # fmt: skip
    assert "tick_overrunning" in codes(evaluate(snap(eng, over), over, BASE), Severity.CRITICAL)
    p.gate.set()
    t.join(60)
    s = snap(eng)
    assert s.active_tick is None and s.last_tick.status == "succeeded"
    assert json.dumps(s.last_tick.as_dict(), default=str)  # serialisable for --json
