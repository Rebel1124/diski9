"""GENUINE Supabase Auth integration tests (no mocks).

They run against a real Supabase Auth server: the local harness
(``tools/local_auth/local_auth.py``, which runs the official Supabase Auth server
built from source or taken from the official container image) or the Supabase CLI
stack. They are skipped unless ``DISKI9_TEST_SUPABASE_AUTH_URL``,
``DISKI9_TEST_SUPABASE_ANON_KEY`` and ``DISKI9_TEST_SUPABASE_MAIL_DIR`` are set
(the harness writes them to ``tmp/local_auth/env``). Never point them at a
production project: they create throwaway users.
"""

from __future__ import annotations

import base64
import email
import json
import os
import re
import time
import uuid
from pathlib import Path

import pytest
from auth_helpers import csrf_from, make_settings

AUTH_URL = os.environ.get("DISKI9_TEST_SUPABASE_AUTH_URL")
ANON = os.environ.get("DISKI9_TEST_SUPABASE_ANON_KEY")
MAIL_DIR = os.environ.get("DISKI9_TEST_SUPABASE_MAIL_DIR")
KEYS = Path(__file__).resolve().parents[2] / "tmp" / "local_auth" / "keys.json"

if os.environ.get("DISKI9_REQUIRE_SUPABASE_AUTH") == "1" and not (AUTH_URL and ANON and MAIL_DIR):
    raise RuntimeError("DISKI9_REQUIRE_SUPABASE_AUTH=1 but no Supabase Auth server is configured")
pytestmark = pytest.mark.skipif(
    not (AUTH_URL and ANON and MAIL_DIR),
    reason="needs a real Supabase Auth server (see docs/authentication.md, local testing)",
)
PASSWORD = "Local-Supabase-9"


@pytest.fixture
def settings():
    return make_settings(
        supabase_auth_url=AUTH_URL, supabase_publishable_key=ANON, supabase_jwt_issuer=AUTH_URL
    )


@pytest.fixture
def provider(settings):
    from diski9.backend.auth.provider import SupabaseAuthProvider

    return SupabaseAuthProvider(settings)


def _mail_count() -> int:
    return len(list(Path(MAIL_DIR).glob("*.eml")))


def _wait_link(before: int, kind: str) -> str:
    for _ in range(100):
        files = sorted(Path(MAIL_DIR).glob("*.eml"))
        if len(files) > before:
            msg = email.message_from_string(files[-1].read_text())
            body = (msg.get_payload(decode=True) or b"").decode()
            m = re.search(r"token_hash=([A-Za-z0-9_-]+)&(?:amp;)?type=(\w+)", body)
            assert m and m.group(2) == kind, body[:300]
            return m.group(1)
        time.sleep(0.1)
    raise AssertionError("no email arrived")


def _new_email() -> str:
    return f"it-{uuid.uuid4().hex[:10]}@example.com"


def confirmed_user(provider):
    addr = _new_email()
    n = _mail_count()
    provider.sign_up(addr, PASSWORD)
    session = provider.verify_email_link(_wait_link(n, "email"), "email")
    return addr, session


# ---------------------------------------------------------------- provider flows
def test_sign_up_confirmation_link_and_verified_token(provider, settings):
    addr, s = confirmed_user(provider)
    assert s.identity.email == addr and s.identity.email_verified
    claims = provider.verify_access_token(s.access_token)
    assert claims["iss"] == settings.issuer and claims["aud"] == "authenticated"
    assert claims["role"] == "authenticated" and claims["sub"] == s.identity.subject
    header = json.loads(base64.urlsafe_b64decode(s.access_token.split(".")[0] + "=="))
    assert header["alg"] in ("ES256", "RS256")  # asymmetric signing key in use


def test_confirmation_links_are_single_use(provider):
    from diski9.backend.auth.provider import InvalidLink

    addr = _new_email()
    n = _mail_count()
    provider.sign_up(addr, PASSWORD)
    th = _wait_link(n, "email")
    provider.verify_email_link(th, "email")
    with pytest.raises(InvalidLink):
        provider.verify_email_link(th, "email")


def test_unconfirmed_users_cannot_sign_in(provider):
    from diski9.backend.auth.provider import EmailNotConfirmed

    addr = _new_email()
    provider.sign_up(addr, PASSWORD)
    with pytest.raises(EmailNotConfirmed):
        provider.sign_in_with_password(addr, PASSWORD)


def test_wrong_password_and_unknown_user_are_indistinguishable(provider):
    from diski9.backend.auth.provider import InvalidCredentials

    addr, _ = confirmed_user(provider)
    for e, p in ((addr, "Wrong-Password-1"), (_new_email(), "Wrong-Password-1")):
        with pytest.raises(InvalidCredentials):
            provider.sign_in_with_password(e, p)


def test_tampered_and_foreign_tokens_are_rejected(provider):
    import jwt

    from diski9.backend.auth.provider import InvalidToken

    _, s = confirmed_user(provider)
    h, p, sig = s.access_token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(p + "=="))
    payload["sub"] = str(uuid.uuid4())
    forged_p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    with pytest.raises(InvalidToken):
        provider.verify_access_token(f"{h}.{forged_p}.{sig}")
    with pytest.raises(InvalidToken):  # signed with an unrelated key
        provider.verify_access_token(
            jwt.encode(
                {**payload, "exp": int(time.time()) + 600},
                "attacker-secret-attacker-secret!",
                "HS256",
            )
        )
    with pytest.raises(InvalidToken):
        provider.verify_access_token("not.a.token")
    with pytest.raises(InvalidToken):  # alg "none"
        provider.verify_access_token(
            f"{base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip('=')}.{p}."
        )


