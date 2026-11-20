# ruff: noqa: B023  (closures are called immediately inside each loop iteration)
"""Phase 6C.5 Stage D: timings of corrections and recalculation (real PostgreSQL).

Creates its own database ``diski9_perf6c5d_test`` with N participants entering
R development rounds (R >= 11, ten-round championships, so the eleventh round
starts the next championship). After every round is final it measures the
re-finalisation (settlement + weekly republication + championship processing)
of corrections through the real 6C.4 services:

* valid-to-valid correction of a counted round in the completed (historical)
  championship (whole round re-scored, ten-round standings rebuilt);
* invalidation of a counted round after the successor commenced (D-30a);
* restoration of that round into its own free capacity;
* invalidation of the open championship's only counted round and the processing
  of the pending assignments that follows;
* the integrity inspection (``competition verify``) and a repair preview and run
  of a tampered counter;
* standings reads running concurrently with a correction's re-finalisation.

    uv run python tools/phase6c5_perf_corrections.py URL N R

Results are measurements on this machine, not guarantees.
"""

from __future__ import annotations

import itertools
import statistics
import sys
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "backend"))

import sqlalchemy as sa  # noqa: E402


def ms(fn):
    t = time.perf_counter()
    value = fn()
    return value, (time.perf_counter() - t) * 1000


def main(url: str, n: int, r: int) -> None:
    import champ_helpers as h

    from diski9.backend.db import transaction
    from diski9.backend.repositories import accounts as accounts_repo
    from diski9.backend.services import championships as ch
    from diski9.backend.services import competition_ops as cops
    from diski9.backend.services import corrections as co
    from diski9.backend.services import leaderboards as lb

    name = "diski9_perf6c5d_test"
    eng, target = h.isolated_engine(url, name)
    op, own = h.operator(eng), h.owner(eng)
    counter = itertools.count(1)
    with transaction(eng) as conn:
        people = []
        for _ in range(n):
            k = next(counter)
            uid = accounts_repo.create_user(conn)
            accounts_repo.link_identity(conn, uid, "supabase", f"perf-{uuid.uuid4().hex}")
            accounts_repo.create_profile(conn, uid, f"perf{k:06d}", f"Anonymous {10_000_000 + k}")
            people.append(uid)
    print(f"=== {n} participants, {r} rounds ===", flush=True)
    t0 = time.perf_counter()
    plan = [[(u, h.WIN if (i + k) % 7 == 0 else h.lose(i)) for i, u in enumerate(people)]
            for k in range(r)]  # fmt: skip
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=6))
    h.prepare(eng, op, made)
    for w in made:
        h.finalise(eng, op, w)
    print(f"build, settle, finalise {r} rounds: {time.perf_counter() - t0:.0f} s", flush=True)

    def stage(label, fn):
        _, t = ms(fn)
        print(f"{label:62}: {t:7.0f} ms", flush=True)

    def refinalise(w):
        return lambda: h.finalise(eng, h.fresh(eng, op), w)

    hist, cur = made[0:10], made[10]
    # valid-to-valid correction in the historical championship (two results changed)
    h.reopen_correct(eng, own, op, hist[3], [co.CorrectionInput(f, "FT", 2, 2)
                                             for f in hist[3]["fixtures"][:2]])  # fmt: skip
    stage("re-finalisation, valid-to-valid (historical, 10 rounds)", refinalise(hist[3]))
    # D-30a: invalidation after the successor commenced
    h.reopen_correct(eng, own, op, hist[5], [co.CorrectionInput(f, "CANC")
                                             for f in hist[5]["fixtures"][:6]])  # fmt: skip
    stop, errors, read_ms = threading.Event(), [], []

    def reader():
        while not stop.is_set():
            t = time.perf_counter()
            try:
                lb.championship_board(eng, stream="development", name="Championship Nov-26",
                                      include_development=True)  # fmt: skip
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
            read_ms.append((time.perf_counter() - t) * 1000)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    stage("re-finalisation, valid-to-void (D-30a) with 4 reader threads", refinalise(hist[5]))
    stop.set()
    for t in threads:
        t.join()
    p95 = sorted(read_ms)[max(0, int(len(read_ms) * 0.95) - 1)] if read_ms else 0
    print(f"  reads during it: {len(read_ms)} reads, {len(errors)} errors, "
          f"median {statistics.median(read_ms):.1f} ms, p95 {p95:.1f} ms", flush=True)  # fmt: skip
    # restoration into the free slot
    h.reopen_correct(eng, own, op, hist[5], h.played(hist[5]))
    stage("re-finalisation, void-to-valid restoration (counted again)", refinalise(hist[5]))
    # the open championship's counted round invalidated (L-32): pending reprocessing
    h.reopen_correct(eng, own, op, cur, [co.CorrectionInput(f, "CANC")
                                         for f in cur["fixtures"][:6]])  # fmt: skip
    stage("re-finalisation, valid-to-void (active championship)", refinalise(cur))

    def process():
        with transaction(eng) as conn:
            return ch.process_stream(conn, "development")

    stage("stream processing with nothing to change", process)

    def verify():
        with transaction(eng) as conn:
            return ch.inspect_stream(conn, "development")

    ins, t = ms(verify)
    print(f"{'competition verify (inspection, ' + str(r) + ' rounds)':62}: {t:7.0f} ms "
          f"[{len(ins.findings)} findings]", flush=True)  # fmt: skip
    admin = sa.create_engine(target, poolclass=sa.pool.NullPool)
    with admin.begin() as conn:
        conn.execute(sa.text("UPDATE app.championships SET counted_rounds = 0 "
                             "WHERE display_name = 'Championship Nov-26'"))  # fmt: skip
    admin.dispose()
    p = h.fresh(eng, op)
    plan_, t = ms(lambda: cops.preview_repair(eng, p, stream="development"))
    print(f"{'repair preview (tampered counter)':62}: {t:7.0f} ms", flush=True)
    stage(
        "repair run (preview included)",
        lambda: cops.run_repair(
            eng, h.fresh(eng, op), confirmation=plan_.token, reason="perf", stream="development"
        ),
    )
    ins = verify()
    print(f"integrity after the run: {ins.findings or 'consistent'}")
    eng.dispose()
    h.drop(url, name)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0], int(args[1]) if len(args) > 1 else 1000, int(args[2]) if len(args) > 2 else 11)
