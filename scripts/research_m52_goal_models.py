"""Milestone 5.2 research: market-implied goal expectations, Poisson vs Dixon-Coles.

Replays the committed odds-trial captures (monitoring/odds_trial/) into a scratch
copy of the database, fits every model / market configuration to each fresh
pre-kickoff snapshot, runs identifiability and sensitivity checks, and runs the
result-validation pipeline (on the trial replay and on the main database).

Run: uv run python scripts/research_m52_goal_models.py
Writes docs/research/m52/goal_models_*.{json,csv}. No API calls; read-only for
production data.
"""

from __future__ import annotations

import json
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import select

from diski9.db import make_engine
from diski9.db.schema import fixtures, odds_fetches, odds_fixture_observations, odds_quotes
from diski9.odds.display import display_consensus
from diski9.odds.monitor import load_runs, replay
from diski9.research.form_score_comparison import write_csv
from diski9.research.goal_models import Spec, fit_market, perturb_price
from diski9.research.market_implied_xg import from_display
from diski9.research.result_validation import collect_records, evaluate

OUT = Path("docs/research/m52")
CONFIGS = (("1x2",), ("1x2", "ou25"), ("1x2", "btts"), ("1x2", "btts", "ou25"))
RHO_GRID = np.round(np.arange(-0.25, 0.2501, 0.01), 4)


def pct(values, q):
    s = sorted(v for v in values if v is not None)
    if not s:
        return None
    return round(s[min(len(s) - 1, int(q * (len(s) - 1)))], 4)


def smean(values):
    values = list(values)
    return round(statistics.mean(values), 4) if values else None


def err(sel, market):
    return [
        r[f"model_{market}_0"] - r[f"market_{market}_0"]
        for r in sel
        if r[f"model_{market}_0"] is not None and r[f"market_{market}_0"] is not None
    ]


