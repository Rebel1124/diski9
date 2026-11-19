"""Test doubles and helpers for authentication tests.

``FakeProvider`` is a MOCK of Supabase Auth (in memory). Tests that use it are
labelled "mock" in their module docstrings; they test Diski 9's own logic
(sessions, permissions, accounts, CSRF, redirects) on real PostgreSQL. Genuine
Supabase Auth behaviour is tested separately in ``test_backend_supabase_local.py``
against a real Supabase Auth server.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet

from diski9.backend.auth.provider import (
    EmailNotConfirmed,
    InvalidCredentials,
    InvalidLink,
    InvalidToken,
    ProviderIdentity,
    ProviderSession,
    ProviderUnavailable,
    SessionEnded,
)
from diski9.backend.auth.settings import AuthSettings

FERNET_KEY = Fernet.generate_key().decode()


def make_settings(**overrides) -> AuthSettings:
    values = dict(
        supabase_auth_url="http://auth.test",
        supabase_publishable_key="publishable-test-key",
        app_secret_key="s" * 48,
        app_token_encryption_key=FERNET_KEY,
        app_site_url="http://localhost",
        app_environment="test",
        app_cookie_secure=False,
    )
    values.update(overrides)
    return AuthSettings(_env_file=None, **values)


class FakeProvider:
    """In-memory stand-in for Supabase Auth (mock)."""

    name = "supabase"

    def __init__(self):
        self.users: dict[str, dict] = {}  # email -> {subject, password, confirmed, banned}
        self.sessions: dict[str, dict] = {}  # provider session id -> {subject, alive}
        self.refresh_tokens: dict[str, str] = {}  # refresh token -> session id
        self.access_tokens: dict[str, str] = {}
        self.links: dict[str, tuple[str, str]] = {}  # token_hash -> (email, kind)
        self.down = False
        self.calls: list[str] = []

    # helpers for tests
    def add_user(self, email: str, password: str, confirmed: bool = True) -> str:
        sub = str(uuid.uuid4())
        self.users[email.lower()] = {
            "subject": sub,
            "password": password,
            "confirmed": confirmed,
            "banned": False,
        }
        return sub

    def end_all_sessions(self, email: str) -> None:
        sub = self.users[email.lower()]["subject"]
        for s in self.sessions.values():
            if s["subject"] == sub:
                s["alive"] = False

    def _check_up(self):
        if self.down:
            raise ProviderUnavailable()

    def _issue(self, email: str, ttl: timedelta = timedelta(hours=1)) -> ProviderSession:
        u = self.users[email.lower()]
        sid = str(uuid.uuid4())
        self.sessions[sid] = {"subject": u["subject"], "alive": True}
        return self._tokens(sid, email, ttl)

    def _tokens(self, sid: str, email: str, ttl: timedelta = timedelta(hours=1)) -> ProviderSession:
        u = self.users[email.lower()]
        access, refresh = f"at-{uuid.uuid4().hex}", f"rt-{uuid.uuid4().hex}"
        self.access_tokens[access] = sid
        self.refresh_tokens[refresh] = sid
        return ProviderSession(
            ProviderIdentity(self.name, u["subject"], email, u["confirmed"]),
            access,
            refresh,
            datetime.now(UTC) + ttl,
            uuid.UUID(sid),
        )

    def _email_of(self, sub: str) -> str:
        return next(e for e, u in self.users.items() if u["subject"] == sub)

    # AuthProvider
    def sign_up(self, email, password):
        self._check_up()
        self.calls.append("sign_up")
        if email.lower() not in self.users:
            self.add_user(email, password, confirmed=False)
        th = uuid.uuid4().hex
        self.links[th] = (email.lower(), "email")

    def sign_in_with_password(self, email, password):
        self._check_up()
        self.calls.append("sign_in")
        u = self.users.get(email.lower())
        if not u or u["password"] != password or u["banned"]:
            raise InvalidCredentials()
        if not u["confirmed"]:
            raise EmailNotConfirmed()
        return self._issue(email)

    def verify_email_link(self, token_hash, kind):
        self._check_up()
        found = self.links.pop(token_hash, None)
        if not found or found[1] != kind:
            raise InvalidLink()
        self.users[found[0]]["confirmed"] = True
        return self._issue(found[0])

    def send_password_recovery(self, email):
        self._check_up()
        if email.lower() in self.users:
            self.links[uuid.uuid4().hex] = (email.lower(), "recovery")

    def update_password(self, session, new_password):
        sid = self.access_tokens.get(session.access_token)
        if not sid or not self.sessions[sid]["alive"]:
            raise SessionEnded()
        self.users[self._email_of(self.sessions[sid]["subject"])]["password"] = new_password

    def refresh(self, refresh_token):
        self._check_up()
        self.calls.append("refresh")
        sid = self.refresh_tokens.pop(refresh_token, None)
        if not sid or not self.sessions[sid]["alive"]:
            raise SessionEnded()
        sub = self.sessions[sid]["subject"]
        email = self._email_of(sub)
        if self.users[email]["banned"]:
            raise SessionEnded()
        return self._tokens(sid, email)

    def check_session(self, access_token):
        self._check_up()
        sid = self.access_tokens.get(access_token)
        if not sid or not self.sessions[sid]["alive"]:
            raise SessionEnded()
        email = self._email_of(self.sessions[sid]["subject"])
        u = self.users[email]
        return ProviderIdentity(self.name, u["subject"], email, u["confirmed"])

    def sign_out(self, access_token, scope="local"):
        sid = self.access_tokens.get(access_token)
        if not sid:
            return
        sub = self.sessions[sid]["subject"]
        for k, s in self.sessions.items():
            if (
                (scope == "local" and k == sid)
                or (scope == "global" and s["subject"] == sub)
                or (scope == "others" and s["subject"] == sub and k != sid)
            ):
                s["alive"] = False

    def verify_access_token(self, access_token):
        if access_token not in self.access_tokens:
            raise InvalidToken()
        return {"sub": self.sessions[self.access_tokens[access_token]]["subject"]}

    def link_for(self, email: str, kind: str) -> str:
        return next(th for th, (e, k) in self.links.items() if e == email.lower() and k == kind)


CSRF_RE = re.compile(r'name="csrf_token" value="([0-9a-f]{64})"')


def csrf_from(html: str) -> str:
    m = CSRF_RE.search(html)
    assert m, "no CSRF token on page"
    return m.group(1)
