"""GENUINE operator CLI tests (Phase 6C.4, Stage E): the real ``diski9`` command
in a pseudo-terminal, a real Supabase Auth server (local harness or Supabase CLI
stack) and real PostgreSQL. Nothing is mocked: passwords are typed at the hidden
``getpass`` prompt, verified by Supabase Auth, and roles come from the database.

Skipped unless both a test PostgreSQL database and a Supabase Auth server are
configured (``tmp/local_auth/env`` from ``tools/local_auth/local_auth.py``).
"""

from __future__ import annotations

import email
import os
import re
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from auth_helpers import make_settings
from pty_cli import Session, run_cli
from settle_helpers import grant, settlement_world
from sqlalchemy import select, text
from svc_helpers import principal, publish_dev, wait_until

from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import audit_log, rounds
from diski9.backend.services import settlement as st

AUTH_URL = os.environ.get("DISKI9_TEST_SUPABASE_AUTH_URL")
ANON = os.environ.get("DISKI9_TEST_SUPABASE_ANON_KEY")
MAIL_DIR = os.environ.get("DISKI9_TEST_SUPABASE_MAIL_DIR")
if os.environ.get("DISKI9_REQUIRE_SUPABASE_AUTH") == "1" and not (AUTH_URL and ANON and MAIL_DIR):
    raise RuntimeError("DISKI9_REQUIRE_SUPABASE_AUTH=1 but no Supabase Auth server is configured")
pytestmark = pytest.mark.skipif(
    not (AUTH_URL and ANON and MAIL_DIR),
    reason="needs a real Supabase Auth server (see docs/authentication.md, local testing)",
)
PASSWORD = "Operator-Cli-9z"


# ------------------------------------------------------------------ accounts
@pytest.fixture(scope="module")
def provider():
    from diski9.backend.auth.provider import SupabaseAuthProvider

    return SupabaseAuthProvider(
        make_settings(
            supabase_auth_url=AUTH_URL, supabase_publishable_key=ANON, supabase_jwt_issuer=AUTH_URL
        )
    )


def _wait_link(before: int) -> str:
    for _ in range(100):
        files = sorted(Path(MAIL_DIR).glob("*.eml"))
        if len(files) > before:
            body = (email.message_from_string(files[-1].read_text()).get_payload(decode=True)
                    or b"").decode()  # fmt: skip
            m = re.search(r"token_hash=([A-Za-z0-9_-]+)&(?:amp;)?type=email", body)
            assert m, body[:300]
            return m.group(1)
        time.sleep(0.1)
    raise AssertionError("no confirmation email arrived")


def make_account(engine, provider, role: str | None = None) -> tuple[str, uuid.UUID]:
    """A confirmed Supabase user linked to an onboarded Diski 9 account."""
    from diski9.backend.auth.accounts import complete_onboarding, ensure_app_user

    addr = f"cli-{uuid.uuid4().hex[:10]}@example.com"
    n = len(list(Path(MAIL_DIR).glob("*.eml")))
    provider.sign_up(addr, PASSWORD)
    session = provider.verify_email_link(_wait_link(n), "email")
    with transaction(engine) as conn:
        uid = ensure_app_user(conn, session.identity)
        complete_onboarding(
            conn, uid, username=f"Cli{uuid.uuid4().hex[:8]}", terms_version="beta-2026-11",
            accepted_terms=True, age_confirmed=True,
        )  # fmt: skip
    provider.sign_out(session.access_token, "local")
    if role:
        grant(engine, uid, role)
    return addr, uid


@pytest.fixture(scope="module")
def accounts(engine, provider):
    return {
        "operator": make_account(engine, provider, "operator"),
        "owner": make_account(engine, provider, "owner"),
        "participant": make_account(engine, provider),
    }


@pytest.fixture
def env(pg_url):
    return {
        "DISKI9_APP_DATABASE_URL": pg_url,
        "DISKI9_APP_ENVIRONMENT": "test",
        "DISKI9_SUPABASE_AUTH_URL": AUTH_URL,
        "DISKI9_SUPABASE_PUBLISHABLE_KEY": ANON,
        "DISKI9_SUPABASE_JWT_ISSUER": AUTH_URL,
    }


