"""Scenario A3 active from day one: migration app_0009 (Checkpoint 4C, Option D).

* fresh installation: weekend v3 on a3-432-v1 from the migration instant, every other
  attribute copied from v2;
* upgrade of a database holding broad60 rounds and an unpublished draft: their
  bindings and configuration stay broad60; new rounds bind A3;
* strict refusal of unexpected states, with nothing changed (atomic rollback);
* downgrade restores v2 atomically, and refuses once a round is bound to v3;
* the session database (migrated to head): exact half-open boundary, new rounds and
  the database-backed rules configuration are A3.

Migration tests use the separate disposable database ``fresh_url``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pg_helpers import unique
from sqlalchemy import create_engine, pool, text
from svc_helpers import principal, publish_dev

from diski9.app.challenge.persist import Backend
from diski9.backend.db import BackendDatabaseSettings, db_now, make_app_engine, migrate, transaction
from diski9.backend.devdata import dev_snapshot
from diski9.backend.services import rounds as svc
from diski9.backend.services import schedules
from diski9.backend.services.common import ServiceError
from diski9.challenge.config import A3_432_V1, BROAD60_432_V1, DEFAULT_CONFIG

COPIED = ("timezone", "eligible_competitions", "window_rule", "publish_rule",
          "deadline_buffer_minutes", "settle_cutoff_hours", "correction_window_hours",
          "rules_version", "scoring_version", "series_id")  # fmt: skip


def _eng(url):
    return make_app_engine(BackendDatabaseSettings(environment="test", lock_timeout_ms=5000),
                           url=url)  # fmt: skip


def _weekend(conn) -> dict[int, dict]:
    rows = conn.execute(text(
        "SELECT s.*, c.code AS series FROM app.round_schedules s JOIN app.championship_series c "
        "ON c.id = s.series_id WHERE s.code = 'weekend' ORDER BY version")).mappings().all()  # fmt: skip
    return {r["version"]: dict(r) for r in rows}


def _rounds(conn) -> list[tuple]:
    return conn.execute(text(
        "SELECT r.code, s.version, r.config_version, r.status FROM app.rounds r "
        "JOIN app.round_schedules s ON s.id = r.schedule_id ORDER BY r.code")).all()  # fmt: skip


def _publish(engine, op, config, *, development=True):
    """A development round published through the services with ``config``."""
    with transaction(engine) as conn:
        now = db_now(conn)
    code = unique("dev-a3")
    snap = dev_snapshot(code, now, now + timedelta(hours=2, minutes=15), config=config)
    v = svc.create_round(engine, op, code=code, window_start=snap.window[0],
                         window_end=snap.window[1], development=development)  # fmt: skip
    return svc.publish_round(engine, op, v.id, snap, source="development"), snap


# ------------------------------------------------------------------ migration
def test_fresh_installation_makes_a3_active_and_copies_every_attribute(fresh_url):
    migrate.upgrade(fresh_url)
    assert migrate.current(fresh_url) == "app_0009"
    eng = _eng(fresh_url)
    try:
        with transaction(eng) as conn:
            w = _weekend(conn)
            cur = schedules.current_schedule(conn, "weekend")
        assert sorted(w) == [1, 2, 3]
        v2, v3 = w[2], w[3]
        assert (v2["config_version"], v3["config_version"]) == ("broad60-432-v1", "a3-432-v1")
        assert v2["active_to"] == v3["active_from"] and v3["active_to"] is None
        assert v3["active_from"] > v2["active_from"]  # separate migration transactions
        assert all(v2[c] == v3[c] for c in COPIED)
        assert v3["series"] == "beta"  # series binding preserved (Official: Phase 10)
        assert cur.id == v3["id"] and cur.config_version == "a3-432-v1"
    finally:
        eng.dispose()


def test_upgrade_keeps_broad60_rounds_and_drafts_and_new_rounds_bind_a3(fresh_url):
    migrate.upgrade(fresh_url, "app_0008")
    eng = _eng(fresh_url)
    try:
        op = principal(eng, role="operator")
        published, _ = _publish(eng, op, BROAD60_432_V1)
        with transaction(eng) as conn:
            now = db_now(conn)
        draft = svc.create_round(eng, op, code=unique("dev-a3d"), window_start=now,
                                 window_end=now + timedelta(days=3), development=True)  # fmt: skip
        with transaction(eng) as conn:
            before = _rounds(conn)
        migrate.upgrade(fresh_url)
        assert migrate.current(fresh_url) == "app_0009"
        with transaction(eng) as conn:
            assert _rounds(conn) == before  # nothing rebound or changed
            v2_id = _weekend(conn)[2]["id"]
            ids = dict(conn.execute(text("SELECT id, schedule_id FROM app.rounds")).all())
        assert ids[published.id] == v2_id and ids[draft.id] == v2_id
        # the pre-migration draft still publishes under its own row: broad60
        snap = dev_snapshot(draft.code, now, now + timedelta(hours=2, minutes=15),
                            config=BROAD60_432_V1)  # fmt: skip
        with pytest.raises(ServiceError):  # an A3 snapshot is refused for this draft
            svc.publish_round(eng, op, draft.id, dev_snapshot(
                draft.code, now, now + timedelta(hours=2, minutes=15), config=A3_432_V1),
                source="development")  # fmt: skip
        v = svc.publish_round(eng, op, draft.id, snap, source="development")
        assert v.config_version == "broad60-432-v1"
        # a round created after the migration binds v3 and publishes A3
        new, _ = _publish(eng, op, A3_432_V1)
        assert new.config_version == "a3-432-v1"
        with transaction(eng) as conn:
            assert conn.execute(text("SELECT s.version FROM app.rounds r JOIN "
                                     "app.round_schedules s ON s.id = r.schedule_id "
                                     "WHERE r.id = :i"), {"i": new.id}).scalar_one() == 3  # fmt: skip
    finally:
        eng.dispose()


def _admin(url):
    return create_engine(url, poolclass=pool.NullPool)


def _refuses(url, match):
    with _admin(url).connect() as c:
        before = _weekend(c)
    with pytest.raises(Exception, match=match):
        migrate.upgrade(url)
    assert migrate.current(url) == "app_0008"
    with _admin(url).connect() as c:
        assert _weekend(c) == before  # atomic: nothing changed


def test_upgrade_refuses_unexpected_states_and_changes_nothing(fresh_url):
    migrate.upgrade(fresh_url, "app_0008")
    eng = _admin(fresh_url)
    # (a) v2 is not on broad60-432-v1 (unreferenced row: the row guard allows the edit)
    with eng.begin() as c:
        c.execute(text("SELECT app.schedule_write_lock()"))
        c.execute(text("UPDATE app.round_schedules SET config_version = 'other-v1' "
                       "WHERE code = 'weekend' AND version = 2"))  # fmt: skip
    _refuses(fresh_url, "not in the expected state")
    with eng.begin() as c:
        c.execute(text("SELECT app.schedule_write_lock()"))
        c.execute(text("UPDATE app.round_schedules SET config_version = 'broad60-432-v1' "
                       "WHERE code = 'weekend' AND version = 2"))  # fmt: skip
    # (b) a later version already exists (v3 open, v2 closed): not silently skipped
    with eng.begin() as c:
        c.execute(text("SELECT app.schedule_write_lock()"))
        c.execute(text("UPDATE app.round_schedules SET active_to = now() + interval '1 day' "
                       "WHERE code = 'weekend' AND version = 2"))  # fmt: skip
        c.execute(text(
            "INSERT INTO app.round_schedules (code, version, timezone, eligible_competitions, "
            "window_rule, publish_rule, deadline_buffer_minutes, settle_cutoff_hours, "
            "correction_window_hours, config_version, rules_version, scoring_version, "
            "series_id, active_from) SELECT code, 3, timezone, eligible_competitions, "
            "window_rule, publish_rule, deadline_buffer_minutes, settle_cutoff_hours, "
            "correction_window_hours, 'a3-432-v1', rules_version, scoring_version, series_id, "
            "active_to FROM app.round_schedules WHERE code = 'weekend' AND version = 2"))  # fmt: skip
    _refuses(fresh_url, "not in the expected state")
    eng.dispose()


def test_upgrade_refuses_when_a_v2_round_was_created_after_the_migration_instant(fresh_url):
    """The app_0008 row guard: v2 cannot close before one of its rounds was created;
    the whole revision rolls back."""
    migrate.upgrade(fresh_url, "app_0008")
    eng = _admin(fresh_url)
    with eng.begin() as c:
        sid, series = c.execute(text("SELECT id, series_id FROM app.round_schedules "
                                     "WHERE code = 'weekend' AND version = 2")).one()  # fmt: skip
        c.execute(text(
            "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, "
            "window_end_at, created_at) VALUES (:c, :s, :r, now(), now() + interval '3 days', "
            "now() + interval '1 hour')"), {"c": unique("later-"), "s": sid, "r": series})  # fmt: skip
    _refuses(fresh_url, "cannot close")
    eng.dispose()


def test_downgrade_restores_v2_and_refuses_once_a3_is_referenced(fresh_url):
    migrate.upgrade(fresh_url)
    migrate.downgrade(fresh_url, "app_0008")
    eng = _eng(fresh_url)
    try:
        with transaction(eng) as conn:
            w = _weekend(conn)
        assert sorted(w) == [1, 2] and w[2]["active_to"] is None
        assert w[2]["config_version"] == "broad60-432-v1"
        migrate.upgrade(fresh_url)  # re-upgrade works
        op = principal(eng, role="operator")
        _publish(eng, op, A3_432_V1)  # a round bound to v3
        with transaction(eng) as conn:
            before = _weekend(conn)
        with pytest.raises(Exception, match="forward-only"):
            migrate.downgrade(fresh_url, "app_0008")
        assert migrate.current(fresh_url) == "app_0009"
        with transaction(eng) as conn:
            assert _weekend(conn) == before
    finally:
        eng.dispose()


# ------------------------------------------------------------------ session database (head)
def test_session_database_is_a3_with_an_exact_half_open_boundary(engine):
    us = timedelta(microseconds=1)
    with transaction(engine) as conn:
        w = _weekend(conn)
        T = w[3]["active_from"]
        assert schedules.schedule_at(conn, "weekend", T - us).version == 2
        assert schedules.schedule_at(conn, "weekend", T).version == 3
        assert schedules.schedule_at(conn, "weekend", T + us).version == 3
        assert svc.schedule_config(conn, "weekend") is A3_432_V1


def test_new_rounds_publish_a3_and_the_database_rules_follow_the_schedule(engine):
    op = principal(engine, role="operator")
    v, snap = publish_dev(engine, op)  # schedule-aware: the default is the A3 schedule's
    assert v.config_version == "a3-432-v1" and snap.config is A3_432_V1
    assert DEFAULT_CONFIG is A3_432_V1
    assert Backend(engine).schedule_config() is A3_432_V1
    with pytest.raises(ServiceError):  # a broad60 snapshot cannot be published now
        _publish(engine, op, BROAD60_432_V1)
