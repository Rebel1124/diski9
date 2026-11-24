"""Scenario A3 Checkpoint 4A: schedule resolution by validity interval, on PostgreSQL.

Every test uses its own synthetic schedule code (never changes ``weekend``), copied
from the weekend row valid now, with explicit validity intervals. What is proved
here is application behaviour: the half-open interval, safe refusal, one database
timestamp and one schedule identity per creation path. Database-level guarantees
(no overlaps or gaps, immutable referenced rows, validity checked at round
insertion, coordination with schedule migrations) belong to Checkpoint 4B and are
NOT claimed here."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pg_helpers import unique
from sqlalchemy import select, text
from svc_helpers import principal

from diski9.backend import dev_championship as dc
from diski9.backend.db import db_now, read_only, transaction
from diski9.backend.db.schema import rounds
from diski9.backend.devdata import dev_snapshot
from diski9.backend.jobs import prepare
from diski9.backend.services import rounds as svc
from diski9.backend.services import schedules
from diski9.backend.services.common import ValidationFailed
from diski9.challenge.config import A3_432_V1, BROAD60_432_V1

MICRO = timedelta(microseconds=1)


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def _code(prefix="s4a") -> str:
    return unique(prefix).replace("-", "")[:40]


def add_row(engine, code, version, active_from, active_to=None, *, cfg=None, buffer=None):
    """A synthetic schedule version copied from the weekend row valid now.

    A3 Checkpoint 4B (app_0008): every committed state must be contiguous with one
    open-ended row per code. So, as a real schedule change does, the new version is
    inserted open-ended and the previous open version is closed at its
    ``active_from`` in the same transaction. ``active_to`` documents the intended end
    of this version, which the next ``add_row`` sets; it must equal that version's
    ``active_from`` (every caller uses contiguous versions)."""
    with transaction(engine) as conn:
        base = schedules.current_schedule(conn, "weekend")
        conn.execute(
            text(
                "UPDATE app.round_schedules SET active_to = :af "
                "WHERE code = :code AND active_to IS NULL"
            ),
            {"code": code, "af": active_from},
        )
        conn.execute(
            text(
                "INSERT INTO app.round_schedules (code, version, timezone, eligible_competitions,"
                " window_rule, publish_rule, deadline_buffer_minutes, settle_cutoff_hours,"
                " correction_window_hours, config_version, rules_version, scoring_version,"
                " series_id, active_from, active_to)"
                " SELECT :code, :version, timezone, eligible_competitions, window_rule,"
                " publish_rule, :buffer, settle_cutoff_hours, correction_window_hours, :cfg,"
                " rules_version, scoring_version, series_id, :af, :at"
                " FROM app.round_schedules WHERE id = :base"
            ),
            {"code": code, "version": version, "af": active_from,
             "at": None, "cfg": cfg or base.config_version, "base": base.id,
             "buffer": base.deadline_buffer_minutes if buffer is None else buffer},
        )  # fmt: skip
        return conn.execute(
            text("SELECT id FROM app.round_schedules WHERE code = :c AND version = :v"),
            {"c": code, "v": version},
        ).scalar_one()


def now_db(engine) -> datetime:
    with transaction(engine) as conn:
        return db_now(conn)


def _draft(engine, op, code, **kw):
    t = now_db(engine)
    return svc.create_round(engine, op, code=unique("dev-s4a"), window_start=t,
                            window_end=t + timedelta(days=3), schedule_code=code,
                            development=True, **kw)  # fmt: skip


def _round_count(engine, code) -> int:
    with transaction(engine) as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM app.rounds r JOIN app.round_schedules s "
                "ON s.id = r.schedule_id WHERE s.code = :c"
            ),
            {"c": code},
        ).scalar_one()


# ------------------------------------------------------------------ the boundary
def test_half_open_boundary_before_at_and_after(engine):
    code = _code()
    boundary = datetime(2031, 3, 1, 12, 0, tzinfo=UTC)
    v1 = add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC), boundary)
    v2 = add_row(engine, code, 2, boundary, cfg=A3_432_V1.version)
    with read_only(engine) as conn:
        assert schedules.schedule_at(conn, code, boundary - MICRO).id == v1
        assert schedules.schedule_at(conn, code, boundary).id == v2  # [from, to)
        assert schedules.schedule_at(conn, code, boundary + MICRO).id == v2
        assert schedules.schedule_at(conn, code, boundary + timedelta(days=900)).id == v2
        assert schedules.current_schedule(conn, code).id == v1  # now is before 2031


def test_utc_offsets_and_session_time_zone_do_not_change_the_selection(engine):
    code = _code()
    boundary = datetime(2031, 3, 1, 0, 0, tzinfo=UTC)
    v1 = add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC), boundary)
    v2 = add_row(engine, code, 2, boundary)
    sast = timezone(timedelta(hours=2))
    nz = timezone(timedelta(hours=13))
    with read_only(engine) as conn:
        conn.execute(text("SET LOCAL TIME ZONE 'Pacific/Auckland'"))
        # the same instants written with other offsets
        assert schedules.schedule_at(conn, code, datetime(2031, 3, 1, 1, 59, 59, 999999,
                                                          tzinfo=sast)).id == v1  # fmt: skip
        assert schedules.schedule_at(conn, code, datetime(2031, 3, 1, 2, 0, tzinfo=sast)).id == v2
        assert schedules.schedule_at(conn, code, datetime(2031, 3, 1, 13, 0, tzinfo=nz)).id == v2


def test_naive_instants_are_refused(engine):
    with read_only(engine) as conn, pytest.raises(ValidationFailed, match="timezone-aware"):
        schedules.schedule_at(conn, "weekend", datetime(2031, 3, 1, 12, 0))


# ------------------------------------------------------------------ safe refusal
def test_no_valid_schedule_refuses_creation_and_writes_nothing(engine, op):
    code = _code()
    add_row(engine, code, 1, datetime(2040, 1, 1, tzinfo=UTC))  # only a future row
    with read_only(engine) as conn, pytest.raises(schedules.ScheduleUnavailable, match="No"):
        schedules.current_schedule(conn, code)
    with pytest.raises(schedules.ScheduleUnavailable):
        _draft(engine, op, code)
    assert _round_count(engine, code) == 0


def _raw_insert(conn, code, version, active_from, active_to=None):
    conn.execute(
        text(
            "INSERT INTO app.round_schedules (code, version, timezone, eligible_competitions,"
            " window_rule, publish_rule, deadline_buffer_minutes, settle_cutoff_hours,"
            " correction_window_hours, config_version, rules_version, scoring_version,"
            " series_id, active_from, active_to)"
            " SELECT :code, :v, timezone, eligible_competitions, window_rule, publish_rule,"
            " deadline_buffer_minutes, settle_cutoff_hours, correction_window_hours,"
            " config_version, rules_version, scoring_version, series_id, :af, :at"
            " FROM app.round_schedules WHERE code = 'weekend' AND active_to IS NULL"
        ),
        {"code": code, "v": version, "af": active_from, "at": active_to},
    )


def test_overlapping_versions_are_refused_by_the_database(engine, op):
    """4A refused overlaps at resolution; since app_0008 they can no longer exist (the
    exclusion constraint), so creation can never meet them."""
    from sqlalchemy.exc import IntegrityError

    code = _code()
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    with pytest.raises(IntegrityError), transaction(engine) as conn:  # both open-ended
        _raw_insert(conn, code, 2, datetime(2021, 1, 1, tzinfo=UTC))
    with read_only(engine) as conn:
        assert schedules.current_schedule(conn, code).version == 1  # unchanged, never v2
    assert _draft(engine, op, code).status == "draft"


def test_a_gap_between_versions_is_refused_by_the_database(engine):
    """4A refused resolution inside a gap; since app_0008 a gap cannot commit."""
    from sqlalchemy.exc import IntegrityError

    code = _code()
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    with pytest.raises(IntegrityError, match="must start exactly"), transaction(engine) as conn:
        conn.execute(text("UPDATE app.round_schedules SET active_to = '2030-01-01Z' "
                          "WHERE code = :c"), {"c": code})  # fmt: skip
        _raw_insert(conn, code, 2, datetime(2030, 1, 2, tzinfo=UTC))
    with read_only(engine) as conn:  # rolled back: v1 open-ended again, no v2
        assert schedules.schedule_at(conn, code, datetime(2030, 1, 1, 12, tzinfo=UTC)).version == 1


# ------------------------------------------------------------------ one timestamp, one row
def test_round_is_bound_to_the_row_valid_at_its_created_at(engine, op):
    code = _code()
    sid = add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    v = _draft(engine, op, code)
    with transaction(engine) as conn:
        r = conn.execute(
            select(rounds.c.schedule_id, rounds.c.created_at).where(rounds.c.id == v.id)
        ).one()
        assert r.schedule_id == sid
        assert schedules.schedule_at(conn, code, r.created_at).id == sid


def test_a_real_boundary_passing_changes_the_binding_of_new_rounds_only(engine, op):
    code = _code()
    t = now_db(engine)
    boundary = t + timedelta(seconds=2)
    v1 = add_row(engine, code, 1, t - timedelta(days=1), boundary, cfg=BROAD60_432_V1.version)
    v2 = add_row(engine, code, 2, boundary, cfg=A3_432_V1.version)
    before = _draft(engine, op, code)
    while now_db(engine) < boundary + timedelta(milliseconds=50):
        time.sleep(0.1)
    after = _draft(engine, op, code)
    with transaction(engine) as conn:
        ids = dict(conn.execute(select(rounds.c.id, rounds.c.schedule_id)
                                .where(rounds.c.id.in_([before.id, after.id]))).all())  # fmt: skip
        assert ids[before.id] == v1 and ids[after.id] == v2
        # the pre-boundary draft keeps its own configuration after the boundary
        assert svc.round_config(conn, before.id) is BROAD60_432_V1
        assert svc.round_config(conn, after.id) is A3_432_V1
        config = svc.round_config(conn, before.id)
    # and publishes under it after the boundary
    t2 = now_db(engine)
    snap = dev_snapshot(before.code, t2, t2 + timedelta(hours=3), config=config)
    view = svc.publish_round(engine, op, before.id, snap, source="development")
    assert view.config_version == BROAD60_432_V1.version


def test_expected_schedule_mismatch_refuses_and_writes_nothing(engine, op):
    code = _code()
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    with pytest.raises(svc.ScheduleChanged, match="Plan again"):
        _draft(engine, op, code, expected_schedule_id=-1)
    assert _round_count(engine, code) == 0
    with read_only(engine) as conn:
        sid = schedules.current_schedule(conn, code).id
    assert _draft(engine, op, code, expected_schedule_id=sid).status == "draft"


def test_planned_window_carries_the_schedule_identity(engine):
    code = _code()
    sid = add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    w = svc.plan_window(engine, 2031, 11, code)
    assert w.schedule_id == sid and w.schedule_version == 1
    assert (w.start, w.end) == svc.schedule_window(engine, 2031, 11, code)


def test_scheduled_draft_uses_window_series_and_identity_of_one_row(engine, monkeypatch):
    code = _code("s4asch")
    sid = add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    monkeypatch.setattr(svc, "SCHEDULED_SCHEDULE", code)
    res = svc.create_scheduled_draft(engine, svc.SYSTEM, iso_year=2033, iso_week=7)
    assert res.created
    with transaction(engine) as conn:
        row = conn.execute(select(rounds.c.schedule_id, rounds.c.created_at)
                           .where(rounds.c.id == res.round.id)).one()  # fmt: skip
        assert row.schedule_id == sid
        assert schedules.schedule_at(conn, code, row.created_at).id == sid
    assert (res.round.window_start_at, res.round.window_end_at) == svc.schedule_window(
        engine, 2033, 7, code
    )


def test_scheduled_draft_refuses_when_no_schedule_is_valid(engine, monkeypatch):
    code = _code("s4asch")
    add_row(engine, code, 1, datetime(2040, 1, 1, tzinfo=UTC))
    monkeypatch.setattr(svc, "SCHEDULED_SCHEDULE", code)
    with pytest.raises(schedules.ScheduleUnavailable):
        svc.create_scheduled_draft(engine, svc.SYSTEM, iso_year=2033, iso_week=8)
    assert _round_count(engine, code) == 0


# ------------------------------------------------------------------ dev championship
def test_dev_championship_buffer_comes_from_the_row_it_binds_to(engine, monkeypatch):
    """Before 4A the buffer came from the first schedule row in the table (any code,
    any version). The bound row's buffer must be used."""
    code = _code("s4adev")
    t = now_db(engine)
    add_row(engine, code, 1, t - timedelta(days=2), t - timedelta(days=1), buffer=15)
    sid = add_row(engine, code, 2, t - timedelta(days=1), buffer=7, cfg=BROAD60_432_V1.version)
    monkeypatch.setattr(dc, "DEV_SCHEDULE", code)
    now, sched, config, first = dc.opening_parameters(engine, 300)
    assert sched.id == sid and sched.deadline_buffer_minutes == 7
    assert first == now + timedelta(seconds=300, minutes=7)
    assert config is BROAD60_432_V1
    with transaction(engine) as conn:  # the first row in the table differs (15 min)
        first_row = conn.execute(text("SELECT deadline_buffer_minutes FROM app.round_schedules "
                                      "ORDER BY id LIMIT 1")).scalar_one()  # fmt: skip
    assert first_row == 15


