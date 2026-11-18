"""Phase 6A.1 research: risk-structured Weekly Challenge (research only).

Reproduces every number in docs/research/weekly_challenge_risk_structure.md from
the frozen real pools in docs/research/weekly_challenge_risk/:

    uv run python scripts/research_risk_structure.py            # all experiments
    uv run python scripts/research_risk_structure.py --quick    # smaller samples

Data provenance (see the report): pool_weekend.json / pool_fortnight.json are real,
read-only, point-in-time snapshots (as of 2026-11-17 22:00 UTC) built by
``diski9.research.risk_pool.build_pool``. Bootstrapped pools and simulated match
results are synthetic and labelled as such.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path

from diski9.challenge import portfolio as pf
from diski9.research import charts
from diski9.research import risk_structure as rs

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "research" / "weekly_challenge_risk"
SEED = 61101


def load(name):
    return json.loads((OUT / f"pool_{name}.json").read_text())


def configs():
    return [rs.Config(b, s, a) for b in rs.BAND_SETS for s in rs.SIZES for a in rs.ALLOCATIONS]


# ------------------------------------------------------------- E1 feasibility
def feasibility(pools):
    res = {}
    for pname, outs in pools.items():
        for b in rs.BAND_SETS:
            for s in rs.SIZES:
                cfg = rs.Config(b, s, "30/30/30/10")
                for src in ("p_model", "p_market"):
                    res[f"{pname}|{b}|{s}|{src}"] = {
                        "portfolios": rs.count_portfolios(outs, cfg, src),
                        "availability": rs.band_availability(outs, cfg, src),
                    }
    return res


def feasibility_by_pool_size(outs, n_draws, sizes=(10, 15, 20, 30, 45)):
    """Synthetic: random fixture subsets of the real weekend pool."""
    rng = random.Random(SEED)
    fixtures = sorted({o.fixture_id for o in outs}, key=str)
    by_fx = {}
    for o in outs:
        by_fx.setdefault(o.fixture_id, []).append(o)
    res = {}
    for n in sizes:
        subsets = [rng.sample(fixtures, n) for _ in range(n_draws)]
        for b in rs.BAND_SETS:
            for s in rs.SIZES:
                cfg = rs.Config(b, s, "30/30/30/10")
                for src in ("p_model", "p_market"):
                    ok = sum(
                        rs.count_portfolios([o for f in sub for o in by_fx[f]], cfg, src) > 0
                        for sub in subsets
                    )
                    res[f"{n}|{b}|{s}|{src}"] = ok / n_draws
    return res


def feasibility_by_league(pool):
    res = {}
    for lg in sorted({f["league_id"] for f in pool["fixtures"]}):
        sub = {"fixtures": [f for f in pool["fixtures"] if f["league_id"] == lg]}
        outs = rs.pool_outcomes(sub)
        for b in rs.BAND_SETS:
            for s in rs.SIZES:
                cfg = rs.Config(b, s, "30/30/30/10")
                res[f"{lg}|{b}|{s}"] = rs.count_portfolios(outs, cfg, "p_model")
    return res


# -------------------------------------------------- E3/E4 portfolio metrics
def summarise(metrics):
    if not metrics:
        return None

    def mean(f):
        return statistics.fmean(f(m) for m in metrics)

    pr = [m.p_recover for m in metrics]
    return {
        "n": len(metrics),
        "p_recover_mean": mean(lambda m: m.p_recover),
        "p_recover_p10": sorted(pr)[int(0.1 * len(pr))],
        "p_recover_p90": sorted(pr)[int(0.9 * len(pr)) - 1 if len(pr) > 1 else 0],
        "expected_mean": mean(lambda m: m.expected),
        "p_zero_mean": mean(lambda m: m.p_zero),
        "median_payout_mean": mean(lambda m: float(m.median)),
        "q90_payout_mean": mean(lambda m: float(m.q90)),
        "max_payout_mean": mean(lambda m: float(m.max_payout)),
        "max_payout_max": max(float(m.max_payout) for m in metrics),
        "p_bucket_mean": [mean(lambda m, j=j: m.p_bucket[j]) for j in range(3)],
        "payout_bucket_mean": [mean(lambda m, j=j: float(m.payout_bucket[j])) for j in range(3)],
        "p_wins_mean": [mean(lambda m, k=k: m.p_wins[k]) for k in range(4)],
        "p_nine_mean": mean(lambda m: m.p_nine),
        "only_all_nine_share": mean(lambda m: float(m.only_all_nine_recovers)),
        "a_alone_share": mean(lambda m: float(m.a_alone_recovers)),
    }


def structured_metrics(outs, n_random):
    rng = random.Random(SEED + 3)
    res = {}
    for cfg in configs():
        if rs.count_portfolios(outs, cfg) == 0:
            res[cfg.name()] = {"feasible": False}
            continue
        entry = {"feasible": True}
        for strat in rs.STRATEGIES:
            reps = n_random if strat == "random" else 1
            model, market = [], []
            for _ in range(reps):
                picks = rs.build_structured(outs, cfg, strat, rng)
                if picks is None:
                    continue
                model.append(rs.evaluate(rs.legs(picks, "p_model"), cfg.stakes))
                market.append(rs.evaluate(rs.legs(picks, "p_market"), cfg.stakes))
            entry[strat] = {"model": summarise(model), "market": summarise(market)}
        res[cfg.name()] = entry
    return res


def free_metrics(outs, n_random):
    """Original design: free choice of nine, grouped by the Phase 6A recommendation."""
    rng = random.Random(SEED + 4)
    res = {}
    for strat in rs.STRATEGIES:
        reps = n_random if strat == "random" else 1
        model, market = [], []
        for _ in range(reps):
            picks = rs.build_free(outs, strat, rng)
            m, k = evaluate_free(picks)
            model.append(m)
            market.append(k)
        res[strat] = {"model": summarise(model), "market": summarise(market)}
    return res


def evaluate_free(picks):
    sels = [
        pf.make_selection(f"x{i}", o.fixture_id, o.p_model, o.odds) for i, o in enumerate(picks)
    ]
    rec = pf.evaluate_all(sels).recommended
    buckets = [[picks[i] for i in b.positions] for b in rec.buckets]
    stakes = (30, 30, 30, 10)
    return (rs.evaluate(rs.legs(buckets, "p_model"), stakes),
            rs.evaluate(rs.legs(buckets, "p_market"), stakes))  # fmt: skip


def flexible_rules(outs, n_random):
    """Flexible candidates: how many random free portfolios satisfy each rule, and
    how rule-satisfying portfolios behave (Phase 6A grouping, 30/30/30/10)."""
    rng = random.Random(SEED + 5)
    res = {}
    samples = []
    for _ in range(n_random):
        picks = rs.build_free(outs, "random", rng)
        samples.append(picks)
    for rule in rs.FLEX_RULES:
        ok = [p for p in samples if rule.ok([o.p_model for o in p])]
        model = [evaluate_free(p)[0] for p in ok[: max(50, n_random // 4)]]
        # constructive: favourite-anchored portfolio satisfying the rule
        res[rule.name] = {
            "description": rule.description,
            "share_of_random_free_portfolios": len(ok) / len(samples),
            "model": summarise(model),
        }
    return res


# ------------------------------------------------- E5 model vs market bands
def classification_agreement(outs):
    res = {}
    for b, bands in rs.BAND_SETS.items():
        cm = Counter()
        for o in outs:
            cm[(rs.classify(o.p_model, bands), rs.classify(o.p_market, bands))] += 1
        same = sum(v for (x, y), v in cm.items() if x == y)
        in_any = sum(v for (x, y), v in cm.items() if x is not None or y is not None)
        same_in = sum(v for (x, y), v in cm.items() if x == y and x is not None)
        res[b] = {
            "agree_including_unbanded": same / len(outs),
            "agree_among_banded": same_in / in_any if in_any else None,
            "matrix": {f"{x}->{y}": v for (x, y), v in sorted(cm.items(), key=str)},
        }
    diffs = [o.p_model - o.p_market for o in outs]
    hi = [o.p_model - o.p_market for o in outs if o.p_market >= 0.6]
    lo = [o.p_model - o.p_market for o in outs if o.p_market < 0.25]
    res["gap"] = {
        "mean_model_minus_market": statistics.fmean(diffs),
        "mean_gap_market_ge_60": statistics.fmean(hi) if hi else None,
        "mean_gap_market_lt_25": statistics.fmean(lo) if lo else None,
        "n_market_ge_60": len(hi),
        "n_market_lt_25": len(lo),
    }
    return res


# ----------------------------------------------------------- E6 sensitivity
def sensitivity(outs, n_draws, sd=0.3):
    rng = random.Random(SEED + 6)
    res = {}
    for b, bands in rs.BAND_SETS.items():
        moved = 0
        total = 0
        for _ in range(n_draws):
            for o in outs:
                lg = math.log(o.p_model / (1 - o.p_model)) + rng.gauss(0, sd)
                p2 = 1 / (1 + math.exp(-lg))
                total += 1
                moved += rs.classify(p2, bands) != rs.classify(o.p_model, bands)
        res[b] = {"reclassified_share": moved / total}
    return res


# ------------------------------------------------- E7 leaderboard simulation
def bootstrap_pool(pool, rng, n=60):
    fx = [f for f in pool["fixtures"] if any(o["eligible"] for o in f["outcomes"])]
    chosen = [rng.choice(fx) for _ in range(n)]
    return [dict(f, fixture_id=f"{f['fixture_id']}#{i}") for i, f in enumerate(chosen)]


def simulate_results(fixtures, truth, rng):
    """One scoreline per fixture: Poisson goals from the truth scenario's rates."""

    def poisson(lam):
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= L:
                return k
            k += 1

    won = set()
    for f in fixtures:
        lam = f["lambda_model"] if truth == "model" else (f["lambda_market"] or f["lambda_model"])
        h, a = poisson(lam[0]), poisson(lam[1])
        result = "home" if h > a else "draw" if h == a else "away"
        btts = "btts_yes" if h and a else "btts_no"
        goals = "over" if h + a >= 3 else "under"
        keys = {result, btts, goals}
        for k in keys:
            won.add((f["fixture_id"], k))
    return won


