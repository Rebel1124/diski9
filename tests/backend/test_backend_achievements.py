"""Phase 7 achievements against real PostgreSQL, through the real settlement,
finalisation, publication, reopening and correction services, on this module's
own database (two-round championships). The tests run in order as one story.

Viewer u0 (others enter ``lose(i)`` portfolios on fixtures 0..8):

* R1 competitive, X portfolio (4 Home, 3 Over 2.5, 2 Draws), every pick correct:
  Foundation, Balanced, Challenger, Goals Guru, Draw Dynamo.
* R2 competitive, Y portfolio (4 Home, 3 BTTS Yes, 2 Away), every pick correct:
  Foundation, Balanced, Challenger, BTTS Bonanza. Later invalidated (void), then
  restored while championship A is full (``not_counted``).
* R3 competitive, u0 loses: eligible, no badges (fills A while R2 is void).
* R4 practice, R5 void (D-32b), R6 competitive with u0 refunded (all nine void):
  nothing.
* R7 competitive, a Challenger pick void: Foundation and Balanced only.
* R8 competitive, u0 on fixtures 9..17, untouched by a later correction of
  fixture 0 (an entry settlement revision older than the republished score set).
* RB beta round on a3-432-v1 (stream isolation and the A3 binding).
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import sqlalchemy as sa
from champ_helpers import (
    REFUND,
    WIN,
    WINNER,
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
    settle,
    users,
    void_majority,
    winner,
)
from settle_helpers import provider_item, shifted
from svc_helpers import principal, wait_until

from diski9.backend.auth.permissions import GUEST
from diski9.backend.db import transaction
from diski9.backend.repositories import results as results_repo
from diski9.backend.services import achievements as ac
from diski9.backend.services import corrections as co
from diski9.backend.services import settlement as st
from diski9.backend.services.common import NotFound
from diski9.ingestion.results_fetch import canonical_hash, evidence_fields

DB = "diski9_achievements_test"
F, B, C = ac.Badge.FOUNDATION_FUNDI, ac.Badge.BALANCED_BRAWLER, ac.Badge.CHALLENGER_CHAMP
GG, BT, DD = ac.Badge.GOALS_GURU, ac.Badge.BTTS_BONANZA, ac.Badge.DRAW_DYNAMO

HOME4 = tuple((i, "1X2", "HOME") for i in range(4))
X = HOME4 + tuple((i, "OU25", "OVER_2_5") for i in (4, 5, 6)) + ((7, "1X2", "DRAW"),
                                                               (8, "1X2", "DRAW"))  # fmt: skip
Y = HOME4 + tuple((i, "BTTS", "BTTS_YES") for i in (4, 5, 6)) + ((7, "1X2", "AWAY"),
                                                                (8, "1X2", "AWAY"))  # fmt: skip


def res_x(i):  # home wins with 3+ goals, 2-1s, draws; fixtures 9..17 played
    return (3, 0) if i < 4 else (2, 1) if i < 7 else (1, 1) if i < 9 else (1, 0)


def res_y(i):  # home wins, 1-1s (both teams score), away wins
    return (2, 0) if i < 4 else (1, 1) if i < 7 else (0, 1) if i < 9 else (1, 0)


def res_partial(i):  # WIN wins everything except fixture 8 (cancelled: a void Challenger)
    return "CANC" if i >= 8 else WINNER[i]


def res_shift(i):  # fixtures 0..8 and 9..17 both follow the WINNER pattern
    return WINNER[i % 9]


@pytest.fixture(scope="module")
def world(pg_url):
    eng, _ = isolated_engine(pg_url, DB)
    set_required(eng, 2)
    yield {"engine": eng, "op": operator(eng), "own": owner(eng), "u": users(eng, 6), "w": {}}
    eng.dispose()
    drop(pg_url, DB)


def plan_for(world, mine, n=6):
    u = world["u"]
    return [(u[0], mine)] + [(u[i], lose(i)) for i in range(1, n)]


def viewer(world, i=0):
    return principal(world["engine"], user_id=world["u"][i])


def dev(world, i=0) -> ac.Achievements:
    return ac.my_achievements(world["engine"], viewer(world, i), stream="development",
                              include_development=True)  # fmt: skip


def counts(a) -> tuple:
    return tuple(a.counts[b] for b in ac.BADGES)


def badges(world, code, i=0, stream="development"):
    r = ac.my_round_badges(world["engine"], viewer(world, i), world["w"][code]["round"],
                           stream=stream, include_development=True)  # fmt: skip
    return None if r is None else set(r.badges)


def fresh_ops(world):
    eng = world["engine"]
    world["op"], world["own"] = fresh(eng, world["op"]), fresh(eng, world["own"])
    return world["op"], world["own"]


def table_counts(eng):
    with transaction(eng) as conn:
        return conn.execute(sa.text(
            "SELECT (SELECT count(*) FROM app.score_sets), (SELECT count(*) FROM "
            "app.entry_settlements), (SELECT count(*) FROM app.audit_log), (SELECT count(*) "
            "FROM app.domain_events)")).one()  # fmt: skip


def latest_set(eng, w):
    with transaction(eng) as conn:
        return conn.execute(sa.text(
            "SELECT revision, kind, run_id FROM app.score_sets WHERE round_id = :r "
            "ORDER BY revision DESC LIMIT 1"), {"r": w["round"]}).one()  # fmt: skip


def role(eng, w):
    with transaction(eng) as conn:
        return conn.execute(sa.text("SELECT role FROM app.championship_rounds WHERE round_id = :r"),
                            {"r": w["round"]}).scalar()  # fmt: skip


# ------------------------------------------------------------------ the story
def test_only_published_competitive_results_award_badges(world):
    eng, op = world["engine"], world["op"]
    r1, r2 = build(eng, [plan_for(world, X), plan_for(world, Y)], extra_outcomes=True)
    world["w"] |= {"R1": r1, "R2": r2}
    prepare(eng, op, [r1, r2], [res_x, res_y])
    # settled but provisional (not finalised, nothing published): nothing yet
    a = dev(world)
    assert counts(a) == (0,) * 6 and a.eligible_rounds == 0 and a.level is ac.Level.BEGINNER
    assert badges(world, "R1") is None
    finalise(eng, op, r1)
    finalise(eng, op, r2)
    before = table_counts(eng)
    a = dev(world)
    assert counts(a) == (2, 2, 2, 1, 1, 1) and a.total == 9 and a.eligible_rounds == 2
    assert a.level is ac.Level.SEMI_PRO and a.progress.next_level is ac.Level.PRO
    assert a.progress.missing == ac.BADGES  # every category still below 3
    assert badges(world, "R1") == {F, B, C, GG, DD} and badges(world, "R2") == {F, B, C, BT}
    assert [r.revision for r in a.rounds] == [1, 1]
    assert table_counts(eng) == before  # read-only: nothing written


def test_a_competitive_round_republished_as_void_loses_its_badges(world):
    eng = world["engine"]
    op, own = fresh_ops(world)
    invalidate(eng, own, op, world["w"]["R2"])
    s = latest_set(eng, world["w"]["R2"])
    assert (s.revision, s.kind) == (2, "void")  # the newer void publication wins
    a = dev(world)
    assert counts(a) == (1, 1, 1, 1, 0, 1) and a.level is ac.Level.BEGINNER
    assert a.progress.missing == (BT,)
    assert badges(world, "R2") is None


def test_a_round_that_does_not_count_for_its_championship_still_awards_badges(world):
    eng = world["engine"]
    op, own = fresh_ops(world)
    (r3,) = build(eng, [plan_for(world, lose(0))])
    world["w"]["R3"] = r3
    prepare(eng, op, [r3])
    finalise(eng, op, r3)  # fills championship A while R2 is void
    op, own = fresh_ops(world)
    restore(eng, own, op, world["w"]["R2"], res_y)  # valid again, A already full
    assert role(eng, world["w"]["R2"]) == "not_counted"  # D-2
    a = dev(world)
    assert counts(a) == (2, 2, 2, 1, 1, 1) and a.level is ac.Level.SEMI_PRO
    assert badges(world, "R2") == {F, B, C, BT} and badges(world, "R3") == set()
    assert a.eligible_rounds == 3  # R3 is eligible with no badges


def test_exclusions_partial_voids_and_accumulation_across_championships(world):
    eng = world["engine"]
    op, own = fresh_ops(world)
    u = world["u"]
    plans = [
        [(u[0], X), (u[1], lose(1)), (u[2], lose(2))],  # R4 practice
        plan_for(world, X),  # R5 void (D-32b)
        plan_for(world, REFUND),  # R6: u0 refunded, all nine void
        plan_for(world, WIN),  # R7: one Challenger pick void
        plan_for(world, shifted(9)),  # R8: u0 on fixtures 9..17
    ]
    made = build(eng, plans, extra_outcomes=True)
    world["w"] |= dict(zip(("R4", "R5", "R6", "R7", "R8"), made, strict=True))
    prepare(eng, op, made, [res_x, void_majority, winner, res_partial, res_shift])
    for w in made:
        finalise(eng, op, w)
    kinds = {k: latest_set(eng, world["w"][k]).kind for k in ("R4", "R5", "R6", "R7", "R8")}
    assert kinds == {"R4": "practice", "R5": "void", "R6": "championship",
                     "R7": "championship", "R8": "championship"}  # fmt: skip
    assert badges(world, "R4") is None and badges(world, "R5") is None
    assert badges(world, "R6") is None  # refunded entry: excluded (D-5)
    assert badges(world, "R7") == {F, B}  # the void Challenger pick cannot complete C
    assert badges(world, "R8") == {F, B, C}
    a = dev(world)
    assert counts(a) == (4, 4, 3, 1, 1, 1) and a.total == 14 and a.eligible_rounds == 5
    with transaction(eng) as conn:
        champs = conn.execute(sa.text(
            "SELECT DISTINCT c.display_name FROM app.championship_rounds cr JOIN "
            "app.championships c ON c.id = cr.championship_id WHERE cr.round_id = ANY(:r)"),
            {"r": [world["w"][k]["round"] for k in ("R1", "R7", "R8")]}).scalars().all()  # fmt: skip
    assert len(champs) >= 2  # one stream, several championships, no reset


def test_reopened_round_keeps_published_badges_until_republished(world):
    eng = world["engine"]
    op, own = fresh_ops(world)
    w = world["w"]["R1"]
    reopen_correct(eng, own, op, w, [co.CorrectionInput(w["fixtures"][7], "FT", 0, 1)])
    # under review: a provisional revision exists, but the published result still rules
    with transaction(eng) as conn:
        assert conn.execute(sa.text("SELECT status FROM app.rounds WHERE id = :r"),
                            {"r": w["round"]}).scalar() == "settling"  # fmt: skip
        newest = conn.execute(sa.text(
            "SELECT max(revision) FROM app.entry_settlements WHERE entry_id = :e"),
            {"e": w["entries"][0]}).scalar()  # fmt: skip
    assert newest >= 2
    a = dev(world)
    assert counts(a) == (4, 4, 3, 1, 1, 1) and a.level is ac.Level.SEMI_PRO
    assert badges(world, "R1") == {F, B, C, GG, DD}
    # republished: the lost draw removes Challenger and Draw Dynamo; the level drops
    finalise(eng, fresh(eng, op), w)
    a = dev(world)
    assert counts(a) == (4, 4, 2, 1, 1, 0) and a.level is ac.Level.BEGINNER
    assert badges(world, "R1") == {F, B, GG}
    # a further correction restores them, and the level with them
    op, own = fresh_ops(world)
    correct_all(eng, own, op, w, res_x)
    a = dev(world)
    assert counts(a) == (4, 4, 3, 1, 1, 1) and a.level is ac.Level.SEMI_PRO
    assert badges(world, "R1") == {F, B, C, GG, DD}
    assert next(r for r in a.rounds if r.round_id == w["round"]).revision == 3


def test_an_unchanged_entry_keeps_its_earlier_settlement_revision(world):
    eng = world["engine"]
    op, own = fresh_ops(world)
    w = world["w"]["R8"]
    reopen_correct(eng, own, op, w, [co.CorrectionInput(w["fixtures"][0], "FT", 0, 0)])
    finalise(eng, fresh(eng, op), w)
    s = latest_set(eng, w)
    with transaction(eng) as conn:
        mine = conn.execute(sa.text(
            "SELECT max(revision), max(run_id) FROM app.entry_settlements WHERE entry_id = :e"),
            {"e": w["entries"][0]}).one()  # fmt: skip
        others = conn.execute(sa.text(
            "SELECT max(revision) FROM app.entry_settlements WHERE entry_id = ANY(:e)"),
            {"e": w["entries"][1:]}).scalar()  # fmt: skip
    assert s.revision == 2 and others >= 2  # republished; another entry changed
    assert mine[0] == 1 and mine[1] < s.run_id  # u0 untouched: an earlier run's revision
    assert badges(world, "R8") == {F, B, C}
    assert next(r for r in dev(world).rounds if r.round_id == w["round"]).revision == 2


def test_streams_are_isolated_and_development_is_server_authorised(world):
    eng = world["engine"]
    op, own = fresh_ops(world)
    before = counts(dev(world))
    (rb,) = build(eng, [plan_for(world, Y)], development=False, extra_outcomes=True,
                  config_version="a3-432-v1", correction_window_hours=0)  # fmt: skip
    world["w"]["RB"] = rb
    at = rb["deadline"] + timedelta(milliseconds=1500)
    wait_until(eng, at)
    for i, fid in enumerate(rb["fixtures"]):  # a genuine round takes provider evidence
        item = provider_item(fid, "FT", ko=rb["deadline"] + timedelta(seconds=1),
                             h=res_y(i)[0], a=res_y(i)[1])  # fmt: skip
        with transaction(eng) as conn:
            results_repo.record_evidence(conn, source="api-football", fixture_id=fid,
                                         observed_at=at, raw=item, raw_hash=canonical_hash(item),
                                         fields=evidence_fields(item))  # fmt: skip
    settle(eng, op, rb)
    with transaction(eng) as conn:
        r = conn.execute(sa.text("SELECT * FROM app.rounds WHERE id = :r"),
                         {"r": rb["round"]}).one()  # fmt: skip
        wait_until(eng, st.earliest_finalisation(conn, r) + timedelta(milliseconds=50))
    assert co.finalise_round(eng, fresh(eng, op), rb["round"]).finalised  # real clock only
    beta = ac.my_achievements(eng, viewer(world))  # default stream: beta
    assert beta.stream == "beta" and counts(beta) == (1, 1, 1, 0, 1, 0)
    assert badges(world, "RB", stream="beta") == {F, B, C, BT}
    assert badges(world, "RB") is None  # a beta round is never development
    assert counts(dev(world)) == before  # development unaffected by beta
    off = ac.my_achievements(eng, viewer(world), stream="official")
    assert counts(off) == (0,) * 6 and off.eligible_rounds == 0 and off.level is ac.Level.BEGINNER
    # development needs the server's own setting; without it the stream does not exist
    with pytest.raises(NotFound):
        ac.my_achievements(eng, viewer(world), stream="development")
    with pytest.raises(NotFound):
        ac.my_round_badges(eng, viewer(world), world["w"]["R1"]["round"], stream="development")
    # bindings: historical broad60 rounds and the A3 beta round both evaluate
    with transaction(eng) as conn:
        cfg = dict(conn.execute(sa.text("SELECT id, config_version FROM app.rounds "
                                        "WHERE id IN (:a, :b)"),
                                {"a": world["w"]["R1"]["round"], "b": rb["round"]}).all())  # fmt: skip
    assert cfg == {world["w"]["R1"]["round"]: "broad60-432-v1", rb["round"]: "a3-432-v1"}


def test_privacy_guests_and_other_users(world):
    eng = world["engine"]
    rid = world["w"]["R1"]["round"]
    assert ac.my_achievements(eng, GUEST, stream="development", include_development=True) is None
    assert ac.my_achievements(eng, None) is None
    assert ac.my_round_badges(eng, GUEST, rid, stream="development",
                              include_development=True) is None  # fmt: skip
    # another participant sees only their own entries, never u0's badges
    other = dev(world, 3)
    entered = {world["w"][k]["round"] for k in ("R1", "R2", "R3", "R5", "R6", "R7", "R8")}
    assert {r.round_id for r in other.rounds} <= entered
    assert badges(world, "R1", i=3) == set()  # u3's own losing entry
    assert badges(world, "R4", i=3) is None  # u3 did not enter the practice round
    assert badges(world, "R1", i=3) != badges(world, "R1")


def test_a_malformed_authoritative_record_is_refused_not_shown_as_zero(world):
    eng = world["engine"]
    w = world["w"]["R8"]
    s = latest_set(eng, w)
    with transaction(eng) as conn:
        cur = conn.execute(sa.text(
            "SELECT * FROM app.entry_settlements WHERE entry_id = :e ORDER BY revision DESC "
            "LIMIT 1"), {"e": w["entries"][0]}).one()  # fmt: skip
        legs = dict(cur.legs)
        legs["legs"] = legs["legs"][:8]  # a prediction missing
        conn.execute(sa.text(
            "INSERT INTO app.entry_settlements (run_id, entry_id, submission_id, revision, "
            "gross, net, legs, basis, complete) VALUES (:run, :e, :s, :rev, :g, :n, "
            "CAST(:legs AS jsonb), :b, true)"),
            {"run": s.run_id, "e": w["entries"][0], "s": cur.submission_id,
             "rev": cur.revision + 1, "g": cur.gross, "n": cur.net,
             "legs": json.dumps(legs), "b": cur.basis})  # fmt: skip
    with pytest.raises(ac.AchievementIntegrityError) as e:
        dev(world)
    assert e.value.code == "achievement_integrity"
    with pytest.raises(ac.AchievementIntegrityError):
        badges(world, "R8")
    assert badges(world, "R1") == {F, B, C, GG, DD}  # other rounds unaffected
