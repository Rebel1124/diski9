"""Web layer (Flask routes, request hooks, guards, Dash shell) on REAL PostgreSQL
with a MOCK identity provider (``FakeProvider``): registration, sign-in, CSRF,
Origin checks, session fixation and rotation, sign-out, re-authentication, open
redirects, account isolation, guest access and privilege checks."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from auth_helpers import FakeProvider, csrf_from, make_settings
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select, text, update

from diski9.backend.auth import accounts as acct
from diski9.backend.auth import privileged as pv
from diski9.backend.auth.permissions import Capability
from diski9.backend.auth.sessions import revoke_all_sessions
from diski9.backend.auth.web import (
    AuthRuntime,
    authorize_callback,
    current_principal,
    init_auth,
    require,
)
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import app_sessions, users

ORIGIN = {"Origin": "http://localhost"}
PASSWORD = "Correct-Horse-9"


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def app(engine, provider):
    server = Flask("auth-test")
    settings = make_settings()
    rt = AuthRuntime.create(engine, settings, provider)
    init_auth(server, rt)

    @server.route("/test/whoami")
    def whoami():
        p = current_principal()
        return {
            "user": str(p.user_id) if p.user_id else None,
            "onboarded": p.onboarded,
            "roles": sorted(p.roles),
        }

    @server.route("/test/void-round", methods=["GET", "POST"])
    @require(Capability.VOID_ROUND)
    def void_round():
        return "voided"

    @server.route("/test/publish")
    @require(Capability.PUBLISH_ROUND)
    def publish():
        return "published"

    @server.route("/test/feature")
    def feature():
        from diski9.backend.auth.permissions import Forbidden, require_feature

        try:
            require_feature(current_principal(), "lucy.research")
        except Forbidden:
            return "forbidden", 403
        return "feature"

    @server.route("/test/echo", methods=["POST"])
    def echo():
        return {"user": str(current_principal().user_id) if current_principal().user_id else None}

    @server.route("/test/callback")
    def callback():
        from dash.exceptions import PreventUpdate

        try:
            authorize_callback(Capability.CORRECT_RESULT)
        except PreventUpdate:
            return "prevented", 204
        return "allowed"

    server.config["TESTING"] = True

    class OwnAddressClient(FlaskClient):
        """Each test client gets its own address so rate limits do not leak between
        tests (they are tested on purpose in test_sign_in_rate_limit)."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.environ_base["REMOTE_ADDR"] = f"198.51.100.{uuid.uuid4().int % 250 + 1}"

    server.test_client_class = OwnAddressClient
    return server


@pytest.fixture
def client(app):
    return app.test_client()


def post(client, path, data=None, *, page=None, headers=ORIGIN, **kw):
    """POST a form with the CSRF token read from ``page`` (default: ``path``)."""
    html = client.get(page or path).get_data(as_text=True)
    form = {"csrf_token": csrf_from(html), **(data or {})}
    return client.post(path, data=form, headers=headers, **kw)


def register(client, provider, email=None, username=None):
    email = email or f"{uuid.uuid4().hex[:8]}@example.com"
    provider.add_user(email, PASSWORD)
    r = post(client, "/auth/sign-in", {"email": email, "password": PASSWORD})
    assert r.status_code == 303, r.get_data(as_text=True)[:300]
    r = post(
        client,
        "/account/welcome",
        {
            "username": username or f"user{uuid.uuid4().hex[:8]}",
            "terms_version": "beta-2026-11",
            "age_confirmed": "yes",
            "accept_terms": "yes",
        },
    )
    assert r.status_code == 303 and "/account" in r.headers["Location"]
    return email


def cookie(client, name="d9_session"):
    c = client.get_cookie(name)
    return c.value if c else None


# ---------------------------------------------------------------- registration
def test_sign_up_never_reveals_whether_an_email_exists(client, provider):
    provider.add_user("taken@example.com", PASSWORD)
    a = post(client, "/auth/sign-up", {"email": "taken@example.com", "password": "Another-Pass-1"})
    b = post(client, "/auth/sign-up", {"email": "fresh@example.com", "password": "Another-Pass-1"})
    assert a.status_code == b.status_code == 303
    assert a.headers["Location"] == b.headers["Location"]


def test_sign_up_validates_input(client):
    r = post(client, "/auth/sign-up", {"email": "not-an-email", "password": "Another-Pass-1"})
    assert r.status_code == 400
    r = post(client, "/auth/sign-up", {"email": "a@example.com", "password": "short"})
    assert r.status_code == 400


