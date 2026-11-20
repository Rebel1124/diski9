"""Phase 6C.5 Stage D: championship corrections through the real 6C.4 services
(owner reopening, operator corrections and invalidation, finalisation) on its own
PostgreSQL database, with two-round championships for this database only.

Rounds are built in phases so that "the next championship has not commenced yet"
is real (a later round published later):

* R1 (u0 wins), R2 (u1 wins) -> championship A, joint champions u0 and u1.
* Review of two reopened rounds; valid-to-valid correction of R2 (nobody recovers):
  u0 becomes the sole champion; the previous version stays readable.
* R2 invalidated (D-32b) before any successor: A returns to in progress (L-33).
* R3 (u2 wins) published later joins A and completes it again.
* R2 restored while A is full: weekly results republished, ``not_counted`` (CH-05).
* R4 (u3), R5 (u4) start and complete championship B; A's boundary is fixed.
* R1 invalidated after B commenced: R2 takes the freed slot (it is A's own member);
  then R3 invalidated: A stays completed with one round (D-30a); no champion; B is
  untouched. R3 restored into the free slot; then corrected to zero points.
* R5 operator-invalidated: B returns to in progress; a later correction cannot
  restore it (6C.4 limitation); R6 (u5) completes B."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from champ_helpers import (
    WIN,
    build,
    correct_all,
    drop,
    finalise,
    fresh,
    invalidate,
    isolated_engine,
    lose,
    operator,
    owner,
    prepare,
    reopen_correct,
    restore,
    set_required,
    users,
)
from svc_helpers import principal

from diski9.backend.auth.permissions import GUEST
from diski9.backend.db import transaction
from diski9.backend.services import championships as ch
from diski9.backend.services import corrections as co
from diski9.backend.services import leaderboards as lb

DB = "diski9_champ_corr_test"
A, B = "Championship Nov-26", "Championship Nov-26 (2)"


@pytest.fixture(scope="module")
def world(pg_url):
    eng, _ = isolated_engine(pg_url, DB)
    set_required(eng, 2)
    op, own = operator(eng), owner(eng)
    u = users(eng, 6)
    names = {}
    with transaction(eng) as conn:
        for x in u:
            names[x] = conn.execute(sa.text("SELECT username FROM app.profiles WHERE user_id = :u"),
                                    {"u": x}).scalar()  # fmt: skip
    st = {"engine": eng, "op": op, "own": own, "u": u, "w": {}, "names": names}

    def add(*specs):  # specs: (code, winner index) built together, prepared, not final
        plan = [[(u[i], WIN if i == win else lose(i)) for i in range(5) if i != skip] +
                ([(u[5], WIN if win == 5 else lose(5))] if skip is not None else [])
                for _, win, skip in specs]  # fmt: skip
        made = build(eng, plan)
        prepare(eng, op, made)
        for (code, _, _), w in zip(specs, made, strict=True):
            st["w"][code] = w

    st["add"] = add
    yield st
    eng.dispose()
    drop(pg_url, DB)


def board(eng, name=A, **kw):
    return lb.championship_board(eng, stream="development", name=name,
                                 include_development=True, **kw)  # fmt: skip


def counts(eng):
    with transaction(eng) as conn:
        return {t: conn.execute(sa.text(f"SELECT count(*) FROM app.{t}")).scalar_one()
                for t in ("score_sets", "championship_versions", "championship_standings",
                          "championship_rounds")}  # fmt: skip


def role(eng, w):
    with transaction(eng) as conn:
        return conn.execute(sa.text("SELECT role FROM app.championship_rounds WHERE round_id = :r"),
                            {"r": w["round"]}).scalar()  # fmt: skip


def code(eng, w):
    with transaction(eng) as conn:
        return conn.execute(sa.text("SELECT code FROM app.rounds WHERE id = :r"),
                            {"r": w["round"]}).scalar()  # fmt: skip


def consistent(eng):
    with transaction(eng) as conn:
        ins = ch.inspect_stream(conn, "development")
    assert ins.findings == (), ins.findings
    return ins


def champions(eng, name=A, **kw):
    return set(board(eng, name, **kw).champions)


def test_first_championship_and_joint_champions(world):
    eng, op, u, nm = world["engine"], world["op"], world["u"], world["names"]
    world["add"](("R1", 0, None), ("R2", 1, None))
    for k in ("R1", "R2"):
        finalise(eng, op, world["w"][k])
    b = board(eng)
    assert (b.status, b.counted_rounds, b.version) == ("completed", 2, b.latest_version)
    assert champions(eng) == {nm[u[0]], nm[u[1]]} and b.rows[0].shared and b.definitive
    consistent(eng)


def test_reopening_preserves_published_results_and_reviews_resolve_independently(world):
    eng, own, op, w = world["engine"], world["own"], world["op"], world["w"]
    before, rows_before = board(eng), counts(eng)
    co_own = fresh(eng, own)
    imp = co.preview_reopen(eng, co_own, w["R1"]["round"])
    co.reopen_round(eng, co_own, w["R1"]["round"], reason="check", evidence="league statement",
                    confirmation=imp.token)  # fmt: skip
    reopen_correct(
        eng, own, op, w["R2"], [co.CorrectionInput(f, "FT", 2, 2) for f in w["R2"]["fixtures"][:9]]
    )
    during = board(eng)
    assert counts(eng) == rows_before  # reopening and corrections write no results
    assert during.rows == before.rows and during.version == before.version
    assert during.under_review and during.review_reasons == ("reopened",)
    assert during.review_rounds == (code(eng, w["R1"]), code(eng, w["R2"]))
    assert not during.definitive
    # the participant sees the last published result next to the current settlement
    mine = lb.my_round_result(eng, principal(eng, user_id=world["u"][1]), w["R2"]["round"],
                              include_development=True)  # fmt: skip
    assert mine.published and mine.under_review and mine.weekly_points == 150
    assert mine.counts_toward_championship and mine.championship_points == 150
    assert mine.current is not None and mine.current.gross < 100  # corrected, not published
    wk = lb.weekly_board(eng, w["R2"]["round"], include_development=True)
    assert wk.state == "under_review" and wk.revision == 1
    # R2 re-finalised (valid to valid): A is recalculated; R1 is still under review
    finalise(eng, fresh(eng, op), w["R2"])
    after = board(eng)
    assert after.version == before.version + 1 and after.counted_rounds == 2
    assert after.review_reasons == ("reopened",) and after.review_rounds == (code(eng, w["R1"]),)
    assert champions(eng) == {world["names"][world["u"][0]]} and not after.rows[0].shared
    assert after.corrected_after_completion
    wk = lb.weekly_board(eng, w["R2"]["round"], include_development=True)
    assert wk.state == "final" and wk.revision == 2 and wk.corrected
    assert {r.points for r in wk.rows} == {0}  # the whole round was re-ranked
    # R1 re-finalised unchanged: the review clears; no new standings version
    finalise(eng, fresh(eng, op), w["R1"])
    cleared = board(eng)
    assert not cleared.under_review and cleared.definitive and cleared.version == after.version
    # the previous published version stays readable, names resolved now
    old = board(eng, version=before.version)
    assert (
        old.rows == before.rows
        and not old.definitive
        and set(old.champions) == set(before.champions)
    )
    versions = lb.championship_versions_list(eng, stream="development", name=A,
                                             include_development=True)  # fmt: skip
    assert versions[0].current and versions[0].cause == "round_republished"
    consistent(eng)


def test_invalidation_before_the_successor_reopens_the_championship(world):
    """L-33: a completed championship whose successor has not commenced returns to
    in progress and needs a replacement round."""
    eng, own, op, w = world["engine"], world["own"], world["op"], world["w"]
    with transaction(eng) as conn:
        completed_at = conn.execute(sa.text("SELECT completed_at FROM app.championships "
                                            "WHERE display_name = :n"), {"n": A}).scalar()  # fmt: skip
    invalidate(eng, own, op, w["R2"])
    b = board(eng)
    assert (b.status, b.counted_rounds) == ("in_progress", 1) and b.reopened_after_completion
    assert b.champions == () and not b.no_champion  # leaders only while in progress
    assert "continues until" in b.disclosure and role(eng, w["R2"]) == "void"
    assert lb.weekly_board(eng, w["R2"]["round"], include_development=True).round_void
    with transaction(eng) as conn:
        c = conn.execute(sa.text("SELECT completed_at, corrected_after_completion "
                                 "FROM app.championships WHERE display_name = :n"),
                         {"n": A}).one()  # fmt: skip
        ev = conn.execute(sa.text("SELECT count(*) FROM app.domain_events "
                                  "WHERE kind = 'championship_reopened'")).scalar()  # fmt: skip
        v = conn.execute(sa.text(
            "SELECT v.cause, v.reason FROM app.championship_versions v JOIN app.championships c "
            "ON c.id = v.championship_id AND v.version = c.current_version "
            "WHERE c.display_name = :n"), {"n": A}).one()  # fmt: skip
    assert c.completed_at == completed_at and c.corrected_after_completion and ev == 1
    assert v.cause == "round_invalidated" and "L-33" in v.reason
    ins = consistent(eng)
    assert any(n.kind == "reopened_after_completion" for n in ins.notes)
    # a later round joins A (not a new championship) and completes it again
    world["add"](("R3", 2, None))
    assert role(eng, w["R3"]) == "pending"
    finalise(eng, op, w["R3"])
    b = board(eng)
    assert (b.status, b.counted_rounds) == ("completed", 2) and not b.reopened_after_completion
    assert champions(eng) == {world["names"][world["u"][0]], world["names"][world["u"][2]]}
    assert len(lb.championship_list(eng, stream="development", include_development=True)) == 1
    consistent(eng)


def test_restored_round_without_capacity_does_not_count(world):
    eng, own, op, w = world["engine"], world["own"], world["op"], world["w"]
    before = board(eng)
    restore(eng, own, op, w["R2"], lambda i: (2, 2))  # valid again; nobody recovers
    assert role(eng, w["R2"]) == "not_counted"
    after = board(eng)
    assert after.rows == before.rows and after.counted_rounds == 2
    assert after.not_counted_rounds and after.version == before.version + 1  # role versioned
    wk = lb.weekly_board(eng, w["R2"]["round"], include_development=True)
    assert wk.state == "final" and not wk.round_void and wk.championship == A
    assert wk.counts_toward_championship is False
    assert "already reached 2 counted rounds" in wk.championship_note
    ins = consistent(eng)
    assert any(n.kind == "not_counted" for n in ins.notes)


def test_successor_commences_and_fixes_the_boundary(world):
    eng, op, w = world["engine"], world["op"], world["w"]
    world["add"](("R4", 3, None), ("R5", 4, None))
    for k in ("R4", "R5"):
        finalise(eng, op, w[k])
    with transaction(eng) as conn:
        fixed = conn.execute(sa.text("SELECT boundary_fixed_at FROM app.championships "
                                     "WHERE display_name = :n"), {"n": A}).scalar()  # fmt: skip
    assert fixed is not None and board(eng, B).status == "completed"
    consistent(eng)


def snapshot_b(eng):
    b = board(eng, B)
    return (b.version, b.status, b.counted_rounds, b.rows, b.champions)


def test_historical_invalidation_after_commencement_d30a(world, monkeypatch):
    eng, own, op, w, u, nm = (world[k] for k in ("engine", "own", "op", "w", "u", "names"))
    b_before = snapshot_b(eng)
    # a failure inside championship processing rolls back the whole re-finalisation
    real = ch._refresh

    def boom(*a, **k):
        raise RuntimeError("injected")

    reopen_correct(
        eng, own, op, w["R1"], [co.CorrectionInput(f, "CANC") for f in w["R1"]["fixtures"][:6]]
    )
    monkeypatch.setattr(ch, "_refresh", boom)
    with pytest.raises(RuntimeError, match="injected"):
        finalise(eng, fresh(eng, op), w["R1"])
    monkeypatch.setattr(ch, "_refresh", real)
    assert role(eng, w["R1"]) == "counted" and board(eng).under_review  # nothing changed
    finalise(eng, fresh(eng, op), w["R1"])  # the retry succeeds
    # R1 void: A's own not_counted member R2 takes the freed slot (spec §23.5 rule 4)
    assert (role(eng, w["R1"]), role(eng, w["R2"])) == ("void", "counted")
    b = board(eng)
    assert (b.status, b.counted_rounds) == ("completed", 2) and b.disclosure is not None
    assert champions(eng) == {nm[u[2]]}  # historical winner change: u0 lost R1
    # R3 invalidated too: A stays completed with one counted round (D-30a)
    invalidate(eng, own, op, w["R3"])
    b = board(eng)
    assert (b.status, b.counted_rounds) == ("completed", 1)
    assert b.corrected_with_fewer_rounds and "corrected after completion" in b.disclosure
    assert b.no_champion and b.champions == ()  # nobody recovered in R2
    assert snapshot_b(eng) == b_before  # the successor is untouched
    ins = consistent(eng)
    assert any(n.kind == "historical_correction" for n in ins.notes)
    # R2 invalidated as well: no counted round left; still completed, no standings
    invalidate(eng, own, op, w["R2"])
    b = board(eng)
    assert (b.status, b.counted_rounds, b.total, b.no_champion) == ("completed", 0, 0, True)
    assert snapshot_b(eng) == b_before
    consistent(eng)


def test_historical_restoration_into_free_capacity_then_zero_points(world):
    eng, own, op, w, u, nm = (world[k] for k in ("engine", "own", "op", "w", "u", "names"))
    b_before = snapshot_b(eng)
    restore(eng, own, op, w["R3"])
    assert role(eng, w["R3"]) == "counted"
    b = board(eng)
    assert (b.status, b.counted_rounds) == ("completed", 1) and champions(eng) == {nm[u[2]]}
    # valid-to-valid correction: nobody recovers any more, so there is no champion
    correct_all(eng, own, op, w["R3"], lambda i: (2, 2))
    b = board(eng)
    assert b.no_champion and {r.points for r in b.rows} == {0} and b.total == 5
    assert snapshot_b(eng) == b_before
    with transaction(eng) as conn:
        causes = conn.execute(sa.text(
            "SELECT v.cause FROM app.championship_versions v JOIN app.championships c "
            "ON c.id = v.championship_id WHERE c.display_name = :n ORDER BY v.version"),
            {"n": A}).scalars().all()  # fmt: skip
    assert causes[-2:] == ["round_restored", "round_republished"]
    assert "round_invalidated" in causes
    consistent(eng)


def test_operator_invalidation_cannot_be_restored(world):
    eng, own, op, w = world["engine"], world["own"], world["op"], world["w"]
    o = fresh(eng, own)
    imp = co.preview_reopen(eng, o, w["R5"]["round"])
    co.reopen_round(eng, o, w["R5"]["round"], reason="ruling", evidence="league statement",
                    confirmation=imp.token)  # fmt: skip
    p = fresh(eng, op)
    imp = co.preview_invalidation(eng, p, w["R5"]["round"], reason="abandoned weekend")
    co.invalidate_round(eng, p, w["R5"]["round"], reason="abandoned weekend",
                        confirmation=imp.token)  # fmt: skip
    finalise(eng, fresh(eng, op), w["R5"])
    b = board(eng, B)
    assert role(eng, w["R5"]) == "void" and (b.status, b.counted_rounds) == ("in_progress", 1)
    assert lb.weekly_board(eng, w["R5"]["round"], include_development=True).void_basis == \
        "operator"  # fmt: skip
    # a later correction making the matches played does not restore it (6C.4)
    restore(eng, own, op, w["R5"])
    assert role(eng, w["R5"]) == "void" and board(eng, B).counted_rounds == 1
    # a replacement round completes B
    world["add"](("R6", 5, 0))
    finalise(eng, op, w["R6"])
    b = board(eng, B)
    assert (b.status, b.counted_rounds) == ("completed", 2)
    assert len(lb.championship_list(eng, stream="development", include_development=True)) == 2
    consistent(eng)


def test_privacy_across_corrected_versions_and_read_only_services(world, monkeypatch):
    """Retroactive anonymity applies to every published version (names are never
    stored in standings); payloads carry no identifiers or emails; development
    championships are hidden from public reads; reads write nothing and never
    construct a football provider client."""
    import dataclasses
    import re

    from diski9.backend.auth import accounts
    from diski9.backend.services.common import NotFound

    eng, u = world["engine"], world["u"]
    with transaction(eng) as conn:
        alias = conn.execute(sa.text("SELECT anonymous_alias FROM app.profiles WHERE user_id=:u"),
                             {"u": u[3]}).scalar_one()  # fmt: skip
        accounts.set_privacy(conn, u[3], "anonymous", retroactive=True)
    built = []
    import diski9.api_football.client as provider

    monkeypatch.setattr(provider.ApiFootballClient, "__init__",
                        lambda *a, **k: built.append(1) or None)  # fmt: skip
    before = counts(eng)
    versions = lb.championship_versions_list(eng, stream="development", name=B,
                                             include_development=True)  # fmt: skip
    boards = [board(eng, B, version=v.version) for v in versions]
    boards.append(board(eng, B, viewer=principal(eng, user_id=u[3])))
    mine = lb.my_round_result(eng, principal(eng, user_id=u[3]), world["w"]["R4"]["round"],
                              include_development=True)  # fmt: skip
    assert counts(eng) == before and built == []
    named = [b for b in boards if b.total]
    assert named and all(alias in [r.name for r in b.rows] for b in named)
    assert all(world["names"][u[3]] not in [r.name for r in b.rows] for b in named)
    uuid_re = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    for b in boards:
        text = repr(dataclasses.asdict(b))
        assert not uuid_re.search(text) and "@" not in text
    assert mine.weekly_points == 150 and mine.counts_toward_championship
    with pytest.raises(NotFound):
        lb.championship_board(eng, stream="development")  # public reads
    with pytest.raises(NotFound):
        lb.championship_versions_list(eng, stream="development", name=B)
    assert (
        lb.my_round_result(eng, GUEST, world["w"]["R4"]["round"], include_development=True) is None
    )  # guests: nothing personal


def test_restart_and_repeated_processing_change_nothing(world, pg_url):
    eng = world["engine"]
    before = counts(eng)
    eng.dispose()  # a fresh pool, as after an application restart
    with transaction(eng) as conn:
        out = ch.process_stream(conn, "development")
    assert out.versions == 0 and out.changes == () and out.assigned == 0
    assert counts(eng) == before
    consistent(eng)
