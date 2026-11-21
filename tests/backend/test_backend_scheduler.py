"""Phase 6C.6 Stage C: the lifecycle reconciler (``diski9 jobs tick``) on real
PostgreSQL, with mocked provider responses (no live provider calls).

Each test gets its own freshly migrated database, because a tick processes every
round of the allowlisted streams and must not touch other tests' rounds. Rounds use
short real deadlines and settlement cutoffs; the frozen correction window is 0 hours
where a test needs to reach S-02 finalisation on the real database clock (the
scheduler has no time override, and real rounds keep the schedule's 24 hours).
"""

from __future__ import annotations

import ast
import math
import os
import subprocess
import sys
import threading
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from champ_helpers import drop, isolated_engine
from pg_helpers import make_user
from settle_helpers import (
    DEFAULT_ENTRY,
    confirm_entry,
    make_settlement_round,
    provider_item,
    settlement_world,
)
from svc_helpers import wait_until

from diski9.api_football.errors import ApiFootballAuthError, ApiFootballHTTPError
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import audit_log, job_runs, score_sets, settlement_runs
from diski9.backend.db.schema import rounds as rounds_t
from diski9.backend.jobs import (
    ConfigError,
    Outcome,
    SchedulerConfig,
    load_config,
    plan_tick,
    tick,
)
from diski9.backend.jobs import reconciler as rec
from diski9.backend.repositories import results as results_repo
from diski9.challenge.settle import Alert

ROOT = Path(__file__).resolve().parents[2]
BASE = SchedulerConfig(
    enabled=True,
    streams=("beta", "development"),
    provider_calls=True,
    results_refresh=timedelta(0),
    settle_refresh=timedelta(0),
    retry_base=timedelta(seconds=1),
    retry_max=timedelta(seconds=2),
    environment="test",
)


@pytest.fixture
def db(pg_url, request):
    name = f"diski9_sched_{request.node.name[:30].lower()}_test".replace("[", "_").replace("]", "")
    eng, url = isolated_engine(pg_url, name)
    try:
        yield eng, url
    finally:
        eng.dispose()
        drop(pg_url, name)


class FakeProvider:
    """Answers ``/fixtures`` by ID with full-time scores (1-0) for known fixtures."""

    def __init__(self, kickoffs=None, fail=None, gate=None):
        self.kickoffs = dict(kickoffs or {})
        self.fail, self.gate = fail, gate
        self.requests_made, self.calls = 0, []

    def add(self, w):
        for f in w["fixtures"]:
            self.kickoffs[f] = w["deadline"] + timedelta(seconds=1)

    def fetch(self, ids, reserve):
        need = math.ceil(len(set(ids)) / 20)
        for _ in range(need):
            reserve()  # recorded (and ownership checked) before every request
        self.calls.append(sorted(ids))
        if self.gate is not None:
            self.gate.wait(30)
        self.requests_made += need
        if self.fail is not None:
            raise self.fail
        items = [provider_item(f, "FT", ko=self.kickoffs[f], h=1, a=0)
                 for f in ids if f in self.kickoffs]  # fmt: skip
        return items, need


def world(eng, *, entries=1, cwh=0, development=False, deadline_in=3, cutoff_after=3):
    return settlement_world(
        eng, (DEFAULT_ENTRY,) * entries, development=development, lock=False,
        deadline_in=timedelta(seconds=deadline_in), cutoff_after=timedelta(seconds=cutoff_after),
        correction_window_hours=cwh,
    )  # fmt: skip


def status(eng, rid):
    with transaction(eng) as conn:
        return conn.execute(sa.select(rounds_t.c.status).where(rounds_t.c.id == rid)).scalar_one()


def runs(eng, job=None):
    q = sa.select(job_runs).where(job_runs.c.job.like("scheduler.%")).order_by(job_runs.c.id)
    if job:
        q = q.where(job_runs.c.job == job)
    with transaction(eng) as conn:
        return list(conn.execute(q))


