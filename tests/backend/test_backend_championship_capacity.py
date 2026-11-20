"""Phase 6C.5 Stage D: corrections interacting with reserved slots, pending
assignments, restoration capacity and rollover; concurrent corrections and
restorations (real PostgreSQL, three-round championships for this database).

R1..R8 are published together. A = R1, R2, R3 (R3 unresolved, reserving the last
slot); R4..R8 wait. R4 finalises first (out of order). R1 is invalidated: R4 takes
the freed slot. R1 is restored while R3 still reserves the last slot: not counted.
R3 finalises void: the restored R1 takes the slot before any new round; A completes
and R5 starts B (R6, R7 join; R8 waits). R6 and R7 are void, R8 joins; R6 and R7
are restored concurrently with one slot left; R5 and R8 are then invalidated
concurrently with stream processing and reads."""

from __future__ import annotations

import threading

import pytest
import sqlalchemy as sa
from champ_helpers import (
    WIN,
    build,
    drop,
    finalise,
    fresh,
    invalidate,
    isolated_engine,
    lose,
    operator,
    owner,
    played,
    prepare,
    reopen_correct,
    set_required,
    users,
    void_majority,
    winner,
)

from diski9.backend.db import transaction
from diski9.backend.services import championships as ch
from diski9.backend.services import corrections as co
from diski9.backend.services import leaderboards as lb

DB = "diski9_champ_cap_test"
CODES = [f"R{i}" for i in range(1, 9)]
WINNERS = {"R1": 0, "R2": 1, "R3": 2, "R4": 2, "R5": 3, "R6": 0, "R7": 1, "R8": 4}
VOID = {"R3", "R6", "R7"}
A, B = "Championship Nov-26", "Championship Nov-26 (2)"


@pytest.fixture(scope="module")
def cap(pg_url):
    eng, _ = isolated_engine(pg_url, DB)
    set_required(eng, 3)
    op, own = operator(eng), owner(eng)
    u = users(eng, 5)
    plan = [[(u[i], WIN if i == WINNERS[c] else lose(i)) for i in range(5)] for c in CODES]
    made = build(eng, plan)
    prepare(eng, op, made, [void_majority if c in VOID else winner for c in CODES])
    w = dict(zip(CODES, made, strict=True))
    with transaction(eng) as conn:
        for c in CODES:
            w[c]["code"] = conn.execute(sa.text("SELECT code FROM app.rounds WHERE id = :r"),
                                        {"r": w[c]["round"]}).scalar()  # fmt: skip
    yield {"engine": eng, "op": op, "own": own, "w": w}
    eng.dispose()
    drop(pg_url, DB)


def member(eng, w):
    with transaction(eng) as conn:
        row = conn.execute(sa.text(
            "SELECT c.display_name, cr.role FROM app.championship_rounds cr JOIN "
            "app.championships c ON c.id = cr.championship_id WHERE cr.round_id = :r"),
            {"r": w["round"]}).one_or_none()  # fmt: skip
    return None if row is None else tuple(row)


def consistent(eng):
    with transaction(eng) as conn:
        ins = ch.inspect_stream(conn, "development")
    assert ins.findings == (), ins.findings
    return ins


def board(eng, name=A):
    return lb.championship_board(eng, stream="development", name=name, include_development=True)


def restore_six(eng, own, op, w):
    reopen_correct(eng, own, op, w, played(w))


def test_waiting_round_finalised_first_is_published_but_not_assigned(cap):
    eng, op, w = cap["engine"], cap["op"], cap["w"]
    for k in ("R1", "R2"):
        finalise(eng, op, w[k])
    assert member(eng, w["R3"]) == (A, "pending") and member(eng, w["R4"]) is None
    wk = lb.weekly_board(eng, w["R4"]["round"], include_development=True)
    assert wk.championship_status == "pending_assignment" and wk.counts_toward_championship is None
    assert wk.championship_note == (f"The championship this round counts toward is confirmed "
                                    f"when Round {w['R3']['code']} is final.")  # fmt: skip
    finalise(eng, op, w["R4"])  # out of order: weekly results publish, membership waits
    wk = lb.weekly_board(eng, w["R4"]["round"], include_development=True)
    assert wk.state == "final" and member(eng, w["R4"]) is None
    ins = consistent(eng)
    assert {n.subject for n in ins.notes if n.kind == "pending_assignment"} >= {
        f"Round {w['R4']['code']}", f"Round {w['R5']['code']}"}  # fmt: skip


def test_invalidation_releases_the_slot_to_the_waiting_round(cap):
    eng, op, own, w = cap["engine"], cap["op"], cap["own"], cap["w"]
    invalidate(eng, own, op, w["R1"])
    assert member(eng, w["R1"]) == (A, "void")
    assert member(eng, w["R4"]) == (A, "counted")  # joined and counted at once
    assert member(eng, w["R5"]) is None  # A's commitment is full again (R2, R3, R4)
    b = board(eng)
    assert (b.status, b.counted_rounds) == ("in_progress", 2)
    consistent(eng)


