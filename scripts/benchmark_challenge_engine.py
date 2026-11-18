"""Benchmarks for the Phase 6A.3 engines (pure Python, single process).

    uv run python scripts/benchmark_challenge_engine.py

Uses the real 17 Nov 2026 weekend pool (60 eligible fixtures, 6 leagues) from
``docs/research/weekly_challenge_risk/pool_weekend.json``. Reports the median of
repeated timings.
"""

from __future__ import annotations

import json
import random
import statistics
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from diski9.challenge.config import BROAD60_432_V1 as CFG
from diski9.challenge.scoring import (
    POINTS_150_75_V2,
    EntryResult,
    RoundClassification,
    RoundResult,
    aggregate_championship,
    score_round,
)
from diski9.challenge.structured import (
    assess_outcome,
    evaluate_market_and_model,
    evaluate_portfolio,
    make_outcome,
    portfolio_feasible,
    portfolio_progress,
    round_opening_report,
    validate_portfolio,
)

ROOT = Path(__file__).resolve().parents[1]
POOL = json.loads((ROOT / "docs/research/weekly_challenge_risk/pool_weekend.json").read_text())
SNAP = datetime.fromisoformat(POOL["as_of"])


def outcomes():
    out = []
    for f in POOL["fixtures"]:
        for o in f["outcomes"]:
            if o["odds"] is not None:
                out.append(
                    make_outcome(
                        f["fixture_id"],
                        o["market"],
                        o["outcome"],
                        o["p_market"],
                        o["odds"],
                        o["p_model"],
                        o["groups"],
                        SNAP,
                        f["league_id"],
                    )
                )
    return out


def timeit(fn, repeat=50):
    ts = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return statistics.median(ts) * 1000


def main():
    pool = outcomes()
    rng = random.Random(1)
    elig = [o for o in pool if assess_outcome(o, SNAP).eligible]
    by = {c: [o for o in elig if CFG.classify(o.market_probability) == c] for c in "ABC"}
    while True:
        used, sel = set(), []
        for c, n in zip("ABC", (4, 3, 2), strict=True):
            for o in rng.sample([o for o in by[c] if o.fixture_id not in used], n):
                sel.append(o)
                used.add(o.fixture_id)
        if len(used) == 9:
            break
    port = validate_portfolio(sel, SNAP)
    rows = [
        (
            "validate complete portfolio (with pool check)",
            timeit(lambda: validate_portfolio(sel, SNAP, pool=pool)),
        ),
        ("evaluate portfolio, market only", timeit(lambda: evaluate_portfolio(port))),
        ("evaluate portfolio, market + model", timeit(lambda: evaluate_market_and_model(port))),
        ("payout distribution", timeit(lambda: evaluate_portfolio(port).distribution())),
        (
            f"partial progress + completability ({len(pool)} outcomes)",
            timeit(lambda: portfolio_progress(sel[:4], SNAP, pool=pool)),
        ),
        ("full-pool strict feasibility", timeit(lambda: portfolio_feasible(pool, SNAP))),
        ("round-opening report", timeit(lambda: round_opening_report(pool, SNAP))),
    ]
    v = POINTS_150_75_V2.version
    for n in (25, 100, 500, 1000):
        ents = tuple(
            EntryResult(f"u{i}", Decimal(rng.choice([0, 0, 80, 100, 145, 238, 400])))
            for i in range(n)
        )
        r = RoundResult("r", "c", RoundClassification.COMPETITIVE, ents, v)
        rows.append(
            (f"weekly ranking + points, {n} entrants", timeit(lambda r=r: score_round(r), 20))
        )
        rounds = [
            RoundResult(
                f"r{k}",
                "c",
                RoundClassification.COMPETITIVE,
                tuple(
                    EntryResult(e.participant_id, Decimal(rng.choice([0, 80, 100, 145, 400])))
                    for e in ents
                ),
                v,
            )
            for k in range(10)
        ]
        rows.append(
            (
                f"ten-round championship, {n} entrants",
                timeit(lambda rounds=rounds: aggregate_championship("c", rounds), 5),
            )
        )
    width = max(len(name) for name, _ in rows)
    print(f"{'operation':<{width}}  median ms")
    for name, ms in rows:
        print(f"{name:<{width}}  {ms:9.3f}")


if __name__ == "__main__":
    main()
