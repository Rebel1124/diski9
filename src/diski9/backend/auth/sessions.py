"""Server-side application sessions (T-12).

* The browser holds only an opaque random token in a cookie; the database stores
  its SHA-256 hash (``app_sessions.id``), so a database leak cannot be replayed.
* Lifetimes: idle 14 days, absolute 30 days, enforced on every request by the
  database clock. Expired sessions are revoked with a reason.
* A new token is issued at every sign-in, re-authentication and privilege-relevant
  change (rotation, ``rotated_from``); a token presented before sign-in is never
  promoted, which prevents session fixation.
* The provider session behind each app session is kept, encrypted, so that
  revocation at Supabase (sign-out elsewhere, password change, ban, deletion) ends
  the app session: the tokens are refreshed when the access token is close to
  expiry, and privileged checks ask the provider directly.
* Suspended or deleted accounts cannot use any session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, Engine, insert, select, update

from ..db import db_now, transaction
from ..db.schema import app_sessions, users
from .crypto import TokenCipher, new_session_token, token_hash
from .provider import AuthProvider, ProviderSession, ProviderUnavailable, SessionEnded
from .settings import AuthSettings

log = logging.getLogger(__name__)
TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class AppSession:
    id: str  # token hash
    user_id: UUID
    created_at: datetime
    authenticated_at: datetime
    reauthenticated_at: datetime | None
    idle_expires_at: datetime
    absolute_expires_at: datetime
    provider_session_id: UUID | None
    provider_access_expires_at: datetime | None
    now: datetime


class SessionManager:
    def __init__(self, engine: Engine, provider: AuthProvider, settings: AuthSettings):
        self.engine = engine
        self.provider = provider
        self.settings = settings
        self.cipher = TokenCipher(settings.encryption_key())

    # ------------------------------------------------------------ create
    def start(
        self,
        conn: Connection,
        user_id: UUID,
        provider_session: ProviderSession,
        *,
        rotated_from: str | None = None,
        absolute_expires_at: datetime | None = None,
        user_agent_hash: str | None = None,
    ) -> str:
        """Create a session after credentials were just presented; returns the token
        to put in the cookie (never stored)."""
        now = db_now(conn)
        token = new_session_token()
        absolute = absolute_expires_at or now + self.settings.absolute_lifetime
        conn.execute(
            insert(app_sessions).values(
                id=token_hash(token),
                user_id=user_id,
                created_at=now,
                last_seen_at=now,
                authenticated_at=now,
                reauthenticated_at=now,
                idle_expires_at=min(now + self.settings.idle_lifetime, absolute),
                absolute_expires_at=absolute,
                rotated_from=rotated_from,
                user_agent_hash=user_agent_hash,
                **self._provider_values(provider_session, now),
            )
        )
        return token

    def _provider_values(self, ps: ProviderSession, now: datetime) -> dict:
        return {
            "provider_session_id": ps.provider_session_id,
            "provider_refresh_token_enc": self.cipher.encrypt(ps.refresh_token),
            "provider_access_token_enc": self.cipher.encrypt(ps.access_token),
            "provider_access_expires_at": ps.access_expires_at,
            "provider_checked_at": now,
        }

    # ------------------------------------------------------------ resolve
    def resolve(self, token: str | None) -> AppSession | None:
        """The live session for a cookie token, or None. Enforces revocation, idle
        and absolute expiry and account status; refreshes provider tokens when the
        access token is near expiry (revoking the session if the provider ended it)."""
        if not token or len(token) > 128:
            return None
        h = token_hash(token)
        with transaction(self.engine) as conn:
            now = db_now(conn)
            row = conn.execute(
                select(app_sessions, users.c.status)
                .join(users, users.c.id == app_sessions.c.user_id)
                .where(app_sessions.c.id == h)
            ).one_or_none()
            if row is None or row.revoked_at is not None:
                return None
            reason = None
            if row.status != "active":
                reason = "account_suspended"
            elif now >= row.absolute_expires_at:
                reason = "expired_absolute"
            elif now >= row.idle_expires_at:
                reason = "expired_idle"
            if reason:
                self._revoke(conn, h, reason, now)
                return None
            if now - row.last_seen_at >= TOUCH_INTERVAL:
                conn.execute(
                    update(app_sessions)
                    .where(app_sessions.c.id == h)
                    .values(
                        last_seen_at=now,
                        idle_expires_at=min(
                            now + self.settings.idle_lifetime, row.absolute_expires_at
                        ),
                    )
                )
        session = self._as_session(row, now)
        margin = timedelta(minutes=self.settings.provider_refresh_margin_minutes)
        if row.provider_access_expires_at is None or row.provider_access_expires_at - now <= margin:
            if not self.refresh_provider(h):
                return None
            return self.resolve_without_refresh(h)
        return session

    def resolve_without_refresh(self, h: str) -> AppSession | None:
        with transaction(self.engine) as conn:
            now = db_now(conn)
            row = conn.execute(select(app_sessions).where(app_sessions.c.id == h)).one_or_none()
            if row is None or row.revoked_at is not None:
                return None
            return self._as_session(row, now)

    def _as_session(self, row, now: datetime) -> AppSession:
        return AppSession(
            id=row.id,
            user_id=row.user_id,
            created_at=row.created_at,
            authenticated_at=row.authenticated_at,
            reauthenticated_at=row.reauthenticated_at,
            idle_expires_at=row.idle_expires_at,
            absolute_expires_at=row.absolute_expires_at,
            provider_session_id=row.provider_session_id,
            provider_access_expires_at=row.provider_access_expires_at,
            now=now,
        )

    # ------------------------------------------------------------ provider
    def refresh_provider(self, h: str, *, strict: bool = False) -> bool:
        """Rotate the provider tokens under a row lock (refresh tokens are single
        use; concurrent requests must not both use the same one). Returns False and
        revokes the app session if the provider session has ended. With
        ``strict=True`` an unreachable provider also fails (privileged checks)."""
        with transaction(self.engine) as conn:
            now = db_now(conn)
            row = conn.execute(
                select(app_sessions).where(app_sessions.c.id == h).with_for_update()
            ).one_or_none()
            if row is None or row.revoked_at is not None:
                return False
            margin = timedelta(minutes=self.settings.provider_refresh_margin_minutes)
            if (
                not strict
                and row.provider_access_expires_at is not None
                and row.provider_access_expires_at - now > margin
            ):
                return True  # another request refreshed it while we waited
            refresh = self.cipher.decrypt(row.provider_refresh_token_enc)
            if not refresh:
                self._revoke(conn, h, "provider_session_ended", now)
                return False
            try:
                fresh = self.provider.refresh(refresh)
            except SessionEnded:
                self._revoke(conn, h, "provider_session_ended", now)
                return False
            except ProviderUnavailable:
                log.warning("auth provider unavailable during refresh")
                return not strict
            conn.execute(
                update(app_sessions)
                .where(app_sessions.c.id == h)
                .values(**self._provider_values(fresh, now))
            )
            return True

    def verify_with_provider(self, h: str) -> bool:
        """Fail-closed check used before privileged operations: refresh and ask the
        provider whether the session still exists."""
        if not self.refresh_provider(h, strict=True):
            return False
        access = self.access_token(h)
        if not access:
            return False
        try:
            self.provider.check_session(access)
        except SessionEnded:
            with transaction(self.engine) as conn:
                self._revoke(conn, h, "provider_session_ended", db_now(conn))
            return False
        except ProviderUnavailable:
            return False
        return True

    def access_token(self, h: str) -> str | None:
        with self.engine.connect() as conn:
            enc = conn.execute(
                select(app_sessions.c.provider_access_token_enc).where(app_sessions.c.id == h)
            ).scalar_one_or_none()
        return self.cipher.decrypt(enc)

    def provider_session(self, h: str) -> ProviderSession | None:
        """The stored provider session (for password changes and sign-out)."""
        from .provider import ProviderIdentity

        with self.engine.connect() as conn:
            row = conn.execute(select(app_sessions).where(app_sessions.c.id == h)).one_or_none()
        if row is None:
            return None
        access = self.cipher.decrypt(row.provider_access_token_enc)
        refresh = self.cipher.decrypt(row.provider_refresh_token_enc)
        if not (access and refresh):
            return None
        return ProviderSession(
            ProviderIdentity(self.provider.name, "", None, True),
            access,
            refresh,
            row.provider_access_expires_at,
            row.provider_session_id,
        )

    # ------------------------------------------------------------ rotate / revoke
    def rotate(
        self,
        conn: Connection,
        h: str,
        provider_session: ProviderSession | None = None,
        *,
        reauthenticated: bool = False,
    ) -> str:
        """Replace a session with a new token (same absolute expiry); the old token
        stops working immediately."""
        now = db_now(conn)
        row = conn.execute(
            select(app_sessions).where(app_sessions.c.id == h).with_for_update()
        ).one()
        token = new_session_token()
        values = {
            "id": token_hash(token),
            "user_id": row.user_id,
            "created_at": now,
            "last_seen_at": now,
            "authenticated_at": now if reauthenticated else row.authenticated_at,
            "reauthenticated_at": now if reauthenticated else row.reauthenticated_at,
            "idle_expires_at": min(now + self.settings.idle_lifetime, row.absolute_expires_at),
            "absolute_expires_at": row.absolute_expires_at,
            "rotated_from": h,
            "user_agent_hash": row.user_agent_hash,
        }
        if provider_session is not None:
            values.update(self._provider_values(provider_session, now))
        else:
            values.update(
                {
                    "provider_session_id": row.provider_session_id,
                    "provider_refresh_token_enc": row.provider_refresh_token_enc,
                    "provider_access_token_enc": row.provider_access_token_enc,
                    "provider_access_expires_at": row.provider_access_expires_at,
                    "provider_checked_at": row.provider_checked_at,
                }
            )
        conn.execute(insert(app_sessions).values(**values))
        self._revoke(conn, h, "rotated", now)
        return token

    def revoke(self, h: str, reason: str) -> None:
        with transaction(self.engine) as conn:
            self._revoke(conn, h, reason, db_now(conn))

    def revoke_all_for_user(self, conn: Connection, user_id: UUID, reason: str) -> int:
        return revoke_all_sessions(conn, user_id, reason)

    @staticmethod
    def _revoke(conn: Connection, h: str, reason: str, now: datetime) -> None:
        conn.execute(
            update(app_sessions)
            .where(app_sessions.c.id == h, app_sessions.c.revoked_at.is_(None))
            .values(
                revoked_at=now,
                revoked_reason=reason,
                provider_refresh_token_enc=None,
                provider_access_token_enc=None,
            )
        )


def revoke_all_sessions(conn: Connection, user_id: UUID, reason: str) -> int:
    """Revoke every live session of an account (suspension, sign-out everywhere)."""
    now = db_now(conn)
    res = conn.execute(
        update(app_sessions)
        .where(app_sessions.c.user_id == user_id, app_sessions.c.revoked_at.is_(None))
        .values(
            revoked_at=now,
            revoked_reason=reason,
            provider_refresh_token_enc=None,
            provider_access_token_enc=None,
        )
    )
    return res.rowcount
