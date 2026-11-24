"""Scenario A3 Checkpoint 4B: database schedule safeguards (migration app_0008).

Direct SQL against PostgreSQL (the owner role unless stated), synthetic schedule codes
only (``weekend`` is never changed), separate connections and threads for the
concurrency cases. Migration upgrade, refusal and downgrade run in a separate
database (``fresh_url``)."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from pg_helpers import confirm, make_round, make_user, unique
from sqlalchemy import create_engine, pool, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from svc_helpers import principal, publish_dev
from test_backend_schedule_resolution import _code, _draft, add_row, now_db

from diski9.backend.db import BackendDatabaseSettings, make_app_engine, migrate, transaction
from diski9.backend.services import schedules

MICRO = timedelta(microseconds=1)
OBJECTS = {
    "constraint": "round_schedules_no_overlap",
    "index": "round_schedules_one_open",
    "triggers": {
        "round_schedules_write_lock",
        "round_schedules_row_guard",
        "round_schedules_contiguous",
        "rounds_schedule_valid",
        "rounds_identity_immutable",
    },  # fmt: skip
}


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def _eng(url):
    return create_engine(url, poolclass=pool.NullPool)


def _installed(conn) -> dict:
    trig = set(conn.execute(text(
        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN "
        "('app.round_schedules'::regclass, 'app.rounds'::regclass)")).scalars())  # fmt: skip
    return {
        "constraint": conn.execute(
            text("SELECT count(*) FROM pg_constraint WHERE conname = 'round_schedules_no_overlap'")
        ).scalar_one(),  # fmt: skip
        "index": conn.execute(
            text("SELECT count(*) FROM pg_indexes WHERE indexname = 'round_schedules_one_open'")
        ).scalar_one(),  # fmt: skip
        "triggers": trig & OBJECTS["triggers"],
        "btree_gist": conn.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")
        ).scalar_one(),
        "runtime_write": conn.execute(
            text(
                "SELECT has_table_privilege('diski9_app', 'app.round_schedules', 'INSERT') OR "
                "has_table_privilege('diski9_app', 'app.round_schedules', 'UPDATE') OR "
                "has_table_privilege('diski9_app', 'app.round_schedules', 'DELETE')"
            )
        ).scalar_one(),
        "runtime_read": conn.execute(
            text("SELECT has_table_privilege('diski9_app', 'app.round_schedules', 'SELECT')")
        ).scalar_one(),  # fmt: skip
    }


def _snapshot_data(conn):
    return (
        conn.execute(text("SELECT * FROM app.round_schedules ORDER BY id")).all(),
        conn.execute(
            text("SELECT id, code, schedule_id, created_at FROM app.rounds ORDER BY id")
        ).all(),  # fmt: skip
    )


# ===================================================================== migration
def test_fresh_installation_installs_every_safeguard(fresh_url):
    migrate.upgrade(fresh_url)
    assert migrate.current(fresh_url) == "app_0008"
    with _eng(fresh_url).connect() as conn:
        got = _installed(conn)
    assert got["constraint"] == 1 and got["index"] == 1 and got["btree_gist"] == 1
    assert got["triggers"] == OBJECTS["triggers"]
    assert got["runtime_read"] and not got["runtime_write"]


def test_upgrade_from_app_0007_with_rounds_keeps_data_and_downgrade_restores_it(fresh_url):
    migrate.upgrade(fresh_url, "app_0007")
    eng = _eng(fresh_url)
    with eng.begin() as conn:
        uid = make_user(conn)
        rid, snap_id, fids = make_round(conn)
        confirm(conn, rid, snap_id, fids, uid)
        make_round(conn)
    with eng.connect() as conn:
        before = _snapshot_data(conn)
        assert _installed(conn)["runtime_write"]  # app_0007: projection privileges
    migrate.upgrade(fresh_url)
    with eng.connect() as conn:
        assert _snapshot_data(conn) == before  # safeguards only: no data touched
        assert _installed(conn)["triggers"] == OBJECTS["triggers"]
    migrate.downgrade(fresh_url, "app_0007")
    with eng.connect() as conn:
        got = _installed(conn)
        assert _snapshot_data(conn) == before
    assert got["triggers"] == set() and got["constraint"] == 0 and got["index"] == 0
    assert got["runtime_write"] and got["runtime_read"]  # prior privileges restored
    assert got["btree_gist"] == 1  # the shared extension is never dropped
    migrate.upgrade(fresh_url)  # re-upgrade
    with eng.connect() as conn:
        assert _installed(conn)["triggers"] == OBJECTS["triggers"]
        assert _snapshot_data(conn) == before
    eng.dispose()


FUNCTIONS = (
    "require_read_committed",
    "schedule_write_lock",
    "schedule_read_lock",
    "round_schedules_write_lock",
    "check_schedule_contiguity",
    "round_schedules_contiguity",
    "round_schedules_row_guard",
    "round_schedule_valid",
)


def _schema_state(conn) -> dict:
    """Everything app_0008 could add, plus the round and schedule data."""
    got = _installed(conn)
    got["functions"] = conn.execute(text(
        "SELECT count(*) FROM pg_proc WHERE pronamespace = 'app'::regnamespace "
        "AND proname = ANY(:f)"), {"f": list(FUNCTIONS)}).scalar_one()  # fmt: skip
    got["data"] = _snapshot_data(conn)
    return got


def _refused(url, match, before=None):
    with pytest.raises(DBAPIError, match="app_0008 upgrade refused") as exc:
        migrate.upgrade(url)
    assert match in str(exc.value)
    assert migrate.current(url) == "app_0007"
    with _eng(url).connect() as conn:  # nothing installed
        got = _schema_state(conn)
    assert got["constraint"] == 0 and got["triggers"] == set() and got["runtime_write"]
    assert got["functions"] == 0 and got["index"] == 0
    if before is not None:  # schema and data exactly as before the attempt
        assert got == before


def test_upgrade_refuses_inconsistent_history_and_repairs_nothing(fresh_url):
    migrate.upgrade(fresh_url, "app_0007")
    eng = _eng(fresh_url)
    copy = ("INSERT INTO app.round_schedules (code, version, timezone, eligible_competitions,"
            " window_rule, publish_rule, deadline_buffer_minutes, settle_cutoff_hours,"
            " correction_window_hours, config_version, rules_version, scoring_version,"
            " series_id, active_from, active_to) SELECT 'audit', :v, timezone,"
            " eligible_competitions, window_rule, publish_rule, deadline_buffer_minutes,"
            " settle_cutoff_hours, correction_window_hours, config_version, rules_version,"
            " scoring_version, series_id, :af, :at FROM app.round_schedules"
            " WHERE code = 'weekend' AND active_to IS NULL")  # fmt: skip
    # 1. overlapping versions
    with eng.begin() as conn:
        conn.execute(text(copy), {"v": 1, "af": "2026-01-01Z", "at": None})
        conn.execute(text(copy), {"v": 2, "af": "2026-06-01Z", "at": None})
    with eng.connect() as conn:
        before = _schema_state(conn)
    assert before["btree_gist"] == 0  # a fresh database: the refusal must not add it
    _refused(fresh_url, "overlapping versions", before)
    with eng.begin() as conn:
        rows = conn.execute(text("SELECT count(*) FROM app.round_schedules WHERE code='audit'"))
        assert rows.scalar_one() == 2  # not repaired
        conn.execute(text("DELETE FROM app.round_schedules WHERE code = 'audit'"))
    # 2. a gap (and a closed highest version)
    with eng.begin() as conn:
        conn.execute(text(copy), {"v": 1, "af": "2026-01-01Z", "at": "2026-02-01Z"})
        conn.execute(text(copy), {"v": 2, "af": "2026-03-01Z", "at": "2026-04-01Z"})
    _refused(fresh_url, "non-contiguous versions")
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM app.round_schedules WHERE code = 'audit'"))
    # 3. a round created before its schedule row was valid (e.g. before 19 Nov)
    with eng.begin() as conn:
        rid = conn.execute(text(
            "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, "
            "window_end_at, created_at) SELECT 'early', id, series_id, now(), now() + "
            "interval '1 day', '2026-11-01T00:00:00Z' FROM app.round_schedules "
            "WHERE code = 'weekend' AND active_to IS NULL RETURNING id")).scalar_one()  # fmt: skip
    _refused(fresh_url, "rounds outside their schedule validity")
    with eng.begin() as conn:  # the round is untouched (no rebinding, no new timestamp)
        assert str(conn.execute(text("SELECT created_at FROM app.rounds WHERE id = :r"),
                                {"r": rid}).scalar_one().isoformat()).startswith("2026-11-01")  # fmt: skip
        conn.execute(text("DELETE FROM app.rounds WHERE id = :r"), {"r": rid})
    migrate.upgrade(fresh_url)  # consistent again: installs
    assert migrate.current(fresh_url) == "app_0008"
    eng.dispose()


# ===================================================================== direct SQL guards
def _insert(conn, code, version, active_from, active_to=None):
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


def _sid(conn, code, version):
    return conn.execute(text("SELECT id FROM app.round_schedules WHERE code=:c AND version=:v"),
                        {"c": code, "v": version}).scalar_one()  # fmt: skip


def test_highest_version_must_stay_open_ended(engine):
    code = _code("s4b")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    with pytest.raises(IntegrityError, match="must be open-ended"), transaction(engine) as conn:
        conn.execute(text("UPDATE app.round_schedules SET active_to = '2035-01-01Z' "
                          "WHERE code = :c"), {"c": code})  # fmt: skip
    with pytest.raises(IntegrityError, match="must be open-ended"), transaction(engine) as conn:
        _insert(conn, code + "x", 1, "2020-01-01Z", "2030-01-01Z")  # a closed-only code


def test_versions_must_be_chronological(engine):
    code = _code("s4b")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    with pytest.raises(IntegrityError, match="must start exactly"), transaction(engine) as conn:
        conn.execute(text("UPDATE app.round_schedules SET active_to = '2030-01-01Z' "
                          "WHERE code = :c"), {"c": code})  # fmt: skip
        _insert(conn, code, 2, "2010-01-01Z", "2020-01-01Z")  # earlier, not overlapping
        _insert(conn, code, 3, "2030-01-01Z")


def test_one_open_ended_row_per_code_is_indexed(engine):
    with transaction(engine) as conn:
        idx = conn.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'round_schedules_one_open'"
        )).scalar_one()  # fmt: skip
    assert "UNIQUE" in idx and "WHERE (active_to IS NULL)" in idx


def test_referenced_rows_are_protected_with_a_strict_half_open_close(engine, op):
    code = _code("s4b")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    r = _draft(engine, op, code)
    with transaction(engine) as conn:
        created = conn.execute(text("SELECT created_at FROM app.rounds WHERE id = :r"),
                               {"r": r.id}).scalar_one()  # fmt: skip
        v1 = _sid(conn, code, 1)
    with pytest.raises(DBAPIError, match="can never be deleted"), transaction(engine) as conn:
        conn.execute(text("DELETE FROM app.round_schedules WHERE id = :i"), {"i": v1})
    with pytest.raises(DBAPIError, match="only its closing time"), transaction(engine) as conn:
        conn.execute(text("UPDATE app.round_schedules SET deadline_buffer_minutes = 99 "
                          "WHERE id = :i"), {"i": v1})  # fmt: skip
    # closing exactly at the round's created_at is refused (half-open: it would exclude it)
    with pytest.raises(DBAPIError, match="strictly later"), transaction(engine) as conn:
        conn.execute(text("UPDATE app.round_schedules SET active_to = :t WHERE id = :i"),
                     {"t": created, "i": v1})  # fmt: skip
        _insert(conn, code, 2, created)
    # one microsecond later is allowed, once
    with transaction(engine) as conn:
        conn.execute(text("UPDATE app.round_schedules SET active_to = :t WHERE id = :i"),
                     {"t": created + MICRO, "i": v1})  # fmt: skip
        _insert(conn, code, 2, created + MICRO)
    with pytest.raises(DBAPIError, match="set once"), transaction(engine) as conn:
        conn.execute(text("UPDATE app.round_schedules SET active_to = active_to + interval "
                          "'1 day' WHERE id = :i"), {"i": v1})  # fmt: skip
    with (
        pytest.raises(DBAPIError, match="only after every later version"),
        transaction(engine) as conn,
    ):
        conn.execute(text("UPDATE app.round_schedules SET active_to = NULL WHERE id = :i"),
                     {"i": v1})  # fmt: skip
    # undo of an unused activation: remove the later version, then reopen
    with transaction(engine) as conn:
        conn.execute(text("DELETE FROM app.round_schedules WHERE code = :c AND version = 2"),
                     {"c": code})  # fmt: skip
        conn.execute(text("UPDATE app.round_schedules SET active_to = NULL WHERE id = :i"),
                     {"i": v1})  # fmt: skip
    with transaction(engine) as conn:
        assert schedules.current_schedule(conn, code).id == v1


def test_round_insertion_requires_validity_at_created_at(engine):
    code = _code("s4b")
    b = datetime(2031, 6, 1, 12, 0, tzinfo=UTC)
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC), b)
    add_row(engine, code, 2, b)
    sql = text(
        "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, window_end_at,"
        " created_at, is_development) SELECT :rc, id, series_id, now(), now() + interval"
        " '1 day', :ca, true FROM app.round_schedules WHERE code = :c AND version = :v"
    )

    def ins(v, at):
        with transaction(engine) as conn:
            conn.execute(sql, {"rc": unique("dev-s4b"), "ca": at, "c": code, "v": v})

    ins(1, b - MICRO)  # last instant of v1
    ins(2, b)  # first instant of v2
    for v, at in ((1, b), (2, b - MICRO), (1, datetime(2019, 1, 1, tzinfo=UTC))):
        with pytest.raises(IntegrityError, match="not valid at the round"):
            ins(v, at)
    # the default created_at (transaction time, 2026) is valid only for v1
    with transaction(engine) as conn:
        conn.execute(text(
            "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, window_end_at,"
            " is_development) SELECT :rc, id, series_id, now(), now() + interval '1 day', true "
            "FROM app.round_schedules WHERE code = :c AND version = 1"),
            {"rc": unique("dev-s4b"), "c": code})  # fmt: skip
    with pytest.raises(IntegrityError), transaction(engine) as conn:
        conn.execute(text(
            "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, window_end_at,"
            " is_development) SELECT :rc, id, series_id, now(), now() + interval '1 day', true "
            "FROM app.round_schedules WHERE code = :c AND version = 2"),
            {"rc": unique("dev-s4b"), "c": code})  # fmt: skip


def test_round_schedule_id_and_created_at_are_immutable(engine, op):
    code = _code("s4b")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    r = _draft(engine, op, code)
    for sql in ("UPDATE app.rounds SET created_at = created_at - interval '1 second' "
                "WHERE id = :r",
                "UPDATE app.rounds SET schedule_id = (SELECT id FROM app.round_schedules "
                "WHERE code = 'weekend' AND active_to IS NULL) WHERE id = :r"):  # fmt: skip
        with pytest.raises(DBAPIError, match="set once"), transaction(engine) as conn:
            conn.execute(text(sql), {"r": r.id})


@pytest.mark.parametrize("level", ["REPEATABLE READ", "SERIALIZABLE"])
def test_checks_refuse_other_isolation_levels(engine, level):
    code = _code("s4b")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    with pytest.raises(DBAPIError, match="READ COMMITTED"), engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET TRANSACTION ISOLATION LEVEL {level}"))
        conn.execute(text(
            "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, "
            "window_end_at, is_development) SELECT :rc, id, series_id, now(), now() + "
            "interval '1 day', true FROM app.round_schedules WHERE code = :c"),
            {"rc": unique("dev-s4b"), "c": code})  # fmt: skip
    with pytest.raises(DBAPIError, match="READ COMMITTED"), engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET TRANSACTION ISOLATION LEVEL {level}"))
        conn.execute(text("UPDATE app.round_schedules SET deadline_buffer_minutes = 20 "
                          "WHERE code = :c"), {"c": code})  # fmt: skip


# ===================================================================== runtime role
@pytest.fixture
def app_engine(pg_url):
    from sqlalchemy import event

    eng = make_app_engine(BackendDatabaseSettings(environment="test"), url=pg_url)

    @event.listens_for(eng, "begin")
    def _as_runtime_role(conn):
        conn.exec_driver_sql("SET LOCAL ROLE diski9_app")

    yield eng
    eng.dispose()


def test_runtime_role_reads_but_cannot_write_schedules_and_still_creates_rounds(
    engine, app_engine, op
):
    for sql in ("UPDATE app.round_schedules SET deadline_buffer_minutes = 15 WHERE false",
                "DELETE FROM app.round_schedules WHERE false",
                "INSERT INTO app.round_schedules (code) VALUES ('x')"):  # fmt: skip
        with pytest.raises(DBAPIError, match="permission denied"), transaction(app_engine) as conn:
            conn.execute(text(sql))
    with transaction(app_engine) as conn:
        assert conn.execute(text("SELECT current_user")).scalar() == "diski9_app"
        assert schedules.current_schedule(conn, "weekend").active_to is None
    view, _ = publish_dev(app_engine, op)  # create_round + publish as the runtime role
    assert view.status == "open"


# ===================================================================== concurrency
def _bg(fn):
    out = {}

    def run():
        try:
            out["result"] = fn()
        except Exception as exc:  # noqa: BLE001 - asserted by the caller
            out["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    return t, out


def _waiting_for_advisory(engine) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
        )).scalar_one())  # fmt: skip


def _wait_until_blocked(engine, timeout=1.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _waiting_for_advisory(engine):
            return True
        time.sleep(0.02)
    return False


def test_creation_that_starts_before_a_schedule_change_waits_and_binds_correctly(engine, op):
    """The creator's transaction (and so created_at) starts after the change began but
    before it commits; it waits for the lock and then binds to the new version."""
    code = _code("s4bc")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    writer = engine.connect()
    tx = writer.begin()
    writer.execute(text("SELECT app.schedule_write_lock()"))
    boundary = writer.execute(text("SELECT clock_timestamp()")).scalar_one()
    writer.execute(text("UPDATE app.round_schedules SET active_to = :b WHERE code = :c"),
                   {"b": boundary, "c": code})  # fmt: skip
    _insert(writer, code, 2, boundary)
    t, out = _bg(lambda: _draft(engine, op, code))  # starts after `boundary`, then blocks
    assert _wait_until_blocked(engine)
    tx.commit()
    writer.close()
    t.join(10)
    assert "error" not in out, out.get("error")
    with transaction(engine) as conn:
        row = conn.execute(text("SELECT r.created_at, s.version FROM app.rounds r JOIN "
                                "app.round_schedules s ON s.id = r.schedule_id WHERE r.id = :r"),
                           {"r": out["result"].id}).one()  # fmt: skip
    assert row.created_at >= boundary and row.version == 2


def test_a_stale_binding_cannot_commit_after_a_schedule_change(engine):
    """A direct-SQL creator reads v1 before the change, then inserts after it commits:
    its created_at (fixed at its start) is after the new boundary, so the insert
    trigger (shared lock, fresh snapshot) refuses."""
    code = _code("s4bc")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    creator = engine.connect()
    ctx = creator.begin()
    t0 = creator.execute(text("SELECT now()")).scalar_one()
    v1 = _sid(creator, code, 1)  # read without the lock: v1 is valid
    with transaction(engine) as conn:  # the change commits with a boundary <= t0
        conn.execute(text("SELECT app.schedule_write_lock()"))
        conn.execute(text("UPDATE app.round_schedules SET active_to = :b WHERE code = :c"),
                     {"b": t0, "c": code})  # fmt: skip
        _insert(conn, code, 2, t0)
    with pytest.raises(IntegrityError, match="not valid at the round"):
        creator.execute(text(
            "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, "
            "window_end_at, is_development) SELECT :rc, id, series_id, now(), now() + "
            "interval '1 day', true FROM app.round_schedules WHERE id = :s"),
            {"rc": unique("dev-s4bc"), "s": v1})  # fmt: skip
    ctx.rollback()
    creator.close()


def test_a_schedule_change_waits_for_an_open_creation_and_respects_it(engine):
    """A round inserted (uncommitted, shared lock held) before the change: the writer
    waits, then sees the committed round and refuses a close at or before it."""
    code = _code("s4bc")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    creator = engine.connect()
    ctx = creator.begin()
    created = creator.execute(text(
        "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, window_end_at,"
        " is_development) SELECT :rc, id, series_id, now(), now() + interval '1 day', true "
        "FROM app.round_schedules WHERE code = :c RETURNING created_at"),
        {"rc": unique("dev-s4bc"), "c": code}).scalar_one()  # fmt: skip

    def change():
        with transaction(engine) as conn:
            conn.execute(text("SELECT app.schedule_write_lock()"))
            conn.execute(text("UPDATE app.round_schedules SET active_to = :b WHERE code = :c"),
                         {"b": created, "c": code})  # fmt: skip
            _insert(conn, code, 2, created)

    t, out = _bg(change)
    assert _wait_until_blocked(engine)  # the writer waits for the creator
    ctx.commit()
    creator.close()
    t.join(10)
    assert isinstance(out.get("error"), DBAPIError) and "strictly later" in str(out["error"])


def test_concurrent_overlapping_versions_cannot_both_commit(engine):
    code = _code("s4bc")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    gate = threading.Barrier(2)

    def activate(version, start):
        def run():
            with transaction(engine) as conn:
                gate.wait()
                # no explicit lock first: the statement trigger still serialises writers
                conn.execute(text("UPDATE app.round_schedules SET active_to = :b WHERE "
                                  "code = :c AND active_to IS NULL"),
                             {"b": start, "c": code})  # fmt: skip
                _insert(conn, code, version, start)
                time.sleep(0.2)

        return run

    a = _bg(activate(2, datetime(2032, 1, 1, tzinfo=UTC)))
    b = _bg(activate(3, datetime(2033, 1, 1, tzinfo=UTC)))
    for t, _ in (a, b):
        t.join(15)
    errors = [o for _, o in (a, b) if "error" in o]
    assert len(errors) == 1, (a[1], b[1])
    with transaction(engine) as conn:
        rows = conn.execute(text("SELECT version, active_from, active_to FROM "
                                 "app.round_schedules WHERE code = :c ORDER BY version"),
                            {"c": code}).all()  # fmt: skip
    assert len(rows) == 2 and rows[0].active_to == rows[1].active_from
    assert rows[1].active_to is None  # contiguous, exactly one open-ended row


def test_concurrent_gap_validation_is_serialised(engine):
    """Two writers each leave a valid state on their own; combined they would leave a
    gap. The deferred check runs under the exclusive lock with a fresh snapshot, so the
    second sees the first's commit and fails."""
    code = _code("s4bc")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    add_row(engine, code, 2, datetime(2030, 1, 1, tzinfo=UTC))
    gate = threading.Barrier(2)

    def drop_v2_reopen_v1():
        with transaction(engine) as conn:
            gate.wait()
            conn.execute(text("SELECT app.schedule_write_lock()"))
            conn.execute(text("DELETE FROM app.round_schedules WHERE code = :c AND version = 2"),
                         {"c": code})  # fmt: skip
            conn.execute(text("UPDATE app.round_schedules SET active_to = NULL WHERE code = :c "
                              "AND version = 1"), {"c": code})  # fmt: skip
            time.sleep(0.2)

    def add_v3():
        with transaction(engine) as conn:
            gate.wait()
            time.sleep(0.05)
            conn.execute(text("SELECT app.schedule_write_lock()"))
            conn.execute(text("UPDATE app.round_schedules SET active_to = '2035-01-01Z' WHERE "
                              "code = :c AND version = 2"), {"c": code})  # fmt: skip
            _insert(conn, code, 3, "2035-01-01Z")

    a, b = _bg(drop_v2_reopen_v1), _bg(add_v3)
    for t, _ in (a, b):
        t.join(15)
    assert "error" not in a[1], a[1]
    assert "error" in b[1]  # v2 is gone once it may run: its change no longer fits
    with transaction(engine) as conn:
        rows = conn.execute(text("SELECT version, active_to FROM app.round_schedules "
                                 "WHERE code = :c ORDER BY version"), {"c": code}).all()  # fmt: skip
    assert [(r.version, r.active_to) for r in rows] == [(1, None)]


