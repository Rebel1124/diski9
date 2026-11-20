# ruff: noqa: B023  (closures are called immediately inside each loop iteration)
"""Phase 6C.5 Stage E: read-service timings and statement counts behind the new pages
(real PostgreSQL; its own database ``diski9_perf6c5e_test``).

N participants enter R development rounds (ten-round championships, so R >= 11
gives a completed and a current championship). For one participant it times the
reads each page makes and counts the SQL statements each read issues, so that an
N+1 query pattern would show up:

* Weekly page: ``round_list``, then ``weekly_board`` (page 1 and the viewer's row).
* Championship page: ``championship_list`` and ``championship_board``.
* My Challenge History: ``my_statistics`` (all championships and one), and
  ``my_history`` (one page of 20).
* Drill-down: ``my_round_result`` with its ``my_settlement``.

    uv run python tools/phase6c5_perf_stage_e.py URL N R

Results are measurements on this machine, not guarantees.
"""

from __future__ import annotations

import itertools
import statistics
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "backend"))

from sqlalchemy import event  # noqa: E402


def main(url: str, n: int, r: int) -> None:
    import champ_helpers as h
    from svc_helpers import principal

    from diski9.backend.db import transaction
    from diski9.backend.repositories import accounts as accounts_repo
    from diski9.backend.services import challenge_history as ch
    from diski9.backend.services import leaderboards as lb

    name = "diski9_perf6c5e_test"
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
    t0 = time.perf_counter()
    plan = [[(u, h.WIN if (i + k) % 7 == 0 else h.lose(i)) for i, u in enumerate(people)]
            for k in range(r)]  # fmt: skip
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=6))
    h.prepare(eng, op, made)
    for w in made:
        h.finalise(eng, op, w)
    print(f"=== {n} participants, {r} rounds (built in {time.perf_counter() - t0:.0f} s) ===")
    viewer = principal(eng, user_id=people[n // 2])
    statements = {"n": 0}

    @event.listens_for(eng, "before_cursor_execute")
    def _count(*_a, **_k):
        statements["n"] += 1

    def measure(label, fn, repeat=10):
        times = []
        for _ in range(repeat):
            statements["n"] = 0
            t = time.perf_counter()
            fn()
            times.append((time.perf_counter() - t) * 1000)
        print(f"{label:58}: median {statistics.median(times):6.1f} ms, max {max(times):6.1f} ms,"
              f" {statements['n']} statements")  # fmt: skip

    dev = {"include_development": True}
    rounds = lb.round_list(eng, stream="development", **dev)
    code = lb.default_round(rounds).code
    rid = lb.round_id_for(eng, code, stream="development", **dev)
    measure(
        "weekly: round_list (selector)", lambda: lb.round_list(eng, stream="development", **dev)
    )
    measure("weekly: weekly_board page 1 + viewer row",
            lambda: lb.weekly_board(eng, rid, viewer=viewer, **dev))  # fmt: skip
    measure(
        "weekly: weekly_board last page",
        lambda: lb.weekly_board(eng, rid, viewer=viewer, page=n // 50 + 1, **dev),
    )
    measure(
        "championship: championship_list",
        lambda: lb.championship_list(eng, stream="development", **dev),
    )
    measure("championship: championship_board (completed, 10 rounds)",
            lambda: lb.championship_board(eng, stream="development", name="Championship Nov-26",
                                          viewer=viewer, **dev))  # fmt: skip
    measure(
        "history: my_statistics (all championships)",
        lambda: ch.my_statistics(eng, viewer, stream="development", **dev),
    )
    measure("history: my_statistics (one championship)",
            lambda: ch.my_statistics(eng, viewer, stream="development",
                                     championship="Championship Nov-26", **dev))  # fmt: skip
    measure(
        "history: my_history page of 20",
        lambda: ch.my_history(eng, viewer, stream="development", **dev),
    )
    measure(
        "drill-down: my_round_result (incl. my_settlement)",
        lambda: lb.my_round_result(eng, viewer, rid, **dev),
    )
    eng.dispose()
    h.drop(url, name)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], int(a[1]) if len(a) > 1 else 1000, int(a[2]) if len(a) > 2 else 11)
