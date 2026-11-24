"""Phase 6C.6 Stage F2: offline full-week rehearsal on provably isolated targets
(safeguard C), and the isolation harness's own refusals.

SIMULATED OFFLINE REHEARSAL: a disposable PostgreSQL database created (and dropped)
by the harness, a temporary football store, mock API-Football transports, the week
clock seam of the E.1a/E.1b tests and a compressed settlement world. Nothing here is
real-clock evidence (Q-14): S-02 finalisation timing is exercised with a zero-hour
correction window only, and genuine finalisation evidence needs real elapsed time.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from svc_helpers import principal
from test_backend_prepare import builder, place_clock
from test_backend_refresh import FRI_0420, LEAGUES, REFRESH, Api, run, sweep
from test_backend_scheduler import BASE, FakeProvider, after, status, world

from diski9 import cli
from diski9.backend.auth.permissions import AuthorizationError
from diski9.backend.db import BackendDatabaseSettings, db_now, make_app_engine, migrate, transaction
from diski9.backend.db.schema import audit_log, rounds
from diski9.backend.jobs import prepare, refresh, tick
from diski9.backend.services import rounds as svc
from diski9.backend.services.rounds import SYSTEM
from diski9.backup.isolation import (
    MARKER_TABLE,
    REHEARSAL_LABEL,
    DisposableDatabase,
    DisposableStore,
    IsolationError,
    no_network,
)
from diski9.db import make_engine, upgrade
from tests.factories import seed_competition


@pytest.fixture
def target(pg_url):
    db = DisposableDatabase.create(pg_url, "f2reh")
    db.verify()
    migrate.upgrade(db.url)
    eng = make_app_engine(BackendDatabaseSettings(environment="test"), url=db.url)
    try:
        yield db, eng
    finally:
        eng.dispose()
        db.drop()


@pytest.fixture
def football(tmp_path):
    s = DisposableStore.create(tmp_path)
    upgrade(s.url)
    eng = make_engine(s.url)
    with eng.begin() as c:
        for cid in LEAGUES:
            seed_competition(c, cid, name=f"League {cid}")
    eng.dispose()
    yield s
    s.remove()


def _cli(capsys, *argv) -> tuple[int, str]:
    rc = cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out + out.err


def test_offline_full_week_rehearsal(target, football, monkeypatch, capsys, tmp_path):
    db, eng = target
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    monkeypatch.setenv("DISKI9_APP_ENVIRONMENT", "test")
    with no_network():
        # 1. preparation: Tuesday draft (SYSTEM), Friday sweeps, readiness with data label
        week = place_clock(monkeypatch, eng, 12)
        api = Api(week)
        run(eng, api, football.url)
        db.verify()
        draft = _round(eng, week.code)
        assert draft.status == "draft" and draft.published_at is None
        week = place_clock(monkeypatch, eng, FRI_0420)
        for _ in range(3):
            run(eng, api, football.url)
            if sweep(eng, week).state == "complete":
                break
        assert sweep(eng, week).state == "complete"
        with transaction(eng) as conn:
            label = refresh.data_label(refresh.latest_closed(conn, week.code))
        assert label.startswith("complete@")
        st = prepare.preparation_status(eng, REFRESH)
        assert st.state in ("draft_ready", "draft_not_ready") and draft.status == "draft"
        # 2. publication by an authenticated human operator, never by SYSTEM
        with transaction(eng) as conn:
            now = db_now(conn)
            config = svc.round_config(conn, draft.id)  # the draft's own configuration
        snap = builder()(week.code, week.window_start, week.window_end, now, config)
        with pytest.raises(AuthorizationError):
            svc.publish_round(eng, SYSTEM, draft.id, snap, source="football-db",
                              expected_fingerprint=snap.fingerprint)  # fmt: skip
        op = principal(eng, role="operator")
        svc.publish_round(eng, op, draft.id, snap, source="football-db",
                          expected_fingerprint=snap.fingerprint)  # fmt: skip
        with transaction(eng) as conn:
            pub = conn.execute(sa.select(audit_log).where(
                audit_log.c.action == "round.publish")).one()  # fmt: skip
        assert pub.actor_user_id == op.user_id and pub.after["fingerprint"] == snap.fingerprint
        assert _round(eng, week.code).status == "open"
        # 3. lifecycle on a compressed settlement world: lock, results (mock), settle,
        #    S-02 finalisation (correction window 0), weekly results, championships
        w = world(eng, entries=5, deadline_in=3, cutoff_after=8)
        fake = FakeProvider()
        fake.add(w)
        after(eng, w["deadline"])
        tick(eng, BASE, provider_factory=lambda: fake)
        assert status(eng, w["round"]) == "settling"
        after(eng, w["cutoff"])
        for _ in range(4):
            tick(eng, BASE, provider_factory=lambda: fake)
            if status(eng, w["round"]) == "final":
                break
        assert status(eng, w["round"]) == "final"
        assert _round(eng, week.code).status == "open"  # the published round is untouched
        db.verify()
        # 4. evidence pack (the design's commands), labelled simulated
        import diski9.settlement_cli as sc

        # the evidence commands read the target from the environment; the isolation
        # checks (which refuse any configured database) run outside this block. The
        # operator commands use the authenticated test principal (password checks are
        # covered by the S-07 suites).
        with monkeypatch.context() as m:
            m.setenv("DISKI9_APP_DATABASE_URL", db.url)
            m.setattr(sc, "_principal", lambda engine, email, who="Operator": op)
            outputs = _evidence(capsys, evidence)
        db.verify()
        assert outputs["competition_verify.txt"][0] == 0, outputs["competition_verify.txt"][1]
        assert "consistent" in outputs["competition_verify.txt"][1]
        assert json.loads(outputs["ops_status.json"][1])["environment"] == "test"
        bdir = tmp_path / "store-backups"
        rc, out = _cli(capsys, "--database-url", football.url, "backup", "store", "--out",
                       str(bdir))  # fmt: skip
        assert rc == 0, out
        bfile = next(bdir.glob("diski9-store-*.sqlite"))
        rc, out = _cli(capsys, "--database-url", football.url, "restore", "store", "--from",
                       str(bfile), "--to", str(tmp_path / "drill.sqlite"), "--purpose",
                       "drill")  # fmt: skip
        assert rc == 0, out
        (evidence / "README.txt").write_text(REHEARSAL_LABEL + "\n")
    for f in evidence.iterdir():
        text = f.read_text()
        assert "SIMULATED OFFLINE REHEARSAL" in text and "Not real-clock evidence" in text
        assert db.url not in text and str(football.folder) not in text
    assert api.calls and all(p in ("status", "fixtures", "odds") for p, _ in api.calls)


EVIDENCE = {
    "ops_status.json": ("ops", "status", "--json"),
    "ops_check.txt": ("ops", "check"),
    "ops_jobs.txt": ("ops", "jobs", "--limit", "50"),
    "competition_verify.txt": ("competition", "verify"),
    "round_list.txt": ("round", "list"),
}


def _evidence(capsys, folder: Path) -> dict:
    out = {}
    for name, argv in EVIDENCE.items():
        rc, text = _cli(capsys, *argv)
        out[name] = (rc, text)
        if name.endswith(".json"):
            (folder / name).write_text(json.dumps({"label": REHEARSAL_LABEL,
                                                   "output": json.loads(text)}, indent=2))  # fmt: skip
        else:
            (folder / name).write_text(f"# {REHEARSAL_LABEL}\n{text}")
    return out


def _round(eng, code):
    with transaction(eng) as conn:
        return conn.execute(sa.select(rounds).where(rounds.c.code == code)).one()


# ------------------------------------------------------------------ isolation refusals
def test_production_is_refused_before_anything_is_created(pg_url, monkeypatch):
    monkeypatch.setenv("DISKI9_APP_ENVIRONMENT", "production")
    with pytest.raises(IsolationError, match="production"):
        DisposableDatabase.create(pg_url, "f2iso")
    with pytest.raises(IsolationError, match="production"):
        DisposableStore.create()


def test_protected_configured_and_foreign_targets_are_refused(pg_url, monkeypatch):
    for name in ("diski9", "diski9_6c5_acceptance", "diski9_f1_e2e", "diski9_f2_e2e",
                 "diski9_f2_e2e_nochamp"):  # fmt: skip
        with pytest.raises(IsolationError):
            DisposableDatabase(pg_url, name, "x").verify()
    with pytest.raises(IsolationError, match="not a disposable database name"):
        DisposableDatabase(pg_url, "my_real_data", "x").verify()
    # a _test name alone is not enough: the configured database is refused
    monkeypatch.setenv("DISKI9_APP_DATABASE_URL",
                       "postgresql+psycopg://u@127.0.0.1:5432/diski9_live_copy_test")  # fmt: skip
    with pytest.raises(IsolationError, match="configured competition database"):
        DisposableDatabase(pg_url, "diski9_live_copy_test", "x").verify()
    # hosted servers are refused, whatever the name
    with pytest.raises(IsolationError, match="loopback"):
        DisposableDatabase.create("postgresql+psycopg://u:p@db.example.org:5432/x", "f2iso")


def test_an_existing_database_is_never_adopted_or_dropped(pg_url):
    """A database the harness did not create (here: one with a plausible name and
    real tables) fails verification, so neither setup nor teardown touches it."""
    from sqlalchemy import create_engine, pool
    from sqlalchemy.engine import make_url

    name = "diski9_f2pre_existing_test"
    admin = create_engine(make_url(pg_url).set(database="postgres"), poolclass=pool.NullPool,
                          isolation_level="AUTOCOMMIT")  # fmt: skip
    with admin.connect() as c:
        c.execute(sa.text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        c.execute(sa.text(f"CREATE DATABASE {name}"))
    other = create_engine(make_url(pg_url).set(database=name), poolclass=pool.NullPool)
    try:
        with other.begin() as c:
            c.execute(sa.text("CREATE TABLE precious (x int)"))
        forged = DisposableDatabase(pg_url, name, "guessed-token")
        with pytest.raises(IsolationError, match="no disposable marker"):
            forged.verify()
        with pytest.raises(IsolationError):
            forged.drop()
        with other.begin() as c:  # a planted marker with another token is refused too
            c.execute(sa.text(f"CREATE TABLE public.{MARKER_TABLE} (token text, purpose text, "
                              "created_at timestamptz)"))  # fmt: skip
            c.execute(sa.text(f"INSERT INTO public.{MARKER_TABLE} VALUES ('other', 'x', now())"))
        with pytest.raises(IsolationError, match="does not match"):
            forged.drop()
        with other.connect() as c:
            assert c.execute(sa.text("SELECT count(*) FROM precious")).scalar_one() == 0
    finally:
        other.dispose()
        with admin.connect() as c:
            c.execute(sa.text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()


def test_a_created_target_is_unique_marked_and_dropped(pg_url):
    a = DisposableDatabase.create(pg_url, "f2iso")
    b = DisposableDatabase.create(pg_url, "f2iso")
    try:
        assert a.name != b.name and a.token != b.token
        a.verify()
        with pytest.raises(IsolationError):
            DisposableDatabase(pg_url, a.name, b.token).verify()  # another run's token
    finally:
        a.drop()
        b.drop()
    with pytest.raises(IsolationError):
        a.verify()  # gone


def test_store_isolation_refuses_the_live_store(tmp_path, monkeypatch):
    s = DisposableStore.create(tmp_path)
    monkeypatch.setenv("DISKI9_DATABASE_URL", f"sqlite:///{s.path}")
    with pytest.raises(IsolationError, match="live football store"):
        s.verify()
    monkeypatch.delenv("DISKI9_DATABASE_URL")
    (s.folder / ".diski9-disposable").write_text("tampered")
    with pytest.raises(IsolationError, match="marker"):
        s.remove()
    assert s.folder.exists()
    from diski9.db.engine import PROJECT_ROOT

    with pytest.raises(IsolationError, match="data folder|live football store"):
        DisposableStore(PROJECT_ROOT / "data", "x").verify()


def test_no_network_allows_only_loopback_and_mock_transports(pg_url):
    with no_network():
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("192.0.2.1", 443), timeout=1)
        with pytest.raises(httpx.ConnectError):
            httpx.get("https://v3.football.api-sports.io/status", timeout=2, trust_env=False)
        mock = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        assert mock.get("https://v3.football.api-sports.io/status").status_code == 200
        eng = sa.create_engine(pg_url, poolclass=sa.pool.NullPool)
        with eng.connect() as c:
            assert c.execute(sa.text("SELECT 1")).scalar_one() == 1
        eng.dispose()
    assert os.environ.get("DISKI9_APP_ENVIRONMENT") != "production"
    assert Path(__file__).exists()