# ------------------------------------------------------------------ inspection
def test_schedule_report_lists_validity_configs_and_selection(engine):
    code = _code()
    boundary = datetime(2031, 3, 1, tzinfo=UTC)
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC), boundary,
            cfg=BROAD60_432_V1.version)  # fmt: skip
    add_row(engine, code, 2, boundary, cfg="not-registered-v9")
    with read_only(engine) as conn:
        rep = schedules.schedule_report(conn, code, boundary)
    c = rep["codes"][code]
    v1, v2 = c["versions"]
    assert v1["valid_now"] and not v2["valid_now"]
    assert v1["config_registered"] and v1["config_fingerprint"] == BROAD60_432_V1.fingerprint()
    assert not v2["config_registered"] and v2["config_error"]
    assert c["selected_now"]["version"] == 1 and c["selected_at"]["version"] == 2
    text_ = "\n".join(schedules.report_lines(rep))
    assert "NOT REGISTERED" in text_ and "<- valid now" in text_ and "read-only" in text_
    with read_only(engine) as conn:
        gap = schedules.schedule_report(conn, code, datetime(2019, 1, 1, tzinfo=UTC))
    assert gap["codes"][code]["selected_at"]["problem"]


# ------------------------------------------------------------------ prepare reporting
def _week(create_at, target):
    return prepare.Week(2031, 11, "x", create_at - timedelta(days=3), create_at, target,
                        target, create_at)  # fmt: skip


