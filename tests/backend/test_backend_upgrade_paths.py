"""Phase 6C.3 Stage G: database upgrade paths on a separate PostgreSQL database.

* fresh installation to the head revision;
* upgrade from Phase 6C.2 (``app_0002``) with accounts and Your View rows;
* upgrade from the Stage D checkpoint (``app_0003``) with a published round, a
  versioned draft, a confirmed entry and Your View rows;
* downgrade to each earlier revision and re-upgrade, data kept;
* a new engine (application restart) reconstructs everything from PostgreSQL.

The session test database is left untouched: this module creates and drops its
own ``*_upgrade_test`` database on the same server.
"""

from __future__ import annotations

import json

import pytest
from pg_helpers import confirm, make_round, make_user
from sqlalchemy import create_engine, pool, text
from sqlalchemy.exc import DBAPIError

from diski9.backend.db import migrate


def _eng(url):
    return create_engine(url, poolclass=pool.NullPool)


STATE = {"context": {"home": 0.2, "away": -0.1}, "cats": {}, "manual": {"home": 0, "away": 0}}


def _counts(url):
    with _eng(url).connect() as conn:
        return {
            t: conn.execute(text(f"SELECT count(*) FROM app.{t}")).scalar_one()
            for t in ("users", "profiles", "user_identities", "your_view_adjustments",
                      "rounds", "portfolio_drafts", "entries", "submissions")
        }  # fmt: skip


def test_fresh_installation_reaches_head(fresh_url):
    migrate.upgrade(fresh_url)
    assert migrate.current(fresh_url) == migrate.head() == "app_0008"
    with _eng(fresh_url).connect() as conn:
        rule = conn.execute(
            text(
                "SELECT publish_rule FROM app.round_schedules WHERE code='weekend' "
                "ORDER BY version DESC LIMIT 1"
            )  # fmt: skip
        ).scalar_one()
    assert rule == {"weekday": "friday", "time": "08:00", "tz": "Africa/Johannesburg"}


def test_upgrade_from_phase_6c2_keeps_accounts_and_your_view(fresh_url):
    migrate.upgrade(fresh_url, "app_0002")
    eng = _eng(fresh_url)
    with eng.begin() as conn:
        uid = make_user(conn)
        conn.execute(
            text("INSERT INTO app.your_view_adjustments (user_id, fixture_id, model_context, "
                 "state) VALUES (:u, 4242, '1.0|4242|1.31|1.02', CAST(:s AS jsonb))"),
            {"u": uid, "s": json.dumps(STATE)},
        )  # fmt: skip
    migrate.upgrade(fresh_url)
    assert migrate.current(fresh_url) == "app_0008"
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT context_kind, snapshot_id, version, model_context, state "
                 "FROM app.your_view_adjustments WHERE user_id = :u"), {"u": uid}
        ).one()  # fmt: skip
        assert conn.execute(text("SELECT count(*) FROM app.profiles WHERE user_id=:u"),
                            {"u": uid}).scalar_one() == 1  # fmt: skip
    assert row.context_kind == "unassigned" and row.snapshot_id is None
    assert row.model_context == "1.0|4242|1.31|1.02" and row.state == STATE  # exact numbers
    # downgrade to 6C.2 and back: still there
    migrate.downgrade(fresh_url, "app_0002")
    migrate.upgrade(fresh_url)
    with eng.connect() as conn:
        state = conn.execute(
            text("SELECT state FROM app.your_view_adjustments WHERE user_id=:u"), {"u": uid}
        ).scalar_one()
    assert state == STATE
    eng.dispose()


