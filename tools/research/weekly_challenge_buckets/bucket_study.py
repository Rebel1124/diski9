"""Weekly Challenge probability-bucket research (read-only).

Reproduces the Scenario A/B/C/D/A2/A3 investigations that led to the approved A3 bucket
design (``a3-432-v1``; see ``docs/research/weekly_challenge_bucket_review.md``).

Read-only by construction:

* the local football store is opened with SQLite ``mode=ro``;
* the only other input is the committed real-market research pool
  ``docs/research/weekly_challenge_risk/pool_fortnight.json``;
* no network access, no provider calls, no database writes;
* the per-fixture backtest (derived provider data) is written only to a work directory
  outside the repository (default: the system temporary directory) and is never committed;
* the committed outputs are aggregates only (``summary.json``, ``weekly.csv``).

Production code is reused unchanged: ``screener.goal_model.fixture_estimate`` (point-in-time
Goal Model 1.0), ``challenge.structured._match`` (exact 4/3/2 distinct-fixture matching, as in
the D-28 opening check), ``challenge.structured.evaluate_groups`` (payouts, D-15 rounding,
eight states, recovery) and ``challenge.scoring.score_round`` (D-31, ``points-150-75-v2``).

Usage (from the repository root)::

    uv run python tools/research/weekly_challenge_buckets/bucket_study.py all
    uv run python tools/research/weekly_challenge_buckets/bucket_study.py all --quick

Scenario definitions here are research inputs only; the production configuration lives in
``src/diski9/challenge/config.py`` and is not read or changed by this tool.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import random
import statistics as st
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[3]
POOL = ROOT / "docs/research/weekly_challenge_risk/pool_fortnight.json"
STORE = ROOT / "data/diski9.sqlite"
OUT = ROOT / "docs/research/weekly_challenge_buckets"

EURO = (39, 40, 61, 78, 135, 140)  # leagues with real strict-consensus odds in the pool
ALL8 = (*EURO, 288, 289)
LEAGUE = {
    39: "EPL",
    40: "Championship",
    61: "Ligue 1",
    78: "Bundesliga",
    135: "Serie A",
    140: "La Liga",
    288: "PSL",
    289: "PSL 1st Div",
}
NEED = {"A": 4, "B": 3, "C": 2}  # C-10: Foundation 4, Balanced 3, Challenger 2
STAKES, NINE = (40, 30, 20), 10  # C-11
OUTS = (
    ("1X2", "HOME", "home"),
    ("1X2", "DRAW", "draw"),
    ("1X2", "AWAY", "away"),
    ("BTTS", "BTTS_YES", "btts_yes"),
    ("BTTS", "BTTS_NO", "btts_no"),
    ("OU25", "OVER_2_5", "over"),
    ("OU25", "UNDER_2_5", "under"),
)

# (lower, upper, upper_inclusive); lower bounds always inclusive. Bucket A = Foundation,
# B = Balanced, C = Challenger.
SCENARIOS = {
    "A": {"A": (0.60, 0.95, True), "B": (0.40, 0.60, False), "C": (0.20, 0.40, False)},
    "A2": {"A": (0.60, 0.90, True), "B": (0.40, 0.60, False), "C": (0.20, 0.40, False)},
    "A3": {"A": (0.60, 0.90, True), "B": (0.40, 0.60, False), "C": (0.10, 0.40, False)},
    "B": {"A": (0.70, 0.90, True), "B": (0.50, 0.70, False), "C": (0.30, 0.50, False)},
    "C": {"A": (0.75, 0.90, True), "B": (0.60, 0.75, False), "C": (0.45, 0.60, False)},
    "D": {"A": (0.60, 0.90, True), "B": (0.45, 0.60, False), "C": (0.30, 0.45, False)},
}
STRATEGIES = ("conservative", "random", "aggressive")


def bucket_of(p: float, sc: dict) -> str | None:
    for b, (lo, hi, inc) in sc.items():
        if p >= lo and (p <= hi if inc else p < hi):
            return b
    return None


def pct(xs, q: float) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def won(outcome: str, ft) -> bool:
    h, a = ft
    return {
        "HOME": h > a,
        "DRAW": h == a,
        "AWAY": h < a,
        "BTTS_YES": h > 0 and a > 0,
        "BTTS_NO": not (h > 0 and a > 0),
        "OVER_2_5": h + a >= 3,
        "UNDER_2_5": h + a < 3,
    }[outcome]


# ======================================================================= inputs
def backtest(work: Path) -> Path:
    """Point-in-time Goal Model 1.0 for every completed fixture kicking off Fri-Mon (the
    `weekend` round window). Cutoff: Thursday 06:00 UTC of that week (publication), so only
    results known before the round are used. Writes ``hist.json`` to the work directory."""
    from sqlalchemy import create_engine

    from diski9.screener.engine import MatchStore
    from diski9.screener.goal_model import fixture_estimate

    if not STORE.exists():
        raise SystemExit(f"Local football store not found: {STORE}")
    engine = create_engine(f"sqlite:///file:{STORE}?mode=ro&uri=true")
    with engine.connect() as conn:
        store = MatchStore(conn)
        rows = conn.exec_driver_sql(
            "select id, competition_id, season, kickoff_utc, home_team_id, away_team_id,"
            " is_final, ft_home, ft_away, stats_exclusion_reason from fixtures"
        ).fetchall()
    out = []
    for r in rows:
        ko = datetime.fromisoformat(r.kickoff_utc)
        ko = ko if ko.tzinfo else ko.replace(tzinfo=UTC)
        if ko.weekday() not in (4, 5, 6, 0) or not r.is_final or r.stats_exclusion_reason:
            continue
        fri = (ko - timedelta(days=(ko.weekday() - 4) % 7)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        est = fixture_estimate(
            store,
            r.competition_id,
            r.season,
            r.home_team_id,
            r.away_team_id,
            fri - timedelta(hours=18),
        )
        rec = {
            "fixture_id": r.id,
            "league": r.competition_id,
            "fri": fri.date().isoformat(),
            "ft": [r.ft_home, r.ft_away],
            "available": est["available"],
        }
        if est["available"]:
            rec["p"] = est["probabilities"]
        out.append(rec)
    work.mkdir(parents=True, exist_ok=True)
    path = work / "hist.json"
    path.write_text(json.dumps(out))
    return path


def load_pool() -> dict:
    return json.loads(POOL.read_text())


def real_weeks(pool: dict) -> dict[str, list]:
    """The two Fri-Mon windows in the real snapshot (17 Nov 2026 22:00 UTC). Only outcomes
    flagged strict-consensus eligible with reference odds are used."""
    wk = collections.defaultdict(list)
    for f in pool["fixtures"]:
        el = [o for o in f["outcomes"] if o.get("eligible") and o.get("odds")]
        ko = f["kickoff"][:10]
        if not el:
            continue
        if "2026-11-20" <= ko <= "2026-11-23":
            w = "2026-11-20"
        elif "2026-11-27" <= ko <= "2026-11-30":
            w = "2026-11-27"
        else:
            continue
        wk[w].append(
            {
                "fid": f["fixture_id"],
                "league": f["league_id"],
                "lam_mkt": f.get("lambda_market"),
                "outs": [
                    (
                        o["market"],
                        o["outcome"],
                        o["p_market"],
                        Decimal(o["odds"]),
                        o["p_model"],
                        o["groups"],
                    )
                    for o in el
                ],
            }
        )
    return dict(sorted(wk.items()))


def calibration(pool: dict) -> dict:
    """Logit-linear model->market mapping per outcome (fitted on the real pool) plus the
    real residuals, and the average odds x market probability per market."""
    pairs, ret = collections.defaultdict(list), collections.defaultdict(list)
    for f in pool["fixtures"]:
        for o in f["outcomes"]:
            if o.get("eligible") and o.get("odds"):
                ret[o["market"]].append(float(o["odds"]) * o["p_market"])
                if o["p_model"] is not None:
                    pairs[o["outcome"]].append((o["p_model"], o["p_market"]))
    lg = lambda p: math.log(p / (1 - p))  # noqa: E731
    cal = {}
    for k, v in pairs.items():
        x = np.array([lg(a) for a, _ in v])
        y = np.array([lg(b) for _, b in v])
        b, a = np.polyfit(x, y, 1)
        r = y - (a + b * x)
        cal[k] = {
            "a": float(a),
            "b": float(b),
            "sd": float(r.std(ddof=2)),
            "n": len(v),
            "residuals": [float(z) for z in r],
        }
    return {"outcomes": cal, "return": {k: st.mean(v) for k, v in ret.items()}}


def proxy_weeks(hist, cal, rng, leagues=EURO, start="2025-08-01", end="2026-12-01"):
    """Estimated market weeks: model probabilities mapped with the calibration plus a
    resampled real residual; proxy odds = market return / probability. Results are the
    fixtures' actual scores, used only for settlement after selection."""
    ilg = lambda x: 1 / (1 + math.exp(-x))  # noqa: E731

    def m(key, val):
        c = cal["outcomes"][key]
        v = min(max(val, 1e-6), 1 - 1e-6)
        return ilg(c["a"] + c["b"] * math.log(v / (1 - v)) + rng.choice(c["residuals"]))

    wk = collections.defaultdict(list)
    for f in hist:
        if not f["available"] or f["league"] not in leagues or not start <= f["fri"] < end:
            continue
        p = f["p"]
        h, dr, aw = m("HOME", p["home"]), m("DRAW", p["draw"]), m("AWAY", p["away"])
        s = h + dr + aw
        y, ov = m("BTTS_YES", p["btts_yes"]), m("OVER_2_5", p["over"])
        q = {
            "home": h / s,
            "draw": dr / s,
            "away": aw / s,
            "btts_yes": y,
            "btts_no": 1 - y,
            "over": ov,
            "under": 1 - ov,
        }
        outs = []
        for mk, oc, k in OUTS:
            odds = Decimal(str(round(cal["return"][mk] / q[k], 2))) if q[k] > 0 else Decimal(1000)
            outs.append((mk, oc, q[k], max(odds, Decimal("1.01")), p[k], None))
        wk[f["fri"]].append(
            {"fid": f["fixture_id"], "league": f["league"], "ft": f["ft"], "outs": outs}
        )
    return dict(sorted(wk.items()))


