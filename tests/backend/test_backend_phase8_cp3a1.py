"""Phase 8 CP3A-1 with accounts enabled (real PostgreSQL, mock identity provider):
the new routes and the redirects of old addresses behave the same for guests and
signed-in participants, the redirect runs after the account hooks (the session is
kept, never cleared), and signing in from the builder returns to Portfolio Build."""

from __future__ import annotations

import pytest
from auth_helpers import FakeProvider, make_settings
from test_backend_auth_web import ORIGIN, PASSWORD, cookie, post, register

from diski9.app import ScreenerData, create_app
from diski9.backend.auth.web import AuthRuntime
from diski9.db import make_engine, upgrade

PAGES = ("/", "/lab", "/challenge/me", "/leaderboards", "/learn")


@pytest.fixture
def store(tmp_path):
    url = f"sqlite:///{tmp_path / 'store.sqlite'}"
    upgrade(url)
    eng = make_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def server(engine, store, provider):
    rt = AuthRuntime.create(engine, make_settings(), provider)
    srv = create_app(ScreenerData(store), auth=rt).server
    srv.config["TESTING"] = True
    return srv


def _check_routes(client):
    for path in PAGES:
        r = client.get(path)
        assert r.status_code == 200, path
        assert "Max-Age=0" not in r.headers.get("Set-Cookie", ""), path  # session kept
    for old, new in (("/challenge", "/"), ("/?fixture=9", "/lab?fixture=9")):
        r = client.get(old)
        assert r.status_code == 302 and r.headers["Location"] in (new, "http://localhost" + new)
        assert "Max-Age=0" not in r.headers.get("Set-Cookie", "")


def test_routes_for_guest_and_signed_in_participant(server, provider):
    guest = server.test_client()
    _check_routes(guest)
    assert cookie(guest) is None
    member = server.test_client()
    register(member, provider)
    token = cookie(member)
    assert token
    _check_routes(member)
    assert cookie(member) == token  # navigating and redirects never rotate or drop it
    menu = member.get("/_dash-layout").get_data(as_text=True)
    assert "Sign out" in menu and '"Portfolio Build"' in menu


def test_sign_in_from_the_builder_returns_to_portfolio_build(server, provider):
    """The builder's guest "Sign in to confirm" link now carries ``next=/``; an
    onboarded participant signing in from it lands on Portfolio Build."""
    email = register(server.test_client(), provider)  # onboarded on another device
    c = server.test_client()
    r = post(c, "/auth/sign-in?next=/", {"email": email, "password": PASSWORD}, headers=ORIGIN)
    assert r.status_code == 303
    assert r.headers["Location"] in ("/", "http://localhost/")
