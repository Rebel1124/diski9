"""Phase 6C.6 Stage F2: backup and restore records, backup-health monitoring with
truthful evidence levels (safeguard B), the provider hold after a competition-
database restore (safeguard D), scheduler recovery from a restored dump, and the
refresh restore-awareness rule. Isolated PostgreSQL databases, temporary SQLite
football stores, mock providers; no live calls."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from auth_helpers import FakeProvider as FakeAuth
from champ_helpers import drop, isolated_engine
from test_backend_refresh import FRI_0420, Api, run, sweep
from test_backend_refresh import store as store  # noqa: F401 - fixture
from test_backend_scheduler import BASE, FakeProvider, after, world
from test_backend_settlement_ops import auth, linked

from diski9 import cli, ops_cli
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import audit_log, job_runs
from diski9.backend.jobs import prepare, refresh, tick
from diski9.backend.ops import OpsConfig, Severity, collect, evaluate
from diski9.backend.ops.backups import evidence_lines
from diski9.backup import records
from diski9.backup.store import backup_store
from diski9.db import make_engine, upgrade

ON = OpsConfig(backup_expected=True)


@pytest.fixture
def db(pg_url, request):
    name = f"diski9_bk_{request.node.name[:33].lower()}_test"
    eng, url = isolated_engine(pg_url, name)
    try:
        yield eng, url
    finally:
        eng.dispose()
        drop(pg_url, name)


@pytest.fixture
def live(tmp_path):
    (tmp_path / "var").mkdir()
    url = f"sqlite:///{tmp_path / 'var' / 'diski9.sqlite'}"
    upgrade(url)
    make_engine(url).dispose()
    return tmp_path / "var" / "diski9.sqlite"


def snap(eng):
    return collect(eng, environment="test", finalise_warning=timedelta(hours=6))


def found(eng, ops=ON, jobs=None):
    return {(f.code, f.subject): f for f in evaluate(snap(eng), ops, jobs)}


def rec(eng, job, args, *, age=timedelta(0), ok=True):
    """A record dated ``age`` ago (completed-row insert, as the commands write)."""
    with transaction(eng) as conn:
        now = db_now(conn)
        return conn.execute(sa.insert(job_runs).values(
            job=job, scope="", args=args, started_at=now - age, finished_at=now - age,
            status="succeeded" if ok else "failed", api_requests=0).returning(job_runs.c.id)
        ).scalar_one()  # fmt: skip


def main(capsys, monkeypatch, url, *argv):
    monkeypatch.setenv("DISKI9_APP_DATABASE_URL", url)
    rc = cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out + out.err


# ------------------------------------------------------------------ monitoring
def test_backup_monitoring_is_off_by_default(db):
    eng, _ = db
    f = found(eng, OpsConfig())
    assert ("backup_monitoring_off", "backup") in f
    assert f[("backup_monitoring_off", "backup")].severity == Severity.INFO
    assert not [k for k in f if k[0].startswith(("backup_store", "backup_postgres", "offhost"))]


def test_monitoring_on_with_nothing_recorded_reports_every_gap(db):
    eng, _ = db
    f = found(eng)
    for code, subject in (("backup_store_stale", "football_store"),
                          ("backup_postgres_stale", "postgres"),
                          ("backup_offhost_stale", "offhost")):  # fmt: skip
        assert f[(code, subject)].severity == Severity.CRITICAL
        assert "no " in f[(code, subject)].message
    assert f[("offhost_restore_unverified", "offhost")].severity == Severity.WARNING
    assert "NOT verified" in f[("offhost_restore_unverified", "offhost")].message


def test_cli_records_each_evidence_level_truthfully(db, live, tmp_path, capsys, monkeypatch):
    eng, url = db
    monkeypatch.chdir(tmp_path)
    bdir = tmp_path / "backups"
    rc, out = main(capsys, monkeypatch, url, "--database-url", f"sqlite:///{live}", "backup",
                   "store", "--out", str(bdir))  # fmt: skip
    assert rc == 0 and "recorded as ops.backup_store" in out
    f = found(eng)
    assert ("backup_store_stale", "football_store") not in f  # levels 1-2 established
    assert ("backup_offhost_stale", "offhost") in f  # level 3 is NOT implied by a backup
    assert ("offhost_restore_unverified", "offhost") in f  # nor level 4
    dump = tmp_path / "diski9-competition.dump"
    dump.write_bytes(b"PGDMP" + b"\x01" * 100)
    rc, out = main(capsys, monkeypatch, url, "backup", "record", "--kind", "postgres",
                   "--file", str(dump))  # fmt: skip
    assert rc == 0 and "proven restorable only by a restore drill" in out
    assert ("backup_postgres_stale", "postgres") not in found(eng)
    bfile = next(bdir.glob("diski9-store-*.sqlite"))
    rc, out = main(capsys, monkeypatch, url, "backup", "record", "--kind", "offhost-copy",
                   "--file", str(bfile), "--label", "second-box")  # fmt: skip
    assert rc == 0 and "REPORTED (not verified by Diski 9)" in out
    f = found(eng)
    assert ("backup_offhost_stale", "offhost") not in f
    assert ("offhost_restore_unverified", "offhost") in f  # a copy is not a restore
    # a drill from an off-host copy whose content matches the recorded backup: level 4
    rc, out = main(capsys, monkeypatch, url, "--database-url", f"sqlite:///{live}", "restore",
                   "store", "--from", str(bfile), "--to", str(tmp_path / "drill.sqlite"),
                   "--purpose", "drill", "--source-origin", "offhost")  # fmt: skip
    assert rc == 0 and "recorded as ops.restore_drill" in out
    f = found(eng)
    assert not [k for k in f if k[1] in ("football_store", "postgres", "offhost")]
    lines = "\n".join(evidence_lines(snap(eng), ON))
    assert "3 off-host copy (reported, not verified by Diski 9)" in lines
    assert "origin operator-declared; matches a recorded backup: yes" in lines
    assert ("store_restored", "football_store") not in f  # a drill is not a recovery


def test_a_drill_not_matching_any_recorded_backup_is_not_restore_evidence(db, live, tmp_path,
                                                                          capsys, monkeypatch):  # fmt: skip
    eng, url = db
    monkeypatch.chdir(tmp_path)
    res = backup_store(live, tmp_path / "unrecorded")  # never recorded in this database
    rc, _ = main(capsys, monkeypatch, url, "--database-url", f"sqlite:///{live}", "restore",
                 "store", "--from", str(res.file), "--to", str(tmp_path / "d.sqlite"),
                 "--purpose", "drill", "--source-origin", "offhost")  # fmt: skip
    assert rc == 0
    f = found(eng)
    assert ("offhost_restore_unverified", "offhost") in f
    assert "matches a recorded backup: no" in "\n".join(evidence_lines(snap(eng), ON))


def test_stale_and_failed_backups(db):
    eng, _ = db
    for job in (records.BACKUP_STORE, records.BACKUP_POSTGRES, records.BACKUP_OFFHOST):
        rec(eng, job, {"sha256_prefix": "a" * 16}, age=timedelta(hours=30))
    f = found(eng)
    assert f[("backup_store_stale", "football_store")].severity == Severity.WARNING
    assert f[("backup_postgres_stale", "postgres")].severity == Severity.WARNING
    assert f[("backup_offhost_stale", "offhost")].severity == Severity.WARNING
    rec(eng, records.BACKUP_STORE, {"verified": False}, ok=False)
    f = found(eng)
    assert f[("backup_failed", "football_store")].severity == Severity.WARNING
    for job in (records.BACKUP_STORE, records.BACKUP_POSTGRES, records.BACKUP_OFFHOST):
        rec(eng, job, {"sha256_prefix": "b" * 16}, age=timedelta(hours=60))
    # newer successful records exist (30 h); a 60 h-old record does not change "latest"
    assert found(eng)[("backup_store_stale", "football_store")].severity == Severity.WARNING
    rec(eng, records.RESTORE_DRILL, {"source_origin": "offhost", "store": "football",
                                     "matches_recorded_backup": True}, age=timedelta(days=40))  # fmt: skip
    assert ("restore_drill_stale", "offhost") in found(eng)


def test_postgres_record_refuses_a_non_dump_and_needs_a_database(db, tmp_path, capsys,
                                                                 monkeypatch):  # fmt: skip
    eng, url = db
    monkeypatch.chdir(tmp_path)
    junk = tmp_path / "junk.dump"
    junk.write_bytes(b"not a dump")
    rc, out = main(capsys, monkeypatch, url, "backup", "record", "--kind", "postgres",
                   "--file", str(junk))  # fmt: skip
    assert rc == 1 and "not a pg_dump" in out
    assert found(eng)[("backup_failed", "postgres")].severity == Severity.WARNING
    monkeypatch.delenv("DISKI9_APP_DATABASE_URL")
    rc = cli.main(["backup", "record", "--kind", "postgres-restore", "--file", str(junk)])
    assert rc == 2  # evidence that must be recorded is never silently dropped


# ------------------------------------------------------------------ safeguard D
def _restore_pg(capsys, monkeypatch, url, tmp_path):
    dump = tmp_path / "competition.dump"
    dump.write_bytes(b"PGDMP" + b"\x02" * 64)
    return main(capsys, monkeypatch, url, "backup", "record", "--kind", "postgres-restore",
                "--file", str(dump))  # fmt: skip


def test_provider_hold_after_restore_survives_scheduler_restarts(db, tmp_path, capsys,
                                                                monkeypatch):  # fmt: skip
    eng, url = db
    monkeypatch.chdir(tmp_path)
    w = world(eng)
    fake = FakeProvider()
    fake.add(w)
    rc, out = _restore_pg(capsys, monkeypatch, url, tmp_path)
    assert rc == 0 and "HELD" in out
    after(eng, w["deadline"])
    called = []

    def factory():
        called.append(1)
        return fake

    for _ in range(3):  # ordinary restarts: every tick re-reads the hold
        r = tick(eng, BASE, provider_factory=factory)
        assert r.status == "completed"
        assert any("provider calls are held" in n for n in r.notes)
    assert called == [] and fake.requests_made == 0
    with transaction(eng) as conn:
        ticks = conn.execute(sa.select(job_runs.c.args).where(
            job_runs.c.job == "scheduler.tick").order_by(job_runs.c.id)).scalars().all()  # fmt: skip
        ledger = conn.execute(sa.select(sa.func.count()).select_from(job_runs).where(
            job_runs.c.job == "scheduler.provider")).scalar_one()  # fmt: skip
    assert all(t["provider_calls"] is False for t in ticks if "streams" in t)
    assert ledger == 0
    f = found(eng, OpsConfig())
    assert f[("provider_hold_after_restore", "provider")].severity == Severity.WARNING
    # the hold also covers the E.1b refresh even when it is configured on
    from test_backend_refresh import REFRESH

    r = tick(eng, REFRESH, provider_factory=factory)
    assert r.status == "completed" and called == []


def test_only_an_authenticated_operator_lifts_the_hold(db, tmp_path, capsys, monkeypatch):
    eng, url = db
    monkeypatch.chdir(tmp_path)
    _restore_pg(capsys, monkeypatch, url, tmp_path)
    fp = FakeAuth()
    op_addr, op_uid = linked(eng, fp, role="operator")
    user_addr, _ = linked(eng, fp)
    args = SimpleNamespace(operator=op_addr, reason="reviewed rounds, entries and quota")

    def resume(a, answer="RESUME"):
        return ops_cli._provider_resume(
            a, engine=eng, authenticate=lambda e, addr: auth(e, fp, addr),
            confirm=lambda prompt: answer)  # fmt: skip

    assert resume(SimpleNamespace(operator=op_addr, reason="short")) == 2
    assert resume(SimpleNamespace(operator=user_addr, reason=args.reason)) == 2  # participant
    assert resume(args, answer="yes") == 1  # typed confirmation required
    with transaction(eng) as conn:
        assert records.provider_hold(conn) is not None
    assert resume(args) == 0
    with transaction(eng) as conn:
        assert records.provider_hold(conn) is None
        a = conn.execute(sa.select(audit_log).where(
            audit_log.c.action == "ops.provider_resume")).one()  # fmt: skip
    assert a.actor_user_id == op_uid and a.actor_role == "operator"
    # a later restore places a new hold
    _restore_pg(capsys, monkeypatch, url, tmp_path)
    with transaction(eng) as conn:
        assert records.provider_hold(conn) is not None


def test_resume_lets_the_scheduler_use_the_provider_again(db, tmp_path, capsys, monkeypatch):
    eng, url = db
    monkeypatch.chdir(tmp_path)
    w = world(eng)
    fake = FakeProvider()
    fake.add(w)
    _restore_pg(capsys, monkeypatch, url, tmp_path)
    fp = FakeAuth()
    op_addr, _ = linked(eng, fp, role="operator")
    assert (
        ops_cli._provider_resume(
            SimpleNamespace(operator=op_addr, reason="reconciled after the restore drill"),
            engine=eng,
            authenticate=lambda e, a: auth(e, fp, a),
            confirm=lambda p: "RESUME",
        )
        == 0
    )
    after(eng, w["deadline"])
    r = tick(eng, BASE, provider_factory=lambda: fake)
    assert r.status == "completed" and not any("held" in n for n in r.notes)
    tick(eng, BASE, provider_factory=lambda: fake)
    assert fake.requests_made > 0


def test_restored_dump_with_interrupted_steps_recovers_under_stage_d_rules(db, tmp_path, capsys,
                                                                           monkeypatch):  # fmt: skip
    """A dump taken mid-tick restores ``running`` rows of ticks that no longer exist:
    old ones are abandoned, young ones block lifecycle work until they age out
    (unchanged Stage D rules); the provider stays held throughout."""
    eng, url = db
    monkeypatch.chdir(tmp_path)

    def ghost(age, token):
        with transaction(eng) as conn:
            now = db_now(conn)
            tid = conn.execute(sa.insert(job_runs).values(
                job="scheduler.tick", scope="global", args={"run_token": token},
                status="running", started_at=now - age).returning(job_runs.c.id)).scalar_one()  # fmt: skip
            conn.execute(sa.insert(job_runs).values(
                job="scheduler.results", scope="R", args={"tick": tid, "run_token": token},
                status="running", started_at=now - age))  # fmt: skip
        return tid

    old = ghost(timedelta(hours=2), "from-the-dump")
    _restore_pg(capsys, monkeypatch, url, tmp_path)
    r = tick(eng, BASE, provider_factory=lambda: pytest.fail("provider used during the hold"))
    assert r.status == "completed" and any("abandoned" in n for n in r.notes)
    assert any("held" in n for n in r.notes)
    with transaction(eng) as conn:
        st = conn.execute(sa.select(job_runs.c.status).where(job_runs.c.id == old)).scalar_one()
    assert st == "failed"
    ghost(timedelta(minutes=3), "young")
    r = tick(eng, BASE, provider_factory=lambda: pytest.fail("provider used during the hold"))
    assert r.status == "indeterminate"


# ------------------------------------------------------------------ refresh after a restore
def test_sweeps_before_a_store_restore_no_longer_count(db, store, monkeypatch):  # noqa: F811
    eng, _ = db
    w = place(monkeypatch, eng)
    api = Api(w)
    run(eng, api, store)
    run(eng, api, store)
    assert sweep(eng, w).state == "complete"
    with transaction(eng) as conn:
        assert refresh.data_label(refresh.latest_closed(conn, w.code)).startswith("complete@")
    assert refresh.STORE_RESTORE_JOB == records.RESTORE_STORE
    rec(eng, records.RESTORE_STORE, {"store": "football", "target": "restored.sqlite"})
    with transaction(eng) as conn:
        assert refresh.latest_closed(conn, w.code) is None
        assert refresh.data_label(refresh.latest_closed(conn, w.code)) == "none"
    assert sweep(eng, w).state == "none"  # the slot is swept again
    calls = len(api.calls)
    run(eng, api, store)
    run(eng, api, store)
    assert len(api.calls) > calls
    assert sweep(eng, w).state == "complete"
    with transaction(eng) as conn:
        assert refresh.latest_closed(conn, w.code) is not None
    f = found(eng, OpsConfig())
    assert ("store_restored", "football_store") in f


def place(monkeypatch, eng):
    from test_backend_prepare import place_clock

    return place_clock(monkeypatch, eng, FRI_0420)


def test_drill_restores_do_not_affect_refresh(db, store, monkeypatch):  # noqa: F811
    eng, _ = db
    w = place(monkeypatch, eng)
    api = Api(w)
    run(eng, api, store)
    run(eng, api, store)
    rec(eng, records.RESTORE_DRILL, {"store": "football", "source_origin": "local"})
    assert sweep(eng, w).state == "complete"
    with transaction(eng) as conn:
        assert prepare._now(conn) is not None
        assert refresh.latest_closed(conn, w.code) is not None


def test_hold_and_refresh_config_are_unchanged_by_replace():
    """The hold switches provider calls and refresh off for one tick only (a copy of
    the configuration), never the operator's settings."""
    from test_backend_refresh import REFRESH

    held = replace(REFRESH, provider_calls=False, prepare_refresh=False)
    assert REFRESH.provider_calls and REFRESH.prepare_refresh
    assert not held.provider_calls and not held.prepare_refresh
    assert held.max_requests_per_day == REFRESH.max_requests_per_day