def test_email_confirmation_requires_a_click_and_signs_in(client, provider):
    post(client, "/auth/sign-up", {"email": "new@example.com", "password": "Another-Pass-1"})
    th = provider.link_for("new@example.com", "email")
    page = client.get(f"/auth/confirm?token_hash={th}&type=email")
    assert page.status_code == 200 and th in page.get_data(as_text=True)
    assert provider.users["new@example.com"]["confirmed"] is False  # GET consumes nothing
    r = client.post(
        "/auth/confirm",
        data={
            "csrf_token": csrf_from(page.get_data(as_text=True)),
            "token_hash": th,
            "type": "email",
        },
        headers=ORIGIN,
    )
    assert r.status_code == 303 and "/account/welcome" in r.headers["Location"]
    assert cookie(client)
    assert client.get("/test/whoami").json["user"] is not None


def test_reused_or_forged_confirmation_links_fail(client, provider):
    post(client, "/auth/sign-up", {"email": "x@example.com", "password": "Another-Pass-1"})
    th = provider.link_for("x@example.com", "email")
    post(
        client,
        "/auth/confirm",
        {"token_hash": th, "type": "email"},
        page=f"/auth/confirm?token_hash={th}&type=email",
    )
    r = post(
        client,
        "/auth/confirm",
        {"token_hash": th, "type": "email"},
        page=f"/auth/confirm?token_hash={th}&type=email",
    )
    assert r.status_code == 400
    assert client.get("/auth/confirm?token_hash=<script>&type=email").status_code == 400
    assert client.get(f"/auth/confirm?token_hash={th}&type=magiclink").status_code == 400


# ---------------------------------------------------------------- sign-in
def test_invalid_credentials_and_unknown_accounts_look_the_same(client, provider):
    provider.add_user("known@example.com", PASSWORD)
    a = post(client, "/auth/sign-in", {"email": "known@example.com", "password": "wrong-one-1"})
    b = post(client, "/auth/sign-in", {"email": "nobody@example.com", "password": "wrong-one-1"})
    assert a.status_code == b.status_code == 400
    msg = "The email address or password is incorrect."
    assert msg in a.get_data(as_text=True) and msg in b.get_data(as_text=True)
    assert cookie(client) is None


def test_unverified_identity_cannot_sign_in(client, provider):
    provider.add_user("pending@example.com", PASSWORD, confirmed=False)
    r = post(client, "/auth/sign-in", {"email": "pending@example.com", "password": PASSWORD})
    assert r.status_code == 400 and cookie(client) is None


def test_sign_in_rate_limit(client, provider):
    provider.add_user("rl@example.com", PASSWORD)
    codes = [
        post(
            client, "/auth/sign-in", {"email": "rl@example.com", "password": "bad-pass-1"}
        ).status_code
        for _ in range(9)
    ]
    assert codes[-1] == 429


def test_session_cookie_attributes(client, provider):
    provider.add_user("c@example.com", PASSWORD)
    r = post(client, "/auth/sign-in", {"email": "c@example.com", "password": PASSWORD})
    header = r.headers["Set-Cookie"]
    assert "HttpOnly" in header and "SameSite=Lax" in header and "Path=/" in header


def test_production_cookie_uses_host_prefix_and_secure():
    s = make_settings(
        app_environment="production",
        app_site_url="https://diski9.example",
        supabase_auth_url="https://x.supabase.co/auth/v1",
        app_cookie_secure=None,
    )
    assert s.session_cookie_name == "__Host-d9_session" and s.cookie_secure


def test_session_fixation_is_impossible(client, provider):
    client.set_cookie("d9_session", "attacker-chosen-token-value")
    provider.add_user("fix@example.com", PASSWORD)
    post(client, "/auth/sign-in", {"email": "fix@example.com", "password": PASSWORD})
    assert cookie(client) != "attacker-chosen-token-value"


def test_unauthenticated_requests_are_redirected(client):
    r = client.get("/account")
    assert r.status_code == 303 and "/auth/sign-in" in r.headers["Location"]


def test_onboarding_is_required_before_settings(client, provider):
    provider.add_user("on@example.com", PASSWORD)
    post(client, "/auth/sign-in", {"email": "on@example.com", "password": PASSWORD})
    r = client.get("/account")
    assert r.status_code == 303 and "/account/welcome" in r.headers["Location"]