# ================================================================== eligibility
def options(week, sc) -> dict:
    """fixture -> bucket -> outcomes. Buckets always use the MARKET probability (C-09)."""
    opt: dict = {}
    for f in week:
        for o in f["outs"]:
            b = bucket_of(o[2], sc)
            if b:
                opt.setdefault(f["fid"], {}).setdefault(b, []).append(o)
    return opt


def opening(week, sc) -> dict:
    """D-28: >= 15 eligible fixtures, >= 3 leagues, exact 4/3/2 distinct-fixture matching."""
    from diski9.challenge.structured import _match

    opt = options(week, sc)
    leagues = {f["league"] for f in week if f["fid"] in opt}
    feasible = _match(NEED, {f: set(bs) for f, bs in opt.items()})
    return {
        "opt": opt,
        "eligible_fixtures": len(opt),
        "leagues": len(leagues),
        "feasible": feasible,
        "playable": feasible and len(opt) >= 15 and len(leagues) >= 3,
        "unique": {b: sum(b in bs for bs in opt.values()) for b in NEED},
        "outcomes": {b: sum(len(bs.get(b, [])) for bs in opt.values()) for b in NEED},
    }


# =================================================================== strategies
def optimise(opt, sign: int, noise=None):
    """Exact optimum over valid 4/3/2 portfolios on distinct fixtures (assignment problem,
    9 slots x fixtures). sign=+1 maximises sum(log p) (conservative: highest probability that
    all nine win); sign=-1 minimises it (aggressive). Per fixture and bucket the outcome that
    is best for the objective is used; ties break on (market, outcome). ``noise`` adds a
    participant-specific logit perturbation (leaderboard players only)."""
    fids = sorted(opt)
    slots = [b for b in "ABC" for _ in range(NEED[b])]
    big = 1e6
    cost = np.full((len(slots), len(fids)), big)
    pick = {}
    for j, f in enumerate(fids):
        for b, outs in opt[f].items():

            def val(o, f=f):
                p = o[2]
                if noise is not None:
                    p = 1 / (1 + math.exp(-(math.log(p / (1 - p)) + noise[(f, o[0], o[1])])))
                return math.log(p)

            best = sorted(outs, key=lambda o: (-sign * val(o), o[0], o[1]))[0]
            pick[(f, b)] = best
            for i, s in enumerate(slots):
                if s == b:
                    cost[i, j] = -sign * val(best)
    r, c = linear_sum_assignment(cost)
    if any(cost[i, j] >= big for i, j in zip(r, c, strict=True)):
        return None
    port = {"A": [], "B": [], "C": []}
    for i, j in zip(r, c, strict=True):
        port[slots[i]].append((fids[j], pick[(fids[j], slots[i])]))
    return port


