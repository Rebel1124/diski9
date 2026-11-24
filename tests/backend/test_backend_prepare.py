"""Phase 6C.6 Stage E.1a: automated Beta draft creation, readiness and monitoring.

Isolated PostgreSQL databases. The week clock (``prepare._now``) is placed on a
chosen weekday of a week at least four days ahead, so every test runs the same on
any calendar day; readiness itself always uses the real database clock, and the
snapshot builder is injected (synthetic snapshots built exactly like the Stage E
tests) except where the default football-store builder is exercised.
"""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from champ_helpers import drop, isolated_engine
from svc_helpers import principal
from test_backend_scheduler import BASE as SCHEDULER_BASE
from test_backend_scheduler import after, world

from diski9.backend.auth.permissions import Forbidden
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import audit_log, job_runs, round_status_history, rounds
from diski9.backend.devdata import dev_snapshot
from diski9.backend.jobs import ConfigError, SchedulerConfig, load_config, plan_tick, prepare, tick
from diski9.backend.ops import OpsConfig, collect, evaluate
from diski9.backend.services import rounds as svc
from diski9.backend.services.common import ValidationFailed
from diski9.backend.services.rounds import SYSTEM

PREP = replace(SCHEDULER_BASE, provider_calls=False, prepare=True, prepare_streams=("beta",),
               prepare_min_seconds=10.0)  # fmt: skip


@pytest.fixture
def db(pg_url, request):
    name = f"diski9_p_{request.node.name[:34].lower()}_test".replace("[", "_").replace("]", "")
    eng, url = isolated_engine(pg_url, name)
    try:
        yield eng, url
    finally:
        eng.dispose()
        drop(pg_url, name)


def place_clock(monkeypatch, eng, hours_after_tuesday: float) -> prepare.Week:
    """Run the week clock at Tuesday 00:00 UTC + ``hours`` of a week 4–10 days ahead."""
    with transaction(eng) as conn:
        real = db_now(conn)
        sched = prepare.load_schedule(conn)
    d = (real + timedelta(days=10)).date()
    tuesday = datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(days=(d.weekday() - 1) % 7)
    offset = tuesday + timedelta(hours=hours_after_tuesday) - real
    monkeypatch.setattr(prepare, "_now", lambda conn: db_now(conn) + offset)
    return prepare.week_at(real + offset, sched.window_rule, sched.publish_rule,
                           timedelta(hours=78))  # fmt: skip


def builder(fixtures: int = 20, calls: list | None = None, before=None):
    def build(code, window_start, window_end, as_of, config):
        if calls is not None:
            calls.append(code)
        if before is not None:
            before()
        snap = dev_snapshot("dev-x", as_of, window_start + timedelta(hours=2), fixtures=fixtures)
        return replace(snap, round_id=code, config_version=config.version)

    return build


def counts(eng):
    with transaction(eng) as conn:

        def q(t, *w):
            return conn.execute(sa.select(sa.func.count()).select_from(t).where(*w)).scalar_one()

        return {
            "rounds": q(rounds),
            "audit": q(audit_log),
            "history": q(round_status_history),
            "ledger": q(job_runs, job_runs.c.job == "scheduler.provider"),
        }


def row(eng, code):
    with transaction(eng) as conn:
        return conn.execute(sa.select(rounds).where(rounds.c.code == code)).one_or_none()


def runs(eng, job):
    with transaction(eng) as conn:
        return list(conn.execute(sa.select(job_runs).where(job_runs.c.job == job)
                                 .order_by(job_runs.c.id)))  # fmt: skip