def test_prepare_binding_explains_a_pre_activation_draft(engine, monkeypatch):
    code = _code("s4aprep")
    t = now_db(engine)
    boundary = t + timedelta(days=2)
    v1 = add_row(engine, code, 1, t - timedelta(days=1), boundary, cfg=BROAD60_432_V1.version)
    add_row(engine, code, 2, boundary, cfg=A3_432_V1.version)
    monkeypatch.setattr(svc, "SCHEDULED_SCHEDULE", code)
    week = _week(t + timedelta(days=1), t + timedelta(days=3))  # due before, target after
    with read_only(engine) as conn:
        b = prepare.schedule_binding(conn, week, None, t)
        assert b.bound.id == v1 and b.later.version == 2
        lines = "\n".join(b.lines(week))
        assert "applies when the draft is created" in lines
        assert "takes effect at" in lines and "after this draft is due" in lines
        # an existing draft bound to v1 keeps it and publishes under the original rules
        row = type("R", (), {"schedule_id": v1, "config_version": None})()
        b2 = prepare.schedule_binding(conn, week, row, t)
        assert "will publish under the original rules" in "\n".join(b2.lines(week))
        # once published, the configuration is frozen: no note
        pub = type("R", (), {"schedule_id": v1, "config_version": BROAD60_432_V1.version})()
        b3 = prepare.schedule_binding(conn, week, pub, t)
        out = "\n".join(b3.lines(week))
        assert "frozen at publication" in out and "note" not in out