def random_portfolio(opt, rng, tries: int = 20000):
    """Uniform over valid portfolios at outcome level (rejection sampling)."""
    pools = {b: [(f, o) for f, bs in opt.items() for o in bs.get(b, [])] for b in "ABC"}
    for _ in range(tries):
        port, used, ok = {}, set(), True
        for b in "ABC":
            if len(pools[b]) < NEED[b]:
                return None
            sel = rng.sample(pools[b], NEED[b])
            fs = {f for f, _ in sel}
            if len(fs) < NEED[b] or used & fs:
                ok = False
                break
            used |= fs
            port[b] = sel
        if ok:
            return port
    return None


def metrics(port) -> dict:
    """Exact figures at market probabilities with the production payout code."""
    from diski9.challenge.structured import evaluate_groups

    ev = evaluate_groups([[(o[2], o[3]) for _, o in port[b]] for b in "ABC"], STAKES, NINE)
    return {
        "pick_p": st.mean(o[2] for b in "ABC" for _, o in port[b]),
        "foundation": ev.buckets[0].win_probability,
        "balanced": ev.buckets[1].win_probability,
        "challenger": ev.buckets[2].win_probability,
        "all_nine": ev.nine_fold.win_probability,
        "recover": ev.p_recover,
        "expected_gross": ev.expected_gross,
        "max_gross": float(ev.max_gross),
    }