def test_restoration_never_takes_a_reserved_slot(cap):
    eng, op, own, w = cap["engine"], cap["op"], cap["own"], cap["w"]
    restore_six(eng, own, op, w["R1"])
    finalise(eng, fresh(eng, op), w["R1"])
    assert member(eng, w["R1"]) == (A, "not_counted") and member(eng, w["R3"]) == (A, "pending")
    wk = lb.weekly_board(eng, w["R1"]["round"], include_development=True)
    assert wk.counts_toward_championship is False and "reserved" in wk.championship_note
    assert board(eng).counted_rounds == 2
    consistent(eng)


def test_released_reservation_goes_to_the_restored_round_before_rollover(cap):
    eng, op, w = cap["engine"], cap["op"], cap["w"]
    finalise(eng, op, w["R3"])  # void: releases the reserved slot
    assert member(eng, w["R3"]) == (A, "void") and member(eng, w["R1"]) == (A, "counted")
    a = board(eng)
    assert (a.status, a.counted_rounds) == ("completed", 3)
    # rollover in the same transaction: R5 starts B, R6 and R7 join, R8 waits
    assert [member(eng, w[k]) for k in ("R5", "R6", "R7")] == [(B, "pending")] * 3
    assert member(eng, w["R8"]) is None
    consistent(eng)


def test_concurrent_restorations_never_exceed_capacity(cap):
    eng, op, own, w = cap["engine"], cap["op"], cap["own"], cap["w"]
    for k in ("R5", "R6", "R7"):
        finalise(eng, op, w[k])
    assert member(eng, w["R8"]) == (B, "pending")  # R6, R7 void: R8 joins
    finalise(eng, op, w["R8"])
    assert board(eng, B).counted_rounds == 2  # one slot left
    for k in ("R6", "R7"):
        restore_six(eng, own, op, w[k])
    errors, seen, stop = [], [], threading.Event()

    def fin(k):
        try:
            finalise(eng, fresh(eng, op), w[k])
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    def reader():
        while not stop.is_set():
            try:
                b = board(eng, B)
                seen.append((b.version, b.counted_rounds, b.total))
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

    readers = [threading.Thread(target=reader) for _ in range(2)]
    for t in readers:
        t.start()
    threads = [threading.Thread(target=fin, args=(k,)) for k in ("R6", "R7")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    for t in readers:
        t.join()
    assert errors == []
    roles = sorted(member(eng, w[k])[1] for k in ("R6", "R7"))
    assert roles == ["counted", "not_counted"]  # exactly one took the last slot
    b = board(eng, B)
    assert (b.status, b.counted_rounds) == ("completed", 3)
    with transaction(eng) as conn:
        for version, counted, total in set(seen):  # readers never saw a mixed version
            row = conn.execute(sa.text(
                "SELECT v.counted_rounds, (SELECT count(*) FROM app.championship_standings s "
                "WHERE s.version_id = v.id) FROM app.championship_versions v JOIN "
                "app.championships c ON c.id = v.championship_id WHERE c.display_name = :n "
                "AND v.version = :v"), {"n": B, "v": version}).one()  # fmt: skip
            assert tuple(row) == (counted, total)
    consistent(eng)


def test_concurrent_invalidations_with_processing_and_no_deadlock(cap):
    eng, op, own, w = cap["engine"], cap["op"], cap["own"], cap["w"]
    loser = next(k for k in ("R6", "R7") if member(eng, w[k])[1] == "not_counted")
    for k in ("R5", "R8"):
        reopen_correct(eng, own, op, w[k], [co.CorrectionInput(f, "CANC")
                                            for f in w[k]["fixtures"][:6]])  # fmt: skip
    errors = []

    def fin(k):
        try:
            finalise(eng, fresh(eng, op), w[k])
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    def proc():
        for _ in range(4):
            try:
                with transaction(eng) as conn:
                    ch.process_stream(conn, "development")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

    threads = [threading.Thread(target=fin, args=(k,)) for k in ("R5", "R8")]
    threads += [threading.Thread(target=proc) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert member(eng, w["R5"])[1] == member(eng, w["R8"])[1] == "void"
    assert member(eng, w[loser]) == (B, "counted")  # reconsidered into the freed capacity
    b = board(eng, B)
    # B lost two counted rounds and had no successor: back in progress (L-33)
    assert (b.status, b.counted_rounds) == ("in_progress", 2) and b.reopened_after_completion
    assert board(eng).status == "completed"  # A (fixed) unaffected
    consistent(eng)
