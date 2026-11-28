"""CP3A-R items 4, 10 and 11 (research only): Friday-Sunday vs Friday-Monday challenge
windows and rolling-entry feasibility on historical schedules.

Evidence types are kept separate:
  * schedule  - historical fixture availability (complete, 2023/24 to Nov 2026);
  * proxy     - point-in-time Goal Model 1.1 probabilities as a stand-in for market
                bucket classification (no historical point-in-time odds exist locally);
  * resample  - bucket profiles of the one real strict-consensus snapshot
                (17 Nov 2026, docs/research/weekly_challenge_risk/pool_weekend.json)
                drawn at random for each remaining fixture (the CP1 method);
  * real      - that real snapshot itself, by arrival time (assumes its prices held).
Feasibility always uses the production matching (challenge.structured._match) and the
A3 configuration. Odds leagues only (PSL and PSL 1st Division have no provider odds, so
they are never challenge-eligible today). No provider calls; stores copied read-only.

Run:  uv run python tools/research/cp3ar/fixture_windows.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import research_phase8_cp1 as cp1  # noqa: E402

from diski9.challenge.config import A3_432_V1 as CFG  # noqa: E402
from diski9.challenge.structured import _match  # noqa: E402

OUT = ROOT / "docs/research/phase8_cp3ar/fixture_windows.json"
ODDS = (39, 40, 140, 61, 78, 135)
NO_ODDS = (288, 289)
NEED = dict(zip(CFG.bucket_codes, CFG.sizes, strict=True))
LAST_FRIDAY = datetime(2026, 11, 13, tzinfo=UTC)  # results stored to mid-November 2026
BUFFER = timedelta(minutes=15)
# arrival times in UTC (SAST = UTC+2): Fri 08:00, Sat 10:00, Sat 15:00, Sun 10:00, Sun 15:00 SAST
ARRIVALS = {
    "fri_0800": (0, 6),
    "sat_1000": (1, 8),
    "sat_1500": (1, 13),
    "sun_1000": (2, 8),
    "sun_1500": (2, 13),
}
# (start, end) in days from Friday 00:00 UTC. A is the current rule. S is an alternative
# with the current frozen architecture: a Saturday-Sunday universe, so the common deadline
# (earliest kickoff - 15 min) moves from Friday evening to Saturday.
WINDOWS = {"A_fri_mon": (0, 4), "B_fri_sun": (0, 3), "S_sat_sun": (1, 3)}


def schedule(tmp: Path):
    rows = []
    for src, comps in ((cp1.DEV_DB, (39, 40, 288, 289)), (cp1.RESEARCH_DB, (140, 61, 78, 135))):
        dst = tmp / ("w_" + src.name)
        shutil.copy(src, dst)
        c = sqlite3.connect(dst)
        q = (
            "SELECT id, competition_id, season, kickoff_utc, round_name, round_type FROM fixtures "
            f"WHERE competition_id IN ({','.join(map(str, comps))})"
        )
        for fid, comp, season, k, rn, rt in c.execute(q):
            if not (rt == "regular" or (rn or "").lower().startswith("regular")):
                continue
            kk = datetime.fromisoformat(k)
            rows.append((fid, comp, season, kk if kk.tzinfo else kk.replace(tzinfo=UTC)))
        c.close()
    return rows


def bands(p: dict) -> set:
    vals = [
        p["home"],
        p["draw"],
        p["away"],
        p["btts_yes"],
        1 - p["btts_yes"],
        p["over"],
        1 - p["over"],
    ]
    return {CFG.classify(float(v)) for v in vals} - {None}


def real_profiles(path: str):
    snap = json.loads((ROOT / "docs/research/weekly_challenge_risk" / path).read_text())
    out = []
    for f in snap["fixtures"]:
        if f["league_id"] not in ODDS:
            continue
        b = {CFG.classify(o["p_market"]) for o in f["outcomes"] if o["eligible"]} - {None}
        if any(o["eligible"] for o in f["outcomes"]):
            out.append((f, b))
    return snap, out


def proxy_agreement(snap) -> dict:
    """How well model-probability buckets stand in for market buckets (real snapshot)."""
    agree = n = 0
    conf = Counter()
    for f in snap["fixtures"]:
        for o in f["outcomes"]:
            if o["eligible"] and o["p_model"] is not None:
                bm, bk = CFG.classify(o["p_market"]), CFG.classify(o["p_model"])
                conf[(bk or "-", bm or "-")] += 1
                agree += bm == bk
                n += 1
    per_bucket_market = Counter(k[1] for k in conf.elements())
    per_bucket_model = Counter(k[0] for k in conf.elements())
    return {
        "outcomes": n,
        "same_bucket_share": round(agree / n, 3),
        "market_bucket_counts": dict(per_bucket_market),
        "model_bucket_counts": dict(per_bucket_model),
        "confusion_model_to_market": {f"{a}->{b}": v for (a, b), v in sorted(conf.items())},
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sched = schedule(Path(tmp))
        store, stage = cp1.load_matches(Path(tmp))
        rows = cp1.build_rows(store, stage, set(cp1.DOMESTIC), set(cp1.SEASONS))
    mk, _, _, ok = cp1.predict(rows, cp1.Candidate("C1-2-20", None, 2, 20))
    proxy = {}
    for i in np.flatnonzero(ok):
        proxy[int(rows.fixture[i])] = bands({k: float(np.asarray(v)[i]) for k, v in mk.items()})

    snap_w, prof_w = real_profiles("pool_weekend.json")
    snap_f, _ = real_profiles("pool_fortnight.json")
    profiles = [b for _, b in prof_w]
    rng = np.random.default_rng(20261128)

    def resample_share(n: int, reps: int = 300) -> float:
        if n < 9:
            return 0.0
        hits = 0
        for _ in range(reps):
            pick = rng.integers(0, len(profiles), n)
            hits += _match(NEED, {j: profiles[p] for j, p in enumerate(pick)})
        return round(hits / reps, 3)

    by_week = defaultdict(list)
    first = datetime(2023, 8, 1, tzinfo=UTC)  # first season with all eight leagues stored
    fri0 = (first - timedelta(days=(first.weekday() - 4) % 7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    weeks = []
    w = fri0
    while w <= LAST_FRIDAY:
        if w.month not in (6, 7):  # off-season months excluded
            weeks.append(w)
        w += timedelta(days=7)
    for fid, comp, _season, k in sched:
        if k < first:
            continue
        d = (k - fri0).days // 7
        by_week[fri0 + timedelta(days=7 * d)].append((fid, comp, k))

    records = []
    for fri in weeks:
        allfx = by_week.get(fri, [])
        rec = {
            "friday": fri.date().isoformat(),
            "all8_by_day": Counter(((k - fri).days) for _, c, k in allfx if c in ODDS + NO_ODDS),
            "big5_in_window": sum(
                1 for _, c, k in allfx if c in (39, 140, 61, 78, 135) and (k - fri).days < 4
            ),
        }
        rec["all8_by_day"] = {str(d): n for d, n in sorted(rec["all8_by_day"].items())}
        for wname, (sd, ed) in WINDOWS.items():
            start, end = fri + timedelta(days=sd), fri + timedelta(days=ed)
            win = [(f, c, k) for f, c, k in allfx if c in ODDS and start <= k < end]
            if win:
                rec[f"{wname}|earliest_kickoff"] = min(k for *_, k in win).isoformat()
            for aname, (dd, hh) in ARRIVALS.items():
                t = fri + timedelta(days=dd, hours=hh)
                rem = [(f, c, k) for f, c, k in win if k > t + BUFFER]
                leagues = {c for _, c, _ in rem}
                prox = {f: proxy[f] for f, _, _ in rem if f in proxy}
                r = {
                    "fixtures": len(rem),
                    "leagues": len(leagues),
                    "proxy_fixtures": len(prox),
                    "proxy_feasible": bool(len(prox) >= 9 and _match(NEED, prox)),
                    "resample_share": resample_share(len(rem)),
                }
                if aname == "fri_0800":
                    r["opens_d28_counts"] = len(rem) >= 15 and len(leagues) >= 3
                rec[f"{wname}|{aname}"] = r
        records.append(rec)

    # ---------------------------------------------------------------- aggregates
    def agg(wname, aname, subset):
        rs = [x[f"{wname}|{aname}"] for x in subset]
        fx = [r["fixtures"] for r in rs]
        out = {
            "weeks": len(rs),
            "median_fixtures": statistics.median(fx),
            "p10_fixtures": float(np.quantile(fx, 0.1)),
            "min_fixtures": min(fx),
            "weeks_ge9_fixtures": sum(f >= 9 for f in fx),
            "weeks_ge15_and_3_leagues": sum(r["fixtures"] >= 15 and r["leagues"] >= 3 for r in rs),
            "proxy_feasible_weeks": sum(r["proxy_feasible"] for r in rs),
            "proxy_assessable_weeks": sum(r["proxy_fixtures"] >= 9 for r in rs),
            "mean_resample_share": round(float(np.mean([r["resample_share"] for r in rs])), 3),
            "weeks_resample_ge_0_95": sum(r["resample_share"] >= 0.95 for r in rs),
        }
        return out

    summary: dict = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "weeks_total": len(records),
        "arrivals_utc": ARRIVALS,
        "windows_days": WINDOWS,
        "proxy_coverage_fixtures": len(proxy),
        "proxy_agreement_weekend": proxy_agreement(snap_w),
        "proxy_agreement_fortnight": proxy_agreement(snap_f),
        "real_profiles": len(profiles),
        "all": {},
        "opened_A": {},
        "opened_B": {},
        "break_weeks": {},
        "real_snapshot_by_arrival": {},
    }
    opened_a = [x for x in records if x["A_fri_mon|fri_0800"]["opens_d28_counts"]]
    opened_b = [x for x in records if x["B_fri_sun|fri_0800"]["opens_d28_counts"]]
    summary["opens"] = {
        w: sum(x[f"{w}|fri_0800"]["opens_d28_counts"] for x in records) for w in WINDOWS
    }
    summary["opens_and_proxy_feasible"] = {
        w: sum(
            x[f"{w}|fri_0800"]["opens_d28_counts"] and x[f"{w}|fri_0800"]["proxy_feasible"]
            for x in records
        )
        for w in WINDOWS
    }
    dl = Counter()
    for x in records:
        if x["S_sat_sun|fri_0800"]["opens_d28_counts"]:
            k = datetime.fromisoformat(x["S_sat_sun|earliest_kickoff"]) - BUFFER
            dl[(k + timedelta(hours=2)).strftime("%a %H:%M SAST")] += 1
    summary["S_deadline_distribution"] = dict(dl.most_common())
    breaks = [
        x for x in records if x["big5_in_window"] == 0
    ]  # international breaks (and season gaps)
    for wname in WINDOWS:
        for aname in ARRIVALS:
            key = f"{wname}|{aname}"
            summary["all"][key] = agg(wname, aname, records)
            summary["opened_A"][key] = agg(wname, aname, opened_a)
            summary["opened_B"][key] = agg(wname, aname, opened_b) if opened_b else None
            summary["break_weeks"][key] = agg(wname, aname, breaks) if breaks else None
    # day-of-week distribution of odds-league window fixtures (Fri=0 .. Mon=3)
    dist = Counter()
    for x in records:
        for d, n in x["all8_by_day"].items():
            dist[d] += n
    summary["all8_fixtures_by_day_from_friday"] = dict(
        sorted(dist.items(), key=lambda t: int(t[0]))
    )
    odds_dist = Counter()
    for _f, c, _s, k in sched:
        if c in ODDS:
            odds_dist[k.strftime("%a")] += 1
    summary["odds_leagues_fixtures_by_weekday_utc"] = dict(odds_dist)
    nodds = Counter(k.strftime("%a") for f, c, _s, k in sched if c in NO_ODDS)
    summary["psl_leagues_fixtures_by_weekday_utc"] = dict(nodds)

    # the real snapshot (window 20-24 Nov 2026), by arrival, prices assumed to hold
    fri = datetime(2026, 11, 20, tzinfo=UTC)
    for wname, (sd, ed) in WINDOWS.items():
        for aname, (dd, hh) in ARRIVALS.items():
            t = fri + timedelta(days=dd, hours=hh)
            rem = {
                f["fixture_id"]: b
                for f, b in prof_w
                if datetime.fromisoformat(f["kickoff"]) > t + BUFFER
                and fri + timedelta(days=sd)
                <= datetime.fromisoformat(f["kickoff"])
                < fri + timedelta(days=ed)
            }
            cnt = Counter(c for b in rem.values() for c in b)
            summary["real_snapshot_by_arrival"][f"{wname}|{aname}"] = {
                "fixtures": len(rem),
                "fixtures_with_bucket": dict(cnt),
                "feasible": bool(len(rem) >= 9 and _match(NEED, rem)),
            }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "weeks": records}, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str)[:12000])


if __name__ == "__main__":
    main()
