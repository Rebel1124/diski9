"""CP3A-R item 7 (research only): Goal Model 1.1 calibration sensitivity, four configs.

Protocol (pre-registered, committed before the run):
  docs/research/phase8_cp3ar/goal_model_sensitivity_protocol.md
Reuses the accepted Phase 8 CP1 harness (scripts/research_phase8_cp1.py): same stores
(copied to a temporary directory), eligibility, availability (C1-2-20), lag and
bootstrap. Only k_s / k_t differ. No provider calls; no production code or data changed.

Run:  uv run python tools/research/cp3ar/goal_model_sensitivity.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import research_phase8_cp1 as cp1  # noqa: E402
from research_goal_distribution import metrics, per_row_losses  # noqa: E402

from diski9.research.evaluation import iso_week, paired_bootstrap  # noqa: E402
from diski9.screener import goal_model as gm  # noqa: E402

OUT = ROOT / "docs/research/phase8_cp3ar/goal_model_sensitivity.json"
CONFIGS = {  # name: (k_s strength, k_t tempo)
    "A": (12.0, 96.0),
    "B": (12.0, 90.0),
    "C": (18.0, 96.0),
    "D": (18.0, 90.0),
    "L_label_check": (90.0, 18.0),  # literal labels; not a candidate (protocol §1)
}
LOSSES = ("1x2_log_loss", "btts_log_loss", "ou_log_loss", "1x2_brier", "btts_brier", "ou_brier")
PERIODS = {"selection": (2023, 2024), "confirmation": (2025, 2026), "all": (2023, 2024, 2025, 2026)}


def cand(name: str) -> cp1.Candidate:
    ks, kt = CONFIGS[name]
    return cp1.Candidate(name, None, 2, 20, ks, kt)


def deltas(a, b, r, which=LOSSES):
    cl = [iso_week(k) for k in r.kickoff]
    la, lb = per_row_losses(a, r), per_row_losses(b, r)
    return {m: paired_bootstrap(la[m] - lb[m], cl) for m in which}


def shift_stats(x):
    x = np.abs(np.asarray(x)) * 100  # percentage points
    return {
        "median_pp": round(float(np.median(x)), 3),
        "p90_pp": round(float(np.quantile(x, 0.9)), 3),
        "max_pp": round(float(x.max()), 3),
        "share_gt_1pp": round(float((x > 1).mean()), 4),
        "share_gt_3pp": round(float((x > 3).mean()), 4),
    }


def team_ids(store, fixtures):
    by = {m.fixture_id: (m.home_id, m.away_id) for m in store.matches}
    return np.array([by[int(f)] for f in fixtures])


def team_volatility(r, ids, lh, la):
    last: dict = {}
    diffs = []
    for i in np.argsort([k.timestamp() for k in r.kickoff]):
        for team, lam in ((ids[i][0], lh[i]), (ids[i][1], la[i])):
            key = (team, int(r.comp[i]), int(r.season[i]))
            if key in last:
                diffs.append(abs(lam - last[key]))
            last[key] = lam
    return round(float(np.mean(diffs)), 4)


def worked_example(r, i, ids, names):
    t = r.team[i]
    rec = lambda v: gm.TeamRecord(*[int(x) for x in v])  # noqa: E731
    home, away = rec(t[:6]), rec(t[6:])
    H, A = r.cur_hg[i] / r.cur_n[i], r.cur_ag[i] / r.cur_n[i]
    out = {
        "fixture": int(r.fixture[i]),
        "competition": cp1.NAMES[int(r.comp[i])],
        "kickoff": r.kickoff[i].isoformat(),
        "home": names.get(ids[i][0]),
        "away": names.get(ids[i][1]),
        "competition_H": round(H, 4),
        "competition_A": round(A, 4),
        "home_record": gm.asdict(home),
        "away_record": gm.asdict(away),
        "configs": {},
    }
    for name in ("A", "B", "C", "D"):
        ks, kt = CONFIGS[name]
        e = gm.estimate(home, away, (H, A), gm.GoalModelParams(k_s=ks, k_t=kt))
        p = e["probabilities"]
        out["configs"][name] = {
            "k_s": ks,
            "k_t": kt,
            "home_strength": round(e["home_team"]["strength"], 4),
            "home_tempo": round(e["home_team"]["tempo"], 4),
            "away_strength": round(e["away_team"]["strength"], 4),
            "away_tempo": round(e["away_team"]["tempo"], 4),
            "lambda_home": round(e["lambda_home"], 3),
            "lambda_away": round(e["lambda_away"], 3),
            "p": {k: round(v, 4) for k, v in p.items()},
        }
    return out


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store, stage = cp1.load_matches(Path(tmp))
        r_all = cp1.build_rows(store, stage, set(cp1.DOMESTIC), set(cp1.SEASONS))
    preds = {n: cp1.predict(r_all, cand(n)) for n in CONFIGS}
    ok = preds["A"][3]
    assert all((p[3] == ok).all() for p in preds.values()), "availability must not depend on k"
    r = r_all.subset(ok)
    P = {n: (cp1.take(p[0], ok), p[1][ok], p[2][ok]) for n, p in preds.items()}
    ids = team_ids(store, r.fixture)
    names = store.team_names

    # reproduction: research predict == production estimate (sample of rows, every config)
    rng = np.random.default_rng(7)
    worst = 0.0
    for i in rng.choice(len(r), 300, replace=False):
        t = r.team[i]
        home = gm.TeamRecord(*[int(x) for x in t[:6]])
        away = gm.TeamRecord(*[int(x) for x in t[6:]])
        H, A = r.cur_hg[i] / r.cur_n[i], r.cur_ag[i] / r.cur_n[i]
        for n, (ks, kt) in CONFIGS.items():
            e = gm.estimate(home, away, (H, A), gm.GoalModelParams(k_s=ks, k_t=kt))
            worst = max(
                worst, abs(e["lambda_home"] - P[n][1][i]), abs(e["lambda_away"] - P[n][2][i])
            )
    assert worst < 1e-9, worst

    res: dict = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "protocol": "docs/research/phase8_cp3ar/goal_model_sensitivity_protocol.md",
        "configs": {n: {"k_s": v[0], "k_t": v[1]} for n, v in CONFIGS.items()},
        "fixtures_available": int(ok.sum()),
        "fixtures_total": len(r_all),
        "reproduction_max_abs_lambda_diff": worst,
        "periods": {},
        "per_league": {},
        "bands": {},
        "months": {},
        "stability": {},
        "shifts": {},
        "examples": [],
    }
    for pname, seasons in PERIODS.items():
        m = np.isin(r.season, seasons)
        rs = r.subset(m)
        block = {"n": int(m.sum())}
        for n in CONFIGS:
            a = cp1.take(P[n][0], m)
            met = metrics(a, rs)
            block[n] = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in met.items()}
            if n != "A":
                block[n]["delta_vs_A"] = deltas(a, cp1.take(P["A"][0], m), rs)
        res["periods"][pname] = block

    for comp in cp1.DOMESTIC:
        m = r.comp == comp
        rs = r.subset(m)
        row = {
            "n": int(m.sum()),
            "A_1x2_log_loss": round(
                float(per_row_losses(cp1.take(P["A"][0], m), rs)["1x2_log_loss"].mean()), 5
            ),
        }
        for n in ("B", "C", "D"):
            row[n] = deltas(
                cp1.take(P[n][0], m),
                cp1.take(P["A"][0], m),
                rs,
                ("1x2_log_loss", "btts_log_loss", "ou_log_loss"),
            )
        res["per_league"][cp1.NAMES[comp]] = row

    nh, na = r.played
    lo = np.minimum(nh, na)
    for bname, band in (
        ("2-5", lo <= 5),
        ("6-9", (lo >= 6) & (lo <= 9)),
        ("10-19", (lo >= 10) & (lo <= 19)),
        ("20+", lo >= 20),
    ):
        rs = r.subset(band)
        res["bands"][bname] = {
            "n": int(band.sum()),
            **{
                n: deltas(
                    cp1.take(P[n][0], band),
                    cp1.take(P["A"][0], band),
                    rs,
                    ("1x2_log_loss", "btts_log_loss", "ou_log_loss"),
                )
                for n in ("B", "C", "D")
            },
        }

    months = np.array([k.month for k in r.kickoff])
    for mo in (8, 9, 10, 11, 12, 1, 2, 3, 4, 5):
        m = months == mo
        if m.sum() < 100:
            continue
        rs = r.subset(m)
        d = deltas(cp1.take(P["D"][0], m), cp1.take(P["A"][0], m), rs, ("1x2_log_loss",))
        res["months"][mo] = {"n": int(m.sum()), "D_minus_A_1x2": d["1x2_log_loss"]}

    for n in CONFIGS:
        mk, lh, la = P[n]
        res["stability"][n] = {
            "sd_lambda_home": round(float(np.std(lh)), 4),
            "sd_lambda_away": round(float(np.std(la)), 4),
            "sd_total": round(float(np.std(lh + la)), 4),
            "mean_total": round(float(np.mean(lh + la)), 4),
            "team_volatility_mean_abs_change": team_volatility(r, ids, lh, la),
        }
        if n != "A":
            res["shifts"][n] = {
                "home_win": shift_stats(np.asarray(mk["home"]) - np.asarray(P["A"][0]["home"])),
                "btts_yes": shift_stats(
                    np.asarray(mk["btts_yes"]) - np.asarray(P["A"][0]["btts_yes"])
                ),
                "over_2_5": shift_stats(np.asarray(mk["over"]) - np.asarray(P["A"][0]["over"])),
                "mean_abs_lambda_total_change": round(
                    float(np.mean(np.abs(lh + la - P["A"][1] - P["A"][2]))), 4
                ),
            }

    # worked examples: an early-season mismatch, a mid-season mismatch, a late-season even game
    dA = np.abs(np.asarray(P["D"][0]["home"]) - np.asarray(P["A"][0]["home"]))
    early = np.flatnonzero((lo <= 4) & (r.comp == 39))
    mid = np.flatnonzero((lo >= 12) & (lo <= 16) & (r.comp == 288))
    late = np.flatnonzero((lo >= 30) & (r.comp == 140))
    for pool in (early, mid, late):
        if len(pool):
            i = pool[np.argmax(dA[pool])]
            res["examples"].append(worked_example(r, i, ids, names))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1, default=str))
    print(
        json.dumps(
            {
                p: {
                    n: res["periods"][p][n].get("delta_vs_A", {}).get("1x2_log_loss")
                    for n in ("B", "C", "D")
                }
                for p in PERIODS
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
