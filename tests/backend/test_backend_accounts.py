"""Accounts, usernames, privacy, sessions and privileged administration on REAL
PostgreSQL with a MOCK identity provider (``FakeProvider``)."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from auth_helpers import FakeProvider, make_settings
from sqlalchemy import select, text, update

from diski9.backend.auth import accounts as acct
from diski9.backend.auth import privileged as pv
from diski9.backend.auth import ratelimit as rl
from diski9.backend.auth.provider import ProviderIdentity
from diski9.backend.auth.sessions import SessionManager, revoke_all_sessions
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import (
    app_sessions,
    audit_log,
    entitlement_grants,
    profiles,
    user_identities,
    user_roles,
    username_history,
    users,
)

TERMS = "beta-2026-11"


def identity(email=None, verified=True, subject=None):
    return ProviderIdentity(
        "supabase",
        subject or str(uuid.uuid4()),
        email or f"{uuid.uuid4().hex[:8]}@example.com",
        verified,
    )


def onboarded_user(engine, name=None):
    ident = identity()
    with transaction(engine) as conn:
        uid = acct.ensure_app_user(conn, ident)
        acct.complete_onboarding(
            conn,
            uid,
            username=name or f"user{uuid.uuid4().hex[:8]}",
            terms_version=TERMS,
            accepted_terms=True,
            age_confirmed=True,
        )
    return uid, ident


# ---------------------------------------------------------------- identity mapping
def test_identity_mapping_is_idempotent(engine):
    ident = identity()
    with transaction(engine) as conn:
        a = acct.ensure_app_user(conn, ident)
    with transaction(engine) as conn:
        b = acct.ensure_app_user(conn, ident)
    assert a == b


def test_unverified_identities_are_not_mapped(engine):
    with pytest.raises(acct.AccountError), transaction(engine) as conn:
        acct.ensure_app_user(conn, identity(verified=False))


def test_concurrent_first_sign_ins_create_one_user(engine):
    ident = identity()
    barrier = threading.Barrier(6)

    def go(_):
        barrier.wait()
        with transaction(engine) as conn:
            return acct.ensure_app_user(conn, ident)

    with ThreadPoolExecutor(6) as pool:
        ids = set(pool.map(go, range(6)))
    assert len(ids) == 1
    with transaction(engine) as conn:
        n = conn.execute(
            select(user_identities).where(user_identities.c.subject == ident.subject)
        ).all()
    assert len(n) == 1


def test_internal_ids_are_independent_of_provider_ids(engine):
    ident = identity()
    with transaction(engine) as conn:
        uid = acct.ensure_app_user(conn, ident)
    assert str(uid) != ident.subject


# ---------------------------------------------------------------- onboarding
def test_onboarding_requires_terms_and_age(engine):
    ident = identity()
    with transaction(engine) as conn:
        uid = acct.ensure_app_user(conn, ident)
    for kwargs in (
        {"accepted_terms": False, "age_confirmed": True},
        {"accepted_terms": True, "age_confirmed": False},
    ):
        with pytest.raises(acct.AccountError), transaction(engine) as conn:
            acct.complete_onboarding(
                conn, uid, username="Valid Name", terms_version=TERMS, **kwargs
            )
    with pytest.raises(acct.AccountError), transaction(engine) as conn:
        acct.complete_onboarding(
            conn,
            uid,
            username="Valid Name",
            terms_version="v-unknown",
            accepted_terms=True,
            age_confirmed=True,
        )
    with transaction(engine) as conn:
        view = acct.account(conn, uid)
    assert not view.onboarded(TERMS)


def test_onboarding_records_terms_age_history_and_audit(engine):
    uid, _ = onboarded_user(engine, name=f"Onb{uuid.uuid4().hex[:6]}")
    with transaction(engine) as conn:
        view = acct.account(conn, uid)
        hist = conn.execute(select(username_history).where(username_history.c.user_id == uid))
        audits = (
            conn.execute(select(audit_log.c.action).where(audit_log.c.target_id == str(uid)))
            .scalars()
            .all()
        )
    assert view.onboarded(TERMS) and view.age_confirmed and TERMS in view.accepted_terms
    assert view.privacy_mode == "public" and view.anonymous_alias.startswith("Anonymous ")
    assert len(hist.all()) == 1
    assert {"account.created", "account.onboarded"} <= set(audits)


def test_concurrent_username_claims_one_wins(engine):
    name = f"Race{uuid.uuid4().hex[:6]}"
    uids = []
    for _ in range(5):
        with transaction(engine) as conn:
            uids.append(acct.ensure_app_user(conn, identity()))
    barrier = threading.Barrier(5)

    def claim(i):
        barrier.wait()
        try:
            with transaction(engine) as conn:
                acct.complete_onboarding(
                    conn,
                    uids[i],
                    username=name.upper() if i % 2 else name,
                    terms_version=TERMS,
                    accepted_terms=True,
                    age_confirmed=True,
                )
            return "ok"
        except acct.UsernameTaken:
            return "taken"

    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(claim, range(5)))
    assert results.count("ok") == 1 and results.count("taken") == 4


def test_username_change_once_per_30_days(engine):
    uid, _ = onboarded_user(engine)
    new = f"Renamed{uuid.uuid4().hex[:6]}"
    with transaction(engine) as conn:  # the onboarding choice is "now": too soon
        with pytest.raises(acct.AccountError, match="again from"):
            acct.change_username(conn, uid, new)
        conn.execute(
            update(profiles)
            .where(profiles.c.user_id == uid)
            .values(username_changed_at=db_now(conn) - timedelta(days=31))
        )
    with transaction(engine) as conn:
        assert acct.change_username(conn, uid, new) == new
    with pytest.raises(acct.AccountError), transaction(engine) as conn:
        acct.change_username(conn, uid, f"Again{uuid.uuid4().hex[:6]}")
    with transaction(engine) as conn:
        names = (
            conn.execute(
                select(username_history.c.username)
                .where(username_history.c.user_id == uid)
                .order_by(username_history.c.id)
            )
            .scalars()
            .all()
        )
    assert names[-1] == new and len(names) == 2


def test_operator_rename_needs_reason_and_is_audited(engine):
    uid, _ = onboarded_user(engine)
    op_uid, _ = onboarded_user(engine)
    with pytest.raises(acct.AccountError), transaction(engine) as conn:
        acct.change_username(conn, uid, f"Mod{uuid.uuid4().hex[:6]}", by_operator=op_uid)
    with transaction(engine) as conn:
        acct.change_username(
            conn, uid, f"Mod{uuid.uuid4().hex[:6]}", by_operator=op_uid, reason="offensive name"
        )
        row = conn.execute(
            select(audit_log).where(
                audit_log.c.action == "account.username_changed", audit_log.c.target_id == str(uid)
            )
        ).one()
    assert row.actor_user_id == op_uid and row.reason == "offensive name"


# ---------------------------------------------------------------- privacy
def _name(conn, uid, locked_at, mode="public", public="Shown Name"):
    return acct.leaderboard_name(
        conn,
        user_id=uid,
        locked_at=locked_at,
        public_name_at_lock=public,
        privacy_mode_at_lock=mode,
    )


def test_retroactive_anonymity_hides_past_entries_permanently(engine):
    uid, _ = onboarded_user(engine)
    with transaction(engine) as conn:
        alias = acct.account(conn, uid).anonymous_alias
        before = db_now(conn) - timedelta(days=3)
        assert _name(conn, uid, before) == "Shown Name"
        assert _name(conn, uid, before, mode="anonymous") == alias
    with transaction(engine) as conn:
        acct.set_privacy(conn, uid, "anonymous", retroactive=True)
    with transaction(engine) as conn:
        assert _name(conn, uid, before) == alias  # past public entry now hidden
    with transaction(engine) as conn:
        acct.set_privacy(conn, uid, "public")
    with transaction(engine) as conn:
        assert _name(conn, uid, before) == alias  # anonymity never removed retroactively
        later = db_now(conn) + timedelta(days=1)
        assert _name(conn, uid, later, public="New Public") == "New Public"


def test_non_retroactive_anonymity_affects_only_later_entries(engine):
    uid, _ = onboarded_user(engine)
    with transaction(engine) as conn:
        before = db_now(conn) - timedelta(days=1)
    with transaction(engine) as conn:
        acct.set_privacy(conn, uid, "anonymous", retroactive=False)
    with transaction(engine) as conn:
        assert _name(conn, uid, before) == "Shown Name"
    with pytest.raises(acct.AccountError), transaction(engine) as conn:
        acct.set_privacy(conn, uid, "public", retroactive=True)


def test_leaderboard_names_never_contain_email_or_ids(engine):
    uid, ident = onboarded_user(engine)
    with transaction(engine) as conn:
        name = _name(conn, uid, db_now(conn), mode="anonymous")
    assert ident.email not in name and str(uid) not in name and ident.subject not in name


# ---------------------------------------------------------------- sessions
@pytest.fixture
def mgr(engine):
    return SessionManager(engine, FakeProvider(), make_settings())


def _start(engine, mgr, uid=None, email=None):
    email = email or f"{uuid.uuid4().hex[:8]}@example.com"
    mgr.provider.add_user(email, "pw-1234567890")
    ps = mgr.provider.sign_in_with_password(email, "pw-1234567890")
    if uid is None:
        with transaction(engine) as conn:
            uid = acct.ensure_app_user(conn, ps.identity)
    with transaction(engine) as conn:
        token = mgr.start(conn, uid, ps)
    return uid, token, email


def test_session_token_is_stored_only_as_a_hash(engine, mgr):
    _, token, _ = _start(engine, mgr)
    with transaction(engine) as conn:
        rows = conn.execute(
            select(app_sessions.c.id, app_sessions.c.provider_refresh_token_enc)
            .order_by(app_sessions.c.created_at.desc())
            .limit(1)
        ).one()
    assert token not in rows.id and rows.id != token
    assert "rt-" not in rows.provider_refresh_token_enc  # provider token encrypted


def test_resolve_and_lifetimes(engine, mgr):
    _, token, _ = _start(engine, mgr)
    s = mgr.resolve(token)
    assert s is not None
    assert s.absolute_expires_at - s.created_at == timedelta(days=30)
    assert s.idle_expires_at - s.created_at == timedelta(days=14)
    assert mgr.resolve("not-a-real-token") is None
    assert mgr.resolve(None) is None


@pytest.mark.parametrize(
    ("column", "reason"),
    [("idle_expires_at", "expired_idle"), ("absolute_expires_at", "expired_absolute")],
)
def test_expired_sessions_are_rejected_and_revoked(engine, mgr, column, reason):
    _, token, _ = _start(engine, mgr)
    h = mgr.resolve(token).id
    with transaction(engine) as conn:
        conn.execute(
            text(
                f"UPDATE app.app_sessions SET {column} = now() - interval '1 second', "
                "idle_expires_at = LEAST(idle_expires_at, now() - interval '1 second') "
                "WHERE id = :h"
                if column == "absolute_expires_at"
                else f"UPDATE app.app_sessions SET {column} = now() - interval '1 second' "
                "WHERE id = :h"
            ),
            {"h": h},
        )
    assert mgr.resolve(token) is None
    with transaction(engine) as conn:
        assert (
            conn.execute(
                select(app_sessions.c.revoked_reason).where(app_sessions.c.id == h)
            ).scalar_one()
            == reason
        )


def test_rotation_invalidates_the_old_token(engine, mgr):
    _, token, _ = _start(engine, mgr)
    h = mgr.resolve(token).id
    with transaction(engine) as conn:
        new = mgr.rotate(conn, h, reauthenticated=True)
    assert mgr.resolve(token) is None
    s = mgr.resolve(new)
    assert s is not None and s.reauthenticated_at is not None
    with transaction(engine) as conn:
        assert (
            conn.execute(
                select(app_sessions.c.rotated_from).where(app_sessions.c.id == s.id)
            ).scalar_one()
            == h
        )


def test_suspension_ends_every_session(engine, mgr):
    uid, token, _ = _start(engine, mgr)
    _, token2, _ = _start(engine, mgr, uid=uid)
    with transaction(engine) as conn:
        conn.execute(update(users).where(users.c.id == uid).values(status="suspended"))
    assert mgr.resolve(token) is None and mgr.resolve(token2) is None


def test_provider_revocation_ends_the_app_session_at_refresh(engine, mgr):
    _, token, email = _start(engine, mgr)
    h = mgr.resolve(token).id
    mgr.provider.end_all_sessions(email)  # e.g. password changed or banned at Supabase
    with transaction(engine) as conn:  # access token near expiry: next request refreshes
        conn.execute(
            update(app_sessions)
            .where(app_sessions.c.id == h)
            .values(provider_access_expires_at=db_now(conn))
        )
    assert mgr.resolve(token) is None
    with transaction(engine) as conn:
        assert (
            conn.execute(
                select(app_sessions.c.revoked_reason).where(app_sessions.c.id == h)
            ).scalar_one()
            == "provider_session_ended"
        )


def test_refresh_rotates_provider_tokens_once_under_concurrency(engine, mgr):
    _, token, _ = _start(engine, mgr)
    h = mgr.resolve(token).id
    with transaction(engine) as conn:
        conn.execute(
            update(app_sessions)
            .where(app_sessions.c.id == h)
            .values(provider_access_expires_at=db_now(conn))
        )
    mgr.provider.calls.clear()
    barrier = threading.Barrier(4)

    def go(_):
        barrier.wait()
        return mgr.resolve(token) is not None

    with ThreadPoolExecutor(4) as pool:
        assert all(pool.map(go, range(4)))
    assert mgr.provider.calls.count("refresh") == 1  # single-use refresh token used once


def test_privileged_check_fails_closed_when_provider_is_down(engine, mgr):
    _, token, _ = _start(engine, mgr)
    h = mgr.resolve(token).id
    assert mgr.verify_with_provider(h)
    mgr.provider.down = True
    assert not mgr.verify_with_provider(h)  # privileged: refuse
    assert mgr.resolve(token) is not None  # ordinary browsing continues


def test_revoke_all_sessions(engine, mgr):
    uid, t1, _ = _start(engine, mgr)
    _, t2, _ = _start(engine, mgr, uid=uid)
    with transaction(engine) as conn:
        assert revoke_all_sessions(conn, uid, "sign_out_everywhere") == 2
    assert mgr.resolve(t1) is None and mgr.resolve(t2) is None


# ---------------------------------------------------------------- privileged administration
def _no_owners(engine):
    with transaction(engine) as conn:
        conn.execute(text("DELETE FROM app.user_roles WHERE role = 'owner'"))


def test_owner_bootstrap_works_once(engine):
    _no_owners(engine)
    first, _ = onboarded_user(engine)
    second, _ = onboarded_user(engine)
    with transaction(engine) as conn:
        pv.bootstrap_owner(conn, first, "initial owner")
    with pytest.raises(pv.PrivilegeError, match="already exists"), transaction(engine) as conn:
        pv.bootstrap_owner(conn, second, "second attempt")
    with transaction(engine) as conn:
        feats = set(
            conn.execute(
                select(entitlement_grants.c.feature_key).where(
                    entitlement_grants.c.user_id == first, entitlement_grants.c.revoked_at.is_(None)
                )
            ).scalars()
        )
        audit = (
            conn.execute(select(audit_log.c.action).where(audit_log.c.target_id == str(first)))
            .scalars()
            .all()
        )
    assert feats == {"lucy.research", "lucy.voice", "lucy.presenter"}
    assert "role.bootstrap_owner" in audit


def test_bootstrap_requires_an_onboarded_active_account(engine):
    _no_owners(engine)
    with transaction(engine) as conn:
        uid = acct.ensure_app_user(conn, identity())
    with pytest.raises(pv.PrivilegeError), transaction(engine) as conn:
        pv.bootstrap_owner(conn, uid, "not onboarded")


def test_no_self_escalation_and_owner_only_changes(engine):
    _no_owners(engine)
    owner, _ = onboarded_user(engine)
    member, _ = onboarded_user(engine)
    other, _ = onboarded_user(engine)
    with transaction(engine) as conn:
        pv.bootstrap_owner(conn, owner, "initial")
    for actor in (member, other):  # participants cannot grant anything, even to themselves
        with pytest.raises(pv.PrivilegeError), transaction(engine) as conn:
            pv.grant_role(conn, actor, actor, "owner", "self")
        with pytest.raises(pv.PrivilegeError), transaction(engine) as conn:
            pv.grant_feature(conn, actor, actor, "lucy.research", "self")
    with transaction(engine) as conn:
        pv.grant_role(conn, owner, member, "operator", "run rounds")
    with pytest.raises(pv.PrivilegeError), transaction(engine) as conn:  # operators are not owners
        pv.grant_role(conn, member, other, "operator", "delegate")
    with pytest.raises(pv.PrivilegeError, match="reason"), transaction(engine) as conn:
        pv.grant_feature(conn, owner, other, "lucy.research", " ")
    with transaction(engine) as conn:
        pv.grant_feature(conn, owner, other, "lucy.research", "premium pilot")
        roles = set(
            conn.execute(select(user_roles.c.role).where(user_roles.c.user_id == other)).scalars()
        )
    assert roles == set()  # entitlement without any role
    with pytest.raises(pv.PrivilegeError, match="last owner"), transaction(engine) as conn:
        pv.revoke_role(conn, owner, owner, "owner", "oops")


def test_suspension_by_operator_revokes_sessions_and_is_audited(engine, mgr):
    _no_owners(engine)
    owner, _ = onboarded_user(engine)
    with transaction(engine) as conn:
        pv.bootstrap_owner(conn, owner, "initial")
    target, token, _ = _start(engine, mgr)
    with pytest.raises(pv.PrivilegeError), transaction(engine) as conn:
        pv.set_status(conn, target, owner, "suspended", "revenge", revoke_all_sessions)
    with transaction(engine) as conn:
        pv.set_status(conn, owner, target, "suspended", "abuse", revoke_all_sessions)
    assert mgr.resolve(token) is None
    with pytest.raises(pv.PrivilegeError), transaction(engine) as conn:
        pv.set_status(conn, owner, owner, "suspended", "self", revoke_all_sessions)


# ---------------------------------------------------------------- rate limits
def test_rate_limits_by_hashed_key(engine):
    lim = rl.Limit(f"test:{uuid.uuid4().hex[:6]}", 3, timedelta(minutes=5))
    secret = b"k" * 32
    with transaction(engine) as conn:
        results = [rl.hit(conn, secret, lim, "203.0.113.9") for _ in range(4)]
        other = rl.hit(conn, secret, lim, "203.0.113.10")
        stored = (
            conn.execute(
                text("SELECT key_hash FROM app.auth_rate_events WHERE bucket = :b"),
                {"b": lim.bucket},
            )
            .scalars()
            .all()
        )
    assert results == [True, True, True, False] and other
    assert all("203.0.113" not in k for k in stored)