def settle(port, results) -> tuple[float, tuple[int, int, int]]:
    from diski9.challenge.structured import evaluate_groups

    ev = evaluate_groups([[(o[2], o[3]) for _, o in port[b]] for b in "ABC"], STAKES, NINE)
    wins = tuple(int(all(results[(f, o[0], o[1])] for f, o in port[b])) for b in "ABC")
    gross = next(float(s.gross) for s in ev.states if s.wins == wins)
    return gross, wins


def _mean(ms, keys=None):
    keys = keys or ms[0].keys()
    return {k: st.mean(m[k] for m in ms) for k in keys}


# ======================================================================= studies
def availability(real, proxy_draws, proxy8_draws, scenarios=SCENARIOS):
    """Weekly availability per scenario: real weeks and proxy weeks (D-28 rules)."""
    out = {"real": {}, "proxy_6_leagues": {}, "proxy_8_leagues": {}}
    weekly = collections.defaultdict(dict)
    for name, sc in scenarios.items():
        out["real"][name] = {
            w: {k: v for k, v in opening(week, sc).items() if k != "opt"}
            for w, week in real.items()
        }
        for label, draws in (("proxy_6_leagues", proxy_draws), ("proxy_8_leagues", proxy8_draws)):
            per = collections.defaultdict(list)
            unplayable, weeks = [], 0
            for weeks_map in draws:
                bad = 0
                for fri, week in weeks_map.items():
                    r = opening(week, sc)
                    for b in NEED:
                        per[b].append(r["unique"][b])
                    bad += not r["playable"]
                    if label == "proxy_6_leagues":
                        weekly[fri].setdefault(name, []).append(r)
                unplayable.append(bad)
                weeks = len(weeks_map)
            out[label][name] = {
                "weeks": weeks,
                "unplayable_mean": st.mean(unplayable),
                "unplayable_range": [min(unplayable), max(unplayable)],
                "unique_per_week": {
                    b: {
                        "median": st.median(v),
                        "p10": pct(v, 0.1),
                        "p25": pct(v, 0.25),
                        "min": min(v),
                        "max": max(v),
                    }
                    for b, v in per.items()
                },
            }
    rows = []
    for fri in sorted(weekly):
        row = {"week_friday": fri}
        for name, rs in weekly[fri].items():
            row[f"{name}_playable_share"] = round(st.mean(r["playable"] for r in rs), 3)
            for b, label in (("A", "foundation"), ("B", "balanced"), ("C", "challenger")):
                row[f"{name}_{label}_fixtures_median"] = st.median(r["unique"][b] for r in rs)
        row["eligible_fixtures_median_A"] = st.median(
            r["eligible_fixtures"] for r in weekly[fri]["A"]
        )
        rows.append(row)
    return out, rows