# ------------------------------------------------------------------ configuration
def test_configuration_is_off_by_default_beta_only_and_fails_closed():
    base = {"DISKI9_JOBS_ENABLED": "1", "DISKI9_JOBS_STREAMS": "beta"}
    cfg = load_config(base, environment="test")
    assert not cfg.prepare and cfg.prepare_streams == ()
    on = load_config({**base, "DISKI9_JOBS_PREPARE": "1", "DISKI9_JOBS_PREPARE_STREAMS": "beta"},
                     environment="production")  # fmt: skip
    assert on.prepare and on.prepare_streams == ("beta",)
    assert on.prepare_create_lead == timedelta(hours=78)
    assert on.prepare_readiness_interval == timedelta(minutes=30)
    bad = [
        {"DISKI9_JOBS_PREPARE": "1", "DISKI9_JOBS_PREPARE_STREAMS": "beta"},  # no automation
        {**base, "DISKI9_JOBS_PREPARE": "1"},  # no stream
        {**base, "DISKI9_JOBS_PREPARE": "1", "DISKI9_JOBS_PREPARE_STREAMS": "official"},
        {**base, "DISKI9_JOBS_PREPARE": "1", "DISKI9_JOBS_PREPARE_STREAMS": "development"},
        {**base, "DISKI9_JOBS_PREPARE_CREATE_LEAD_HOURS": "79"},
        {**base, "DISKI9_JOBS_PREPARE_READINESS_MINUTES": "1"},
        {**base, "DISKI9_JOBS_PREPARE_GRACE_HOURS": "0"},
        {**base, "DISKI9_JOBS_PREPARE": "maybe"},
        {**base, "DISKI9_JOBS_PREPARE": "1", "DISKI9_JOBS_PREPARE_STREAMS": "beta",
         "DISKI9_JOBS_TICK_BUDGET_SECONDS": "60", "DISKI9_JOBS_PREPARE_MIN_SECONDS": "60"},
    ]  # fmt: skip
    for env in bad:
        with pytest.raises(ConfigError):
            load_config(env, environment="test")
    for streams in (("official",), ("development",)):
        with pytest.raises(ConfigError):
            SchedulerConfig(enabled=True, streams=("beta",), prepare=True, prepare_streams=streams)


# ------------------------------------------------------------------ the service
def test_scheduled_draft_is_system_only_schedule_derived_and_audited(db):
    eng, _ = db
    with pytest.raises(Forbidden):
        svc.create_scheduled_draft(eng, principal(eng, role="owner"), iso_year=2031, iso_week=10)
    for bad in ((2031, 0), (2031, 54), (True, 3)):
        with pytest.raises(ValidationFailed):
            svc.create_scheduled_draft(eng, SYSTEM, iso_year=bad[0], iso_week=bad[1])
    with pytest.raises(TypeError):  # no code, window, series or development flag can be passed
        svc.create_scheduled_draft(eng, SYSTEM, iso_year=2031, iso_week=10, code="evil")
    before = counts(eng)
    res = svc.create_scheduled_draft(eng, SYSTEM, iso_year=2031, iso_week=10, job_run_id=None)
    assert res.created and res.round.code == "2031-W10-weekend"
    assert res.round.status == "draft" and not res.round.is_development
    assert res.round.series == "beta"
    assert (res.round.window_start_at, res.round.window_end_at) == svc.schedule_window(
        eng, 2031, 10
    )
    assert res.round.fingerprint is None and res.round.published_at is None  # inert
    with transaction(eng) as conn:
        a = conn.execute(sa.select(audit_log).where(audit_log.c.action == "round.create")).one()
        h = conn.execute(sa.select(round_status_history)
                         .where(round_status_history.c.round_id == res.round.id)).one()  # fmt: skip
    assert a.actor_role == "system" and a.actor_user_id is None and a.after["scheduled"] is True
    assert h.reason == "created (scheduled)" and h.actor_user_id is None
    assert counts(eng) == {**before, "rounds": 1 + before["rounds"], "audit": before["audit"] + 1,
                           "history": before["history"] + 1}  # fmt: skip
    again = svc.create_scheduled_draft(eng, SYSTEM, iso_year=2031, iso_week=10)
    assert not again.created and again.round.id == res.round.id
    assert counts(eng)["audit"] == before["audit"] + 1  # nothing written the second time