def test_creators_share_the_lock_and_do_not_block_each_other(engine, op):
    code = _code("s4bc")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    holder = engine.connect()
    htx = holder.begin()
    schedules.lock_for_round_creation(holder)  # a creator holds the shared lock
    t0 = time.monotonic()
    r = _draft(engine, op, code)  # another creator proceeds at once
    assert r.status == "draft" and time.monotonic() - t0 < 1.5
    assert not _waiting_for_advisory(engine)
    htx.rollback()
    holder.close()
    assert now_db(engine)  # connection pool healthy


# ===================================================================== app follow-ups (4B)
def test_scheduled_draft_pinned_to_its_planned_schedule(engine, monkeypatch):
    """A schedule change between planning and creation: nothing is written."""
    from diski9.backend.services import rounds as svc

    code = _code("s4bp")
    add_row(engine, code, 1, datetime(2020, 1, 1, tzinfo=UTC))
    monkeypatch.setattr(svc, "SCHEDULED_SCHEDULE", code)
    with transaction(engine) as conn:
        planned = schedules.current_schedule(conn, code).id
    t = now_db(engine)
    add_row(engine, code, 2, t)  # the schedule changes after planning
    with pytest.raises(svc.ScheduleChanged):
        svc.create_scheduled_draft(engine, svc.SYSTEM, iso_year=2034, iso_week=3,
                                   expected_schedule_id=planned)  # fmt: skip
    with transaction(engine) as conn:
        assert not conn.execute(text("SELECT count(*) FROM app.rounds WHERE code = :c"),
                                {"c": svc.scheduled_code(2034, 3)}).scalar_one()  # fmt: skip
    res = svc.create_scheduled_draft(engine, svc.SYSTEM, iso_year=2034, iso_week=3)
    assert res.created  # replanned: the new row applies


