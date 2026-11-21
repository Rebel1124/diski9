"""Phase 6C.5 Stage F1: development tooling (participants, bulk entries, resumable
championship runner) on real PostgreSQL through the real services.

Each scenario runs in its own database (championship streams are global state).
Plans use short *real* deadlines (5 s) and, except for the ten-round test, three
rounds per championship for speed; ``set_required`` changes that setting of the
isolated test database only. Nothing here changes the clock: locks wait for the
real deadline, and only settle and finalise use the existing development-only
``as_of`` overrides."""

from __future__ import annotations

import contextlib
from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa
from champ_helpers import drop, isolated_engine, operator, owner, set_required
from svc_helpers import principal, publish_dev

from diski9.backend import dev_championship as dc
from diski9.backend.auth.permissions import Forbidden
from diski9.backend.db import db_now, transaction

FAST = {"deadline_seconds": 5, "evidence_seconds": 2, "participants": 6}


@pytest.fixture
def db(pg_url, request):
    name = "diski9_f1_" + request.node.name[5:30].replace("-", "_") + "_test"
    eng, _ = isolated_engine(pg_url, name)
    set_required(eng, 3)
    yield eng
    eng.dispose()
    drop(pg_url, name)


def q(eng, sql, **params):
    with transaction(eng) as conn:
        return conn.execute(sa.text(sql), params).all()


def quiet(_msg):
    pass


def integrity(eng):
    """No duplicate entries, points, memberships or mixed standings versions."""
    assert not q(eng, "SELECT round_id, user_id FROM app.entries GROUP BY 1, 2 HAVING count(*) > 1")
    assert not q(eng, "SELECT score_set_id, user_id FROM app.round_scores GROUP BY 1, 2 "
                      "HAVING count(*) > 1")  # fmt: skip
    assert not q(eng, "SELECT round_id FROM app.championship_rounds GROUP BY 1 "
                      "HAVING count(*) > 1")  # fmt: skip
    # no cross-stream contamination: development participants only in development rounds
    assert not q(eng, "SELECT 1 FROM app.entries e JOIN app.rounds r ON r.id = e.round_id "
                      "JOIN app.user_identities i ON i.user_id = e.user_id "
                      "WHERE i.provider = 'development' AND NOT r.is_development")  # fmt: skip
    assert not q(eng, "SELECT 1 FROM app.championships WHERE stream <> 'development'")
    with transaction(eng) as conn:
        from diski9.backend.services.championships import verify_stream

        assert verify_stream(conn, "development") == []


def champs(eng):
    return {c.name: c for c in dc.championships(eng)}


# ------------------------------------------------------------------ participants and entries
def test_participants_are_development_only_idempotent_and_audited(db):
    op = operator(db)
    assert dc.ensure_participants(db, op, 6, preview=True) == (0, 0)
    assert dc.ensure_participants(db, op, 6) == (0, 6)
    assert dc.ensure_participants(db, op, 6) == (6, 0)  # repeated: no duplicates
    assert dc.ensure_participants(db, op, 8) == (6, 2)
    rows = q(db, "SELECT p.username, i.provider, i.subject, u.email FROM app.profiles p "
                 "JOIN app.user_identities i ON i.user_id = p.user_id "
                 "LEFT JOIN app.user_private u ON u.user_id = p.user_id "
                 "WHERE p.username LIKE 'devp-%' ORDER BY 1")  # fmt: skip
    assert [r.username for r in rows] == [f"devp-{i:04d}" for i in range(1, 9)]
    assert {r.provider for r in rows} == {"development"} and all(r.email is None for r in rows)
    assert (
        len(
            q(
                db,
                "SELECT 1 FROM app.user_identities i JOIN app.profiles p ON p.user_id = "
                "i.user_id WHERE p.username LIKE 'devp-%'",
            )
        )
        == 8
    )  # one identity each
    # no Supabase identity and no role: nobody can sign in as them or act as staff
    assert not q(db, "SELECT 1 FROM app.user_roles r JOIN app.user_identities i "
                     "ON i.user_id = r.user_id WHERE i.provider = 'development'")  # fmt: skip
    audits = q(db, "SELECT action FROM app.audit_log WHERE action = 'dev_participants_created'")
    assert len(audits) == 2
    with pytest.raises(dc.DevToolError):
        dc.ensure_participants(db, op, 0)
    with pytest.raises(Forbidden):  # an ordinary participant cannot create them
        dc.ensure_participants(db, principal(db), 3)