def test_existing_and_published_rounds_are_never_touched(db):
    eng, _ = db
    op = principal(eng, role="operator")
    start, end = svc.schedule_window(eng, 2031, 11)
    v = svc.create_round(eng, op, code="2031-W11-weekend", window_start=start, window_end=end)
    res = svc.create_scheduled_draft(eng, SYSTEM, iso_year=2031, iso_week=11)
    assert not res.created and res.round.id == v.id
    # a published round with the scheduled code: still untouched
    with transaction(eng) as conn:
        now = db_now(conn)
    code = svc.scheduled_code(2031, 12)
    snap = replace(dev_snapshot("dev-x", now, now + timedelta(hours=3)), round_id=code)
    w = svc.create_round(eng, op, code=code, window_start=snap.window[0], window_end=snap.window[1])
    pub = svc.publish_round(eng, op, w.id, snap, source="football-db")
    before = (row(eng, code), counts(eng))
    res = svc.create_scheduled_draft(eng, SYSTEM, iso_year=2031, iso_week=12)
    assert (
        not res.created and res.round.status == "open" and res.round.fingerprint == pub.fingerprint
    )
    assert (row(eng, code), counts(eng)) == before


def test_non_beta_schedule_is_refused(db):
    eng, _ = db
    with transaction(eng) as conn:
        conn.execute(sa.text(
            "UPDATE app.round_schedules SET series_id = (SELECT id FROM app.championship_series "
            "WHERE code = 'official') WHERE code = 'weekend'"))  # fmt: skip
    with pytest.raises(ValidationFailed):
        svc.create_scheduled_draft(eng, SYSTEM, iso_year=2031, iso_week=13)
    assert counts(eng)["rounds"] == 0


def test_concurrent_scheduled_and_manual_creation_make_one_round(db):
    eng, _ = db
    op = principal(eng, role="operator")
    start, end = svc.schedule_window(eng, 2031, 14)
    errors, barrier = [], threading.Barrier(5)

    def scheduled():
        barrier.wait()
        try:
            svc.create_scheduled_draft(eng, SYSTEM, iso_year=2031, iso_week=14)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def manual():
        barrier.wait()
        # the person may lose the race: refused, nothing written
        with contextlib.suppress(ValidationFailed, sa.exc.IntegrityError):
            svc.create_round(eng, op, code="2031-W14-weekend", window_start=start, window_end=end)

    threads = [threading.Thread(target=scheduled) for _ in range(4)]
    threads.append(threading.Thread(target=manual))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with transaction(eng) as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(rounds)).scalar_one()
        creates = conn.execute(sa.select(sa.func.count()).select_from(audit_log)
                               .where(audit_log.c.action == "round.create")).scalar_one()  # fmt: skip
    assert n == 1 and creates == 1


# ------------------------------------------------------------------ inside jobs tick
def test_disabled_paused_and_dry_run_create_nothing(db, monkeypatch):
    eng, _ = db
    place_clock(monkeypatch, eng, 12)
    before = counts(eng)
    tick(eng, replace(PREP, prepare=False, prepare_streams=()), snapshot_builder=builder())
    tick(eng, replace(PREP, paused=True, pause_reason="test"), snapshot_builder=builder())
    report = plan_tick(eng, PREP)
    assert [s.step for s in report.steps if s.outcome.value == "planned"] == ["prepare_draft"]
    assert counts(eng) == before and not runs(eng, prepare.PREPARE_DRAFT)


def test_tick_creates_once_and_evaluates_readiness_without_provider_calls(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 12)
    calls: list = []
    before = counts(eng)
    r1 = tick(eng, PREP, snapshot_builder=builder(calls=calls))
    assert r1.status == "completed" and r1.exit_code == 0
    steps = {s.step: s for s in r1.steps}
    assert steps["prepare_draft"].outcome.value == "succeeded"
    assert steps["prepare_readiness"].outcome.value == "succeeded"
    assert "READY" in steps["prepare_readiness"].detail and "nothing published" in steps[
        "prepare_readiness"].detail  # fmt: skip
    r = row(eng, week.code)
    assert r.status == "draft" and not r.is_development and r.window_start_at == week.window_start
    (ready,) = runs(eng, prepare.PREPARE_READINESS)
    v = prepare.decode(ready.error, ready.finished_at)
    assert ready.status == "succeeded" and v.ready and v.summary["eligible"] != "0"
    r2 = tick(eng, PREP, snapshot_builder=builder(calls=calls))  # within the interval
    assert not [s for s in r2.steps if s.job_run_id and s.step.startswith("prepare")]
    assert calls == [week.code] and len(runs(eng, prepare.PREPARE_DRAFT)) == 1
    after_counts = counts(eng)
    assert after_counts["rounds"] == before["rounds"] + 1
    assert after_counts["ledger"] == before["ledger"] == 0  # no provider request
    st = prepare.preparation_status(eng, PREP)
    assert st.state == "draft_ready" and st.created_by == "scheduled"
    assert any("READY for operator review" in n for n in r2.notes)


