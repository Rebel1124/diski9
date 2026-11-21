"""Shared pieces of the competition services: typed, user-safe errors and the
checks every mutation repeats inside its transaction.

Services never show database exceptions to users. Each error carries a short
``code`` for callers and tests and a ``message`` that is safe to display.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from ..auth.accounts import account
from ..auth.permissions import Principal
from ..db.schema import users

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Base class: ``code`` for programs, ``message`` safe to show a participant."""

    code = "service_error"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details


class NotFound(ServiceError):
    code = "not_found"


class AccountInactive(ServiceError):
    code = "account_inactive"


class RoundClosed(ServiceError):
    """The round does not accept changes (not open, or past its deadline)."""

    code = "round_closed"


class ValidationFailed(ServiceError):
    """Input rejected as a whole; ``issues`` explains each problem."""

    code = "invalid"

    def __init__(self, message: str, issues: Sequence[dict], **kw):
        super().__init__(message, details=list(issues), **kw)
        self.issues = list(issues)


class VersionConflict(ServiceError):
    """Another tab or device saved newer work; ``latest`` is that saved work."""

    code = "conflict"

    def __init__(self, message: str, latest: Any):
        super().__init__(message, details=latest)
        self.latest = latest


class PublicationRefused(ServiceError):
    code = "publication_refused"


class LockRefused(ServiceError):
    code = "lock_refused"


class SnapshotIntegrityError(ServiceError):
    code = "snapshot_integrity"


def require_active(conn: Connection, user_id: UUID) -> None:
    """The account must still be active at the moment of the write (a suspension
    made after the request started still stops it). Takes ``FOR SHARE`` on the
    user row so a concurrent suspension waits for this transaction."""
    status = conn.execute(
        select(users.c.status).where(users.c.id == user_id).with_for_update(read=True)
    ).scalar_one_or_none()
    if status != "active":
        raise AccountInactive("This account cannot make changes at the moment.")


def cli_principal(conn: Connection, user_id: UUID, now) -> Principal:
    """A principal built from the database **without** verifying a password: for
    development tools and tests only (seed scripts, demonstrations, read-only
    expectation builders). No product command uses it: privileged human operations
    authenticate through ``authenticate_operator`` (S-07, Phase 6C.6). Refused when
    the application environment is ``production``."""
    from ..db import BackendDatabaseSettings

    if BackendDatabaseSettings().environment == "production":
        raise ServiceError(
            "Unverified principals are not available in production.", code="forbidden"
        )
    view = account(conn, user_id)
    return Principal(
        user_id=user_id,
        roles=view.roles,
        features=view.features,
        onboarded=bool(view.username) and view.age_confirmed and view.status == "active",
        username=view.username,
        authenticated_at=now,
        reauthenticated_at=None,
        now=now,
    )


class PersistenceFailed(ServiceError):
    """The database could not complete the write; nothing was saved."""

    code = "persistence_failed"


SAVE_FAILED = "Your changes could not be saved just now. They are still on this page; try again."


class map_db_errors:  # noqa: N801 - used as a context manager
    """Turn database exceptions into user-safe service errors (details are logged,
    never shown). A deadline trigger firing in a race becomes :class:`RoundClosed`."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        from sqlalchemy.exc import DBAPIError

        if exc is None or not isinstance(exc, DBAPIError):
            return False
        code = getattr(getattr(exc, "orig", None), "sqlstate", None)
        logger.warning("competition write failed: %s (%s)", type(exc.orig).__name__, code)
        if code == "23514" and "not open" in str(exc.orig):
            raise RoundClosed("The deadline has passed; this round can no longer change.") from None
        raise PersistenceFailed(SAVE_FAILED) from None


_TAB_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


class Writer:
    """Which browser tab sent a save, and that tab's request sequence (app_0005).
    A random per-tab token, never linked to an identity."""

    __slots__ = ("seq", "tab")

    def __init__(self, tab: str, seq: int):
        if (
            not isinstance(tab, str)
            or not 16 <= len(tab) <= 64
            or not set(tab) <= _TAB_CHARS
            or isinstance(seq, bool)
            or not isinstance(seq, int)
            or seq < 0
        ):
            raise ValidationFailed("Invalid page token.", [{"reason": "writer"}])
        self.tab, self.seq = tab, seq


def save_decision(row, expected_version: int, writer: Writer | None) -> str:
    """``write`` (version matches, or a newer save from the tab that wrote last),
    ``superseded`` (an older save from that same tab arriving late: ignore it) or
    ``conflict`` (another tab or device saved in between)."""
    current = row.version if row is not None else 0
    if expected_version == current:
        return "write"
    if writer is not None and row is not None and row.writer_tab == writer.tab:
        return "write" if writer.seq > (row.writer_seq or -1) else "superseded"
    return "conflict"
