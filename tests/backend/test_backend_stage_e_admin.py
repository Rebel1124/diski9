"""Phase 6C.6 Stage E: operational administration.

* Publication readiness (``round readiness`` and the summary + confirmation in
  ``round publish``): the same checks as publication, nothing written, and the
  readiness verdict always agrees with ``publish_round``.
* One-round investigation (``round inspect``): read-only, authorised like
  ``settle status``, never available to the scheduler's ``SYSTEM`` actor, never
  finalises early.
* Audit viewer (``audit list``, ``audit.view``): attribution without emails.
* One-line errors: missing or unreachable database, missing ``--code``, account
  arguments checked before the password prompt.

Service-level tests use isolated PostgreSQL databases; CLI tests run the real
command (in-process with the snapshot builder and authentication replaced, or in a
pseudo-terminal against the local Supabase Auth harness).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa
from champ_helpers import drop, isolated_engine
from pg_helpers import unique
from pty_cli import run_cli
from svc_helpers import principal, publish_dev
from test_backend_scheduler import BASE, FakeProvider, after, status, world

from diski9 import cli
from diski9.backend.auth.permissions import Forbidden
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import audit_log, job_runs, round_snapshots, rounds
from diski9.backend.devdata import dev_snapshot
from diski9.backend.jobs import tick
from diski9.backend.ops.audit import audit_list
from diski9.backend.ops.inspect import inspect_round
from diski9.backend.services import rounds as svc
from diski9.backend.services.common import NotFound, PublicationRefused
from diski9.backend.services.rounds import SYSTEM


@pytest.fixture
def db(pg_url, request):
    name = f"diski9_e_{request.node.name[:34].lower()}_test".replace("[", "_").replace("]", "")
    eng, url = isolated_engine(pg_url, name)
    try:
        yield eng, url
    finally:
        eng.dispose()
        drop(pg_url, name)


def _counts(eng):
    with transaction(eng) as conn:
        return tuple(
            conn.execute(sa.select(sa.func.count()).select_from(t)).scalar_one()
            for t in (job_runs, audit_log, round_snapshots)
        )


def _draft(eng, op, *, fixtures=20, first_in=timedelta(hours=3)):
    """A real (beta) draft round and a synthetic live snapshot built for it."""
    with transaction(eng) as conn:
        now = db_now(conn)
    code = unique("2031-W20-e")
    snap = dev_snapshot("dev-x", now, now + first_in, fixtures=fixtures)
    snap = replace(snap, round_id=code)
    v = svc.create_round(eng, op, code=code, window_start=snap.window[0],
                         window_end=snap.window[1])  # fmt: skip
    return v, snap


# ------------------------------------------------------------------ readiness
def test_readiness_writes_nothing_and_agrees_with_publication(db):
    eng, _ = db
    op = principal(eng, role="operator")
    v, snap = _draft(eng, op)
    before = _counts(eng)
    rd = svc.publication_readiness(eng, v.id, snap, source="football-db")
    assert rd.ready and rd.problem is None, rd.problem
    assert _counts(eng) == before  # no job record, audit entry or snapshot
    assert svc.get_round(eng, v.id).status == "draft"
    assert rd.report["opens"] and rd.required_by_bucket == {"A": 4, "B": 3, "C": 2}
    assert rd.fixtures == len(snap.fixtures) and rd.fingerprint == snap.fingerprint
    assert rd.newest_observation_at is not None and rd.max_quote_age_hours == 24
    published = svc.publish_round(eng, op, v.id, snap, source="football-db")
    assert published.status == "open"
    assert published.deadline_at == rd.deadline_at
    assert published.settle_cutoff_at == rd.settle_cutoff_at
    assert published.fingerprint == rd.fingerprint
    # a published round is not ready again (a snapshot never changes)
    again = svc.publication_readiness(eng, v.id, snap, source="football-db")
    assert not again.ready and "already open" in again.problem


@pytest.mark.parametrize("case", ["too_few_fixtures", "too_old", "wrong_source"])
def test_readiness_refusal_matches_the_publication_refusal(db, case):
    eng, _ = db
    op = principal(eng, role="operator")
    v, snap = _draft(eng, op, fixtures=5 if case == "too_few_fixtures" else 20)
    kw = {"source": "development" if case == "wrong_source" else "football-db"}
    if case == "too_old":
        kw["snapshot_age_limit"] = timedelta(microseconds=1)
    before = _counts(eng)
    rd = svc.publication_readiness(eng, v.id, snap, **kw)
    assert not rd.ready and rd.problem
    assert _counts(eng) == before
    with pytest.raises(PublicationRefused) as exc:
        svc.publish_round(eng, op, v.id, snap, **kw)
    assert exc.value.message == rd.problem  # one shared check: never disagrees
    assert svc.get_round(eng, v.id).status == "draft"


def test_readiness_unknown_round(db):
    eng, _ = db
    _, snap = _draft(eng, principal(eng, role="operator"))
    with pytest.raises(NotFound):
        svc.publication_readiness(eng, __import__("uuid").uuid4(), snap, source="football-db")


# ------------------------------------------------------------------ inspection
def test_inspection_is_authorised_and_never_for_system(db):
    eng, _ = db
    op = principal(eng, role="operator")
    view, _ = publish_dev(eng, op)
    for who in (principal(eng), SYSTEM):  # a participant; the scheduler actor
        with pytest.raises(Forbidden):
            inspect_round(eng, who, view.id)
    with pytest.raises(Forbidden):
        audit_list(eng, SYSTEM)


def test_inspection_of_draft_and_open_rounds_writes_nothing(db):
    eng, _ = db
    op = principal(eng, role="operator")
    v, _ = _draft(eng, op)
    view, _ = publish_dev(eng, op)
    before = _counts(eng)
    d = inspect_round(eng, op, v.id)
    assert d.position == "awaiting_publication" and d.settlement is None
    assert any("round readiness" in n for n in d.notes)
    o = inspect_round(eng, op, view.id)
    assert o.position == "entries_open" and o.settlement is not None
    assert o.settlement.eligible_to_finalise is False
    assert {"publish"} <= {j["job"] for j in o.jobs}
    assert {"round.create", "round.publish"} <= {a["action"] for a in o.audit}
    assert _counts(eng) == before


def test_inspection_reports_s02_timing_without_finalising(db):
    """Recovery visibility: a settled round in its correction window shows the
    earliest finalisation and 'cannot finalise'; inspecting it changes nothing."""
    eng, _ = db
    op = principal(eng, role="operator")
    w = world(eng, entries=1, cwh=None, cutoff_after=4)  # the schedule's real 24 h window
    fake = FakeProvider()
    fake.add(w)
    after(eng, w["deadline"])
    tick(eng, BASE, provider_factory=lambda: fake)
    after(eng, w["cutoff"])
    tick(eng, BASE, provider_factory=lambda: fake)
    assert status(eng, w["round"]) == "settling"
    before = _counts(eng)
    ins = inspect_round(eng, op, w["round"])
    assert ins.position == "correction_window"
    s = ins.settlement
    assert s.version is not None and not s.eligible_to_finalise
    assert s.earliest_finalisation > ins.evaluated_at + timedelta(hours=23)
    assert ins.fixture_summary["relevant"] >= 1 and ins.fixture_summary["unresolved"] == 0
    assert {"scheduler.lock", "scheduler.settle"} <= {j["job"] for j in ins.jobs}
    assert "round.lock" in {a["action"] for a in ins.audit}
    assert _counts(eng) == before and status(eng, w["round"]) == "settling"


# ------------------------------------------------------------------ audit viewer
def test_audit_list_attribution_filters_and_privacy(db):
    eng, _ = db
    op = principal(eng, role="operator")
    with pytest.raises(Forbidden):
        audit_list(eng, principal(eng))  # a participant has no audit.view
    v, _ = _draft(eng, op)
    view, _ = publish_dev(eng, op)
    rows = audit_list(eng, op, round_code=view.code)
    assert {r["action"] for r in rows} == {"round.create", "round.publish"}
    assert all(r["target"] == view.code and r["actor_role"] == "operator" for r in rows)
    assert all("@" not in json.dumps(r, default=str) for r in audit_list(eng, op, limit=200))
    assert {r["action"] for r in audit_list(eng, op, action="round.pub")} == {"round.publish"}
    assert audit_list(eng, op, action="round_") == []  # wildcards are literal
    with pytest.raises(NotFound):
        audit_list(eng, op, round_code="no-such-round")
    w = world(eng, entries=1, deadline_in=2)
    after(eng, w["deadline"])
    svc.lock_round(eng, SYSTEM, w["round"])
    (lock,) = [r for r in audit_list(eng, op, action="round.lock")]
    assert lock["actor"] == "SYSTEM" and lock["actor_role"] == "system"


# ------------------------------------------------------------------ CLI (in-process)
@pytest.fixture
def cli_env(db, monkeypatch):
    eng, url = db
    monkeypatch.setenv("DISKI9_APP_DATABASE_URL", url)
    monkeypatch.setenv("DISKI9_APP_ENVIRONMENT", "test")
    return eng


def _patch(monkeypatch, snap, op, answers=()):
    """Replace only the football-store snapshot builder and the password step."""
    import diski9.challenge.roundsheet as rs
    import diski9.settlement_cli as sc

    monkeypatch.setattr(rs, "build_live_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr(sc, "_principal", lambda engine, email, who="Operator": op)
    it = iter(answers)
    monkeypatch.setattr(sc, "_ask", lambda prompt: next(it))


def test_cli_readiness_exit_codes_and_json(cli_env, monkeypatch, capsys):
    eng = cli_env
    op = principal(eng, role="operator")
    v, snap = _draft(eng, op)
    _patch(monkeypatch, snap, op)
    assert cli.main(["round", "readiness", "--code", v.code]) == 0
    out = capsys.readouterr().out
    assert "READY to publish" in out and "buckets (eligible/pick): A" in out
    assert cli.main(["round", "readiness", "--code", v.code, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ready"] and data["fingerprint"] == snap.fingerprint
    _, small = _draft(eng, op, fixtures=5)
    _patch(monkeypatch, replace(small, round_id=v.code), op)
    assert cli.main(["round", "readiness", "--code", v.code]) == 1
    assert "NOT READY" in capsys.readouterr().out
    assert svc.get_round(eng, v.id).status == "draft"


def test_cli_publish_shows_readiness_and_needs_the_round_code(cli_env, monkeypatch, capsys):
    eng = cli_env
    op = principal(eng, role="operator")
    v, snap = _draft(eng, op)
    before = _counts(eng)
    _patch(monkeypatch, snap, op, answers=["yes"])  # not the round code
    assert cli.main(["round", "publish", "--code", v.code]) == 0
    out = capsys.readouterr().out
    assert "READY to publish" in out and "Not confirmed; nothing changed." in out
    assert svc.get_round(eng, v.id).status == "draft" and _counts(eng) == before
    _patch(monkeypatch, snap, op, answers=[v.code])
    assert cli.main(["round", "publish", "--code", v.code]) == 0
    r = svc.get_round(eng, v.id)
    assert r.status == "open" and r.fingerprint == snap.fingerprint
    with transaction(eng) as conn:
        actor = conn.execute(sa.select(audit_log.c.actor_user_id).where(
            audit_log.c.action == "round.publish")).scalar_one()  # fmt: skip
    assert actor == op.user_id


def test_cli_publish_not_ready_is_refused_by_the_service_and_recorded(cli_env, monkeypatch,
                                                                      capsys):  # fmt: skip
    eng = cli_env
    op = principal(eng, role="operator")
    v, _ = _draft(eng, op)
    _, small = _draft(eng, op, fixtures=5)
    _patch(monkeypatch, replace(small, round_id=v.code), op)  # no answers: never asked
    assert cli.main(["round", "publish", "--code", v.code]) == 2
    captured = capsys.readouterr()
    assert "NOT READY" in captured.out and "Not enough eligible fixtures" in captured.err
    with transaction(eng) as conn:
        refused = conn.execute(sa.select(job_runs).where(job_runs.c.job == "publish",
                                                         job_runs.c.scope == v.code)).one()  # fmt: skip
    assert refused.status == "failed"  # the refusal is still recorded, as before Stage E
    assert svc.get_round(eng, v.id).status == "draft"


def test_cli_inspect_and_audit_output(cli_env, monkeypatch, capsys):
    eng = cli_env
    op = principal(eng, role="operator")
    view, _ = publish_dev(eng, op)
    _patch(monkeypatch, None, op)
    assert cli.main(["round", "inspect", "--code", view.code]) == 0
    out = capsys.readouterr().out
    assert "position entries open" in out and "can finalise now:      no" in out
    assert "championship:" in out and "@" not in out
    assert cli.main(["audit", "list", "--round", view.code]) == 0
    out = capsys.readouterr().out
    assert "round.publish" in out and f"on {view.code}" in out and "@" not in out
    assert cli.main(["audit", "list", "--since", "not-a-time"]) == 2
    assert "--since must be an ISO time" in capsys.readouterr().err


def test_cli_one_line_errors(cli_env, monkeypatch, capsys, tmp_path):
    for argv in (["round", "show"], ["round", "lock"], ["round", "inspect"],
                 ["round", "readiness"], ["round", "finalise-check"]):  # fmt: skip
        assert cli.main(argv) == 2
        assert "--code is required" in capsys.readouterr().err
    monkeypatch.delenv("DISKI9_APP_DATABASE_URL")
    monkeypatch.chdir(tmp_path)  # no .env file here either
    assert cli.main(["round", "list"]) == 2
    err = capsys.readouterr().err
    assert "DISKI9_APP_DATABASE_URL is not set" in err and "Traceback" not in err
    monkeypatch.setenv(
        "DISKI9_APP_DATABASE_URL", "postgresql+psycopg://someone:S3cretPw@127.0.0.1:1/nowhere"
    )
    assert cli.main(["round", "list"]) == 1
    err = capsys.readouterr().err
    assert "database is unavailable" in err and "S3cretPw" not in err
    monkeypatch.setenv("DISKI9_APP_DATABASE_URL", "mysql://someone:S3cretPw@h/x")
    assert cli.main(["settle", "status", "--round", "x"]) == 2
    err = capsys.readouterr().err
    assert "must be a PostgreSQL URL" in err and "S3cretPw" not in err


# ------------------------------------------------------------------ CLI (real terminal)
from test_backend_operator_cli import ANON, AUTH_URL, PASSWORD, make_account, provider  # noqa: E402,F401,I001

needs_auth = pytest.mark.skipif(not (AUTH_URL and ANON), reason="needs the local Supabase Auth")


def _env(url):
    return {"DISKI9_APP_DATABASE_URL": url, "DISKI9_APP_ENVIRONMENT": "test",
            "DISKI9_SUPABASE_AUTH_URL": AUTH_URL, "DISKI9_SUPABASE_PUBLISHABLE_KEY": ANON,
            "DISKI9_SUPABASE_JWT_ISSUER": AUTH_URL}  # fmt: skip


@needs_auth
def test_pty_account_arguments_are_checked_before_the_password(engine, pg_url, provider):  # noqa: F811
    owner, _ = make_account(engine, provider, "owner")
    cases = (
        (["grant-role"], "--role is required"),
        (["revoke-feature"], "--feature is required"),
        (["suspend", "--role", "operator"], "--role does not apply"),
        (["reinstate", "--feature", "lucy.research"], "--feature does not apply"),
    )
    for extra, msg in cases:
        rc, out = run_cli(["account", *extra, "--email", "x@example.com", "--reason", "r",
                           "--operator", owner], _env(pg_url))  # fmt: skip
        assert rc == 2 and msg in out and "assword for" not in out, out


@needs_auth
def test_pty_inspect_and_audit_need_an_authorised_person(engine, pg_url, provider):  # noqa: F811
    op, op_id = make_account(engine, provider, "operator")
    part, _ = make_account(engine, provider)
    with transaction(engine) as conn:
        code = conn.execute(sa.select(rounds.c.code).limit(1)).scalar_one_or_none()
    if code is None:
        view, _ = publish_dev(engine, principal(engine, role="operator"))
        code = view.code
    for argv in (["round", "inspect", "--code", code], ["audit", "list", "--limit", "5"]):
        rc, out = run_cli([*argv, "--operator", part], _env(pg_url), password=PASSWORD)
        assert rc == 3 and "does not have permission" in out, out
        rc, out = run_cli([*argv, "--operator", op], _env(pg_url), password=PASSWORD)
        assert rc == 0 and PASSWORD not in out, out
