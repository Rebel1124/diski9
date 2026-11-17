"""Research only (Phase 5B): slate-level experiments for the Weekly Challenge
portfolio study, built on :mod:`challenge_portfolio`. Pure functions of the nine
selections; loading data, writing files and charts happen in the script.

Strategy definitions used throughout
------------------------------------
* ``equal_stakes``  - 6 / 6 / 6 (+2 nine-fold) for every partition.
* ``equal_payout``  - the most balanced feasible bucket payouts: minimise
  max-min payout (tie: squared deviation, E[R], stakes). Continuous version via
  water-filling; discrete versions by exhaustive search of the increment grid.
* ``recovery``      - the feasible allocation with the highest P(R >= 20); ties:
  higher E[R], lower SD, smaller payout range, stakes (sequential). Continuous
  version via the exact up-set / LP formulation; discrete by exhaustive search.

The *primary* comparison uses the 0.1-credit grid for ``equal_payout`` and
``recovery`` (closest practical increment to the continuous benchmark).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from . import challenge_portfolio as cp

STRATEGIES = ("equal_stakes", "equal_payout", "recovery")
PRIMARY_STEP = "0.1"
FRONTIERS = {  # name: (x metric, y metric, x higher is better, y higher is better)
    "recovery_vs_min_payout": ("p_recover", "min_bucket_payout", True, True),
    "recovery_vs_expected": ("p_recover", "expected", True, True),
    "mean_variance": ("sd", "expected", False, True),
}
_GRIDS = {
    "p_recover": cp.PROB_GRID,
    "min_bucket_payout": cp.CREDIT_GRID,
    "expected": cp.CREDIT_GRID,
    "sd": cp.CREDIT_GRID,
}


def _m(stakes, b, include_nine=True) -> dict:
    return cp.metrics(np.asarray(stakes, dtype=float), b, include_nine=include_nine)


def analyse_partition(sel: Sequence[cp.Selection], part, grids: dict, continuous=True) -> dict:
    """Every strategy and granularity for one partition."""
    b = cp.bucket_inputs(sel, part)
    out: dict = {
        "id": cp.partition_id(part),
        "P": b.P.tolist(),
        "O": b.O.tolist(),
        "P9": b.P9,
        "O9": b.O9,
        "equal_stakes": _m([6, 6, 6], b),
        "equal_stakes_no_nine": _m([6, 6, 6], b, include_nine=False),
    }
    s_eq, feasible = cp.equal_payout_continuous(b.O)
    out["equal_payout_feasible"] = feasible
    out["equal_payout_cont"] = {"stakes": s_eq.tolist(), **_m(s_eq, b)}
    for step, ticks in grids.items():
        cred = cp.to_credits(ticks)
        mb = cp.metrics_batch(cred, b)
        i = cp.best_equal_payout(b, ticks, "range")
        out[f"equal_payout_{step}"] = {"stakes": cred[i].tolist(), **_m(cred[i], b)}
        k = cp.best_recovery(b, ticks, mb)
        out[f"recovery_{step}"] = {"stakes": cred[k].tolist(), **_m(cred[k], b)}
        if step == PRIMARY_STEP:
            j = cp.best_equal_payout(b, ticks, "squares")
            out["equal_payout_squares_same"] = bool(np.array_equal(ticks[i], ticks[j]))
            out["recovery_no_nine_0.1"] = _m(cred[k], b, include_nine=False)
    if continuous:
        rc = cp.recovery_continuous(b)
        out["recovery_cont"] = {"stakes": rc["stakes"].tolist(), **_m(rc["stakes"], b)}
        out["recovery_cont"]["p_recover_exact"] = rc["p_recover"]
    return out


def analyse_slate(
    sel: Sequence[cp.Selection], steps=("0.1", "0.5", "1.0"), continuous=True
) -> list[dict]:
    grids = {s: cp.allocations(cp.INCREMENTS[s]) for s in steps}
    return [analyse_partition(sel, part, grids, continuous) for part in cp.partitions()]


def strategy_key(strategy: str, step: str = PRIMARY_STEP) -> str:
    return "equal_stakes" if strategy == "equal_stakes" else f"{strategy}_{step}"


def frontier(rows: Sequence[dict], key: str, name: str) -> np.ndarray:
    xm, ym, xh, yh = FRONTIERS[name]
    x = [r[key][xm] for r in rows]
    y = [r[key][ym] for r in rows]
    return cp.pareto_mask(x, y, xh, yh, _GRIDS[xm], _GRIDS[ym])


def distinct_coords(rows, key, name, mask=None) -> int:
    xm, ym, *_ = FRONTIERS[name]
    pts = {
        (round(r[key][xm] / _GRIDS[xm]), round(r[key][ym] / _GRIDS[ym]))
        for i, r in enumerate(rows)
        if mask is None or mask[i]
    }
    return len(pts)


def summarise(rows: Sequence[dict], strategy: str, step: str = PRIMARY_STEP) -> dict:
    key = strategy_key(strategy, step)
    eff = frontier(rows, key, "recovery_vs_min_payout")
    vals = {k: np.array([r[key][k] for r in rows]) for k in
            ("p_recover", "expected", "sd", "min_bucket_payout", "max_bucket_payout")}  # fmt: skip
    base = np.array([r["equal_stakes"]["p_recover"] for r in rows])
    diff = vals["p_recover"] - base
    return {
        "strategy": strategy,
        "step": step if strategy != "equal_stakes" else "fixed 6/6/6",
        "partitions": len(rows),
        "efficient": int(eff.sum()),
        "dominated": int((~eff).sum()),
        "distinct_frontier_coords": distinct_coords(rows, key, "recovery_vs_min_payout", eff),
        "distinct_coords_all": distinct_coords(rows, key, "recovery_vs_min_payout"),
        "p_recover_min": float(vals["p_recover"].min()),
        "p_recover_max": float(vals["p_recover"].max()),
        "expected_min": float(vals["expected"].min()),
        "expected_max": float(vals["expected"].max()),
        "sd_min": float(vals["sd"].min()),
        "sd_max": float(vals["sd"].max()),
        "min_payout_min": float(vals["min_bucket_payout"].min()),
        "min_payout_max": float(vals["min_bucket_payout"].max()),
        "one_bucket_recovers": int(sum(r[key]["one_bucket_recovers"] for r in rows)),
        "equal_payout_infeasible": int(sum(not r["equal_payout_feasible"] for r in rows)),
        "diff_vs_equal_stakes": {
            "mean": float(diff.mean()),
            "min": float(diff.min()),
            "max": float(diff.max()),
            "better": int((diff > cp.PROB_GRID).sum()),
            "worse": int((diff < -cp.PROB_GRID).sum()),
            "same": int((np.abs(diff) <= cp.PROB_GRID).sum()),
        },
    }


def granularity(rows: Sequence[dict]) -> dict:
    """Recovery and balance lost by coarser credit increments (vs continuous)."""
    out = {}
    for strat in ("recovery", "equal_payout"):
        cont = np.array([r[f"{strat}_cont"]["p_recover"] for r in rows])
        rng_c = np.array([r[f"{strat}_cont"]["payout_range"] for r in rows])
        for step in ("0.1", "0.5", "1.0"):
            v = np.array([r[f"{strat}_{step}"]["p_recover"] for r in rows])
            rg = np.array([r[f"{strat}_{step}"]["payout_range"] for r in rows])
            out[f"{strat}_{step}"] = {
                "max_p_recover": float(v.max()),
                "mean_gap_vs_continuous": float((cont - v).mean()),
                "max_gap_vs_continuous": float((cont - v).max()),
                "partitions_below_continuous": int((cont - v > cp.PROB_GRID).sum()),
                "mean_payout_range": float(rg.mean()),
                "mean_payout_range_continuous": float(rng_c.mean()),
            }
    return out


def nine_fold_effect(rows: Sequence[dict]) -> dict:
    out = {}
    for name, with_k, without_k in (
        ("equal_stakes", "equal_stakes", "equal_stakes_no_nine"),
        ("recovery_0.1", "recovery_0.1", "recovery_no_nine_0.1"),
    ):
        de = np.array([r[with_k]["expected"] - r[without_k]["expected"] for r in rows])
        dp = np.array([r[with_k]["p_recover"] - r[without_k]["p_recover"] for r in rows])
        out[name] = {
            "expected_added_mean": float(de.mean()),
            "expected_added_max": float(de.max()),
            "share_of_expected_mean": float(
                np.mean(de / np.array([r[with_k]["expected"] for r in rows]))
            ),
            "p_recover_changed_partitions": int((dp > cp.PROB_GRID).sum()),
            "p_recover_added_max": float(dp.max()),
        }
    return out


def combined_frontier(rows: Sequence[dict], name="recovery_vs_min_payout") -> dict:
    """Pool 280 x 3 candidates (equal stakes, equal payout 0.1, recovery 0.1)."""
    xm, ym, xh, yh = FRONTIERS[name]
    cands = [(r["id"], s, r[strategy_key(s)]) for r in rows for s in STRATEGIES]
    mask = cp.pareto_mask([c[2][xm] for c in cands], [c[2][ym] for c in cands], xh, yh,
                          _GRIDS[xm], _GRIDS[ym])  # fmt: skip
    eff = [(pid, s) for (pid, s, _), e in zip(cands, mask, strict=True) if e]
    by_strategy = {s: sum(1 for _, t in eff if t == s) for s in STRATEGIES}
    return {"candidates": len(cands), "efficient": len(eff), "by_strategy": by_strategy,
            "efficient_ids": eff}  # fmt: skip


# ------------------------------------------------------------- sensitivity
def dependence_sensitivity(
    sel, rows, rhos=(0.05, 0.10, 0.20), strategies=("equal_stakes", "recovery")
) -> dict:
    """Hypothetical common-factor dependence (marginals preserved). Stakes stay
    those chosen under independence; recovery probability, E[R] and the
    recovery-vs-min-payout frontier are recomputed."""
    from scipy.stats import kendalltau

    parts = cp.partitions()
    out = {}
    for strat in strategies:
        key = strategy_key(strat)
        base_p = np.array([r[key]["p_recover"] for r in rows])
        base_eff = frontier(rows, key, "recovery_vs_min_payout")
        base_top = int(np.argmax(base_p))
        res = {}
        for rho in rhos:
            pr_new, er_new = [], []
            for part, r in zip(parts, rows, strict=True):
                groups = [[sel[i].p for i in g] for g in part]
                probs = cp.factor_state_probs(groups, rho)
                b = cp.bucket_inputs(sel, part)
                m = cp.metrics(r[key].get("stakes", [6, 6, 6]), b, probs=probs)
                pr_new.append(m["p_recover"])
                er_new.append(m["expected"])
            pr_new = np.array(pr_new)
            y = [r[key]["min_bucket_payout"] for r in rows]
            eff = cp.pareto_mask(pr_new, y)
            inter, union = (eff & base_eff).sum(), (eff | base_eff).sum()
            tau = kendalltau(base_p, pr_new).statistic if np.ptp(base_p) > 0 else float("nan")
            res[str(rho)] = {
                "kendall_tau_p_recover": float(tau),
                "frontier_jaccard": float(inter / union) if union else 1.0,
                "efficient": int(eff.sum()),
                "p_recover_change_mean": float((pr_new - base_p).mean()),
                "p_recover_change_min": float((pr_new - base_p).min()),
                "p_recover_change_max": float((pr_new - base_p).max()),
                "expected_change_mean": float(
                    np.mean(np.array(er_new) - [r[key]["expected"] for r in rows])
                ),
                "top_recovery_partition_kept": int(np.argmax(pr_new)) == base_top,
            }
        out[strat] = res
    return out


def probability_sensitivity(sel, n_draws=30, sd_logit=0.3, seed=20261117) -> dict:
    """Perturb each model probability on the logit scale (N(0, sd)), odds fixed.
    Equal stakes only (cheap, allocation-free): how stable are frontier
    membership and the top-recovery partition?"""
    rng = np.random.default_rng(seed)
    parts = cp.partitions()

    def eq_rows(s):
        return [{"equal_stakes": cp.metrics([6, 6, 6], cp.bucket_inputs(s, p))} for p in parts]

    base = eq_rows(sel)
    base_eff = frontier(base, "equal_stakes", "recovery_vs_min_payout")
    base_top = int(np.argmax([r["equal_stakes"]["p_recover"] for r in base]))
    jac, top_kept, eff_freq = [], 0, np.zeros(len(parts))
    for _ in range(n_draws):
        new = []
        for s in sel:
            lg = math.log(s.p / (1 - s.p)) + rng.normal(0, sd_logit)
            new.append(cp.Selection(s.label, 1 / (1 + math.exp(-lg)), s.odds))
        rows = eq_rows(new)
        eff = frontier(rows, "equal_stakes", "recovery_vs_min_payout")
        eff_freq += eff
        union = (eff | base_eff).sum()
        jac.append((eff & base_eff).sum() / union if union else 1.0)
        top_kept += int(np.argmax([r["equal_stakes"]["p_recover"] for r in rows])) == base_top
    return {
        "draws": n_draws,
        "sd_logit": sd_logit,
        "frontier_jaccard_mean": float(np.mean(jac)),
        "frontier_jaccard_min": float(np.min(jac)),
        "top_recovery_partition_kept": top_kept,
        "partitions_ever_efficient": int((eff_freq > 0).sum()),
        "partitions_always_efficient": int((eff_freq == n_draws).sum()),
    }
