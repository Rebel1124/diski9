"""Phase 6C.5 Stage C: a full development championship through the real services
(publication, lock, settlement, finalisation) on its own PostgreSQL database.

Fourteen rounds in deadline order: C1-C5, a practice round P, C6, a void round V,
C7-C12. Championship 1 = C1-C10 (P and V never count; more than ten weeks).
C11 is finalised before C10 and has to wait for its championship; C11 then starts
championship 2."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from champ_helpers import (
    REFUND,
    WIN,
    build,
    drop,
    finalise,
    isolated_engine,
    lose,
    operator,
    results,
    settle,
    users,
    void_majority,
    winner,
)
from svc_helpers import principal

from diski9.backend.db import transaction
from diski9.backend.db.schema import (
    championship_rounds,
    championship_standings,
    championship_versions,
    championships,
)
from diski9.backend.services import championships as ch
from diski9.backend.services import leaderboards as lb
from diski9.backend.services.common import NotFound
from diski9.challenge import scoring

DB = "diski9_champ_life_test"
WINNERS = {"C1": [0], "C2": [0, 1], "C3": [1], "C4": [2], "C5": [0], "C6": [3], "C7": [1],
           "C8": [0], "C9": [2], "C10": [4], "C11": [5], "C12": [0]}  # fmt: skip
ORDER = ["C1", "C2", "C3", "C4", "C5", "P", "C6", "V", "C7", "C8", "C9", "C10", "C11", "C12"]


@pytest.fixture(scope="module")
def life(pg_url):
    eng, _ = isolated_engine(pg_url, DB)
    op = operator(eng)
    u = users(eng, 9)  # u0-u5 regulars (u5 from C4), u6 one round, u7 practice only, u8 refund
    plan = []
    for name in ORDER:
        if name == "P":
            plan.append([(u[0], lose(1)), (u[1], lose(2)), (u[7], WIN)])
            continue
        if name == "V":
            plan.append([(u[i], lose(i)) for i in range(5)])
            continue
        k = int(name[1:])
        players = [0, 1, 2, 3, 4] + ([5] if k >= 4 else []) + ([6] if k == 2 else [])
        entries = [(u[i], WIN if i in WINNERS[name] else lose(i)) for i in players]
        if k == 3:
            entries.append((u[8], REFUND))  # all nine predictions void: refunded
        plan.append(entries)
    made = build(eng, plan)
    w = dict(zip(ORDER, made, strict=True))
    for name in ORDER:
        results(eng, op, w[name], void_majority if name == "V" else winner)
    for name in ORDER:
        settle(eng, op, w[name])
    state = {"engine": eng, "op": op, "users": u, "w": w}
    yield state
    eng.dispose()
    drop(pg_url, DB)


def membership(eng):
    with transaction(eng) as conn:
        rows = conn.execute(
            sa.select(championships.c.display_name, championship_rounds.c.round_id,
                      championship_rounds.c.role, championship_rounds.c.slot)
            .select_from(championship_rounds.join(
                championships, championships.c.id == championship_rounds.c.championship_id))
        ).all()  # fmt: skip
    return {r.round_id: (r.display_name, r.role, r.slot) for r in rows}


def champ(eng, name):
    with transaction(eng) as conn:
        return conn.execute(sa.select(championships).where(
            championships.c.display_name == name)).one()  # fmt: skip


def test_rounds_join_at_lock_while_slots_remain_and_later_rounds_wait(life):
    eng, w = life["engine"], life["w"]
    m = membership(eng)
    # P became practice at its lock and released its slot, so C9 joined; V (locked,
    # competitive, unresolved) still reserves the tenth slot: C10, C11 and C12 wait
    assert {k for k in ORDER if w[k]["round"] in m} == set(ORDER[:11])
    assert m[w["P"]["round"]][1] == "practice" and m[w["V"]["round"]][1] == "pending"
    (c,) = {v[0] for v in m.values()}
    assert c == "Championship Nov-26"
    board = lb.weekly_board(eng, w["C11"]["round"], include_development=True)
    assert board.championship is None and board.championship_status == "pending_assignment"


def test_finalising_in_order_completes_after_ten_valid_rounds(life):
    eng, op, w = life["engine"], life["op"], life["w"]
    for name in ["C1", "C2", "C3", "C4", "C5", "P", "C6", "C7", "C8", "C9"]:
        finalise(eng, op, w[name])
    assert w["C10"]["round"] not in membership(eng)  # V still reserves the last slot
    finalise(eng, op, w["V"])  # void: the slot is released and C10 joins (pending)
    c1 = champ(eng, "Championship Nov-26")
    assert c1.counted_rounds == 9 and c1.status == "in_progress"  # P and V never count
    m = membership(eng)
    assert m[w["V"]["round"]][1] == "void" and m[w["P"]["round"]][1] == "practice"
    assert m[w["C10"]["round"]][1] == "pending"
    # C11 finalises before C10: its weekly result is published, its championship waits
    finalise(eng, op, w["C11"])
    assert w["C11"]["round"] not in membership(eng)
    b11 = lb.weekly_board(eng, w["C11"]["round"], include_development=True)
    assert b11.state == "final" and b11.championship_status == "pending_assignment"
    assert champ(eng, "Championship Nov-26").counted_rounds == 9
    # C10 completes championship 1; C11 then starts championship 2 in the same transaction
    finalise(eng, op, w["C10"])
    c1 = champ(eng, "Championship Nov-26")
    assert (c1.status, c1.counted_rounds) == ("completed", 10)
    assert c1.completed_at is not None and c1.boundary_fixed_at is not None
    m = membership(eng)
    assert m[w["C11"]["round"]][:2] == ("Championship Nov-26 (2)", "counted")
    counted = [w[k]["round"] for k in ORDER if k not in ("P", "V", "C11", "C12")]
    assert [m[r][2] for r in counted] == list(range(1, 11))  # slots in deadline order
    finalise(eng, op, w["C12"])
    c2 = champ(eng, "Championship Nov-26 (2)")
    assert (c2.status, c2.counted_rounds) == ("in_progress", 2)
    with transaction(eng) as conn:
        assert ch.verify_stream(conn, "development") == []


def standings(eng, name):
    with transaction(eng) as conn:
        c = conn.execute(sa.select(championships).where(
            championships.c.display_name == name)).one()  # fmt: skip
        v = conn.execute(sa.select(championship_versions).where(
            championship_versions.c.championship_id == c.id,
            championship_versions.c.version == c.current_version)).one()  # fmt: skip
        rows = conn.execute(sa.select(championship_standings).where(
            championship_standings.c.version_id == v.id)
            .order_by(championship_standings.c.display_order)).all()  # fmt: skip
    return v, {r.user_id: r for r in rows}


def test_championship_standings_and_champion(life):
    eng, u = life["engine"], life["users"]
    v, rows = standings(eng, "Championship Nov-26")
    assert v.status == "completed" and v.counted_rounds == 10 and v.champion_count == 1
    # u0 won C1, C2 (shared), C5 and C8: 4 x 150
    assert (rows[u[0]].rank, rows[u[0]].points, rows[u[0]].recoveries) == (1, 600, 4)
    assert rows[u[0]].qualifying_top10 == 4
    assert rows[u[1]].points == 450 and rows[u[1]].rank == 2  # C2 (shared), C3, C7
    assert rows[u[3]].points == rows[u[4]].points == 150 and rows[u[3]].rank == rows[u[4]].rank
    assert rows[u[5]].points == 0 and rows[u[5]].rounds_played == 7  # joined at C4
    assert rows[u[6]].rounds_played == 1 and rows[u[6]].points == 0  # one round only
    assert u[7] not in rows  # practice only
    assert u[8] not in rows  # refunded only
    assert rows[u[5]].rank == rows[u[6]].rank  # zero points, zero recoveries: shared
    # the second championship starts from zero: only C11 and C12 count
    v2, rows2 = standings(eng, "Championship Nov-26 (2)")
    assert rows2[u[0]].points == 150 and rows2[u[5]].points == 150
    assert rows2[u[0]].rounds_played == 2 and v2.champion_count == 0  # not completed


def test_versions_are_kept_and_reproducible(life):
    eng = life["engine"]
    with transaction(eng) as conn:
        c = conn.execute(sa.select(championships).where(
            championships.c.display_name == "Championship Nov-26")).one()  # fmt: skip
        vs = conn.execute(sa.select(championship_versions).where(
            championship_versions.c.championship_id == c.id)
            .order_by(championship_versions.c.version)).all()  # fmt: skip
    assert [v.version for v in vs] == list(range(1, len(vs) + 1)) == list(range(1, 12))
    assert vs[0].cause == "round_assigned" and vs[0].status == "upcoming"
    assert [v.counted_rounds for v in vs] == list(range(0, 11))
    assert len({v.content_hash for v in vs}) == len(vs)
    assert vs[-1].status == "completed" and vs[1].status == "in_progress"


def test_repeated_processing_and_restart_change_nothing(life, pg_url):
    from sqlalchemy.engine import make_url

    from diski9.backend.db import BackendDatabaseSettings, make_app_engine

    url = make_url(pg_url).set(database=DB).render_as_string(hide_password=False)
    again = make_app_engine(BackendDatabaseSettings(environment="test"), url=url)  # restart
    with transaction(again) as conn:
        before = conn.execute(sa.text("SELECT count(*) FROM app.championship_versions")).scalar()
        out = ch.process_stream(conn, "development")
        assert out.assigned == 0 and out.versions == 0 and out.created == ()
        assert conn.execute(sa.text("SELECT count(*) FROM app.championship_versions")
                            ).scalar() == before  # fmt: skip
    again.dispose()


def test_championship_board_reads(life):
    eng, u = life["engine"], life["users"]
    with pytest.raises(NotFound):
        lb.championship_board(eng, stream="development")  # hidden unless enabled
    beta = lb.championship_board(eng, stream="beta")
    assert beta.name is None and beta.rows == ()  # no development data in beta
    cur = lb.championship_board(eng, stream="development", include_development=True)
    assert cur.name == "Championship Nov-26 (2)" and cur.status == "in_progress"
    assert [s.name for s in cur.championships] == ["Championship Nov-26 (2)",
                                                   "Championship Nov-26"]  # fmt: skip
    me = principal(eng, user_id=u[5])
    pages = [lb.championship_board(eng, stream="development", name="Championship Nov-26",
                                   viewer=me, page=p, page_size=3, include_development=True)
             for p in (1, 2, 3)]  # fmt: skip
    b = pages[0]
    assert b.status == "completed" and b.counted_rounds == 10 and b.champions
    assert not b.no_champion and not b.under_review and b.total == 7 and b.pages == 3
    flat = [r for p in pages for r in p.rows]
    assert [r.position for r in flat] == sorted(r.position for r in flat)
    assert flat[0].points == 600 and str(flat[0].recovery_rate) == "0.4000"  # 4 of 10
    assert b.me is not None and b.me.is_me and b.me_status == "ranked"
    assert b.me.points == 0 and b.me_page in (2, 3)  # bottom (shared) rank
    for who, status in ((u[7], "practice_only"), (u[8], "refunded_only")):
        x = lb.championship_board(
            eng,
            stream="development",
            name="Championship Nov-26",
            viewer=principal(eng, user_id=who),
            include_development=True,
        )
        assert x.me is None and x.me_status == status
    outsider = principal(eng, role="operator")
    assert (
        lb.championship_board(
            eng, stream="development", viewer=outsider, include_development=True
        ).me_status
        == "not_entered"
    )
    guest = lb.championship_board(eng, stream="development", include_development=True)
    assert guest.me is None and guest.me_status is None
    text = repr(pages)
    assert not any(str(x) in text for x in u) and "@" not in text
    with pytest.raises(NotFound):
        lb.championship_board(eng, stream="development", name="Championship Jan-99",
                              include_development=True)  # fmt: skip
    wb = lb.weekly_board(eng, life["w"]["C3"]["round"], include_development=True)
    assert (wb.championship, wb.championship_status) == ("Championship Nov-26", "assigned")
    wp = lb.weekly_board(eng, life["w"]["P"]["round"], include_development=True)
    assert wp.championship_status == "practice"


def test_standings_equal_a_recomputation_with_the_engine(life):
    eng = life["engine"]
    with transaction(eng) as conn:
        c = conn.execute(sa.select(championships).where(
            championships.c.display_name == "Championship Nov-26")).one()  # fmt: skip
        sets = conn.execute(sa.text(
            "SELECT cr.round_id, (SELECT id FROM app.score_sets s WHERE s.round_id = cr.round_id "
            "AND s.kind = 'championship' ORDER BY revision DESC LIMIT 1) AS sid, r.deadline_at "
            "FROM app.championship_rounds cr JOIN app.rounds r ON r.id = cr.round_id "
            "WHERE cr.championship_id = :c AND cr.role = 'counted' ORDER BY r.deadline_at"),
            {"c": c.id}).all()  # fmt: skip
        table, _ = ch.compute_standings(conn, c.id, [(s.round_id, s.sid) for s in sets])
    _, rows = standings(eng, "Championship Nov-26")
    assert {uuid.UUID(s.participant_id): (s.rank, s.points, s.rounds_entered, s.recoveries,
                                          s.qualifying_top10) for s in table.standings} == {
        k: (r.rank, r.points, r.rounds_played, r.recoveries, r.qualifying_top10)
        for k, r in rows.items()}  # fmt: skip
    assert isinstance(table, scoring.ChampionshipTable)
