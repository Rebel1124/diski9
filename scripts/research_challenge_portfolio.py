"""Phase 5B research: Weekly Challenge portfolio optimisation (research only).

Reproduces every number and chart in
``docs/research/weekly_challenge_portfolio_optimisation.md``.

    uv run python scripts/research_challenge_portfolio.py            # synthetic + random + real
    uv run python scripts/research_challenge_portfolio.py --no-real  # skip the database

Real slates are read from the local database (read-only) for a fixed challenge
window; their inputs are frozen to ``docs/research/weekly_challenge/challenge_real_slates.json``.
Re-running with ``--replay`` re-analyses that frozen snapshot instead of the live
database, so the report stays reproducible after odds expire.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from diski9.research import challenge_charts as charts
from diski9.research import challenge_experiments as ce
from diski9.research import challenge_portfolio as cp
from diski9.research.charts import SERIES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "research"
DATA = OUT / "weekly_challenge"
FIG = DATA / "figures"
WINDOW = (datetime(2026, 11, 20, tzinfo=UTC), datetime(2026, 11, 24, tzinfo=UTC))
SEED = 20261117


def S(rows):
    return [cp.Selection(f"S{i + 1}", p, o) for i, (p, o) in enumerate(rows)]


def seeded(n, p_lo, p_hi, edge_lo, edge_hi, seed, margin=1.05):
    """Seeded selections: model p uniform in [p_lo, p_hi]; market probability
    q = p / (1 + edge); odds = round(1 / (q * margin), 2)."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        p = float(rng.uniform(p_lo, p_hi))
        q = min(p / (1 + float(rng.uniform(edge_lo, edge_hi))), 0.97)
        out.append((round(p, 4), max(round(1 / (q * margin), 2), 1.01)))
    return out


SYNTHETIC = {
    "S01 identical (p 0.50, odds 2.00)": S([(0.5, 2.0)] * 9),
    "S02 similar coin-flips": S(seeded(9, 0.45, 0.55, -0.03, 0.03, SEED + 2)),
    "S03 favourites and underdogs": S(
        [
            (0.75, 1.30),
            (0.70, 1.40),
            (0.65, 1.50),
            (0.50, 2.00),
            (0.45, 2.20),
            (0.40, 2.50),
            (0.30, 3.40),
            (0.25, 4.20),
            (0.20, 5.50),
        ]
    ),  # fmt: skip
    "S04 strong favourites (odds ~1.2)": S(seeded(9, 0.78, 0.88, -0.02, 0.02, SEED + 4)),
    "S05 long shots": S(seeded(9, 0.15, 0.30, -0.05, 0.05, SEED + 5)),
    "S06 same odds 2.00, different p": S(
        [(p, 2.0) for p in (0.35, 0.40, 0.44, 0.48, 0.50, 0.52, 0.56, 0.60, 0.65)]
    ),
    "S07 model above market (+15% edge)": S(seeded(9, 0.35, 0.65, 0.12, 0.18, SEED + 7)),
    "S08 model below market (-15% edge)": S(seeded(9, 0.35, 0.65, -0.18, -0.12, SEED + 8)),
    "S09 highly unequal (3 shots, 3 mid, 3 fav)": S(
        [
            (0.15, 6.0),
            (0.18, 5.0),
            (0.2, 4.5),
            (0.45, 2.1),
            (0.5, 1.95),
            (0.55, 1.8),
            (0.8, 1.22),
            (0.82, 1.2),
            (0.85, 1.15),
        ]
    ),  # fmt: skip
    "S10 one bucket insufficient (odds 1.20)": S([(0.80, 1.20)] * 9),
    "S11 two buckets needed (odds 1.30)": S(seeded(9, 0.72, 0.78, -0.02, 0.02, SEED + 11)),
    "S12 extreme favourites (odds 1.03)": S([(0.96, 1.03)] * 9),
    "S13 low odds, mixed (equal payout infeasible)": S(
        [
            (0.85, 1.12),
            (0.82, 1.15),
            (0.80, 1.18),
            (0.3, 3.2),
            (0.28, 3.5),
            (0.25, 4.0),
            (0.75, 1.28),
            (0.72, 1.32),
            (0.7, 1.35),
        ]
    ),  # fmt: skip
}


# --------------------------------------------------------------------- run
def analyse(name, sel, out, full=True):
    t = time.time()
    rows = ce.analyse_slate(sel)
    res = {
        "inputs": [{"label": s.label, "p": s.p, "odds": s.odds} for s in sel],
        "summary": {s: ce.summarise(rows, s) for s in ce.STRATEGIES},
        "summary_whole_credit": {
            s: ce.summarise(rows, s, "1.0") for s in ("equal_payout", "recovery")
        },
        "granularity": ce.granularity(rows),
        "nine_fold": ce.nine_fold_effect(rows),
        "combined": {k: v for k, v in ce.combined_frontier(rows).items() if k != "efficient_ids"},
        "frontiers": {
            f: {s: int(ce.frontier(rows, ce.strategy_key(s), f).sum()) for s in ce.STRATEGIES}
            for f in ce.FRONTIERS
        },
        "squares_vs_range_same": int(sum(r["equal_payout_squares_same"] for r in rows)),
        "examples": example_partitions(rows),
    }
    if full:
        res["dependence"] = ce.dependence_sensitivity(sel, rows)
        res["probability_sensitivity"] = ce.probability_sensitivity(sel)
    out[name] = res
    print(f"{name}: {time.time() - t:.1f}s")
    return rows


