"""Milestone 5.2 research: BTTS / Over 2.5 historical indicators and the
historical goal-rate model (Poisson vs Dixon-Coles) against actual results.

Run: uv run python scripts/research_m52_goals.py
Writes docs/research/m52/goals_*.{json,csv,svg}. Read-only; no API calls.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import numpy as np

from diski9.db import make_engine
from diski9.research.charts import calibration_panels
from diski9.research.evaluation import (
    auc,
    brier_binary,
    brier_multiclass,
    calibration_table,
    expected_calibration_error,
    fit_logistic,
    iso_week,
    log_loss_binary,
    log_loss_multiclass,
    monthly_folds,
    paired_bootstrap,
)
from diski9.research.form_score_comparison import write_csv
from diski9.research.goal_models import probabilities
from diski9.research.historical_goals import build_rows, fit_rho
from diski9.screener.engine import MatchStore

OUT = Path("docs/research/m52")
COMPS = (39, 40, 288, 289)
LEAGUE = {39: "EPL", 40: "Championship", 288: "PSL", 289: "PSL 1st Div"}
FIRST_TEST = datetime(2024, 8, 1, tzinfo=UTC)
SIZE_BANDS = [(1, 2), (3, 5), (6, 9), (10, 10)]
IND_BANDS = [0, 0.2, 0.4, 0.6, 0.8, 1.0001]
CLIP = 0.02  # raw indicator can be 0% or 100%: clip before log loss (documented)


def add_model_probs(rows, rho_by_month):
    """Poisson and walk-forward Dixon-Coles probabilities for each row."""
    for r in rows:
        if r.lambda_home is None:
            r.p = None
            continue
        pois = probabilities(r.lambda_home, r.lambda_away)
        rho = rho_by_month.get((r.kickoff.year, r.kickoff.month))
        r.p = {"poisson": pois}
        if rho is not None:
            from diski9.research.goal_models import rho_limits

            lo, hi = rho_limits(r.lambda_home, r.lambda_away)
            r.p["dc"] = probabilities(r.lambda_home, r.lambda_away, min(max(rho, lo), hi))


def binary_metrics(p, y):
    p = np.asarray(p, dtype=float)
    return {
        "brier": round(float(brier_binary(p, y).mean()), 4),
        "log_loss": round(float(log_loss_binary(np.clip(p, CLIP, 1 - CLIP), y).mean()), 4),
        "auc": None if (a := auc(p, y)) is None else round(a, 3),
        "ece": expected_calibration_error(np.clip(p, 0, 1), y),
        "mean_forecast": round(float(p.mean()), 4),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with make_engine().connect() as c:
        store = MatchStore(c)
    rows = build_rows(store, COMPS, (2023, 2024, 2025, 2026))
    folds = monthly_folds(FIRST_TEST, max(r.kickoff for r in rows))
    summary: dict = {"generated": datetime.now(UTC).isoformat(timespec="seconds")}

    # walk-forward Dixon-Coles rho: fitted on all overall-basis rows before each month
    rho_by = {}
    for basis in ("overall", "venue"):
        base_rows = [r for r in rows if r.basis == basis and r.lambda_home is not None]
        rho_by[basis] = {}
        for f in folds:
            train = [r for r in base_rows if r.kickoff < f.start]
            if len(train) >= 500:
                rho_by[basis][(f.start.year, f.start.month)] = fit_rho(train)
        add_model_probs([r for r in rows if r.basis == basis], rho_by[basis])
    summary["dc_rho_walk_forward"] = {
        b: {f"{k[0]}-{k[1]:02d}": round(v, 4) for k, v in d.items()} for b, d in rho_by.items()
    }
    pre = [
        r
        for r in rows
        if r.basis == "overall" and r.lambda_home is not None and r.kickoff < FIRST_TEST
    ]
    summary["dc_rho_by_league_pre_test"] = {
        LEAGUE[c]: round(fit_rho([r for r in pre if r.competition_id == c]), 4) for c in COMPS
    }

    # test rows: Aug 2024 onwards; common sample needs the production indicator and the model
    test = {
        b: [
            r
            for r in rows
            if r.basis == b
            and r.kickoff >= FIRST_TEST
            and r.btts_indicator is not None
            and r.p is not None
            and "dc" in r.p
        ]
        for b in ("overall", "venue")
    }
    summary["test_sample"] = {
        b: {
            "fixtures": len(v),
            "period": [
                min(r.kickoff for r in v).date().isoformat(),
                max(r.kickoff for r in v).date().isoformat(),
            ],
            "btts_rate": round(mean(r.btts for r in v), 4),
            "over_rate": round(mean(r.over for r in v), 4),
            "by_league": dict(Counter(LEAGUE[r.competition_id] for r in v)),
        }
        for b, v in test.items()
    }
    eligible_all = [r for r in rows if r.basis == "overall" and r.kickoff >= FIRST_TEST]
    summary["excluded_no_indicator_overall"] = sum(r.btts_indicator is None for r in eligible_all)
    summary["excluded_no_indicator_venue"] = sum(
        r.btts_indicator is None for r in rows if r.basis == "venue" and r.kickoff >= FIRST_TEST
    )

    # walk-forward recalibration of the raw indicator and "indicator beyond model"
    def wf_logistic(data, xfun, yfun):
        out = np.full(len(data), np.nan)
        for f in folds:
            tr = [r for r in rows_pool if r.kickoff < f.start]
            idx = [i for i, r in enumerate(data) if f.start <= r.kickoff < f.end]
            if len(tr) < 300 or not idx:
                continue
            m = fit_logistic(np.array([xfun(r) for r in tr]), [yfun(r) for r in tr])
            out[idx] = m.predict(np.array([xfun(data[i]) for i in idx]))
        return out

    results = {}
    cal_rows, band_rows, size_rows, league_rows = [], [], [], []
    panels = {}
    for basis, data in test.items():
        rows_pool = [
            r for r in rows if r.basis == basis and r.btts_indicator is not None and r.p is not None
        ]
        weeks = [iso_week(r.kickoff) for r in data]
        for market in ("btts", "over"):
            y = np.array([getattr(r, market) for r in data])
            ind = np.array([getattr(r, f"{market}_indicator") for r in data])
            key = "btts" if market == "btts" else "ou25"
            cands = {
                "league_rate": np.array([getattr(r.league, market) for r in data]),
                "raw_indicator (experiment)": ind,
                "shrunk_indicator": np.array([getattr(r, f"{market}_shrunk") for r in data]),
                "recalibrated_indicator": wf_logistic(
                    data,
                    lambda r, market=market: [getattr(r, f"{market}_indicator")],
                    lambda r, market=market: getattr(r, market),
                ),
                "poisson": np.array([r.p["poisson"][key][0] for r in data]),
                "dixon_coles": np.array([r.p["dc"][key][0] for r in data]),
                "poisson+indicator (logistic)": wf_logistic(
                    data,
                    lambda r, key=key, market=market: [
                        r.p["poisson"][key][0],
                        getattr(r, f"{market}_indicator"),
                    ],
                    lambda r, market=market: getattr(r, market),
                ),
                "poisson (logistic recalibrated)": wf_logistic(
                    data,
                    lambda r, key=key: [r.p["poisson"][key][0]],
                    lambda r, market=market: getattr(r, market),
                ),
            }
            ok = np.all([~np.isnan(v) for v in cands.values()], axis=0)
            yy = y[ok]
            wk = [w for w, k in zip(weeks, ok, strict=True) if k]
            res = {
                "n": int(ok.sum()),
                "observed_rate": round(float(yy.mean()), 4),
                "models": {},
                "paired_brier": {},
            }
            for name, p in cands.items():
                res["models"][name] = binary_metrics(p[ok], yy)
            bri = {name: brier_binary(p[ok], yy) for name, p in cands.items()}
            for name in cands:
                if name != "league_rate":
                    res["paired_brier"][f"{name} - league_rate"] = paired_bootstrap(
                        bri[name] - bri["league_rate"], wk
                    )
            for a, b in (
                ("shrunk_indicator", "raw_indicator (experiment)"),
                ("dixon_coles", "poisson"),
                ("poisson+indicator (logistic)", "poisson (logistic recalibrated)"),
                ("poisson", "shrunk_indicator"),
            ):
                res["paired_brier"][f"{a} - {b}"] = paired_bootstrap(bri[a] - bri[b], wk)
            results[f"{basis}_{market}"] = res

            # calibration of indicator and model
            for name in ("raw_indicator (experiment)", "shrunk_indicator", "poisson"):
                for row in calibration_table(cands[name][ok], yy, IND_BANDS):
                    cal_rows.append({"basis": basis, "market": market, "forecast": name, **row})
            panels.setdefault(f"{'BTTS Yes' if market == 'btts' else 'Over 2.5'} ({basis})", {})
            for name, label in (
                ("raw_indicator (experiment)", "Raw indicator"),
                ("shrunk_indicator", "Shrunk indicator"),
                ("poisson", "Goal-rate Poisson"),
            ):
                tab = calibration_table(cands[name][ok], yy, IND_BANDS)
                panels[f"{'BTTS Yes' if market == 'btts' else 'Over 2.5'} ({basis})"][label] = [
                    (t["mean_forecast"], t["observed"], t["n"]) for t in tab if t["n"]
                ]
            # observed by indicator band (all test rows)
            for row in calibration_table(ind, y, IND_BANDS):
                band_rows.append({"basis": basis, "market": market, **row})
            # by sample size
            for lo, hi in SIZE_BANDS:
                sel = np.array([lo <= r.min_n <= hi for r in data]) & ok
                if sel.sum() < 30:
                    continue
                ys = y[sel]
                size_rows.append(
                    {
                        "basis": basis,
                        "market": market,
                        "smaller_team_sample": f"{lo}-{hi}" if lo != hi else str(lo),
                        "n": int(sel.sum()),
                        "share_of_fixtures": round(float(sel.sum() / ok.sum()), 3),
                        "observed": round(float(ys.mean()), 3),
                        "auc_raw": round(auc(ind[sel], ys) or 0, 3),
                        "brier_league_rate": round(
                            float(brier_binary(cands["league_rate"][sel], ys).mean()), 4
                        ),
                        "brier_raw": round(float(brier_binary(ind[sel], ys).mean()), 4),
                        "brier_shrunk": round(
                            float(brier_binary(cands["shrunk_indicator"][sel], ys).mean()), 4
                        ),
                        "brier_poisson": round(
                            float(brier_binary(cands["poisson"][sel], ys).mean()), 4
                        ),
                        "indicator_sd": round(float(ind[sel].std()), 3),
                    }
                )
            for comp in COMPS:
                sel = np.array([r.competition_id == comp for r in data]) & ok
                ys = y[sel]
                league_rows.append(
                    {
                        "basis": basis,
                        "market": market,
                        "league": LEAGUE[comp],
                        "n": int(sel.sum()),
                        "observed": round(float(ys.mean()), 3),
                        "auc_raw": round(auc(ind[sel], ys) or 0, 3),
                        "auc_poisson": round(auc(cands["poisson"][sel], ys) or 0, 3),
                        "brier_league_rate": round(
                            float(brier_binary(cands["league_rate"][sel], ys).mean()), 4
                        ),
                        "brier_raw": round(float(brier_binary(ind[sel], ys).mean()), 4),
                        "brier_shrunk": round(
                            float(brier_binary(cands["shrunk_indicator"][sel], ys).mean()), 4
                        ),
                        "brier_poisson": round(
                            float(brier_binary(cands["poisson"][sel], ys).mean()), 4
                        ),
                    }
                )
    summary["indicator_evaluation"] = results
    write_csv(OUT / "goals_calibration.csv", cal_rows)
    write_csv(OUT / "goals_observed_by_indicator_band.csv", band_rows)
    write_csv(OUT / "goals_by_sample_size.csv", size_rows)
    write_csv(OUT / "goals_by_league.csv", league_rows)

    # overall vs venue on the same fixtures (paired)
    ov = {r.fixture_id: r for r in test["overall"]}
    ve = {r.fixture_id: r for r in test["venue"]}
    common = sorted(set(ov) & set(ve))
    summary["overall_vs_venue_common"] = {"fixtures": len(common)}
    for market in ("btts", "over"):
        y = np.array([getattr(ov[f], market) for f in common])
        wk = [iso_week(ov[f].kickoff) for f in common]
        for name, attr in (("raw", f"{market}_indicator"), ("shrunk", f"{market}_shrunk")):
            po = np.array([getattr(ov[f], attr) for f in common])
            pv = np.array([getattr(ve[f], attr) for f in common])
            summary["overall_vs_venue_common"][f"{market}_{name}"] = {
                "brier_overall": round(float(brier_binary(po, y).mean()), 4),
                "brier_venue": round(float(brier_binary(pv, y).mean()), 4),
                "auc_overall": round(auc(po, y), 3),
                "auc_venue": round(auc(pv, y), 3),
                "venue_minus_overall_brier": paired_bootstrap(
                    brier_binary(pv, y) - brier_binary(po, y), wk
                ),
            }

    # early season: how many fixtures are below the production Limited threshold (6)
    early = {}
    for basis in ("overall", "venue"):
        v = [r for r in rows if r.basis == basis and r.kickoff >= FIRST_TEST]
        early[basis] = {
            "fixtures": len(v),
            "no_indicator_share": round(sum(r.btts_indicator is None for r in v) / len(v), 3),
            "limited_share_min_n_lt_6": round(sum(r.min_n < 6 for r in v) / len(v), 3),
            "full_10_share": round(sum(r.min_n >= 10 for r in v) / len(v), 3),
        }
        # matchweek-style: median team-match count at which both teams reach 6
    summary["early_season"] = early

    # goal-rate model vs results: totals, 1X2, Poisson vs Dixon-Coles
    gm = {}
    for basis, data in test.items():
        y = [r.outcome for r in data]
        wk = [iso_week(r.kickoff) for r in data]
        P = {m: np.array([r.p[m]["1x2"] for r in data]) for m in ("poisson", "dc")}
        ll = {m: log_loss_multiclass(P[m], y) for m in P}
        lam_h = np.array([r.lambda_home for r in data])
        lam_a = np.array([r.lambda_away for r in data])
        hg = np.array([r.home_goals for r in data])
        ag = np.array([r.away_goals for r in data])
        tot = hg + ag
        dist = {}
        for m in ("poisson", "dc"):
            pred = np.zeros(11)
            for r in data:
                tg = r.p[m]["total_goals"]
                pred[: min(10, len(tg))] += tg[:10]
                pred[10] += tg[10:].sum()
            dist[m] = [round(float(x / len(data)), 4) for x in pred]
        obs = np.bincount(np.minimum(tot, 10), minlength=11) / len(data)
        draws = np.array([r.outcome == 1 for r in data])
        gm[basis] = {
            "n": len(data),
            "mean_lambda_home": round(float(lam_h.mean()), 3),
            "mean_home_goals": round(float(hg.mean()), 3),
            "mean_lambda_away": round(float(lam_a.mean()), 3),
            "mean_away_goals": round(float(ag.mean()), 3),
            "mean_lambda_total": round(float((lam_h + lam_a).mean()), 3),
            "mean_total_goals": round(float(tot.mean()), 3),
            "total_goals_distribution": {
                "goals": list(range(10)) + ["10+"],
                "observed": [round(float(x), 4) for x in obs],
                "poisson": dist["poisson"],
                "dixon_coles": dist["dc"],
            },
            "draw_rate_observed": round(float(draws.mean()), 4),
            "draw_prob_poisson": round(float(P["poisson"][:, 1].mean()), 4),
            "draw_prob_dc": round(float(P["dc"][:, 1].mean()), 4),
            "low_score_observed": {
                f"{s[0]}-{s[1]}": round(float(((hg == s[0]) & (ag == s[1])).mean()), 4)
                for s in ((0, 0), (1, 0), (0, 1), (1, 1))
            },
            "log_loss_1x2": {m: round(float(v.mean()), 4) for m, v in ll.items()},
            "brier_1x2": {m: round(float(brier_multiclass(P[m], y).mean()), 4) for m in P},
            "dc_minus_poisson_log_loss_1x2": paired_bootstrap(ll["dc"] - ll["poisson"], wk),
            "ece_draw": {m: expected_calibration_error(P[m][:, 1], draws.astype(int)) for m in P},
        }
        # total-goals calibration by predicted-total band
        bands = [(0, 2.25), (2.25, 2.5), (2.5, 2.75), (2.75, 3.0), (3.0, 9)]
        gm[basis]["total_goals_calibration"] = [
            {
                "predicted_band": f"[{lo}, {hi})",
                "n": int(sel.sum()),
                "mean_predicted": round(float((lam_h + lam_a)[sel].mean()), 3),
                "mean_observed": round(float(tot[sel].mean()), 3),
            }
            for lo, hi in bands
            if (sel := ((lam_h + lam_a) >= lo) & ((lam_h + lam_a) < hi)).sum()
        ]
    summary["goal_rate_model"] = gm
    (OUT / "goals_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    calibration_panels(
        OUT / "goals_calibration_overall.svg",
        {k: v for k, v in panels.items() if "overall" in k},
        "Calibration, overall basis, Aug 2024 to Nov 2026 (observed vs forecast)",
    )

    for k, v in results.items():
        print(k, v["n"], v["observed_rate"])
        for name, m in v["models"].items():
            print("   ", f"{name:34s}", m)
        for name, m in v["paired_brier"].items():
            print("   ", name, m["mean"], m["ci95"])
    print(
        json.dumps(
            {
                k: summary[k]
                for k in ("overall_vs_venue_common", "early_season", "dc_rho_by_league_pre_test")
            },
            indent=1,
            default=str,
        )
    )
    for b in gm:
        print(b, {k: v for k, v in gm[b].items() if k not in ("total_goals_distribution",)})


if __name__ == "__main__":
    main()