def counts(eng):
    with transaction(eng) as conn:
        return tuple(
            conn.execute(sa.select(sa.func.count()).select_from(t)).scalar_one()
            for t in (job_runs, settlement_runs, audit_log, score_sets)
        )


def steps(report, step=None):
    return [s for s in report.steps if step is None or s.step == step]


def after(eng, moment):
    wait_until(eng, moment + timedelta(milliseconds=300))


# ------------------------------------------------------------------ configuration
def test_configuration_fails_closed():
    cfg = load_config({}, environment="test")
    assert not cfg.enabled and cfg.streams == () and not cfg.provider_calls  # off by default
    good = {"DISKI9_JOBS_ENABLED": "1", "DISKI9_JOBS_STREAMS": "beta, development"}
    assert load_config(good, environment="test").streams == ("beta", "development")
    bad = [
        {"DISKI9_JOBS_ENABLED": "1"},  # no allowlist
        {**good, "DISKI9_JOBS_STREAMS": "beta,official"},  # never automatable
        {**good, "DISKI9_JOBS_STREAMS": "OFFICIAL"},
        {**good, "DISKI9_JOBS_STREAMS": "staging"},  # unknown
        {**good, "DISKI9_JOBS_ENABLED": "maybe"},
        {**good, "DISKI9_JOBS_MAX_REQUESTS_PER_TICK": "0"},
        {**good, "DISKI9_JOBS_MAX_REQUESTS_PER_TICK": "ten"},
        {**good, "DISKI9_JOBS_MAX_REQUESTS_PER_TICK": "50", "DISKI9_JOBS_MAX_REQUESTS_PER_DAY": "20"},
        {**good, "DISKI9_JOBS_RESULTS_REFRESH_MINUTES": "1"},
        {**good, "DISKI9_JOBS_RETRY_BASE_MINUTES": "60", "DISKI9_JOBS_RETRY_MAX_MINUTES": "30"},
    ]  # fmt: skip
    for env in bad:
        with pytest.raises(ConfigError):
            load_config(env, environment="test")
    with pytest.raises(ConfigError):  # development rounds are never automated in production
        load_config(good, environment="production")
    for streams in (("official",), ("beta", "official"), ("staging",)):
        with pytest.raises(ConfigError):  # a configuration built in code is checked too
            SchedulerConfig(enabled=True, streams=streams)
    with pytest.raises(ConfigError):
        SchedulerConfig(enabled=True, streams=())


def test_pause_switch_and_pause_file(tmp_path):
    env = {"DISKI9_JOBS_ENABLED": "1", "DISKI9_JOBS_STREAMS": "beta"}
    flag = tmp_path / "pause"
    env["DISKI9_JOBS_PAUSE_FILE"] = str(flag)
    assert not load_config(env, environment="test").paused
    flag.write_text("")
    assert load_config(env, environment="test").paused
    flag.unlink()
    assert load_config({**env, "DISKI9_JOBS_PAUSED": "on"}, environment="test").paused


def test_disabled_and_paused_ticks_change_nothing(db):
    eng, _ = db
    w = world(eng, deadline_in=2)
    after(eng, w["deadline"])
    before = counts(eng)
    r = tick(eng, replace(BASE, enabled=False))
    assert r.status == "disabled" and r.exit_code == 0 and counts(eng) == before
    r = tick(eng, replace(BASE, paused=True, pause_reason="test"))
    assert r.status == "paused" and r.exit_code == 0
    assert status(eng, w["round"]) == "open"  # past its deadline, yet untouched
    (row,) = runs(eng)
    assert row.job == "scheduler.tick" and row.status == "skipped" and "paused" in row.error