def test_upgrade_from_stage_d_checkpoint_keeps_rounds_drafts_and_entries(fresh_url):
    migrate.upgrade(fresh_url, "app_0003")
    eng = _eng(fresh_url)
    with eng.begin() as conn:
        uid = make_user(conn)
        rid, snap_id, fids = make_round(conn)
        sels = [{"fixture_id": f, "market": "1X2", "outcome": "HOME"} for f in fids]
        conn.execute(
            text("INSERT INTO app.portfolio_drafts (user_id, round_id, selections, version, "
                 "updated_at) VALUES (:u, :r, CAST(:s AS jsonb), 4, now())"),
            {"u": uid, "r": rid, "s": json.dumps(sels)},
        )  # fmt: skip
        other = make_user(conn)
        confirm(conn, rid, snap_id, fids, other)
        conn.execute(
            text("INSERT INTO app.your_view_adjustments (user_id, fixture_id, model_context, "
                 "state, version) VALUES (:u, :f, '1.0|x|1.10|0.90', CAST(:s AS jsonb), 3)"),
            {"u": uid, "f": fids[0], "s": json.dumps(STATE)},
        )  # fmt: skip
    before = _counts(fresh_url)
    migrate.upgrade(fresh_url)
    assert _counts(fresh_url) == before  # nothing lost or duplicated
    with eng.connect() as conn:
        d = conn.execute(
            text("SELECT selections, version, writer_tab FROM app.portfolio_drafts "
                 "WHERE user_id=:u"), {"u": uid}
        ).one()  # fmt: skip
        sub = conn.execute(
            text("SELECT s.version, s.max_gross FROM app.entries e JOIN app.submissions s "
                 "ON s.id = e.current_submission_id WHERE e.user_id=:u"), {"u": other}
        ).one()  # fmt: skip
        yv = conn.execute(
            text("SELECT context_kind, version, state FROM app.your_view_adjustments "
                 "WHERE user_id=:u"), {"u": uid}
        ).one()  # fmt: skip
        dev = conn.execute(
            text("SELECT is_development FROM app.rounds WHERE id=:r"), {"r": rid}
        ).scalar_one()
    assert d.selections == sels and d.version == 4 and d.writer_tab is None
    assert sub.version == 1
    assert (yv.context_kind, yv.version, yv.state) == ("unassigned", 3, STATE)
    assert dev is False
    # Submissions stay immutable after the upgrade.
    with (
        pytest.raises(Exception, match="(?i)immutable|not allowed|cannot|denied|forbid"),
        eng.begin() as conn,
    ):
        conn.execute(text("UPDATE app.submissions SET max_gross = max_gross + 1"))
    # downgrade to the checkpoint and re-upgrade: same data
    migrate.downgrade(fresh_url, "app_0003")
    migrate.upgrade(fresh_url)
    assert _counts(fresh_url) == before
    eng.dispose()
    # "Restart": a brand-new engine reads the same state.
    eng2 = _eng(fresh_url)
    with eng2.connect() as conn:
        assert (
            conn.execute(
                text("SELECT version FROM app.portfolio_drafts WHERE user_id=:u"), {"u": uid}
            ).scalar_one()
            == 4
        )
    eng2.dispose()


def test_upgrade_to_settlement_schema_backfills_and_downgrade_is_honest(fresh_url):
    """Phase 6C.4 (app_0006): a published round from app_0005 gains its frozen
    correction window and real result mode; down/up with no settlement data
    restores app_0005 exactly; once settlement data exists the downgrade refuses
    and changes nothing (settlement history is never discarded silently)."""
    migrate.upgrade(fresh_url, "app_0005")
    eng = _eng(fresh_url)
    with eng.begin() as conn:
        uid = make_user(conn)
        rid, snap_id, fids = make_round(conn)
        confirm(conn, rid, snap_id, fids, uid)
    before = _counts(fresh_url)
    migrate.upgrade(fresh_url)
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT correction_window_hours, result_mode FROM app.rounds WHERE id=:r"),
            {"r": rid},
        ).one()
    assert tuple(row) == (24, "real") and _counts(fresh_url) == before
    migrate.downgrade(fresh_url, "app_0005")
    assert migrate.current(fresh_url) == "app_0005" and _counts(fresh_url) == before
    migrate.upgrade(fresh_url)
    with eng.begin() as conn:  # settlement data now exists
        conn.execute(
            text("INSERT INTO app.result_observations (fixture_id, observed_at, source, "
                 "status_short, raw_hash) VALUES (:f, now(), 'api-football', 'NS', :h), "
                 "(:f, now(), 'api-football', 'NS', :h)"),
            {"f": fids[0], "h": "d" * 64},
        )  # fmt: skip
    with pytest.raises(DBAPIError, match="downgrade refused"):
        migrate.downgrade(fresh_url, "app_0005")
    assert migrate.current(fresh_url) == "app_0006"
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.result_observations")).scalar_one() == 2
    eng.dispose()