def example_partitions(rows):
    """Best equal-stakes recovery partition and its three allocations."""
    i = int(np.argmax([r["equal_stakes"]["p_recover"] for r in rows]))
    r = rows[i]
    keep = ("p_recover", "expected", "sd", "min_bucket_payout", "max_payout", "p_any", "p_profit",
            "bucket_payouts")  # fmt: skip
    return {
        "best_equal_stakes_partition": r["id"],
        "P": r["P"],
        "O": r["O"],
        **{
            k: {"stakes": r[k].get("stakes", [6, 6, 6]), **{m: r[k][m] for m in keep}}
            for k in ("equal_stakes", "equal_payout_0.1", "recovery_0.1", "recovery_cont")
        },
    }


def random_study(n_slates=200, seed=SEED):
    """Seeded random realistic slates: how often does each strategy change recovery?"""
    rng = np.random.default_rng(seed)
    grid = cp.allocations(cp.INCREMENTS["0.5"])
    cred = cp.to_credits(grid)
    tally = {k: 0 for k in ("partitions", "eqpay_better", "eqpay_worse", "eqpay_same",
                            "eqpay_infeasible", "rec_better", "one_bucket_all", "one_bucket_none",
                            "nine_changes_recovery")}  # fmt: skip
    gains, losses, rec_gain = [], [], []
    slates_one_bucket_all = 0
    parts = cp.partitions()
    for _ in range(n_slates):
        sel = []
        for _k in range(9):
            p = float(np.clip(rng.beta(2.2, 2.6), 0.08, 0.92))
            q = float(np.clip(p * math.exp(rng.normal(0, 0.12)), 0.05, 0.95))
            sel.append(cp.Selection("r", p, max(round(1 / (q * 1.05), 2), 1.01)))
        all_one = True
        for part in parts:
            b = cp.bucket_inputs(sel, part)
            eq = cp.metrics_batch(np.array([[6.0, 6.0, 6.0]]), b)
            s_ep, feas = cp.equal_payout_continuous(b.O)
            ep = cp.metrics_batch(s_ep[None, :], b)
            mb = cp.metrics_batch(cred, b)
            rec = mb["p_recover"][cp.best_recovery(b, grid, mb)]
            no9 = cp.metrics_batch(np.array([[6.0, 6.0, 6.0]]), b, include_nine=False)
            d = ep["p_recover"][0] - eq["p_recover"][0]
            tally["partitions"] += 1
            tally["eqpay_infeasible"] += not feas
            if d > cp.PROB_GRID:
                tally["eqpay_better"] += 1
                gains.append(d)
            elif d < -cp.PROB_GRID:
                tally["eqpay_worse"] += 1
                losses.append(d)
            else:
                tally["eqpay_same"] += 1
            if rec - eq["p_recover"][0] > cp.PROB_GRID:
                tally["rec_better"] += 1
                rec_gain.append(rec - eq["p_recover"][0])
            one = bool(eq["one_bucket_recovers"][0])
            tally["one_bucket_all"] += one
            all_one &= one
            tally["nine_changes_recovery"] += (
                eq["p_recover"][0] - no9["p_recover"][0]
            ) > cp.PROB_GRID
        slates_one_bucket_all += all_one
    tally.update(
        slates=n_slates,
        slates_where_every_partition_one_bucket_recovers=slates_one_bucket_all,
        eqpay_gain_mean=float(np.mean(gains)) if gains else 0.0,
        eqpay_gain_max=float(np.max(gains)) if gains else 0.0,
        eqpay_loss_mean=float(np.mean(losses)) if losses else 0.0,
        eqpay_loss_min=float(np.min(losses)) if losses else 0.0,
        rec_gain_mean=float(np.mean(rec_gain)) if rec_gain else 0.0,
        rec_gain_max=float(np.max(rec_gain)) if rec_gain else 0.0,
    )
    return tally


