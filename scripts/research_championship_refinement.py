"""Phase 6A.2.1 research: final championship scoring refinement (research only).

Reproduces the Phase 6A.2.1 sections of
docs/research/weekly_challenge_championship_scoring.md:

    uv run python scripts/research_championship_refinement.py            # full run
    uv run python scripts/research_championship_refinement.py --quick    # smoke run (~10%)

It reuses the Phase 6A.2 infrastructure (``research_championship_scoring.py``):
rounds bootstrapped from the real weekend pool, one common simulated scoreline per
fixture (market-implied Poisson rates), the same five diagnostic behaviours and
D-15 settlement.

**Common random numbers.** Each championship's rounds, scorelines and every
participant's portfolio are generated once, from seeds derived from
``(seed, championship, round, participant)``. The resulting settled gross payouts
are then scored under all five scoring scenarios, so differences between scenarios
come only from the scoring rules. The late-championship test re-scores the same
championship with one trailing participant switching behaviour (everyone else's
portfolios and every scoreline unchanged).

**Joint champions** receive fractional win credit 1/k each, so the credits of a
championship always sum to exactly 1 and win shares are never inflated by ties.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import statistics
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

from diski9.research import championship as ch
from diski9.research import risk_structure as rs

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "c62", ROOT / "scripts" / "research_championship_scoring.py"
)
c62 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c62)

OUT = ROOT / "docs" / "research" / "weekly_challenge_championship"
SEED = 62102
ORIG = ch.PROPOSED_TOP10
NEW = ch.REVISED_TOP10
SCENARIOS = {  # name: (top-ten schedule, floor, tie rule)
    "A": (ORIG, 50, "average"),
    "B": (ORIG, 75, "average"),
    "C": (NEW, 75, "average"),
    "D": (NEW, 75, "competition"),
    "E": (ORIG, 50, "competition"),
}
BEHAVIOURS = c62.BEHAVIOURS
HERD_BEHAVIOURS = (*BEHAVIOURS, "herd", "correlated")
FULL_PLAN = [(5, 4000), (10, 3000), (25, 1500), (50, 1000), (100, 600), (250, 400),
             (500, 400), (1000, 300)]  # fmt: skip
HERD_PLAN = [(25, 2000), (100, 800), (500, 200)]
_POOL = None


def pool():
    global _POOL
    if _POOL is None:
        _POOL = json.loads(c62.POOL.read_text())
    return _POOL


def points_fn(scenario):
    top10, floor, ties = SCENARIOS[scenario]
    return lambda gross: ch.position_points(gross, top10, floor, ties)


def herd_roster(n):
    k_herd, k_corr = round(0.20 * n), round(0.10 * n)
    rest = c62.roster(n - k_herd - k_corr)
    return rest + ["herd"] * k_herd + ["correlated"] * k_corr


def build(behaviour, by_band, rng):
    if behaviour == "herd":  # the round's single most popular portfolio: exact duplicates
        return c62._greedy(by_band, lambda o: -o.p_market, rng, 0.0)
    if behaviour == "correlated":  # heavily overlapping popular favourites
        return c62._greedy(by_band, lambda o: -o.p_market, rng, 0.005)
    return c62.build(behaviour, by_band, rng)


def entry_sd(picks):
    m = rs.evaluate(rs.legs(picks, "p_market"), c62.STAKES)
    return m.expected, math.sqrt(sum(p * (float(v) - m.expected) ** 2 for v, p in m.dist))


# ------------------------------------------------------------ one championship
def simulate(args):
    """Simulate one championship and score it under every scenario (CRN)."""
    n, c, seed, herd = args
    people = herd_roster(n) if herd else c62.roster(n)
    rng_round = random.Random(f"{seed}:{n}:{c}:rounds")
    G = []  # G[r][i] settled gross of participant i in round r
    switch_G = {}  # (r, i) -> gross if i switched to lower-in-band (rounds 8-10)
    rounds_ctx = []
    exp_ret = [[] for _ in range(n)]
    sd = [[] for _ in range(n)]
    for r in range(10):
        fixtures, _, by_band = c62.make_round(pool(), rng_round)
        won = c62.simulate_scores(fixtures, "market", rng_round)
        row = []
        for i, beh in enumerate(people):
            picks = build(beh, by_band, random.Random(f"{seed}:{n}:{c}:{r}:{i}"))
            row.append(c62.realised_gross(picks, won))
            e, s = entry_sd(picks)
            exp_ret[i].append(e)
            sd[i].append(s)
        G.append(row)
        rounds_ctx.append((by_band, won))

    def switch_gross(r, i):
        if (r, i) not in switch_G:
            by_band, won = rounds_ctx[r]
            picks = c62.build("lower_in_band", by_band, random.Random(f"{seed}:{n}:{c}:{r}:{i}:sw"))
            switch_G[(r, i)] = c62.realised_gross(picks, won)
        return switch_G[(r, i)]

    ids = list(range(n))
    out = {"weekly": weekly_stats(G), "scen": {}}
    mean_sd = [statistics.fmean(v) for v in sd]
    mean_exp = [statistics.fmean(v) for v in exp_ret]
    for s in SCENARIOS:
        fn = points_fn(s)
        table = {}
        for row in G:
            ch.add_round(table, ids, row, fn)
        st = ch.standings(table)
        champs = [w for pos, w, _ in st if pos == 1]
        credit = Counter()
        for w in champs:
            credit[people[w]] += 1 / len(champs)
        pts = [float(table[i].points) for i in ids]
        ranked = sorted(pts, reverse=True)
        top10_recipients = []
        for row in G:
            ranks = ch.competition_ranks(row)
            top10_recipients.append(
                sum(1 for g, rk in zip(row, ranks, strict=True) if g >= ch.TARGET and rk <= 10)
            )
        res = {
            "credit": dict(credit),
            "joint": len(champs) > 1,
            "n_champions": len(champs),
            "top_two_level": n > 1 and ranked[0] == ranked[1],
            "best_round_share": statistics.fmean(
                float(table[w].best_round / table[w].points) if table[w].points else 0.0
                for w in champs
            ),
            "rho_recoveries": c62.spearman([table[i].recoveries for i in ids], pts),
            "rho_sd": c62.spearman(mean_sd, pts),
            "rho_expected": c62.spearman(mean_exp, pts),
            "zero_share": sum(p == 0 for p in pts) / n,
            "gini": c62.gini(pts),
            "pts_q": quantiles(pts),
            "top10_recipients": statistics.fmean(top10_recipients),
            "over10_recipients": sum(x > 10 for x in top10_recipients) / 10,
            "beh_points": {
                b: statistics.fmean(pts[i] for i in ids if people[i] == b) / 10 for b in set(people)
            },  # fmt: skip
        }
        if n >= 5:
            res["late"] = late_switch(G, ids, fn, table, switch_gross, seed, n, c, s)
        out["scen"][s] = res
    return out


def late_switch(G, ids, fn, full_table, switch_gross, seed, n, c, s):
    """Unilateral deviation: a trailing participant (outside the top three after
    seven rounds) switches to lower-in-band for rounds 8-10; all else unchanged."""
    t7 = {}
    for row in G[:7]:
        ch.add_round(t7, ids, row, fn)
    trailing = [w for pos, w, _ in ch.standings(t7) if pos > 3]
    pick = random.Random(f"{seed}:{n}:{c}:{s}:late").sample(trailing, min(3, len(trailing)))
    stay_st = {w: pos for pos, w, _ in ch.standings(full_table)}
    stay_champs = sum(1 for p in stay_st.values() if p == 1)
    res = []
    for j in pick:
        tbl = {}
        for r, row in enumerate(G):
            row2 = list(row)
            if r >= 7:
                row2[j] = switch_gross(r, j)
            ch.add_round(tbl, ids, row2, fn)
        sw = {w: pos for pos, w, _ in ch.standings(tbl)}
        sw_champs = sum(1 for p in sw.values() if p == 1)
        res.append({
            "stay_win": (stay_st[j] == 1) / stay_champs,
            "switch_win": (sw[j] == 1) / sw_champs,
            "stay_top3": stay_st[j] <= 3,
            "switch_top3": sw[j] <= 3,
            "stay_pos": stay_st[j] / n,
            "switch_pos": sw[j] / n,
        })  # fmt: skip
    return res


def weekly_stats(G):
    any_tie = first_tie = boundary_tie = recov = groups = 0
    for row in G:
        q = sorted((g for g in row if g >= ch.TARGET), reverse=True)
        recov += len(q)
        cnt = Counter(q)
        groups += sum(1 for v in cnt.values() if v > 1)
        any_tie += any(v > 1 for v in cnt.values())
        first_tie += bool(q) and cnt[q[0]] > 1
        pos = 1
        crossed = False
        for g in sorted(cnt, reverse=True):
            k = cnt[g]
            if k > 1 and pos <= 10 < pos + k - 1:
                crossed = True
            pos += k
        boundary_tie += crossed
    r = len(G)
    return {"rounds_with_tie": any_tie / r, "first_place_tie": first_tie / r,
            "boundary_tie": boundary_tie / r, "tie_groups": groups / r,
            "recoverers": recov / r}  # fmt: skip


def quantiles(v):
    s = sorted(v)
    q = lambda p: s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]  # noqa: E731
    return {"p10": q(0.1), "p50": q(0.5), "p90": q(0.9), "max": s[-1]}


# --------------------------------------------------------------- aggregation
def ci(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    m = statistics.fmean(v)
    h = 1.96 * statistics.stdev(v) / math.sqrt(len(v)) if len(v) > 1 else 0.0
    return [round(m, 4), round(h, 4)]


def aggregate(n, sims, herd):
    people = herd_roster(n) if herd else c62.roster(n)
    rep = Counter(people)
    behs = HERD_BEHAVIOURS if herd else BEHAVIOURS
    behs = [b for b in behs if rep[b]]
    weekly = {k: ci([s["weekly"][k] for s in sims]) for k in sims[0]["weekly"]}
    res = {"participants": n, "championships": len(sims),
           "roster": {b: rep[b] for b in behs}, "weekly": weekly}  # fmt: skip
    for sc in SCENARIOS:
        rows = [s["scen"][sc] for s in sims]
        r = {}
        r["win_share"] = {b: ci([x["credit"].get(b, 0.0) for x in rows]) for b in behs}
        r["win_ratio"] = {
            b: [round(r["win_share"][b][0] * n / rep[b], 3),
                round(r["win_share"][b][1] * n / rep[b], 3)]
            for b in behs
        }  # fmt: skip
        for k in ("joint", "top_two_level", "best_round_share", "rho_recoveries", "rho_sd",
                  "rho_expected", "zero_share", "gini", "top10_recipients",
                  "over10_recipients"):  # fmt: skip
            r[k] = ci([float(x[k]) if x[k] is not None else None for x in rows])
        r["n_champions_mean"] = ci([x["n_champions"] for x in rows])
        r["points_quantiles_median"] = {
            q: statistics.median(x["pts_q"][q] for x in rows) for q in ("p10", "p50", "p90", "max")
        }
        r["points_per_round"] = {b: ci([x["beh_points"][b] for x in rows]) for b in behs}
        if "late" in rows[0]:
            late = [y for x in rows for y in x["late"]]
            r["late_switch"] = {
                "cases": len(late),
                "stay_win": ci([y["stay_win"] for y in late]),
                "switch_win": ci([y["switch_win"] for y in late]),
                "win_gain": ci([y["switch_win"] - y["stay_win"] for y in late]),
                "stay_top3": ci([float(y["stay_top3"]) for y in late]),
                "switch_top3": ci([float(y["switch_top3"]) for y in late]),
                "pos_change": ci([y["switch_pos"] - y["stay_pos"] for y in late]),
            }
        res[sc] = r
    # paired (common random numbers) differences against scenario A
    res["paired_vs_A"] = {}
    for sc in "BCDE":
        res["paired_vs_A"][sc] = {
            b: [round(v * n / rep[b], 3) for v in ci([
                s["scen"][sc]["credit"].get(b, 0.0) - s["scen"]["A"]["credit"].get(b, 0.0)
                for s in sims])]
            for b in behs
        }  # fmt: skip
        res["paired_vs_A"][sc]["rho_sd"] = ci(
            [(s["scen"][sc]["rho_sd"] or 0) - (s["scen"]["A"]["rho_sd"] or 0) for s in sims]
        )
    return res


def run(plan, herd, seed, q, workers, log):
    out = []
    for n, reps in plan:
        reps = max(20, int(reps * q))
        t0 = time.time()
        with Pool(workers) as p:
            sims = p.map(simulate, [(n, c, seed, herd) for c in range(reps)], chunksize=4)
        a = aggregate(n, sims, herd)
        a["runtime_seconds"] = round(time.time() - t0, 1)
        out.append(a)
        log(f"{'herd' if herd else 'main'} N={n} reps={reps} {a['runtime_seconds']}s")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    q = 0.1 if args.quick else 1.0
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    def log(msg):
        print(f"[{round(time.time() - t0)}s] {msg}", flush=True)

    results = {
        "config": c62.CFG.name(),
        "seed": SEED,
        "truth": "market",
        "scenarios": {
            k: {"top10": list(v[0]), "floor": v[1], "ties": v[2]} for k, v in SCENARIOS.items()
        },  # fmt: skip
        "win_credit": "joint champions receive 1/k each; credits per championship sum to 1",
        "intervals": "mean and 95% half-width (1.96 x SD / sqrt(championships))",
        "quick": args.quick,
    }
    results["main"] = run(FULL_PLAN, False, SEED, q, args.workers, log)
    results["herd"] = run(HERD_PLAN, True, SEED + 1, q, args.workers, log)
    results["runtime_seconds"] = round(time.time() - t0, 1)
    name = "refinement_results_quick.json" if args.quick else "refinement_results.json"
    (OUT / name).write_text(json.dumps(results, indent=1) + "\n")
    log("done")


if __name__ == "__main__":
    main()
