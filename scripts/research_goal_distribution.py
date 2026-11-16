"""Research only: unified goal-distribution model (1X2, BTTS, Over/Under 2.5).

Run: uv run python scripts/research_goal_distribution.py
Writes docs/research/goal_model/*.{json,csv,svg}. Read-only: no API calls, no
bookmaker data, no production code or cache touched.

Protocol
--------
* Seasons 2023/24 is tuning-only. Each test season (2024/25, 2025/26, 2026/27 to
  date) is predicted with hyperparameters chosen on all earlier seasons only
  (expanding window), by the mean log-probability of the observed scoreline.
* Every fixture of a test season is predicted, including opening rounds (teams with
  zero matches fall back to the league average through the shrinkage).
* All candidates are scored on the identical fixture set.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import numpy as np

from diski9.db import make_engine
from diski9.research.charts import calibration_panels
from diski9.research.evaluation import (
    brier_binary,
    brier_multiclass,
    calibration_table,
    expected_calibration_error,
    fit_logistic,
    iso_week,
    log_loss_binary,
    log_loss_multiclass,
    paired_bootstrap,
)
from diski9.research.form_score_comparison import write_csv
from diski9.research.goal_distribution import (
    HALF_LIVES,
    INF,
    LEAGUE_NAME,
    Params,
    _factors,
    build_dataset,
    dc_rho_limits,
    dixon_coles_adjust,
    empirical_marginals,
    empirical_score_logprob,
    lambdas,
    league_frequencies,
    league_rates,
    league_weight,
    markets_from_marginals,
    overall_factors,
    poisson_marginals,
    poisson_markets,
    poisson_score_logprob,
    tune_empirical,
    tune_poisson,
)
from diski9.screener.engine import MatchStore

OUT = Path("docs/research/goal_model")
COMPS = (39, 40, 288, 289)
SEASONS = (2023, 2024, 2025, 2026)
TEST_SEASONS = (2024, 2025, 2026)
M0 = 30.0  # league prior pseudo-matches (sensitivity tested below)
K_O = (0.5, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32)
K_V = (1, 2, 4, 6, 8, 12, 16, 24, 32, 48, 96, 192)
K_T = (8, 16, 24, 32, 48, 64, 96, 128, 192, 256, 1e12)
REC = "A_split"  # reference model (season-to-date, strength / tempo shrinkage)
BIG = 1e12  # "infinite" shrinkage: league average only


def grids():
    g = {
        "A_overall": [Params("season", k, INF, M0) for k in K_O],
        "A_venue": [Params("season", k, v, M0) for k, v in product(K_O, K_V)],
        "A_split": [Params("season", k, INF, M0, t) for k, t in product(K_O, K_T)],
        "B_last8": [Params("last8", k, v, M0) for k, v in product(K_O, (*K_V, INF))],
        "C_last10": [Params("last10", k, v, M0) for k, v in product(K_O, (*K_V, INF))],
        "D_decay": [
            Params(f"decay{h}", k, v, M0) for h, k, v in product(HALF_LIVES, K_O, (*K_V, INF))
        ],
    }
    fixed = {
        "league_poisson": Params("season", BIG, INF, M0),
        "raw_overall": Params("season", 0, INF, M0),
        "raw_venue": Params("season", 0, 0, M0),
    }
    return g, fixed


# ------------------------------------------------------------------ metrics
def probs_to_arrays(mk):
    P = np.column_stack([mk["home"], mk["draw"], mk["away"]])
    return P, np.asarray(mk["btts_yes"]), np.asarray(mk["over"])


def calib_slope(p, y):
    """Logistic recalibration slope of logit(p): 1 = well spread; < 1 = too extreme."""
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    x = np.log(p / (1 - p))
    m = fit_logistic(x[:, None], y)
    return round(float(m.weights[1] / m.scale[0]), 3)


def metrics(mk, ds, score_lp=None):
    P, b, o = probs_to_arrays(mk)
    y, yb, yo = ds.outcome, ds.btts, ds.over
    out = {
        "n": len(y),
        "1x2_log_loss": float(log_loss_multiclass(P, y).mean()),
        "1x2_brier": float(brier_multiclass(P, y).mean()),
        "1x2_ece_home": expected_calibration_error(P[:, 0], (y == 0).astype(int)),
        "1x2_ece_draw": expected_calibration_error(P[:, 1], (y == 1).astype(int)),
        "1x2_ece_away": expected_calibration_error(P[:, 2], (y == 2).astype(int)),
        "1x2_slope_home": calib_slope(P[:, 0], (y == 0).astype(int)),
        "btts_log_loss": float(log_loss_binary(b, yb).mean()),
        "btts_brier": float(brier_binary(b, yb).mean()),
        "btts_ece": expected_calibration_error(b, yb),
        "btts_slope": calib_slope(b, yb),
        "ou_log_loss": float(log_loss_binary(o, yo).mean()),
        "ou_brier": float(brier_binary(o, yo).mean()),
        "ou_ece": expected_calibration_error(o, yo),
        "ou_slope": calib_slope(o, yo),
        "mean_p_home": float(P[:, 0].mean()),
        "mean_p_draw": float(P[:, 1].mean()),
        "mean_p_btts": float(b.mean()),
        "mean_p_over": float(o.mean()),
    }
    if score_lp is not None:
        out["score_loglik"] = float(np.mean(score_lp))
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def per_row_losses(mk, ds):
    P, b, o = probs_to_arrays(mk)
    return {
        "1x2_log_loss": log_loss_multiclass(P, ds.outcome),
        "1x2_brier": brier_multiclass(P, ds.outcome),
        "btts_log_loss": log_loss_binary(b, ds.btts),
        "btts_brier": brier_binary(b, ds.btts),
        "ou_log_loss": log_loss_binary(o, ds.over),
        "ou_brier": brier_binary(o, ds.over),
    }


def fmt_params(p):
    if isinstance(p, Params):
        return {
            "window": p.window,
            "k_o": p.k_o if p.k_o < BIG else "inf",
            "k_v": "inf" if math.isinf(p.k_v) else p.k_v,
            "m0": p.m0,
            "k_t": "inf" if (p.k_t or 0) >= BIG else p.k_t,
        }
    return p


# ------------------------------------------------------------------ main
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with make_engine().connect() as c:
        store = MatchStore(c)
    ds_all = build_dataset(store, COMPS, SEASONS)
    summary: dict = {"generated": datetime.now(UTC).isoformat(timespec="seconds")}

    # ------------------------------------------------------------ dataset
    excl = defaultdict(int)
    from sqlalchemy import text

    with make_engine().connect() as c:
        rows = c.execute(
            text(
                "select competition_id, season, coalesce(stats_exclusion_reason, 'eligible'), "
                "count(*) from fixtures where competition_id in (39,40,288,289) "
                "group by 1,2,3 order by 1,2,3"
            )
        ).all()
    for _comp, _yr, reason, n in rows:
        excl[f"{reason}"] += n
    _, _, avail_all = league_rates(ds_all, M0)
    coverage = []
    for comp in COMPS:
        for yr in SEASONS:
            m = (ds_all.competition == comp) & (ds_all.season == yr)
            coverage.append(
                {
                    "league": LEAGUE_NAME[comp],
                    "season": f"{yr}/{str(yr + 1)[2:]}",
                    "eligible_completed": int(m.sum()),
                    "predictable": int((m & avail_all).sum()),
                    "role": "tuning only" if yr == 2023 else "test (out of sample)",
                    "neutral_venue": int(
                        sum(
                            1
                            for x in store.by_comp_season.get((comp, yr), [])
                            if x.venue_classification == "neutral"
                        )
                    ),
                }
            )
    write_csv(OUT / "coverage.csv", coverage)
    summary["dataset"] = {
        "fixture_status_counts": dict(excl),
        "eligible_completed": len(ds_all),
        "unavailable_league_prior": int((~avail_all).sum()),
        "unavailable_note": "2023/24 opening rounds only: no 2022/23 season stored and "
        "fewer than 30 current-season league matches",
        "goals_missing": 0,
    }

    # ------------------------------------------------------- walk-forward
    g, fixed = grids()
    preds: dict[str, list] = defaultdict(list)  # variant -> list of (mask, mk, lp, lh, la)
    chosen: dict[str, dict] = defaultdict(dict)
    tuning_tables = {}
    test_mask = np.isin(ds_all.season, TEST_SEASONS) & avail_all
    test = ds_all.subset(test_mask)
    store_mk: dict[str, dict] = {}
    store_lambda: dict[str, tuple] = {}
    store_lp: dict[str, np.ndarray] = {}
    params_used: dict[str, dict[int, Params]] = defaultdict(dict)

    def collect(name, season, mk, lp=None, lh=None, la=None):
        preds[name].append((season, mk, lp, lh, la))

    for S in TEST_SEASONS:
        train = ds_all.subset((ds_all.season < S) & avail_all)
        tst = ds_all.subset((ds_all.season == S) & avail_all)
        for name, grid in g.items():
            best, table = tune_poisson(train, grid)
            chosen[name][S] = fmt_params(best)
            params_used[name][S] = best
            tuning_tables[(name, S)] = table
            lh, la, _ = lambdas(tst, best)
            collect(
                name,
                S,
                poisson_markets(lh, la),
                poisson_score_logprob(lh, la, tst.hg, tst.ag),
                lh,
                la,
            )
        for name, p in fixed.items():
            lh, la, _ = lambdas(tst, p)
            params_used[name][S] = p
            collect(
                name,
                S,
                poisson_markets(lh, la),
                poisson_score_logprob(lh, la, tst.hg, tst.ag),
                lh,
                la,
            )
        (ko, kv), etab = tune_empirical(train, list(product(K_O, (*K_V, INF))), M0)
        chosen["empirical"][S] = {"k_o": ko, "k_v": "inf" if math.isinf(kv) else kv, "m0": M0}
        ph, pa, _ = empirical_marginals(tst, ko, kv, M0)
        collect(
            "empirical",
            S,
            markets_from_marginals(ph, pa),
            empirical_score_logprob(ph, pa, tst.hg, tst.ag),
        )
        lf = league_frequencies(tst, M0)
        collect(
            "league_freq",
            S,
            {
                "home": lf["home"],
                "draw": lf["draw"],
                "away": lf["away"],
                "btts_yes": lf["btts_yes"],
                "over": lf["over"],
            },
        )

    def cat(name):
        parts = preds[name]
        mk = {
            k: np.concatenate([np.asarray(p[1][k]) for p in parts])
            for k in ("home", "draw", "away", "btts_yes", "over")
        }
        lp = np.concatenate([p[2] for p in parts]) if parts[0][2] is not None else None
        lh = np.concatenate([p[3] for p in parts]) if parts[0][3] is not None else None
        la = np.concatenate([p[4] for p in parts]) if parts[0][4] is not None else None
        return mk, lp, lh, la

    variants = [
        "league_freq",
        "league_poisson",
        "raw_overall",
        "raw_venue",
        "A_overall",
        "A_venue",
        "A_split",
        "B_last8",
        "C_last10",
        "D_decay",
        "empirical",
    ]
    for v in variants:
        store_mk[v], store_lp[v], lh, la = cat(v)
        if lh is not None:
            store_lambda[v] = (lh, la)
    # test rows in the same order as concatenation (season blocks, store order)
    test = ds_all.subset(test_mask)
    assert len(test) == len(store_mk["league_freq"]["home"])
    for v in variants:  # every market sums to one
        mk = store_mk[v]
        assert np.allclose(mk["home"] + mk["draw"] + mk["away"], 1)

    summary["chosen_hyperparameters"] = chosen
    summary["overall"] = {v: metrics(store_mk[v], test, store_lp[v]) for v in variants}
    summary["form_score_reference"] = form_score_reference(store, ds_all, avail_all, test, store_mk)

    # ---------------------------------------------------------- bootstrap
    clusters = [iso_week(k) for k in test.kickoff]
    losses = {v: per_row_losses(store_mk[v], test) for v in variants}
    boot = {}
    for ref in ("league_freq", "A_overall", REC):
        for v in variants:
            if v == ref:
                continue
            boot[f"{v} - {ref}"] = {
                m: paired_bootstrap(losses[v][m] - losses[ref][m], clusters) for m in losses[v]
            }
    summary["paired_differences"] = boot

    # ------------------------------------------------------------ segments
    prog = test.progress()
    stage = np.where(prog < 0.25, "early", np.where(prog <= 0.75, "mid", "late"))
    nh, na = test.matches_played()
    nmin = np.minimum(nh, na)
    tt = test.team["season"]
    venue_min = np.minimum(tt[:, 0], tt[:, 7])  # home team's home matches, away team's away
    seg_defs = {
        "stage": stage,
        "league": np.array([LEAGUE_NAME[c] for c in test.competition]),
        "season": np.array([f"{s}/{str(s + 1)[2:]}" for s in test.season]),
        "min_matches": np.select(
            [nmin == 0, nmin == 1, nmin == 2, nmin == 3, nmin <= 7],
            ["0", "1", "2", "3", "4-7"],
            "8+",
        ),
        "venue_history": np.select(
            [venue_min == 0, venue_min <= 2, venue_min <= 5], ["0", "1-2", "3-5"], "6+"
        ),
    }
    seg_rows = []
    key_variants = [
        "league_freq",
        "league_poisson",
        "A_overall",
        "A_venue",
        REC,
        "B_last8",
        "C_last10",
        "D_decay",
        "empirical",
        "raw_venue",
    ]
    for seg, labels in seg_defs.items():
        for lab in sorted(set(labels)):
            m = labels == lab
            for v in key_variants:
                row = {"segment": seg, "group": lab, "variant": v, "n": int(m.sum())}
                for k in (
                    "1x2_log_loss",
                    "btts_log_loss",
                    "ou_log_loss",
                    "1x2_brier",
                    "btts_brier",
                    "ou_brier",
                ):
                    row[k] = round(float(losses[v][k][m].mean()), 4)
                seg_rows.append(row)
    write_csv(OUT / "segments.csv", seg_rows)
    seg_boot = {}
    for lab in ("early", "mid", "late"):
        m = stage == lab
        cl = [c for c, keep in zip(clusters, m, strict=True) if keep]
        seg_boot[lab] = {
            f"{v} - {ref}": {
                k: paired_bootstrap(losses[v][k][m] - losses[ref][k][m], cl)
                for k in ("1x2_log_loss", "btts_log_loss", "ou_log_loss")
            }
            for v, ref in (
                ("A_overall", "league_freq"),
                (REC, "league_freq"),
                (REC, "A_overall"),
                ("A_venue", "A_overall"),
                ("B_last8", "A_overall"),
                ("C_last10", "A_overall"),
                ("D_decay", "A_overall"),
                ("empirical", "A_overall"),
            )
        }
    summary["stage_differences"] = seg_boot
    summary["stage_counts"] = {lab: int((stage == lab).sum()) for lab in ("early", "mid", "late")}

    # --------------------------------------------------------- calibration
    cal = {}
    panels = {"Home win": {}, "Draw": {}, "BTTS Yes": {}, "Over 2.5": {}}
    for v, label in (
        ("league_freq", "League baseline"),
        (REC, "Season-to-date, smoothed"),
        ("raw_venue", "Raw venue rates"),
    ):
        P, b, o = probs_to_arrays(store_mk[v])
        y = test.outcome
        cal[v] = {}
        for name, p, yy in (
            ("Home win", P[:, 0], (y == 0).astype(int)),
            ("Draw", P[:, 1], (y == 1).astype(int)),
            ("BTTS Yes", b, test.btts),
            ("Over 2.5", o, test.over),
        ):
            tab = calibration_table(p, yy)
            cal[v][name] = tab
            panels[name][label] = [
                (r["mean_forecast"], r["observed"], r["n"]) for r in tab if r["n"]
            ]
    summary["calibration_tables"] = cal
    calibration_panels(
        OUT / "calibration.svg",
        panels,
        "Calibration on 3,2xx out-of-sample fixtures (2024/25 to 2026/27)".replace(
            "3,2xx", f"{len(test):,}"
        ),
    )

    # ------------------------------------------------- extremes & stability
    ext = {}
    for v in (
        "A_overall",
        "A_venue",
        REC,
        "B_last8",
        "C_last10",
        "D_decay",
        "raw_venue",
        "raw_overall",
    ):
        lh, la = store_lambda[v]
        P, _, _ = probs_to_arrays(store_mk[v])
        top = P.max(axis=1)
        hit = P.argmax(axis=1) == test.outcome
        ext[v] = {
            "lambda_home_q": [round(float(x), 2) for x in np.quantile(lh, [0, 0.01, 0.5, 0.99, 1])],
            "lambda_away_q": [round(float(x), 2) for x in np.quantile(la, [0, 0.01, 0.5, 0.99, 1])],
            "share_lambda_gt_3": round(float(((lh > 3) | (la > 3)).mean()), 4),
            "share_lambda_lt_0_4": round(float(((lh < 0.4) | (la < 0.4)).mean()), 4),
            "share_max_1x2_gt_0_75": round(float((top > 0.75).mean()), 4),
            "observed_hit_when_gt_0_75": round(float(hit[top > 0.75].mean()), 3)
            if (top > 0.75).any()
            else None,
            "mean_forecast_when_gt_0_75": round(float(top[top > 0.75].mean()), 3)
            if (top > 0.75).any()
            else None,
            "early_lambda_q": [
                round(float(x), 2)
                for x in np.quantile(
                    np.concatenate([lh[stage == "early"], la[stage == "early"]]), [0.01, 0.5, 0.99]
                )
            ],
        }
    summary["extremes"] = ext

    def stability(v):
        """Mean |change| in a team's overall attack and defence factors
        between its consecutive fixtures, by stage."""
        res = {}
        seq = defaultdict(list)
        for S in TEST_SEASONS:
            p = params_used[v][S]
            m = test.season == S
            sub = test.subset(m)
            H, A, _ = league_rates(sub, p.m0)
            win = p.window
            th = sub.team[win]
            ah, dh, _, _ = _factors(th[:, :6], H, A, p.k_o, INF, p.k_t)
            aa, da, _, _ = _factors(th[:, 6:], H, A, p.k_o, INF, p.k_t)
            st = stage[m]
            for i in range(len(sub)):
                seq[(S, sub.home_id[i])].append((sub.kickoff[i], ah[i], dh[i], st[i]))
                seq[(S, sub.away_id[i])].append((sub.kickoff[i], aa[i], da[i], st[i]))
        diffs = defaultdict(list)
        for items in seq.values():
            items.sort(key=lambda x: x[0])
            for (_, a0, d0, _), (_, a1, d1, s1) in zip(items, items[1:], strict=False):
                diffs[s1].append(abs(a1 - a0) + abs(d1 - d0))
        for s, d in diffs.items():
            res[s] = round(float(np.mean(d)), 4)
        return res

    summary["stability"] = {
        v: stability(v) for v in ("A_overall", REC, "B_last8", "C_last10", "D_decay", "raw_overall")
    }

    # ------------------------------------------------- Poisson diagnostics
    lh, la = store_lambda[REC]
    diag = {
        "pearson_dispersion_home": round(float(np.mean((test.hg - lh) ** 2 / lh)), 3),
        "pearson_dispersion_away": round(float(np.mean((test.ag - la) ** 2 / la)), 3),
        "mean_goals_home": [round(float(test.hg.mean()), 3), round(float(lh.mean()), 3)],
        "mean_goals_away": [round(float(test.ag.mean()), 3), round(float(la.mean()), 3)],
    }
    G = 11
    ph, pa = poisson_marginals(lh, G), poisson_marginals(la, G)
    sc = []
    for h, a in ((0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (0, 2), (2, 1), (1, 2), (2, 2)):
        sc.append(
            {
                "score": f"{h}-{a}",
                "observed": int(((test.hg == h) & (test.ag == a)).sum()),
                "expected": round(float((ph[:, h] * pa[:, a]).sum()), 1),
            }
        )
    tot = test.hg + test.ag
    for t in range(6):
        exp_t = (
            sum((ph[:, i] * pa[:, t - i]).sum() for i in range(t + 1))
            if t < 5
            else len(test)
            - sum((ph[:, i] * pa[:, j]).sum() for i in range(5) for j in range(5 - i))
        )
        sc.append(
            {
                "score": f"total {t}{'+' if t == 5 else ''}",
                "observed": int((tot == t).sum() if t < 5 else (tot >= 5).sum()),
                "expected": round(float(exp_t), 1),
            }
        )
    mk = store_mk[REC]
    for lab in sorted(set(seg_defs["league"])):
        m = seg_defs["league"] == lab
        sc.append(
            {
                "score": f"draws {lab}",
                "observed": int((test.outcome[m] == 1).sum()),
                "expected": round(float(mk["draw"][m].sum()), 1),
            }
        )
    sc.append(
        {
            "score": "draws all",
            "observed": int((test.outcome == 1).sum()),
            "expected": round(float(mk["draw"].sum()), 1),
        }
    )
    write_csv(OUT / "poisson_scorelines.csv", sc)
    diag["scorelines"] = sc

    # walk-forward Dixon-Coles rho (diagnostic): fit on earlier seasons' predictions
    from scipy.optimize import minimize_scalar

    dc_parts = []
    rhos = {}
    for S in TEST_SEASONS:
        p = params_used[REC][S]
        tr = ds_all.subset((ds_all.season < S) & avail_all)
        tl_h, tl_a, _ = lambdas(tr, p)
        h, a = tr.hg, tr.ag
        lo, hi = dc_rho_limits(tl_h, tl_a)

        def nll(rho, tl_h=tl_h, tl_a=tl_a, h=h, a=a, lo=lo, hi=hi):
            r = np.clip(rho, lo, hi)
            t = np.ones(len(h))
            t = np.where((h == 0) & (a == 0), 1 - tl_h * tl_a * r, t)
            t = np.where((h == 0) & (a == 1), 1 + tl_h * r, t)
            t = np.where((h == 1) & (a == 0), 1 + tl_a * r, t)
            t = np.where((h == 1) & (a == 1), 1 - r, t)
            return -np.log(np.clip(t, 1e-12, None)).sum()

        rho = float(minimize_scalar(nll, bounds=(-0.3, 0.3), method="bounded").x)
        rhos[S] = round(rho, 4)
        m = test.season == S
        sl_h, sl_a = lh[m], la[m]
        lo2, hi2 = dc_rho_limits(sl_h, sl_a)
        r = np.clip(rho, lo2, hi2)
        base = {k: np.asarray(v)[m] for k, v in mk.items()}
        dc_parts.append(dixon_coles_adjust(base, sl_h, sl_a, r))
    dc_mk = {
        k: np.concatenate([d[k] for d in dc_parts])
        for k in ("home", "draw", "away", "btts_yes", "over")
    }
    diag["dixon_coles"] = {
        "rho_by_test_season": rhos,
        "metrics": metrics(dc_mk, test),
        "vs_poisson": {
            k: paired_bootstrap(per_row_losses(dc_mk, test)[k] - losses[REC][k], clusters)
            for k in ("1x2_log_loss", "btts_log_loss")
        },
    }
    summary["poisson_diagnostics"] = diag

    # -------------------------------------------- league prior sensitivity
    sens = {}
    base_p = {S: params_used[REC][S] for S in TEST_SEASONS}
    for m0 in (0.0, 10.0, 30.0, 100.0):
        mks, keep = [], []
        for S in TEST_SEASONS:
            sub = ds_all.subset(ds_all.season == S)
            p = Params(base_p[S].window, base_p[S].k_o, base_p[S].k_v, m0, base_p[S].k_t)
            lh_, la_, av = lambdas(sub, p)
            lh_ = np.where(av, lh_, 1.0)
            la_ = np.where(av, la_, 1.0)
            mks.append(poisson_markets(lh_, la_))
            keep.append(av)
        av = np.concatenate(keep)
        mkc = {
            k: np.concatenate([x[k] for x in mks])
            for k in ("home", "draw", "away", "btts_yes", "over")
        }
        full = ds_all.subset(np.isin(ds_all.season, TEST_SEASONS))
        st = np.where(full.progress() < 0.25, "early", "later")
        sub_mk = {k: v[av] for k, v in mkc.items()}
        sub = full.subset(av)
        e = st[av] == "early"
        ll = per_row_losses(sub_mk, sub)
        sens[f"m0={m0:g}" if m0 else "current season only (>= 30 matches)"] = {
            "available": int(av.sum()),
            "unavailable": int((~av).sum()),
            "early_available": int(e.sum()),
            "early_1x2_log_loss": round(float(ll["1x2_log_loss"][e].mean()), 4),
            "early_ou_log_loss": round(float(ll["ou_log_loss"][e].mean()), 4),
            "early_btts_log_loss": round(float(ll["btts_log_loss"][e].mean()), 4),
        }
    # same fixtures for a fair comparison: those available under every policy
    summary["league_prior_sensitivity"] = sens

    # ------------------------------------------------ shrinkage weights
    p25 = params_used["A_venue"][2026]
    p25o = params_used["A_overall"][2026]
    ps = params_used[REC][2026]
    ns = (0, 1, 2, 3, 5, 10, 20, 38)
    summary["shrinkage_weights"] = {
        f"A_overall (k_o={p25o.k_o:g})": [league_weight(n, p25o.k_o, INF) for n in ns],
        f"A_venue (k_o={p25.k_o:g}, k_v={p25.k_v:g})": [
            league_weight(n, p25.k_o, p25.k_v) for n in ns
        ],
        f"A_split strength (k_s={ps.k_o:g})": [league_weight(n, ps.k_o, INF) for n in ns],
        f"A_split tempo (k_t={ps.k_t:g})": [league_weight(n, ps.k_t, INF) for n in ns],
    }
    tsurf = []
    for (name, S), table in tuning_tables.items():
        if name in ("A_overall", "A_venue", REC):
            best = max(r["score_loglik"] for r in table)
            for r in table:
                tsurf.append(
                    {
                        "variant": name,
                        "test_season": S,
                        **fmt_params(r["params"]),
                        "score_loglik": round(r["score_loglik"], 5),
                        "gap_to_best": round(best - r["score_loglik"], 5),
                    }
                )
    write_csv(OUT / "tuning_surface.csv", tsurf)

    # ------------------------------------------------- worked example
    summary["worked_example"] = worked_example(store, ds_all, params_used)
    summary["adjustment_example"] = adjustment_example()

    write_csv(
        OUT / "overall_metrics.csv",
        [{"variant": v, "score_loglik": None, **summary["overall"][v]} for v in variants],
    )
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({"overall": summary["overall"], "chosen": chosen}, indent=1, default=str))


def worked_example(store, ds_all, params_used):
    """EPL 2025/26, the first fixture played after the season's midpoint, with the
    reference model and the parameters chosen for 2025/26 (earlier seasons only)."""
    m = (ds_all.competition == 39) & (ds_all.season == 2025)
    idx = np.flatnonzero(m)
    prog = ds_all.progress()
    i = int(idx[np.argmax(prog[idx] >= 0.5)])
    row = ds_all.subset(np.arange(len(ds_all)) == i)
    p = params_used[REC][2025]
    H, A, _ = league_rates(row, p.m0)
    Hv, Av = float(H[0]), float(A[0])
    t = row.team["season"][0]

    def team(block):
        n_h, n_a, gf_h, ga_h, gf_a, ga_a = (float(x) for x in block)
        e_for, e_ag = n_h * Hv + n_a * Av, n_h * Av + n_a * Hv
        a_s, d_s = (float(x[0]) for x in overall_factors(block[None, :], H, A, p.k_o))
        a_t, d_t = (float(x[0]) for x in overall_factors(block[None, :], H, A, p.k_t))
        st, te = math.sqrt(a_s / d_s), math.sqrt(a_t * d_t)
        return {
            "home": {"played": int(n_h), "scored": int(gf_h), "conceded": int(ga_h)},
            "away": {"played": int(n_a), "scored": int(gf_a), "conceded": int(ga_a)},
            "expected_scored_at_league_rates": round(e_for, 3),
            "expected_conceded_at_league_rates": round(e_ag, 3),
            "raw_attack": round((gf_h + gf_a) / e_for, 4),
            "raw_defence": round((ga_h + ga_a) / e_ag, 4),
            "attack_shrunk_k_s": round(a_s, 4),
            "defence_shrunk_k_s": round(d_s, 4),
            "attack_shrunk_k_t": round(a_t, 4),
            "defence_shrunk_k_t": round(d_t, 4),
            "strength": round(st, 4),
            "tempo": round(te, 4),
            "_s": st,
            "_t": te,
        }

    home, away = team(t[:6]), team(t[6:])
    lh = Hv * (home["_s"] / away["_s"]) * home["_t"] * away["_t"]
    la = Av * (away["_s"] / home["_s"]) * home["_t"] * away["_t"]
    for d in (home, away):
        d.pop("_s"), d.pop("_t")
    # cross-check against the vectorised implementation
    vlh, vla, _ = lambdas(row, p)
    assert abs(vlh[0] - lh) < 1e-9 and abs(vla[0] - la) < 1e-9
    mk = poisson_markets([lh], [la])
    ph, pa = poisson_marginals([lh], 8)[0], poisson_marginals([la], 8)[0]
    names = store.team_names
    return {
        "fixture_id": int(row.fixture_id[0]),
        "fixture": f"{names[int(row.home_id[0])]} v {names[int(row.away_id[0])]}",
        "kickoff": row.kickoff[0].isoformat(),
        "parameters": {
            "k_s": p.k_o,
            "k_t": p.k_t,
            "m0": p.m0,
            "chosen_on": "2023/24 and 2024/25 fixtures only",
        },
        "league": {
            "current_season_matches": int(row.cur_n[0]),
            "current_home_goals": int(row.cur_hg[0]),
            "current_away_goals": int(row.cur_ag[0]),
            "previous_season_matches": int(row.prev_n[0]),
            "previous_season_home_per_match": round(float(row.prev_hg[0] / row.prev_n[0]), 4),
            "previous_season_away_per_match": round(float(row.prev_ag[0] / row.prev_n[0]), 4),
            "H": round(Hv, 4),
            "A": round(Av, 4),
        },
        "home_team": home,
        "away_team": away,
        "estimated_goals": {"home": round(lh, 3), "away": round(la, 3)},
        "goal_distribution_home_0_to_7": [round(float(x), 4) for x in ph],
        "goal_distribution_away_0_to_7": [round(float(x), 4) for x in pa],
        "probabilities": {k: round(float(v[0]), 4) for k, v in mk.items() if k != "mass"},
        "actual_result": f"{int(row.hg[0])}-{int(row.ag[0])}",
    }


def form_score_reference(store, ds_all, avail_all, test, store_mk):
    """1X2 only: the production Form Score difference (current season, last eight,
    engine 2.4.0 formula) turned into H/D/A probabilities by a multinomial logistic
    regression fitted on earlier seasons only. A fixture where either team has no
    current-season match gets a difference of 0. Same test fixtures."""
    from diski9.research.evaluation import fit_multinomial
    from diski9.screener.calc import diski_form_score

    diff = np.zeros(len(ds_all))
    for i in range(len(ds_all)):
        k, comp, yr = ds_all.kickoff[i], int(ds_all.competition[i]), int(ds_all.season[i])
        sc = []
        for team in (int(ds_all.home_id[i]), int(ds_all.away_id[i])):
            w = store.team_window(team, k, None, 8, competition_id=comp, season=yr)
            f = diski_form_score([(t.goals_for, t.goals_against) for t in w])
            sc.append(None if f is None else float(f.score))
        diff[i] = 0.0 if None in sc else sc[0] - sc[1]
    parts = []
    for S in TEST_SEASONS:
        tr = (ds_all.season < S) & avail_all
        te = (ds_all.season == S) & avail_all
        model = fit_multinomial(diff[tr][:, None], ds_all.outcome[tr])
        parts.append(model.predict(diff[te][:, None]))
    P = np.vstack(parts)
    ref = per_row_losses(store_mk[REC], test)
    ll = log_loss_multiclass(P, test.outcome)
    br = brier_multiclass(P, test.outcome)
    clusters = [iso_week(k) for k in test.kickoff]
    return {
        "1x2_log_loss": round(float(ll.mean()), 4),
        "1x2_brier": round(float(br.mean()), 4),
        "1x2_ece_home": expected_calibration_error(P[:, 0], (test.outcome == 0).astype(int)),
        "goal_model_minus_form_score_log_loss": paired_bootstrap(
            ref["1x2_log_loss"] - ll, clusters
        ),
        "goal_model_minus_form_score_brier": paired_bootstrap(ref["1x2_brier"] - br, clusters),
    }


def adjustment_example():
    out = {}
    for label, lh, la in (("baseline", 1.80, 1.10), ("adjusted", 1.55, 1.10)):
        mk = poisson_markets([lh], [la])
        out[label] = {
            "home_goals": lh,
            "away_goals": la,
            **{k: round(float(v[0]), 4) for k, v in mk.items() if k != "mass"},
        }
    return out


if __name__ == "__main__":
    main()
