"""Phase 6C.6 Stage D: operational status, health checks, notifications and job
history, on isolated PostgreSQL databases with a local test webhook (no external
calls). Severity rules are also unit-tested on synthetic snapshots."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import sqlalchemy as sa
from champ_helpers import drop, isolated_engine
from svc_helpers import wait_until
from test_backend_scheduler import BASE, FakeProvider, after, status, world

from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import job_runs
from diski9.backend.jobs import ConfigError, tick
from diski9.backend.ops import OpsConfig, Severity, collect, evaluate, exit_code, load_ops_config
from diski9.backend.ops.checks import Finding, deep_findings
from diski9.backend.ops.history import recent_jobs
from diski9.backend.ops.notify import notify
from diski9.backend.ops.snapshot import JobRow, RoundFact, Snapshot
from diski9.backend.repositories import results as results_repo
from diski9.challenge.settle import Alert

ROOT = Path(__file__).resolve().parents[2]
FAST = OpsConfig(lock_warning=timedelta(seconds=1), lock_critical=timedelta(hours=1),
                 finalise_warning=timedelta(seconds=1), finalise_critical=timedelta(hours=1))  # fmt: skip


@pytest.fixture
def db(pg_url, request):
    name = f"diski9_ops_{request.node.name[:32].lower()}_test"
    eng, url = isolated_engine(pg_url, name)
    try:
        yield eng, url
    finally:
        eng.dispose()
        drop(pg_url, name)


def snap(eng, ops=None):
    ops = ops or OpsConfig()
    return collect(eng, environment="test", finalise_warning=ops.finalise_warning)


def codes(findings, sev=None):
    return {f.code for f in findings if sev is None or f.severity == sev}


def add_job(eng, job, scope="", *, status="succeeded", ago=timedelta(0), error=None,
            requests=0):  # fmt: skip
    with transaction(eng) as conn:
        now = db_now(conn)
        conn.execute(sa.insert(job_runs).values(
            job=job, scope=scope, args={}, status=status, api_requests=requests, error=error,
            started_at=now - ago,
            finished_at=None if status == "running" else now - ago + timedelta(seconds=1)))  # fmt: skip


def counts(eng):
    with transaction(eng) as conn:
        return conn.execute(sa.text(
            "SELECT (SELECT count(*) FROM app.job_runs), (SELECT count(*) FROM app.audit_log), "
            "(SELECT count(*) FROM app.settlement_runs), (SELECT count(*) FROM app.rounds "
            "WHERE status = 'final')")).one()  # fmt: skip


# ------------------------------------------------------------------ severity model (pure)
NOW = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)


def synthetic(**kw) -> Snapshot:
    base = dict(now=NOW, environment="test", schema_revision="app_0007", expected_head="app_0007",
                query_ms=1.0)  # fmt: skip
    base.update(kw)
    return Snapshot(**base)


def tick_row(ago, status="succeeded", i=1):
    return JobRow(i, "scheduler.tick", "global", status, NOW - ago, NOW - ago, None)


def rf(code, status, *, deadline=None, cutoff=None, earliest=None, blocking=0, mode="real",
       last_settle=None, stream="beta", first_ko=None, last_import=None):  # fmt: skip
    from diski9.backend.ops.snapshot import classify

    f = RoundFact(None, code, stream, status, mode, deadline, cutoff, earliest, first_ko, blocking,
                  last_settle, last_import, None)  # fmt: skip
    f.category = classify(f, NOW, OpsConfig().finalise_warning)
    return f


def test_scheduler_states_and_heartbeat_thresholds():
    on = replace(BASE, provider_calls=False)
    assert codes(evaluate(synthetic(), OpsConfig(), replace(on, enabled=False)),
                 Severity.INFO) >= {"automation_disabled"}  # fmt: skip
    paused = evaluate(synthetic(), OpsConfig(), replace(on, paused=True, pause_reason="x"))
    assert "automation_paused" in codes(paused, Severity.INFO) and exit_code(paused) == 0
    assert "no_heartbeat" in codes(evaluate(synthetic(), OpsConfig(), on), Severity.CRITICAL)
    healthy = synthetic(ticks=[tick_row(timedelta(minutes=2))],
                        last_ok_tick=tick_row(timedelta(minutes=2)))  # fmt: skip
    assert exit_code(evaluate(healthy, OpsConfig(), on)) == 0
    late = synthetic(
        ticks=[tick_row(timedelta(minutes=20))], last_ok_tick=tick_row(timedelta(minutes=20))
    )
    assert "heartbeat_delayed" in codes(evaluate(late, OpsConfig(), on), Severity.WARNING)
    dead = synthetic(
        ticks=[tick_row(timedelta(hours=2))], last_ok_tick=tick_row(timedelta(hours=2))
    )
    assert "heartbeat_missing" in codes(evaluate(dead, OpsConfig(), on), Severity.CRITICAL)
    # disabled or paused automation is never an outage, however old the last tick
    for cfg in (replace(on, enabled=False), replace(on, paused=True, pause_reason="x")):
        assert exit_code(evaluate(dead, OpsConfig(), cfg)) == 0
    failing = synthetic(ticks=[tick_row(timedelta(minutes=1), "failed", i) for i in range(3)])
    assert "ticks_failing" in codes(evaluate(failing, OpsConfig(), on), Severity.CRITICAL)


def test_lifecycle_thresholds_use_competition_times():
    j = replace(BASE, provider_calls=False)
    rounds = [
        rf("draft", "draft"),
        rf("open-ok", "open", deadline=NOW + timedelta(hours=1)),
        rf("lock-w", "open", deadline=NOW - timedelta(minutes=20)),
        rf("lock-c", "open", deadline=NOW - timedelta(hours=2)),
        rf("window", "settling", cutoff=NOW - timedelta(hours=1), earliest=NOW + timedelta(hours=5),
           last_settle=NOW),
        rf("elig", "settling", cutoff=NOW - timedelta(days=1), earliest=NOW - timedelta(hours=1),
           last_settle=NOW),
        rf("over", "settling", cutoff=NOW - timedelta(days=3), earliest=NOW - timedelta(hours=30),
           last_settle=NOW),
        rf("blk", "settling", cutoff=NOW - timedelta(days=3), earliest=NOW - timedelta(hours=30),
           blocking=2, last_settle=NOW),
        rf("unsettled", "settling", cutoff=NOW - timedelta(hours=7), earliest=None),
    ]  # fmt: skip
    found = {(f.code, f.subject): f.severity
             for f in evaluate(synthetic(rounds=rounds), OpsConfig(), j)}  # fmt: skip
    assert found[("awaiting_publication", "draft")] == Severity.INFO
    assert ("lock_overdue", "open-ok") not in found
    assert found[("lock_overdue", "lock-w")] == Severity.WARNING
    assert found[("lock_overdue", "lock-c")] == Severity.CRITICAL
    assert not [k for k in found if k[1] == "window"]  # the correction window is normal
    assert found[("finalisation_pending", "elig")] == Severity.INFO
    assert found[("finalisation_pending", "over")] == Severity.CRITICAL
    assert found[("blocking_alerts", "blk")] == Severity.CRITICAL  # blocked beyond eligibility
    assert found[("settlement_overdue", "unsettled")] == Severity.WARNING
    assert [r.category for r in rounds] == [
        "awaiting_publication", "entries_open", "awaiting_lock", "awaiting_lock",
        "correction_window", "eligible_for_finalisation", "overdue_for_finalisation", "blocked",
        "awaiting_settlement"]  # fmt: skip


def test_provider_budget_integrity_and_database_findings():
    on = replace(BASE, provider_calls=True, max_requests_per_day=100)
    sev = lambda s, code: {f.code: f.severity for f in evaluate(s, OpsConfig(), on)}.get(code)  # noqa: E731
    assert sev(synthetic(provider_day_requests=50), "budget_high") is None
    assert sev(synthetic(provider_day_requests=85), "budget_high") == Severity.WARNING
    assert sev(synthetic(provider_day_requests=100), "budget_exhausted") == Severity.WARNING
    assert sev(synthetic(provider_day_requests=120), "budget_exceeded") == Severity.CRITICAL
    off = evaluate(synthetic(), OpsConfig(), replace(on, provider_calls=False))
    assert "provider_calls_off" in codes(off, Severity.INFO)
    s = synthetic(official_anomalies=["official round X is open"], final_without_results=["R1"])
    f = evaluate(s, OpsConfig(), on)
    assert "official_anomaly" in codes(f, Severity.CRITICAL)
    assert "final_without_results" in codes(f, Severity.WARNING)
    assert "migration_head" in codes(evaluate(synthetic(schema_revision="app_0006"), OpsConfig(),
                                              on), Severity.CRITICAL)  # fmt: skip
    assert "tables_missing" in codes(evaluate(synthetic(tables_missing=["app.job_runs"]),
                                              OpsConfig(), on))  # fmt: skip
    streak = synthetic(
        streaks={("scheduler.results", "R"): (6, "retryable_failure: provider error")}
    )
    f = evaluate(streak, OpsConfig(), on)
    assert "step_failing" in codes(f, Severity.CRITICAL) and "provider_failing" in codes(f)


def test_monitoring_configuration_fails_closed_and_hides_the_webhook():
    assert not load_ops_config({}).notifications_active  # off by default
    url = "https://hooks.example.invalid/T000/secret-token"
    cfg = load_ops_config({"DISKI9_OPS_NOTIFY": "on", "DISKI9_OPS_WEBHOOK_URL": url})
    assert cfg.notifications_active and "secret-token" not in repr(cfg)
    assert "secret-token" not in cfg.describe_notifications()
    for env in ({"DISKI9_OPS_WEBHOOK_URL": "http://hooks.example.invalid/x"},  # plain http
                {"DISKI9_OPS_NOTIFY": "sometimes"},
                {"DISKI9_OPS_LOCK_WARNING_MINUTES": "90", "DISKI9_OPS_LOCK_CRITICAL_MINUTES": "30"},
                {"DISKI9_OPS_NOTIFY_MIN_SEVERITY": "info"}):  # fmt: skip
        with pytest.raises(ConfigError):
            load_ops_config(env)
    assert load_ops_config({"DISKI9_OPS_WEBHOOK_URL": "http://127.0.0.1:9/x"}).webhook_url


# ------------------------------------------------------------------ against PostgreSQL
def test_status_reflects_real_lifecycle_and_is_read_only(db):
    eng, _ = db
    cfg = replace(BASE, provider_calls=False)
    assert "no_heartbeat" in codes(evaluate(snap(eng), OpsConfig(), cfg), Severity.CRITICAL)
    later = world(eng, deadline_in=600)  # entries open
    due = world(eng, deadline_in=2)
    after(eng, due["deadline"])
    s = snap(eng, FAST)
    cats = {r.code: r.category for r in s.rounds}
    assert sorted(cats.values()) == ["awaiting_lock", "entries_open"]
    time.sleep(1.1)
    assert "lock_overdue" in codes(evaluate(snap(eng, FAST), FAST, cfg), Severity.WARNING)
    before = counts(eng)
    for _ in range(3):  # repeated monitoring is read-only
        evaluate(snap(eng, FAST), FAST, cfg)
    assert counts(eng) == before
    tick(eng, cfg)
    s = snap(eng, FAST)
    assert next(r.category for r in s.rounds if r.id == due["round"]) in (
        "awaiting_results",
        "awaiting_settlement",
    )
    assert s.last_tick is not None and s.last_tick.status == "succeeded"
    assert "no_heartbeat" not in codes(evaluate(s, FAST, cfg))
    assert status(eng, later["round"]) == "open"


def test_failed_abandoned_stuck_and_blocked_rounds(db):
    eng, _ = db
    w = world(eng, cutoff_after=4)
    fake = FakeProvider()
    fake.add(w)
    after(eng, w["deadline"])
    tick(eng, BASE, provider_factory=lambda: fake)
    with transaction(eng) as conn:
        code = conn.execute(sa.text("SELECT code FROM app.rounds WHERE id = :r"),
                            {"r": w["round"]}).scalar_one()  # fmt: skip
    for _ in range(3):
        add_job(
            eng,
            "scheduler.settle",
            code,
            status="failed",
            error="retryable_failure: database error",
        )
    add_job(eng, "scheduler.lock", "other", status="failed",
            error="abandoned: the tick ended before this step finished")  # fmt: skip
    add_job(eng, "scheduler.results", code, status="running", ago=timedelta(hours=1))
    with transaction(eng) as conn:
        results_repo.raise_alerts(conn, w["round"], None,
                                  [Alert("score_conflict", w["fixtures"][0], "t", {})])  # fmt: skip
    f = evaluate(snap(eng), OpsConfig(), BASE)
    assert {"step_failing", "step_abandoned", "step_stuck", "blocking_alerts"} <= codes(
        f, Severity.WARNING
    )
    assert exit_code(f) >= 1
    s = snap(eng)
    assert [r for r in s.rounds if r.code == code][0].blocking_alerts == 1


def test_deep_integrity_is_on_demand_only(db, monkeypatch):
    eng, _ = db
    found, ms = deep_findings(eng)
    assert found == [] and ms >= 0  # a healthy (empty) database

    def boom(*a, **k):
        raise AssertionError("the expensive inspection ran during a light check")

    monkeypatch.setattr("diski9.backend.services.championships.inspect_stream", boom)
    evaluate(snap(eng), OpsConfig(), BASE)  # light checks never inspect

    class Ins:
        material = ["standings hash mismatch"]
        repairable = ["missing weekly results"]

    monkeypatch.setattr("diski9.backend.services.championships.inspect_stream",
                        lambda conn, stream: Ins())  # fmt: skip
    found, _ = deep_findings(eng)
    assert {f.severity for f in found} == {Severity.CRITICAL, Severity.WARNING}
    assert len({f.fingerprint for f in found}) == len(found)


def test_job_history_view(db):
    eng, _ = db
    w = world(eng, deadline_in=2)
    after(eng, w["deadline"])
    tick(eng, replace(BASE, provider_calls=False))
    with transaction(eng) as conn:
        code = conn.execute(sa.text("SELECT code FROM app.rounds WHERE id = :r"),
                            {"r": w["round"]}).scalar_one()  # fmt: skip
    data = recent_jobs(eng, round_code=code)
    jobs = {j["job"] for j in data["jobs"]}
    assert {"scheduler.lock", "scheduler.settle", "lock"} <= jobs
    settle = [j for j in data["jobs"] if j["job"] == "scheduler.settle"][0]
    assert settle["settlement_run_id"] and settle["outcome"] == "succeeded"
    assert {a["action"] for a in data["audit"]} >= {"round.lock"}
    assert all(a["actor_role"] == "system" for a in data["audit"] if a["action"] == "round.lock")
    assert len(recent_jobs(eng, limit=10_000)["jobs"]) <= 200  # bounded


# ------------------------------------------------------------------ notifications
class Hook:
    """A local webhook endpoint (127.0.0.1 only) recording what it receives."""

    def __init__(self, code=200):
        self.code, self.received = code, []
        hook = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers["Content-Length"]))
                hook.received.append(json.loads(body))
                self.send_response(hook.code)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hook/secret-token"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def finding(sev=Severity.WARNING, subject="2026-W48"):
    return Finding(sev, "lifecycle", "lock_overdue", subject, f"{subject} is overdue")


def ledger(eng):
    with transaction(eng) as conn:
        return list(conn.execute(sa.select(job_runs).where(job_runs.c.job == "ops.notify")
                                 .order_by(job_runs.c.id)))  # fmt: skip


def now_of(eng):
    with transaction(eng) as conn:
        return db_now(conn)


def test_notifications_disabled_by_default(db):
    eng, _ = db
    hook = Hook()
    try:
        f = [finding(Severity.CRITICAL)]
        assert notify(eng, f, OpsConfig(), environment="test", now=now_of(eng)) == []
        assert notify(eng, f, OpsConfig(notify=True), environment="test", now=now_of(eng)) == []
        assert notify(eng, f, OpsConfig(webhook_url=hook.url), environment="test",
                      now=now_of(eng)) == []  # fmt: skip
        assert hook.received == [] and ledger(eng) == []
    finally:
        hook.close()


def test_deduplication_renotification_escalation_and_resolution(db):
    eng, _ = db
    hook = Hook()
    try:
        cfg = OpsConfig(notify=True, webhook_url=hook.url, renotify_warning=timedelta(seconds=2),
                        renotify_critical=timedelta(seconds=2))  # fmt: skip
        send = lambda fs: notify(eng, fs, cfg, environment="test", now=now_of(eng))  # noqa: E731
        info = Finding(Severity.INFO, "lifecycle", "awaiting_publication", "d", "draft")
        first = send([finding(), info])
        assert [(d.state, d.delivered) for d in first] == [("new", True)]  # INFO never sent
        assert send([finding()]) == []  # duplicate suppressed
        wait_until(eng, now_of(eng) + timedelta(seconds=2.2))
        assert [d.state for d in send([finding()])] == ["ongoing"]
        assert [d.state for d in send([finding(Severity.CRITICAL)])] == ["ongoing"]  # escalation
        assert [d.state for d in send([])] == ["resolved"]
        assert send([]) == []  # resolved once
        assert [d.state for d in send([finding()])] == ["new"]  # it came back
        states = [p["state"] for p in hook.received]
        assert states == ["new", "ongoing", "ongoing", "resolved", "new"]
        assert all("secret-token" not in json.dumps(p) for p in hook.received)
        rows = ledger(eng)
        assert all("secret-token" not in json.dumps([r.args, r.error, r.scope]) for r in rows)
        assert hook.received[0]["fingerprint"] == "lock_overdue:2026-W48"
    finally:
        hook.close()


def test_delivery_failures_are_recorded_retried_later_and_never_raise(db):
    eng, _ = db
    hook = Hook(code=500)
    try:
        cfg = OpsConfig(notify=True, webhook_url=hook.url, notify_retry=timedelta(seconds=2))
        (d,) = notify(eng, [finding()], cfg, environment="test", now=now_of(eng))
        assert not d.delivered and "HTTP 500" in d.detail
        assert ledger(eng)[-1].status == "failed"
        assert notify(eng, [finding()], cfg, environment="test", now=now_of(eng)) == []  # waits
        hook.code = 200
        wait_until(eng, now_of(eng) + timedelta(seconds=2.2))
        (d,) = notify(eng, [finding()], cfg, environment="test", now=now_of(eng))
        assert d.delivered and d.state == "new"
    finally:
        hook.close()
    closed = OpsConfig(notify=True, webhook_url="http://127.0.0.1:9/hook")  # nothing listens
    (d,) = notify(
        eng, [finding(), finding(subject="other")], closed, environment="test", now=now_of(eng)
    )  # the first is already notified; only the new one is sent
    assert not d.delivered and "delivery failed" in d.detail


# ------------------------------------------------------------------ recovery and boundaries
def test_monitoring_never_acts_on_the_lifecycle():
    """Static: the ops package performs no lifecycle step and no human-only action."""
    names = set()
    for path in (ROOT / "src/diski9/backend/ops").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            if isinstance(node, ast.ImportFrom):
                names |= {a.name for a in node.names}
    forbidden = {"lock_round", "import_results", "settle_round", "finalise_round", "publish_round",
                 "create_round", "correct_result", "resolve_alert", "reopen_round",
                 "invalidate_round", "authenticate_operator", "cli_principal", "SYSTEM", "tick"}  # fmt: skip
    assert not names & forbidden


def test_after_an_interrupted_tick_ops_shows_it_and_recovery_never_finalises_early(db, monkeypatch):
    eng, _ = db
    w = world(eng, cwh=None, cutoff_after=4)  # real 24-hour correction window
    fake = FakeProvider()
    fake.add(w)
    after(eng, w["deadline"])
    from diski9.backend.jobs import reconciler as rec

    monkeypatch.setattr(rec.settlement, "settle_round",
                        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))  # fmt: skip
    with pytest.raises(KeyboardInterrupt):
        tick(eng, BASE, provider_factory=lambda: fake)
    monkeypatch.undo()
    assert not snap(eng).running  # the interrupted tick recorded its own steps
    tick(eng, replace(BASE, retry_base=timedelta(0)), provider_factory=lambda: fake)
    f = evaluate(snap(eng), OpsConfig(), BASE)
    assert "step_abandoned" in codes(f, Severity.WARNING)
    after(eng, w["cutoff"])
    for _ in range(2):
        tick(eng, BASE, provider_factory=lambda: fake)
    assert status(eng, w["round"]) == "settling"  # recovery never finalises before S-02


# ------------------------------------------------------------------ command line
def _cli(args, env):
    full = {k: v for k, v in os.environ.items()
            if not k.startswith(("DISKI9_JOBS_", "DISKI9_OPS_"))}  # fmt: skip
    full.update(env)
    p = subprocess.run([sys.executable, "-m", "diski9.cli", *args], capture_output=True,
                       text=True, env=full, timeout=120)  # fmt: skip
    return p.returncode, p.stdout + p.stderr


def test_cli_status_check_jobs_json_and_no_secrets(db):
    eng, url = db
    w = world(eng, deadline_in=2)
    after(eng, w["deadline"])
    env = {"DISKI9_APP_DATABASE_URL": url, "DISKI9_JOBS_ENABLED": "1",
           "DISKI9_JOBS_STREAMS": "beta", "DISKI9_OPS_NOTIFY": "on",
           "DISKI9_OPS_WEBHOOK_URL": "https://hooks.example.invalid/T0/secret-token"}  # fmt: skip
    rc, out = _cli(["ops", "status"], env)
    assert rc == 0 and "awaiting locking" in out and "notifications on (webhook configured" in out
    rc, out = _cli(["ops", "status", "--json"], env)
    doc = json.loads(out[out.index("{") :])
    assert rc == 0 and doc["scheduler"]["enabled"] and doc["rounds"]["awaiting_lock"]
    rc, out = _cli(["ops", "check"], env)
    assert rc == 2 and "no_heartbeat" in out  # enabled, never ticked
    rc, _ = _cli(["jobs", "tick"], env)
    assert rc == 0
    rc, out = _cli(["ops", "check", "--json"], env)
    doc = json.loads(out[out.index("{") :])
    assert "no_heartbeat" not in {f["code"] for f in doc["findings"]}
    rc, out = _cli(["ops", "jobs", "--limit", "5"], env)
    assert rc == 0 and "scheduler.lock" in out
    for o in (out,):
        assert "secret-token" not in o and "postgresql" not in o
    rc, out = _cli(["ops", "check", "--deep"], env)
    assert "deep_ms" in out
    bad = dict(
        env, DISKI9_APP_DATABASE_URL="postgresql+psycopg://nobody:pw-secret@127.0.0.1:9/none_test"
    )
    rc, out = _cli(["ops", "check"], bad)
    assert rc == 2 and "database_unavailable" in out and "Traceback" not in out
    assert "pw-secret" not in out
    rc, out = _cli(["ops", "status"], bad)
    assert rc == 1 and "Traceback" not in out and "pw-secret" not in out
    rc, out = _cli(["ops", "check"], dict(env, DISKI9_JOBS_STREAMS="official"))
    assert rc == 2 and "config_invalid" in out


# ------------------------------------------------------------------ performance
def test_monitoring_stays_bounded_with_a_large_job_history(db, monkeypatch):
    eng, _ = db
    with transaction(eng) as conn:  # about a year of five-minute ticks plus their steps
        conn.execute(
            sa.text("""
            INSERT INTO app.job_runs (job, scope, args, status, started_at, finished_at,
                                      api_requests)
            SELECT (ARRAY['scheduler.tick','scheduler.settle','scheduler.results',
                          'scheduler.lock','results-import'])[1 + g % 5],
                   CASE WHEN g % 5 = 0 THEN 'global' ELSE 'R' || (g % 300) END, '{}'::jsonb,
                   'succeeded', now() - g * interval '1 minute',
                   now() - g * interval '1 minute' + interval '1 second', g % 2
              FROM generate_series(1, 150000) g""")
        )
        conn.execute(sa.text("ANALYZE app.job_runs"))
    monkeypatch.setattr("diski9.backend.services.championships.inspect_stream",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("deep ran")))  # fmt: skip
    times = []
    for _ in range(3):
        t0 = time.monotonic()
        evaluate(snap(eng), OpsConfig(), BASE)
        times.append(time.monotonic() - t0)
    t0 = time.monotonic()
    recent_jobs(eng, limit=200)
    times.append(time.monotonic() - t0)
    print(f"monitoring timings with 150,000 job runs: {[round(t * 1000) for t in times]} ms")
    assert max(times) < 3.0, times