def test_prepare_binding_without_boundary_has_no_note(engine, monkeypatch):
    code = _code("s4aprep")
    t = now_db(engine)
    add_row(engine, code, 1, t - timedelta(days=1), cfg=BROAD60_432_V1.version)
    monkeypatch.setattr(svc, "SCHEDULED_SCHEDULE", code)
    week = _week(t + timedelta(days=1), t + timedelta(days=3))
    with read_only(engine) as conn:
        b = prepare.schedule_binding(conn, week, None, t)
    assert b.later is None and "note" not in "\n".join(b.lines(week))
    assert b.bound.config_version == BROAD60_432_V1.version


# ------------------------------------------------------------------ app follows the schedule
def test_backend_schedule_config_follows_the_boundary_exactly(engine):
    from diski9.app.challenge.persist import Backend

    code = _code("s4aapp")
    t = now_db(engine)
    boundary = t + timedelta(seconds=1.5)
    add_row(engine, code, 1, t - timedelta(days=1), boundary, cfg=BROAD60_432_V1.version)
    add_row(engine, code, 2, boundary, cfg=A3_432_V1.version)
    be = Backend(engine)
    assert be.schedule_config(code) is BROAD60_432_V1  # cached until the row's active_to
    while now_db(engine) < boundary + timedelta(milliseconds=50):
        time.sleep(0.1)
    assert be.schedule_config(code) is A3_432_V1  # not served from the cache


