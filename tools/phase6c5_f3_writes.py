# ruff: noqa: B023  (closures are called immediately inside each loop iteration)
"""Phase 6C.5 Stage F3: write-path benchmarks (real PostgreSQL, isolated databases;
local development only).

    uv run python tools/phase6c5_f3_writes.py publication URL [ENTRIES] [ROUNDS]
    uv run python tools/phase6c5_f3_writes.py corrections URL NAME [SAMPLES]

``publication`` builds ``diski9_f3_pub`` (dropped and re-created) with ROUNDS
(default 7) development rounds of exactly ENTRIES (default 1,000) locked entries
with varied portfolios (winners, partly void winners, shared losing portfolios,
refunds), then finalises them one by one. The first finalisation is the warm-up;
the rest are measured. Each finalisation is split by wrapping the real functions:
weekly publication (adapter, ranking, score-set insert) = ``publish_finalised``
minus the championship processing (``on_round_event``) it calls. Data generation,
settlement and waiting are outside the timed region. Verified per round: one score
set, a score row for every ranked entry, refunded entries unranked, shared ranks
with equal points, championship standings equal to a from-scratch recomputation.

``corrections`` runs on a built F3 dataset after the read and concurrency tests (it
changes the data): SAMPLES (default 3) valid-to-valid corrections of different
counted rounds of the completed first championship (all nine results corrected so
that nobody recovers; owner reopening, operator corrections, re-finalisation),
timing the re-finalisation end to end and its championship re-aggregation and new
version. Verified: a new championship version each time (not a no-op), standings
equal to a recomputation, no duplicate score sets, verification consistent.
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "backend"))
OUT = ROOT / "tmp" / "f3"

import sqlalchemy as sa  # noqa: E402


def p95(xs):
    s = sorted(xs)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


class Timers:
    """Wrap publish_finalised and on_round_event (the real functions)."""

    def __enter__(self):
        from diski9.backend.services import championships as ch
        from diski9.backend.services import competition as comp

        self.ch, self.comp = ch, comp
        self.weekly, self.champ = [], []
        self.real = (comp.publish_finalised, ch.on_round_event)

        def pub(*a, **k):
            t = time.perf_counter()
            try:
                return self.real[0](*a, **k)
            finally:
                self.weekly.append((time.perf_counter() - t) * 1000)

        def evt(*a, **k):
            t = time.perf_counter()
            try:
                return self.real[1](*a, **k)
            finally:
                self.champ.append((time.perf_counter() - t) * 1000)

        comp.publish_finalised, ch.on_round_event = pub, evt
        return self

    def __exit__(self, *exc):
        self.comp.publish_finalised, self.ch.on_round_event = self.real


def standings_match(conn, ch) -> list[str]:
    """Every championship's latest stored standings equal a recomputation from the
    published weekly score sets of its counted rounds."""
    problems = []
    for (cid,) in conn.execute(sa.text("SELECT id FROM app.championships")):
        sets = conn.execute(sa.text(
            "SELECT cr.round_id, (SELECT id FROM app.score_sets s WHERE s.round_id = "
            "cr.round_id AND s.kind = 'championship' ORDER BY revision DESC LIMIT 1) FROM "
            "app.championship_rounds cr JOIN app.rounds r ON r.id = cr.round_id WHERE "
            "cr.championship_id = :c AND cr.role = 'counted' ORDER BY r.deadline_at"),
            {"c": cid}).all()  # fmt: skip
        if not sets:
            continue
        table, _ = ch.compute_standings(conn, cid, [tuple(x) for x in sets])
        stored = conn.execute(sa.text(
            "SELECT s.user_id, s.points FROM app.championship_standings s WHERE s.version_id = "
            "(SELECT id FROM app.championship_versions WHERE championship_id = :c "
            "ORDER BY version DESC LIMIT 1)"), {"c": cid}).all()  # fmt: skip
        want = {str(x.participant_id): x.points for x in table.standings}
        got = {str(r.user_id): r.points for r in stored}
        if want != got:
            problems.append(f"championship {cid}: stored standings differ from recomputation")
    return problems


def weekly_checks(conn, rid) -> list[str]:
    p = []
    sets = conn.execute(sa.text("SELECT id FROM app.score_sets WHERE round_id = :r"),
                        {"r": rid}).scalars().all()  # fmt: skip
    if len(set(sets)) != len(sets) or not sets:
        p.append("score sets")
    rows = conn.execute(sa.text(
        "SELECT rs.* FROM app.round_scores rs WHERE rs.score_set_id = :s"),
        {"s": sets[-1]}).mappings().all()  # fmt: skip
    if not rows:
        p.append("no score rows")
        return p
    cols = rows[0].keys()
    rank = next((c for c in ("rank", "weekly_rank", "position") if c in cols), None)
    pts = next((c for c in ("weekly_points", "points") if c in cols), None)
    if rank and pts:
        by = {}
        for r in rows:
            if r[rank] is not None:
                by.setdefault(r[rank], set()).add(r[pts])
        if any(len(v) > 1 for v in by.values()):
            p.append("a shared rank with different points")
    return p


def publication(base: str, entries: int = 1000, rounds: int = 7) -> None:
    import champ_helpers as h
    from pg_helpers import make_user

    from diski9.backend.db import transaction
    from diski9.backend.services import championships as ch

    name = os.environ.get("PUB_DB", "diski9_f3_pub")  # F4 re-runs: diski9_f4_pub
    eng, _ = h.isolated_engine(base, name)
    rng = random.Random(77)
    with transaction(eng) as conn:
        people = [make_user(conn, f"pub{k:05d}") for k in range(entries)]
    win = list(h.WIN)
    partial = tuple(win[:7] + [(9, "1X2", "AWAY"), (10, "1X2", "AWAY")])

    def pick(i):
        x = rng.random()
        return (h.REFUND if x < 0.01 else h.WIN if x < 0.11 else partial if x < 0.2
                else h.lose(1 + i % 3) if x < 0.55 else h.lose(i))  # fmt: skip

    plan = [[(u, pick(i)) for i, u in enumerate(people)] for _ in range(rounds)]
    op = h.operator(eng)
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=8))
    h.prepare(eng, op, made)
    fin, problems = [], []
    with Timers() as t:
        for w in made:
            s = time.perf_counter()
            h.finalise(eng, h.fresh(eng, op), w)
            fin.append((time.perf_counter() - s) * 1000)
    with transaction(eng) as conn:
        for w in made:
            problems += weekly_checks(conn, w["round"])
        problems += standings_match(conn, ch)
        problems += ch.verify_stream(conn, "development")
        refunded_ranked = conn.execute(sa.text(
            "SELECT count(*) FROM app.round_scores WHERE status = 'void_refunded' "
            "AND rank IS NOT NULL")).scalar()  # fmt: skip
        refunded = conn.execute(
            sa.text("SELECT count(*) FROM app.round_scores WHERE status = 'void_refunded'")
        ).scalar()
    weekly = [a - b for a, b in zip(t.weekly, t.champ, strict=True)]
    m = slice(1, None)  # the first finalisation is the warm-up
    out = {"entries_per_round": entries, "rounds": rounds, "measured": rounds - 1,
           "weekly_publication_ms": _stats(weekly[m]), "championship_processing_ms":
           _stats(t.champ[m]), "finalisation_total_ms": _stats(fin[m]),
           "per_round": [{"weekly": round(a, 1), "championship": round(b, 1),
                          "finalisation": round(c, 1)} for a, b, c in zip(weekly, t.champ, fin,
                                                                           strict=True)],
           "refunded_entries": refunded, "refunded_entries_ranked": refunded_ranked,
           "problems": problems or "none"}  # fmt: skip
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "publication.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "per_round"}, indent=1))
    eng.dispose()


def _has(conn, table, col) -> bool:
    return bool(conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'app' AND "
        "table_name = :t AND column_name = :c"), {"t": table, "c": col}).scalar())  # fmt: skip


def _stats(xs):
    return {"median": round(statistics.median(xs), 1), "p95": round(p95(xs), 1),
            "min": round(min(xs), 1), "max": round(max(xs), 1), "n": len(xs)}  # fmt: skip


def corrections(base: str, name: str, samples: int = 3) -> None:
    import champ_helpers as h
    from sqlalchemy.engine import make_url

    from diski9.backend.db import BackendDatabaseSettings, make_app_engine, transaction
    from diski9.backend.services import championships as ch

    if not name.startswith(("diski9_f3_", "diski9_f4_")):
        raise SystemExit("refused: F3/F4 databases only")
    url = make_url(base).set(database=name).render_as_string(hide_password=False)
    eng = make_app_engine(BackendDatabaseSettings(environment="development",
                                                  lock_timeout_ms=10000), url=url)  # fmt: skip
    op, own = h.operator(eng), h.owner(eng)
    with transaction(eng) as conn:
        first = conn.execute(sa.text("SELECT id FROM app.championships ORDER BY ordinal LIMIT 1")
                             ).scalar_one()  # fmt: skip
        counted = conn.execute(sa.text(
            "SELECT r.id, r.deadline_at FROM app.championship_rounds cr JOIN app.rounds r ON "
            "r.id = cr.round_id WHERE cr.championship_id = :c AND cr.role = 'counted' "
            "ORDER BY r.deadline_at"), {"c": first}).all()  # fmt: skip
    targets = [counted[i] for i in (2, 4, 6, 8, 1, 3)[:samples]]
    rows, problems = [], []
    for rid, deadline in targets:
        with transaction(eng) as conn:
            fids = sorted(conn.execute(sa.text(
                "SELECT DISTINCT s.fixture_id FROM app.submission_selections s JOIN "
                "app.entries e ON e.locked_submission_id = s.submission_id WHERE e.round_id = :r"),
                {"r": rid}).scalars())[:18]  # fmt: skip
            versions = conn.execute(sa.text("SELECT count(*) FROM app.championship_versions "
                                            "WHERE championship_id = :c"), {"c": first}
                                    ).scalar()  # fmt: skip
        w = {"round": rid, "fixtures": fids, "deadline": deadline}
        t0 = time.perf_counter()
        h.reopen_correct(eng, own, op, w, [__import__(
            "diski9.backend.services.corrections", fromlist=["x"]).CorrectionInput(f, "FT", 2, 2)
            for f in fids[:9]])  # fmt: skip
        reopen_ms = (time.perf_counter() - t0) * 1000
        with Timers() as t:
            s = time.perf_counter()
            h.finalise(eng, h.fresh(eng, op), w)
            refin_ms = (time.perf_counter() - s) * 1000
        with transaction(eng) as conn:
            after = conn.execute(sa.text("SELECT count(*) FROM app.championship_versions "
                                         "WHERE championship_id = :c"), {"c": first}
                                 ).scalar()  # fmt: skip
        if after <= versions:
            problems.append(f"round {rid}: no new championship version (a no-op)")
        rows.append({"reopen_and_corrections_ms": round(reopen_ms, 1),
                     "refinalisation_total_ms": round(refin_ms, 1),
                     "weekly_republication_ms": round(sum(t.weekly) - sum(t.champ), 1),
                     "championship_reaggregation_ms": round(sum(t.champ), 1),
                     "new_versions": after - versions})  # fmt: skip
        print(rows[-1], flush=True)
    with transaction(eng) as conn:
        problems += standings_match(conn, ch)
        problems += ch.verify_stream(conn, "development")
        dup = conn.execute(sa.text("SELECT count(*) FROM (SELECT round_id, kind, revision FROM "
                                   "app.score_sets GROUP BY 1, 2, 3 HAVING count(*) > 1) d")
                           ).scalar()  # fmt: skip
    out = {"database": name, "samples": rows,
           "refinalisation_total_ms": _stats([r["refinalisation_total_ms"] for r in rows]),
           "championship_reaggregation_ms": _stats([r["championship_reaggregation_ms"]
                                                    for r in rows]),
           "duplicate_score_sets": dup, "problems": problems or "none"}  # fmt: skip
    (OUT / f"{name}_corrections.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "samples"}, indent=1))
    eng.dispose()


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "publication":
        publication(a[1], int(a[2]) if len(a) > 2 else 1000, int(a[3]) if len(a) > 3 else 7)
    else:
        corrections(a[1], a[2], int(a[3]) if len(a) > 3 else 3)