# ------------------------------------------------------------------ locking
def test_lock_only_after_the_real_deadline_then_idempotent(db):
    eng, _ = db
    w = world(eng, deadline_in=4)
    r = tick(eng, replace(BASE, provider_calls=False))
    assert status(eng, w["round"]) == "open" and not runs(eng, "scheduler.lock")
    assert any("entries open until" in s.detail for s in steps(r, "lock"))
    after(eng, w["deadline"])
    r = tick(eng, replace(BASE, provider_calls=False))
    (lock,) = steps(r, "lock")
    assert lock.outcome == Outcome.SUCCEEDED and status(eng, w["round"]) in ("locked", "settling")
    with transaction(eng) as conn:
        a = conn.execute(sa.select(audit_log).where(audit_log.c.action == "round.lock")).one()
    assert a.actor_role == "system" and a.actor_user_id is None  # SYSTEM, no person
    tick(eng, replace(BASE, provider_calls=False))
    tick(eng, replace(BASE, provider_calls=False))
    assert len(runs(eng, "scheduler.lock")) == 1  # a locked round is never re-locked
    with transaction(eng) as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(audit_log)
                         .where(audit_log.c.action == "round.lock")).scalar_one()  # fmt: skip
    assert n == 1


# ------------------------------------------------------------------ whole lifecycle
def test_full_lifecycle_to_final_with_championship_processing(db):
    eng, _ = db
    w = world(eng, entries=5, deadline_in=3, cutoff_after=8)
    fake = FakeProvider()
    fake.add(w)
    after(eng, w["deadline"])
    r1 = tick(eng, BASE, provider_factory=lambda: fake)
    assert [s.step for s in r1.steps if s.job_run_id][:3] == ["lock", "results", "settle"]
    assert status(eng, w["round"]) == "settling" and r1.exit_code == 0
    assert any(s.step == "finalise" and "earliest" in s.detail for s in r1.steps)  # not early
    after(eng, w["cutoff"])
    for _ in range(3):
        r = tick(eng, BASE, provider_factory=lambda: fake)
        if status(eng, w["round"]) == "final":
            break
    assert status(eng, w["round"]) == "final", [s.line() for s in r.steps] + [
        f"{x.job} {x.status} {x.error}" for x in runs(eng)
    ]
    jobs = [(x.job, x.status) for x in runs(eng) if x.job != "scheduler.tick"]
    full = max(i for i, j in enumerate(jobs) if j == ("scheduler.results_full", "succeeded"))
    fin = jobs.index(("scheduler.finalise", "succeeded"))
    assert full < fin  # the full results re-check precedes finalisation
    with transaction(eng) as conn:
        a = conn.execute(sa.select(audit_log).where(audit_log.c.action == "round.finalise")).one()
        sets = conn.execute(sa.select(sa.func.count()).select_from(score_sets)
                            .where(score_sets.c.round_id == w["round"])).scalar_one()  # fmt: skip
        linked = conn.execute(
            sa.select(sa.func.count()).select_from(settlement_runs.join(
                job_runs, job_runs.c.id == settlement_runs.c.job_run_id))
            .where(settlement_runs.c.trigger == "scheduled", job_runs.c.job == "scheduler.settle")
        ).scalar_one()  # fmt: skip
    assert a.actor_role == "system" and a.actor_user_id is None
    assert sets >= 1  # weekly results published (and championships processed) inside finalise
    assert linked >= 1  # scheduled settlement runs link to the scheduler's job records
    before = counts(eng)[1:]
    for _ in range(2):
        r = tick(eng, BASE, provider_factory=lambda: fake)
        assert not [s for s in r.steps if s.round_code == w["round"]]
    assert counts(eng)[1:] == before  # repeated ticks: no duplicate effects
    assert all(len(c) <= 20 for c in fake.calls)


def test_never_finalises_before_s02_earliest_time(db):
    eng, _ = db
    w = world(eng, entries=1, cwh=None, cutoff_after=6)  # the schedule's real 24-hour window
    fake = FakeProvider()
    fake.add(w)
    after(eng, w["deadline"])
    tick(eng, BASE, provider_factory=lambda: fake)
    after(eng, w["cutoff"])
    r = tick(eng, BASE, provider_factory=lambda: fake)
    assert status(eng, w["round"]) == "settling"
    assert not runs(eng, "scheduler.finalise") and not runs(eng, "scheduler.results_full")
    (note,) = steps(r, "finalise")
    assert note.outcome == Outcome.SKIPPED and "earliest finalisation" in note.detail