def test_prepare_draft_step_retries_a_changed_schedule_and_reports_the_real_window(
    engine, monkeypatch
):
    from types import SimpleNamespace

    from diski9.backend.jobs import prepare
    from diski9.backend.jobs.reconciler import Outcome
    from diski9.backend.services import rounds as svc

    run = SimpleNamespace(engine=engine, check=lambda: None, tick_id=None, token="t", host=None)
    week = prepare.Week(2034, 9, svc.scheduled_code(2034, 9), *(datetime(2034, 2, 1, tzinfo=UTC),) * 5,
                        schedule_id=-1)  # fmt: skip

    def changed(*a, **k):
        assert k["expected_schedule_id"] == -1  # the plan's row is passed through
        raise svc.ScheduleChanged("The 'weekend' schedule that applies now is not the one")

    monkeypatch.setattr(svc, "create_scheduled_draft", changed)
    rep = prepare._draft_step(run, week)
    assert rep.outcome == Outcome.RETRYABLE and "replanned on the next tick" in rep.detail

    real = SimpleNamespace(created=True, round=SimpleNamespace(
        window_start_at=datetime(2034, 3, 3, tzinfo=UTC), window_end_at=datetime(2034, 3, 7, tzinfo=UTC)))  # fmt: skip
    monkeypatch.setattr(svc, "create_scheduled_draft", lambda *a, **k: real)
    rep = prepare._draft_step(run, week)
    assert rep.outcome == Outcome.SUCCEEDED and "2034-03-03" in rep.detail  # not the plan's