def test_development_tools_refuse_production_and_real_accounts(db, monkeypatch):
    op = operator(db)
    dc.ensure_participants(db, op, 2)
    real = principal(db)  # a real (Supabase-linked) participant
    with pytest.raises(dc.DevToolError, match="Only development participants"):
        dc.participant_principal(db, real.user_id)
    monkeypatch.setenv("DISKI9_APP_ENVIRONMENT", "production")
    with pytest.raises(dc.DevToolError, match="refused in production"):
        dc.ensure_participants(db, op, 2)
    with pytest.raises(dc.DevToolError, match="refused in production"):
        dc.run_plan(db, dc.preset("zero-points", 3, **FAST), "prod", op)


def test_bulk_entries_are_valid_varied_deterministic_and_never_for_beta(db):
    op = operator(db)
    dc.ensure_participants(db, op, 6)
    view, _ = publish_dev(db, op, deadline_in=timedelta(hours=2), fixtures=20)
    assert dc.submit_all(db, op, view.id) == (0, 6)
    assert dc.submit_all(db, op, view.id) == (6, 0)  # resumable: nothing duplicated
    sels = q(db, "SELECT s.entry_id, x.bucket, x.fixture_id, x.market, x.outcome "
                 "FROM app.entries e JOIN app.submissions s ON s.id = e.current_submission_id "
                 "JOIN app.submission_selections x ON x.submission_id = s.id "
                 "WHERE e.round_id = :r", r=view.id)  # fmt: skip
    by_entry: dict = {}
    for r in sels:
        by_entry.setdefault(r.entry_id, []).append(r)
    assert len(by_entry) == 6
    for picks in by_entry.values():  # nine eligible predictions in the 4/3/2 buckets
        assert len(picks) == 9 and sorted(p.bucket for p in picks) == list("AAAABBBCC")
        assert len({p.fixture_id for p in picks}) == 9
    portfolios = {frozenset((p.fixture_id, p.market, p.outcome) for p in v)
                  for v in by_entry.values()}  # fmt: skip
    assert len(portfolios) >= 4  # varied
    # deterministic: the same variant rule gives the same portfolio
    assert dc.variant_for("spread", 2, 1, 2026, 3) == dc.variant_for("spread", 2, 1, 2026, 3)
    assert dc.variant_for("pairs", 2, 1, 2026, 3) == dc.variant_for("pairs", 3, 1, 2026, 3)
    beta = q(db, "SELECT id FROM app.rounds WHERE NOT is_development LIMIT 1")
    if not beta:
        from pg_helpers import make_round

        with transaction(db) as conn:
            rid, _, _ = make_round(conn)
    else:
        rid = beta[0].id
    with pytest.raises(dc.DevToolError, match="only for development rounds"):
        dc.submit_all(db, op, rid)


# ------------------------------------------------------------------ runner: presets
def test_complete_ten_round_championship(pg_url):
    name = "diski9_f1_ten_rounds_test"
    eng, _ = isolated_engine(pg_url, name)
    try:
        # the real preset (8 participants, 40 fixtures); only the deadline is shorter
        plan = dc.preset("ten-round-complete", 10, deadline_seconds=5, evidence_seconds=2)
        rep = dc.run_plan(eng, plan, "ten", operator(eng), say=quiet)
        assert rep.done and rep.stopped is None
        (c,) = dc.championships(eng)
        assert (c.status, c.counted, c.required) == ("completed", 10, 10) and c.champions
        assert len(q(eng, "SELECT 1 FROM app.rounds WHERE status = 'final'")) == 10
        integrity(eng)
    finally:
        eng.dispose()
        drop(pg_url, name)


@pytest.mark.parametrize(
    ("preset", "expect"),
    [
        ("with-practice", {"Championship Nov-26": ("completed", 3)}),
        ("with-invalidated", {"Championship Nov-26": ("completed", 3)}),
        (
            "rollover",
            {
                "Championship Nov-26": ("completed", 3),
                "Championship Nov-26 (2)": ("in_progress", 2),
            },
        ),
        ("historical-invalidation-before-next", {"Championship Nov-26": ("completed", 3)}),
        (
            "historical-invalidation-after-next",
            {
                "Championship Nov-26": ("completed", 2),
                "Championship Nov-26 (2)": ("in_progress", 1),
            },
        ),
    ],  # fmt: skip
)
def test_presets_exercise_the_championship_rules(db, preset, expect):
    rep = dc.run_plan(db, dc.preset(preset, 3, **FAST), "p", operator(db), owner=owner(db),
                      say=quiet)  # fmt: skip
    assert rep.done, rep.log[-3:]
    got = {k: (v.status, v.counted) for k, v in champs(db).items()}
    assert got == expect
    kinds = [r.kind for r in q(db, "SELECT (SELECT kind FROM app.score_sets x "
                                   "WHERE x.round_id = r.id ORDER BY revision DESC LIMIT 1) "
                                   "FROM app.rounds r ORDER BY deadline_at")]  # fmt: skip
    if preset == "with-practice":
        assert kinds[1] == "practice"  # three entries: practice, not counted
    if preset == "with-invalidated":
        assert kinds[1] == "void"  # D-32b at finalisation: not counted
    if preset.startswith("historical"):
        assert kinds[1] == "void"  # round 2 reopened by the owner and invalidated
        assert any("reopened by the owner" in m for m in rep.log)
    if preset == "historical-invalidation-after-next":
        assert champs(db)["Championship Nov-26"].champions  # boundary kept (D-30a)
    integrity(db)