def test_provider_calls_off_hold_real_round_finalisation(db):
    eng, _ = db
    w = world(eng)
    after(eng, w["cutoff"])
    for _ in range(2):
        r = tick(eng, replace(BASE, provider_calls=False))  # no provider factory at all
    assert status(eng, w["round"]) == "settling"
    assert not runs(eng, "scheduler.results") and not runs(eng, "scheduler.results_full")
    notes = {s.step: s for s in r.steps if not s.job_run_id}
    assert notes["results"].outcome == Outcome.DEFERRED
    assert notes["finalise"].outcome == Outcome.DEFERRED and "re-check" in notes["finalise"].detail


def test_blocking_alert_holds_finalisation_for_an_operator(db):
    eng, _ = db
    w = world(eng, cutoff_after=6)
    fake = FakeProvider()
    fake.add(w)
    after(eng, w["deadline"])
    tick(eng, BASE, provider_factory=lambda: fake)  # results before the cutoff: no late alerts
    after(eng, w["cutoff"])
    with transaction(eng) as conn:
        results_repo.raise_alerts(conn, w["round"], None,
                                  [Alert("score_conflict", w["fixtures"][0], "test", {})])  # fmt: skip
    r = tick(eng, BASE, provider_factory=lambda: fake)
    blocked = [s for s in steps(r, "finalise") if s.outcome == Outcome.BLOCKING]
    assert blocked and r.exit_code == 4 and status(eng, w["round"]) == "settling"
    with transaction(eng) as conn:  # never resolved automatically
        assert results_repo.open_alerts(conn, w["round"], blocking_only=True)


# ------------------------------------------------------------------ provider budget
def test_per_tick_and_daily_request_caps_defer_explicitly(db):
    eng, _ = db
    a, b = world(eng), world(eng)
    fake = FakeProvider()
    fake.add(a)
    fake.add(b)
    after(eng, max(a["deadline"], b["deadline"]))
    r = tick(eng, replace(BASE, max_requests_per_tick=1), provider_factory=lambda: fake)
    res = steps(r, "results")
    assert {s.outcome for s in res} == {Outcome.DEFERRED, Outcome.SUCCEEDED} and len(res) == 2
    deferred = next(s for s in res if s.outcome == Outcome.DEFERRED)
    assert "budget exhausted" in deferred.detail and deferred.api_requests == 0
    assert fake.requests_made == 1 and r.api_requests == 1 and r.exit_code == 0
    with transaction(eng) as conn:  # a day's scheduler requests already recorded
        conn.execute(sa.insert(job_runs).values(job="scheduler.provider", scope="x", args={},
                                                status="succeeded", api_requests=100,
                                                finished_at=sa.func.clock_timestamp()))  # fmt: skip
    r = tick(eng, replace(BASE, max_requests_per_day=100), provider_factory=lambda: fake)
    res = steps(r, "results")
    assert res and all(s.outcome == Outcome.DEFERRED and "24-hour" in s.detail for s in res)
    assert fake.requests_made == 1  # nothing more was sent


