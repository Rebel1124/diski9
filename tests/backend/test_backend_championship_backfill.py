"""Phase 6C.5 Stage C: historical backfill (safeguards, interruption, idempotency,
equivalence with normal processing) and the Stage C containment of re-finalised
rounds, on two isolated PostgreSQL databases.

Database A holds "legacy" rounds finalised without official results (as before
app_0007); database B is an identical twin processed normally."""

from __future__ import annotations

from types import SimpleNamespace

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
    results,
    settle,
    users,
    winner,
)
from svc_helpers import principal

from diski9.backend.auth.permissions import Forbidden
from diski9.backend.db import transaction
from diski9.backend.services import championships as ch
from diski9.backend.services import competition as comp
from diski9.backend.services import competition_ops as cops
from diski9.backend.services import corrections as co
from diski9.backend.services import leaderboards as lb

DB_A, DB_B = "diski9_champ_bf_a_test", "diski9_champ_bf_b_test"
ORDER = ["C1", "C2", "P", "C3"]


def world(eng):
    op = operator(eng)
    u = users(eng, 6)
    plan = [
        [(u[i], WIN if i == 0 else lose(i)) for i in range(5)],
        [(u[i], WIN if i in (1, 2) else lose(i)) for i in range(5)],
        [(u[0], lose(1)), (u[5], WIN)],
        [(u[i], WIN if i == 3 else lose(i)) for i in range(1, 6)],
    ]
    made = dict(zip(ORDER, build(eng, plan), strict=True))
    for k in ORDER:
        results(eng, op, made[k], winner)
    for k in ORDER:
        settle(eng, op, made[k])
    return op, u, made


@pytest.fixture(scope="module")
def twins(pg_url):
    a, _ = isolated_engine(pg_url, DB_A)
    b, _ = isolated_engine(pg_url, DB_B)
    op_a, u_a, w_a = world(a)
    op_b, u_b, w_b = world(b)
    yield {"a": (a, op_a, u_a, w_a), "b": (b, op_b, u_b, w_b)}
    a.dispose()
    b.dispose()
    drop(pg_url, DB_A)
    drop(pg_url, DB_B)


def counts(eng):
    with transaction(eng) as conn:
        return [conn.execute(sa.text(f"SELECT count(*) FROM app.{t}")).scalar_one()
                for t in ("score_sets", "round_scores", "championships", "championship_rounds",
                          "championship_versions", "audit_log", "domain_events")]  # fmt: skip


def test_legacy_rounds_have_no_official_results(twins, monkeypatch):
    a, op, _, w = twins["a"]
    monkeypatch.setattr(comp, "publish_finalised", lambda *x, **k: None)  # pre-app_0007
    for k in ORDER:
        finalise(a, op, w[k])
    monkeypatch.undo()
    assert lb.weekly_board(a, w["C1"]["round"], include_development=True).state == "unpublished"
    dev = next(s for s in cops.stream_status(a, op) if s.stream == "development")
    assert len(dev.unpublished_final) == 4 and dev.current == "Championship Nov-26"


def test_preview_changes_nothing_and_needs_an_operator(twins):
    a, op, u, _ = twins["a"]
    with pytest.raises(Forbidden):
        cops.preview_backfill(a, principal(a, user_id=u[0]))
    before = counts(a)
    plan = cops.preview_backfill(a, op)
    assert counts(a) == before
    assert plan.to_publish == 4 and plan.rounds_assigned == 0  # already members (pending)
    assert [i.kind for i in plan.items] == ["championship", "championship", "practice",
                                            "championship"]  # fmt: skip
    assert len(plan.token) == 16
    with pytest.raises(cops.BackfillRefused):
        cops.run_backfill(a, op, confirmation="0" * 16)
    assert counts(a) == before


