"""Phase 6C.6 Stage B — S-07 remediation regression tests (formerly the Phase 6C.5
F2 characterisation tests of the e-mail-identified commands, now inverted).

The real ``diski9`` command runs in a pseudo-terminal against real PostgreSQL and a
real Supabase Auth server; passwords are typed at the hidden ``getpass`` prompt.
Covered for ``round create|publish|lock|dev-open`` and ``account
grant-role|revoke-role|grant-feature|revoke-feature|suspend|reinstate``:

* the former ``--by-email`` path is refused with guidance before anything is read
  or written (the F2 "operator address alone is accepted" gap is closed);
* no terminal, a wrong password, an impersonation attempt (another person's
  address), a participant, an operator for owner-only changes and a suspended
  account are all refused before any write (exit 3, nothing changed);
* valid owners and operators succeed and the audit names the *verified* account
  and its real role;
* owner bootstrap requires the target account's own password and only works while
  no owner exists (isolated database);
* the scheduled-job actor ``SYSTEM`` can still lock a round through the service
  (legitimate unattended locking for the future scheduler) but is refused by every
  capability check and every human-only service;
* the F2 boundaries still hold (development rounds only from ``dev-open``, never in
  production; ``create`` makes beta rounds; ``lock`` is refused before the deadline).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from champ_helpers import drop, isolated_engine
from pg_helpers import make_round
from pty_cli import Session, run_cli
from sqlalchemy import func, select, update
from svc_helpers import principal, publish_dev, wait_until

# real Supabase accounts and the CLI conventions of the 6C.4 operator CLI tests
from test_backend_operator_cli import (  # noqa: F401  (``provider`` is a fixture)
    ANON,
    AUTH_URL,
    PASSWORD,
    make_account,
    provider,
)

from diski9.backend.auth.permissions import (
    Capability,
    NotAuthenticated,
    RecentAuthenticationRequired,
    authorize,
)
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import (
    audit_log,
    championship_series,
    entitlement_grants,
    rounds,
    user_roles,
    users,
)
from diski9.backend.services import corrections as co
from diski9.backend.services import results as rs
from diski9.backend.services import rounds as svc
from diski9.backend.services.common import ServiceError, cli_principal

pytestmark = pytest.mark.skipif(
    not (AUTH_URL and ANON), reason="needs a real Supabase Auth server (local harness)"
)

WRONG = "Not-The-Password-1"


@pytest.fixture(scope="module")
def people(engine, provider):  # noqa: F811
    return {
        "owner": make_account(engine, provider, "owner"),
        "owner2": make_account(engine, provider, "owner"),
        "operator": make_account(engine, provider, "operator"),
        "participant": make_account(engine, provider),
        "target": make_account(engine, provider),
    }


def _env(pg_url, environment: str = "test") -> dict[str, str]:
    return {
        "DISKI9_APP_DATABASE_URL": pg_url,
        "DISKI9_APP_ENVIRONMENT": environment,
        "DISKI9_SUPABASE_AUTH_URL": AUTH_URL,
        "DISKI9_SUPABASE_PUBLISHABLE_KEY": ANON,
        "DISKI9_SUPABASE_JWT_ISSUER": AUTH_URL,
    }


def _counts(engine) -> tuple[int, int, int, int, int]:
    """Rounds, audit records, roles, entitlement grants, suspended accounts."""
    with transaction(engine) as conn:
        return (
            conn.execute(select(func.count()).select_from(rounds)).scalar_one(),
            conn.execute(select(func.count()).select_from(audit_log)).scalar_one(),
            conn.execute(select(func.count()).select_from(user_roles)).scalar_one(),
            conn.execute(select(func.count()).select_from(entitlement_grants)).scalar_one(),
            conn.execute(
                select(func.count()).select_from(users).where(users.c.status != "active")
            ).scalar_one(),
        )


def _last_audit(engine, action: str, target: str):
    with transaction(engine) as conn:
        return conn.execute(
            select(audit_log)
            .where(audit_log.c.action == action, audit_log.c.target_id == target)
            .order_by(audit_log.c.id.desc())
            .limit(1)
        ).one()


ALL_COMMANDS = [
    ["round", "create", "--week", "2031-W08"],
    ["round", "publish", "--code", "2031-W08-weekend"],
    ["round", "lock", "--code", "any"],
    ["round", "dev-open"],
    ["account", "grant-role", "--email", "x@example.com", "--role", "operator", "--reason", "r"],
    ["account", "revoke-role", "--email", "x@example.com", "--role", "operator", "--reason", "r"],
    ["account", "grant-feature", "--email", "x@example.com", "--feature", "lucy.research",
     "--reason", "r"],
    ["account", "revoke-feature", "--email", "x@example.com", "--feature", "lucy.research",
     "--reason", "r"],
    ["account", "suspend", "--email", "x@example.com", "--reason", "r"],
    ["account", "reinstate", "--email", "x@example.com", "--reason", "r"],
]  # fmt: skip


# ------------------------------------------------------------------ former path
@pytest.mark.parametrize("argv", ALL_COMMANDS, ids=lambda a: "-".join(a[:2]))
def test_former_by_email_path_is_refused_with_guidance(engine, pg_url, people, argv):
    """F2 gap closed: naming an operator's or owner's address changes nothing and
    asks for no password; the message tells the user what to do instead."""
    before = _counts(engine)
    rc, out = run_cli([*argv, "--by-email", people["owner"][0]], _env(pg_url))
    assert rc == 2, out
    assert "--by-email was removed" in out and "--operator" in out
    assert "assword for" not in out
    assert _counts(engine) == before


# ------------------------------------------------------------------ refusals
def test_no_terminal_is_refused_before_anything_is_written(engine, pg_url, people):
    before = _counts(engine)
    s = Session(["round", "dev-open", "--operator", people["operator"][0]], _env(pg_url),
                stdin_tty=False)  # fmt: skip
    rc, out = s.finish()
    assert rc == 3 and "interactive terminal" in out, out
    assert _counts(engine) == before


def test_wrong_password_and_impersonation_are_refused(engine, pg_url, people):
    """Naming another person's address needs *their* password: typing your own (or
    any wrong) password is refused, and nothing changes."""
    before = _counts(engine)
    for who in ("operator", "owner"):
        rc, out = run_cli(["round", "dev-open", "--operator", people[who][0]], _env(pg_url),
                          password=WRONG)  # fmt: skip
        assert rc == 3 and "incorrect" in out and "Nothing was changed" in out, out
    rc, out = run_cli(["account", "grant-role", "--email", people["target"][0], "--role",
                       "operator", "--reason", "impersonation", "--operator",
                       people["owner"][0]], _env(pg_url), password=WRONG)  # fmt: skip
    assert rc == 3 and "incorrect" in out, out
    assert _counts(engine) == before


def test_participant_and_unknown_accounts_cannot_run_round_commands(engine, pg_url, people):
    before = _counts(engine)
    for argv in (["round", "dev-open"], ["round", "create", "--week", "2031-W09"]):
        rc, out = run_cli([*argv, "--operator", people["participant"][0]], _env(pg_url),
                          password=PASSWORD)  # fmt: skip
        assert rc == 3 and "does not have permission" in out, out
    rc, out = run_cli(["round", "dev-open", "--operator", "nobody-s07@example.com"],
                      _env(pg_url), password=PASSWORD)  # fmt: skip
    assert rc == 3 and "Nothing was changed" in out, out
    assert _counts(engine) == before


def test_operator_cannot_make_owner_only_changes(engine, pg_url, people):
    before = _counts(engine)
    for argv in (
        ["account", "grant-role", "--role", "operator"],
        ["account", "grant-feature", "--feature", "lucy.research"],
    ):
        rc, out = run_cli([*argv, "--email", people["target"][0], "--reason", "try",
                           "--operator", people["operator"][0]], _env(pg_url),
                          password=PASSWORD)  # fmt: skip
        assert rc == 3 and "does not have permission" in out, out
    assert _counts(engine) == before


def test_suspended_owner_is_refused(engine, pg_url, provider):  # noqa: F811
    addr, uid = make_account(engine, provider, "owner")
    with transaction(engine) as conn:
        conn.execute(update(users).where(users.c.id == uid).values(status="suspended"))
    before = _counts(engine)
    rc, out = run_cli(["account", "grant-feature", "--email", addr, "--feature",
                       "lucy.research", "--reason", "x", "--operator", addr], _env(pg_url),
                      password=PASSWORD)  # fmt: skip
    assert rc == 3 and "not active" in out, out
    assert _counts(engine) == before


# ------------------------------------------------------------------ valid actions
def test_owner_role_and_entitlement_changes_are_attributed(engine, pg_url, people):
    target, target_id = people["target"]
    owner, owner_id = people["owner"]
    steps = (
        (["grant-role", "--role", "operator"], "role.granted"),
        (["grant-feature", "--feature", "lucy.research"], "entitlement.granted"),
        (["revoke-feature", "--feature", "lucy.research"], "entitlement.revoked"),
        (["revoke-role", "--role", "operator"], "role.revoked"),
    )
    for argv, action in steps:
        rc, out = run_cli(["account", *argv, "--email", target, "--reason", f"s07 {action}",
                           "--operator", owner], _env(pg_url), password=PASSWORD)  # fmt: skip
        assert rc == 0 and "done (audited)" in out and PASSWORD not in out, out
        a = _last_audit(engine, action, str(target_id))
        assert a.actor_user_id == owner_id and a.actor_role == "owner", action
    with transaction(engine) as conn:
        assert not conn.execute(select(user_roles).where(user_roles.c.user_id == target_id)
                                ).first()  # fmt: skip


def test_suspension_records_the_actors_real_role(engine, pg_url, people, provider):  # noqa: F811
    victim, victim_id = make_account(engine, provider)
    op, op_id = people["operator"]
    rc, out = run_cli(["account", "suspend", "--email", victim, "--reason", "s07 suspend",
                       "--operator", op], _env(pg_url), password=PASSWORD)  # fmt: skip
    assert rc == 0, out
    a = _last_audit(engine, "account.suspended", str(victim_id))
    assert a.actor_user_id == op_id and a.actor_role == "operator"
    owner, owner_id = people["owner2"]
    rc, out = run_cli(["account", "reinstate", "--email", victim, "--reason", "s07 back",
                       "--operator", owner], _env(pg_url), password=PASSWORD)  # fmt: skip
    assert rc == 0, out
    a = _last_audit(engine, "account.reinstated", str(victim_id))
    assert a.actor_user_id == owner_id and a.actor_role == "owner"


def test_operator_dev_open_create_and_attribution(engine, pg_url, people):
    op, op_id = people["operator"]
    code = f"dev-s07-{uuid.uuid4().hex[:6]}"
    rc, out = run_cli(["round", "dev-open", "--operator", op, "--code", code,
                       "--deadline-minutes", "5"], _env(pg_url), password=PASSWORD)  # fmt: skip
    assert rc == 0 and "Verified" in out and PASSWORD not in out, out
    with transaction(engine) as conn:
        r = conn.execute(select(rounds).where(rounds.c.code == code)).one()
        actors = set(conn.execute(select(audit_log.c.actor_user_id).where(
            audit_log.c.target_id == str(r.id))).scalars())  # fmt: skip
    assert r.is_development and r.status == "open"
    assert actors == {op_id}
    rc, out = run_cli(["round", "create", "--week", "2031-W10", "--operator", op],
                      _env(pg_url), password=PASSWORD)  # fmt: skip
    assert rc == 0, out
    with transaction(engine) as conn:
        series = conn.execute(
            select(championship_series.c.code)
            .join(rounds, rounds.c.series_id == championship_series.c.id)
            .where(rounds.c.code == "2031-W10-weekend")
        ).scalar_one()
    assert series == "beta"  # never official


def test_manual_lock_needs_an_operator_and_is_attributed(engine, pg_url, people):
    op, op_id = people["operator"]
    with transaction(engine) as conn:
        rid, _, _ = make_round(conn, deadline_in=timedelta(hours=2))
        early = conn.execute(select(rounds.c.code).where(rounds.c.id == rid)).scalar_one()
    rc, out = run_cli(["round", "lock", "--code", early, "--operator", op], _env(pg_url),
                      password=PASSWORD)  # fmt: skip
    assert rc == 2 and "deadline has not been reached" in out, out
    # no SYSTEM fallback any more: without an operator the command cannot proceed
    s = Session(["round", "lock", "--code", early], _env(pg_url), stdin_tty=False)
    rc, out = s.finish()
    assert rc != 0, out
    with transaction(engine) as conn:
        assert conn.execute(select(rounds.c.status).where(rounds.c.id == rid)).scalar_one() == (
            "open")  # fmt: skip
    view, _ = publish_dev(engine, principal(engine, role="operator"),
                          deadline_in=timedelta(seconds=3))  # fmt: skip
    wait_until(engine, view.deadline_at + timedelta(seconds=1))
    rc, out = run_cli(["round", "lock", "--code", view.code, "--operator", op], _env(pg_url),
                      password=PASSWORD)  # fmt: skip
    assert rc == 0 and "locked" in out, out
    a = _last_audit(engine, "round.lock", str(view.id))
    assert a.actor_user_id == op_id and a.actor_role == "operator"


def test_dev_open_refused_in_production_and_for_non_dev_codes(engine, pg_url, people):
    op = people["operator"][0]
    before = _counts(engine)
    rc, out = run_cli(["round", "dev-open", "--operator", op], _env(pg_url, "production"))
    assert rc != 0, out  # refused before anything runs (and before any password)
    rc, out = run_cli(["round", "dev-open", "--operator", op, "--code", "2026-W99-weekend"],
                      _env(pg_url), password=PASSWORD)  # fmt: skip
    assert rc != 0 and "only for 'dev-' rounds" in out, out
    assert _counts(engine) == before


# ------------------------------------------------------------------ bootstrap
BOOT_DB = "diski9_s07_bootstrap_test"


def test_owner_bootstrap_requires_the_target_accounts_password(pg_url, provider):  # noqa: F811
    eng, url = isolated_engine(pg_url, BOOT_DB)
    try:
        addr, uid = make_account(eng, provider)  # no owner exists in this database
        env = _env(url)
        rc, out = run_cli(["account", "bootstrap-owner", "--email", addr], env)
        assert rc == 2 and "--confirm" in out, out
        rc, out = run_cli(["account", "bootstrap-owner", "--email", addr, "--confirm"], env,
                          password=WRONG)  # fmt: skip
        assert rc == 3 and "incorrect" in out, out
        with transaction(eng) as conn:
            assert not conn.execute(select(user_roles)).first()
        rc, out = run_cli(["account", "bootstrap-owner", "--email", addr, "--confirm",
                           "--reason", "first owner"], env, password=PASSWORD)  # fmt: skip
        assert rc == 0 and "owner role granted" in out, out
        a = _last_audit(eng, "role.bootstrap_owner", str(uid))
        assert a.actor_user_id == uid and a.actor_role == "participant"
        assert a.after["verified"] == "password"
        # once an owner exists, bootstrap is refused before any password is asked
        other, _ = make_account(eng, provider)
        rc, out = run_cli(["account", "bootstrap-owner", "--email", other, "--confirm"], env)
        assert rc == 2 and "already exists" in out and "assword for" not in out, out
    finally:
        eng.dispose()
        drop(pg_url, BOOT_DB)


# ------------------------------------------------------------------ SYSTEM actor
def test_system_can_lock_through_the_service_only(engine):
    """Legitimate unattended locking (for the Stage C scheduler) is a service call
    with the explicit SYSTEM actor, audited as the system."""
    view, _ = publish_dev(engine, principal(engine, role="operator"),
                          deadline_in=timedelta(seconds=2))  # fmt: skip
    wait_until(engine, view.deadline_at + timedelta(seconds=1))
    res = svc.lock_round(engine, svc.SYSTEM, view.id)
    assert res.round.status == "locked"
    a = _last_audit(engine, "round.lock", str(view.id))
    assert a.actor_user_id is None and a.actor_role == "system"


def test_system_cannot_escalate_into_human_only_operations(engine):
    """SYSTEM never satisfies a capability check and every human-only service
    refuses it before writing."""
    for cap in Capability:
        with pytest.raises(NotAuthenticated):
            authorize(svc.SYSTEM, cap)
    with transaction(engine) as conn:
        rid, _, _ = make_round(conn, deadline_in=timedelta(hours=2))
        now = db_now(conn)
    before = _counts(engine)
    with pytest.raises(NotAuthenticated):
        svc.create_round(engine, svc.SYSTEM, code=f"dev-sys-{uuid.uuid4().hex[:6]}",
                         window_start=now, window_end=now + timedelta(days=3),
                         development=True)  # fmt: skip
    with pytest.raises(NotAuthenticated):
        rs.set_result_mode(engine, svc.SYSTEM, rid, "synthetic")
    human_only = (
        lambda: co.correct_result(engine, svc.SYSTEM, rid, None, reason="r", evidence="e",
                                  confirmation="x"),
        lambda: co.reopen_round(engine, svc.SYSTEM, rid, reason="r", evidence="e",
                                confirmation="x"),
        lambda: co.invalidate_round(engine, svc.SYSTEM, rid, reason="r", confirmation="x"),
    )  # fmt: skip
    for call in human_only:
        with pytest.raises(co.CorrectionRefused, match="authenticated person"):
            call()
    assert _counts(engine) == before


def test_unverified_principal_cannot_pass_sensitive_checks(engine, people):
    """The old CLI principal (built from an address, no password) has no recent
    authentication, so T-14 refuses every sensitive capability."""
    with transaction(engine) as conn:
        p = cli_principal(conn, people["owner"][1], db_now(conn))
    for cap in (Capability.MANAGE_ROLES, Capability.MANAGE_ENTITLEMENTS,
                Capability.SUSPEND_USER, Capability.REOPEN_ROUND):  # fmt: skip
        with pytest.raises(RecentAuthenticationRequired):
            authorize(p, cap)


def test_cli_principal_is_refused_in_production(engine, people, monkeypatch):
    monkeypatch.setenv("DISKI9_APP_ENVIRONMENT", "production")
    monkeypatch.delenv("DISKI9_APP_DATABASE_URL", raising=False)  # isolate this check
    with (
        pytest.raises(ServiceError, match="not available in production"),
        transaction(engine) as conn,
    ):
        cli_principal(conn, people["owner"][1], db_now(conn))


def test_no_operator_command_builds_a_principal_without_a_password():
    """Static sweep of the command modules: no unverified principal, no e-mail
    identity, no SYSTEM actor in the human commands."""
    src = Path(__file__).resolve().parents[2] / "src" / "diski9"
    for name in ("cli.py", "settlement_cli.py"):
        code = (src / name).read_text()
        assert "cli_principal" not in code, name
        assert "args.by_email)" not in code, name
        assert "svc.SYSTEM" not in code and "rounds.SYSTEM" not in code, name