def test_provider_failure_is_retryable_with_backoff_then_recovers(db):
    eng, _ = db
    w = world(eng)
    broken = FakeProvider(fail=ApiFootballHTTPError(503, "unavailable"))
    broken.add(w)
    after(eng, w["deadline"])
    r = tick(eng, BASE, provider_factory=lambda: broken)
    (res,) = steps(r, "results")
    assert res.outcome == Outcome.RETRYABLE and r.exit_code == 1
    assert runs(eng, "scheduler.results")[-1].status == "failed"
    assert runs(eng, "scheduler.results")[-1].api_requests == 1  # failed requests still count
    calls = len(broken.calls)
    r = tick(eng, BASE, provider_factory=lambda: broken)  # inside the back-off window
    assert len(broken.calls) == calls
    assert any(
        s.outcome == Outcome.DEFERRED and "back-off" in s.detail for s in steps(r, "results")
    )
    with transaction(eng) as conn:
        after(eng, db_now(conn) + timedelta(seconds=1))
    good = FakeProvider()
    good.add(w)
    r = tick(eng, BASE, provider_factory=lambda: good)
    assert [s.outcome for s in steps(r, "results") if s.job_run_id] == [Outcome.SUCCEEDED]
    denied = FakeProvider(fail=ApiFootballAuthError("fixtures", {"token": "invalid"}))
    denied.add(w)
    with transaction(eng) as conn:
        after(eng, db_now(conn) + timedelta(milliseconds=100))
    r = tick(eng, BASE, provider_factory=lambda: denied)
    (res,) = [s for s in steps(r, "results") if s.job_run_id]
    assert res.outcome == Outcome.BLOCKING and "invalid" not in res.detail  # no provider text


# ------------------------------------------------------------------ reliability
def test_concurrent_ticks_one_runs_the_other_skips(db):
    eng, _ = db
    w = world(eng)
    gate = threading.Event()
    slow = FakeProvider(gate=gate)
    slow.add(w)
    after(eng, w["deadline"])
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", tick(eng, BASE,
                         provider_factory=lambda: slow)))  # fmt: skip
    t.start()
    for _ in range(100):  # wait until the first tick is inside the provider call
        if slow.calls:
            break
        threading.Event().wait(0.1)
    second = tick(eng, BASE, provider_factory=lambda: slow)
    gate.set()
    t.join(60)
    assert second.status == "busy" and second.exit_code == 0
    assert out["a"].status == "completed"
    assert len(runs(eng, "scheduler.lock")) == 1 and len(slow.calls) == 1


def test_interrupted_tick_is_recorded_as_abandoned_and_resumes(db, monkeypatch):
    eng, _ = db
    w = world(eng)
    after(eng, w["deadline"])

    def crash(*a, **k):
        raise KeyboardInterrupt  # the process is stopped in the middle of a step

    monkeypatch.setattr(rec.rounds_svc, "lock_round", crash)
    with pytest.raises(KeyboardInterrupt):
        tick(eng, replace(BASE, provider_calls=False))
    # the interrupted tick knew it was ending: it recorded its own step as abandoned
    last = runs(eng, "scheduler.lock")[-1]
    assert last.status == "failed" and last.error.startswith("abandoned: interrupted")
    assert status(eng, w["round"]) == "open"  # nothing half-done
    monkeypatch.undo()
    r = tick(eng, replace(BASE, provider_calls=False))
    assert any(s.outcome == Outcome.DEFERRED for s in steps(r, "lock"))  # back-off first
    with transaction(eng) as conn:
        after(eng, db_now(conn) + timedelta(seconds=1))
    r = tick(eng, replace(BASE, provider_calls=False))
    assert [s.outcome for s in steps(r, "lock")] == [Outcome.SUCCEEDED]