def test_manual_draft_first_is_evaluated_not_recreated(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 30)
    op = principal(eng, role="operator")
    svc.create_round(eng, op, code=week.code, window_start=week.window_start,
                     window_end=week.window_end)  # fmt: skip
    r = tick(eng, PREP, snapshot_builder=builder(fixtures=5))
    assert "prepare_draft" not in {s.step for s in r.steps}
    assert not runs(eng, prepare.PREPARE_DRAFT)
    st = prepare.preparation_status(eng, PREP)
    assert st.created_by == "operator" and st.state == "draft_not_ready"
    assert st.verdict.category == "opening_checks"


def test_concurrent_ticks_make_one_draft(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 12)
    out, barrier = [], threading.Barrier(4)

    def go():
        barrier.wait()
        out.append(tick(eng, PREP, snapshot_builder=builder()).status)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # one owner at a time; a tick racing another's "busy" record may wait (indeterminate,
    # Stage D); never two drafts. A later tick completes whatever is left.
    assert set(out) <= {"completed", "busy", "indeterminate"}
    if "completed" not in out:
        tick(eng, PREP, snapshot_builder=builder())
    with transaction(eng) as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(rounds)
                         .where(rounds.c.code == week.code)).scalar_one()  # fmt: skip
    assert n == 1 and len(runs(eng, prepare.PREPARE_DRAFT)) == 1


def test_crash_before_and_after_the_creation_transaction(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 12)
    real = svc.create_scheduled_draft

    def before_commit(*a, **k):
        raise RuntimeError("process died before the transaction")

    monkeypatch.setattr(svc, "create_scheduled_draft", before_commit)
    r = tick(eng, PREP, snapshot_builder=builder())
    assert {s.step: s.outcome.value for s in r.steps}["prepare_draft"] == "retryable_failure"
    assert row(eng, week.code) is None
    time.sleep(1.2)  # back-off (1 s in the test configuration)

    def after_commit(*a, **k):
        real(*a, **k)
        raise RuntimeError("process died after the transaction")

    monkeypatch.setattr(svc, "create_scheduled_draft", after_commit)
    tick(eng, PREP, snapshot_builder=builder())
    assert row(eng, week.code) is not None
    monkeypatch.setattr(svc, "create_scheduled_draft", real)
    time.sleep(1.2)
    r = tick(eng, PREP, snapshot_builder=builder())
    assert "prepare_draft" not in {s.step for s in r.steps if s.job_run_id}
    assert prepare.preparation_status(eng, PREP).state == "draft_ready"
    with transaction(eng) as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(audit_log)
                            .where(audit_log.c.action == "round.create")).scalar_one() == 1  # fmt: skip


def test_interrupted_readiness_is_recorded_and_recovered(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 12)

    def boom():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        tick(eng, PREP, snapshot_builder=builder(before=boom))
    (first,) = runs(eng, prepare.PREPARE_READINESS)
    assert first.status == "failed" and first.error.startswith("abandoned: interrupted")
    assert row(eng, week.code).status == "draft"
    time.sleep(1.2)
    tick(eng, PREP, snapshot_builder=builder())
    assert prepare.preparation_status(eng, PREP).state == "draft_ready"


def test_lock_lost_during_readiness_records_no_verdict(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 12)
    svc.create_scheduled_draft(eng, SYSTEM, iso_year=week.iso_year, iso_week=week.iso_week)

    def kill_holder():
        with eng.connect() as c:
            c.execute(sa.text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                              "WHERE application_name LIKE 'diski9-tick:%'"))  # fmt: skip
            c.commit()

    r = tick(eng, PREP, snapshot_builder=builder(before=kill_holder))
    assert r.status == "lock_lost" and r.exit_code == 1
    (rr,) = runs(eng, prepare.PREPARE_READINESS)
    assert rr.status == "failed" and "lock lost" in rr.error
    assert prepare.preparation_status(eng, PREP).verdict is None
    assert row(eng, week.code).status == "draft"


