"""Account lifecycle: identity mapping, onboarding, usernames and privacy.

Diski 9 user IDs are independent of the identity provider: ``user_identities``
maps ``(provider, subject)`` to an internal UUID. Roles, entitlements, usernames
and privacy live only in the Diski 9 database. No password ever reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, exists, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from ..db import db_now
from ..db.schema import (
    entitlement_grants,
    privacy_history,
    profiles,
    terms_acceptances,
    terms_versions,
    user_identities,
    user_private,
    user_roles,
    username_history,
    users,
)
from ..repositories.ops import record_audit
from .provider import ProviderIdentity
from .usernames import UsernameError, new_alias, validate

RENAME_INTERVAL = timedelta(days=30)


class AccountError(ValueError):
    """``str(exc)`` is safe to show to the user."""


class UsernameTaken(AccountError):
    def __init__(self):
        super().__init__("That username is already taken. Please choose another.")


@dataclass(frozen=True)
class AccountView:
    user_id: UUID
    status: str
    email: str | None
    email_verified: bool
    username: str | None
    privacy_mode: str | None
    anonymous_alias: str | None
    username_changed_at: datetime | None
    accepted_terms: frozenset[str]
    age_confirmed: bool
    roles: frozenset[str]
    features: frozenset[str]

    def onboarded(self, terms_version: str) -> bool:
        return bool(self.username) and self.age_confirmed and terms_version in self.accepted_terms


# ---------------------------------------------------------------- identity mapping
def ensure_app_user(conn: Connection, identity: ProviderIdentity) -> UUID:
    """The Diski 9 user for a verified provider identity, created on first use.

    Idempotent and safe under concurrency: a transaction-scoped advisory lock on
    the identity serialises first sign-ins, and ``UNIQUE (provider, subject)``
    backs it up. Only verified identities are accepted."""
    if not identity.email_verified:
        raise AccountError("Please confirm your email address first.")
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"diski9:identity:{identity.provider}:{identity.subject}"},
    )
    uid = conn.execute(
        select(user_identities.c.user_id).where(
            user_identities.c.provider == identity.provider,
            user_identities.c.subject == identity.subject,
        )
    ).scalar_one_or_none()
    now = db_now(conn)
    if uid is None:
        uid = conn.execute(insert(users).returning(users.c.id)).scalar_one()
        conn.execute(
            insert(user_identities).values(
                user_id=uid,
                provider=identity.provider,
                subject=identity.subject,
                last_sign_in_at=now,
            )
        )
        conn.execute(
            insert(user_private).values(
                user_id=uid, email=identity.email, email_verified=True, updated_at=now
            )
        )
        record_audit(
            conn,
            action="account.created",
            target_type="user",
            target_id=str(uid),
            actor=uid,
            actor_role="participant",
        )
    else:
        conn.execute(
            update(user_identities)
            .where(
                user_identities.c.provider == identity.provider,
                user_identities.c.subject == identity.subject,
            )
            .values(last_sign_in_at=now)
        )
        conn.execute(
            update(user_private)
            .where(user_private.c.user_id == uid)
            .values(email=identity.email, email_verified=True, updated_at=now)
        )
    return uid


def account(conn: Connection, user_id: UUID) -> AccountView:
    row = conn.execute(
        select(
            users.c.id,
            users.c.status,
            user_private.c.email,
            user_private.c.email_verified,
            user_private.c.age_confirmed_at,
            profiles.c.username,
            profiles.c.privacy_mode,
            profiles.c.anonymous_alias,
            profiles.c.username_changed_at,
        )
        .select_from(users)
        .outerjoin(user_private, user_private.c.user_id == users.c.id)
        .outerjoin(profiles, profiles.c.user_id == users.c.id)
        .where(users.c.id == user_id)
    ).one()
    terms = frozenset(
        conn.execute(
            select(terms_acceptances.c.terms_version).where(terms_acceptances.c.user_id == user_id)
        ).scalars()
    )
    roles = frozenset(
        conn.execute(select(user_roles.c.role).where(user_roles.c.user_id == user_id)).scalars()
    )
    now = func.transaction_timestamp()
    features = frozenset(
        conn.execute(
            select(entitlement_grants.c.feature_key).where(
                entitlement_grants.c.user_id == user_id,
                entitlement_grants.c.revoked_at.is_(None),
                entitlement_grants.c.valid_from <= now,
                (entitlement_grants.c.valid_to.is_(None)) | (entitlement_grants.c.valid_to > now),
            )
        ).scalars()
    )
    return AccountView(
        user_id=row.id,
        status=row.status,
        email=row.email,
        email_verified=bool(row.email_verified),
        username=row.username,
        privacy_mode=row.privacy_mode,
        anonymous_alias=row.anonymous_alias,
        username_changed_at=row.username_changed_at,
        accepted_terms=terms,
        age_confirmed=row.age_confirmed_at is not None,
        roles=roles,
        features=features,
    )


# ---------------------------------------------------------------- onboarding
def complete_onboarding(
    conn: Connection,
    user_id: UUID,
    *,
    username: str,
    terms_version: str,
    accepted_terms: bool,
    age_confirmed: bool,
) -> None:
    """Choose a username, declare 18+ and accept the current terms (once)."""
    if not accepted_terms:
        raise AccountError("Please accept the terms to continue.")
    if not age_confirmed:
        raise AccountError("You must be 18 or older to create an account.")
    if not conn.execute(select(exists().where(terms_versions.c.version == terms_version))).scalar():
        raise AccountError("The terms could not be found. Please reload the page.")
    try:
        name = validate(username)
    except UsernameError as exc:
        raise AccountError(str(exc)) from None
    now = db_now(conn)
    if conn.execute(select(profiles.c.user_id).where(profiles.c.user_id == user_id)).first():
        raise AccountError("Your account is already set up.")
    try:
        with conn.begin_nested():
            for _ in range(5):
                alias = new_alias()
                taken = conn.execute(
                    select(profiles.c.user_id).where(profiles.c.anonymous_alias == alias)
                ).first()
                if not taken:
                    break
            conn.execute(
                insert(profiles).values(
                    user_id=user_id,
                    username=name.display,
                    username_key=name.key,
                    username_changed_at=now,
                    privacy_mode="public",
                    anonymous_alias=alias,
                    updated_at=now,
                )
            )
    except IntegrityError as exc:
        if "profiles_username_key" in str(exc.orig):
            raise UsernameTaken() from None
        raise
    conn.execute(
        insert(username_history).values(
            user_id=user_id,
            username=name.display,
            valid_from=now,
            changed_by=user_id,
            reason="onboarding",
        )
    )
    conn.execute(
        insert(privacy_history).values(
            user_id=user_id, privacy_mode="public", retroactive=False, effective_at=now
        )
    )
    conn.execute(
        insert(terms_acceptances).values(
            user_id=user_id, terms_version=terms_version, accepted_at=now, age_confirmed=True
        )
    )
    conn.execute(
        update(user_private)
        .where(user_private.c.user_id == user_id)
        .values(age_confirmed_at=now, updated_at=now)
    )
    record_audit(
        conn,
        action="account.onboarded",
        target_type="user",
        target_id=str(user_id),
        actor=user_id,
        actor_role="participant",
        after={"terms_version": terms_version},
    )


def accept_terms(conn: Connection, user_id: UUID, terms_version: str) -> None:
    """Accept a newer terms version (an existing account); repeating it is harmless."""
    conn.execute(
        pg_insert(terms_acceptances)
        .values(user_id=user_id, terms_version=terms_version, age_confirmed=True)
        .on_conflict_do_nothing(index_elements=["user_id", "terms_version"])
    )


def change_username(
    conn: Connection,
    user_id: UUID,
    new_username: str,
    *,
    by_operator: UUID | None = None,
    reason: str | None = None,
) -> str:
    """One normal change every 30 days (D-05); operators may rename with a reason."""
    try:
        name = validate(new_username)
    except UsernameError as exc:
        raise AccountError(str(exc)) from None
    now = db_now(conn)
    row = conn.execute(
        select(profiles).where(profiles.c.user_id == user_id).with_for_update()
    ).one_or_none()
    if row is None:
        raise AccountError("Please finish setting up your account first.")
    if name.display == row.username:
        raise AccountError("That is already your username.")
    if by_operator is None and now - row.username_changed_at < RENAME_INTERVAL:
        allowed = (row.username_changed_at + RENAME_INTERVAL).date().isoformat()
        raise AccountError(f"You can change your username again from {allowed}.")
    if by_operator is not None and not (reason or "").strip():
        raise AccountError("An operator rename needs a reason.")
    try:
        with conn.begin_nested():
            conn.execute(
                update(profiles)
                .where(profiles.c.user_id == user_id)
                .values(
                    username=name.display,
                    username_key=name.key,
                    username_changed_at=now,
                    updated_at=now,
                )
            )
    except IntegrityError as exc:
        if "profiles_username_key" in str(exc.orig):
            raise UsernameTaken() from None
        raise
    actor = by_operator or user_id
    conn.execute(
        insert(username_history).values(
            user_id=user_id,
            username=name.display,
            valid_from=now,
            changed_by=actor,
            reason=reason or "self-service change",
        )
    )
    record_audit(
        conn,
        action="account.username_changed",
        target_type="user",
        target_id=str(user_id),
        actor=actor,
        actor_role="operator" if by_operator else "participant",
        reason=reason,
        before={"username": row.username},
        after={"username": name.display},
    )
    return name.display


def set_privacy(conn: Connection, user_id: UUID, mode: str, *, retroactive: bool = False) -> None:
    """Public or anonymous leaderboard display (D-04). Anonymity can be applied to
    past entries (``retroactive``) and is never removed from them afterwards:
    switching back to public affects only entries locked later."""
    if mode not in ("public", "anonymous"):
        raise AccountError("Unknown privacy setting.")
    if retroactive and mode != "anonymous":
        raise AccountError("Only anonymity can be applied to past entries.")
    now = db_now(conn)
    row = conn.execute(
        select(profiles.c.privacy_mode).where(profiles.c.user_id == user_id).with_for_update()
    ).one_or_none()
    if row is None:
        raise AccountError("Please finish setting up your account first.")
    conn.execute(
        update(profiles)
        .where(profiles.c.user_id == user_id)
        .values(privacy_mode=mode, updated_at=now)
    )
    conn.execute(
        insert(privacy_history).values(
            user_id=user_id, privacy_mode=mode, retroactive=retroactive, effective_at=now
        )
    )
    record_audit(
        conn,
        action="account.privacy_changed",
        target_type="user",
        target_id=str(user_id),
        actor=user_id,
        actor_role="participant",
        before={"privacy_mode": row.privacy_mode},
        after={"privacy_mode": mode, "retroactive": retroactive},
    )


def lock_snapshot(conn: Connection, user_id: UUID) -> tuple[str, str]:
    """(public name, privacy mode) to record on an entry when it locks (Phase 6C.3)."""
    row = conn.execute(
        select(profiles.c.username, profiles.c.privacy_mode).where(profiles.c.user_id == user_id)
    ).one()
    return row.username, row.privacy_mode


def leaderboard_name(
    conn: Connection,
    *,
    user_id: UUID,
    locked_at: datetime,
    public_name_at_lock: str,
    privacy_mode_at_lock: str,
) -> str:
    """The only name a leaderboard may show for an entry: the username recorded at
    lock, or the anonymous alias if the entry was anonymous at lock, if anonymity
    was later applied retroactively, or if the account is deleted. Never an email
    address or an internal ID."""
    alias, status = conn.execute(
        select(profiles.c.anonymous_alias, users.c.status)
        .select_from(users)
        .outerjoin(profiles, profiles.c.user_id == users.c.id)
        .where(users.c.id == user_id)
    ).one()
    alias = alias or "Former participant"
    if status == "deleted" or privacy_mode_at_lock == "anonymous":
        return alias
    hidden = conn.execute(
        select(
            exists().where(
                privacy_history.c.user_id == user_id,
                privacy_history.c.privacy_mode == "anonymous",
                privacy_history.c.retroactive.is_(True),
                privacy_history.c.effective_at >= locked_at,
            )
        )
    ).scalar()
    return alias if hidden else public_name_at_lock