def code_of(engine, rid) -> str:
    with transaction(engine) as conn:
        return conn.execute(select(rounds.c.code).where(rounds.c.id == rid)).scalar_one()


def cli(env, accounts, who, *args, password=PASSWORD, answers=()):
    return run_cli([*args, "--operator", accounts[who][0]], env, password=password, answers=answers)


@pytest.fixture
def dev_round(engine):
    """A locked development round with one entry (fixtures settle in seconds)."""
    w = settlement_world(engine, development=True, cutoff_after=timedelta(seconds=6))
    w["code"] = code_of(engine, w["round"])
    return w


# ------------------------------------------------------------------ authentication
def test_authorised_operator_and_password_never_shown(engine, env, accounts, dev_round):
    rc, out = cli(env, accounts, "operator", "dev-results", "set-mode",
                  "--round", dev_round["code"], "--mode", "synthetic")  # fmt: skip
    assert rc == 0, out
    assert "Verified" in out and "roles: operator" in out
    assert "Result mode: synthetic" in out
    assert PASSWORD not in out
    with transaction(engine) as conn:
        a = conn.execute(
            select(audit_log).where(audit_log.c.action == "round.result_mode")
            .order_by(audit_log.c.id.desc()).limit(1)
        ).one()  # fmt: skip
        assert a.actor_user_id == accounts["operator"][1]


def test_incorrect_password_fails_closed(engine, env, accounts, dev_round):
    rc, out = cli(env, accounts, "operator", "settle", "status", "--round", dev_round["code"],
                  password="Wrong-Password-1")  # fmt: skip
    assert rc == 3 and "email or password is incorrect" in out and "Nothing was changed" in out
    assert "Wrong-Password-1" not in out


def test_unavailable_auth_provider_fails_closed(env, accounts, dev_round):
    down = {**env, "DISKI9_SUPABASE_AUTH_URL": "http://127.0.0.1:9", "DISKI9_SUPABASE_JWT_ISSUER":
            "http://127.0.0.1:9"}  # fmt: skip
    rc, out = cli(down, accounts, "operator", "settle", "status", "--round", dev_round["code"])
    assert rc == 3 and "unavailable" in out


def test_unconfigured_auth_fails_closed_before_asking(env, accounts, dev_round):
    bare = {k: v for k, v in env.items() if "SUPABASE" not in k}
    rc, out = run_cli(["settle", "status", "--round", dev_round["code"], "--operator",
                       accounts["operator"][0]], bare)  # fmt: skip
    assert rc == 3 and "not configured" in out and "assword" not in out


def test_password_is_never_an_argument_or_piped(env, accounts, dev_round):
    rc, out = run_cli(["settle", "status", "--round", dev_round["code"], "--password", "x"], env)
    assert rc == 2 and "unrecognized arguments" in out
    s = Session(["settle", "status", "--round", dev_round["code"], "--operator",
                 accounts["operator"][0]], env, stdin_tty=False)  # fmt: skip
    rc, out = s.finish()
    assert rc == 3 and "needs an interactive terminal" in out


def test_participant_cannot_run_operator_commands(env, accounts, dev_round):
    rc, out = cli(env, accounts, "participant", "settle", "run", "--round", dev_round["code"])
    assert rc == 3 and "does not have permission" in out


def test_database_access_alone_is_not_authority(env, dev_round):
    """No flag, variable or email-only path skips the password: an unknown email
    gets the same generic refusal and nothing runs."""
    rc, out = run_cli(["settle", "run", "--round", dev_round["code"], "--operator",
                       "nobody-here@example.com"], env, password=PASSWORD)  # fmt: skip
    assert rc == 3 and "incorrect" in out