def low_band(pool, proxy_draws):
    """Outcomes below 40% by market band: count, type, league, margin, quote depth, model gap."""
    real_weeks_set = (
        "2026-11-20",
        "2026-11-21",
        "2026-11-22",
        "2026-11-23",
        "2026-11-27",
        "2026-11-28",
        "2026-11-29",
        "2026-11-30",
    )
    bands = {"<10": (0, 0.10), "10-20": (0.10, 0.20), "20-30": (0.20, 0.30), "30-40": (0.30, 0.40)}
    real = {}
    for k, (lo, hi) in bands.items():
        rows = [
            (f, o)
            for f in pool["fixtures"]
            if f["kickoff"][:10] in real_weeks_set
            for o in f["outcomes"]
            if o.get("eligible") and o.get("odds") and lo <= o["p_market"] < hi
        ]
        if not rows:
            continue
        real[k] = {
            "outcomes": len(rows),
            "fixtures": len({f["fixture_id"] for f, _ in rows}),
            "by_outcome": dict(collections.Counter(o["outcome"] for _, o in rows).most_common()),
            "by_league": dict(
                collections.Counter(LEAGUE[f["league_id"]] for f, _ in rows).most_common()
            ),
            "odds_x_market_prob_mean": st.mean(float(o["odds"]) * o["p_market"] for _, o in rows),
            "bookmaker_groups_median": st.median(o["groups"] for _, o in rows),
            "bookmaker_groups_min": min(o["groups"] for _, o in rows),
            "model_minus_market_pts": 100 * st.mean(o["p_model"] - o["p_market"] for _, o in rows),
            "model_over_market_ratio": st.mean(o["p_model"] / o["p_market"] for _, o in rows),
        }
    per_week, kinds = [], collections.Counter()
    for weeks in proxy_draws:
        for week in weeks.values():
            new = [(f, o) for f in week for o in f["outs"] if 0.10 <= o[2] < 0.20]
            per_week.append(len(new))
            for f, o in new:
                kinds[o[1]] += 1
                kinds["league:" + LEAGUE[f["league"]]] += 1
    n = len(proxy_draws)
    return {
        "real": real,
        "proxy_10_20": {
            "outcomes_per_week_median": st.median(per_week),
            "p10": pct(per_week, 0.1),
            "p90": pct(per_week, 0.9),
            "per_draw": {k: round(v / n, 1) for k, v in kinds.most_common()},
        },
    }


def ceiling_90_95(proxy_draws):
    cnt, by = 0, collections.Counter()
    for weeks in proxy_draws:
        for week in weeks.values():
            for f in week:
                for o in f["outs"]:
                    if 0.90 <= o[2] <= 0.95:
                        cnt += 1
                        by[f"{o[0]}:{o[1]}"] += 1
                        by["league:" + LEAGUE[f["league"]]] += 1
    n = len(proxy_draws)
    return {
        "proxy_outcomes_per_49_weeks": cnt / n,
        "breakdown_per_draw": {k: v / n for k, v in by.items()},
    }


def calibration_check(hist, cal, rng, draws=5):
    """Observed win rate vs probability by band, against ACTUAL results (indicative)."""
    out = {}
    for label in ("proxy_market", "raw_model"):
        acc = collections.defaultdict(lambda: [0, 0, 0.0])
        for d in range(draws if label == "proxy_market" else 1):
            weeks = proxy_weeks(hist, cal, random.Random(1000 + d))
            for week in weeks.values():
                for f in week:
                    for o in f["outs"]:
                        p = o[2] if label == "proxy_market" else o[4]
                        for k, (lo, hi) in {
                            "10-20": (0.1, 0.2),
                            "20-30": (0.2, 0.3),
                            "30-40": (0.3, 0.4),
                            "60-90": (0.6, 0.9001),
                        }.items():
                            if lo <= p < hi:
                                a = acc[k]
                                a[0] += 1
                                a[1] += won(o[1], f["ft"])
                                a[2] += p
        out[label] = {
            k: {"n": v[0], "predicted": v[2] / v[0], "observed": v[1] / v[0]}
            for k, v in sorted(acc.items())
        }
    return out