def test_readiness_never_starts_without_enough_tick_time(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 12)
    svc.create_scheduled_draft(eng, SYSTEM, iso_year=week.iso_year, iso_week=week.iso_week)

    def seed(seconds):
        with transaction(eng) as conn:
            now = db_now(conn)
            conn.execute(sa.insert(job_runs).values(
                job=prepare.PREPARE_READINESS, scope="seed", args={}, status="succeeded",
                started_at=now - timedelta(seconds=seconds + 60),
                finished_at=now - timedelta(seconds=60), api_requests=0))  # fmt: skip

    seed(130)  # twice 130 s exceeds the 240 s budget: wait for a fresh tick
    r = tick(eng, PREP, snapshot_builder=builder())
    (rep,) = [s for s in r.steps if s.step == "prepare_readiness"]
    assert rep.outcome.value == "deferred" and rep.job_run_id is None and "260 s" in rep.detail
    assert not [x for x in runs(eng, prepare.PREPARE_READINESS) if x.scope == week.code]
    seed(500)  # beyond the safe limit for the 20-minute abandonment threshold
    r = tick(eng, PREP, snapshot_builder=builder())
    (rep,) = [s for s in r.steps if s.step == "prepare_readiness"]
    assert rep.outcome.value == "blocking_failure" and "too long" in rep.detail
    assert prepare.preparation_status(eng, PREP).verdict is None
    assert prepare.needed_seconds(None, PREP) == 10.0 and prepare.needed_seconds(30, PREP) == 60


def test_unavailable_football_store_fails_closed(db, monkeypatch, tmp_path):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 12)
    missing = prepare.football_snapshot_builder(f"sqlite:///{tmp_path / 'absent.sqlite'}")
    r = tick(eng, PREP, snapshot_builder=missing)
    (rep,) = [s for s in r.steps if s.step == "prepare_readiness"]
    assert rep.outcome.value == "blocking_failure" and "football store unavailable" in rep.detail
    assert not (tmp_path / "absent.sqlite").exists()  # never created
    assert r.exit_code == 4
    st = prepare.preparation_status(eng, PREP)
    assert st.state == "intervention" and st.blocked
    assert row(eng, week.code).status == "draft"


def test_default_builder_reads_a_real_football_store(db, monkeypatch, tmp_path):
    from diski9.db.engine import make_engine
    from diski9.db.schema import metadata

    eng, _ = db
    place_clock(monkeypatch, eng, 12)
    url = f"sqlite:///{tmp_path / 'football.sqlite'}"
    fe = make_engine(url)
    metadata.create_all(fe)
    fe.dispose()
    tick(eng, PREP, snapshot_builder=prepare.football_snapshot_builder(url))
    st = prepare.preparation_status(eng, PREP)
    assert st.state == "draft_not_ready" and st.verdict.category == "no_fixtures"


# ------------------------------------------------------------------ states and monitoring
def _findings(eng, jobs=PREP, ops=None):
    snap = collect(eng, environment="test", finalise_warning=timedelta(hours=6), jobs=jobs)
    return {f.code: f for f in evaluate(snap, ops or OpsConfig(), jobs)
            if f.category == "preparation"}  # fmt: skip


