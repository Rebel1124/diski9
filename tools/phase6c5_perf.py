# ruff: noqa: B023  (closures are called immediately inside each loop iteration)
"""Phase 6C.5 Stage B: timings of weekly results (real PostgreSQL).

Creates its own database ``diski9_perf6c5_test`` on the server of the given URL,
migrates it, builds a development round with N locked entries over 18 fixtures,
records synthetic final results, settles it, and times:

* provisional weekly standings (uncached and cached reads);
* the official weekly publication inside finalisation (and the whole finalisation);
* official weekly pages (first and last page), with and without a signed-in viewer
  (personal position lookup);
* reads running concurrently with the publication (errors and consistency).

    uv run python tools/phase6c5_perf.py postgresql+psycopg://postgres@127.0.0.1:5433/x 1000 10000

Results are measurements on this machine, not guarantees.
"""

from __future__ import annotations

import statistics
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "backend"))

from sqlalchemy import create_engine, pool, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from diski9.backend.db import (  # noqa: E402
    BackendDatabaseSettings,
    make_app_engine,
    migrate,
    transaction,
)


def timed(fn, n=1):
    out = []
    value = None
    for _ in range(n):
        t = time.perf_counter()
        value = fn()
        out.append((time.perf_counter() - t) * 1000)
    return value, statistics.median(out), max(out)


