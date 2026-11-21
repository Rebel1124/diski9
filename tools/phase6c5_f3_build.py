# ruff: noqa: B023  (closures are called immediately inside each loop iteration)
"""Phase 6C.5 Stage F3: realistic benchmark datasets on isolated PostgreSQL databases
(local development only), built through the real services with the existing test
factories (``tests/backend/champ_helpers.py``), not the F1 runner (whose
500-participant safeguard is left unchanged).

    uv run python tools/phase6c5_f3_build.py create   URL NAME
    uv run python tools/phase6c5_f3_build.py populate URL NAME N [ACCOUNTS_JSON]
    uv run python tools/phase6c5_f3_build.py history  URL NAME

``create`` makes and migrates database ``NAME`` (refused unless it starts with
``diski9_f3_``). ``populate`` adds N participants (plus the onboarded local test
accounts in ACCOUNTS_JSON, so they can sign in for the HTTP tests) and 13 development
rounds:

* R1–R10 competitive and final: the first championship completes (10 counted).
* R11 final: the second championship starts (rollover).
* R12 settled, not finalised (provisional).
* R13 locked and settled, held unfinalised for the concurrent-publication test.

About 85 % of participants enter each round (so some miss rounds), with varied
portfolios: full winners (about 1 in 9), partly void winners (varied returns),
several losing portfolios shared by many entrants (weekly and championship ties),
and all-void refunds (about 1 %). The finalisations of R1–R11 are timed, split into
the weekly publication and the championship processing (wrapping the real
functions), and written to ``tmp/f3/<NAME>_build.json`` with the integrity counts.

``history`` builds the History benchmark: one participant with 50 entries (50
rounds of five entrants, five championships).
"""

from __future__ import annotations

import json
import os
import random
import statistics
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "backend"))
OUT = ROOT / "tmp" / "f3"

import sqlalchemy as sa  # noqa: E402


def _url(base: str, name: str) -> str:
    from sqlalchemy.engine import make_url

    if not name.startswith("diski9_f3_"):
        raise SystemExit("refused: F3 databases must be named diski9_f3_*")
    return make_url(base).set(database=name).render_as_string(hide_password=False)


def _engine(base: str, name: str):
    from diski9.backend.db import BackendDatabaseSettings, make_app_engine

    return make_app_engine(BackendDatabaseSettings(environment="development",
                                                   lock_timeout_ms=10000),
                           url=_url(base, name))  # fmt: skip


def create(base: str, name: str) -> None:
    import champ_helpers as h

    _url(base, name)
    eng, _ = h.isolated_engine(base, name)
    eng.dispose()
    print(f"created and migrated {name}")


def counts(eng) -> dict:
    with eng.connect() as conn:
        q = lambda s: conn.execute(sa.text(s)).scalar()  # noqa: E731
        return {
            "participants": q("SELECT count(*) FROM app.profiles"),
            "entries_locked": q("SELECT count(*) FROM app.entries WHERE locked_at IS NOT NULL"),
            "rounds": q("SELECT count(*) FROM app.rounds"),
            "score_sets": q("SELECT count(*) FROM app.score_sets"),
            "round_score_rows": q("SELECT count(*) FROM app.round_scores"),
            "championships": q("SELECT count(*) FROM app.championships"),
            "championship_versions": q("SELECT count(*) FROM app.championship_versions"),
            "standing_rows": q("SELECT count(*) FROM app.championship_standings"),
            "duplicate_score_sets": q(
                "SELECT count(*) FROM (SELECT round_id, kind, revision FROM app.score_sets "
                "GROUP BY 1, 2, 3 HAVING count(*) > 1) d"),
            "duplicate_memberships": q(
                "SELECT count(*) FROM (SELECT round_id FROM app.championship_rounds "
                "GROUP BY 1 HAVING count(*) > 1) d"),
        }  # fmt: skip


def portfolio(rng, h, i, variants):
    x = rng.random()
    if x < 0.01:
        return h.REFUND
    if x < 0.11:
        return h.WIN
    if x < 0.25:
        return variants[i % len(variants)]
    if x < 0.55:
        return h.lose(1 + i % 3)  # few shared losing portfolios: ties
    return h.lose(i)


