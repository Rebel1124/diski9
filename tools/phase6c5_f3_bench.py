# ruff: noqa: B023  (closures are called immediately inside each loop iteration)
"""Phase 6C.5 Stage F3: service-level read benchmarks on a built F3 dataset
(``phase6c5_f3_build.py``); read-only. Measures, in this process, the read services
the pages call (no HTTP, no browser), with SQL statement counts.

    uv run python tools/phase6c5_f3_bench.py reads   URL NAME [ITER]
    uv run python tools/phase6c5_f3_bench.py history URL NAME [ITER]

Method: for each operation one *cold* call (provisional cache cleared, new engine
and connection pool), then 5 warm-up calls, then ITER (default 30) measured calls
with ``time.perf_counter``; median, p95 (nearest rank), min and max in milliseconds,
and the statements issued by one call. Results go to ``tmp/f3/<NAME>_<kind>.json``.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "backend"))
OUT = ROOT / "tmp" / "f3"

from sqlalchemy import event, text  # noqa: E402


def p95(xs):
    s = sorted(xs)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


class Bench:
    def __init__(self, url, iters):
        self.url, self.iters, self.rows = url, iters, []
        self.eng = self.engine()

    def engine(self):
        from diski9.backend.db import BackendDatabaseSettings, make_app_engine

        eng = make_app_engine(BackendDatabaseSettings(environment="development"), url=self.url)
        eng.statements = 0

        @event.listens_for(eng, "before_cursor_execute")
        def _count(*_a, **_k):
            eng.statements += 1

        return eng

    def run(self, name, fn, *, population, target=None, cold=True, before=None):
        from diski9.backend.services import leaderboards as lb

        cold_ms = None
        if cold:
            lb.clear_cache()
            fresh = self.engine()
            t = time.perf_counter()
            fn(fresh)
            cold_ms = (time.perf_counter() - t) * 1000
            fresh.dispose()
        for _ in range(5):
            if before:
                before()
            fn(self.eng)
        xs = []
        for _ in range(self.iters):
            if before:
                before()
            t = time.perf_counter()
            fn(self.eng)
            xs.append((time.perf_counter() - t) * 1000)
        if before:
            before()
        self.eng.statements = 0
        fn(self.eng)
        row = {"operation": name, "population": population, "target_ms": target,
               "cold_ms": None if cold_ms is None else round(cold_ms, 1),
               "median_ms": round(statistics.median(xs), 2), "p95_ms": round(p95(xs), 2),
               "min_ms": round(min(xs), 2), "max_ms": round(max(xs), 2), "n": len(xs),
               "statements": self.eng.statements,
               "result": None if target is None else
               ("pass" if statistics.median(xs) <= target else "miss")}  # fmt: skip
        self.rows.append(row)
        print(f"{name:58} med {row['median_ms']:8.2f}  p95 {row['p95_ms']:8.2f}  cold "
              f"{row['cold_ms'] or 0:8.1f}  stmts {row['statements']:3}  "
              f"{row['result'] or ''}", flush=True)  # fmt: skip
        return row


def principal_for(eng, uid):
    from svc_helpers import principal

    return principal(eng, user_id=UUID(str(uid)))


def reads(url, name, iters):
    from diski9.backend.services import challenge_history as chist
    from diski9.backend.services import leaderboards as lb

    meta = json.loads((OUT / f"{name}_build.json").read_text())
    n = meta["participants"]
    pop = f"{n:,} participants"
    b = Bench(url, iters)
    dev = {"include_development": True}
    codes = meta["codes"]
    rid = {k: lb.round_id_for(b.eng, c, stream="development", **dev)
           for k, c in zip(range(1, 14), codes, strict=True)}  # fmt: skip
    if not meta["account_ids"]:
        raise SystemExit("this benchmark needs a dataset built with test accounts")
    viewer = principal_for(b.eng, meta["account_ids"][0])
    first = lb.weekly_board(b.eng, rid[11], **dev)
    pages = first.pages
    # a page whose first row shares its rank with the previous page's last row
    boundary = None
    for pg in range(2, pages + 1):
        prev = lb.weekly_board(b.eng, rid[11], page=pg - 1, **dev).rows[-1]
        cur = lb.weekly_board(b.eng, rid[11], page=pg, **dev).rows[0]
        if prev.position == cur.position:
            boundary = pg
            break
    mine = lb.weekly_board(b.eng, rid[11], viewer=viewer, **dev)
    print(
        f"=== {name}: {n} participants; R11 {first.total} ranked rows, {pages} pages; "
        f"viewer page {mine.me_page}; shared-rank boundary page {boundary} ==="
    )
    official_target = 50 if n <= 1000 else 80
    b.run(
        "weekly official page 1 (guest)",
        lambda e: lb.weekly_board(e, rid[11], **dev),
        population=pop,
        target=official_target,
    )
    b.run(
        "weekly official middle page (guest)",
        lambda e: lb.weekly_board(e, rid[11], page=max(1, pages // 2), **dev),
        population=pop,
        target=official_target,
    )
    b.run(
        "weekly official last page (guest)",
        lambda e: lb.weekly_board(e, rid[11], page=pages, **dev),
        population=pop,
        target=official_target,
    )
    if boundary:
        b.run(
            "weekly official shared-rank boundary page",
            lambda e: lb.weekly_board(e, rid[11], page=boundary, **dev),
            population=pop,
            target=official_target,
        )
    b.run(
        "weekly official page 1 + viewer position",
        lambda e: lb.weekly_board(e, rid[11], viewer=viewer, **dev),
        population=pop,
        target=official_target,
    )
    b.run(
        "weekly official viewer's page + position",
        lambda e: lb.weekly_board(e, rid[11], viewer=viewer, page=mine.me_page or 1, **dev),
        population=pop,
        target=official_target,
    )
    b.run(
        "weekly provisional page 1, uncached (R12)",
        lambda e: lb.weekly_board(e, rid[12], **dev),
        population=pop,
        target=250 if n <= 1000 else None,
        before=lb.clear_cache,
    )
    b.run(
        "weekly provisional page 1, cached (R12)",
        lambda e: lb.weekly_board(e, rid[12], **dev),
        population=pop,
        target=30 if n <= 1000 else None,
    )
    champs = lb.championship_list(b.eng, stream="development", **dev)
    done = next(c for c in champs if c.status == "completed").name
    cur = next(c for c in champs if c.status != "completed").name
    cb = lb.championship_board(b.eng, stream="development", name=done, viewer=viewer, **dev)
    b.run(
        "championship completed, page 1 (guest)",
        lambda e: lb.championship_board(e, stream="development", name=done, **dev),
        population=pop,
        target=official_target,
    )
    b.run("championship completed, last page",
          lambda e: lb.championship_board(e, stream="development", name=done, page=cb.pages,
                                          **dev), population=pop,
          target=official_target)  # fmt: skip
    b.run("championship completed, page 1 + personal rank",
          lambda e: lb.championship_board(e, stream="development", name=done, viewer=viewer,
                                          **dev), population=pop,
          target=official_target)  # fmt: skip
    b.run("championship in progress, page 1 + personal rank",
          lambda e: lb.championship_board(e, stream="development", name=cur, viewer=viewer,
                                          **dev), population=pop,
          target=official_target)  # fmt: skip
    b.run(
        "championship list (selector)",
        lambda e: lb.championship_list(e, stream="development", **dev),
        population=pop,
    )
    b.run(
        "round list (selector)",
        lambda e: lb.round_list(e, stream="development", **dev),
        population=pop,
    )
    # personal rank lookup: no separate service call exists; the viewer's row is read
    # inside the board. The whole read (50-row page *and* the personal rank) is taken
    # as a conservative upper bound (the difference to the guest read is within noise)
    withme = next(
        r for r in b.rows if r["operation"] == "championship completed, page 1 + personal rank"
    )
    b.rows.append({"operation": "personal rank lookup (upper bound: page 1 + personal rank)",
                   "population": pop, "target_ms": 20, "median_ms": withme["median_ms"],
                   "p95_ms": withme["p95_ms"], "derived": withme["operation"],
                   "result": "pass" if withme["median_ms"] <= 20 else "miss"})  # fmt: skip
    b.run(
        "my round result (drill-down, R11)",
        lambda e: lb.my_round_result(e, viewer, rid[11], **dev),
        population=pop,
    )
    b.run(
        "my statistics (all championships)",
        lambda e: chist.my_statistics(e, viewer, stream="development", **dev),
        population=pop,
    )
    b.run(
        "my history page 1 (20)",
        lambda e: chist.my_history(e, viewer, stream="development", page_size=20, **dev),
        population=pop,
    )
    # direct visit: the account hydration read added in F2 (§7.9 F2-3), and the page
    from diski9.app.challenge import pages, persist
    from diski9.app.challenge.service import ChallengeService
    from diski9.backend.auth import web

    web.current_principal = lambda: viewer
    web.owner_tag = lambda: str(viewer.user_id)[:12]

    def service(e):
        data = SimpleNamespace(
            clock=lambda: datetime.now(UTC),
            detail=lambda fid: (None, None, None),
            snapshot=lambda: SimpleNamespace(
                cache_calculated_at=datetime(2026, 11, 19, tzinfo=UTC)
            ),
        )
        return ChallengeService(data, backend=persist.Backend(e, show_development=True,
                                                               ttl=3.0))  # fmt: skip

    svc = service(b.eng)

    def local(dt):
        return str(dt)

    b.run(
        "My Challenge: account hydration (direct visit)",
        lambda e: persist.hydrate(svc, {}),
        population=pop,
    )
    b.run(
        "My Challenge: page render from an empty store (direct visit)",
        lambda e: pages.my_challenge(svc, {}, local),
        population=pop,
    )
    hydrated = persist.hydrate(svc, {})
    assert hydrated.get("submitted"), "the live round's confirmed entry was not hydrated"
    b.run(
        "My Challenge: page render from a hydrated store",
        lambda e: pages.my_challenge_body(svc, hydrated, local),
        population=pop,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}_reads.json").write_text(json.dumps(b.rows, indent=1))
    b.eng.dispose()


def history(url, name, iters):
    from diski9.backend.services import challenge_history as chist

    meta = json.loads((OUT / f"{name}_build.json").read_text())
    b = Bench(url, iters)
    v = principal_for(b.eng, meta["viewer"])
    dev = {"stream": "development", "include_development": True}
    print(f"=== {name}: one participant with {meta['entries']} entries ===")
    b.run(
        "history list (20 rows)",
        lambda e: chist.my_history(e, v, page_size=20, **dev),
        population="50 entries",
    )
    b.run(
        "statistics (all championships)",
        lambda e: chist.my_statistics(e, v, **dev),
        population="50 entries",
    )
    b.run("history list (20 rows) + statistics",
          lambda e: (chist.my_history(e, v, page_size=20, **dev),
                     chist.my_statistics(e, v, **dev)),
          population="50 entries", target=100)  # fmt: skip
    names = (
        [c for c in chist.scope_options(b.eng, v, **dev)] if hasattr(chist, "scope_options") else []
    )
    del names
    b.run("history filtered to one championship + statistics",
          lambda e: (chist.my_history(e, v, page_size=20, championship="Championship Nov-26",
                                      **dev),
                     chist.my_statistics(e, v, championship="Championship Nov-26", **dev)),
          population="50 entries", target=100)  # fmt: skip
    b.run(
        "history last page (3 of 3)",
        lambda e: chist.my_history(e, v, page_size=20, page=3, **dev),
        population="50 entries",
    )
    (OUT / f"{name}_history.json").write_text(json.dumps(b.rows, indent=1))
    b.eng.dispose()


def _url(base, name):
    from sqlalchemy.engine import make_url

    return make_url(base).set(database=name).render_as_string(hide_password=False)


if __name__ == "__main__":
    a = sys.argv[1:]
    it = int(a[3]) if len(a) > 3 else 30
    {"reads": reads, "history": history}[a[0]](_url(a[1], a[2]), a[2], it)
    del text