def main(url: str, sizes: list[int]) -> None:
    base = make_url(url)
    name = "diski9_perf6c5_test"
    admin = create_engine(base.set(database="postgres"), poolclass=pool.NullPool,
                          isolation_level="AUTOCOMMIT")  # fmt: skip
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {name}"))
    target = base.set(database=name).render_as_string(hide_password=False)
    with create_engine(target, poolclass=pool.NullPool).begin() as c:
        c.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname="
                       "'diski9_app') THEN CREATE ROLE diski9_app NOLOGIN; "
                       "END IF; END $$;"))  # fmt: skip
    migrate.upgrade(target)
    engine = make_app_engine(BackendDatabaseSettings(environment="test"), url=target)

    import itertools
    import uuid

    import settle_helpers
    from settle_helpers import DEFAULT_ENTRY, settlement_worlds, shifted

    from diski9.backend.repositories import accounts as accounts_repo

    counter = itertools.count(1)

    def make_user(conn):  # unique aliases (random ones collide at 20,000 users)
        k = next(counter)
        uid = accounts_repo.create_user(conn)
        accounts_repo.link_identity(conn, uid, "supabase", f"perf-{uuid.uuid4().hex}")
        accounts_repo.create_profile(conn, uid, f"perf{k:06d}", f"Anonymous {10_000_000 + k}")
        return uid

    settle_helpers.make_user = make_user
    from svc_helpers import principal, wait_until

    from diski9.backend.db import db_now
    from diski9.backend.db.schema import rounds
    from diski9.backend.services import competition as comp
    from diski9.backend.services import corrections as co
    from diski9.backend.services import leaderboards as lb
    from diski9.backend.services import results as rs
    from diski9.backend.services import settlement as st

    def fresh(p):
        from dataclasses import replace

        with transaction(engine) as conn:
            now = db_now(conn)
        return replace(p, authenticated_at=now, reauthenticated_at=now, now=now)

    op = fresh(principal(engine, role="operator"))
    winner = {0: (1, 0), 1: (1, 0), 2: (1, 0), 3: (1, 0), 4: (1, 1), 5: (1, 1), 6: (0, 0),
              7: (0, 1), 8: (0, 1)}  # fmt: skip
    specs_pool = [tuple(((j + r) % 9, m, o) for j, (_, m, o) in enumerate(DEFAULT_ENTRY))
                  for r in range(9)] + [shifted(k) for k in range(1, 10)]  # fmt: skip

    for n in sizes:
        print(f"\n=== {n} entries ===", flush=True)
        t0 = time.perf_counter()
        spec = [specs_pool[i % len(specs_pool)] for i in range(n)]
        w, w2 = settlement_worlds(engine, [spec, spec], development=True,
                                  cutoff_after=timedelta(seconds=4))  # fmt: skip
        print(f"build (two rounds): {time.perf_counter() - t0:.1f} s", flush=True)
        for ww in (w, w2):
            rs.set_result_mode(engine, op, ww["round"], "synthetic")
            at = ww["deadline"] + timedelta(milliseconds=1500)
            ko = ww["deadline"] + timedelta(seconds=1)
            wait_until(engine, at)
            for i, fid in enumerate(ww["fixtures"]):
                h, a = winner.get(i, (2, 1))
                rs.record_synthetic_observation(engine, op, ww["round"], fid, observed_at=at,
                                                status="FT", kickoff_at=ko, ft_home=h,
                                                ft_away=a)  # fmt: skip
        wait_until(engine, w2["cutoff"] + timedelta(milliseconds=200))
        _, settle_ms, _ = timed(lambda: st.settle_round(engine, op, w["round"]))
        st.settle_round(engine, op, w2["round"])
        print(f"settlement run (6C.4, for reference): {settle_ms:.0f} ms", flush=True)

        def prov_uncached():
            lb.clear_cache()
            return lb.weekly_board(engine, w["round"], include_development=True)

        b, med, mx = timed(prov_uncached, 10)
        print(f"provisional page (uncached): median {med:.1f} ms, max {mx:.1f} ms "
              f"[state {b.state}, rows {b.total}]", flush=True)  # fmt: skip
        _, med, mx = timed(lambda: lb.weekly_board(engine, w["round"], include_development=True),
                           20)  # fmt: skip
        print(f"provisional page (cached): median {med:.1f} ms, max {mx:.1f} ms", flush=True)

        # finalisation with the publication timed inside it
        publish_ms = []
        real = comp.publish_finalised

        def wrapped(*a, **k):
            t = time.perf_counter()
            try:
                return real(*a, **k)
            finally:
                publish_ms.append((time.perf_counter() - t) * 1000)

        def earliest_of(rid):
            with transaction(engine) as conn:
                return st.earliest_finalisation(
                    conn, conn.execute(select(rounds).where(rounds.c.id == rid)).one()
                )

        # 1) publication timed alone (no concurrent load)
        comp.publish_finalised = wrapped
        try:
            out, fin_ms, _ = timed(
                lambda: co.finalise_round(engine, op, w["round"], as_of=earliest_of(w["round"]))
            )
        finally:
            comp.publish_finalised = real
        assert out.finalised, out.reason
        print(f"publication inside finalisation (alone): {publish_ms[-1]:.0f} ms "
              f"(whole finalisation {fin_ms:.0f} ms)", flush=True)  # fmt: skip

        # 2) a second round finalised while 8 reader threads read it
        stop = threading.Event()
        seen, errors, read_ms = set(), [], []

        def reader():
            while not stop.is_set():
                t = time.perf_counter()
                try:
                    bb = lb.weekly_board(engine, w2["round"], include_development=True)
                    seen.add((bb.state, bb.revision, bb.total))
                except Exception as exc:  # noqa: BLE001
                    errors.append(repr(exc))
                read_ms.append((time.perf_counter() - t) * 1000)

        readers = [threading.Thread(target=reader) for _ in range(8)]
        for t in readers:
            t.start()
        time.sleep(0.3)
        comp.publish_finalised = wrapped
        try:
            out, fin_ms, _ = timed(
                lambda: co.finalise_round(engine, op, w2["round"], as_of=earliest_of(w2["round"]))
            )
        finally:
            comp.publish_finalised = real
        time.sleep(0.5)
        stop.set()
        for t in readers:
            t.join()
        assert out.finalised, out.reason
        print(f"publication under 8 concurrent readers (same process): {publish_ms[-1]:.0f} ms "
              f"(whole finalisation {fin_ms:.0f} ms)", flush=True)  # fmt: skip
        p95 = sorted(read_ms)[int(len(read_ms) * 0.95) - 1] if read_ms else 0
        print(f"concurrent reads: {len(read_ms)} reads by 8 threads, {len(errors)} errors, "
              f"states seen {sorted(seen, key=str)}, p95 {p95:.1f} ms", flush=True)  # fmt: skip

        b1 = lb.weekly_board(engine, w["round"], include_development=True)
        last = b1.pages
        _, med, mx = timed(lambda: lb.weekly_board(engine, w["round"], include_development=True),
                           20)  # fmt: skip
        print(f"official page 1 (guest): median {med:.1f} ms, max {mx:.1f} ms", flush=True)
        _, med, mx = timed(lambda: lb.weekly_board(engine, w["round"], page=last,
                                                   include_development=True), 20)  # fmt: skip
        print(f"official last page {last} (guest): median {med:.1f} ms, max {mx:.1f} ms",
              flush=True)  # fmt: skip
        viewer = principal(engine, user_id=w["users"][n // 2])
        bv, med, mx = timed(lambda: lb.weekly_board(engine, w["round"], viewer=viewer,
                                                    include_development=True), 20)  # fmt: skip
        print(f"official page 1 + my position: median {med:.1f} ms, max {mx:.1f} ms "
              f"[my page {bv.me_page}]", flush=True)  # fmt: skip

    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    admin.dispose()


if __name__ == "__main__":
    main(sys.argv[1], [int(x) for x in sys.argv[2:]] or [1000])