def strategies(real, proxy_draws, names=("A", "A2", "A3", "D"), n_random=2000, proxy_random=60):
    """Completion probabilities per strategy: exact on real weeks; median over proxy weeks;
    and settled against actual results for the proxy weeks."""
    out = {"real": {}, "proxy": {}, "actual_results": {}, "ordering": {}}
    for name in names:
        sc = SCENARIOS[name]
        out["real"][name] = {}
        for w, week in real.items():
            r = opening(week, sc)
            if not r["feasible"]:
                out["real"][name][w] = None
                continue
            rng = random.Random(20261120)
            rand = [metrics(random_portfolio(r["opt"], rng)) for _ in range(n_random)]
            se = st.stdev(m["challenger"] for m in rand) / math.sqrt(len(rand))
            out["real"][name][w] = {
                "conservative": metrics(optimise(r["opt"], +1)),
                "random": {
                    **_mean(rand),
                    "se_challenger": se,
                    "share_challenger_above_balanced": st.mean(
                        m["challenger"] > m["balanced"] for m in rand
                    ),
                },
                "aggressive": metrics(optimise(r["opt"], -1)),
            }
        agg = {s: collections.defaultdict(list) for s in STRATEGIES}
        act = {s: collections.Counter() for s in STRATEGIES}
        order = collections.Counter()
        for di, weeks in enumerate(proxy_draws):
            for wi, (_fri, week) in enumerate(weeks.items()):
                r = opening(week, sc)
                if not r["playable"]:
                    continue
                results = {
                    (f["fid"], o[0], o[1]): won(o[1], f["ft"]) for f in week for o in f["outs"]
                }
                rng = random.Random(di * 100_000 + wi)
                ports = {
                    "conservative": [optimise(r["opt"], +1)],
                    "aggressive": [optimise(r["opt"], -1)],
                    "random": [random_portfolio(r["opt"], rng) for _ in range(proxy_random)],
                }
                for s, ps in ports.items():
                    m = _mean([metrics(p) for p in ps])
                    for k, v in m.items():
                        agg[s][k].append(v)
                    order[s + "_n"] += 1
                    order[s + "_f_gt_b_gt_c"] += m["foundation"] > m["balanced"] > m["challenger"]
                    order[s + "_c_gt_b"] += m["challenger"] > m["balanced"]
                    for p in ps:
                        g, wins = settle(p, results)
                        a = act[s]
                        a["n"] += 1
                        a["foundation"] += wins[0]
                        a["balanced"] += wins[1]
                        a["challenger"] += wins[2]
                        a["all_nine"] += all(wins)
                        a["recovered"] += g >= 100
                        a["gross"] += g
        out["proxy"][name] = {s: {k: st.median(v) for k, v in agg[s].items()} for s in STRATEGIES}
        out["actual_results"][name] = {
            s: {k: (v / act[s]["n"]) for k, v in act[s].items() if k != "n"} | {"n": act[s]["n"]}
            for s in STRATEGIES
        }
        out["ordering"][name] = dict(order)
    return out


def bootstrap_reversal(real, names=("A2", "D"), reps=200, per=300):
    """Bootstrap over fixtures (real 20-23 Nov): random-strategy Challenger minus Balanced."""
    week = real["2026-11-20"]
    out = {}
    for name in names:
        brng, diffs = random.Random(11), []
        for bi in range(reps):
            bw = [dict(f, fid=(f["fid"], i)) for i, f in enumerate(brng.choices(week, k=len(week)))]
            r = opening(bw, SCENARIOS[name])
            if not r["feasible"]:
                continue
            rng = random.Random(bi)
            ms = [metrics(random_portfolio(r["opt"], rng)) for _ in range(per)]
            diffs.append(st.mean(m["challenger"] for m in ms) - st.mean(m["balanced"] for m in ms))
        out[name] = {
            "mean_pts": 100 * st.mean(diffs),
            "ci95_pts": [100 * pct(diffs, 0.025), 100 * pct(diffs, 0.975)],
            "share_positive": st.mean(d > 0 for d in diffs),
            "n": len(diffs),
        }
    return out


# ================================================================== leaderboard
MIX = ["conservative"] * 30 + ["random"] * 40 + ["aggressive"] * 30


def _players(week, opt, seed):
    keys = sorted((f["fid"], o[0], o[1]) for f in week for o in f["outs"])
    out = []
    for i, s in enumerate(MIX):
        rng = random.Random(seed * 1000 + i)
        noise = {k: rng.gauss(0, 0.3) for k in keys}  # identical across scenarios (paired)
        if s == "random":
            out.append(random_portfolio(opt, rng))
        else:
            out.append(optimise(opt, +1 if s == "conservative" else -1, noise))
    return out


def _score(grosses):
    from diski9.challenge.scoring import (
        EntryResult,
        RoundClassification,
        RoundResult,
        score_round,
    )

    rr = RoundResult(
        "r",
        "ch",
        RoundClassification.COMPETITIVE,
        tuple(
            EntryResult(f"p{i}", Decimal(str(g)).quantize(Decimal("0.01")))
            for i, g in enumerate(grosses)
        ),
        "points-150-75-v2",
    )
    by = {s.participant_id: s for s in score_round(rr).scores}
    return [by[f"p{i}"] for i in range(len(grosses))]


