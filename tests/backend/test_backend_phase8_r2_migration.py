"""Migration ``app_0010`` (Phase 8 R2) on a separate disposable database: upgrade of a
populated ``app_0009`` database, safe downgrade, refusal when rolling-entry data
exists, and no schedule activation."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from pg_helpers import confirm, make_round, make_user
from rolling_helpers import publish_rolling
from svc_helpers import principal

from diski9.backend.db import BackendDatabaseSettings, make_app_engine, migrate, transaction


def _eng(url):
    return make_app_engine(BackendDatabaseSettings(environment="test", lock_timeout_ms=5000),
                           url=url)  # fmt: skip


def _q(eng, sql, **p):
    with transaction(eng) as conn:
        return conn.execute(sa.text(sql), p).all()


def test_upgrade_of_a_populated_database_keeps_snapshots_and_references(fresh_url):
    migrate.upgrade(fresh_url, "app_0009")
    eng = _eng(fresh_url)
    try:
        with transaction(eng) as conn:
            uid = make_user(conn)
            rid, sid, fids = make_round(conn)
            entry, sub = confirm(conn, rid, sid, fids, uid)
        before = _q(eng, "SELECT id, round_id FROM app.round_snapshots ORDER BY id")
        refs = _q(eng, "SELECT id, snapshot_id FROM app.submissions ORDER BY id")
        migrate.upgrade(fresh_url)
        assert migrate.current(fresh_url) == "app_0010"
        after = _q(eng, "SELECT id, round_id, edition FROM app.round_snapshots ORDER BY id")
        assert [(r.id, r.round_id) for r in after] == [tuple(r) for r in before]
        assert {r.edition for r in after} == {1}  # existing snapshots are edition 1
        assert _q(eng, "SELECT id, snapshot_id FROM app.submissions ORDER BY id") == refs
        # nothing invented for history; no schedule activated
        assert _q(eng, "SELECT count(*) FROM app.snapshot_offers WHERE oldest_observation_at "
                       "IS NOT NULL")[0][0] == 0  # fmt: skip
        assert _q(eng, "SELECT count(*) FROM app.round_schedules WHERE rules_version = "
                       "'rolling/v1'")[0][0] == 0  # fmt: skip
        assert _q(eng, "SELECT count(*) FROM app.submission_views")[0][0] == 0
        assert entry and sub
    finally:
        eng.dispose()


def test_downgrade_is_safe_without_rolling_data_and_restores_the_old_constraint(fresh_url):
    migrate.upgrade(fresh_url)
    eng = _eng(fresh_url)
    try:
        with transaction(eng) as conn:
            rid, sid, fids = make_round(conn)
        migrate.downgrade(fresh_url, "app_0009")
        assert migrate.current(fresh_url) == "app_0009"
        cols = {r[0] for r in _q(eng, "SELECT column_name FROM information_schema.columns "
                                      "WHERE table_schema = 'app' AND table_name = "
                                      "'round_snapshots'")}  # fmt: skip
        assert "edition" not in cols
        assert _q(eng, "SELECT to_regclass('app.submission_views')")[0][0] is None
        with pytest.raises(sa.exc.DBAPIError), transaction(eng) as conn:  # UNIQUE (round_id)
            conn.execute(sa.text(
                "INSERT INTO app.round_snapshots (round_id, as_of, fingerprint, model_version, "
                "feasibility) VALUES (:r, now(), :f, 'm', '{}')"), {"r": rid, "f": "a" * 16})  # fmt: skip
        migrate.upgrade(fresh_url)  # re-upgrade works
        assert migrate.current(fresh_url) == "app_0010"
    finally:
        eng.dispose()


def test_downgrade_refuses_when_rolling_entry_data_exists(fresh_url):
    migrate.upgrade(fresh_url)
    eng = _eng(fresh_url)
    try:
        op = principal(eng, role="operator")
        publish_rolling(eng, op, close_in=timedelta(days=1), seed=5101)
        with pytest.raises(Exception, match="app_0010 downgrade refused"):
            migrate.downgrade(fresh_url, "app_0009")
        assert migrate.current(fresh_url) == "app_0010"
        assert _q(eng, "SELECT count(*) FROM app.rounds WHERE rules_version = 'rolling/v1'"
                  )[0][0] == 1  # nothing changed  # fmt: skip
    finally:
        eng.dispose()