def _app_counts(url):
    with _eng(url).connect() as conn:
        return {
            t: conn.execute(text(f"SELECT count(*) FROM app.{t}")).scalar_one()
            for t in ("users", "profiles", "rounds", "entries", "submissions", "entry_events",
                      "round_snapshots", "designations", "result_observations", "audit_log")
        }  # fmt: skip


def test_upgrade_to_competition_results_keeps_data_and_downgrade_is_honest(fresh_url):
    """Phase 6C.5 (app_0007): existing rounds, entries and settlement evidence are
    unchanged by the upgrade; with no official results the downgrade restores
    app_0006; once results exist it refuses and changes nothing."""
    migrate.upgrade(fresh_url, "app_0006")
    eng = _eng(fresh_url)
    with eng.begin() as conn:
        uid = make_user(conn)
        rid, snap_id, fids = make_round(conn)
        confirm(conn, rid, snap_id, fids, uid)
        conn.execute(
            text("INSERT INTO app.result_observations (fixture_id, observed_at, source, "
                 "status_short, raw_hash) VALUES (:f, now(), 'api-football', 'NS', :h)"),
            {"f": fids[0], "h": "e" * 64},
        )  # fmt: skip
    before = _app_counts(fresh_url)
    with eng.connect() as conn:
        rows_before = conn.execute(text("SELECT * FROM app.entries ORDER BY id")).all()
    migrate.upgrade(fresh_url)
    assert migrate.current(fresh_url) == "app_0008" and _app_counts(fresh_url) == before
    with eng.connect() as conn:
        assert conn.execute(text("SELECT * FROM app.entries ORDER BY id")).all() == rows_before
        tables = set(
            conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='app'")
            ).scalars()
        )
        cols = set(conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='app' "
            "AND table_name='score_sets'")).scalars())  # fmt: skip
        idx = set(conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE schemaname='app'")).scalars())  # fmt: skip
    assert "championship_freezes" not in tables
    assert {"championships", "championship_rounds", "championship_versions",
            "championship_standings"} <= tables  # fmt: skip
    assert {"settlement_version_id", "scoring_version", "published_at"} <= cols
    assert {"ix_round_scores_user", "ix_score_sets_round", "ix_championship_rounds",
            "ix_championship_standings_user", "score_sets_settlement_version_key",
            "round_scores_display_order_key"} <= idx  # fmt: skip
    migrate.downgrade(fresh_url, "app_0006")
    assert migrate.current(fresh_url) == "app_0006" and _app_counts(fresh_url) == before
    migrate.upgrade(fresh_url)
    with eng.begin() as conn:  # an official competition record now exists
        conn.execute(text(
            "INSERT INTO app.championships (stream, series_id, ordinal, start_date, display_name) "
            "SELECT 'beta', id, 1, '2026-11-27', 'Championship Nov-26' "
            "FROM app.championship_series WHERE code='beta'"))  # fmt: skip
    with pytest.raises(DBAPIError, match="downgrade refused"):
        migrate.downgrade(fresh_url, "app_0006")
    # one transaction per migration (migrations_app/env.py): app_0008's downgrade (its
    # safeguards only, no data) committed before app_0007 refused; app_0007's data stays
    assert migrate.current(fresh_url) == "app_0007"
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.championships")).scalar_one() == 1
    eng.dispose()


def test_upgrade_refuses_unexpected_rows_in_the_placeholder_tables(fresh_url):
    """``championship_freezes`` is dropped only when it is empty (it was never
    written); otherwise nothing changes."""
    migrate.upgrade(fresh_url, "app_0006")
    eng = _eng(fresh_url)
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO app.championship_freezes (series_id, number, round_ids, standings, "
            "champions, content_hash) SELECT id, 1, '{}', '[]', '[]', :h "
            "FROM app.championship_series WHERE code='beta'"), {"h": "a" * 64})  # fmt: skip
    with pytest.raises(DBAPIError, match="upgrade refused"):
        migrate.upgrade(fresh_url)
    assert migrate.current(fresh_url) == "app_0006"
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.championship_freezes")).scalar_one() == 1
    eng.dispose()
