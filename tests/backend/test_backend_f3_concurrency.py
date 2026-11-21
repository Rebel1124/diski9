"""Phase 6C.5 Stage F3: concurrent writers in *separate operating-system processes*
(own interpreter, own connection pool, as with several web or job workers), released
together by a barrier so collisions are forced rather than left to timing luck. On
its own PostgreSQL database with two-round championships.

* four processes finalise the same round at once: one finalisation, one score set,
  one membership, one audit record; the others change nothing;
* two rounds compete for the last slot of a championship: the earlier deadline takes
  it, the later one starts the next championship, never a duplicate;
* repeated finalisation of a final round is a no-op;
* readers during a rollover finalisation always see complete standings of one
  published version (compared with the stored version, row by row).
"""

from __future__ import annotations

import multiprocessing as mp
import threading
from datetime import timedelta

import pytest
import sqlalchemy as sa
from champ_helpers import (
    WIN,
    build,
    drop,
    finalise,
    isolated_engine,
    lose,
    operator,
    prepare,
    set_required,
    users,
)

from diski9.backend.db import transaction
from diski9.backend.services import championships as ch
from diski9.backend.services import leaderboards as lb

DB = "diski9_f3_concurrency_test"


def _finalise_in_process(url, round_id, barrier, results):
    """Child process: its own engine and operator; finalise after the barrier."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from uuid import UUID

    import champ_helpers as h

    from diski9.backend.db import BackendDatabaseSettings, make_app_engine
    from diski9.backend.services import corrections as co
    from diski9.backend.services import settlement as st

    round_id = UUID(round_id)  # the services take UUIDs (as every production caller passes)
    eng = make_app_engine(BackendDatabaseSettings(environment="test", lock_timeout_ms=10000),
                          url=url)  # fmt: skip
    try:
        op = h.operator(eng)
        with eng.begin() as conn:
            row = conn.execute(sa.text("SELECT * FROM app.rounds WHERE id = :r"),
                               {"r": round_id}).one()  # fmt: skip
            earliest = st.earliest_finalisation(conn, row)
        barrier.wait(timeout=60)
        out = co.finalise_round(eng, op, round_id, as_of=earliest)
        results.put(("ok", bool(out.finalised), str(out.reason or "")))
    except Exception as exc:  # noqa: BLE001
        import traceback

        results.put(("error", False, repr(exc)[:300] + "\n" + traceback.format_exc()[-3000:]))
    finally:
        eng.dispose()


def _race(url, round_ids):
    ctx = mp.get_context("spawn")
    barrier, results = ctx.Barrier(len(round_ids)), ctx.Queue()
    procs = [ctx.Process(target=_finalise_in_process, args=(url, str(r), barrier, results))
             for r in round_ids]  # fmt: skip
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=180)
        assert p.exitcode == 0
    return [results.get(timeout=5) for _ in procs]


@pytest.fixture(scope="module")
def world(pg_url):
    eng, url = isolated_engine(pg_url, DB)
    set_required(eng, 2)
    op = operator(eng)
    u = users(eng, 6)
    five = range(5)
    plan = [[(u[i], WIN if i == k else lose(i)) for i in five] for k in range(5)]
    made = build(eng, plan, cutoff_after=timedelta(seconds=4))
    prepare(eng, op, made)
    yield {"engine": eng, "url": url, "op": op, "w": made}
    eng.dispose()
    drop(pg_url, DB)


def _one(conn, sql, **params):
    return conn.execute(sa.text(sql), params).scalar()


def test_four_processes_finalise_the_same_round_once(world):
    eng, w = world["engine"], world["w"][0]
    results = _race(world["url"], [w["round"]] * 4)
    # exactly one process finalised it; the others were refused cleanly (the round
    # was no longer settling when they obtained its lock), never an unexpected error
    assert sum(1 for r in results if r[1]) == 1, results
    others = [r for r in results if not r[1]]
    assert all("Only a settling round can be finalised" in r[2] for r in others), results
    with transaction(eng) as conn:
        assert _one(conn, "SELECT status FROM app.rounds WHERE id = :r", r=w["round"]) == "final"
        assert _one(conn, "SELECT count(*) FROM app.score_sets WHERE round_id = :r",
                    r=w["round"]) == 1  # fmt: skip
        assert _one(conn, "SELECT count(*) FROM app.championship_rounds WHERE round_id = :r",
                    r=w["round"]) == 1  # fmt: skip
        assert _one(conn, "SELECT count(*) FROM app.audit_log WHERE action = 'round.finalise' "
                    "AND target_id = :r", r=str(w["round"])) == 1  # fmt: skip
        assert ch.verify_stream(conn, "development") == []


def test_repeated_finalisation_is_a_no_op(world):
    eng, op, w = world["engine"], world["op"], world["w"][0]
    with transaction(eng) as conn:
        before = (_one(conn, "SELECT count(*) FROM app.score_sets"),
                  _one(conn, "SELECT count(*) FROM app.championship_versions"),
                  _one(conn, "SELECT count(*) FROM app.audit_log"))  # fmt: skip
    from diski9.backend.services.corrections import CorrectionRefused

    with pytest.raises(CorrectionRefused, match="Only a settling round"):
        finalise(eng, op, w)
    with transaction(eng) as conn:
        after = (_one(conn, "SELECT count(*) FROM app.score_sets"),
                 _one(conn, "SELECT count(*) FROM app.championship_versions"),
                 _one(conn, "SELECT count(*) FROM app.audit_log"))  # fmt: skip
    assert after == before


def test_two_rounds_racing_for_the_last_slot(world):
    """R1 is counted (1 of 2). R2 (earlier deadline) and R3 finalise at the same
    instant in two processes: R2 completes the championship, R3 starts the next."""
    eng, w = world["engine"], world["w"]
    results = _race(world["url"], [w[1]["round"], w[2]["round"]])
    assert [r for r in results if r[0] == "error"] == [] and all(r[1] for r in results)
    with transaction(eng) as conn:
        rows = conn.execute(sa.text(
            "SELECT c.ordinal, cr.round_id, cr.role FROM app.championship_rounds cr JOIN "
            "app.championships c ON c.id = cr.championship_id ORDER BY c.ordinal")).all()  # fmt: skip
        by_round = {r.round_id: r.ordinal for r in rows}
        assert by_round[w[0]["round"]] == by_round[w[1]["round"]] == 1
        assert by_round[w[2]["round"]] == 2
        assert _one(conn, "SELECT count(*) FROM app.championships") == len(
            set(conn.execute(sa.text("SELECT display_name FROM app.championships")).scalars())
        )
        assert _one(conn, "SELECT status FROM app.championships WHERE ordinal = 1") == (
            "completed")  # fmt: skip
        assert ch.verify_stream(conn, "development") == []


def test_readers_see_complete_versions_during_a_rollover_finalisation(world):
    """Threads read the current championship board while another process finalises
    R4 (the second round of championship 2, completing it) and R5 (rollover)."""
    eng, w = world["engine"], world["w"]
    stop, bad, reads = threading.Event(), [], []

    def stored(version_id):
        with transaction(eng) as conn:
            return conn.execute(sa.text(
                "SELECT rank, points FROM app.championship_standings WHERE version_id = :v "
                "ORDER BY display_order LIMIT 50"), {"v": version_id}).all()  # fmt: skip

    def reader():
        while not stop.is_set():
            names = lb.championship_list(eng, stream="development", include_development=True)
            for c in names:
                b = lb.championship_board(eng, stream="development", name=c.name,
                                          include_development=True)  # fmt: skip
                if b.version is None:
                    continue
                with transaction(eng) as conn:
                    vid = _one(
                        conn,
                        "SELECT v.id FROM app.championship_versions v JOIN "
                        "app.championships c ON c.id = v.championship_id WHERE "
                        "c.display_name = :n AND v.version = :v",
                        n=c.name,
                        v=b.version,
                    )
                want = [(r.rank, r.points) for r in stored(vid)]
                got = [(r.position, r.points) for r in b.rows]
                reads.append(1)
                if want != got:
                    bad.append((c.name, b.version))

    ts = [threading.Thread(target=reader) for _ in range(4)]
    for t in ts:
        t.start()
    try:
        for k in (3, 4):
            res = _race(world["url"], [w[k]["round"]])
            assert res[0][0] == "ok" and res[0][1], res
    finally:
        stop.set()
        for t in ts:
            t.join()
    assert reads and bad == []
    with transaction(eng) as conn:
        assert ch.verify_stream(conn, "development") == []
        assert (
            _one(
                conn,
                "SELECT count(*) FROM (SELECT round_id, kind, revision FROM "
                "app.score_sets GROUP BY 1, 2, 3 HAVING count(*) > 1) d",
            )
            == 0
        )


DB2 = "diski9_f3_backlog_test"


def test_one_pass_creating_and_filling_championships_with_final_waiting_rounds(pg_url):
    """F3 defect: rounds that finalise while an earlier round holds the last slot wait
    unassigned. When that round finalises, one processing pass assigns the backlog:
    it fills a new championship with already-final rounds (fixing its boundary) and
    creates the next one. The boundary update used the new championship's placeholder
    key ("new", 0) before it was inserted, so the finalisation failed every time."""
    eng, _ = isolated_engine(pg_url, DB2)
    try:
        set_required(eng, 2)
        op = operator(eng)
        u = users(eng, 6)
        plan = [[(u[i], WIN if i == k else lose(i)) for i in range(5)] for k in range(5)]
        made = build(eng, plan, cutoff_after=timedelta(seconds=4))
        prepare(eng, op, made)
        for w in made[2:]:  # R3-R5 finalise first: they wait (R1 and R2 reserve champ 1)
            finalise(eng, op, w)
        with transaction(eng) as conn:
            assert _one(conn, "SELECT count(*) FROM app.championships") == 1
        finalise(eng, op, made[0])
        finalise(eng, op, made[1])  # the pass assigns R3, R4 (champ 2 full) and R5 (champ 3)
        with transaction(eng) as conn:
            rows = conn.execute(sa.text(
                "SELECT c.ordinal, c.status, c.boundary_fixed_at IS NOT NULL AS fixed, "
                "count(cr.round_id) AS n FROM app.championships c LEFT JOIN "
                "app.championship_rounds cr ON cr.championship_id = c.id "
                "GROUP BY c.id ORDER BY c.ordinal")).all()  # fmt: skip
            assert [(r.ordinal, r.status, r.fixed, r.n) for r in rows] == [
                (1, "completed", True, 2),
                (2, "completed", True, 2),
                (3, "in_progress", False, 1),
            ]
            assert ch.verify_stream(conn, "development") == []
    finally:
        eng.dispose()
        drop(pg_url, DB2)