# ---------------------------------------------------------------- CSRF and origin
def test_cross_origin_posts_are_rejected(client, provider):
    register(client, provider)
    r = client.post(
        "/account/privacy", data={"mode": "anonymous"}, headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403


def test_posts_without_csrf_token_are_rejected(client, provider):
    register(client, provider)
    r = client.post("/account/privacy", data={"mode": "anonymous"}, headers=ORIGIN)
    assert r.status_code == 400
    r = client.post(
        "/account/privacy", data={"mode": "anonymous", "csrf_token": "0" * 64}, headers=ORIGIN
    )
    assert r.status_code == 400


def test_cookie_bearing_posts_need_an_origin(client, provider):
    register(client, provider)
    r = client.post("/_dash-update-component", json={}, headers={})
    assert r.status_code == 403  # Dash callbacks included


def test_csrf_token_is_bound_to_the_session(app, provider):
    a, b = app.test_client(), app.test_client()
    register(a, provider)
    register(b, provider)
    token_a = csrf_from(a.get("/account").get_data(as_text=True))
    r = b.post(
        "/account/privacy", data={"mode": "anonymous", "csrf_token": token_a}, headers=ORIGIN
    )
    assert r.status_code == 400


# ---------------------------------------------------------------- open redirects
@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example", "/\\evil.example"])
def test_sign_in_never_redirects_off_site(client, provider, target):
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    register(client, provider, email=email)
    client.post(
        "/auth/sign-out",
        data={"csrf_token": csrf_from(client.get("/auth/sign-out").get_data(as_text=True))},
        headers=ORIGIN,
    )
    r = post(
        client,
        f"/auth/sign-in?next={target}",
        {"email": email, "password": PASSWORD, "next": target},
    )
    assert r.headers["Location"] in ("/", "http://localhost/")


# ---------------------------------------------------------------- sign-out
def test_sign_out_revokes_session_clears_cookie_and_browser_state(client, provider, engine):
    register(client, provider)
    token = cookie(client)
    r = post(client, "/auth/sign-out")
    assert r.status_code == 200
    assert r.headers.get("Clear-Site-Data") == '"storage"'
    assert 'data-clear-state="1"' in r.get_data(as_text=True)
    assert cookie(client) is None
    client.set_cookie("d9_session", token)  # replaying the old cookie does not work
    assert client.get("/test/whoami").json["user"] is None


def test_sign_out_everywhere_ends_other_devices(app, provider):
    a, b = app.test_client(), app.test_client()
    email = register(a, provider)
    post(b, "/auth/sign-in", {"email": email, "password": PASSWORD})
    assert b.get("/test/whoami").json["user"]
    post(a, "/auth/sign-out-everywhere", page="/account")
    assert b.get("/test/whoami").json["user"] is None


def test_suspended_account_session_stops_working(client, provider, engine):
    register(client, provider)
    uid = client.get("/test/whoami").json["user"]
    with transaction(engine) as conn:
        conn.execute(update(users).where(users.c.id == uid).values(status="suspended"))
    assert client.get("/test/whoami").json["user"] is None
    assert client.get("/account").status_code == 303


# ---------------------------------------------------------------- re-authentication
def test_password_change_requires_recent_reauthentication_and_rotates(client, provider, engine):
    email = register(client, provider)
    h_before = client.get("/test/whoami").json["user"]
    with transaction(engine) as conn:  # make the sign-in 20 minutes old
        conn.execute(
            update(app_sessions)
            .where(app_sessions.c.revoked_at.is_(None))
            .values(reauthenticated_at=db_now(conn) - timedelta(minutes=20))
        )
    r = client.get("/auth/password")
    assert r.status_code == 303 and "/auth/reauthenticate" in r.headers["Location"]
    old_cookie = cookie(client)
    r = post(
        client,
        "/auth/reauthenticate?next=/auth/password",
        {"password": PASSWORD, "next": "/auth/password"},
    )
    assert r.status_code == 303 and r.headers["Location"].endswith("/auth/password")
    assert cookie(client) != old_cookie  # rotated
    r = post(
        client, "/auth/password", {"password": "New-Password-99", "confirm": "New-Password-99"}
    )
    assert r.status_code == 303 and "password_changed" in r.headers["Location"]
    assert provider.users[email]["password"] == "New-Password-99"
    assert client.get("/test/whoami").json["user"] == h_before


def test_wrong_password_at_reauthentication_is_refused(client, provider):
    register(client, provider)
    r = post(client, "/auth/reauthenticate", {"password": "wrong-pass-1"})
    assert r.status_code == 400


# ---------------------------------------------------------------- authorisation
def test_participants_cannot_reach_privileged_routes(client, provider):
    register(client, provider)
    assert client.get("/test/publish").status_code == 403
    assert client.get("/test/void-round").status_code == 403
    assert client.get("/test/callback").status_code == 204


def test_forged_role_inputs_do_nothing(client, provider):
    register(client, provider)
    r = client.get("/test/publish?role=owner", headers={"X-Role": "owner"})
    client.set_cookie("role", "owner")
    assert r.status_code == 403
    assert client.get("/test/whoami").json["roles"] == []


def test_operator_route_and_sensitive_reauth(client, provider, engine):
    email = register(client, provider)
    uid = client.get("/test/whoami").json["user"]
    with transaction(engine) as conn:
        conn.execute(text("DELETE FROM app.user_roles WHERE role = 'owner'"))
        pv.bootstrap_owner(conn, uuid.UUID(uid), "test owner")
    assert client.get("/test/publish").get_data(as_text=True) == "published"
    with transaction(engine) as conn:  # sensitive needs credentials within 15 minutes
        conn.execute(
            update(app_sessions)
            .where(app_sessions.c.user_id == uid)
            .values(reauthenticated_at=db_now(conn) - timedelta(minutes=16))
        )
    r = client.get("/test/void-round")
    assert r.status_code == 303 and "/auth/reauthenticate" in r.headers["Location"]
    post(client, "/auth/reauthenticate", {"password": PASSWORD})
    assert client.get("/test/void-round").get_data(as_text=True) == "voided"
    provider.end_all_sessions(email)  # revoked at the provider: privileged checks fail closed
    assert client.get("/test/void-round").status_code == 303


# ---------------------------------------------------------------- T-16 application-side revocation
def test_role_and_entitlement_revocations_apply_to_the_next_request(app, provider, engine):
    """Application-side changes need no provider round trip and no new sign-in: the
    Principal is rebuilt from the database on every request."""
    owner_c, member_c = app.test_client(), app.test_client()
    register(owner_c, provider)
    owner = uuid.UUID(owner_c.get("/test/whoami").json["user"])
    register(member_c, provider)
    member = uuid.UUID(member_c.get("/test/whoami").json["user"])
    with transaction(engine) as conn:
        conn.execute(text("DELETE FROM app.user_roles WHERE role = 'owner'"))
        pv.bootstrap_owner(conn, owner, "test owner")
        pv.grant_role(conn, owner, member, "operator", "trial operator")
        pv.grant_feature(conn, owner, member, "lucy.research", "trial")
    assert member_c.get("/test/publish").get_data(as_text=True) == "published"
    assert member_c.get("/test/feature").get_data(as_text=True) == "feature"
    with transaction(engine) as conn:
        pv.revoke_role(conn, owner, member, "operator", "trial over")
        pv.revoke_feature(conn, owner, member, "lucy.research", "trial over")
    # same session, very next request: both are gone
    assert member_c.get("/test/publish").status_code == 403
    assert member_c.get("/test/feature").status_code == 403
    assert member_c.get("/test/whoami").json["roles"] == []
    # ordinary participant access in that session continues
    assert member_c.get("/account").status_code == 200


def test_operator_suspension_ends_the_session_immediately(app, provider, engine):
    owner_c, member_c = app.test_client(), app.test_client()
    register(owner_c, provider)
    owner = uuid.UUID(owner_c.get("/test/whoami").json["user"])
    register(member_c, provider)
    member = uuid.UUID(member_c.get("/test/whoami").json["user"])
    with transaction(engine) as conn:
        conn.execute(text("DELETE FROM app.user_roles WHERE role = 'owner'"))
        pv.bootstrap_owner(conn, owner, "test owner")
        pv.set_status(conn, owner, member, "suspended", "abuse report", revoke_all_sessions)
    # the provider session is untouched (FakeProvider still valid); the app session is not
    assert member_c.get("/test/whoami").json["user"] is None
    assert member_c.get("/account").status_code == 303


def test_accounts_are_isolated(app, provider):
    a, b = app.test_client(), app.test_client()
    email_a = register(a, provider, username=f"Alpha{uuid.uuid4().hex[:5]}")
    register(b, provider, username=f"Bravo{uuid.uuid4().hex[:5]}")
    page_b = b.get("/account").get_data(as_text=True)
    assert email_a not in page_b and "Alpha" not in page_b
    post(b, "/account/privacy", {"mode": "anonymous"}, page="/account")
    page_a = a.get("/account").get_data(as_text=True)
    assert 'value="public" checked' in page_a  # B's change did not touch A


def test_username_cannot_be_claimed_twice_through_the_web(app, provider):
    a, b = app.test_client(), app.test_client()
    name = f"Unique{uuid.uuid4().hex[:5]}"
    register(a, provider, username=name)
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    provider.add_user(email, PASSWORD)
    post(b, "/auth/sign-in", {"email": email, "password": PASSWORD})
    r = post(
        b,
        "/account/welcome",
        {
            "username": name.lower(),
            "terms_version": "beta-2026-11",
            "age_confirmed": "yes",
            "accept_terms": "yes",
        },
    )
    assert r.status_code == 400 and "already taken" in r.get_data(as_text=True)


def test_onboarding_rejects_stale_terms_version(client, provider):
    provider.add_user("terms@example.com", PASSWORD)
    post(client, "/auth/sign-in", {"email": "terms@example.com", "password": PASSWORD})
    r = post(
        client,
        "/account/welcome",
        {
            "username": "Terms Tester",
            "terms_version": "old",
            "age_confirmed": "yes",
            "accept_terms": "yes",
        },
    )
    assert r.status_code == 400


def test_account_pages_are_not_cached_and_have_csp(client):
    r = client.get("/auth/sign-in")
    assert r.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]