def test_missed_ticks_catch_up_in_dependency_order(db):
    """The scheduler was down through the deadline. Round A recovers before its
    settlement cutoff and catches up to final in order; round B's outage ran past its
    cutoff, so the results arrive late and the existing late-notification alerts hold
    it for an operator (a missed tick never bypasses a safeguard)."""
    eng, _ = db
    a = world(eng, entries=2, deadline_in=2, cutoff_after=8)
    b = world(eng, entries=2, deadline_in=2, cutoff_after=1)
    fake = FakeProvider()
    fake.add(a)
    fake.add(b)
    after(eng, b["cutoff"])  # several ticks missed; A's cutoff not yet reached
    first = tick(eng, BASE, provider_factory=lambda: fake)
    done_a = [s.step for s in first.steps if s.round_code == status_code(eng, a) and s.job_run_id]
    assert done_a[:3] == ["lock", "results", "settle"]
    after(eng, a["cutoff"])
    lines = []
    for _ in range(3):
        r = tick(eng, BASE, provider_factory=lambda: fake)
        lines += [s.line() for s in r.steps]
        if status(eng, a["round"]) == "final":
            break
    assert status(eng, a["round"]) == "final", lines
    code_a = status_code(eng, a)
    order = [x.job for x in runs(eng)
             if x.scope == code_a and x.status == "succeeded"]  # fmt: skip
    firsts = [order.index(j) for j in ("scheduler.lock", "scheduler.results", "scheduler.settle",
                                       "scheduler.results_full", "scheduler.finalise")]  # fmt: skip
    assert firsts == sorted(firsts)
    assert status(eng, b["round"]) == "settling"
    held = [s for s in r.steps if s.round_code == status_code(eng, b) and s.step == "finalise"]
    assert held and held[0].outcome == Outcome.BLOCKING and r.exit_code == 4
    with transaction(eng) as conn:
        codes = {x.code for x in results_repo.open_alerts(conn, b["round"], blocking_only=True)}
    assert "late_notification" in codes


def status_code(eng, w):
    with transaction(eng) as conn:
        return conn.execute(
            sa.select(rounds_t.c.code).where(rounds_t.c.id == w["round"])
        ).scalar_one()


def test_failure_in_one_round_does_not_affect_another(db, monkeypatch):
    eng, _ = db
    a, b = world(eng), world(eng)
    after(eng, max(a["deadline"], b["deadline"]))
    real = rec.settlement.settle_round

    def flaky(engine, actor, rid, **kw):
        if rid == a["round"]:
            raise sa.exc.OperationalError("SELECT 1", {}, Exception("connection lost"))
        return real(engine, actor, rid, **kw)

    monkeypatch.setattr(rec.settlement, "settle_round", flaky)
    r = tick(eng, replace(BASE, provider_calls=False))
    by_round = {}
    for s in steps(r, "settle"):
        by_round.setdefault(s.round_code, s)
    codes = {x.scope: x for x in runs(eng, "scheduler.settle")}
    outcomes = {s.round_code: s.outcome for s in by_round.values()}
    assert set(outcomes.values()) == {Outcome.SUCCEEDED, Outcome.RETRYABLE} and r.exit_code == 1
    assert "connection lost" not in str([s.detail for s in r.steps])  # type name only
    assert status(eng, a["round"]) == "locked" and status(eng, b["round"]) == "settling"
    assert {x.status for x in codes.values()} == {"failed", "succeeded"}


def test_database_unavailable_is_reported_not_raised():
    eng = sa.create_engine("postgresql+psycopg://nobody@127.0.0.1:9/none_test",
                           connect_args={"connect_timeout": 2})  # fmt: skip
    r = tick(eng, BASE)
    assert r.status == "unavailable" and r.exit_code == 1 and "database" in r.detail


# ------------------------------------------------------------------ streams and publication
def test_official_and_unlisted_streams_are_never_touched(db):
    eng, _ = db
    with transaction(eng) as conn:
        try:
            off, osnap, ofids, odl, _ = make_settlement_round(conn, series="official")
            confirm_entry(conn, off, osnap, ofids, make_user(conn))
        except sa.exc.DBAPIError:
            off = None  # the database itself refuses an official round before D-38
    dev = world(eng, development=True)
    beta = world(eng)
    after(eng, max(dev["deadline"], beta["deadline"]))
    r = tick(eng, replace(BASE, streams=("beta",), provider_calls=False))
    assert status(eng, beta["round"]) in ("locked", "settling")
    assert status(eng, dev["round"]) == "open"  # development not in this allowlist
    if off is not None:
        assert status(eng, off) == "open"
    assert {s.stream for s in r.steps} == {"beta"}


