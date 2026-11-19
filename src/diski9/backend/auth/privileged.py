"""Privileged account administration: roles, entitlements and suspension.

There is no web route for any of this. These functions are called from the
server command line (``diski9 account ...``) by someone with database access, and
every change is written to the immutable audit log in the same transaction.

* **Owner bootstrap** works exactly once: it succeeds only while no owner exists,
  for an existing, active, onboarded account whose email is verified.
* Afterwards roles and entitlements can be changed only by an existing active
  owner (named explicitly as the actor), with a reason.
* Suspension revokes every session of the account immediately.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, delete, func, insert, select, text, update

from ..db.schema import entitlement_grants, features, profiles, user_private, user_roles, users
from ..repositories.ops import record_audit

ROLES = ("operator", "owner")
OWNER_FEATURES = ("lucy.research", "lucy.voice", "lucy.presenter")


class PrivilegeError(RuntimeError):
    pass


def _lock(conn: Connection) -> None:
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('diski9:roles', 0))"))


def find_user_by_email(conn: Connection, email: str) -> UUID:
    rows = (
        conn.execute(
            select(user_private.c.user_id).where(
                func.lower(user_private.c.email) == email.strip().lower(),
                user_private.c.email_verified.is_(True),
            )
        )
        .scalars()
        .all()
    )
    if len(rows) != 1:
        raise PrivilegeError("no single verified account with that email address")
    return rows[0]


def _require_active_onboarded(conn: Connection, user_id: UUID) -> None:
    row = conn.execute(
        select(users.c.status, profiles.c.user_id)
        .select_from(users)
        .outerjoin(profiles, profiles.c.user_id == users.c.id)
        .where(users.c.id == user_id)
    ).one_or_none()
    if row is None or row.status != "active" or row.user_id is None:
        raise PrivilegeError("the account must exist, be active and have finished set-up")


def _require_owner(conn: Connection, actor: UUID) -> None:
    ok = conn.execute(
        select(users.c.id)
        .join(user_roles, user_roles.c.user_id == users.c.id)
        .where(users.c.id == actor, users.c.status == "active", user_roles.c.role == "owner")
    ).first()
    if not ok:
        raise PrivilegeError("only an active owner can change roles or entitlements")


def owner_count(conn: Connection) -> int:
    return conn.execute(
        select(func.count()).select_from(user_roles).where(user_roles.c.role == "owner")
    ).scalar_one()


def bootstrap_owner(conn: Connection, user_id: UUID, reason: str) -> None:
    """Grant the first owner role (and the owner-only Lucy entitlements)."""
    _lock(conn)
    if owner_count(conn) > 0:
        raise PrivilegeError("an owner already exists; use grant-role as that owner")
    _require_active_onboarded(conn, user_id)
    conn.execute(insert(user_roles).values(user_id=user_id, role="owner", granted_by=None))
    for f in OWNER_FEATURES:
        conn.execute(
            insert(entitlement_grants).values(
                user_id=user_id,
                feature_key=f,
                source="owner",
                granted_by=user_id,
                reason="owner bootstrap",
            )
        )
    record_audit(
        conn,
        action="role.bootstrap_owner",
        target_type="user",
        target_id=str(user_id),
        actor_role="system",
        reason=reason or "bootstrap",
        after={"role": "owner", "features": list(OWNER_FEATURES)},
    )


def grant_role(conn: Connection, actor: UUID, user_id: UUID, role: str, reason: str) -> None:
    if role not in ROLES:
        raise PrivilegeError(f"unknown role {role!r}")
    if not reason.strip():
        raise PrivilegeError("a reason is required")
    _lock(conn)
    _require_owner(conn, actor)
    _require_active_onboarded(conn, user_id)
    exists = conn.execute(
        select(user_roles.c.role).where(user_roles.c.user_id == user_id, user_roles.c.role == role)
    ).first()
    if exists:
        raise PrivilegeError("the account already has that role")
    conn.execute(insert(user_roles).values(user_id=user_id, role=role, granted_by=actor))
    record_audit(
        conn,
        action="role.granted",
        target_type="user",
        target_id=str(user_id),
        actor=actor,
        actor_role="owner",
        reason=reason,
        after={"role": role},
    )


def revoke_role(conn: Connection, actor: UUID, user_id: UUID, role: str, reason: str) -> None:
    if not reason.strip():
        raise PrivilegeError("a reason is required")
    _lock(conn)
    _require_owner(conn, actor)
    if role == "owner" and owner_count(conn) <= 1:
        raise PrivilegeError("the last owner cannot be removed")
    res = conn.execute(
        delete(user_roles).where(user_roles.c.user_id == user_id, user_roles.c.role == role)
    )
    if res.rowcount != 1:
        raise PrivilegeError("the account does not have that role")
    record_audit(
        conn,
        action="role.revoked",
        target_type="user",
        target_id=str(user_id),
        actor=actor,
        actor_role="owner",
        reason=reason,
        before={"role": role},
    )


def grant_feature(conn: Connection, actor: UUID, user_id: UUID, feature: str, reason: str) -> None:
    if not reason.strip():
        raise PrivilegeError("a reason is required")
    _lock(conn)
    _require_owner(conn, actor)
    _require_active_onboarded(conn, user_id)
    if not conn.execute(select(features.c.key).where(features.c.key == feature)).first():
        raise PrivilegeError(f"unknown feature {feature!r}")
    live = conn.execute(
        select(entitlement_grants.c.id).where(
            entitlement_grants.c.user_id == user_id,
            entitlement_grants.c.feature_key == feature,
            entitlement_grants.c.revoked_at.is_(None),
        )
    ).first()
    if live:
        raise PrivilegeError("the account already has that entitlement")
    conn.execute(
        insert(entitlement_grants).values(
            user_id=user_id, feature_key=feature, source="manual", granted_by=actor, reason=reason
        )
    )
    record_audit(
        conn,
        action="entitlement.granted",
        target_type="user",
        target_id=str(user_id),
        actor=actor,
        actor_role="owner",
        reason=reason,
        after={"feature": feature},
    )


def revoke_feature(conn: Connection, actor: UUID, user_id: UUID, feature: str, reason: str) -> None:
    if not reason.strip():
        raise PrivilegeError("a reason is required")
    _lock(conn)
    _require_owner(conn, actor)
    res = conn.execute(
        update(entitlement_grants)
        .where(
            entitlement_grants.c.user_id == user_id,
            entitlement_grants.c.feature_key == feature,
            entitlement_grants.c.revoked_at.is_(None),
        )
        .values(revoked_at=func.transaction_timestamp(), revoked_by=actor, revoke_reason=reason)
    )
    if res.rowcount != 1:
        raise PrivilegeError("the account does not have that entitlement")
    record_audit(
        conn,
        action="entitlement.revoked",
        target_type="user",
        target_id=str(user_id),
        actor=actor,
        actor_role="owner",
        reason=reason,
        before={"feature": feature},
    )


def set_status(
    conn: Connection, actor: UUID, user_id: UUID, status: str, reason: str, revoke_sessions
) -> None:
    """Suspend or reinstate an account (operators and owners; audited)."""
    if status not in ("active", "suspended"):
        raise PrivilegeError("status must be active or suspended")
    if not reason.strip():
        raise PrivilegeError("a reason is required")
    actor_ok = conn.execute(
        select(users.c.id)
        .join(user_roles, user_roles.c.user_id == users.c.id)
        .where(
            users.c.id == actor,
            users.c.status == "active",
            user_roles.c.role.in_(("operator", "owner")),
        )
    ).first()
    if not actor_ok:
        raise PrivilegeError("only an active operator or owner can change account status")
    if actor == user_id:
        raise PrivilegeError("you cannot change your own account status")
    before = conn.execute(select(users.c.status).where(users.c.id == user_id)).scalar_one()
    conn.execute(update(users).where(users.c.id == user_id).values(status=status))
    if status == "suspended":
        revoke_sessions(conn, user_id, "account_suspended")
    record_audit(
        conn,
        action=f"account.{'suspended' if status == 'suspended' else 'reinstated'}",
        target_type="user",
        target_id=str(user_id),
        actor=actor,
        actor_role="operator",
        reason=reason,
        before={"status": before},
        after={"status": status},
    )