def test_ties_and_zero_points(db):
    op = operator(db)
    rep = dc.run_plan(db, dc.preset("championship-tie", 3, **FAST), "tie", op, say=quiet)
    assert rep.done
    (c,) = dc.championships(db)
    assert c.status == "completed" and len(c.champions) >= 2  # joint champions
    shared = q(db, "SELECT score_set_id, rank FROM app.round_scores WHERE rank IS NOT NULL "
                   "GROUP BY 1, 2 HAVING count(*) > 1")  # fmt: skip
    assert shared  # shared weekly ranks, each with the same points (scoring engine)
    for s in shared:
        pts = q(db, "SELECT DISTINCT points FROM app.round_scores WHERE score_set_id = :s "
                    "AND rank = :r", s=s.score_set_id, r=s.rank)  # fmt: skip
        assert len(pts) == 1
    integrity(db)


def test_zero_points_has_no_champion_and_weekly_ties_spread(db):
    op = operator(db)
    assert dc.run_plan(db, dc.preset("zero-points", 3, **FAST), "zero", op, say=quiet).done
    (c,) = dc.championships(db)
    assert c.status == "completed" and c.champions == ()
    assert dc.run_plan(db, dc.preset("weekly-ties", 3, **FAST), "wties", op, say=quiet).done
    integrity(db)


def test_reopen_and_correct_recalculates(db):
    rep = dc.run_plan(db, dc.preset("reopen-and-correct", 3, **FAST), "rc", operator(db),
                      owner=owner(db), say=quiet)  # fmt: skip
    assert rep.done
    r2 = q(db, "SELECT (SELECT count(*) FROM app.score_sets x WHERE x.round_id = r.id) AS n "
               "FROM app.rounds r ORDER BY deadline_at")[1]  # fmt: skip
    assert r2.n == 2  # a second official publication after the correction
    # the correction republished round 2 and the standings were recalculated
    assert q(db, "SELECT 1 FROM app.championship_versions WHERE cause = 'round_republished'")
    integrity(db)


# ------------------------------------------------------------------ interruption and resume
class Boom(Exception):
    pass


@pytest.mark.parametrize("event", ["before:settle", "after:lock", "after:finalise",
                                   "before:entries"])  # fmt: skip
def test_interruption_then_resume_has_no_duplicates(db, event):
    op = operator(db)
    plan = dc.preset("ten-round-complete", 3, **FAST)

    def crash(e, k):
        if e == event and k == 2:
            raise Boom(e)

    with pytest.raises(Boom):
        dc.run_plan(db, plan, "intr", op, say=quiet, hook=crash)
    before = dc.inspect_run(db, "intr", plan)
    assert before[0].stage.startswith("final") and before[2].status is None
    rep = dc.run_plan(db, plan, "intr", op, say=quiet)  # resume
    assert rep.done and any("already final" in m for m in rep.log)
    rep2 = dc.run_plan(db, plan, "intr", op, say=quiet)  # repeated resume: nothing to do
    assert rep2.done and sum("already final" in m for m in rep2.log) == 3
    (c,) = dc.championships(db)
    assert (c.status, c.counted) == ("completed", 3)
    integrity(db)