def test_no_publication_pathway_and_drafts_stay_drafts(db):
    eng, _ = db
    with transaction(eng) as conn:
        now = db_now(conn)
        from diski9.backend.repositories import rounds as rounds_repo

        draft = conn.execute(sa.insert(rounds_t).values(
            code="2026-W49-draft", schedule_id=rounds_repo.schedule_id(conn),
            series_id=rounds_repo.series_id(conn, "beta"), window_start_at=now - timedelta(hours=1),
            window_end_at=now + timedelta(days=3)).returning(rounds_t.c.id)).scalar_one()  # fmt: skip
    r = tick(eng, replace(BASE, provider_calls=False))
    assert status(eng, draft) == "draft"
    assert any("2026-W49-draft" in n and "operator" in n for n in r.notes)
    # static guarantee: the scheduler package calls only the four approved services and
    # never publication, round creation, human-only services or operator sign-in
    called, imported = set(), set()
    for path in (ROOT / "src/diski9/backend/jobs").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                called.add(node.attr)
            if isinstance(node, ast.ImportFrom):
                imported |= {a.name for a in node.names} | {node.module or ""}
    forbidden = {"publish_round", "create_round", "build_live_snapshot", "correct_result",
                 "withdraw_correction", "resolve_alert", "invalidate_round", "reopen_round",
                 "set_result_mode", "authenticate_operator", "cli_principal", "getpass",
                 "grant_role", "bootstrap_owner", "as_of"}  # fmt: skip
    assert not (called | imported) & forbidden
    assert {"lock_round", "import_results", "settle_round", "finalise_round"} <= called


def test_dry_run_writes_nothing_and_calls_no_provider(db):
    eng, _ = db
    w = world(eng)
    fake = FakeProvider()
    fake.add(w)
    after(eng, w["deadline"])
    before = counts(eng)
    report = plan_tick(eng, BASE)
    assert [s.step for s in report.steps if s.outcome == Outcome.PLANNED] == ["lock"]
    assert counts(eng) == before and status(eng, w["round"]) == "open" and not fake.calls


# ------------------------------------------------------------------ command line
def _cli(args, env):
    full = {k: v for k, v in os.environ.items() if not k.startswith("DISKI9_JOBS_")}
    full.update(env)
    p = subprocess.run([sys.executable, "-m", "diski9.cli", *args], capture_output=True,
                       text=True, env=full, timeout=120)  # fmt: skip
    return p.returncode, p.stdout + p.stderr


def test_cli_exit_codes_and_cron_friendly_output(db):
    eng, url = db
    w = world(eng, deadline_in=2)
    after(eng, w["deadline"])
    rc, out = _cli(["jobs", "tick"], {"DISKI9_APP_DATABASE_URL": url})
    assert rc == 0 and "disabled" in out and status(eng, w["round"]) == "open"
    rc, out = _cli(["jobs", "tick"], {"DISKI9_JOBS_ENABLED": "1", "DISKI9_JOBS_STREAMS": "official",
                                      "DISKI9_APP_DATABASE_URL": url})  # fmt: skip
    assert rc == 2 and "official" in out and status(eng, w["round"]) == "open"
    env = {"DISKI9_JOBS_ENABLED": "1", "DISKI9_JOBS_STREAMS": "beta",
           "DISKI9_APP_DATABASE_URL": url}  # fmt: skip
    rc, out = _cli(["jobs", "tick", "--dry-run"], env)
    assert rc == 0 and "lock: planned" in out and "nothing was written" in out
    assert status(eng, w["round"]) == "open"
    rc, out = _cli(["jobs", "tick"], env)
    assert rc == 0 and "lock: succeeded" in out and "completed:" in out, out
    assert "postgresql" not in out and "password" not in out.lower()
    rc, out = _cli(["jobs", "status"], env)
    assert rc == 0 and "scheduler.lock" in out and "automation enabled" in out


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))
