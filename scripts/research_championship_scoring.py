"""Phase 6A.2 research: championship scoring diagnostics (research only).

Reproduces docs/research/weekly_challenge_championship_scoring.md:

    uv run python scripts/research_championship_scoring.py           # full (about 25 minutes)
    uv run python scripts/research_championship_scoring.py --quick   # smaller samples

Primary scenario: Broad-60 bands, 4/3/2 picks, 40/30/20/10 credits, buckets assigned
by margin-adjusted market probability (the approved MVP). Rounds are synthetic
pools bootstrapped from the real 20-23 Nov 2026 weekend pool (60 fixtures). Every
participant faces the same simulated scoreline per fixture, drawn from Poisson
goal rates: market-implied rates (primary) or Goal Model 1.0 rates
(sensitivity). The selection behaviours are diagnostic only.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from diski9.research import championship as ch
from diski9.research import risk_structure as rs

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "docs" / "research" / "weekly_challenge_risk" / "pool_weekend.json"
OUT = ROOT / "docs" / "research" / "weekly_challenge_championship"
SEED = 62002
CFG = rs.Config("Broad-60", "4/3/2", "40/30/20/10")
STAKES = CFG.stakes
BEHAVIOURS = ("random", "higher_in_band", "lower_in_band", "recovery_focused", "disagreement")
MIX = {"random": 0.30, "higher_in_band": 0.20, "lower_in_band": 0.20,
       "recovery_focused": 0.15, "disagreement": 0.15}  # fmt: skip


def roster(n):
    if n <= len(BEHAVIOURS):
        return list(BEHAVIOURS[:n])
    counts = {b: max(1, round(w * n)) for b, w in MIX.items()}
    while sum(counts.values()) > n:
        counts[max(counts, key=counts.get)] -= 1
    while sum(counts.values()) < n:
        counts["random"] += 1
    return [b for b in BEHAVIOURS for _ in range(counts[b])]


# ------------------------------------------------------------------ rounds
def make_round(pool, rng):
    fx = [f for f in pool["fixtures"] if any(o["eligible"] for o in f["outcomes"])]
    chosen = [dict(rng.choice(fx)) for _ in range(60)]
    for i, f in enumerate(chosen):
        f["fixture_id"] = f"{f['fixture_id']}#{i}"
    outs = rs.pool_outcomes({"fixtures": chosen})
    by_band = [[o for o in outs if rs.classify(o.p_market, CFG.band_tuple) == b] for b in range(3)]
    return chosen, outs, by_band


def simulate_scores(fixtures, truth, rng):
    def poisson(lam):
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1

    won = set()
    for f in fixtures:
        lam = f["lambda_market"] if truth == "market" and f["lambda_market"] else f["lambda_model"]
        h, a = poisson(lam[0]), poisson(lam[1])
        result = "home" if h > a else "draw" if h == a else "away"
        won.update({(f["fixture_id"], result),
                    (f["fixture_id"], "btts_yes" if h and a else "btts_no"),
                    (f["fixture_id"], "over" if h + a >= 3 else "under")})  # fmt: skip
    return won


def _greedy(by_band, key, rng, noise):
    need = list(CFG.size_tuple)
    order = sorted(range(3), key=lambda b: len({o.fixture_id for o in by_band[b]}) - need[b])
    for attempt in range(25):
        used, picks = set(), [[], [], []]
        jitter = noise + 0.02 * attempt
        for b in order:
            cands = sorted(
                by_band[b], key=lambda o: key(o) + (rng.gauss(0, jitter) if jitter else 0)
            )
            for o in cands:
                if len(picks[b]) == need[b]:
                    break
                if o.fixture_id not in used:
                    picks[b].append(o)
                    used.add(o.fixture_id)
            if len(picks[b]) < need[b]:
                break
        else:
            return picks
    return None


def p_recover(picks, src="p_market"):
    return rs.evaluate(rs.legs(picks, src), STAKES).p_recover


def build(behaviour, by_band, rng):
    if behaviour == "random":
        return _greedy(by_band, lambda o: rng.random(), rng, 0.0)
    if behaviour == "higher_in_band":
        return _greedy(by_band, lambda o: -o.p_market, rng, 0.03)
    if behaviour == "lower_in_band":
        return _greedy(by_band, lambda o: o.p_market, rng, 0.03)
    if behaviour == "disagreement":  # largest model-over-market gap
        return _greedy(by_band, lambda o: -(o.p_model - o.p_market), rng, 0.02)
    if behaviour == "recovery_focused":  # best market recovery among a few candidates
        cands = [_greedy(by_band, lambda o: rng.random(), rng, 0.0) for _ in range(6)]
        cands.append(_greedy(by_band, lambda o: -o.p_market, rng, 0.03))
        return max((c for c in cands if c), key=p_recover)
    raise ValueError(behaviour)


def realised_gross(picks, won):
    gross, wins = Decimal(0), []
    for b, s in zip(picks, STAKES[:3], strict=True):
        w = all((o.fixture_id, o.key) in won for o in b)
        wins.append(w)
        if w:
            gross += rs._round(s * math.prod((o.odds for o in b), start=Decimal(1)))
    if all(wins):
        gross += rs._round(
            STAKES[3] * math.prod((o.odds for b in picks for o in b), start=Decimal(1))
        )
    return gross


def entry_stats(picks, truth):
    m = rs.evaluate(rs.legs(picks, "p_market" if truth == "market" else "p_model"), STAKES)
    var = sum(p * (float(v) - m.expected) ** 2 for v, p in m.dist)
    return m.expected, math.sqrt(var), m.p_recover


# -------------------------------------------------------------- championships
def championship(pool, n, truth, rng, participation="full", floors=(25, 50, 75)):
    people = roster(n)
    join = {i: 0 for i in range(n)}
    p_miss = 0.0
    if participation == "realistic":
        late = rng.sample(range(n), k=max(1, n // 5)) if n >= 5 else []
        join.update({i: 3 for i in late})  # join at round 4
        p_miss = 0.2
    tables = {s: {} for s in ch.SYSTEMS}
    floor_tables = {f: {} for f in floors}
    exp_ret = defaultdict(list)
    sd = defaultdict(list)
    prec = defaultdict(list)
    weekly_tie_groups = 0
    weekly_rounds = 0
    for r in range(10):
        fixtures, outs, by_band = make_round(pool, rng)
        won = simulate_scores(fixtures, truth, rng)
        entrants, gross = [], []
        for i, beh in enumerate(people):
            if r < join[i] or rng.random() < p_miss:
                continue
            picks = build(beh, by_band, rng)
            g = realised_gross(picks, won)
            entrants.append(i)
            gross.append(g)
            e, s, p = entry_stats(picks, truth)
            exp_ret[i].append(e)
            sd[i].append(s)
            prec[i].append(p)
        if not entrants:
            continue
        weekly_rounds += 1
        qual = [g for g in gross if g >= ch.TARGET]
        weekly_tie_groups += sum(1 for v in Counter(qual).values() if v > 1)
        for s in ch.SYSTEMS:
            ch.add_round(tables[s], entrants, gross, s)
        for f in floors:
            pts = ch.proposed_points(gross, floor=f)
            for i, p in zip(entrants, pts, strict=True):
                floor_tables[f].setdefault(i, Fraction(0))
                floor_tables[f][i] += p
    return people, tables, floor_tables, exp_ret, sd, prec, weekly_tie_groups, weekly_rounds, join


def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                rk[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return rk

    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def gini(vals):
    v = sorted(float(x) for x in vals)
    n, s = len(v), sum(v)
    if not n or s <= 0:
        return None
    return sum((2 * (i + 1) - n - 1) * x for i, x in enumerate(v)) / (n * s)


def experiment(pool, n, truth, reps, participation, seed):
    rng = random.Random(seed)
    agg = {s: defaultdict(list) for s in ch.SYSTEMS}
    floor_agg = {f: defaultdict(list) for f in (25, 50, 75)}
    beh_points = {s: defaultdict(list) for s in ch.SYSTEMS}
    late_rank = defaultdict(list)
    tie_groups = rounds = 0
    for _ in range(reps):
        people, tables, ftables, exp_ret, sd, prec, tg, wr, join = championship(
            pool, n, truth, rng, participation
        )
        tie_groups += tg
        rounds += wr
        for s, table in tables.items():
            st = ch.standings(table)
            champs = [w for pos, w, _ in st if pos == 1]
            a = agg[s]
            for w in champs:
                a["champion_behaviour"].append((people[w], 1 / len(champs)))
            a["joint_champions"].append(len(champs) > 1)
            top = [r for pos, _, r in st if pos == 1][0]
            a["champ_best_round_share"].append(
                float(top.best_round / top.points) if top.points > 0 else None
            )
            pts = {w: float(r.points) for _, w, r in st}
            ids = list(pts)
            a["rho_recoveries"].append(
                spearman([table[w].recoveries for w in ids], [pts[w] for w in ids])
            )
            a["rho_expected"].append(
                spearman([statistics.fmean(exp_ret[w]) for w in ids], [pts[w] for w in ids])
            )
            a["rho_sd"].append(
                spearman([statistics.fmean(sd[w]) for w in ids], [pts[w] for w in ids])
            )
            a["zero_points_share"].append(sum(r.points == 0 for _, _, r in st) / len(st))
            if s != "cumulative_net":
                a["gini"].append(gini([r.points for _, _, r in st]))
            # tie-break use: groups equal on points
            ranked_pts = sorted((r.points for _, _, r in st), reverse=True)
            a["tiebreak_needed"].append(len(ranked_pts) > 1 and ranked_pts[0] == ranked_pts[1])
            best = {}
            for pos, w, _ in st:
                b = people[w]
                best[b] = min(best.get(b, 10**9), pos)
            if "recovery_focused" in best and "lower_in_band" in best:
                a["recovery_beats_lower"].append(best["recovery_focused"] < best["lower_in_band"])
            for _, w, r in st:
                beh_points[s][people[w]].append(float(r.points) / max(r.entered, 1))
            if participation == "realistic":
                n_st = len(st)
                for pos, w, _ in st:
                    late_rank["late" if join[w] else "full"].append(pos / n_st)
        for f, tbl in ftables.items():
            order = sorted(tbl, key=lambda w: -tbl[w])
            top = tbl[order[0]]
            champs = [w for w in order if tbl[w] == top]
            for w in champs:
                floor_agg[f]["champion_behaviour"].append((people[w], 1 / len(champs)))
            ids = list(tbl)
            rec = [tables["proposed"][w].recoveries for w in ids]
            floor_agg[f]["rho_recoveries"].append(spearman(rec, [float(tbl[w]) for w in ids]))

    def share(pairs):
        c = Counter()
        for b, wgt in pairs:
            c[b] += wgt
        tot = sum(c.values())
        return {b: round(c[b] / tot, 3) for b in BEHAVIOURS}

    def mean(v):
        v = [x for x in v if x is not None]
        return round(statistics.fmean(v), 3) if v else None

    res = {
        "participants": n,
        "truth": truth,
        "championships": reps,
        "participation": participation,
        "weekly_qualifying_tie_groups_per_round": round(tie_groups / max(rounds, 1), 4),
    }
    for s, a in agg.items():
        res[s] = {
            "champion_behaviour_share": share(a["champion_behaviour"]),
            "joint_champions_rate": mean(a["joint_champions"]),
            "tiebreak_needed_rate": mean(a["tiebreak_needed"]),
            "champion_best_round_share_median": round(
                statistics.median([x for x in a["champ_best_round_share"] if x is not None]), 3
            )
            if any(x is not None for x in a["champ_best_round_share"])
            else None,  # fmt: skip
            "rho_recoveries_points": mean(a["rho_recoveries"]),
            "rho_expected_points": mean(a["rho_expected"]),
            "rho_sd_points": mean(a["rho_sd"]),
            "zero_points_share": mean(a["zero_points_share"]),
            "gini": mean(a.get("gini", [])),
            "recovery_beats_lower_rate": mean(a["recovery_beats_lower"]),
            "points_per_round_by_behaviour": {b: mean(beh_points[s][b]) for b in BEHAVIOURS},
        }
    res["floor_sensitivity"] = {
        str(f): {
            "champion_behaviour_share": share(v["champion_behaviour"]),
            "rho_recoveries_points": mean(v["rho_recoveries"]),
        }  # fmt: skip
        for f, v in floor_agg.items()
    }
    if late_rank:
        res["late_or_missing_relative_rank"] = {k: mean(v) for k, v in late_rank.items()}
    return res


def behaviour_profile(pool, reps, seed):
    """Per-entry statistics by behaviour (market probabilities), one per round."""
    rng = random.Random(seed)
    stats = defaultdict(lambda: defaultdict(list))
    for _ in range(reps):
        _, _, by_band = make_round(pool, rng)
        for b in BEHAVIOURS:
            picks = build(b, by_band, rng)
            m = rs.evaluate(rs.legs(picks, "p_market"), STAKES)
            var = sum(p * (float(v) - m.expected) ** 2 for v, p in m.dist)
            stats[b]["p_recover"].append(m.p_recover)
            stats[b]["expected"].append(m.expected)
            stats[b]["sd"].append(math.sqrt(var))
            stats[b]["p_zero"].append(m.p_zero)
            stats[b]["max"].append(float(m.max_payout))
            mm = rs.evaluate(rs.legs(picks, "p_model"), STAKES)
            stats[b]["p_recover_model"].append(mm.p_recover)
    return {b: {k: round(statistics.fmean(v), 4) for k, v in d.items()} for b, d in stats.items()}


def feasibility_check(pool, n_rounds, seed):
    """Feasibility of bootstrapped rounds and of smaller real sub-pools."""
    rng = random.Random(seed)
    league = {f["fixture_id"]: f["league_id"] for f in pool["fixtures"]}
    fx = [f for f in pool["fixtures"] if any(o["eligible"] for o in f["outcomes"])]

    def cls(o):
        return rs.classify(o.p_market, CFG.band_tuple)

    out = {}
    for size in (10, 15, 20, 30):
        opened = exists = 0
        for _ in range(n_rounds):
            sub = rng.sample(fx, size)
            outs = rs.pool_outcomes({"fixtures": sub})
            r = ch.round_feasibility(outs, cls, league)
            opened += r["opens"]
            exists += r["portfolio_exists"]
        out[str(size)] = {"portfolio_exists": exists / n_rounds, "opens": opened / n_rounds}
    full = ch.round_feasibility(rs.pool_outcomes(pool), cls, league)
    out["real_weekend_pool"] = full
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    q = 0.1 if args.quick else 1.0
    pool = json.loads(POOL.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    results = {"config": CFG.name(), "classification": "p_market", "seed": SEED}
    results["feasibility"] = feasibility_check(pool, int(400 * q) or 20, SEED + 1)
    results["behaviour_profile"] = behaviour_profile(pool, int(300 * q) or 20, SEED + 2)
    print("profile", round(time.time() - t0))
    plan = [(5, "market", 2000), (10, "market", 2000), (25, "market", 1000), (100, "market", 300),
            (25, "model", 500), (10, "model", 1000)]  # fmt: skip
    results["experiments"] = []
    for k, (n, truth, reps) in enumerate(plan):
        results["experiments"].append(
            experiment(pool, n, truth, max(10, int(reps * q)), "full", SEED + 10 + k)
        )
        print(n, truth, round(time.time() - t0))
    results["experiments"].append(
        experiment(pool, 25, "market", max(10, int(1000 * q)), "realistic", SEED + 30)
    )
    print("realistic", round(time.time() - t0))
    (OUT / "results.json").write_text(json.dumps(results, indent=1) + "\n")
    print("done", round(time.time() - t0))


if __name__ == "__main__":
    main()