def test_interrupted_backfill_resumes_safely(twins, monkeypatch):
    a, op, _, w = twins["a"]
    plan = cops.preview_backfill(a, op)
    real = comp.publish_finalised
    calls = {"n": 0}

    def flaky(*args, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("interrupted")
        return real(*args, **kw)

    monkeypatch.setattr(comp, "publish_finalised", flaky)
    # the preview inside run_backfill uses the real function first; patch counts the
    # execution phase: preview (4 real calls) is done before the patch takes effect
    monkeypatch.setattr(cops, "preview_backfill", lambda e, p: plan)
    with pytest.raises(RuntimeError, match="interrupted"):
        cops.run_backfill(a, op, confirmation=plan.token)
    monkeypatch.undo()
    again = cops.preview_backfill(a, op)
    assert [i.action for i in again.items] == ["already_published", "publish", "publish",
                                               "publish"]  # fmt: skip
    cops.run_backfill(a, op, confirmation=again.token)
    assert all(i.action == "already_published" for i in cops.preview_backfill(a, op).items)
    with transaction(a) as conn:
        assert ch.verify_stream(conn, "development") == []
        roles = dict(conn.execute(sa.text(
            "SELECT r.code, cr.role FROM app.championship_rounds cr JOIN app.rounds r "
            "ON r.id = cr.round_id")).all())  # fmt: skip
        audit = conn.execute(
            sa.text("SELECT count(*) FROM app.audit_log WHERE action = 'competition.backfill'")
        ).scalar()
    assert sorted(roles.values()) == ["counted", "counted", "counted", "practice"]
    assert audit == 1


def test_repeated_backfill_is_a_no_op(twins):
    a, op, _, _ = twins["a"]
    before = counts(a)
    plan = cops.preview_backfill(a, op)
    assert plan.to_publish == 0
    cops.run_backfill(a, op, confirmation=plan.token)
    after = counts(a)
    assert after[:5] == before[:5] and after[5] == before[5] + 1  # only the audit record


def normalised(eng, u, w):
    idx = {x: i for i, x in enumerate(u)}
    with transaction(eng) as conn:
        # display order within a shared rank uses internal IDs (they differ between
        # the two databases), so rows are compared as sorted lists
        sql = sa.text(
            "SELECT rs.* FROM app.round_scores rs JOIN app.score_sets s "
            "ON s.id = rs.score_set_id WHERE s.round_id = :r"
        )
        weekly = {
            k: sorted((idx[r.user_id], str(r.gross), r.rank, r.points, r.status)
                      for r in conn.execute(sql, {"r": w[k]["round"]}))
            for k in ORDER
        }  # fmt: skip
        member = {k: tuple(conn.execute(sa.text(
            "SELECT c.display_name, cr.role, cr.slot FROM app.championship_rounds cr JOIN "
            "app.championships c ON c.id = cr.championship_id WHERE cr.round_id = :r"),
            {"r": w[k]["round"]}).one()) for k in ORDER}  # fmt: skip
        champ = tuple(
            conn.execute(
                sa.text("SELECT display_name, status, counted_rounds FROM app.championships")
            ).one()
        )
        standings = {
            idx[r.user_id]: (r.rank, r.points, r.rounds_played, r.recoveries, r.qualifying_top10)
            for r in conn.execute(sa.text(
                "SELECT s.* FROM app.championship_standings s JOIN app.championship_versions v "
                "ON v.id = s.version_id JOIN app.championships c ON c.id = v.championship_id "
                "AND v.version = c.current_version"))
        }  # fmt: skip
    return weekly, member, champ, standings


def test_backfill_equals_normal_lifecycle_processing(twins):
    b, op_b, u_b, w_b = twins["b"]
    for k in ORDER:
        finalise(b, op_b, w_b[k])  # normal: published at finalisation
    a, _, u_a, w_a = twins["a"]
    na, nb = normalised(a, u_a, w_a), normalised(b, u_b, w_b)
    for part_a, part_b in zip(na, nb, strict=True):
        assert part_a == part_b
    assert na[2] == ("Championship Nov-26", "in_progress", 3)


def test_unclassifiable_rounds_are_reported_not_assigned(twins):
    a, _, _, _ = twins["a"]
    base = {"is_development": True, "result_mode": "synthetic", "series": "beta",
            "latest_kind": "final", "latest_version": 1, "provisional": False}  # fmt: skip
    cases = [
        ({"result_mode": None}, "cannot be classified"),
        ({"is_development": False, "result_mode": "synthetic"}, "cannot be classified"),
        ({"series": "legacy"}, "cannot be classified"),
        ({"is_development": False, "result_mode": "real", "series": "official"},
         "official series has not started"),
        ({"latest_kind": "reopened"}, "no final settlement version"),
        ({"provisional": True}, "designation is not final"),
    ]  # fmt: skip
    with transaction(a) as conn:
        assert cops._exclusion(conn, SimpleNamespace(**base)) is None
        for change, why in cases:
            assert why in cops._exclusion(conn, SimpleNamespace(**(base | change)))


def test_refinalised_round_changing_role_is_contained_until_stage_d(twins):
    """A counted round re-finalised as void (owner reopening + corrections) keeps
    its counted role and the last published standings; the championship is marked
    under review (pending recalculation) instead of being changed (Stage D)."""
    b, op, _, w = twins["b"]
    owner = fresh(b, principal(b, role="owner"))
    rid, fids = w["C3"]["round"], w["C3"]["fixtures"]
    first = co.CorrectionInput(fids[0], "CANC")
    imp = co.preview_reopen(b, owner, rid, correction=first)
    co.reopen_round(b, owner, rid, reason="league void ruling", evidence="league statement",
                    confirmation=imp.token, correction=first)  # fmt: skip
    review = lb.championship_board(b, stream="development", include_development=True)
    assert review.under_review and review.review_reasons == ("reopened",)
    for i in range(1, 6):  # six of nine matches cancelled: the round fails D-32b
        c = co.CorrectionInput(fids[i], "CANC")
        imp = co.preview_correction(b, op, rid, c)
        co.correct_result(b, op, rid, c, reason="cancelled", evidence="league statement",
                          confirmation=imp.token)  # fmt: skip
    before = lb.championship_board(b, stream="development", include_development=True)
    finalise(b, op, w["C3"])
    after = lb.championship_board(b, stream="development", include_development=True)
    assert after.counted_rounds == before.counted_rounds == 3  # not changed in Stage C
    assert after.rows == before.rows and after.version == before.version
    assert after.under_review and after.review_reasons == ("recalculation_pending",)
    wk = lb.weekly_board(b, rid, include_development=True)
    assert wk.round_void and wk.revision == 2  # the weekly result itself is republished
    with transaction(b) as conn:
        problems = ch.verify_stream(conn, "development")
    assert len(problems) == 1 and "Stage D" in problems[0]
