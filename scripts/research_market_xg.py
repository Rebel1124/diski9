"""Milestone 5.1 research: market-implied expected goals on cached odds.

Replays the committed odds-trial captures (monitoring/odds_trial/) into a scratch
copy of the database, then at each capture time fits the independent-Poisson
model to the fresh, snapshot-coherent consensus of every fixture that has not
kicked off. Read-only for production data; no API calls.

Run: uv run python scripts/research_market_xg.py
Writes docs/research/market_xg_fits.csv and docs/research/market_xg_summary.json
"""

from __future__ import annotations

import json
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from diski9.db import make_engine
from diski9.db.schema import fixtures, odds_fetches, odds_fixture_observations, odds_quotes
from diski9.odds.display import display_consensus
from diski9.odds.monitor import load_runs, replay
from diski9.research.form_score_comparison import write_csv
from diski9.research.market_implied_xg import MARKETS, fit, from_display, subset

OUT = Path("docs/research")
COMBOS = [("1x2",), ("ou25",), ("btts",), ("1x2", "ou25"), ("1x2", "btts"), ("1x2", "btts", "ou25")]


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1)))], 4)


def main() -> None:
    src = make_engine().url.database
    runs = load_runs()
    rows, names, finished = [], {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "replay.sqlite"
        shutil.copy(src, copy)
        eng = make_engine(f"sqlite:///{copy}")
        with eng.begin() as conn:
            for t in (odds_quotes, odds_fixture_observations, odds_fetches):
                conn.execute(t.delete())
            replay(conn, runs)
            fx = {
                r.id: r
                for r in conn.execute(
                    select(fixtures).where(fixtures.c.competition_id.in_([39, 288]))
                )
            }
            for run in runs:
                # evaluate at the capture's last page retrieval (run_at is stamped just before)
                retrieved = [
                    datetime.fromisoformat(p["retrieved_at"])
                    for e in run["competitions"].values()
                    for p in e["pages"]
                ]
                if not retrieved:
                    continue
                t = max(retrieved)
                ids = {
                    i["fixture"]["id"]
                    for e in run["competitions"].values()
                    for p in e["pages"]
                    for i in p["items"]
                }
                for fid in sorted(ids):
                    f = fx.get(fid)
                    if f is None or f.kickoff_utc <= t:  # never use odds at or after kickoff
                        continue
                    disp = display_consensus(conn, fid, t)
                    inputs = from_display(disp, fid)  # fresh, snapshot-coherent markets only
                    names[fid] = f"{f.home_team_id}-{f.away_team_id}"
                    finished[fid] = f.is_final
                    for combo in COMBOS:
                        res = fit(subset(inputs, combo))
                        rows.append(
                            {
                                "fixture_id": fid,
                                "captured_at": run["run_at"],
                                "kickoff": f.kickoff_utc.isoformat(),
                                "hours_to_kickoff": round(
                                    (f.kickoff_utc - t).total_seconds() / 3600, 1
                                ),
                                "markets": "+".join(combo),
                                "available": "+".join(inputs.available()),
                                "status": res.status,
                                "lambda_home": None
                                if res.lambda_home is None
                                else round(res.lambda_home, 4),
                                "lambda_away": None
                                if res.lambda_away is None
                                else round(res.lambda_away, 4),
                                "lambda_total": None
                                if res.lambda_total is None
                                else round(res.lambda_total, 4),
                                "max_abs_residual": None
                                if res.max_abs_residual is None
                                else round(res.max_abs_residual, 5),
                                **{
                                    f"res_{m}_{i}": (
                                        round(res.residuals[m][i], 5)
                                        if res.residuals and m in res.residuals
                                        else None
                                    )
                                    for m in MARKETS
                                    for i in range(3 if m == "1x2" else 2)
                                },
                                "smallest_singular_value": None
                                if not res.jacobian_singular_values
                                else round(res.jacobian_singular_values[-1], 4),
                                "at_boundary": res.at_boundary,
                                "converged": res.converged,
                                "sources_1x2": inputs.metadata["1X2"]["sources"],
                            }
                        )
        eng.dispose()
    write_csv(OUT / "market_xg_fits.csv", rows)

    full = [
        r for r in rows if r["markets"] == "1x2+btts+ou25" and r["available"] == "1x2+btts+ou25"
    ]
    summary = {
        "captures": len(runs),
        "fixtures": len({r["fixture_id"] for r in rows}),
        "snapshots_with_all_three_markets": len(full),
        "status_by_combination": {
            "+".join(c): dict(Counter(r["status"] for r in rows if r["markets"] == "+".join(c)))
            for c in COMBOS
        },
        "residuals_all_three": {
            "max_abs": {
                q: pct([r["max_abs_residual"] for r in full], q) for q in (0.1, 0.5, 0.75, 0.9, 1.0)
            },
            "draw_residual_mean": round(statistics.mean(r["res_1x2_1"] for r in full), 4)
            if full
            else None,
            "home_residual_mean": round(statistics.mean(r["res_1x2_0"] for r in full), 4)
            if full
            else None,
            "btts_yes_residual_mean": round(statistics.mean(r["res_btts_0"] for r in full), 4)
            if full
            else None,
            "over_residual_mean": round(statistics.mean(r["res_ou25_0"] for r in full), 4)
            if full
            else None,
        },
        "lambda_ranges_all_three": {
            k: [
                min(r[k] for r in full),
                round(statistics.median(r[k] for r in full), 3),
                max(r[k] for r in full),
            ]
            for k in ("lambda_home", "lambda_away", "lambda_total")
        }
        if full
        else None,
        "smallest_singular_value_median": {
            "+".join(c): pct(
                [
                    r["smallest_singular_value"]
                    for r in rows
                    if r["markets"] == "+".join(c) and r["smallest_singular_value"] is not None
                ],
                0.5,
            )
            for c in COMBOS
        },
    }
    # sensitivity to market combination (vs the all-three fit at the same snapshot)
    ref = {(r["fixture_id"], r["captured_at"]): r for r in full}
    sens = defaultdict(list)
    for r in rows:
        k = (r["fixture_id"], r["captured_at"])
        if k in ref and r["lambda_home"] is not None and r["markets"] != "1x2+btts+ou25":
            sens[r["markets"]].append(
                max(
                    abs(r["lambda_home"] - ref[k]["lambda_home"]),
                    abs(r["lambda_away"] - ref[k]["lambda_away"]),
                )
            )
    summary["combination_sensitivity_max_abs_lambda_change"] = {
        m: {"median": pct(v, 0.5), "p90": pct(v, 0.9)} for m, v in sens.items()
    }
    # stability across capture times (all-three fits, per fixture)
    per_fx = defaultdict(list)
    for r in full:
        per_fx[r["fixture_id"]].append(r)
    stab = [
        {
            "fixture_id": f,
            "snapshots": len(v),
            "lambda_home_range": round(
                max(x["lambda_home"] for x in v) - min(x["lambda_home"] for x in v), 3
            ),
            "lambda_away_range": round(
                max(x["lambda_away"] for x in v) - min(x["lambda_away"] for x in v), 3
            ),
        }
        for f, v in per_fx.items()
        if len(v) > 1
    ]
    summary["stability_across_captures"] = {
        "fixtures": len(stab),
        "median_home_range": pct([s["lambda_home_range"] for s in stab], 0.5),
        "max_home_range": pct([s["lambda_home_range"] for s in stab], 1.0),
        "median_away_range": pct([s["lambda_away_range"] for s in stab], 0.5),
        "max_away_range": pct([s["lambda_away_range"] for s in stab], 1.0),
    }
    summary["outcome_validation"] = {
        "fixtures_with_pre_kickoff_odds_and_final_result": sum(
            1 for f, done in finished.items() if done
        ),
        "note": "insufficient for outcome validation" if sum(finished.values()) < 100 else "",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "market_xg_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