def realised(buckets, stakes, won):
    gross = Decimal(0)
    wins = []
    for b, s in zip(buckets, stakes[:3], strict=True):
        w = all((o.fixture_id, o.key) in won for o in b)
        wins.append(w)
        if w:
            gross += rs._round(s * math.prod((o.odds for o in b), start=Decimal(1)))
    if all(wins):
        o9 = math.prod((o.odds for b in buckets for o in b), start=Decimal(1))
        gross += rs._round(stakes[3] * o9)
    return float(gross)


MIX = {"random": 0.4, "favourite": 0.15, "longshot": 0.15, "midband": 0.15, "model_value": 0.15}


def season(pool, design, truth, rounds, players, rng_seed):
    rng = random.Random(rng_seed)
    roster = [s for s, w in MIX.items() for _ in range(round(w * players))]
    nets = [[0.0] * rounds for _ in roster]
    for r in range(rounds):
        fixtures = bootstrap_pool(pool, rng)
        outs = rs.pool_outcomes({"fixtures": fixtures})
        won = simulate_results(fixtures, truth, rng)
        for i, strat in enumerate(roster):
            noise = 0.0 if strat == "random" else 0.04
            if design == "original":
                picks = rs.build_free(outs, strat, rng, noise=noise)
                sels = [pf.make_selection(f"x{k}", o.fixture_id, o.p_model, o.odds)
                        for k, o in enumerate(picks)]  # fmt: skip
                rec = pf.evaluate_all(sels).recommended
                buckets = [[picks[k] for k in b.positions] for b in rec.buckets]
                stakes = (30, 30, 30, 10)
            else:
                cfg = design
                picks = rs.build_structured(outs, cfg, strat, rng, noise=noise)
                if picks is None:
                    nets[i][r] = float("nan")
                    continue
                buckets, stakes = picks, cfg.stakes
            nets[i][r] = realised(buckets, stakes, won) - 100
    return roster, nets


