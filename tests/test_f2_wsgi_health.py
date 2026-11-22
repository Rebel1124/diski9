"""Phase 6C.6 Stage F2: the shared app factory, the production WSGI entry point and the
health endpoints (guest mode, temporary SQLite football stores; no network)."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from diski9.app.factory import build_app
from diski9.app.health import REQUIRED_STORE_TABLES
from diski9.db import make_engine
from diski9.wsgi import WsgiConfigError, check_store_location

ROOT = Path(__file__).resolve().parents[1]
AUTH_VARS = ("DISKI9_SUPABASE_AUTH_URL", "DISKI9_SUPABASE_PUBLISHABLE_KEY")


@pytest.fixture(autouse=True)
def _guest_mode(monkeypatch, tmp_path):
    for var in AUTH_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # no repository .env is read


def _client(engine):
    return build_app(engine).app.server.test_client()


def _child_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in AUTH_VARS}
    env.update(extra)
    return env


def _rules(server) -> list[str]:
    rules = sorted(f"{r.rule} {sorted(r.methods or ())}" for r in server.url_map.iter_rules())
    return [type(server.wsgi_app).__name__, *rules]


# ------------------------------------------------------------------ /healthz
def test_healthz_is_liveness_only(engine):
    c = _client(engine)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}
    assert r.headers["Cache-Control"] == "no-store"
    assert "Set-Cookie" not in r.headers
    assert c.head("/healthz").status_code == 200


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_health_routes_refuse_unsafe_methods(engine, path, method):
    r = getattr(_client(engine), method)(path)
    assert r.status_code == 405
    assert r.headers["Allow"] == "GET, HEAD"
    assert "Set-Cookie" not in r.headers


# ------------------------------------------------------------------- /readyz
def test_readyz_ready_with_a_migrated_store_and_no_accounts(engine):
    r = _client(engine).get("/readyz")
    assert r.status_code == 200
    assert r.get_json() == {
        "status": "ready",
        "checks": {"database": "not_configured", "football_store": "ok"},
    }
    assert r.headers["Cache-Control"] == "no-store"
    assert "Set-Cookie" not in r.headers


def test_readyz_missing_store_is_not_ready_and_never_creates_the_file(engine, tmp_path):
    """On a fresh worker (no page served yet), a missing store is reported without
    creating an empty database file, and liveness still answers."""
    c = _client(engine)
    store = Path(engine.url.database)
    engine.dispose()
    moved = tmp_path / "moved.sqlite"
    store.rename(moved)
    for side in ("-wal", "-shm"):
        Path(f"{store}{side}").unlink(missing_ok=True)
    r = c.get("/readyz")
    assert r.status_code == 503
    assert r.get_json() == {
        "status": "not_ready",
        "checks": {"database": "not_configured", "football_store": "unavailable"},
    }
    assert not store.exists()
    assert c.get("/healthz").status_code == 200
    assert not store.exists()


def test_readyz_store_without_required_tables_is_not_ready(tmp_path):
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).execute("CREATE TABLE unrelated (x)").connection.close()
    r = _client(make_engine(f"sqlite:///{empty}")).get("/readyz")
    assert r.status_code == 503
    assert r.get_json()["checks"]["football_store"] == "unavailable"


def test_readyz_corrupt_store_is_not_ready_without_details(tmp_path, caplog):
    bad = tmp_path / "corrupt.sqlite"
    bad.write_bytes(b"this is not a database at " + str(tmp_path).encode() * 20)
    r = _client(make_engine(f"sqlite:///{bad}")).get("/readyz")
    assert r.status_code == 503
    body = r.get_data(as_text=True)
    assert str(tmp_path) not in body and "Error" not in body
    assert str(tmp_path) not in caplog.text  # logged by exception type only


def test_health_responses_contain_no_paths_versions_or_urls(engine):
    import diski9

    c = _client(engine)
    for path in ("/healthz", "/readyz"):
        body = c.get(path).get_data(as_text=True)
        assert str(engine.url.database) not in body
        assert "sqlite" not in body.lower() and "postgres" not in body.lower()
        assert getattr(diski9, "__version__", "4.2.0") not in body
        assert set(json.loads(body)) <= {"status", "checks"}


def test_required_tables_exist_in_the_real_store_schema(engine):
    from sqlalchemy import inspect

    assert set(inspect(engine).get_table_names()) >= REQUIRED_STORE_TABLES


# --------------------------------------------------------- factory and WSGI
def test_factory_builds_the_same_app_as_serve(engine, monkeypatch):
    """``diski9 serve`` goes through the factory (no separate construction)."""
    from diski9 import cli

    calls = {}

    class FakeApp:
        def run(self, **kw):
            calls["run"] = kw

    def fake_build(eng, *, ttl_seconds, tz):
        calls["build"] = (eng, ttl_seconds, tz)
        from diski9.app.factory import BuiltApp

        return BuiltApp(app=FakeApp(), accounts_enabled=False)

    monkeypatch.setattr("diski9.app.factory.build_app", fake_build)
    args = type("A", (), dict(ttl=12.0, tz="UTC", host="127.0.0.1", port=1, debug=False))
    cli.cmd_serve(args, engine)
    assert calls["build"] == (engine, 12.0, "UTC")
    assert calls["run"] == {"host": "127.0.0.1", "port": 1, "debug": False}


def test_store_location_rule():
    check_store_location("sqlite:///data/diski9.sqlite", "development")
    check_store_location("sqlite:////var/lib/diski9/diski9.sqlite", "production")
    check_store_location("postgresql+psycopg://h/db", "production")
    for url in ("sqlite:///data/diski9.sqlite", "sqlite:///:memory:"):
        with pytest.raises(WsgiConfigError):
            check_store_location(url, "production")


def _import_rules(module: str, cwd: Path, env: dict) -> list[str]:
    code = (
        f"import json, sys; sys.path.insert(0, {str(ROOT / 'tools')!r}); import {module} as m; "
        "print(json.dumps([type(m.server.wsgi_app).__name__, *sorted(f'{r.rule} "
        "{sorted(r.methods or ())}' for r in m.server.url_map.iter_rules())]))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True,
                         text=True, timeout=120)  # fmt: skip
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_wsgi_module_and_f3_tool_share_the_factory(engine, tmp_path):
    """``diski9.wsgi`` and ``tools/f3_wsgi.py`` expose exactly the routes the factory
    builds (one construction path), importing without network access."""
    url = f"sqlite:///{engine.url.database}"
    env = _child_env(DISKI9_DATABASE_URL=url, DISKI9_APP_ENVIRONMENT="test",
                     HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9")  # fmt: skip
    expected = _rules(build_app(engine).app.server)
    assert expected[0] == "HealthMiddleware"
    assert _import_rules("diski9.wsgi", tmp_path, env) == expected
    assert _import_rules("f3_wsgi", tmp_path, env) == expected
    src = (ROOT / "tools" / "f3_wsgi.py").read_text()
    assert "create_app" not in src and "AuthRuntime" not in src  # no parallel construction


def test_wsgi_refuses_a_relative_store_in_production(tmp_path):
    env = _child_env(DISKI9_DATABASE_URL="sqlite:///data/diski9.sqlite",
                     DISKI9_APP_ENVIRONMENT="production")  # fmt: skip
    out = subprocess.run([sys.executable, "-c", "import diski9.wsgi"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)  # fmt: skip
    assert out.returncode != 0
    assert "absolute SQLite path" in out.stderr
    assert not (tmp_path / "data").exists()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_gunicorn_serves_the_wsgi_entry_point(engine, tmp_path):
    """Gunicorn (optional ``server`` extra, installed in CI) serves ``diski9.wsgi``
    with two workers: liveness, readiness and the Screener page."""
    gunicorn = Path(sys.executable).with_name("gunicorn")
    assert gunicorn.exists(), "install the optional extra: uv sync --extra server"
    port = _free_port()
    env = _child_env(DISKI9_DATABASE_URL=f"sqlite:///{engine.url.database}",
                     DISKI9_APP_ENVIRONMENT="test")  # fmt: skip
    proc = subprocess.Popen(
        [str(gunicorn), "diski9.wsgi:server", "--workers", "2", "--bind", f"127.0.0.1:{port}",
         "--timeout", "60"],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )  # fmt: skip
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 60
        while True:
            try:
                r = httpx.get(f"{base}/healthz", timeout=2, trust_env=False)
                break
            except httpx.TransportError:
                assert proc.poll() is None, proc.stdout.read().decode()[-2000:]
                assert time.monotonic() < deadline, "gunicorn did not start"
                time.sleep(0.3)
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        ready = httpx.get(f"{base}/readyz", timeout=5, trust_env=False)
        assert ready.status_code == 200 and ready.json()["status"] == "ready"
        page = httpx.get(f"{base}/", timeout=30, trust_env=False)
        assert page.status_code == 200 and "Diski 9" in page.text
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