def snapshots(conn, runs):
    """(fixture, capture time, fresh market probabilities, metadata) for every
    fixture not yet kicked off at each capture's last page retrieval."""
    fx = {r.id: r for r in conn.execute(select(fixtures))}
    out = []
    for run in runs:
        times = [
            datetime.fromisoformat(p["retrieved_at"])
            for e in run["competitions"].values()
            for p in e["pages"]
        ]
        if not times:
            continue
        t = max(times)
        ids = {
            i["fixture"]["id"]
            for e in run["competitions"].values()
            for p in e["pages"]
            for i in p["items"]
        }
        for fid in sorted(ids):
            f = fx.get(fid)
            if f is None or f.kickoff_utc <= t:
                continue
            inputs = from_display(display_consensus(conn, fid, t), fid)
            if inputs.available():
                out.append((f, t, inputs.available(), inputs.metadata))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    src = make_engine().url.database
    runs = load_runs()
    summary: dict = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "captures": len(runs),
    }
    hist = json.loads((OUT / "goals_summary.json").read_text())
    rho_hist = hist["dc_rho_by_league_pre_test"]["EPL"]
    summary["rho_historical_epl"] = rho_hist

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "replay.sqlite"
        shutil.copy(src, copy)
        eng = make_engine(f"sqlite:///{copy}")
        with eng.begin() as conn:
            for t in (odds_quotes, odds_fixture_observations, odds_fetches):
                conn.execute(t.delete())
            replay(conn, runs)
            snaps = snapshots(conn, runs)
            trial_records = collect_records(conn)
        eng.dispose()

    summary["snapshots"] = len(snaps)
    summary["fixtures"] = len({f.id for f, *_ in snaps})
    summary["market_coverage"] = dict(Counter("+".join(sorted(m)) for _, _, m, _ in snaps))
    summary["sources_1x2"] = dict(Counter(meta["1X2"]["sources"] for *_, meta in snaps))
    summary["provider_timestamps"] = sorted(
        {
            meta["1X2"]["provider_updated_at"]
            for *_, meta in snaps
            if meta["1X2"]["provider_updated_at"]
        }
    )

    # ---- latest snapshot per fixture: pooled rho from the market (profile)
    latest = {}
    for f, t, m, meta in snaps:
        if f.id not in latest or t > latest[f.id][1]:
            latest[f.id] = (f, t, m, meta)
    full_latest = {k: v for k, v in latest.items() if len(v[2]) == 3}
    prof = defaultdict(dict)  # fixture -> rho -> objective
    for fid, (_, _, m, _) in full_latest.items():
        for r in RHO_GRID:
            prof[fid][float(r)] = fit_market(m, Spec("dc_fixed", float(r))).objective_value
    total = {float(r): sum(prof[f][float(r)] for f in prof) for r in RHO_GRID}
    rho_market = min(total, key=total.get)
    summary["rho_market_pooled"] = rho_market
    summary["rho_market_profile"] = {
        f"{k:+.2f}": round(v, 6) for k, v in total.items() if abs(k * 100) % 5 == 0
    }
    # leave-one-fixture-out: is the pooled rho a genuine improvement on unseen fixtures?
    loo = []
    for fid, (_, _, m, _) in full_latest.items():
        others = {r: sum(prof[g][r] for g in prof if g != fid) for r in total}
        r_loo = min(others, key=others.get)
        pois = fit_market(m, Spec("poisson"))
        dc = fit_market(m, Spec("dc_fixed", r_loo))
        loo.append(
            {
                "fixture_id": fid,
                "rho_loo": r_loo,
                "poisson_max_err": round(pois.max_abs_error, 5),
                "dc_max_err": round(dc.max_abs_error, 5),
                "poisson_draw_err": round(pois.model["1x2"][1] - m["1x2"][1], 5),
                "dc_draw_err": round(dc.model["1x2"][1] - m["1x2"][1], 5),
                "poisson_kl": round(pois.objective_value, 6),
                "dc_kl": round(dc.objective_value, 6),
            }
        )
    write_csv(OUT / "goal_models_loo_pooled_rho.csv", loo)
    summary["loo_pooled_rho"] = {
        "fixtures": len(loo),
        "rho_range": [min(x["rho_loo"] for x in loo), max(x["rho_loo"] for x in loo)],
        "dc_better_max_err": sum(x["dc_max_err"] < x["poisson_max_err"] for x in loo),
        "median_max_err": {
            "poisson": round(statistics.median(x["poisson_max_err"] for x in loo), 4),
            "dc": round(statistics.median(x["dc_max_err"] for x in loo), 4),
        },
        "mean_draw_err": {
            "poisson": round(statistics.mean(x["poisson_draw_err"] for x in loo), 4),
            "dc": round(statistics.mean(x["dc_draw_err"] for x in loo), 4),
        },
        "mean_kl": {
            "poisson": round(statistics.mean(x["poisson_kl"] for x in loo), 6),
            "dc": round(statistics.mean(x["dc_kl"] for x in loo), 6),
        },
    }

    # ---- every snapshot x configuration x model
    specs = [
        Spec("poisson", objective="kl"),
        Spec("poisson", objective="sq"),
        Spec("dc_fixed", rho_hist),
        Spec("dc_fixed", rho_market),
        Spec("dc_free"),
    ]
    rows = []
    for f, t, m, meta in snaps:
        for config in CONFIGS:
            if not all(c in m for c in config):
                continue
            sub = {c: m[c] for c in config}
            for spec in specs:
                fit = fit_market(sub, spec)
                row = {
                    "fixture_id": f.id,
                    "snapshot_at": t.isoformat(),
                    "provider_updated_at": meta["1X2"]["provider_updated_at"],
                    "hours_to_kickoff": round((f.kickoff_utc - t).total_seconds() / 3600, 1),
                    "sources_1x2": meta["1X2"]["sources"],
                    "config": "+".join(config),
                    "model": spec.label,
                    "status": fit.status,
                    "lambda_home": None if fit.lambda_home is None else round(fit.lambda_home, 4),
                    "lambda_away": None if fit.lambda_away is None else round(fit.lambda_away, 4),
                    "lambda_total": None
                    if fit.lambda_total is None
                    else round(fit.lambda_total, 4),
                    "rho": None if fit.rho is None else round(fit.rho, 4),
                    "max_abs_error": None
                    if fit.max_abs_error is None
                    else round(fit.max_abs_error, 5),
                    "mean_abs_error": None
                    if fit.mean_abs_error is None
                    else round(fit.mean_abs_error, 5),
                    "converged": fit.converged,
                    "start_spread": None
                    if fit.start_spread is None
                    else round(fit.start_spread, 5),
                    "sv_min": None
                    if not fit.singular_values
                    else round(fit.singular_values[-1], 5),
                    "sv_ratio": None
                    if not fit.singular_values
                    else round(fit.singular_values[-1] / fit.singular_values[0], 5),
                }
                for mk, n in (("1x2", 3), ("btts", 2), ("ou25", 2)):
                    for i in range(n):
                        row[f"market_{mk}_{i}"] = round(m[mk][i], 5) if mk in m else None
                        row[f"model_{mk}_{i}"] = round(fit.model[mk][i], 5) if fit.model else None
                rows.append(row)
    write_csv(OUT / "goal_models_fits.csv", rows)

    agg = {}
    for config in CONFIGS:
        c = "+".join(config)
        for spec in specs:
            sel = [r for r in rows if r["config"] == c and r["model"] == spec.label]
            if not sel:
                continue
            usable = [r for r in sel if r["status"] in ("good_fit", "approximate_fit")]
            draw_err = [
                r["model_1x2_1"] - r["market_1x2_1"] for r in sel if r["model_1x2_1"] is not None
            ]
            agg[f"{c} | {spec.label}"] = {
                "snapshots": len(sel),
                "status": dict(Counter(r["status"] for r in sel)),
                "max_err_median": pct([r["max_abs_error"] for r in sel], 0.5),
                "max_err_p90": pct([r["max_abs_error"] for r in sel], 0.9),
                "mean_abs_err_median": pct([r["mean_abs_error"] for r in sel], 0.5),
                "draw_err_mean": smean(draw_err),
                "btts_err_mean": smean(err(sel, "btts")),
                "over_err_mean": smean(err(sel, "ou25")),
                "lambda_home_median": pct([r["lambda_home"] for r in usable], 0.5),
                "lambda_away_median": pct([r["lambda_away"] for r in usable], 0.5),
                "rho_range": [
                    min(r["rho"] for r in sel if r["rho"] is not None),
                    max(r["rho"] for r in sel if r["rho"] is not None),
                ]
                if spec.model == "dc_free" and any(r["rho"] is not None for r in sel)
                else None,
                "sv_ratio_median": pct([r["sv_ratio"] for r in sel], 0.5),
                "start_spread_max": pct([r["start_spread"] for r in sel], 1.0),
            }
    summary["fit_summary"] = agg

    # ---- lambda shift vs the all-three Poisson fit (same snapshot)
    ref = {
        (r["fixture_id"], r["snapshot_at"]): r
        for r in rows
        if r["config"] == "1x2+btts+ou25" and r["model"] == "poisson/kl"
    }
    shift = defaultdict(list)
    for r in rows:
        k = (r["fixture_id"], r["snapshot_at"])
        if k in ref and r["lambda_home"] is not None and r is not ref[k]:
            shift[f"{r['config']} | {r['model']}"].append(
                max(
                    abs(r["lambda_home"] - ref[k]["lambda_home"]),
                    abs(r["lambda_away"] - ref[k]["lambda_away"]),
                )
            )
    summary["lambda_shift_vs_poisson_all_three"] = {
        k: {"median": pct(v, 0.5), "p90": pct(v, 0.9)} for k, v in shift.items()
    }

    # ---- sensitivity: each price moved by +/-1%, latest snapshot per fixture
    sens = defaultdict(list)
    for _f, _t, m, meta in full_latest.values():
        prices = {
            "1x2": tuple(float(meta["1X2"]["prices"][o]) for o in ("HOME", "DRAW", "AWAY")),
            "btts": tuple(float(meta["BTTS"]["prices"][o]) for o in ("BTTS_YES", "BTTS_NO")),
            "ou25": tuple(float(meta["OU25"]["prices"][o]) for o in ("OVER_2_5", "UNDER_2_5")),
        }
        for config in CONFIGS:
            for spec in (Spec("poisson"), Spec("dc_fixed", rho_market), Spec("dc_free")):
                base = fit_market({c: m[c] for c in config}, spec)
                if not base.usable and base.status != "unidentified":
                    continue
                if base.lambda_home is None:
                    continue
                worst_l, worst_r = 0.0, 0.0
                for mk in config:
                    for i in range(len(prices[mk])):
                        for rel in (-0.01, 0.01):
                            pert = {c: m[c] for c in config}
                            pert[mk] = perturb_price(prices[mk], i, rel)
                            p = fit_market(pert, spec)
                            if p.lambda_home is None:
                                continue
                            worst_l = max(
                                worst_l,
                                abs(p.lambda_home - base.lambda_home),
                                abs(p.lambda_away - base.lambda_away),
                            )
                            worst_r = max(worst_r, abs((p.rho or 0) - (base.rho or 0)))
                sens[f"{'+'.join(config)} | {spec.label}"].append((worst_l, worst_r, base.status))
    summary["sensitivity_1pct_price"] = {
        k: {
            "fixtures": len(v),
            "max_lambda_change_median": pct([x[0] for x in v], 0.5),
            "max_lambda_change_max": pct([x[0] for x in v], 1.0),
            "max_rho_change_median": pct([x[1] for x in v], 0.5),
            "max_rho_change_max": pct([x[1] for x in v], 1.0),
        }
        for k, v in sens.items()
    }
    # price check: the meta keys above must match production outcome names
    # (asserted implicitly: a KeyError would stop the run)

    # ---- dc_free rho profile flatness on the latest all-three snapshots
    flat = []
    for fid in prof:
        p = prof[fid]
        best = min(p, key=p.get)
        within = [r for r, v in p.items() if v - p[best] <= 1e-5]
        flat.append(
            {
                "fixture_id": fid,
                "rho_best_grid": best,
                "rho_within_1e-5": [min(within), max(within)],
            }
        )
    summary["rho_profile_flatness"] = {
        "fixtures": len(flat),
        "best_rho_range": [
            min(x["rho_best_grid"] for x in flat),
            max(x["rho_best_grid"] for x in flat),
        ],
        "median_width_within_1e-5": pct(
            [x["rho_within_1e-5"][1] - x["rho_within_1e-5"][0] for x in flat], 0.5
        ),
    }

    # ---- worked examples: latest snapshot, all three markets
    examples = []
    for fid, (f, t, m, meta) in sorted(full_latest.items())[:20]:
        fp = fit_market(m, Spec("poisson"))
        fd = fit_market(m, Spec("dc_fixed", rho_market))
        examples.append(
            {
                "fixture_id": fid,
                "home_team_id": f.home_team_id,
                "away_team_id": f.away_team_id,
                "snapshot_at": t.isoformat(),
                "prices": {k: meta[k]["prices"] for k in ("1X2", "BTTS", "OU25")},
                "market": {k: [round(x, 4) for x in v] for k, v in m.items()},
                "poisson": {
                    "lambda": [round(fp.lambda_home, 3), round(fp.lambda_away, 3)],
                    "model": {k: [round(x, 4) for x in v] for k, v in fp.model.items()},
                    "max_err": round(fp.max_abs_error, 4),
                    "status": fp.status,
                },
                "dc_pooled": {
                    "lambda": [round(fd.lambda_home, 3), round(fd.lambda_away, 3)],
                    "rho": fd.rho,
                    "model": {k: [round(x, 4) for x in v] for k, v in fd.model.items()},
                    "max_err": round(fd.max_abs_error, 4),
                    "status": fd.status,
                },
            }
        )
    summary["examples"] = examples

    # ---- validation against results (trial replay + main database)
    with make_engine().connect() as conn:
        main_records = collect_records(conn)
    merged = {r.fixture_id: r for r in trial_records}
    for r in main_records:
        if r.fixture_id not in merged or r.snapshot_at > merged[r.fixture_id].snapshot_at:
            merged[r.fixture_id] = r
    val_specs = (Spec("poisson"), Spec("dc_fixed", rho_market), Spec("dc_fixed", rho_hist))
    summary["result_validation"] = evaluate(list(merged.values()), val_specs)
    summary["result_validation"]["sources"] = {
        "trial_replay_records": len(trial_records),
        "main_database_records": len(main_records),
    }
    (OUT / "goal_models_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("examples", "fit_summary")},
            indent=1,
            default=str,
        )
    )
    for k, v in agg.items():
        print(k, v)


if __name__ == "__main__":
    main()