# ---------------------------------------------------------------- Dash shell
def test_dash_shell_menu_for_guest_and_member(app, provider, engine):
    from diski9.app.app import account_menu

    def menu_html(client=None):
        headers = {}
        if client is not None and cookie(client):
            headers = {"Cookie": f"d9_session={cookie(client)}"}
        with app.test_request_context("/", headers=headers):
            app.preprocess_request()
            return str(account_menu())

    guest = menu_html()
    assert "Sign in" in guest and "data-owner" in guest and "guest" in guest
    c = app.test_client()
    name = f"Menu{uuid.uuid4().hex[:5]}"
    email = register(c, provider, username=name)
    member = menu_html(c)
    assert name in member and email not in member
    uid = c.get("/test/whoami").json["user"]
    assert uid not in member  # the owner tag is derived, never the internal ID


def test_dash_shell_without_auth_is_unchanged():
    from diski9.app.app import account_menu

    plain = Flask("plain")
    with plain.test_request_context("/"):
        assert account_menu() == []


def test_guest_principal_outside_requests():
    assert current_principal().is_authenticated is False


def test_privacy_form_rejects_unknown_modes(client, provider):
    register(client, provider)
    r = post(client, "/account/privacy", {"mode": "superpublic"}, page="/account")
    assert r.status_code == 400


