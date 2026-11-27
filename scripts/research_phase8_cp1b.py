"""Phase 8 CP1 supplementary research only: Goal Model simplification.

Compares, on identical fixtures (C1-2-20 availability, current season only):
  A    strength / tempo (k_s 12, k_t 96)        - the agreed reference
  B(k) attack x defence with one common k     - k in {6, 12, 24, 48, 96}
  C    attack x defence without shrinkage (k=0)

Protocol: docs/research/phase8_cp1/supplementary_preregistration.md (committed first).
Reuses the CP1 data, 3-hour availability lag, periods and helpers
(scripts/research_phase8_cp1.py). Writes docs/research/phase8_cp1/simplification_*.

Run:  uv run python scripts/research_phase8_cp1b.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import research_phase8_cp1 as r8  # noqa: E402
from research_goal_distribution import calib_slope, metrics  # noqa: E402

from diski9.research import goal_distribution as gd  # noqa: E402
from diski9.research.evaluation import expected_calibration_error  # noqa: E402
from diski9.research.form_score_comparison import write_csv  # noqa: E402

OUT = r8.OUT
K_GRID = (6, 12, 24, 48, 96)
GATE = r8.Candidate("C1-2-20", None, 2, 20)  # availability for every model
TIE = 0.0005
IMPOSSIBLE = 1e-12


# ------------------------------------------------------------------ models
def rates(r: r8.Rows):
    with np.errstate(invalid="ignore", divide="ignore"):
        return r.cur_hg / r.cur_n, r.cur_ag / r.cur_n


def factors(stats: np.ndarray, H, A, k: float):
    """Venue-normalised attack and defence with k pseudo-matches. No safeguard:
    with k = 0 they are the raw ratios GF / E_for and GA / E_ag."""
    n_h, n_a, gf_h, ga_h, gf_a, ga_a = (stats[:, i] for i in range(6))
    g = (H + A) / 2
    e_for = n_h * H + n_a * A
    e_ag = n_h * A + n_a * H
    with np.errstate(invalid="ignore", divide="ignore"):
        return (gf_h + gf_a + k * g) / (e_for + k * g), (ga_h + ga_a + k * g) / (e_ag + k * g)


def model_b(r: r8.Rows, k: float, ok: np.ndarray):
    """Attack x defence (Model B; Model C when k = 0). Unavailable rows: lambda = 1
    placeholders, always masked out by ``ok``."""
    H, A = rates(r)
    Hs, As = np.where(ok, H, 1.0), np.where(ok, A, 1.0)
    ah, dh = factors(r.team[:, :6], Hs, As, k)
    aa, da = factors(r.team[:, 6:], Hs, As, k)
    lh = np.where(ok, Hs * ah * da, 1.0)
    la = np.where(ok, As * aa * dh, 1.0)
    return lh, la, (ah, dh, aa, da)


def model_a(r: r8.Rows, ok: np.ndarray, k_s: float = 12.0, k_t: float = 96.0):
    """Strength / tempo: effective attack s*t and defence t/s (lambda identical to
    H (s_h / s_a) t_h t_a)."""
    H, A = rates(r)
    Hs, As = np.where(ok, H, 1.0), np.where(ok, A, 1.0)
    eff = []
    for blk in (r.team[:, :6], r.team[:, 6:]):
        a1, d1 = factors(blk, Hs, As, k_s)
        a2, d2 = factors(blk, Hs, As, k_t)
        s, t = np.sqrt(a1 / d1), np.sqrt(a2 * d2)
        eff += [s * t, t / s]
    ah, dh, aa, da = eff
    lh = np.where(ok, Hs * ah * da, 1.0)
    la = np.where(ok, As * aa * dh, 1.0)
    return lh, la, (ah, dh, aa, da)


def markets(lh, la):
    return gd.poisson_markets(lh, la)


# ------------------------------------------------------------------ evaluation
def realised_probs(mk: dict, r: r8.Rows) -> np.ndarray:
    """(N, 3): probability given to the realised 1X2, BTTS and O/U outcomes."""
    y = r.outcome
    p1 = np.choose(y, [mk["home"], mk["draw"], mk["away"]])
    pb = np.where(r.btts == 1, mk["btts_yes"], 1 - mk["btts_yes"])
    po = np.where(r.over == 1, mk["over"], 1 - mk["over"])
    return np.column_stack([p1, pb, po])


def robustness(mk: dict, lh, la, r: r8.Rows) -> dict:
    rp = realised_probs(mk, r)
    tot = lh + la
    n = len(r)
    p = np.column_stack([mk["home"], mk["draw"], mk["away"]])
    return {
        "fixtures": n,
        "undefined_or_nonfinite": int((~np.isfinite(lh) | ~np.isfinite(la)).sum()),
        "lambda_zero": int(((lh == 0) | (la == 0)).sum()),
        "lambda_below_0_2": int(((lh < 0.2) | (la < 0.2)).sum()),
        "lambda_above_4": int(((lh > 4) | (la > 4)).sum()),
        "total_lambda": {
            q: round(float(np.quantile(tot, v)), 3)
            for q, v in (("min", 0), ("p1", 0.01), ("median", 0.5), ("p99", 0.99), ("max", 1))
        },
        "max_lambda": round(float(max(lh.max(), la.max())), 3),
        "any_1x2_above_95pct": int((p.max(axis=1) > 0.95).sum()),
        "any_1x2_below_1pct": int((p.min(axis=1) < 0.01).sum()),
        "impossible_events": int((rp < IMPOSSIBLE).sum()),
        "realised_below_0_1pct_fixtures": int((rp.min(axis=1) < 0.001).sum()),
        "realised_below_1pct_fixtures": int((rp.min(axis=1) < 0.01).sum()),
        "share_realised_below_0_1pct": round(float((rp.min(axis=1) < 0.001).mean()), 4),
    }


def calibration(mk: dict, r: r8.Rows) -> dict:
    y = r.outcome
    return {
        "slope_home": calib_slope(mk["home"], (y == 0).astype(int)),
        "ece_home": round(expected_calibration_error(mk["home"], (y == 0).astype(int)), 4),
        "slope_btts": calib_slope(mk["btts_yes"], r.btts),
        "ece_btts": round(expected_calibration_error(mk["btts_yes"], r.btts), 4),
        "slope_ou": calib_slope(mk["over"], r.over),
        "ece_ou": round(expected_calibration_error(mk["over"], r.over), 4),
    }


def compare(cand: dict, ref: dict, r: r8.Rows, cand_rob: dict, ref_rob: dict) -> dict:
    """S1-S5 for a candidate against Model A on identical fixtures."""
    d = r8.deltas(cand, ref, r)
    cc, rc = calibration(cand, r), calibration(ref, r)
    nh, na = r.played
    lo = np.minimum(nh, na)
    band = lo <= 5
    rb = subset_ids(r, band)
    d4 = r8.deltas(r8.take(cand, band), r8.take(r8.baseline(r, GATE), band), rb)["1x2_log_loss"]
    v = {
        "S1": r8.ni_verdict(d["1x2_log_loss"], 0.005),
        "S2_btts": r8.ni_verdict(d["btts_log_loss"], 0.003),
        "S2_ou": r8.ni_verdict(d["ou_log_loss"], 0.003),
        "S3": "pass"
        if (0.8 <= cc["slope_home"] <= 1.25 and cc["ece_home"] <= rc["ece_home"] + 0.01)
        else "fail",
        "S4": "pass" if d4["ci95"][1] < 0 else "fail",
        "S5": "pass"
        if (
            cand_rob["impossible_events"] == 0
            and cand_rob["share_realised_below_0_1pct"]
            <= ref_rob["share_realised_below_0_1pct"] + 0.005
        )
        else "fail",
    }
    return {
        "delta_vs_A": d,
        "S4_band_vs_baseline": d4,
        "calibration": cc,
        "calibration_A": rc,
        "verdicts": v,
        "passes": all(x == "pass" for x in v.values()),
    }


def bands(cand: dict, ref: dict, r: r8.Rows) -> list[dict]:
    nh, na = r.played
    lo = np.minimum(nh, na)
    out = []
    groups = [(str(i), lo == i) for i in (2, 3, 4, 5)]
    groups += [("2-5", lo <= 5), ("6-9", (lo >= 6) & (lo <= 9)), ("10+", lo >= 10)]
    for name, m in groups:
        if m.sum() < 20:
            continue
        rs = subset_ids(r, m)
        d = r8.deltas(r8.take(cand, m), r8.take(ref, m), rs)
        out.append({"band": name, "n": int(m.sum()),
                    **{k: v for k, v in d.items()}})  # fmt: skip
    return out


def per_league(cand: dict, ref: dict, r: r8.Rows) -> list[dict]:
    out = []
    for comp in r8.DOMESTIC:
        m = r.comp == comp
        if m.sum() < 30:
            continue
        rs = subset_ids(r, m)
        d = r8.deltas(r8.take(cand, m), r8.take(ref, m), rs)
        x = d["1x2_log_loss"]
        out.append({
            "competition": r8.NAMES[comp], "n": int(m.sum()), "delta": d,
            "verdict_1x2": r8.ni_verdict(x, 0.005),
            "material_deterioration": bool(x["ci95"][0] > 0 or x["mean"] > 0.010),
        })  # fmt: skip
    return out


def stability(r: r8.Rows, fac) -> dict:
    """|change| in a team's log attack and log defence between consecutive appearances
    one match apart, by match-count band, and after a >= 5-goal match."""
    ah, dh, aa, da = fac
    seq = defaultdict(list)  # (team id, season) -> appearances (ids from attach_ids())
    for i in range(len(r)):
        for side, a, d, blk in (("h", ah[i], dh[i], r.team[i, :6]), ("a", aa[i], da[i],
                                r.team[i, 6:])):  # fmt: skip
            tid = r.home_id[i] if side == "h" else r.away_id[i]
            seq[(int(tid), int(r.season[i]))].append((r.kickoff[i], a, d, blk))
    rows = []
    zero_transitions = 0
    for items in seq.values():
        items.sort(key=lambda x: x[0])
        for (_, a0, d0, b0), (_, a1, d1, b1) in zip(items, items[1:], strict=False):
            n0, n1 = b0[0] + b0[1], b1[0] + b1[1]
            if n1 - n0 != 1:
                continue
            if min(a0, a1, d0, d1) <= 0:
                zero_transitions += 1
                continue
            big = (b1[2] + b1[4] - b0[2] - b0[4]) >= 5 or (b1[3] + b1[5] - b0[3] - b0[5]) >= 5
            rows.append((n0, abs(np.log(a1 / a0)), abs(np.log(d1 / d0)), big))
    out = {"transitions": len(rows), "transitions_involving_zero_factor": zero_transitions}
    arr = np.array([(n, x, y, b) for n, x, y, b in rows], dtype=float)
    groups = (("2-5", arr[:, 0] <= 5), ("6-9", (arr[:, 0] >= 6) & (arr[:, 0] <= 9)),
              ("10+", arr[:, 0] >= 10), ("after_5plus_goal_match", arr[:, 3] == 1))  # fmt: skip
    for name, m in groups:
        if m.sum() == 0:
            continue
        v = np.maximum(arr[m, 1], arr[m, 2])
        out[name] = {"n": int(m.sum()), "median": round(float(np.median(v)), 3),
                     "p95": round(float(np.quantile(v, 0.95)), 3),
                     "max": round(float(v.max()), 3)}  # fmt: skip
    return out


def attach_ids(r: r8.Rows, store) -> r8.Rows:
    ids = {m.fixture_id: (m.home_id, m.away_id) for m in store.matches}
    r.home_id = np.array([ids[int(f)][0] for f in r.fixture])
    r.away_id = np.array([ids[int(f)][1] for f in r.fixture])
    return r


def subset_ids(r: r8.Rows, mask) -> r8.Rows:
    """Rows.subset that also carries the team ids attached by attach_ids()."""
    idx = np.flatnonzero(mask)
    kw = {}
    for f in r8.Rows.__dataclass_fields__:
        v = getattr(r, f)
        kw[f] = [v[i] for i in idx] if isinstance(v, list) else v[idx]
    s = r8.Rows(**kw)
    if hasattr(r, "home_id"):
        s.home_id, s.away_id = r.home_id[idx], r.away_id[idx]
    return s


# ------------------------------------------------------------------ examples
def example(r: r8.Rows, i: int, k_star: float, names) -> dict:
    sub = subset_ids(r, np.arange(len(r)) == i)
    ok = np.array([True])
    H, A = rates(sub)
    out = {
        "fixture_id": int(sub.fixture[0]), "competition": r8.NAMES[int(sub.comp[0])],
        "kickoff": sub.kickoff[0].isoformat(), "home": names.get(int(sub.home_id[0])),
        "away": names.get(int(sub.away_id[0])), "score": f"{int(sub.hg[0])}-{int(sub.ag[0])}",
        "league_home_rate_H": round(float(H[0]), 4), "league_away_rate_A": round(float(A[0]), 4),
        "g": round(float((H[0] + A[0]) / 2), 4),
    }  # fmt: skip
    for side, blk in (("home_team", sub.team[0, :6]), ("away_team", sub.team[0, 6:])):
        n_h, n_a, gfh, gah, gfa, gaa = (float(x) for x in blk)
        out[side] = {
            "played": int(n_h + n_a), "home_played": int(n_h), "away_played": int(n_a),
            "scored": int(gfh + gfa), "conceded": int(gah + gaa),
            "expected_scored": round(n_h * H[0] + n_a * A[0], 3),
            "expected_conceded": round(n_h * A[0] + n_a * H[0], 3),
        }  # fmt: skip
    for name, fn in (("A", lambda: model_a(sub, ok)), (f"B{k_star:g}", lambda: model_b(sub,
                     k_star, ok)), ("C", lambda: model_b(sub, 0.0, ok))):  # fmt: skip
        lh, la, (ah, dh, aa, da) = fn()
        mk = markets(lh, la)
        out[name] = {
            "home_attack": round(float(ah[0]), 4), "home_defence": round(float(dh[0]), 4),
            "away_attack": round(float(aa[0]), 4), "away_defence": round(float(da[0]), 4),
            "lambda_home": round(float(lh[0]), 4), "lambda_away": round(float(la[0]), 4),
            "home": round(float(mk["home"][0]), 4), "draw": round(float(mk["draw"][0]), 4),
            "away": round(float(mk["away"][0]), 4),
            "btts_yes": round(float(mk["btts_yes"][0]), 4),
            "over_2_5": round(float(mk["over"][0]), 4),
        }  # fmt: skip
    return out


def pick_examples(r: r8.Rows, lam_a) -> dict[str, int]:
    nh, na = r.played
    lo = np.minimum(nh, na)
    t = r.team
    gf = (t[:, 2] + t[:, 4], t[:, 8] + t[:, 10])
    ga = (t[:, 3] + t[:, 5], t[:, 9] + t[:, 11])
    tot = lam_a[0] + lam_a[1]
    med = np.median(tot)
    typical = int(np.argmin(np.where(lo >= 10, np.abs(tot - med), np.inf)))
    swing = np.maximum(np.abs(gf[0] - ga[0]), np.abs(gf[1] - ga[1]))
    early = int(np.argmax(np.where(lo == 2, swing, -1)))
    zero = np.where((lo >= 2) & ((gf[0] == 0) | (gf[1] == 0) | (ga[0] == 0) | (ga[1] == 0)))[0]
    zero_i = int(zero[0]) if len(zero) else -1
    rate = ((gf[0] + ga[0]) / np.maximum(nh, 1) + (gf[1] + ga[1]) / np.maximum(na, 1)) / 2
    high = int(np.argmax(np.where(lo >= 6, rate, -1)))
    low = int(np.argmin(np.where(lo >= 6, rate, np.inf)))
    return {"typical": typical, "early_extreme": early, "zero_goals": zero_i,
            "high_scoring": high, "low_scoring": low}  # fmt: skip


# ------------------------------------------------------------------ main
def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        store, stage = r8.load_matches(Path(td))
    dom = r8.build_rows(store, stage, set(r8.DOMESTIC), set(r8.SEASONS))
    dom = attach_ids(dom, store)
    ok_all = r8.predict(dom, GATE)[3]
    r = subset_ids(dom, ok_all)  # identical availability for every model
    names = store.team_names
    summary: dict = {"generated": datetime.now(UTC).isoformat(timespec="seconds"),
                     "available_fixtures": len(r), "all_fixtures": len(dom)}  # fmt: skip

    # equivalence: A with k_s = k_t = k equals B(k)
    ok = np.ones(len(r), bool)
    eq = 0.0
    for k in K_GRID:
        la_, lb_ = model_a(r, ok, k, k), model_b(r, k, ok)
        eq = max(eq, float(np.max(np.abs(la_[0] - lb_[0]))), float(np.max(np.abs(la_[1] -
                 lb_[1]))))  # fmt: skip
    a_ref = r8.predict(r, GATE)
    eq_ref = float(max(np.max(np.abs(model_a(r, ok)[0] - a_ref[1])),
                       np.max(np.abs(model_a(r, ok)[1] - a_ref[2]))))  # fmt: skip
    summary["equivalence"] = {"A_with_equal_k_vs_B_max_abs": eq,
                              "A_here_vs_CP1_C1_2_20_max_abs": eq_ref,
                              "ok": eq < 1e-12 and eq_ref < 1e-12}  # fmt: skip

    sel_m, conf_m = np.isin(r.season, r8.SELECTION), np.isin(r.season, r8.CONFIRMATION)
    sel, conf = subset_ids(r, sel_m), subset_ids(r, conf_m)

    # ---- selection of k (scoreline log-likelihood, selection period only)
    oks = np.ones(len(sel), bool)
    grid = []
    for k in K_GRID:
        lh, la, _ = model_b(sel, k, oks)
        grid.append({"k": k, "score_loglik": float(np.mean(
            gd.poisson_score_logprob(lh, la, sel.hg, sel.ag)))})  # fmt: skip
    lhA, laA, _ = model_a(sel, oks)
    lhC, laC, _ = model_b(sel, 0.0, oks)
    summary["selection"] = {
        "grid": grid,
        "A_score_loglik": float(np.mean(gd.poisson_score_logprob(lhA, laA, sel.hg, sel.ag))),
        "C_score_loglik_finite_rows": float(np.nanmean(np.where(np.isfinite(
            gd.poisson_score_logprob(lhC, laC, sel.hg, sel.ag)),
            gd.poisson_score_logprob(lhC, laC, sel.hg, sel.ag), np.nan))),
        "C_rows_with_zero_likelihood": int((~np.isfinite(gd.poisson_score_logprob(
            lhC, laC, sel.hg, sel.ag))).sum()),
    }  # fmt: skip
    best = max(g["score_loglik"] for g in grid)
    k_star = max(g["k"] for g in grid if g["score_loglik"] >= best - TIE)
    summary["k_star"] = k_star

    # ---- confirmation (evaluated once)
    okc = np.ones(len(conf), bool)
    models = {"A": model_a(conf, okc), f"B{k_star}": model_b(conf, k_star, okc),
              "C": model_b(conf, 0.0, okc)}  # fmt: skip
    if k_star != 12:
        models["B12 (strength-only reference)"] = model_b(conf, 12, okc)
    mks = {n: markets(m[0], m[1]) for n, m in models.items()}
    robs = {n: robustness(mks[n], models[n][0], models[n][1], conf) for n in models}
    summary["confirmation"] = {
        "n": len(conf),
        "metrics": {n: metrics(mks[n], conf) for n in models},
        "calibration": {n: calibration(mks[n], conf) for n in models},
        "robustness": robs,
        "stability": {n: stability(conf, models[n][2]) for n in models},
    }
    for name in (f"B{k_star}", "C"):
        summary["confirmation"][f"{name}_vs_A"] = {
            **compare(mks[name], mks["A"], conf, robs[name], robs["A"]),
            "bands": bands(mks[name], mks["A"], conf),
            "per_league": per_league(mks[name], mks["A"], conf),
        }
    # what the separate tempo parameter adds (A against B(k*)), goals markets
    summary["confirmation"]["A_vs_Bk_star"] = r8.deltas(mks["A"], mks[f"B{k_star}"], conf)
    # secondary: C log loss excluding impossible-event rows
    rp = realised_probs(mks["C"], conf)
    keep = rp.min(axis=1) >= IMPOSSIBLE
    rk = subset_ids(conf, keep)
    summary["confirmation"]["C_sensitivity_excluding_impossible"] = {
        "rows_excluded": int((~keep).sum()),
        "delta_vs_A": r8.deltas(r8.take(mks["C"], keep), r8.take(mks["A"], keep), rk),
    }
    # robustness on the selection period too (frequency, not a criterion)
    summary["selection_robustness"] = {
        n: robustness(markets(m[0], m[1]), m[0], m[1], sel)
        for n, m in (("A", (lhA, laA)), ("C", (lhC, laC)))
    }
    # worked examples
    lamA = model_a(conf, okc)
    picks = pick_examples(conf, lamA)
    summary["examples"] = {k: example(conf, i, k_star, names) for k, i in picks.items()
                           if i >= 0}  # fmt: skip

    (OUT / "simplification_summary.json").write_text(json.dumps(summary, indent=1,
                                                                default=r8._json))  # fmt: skip
    rows = []
    for n in models:
        m, c, rb = summary["confirmation"]["metrics"][n], summary["confirmation"][
            "calibration"][n], robs[n]  # fmt: skip
        rows.append({"model": n, **{k: m[k] for k in ("n", "1x2_log_loss", "btts_log_loss",
                     "ou_log_loss", "1x2_brier")}, **c,
                     **{k: rb[k] for k in ("impossible_events", "lambda_zero",
                        "any_1x2_above_95pct", "realised_below_0_1pct_fixtures")}})  # fmt: skip
    write_csv(OUT / "simplification_comparison.csv", rows)
    print(json.dumps({"k_star": k_star, "equivalence": summary["equivalence"]}))


if __name__ == "__main__":
    main()
