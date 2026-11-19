"""Concurrency and transaction behaviour on real PostgreSQL, using several
simultaneous connections (threads). These cover the 6C.1 foundations: the
database-level protections that later service code relies on."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from pg_helpers import confirm, make_round, make_user, selections_for, submission_values
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from diski9.backend.db import (
    BackendDatabaseError,
    check_health,
    db_now,
    make_app_engine,
    read_only,
    transaction,
)
from diski9.backend.db.schema import entries, job_runs, rounds
from diski9.backend.repositories import ops, portfolios
from diski9.backend.repositories import rounds as round_repo


def test_parallel_first_entries_produce_exactly_one(engine, world):
    barrier = threading.Barrier(6)

    def attempt(_):
        barrier.wait()
        try:
            with transaction(engine) as conn:
                portfolios.create_entry(conn, world["round"], world["user"])
            return "ok"
        except IntegrityError:
            return "duplicate"

    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert results.count("ok") == 1 and results.count("duplicate") == 5


def test_parallel_duplicate_clicks_create_one_submission(engine, world):
    """Six simultaneous confirms with the same idempotency key: one wins; the rest
    fail on the unique key and roll back completely."""
    with transaction(engine) as conn:
        entry_id = portfolios.create_entry(conn, world["round"], world["user"])
    key = "click-" + "x" * 20
    barrier = threading.Barrier(6)

    def attempt(i):
        barrier.wait()
        try:
            with transaction(engine) as conn:
                portfolios.insert_submission(
                    conn,
                    submission_values(
                        entry_id,
                        world["round"],
                        world["user"],
                        world["snapshot"],
                        version=1 + i,
                        key=key,
                    ),
                    selections_for(world["fixtures"]),
                )
            return "ok"
        except IntegrityError:
            return "duplicate"

    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert results.count("ok") == 1
    with transaction(engine) as conn:
        n = conn.execute(
            text("SELECT count(*) FROM app.submissions WHERE entry_id = :e"), {"e": entry_id}
        ).scalar_one()
        sel = conn.execute(
            text(
                "SELECT count(*) FROM app.submission_selections s JOIN app.submissions u "
                "ON u.id = s.submission_id WHERE u.entry_id = :e"
            ),
            {"e": entry_id},
        ).scalar_one()
    assert (n, sel) == (1, 9)


def test_entry_row_lock_serialises_changes(engine, world):
    with transaction(engine) as conn:
        confirm(conn, world["round"], world["snapshot"], world["fixtures"], world["user"])
    with transaction(engine) as a:
        assert portfolios.lock_entry(a, world["round"], world["user"]) is not None
        with (
            pytest.raises(OperationalError, match="could not obtain lock"),
            transaction(engine) as b,
        ):
            portfolios.lock_entry(b, world["round"], world["user"], nowait=True)


def test_two_tabs_one_lost_update_prevented(engine, world):
    """Both tabs read version 1; only the first optimistic update succeeds."""
    with transaction(engine) as conn:
        entry_id, sub = confirm(
            conn, world["round"], world["snapshot"], world["fixtures"], world["user"]
        )
    results = []
    for _ in range(2):
        with transaction(engine) as conn:
            results.append(portfolios.set_current_submission(conn, entry_id, sub, 1))
    assert results == [True, False]


def test_round_lock_waits_for_in_flight_submissions(engine):
    """A submission holds FOR SHARE on its round; the lock job's FOR UPDATE cannot
    proceed until it commits, and afterwards no new submission is accepted."""
    with transaction(engine) as conn:
        uid = make_user(conn)
        rid, snap, fids = make_round(conn)
        entry_id = portfolios.create_entry(conn, rid, uid)

    submitted = threading.Event()
    release = threading.Event()

    def submit():
        with transaction(engine) as conn:
            row = round_repo.lock_round_for_submission(conn, rid)
            assert row.status == "open"
            portfolios.insert_submission(
                conn, submission_values(entry_id, rid, uid, snap), selections_for(fids)
            )
            submitted.set()
            release.wait(5)

    t = threading.Thread(target=submit)
    t.start()
    assert submitted.wait(5)
    with pytest.raises(OperationalError, match="lock"), transaction(engine) as conn:
        conn.execute(text("SET LOCAL lock_timeout = '300ms'"))
        round_repo.lock_round_for_change(conn, rid)
    release.set()
    t.join(5)

    with transaction(engine) as conn:  # the lock job now proceeds
        round_repo.lock_round_for_change(conn, rid)
        round_repo.set_status(conn, rid, "locked", reason="deadline passed")
    with pytest.raises(DBAPIError, match="not open"), transaction(engine) as conn:
        portfolios.insert_submission(
            conn, submission_values(entry_id, rid, uid, snap, version=2), selections_for(fids)
        )
    with transaction(engine) as conn:
        history = conn.execute(
            text(
                "SELECT from_status, to_status FROM app.round_status_history WHERE round_id = :r "
                "ORDER BY id"
            ),
            {"r": rid},
        ).all()
    assert [tuple(h) for h in history] == [("draft", "open"), ("open", "locked")]


def test_overlapping_jobs_are_detected(engine):
    scope = f"round-{time.time_ns()}"
    with transaction(engine) as a:
        assert ops.try_job_lock(a, "settle", scope)
        with transaction(engine) as b:
            assert not ops.try_job_lock(b, "settle", scope)
            assert ops.try_job_lock(b, "settle", scope + "-other")
    with transaction(engine) as c:  # released at commit
        assert ops.try_job_lock(c, "settle", scope)


def test_job_run_can_only_be_completed_once(engine):
    with transaction(engine) as conn:
        run = ops.start_job(conn, "publish", "2026-W48")
        ops.finish_job(conn, run, "succeeded", api_requests=0)
    with pytest.raises(DBAPIError, match="only a running record"), transaction(engine) as conn:
        ops.finish_job(conn, run, "failed", error="rewrite")
    with transaction(engine) as conn:
        assert (
            conn.execute(select(job_runs.c.status).where(job_runs.c.id == run)).scalar_one()
            == "succeeded"
        )


def test_one_running_settlement_per_round(engine, world):
    with transaction(engine) as conn:
        conn.execute(
            text("INSERT INTO app.settlement_runs (round_id, trigger) VALUES (:r, 'scheduled')"),
            {"r": world["round"]},
        )
    with pytest.raises(IntegrityError, match="uq_settlement_running"), transaction(engine) as c:
        c.execute(
            text("INSERT INTO app.settlement_runs (round_id, trigger) VALUES (:r, 'manual')"),
            {"r": world["round"]},
        )


def test_rollback_on_application_error(engine, world):
    class Boom(Exception):
        pass

    with pytest.raises(Boom), transaction(engine) as conn:
        portfolios.create_entry(conn, world["round"], world["user"])
        raise Boom
    with transaction(engine) as conn:
        assert portfolios.lock_entry(conn, world["round"], world["user"]) is None


def test_read_only_transactions_reject_writes(engine, world):
    with pytest.raises(DBAPIError, match="read-only"), read_only(engine) as conn:
        conn.execute(update(rounds).where(rounds.c.id == world["round"]).values(valid_entries=1))


def test_database_clock_is_fixed_within_a_transaction(engine):
    with transaction(engine) as conn:
        a = db_now(conn)
        time.sleep(0.05)
        assert db_now(conn) == a


def test_sessions_run_in_utc_with_timeouts(engine):
    with transaction(engine) as conn:
        assert conn.execute(text("SHOW timezone")).scalar_one() == "UTC"
        assert conn.execute(text("SHOW statement_timeout")).scalar_one() != "0"
        assert conn.execute(text("SHOW lock_timeout")).scalar_one() != "0"


def test_health_check(engine):
    health = check_health(engine)
    assert health["ok"] and health["schema_revision"] == "app_0001"


def test_connection_errors_never_reveal_the_password(pg_url):
    from sqlalchemy.engine import make_url

    bad = make_url(pg_url).set(password="leak-me-not", port=1).render_as_string(hide_password=False)
    eng = make_app_engine(url=bad)
    with pytest.raises(BackendDatabaseError) as exc:
        check_health(eng)
    assert "leak-me-not" not in str(exc.value)
    eng.dispose()


def test_entries_lock_requires_the_session_user(engine, world):
    """Lookups are keyed by (round, user): another user's ID finds nothing."""
    with transaction(engine) as conn:
        confirm(conn, world["round"], world["snapshot"], world["fixtures"], world["user"])
        stranger = make_user(conn)
        assert portfolios.lock_entry(conn, world["round"], stranger) is None
        assert (
            conn.execute(
                select(entries.c.user_id).where(entries.c.round_id == world["round"])
            ).scalar_one()
            == world["user"]
        )