def charts_for(name, rows, tag):
    FIG.mkdir(parents=True, exist_ok=True)
    colours = dict(zip(ce.STRATEGIES, SERIES, strict=False))
    names = {"equal_stakes": "Equal stakes", "equal_payout": "Equal payout (0.1)",
             "recovery": "Recovery-max (0.1)"}  # fmt: skip

    def ser(strats, fr):
        xm, ym, *_ = ce.FRONTIERS[fr]
        return [
            {
                "name": names[s],
                "x": [r[ce.strategy_key(s)][xm] for r in rows],
                "y": [r[ce.strategy_key(s)][ym] for r in rows],
                "efficient": ce.frontier(rows, ce.strategy_key(s), fr).tolist(),
                "color": colours[s],
            }
            for s in strats
        ]

    files = {
        f"{tag}_primary_equal_stakes.svg": charts.scatter_panel(
            ser(["equal_stakes"], "recovery_vs_min_payout"),
            "Probability of recovering 20 credits",
            "Minimum single-bucket gross payout (credits)",
            f"{name}: 280 arrangements, equal stakes 6/6/6/2",
            x_pct=True,
            note="Grey: dominated. Coloured: Pareto-efficient (both axes higher-is-better).",
        ),
        f"{tag}_strategies_min_payout.svg": charts.scatter_panel(
            ser(ce.STRATEGIES, "recovery_vs_min_payout"),
            "Probability of recovering 20 credits",
            "Minimum single-bucket gross payout (credits)",
            f"{name}: recovery vs minimum payout, three allocation rules",
            x_pct=True,
            note="Each rule gives 280 candidates; efficiency computed within each rule.",
        ),
        f"{tag}_recovery_vs_expected.svg": charts.scatter_panel(
            ser(ce.STRATEGIES, "recovery_vs_expected"),
            "Probability of recovering 20 credits",
            "Expected gross return (credits)",
            f"{name}: recovery vs expected return",
            x_pct=True,
        ),
        f"{tag}_mean_variance.svg": charts.scatter_panel(
            ser(ce.STRATEGIES, "mean_variance"),
            "Standard deviation of gross return (credits)",
            "Expected gross return (credits)",
            f"{name}: mean-variance (lower SD, higher mean preferred)",
        ),
    }
    pr = np.array([r["equal_stakes"]["p_recover"] for r in rows])
    edges = np.linspace(pr.min(), pr.max() + 1e-12, 11)
    counts, _ = np.histogram(pr, edges)
    files[f"{tag}_recovery_distribution.svg"] = charts.bars(
        [f"{edges[i] * 100:.1f}" for i in range(10)], [float(c) for c in counts],
        f"{name}: recovery probability across 280 arrangements (equal stakes)",
        "Arrangements", pct=False)  # fmt: skip
    for fname, svg in files.items():
        (FIG / fname).write_text(svg, encoding="utf-8")
    return list(files)


def real_slates(replay: bool):
    snap_path = DATA / "challenge_real_slates.json"
    if replay:
        return json.loads(snap_path.read_text())
    from diski9.config import get_settings
    from diski9.db import make_engine
    from diski9.research import challenge_data as cd

    engine = make_engine(get_settings().database_url)
    now = datetime.now(UTC)
    cands = cd.eligible_candidates(engine, now, *WINDOW)
    slates = {name: cd.build_slate(cands, rule) for name, rule in cd.REAL_RULES.items()}
    snap = {
        "research_snapshot_at": now.isoformat(),
        "note": "Research snapshot only; not an immutable Weekly Challenge submission.",
        "window": [w.isoformat() for w in WINDOW],
        "eligible_fixtures": len(cands),
        "eligible_by_league": {
            str(lg): sum(1 for c in cands if c["league_id"] == lg)
            for lg in sorted({c["league_id"] for c in cands})
        },
        "slates": slates,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    return snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-real", action="store_true")
    ap.add_argument("--replay", action="store_true", help="use the frozen real-slate snapshot")
    ap.add_argument("--random-slates", type=int, default=200)
    args = ap.parse_args()
    out: dict = {"synthetic": {}, "real": {}, "market_implied": {}}
    figs = []
    for name, sel in SYNTHETIC.items():
        rows = analyse(name, sel, out["synthetic"])
        if name.startswith(("S03", "S09")):
            figs += charts_for(name, rows, name[:3].lower())
    if not args.no_real:
        from diski9.research import challenge_data as cd

        snap = real_slates(args.replay)
        out["real_snapshot"] = {k: v for k, v in snap.items() if k != "slates"}
        for name, slate in snap["slates"].items():
            if len(slate) < 9:
                out["real"][name] = {"insufficient": len(slate)}
                continue
            rows = analyse(name, cd.to_selections(slate), out["real"])
            if name.startswith("R2"):
                figs += charts_for(name, rows, "r2")
            if all(s["market_p"] is not None for s in slate):
                analyse(name + " [market-implied p]", cd.to_selections(slate, True),
                        out["market_implied"], full=False)  # fmt: skip
    t = time.time()
    out["random_study"] = random_study(args.random_slates)
    print(f"random study: {time.time() - t:.1f}s")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "challenge_results.json").write_text(json.dumps(out, indent=2, default=float) + "\n")
    print("figures:", ", ".join(figs))


if __name__ == "__main__":
    main()