def test_acct_records_lock_snapshot(engine, client, provider):
    register(client, provider, username=f"Snap{uuid.uuid4().hex[:5]}")
    uid = client.get("/test/whoami").json["user"]
    with transaction(engine) as conn:
        name, mode = acct.lock_snapshot(conn, uuid.UUID(uid))
        assert name.startswith("Snap") and mode == "public"
        assert conn.execute(select(users.c.status).where(users.c.id == uid)).scalar() == "active"


# ---------------------------------------------------------------- guests
def test_guests_keep_cookie_free_analysis(client):
    """Guests (no session cookie) can use stateless POST endpoints such as Dash
    callbacks without an account; nothing is attributed to any user."""
    r = client.post("/test/echo", json={})
    assert r.status_code == 200 and r.json["user"] is None
    r = client.post("/test/echo", json={}, headers=ORIGIN)
    assert r.status_code == 200


def test_guest_cross_origin_posts_are_still_refused(client):
    assert (
        client.post("/test/echo", json={}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )


def test_account_switching_changes_the_owner_tag(app, provider):
    from diski9.backend.auth.web import owner_tag

    tags = []
    for _ in range(2):
        c = app.test_client()
        register(c, provider)
        with app.test_request_context("/", headers={"Cookie": f"d9_session={cookie(c)}"}):
            app.preprocess_request()
            tags.append(owner_tag())
    assert tags[0] != tags[1] and "guest" not in tags
