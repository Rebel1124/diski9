"""Phase 6C.6 Stage F2: health endpoints with accounts enabled (real PostgreSQL,
mock identity provider). Readiness reports the competition database; the probes
never touch sessions, cookies or the CSRF/origin checks of account routes."""

from __future__ import annotations

import pytest
from auth_helpers import FakeProvider, make_settings
from sqlalchemy import create_engine, pool

from diski9.app import ScreenerData, create_app
from diski9.backend.auth.web import AuthRuntime
from diski9.db import make_engine, upgrade

ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture
def store(tmp_path):
    url = f"sqlite:///{tmp_path / 'store.sqlite'}"
    upgrade(url)
    eng = make_engine(url)
    yield eng
    eng.dispose()


def _client(store, competition_engine):
    rt = AuthRuntime.create(competition_engine, make_settings(), FakeProvider())
    return create_app(ScreenerData(store), auth=rt).server.test_client()


def test_readyz_reports_the_competition_database(engine, store):
    r = _client(store, engine).get("/readyz")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ready",
                            "checks": {"database": "ok", "football_store": "ok"}}  # fmt: skip
    assert "Set-Cookie" not in r.headers


def test_readyz_unavailable_database_is_503_without_details(store, caplog):
    dead = create_engine("postgresql+psycopg://nobody:planted-secret-pw@127.0.0.1:1/nodb_test",
                         poolclass=pool.NullPool)  # fmt: skip
    c = _client(store, dead)
    assert c.get("/healthz").status_code == 200  # liveness does not depend on the database
    r = c.get("/readyz")
    assert r.status_code == 503
    assert r.get_json() == {"status": "not_ready",
                            "checks": {"database": "unavailable", "football_store": "ok"}}  # fmt: skip
    text = r.get_data(as_text=True) + caplog.text
    for leak in ("planted-secret-pw", "nobody", "127.0.0.1", "nodb_test", "psycopg"):
        assert leak not in text


def test_probes_ignore_session_cookies_and_set_none(engine, store):
    """A probe with a (forged) session cookie neither resolves nor clears it: the
    session hooks never see health requests."""
    c = _client(store, engine)
    c.set_cookie(make_settings().session_cookie_name, "forged-token-value", domain="localhost")
    for path in ("/healthz", "/readyz"):
        r = c.get(path)
        assert r.status_code == 200
        assert "Set-Cookie" not in r.headers
    # control: an ordinary route does see the forged cookie and clears it
    assert "Set-Cookie" in c.get("/auth/sign-in").headers


def test_account_routes_keep_their_csrf_and_origin_checks(engine, store):
    """Adding the probes does not loosen authentication: a cross-origin POST to an
    account route is still refused, and a POST to a probe is just 405."""
    c = _client(store, engine)
    assert c.post("/auth/sign-in", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/auth/sign-in", headers=ORIGIN, data={"email": "x"}).status_code == 400
    assert c.post("/readyz", headers={"Origin": "https://evil.example"}).status_code == 405
