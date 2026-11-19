"""Server-side authorisation (D-34): identity, roles and feature entitlements.

Deny by default. Every decision is made from database state loaded for the
current server-side session (:class:`Principal`), never from browser-supplied
values, editable profile fields or identity-provider metadata. The same
functions serve Flask routes, Dash callbacks, application services and future
agent tools.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from functools import wraps
from typing import Any
from uuid import UUID


class Capability(StrEnum):
    # participant (any signed-in, onboarded, active account)
    MANAGE_OWN_ACCOUNT = "account.manage_own"
    PERSIST_OWN_ANALYSIS = "analysis.persist_own"  # Your View and drafts (Phase 6C.3)
    SUBMIT_ENTRY = "challenge.submit"  # competitive entries (Phase 6C.3)
    # operator
    PUBLISH_ROUND = "round.publish"
    POSTPONE_ROUND = "round.postpone"
    RUN_JOBS = "jobs.run"
    CORRECT_RESULT = "result.correct"
    VOID_ROUND = "round.void"
    RENAME_USER = "user.rename"
    VIEW_AUDIT = "audit.view"
    SUSPEND_USER = "user.suspend"
    # owner
    REOPEN_CHAMPIONSHIP = "championship.reopen"
    MANAGE_ROLES = "roles.manage"
    MANAGE_ENTITLEMENTS = "entitlements.manage"


PARTICIPANT = frozenset(
    {Capability.MANAGE_OWN_ACCOUNT, Capability.PERSIST_OWN_ANALYSIS, Capability.SUBMIT_ENTRY}
)
OPERATOR = PARTICIPANT | {
    Capability.PUBLISH_ROUND,
    Capability.POSTPONE_ROUND,
    Capability.RUN_JOBS,
    Capability.CORRECT_RESULT,
    Capability.VOID_ROUND,
    Capability.RENAME_USER,
    Capability.VIEW_AUDIT,
    Capability.SUSPEND_USER,
}
OWNER = OPERATOR | {
    Capability.REOPEN_CHAMPIONSHIP,
    Capability.MANAGE_ROLES,
    Capability.MANAGE_ENTITLEMENTS,
}
ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    "participant": PARTICIPANT,
    "operator": OPERATOR,
    "owner": OWNER,
}

# Operator capabilities need a sign-in within 12 hours (T-12) ...
PRIVILEGED = OWNER - PARTICIPANT
# ... and these need credentials re-entered within 15 minutes (proposed, Phase 6C.2).
SENSITIVE = frozenset(
    {
        Capability.MANAGE_ROLES,
        Capability.MANAGE_ENTITLEMENTS,
        Capability.CORRECT_RESULT,
        Capability.VOID_ROUND,
        Capability.REOPEN_CHAMPIONSHIP,
        Capability.SUSPEND_USER,
    }
)


class AuthorizationError(Exception):
    """Base class. ``reason`` is a short code for logs; responses stay generic."""

    status = 403

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class NotAuthenticated(AuthorizationError):
    status = 401


class Forbidden(AuthorizationError):
    pass


class RecentAuthenticationRequired(AuthorizationError):
    status = 401


@dataclass(frozen=True)
class Principal:
    """Who is making the request, as established by the server."""

    user_id: UUID | None = None
    session_hash: str | None = None
    roles: frozenset[str] = frozenset()
    features: frozenset[str] = frozenset()
    onboarded: bool = False
    username: str | None = None
    authenticated_at: datetime | None = None
    reauthenticated_at: datetime | None = None
    now: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None

    def capabilities(self) -> frozenset[Capability]:
        if not self.is_authenticated or not self.onboarded:
            return frozenset()
        caps: set[Capability] = set()
        for role in self.roles | {"participant"}:
            caps |= ROLE_CAPABILITIES.get(role, frozenset())
        return frozenset(caps)


GUEST = Principal()


def authorize(principal: Principal, capability: Capability) -> None:
    """Raise unless ``principal`` may use ``capability`` right now."""
    if not principal.is_authenticated:
        raise NotAuthenticated("not_signed_in")
    if not principal.onboarded:
        raise Forbidden("onboarding_incomplete")
    if capability not in principal.capabilities():
        raise Forbidden(f"missing_capability:{capability}")
    now = principal.now
    if capability in PRIVILEGED:
        hours = principal.extra.get("operator_recency_hours", 12)
        if not _within(principal.authenticated_at, now, timedelta(hours=hours)):
            raise RecentAuthenticationRequired("operator_recency")
    if capability in SENSITIVE:
        minutes = principal.extra.get("sensitive_recency_minutes", 15)
        if not _within(principal.reauthenticated_at, now, timedelta(minutes=minutes)):
            raise RecentAuthenticationRequired("reauthentication_required")


def can(principal: Principal, capability: Capability) -> bool:
    try:
        authorize(principal, capability)
    except AuthorizationError:
        return False
    return True


def require_feature(principal: Principal, feature: str) -> None:
    """Feature entitlements (for example ``lucy.research``) are independent of roles."""
    if not principal.is_authenticated:
        raise NotAuthenticated("not_signed_in")
    if feature not in principal.features:
        raise Forbidden(f"missing_feature:{feature}")


def requires(capability: Capability) -> Callable:
    """Decorator for service functions whose first argument is the Principal."""

    def wrap(fn: Callable) -> Callable:
        @wraps(fn)
        def inner(principal: Principal, *args, **kwargs):
            authorize(principal, capability)
            return fn(principal, *args, **kwargs)

        inner.required_capability = capability  # type: ignore[attr-defined]
        return inner

    return wrap


def _within(moment: datetime | None, now: datetime | None, window: timedelta) -> bool:
    return moment is not None and now is not None and now - moment <= window