def populate(base: str, name: str, n: int, accounts: str | None = None) -> None:
    import champ_helpers as h
    from pg_helpers import make_user

    from diski9.backend.db import transaction
    from diski9.backend.services import championships as ch
    from diski9.backend.services import competition as comp

    eng = _engine(base, name)
    rng = random.Random(2026 + n)
    t0 = time.perf_counter()
    with transaction(eng) as conn:
        people = [make_user(conn, f"bench{k:05d}") for k in range(n)]
        mine = []
        if accounts:
            for a in json.loads(Path(accounts).read_text()).values():
                uid = conn.execute(
                    sa.text("SELECT user_id FROM app.user_identities WHERE subject = :s"),
                    {"s": a["sub"]},
                ).scalar_one()
                mine.append(uid)  # fmt: skip
    everyone = people + mine
    win = list(h.WIN)
    variants = [
        tuple(win[:7] + [(9, "1X2", "AWAY"), (10, "1X2", "AWAY")]),
        tuple(win[:4] + [(9, "BTTS", "BTTS_YES"), (10, "BTTS", "BTTS_YES"),
                         (11, "OU25", "UNDER_2_5")] + win[7:]),
        tuple([(9 + j, "1X2", "HOME") for j in range(4)] + win[4:]),
    ]  # fmt: skip
    plan = []
    for _ in range(13):
        ents = [(u, portfolio(rng, h, i, variants)) for i, u in enumerate(everyone)
                if u in mine or rng.random() < 0.85]  # fmt: skip
        plan.append(ents)
    users_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    op = h.operator(eng)
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=8))
    build_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    for w in made:
        h.results(eng, op, w, h.winner)
    for w in made:
        h.settle(eng, op, w)
    settle_s = time.perf_counter() - t0

    weekly, champ, fin = [], [], []
    real_publish, real_event = comp.publish_finalised, ch.on_round_event

    def pub(*a, **k):
        t = time.perf_counter()
        try:
            return real_publish(*a, **k)
        finally:
            weekly.append((time.perf_counter() - t) * 1000)

    def evt(*a, **k):
        t = time.perf_counter()
        try:
            return real_event(*a, **k)
        finally:
            champ.append((time.perf_counter() - t) * 1000)

    comp.publish_finalised, ch.on_round_event = pub, evt
    try:
        for w in made[:11]:
            t = time.perf_counter()
            h.finalise(eng, h.fresh(eng, op), w)
            fin.append((time.perf_counter() - t) * 1000)
    finally:
        comp.publish_finalised, ch.on_round_event = real_publish, real_event
    with transaction(eng) as conn:
        problems = ch.verify_stream(conn, "development")
        codes = [conn.execute(sa.text("SELECT code FROM app.rounds WHERE id = :r"),
                              {"r": w["round"]}).scalar_one() for w in made]  # fmt: skip
    rows = [{"round": k + 1, "entries": len(plan[k]), "finalisation_ms": round(fin[k], 1),
             "weekly_publication_ms": round(weekly[k] - champ[k], 1),
             "championship_processing_ms": round(champ[k], 1)} for k in range(11)]  # fmt: skip
    out = {
        "database": name, "participants": n, "accounts": len(mine),
        "phases_s": {"users": round(users_s, 1), "entries_and_lock": round(build_s, 1),
                     "results_and_settlement": round(settle_s, 1)},
        "finalisations": rows, "codes": codes,
        "rounds": {"R12": "provisional (settled, not final)", "R13": "settled, held for F3 "
                   "concurrent publication"},
        "user_ids_sample": [str(u) for u in people[:: max(1, n // 20)]][:20],
        "account_ids": [str(u) for u in mine],
        "integrity": {"verify": problems or "consistent", **counts(eng)},
    }  # fmt: skip
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}_build.json").write_text(json.dumps(out, indent=1, default=str))
    w = [r["weekly_publication_ms"] for r in rows]
    c = [r["championship_processing_ms"] for r in rows]
    print(
        json.dumps(out["phases_s"]),
        "| weekly publication median",
        round(statistics.median(w)),
        "ms | championship processing median",
        round(statistics.median(c)),
        "ms | R10",
        rows[9],
        "| integrity",
        out["integrity"],
    )
    eng.dispose()


def live(base: str, name: str) -> None:
    """Add one genuinely published open development round (a valid frozen snapshot,
    published by the services) in which the onboarded test accounts confirm entries
    through the draft and entry services, so My Challenge Current and its account
    hydration can be measured on real page data. The factory rounds above carry
    placeholder snapshot hashes, which the snapshot loader rightly rejects."""
    import champ_helpers as h
    from svc_helpers import principal, publish_dev

    from diski9.backend import settlement_scenarios as sc

    eng = _engine(base, name)
    meta_p = OUT / f"{name}_build.json"
    meta = json.loads(meta_p.read_text())
    op = h.operator(eng)
    view, _ = publish_dev(eng, op, deadline_in=timedelta(hours=12), seed=4141, fixtures=40)
    for k, uid in enumerate(meta["account_ids"]):
        sc.submit_test_entry(eng, principal(eng, user_id=uuid.UUID(uid)), view.id, variant=k)
    meta["live_round"] = {"code": view.code, "entries": len(meta["account_ids"]),
                          "deadline_at": str(view.deadline_at)}  # fmt: skip
    meta_p.write_text(json.dumps(meta, indent=1, default=str))
    print("live round", view.code, "with", len(meta["account_ids"]), "entries")
    eng.dispose()


def history(base: str, name: str) -> None:
    import champ_helpers as h

    from diski9.backend.db import transaction

    eng = _engine(base, name)
    with transaction(eng) as conn:
        from pg_helpers import make_user

        me = make_user(conn, "historian")
        others = [make_user(conn, f"other{k}") for k in range(4)]
    plan = [
        [(me, h.WIN if k % 3 == 0 else h.lose(k))]
        + [(u, h.lose(j + k)) for j, u in enumerate(others)]
        for k in range(50)
    ]
    op = h.operator(eng)
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=8))
    h.prepare(eng, op, made)
    for w in made:
        h.finalise(eng, h.fresh(eng, op), w)
    from diski9.backend.services import championships as ch

    with transaction(eng) as conn:
        problems = ch.verify_stream(conn, "development")
    OUT.mkdir(parents=True, exist_ok=True)
    out = {
        "database": name,
        "viewer": str(me),
        "entries": 50,
        "integrity": {"verify": problems or "consistent", **counts(eng)},
    }
    (OUT / f"{name}_build.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out["integrity"]))
    eng.dispose()


if __name__ == "__main__":
    a = sys.argv[1:]
    os.environ.setdefault("DISKI9_APP_ENVIRONMENT", "development")
    {"create": lambda: create(a[1], a[2]),
     "populate": lambda: populate(a[1], a[2], int(a[3]), a[4] if len(a) > 4 else None),
     "live": lambda: live(a[1], a[2]),
     "history": lambda: history(a[1], a[2])}[a[0]]()  # fmt: skip