def test_states_and_findings_through_the_week(db, monkeypatch):
    eng, _ = db
    fast = replace(PREP, prepare_readiness_interval=timedelta(0))  # evaluate on every tick
    week = place_clock(monkeypatch, eng, 2)  # Tuesday 02:00: draft due, not yet created
    f = _findings(eng)
    assert prepare.preparation_status(eng, PREP).state == "no_draft"
    assert f["prepare_no_draft"].severity.label == "WARNING"
    late = replace(PREP, prepare_create_lead=timedelta(hours=6))
    assert prepare.preparation_status(eng, late).state == "not_due"
    tick(eng, fast, snapshot_builder=builder(fixtures=5))  # created, NOT READY
    assert prepare.preparation_status(eng, PREP).state == "draft_not_ready"
    assert _findings(eng) == {}  # early NOT READY is expected: no noise
    place_clock(monkeypatch, eng, 72 + 4)  # Friday 04:00 UTC: inside the attention window
    assert _findings(eng)["prepare_not_ready"].severity.label == "INFO"
    place_clock(monkeypatch, eng, 72 + 7)  # after the target
    tick(eng, fast, snapshot_builder=builder(fixtures=5))
    assert _findings(eng)["prepare_not_ready"].severity.label == "WARNING"
    tick_ready = builder()
    place_clock(monkeypatch, eng, 72 + 7.6)
    tick(eng, fast, snapshot_builder=tick_ready)
    assert prepare.preparation_status(eng, PREP).state == "draft_ready"
    assert _findings(eng)["prepare_ready_unpublished"].severity.label == "INFO"
    place_clock(monkeypatch, eng, 72 + 9)  # target + 3 h
    tick(eng, fast, snapshot_builder=tick_ready)
    assert _findings(eng)["prepare_ready_unpublished"].severity.label == "WARNING"
    place_clock(monkeypatch, eng, 72 + 13)  # beyond the 6-hour grace
    assert prepare.preparation_status(eng, PREP).state == "target_missed"
    assert _findings(eng)["prepare_target_missed"].severity.label == "WARNING"  # was READY
    del week


def test_a_draft_never_evaluated_near_the_target_is_a_warning(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 30)
    svc.create_scheduled_draft(eng, SYSTEM, iso_year=week.iso_year, iso_week=week.iso_week)
    assert prepare.preparation_status(eng, PREP).state == "draft_not_evaluated"
    assert _findings(eng) == {}  # days before the target: not actionable
    place_clock(monkeypatch, eng, 72 + 4)
    assert _findings(eng)["prepare_stale_evaluation"].severity.label == "WARNING"


def test_no_draft_close_to_the_target_is_critical_and_paused_is_quiet(db, monkeypatch):
    eng, _ = db
    place_clock(monkeypatch, eng, 72 + 1)  # Friday 01:00, target at 06:00
    assert _findings(eng)["prepare_no_draft"].severity.label == "CRITICAL"
    assert _findings(eng, replace(PREP, paused=True, pause_reason="x")) == {}
    off = replace(PREP, prepare=False, prepare_streams=())
    assert set(_findings(eng, off)) == {"prepare_disabled"}
    assert _findings(eng, replace(PREP, enabled=False, prepare=False, prepare_streams=())) == {}


def test_published_and_lapsed_states(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 12)
    tick(eng, PREP, snapshot_builder=builder())
    # an operator publishes (through the service the CLI uses); the scheduler never does
    op = principal(eng, role="operator")
    with transaction(eng) as conn:
        now = db_now(conn)
        config = svc.round_config(conn, row(eng, week.code).id)  # the draft's own config
    snap = builder()(week.code, week.window_start, week.window_end, now, config)
    svc.publish_round(eng, op, row(eng, week.code).id, snap, source="football-db",
                      expected_fingerprint=snap.fingerprint)  # fmt: skip
    assert prepare.preparation_status(eng, PREP).state == "published"
    assert not [s for s in tick(eng, PREP, snapshot_builder=builder()).steps
                if s.step.startswith("prepare_") and s.job_run_id]  # fmt: skip
    # the previous week's draft, never published, is reported as lapsed for 7 days
    py, pw = prepare._shift(week.iso_year, week.iso_week, -1)
    prev = svc.create_scheduled_draft(eng, SYSTEM, iso_year=py, iso_week=pw).round
    st = prepare.preparation_status(eng, PREP)
    assert prev.code in st.lapsed_recent and week.code not in st.lapsed_recent
    assert _findings(eng)["prepare_lapsed"].subject == prev.code


def test_scheduler_never_publishes_even_when_ready(db, monkeypatch):
    eng, _ = db
    week = place_clock(monkeypatch, eng, 72 + 7)  # after the publication target
    for _ in range(3):
        tick(eng, replace(PREP, prepare_readiness_interval=timedelta(minutes=5)),
             snapshot_builder=builder())  # fmt: skip
    r = row(eng, week.code)
    assert r.status == "draft" and r.published_at is None
    with transaction(eng) as conn:
        assert not conn.execute(sa.select(audit_log).where(
            audit_log.c.action == "round.publish")).first()  # fmt: skip


