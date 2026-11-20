"""Phase 6C.5 Stage C: championship edge cases on their own PostgreSQL database,
with two-round championships (``rounds_per_championship`` = 2 for this database
only) so that many lifecycle situations fit in one run.

R1 (practice, published 31 Oct 23:30 SAST) -> names championship 1 "Oct-26";
R2, R3 complete it. R4 (published 1 Nov 00:30 SAST) names championship 2
"Nov-26"; R4, R5 everyone loses (no champion). R6, R7 joint champions
("Nov-26 (2)"). R8 valid, R9 void, R10 finalised first: waits for R9, then
completes championship 4. R11-R13 for concurrency and failure injection."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

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
    results,
    settle,
    users,
    void_majority,
    winner,
)

from diski9.backend.db import transaction
from diski9.backend.db.schema import championship_rounds, championships, score_sets
from diski9.backend.services import championships as ch
from diski9.backend.services import leaderboards as lb

DB = "diski9_champ_edge_test"
NAMES = [f"R{i}" for i in range(1, 14)]


@pytest.fixture(scope="module")
def edge(pg_url):
    eng, _ = isolated_engine(pg_url, DB)
    with transaction(eng) as conn:
        conn.execute(
            sa.text(
                "UPDATE app.championship_series SET rounds_per_championship = 2 WHERE code = 'beta'"
            )
        )
    op = operator(eng)
    u = users(eng, 6)
    five = [0, 1, 2, 3, 4]

    def comp(winners):
        return [(u[i], WIN if i in winners else lose(i)) for i in five]

    plan = [
        [(u[0], WIN), (u[1], lose(1)), (u[2], lose(2))],  # R1 practice
        comp({0}),
        comp({1}),  # R2, R3
        comp(set()),
        comp(set()),  # R4, R5: nobody recovers
        comp({0, 1}),
        comp({0, 1}),  # R6, R7: joint champions
        comp({2}),
        comp({3}),
        comp({4}),  # R8, R9 (void), R10
        comp({0}),
        comp({1}),
        comp({2}),  # R11, R12, R13
    ]
    published = {0: datetime(2026, 10, 31, 21, 30, tzinfo=UTC),
                 3: datetime(2026, 10, 31, 22, 30, tzinfo=UTC)}  # fmt: skip
    made = build(eng, plan, published=published)
    w = dict(zip(NAMES, made, strict=True))
    for k in NAMES:
        results(eng, op, w[k], void_majority if k == "R9" else (
            (lambda i: "CANC" if i >= 9 else (2, 2)) if k in ("R4", "R5")  # every bucket loses
            else winner))  # fmt: skip
    for k in NAMES:
        settle(eng, op, w[k])
    yield {"engine": eng, "op": op, "users": u, "w": w}
    eng.dispose()
    drop(pg_url, DB)


def member(eng, rid):
    with transaction(eng) as conn:
        return conn.execute(
            sa.select(championships.c.display_name, championship_rounds.c.role)
            .select_from(championship_rounds.join(
                championships, championships.c.id == championship_rounds.c.championship_id))
            .where(championship_rounds.c.round_id == rid)
        ).one_or_none()  # fmt: skip


def champ(eng, name):
    with transaction(eng) as conn:
        return conn.execute(sa.select(championships).where(
            championships.c.display_name == name)).one()  # fmt: skip


def test_first_associated_practice_round_names_the_championship_in_sast(edge):
    eng, op, w = edge["engine"], edge["op"], edge["w"]
    assert tuple(member(eng, w["R1"]["round"])) == ("Championship Oct-26", "practice")
    for k in ("R1", "R2", "R3"):
        finalise(eng, op, w[k])
    c1 = champ(eng, "Championship Oct-26")
    assert c1.start_date.isoformat() == "2026-10-31"  # 21:30 UTC is 23:30 SAST
    assert (c1.status, c1.counted_rounds) == ("completed", 2)
    # R4 was published 22:30 UTC on 31 Oct = 1 Nov 00:30 SAST
    assert tuple(member(eng, w["R4"]["round"])) == ("Championship Nov-26", "pending")
    c2 = champ(eng, "Championship Nov-26")
    assert c2.start_date.isoformat() == "2026-11-01" and c1.boundary_fixed_at is not None


def test_no_champion_when_everyone_has_zero_points(edge):
    eng, op, w = edge["engine"], edge["op"], edge["w"]
    for k in ("R4", "R5"):
        finalise(eng, op, w[k])
    b = lb.championship_board(eng, stream="development", name="Championship Nov-26",
                              include_development=True)  # fmt: skip
    assert b.status == "completed" and b.no_champion and b.champions == ()
    assert {r.points for r in b.rows} == {0} and {r.position for r in b.rows} == {1}
    assert b.total == 5  # zero-point participants with valid entries stay listed


def test_joint_champions_and_same_month_suffix(edge):
    eng, op, w = edge["engine"], edge["op"], edge["w"]
    for k in ("R6", "R7"):
        finalise(eng, op, w[k])
    assert member(eng, w["R6"]["round"]).display_name == "Championship Nov-26 (2)"
    b = lb.championship_board(eng, stream="development", name="Championship Nov-26 (2)",
                              include_development=True)  # fmt: skip
    assert b.status == "completed" and len(b.champions) == 2
    assert [r.points for r in b.rows[:2]] == [300, 300] and b.rows[0].shared


def test_reserved_last_slot_and_a_later_round_finalising_first(edge):
    eng, op, w = edge["engine"], edge["op"], edge["w"]
    # R8 and R9 hold both slots of championship 4: R10 waits even when final first
    assert member(eng, w["R10"]["round"]) is None
    finalise(eng, op, w["R10"])
    assert member(eng, w["R10"]["round"]) is None
    with transaction(eng) as conn:
        assert (
            conn.execute(
                sa.select(sa.func.count())
                .select_from(score_sets)
                .where(score_sets.c.round_id == w["R10"]["round"])
            ).scalar_one()
            == 1
        )  # weekly published
    finalise(eng, op, w["R8"])
    assert member(eng, w["R10"]["round"]) is None  # R9 still unresolved
    finalise(eng, op, w["R9"])  # void: releases its slot; R10 joins and completes it
    assert tuple(member(eng, w["R9"]["round"]))[1] == "void"
    name, role = member(eng, w["R10"]["round"])
    c4 = champ(eng, name)
    assert role == "counted" and (c4.status, c4.counted_rounds) == ("completed", 2)
    assert member(eng, w["R11"]["round"]).display_name != name  # next championship


def test_concurrent_finalisation_and_processing_never_deadlock_or_duplicate(edge):
    eng, op, w = edge["engine"], edge["op"], edge["w"]
    errors = []

    def fin(k):
        try:
            finalise(eng, op, w[k])
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    def proc():
        for _ in range(5):
            try:
                with transaction(eng) as conn:
                    ch.process_stream(conn, "development")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

    threads = [threading.Thread(target=fin, args=(k,)) for k in ("R11", "R12")]
    threads += [threading.Thread(target=proc) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with transaction(eng) as conn:
        assert ch.verify_stream(conn, "development") == []
        n = conn.execute(sa.text("SELECT count(*) FROM app.championships")).scalar_one()
        assert n == len(set(conn.execute(sa.text(
            "SELECT display_name FROM app.championships")).scalars()))  # fmt: skip


def test_failure_rolls_back_weekly_and_championship_publication(edge, monkeypatch):
    eng, op, w = edge["engine"], edge["op"], edge["w"]
    before = member(eng, w["R13"]["round"])

    def boom(*a, **k):
        raise RuntimeError("injected championship failure")

    monkeypatch.setattr(ch, "_refresh", boom)
    with pytest.raises(RuntimeError, match="injected"):
        finalise(eng, op, w["R13"])
    with transaction(eng) as conn:
        status = conn.execute(sa.text("SELECT status FROM app.rounds WHERE id = :r"),
                              {"r": w["R13"]["round"]}).scalar_one()  # fmt: skip
        sets = conn.execute(sa.select(sa.func.count()).select_from(score_sets).where(
            score_sets.c.round_id == w["R13"]["round"])).scalar_one()  # fmt: skip
    assert status == "settling" and sets == 0 and member(eng, w["R13"]["round"]) == before
    monkeypatch.undo()
    finalise(eng, op, w["R13"])  # retry succeeds
    assert member(eng, w["R13"]["round"]).role == "counted"
    with transaction(eng) as conn:
        assert ch.verify_stream(conn, "development") == []


def test_reads_are_consistent_during_publication(edge):
    eng = edge["engine"]
    seen, errors = [], []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                b = lb.championship_board(eng, stream="development", include_development=True)
                seen.append((b.name, b.version, b.counted_rounds, b.total))
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    with transaction(eng) as conn:
        ch.process_stream(conn, "development")
    stop.set()
    for t in threads:
        t.join()
    assert errors == [] and seen
    with transaction(eng) as conn:
        for name, version, counted, total in set(seen):
            row = conn.execute(sa.text(
                "SELECT v.counted_rounds, (SELECT count(*) FROM app.championship_standings s "
                "WHERE s.version_id = v.id) FROM app.championship_versions v JOIN "
                "app.championships c ON c.id = v.championship_id WHERE c.display_name = :n "
                "AND v.version = :v"), {"n": name, "v": version}).one()  # fmt: skip
            assert tuple(row) == (counted, total)  # never a mixture of versions


def test_official_stream_is_gated_and_beta_untouched(edge):
    eng = edge["engine"]
    with transaction(eng) as conn:
        out = ch.process_stream(conn, "official")
        assert out.skipped and "official series" in out.skipped
        assert (
            conn.execute(
                sa.text("SELECT count(*) FROM app.championships WHERE stream <> 'development'")
            ).scalar()
            == 0
        )
        assert (
            conn.execute(
                sa.text("SELECT started_at FROM app.championship_series WHERE code='official'")
            ).scalar()
            is None
        )
    b = lb.championship_board(eng, stream="official")
    assert b.name is None and b.pending_assignment == 0