# ------------------------------------------------------------------ lifecycle
def test_full_lifecycle_through_the_cli(engine, env, accounts, dev_round):
    c = dev_round["code"]
    ok = lambda r: r[0] == 0  # noqa: E731
    assert ok(cli(env, accounts, "operator", "dev-results", "set-mode", "--round", c,
                  "--mode", "synthetic"))  # fmt: skip
    rc, out = cli(env, accounts, "operator", "dev-results", "scenario", "--round", c,
                  "--name", "all-correct")  # fmt: skip
    assert rc == 0 and "Recorded" in out, out
    wait_until(engine, dev_round["deadline"] + timedelta(seconds=4))
    rc, out = cli(env, accounts, "operator", "settle", "preview", "--round", c)
    assert rc == 0 and "would change:           yes" in out, out
    rc, out = cli(env, accounts, "operator", "settle", "run", "--round", c)
    assert rc == 0 and "version 1" in out and "round validity:         pass" in out, out
    rc, out = cli(env, accounts, "operator", "results", "show", "--round", c)
    assert rc == 0 and "rule settle" in out and "=won" in out, out
    fid = dev_round["fixtures"][0]
    rc, out = cli(env, accounts, "operator", "results", "show", "--round", c,
                  "--fixture", str(fid))  # fmt: skip
    assert rc == 0 and "synthetic" in out and "FT" in out, out
    # correction: preview, then type the round code to confirm
    rc, out = cli(env, accounts, "operator", "results", "correct", "--round", c,
                  "--fixture", str(fid), "--status", "FT", "--home", "0", "--away", "3",
                  "--reason", "league report", "--evidence", "official match report",
                  answers=[(r"Type the round code", c)])  # fmt: skip
    assert rc == 0 and "Correction recorded" in out and "material change:        yes" in out, out
    rc, out = cli(env, accounts, "operator", "settle", "status", "--round", c)
    assert rc == 0 and "can finalise now:       no" in out and "correction window" in out
    with transaction(engine) as conn:
        r = st.earliest_finalisation(conn, conn.execute(
            select(rounds).where(rounds.c.id == dev_round["round"])).one())  # fmt: skip
    rc, out = cli(env, accounts, "operator", "round", "finalise-check", "--code", c,
                  "--as-of", r.isoformat())  # fmt: skip
    assert rc == 0 and "can finalise now" in out, out
    rc, out = cli(env, accounts, "operator", "round", "finalise", "--code", c,
                  "--as-of", r.isoformat())  # fmt: skip
    assert rc == 0 and "Finalised" in out, out
    # an operator cannot reopen; the owner can, after a preview and confirmation
    rc, out = cli(env, accounts, "operator", "round", "reopen", "--code", c,
                  "--reason", "review", "--evidence", "league note")  # fmt: skip
    assert rc == 3 and "does not have permission" in out
    rc, out = cli(env, accounts, "owner", "round", "reopen", "--code", c, "--reason", "review",
                  "--evidence", "league note", "--preview-only")  # fmt: skip
    assert rc == 0 and "Preview only" in out
    token = re.search(r"confirmation token:\s+(\w+)", out).group(1)
    rc, out = cli(env, accounts, "owner", "round", "reopen", "--code", c, "--reason", "review",
                  "--evidence", "league note", "--token", token)  # fmt: skip
    assert rc == 0 and "Round reopened" in out, out
    with transaction(engine) as conn:
        kinds = [k for (k,) in conn.execute(text(
            "SELECT kind FROM app.settlement_versions WHERE round_id = :r ORDER BY version"),
            {"r": dev_round["round"]})]  # fmt: skip
        assert kinds[:2] == ["provisional", "provisional"] and "final" in kinds
        assert kinds[-2:] == ["reopened", "provisional"] or kinds[-1] == "reopened"
        payloads = conn.execute(text(
            "SELECT coalesce(before::text,'') || coalesce(after::text,'') || coalesce(reason,'')"
            " FROM app.audit_log WHERE actor_user_id IN (:a, :b)"),
            {"a": accounts["operator"][1], "b": accounts["owner"][1]}).scalars().all()  # fmt: skip
    assert payloads and not any(PASSWORD in p or "eyJ" in p for p in payloads)