def test_lifecycle_steps_still_run_first_and_unchanged(db, monkeypatch):
    eng, _ = db
    place_clock(monkeypatch, eng, 12)
    w = world(eng, entries=1, deadline_in=2, cutoff_after=600)
    after(eng, w["deadline"])
    r = tick(eng, replace(PREP, streams=("beta",)), snapshot_builder=builder())
    order = [s.step for s in r.steps if s.job_run_id]
    assert order.index("lock") < order.index("prepare_draft")
    with transaction(eng) as conn:
        st = conn.execute(sa.select(rounds.c.status).where(rounds.c.id == w["round"])).scalar_one()
    assert st in ("locked", "settling")  # lifecycle as before; never finalised early


def test_ops_status_json_and_cli_show_preparation(db, monkeypatch, capsys):
    import json

    from diski9 import cli

    eng, url = db
    place_clock(monkeypatch, eng, 12)
    tick(eng, PREP, snapshot_builder=builder())
    monkeypatch.setenv("DISKI9_APP_DATABASE_URL", url)
    monkeypatch.setenv("DISKI9_APP_ENVIRONMENT", "test")
    for k, v in {
        "DISKI9_JOBS_ENABLED": "1",
        "DISKI9_JOBS_STREAMS": "beta",
        "DISKI9_JOBS_PREPARE": "1",
        "DISKI9_JOBS_PREPARE_STREAMS": "beta",
    }.items():
        monkeypatch.setenv(k, v)  # fmt: skip
    assert cli.main(["ops", "status", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["preparation"]["state"] == "draft_ready" and doc["preparation"]["enabled"]
    assert cli.main(["ops", "status"]) == 0
    out = capsys.readouterr().out
    assert "draft READY for operator review" in out and "never publishes" in out
    assert cli.main(["jobs", "status", "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "draft preparation on (beta" in out and "scheduler.prepare_readiness" in out
    assert cli.main(["ops", "jobs", "--job", "scheduler.prepare_draft"]) == 0
    assert "scheduler.prepare_draft" in capsys.readouterr().out


def test_a_scheduled_draft_goes_live_only_through_round_publish(db, monkeypatch, capsys):
    """The operator's Stage E workflow stays authoritative: the readiness summary of
    the exact snapshot, the typed round code, and the approved fingerprint."""
    import diski9.challenge.roundsheet as rs
    import diski9.settlement_cli as sc
    from diski9 import cli

    eng, url = db
    week = place_clock(monkeypatch, eng, 12)
    tick(eng, PREP, snapshot_builder=builder())
    assert prepare.preparation_status(eng, PREP).state == "draft_ready"
    op = principal(eng, role="operator")
    with transaction(eng) as conn:
        now = db_now(conn)
        config = svc.round_config(conn, row(eng, week.code).id)  # the draft's own config
    snap = builder()(week.code, week.window_start, week.window_end, now, config)
    monkeypatch.setenv("DISKI9_APP_DATABASE_URL", url)
    monkeypatch.setenv("DISKI9_APP_ENVIRONMENT", "test")
    monkeypatch.setattr(rs, "build_live_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr(sc, "_principal", lambda engine, email, who="Operator": op)
    answers = iter(["no", week.code])
    monkeypatch.setattr(sc, "_ask", lambda prompt: next(answers))
    assert cli.main(["round", "publish", "--code", week.code]) == 0
    assert "Not confirmed; nothing changed." in capsys.readouterr().out
    assert row(eng, week.code).status == "draft"
    assert cli.main(["round", "publish", "--code", week.code]) == 0
    r = row(eng, week.code)
    assert r.status == "open"
    with transaction(eng) as conn:
        pub = conn.execute(sa.select(audit_log).where(audit_log.c.action == "round.publish")).one()
    assert pub.actor_user_id == op.user_id and pub.after["fingerprint"] == snap.fingerprint
