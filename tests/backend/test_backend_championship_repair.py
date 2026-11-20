"""Phase 6C.5 Stage D: integrity inspection and the audited competition repair on
its own PostgreSQL database (two-round championships).

Inconsistencies are produced the only ways they can arise: a re-finalisation whose
publication was skipped (as with data from before Stage D, or a manual database
intervention) and direct changes by a database superuser. Repair rebuilds derived
records through the normal services, never rewrites membership or settlement, and
refuses streams with material (non-authoritative) inconsistencies."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa
from champ_helpers import (
    WIN,
    build,
    drop,
    finalise,
    fresh,
    isolated_engine,
    lose,
    operator,
    owner,
    prepare,
    reopen_correct,
    set_required,
    users,
)
from svc_helpers import principal

from diski9.backend.auth.permissions import Forbidden, RecentAuthenticationRequired
from diski9.backend.db import transaction
from diski9.backend.services import championships as ch
from diski9.backend.services import competition as comp
from diski9.backend.services import competition_ops as cops
from diski9.backend.services import corrections as co
from diski9.backend.services import leaderboards as lb

DB = "diski9_champ_repair_test"
A = "Championship Nov-26"


@pytest.fixture(scope="module")
def rep(pg_url):
    eng, target = isolated_engine(pg_url, DB)
    set_required(eng, 2)
    op, own = operator(eng), owner(eng)
    u = users(eng, 5)
    plan = [[(u[i], WIN if i == k else lose(i)) for i in range(5)] for k in (0, 1)]
    made = build(eng, plan)
    prepare(eng, op, made)
    for w in made:
        finalise(eng, op, w)
    admin = sa.create_engine(target, poolclass=sa.pool.NullPool)
    yield {"engine": eng, "admin": admin, "op": op, "own": own, "u": u, "w": made}
    admin.dispose()
    eng.dispose()
    drop(pg_url, DB)


def inspect(eng):
    with transaction(eng) as conn:
        return ch.inspect_stream(conn, "development")


def counts(eng):
    with transaction(eng) as conn:
        return [conn.execute(sa.text(f"SELECT count(*) FROM app.{t}")).scalar_one()
                for t in ("score_sets", "round_scores", "championship_versions",
                          "championship_standings", "audit_log", "domain_events")]  # fmt: skip


def membership(eng):
    with transaction(eng) as conn:
        return sorted(conn.execute(sa.text(
            "SELECT round_id::text, championship_id::text, assigned_at FROM "
            "app.championship_rounds")).all())  # fmt: skip


def test_skipped_republication_is_reported_as_repairable(rep, monkeypatch):
    eng, op, own, w = rep["engine"], rep["op"], rep["own"], rep["w"]
    assert inspect(eng).findings == ()
    reopen_correct(
        eng, own, op, w[1], [co.CorrectionInput(f, "CANC") for f in w[1]["fixtures"][:6]]
    )
    monkeypatch.setattr(comp, "publish_finalised", lambda *a, **k: None)
    finalise(eng, fresh(eng, op), w[1])  # final (void) without official results
    monkeypatch.undo()
    ins = inspect(eng)
    assert ins.material == ()
    assert any("has no official results" in f.message for f in ins.repairable)
    assert ins.republish and ins.republish[0][0] == w[1]["round"]
    b = lb.championship_board(eng, stream="development", include_development=True)
    assert (b.status, b.counted_rounds) == ("completed", 2)  # still the published state


def test_repair_preview_writes_nothing_and_needs_an_operator(rep):
    eng, u = rep["engine"], rep["u"]
    with pytest.raises(Forbidden):
        cops.preview_repair(eng, principal(eng, user_id=u[0]))
    before = counts(eng)
    plan = cops.preview_repair(eng, fresh(eng, rep["op"]))
    assert counts(eng) == before
    assert len(plan.republish) == 1 and plan.unrepairable == () and plan.remaining == ()
    (c,) = plan.changes
    assert (c.name, c.before[:2], c.after[:2]) == (A, ("completed", 2), ("in_progress", 1))
    assert c.standings_changed and c.winners_changed and "L-33" in c.note
    assert len(plan.token) == 16
    # an owner may preview too (owner includes the operator capabilities)
    assert cops.preview_repair(eng, fresh(eng, rep["own"])).token == plan.token


def test_repair_safeguards(rep):
    eng, op = rep["engine"], fresh(rep["engine"], rep["op"])
    plan = cops.preview_repair(eng, op)
    before = counts(eng)
    with pytest.raises(cops.RepairRefused, match="reason"):
        cops.run_repair(eng, op, confirmation=plan.token, reason=" ")
    with pytest.raises(cops.RepairRefused, match="changed since the preview"):
        cops.run_repair(eng, op, confirmation="0" * 16, reason="fix")
    stale = replace(op, reauthenticated_at=op.now - timedelta(minutes=20))
    with pytest.raises(RecentAuthenticationRequired):
        cops.run_repair(eng, stale, confirmation=plan.token, reason="fix")
    with pytest.raises(Forbidden):
        cops.run_repair(eng, principal(eng, user_id=rep["u"][0]), confirmation=plan.token,
                        reason="fix")  # fmt: skip
    with pytest.raises(cops.RepairRefused, match="Unknown stream"):
        cops.preview_repair(eng, op, stream="private")
    assert counts(eng) == before


def test_interrupted_repair_leaves_nothing_partial_and_retry_succeeds(rep, monkeypatch):
    eng, op, w = rep["engine"], fresh(rep["engine"], rep["op"]), rep["w"]
    plan = cops.preview_repair(eng, op)
    before = counts(eng)

    def boom(*a, **k):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(cops, "preview_repair", lambda *a, **k: plan)
    monkeypatch.setattr(ch, "process_stream", boom)
    with pytest.raises(RuntimeError, match="interrupted"):
        cops.run_repair(eng, op, confirmation=plan.token, reason="restore consistency")
    monkeypatch.undo()
    assert counts(eng) == before  # round transaction rolled back as a whole
    again = cops.preview_repair(eng, op)
    assert again.token == plan.token
    done = cops.run_repair(eng, fresh(eng, op), confirmation=again.token,
                           reason="restore consistency")  # fmt: skip
    assert done.republish == plan.republish
    assert inspect(eng).findings == ()
    b = lb.championship_board(eng, stream="development", include_development=True)
    assert (b.status, b.counted_rounds) == ("in_progress", 1) and b.reopened_after_completion
    wk = lb.weekly_board(eng, w[1]["round"], include_development=True)
    assert wk.round_void and wk.revision == 2
    with transaction(eng) as conn:
        audit = conn.execute(
            sa.text("SELECT reason, after FROM app.audit_log WHERE action = 'competition.repair'")
        ).all()
        causes = conn.execute(
            sa.text("SELECT cause FROM app.championship_versions ORDER BY id DESC LIMIT 1")
        ).scalar()
    assert len(audit) == 1 and audit[0].reason == "restore consistency"
    assert audit[0].after["republished"] == list(plan.republish)
    assert "password" not in str(audit[0].after).lower() and causes == "repair"


def test_repeated_repair_is_a_no_op(rep):
    eng, op = rep["engine"], fresh(rep["engine"], rep["op"])
    plan = cops.preview_repair(eng, op)
    assert not plan.material_change and plan.repairable == ()
    before = counts(eng)
    with pytest.raises(cops.RepairRefused, match="Nothing to repair"):
        cops.run_repair(eng, op, confirmation=plan.token, reason="again")
    assert counts(eng) == before


def tamper_counter(rep):
    with rep["admin"].begin() as conn:
        conn.execute(sa.text("UPDATE app.championships SET counted_rounds = 0 "
                             "WHERE display_name = :n"), {"n": A})  # fmt: skip


def test_tampered_counter_is_repaired_without_touching_membership(rep):
    eng, op = rep["engine"], fresh(rep["engine"], rep["op"])
    tamper_counter(rep)
    ins = inspect(eng)
    assert any("counter 0 != 1" in f.message for f in ins.repairable) and ins.material == ()
    members = membership(eng)
    plan = cops.preview_repair(eng, op)
    (c,) = plan.changes
    assert c.before[1] == 0 and c.after[1] == 1 and not c.standings_changed
    cops.run_repair(eng, fresh(eng, op), confirmation=plan.token, reason="manual edit undone")
    assert membership(eng) == members and inspect(eng).findings == ()


def test_concurrent_repair_and_normal_processing(rep):
    eng = rep["engine"]
    tamper_counter(rep)
    op = fresh(eng, rep["op"])
    plan = cops.preview_repair(eng, op)
    errors = []

    def repair():
        try:
            cops.run_repair(eng, fresh(eng, op), confirmation=plan.token, reason="concurrent")
        except cops.RepairRefused:
            pass  # normal processing may have fixed it first: the token is then stale
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    def proc():
        for _ in range(3):
            try:
                with transaction(eng) as conn:
                    ch.process_stream(conn, "development", refresh_all=True)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

    threads = [threading.Thread(target=repair)] + [threading.Thread(target=proc) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and inspect(eng).findings == ()


def test_material_inconsistency_is_refused_and_reported(rep):
    """Published weekly results changed behind the application's back: not
    authoritative, so repair refuses the stream and asks for investigation."""
    eng, op = rep["engine"], fresh(rep["engine"], rep["op"])
    with rep["admin"].begin() as conn:
        conn.execute(sa.text("SET LOCAL session_replication_role = replica"))
        conn.execute(sa.text(
            "UPDATE app.round_scores SET points = 135 WHERE rank = 1 AND score_set_id = "
            "(SELECT id FROM app.score_sets WHERE round_id = :r ORDER BY revision DESC LIMIT 1)"),
            {"r": rep["w"][0]["round"]})  # fmt: skip
    ins = inspect(eng)
    assert ins.material and any("re-scoring" in f.message for f in ins.material)
    before = counts(eng)
    plan = cops.preview_repair(eng, op)
    assert plan.unrepairable and plan.changes == () and not plan.material_change
    with pytest.raises(cops.RepairRefused):
        cops.run_repair(eng, op, confirmation=plan.token, reason="try")
    assert counts(eng) == before
    status = next(s for s in cops.stream_status(eng, op) if s.stream == "development")
    assert status.material and not status.repairable


def test_member_outside_the_stream_never_blocks_processing(rep):
    """A membership row written outside the services (here a draft round inserted by
    a superuser) is reported as material; processing leaves that championship alone
    and publication elsewhere in the stream is not blocked."""
    eng = rep["engine"]
    with rep["admin"].begin() as conn:
        sid = conn.execute(sa.text("SELECT id FROM app.championship_series WHERE code='beta'")
                           ).scalar_one()  # fmt: skip
        draft = conn.execute(
            sa.text(
                "INSERT INTO app.rounds (code, schedule_id, series_id, window_start_at, "
                "window_end_at) SELECT 'draft-outside', id, series_id, now(), now() + interval "
                "'1 day' FROM app.round_schedules ORDER BY id LIMIT 1 RETURNING id"
            )
        ).scalar_one()
        cid = conn.execute(sa.text(
            "INSERT INTO app.championships (stream, series_id, ordinal, start_date, display_name) "
            "VALUES ('development', :s, 99, '2026-11-28', 'Championship Nov-26 (99)') "
            "RETURNING id"), {"s": sid}).scalar_one()  # fmt: skip
        conn.execute(
            sa.text(
                "INSERT INTO app.championship_rounds (round_id, championship_id, "
                "role) VALUES (:r, :c, 'practice')"
            ),
            {"r": draft, "c": cid},
        )
    with transaction(eng) as conn:
        out = ch.process_stream(conn, "development")
    assert out.skipped is None
    ins = inspect(eng)
    assert any("not in the development stream" in f.message for f in ins.material)
    # it is the open championship: shown as under review, never as definitive
    b = lb.championship_board(eng, stream="development", include_development=True)
    assert b.name == "Championship Nov-26 (99)"
    assert b.under_review and "integrity_review" in b.review_reasons and not b.definitive
    healthy = lb.championship_board(eng, stream="development", name=A, include_development=True)
    assert "integrity_review" not in healthy.review_reasons
    # a new round is not assigned into it (no permanent membership from inconsistent
    # state), but its weekly results still publish at finalisation
    u = rep["u"]
    (w,) = build(eng, [[(u[i], WIN if i == 0 else lose(i)) for i in range(5)]])
    prepare(eng, rep["op"], [w])
    finalise(eng, fresh(eng, rep["op"]), w)
    with transaction(eng) as conn:
        assert (
            conn.execute(
                sa.text("SELECT count(*) FROM app.championship_rounds WHERE round_id = :r"),
                {"r": w["round"]},
            ).scalar()
            == 0
        )
    wk = lb.weekly_board(eng, w["round"], include_development=True)
    assert wk.state == "final" and wk.championship_status == "pending_assignment"
    ins = inspect(eng)
    assert any(n.kind == "pending_assignment" and "held" in n.message for n in ins.notes)
    assert not any("not yet assigned" in f.message for f in ins.repairable)
    # repair refuses the stream: nothing is reassigned or rewritten
    plan = cops.preview_repair(eng, fresh(eng, rep["op"]), stream="development")
    assert plan.unrepairable and not plan.material_change