@pytest.mark.skipif(not KEYS.exists(), reason="needs the local harness signing key")
def test_expired_and_wrong_audience_tokens_are_rejected(provider):
    import jwt

    from diski9.backend.auth.provider import InvalidToken

    _, s = confirmed_user(provider)
    jwk = json.loads(KEYS.read_text())["jwk"]
    key = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(jwk))
    claims = provider.verify_access_token(s.access_token)
    for change in (
        {"exp": int(time.time()) - 60},
        {"aud": "something-else"},
        {"iss": "https://evil.example/auth/v1"},
        {"role": "service_role"},
    ):
        token = jwt.encode({**claims, **change}, key, "ES256", headers={"kid": jwk["kid"]})
        with pytest.raises(InvalidToken):
            provider.verify_access_token(token)
    good = jwt.encode(claims, key, "ES256", headers={"kid": jwk["kid"]})
    assert provider.verify_access_token(good)["sub"] == claims["sub"]  # control


def test_refresh_rotation_and_server_side_sign_out(provider):
    from diski9.backend.auth.provider import SessionEnded

    _, s = confirmed_user(provider)
    s2 = provider.refresh(s.refresh_token)
    assert s2.refresh_token != s.refresh_token
    assert provider.check_session(s2.access_token).subject == s.identity.subject
    provider.sign_out(s2.access_token, "local")
    with pytest.raises(SessionEnded):
        provider.refresh(s2.refresh_token)
    with pytest.raises(SessionEnded):
        provider.check_session(s2.access_token)  # detects the ended session


def test_global_sign_out_ends_every_session(provider):
    from diski9.backend.auth.provider import SessionEnded

    addr, a = confirmed_user(provider)
    b = provider.sign_in_with_password(addr, PASSWORD)
    provider.sign_out(a.access_token, "global")
    with pytest.raises(SessionEnded):
        provider.refresh(b.refresh_token)


def test_password_recovery_and_update(provider):
    from diski9.backend.auth.provider import InvalidCredentials

    addr, _ = confirmed_user(provider)
    time.sleep(1.2)  # per-address email frequency limit of the local server
    n = _mail_count()
    provider.send_password_recovery(addr)
    provider.send_password_recovery(_new_email())  # unknown address: no error, no email
    rs = provider.verify_email_link(_wait_link(n, "recovery"), "recovery")
    provider.update_password(rs, "Brand-New-Pass-9")
    with pytest.raises(InvalidCredentials):
        provider.sign_in_with_password(addr, PASSWORD)
    assert provider.sign_in_with_password(addr, "Brand-New-Pass-9").identity.email == addr


# ---------------------------------------------------------------- the full web flow
def test_full_web_flow_against_real_supabase_auth(engine, settings, provider):
    from flask import Flask

    from diski9.backend.auth.web import AuthRuntime, current_principal, init_auth

    server = Flask("supabase-it")
    init_auth(server, AuthRuntime.create(engine, settings, provider))

    @server.route("/test/whoami")
    def whoami():
        p = current_principal()
        return {"user": str(p.user_id) if p.user_id else None, "username": p.username}

    c = server.test_client()
    c.environ_base["REMOTE_ADDR"] = "198.51.100.200"
    origin = {"Origin": "http://localhost"}

    def post(path, data, page=None):
        token = csrf_from(c.get(page or path).get_data(as_text=True))
        return c.post(path, data={"csrf_token": token, **data}, headers=origin)

    addr = _new_email()
    n = _mail_count()
    assert post("/auth/sign-up", {"email": addr, "password": PASSWORD}).status_code == 303
    th = _wait_link(n, "email")
    # T-17: an email scanner (or the person) loading the link consumes nothing
    for _ in range(2):
        assert c.get(f"/auth/confirm?token_hash={th}&type=email").status_code == 200
    r = post(
        "/auth/confirm",
        {"token_hash": th, "type": "email"},
        page=f"/auth/confirm?token_hash={th}&type=email",
    )
    assert r.status_code == 303 and "/account/welcome" in r.headers["Location"]
    name = f"Real{uuid.uuid4().hex[:6]}"
    r = post(
        "/account/welcome",
        {
            "username": name,
            "terms_version": "beta-2026-11",
            "age_confirmed": "yes",
            "accept_terms": "yes",
        },
    )
    assert r.status_code == 303
    assert c.get("/test/whoami").json["username"] == name
    assert addr in c.get("/account").get_data(as_text=True)
    # revoke at the provider (for example, signed out everywhere elsewhere): the app
    # session ends at the next provider revalidation
    other = provider.sign_in_with_password(addr, PASSWORD)
    provider.sign_out(other.access_token, "global")
    from sqlalchemy import update

    from diski9.backend.db import db_now, transaction
    from diski9.backend.db.schema import app_sessions

    with transaction(engine) as conn:
        conn.execute(
            update(app_sessions)
            .where(app_sessions.c.revoked_at.is_(None))
            .values(provider_access_expires_at=db_now(conn))
        )
    assert c.get("/test/whoami").json["user"] is None