def _simulate(rounds, sc):
    recs = []
    for week, results, seed in rounds:
        opt = options(week, sc)
        grosses, wins = [], []
        for p in _players(week, opt, seed):
            g, w = settle(p, results)
            grosses.append(g)
            wins.append(w)
        sc_ = _score(grosses)
        recs.append(
            [
                (
                    MIX[i],
                    grosses[i],
                    wins[i],
                    sc_[i].points,
                    sc_[i].recovered,
                    sc_[i].rank,
                    sc_[i].qualifying_top10,
                )
                for i in range(len(MIX))
            ]
        )
    return recs


def _summary(recs):
    res = {}
    winners = sum(1 for rr in recs for r in rr if r[5] == 1 and r[4])
    for s in STRATEGIES:
        rows = [r for rr in recs for r in rr if r[0] == s]
        g = [r[1] for r in rows]
        res[s] = {
            "points_per_round": st.mean(r[3] for r in rows),
            "recovered": st.mean(r[4] for r in rows),
            "mean_gross": st.mean(g),
            "sd_gross": st.pstdev(g),
            "p_gross_ge_1000": st.mean(x >= 1000 for x in g),
            "p_gross_ge_5000": st.mean(x >= 5000 for x in g),
            "max_gross": max(g),
            "top10": st.mean(r[6] for r in rows),
            "challenger_won": st.mean(r[2][2] for r in rows),
            "all_nine": st.mean(all(r[2]) for r in rows),
            "weekly_win_share": sum(
                1 for rr in recs for r in rr if r[0] == s and r[5] == 1 and r[4]
            )
            / max(1, winners),
        }
    champs, ginis, top10 = collections.Counter(), [], []
    totals = []
    for c in range(len(recs) // 10):
        tot = [0] * len(MIX)
        for rr in recs[c * 10 : (c + 1) * 10]:
            for i, r in enumerate(rr):
                tot[i] += r[3]
        best = max(tot)
        for i, v in enumerate(tot):
            if v == best:
                champs[MIX[i]] += 1 / sum(x == best for x in tot)
        f = sorted(tot)
        n, total = len(f), sum(f)
        ginis.append(sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(f)) / (n * total))
        top10.append(sum(f[-10:]) / total)
        totals.append(tot)
    for s in STRATEGIES:
        res[s]["championship_points"] = st.mean(
            t[i] for t in totals for i in range(len(MIX)) if MIX[i] == s
        )
        res[s]["champion_share"] = champs[s] / len(totals)
    res["_overall"] = {
        "championships": len(totals),
        "gini": st.mean(ginis),
        "top10_players_share": st.mean(top10),
    }
    return res


def _poisson(week, seed):
    rng = np.random.default_rng(seed)
    res = {}
    for f in week:
        h, a = (int(x) for x in rng.poisson(f["lam_mkt"][:2]))
        for o in f["outs"]:
            res[(f["fid"], o[0], o[1])] = won(o[1], (h, a))
    return res


def leaderboard(
    real,
    proxy_draws,
    names=("A", "A2", "A3", "D"),
    real_reps=5,
    real_rounds=200,
    proxy_reps=8,
    proxy_rounds=40,
):
    """Paired leaderboard simulation: identical outcomes and participant noise in every
    scenario; 100 players (30 conservative, 40 random, 30 aggressive); D-31 scoring."""
    week = real["2026-11-20"]
    real_sets = [
        [(week, _poisson(week, 10_000 * r + k), 10_000 * r + k) for k in range(real_rounds)]
        for r in range(real_reps)
    ]
    proxy_sets = []
    base = SCENARIOS["A"]
    for d, weeks in enumerate(proxy_draws[:proxy_reps]):
        rr = []
        for j, (_fri, wk) in enumerate(weeks.items()):
            if not opening(wk, base)["playable"]:
                continue
            res = {(f["fid"], o[0], o[1]): won(o[1], f["ft"]) for f in wk for o in f["outs"]}
            rr.append((wk, res, 777_000 + d * 100 + j))
        proxy_sets.append(rr[:proxy_rounds])
    out = {}
    for label, sets in (
        ("real_simulated_market_scorelines", real_sets),
        ("proxy_actual_results", proxy_sets),
    ):
        out[label] = {}
        reps = {n: [_summary(_simulate(s, SCENARIOS[n])) for s in sets] for n in names}
        for n in names:
            agg = {}
            for s in STRATEGIES:
                agg[s] = {}
                for k in reps[n][0][s]:
                    vals = [r[s][k] for r in reps[n]]
                    agg[s][k] = {
                        "mean": max(vals) if k == "max_gross" else st.mean(vals),
                        "se": st.stdev(vals) / math.sqrt(len(vals)),
                    }
                if n != "A":
                    d = [
                        a[s]["points_per_round"] - b[s]["points_per_round"]
                        for a, b in zip(reps[n], reps["A"], strict=True)
                    ]
                    agg[s]["paired_points_vs_A"] = {
                        "mean": st.mean(d),
                        "se": st.stdev(d) / math.sqrt(len(d)),
                    }
            agg["_overall"] = {
                k: st.mean(r["_overall"][k] for r in reps[n]) for k in reps[n][0]["_overall"]
            }
            agg["_overall"]["championships"] = sum(r["_overall"]["championships"] for r in reps[n])
            out[label][n] = agg
        out[label]["_design"] = {"replicates": len(sets), "rounds_per_replicate": len(sets[0])}
    return out