def test_declined_confirmation_changes_nothing(engine, env, accounts, dev_round):
    c = dev_round["code"]
    cli(env, accounts, "operator", "dev-results", "set-mode", "--round", c, "--mode", "synthetic")
    cli(env, accounts, "operator", "dev-results", "scenario", "--round", c, "--name", "pending")
    wait_until(engine, dev_round["deadline"] + timedelta(seconds=4))
    cli(env, accounts, "operator", "settle", "run", "--round", c)
    rc, out = cli(env, accounts, "operator", "round", "invalidate", "--code", c,
                  "--reason", "pitch problems", answers=[(r"Type the round code", "no")])  # fmt: skip
    assert rc == 1 and "Not confirmed; nothing changed" in out
    with transaction(engine) as conn:
        assert st.current_designation(conn, dev_round["round"]).basis != "operator"
    rc, out = cli(env, accounts, "operator", "round", "invalidate", "--code", c,
                  "--reason", "pitch problems", answers=[(r"Type the round code", c)])  # fmt: skip
    assert rc == 0 and "Round invalidated" in out and "designation:            void" in out


def test_stale_preview_is_rejected(engine, env, accounts, dev_round):
    c = dev_round["code"]
    fid = dev_round["fixtures"][1]
    cli(env, accounts, "operator", "dev-results", "set-mode", "--round", c, "--mode", "synthetic")
    cli(env, accounts, "operator", "dev-results", "scenario", "--round", c, "--name", "all-correct")
    wait_until(engine, dev_round["deadline"] + timedelta(seconds=4))
    cli(env, accounts, "operator", "settle", "run", "--round", c)
    args = ["results", "correct", "--round", c, "--fixture", str(fid), "--status", "FT",
            "--home", "0", "--away", "4", "--reason", "report", "--evidence", "report"]  # fmt: skip
    rc, out = cli(env, accounts, "operator", *args, "--preview-only")
    token = re.search(r"confirmation token:\s+(\w+)", out).group(1)
    # the round changes after the preview (another fixture corrected)
    other = [
        "results",
        "correct",
        "--round",
        c,
        "--fixture",
        str(dev_round["fixtures"][0]),
        "--status",
        "FT",
        "--home",
        "0",
        "--away",
        "5",
        "--reason",
        "r",
        "--evidence",
        "e",
    ]
    assert cli(env, accounts, "operator", *other, answers=[(r"Type the round code", c)])[0] == 0
    rc, out = cli(env, accounts, "operator", *args, "--token", token)
    assert rc == 2 and "changed since the preview" in out
    with transaction(engine) as conn:
        n = conn.execute(text("SELECT count(*) FROM app.result_observations WHERE fixture_id = :f"
                              " AND source = 'operator'"), {"f": fid}).scalar()  # fmt: skip
    assert n == 0


def test_recent_authentication_boundary_at_confirmation(engine, env, accounts, dev_round):
    """T-14 at the moment of the write: with a 1-minute recency setting, a
    confirmation typed more than a minute after the password is refused."""
    c = dev_round["code"]
    fid = dev_round["fixtures"][2]
    cli(env, accounts, "operator", "dev-results", "set-mode", "--round", c, "--mode", "synthetic")
    cli(env, accounts, "operator", "dev-results", "scenario", "--round", c, "--name", "all-correct")
    wait_until(engine, dev_round["deadline"] + timedelta(seconds=4))
    cli(env, accounts, "operator", "settle", "run", "--round", c)
    short = {**env, "DISKI9_SENSITIVE_RECENCY_MINUTES": "1"}
    s = Session(["results", "correct", "--round", c, "--fixture", str(fid), "--status", "FT",
                 "--home", "0", "--away", "2", "--reason", "r", "--evidence", "e",
                 "--operator", accounts["operator"][0]], short)  # fmt: skip
    s.expect(r"password for .*: ")
    s.send(PASSWORD)
    s.expect(r"Type the round code")
    time.sleep(62)
    s.send(c)
    rc, out = s.finish()
    assert rc == 3 and "too old" in out and "Nothing was changed" in out
    with transaction(engine) as conn:
        n = conn.execute(text("SELECT count(*) FROM app.result_observations WHERE fixture_id = :f"
                              " AND source = 'operator'"), {"f": fid}).scalar()  # fmt: skip
    assert n == 0
    # within the window the same confirmation succeeds
    rc, out = run_cli(["results", "correct", "--round", c, "--fixture", str(fid), "--status",
                       "FT", "--home", "0", "--away", "2", "--reason", "r", "--evidence", "e",
                       "--operator", accounts["operator"][0]], short, password=PASSWORD,
                      answers=[(r"Type the round code", c)])  # fmt: skip
    assert rc == 0, out


