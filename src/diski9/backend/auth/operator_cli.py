"""Interactive operator authentication for the server CLI (Phase 6C.4, S-07).

Possession of database credentials is **not** operator authority. Every
settlement command proves who is acting by verifying that person's password with
Supabase Auth, then loads their roles from the competition database:

* The password is read with :func:`getpass.getpass` from a real terminal only. It
  is never accepted as an argument, an environment variable or piped input, never
  logged and never written to an audit payload. If no terminal is attached the
  command stops before anything is read.
* The provider session is verified (signature, issuer, audience, subject) and then
  signed out immediately; no token is stored.
* The verified provider subject must already be linked to an **active, onboarded**
  Diski 9 account (the CLI never creates accounts). Roles and entitlements come
  from the database (:func:`~diski9.backend.auth.accounts.account`), never from
  provider metadata or the command line.
* The resulting :class:`~diski9.backend.auth.permissions.Principal` is valid for one
  command: ``authenticated_at`` and ``reauthenticated_at`` are the database time of
  the verification, so T-12 and T-14 hold. Before each write, :func:`refresh_clock`
  moves ``now`` to the current database time, so a confirmation typed more than
  ``sensitive_recency_minutes`` after the password is refused (T-14).
* Any failure (provider unavailable, configuration missing, wrong password,
  unknown or suspended account) fails closed with a short, user-safe message.

There is no bypass: no flag, environment variable or test hook skips the password
check in the CLI. Tests drive the real command through a pseudo-terminal.
"""

from __future__ import annotations

import getpass
import logging
import sys
from collections.abc import Callable
from dataclasses import replace
from typing import TextIO

from sqlalchemy import Engine, select

from ..db import db_now, transaction
from ..db.schema import user_identities
from .accounts import account
from .permissions import Principal
from .provider import (
    AuthError,
    AuthProvider,
    EmailNotConfirmed,
    InvalidCredentials,
    InvalidToken,
    ProviderUnavailable,
    RateLimited,
)
from .settings import AuthSettings

logger = logging.getLogger(__name__)


class OperatorAuthFailed(Exception):
    """Authentication or account verification failed; ``message`` is safe to print."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.message = message
        self.code = code


def read_password_from_terminal(prompt: str = "Password: ") -> str:
    """Hidden password entry from a real terminal; refuses piped or redirected input
    (which would let a password reach shell history or a file)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise OperatorAuthFailed(
            "This command asks for your password and needs an interactive terminal. "
            "Passwords are never accepted as arguments, environment variables or piped input.",
            code="no_terminal",
        )
    return getpass.getpass(prompt)


def default_provider(settings: AuthSettings | None = None) -> AuthProvider:
    from .provider import SupabaseAuthProvider

    settings = settings or AuthSettings()
    if not settings.enabled:
        raise OperatorAuthFailed(
            "Supabase Auth is not configured (DISKI9_SUPABASE_AUTH_URL and "
            "DISKI9_SUPABASE_PUBLISHABLE_KEY). Nothing was changed.",
            code="auth_not_configured",
        )
    return SupabaseAuthProvider(settings)


def authenticate_operator(
    engine: Engine,
    email: str,
    *,
    provider: AuthProvider | None = None,
    settings: AuthSettings | None = None,
    read_password: Callable[[str], str] = read_password_from_terminal,
    out: TextIO | None = None,
) -> Principal:
    """Verify ``email``'s password with Supabase Auth and return a one-command
    principal built from database roles. Raises :class:`OperatorAuthFailed`."""
    email = (email or "").strip()
    if not email:
        raise OperatorAuthFailed("An operator email address is required.", code="usage")
    settings = settings or AuthSettings()
    provider = provider or default_provider(settings)
    password = read_password(f"Supabase password for {email}: ")
    try:
        session = provider.sign_in_with_password(email, password)
    except InvalidCredentials:
        raise OperatorAuthFailed(
            "Sign-in failed: the email or password is incorrect. Nothing was changed.",
            code="invalid_credentials",
        ) from None
    except EmailNotConfirmed:
        raise OperatorAuthFailed(
            "Sign-in failed: this email address has not been confirmed.", code="unconfirmed"
        ) from None
    except RateLimited:
        raise OperatorAuthFailed(
            "Too many sign-in attempts. Wait a few minutes and try again.", code="rate_limited"
        ) from None
    except ProviderUnavailable:
        raise OperatorAuthFailed(
            "Supabase Auth is unavailable, so your identity cannot be verified. "
            "Nothing was changed.",
            code="provider_unavailable",
        ) from None
    except AuthError:
        raise OperatorAuthFailed(
            "Sign-in could not be completed. Nothing was changed.", code="auth_error"
        ) from None
    finally:
        password = ""  # noqa: F841 - drop the reference as early as possible
    try:
        # Independent check of the token the provider returned (signature, issuer,
        # audience, role and subject), so a provider response is never trusted alone.
        try:
            claims = provider.verify_access_token(session.access_token)
        except (InvalidToken, AuthError):
            raise OperatorAuthFailed(
                "The identity provider's response could not be verified. Nothing was changed.",
                code="invalid_token",
            ) from None
        if claims.get("sub") != session.identity.subject or not session.identity.email_verified:
            raise OperatorAuthFailed(
                "The identity provider's response could not be verified. Nothing was changed.",
                code="invalid_token",
            )
        with transaction(engine) as conn:
            uid = conn.execute(
                select(user_identities.c.user_id).where(
                    user_identities.c.provider == session.identity.provider,
                    user_identities.c.subject == session.identity.subject,
                )
            ).scalar_one_or_none()
            if uid is None:
                raise OperatorAuthFailed(
                    "This sign-in is not linked to a Diski 9 account. Sign in to the web "
                    "app once to finish setting it up.",
                    code="no_account",
                )
            view = account(conn, uid)
            now = db_now(conn)
        if view.status != "active":
            raise OperatorAuthFailed("This account is not active.", code="account_inactive")
        onboarded = view.onboarded(settings.app_terms_version)
        principal = Principal(
            user_id=uid,
            roles=view.roles,
            features=view.features,
            onboarded=onboarded,
            username=view.username,
            authenticated_at=now,
            reauthenticated_at=now,
            now=now,
            extra={
                "operator_recency_hours": settings.operator_recency_hours,
                "sensitive_recency_minutes": settings.sensitive_recency_minutes,
                "via": "cli",
            },
        )
    finally:
        try:
            provider.sign_out(session.access_token, "local")
        except Exception:  # noqa: BLE001 - the token is discarded either way
            logger.info("provider sign-out after CLI verification did not complete")
    if out is not None:
        roles = ", ".join(sorted(view.roles)) or "participant"
        print(f"Verified {view.username or 'account'} (roles: {roles}).", file=out)
    return principal


def refresh_clock(engine: Engine, principal: Principal) -> Principal:
    """The same principal evaluated at the current database time (for T-14 checks
    on a write that follows an interactive confirmation)."""
    with transaction(engine) as conn:
        return replace(principal, now=db_now(conn))
