# ruff: noqa: B023  (closures are called immediately inside each loop iteration)
"""Phase 6C.5 Stage C: timings of championship processing (real PostgreSQL).

Creates its own database ``diski9_perf6c5c_test``; builds a development stream with
N participants entering every round. For R rounds (R >= 11 for a rollover) it
settles and finalises each round and measures, separately:

* the weekly publication (Stage B) and the championship processing (Stage C)
  inside each finalisation;
* the cumulative standings calculation;
* paginated championship reads (first and last page) and the personal position;
* the rollover finalisation (eleventh round);
* reads running concurrently with a finalisation;
* a backfill of B rounds finalised without official results.

    uv run python tools/phase6c5_perf_championships.py URL N R B

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


def timed(fn, n=1):
    out, value = [], None
    for _ in range(n):
        t = time.perf_counter()
        value = fn()
        out.append((time.perf_counter() - t) * 1000)
    return value, statistics.median(out), max(out)


def main(url: str, n: int, r: int, b: int) -> None:
    import champ_helpers as h
    from svc_helpers import principal

    from diski9.backend.db import transaction
    from diski9.backend.repositories import accounts as accounts_repo
    from diski9.backend.services import championships as ch
    from diski9.backend.services import competition as comp
    from diski9.backend.services import competition_ops as cops
    from diski9.backend.services import leaderboards as lb

    name = "diski9_perf6c5c_test"
    eng, _ = h.isolated_engine(url, name)
    op = h.operator(eng)
    counter = itertools.count(1)
    with transaction(eng) as conn:
        people = []
        for _ in range(n):
            k = next(counter)
            uid = accounts_repo.create_user(conn)
            accounts_repo.link_identity(conn, uid, "supabase", f"perf-{uuid.uuid4().hex}")
            accounts_repo.create_profile(conn, uid, f"perf{k:06d}", f"Anonymous {10_000_000 + k}")
            people.append(uid)
    print(f"=== {n} participants, {r} rounds, backfill {b} ===", flush=True)
    t0 = time.perf_counter()
    plan = [[(u, h.WIN if (i + k) % 7 == 0 else h.lose(i)) for i, u in enumerate(people)]
            for k in range(r + b)]  # fmt: skip
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=6))
    print(f"build: {time.perf_counter() - t0:.1f} s", flush=True)
    for w in made:
        h.results(eng, op, w, h.winner)
    for w in made:
        h.settle(eng, op, w)

    weekly_ms, champ_ms = [], []
    real_publish, real_event = comp.publish_finalised, ch.on_round_event

    def pub(*a, **k):
        t = time.perf_counter()
        try:
            return real_publish(*a, **k)
        finally:
            weekly_ms.append((time.perf_counter() - t) * 1000)

    def evt(*a, **k):
        t = time.perf_counter()
        try:
            return real_event(*a, **k)
        finally:
            champ_ms.append((time.perf_counter() - t) * 1000)

    comp.publish_finalised, ch.on_round_event = pub, evt
    fin_ms = []
    try:
        for k, w in enumerate(made[:r]):
            if k == 10:  # reads concurrent with the rollover finalisation
                stop, errors, read_ms = threading.Event(), [], []

                def reader():
                    while not stop.is_set():
                        t = time.perf_counter()
                        try:
                            lb.championship_board(eng, stream="development",
                                                  include_development=True)  # fmt: skip
                        except Exception as exc:  # noqa: BLE001
                            errors.append(repr(exc))
                        read_ms.append((time.perf_counter() - t) * 1000)

                threads = [threading.Thread(target=reader) for _ in range(4)]
                for t in threads:
                    t.start()
            _, ms, _ = timed(lambda: h.finalise(eng, op, w))
            fin_ms.append(ms)
            if k == 10:
                stop.set()
                for t in threads:
                    t.join()
    finally:
        comp.publish_finalised, ch.on_round_event = real_publish, real_event
    # weekly_ms includes the championship processing called inside it
    for k in range(r):
        label = "rollover" if k == 10 else f"round {k + 1}"
        print(f"{label:9}: finalisation {fin_ms[k]:6.0f} ms | weekly publication "
              f"{weekly_ms[k] - champ_ms[k]:6.0f} ms | championship processing "
              f"{champ_ms[k]:6.0f} ms", flush=True)  # fmt: skip
    if r > 10:
        p95 = sorted(read_ms)[max(0, int(len(read_ms) * 0.95) - 1)] if read_ms else 0
        print(
            f"reads during the rollover finalisation (4 threads, same process): "
            f"{len(read_ms)} reads, {len(errors)} errors, p95 {p95:.1f} ms",
            flush=True,
        )

    with transaction(eng) as conn:
        c = conn.execute(sa.text("SELECT id FROM app.championships ORDER BY ordinal LIMIT 1")
                         ).scalar_one()  # fmt: skip
        sets = conn.execute(sa.text(
            "SELECT cr.round_id, (SELECT id FROM app.score_sets s WHERE s.round_id = cr.round_id "
            "AND s.kind = 'championship' ORDER BY revision DESC LIMIT 1) FROM "
            "app.championship_rounds cr JOIN app.rounds r ON r.id = cr.round_id "
            "WHERE cr.championship_id = :c AND cr.role = 'counted' ORDER BY r.deadline_at"),
            {"c": c}).all()  # fmt: skip
        _, med, mx = timed(lambda: ch.compute_standings(conn, c, [tuple(x) for x in sets]), 5)
    print(f"cumulative standings ({len(sets)} rounds x {n}): median {med:.0f} ms, max {mx:.0f} ms")
    first = lb.championship_list(eng, stream="development", include_development=True)[-1].name
    b1 = lb.championship_board(eng, stream="development", name=first, include_development=True)
    _, med, mx = timed(lambda: lb.championship_board(eng, stream="development", name=first,
                                                     include_development=True), 20)  # fmt: skip
    print(f"championship page 1: median {med:.1f} ms, max {mx:.1f} ms [{b1.total} rows, "
          f"{b1.status}]", flush=True)  # fmt: skip
    _, med, mx = timed(lambda: lb.championship_board(eng, stream="development", name=first,
                                                     page=b1.pages,
                                                     include_development=True), 20)  # fmt: skip
    print(f"championship last page {b1.pages}: median {med:.1f} ms, max {mx:.1f} ms")
    viewer = principal(eng, user_id=people[n // 2])
    bv, med, mx = timed(lambda: lb.championship_board(eng, stream="development", name=first,
                                                      viewer=viewer,
                                                      include_development=True), 20)  # fmt: skip
    print(f"championship page 1 + my position: median {med:.1f} ms, max {mx:.1f} ms "
          f"[my page {bv.me_page}]", flush=True)  # fmt: skip

    if b:
        comp.publish_finalised = lambda *a, **k: None  # rounds finalised "before app_0007"
        try:
            for w in made[r:]:
                h.finalise(eng, op, w)
        finally:
            comp.publish_finalised = real_publish
        plan_, med, _ = timed(lambda: cops.preview_backfill(eng, op))
        print(f"backfill preview ({plan_.to_publish} rounds): {med:.0f} ms", flush=True)
        _, med, _ = timed(lambda: cops.run_backfill(eng, op, confirmation=plan_.token))
        print(f"backfill run ({plan_.to_publish} rounds, preview included): {med:.0f} ms")
    with transaction(eng) as conn:
        problems = ch.verify_stream(conn, "development")
    print(f"integrity check: {problems or 'consistent'}")
    eng.dispose()
    h.drop(url, name)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0], int(args[1]) if len(args) > 1 else 1000, int(args[2]) if len(args) > 2 else 11,
         int(args[3]) if len(args) > 3 else 2)  # fmt: skip
