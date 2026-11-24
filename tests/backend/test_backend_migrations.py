"""Competition schema migrations on real PostgreSQL: clean upgrade, downgrade,
repeat upgrades, seed data, and agreement between the migration and the
SQLAlchemy mirror (``diski9.backend.db.schema``)."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, pool, text

from diski9.backend.db import migrate, schema


def _engine(url):
    return create_engine(url, poolclass=pool.NullPool)


def test_downgrade_removes_everything_and_upgrade_recreates_it(fresh_url):
    pg_url = fresh_url  # a separate database: the session database may hold settlement data
    migrate.upgrade(pg_url)
    migrate.downgrade(pg_url, "base")
    eng = _engine(pg_url)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT to_regnamespace('app')")).scalar() is None
    assert migrate.current(pg_url) is None
    migrate.upgrade(pg_url)
    assert migrate.current(pg_url) == migrate.head() == "app_0008"
    migrate.upgrade(pg_url)  # repeat: no-op, no error
    assert migrate.current(pg_url) == "app_0008"
    eng.dispose()


def test_seed_configuration(pg_url):
    eng = _engine(pg_url)
    with eng.connect() as conn:
        feats = set(conn.execute(text("SELECT key FROM app.features")).scalars())
        assert feats == {"lucy.research", "lucy.voice", "lucy.presenter"}
        series = set(conn.execute(text("SELECT code FROM app.championship_series")).scalars())
        assert series == {"beta", "official"}
        sched = conn.execute(
            text(
                "SELECT s.deadline_buffer_minutes, s.settle_cutoff_hours, "
                "s.correction_window_hours, s.config_version, s.rules_version, "
                "s.scoring_version, cs.code, s.eligible_competitions, s.timezone, "
                "s.publish_rule->>'time', s.publish_rule->>'weekday', s.version, s.active_to "
                "FROM app.round_schedules s "
                "JOIN app.championship_series cs ON cs.id = s.series_id WHERE s.code = 'weekend' "
                "ORDER BY s.version DESC LIMIT 1"
            )
        ).one()
        assert sched[:7] == (15, 48, 24, "broad60-432-v1", "settle/v1", "points-150-75-v2", "beta")
        assert sorted(sched[7]) == [39, 40, 61, 78, 135, 140, 288, 289]
        assert sched[8] == "Africa/Johannesburg" and sched[9] == "08:00"
        # D-11 as revised at the 6C.3 checkpoint: Friday 08:00 SAST, schedule version 2
        assert sched[10:13] == ("friday", 2, None)
        old = conn.execute(
            text(
                "SELECT publish_rule->>'weekday', active_to IS NOT NULL FROM app.round_schedules "
                "WHERE code = 'weekend' AND version = 1"
            )
        ).one()
        assert tuple(old) == ("thursday", True)  # kept for rounds published under it
    eng.dispose()


def test_mirror_matches_migrated_schema(pg_url):
    eng = _engine(pg_url)
    insp = inspect(eng)
    db_tables = set(insp.get_table_names(schema="app"))
    assert db_tables == {t.name for t in schema.metadata.sorted_tables}
    for table in schema.metadata.sorted_tables:
        cols = {c["name"]: c for c in insp.get_columns(table.name, schema="app")}
        assert set(cols) == {c.name for c in table.columns}, table.name
        for c in table.columns:
            db = cols[c.name]
            assert db["nullable"] == c.nullable or c.primary_key, (table.name, c.name)
            assert type(db["type"]).__name__.upper().startswith(
                type(c.type).__name__.upper()[:4]
            ) or _compatible(db["type"], c.type), (table.name, c.name, db["type"], c.type)
        pk = insp.get_pk_constraint(table.name, schema="app")["constrained_columns"]
        assert set(pk) == {c.name for c in table.primary_key.columns}, table.name
    eng.dispose()


def _compatible(db_type, mirror_type) -> bool:
    pairs = {
        ("TIMESTAMP", "DATETIME"),
        ("DOUBLE_PRECISION", "DOUBLE"),
        ("DOUBLE PRECISION", "DOUBLE"),
        ("VARCHAR", "TEXT"),
    }
    return (type(db_type).__name__.upper(), type(mirror_type).__name__.upper()) in pairs


def test_every_history_table_is_protected(pg_url):
    eng = _engine(pg_url)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'app' AND NOT t.tgisinternal"
            )
        ).all()
    triggers: dict[str, set[str]] = {}
    for rel, name in rows:
        triggers.setdefault(rel, set()).add(name)
    for t in schema.HISTORY:
        assert f"{t}_insert_only" in triggers.get(t, set()), t
        assert f"{t}_no_truncate" in triggers.get(t, set()), t
    for t in schema.GUARDED:
        assert f"{t}_guard" in triggers.get(t, set()), t
    assert "submissions_deadline" in triggers["submissions"]
    assert "rounds_set_once" in triggers["rounds"]
    assert "entries_set_once" in triggers["entries"]
    eng.dispose()


def test_runtime_role_privileges(pg_url):
    eng = _engine(pg_url)
    with eng.connect() as conn:

        def can(table, priv):
            return conn.execute(
                text("SELECT has_table_privilege('diski9_app', :t, :p)"),
                {"t": f"app.{table}", "p": priv},
            ).scalar()

        for t in schema.HISTORY:
            assert can(t, "INSERT") and can(t, "SELECT"), t
            assert not can(t, "UPDATE") and not can(t, "DELETE"), t
            assert not can(t, "TRUNCATE"), t
        for t in schema.PROJECTION:
            assert can(t, "UPDATE") and can(t, "DELETE"), t
        for t in schema.APPEND_PURGE:
            assert can(t, "INSERT") and can(t, "DELETE") and not can(t, "UPDATE"), t
        for t in schema.MIGRATION_ONLY:  # app_0008: schedules change only via migrations
            assert can(t, "SELECT"), t
            assert not (can(t, "INSERT") or can(t, "UPDATE") or can(t, "DELETE")), t
    eng.dispose()