def test_backend_schedule_config_never_falls_back(engine):
    from sqlalchemy import create_engine

    from diski9.app.challenge.persist import Backend
    from diski9.app.challenge.service import ScheduleConfigUnavailable

    code = _code("s4aapp")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC), cfg="not-registered-v9")
    with pytest.raises(ScheduleConfigUnavailable):
        Backend(engine).schedule_config(code)  # unregistered: no default instead
    with pytest.raises(ScheduleConfigUnavailable):
        Backend(engine).schedule_config(_code("s4anone"))  # no schedule at all
    down = create_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")
    with pytest.raises(ScheduleConfigUnavailable):
        Backend(down).schedule_config()  # database unreachable


def test_round_schedules_command_is_read_only_and_refuses_naive_instants(pg_url):
    import json
    import os
    import subprocess
    import sys

    env = dict(os.environ, DISKI9_APP_DATABASE_URL=pg_url, DISKI9_APP_ENVIRONMENT="test")
    cmd = [sys.executable, "-m", "diski9.cli", "round", "schedules", "--schedule", "weekend"]
    out = subprocess.run([*cmd, "--json", "--at", "2026-11-19T12:00:00Z"], env=env,
                         capture_output=True, text=True, timeout=120)  # fmt: skip
    assert out.returncode == 0, out.stderr
    rep = json.loads(out.stdout)
    assert rep["codes"]["weekend"]["selected_now"]["config_version"] == "a3-432-v1"  # app_0009
    assert rep["codes"]["weekend"]["selected_at"]["version"] == 1
    bad = subprocess.run([*cmd, "--at", "2026-11-19T12:00:00"], env=env,
                         capture_output=True, text=True, timeout=120)  # fmt: skip
    assert bad.returncode == 2 and "UTC offset" in (bad.stderr + bad.stdout)