# ------------------------------------------------------------------ genuine rounds
def test_genuine_round_refuses_synthetic_input_and_time_override(engine, env, accounts):
    w = settlement_world(engine)  # a real (non-development) round, locked
    c = code_of(engine, w["round"])
    rc, out = cli(env, accounts, "operator", "dev-results", "scenario", "--round", c,
                  "--name", "all-correct")  # fmt: skip
    assert rc == 2 and "only for development rounds" in out
    rc, out = cli(env, accounts, "operator", "dev-results", "set-mode", "--round", c,
                  "--mode", "synthetic")  # fmt: skip
    assert rc == 2 and "Real rounds always settle on real results" in out
    with transaction(engine) as conn:
        later = (db_now(conn) + timedelta(days=5)).isoformat()
    rc, out = cli(env, accounts, "operator", "settle", "run", "--round", c, "--as-of", later)
    assert rc == 2 and "only for development rounds" in out
    assert cli(env, accounts, "operator", "settle", "run", "--round", c)[0] == 0
    rc, out = cli(env, accounts, "operator", "round", "finalise", "--code", c, "--as-of", later)
    assert rc == 2 and "development rounds" in out


# ------------------------------------------------------------------ test entries
def test_test_entry_needs_the_participants_own_password(engine, env, accounts):
    op = principal(engine, role="operator")
    view, _ = publish_dev(engine, op, deadline_in=timedelta(hours=2))
    args = ["dev-results", "test-entry", "--round", view.code, "--participant",
            accounts["participant"][0], "--variant", "1"]  # fmt: skip
    rc, out = run_cli(args, env, password="Wrong-Password-1")
    assert rc == 3 and "incorrect" in out
    rc, out = run_cli(args, env, password=PASSWORD)
    assert rc == 0 and "Confirmed test portfolio (variant 1)" in out, out
    with transaction(engine) as conn:
        n = conn.execute(text("SELECT count(*) FROM app.entries WHERE round_id = :r AND "
                              "user_id = :u AND current_submission_id IS NOT NULL"),
                         {"r": view.id, "u": accounts["participant"][1]}).scalar()  # fmt: skip
    assert n == 1


# ------------------------------------------------------------------ Phase 6C.5 Stage C
def test_competition_commands_need_an_operator_password(env, accounts):
    rc, out = cli(env, accounts, "participant", "competition", "status")
    assert rc == 3 and "does not have permission" in out
    rc, out = cli(env, accounts, "operator", "competition", "backfill", "--preview-only",
                  password="Wrong-Password-1")  # fmt: skip
    assert rc == 3 and "email or password is incorrect" in out and "Wrong-Password-1" not in out
    s = Session(["competition", "backfill", "--operator", accounts["operator"][0]], env,
                stdin_tty=False)  # fmt: skip
    rc, out = s.finish()
    assert rc == 3 and "needs an interactive terminal" in out


def test_competition_status_verify_and_backfill_through_the_cli(engine, env, accounts):
    def score_sets():
        with transaction(engine) as conn:
            return conn.execute(text("SELECT count(*) FROM app.score_sets")).scalar_one()

    rc, out = cli(env, accounts, "operator", "competition", "status")
    assert rc in (0, 1) and "development:" in out and "beta:" in out, out
    assert "official: not started" in out and PASSWORD not in out
    rc, out = cli(env, accounts, "operator", "competition", "verify")
    assert rc in (0, 1) and "development" in out, out
    before = score_sets()
    rc, out = cli(env, accounts, "operator", "competition", "backfill", "--preview-only")
    assert rc == 0 and "Backfill preview" in out and "Preview only; nothing changed" in out, out
    assert score_sets() == before
    token = re.search(r"confirmation token:\s+([0-9a-f]{16})", out).group(1)
    rc, out = cli(env, accounts, "operator", "competition", "backfill", "--token", "0" * 16)
    assert rc == 2 and "changed since the preview" in out
    rc, out = cli(env, accounts, "operator", "competition", "backfill", "--token", token)
    assert rc == 0 and "Backfill complete" in out, out
    with transaction(engine) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.audit_log WHERE action = "
                                 "'competition.backfill'")).scalar_one() >= 1  # fmt: skip