def test_schedule_config_cache_is_keyed_by_code_and_never_outlives_a_boundary(engine):
    from diski9.app.challenge.persist import Backend
    from diski9.challenge.config import A3_432_V1, BROAD60_432_V1

    a, b = _code("s4bk"), _code("s4bk")
    add_row(engine, a, 1, datetime(2020, 1, 1, tzinfo=UTC), cfg=BROAD60_432_V1.version)
    add_row(engine, b, 1, datetime(2020, 1, 1, tzinfo=UTC), cfg=A3_432_V1.version)
    be = Backend(engine)
    assert be.schedule_config(a) is BROAD60_432_V1
    assert be.schedule_config(b) is A3_432_V1  # not served from code a's entry
    assert be.schedule_config(a) is BROAD60_432_V1
    t = now_db(engine)
    c = _code("s4bk")
    add_row(engine, c, 1, t - timedelta(days=1), cfg=BROAD60_432_V1.version)
    add_row(engine, c, 2, t + timedelta(seconds=1), cfg=A3_432_V1.version)
    assert be.schedule_config(c) is BROAD60_432_V1
    sent, until = time.monotonic(), be._sched[c][1]
    assert until - sent <= 1.0  # expiry measured from before the query: <= the boundary
    while now_db(engine) < t + timedelta(seconds=1, milliseconds=50):
        time.sleep(0.05)
    assert be.schedule_config(c) is A3_432_V1


