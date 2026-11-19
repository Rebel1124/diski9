"""Authentication building blocks without a database or provider (unit tests):
username rules, the permission model, safe redirects, settings and crypto."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from auth_helpers import make_settings

from diski9.backend.auth.crypto import TokenCipher, derive, generate_fernet_key, token_hash
from diski9.backend.auth.permissions import (
    GUEST,
    OPERATOR,
    PARTICIPANT,
    SENSITIVE,
    Capability,
    Forbidden,
    NotAuthenticated,
    Principal,
    RecentAuthenticationRequired,
    authorize,
    can,
    require_feature,
    requires,
)
from diski9.backend.auth.settings import AuthConfigError
from diski9.backend.auth.usernames import UsernameError, new_alias, validate
from diski9.backend.auth.web import safe_next

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------- usernames
@pytest.mark.parametrize(
    "name", ["Ace", "Ace Striker", "ace_striker.9", "Bafana-Fan", "x" * 24, "Grapes", "Dickson"]
)
def test_valid_usernames(name):
    assert validate(name).display == name
    assert validate(name).key == name.lower()


@pytest.mark.parametrize(
    "name",
    [
        "ab",
        "x" * 25,
        "trail.",
        "bad!name",
        "two  spaces..x",
        "Ádmin",
        "admin",
        "Ad-min",
        "D1SK19",
        "Diski9 Official",
        "Lucy",
        "lucy_ai",
        "Anonymous 1234",
        "owner",
        "sh1t",
        "Shit Head",
        "n1gger99",
        "Former Participant",
        "аdmin",
    ],
)
def test_invalid_usernames(name):
    with pytest.raises(UsernameError):
        validate(name)


def test_whitespace_is_normalised():
    assert validate("  Ace   Striker ").display == "Ace Striker"


def test_aliases_are_random_and_valid():
    aliases = {new_alias() for _ in range(50)}
    assert len(aliases) > 45
    for a in aliases:
        with pytest.raises(UsernameError):
            validate(a)  # an alias can never be claimed as a username


# ---------------------------------------------------------------- permissions
def principal(
    roles=(),
    *,
    onboarded=True,
    auth_age=timedelta(minutes=1),
    reauth_age=timedelta(minutes=1),
    features=(),
):
    return Principal(
        user_id=uuid.uuid4(),
        session_hash="h",
        roles=frozenset(roles),
        features=frozenset(features),
        onboarded=onboarded,
        authenticated_at=NOW - auth_age if auth_age is not None else None,
        reauthenticated_at=NOW - reauth_age if reauth_age is not None else None,
        now=NOW,
    )


def test_guests_have_no_capabilities():
    assert GUEST.capabilities() == frozenset()
    with pytest.raises(NotAuthenticated):
        authorize(GUEST, Capability.MANAGE_OWN_ACCOUNT)


def test_onboarding_required_before_any_capability():
    with pytest.raises(Forbidden):
        authorize(principal(onboarded=False), Capability.MANAGE_OWN_ACCOUNT)


@pytest.mark.parametrize("cap", sorted(OPERATOR - PARTICIPANT))
def test_participants_cannot_use_operator_capabilities(cap):
    assert not can(principal(), cap)


def test_unknown_or_forged_roles_grant_nothing():
    forged = principal(roles=("admin", "superuser", "OWNER", "service_role"))
    assert forged.capabilities() == PARTICIPANT
    assert not can(forged, Capability.MANAGE_ROLES)


def test_operator_needs_signin_within_12_hours():
    assert can(principal(("operator",), reauth_age=None), Capability.PUBLISH_ROUND)
    with pytest.raises(RecentAuthenticationRequired):
        authorize(
            principal(("operator",), auth_age=timedelta(hours=12, minutes=1)),
            Capability.PUBLISH_ROUND,
        )


@pytest.mark.parametrize("cap", sorted(SENSITIVE))
def test_sensitive_operations_need_reauthentication_within_15_minutes(cap):
    role = "owner"
    assert can(principal((role,), reauth_age=timedelta(minutes=14)), cap)
    with pytest.raises(RecentAuthenticationRequired):
        authorize(principal((role,), reauth_age=timedelta(minutes=16)), cap)


def test_operators_cannot_manage_roles_or_reopen_championships():
    for cap in (
        Capability.MANAGE_ROLES,
        Capability.MANAGE_ENTITLEMENTS,
        Capability.REOPEN_CHAMPIONSHIP,
    ):
        assert not can(principal(("operator",)), cap)


def test_entitlements_are_independent_of_roles():
    premium = principal(features=("lucy.research",))
    require_feature(premium, "lucy.research")
    assert not can(premium, Capability.PUBLISH_ROUND)
    with pytest.raises(Forbidden):
        require_feature(principal(("owner",)), "lucy.voice")  # roles never imply features
    with pytest.raises(NotAuthenticated):
        require_feature(GUEST, "lucy.research")


def test_service_decorator_denies_by_default():
    @requires(Capability.VOID_ROUND)
    def void_round(p, round_id):
        return round_id

    with pytest.raises(Forbidden):
        void_round(principal(), "r1")
    assert void_round(principal(("operator",)), "r1") == "r1"
    assert void_round.required_capability is Capability.VOID_ROUND


# ---------------------------------------------------------------- redirects
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/account", "/account"),
        ("/challenge?x=1", "/challenge?x=1"),
        ("//evil.example/x", "/"),
        ("https://evil.example", "/"),
        ("/\\evil.example", "/"),
        ("javascript:alert(1)", "/"),
        ("", "/"),
        (None, "/"),
        ("/ok\r\nSet-Cookie: x", "/"),
        ("evil.example", "/"),
    ],
)
def test_safe_next_blocks_open_redirects(value, expected):
    assert safe_next(value) == expected


# ---------------------------------------------------------------- settings and crypto
def test_settings_require_real_keys():
    with pytest.raises(AuthConfigError):
        make_settings(app_secret_key="short").secret()
    with pytest.raises(AuthConfigError):
        make_settings(app_token_encryption_key="not-a-fernet-key").encryption_key()


def test_production_requires_https_and_secure_cookies():
    with pytest.raises(ValueError):
        make_settings(app_environment="production", app_site_url="http://diski9.example")
    with pytest.raises(ValueError):
        make_settings(
            app_environment="production",
            app_site_url="https://diski9.example",
            supabase_auth_url="https://x.supabase.co/auth/v1",
            app_cookie_secure=False,
        )
    s = make_settings(
        app_environment="production",
        app_site_url="https://diski9.example",
        supabase_auth_url="https://x.supabase.co/auth/v1",
        app_cookie_secure=None,
    )
    assert s.cookie_secure and s.session_cookie_name.startswith("__Host-")


def test_settings_never_echo_secrets_in_errors():
    with pytest.raises(ValueError) as exc:
        make_settings(supabase_auth_url="ftp://user:hunter2@host")
    assert "hunter2" not in str(exc.value)


def test_tokens_are_encrypted_and_hashed():
    cipher = TokenCipher(generate_fernet_key().encode())
    enc = cipher.encrypt("refresh-token-value")
    assert "refresh-token-value" not in enc and cipher.decrypt(enc) == "refresh-token-value"
    assert cipher.decrypt("tampered") is None
    assert TokenCipher(generate_fernet_key().encode()).decrypt(enc) is None  # other key
    assert len(token_hash("abc")) == 64
    assert derive(b"k" * 32, "csrf", "x") != derive(b"k" * 32, "owner", "x")
