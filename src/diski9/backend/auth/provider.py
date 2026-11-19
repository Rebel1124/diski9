"""Supabase Auth adapter: the only module that talks to the identity provider.

Uses the official Supabase Python client (``supabase_auth``, part of supabase-py)
server-side, with a fresh client per call (``persist_session=False``,
``auto_refresh_token=False``) so no tokens are kept in process memory between
requests. The rest of Diski 9 depends only on :class:`AuthProvider` and the
provider-neutral types below, so the competition services never see a Supabase
object.

Flows used (docs/authentication.md):
* email and password sign-up with confirmation links of the form
  ``{{ .SiteURL }}/auth/confirm?token_hash=...&type=email`` verified server-side
  with ``verify_otp`` (Supabase's documented server-side pattern);
* password sign-in (``grant_type=password``) server-side;
* recovery links (``type=recovery``) verified the same way, then ``update_user``;
* refresh-token rotation and server-side sign-out (``scope`` local or global).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import httpx

from .settings import AuthSettings

ALLOWED_ALGORITHMS = frozenset({"ES256", "RS256", "HS256"})  # HS256: verified by the server
JWKS_TTL_SECONDS = 600  # Supabase caches JWKS for 10 minutes; do not cache longer


# ---------------------------------------------------------------- neutral types
@dataclass(frozen=True)
class ProviderIdentity:
    provider: str  # "supabase"
    subject: str  # the provider's user id (UUID)
    email: str | None
    email_verified: bool


@dataclass(frozen=True)
class ProviderSession:
    identity: ProviderIdentity
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    provider_session_id: UUID | None


class AuthError(Exception):
    """Base class; ``public_message`` is safe to show to the user."""

    public_message = "Something went wrong. Please try again."


class InvalidCredentials(AuthError):
    public_message = "The email address or password is incorrect."


class EmailNotConfirmed(AuthError):
    public_message = "Please confirm your email address first. Check your inbox for the link."


class InvalidLink(AuthError):
    public_message = "This link is invalid or has expired. Please request a new one."


class WeakPassword(AuthError):
    public_message = "Please choose a stronger password (at least 10 characters)."


class RateLimited(AuthError):
    public_message = "Too many attempts. Please wait a few minutes and try again."


class SessionEnded(AuthError):
    public_message = "Your session has ended. Please sign in again."


class InvalidToken(AuthError):
    public_message = "Your session could not be verified. Please sign in again."


class ProviderUnavailable(AuthError):
    public_message = "Sign-in is temporarily unavailable. Please try again shortly."


class AuthProvider(Protocol):
    name: str

    def sign_up(self, email: str, password: str) -> None: ...
    def sign_in_with_password(self, email: str, password: str) -> ProviderSession: ...
    def verify_email_link(self, token_hash: str, kind: str) -> ProviderSession: ...
    def send_password_recovery(self, email: str) -> None: ...
    def update_password(self, session: ProviderSession, new_password: str) -> None: ...
    def refresh(self, refresh_token: str) -> ProviderSession: ...
    def check_session(self, access_token: str) -> ProviderIdentity: ...
    def sign_out(self, access_token: str, scope: str = "local") -> None: ...
    def verify_access_token(self, access_token: str) -> dict[str, Any]: ...


# ---------------------------------------------------------------- Supabase
class SupabaseAuthProvider:
    """:class:`AuthProvider` backed by Supabase Auth through ``supabase_auth``."""

    name = "supabase"

    def __init__(self, settings: AuthSettings, *, timeout: float = 10.0):
        if not settings.enabled:
            raise RuntimeError("Supabase Auth is not configured")
        self._settings = settings
        self._timeout = timeout
        self._jwks: dict[str, Any] = {"keys": []}
        self._jwks_at = 0.0
        self._jwks_lock = threading.Lock()

    # -------------------------------------------------------------- internals
    def _client(self):
        from supabase_auth import SyncGoTrueClient

        return SyncGoTrueClient(
            url=self._settings.supabase_auth_url,
            headers={"apikey": self._settings.publishable_key()},
            persist_session=False,
            auto_refresh_token=False,
            http_client=httpx.Client(timeout=self._timeout),
        )

    def _translate(self, exc: Exception) -> AuthError:
        from supabase_auth.errors import AuthApiError, AuthRetryableError, AuthWeakPasswordError

        if isinstance(exc, AuthError):
            return exc
        if isinstance(exc, AuthWeakPasswordError):
            return WeakPassword()
        if isinstance(exc, AuthApiError):
            code = (exc.code or "").lower()
            if exc.status == 429 or "rate_limit" in code or "over_" in code:
                return RateLimited()
            if code == "email_not_confirmed":
                return EmailNotConfirmed()
            if code in ("invalid_credentials", "user_not_found"):
                return InvalidCredentials()
            if code in ("otp_expired", "otp_disabled", "flow_state_expired", "bad_jwt"):
                return InvalidLink()
            if code == "weak_password":
                return WeakPassword()
            if code in (
                "refresh_token_not_found",
                "refresh_token_already_used",
                "session_not_found",
                "session_expired",
                "user_banned",
                "user_not_found",
            ):
                return SessionEnded()
            if exc.status and exc.status >= 500:
                return ProviderUnavailable()
            if exc.status in (401, 403):
                return SessionEnded()
            return AuthError()
        if isinstance(exc, AuthRetryableError | httpx.TransportError):
            return ProviderUnavailable()
        return AuthError()

    def _session(self, raw) -> ProviderSession:
        user = raw.user
        claims = self.verify_access_token(raw.access_token)
        sid = claims.get("session_id")
        expires = datetime.fromtimestamp(int(claims["exp"]), UTC)
        return ProviderSession(
            identity=ProviderIdentity(
                provider=self.name,
                subject=str(user.id),
                email=user.email,
                email_verified=bool(user.email_confirmed_at),
            ),
            access_token=raw.access_token,
            refresh_token=raw.refresh_token,
            access_expires_at=expires,
            provider_session_id=UUID(sid) if sid else None,
        )

    def _cached_jwks(self, force: bool = False) -> dict[str, Any]:
        with self._jwks_lock:
            fresh = time.time() - self._jwks_at < JWKS_TTL_SECONDS
            if force and time.time() - self._jwks_at < 30:
                force = False  # at most one forced refresh every 30 seconds
            if fresh and not force and self._jwks["keys"]:
                return self._jwks
            try:
                resp = httpx.get(
                    f"{self._settings.supabase_auth_url}/.well-known/jwks.json",
                    headers={"apikey": self._settings.publishable_key()},
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                self._jwks = resp.json()
                self._jwks_at = time.time()
            except (httpx.HTTPError, ValueError):
                if not self._jwks["keys"]:
                    raise ProviderUnavailable() from None
            return self._jwks

    # -------------------------------------------------------------- tokens
    def verify_access_token(self, access_token: str) -> dict[str, Any]:
        """Verify an access token with Supabase's ``get_claims`` against the cached
        JWKS (ES256/RS256), plus the checks ``get_claims`` does not make: allowed
        algorithm, issuer, audience, role and subject. HS256 tokens (projects still
        on the legacy secret) are verified by the Auth server itself."""
        import jwt as pyjwt
        from supabase_auth.errors import AuthError as SupabaseAuthError

        try:
            header = pyjwt.get_unverified_header(access_token)
        except pyjwt.PyJWTError:
            raise InvalidToken() from None
        alg = header.get("alg")
        if alg not in ALLOWED_ALGORITHMS:
            raise InvalidToken()
        client = self._client()
        try:
            jwks = self._cached_jwks()
            if alg != "HS256" and not any(k.get("kid") == header.get("kid") for k in jwks["keys"]):
                jwks = self._cached_jwks(force=True)  # key rotation
            result = client.get_claims(access_token, jwks=jwks)
        except SupabaseAuthError as exc:
            raise InvalidToken() from exc
        except Exception as exc:  # noqa: BLE001 - malformed tokens raise library-specific errors
            translated = self._translate(exc)
            raise (
                translated if isinstance(translated, ProviderUnavailable) else InvalidToken()
            ) from None
        finally:
            client.close()
        claims = (result or {}).get("claims") or {}
        aud = claims.get("aud")
        aud_ok = aud == self._settings.supabase_jwt_audience or (
            isinstance(aud, list) and self._settings.supabase_jwt_audience in aud
        )
        if not (
            aud_ok
            and claims.get("iss", "").rstrip("/") == self._settings.issuer
            and claims.get("role") == "authenticated"
            and not claims.get("is_anonymous", False)
            and _is_uuid(claims.get("sub"))
            and claims.get("exp")
        ):
            raise InvalidToken()
        return claims

    # -------------------------------------------------------------- flows
    def sign_up(self, email: str, password: str) -> None:
        client = self._client()
        try:
            # confirmation links point at the Site URL (/auth/confirm), never at a
            # caller-supplied address
            client.sign_up({"email": email, "password": password})
        except Exception as exc:  # noqa: BLE001
            err = self._translate(exc)
            if isinstance(err, RateLimited | ProviderUnavailable | WeakPassword):
                raise err from None
            # anything else (for example "already registered") is not revealed
        finally:
            client.close()

    def sign_in_with_password(self, email: str, password: str) -> ProviderSession:
        client = self._client()
        try:
            raw = client.sign_in_with_password({"email": email, "password": password})
            if raw.session is None:
                raise EmailNotConfirmed()
            return self._session(raw.session)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from None
        finally:
            client.close()

    def verify_email_link(self, token_hash: str, kind: str) -> ProviderSession:
        if kind not in ("email", "recovery"):
            raise InvalidLink()
        client = self._client()
        try:
            raw = client.verify_otp({"token_hash": token_hash, "type": kind})
            if raw.session is None:
                raise InvalidLink()
            return self._session(raw.session)
        except Exception as exc:  # noqa: BLE001
            err = self._translate(exc)
            raise (
                err if isinstance(err, RateLimited | ProviderUnavailable) else InvalidLink()
            ) from None
        finally:
            client.close()

    def send_password_recovery(self, email: str) -> None:
        client = self._client()
        try:
            client.reset_password_for_email(email, {})
        except Exception as exc:  # noqa: BLE001
            err = self._translate(exc)
            if isinstance(err, ProviderUnavailable):
                raise err from None
            # rate limits and unknown addresses are not revealed
        finally:
            client.close()

    def update_password(self, session: ProviderSession, new_password: str) -> None:
        client = self._client()
        try:
            client.set_session(session.access_token, session.refresh_token)
            client.update_user({"password": new_password})
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from None
        finally:
            client.close()

    def refresh(self, refresh_token: str) -> ProviderSession:
        client = self._client()
        try:
            raw = client.refresh_session(refresh_token)
            if raw.session is None:
                raise SessionEnded()
            return self._session(raw.session)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from None
        finally:
            client.close()

    def check_session(self, access_token: str) -> ProviderIdentity:
        """Ask the Auth server whether the session behind a token still exists
        (detects server-side sign-out, bans and deletions; ``get_claims`` cannot)."""
        client = self._client()
        try:
            resp = client.get_user(access_token)
            if resp is None or resp.user is None:
                raise SessionEnded()
            u = resp.user
            return ProviderIdentity(self.name, str(u.id), u.email, bool(u.email_confirmed_at))
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from None
        finally:
            client.close()

    def sign_out(self, access_token: str, scope: str = "local") -> None:
        if scope not in ("local", "global", "others"):
            raise ValueError("invalid sign-out scope")
        client = self._client()
        try:
            client.admin.sign_out(access_token, scope)
        except Exception as exc:  # noqa: BLE001
            err = self._translate(exc)
            if not isinstance(err, SessionEnded):
                raise err from None
        finally:
            client.close()


def _is_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
    except (ValueError, TypeError):
        return False
    return True