# ===================================================================== migration-time locking
def _relation_waiters(url) -> int:
    with _eng(url).connect() as conn:
        return conn.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'relation' AND NOT granted"
        )).scalar_one()  # fmt: skip


def _wait_for_waiters(url, n, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _relation_waiters(url) >= n:
            return True
        time.sleep(0.05)
    return False


INVALID_ROUND = (
    "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, window_end_at, "
    "created_at) SELECT :c, id, series_id, now(), now() + interval '1 day', "
    "'2026-11-01T00:00:00Z' FROM app.round_schedules "
    "WHERE code = 'weekend' AND active_to IS NULL"
)  # created before the open weekend row was valid: an invalid historical binding
VALID_ROUND = (
    "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, window_end_at) "
    "SELECT :c, id, series_id, now(), now() + interval '1 day' FROM app.round_schedules "
    "WHERE code = 'weekend' AND active_to IS NULL"
)


def test_audit_waits_for_an_in_flight_invalid_write_and_refuses_it(fresh_url):
    """Before the refinement the audit could not see an uncommitted round, and
    CREATE TRIGGER then waited for it and installed on top of it. Now the table locks
    come first: the migration waits for the writer, audits its committed row and
    refuses, changing nothing."""
    migrate.upgrade(fresh_url, "app_0007")
    eng = _eng(fresh_url)
    writer = eng.connect()
    wtx = writer.begin()
    writer.execute(text(INVALID_ROUND), {"c": "inflight"})  # uncommitted
    t, out = _bg(lambda: migrate.upgrade(fresh_url))
    assert _wait_for_waiters(fresh_url, 1)  # the migration waits at its table locks
    wtx.commit()
    writer.close()
    t.join(30)
    assert isinstance(out.get("error"), DBAPIError), out
    assert "rounds outside their schedule validity" in str(out["error"])
    assert migrate.current(fresh_url) == "app_0007"
    with eng.connect() as conn:
        got = _schema_state(conn)
        kept = conn.execute(text("SELECT count(*) FROM app.rounds WHERE code = 'inflight'"))
        assert kept.scalar_one() == 1  # never repaired or removed
    assert got["triggers"] == set() and got["functions"] == 0 and got["constraint"] == 0
    eng.dispose()


def test_writes_during_the_migration_queue_and_then_meet_the_safeguards(fresh_url):
    """Writers that do not use the advisory protocol (older application versions,
    direct SQL) arrive while the migration holds its locks: they wait, and run only
    after the safeguards are installed, which then refuse them. Nothing can slip in
    between the audit and the installation."""
    migrate.upgrade(fresh_url, "app_0007")
    eng = _eng(fresh_url)
    holder = eng.connect()
    htx = holder.begin()
    holder.execute(text(VALID_ROUND), {"c": "holder"})  # keeps the migration waiting
    m, mout = _bg(lambda: migrate.upgrade(fresh_url))
    assert _wait_for_waiters(fresh_url, 1)

    def gap_writer():  # a closed-only schedule code: valid under app_0007, not after
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO app.round_schedules (code, version, timezone, "
                "eligible_competitions, window_rule, publish_rule, deadline_buffer_minutes, "
                "settle_cutoff_hours, correction_window_hours, config_version, rules_version, "
                "scoring_version, series_id, active_from, active_to) SELECT 'race', 1, "
                "timezone, eligible_competitions, window_rule, publish_rule, "
                "deadline_buffer_minutes, settle_cutoff_hours, correction_window_hours, "
                "config_version, rules_version, scoring_version, series_id, "
                "'2020-01-01Z', '2030-01-01Z' FROM app.round_schedules "
                "WHERE code = 'weekend' AND active_to IS NULL"))  # fmt: skip

    def round_writer():  # the application's order: read the schedule, then insert
        with eng.begin() as conn:
            sid, series = conn.execute(
                text(
                    "SELECT id, series_id FROM app.round_schedules "
                    "WHERE code = 'weekend' AND active_to IS NULL"
                )
            ).one()  # queues behind the migration's lock
            conn.execute(
                text(
                    "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, "
                    "window_end_at, created_at) VALUES ('late', :s, :r, now(), now() + "
                    "interval '1 day', '2026-11-01T00:00:00Z')"
                ),
                {"s": sid, "r": series},
            )

    g, gout = _bg(gap_writer)
    r, rout = _bg(round_writer)
    assert _wait_for_waiters(fresh_url, 3)  # migration, gap writer, round writer
    htx.commit()
    holder.close()
    for t in (m, g, r):
        t.join(30)
    assert "error" not in mout, mout
    assert migrate.current(fresh_url) == "app_0008"
    assert isinstance(gout.get("error"), DBAPIError) and "open-ended" in str(gout["error"])
    assert isinstance(rout.get("error"), DBAPIError) and "not valid at the round" in str(
        rout["error"]
    )
    with eng.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.round_schedules WHERE code = 'race'")
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(text("SELECT count(*) FROM app.rounds WHERE code = 'late'")).scalar_one()
            == 0
        )
        bad = conn.execute(text(
            "SELECT count(*) FROM app.rounds r JOIN app.round_schedules s ON s.id = r.schedule_id "
            "WHERE NOT (s.active_from <= r.created_at AND (s.active_to IS NULL "
            "OR r.created_at < s.active_to))")).scalar_one()  # fmt: skip
    assert bad == 0  # the audited state still holds after installation
    eng.dispose()