# ========================================================================== CLI
def _clean(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    return x


def run_all(work: Path, out: Path, quick: bool) -> None:
    t0 = time.time()
    hist_path = work / "hist.json"
    if not hist_path.exists():
        print(f"backtest -> {hist_path}")
        backtest(work)
    hist = json.loads(hist_path.read_text())
    pool = load_pool()
    cal = calibration(pool)
    real = real_weeks(pool)
    n_draws = 4 if quick else 20
    print(f"proxy draws: {n_draws}")
    proxy = [proxy_weeks(hist, cal, random.Random(1000 + i)) for i in range(n_draws)]
    proxy8 = [proxy_weeks(hist, cal, random.Random(5000 + i), ALL8) for i in range(n_draws // 2)]
    summary = {
        "generated_by": "tools/research/weekly_challenge_buckets/bucket_study.py",
        "quick": quick,
        "inputs": {
            "real_pool": str(POOL.relative_to(ROOT)),
            "real_pool_as_of": pool["as_of"],
            "historical_fixtures_backtested": len(hist),
            "historical_fixtures_with_model": sum(h["available"] for h in hist),
            "proxy_draws": n_draws,
        },
        "scenarios": {k: {b: list(v) for b, v in sc.items()} for k, sc in SCENARIOS.items()},
        "calibration": {
            k: {kk: v[kk] for kk in ("a", "b", "sd", "n")} for k, v in cal["outcomes"].items()
        }
        | {"return": cal["return"]},
    }
    print("availability ...")
    summary["availability"], weekly = availability(real, proxy, proxy8)
    print("low-probability band ...")
    summary["low_probability_band"] = low_band(pool, proxy)
    summary["foundation_ceiling_90_95"] = ceiling_90_95(proxy)
    summary["calibration_check_actual_results"] = calibration_check(hist, cal, random.Random(3))
    print("strategies ...")
    summary["strategies"] = strategies(
        real, proxy[: 4 if quick else 10], n_random=500 if quick else 2000
    )
    summary["bootstrap_challenger_minus_balanced"] = bootstrap_reversal(
        real, reps=40 if quick else 200, per=100 if quick else 300
    )
    print("leaderboard ...")
    summary["leaderboard"] = leaderboard(
        real,
        proxy,
        real_reps=2 if quick else 5,
        real_rounds=50 if quick else 200,
        proxy_reps=2 if quick else 8,
    )
    summary["runtime_seconds"] = round(time.time() - t0)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(_clean(summary), indent=1, sort_keys=True) + "\n")
    with (out / "weekly.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(weekly[0]))
        w.writeheader()
        w.writerows(weekly)
    print(
        f"wrote {out / 'summary.json'} and {out / 'weekly.csv'} in {summary['runtime_seconds']} s"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("backtest", "all"))
    ap.add_argument(
        "--work",
        type=Path,
        default=Path(tempfile.gettempdir()) / "diski9-bucket-study",
        help="directory for the per-fixture backtest (outside the repository)",
    )
    ap.add_argument("--out", type=Path, default=OUT, help="directory for the aggregate outputs")
    ap.add_argument("--quick", action="store_true", help="fewer draws and replicates (smoke run)")
    a = ap.parse_args(argv)
    work = a.work.resolve()
    if work == ROOT or ROOT in work.parents:
        raise SystemExit("--work must be outside the repository (derived provider data)")
    if a.command == "backtest":
        print(backtest(work))
    else:
        run_all(work, a.out.resolve(), a.quick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