def test_graceful_stop_and_partial_entries_resume(db, monkeypatch):
    op = operator(db)
    plan = dc.preset("ten-round-complete", 3, **FAST)
    calls = {"n": 0}
    rep = dc.run_plan(
        db,
        plan,
        "grace",
        op,
        say=quiet,
        stop=lambda: calls.__setitem__("n", calls["n"] + 1) or calls["n"] > 12,
    )
    assert not rep.done and rep.stopped and "interrupted" in rep.stopped.reason
    # a crash in the middle of the entries step: some participants entered, then resume
    from diski9.backend import settlement_scenarios as sc

    real, seen = sc.submit_test_entry, {"n": 0}

    def flaky(*a, **k):
        seen["n"] += 1
        if seen["n"] == 3:
            raise Boom("connection lost")
        return real(*a, **k)

    states = dc.inspect_run(db, "grace", plan)
    if any(s.status == "open" or s.status is None for s in states):
        monkeypatch.setattr(sc, "submit_test_entry", flaky)
        with contextlib.suppress(Boom):
            dc.run_plan(db, plan, "grace", op, say=quiet)
        monkeypatch.setattr(sc, "submit_test_entry", real)
    rep = dc.run_plan(db, plan, "grace", op, say=quiet)
    assert rep.done
    for s in dc.inspect_run(db, "grace", plan):
        assert s.entries == 6
    integrity(db)


def test_round_limit_pauses_and_a_different_plan_is_refused(db):
    op = operator(db)
    plan = dc.preset("ten-round-complete", 3, **FAST)
    rep = dc.run_plan(db, plan, "lim", op, say=quiet, rounds=1)
    assert rep.paused and not rep.done
    other = replace(plan, seed=99)  # a different plan under the same run id
    with pytest.raises(dc.DevToolError, match="different scenario plan"):
        dc.run_plan(db, other, "lim", op, say=quiet)
    with pytest.raises(dc.DevToolError, match="different scenario plan"):
        dc.inspect_run(db, "lim", other)
    assert dc.run_plan(db, plan, "lim", op, say=quiet).done


def test_operator_password_expiry_pauses_or_reauthenticates(db):
    op = operator(db)
    with transaction(db) as conn:
        now = db_now(conn)
    stale = replace(op, authenticated_at=now - timedelta(hours=13),
                    reauthenticated_at=now - timedelta(hours=13))  # fmt: skip
    plan = dc.preset("zero-points", 3, **FAST)
    rep = dc.run_plan(db, plan, "auth", stale, say=quiet)
    assert rep.stopped and "re-authentication required" in rep.stopped.reason
    assert not q(db, "SELECT 1 FROM app.rounds")  # nothing was written
    asked = []
    rep = dc.run_plan(
        db,
        plan,
        "auth",
        stale,
        say=quiet,
        reauthenticate=lambda role: asked.append(role) or operator(db),
    )
    assert rep.done and asked == ["operator"]  # asked once, then the fresh principal is kept


def test_owner_recency_is_checked_before_reopening(db):
    op, own = operator(db), owner(db)
    with transaction(db) as conn:
        now = db_now(conn)
    old = replace(own, reauthenticated_at=now - timedelta(minutes=20))  # sensitive: 15 min
    plan = dc.preset("reopen-and-correct", 3, **FAST)
    rep = dc.run_plan(db, plan, "own", op, owner=old, say=quiet)
    assert rep.stopped and "owner" in rep.stopped.reason
    assert not q(db, "SELECT 1 FROM app.audit_log WHERE action LIKE '%reopen%'")
    rep = dc.run_plan(db, plan, "own", op, owner=old, say=quiet,
                      reauthenticate=lambda role: owner(db))  # fmt: skip
    assert rep.done


def test_failed_verification_stops_safely(db, monkeypatch):
    from diski9.backend.services import championships as ch

    monkeypatch.setattr(ch, "verify_stream", lambda conn, stream: ["simulated finding"])
    rep = dc.run_plan(db, dc.preset("zero-points", 3, **FAST), "ver", operator(db), say=quiet)
    assert rep.stopped and "verification failed" in rep.stopped.reason
    assert len(q(db, "SELECT 1 FROM app.rounds")) == 1  # stopped after the first round


def test_plan_validation(db):
    with pytest.raises(dc.DevToolError, match="scenario must be one of"):
        dc.plan_from_dict({"name": "x", "rounds": [{"scenario": "pending"}]})
    with pytest.raises(dc.DevToolError, match="more than one action"):
        dc.plan_from_dict(
            {
                "name": "x",
                "rounds": [{}, {}],
                "actions": [
                    {"after": 2, "action": "correct", "round": 1},
                    {"after": 2, "action": "invalidate", "round": 1},
                ],
            }
        )
    p = dc.preset("rollover")
    assert dc.plan_from_dict(dc.plan_to_dict(p)) == p
    with pytest.raises(dc.DevToolError, match="run-id"):
        dc.run_plan(db, p, "Bad Id", operator(db))