def test_migration_gives_up_cleanly_behind_a_long_transaction(fresh_url):
    """A writer that keeps its transaction open past the 10 s lock timeout: the
    migration fails with nothing changed instead of holding writers behind it."""
    migrate.upgrade(fresh_url, "app_0007")
    eng = _eng(fresh_url)
    holder = eng.connect()
    htx = holder.begin()
    holder.execute(text("SELECT count(*) FROM app.round_schedules"))  # holds ACCESS SHARE
    with eng.connect() as conn:
        before = _schema_state(conn)
    t0 = time.monotonic()
    with pytest.raises(DBAPIError, match="lock timeout"):
        migrate.upgrade(fresh_url)
    assert 9 <= time.monotonic() - t0 < 30
    htx.rollback()
    holder.close()
    assert migrate.current(fresh_url) == "app_0007"
    with eng.connect() as conn:
        assert _schema_state(conn) == before
    migrate.upgrade(fresh_url)  # once the transaction is gone it installs
    assert migrate.current(fresh_url) == "app_0008"
    eng.dispose()


def test_runtime_role_cannot_bypass_triggers_or_privileges(engine, app_engine):
    """Only a superuser or the owner of the tables (the migration role) can disable
    these guards; the runtime role is neither."""
    with transaction(engine) as conn:
        priv = conn.execute(text(
            "SELECT has_table_privilege('diski9_app', 'app.round_schedules', 'TRUNCATE'), "
            "has_table_privilege('diski9_app', 'app.round_schedules', 'TRIGGER'), "
            "has_table_privilege('diski9_app', 'app.rounds', 'TRIGGER'), "
            "pg_has_role('diski9_app', (SELECT relowner FROM pg_class "
            "WHERE oid = 'app.round_schedules'::regclass), 'MEMBER'), "
            "(SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = 'diski9_app')"
        )).one()  # fmt: skip
    assert tuple(priv) == (False, False, False, False, False)
    for sql in ("ALTER TABLE app.rounds DISABLE TRIGGER rounds_schedule_valid",
                "ALTER TABLE app.round_schedules DISABLE TRIGGER round_schedules_row_guard",
                "DROP TRIGGER rounds_identity_immutable ON app.rounds",
                "SET LOCAL session_replication_role = replica",
                "TRUNCATE app.round_schedules"):  # fmt: skip
        with (
            pytest.raises(DBAPIError, match="must be owner|permission denied"),
            transaction(app_engine) as conn,
        ):
            conn.execute(text(sql))


