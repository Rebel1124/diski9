"""Phase 6C.5 Stage F3: reproduce (or rule out) deadlocks between finalisations of
two rounds of the same stream running at the same instant in two operating-system
processes (local development only; its own database ``diski9_f3_deadlock_test``).

    uv run python tools/phase6c5_f3_deadlock.py URL [PAIRS]

Builds 2 x PAIRS + 1 development rounds (five entrants each, two-round championships),
settles them, finalises the first, then for each consecutive pair (the last slot
of one championship and the first of the next) starts two processes that finalise the
two rounds after a shared barrier. Counts: both finalised, deadlocks (PostgreSQL
aborts one transaction; the finalisation rolls back and can be retried) and other
errors; then verifies the stream and retries any round left unfinalised.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "backend"))


def child(url, round_id, barrier, q):
    sys.path.insert(0, str(ROOT / "tests" / "backend"))
    import champ_helpers as h
    import sqlalchemy as sa

    from diski9.backend.db import BackendDatabaseSettings, make_app_engine
    from diski9.backend.services import corrections as co
    from diski9.backend.services import settlement as st

    eng = make_app_engine(BackendDatabaseSettings(environment="test", lock_timeout_ms=20000),
                          url=url)  # fmt: skip
    rid = UUID(round_id)
    try:
        op = h.operator(eng)
        with eng.begin() as conn:
            row = conn.execute(sa.text("SELECT * FROM app.rounds WHERE id = :r"),
                               {"r": rid}).one()  # fmt: skip
            earliest = st.earliest_finalisation(conn, row)
        barrier.wait(timeout=60)
        out = co.finalise_round(eng, op, rid, as_of=earliest)
        q.put(("ok" if out.finalised else "refused", out.reason or ""))
    except Exception as exc:  # noqa: BLE001
        q.put(("deadlock" if "DeadlockDetected" in repr(exc) else "error", repr(exc)[:200]))
    finally:
        eng.dispose()


def main(base: str, pairs: int) -> None:
    import champ_helpers as h
    import sqlalchemy as sa

    from diski9.backend.db import transaction
    from diski9.backend.services import championships as ch

    name = "diski9_f3_deadlock_test"
    eng, url = h.isolated_engine(base, name)
    h.set_required(eng, 2)
    op = h.operator(eng)
    u = h.users(eng, 6)
    plan = [[(u[i], h.WIN if i == k % 5 else h.lose(i)) for i in range(5)]
            for k in range(2 * pairs + 1)]  # fmt: skip
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=4))
    h.prepare(eng, op, made)
    # R1 first, so each racing pair is (last slot of a championship, first slot of the
    # next): the championship boundary / rollover race
    h.finalise(eng, h.fresh(eng, op), made[0])
    made = made[1:]
    ctx = mp.get_context("spawn")
    tally = {"ok": 0, "deadlock": 0, "refused": 0, "error": 0}
    left, details = [], []
    for k in range(pairs):
        pair = made[2 * k : 2 * k + 2]
        barrier, q = ctx.Barrier(2), ctx.Queue()
        procs = [ctx.Process(target=child, args=(url, str(w["round"]), barrier, q))
                 for w in pair]  # fmt: skip
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=180)
        res = [q.get(timeout=5) for _ in procs]
        for r in res:
            tally[r[0]] += 1
            if r[0] != "ok":
                details.append(r)
        left += [w for w in pair]
    retried = 0
    for w in left:
        with transaction(eng) as conn:
            status = conn.execute(sa.text("SELECT status FROM app.rounds WHERE id = :r"),
                                  {"r": w["round"]}).scalar()  # fmt: skip
        if status != "final":
            h.finalise(eng, h.fresh(eng, op), w)
            retried += 1
    with transaction(eng) as conn:
        problems = ch.verify_stream(conn, "development")
        dup = conn.execute(sa.text("SELECT count(*) FROM (SELECT round_id FROM "
                                   "app.championship_rounds GROUP BY 1 HAVING count(*) > 1) d")
                           ).scalar()  # fmt: skip
    out = {"pairs": pairs, "finalisations": 2 * pairs, **tally, "retried_afterwards": retried,
           "verify": problems or "consistent", "duplicate_memberships": dup,
           "details": details[:5]}  # fmt: skip
    print(json.dumps(out, indent=1))
    (ROOT / "tmp" / "f3").mkdir(parents=True, exist_ok=True)
    label = sys.argv[3] if len(sys.argv) > 3 else "run"
    (ROOT / "tmp" / "f3" / f"deadlock_{label}.json").write_text(json.dumps(out, indent=1))
    eng.dispose()
    h.drop(base, name)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10)
