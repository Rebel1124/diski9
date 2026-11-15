"""Validate the current-season benchmark threshold (spec 4.7).

The venue-adjusted difference depends on the benchmarks only through the gap
G = (league home Form Score - league away Form Score). For each completed
season with a stored previous season, compare:

* error of the current-season partial gap after the first N eligible matches
  vs the full-season gap, and
* error of the previous season's full gap vs this season's full gap
  (what the fallback would have used).

The threshold is the smallest N from which the mean partial-season error stays
at or below the mean previous-season fallback error for every larger N tested.

Run: uv run python scripts/validate_benchmark_threshold.py [--out FILE]
"""

from __future__ import annotations

import argparse
import json
from statistics import mean

from diski9.db import make_engine
from diski9.screener.calc import pooled_benchmark
from diski9.screener.engine import MatchStore

GRID = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 150]


def gap(cid, season, matches):
    b = pooled_benchmark(cid, season, ((m.home_goals, m.away_goals) for m in matches))
    return float(b.home.score - b.away.score) if b else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/benchmark_threshold_validation.json")
    args = ap.parse_args()
    with make_engine().connect() as c:
        store = MatchStore(c)
    samples = []
    for (cid, season), matches in sorted(store.by_comp_season.items()):
        prev = store.by_comp_season.get((cid, season - 1))
        if not prev or season >= 2026:  # need a previous season and a completed season
            continue
        matches = sorted(
            (m for m in matches if m.venue_classification != "neutral"), key=lambda m: m.kickoff
        )
        full = gap(cid, season, matches)
        prev_err = abs(gap(cid, season - 1, prev) - full)
        partial = {n: abs(gap(cid, season, matches[:n]) - full) for n in GRID if n <= len(matches)}
        samples.append(
            {
                "competition_id": cid,
                "season": season,
                "matches": len(matches),
                "full_gap": round(full, 4),
                "previous_season_error": round(prev_err, 4),
                "partial_error": {n: round(e, 4) for n, e in partial.items()},
            }
        )
    curve = {
        n: round(mean(s["partial_error"][n] for s in samples if n in s["partial_error"]), 4)
        for n in GRID
    }
    prev_mean = round(mean(s["previous_season_error"] for s in samples), 4)
    # smallest N from which the partial-season error stays <= the fallback error
    threshold = next(
        (n for i, n in enumerate(GRID) if all(curve[m] <= prev_mean for m in GRID[i:])), None
    )
    report = {
        "samples": samples,
        "mean_partial_error_by_n": curve,
        "mean_previous_season_error": prev_mean,
        "suggested_threshold": threshold,
    }
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, indent=2))


if __name__ == "__main__":
    main()
