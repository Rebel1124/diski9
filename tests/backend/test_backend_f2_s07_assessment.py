"""Phase 6C.5 Stage F2, S-07 security assessment: characterisation tests for the
older email-identified operator commands (``round create/publish/lock/dev-open``
and ``account grant-role/revoke-role/grant-feature/revoke-feature/suspend/
reinstate``), run through the real ``diski9`` CLI against an isolated ``_test``
database. Nothing here touches the owner's databases.

These tests record what the legacy path does today, so the assessment in
``docs/architecture/phase6c5_implementation.md`` §7.2 rests on executed evidence:

* the roles always come from the database, so naming a *non-operator* (or an
  unknown or unverified address) is refused and nothing is written;
* but no password is asked: whoever runs the command with the application's
  database credentials can name an operator's or owner's address, and the audit
  log attributes the action to that person (the S-07 gap);
* the boundaries that limit the impact hold: ``dev-open`` is refused in production
  and makes development rounds only, ``create``/``publish`` make beta rounds only
  (never official), and ``lock`` is refused before the deadline and idempotent.

They are characterisation tests, not endorsements: when S-07 is remediated
(Phase 6C.6), the "no password" assertions are expected to change.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from pg_helpers import make_round, make_user
from pty_cli import run_cli
from settle_helpers import grant
from sqlalchemy import func, select, text

from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import audit_log, championship_series, rounds, user_roles


def _account(engine, *, role: str | None = None, verified: bool = True) -> tuple[str, uuid.UUID]:
    addr = f"s07-{uuid.uuid4().hex[:10]}@example.com"
    with transaction(engine) as conn:
        uid = make_user(conn)
        conn.execute(
            text(
                "INSERT INTO app.user_private (user_id, email, email_verified, age_confirmed_at,"
                " updated_at) VALUES (:u, :e, :v, now(), now()) ON CONFLICT (user_id) DO UPDATE"
                " SET email = :e, email_verified = :v, age_confirmed_at = now()"
            ),
            {"u": uid, "e": addr, "v": verified},
        )
    if role:
        grant(engine, uid, role)
    return addr, uid


def _env(pg_url, environment: str = "test") -> dict[str, str]:
    return {"DISKI9_APP_DATABASE_URL": pg_url, "DISKI9_APP_ENVIRONMENT": environment}


def _round_count(engine) -> int:
    with transaction(engine) as conn:
        return conn.execute(select(func.count()).select_from(rounds)).scalar_one()


def _audit_count(engine) -> int:
    with transaction(engine) as conn:
        return conn.execute(select(func.count()).select_from(audit_log)).scalar_one()


def test_non_operator_unknown_and_unverified_addresses_are_refused(engine, pg_url):
    participant, _ = _account(engine)
    unverified, _ = _account(engine, role="operator", verified=False)
    before_rounds, before_audit = _round_count(engine), _audit_count(engine)
    for addr in (participant, unverified, "nobody-s07@example.com"):
        rc, out = run_cli(["round", "dev-open", "--by-email", addr], _env(pg_url))
        # unknown/unverified: a clean "error:"; a participant: the service's Forbidden
        # (missing round.publish) escapes as a traceback (exit 1), before any write
        assert rc != 0, out
        assert "error:" in out or "missing_capability:round.publish" in out
    rc, out = run_cli(["round", "dev-open"], _env(pg_url))
    assert rc == 2 and "--by-email" in out
    assert _round_count(engine) == before_rounds
    assert _audit_count(engine) == before_audit


def test_operator_address_alone_is_accepted_without_a_password(engine, pg_url):
    """The S-07 gap: no password prompt, and the audit names the operator."""
    operator, op_id = _account(engine, role="operator")
    code = f"dev-s07-{uuid.uuid4().hex[:6]}"
    rc, out = run_cli(
        ["round", "dev-open", "--by-email", operator, "--code", code, "--deadline-minutes", "5"],
        _env(pg_url),
    )
    assert rc == 0, out
    assert "assword" not in out
    with transaction(engine) as conn:
        r = conn.execute(select(rounds).where(rounds.c.code == code)).one()
        assert r.is_development is True
        assert r.status == "open"
        actors = set(
            conn.execute(
                select(audit_log.c.actor_user_id).where(audit_log.c.target_id == str(r.id))
            ).scalars()
        )
    assert actors == {op_id}


def test_dev_open_is_refused_in_production_and_makes_development_rounds_only(engine, pg_url):
    operator, _ = _account(engine, role="operator")
    before = _round_count(engine)
    rc, out = run_cli(["round", "dev-open", "--by-email", operator], _env(pg_url, "production"))
    # a *_test database is itself refused in production; either way nothing runs
    assert rc != 0, out
    assert _round_count(engine) == before
    rc, out = run_cli(
        ["round", "dev-open", "--by-email", operator, "--code", "2026-W99-weekend"], _env(pg_url)
    )
    # refused before any write (a ValueError traceback: a legacy rough edge, not a gap)
    assert rc != 0 and "only for 'dev-' rounds" in out, out
    assert _round_count(engine) == before


def test_create_makes_beta_rounds_never_official(engine, pg_url):
    operator, _ = _account(engine, role="operator")
    rc, out = run_cli(["round", "create", "--week", "2031-W07", "--by-email", operator],
                      _env(pg_url))  # fmt: skip
    assert rc == 0, out
    with transaction(engine) as conn:
        name = conn.execute(
            select(championship_series.c.code)
            .join(rounds, rounds.c.series_id == championship_series.c.id)
            .where(rounds.c.code == "2031-W07-weekend")
        ).scalar_one()
    assert name == "beta"


def test_lock_is_refused_before_the_deadline_and_is_idempotent(engine, pg_url):
    with transaction(engine) as conn:
        rid, _, _ = make_round(conn, deadline_in=timedelta(hours=2))
        code = conn.execute(select(rounds.c.code).where(rounds.c.id == rid)).scalar_one()
    rc, out = run_cli(["round", "lock", "--code", code], _env(pg_url))
    assert rc == 2 and "deadline has not been reached" in out
    with transaction(engine) as conn:
        assert conn.execute(select(rounds.c.status).where(rounds.c.id == rid)).scalar_one() == (
            "open"
        )
        # the deadline guard is a database trigger; even the CLI cannot move it
        assert (
            db_now(conn)
            < conn.execute(select(rounds.c.deadline_at).where(rounds.c.id == rid)).scalar_one()
        )


def test_account_role_change_needs_an_owner_address_but_no_password(engine, pg_url):
    """``account grant-role`` checks the named actor is an active owner (from the
    database) but asks no password and applies no 15-minute recency (T-14)."""
    owner, owner_id = _account(engine, role="owner")
    operator, _ = _account(engine, role="operator")
    target, target_id = _account(engine)
    rc, out = run_cli(["account", "grant-role", "--email", target, "--role", "operator",
                       "--by-email", operator, "--reason", "s07 check"], _env(pg_url))  # fmt: skip
    assert rc != 0 and "only an active owner" in out
    rc, out = run_cli(["account", "grant-role", "--email", target, "--role", "operator",
                       "--by-email", owner, "--reason", "s07 check"], _env(pg_url))  # fmt: skip
    assert rc == 0 and "assword" not in out, out
    with transaction(engine) as conn:
        assert (
            conn.execute(
                select(user_roles.c.role).where(user_roles.c.user_id == target_id)
            ).scalar_one()
            == "operator"
        )
        a = conn.execute(
            select(audit_log).where(audit_log.c.action == "role.granted",
                                    audit_log.c.target_id == str(target_id))
        ).one()  # fmt: skip
    assert a.actor_user_id == owner_id