def season_stats(roster, nets):
    totals = [sum(x for x in row if x == x) for row in nets]
    order = sorted(range(len(roster)), key=lambda i: -totals[i])
    winner = order[0]
    best_round = max(nets[winner])
    top10 = Counter(roster[i] for i in order[:10])
    by_strat = {}
    for s in MIX:
        vals = [totals[i] for i in range(len(roster)) if roster[i] == s]
        by_strat[s] = {"mean_total": statistics.fmean(vals), "sd_total": statistics.pstdev(vals)}
    all_rounds = [x for row in nets for x in row if x == x]
    positive = sorted((x for x in all_rounds if x > 0), reverse=True)
    top1 = sum(positive[: max(1, len(positive) // 100)]) / sum(positive) if positive else 0
    return {
        "winner_strategy": roster[winner],
        "winner_total": totals[winner],
        "winner_best_round_share": best_round / totals[winner] if totals[winner] > 0 else None,
        "top10_strategies": dict(top10),
        "by_strategy": by_strat,
        "top1pct_share_of_positive_net": top1,
        "infeasible_entries": sum(1 for row in nets for x in row if x != x),
    }


def leaderboard(pool, designs, rounds, players, seasons):
    res = {}
    for name, design in designs.items():
        for truth in ("model", "market"):
            stats = []
            for k in range(seasons):
                roster, nets = season(pool, design, truth, rounds, players, SEED + 100 + k)
                stats.append(season_stats(roster, nets))
            wins = Counter(s["winner_strategy"] for s in stats)
            shares = [s["winner_best_round_share"] for s in stats if s["winner_best_round_share"]]
            res[f"{name}|{truth}"] = {
                "seasons": seasons,
                "winner_strategy_counts": dict(wins),
                "winner_best_round_share_median": statistics.median(shares) if shares else None,
                "top1pct_share_median": statistics.median(
                    s["top1pct_share_of_positive_net"] for s in stats
                ),  # fmt: skip
                "mean_total_by_strategy": {
                    s: statistics.fmean(x["by_strategy"][s]["mean_total"] for x in stats)
                    for s in MIX
                },
                "infeasible_entries": sum(s["infeasible_entries"] for s in stats),
            }
    return res


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    n_random = 100 if args.quick else 400
    n_sub = 100 if args.quick else 400
    seasons = 3 if args.quick else 10
    t0 = time.time()
    weekend, fortnight = load("weekend"), load("fortnight")
    pools = {"weekend": rs.pool_outcomes(weekend), "fortnight": rs.pool_outcomes(fortnight)}
    out = {
        "pool_summary": {
            k: {"fixtures": len({o.fixture_id for o in v}), "outcomes": len(v)}
            for k, v in pools.items()
        }
    }
    out["feasibility"] = feasibility(pools)
    print("E1", round(time.time() - t0, 1))
    out["feasibility_by_pool_size"] = feasibility_by_pool_size(pools["weekend"], n_sub)
    out["feasibility_by_league"] = feasibility_by_league(weekend)
    print("E2", round(time.time() - t0, 1))
    out["structured"] = structured_metrics(pools["weekend"], n_random)
    print("E3", round(time.time() - t0, 1))
    out["original"] = free_metrics(pools["weekend"], n_random)
    out["flexible"] = flexible_rules(pools["weekend"], n_random)
    print("E4", round(time.time() - t0, 1))
    out["classification"] = classification_agreement(pools["weekend"])
    out["sensitivity"] = sensitivity(pools["weekend"], 20)
    designs = {
        "original": "original",
        "Broad-60 · 3/3/3 · 40/30/20/10": rs.Config("Broad-60", "3/3/3", "40/30/20/10"),
        "Broad · 3/3/3 · 30/30/30/10": rs.Config("Broad", "3/3/3", "30/30/30/10"),
        "Broad-55 · 4/3/2 · 40/30/20/10": rs.Config("Broad-55", "4/3/2", "40/30/20/10"),
    }
    out["leaderboard"] = leaderboard(weekend, designs, rounds=30, players=100, seasons=seasons)
    print("E7", round(time.time() - t0, 1))
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    # figure: feasible share by pool size (model probabilities, 3/3/3)
    cats = ["10", "15", "20", "30", "45"]
    charts.grouped_bars(
        OUT / "feasibility_by_pool_size.svg",
        cats,
        {
            b: [out["feasibility_by_pool_size"][f"{n}|{b}|3/3/3|p_model"] * 100 for n in cats]
            for b in ("Broad", "Broad-60", "Broad-55")
        },  # fmt: skip
        "Share of random fixture pools where a 3/3/3 portfolio is possible (Goal Model bands)",
        "% of pools",
        y_max=100,
    )
    print("done", round(time.time() - t0, 1))


if __name__ == "__main__":
    main()