# ------------------------------------------------------------------ Phase 6C.5 Stage D
def test_competition_repair_through_the_cli(engine, env, accounts, dev_round):
    """Genuine terminal, real Supabase Auth: participant refused, wrong password,
    preview only (nothing written), stale token, missing reason, confirmed repair
    of a tampered derived record (audited, membership untouched)."""
    with transaction(engine) as conn:
        # the latest development championship (the dev round itself may legitimately
        # be waiting for assignment behind other tests' unresolved rounds)
        cid = conn.execute(text(
            "SELECT id FROM app.championships WHERE stream = 'development' "
            "ORDER BY ordinal DESC LIMIT 1")).scalar_one()  # fmt: skip
        members = conn.execute(text("SELECT round_id, championship_id FROM "
                                    "app.championship_rounds ORDER BY round_id")).all()  # fmt: skip
        orig = conn.execute(text("SELECT status, counted_rounds, rounds_required FROM "
                                 "app.championships WHERE id = :c"), {"c": cid}).one()  # fmt: skip
        if orig.status == "upcoming":  # a derived value changed behind the services' back
            conn.execute(text("UPDATE app.championships SET status = 'in_progress' "
                              "WHERE id = :c"), {"c": cid})  # fmt: skip
        else:
            wrong = orig.counted_rounds - 1 if orig.counted_rounds else 1
            conn.execute(text("UPDATE app.championships SET counted_rounds = :n WHERE id = :c"),
                         {"n": wrong, "c": cid})  # fmt: skip
    rc, out = cli(env, accounts, "participant", "competition", "repair", "--preview-only")
    assert rc == 3 and "does not have permission" in out
    rc, out = cli(env, accounts, "operator", "competition", "repair", "--preview-only",
                  password="Wrong-Password-1")  # fmt: skip
    assert rc == 3 and "Wrong-Password-1" not in out
    rc, out = cli(env, accounts, "operator", "competition", "verify")
    assert rc == 1 and "repairable:" in out, out
    assert re.search(r"development: \d+ finding\(s\)", out), out  # findings carry their stream

    def versions():
        with transaction(engine) as conn:
            return conn.execute(text("SELECT count(*) FROM app.championship_versions")).scalar()

    before = versions()
    rc, out = cli(env, accounts, "operator", "competition", "repair", "--stream", "development",
                  "--preview-only")  # fmt: skip
    assert rc == 0 and "Repair preview" in out and "Preview only; nothing changed" in out, out
    assert versions() == before and PASSWORD not in out
    token = re.search(r"confirmation token:\s+([0-9a-f]{16})", out).group(1)
    rc, out = cli(env, accounts, "operator", "competition", "repair", "--stream", "development",
                  "--token", token)  # fmt: skip
    assert rc == 2 and "--reason is required" in out
    rc, out = cli(env, accounts, "operator", "competition", "repair", "--stream", "development",
                  "--token", "0" * 16, "--reason", "manual edit undone")  # fmt: skip
    assert rc == 2 and "changed since the preview" in out
    rc, out = cli(env, accounts, "operator", "competition", "repair", "--stream", "development",
                  "--token", token, "--reason", "manual edit undone")  # fmt: skip
    assert rc == 0 and "Repair complete" in out, out
    with transaction(engine) as conn:
        now = conn.execute(text("SELECT status, counted_rounds FROM app.championships "
                                "WHERE id = :c"), {"c": cid}).one()  # fmt: skip
        assert tuple(now) == (orig.status, orig.counted_rounds)
        assert (
            conn.execute(
                text(
                    "SELECT round_id, championship_id FROM "
                    "app.championship_rounds ORDER BY round_id"
                )
            ).all()
            == members
        )
        a = conn.execute(text("SELECT actor_user_id, reason FROM app.audit_log WHERE action = "
                              "'competition.repair' ORDER BY id DESC LIMIT 1")).one()  # fmt: skip
    assert a.actor_user_id == accounts["operator"][1] and a.reason == "manual edit undone"
