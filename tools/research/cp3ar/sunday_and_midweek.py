"""CP3A-R.1 (research only): Sunday cutoff extension and midweek research coverage.

Narrow extension of fixture_windows.py, with the same stores, proxy and production
matching. All calendar boundaries are SAST (Africa/Johannesburg, UTC+2, no daylight
saving); kickoffs are stored in UTC.

1. Sunday arrivals 10:00, 12:00, 14:00 and 15:00 SAST (plus 16:00 and 18:00 to see
   where feasibility collapses), Friday-Sunday SAST universe, 15-minute buffer.
   Scenario "6L": the six leagues with established provider odds.
   Scenario "6L+PSL": adds PSL (288) fixtures, assuming each qualifies, an UPPER
   BOUND (captured odds show some PSL fixtures qualify, not that all do).
2. Midweek research coverage, Monday-Thursday SAST: domestic (eight leagues) and
   UEFA Champions League / Europa League main stage (schedule only; European
   market-implied coverage needs odds that are not stored historically).
   Approach A: Monday-Thursday only.  Approach B: rolling 7 days from Monday 08:00
   SAST.  Approach C: Monday-Thursday, falling back to the coming Friday-Sunday
   fixtures when fewer than 10 midweek fixtures exist.

Run:  uv run python tools/research/cp3ar/sunday_and_midweek.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import statistics
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

import research_phase8_cp1 as cp1  # noqa: E402
from fixture_windows import bands  # noqa: E402

from diski9.challenge.config import A3_432_V1 as CFG  # noqa: E402
from diski9.challenge.structured import _match  # noqa: E402

OUT = ROOT / "docs/research/phase8_cp3ar/sunday_and_midweek.json"
SAST = timedelta(hours=2)
ODDS6 = (39, 40, 140, 61, 78, 135)
PSL = (288,)
ALL8 = ODDS6 + (288, 289)
NEED = dict(zip(CFG.bucket_codes, CFG.sizes, strict=True))
BUFFER = timedelta(minutes=15)
FIRST, LAST = datetime(2023, 8, 1, tzinfo=UTC), datetime(2026, 11, 13, tzinfo=UTC)
SUNDAY_SAST = (10, 12, 14, 15, 16, 18)
MIDWEEK_MIN = 10


def load(tmp: Path):
    rows = []
    for src, comps in (
        (cp1.DEV_DB, (39, 40, 288, 289)),
        (cp1.RESEARCH_DB, (140, 61, 78, 135, 2, 3)),
    ):
        dst = tmp / ("m_" + src.name)
        shutil.copy(src, dst)
        c = sqlite3.connect(dst)
        q = (
            "SELECT id, competition_id, kickoff_utc, round_name, round_type FROM fixtures "
            f"WHERE competition_id IN ({','.join(map(str, comps))})"
        )
        for fid, comp, k, rn, rt in c.execute(q):
            kk = datetime.fromisoformat(k)
            kk = kk if kk.tzinfo else kk.replace(tzinfo=UTC)
            if comp in (2, 3):
                if cp1.uefa_stage(rn)[0] not in ("group", "league", "knockout"):
                    continue  # main stage only (agreed European eligibility)
            elif not (rt == "regular" or (rn or "").lower().startswith("regular")):
                continue
            rows.append((fid, comp, kk))
        c.close()
    return rows


def q(xs, p):
    return float(np.quantile(xs, p)) if xs else None


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sched = load(Path(tmp))
        store, stage = cp1.load_matches(Path(tmp))
        rows = cp1.build_rows(store, stage, set(cp1.DOMESTIC), set(cp1.SEASONS))
    mk, _, _, ok = cp1.predict(rows, cp1.Candidate("C1-2-20", None, 2, 20))
    proxy = {
        int(rows.fixture[i]): bands({k: float(np.asarray(v)[i]) for k, v in mk.items()})
        for i in np.flatnonzero(ok)
    }
    # Friday 00:00 SAST = Thursday 22:00 UTC, first one on or after FIRST
    fri = FIRST + timedelta(days=(3 - FIRST.weekday()) % 7)
    fri = fri.replace(hour=22, minute=0, second=0, microsecond=0)
    weeks = []
    while fri <= LAST:
        if (fri + SAST).month not in (6, 7):
            weeks.append(fri)
        fri += timedelta(days=7)

    out: dict = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "time_zone": "SAST (UTC+2); windows Fri 00:00 SAST to Mon 00:00 SAST",
        "weeks": len(weeks),
        "sunday": {},
        "midweek": {},
    }
    for scen, comps in (("6L", ODDS6), ("6L+PSL_upper_bound", ODDS6 + PSL)):
        recs = []
        for w in weeks:
            win = [(f, c, k) for f, c, k in sched if c in comps and w <= k < w + timedelta(days=3)]
            pub = w + timedelta(hours=6)  # Friday 08:00 SAST
            at_pub = [x for x in win if x[2] > pub + BUFFER]
            opens = len(at_pub) >= 15 and len({c for _, c, _ in at_pub}) >= 3
            rec = {"week_friday_sast": (w + SAST).date().isoformat(), "opens_counts": opens}
            for h in SUNDAY_SAST:
                t = w + timedelta(days=2, hours=h)
                rem = [x for x in win if x[2] > t + BUFFER]
                prox = {f: proxy[f] for f, _, _ in rem if f in proxy}
                rec[h] = {
                    "fixtures": len(rem),
                    "proxy_fixtures": len(prox),
                    "assessable": len(prox) >= 9,
                    "feasible": bool(len(prox) >= 9 and _match(NEED, prox)),
                }
            recs.append(rec)
        opened = [r for r in recs if r["opens_counts"]]
        res = {"schedule_qualified_weeks": len(opened)}
        for h in SUNDAY_SAST:
            fx = [r[h]["fixtures"] for r in opened]
            ass = sum(r[h]["assessable"] for r in opened)
            fea = sum(r[h]["feasible"] for r in opened)
            res[f"sun_{h:02d}00_sast"] = {
                "median_fixtures": statistics.median(fx),
                "p10_fixtures": q(fx, 0.1),
                "p25_fixtures": q(fx, 0.25),
                "weeks_lt9_fixtures": sum(f < 9 for f in fx),
                "weeks_proxy_assessable": ass,
                "weeks_proxy_feasible": fea,
                "conditional_feasibility": round(fea / ass, 3) if ass else None,
                "feasible_share_of_qualified_weeks": round(fea / len(opened), 3),
            }
        out["sunday"][scen] = res

    # ---------------------------------------------------------------- midweek
    mw = {"A_mon_thu": [], "B_rolling_7d_from_mon_0800": [], "C_mon_thu_with_weekend_fallback": []}
    dom_mw, uefa_mw, fallback_weeks = [], [], 0
    for w in weeks:
        mon = w + timedelta(days=3)  # Monday 00:00 SAST
        mt = [(f, c, k) for f, c, k in sched if mon <= k < mon + timedelta(days=4)]
        d = sum(1 for _, c, _ in mt if c in ALL8)
        u = sum(1 for _, c, _ in mt if c in (2, 3))
        dom_mw.append(d)
        uefa_mw.append(u)
        start = mon + timedelta(hours=8)
        roll = sum(
            1
            for _, c, k in sched
            if start <= k < start + timedelta(days=7) and (c in ALL8 or c in (2, 3))
        )
        mw["A_mon_thu"].append(d + u)
        mw["B_rolling_7d_from_mon_0800"].append(roll)
        if d + u < MIDWEEK_MIN:
            fallback_weeks += 1
            nxt = sum(
                1
                for _, c, k in sched
                if mon + timedelta(days=4) <= k < mon + timedelta(days=7) and c in ALL8
            )
            mw["C_mon_thu_with_weekend_fallback"].append(d + u + nxt)
        else:
            mw["C_mon_thu_with_weekend_fallback"].append(d + u)

    def summ(xs):
        return {
            "median": statistics.median(xs),
            "p10": q(xs, 0.1),
            "min": min(xs),
            "weeks_zero": sum(x == 0 for x in xs),
            f"weeks_lt_{MIDWEEK_MIN}": sum(x < MIDWEEK_MIN for x in xs),
        }

    out["midweek"] = {
        "domestic_only_mon_thu": summ(dom_mw),
        "uefa_main_stage_mon_thu": summ(uefa_mw),
        **{k: summ(v) for k, v in mw.items()},
        "approach_C_fallback_weeks": fallback_weeks,
        "note": "UEFA = schedule availability only; eligible market-implied coverage unknown",
    }
    OUT.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