@pytest.mark.parametrize("pattern", ["insert_select", "fk_only"])
def test_a_reverse_order_writer_can_deadlock_but_nothing_invalid_commits(fresh_url, pattern):
    """A direct insert that has not read round_schedules first locks rounds (the target)
    before round_schedules (INSERT ... SELECT, or only the foreign-key check): the
    reverse of the migration's order (schedules first, as the application resolves
    them). PostgreSQL detects the deadlock and aborts one side. Either outcome is safe:
    the writer fails, or the migration fails having changed nothing (and a later
    attempt audits the writer's row)."""
    migrate.upgrade(fresh_url, "app_0007")
    eng = _eng(fresh_url)
    with eng.connect() as conn:
        sid, series = conn.execute(
            text(
                "SELECT id, series_id FROM app.round_schedules "
                "WHERE code = 'weekend' AND active_to IS NULL"
            )
        ).one()
    holder = eng.connect()
    htx = holder.begin()
    holder.execute(text(VALID_ROUND), {"c": "holder"})
    m, mout = _bg(lambda: migrate.upgrade(fresh_url))
    assert _wait_for_waiters(fresh_url, 1)

    def reverse_writer():
        with eng.begin() as conn:
            if pattern == "insert_select":
                conn.execute(text(INVALID_ROUND), {"c": "reverse"})
            else:
                conn.execute(
                    text(
                        "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, "
                        "window_end_at, created_at) VALUES ('reverse', :s, :r, now(), now() + "
                        "interval '1 day', '2026-11-01T00:00:00Z')"
                    ),
                    {"s": sid, "r": series},
                )

    w, wout = _bg(reverse_writer)
    time.sleep(1.5)  # let it queue (and the deadlock detector run, if it deadlocks)
    htx.commit()
    holder.close()
    for t in (m, w):
        t.join(30)
    with eng.connect() as conn:
        bad = conn.execute(text(
            "SELECT count(*) FROM app.rounds r JOIN app.round_schedules s ON s.id = r.schedule_id "
            "WHERE NOT (s.active_from <= r.created_at AND (s.active_to IS NULL "
            "OR r.created_at < s.active_to))")).scalar_one()  # fmt: skip
        state = _schema_state(conn)
    if "error" in mout:  # the migration was the victim: nothing installed
        assert migrate.current(fresh_url) == "app_0007" and state["functions"] == 0
        assert state["triggers"] == set()
        if bad:  # the writer's row committed under app_0007: the next attempt refuses it
            _refused(fresh_url, "rounds outside their schedule validity")
    else:  # installed: the writer was refused (deadlock or trigger), nothing invalid
        assert "error" in wout and migrate.current(fresh_url) == "app_0008"
        assert bad == 0
    eng.dispose()
