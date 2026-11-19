"""Accounts data access: users, identity links, profiles, roles, entitlements, terms.

Plain functions taking an open :class:`~sqlalchemy.Connection` inside the caller's
transaction. Business rules (the 30-day rename rule, blocklists, sign-in) belong to
the Phase 6C.2 services; these functions only read and write rows.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, and_, func, insert, or_, select, update

from ..db.schema import (
    entitlement_grants,
    profiles,
    terms_acceptances,
    user_identities,
    user_roles,
    username_history,
    users,
)

ROLES = frozenset({"operator", "owner"})


def create_user(conn: Connection) -> UUID:
    return conn.execute(insert(users).returning(users.c.id)).scalar_one()


def link_identity(conn: Connection, user_id: UUID, provider: str, subject: str) -> None:
    conn.execute(
        insert(user_identities).values(user_id=user_id, provider=provider, subject=subject)
    )


def find_user_by_identity(conn: Connection, provider: str, subject: str) -> UUID | None:
    return conn.execute(
        select(user_identities.c.user_id).where(
            user_identities.c.provider == provider, user_identities.c.subject == subject
        )
    ).scalar_one_or_none()


def create_profile(
    conn: Connection,
    user_id: UUID,
    username: str,
    anonymous_alias: str,
    changed_by: UUID | None = None,
) -> None:
    conn.execute(
        insert(profiles).values(
            user_id=user_id,
            username=username,
            username_key=username.lower(),
            anonymous_alias=anonymous_alias,
        )
    )
    conn.execute(
        insert(username_history).values(
            user_id=user_id, username=username, changed_by=changed_by or user_id
        )
    )


def username_taken(conn: Connection, username: str) -> bool:
    return (
        conn.execute(
            select(func.count())
            .select_from(profiles)
            .where(profiles.c.username_key == username.lower())
        ).scalar_one()
        > 0
    )


def grant_role(conn: Connection, user_id: UUID, role: str, granted_by: UUID | None) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    conn.execute(insert(user_roles).values(user_id=user_id, role=role, granted_by=granted_by))


def roles_of(conn: Connection, user_id: UUID) -> frozenset[str]:
    rows = conn.execute(select(user_roles.c.role).where(user_roles.c.user_id == user_id))
    return frozenset({"participant", *(r.role for r in rows)})


def grant_feature(
    conn: Connection,
    user_id: UUID,
    feature_key: str,
    source: str,
    granted_by: UUID | None,
    reason: str | None = None,
) -> int:
    return conn.execute(
        insert(entitlement_grants)
        .values(
            user_id=user_id,
            feature_key=feature_key,
            source=source,
            granted_by=granted_by,
            reason=reason,
        )
        .returning(entitlement_grants.c.id)
    ).scalar_one()


def revoke_feature(
    conn: Connection, user_id: UUID, feature_key: str, revoked_by: UUID, reason: str
) -> bool:
    res = conn.execute(
        update(entitlement_grants)
        .where(
            entitlement_grants.c.user_id == user_id,
            entitlement_grants.c.feature_key == feature_key,
            entitlement_grants.c.revoked_at.is_(None),
        )
        .values(
            revoked_at=func.transaction_timestamp(), revoked_by=revoked_by, revoke_reason=reason
        )
    )
    return res.rowcount == 1


def live_features(conn: Connection, user_id: UUID, at: datetime | None = None) -> frozenset[str]:
    moment = at if at is not None else func.transaction_timestamp()
    rows = conn.execute(
        select(entitlement_grants.c.feature_key).where(
            entitlement_grants.c.user_id == user_id,
            entitlement_grants.c.revoked_at.is_(None),
            entitlement_grants.c.valid_from <= moment,
            or_(entitlement_grants.c.valid_to.is_(None), entitlement_grants.c.valid_to > moment),
        )
    )
    return frozenset(r.feature_key for r in rows)


def record_terms_acceptance(conn: Connection, user_id: UUID, version: str) -> None:
    conn.execute(
        insert(terms_acceptances).values(user_id=user_id, terms_version=version, age_confirmed=True)
    )


def has_accepted(conn: Connection, user_id: UUID, version: str) -> bool:
    return (
        conn.execute(
            select(func.count())
            .select_from(terms_acceptances)
            .where(
                and_(
                    terms_acceptances.c.user_id == user_id,
                    terms_acceptances.c.terms_version == version,
                )
            )
        ).scalar_one()
        > 0
    )
