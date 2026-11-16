"""Milestone 5.2 research: Diski Form Score candidates A-D (offline).

Run: uv run python scripts/research_m52_form.py
Writes docs/research/m52/form_*.{json,csv,svg}. Read-only on the database; no
API calls; production results untouched. Plan: docs/research/m52/preregistration.md
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import numpy as np

from diski9.db import make_engine
from diski9.research.charts import grouped_bars, histogram_panels
from diski9.research.evaluation import (
    brier_multiclass,
    expected_calibration_error,
    fit_multinomial,
    iso_week,
    log_loss_multiclass,
    monthly_folds,
    paired_bootstrap,
    walk_forward,
)
from diski9.research.form_models import MODEL_NAMES, MODELS, build_rows, features
from diski9.research.form_score_comparison import describe, spearman, top, write_csv
from diski9.screener.engine import MatchStore

OUT = Path("docs/research/m52")
COMPS = (39, 40, 288, 289)
SEASONS = (2024, 2025, 2026)
LEAGUE = {39: "EPL", 40: "Championship", 288: "PSL", 289: "PSL 1st Div"}
FEATURES = (
    "base",
    "a",
    "b",
    "c",
    "d",
    "ppg",
    "gd",
    "ppg_gd",
    "venue_ppg",
    "ppg_gd_gf",
    "d_plus_bonuses",
)
FIRST_TEST = datetime(2025, 8, 1, tzinfo=UTC)


BAND_LABELS = [
    "(-5, -2]",
    "(-2, -1]",
    "(-1, -0.25]",
    "(-0.25, 0.25)",
    "[0.25, 1)",
    "[1, 2)",
    "[2, 5]",
]


def band_of(d: float) -> str:
    """Predeclared, symmetric Form Difference bands."""
    if d <= -2:
        return BAND_LABELS[0]
    if d <= -1:
        return BAND_LABELS[1]
    if d <= -0.25:
        return BAND_LABELS[2]
    if d < 0.25:
        return BAND_LABELS[3]
    if d < 1:
        return BAND_LABELS[4]
    if d < 2:
        return BAND_LABELS[5]
    return BAND_LABELS[6]


def team_scores(rows, model, side=None):
    out = []
    for r in rows:
        h, a = r.scores[model]
        if side in (None, "home") and h is not None:
            out.append(h)
        if side in (None, "away") and a is not None:
            out.append(a)
    return out


def ranking(rows, basis):
    groups = defaultdict(list)
    for r in rows:
        if r.basis == basis and all(r.diff(m) is not None for m in MODELS):
            groups[iso_week(r.kickoff)].append(r)
    stats = defaultdict(list)
    for g in groups.values():
        if len(g) < 10:
            continue
        d = {m: {r.fixture_id: round(r.diff(m), 9) for r in g} for m in MODELS}
        for m in MODELS:
            c = Counter(d[m].values())
            stats[f"{m}_share_fixtures_tied"].append(sum(v for v in c.values() if v > 1) / len(g))
            stats[f"{m}_distinct_per_fixture"].append(len(c) / len(g))
            if m != "a":
                stats[f"{m}_spearman_vs_a"].append(spearman(d["a"], d[m]))
                for key, f in (("home", lambda v: -v), ("away", lambda v: v), ("even", abs)):
                    stats[f"{m}_top5_{key}_overlap_vs_a"].append(
                        len(top(d["a"], 5, f) & top(d[m], 5, f)) / 5
                    )
    return {"weekly_lists": len(stats["a_share_fixtures_tied"])} | {
        k: round(mean(v), 3) for k, v in stats.items()
    }


def outcomes_by_band(rows, model):
    out = []
    for label in BAND_LABELS:
        sel = [r for r in rows if (d := r.diff(model)) is not None and band_of(d) == label]
        c = Counter(r.outcome for r in sel)
        n = len(sel)
        out.append(
            {
                "band": label,
                "n": n,
                "home": round(c[0] / n, 3) if n else None,
                "draw": round(c[1] / n, 3) if n else None,
                "away": round(c[2] / n, 3) if n else None,
            }
        )
    return out


def quintiles(rows, model, q=5):
    sel = sorted(
        (r for r in rows if r.diff(model) is not None), key=lambda r: (r.diff(model), r.fixture_id)
    )
    out = []
    for i in range(q):
        chunk = sel[i * len(sel) // q : (i + 1) * len(sel) // q]
        c = Counter(r.outcome for r in chunk)
        out.append(
            {
                "q": i + 1,
                "n": len(chunk),
                "home": round(c[0] / len(chunk), 3),
                "draw": round(c[1] / len(chunk), 3),
                "away": round(c[2] / len(chunk), 3),
            }
        )
    return out


def monotone_violations(table, key="home"):
    vals = [r[key] for r in table if r["n"] >= 30]
    return sum(b < a for a, b in zip(vals, vals[1:], strict=False))


def oos(rows, basis, feats=FEATURES, subset=None):
    data = [r for r in rows if r.basis == basis]
    data = [r for r in data if all(f == "base" or features(r, f) is not None for f in feats)]
    if subset is not None:
        keep = {r.fixture_id for r in data if subset(r)}
    folds = monthly_folds(FIRST_TEST, max(r.kickoff for r in data))
    preds, test_rows = {}, None
    for f in feats:
        if f == "base":

            def fit(train):
                c = Counter(r.outcome for r in train)
                return np.array([c[k] / len(train) for k in range(3)])

            def pred(model, test):
                return np.tile(model, (len(test), 1))
        else:

            def fit(train, f=f):
                return fit_multinomial(
                    np.array([features(r, f) for r in train]), [r.outcome for r in train]
                )

            def pred(model, test, f=f):
                return model.predict(np.array([features(r, f) for r in test]))

        tr, P = walk_forward(data, folds, lambda r: r.kickoff, fit, pred)
        test_rows = tr
        preds[f] = P
    if subset is not None:
        mask = np.array([r.fixture_id in keep for r in test_rows])
        test_rows = [r for r, k in zip(test_rows, mask, strict=True) if k]
        preds = {f: P[mask] for f, P in preds.items()}
    y = [r.outcome for r in test_rows]
    weeks = [iso_week(r.kickoff) for r in test_rows]
    ll = {f: log_loss_multiclass(P, y) for f, P in preds.items()}
    br = {f: brier_multiclass(P, y) for f, P in preds.items()}
    res = {
        "n": len(y),
        "test_period": [
            min(r.kickoff for r in test_rows).date().isoformat(),
            max(r.kickoff for r in test_rows).date().isoformat(),
        ],
        "folds": len({(r.kickoff.year, r.kickoff.month) for r in test_rows}),
        "models": {},
        "paired": {},
    }
    for f in feats:
        P = preds[f]
        res["models"][f] = {
            "log_loss": round(float(ll[f].mean()), 4),
            "brier": round(float(br[f].mean()), 4),
            "ece_home": expected_calibration_error(P[:, 0], [int(v == 0) for v in y]),
            "ece_draw": expected_calibration_error(P[:, 1], [int(v == 1) for v in y]),
            "ece_away": expected_calibration_error(P[:, 2], [int(v == 2) for v in y]),
        }
    pairs = [(f, "a") for f in feats if f != "a"] + [
        ("a", "base"),
        ("c", "d"),
        ("d_plus_bonuses", "d"),
        ("ppg_gd_gf", "ppg_gd"),
        ("a", "ppg_gd"),
        ("d", "ppg_gd"),
    ]
    for x, ref in pairs:
        if x in ll and ref in ll:
            res["paired"][f"{x}_minus_{ref}"] = paired_bootstrap(ll[x] - ll[ref], weeks)
    return res, test_rows, preds


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with make_engine().connect() as c:
        store = MatchStore(c)
    rows = build_rows(store, COMPS, SEASONS)
    venue = [r for r in rows if r.basis == "venue"]
    summary: dict = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "fixtures": len(venue),
        "coverage": {
            f"{LEAGUE[c]} {s}": sum(r.competition_id == c and r.season == s for r in venue)
            for c in COMPS
            for s in SEASONS
        },
        "outcomes": dict(Counter("HDA"[r.outcome] for r in venue)),
        "complete_window_share": round(sum(r.complete for r in venue) / len(venue), 3),
        "changed_division_share": round(sum(r.changed_division for r in venue) / len(venue), 3),
        "other_division_in_window_share": round(
            sum(r.other_division_in_window for r in venue) / len(venue), 3
        ),
    }

    # distributions
    dist, dist_rows = {}, []
    for basis in ("venue", "overall"):
        sub = [r for r in rows if r.basis == basis]
        for m in MODELS:
            d_all = describe(team_scores(sub, m))
            d_diff = describe([r.diff(m) for r in sub if r.diff(m) is not None])
            dist[f"{basis}_{m}"] = {
                "team": d_all,
                "home_team": describe(team_scores(sub, m, "home")),
                "away_team": describe(team_scores(sub, m, "away")),
                "difference": d_diff,
            }
            dist_rows.append(
                {
                    "basis": basis,
                    "model": m.upper(),
                    **{
                        f"team_{k}": d_all.get(k) for k in ("n", "mean", "median", "sd", "distinct")
                    },
                    "team_most_common": d_all["most_common"],
                    "team_share_le_1": d_all["share_lowest_20pct_of_scale"],
                    "diff_distinct": d_diff["distinct"],
                    "diff_sd": d_diff["sd"],
                }
            )
    summary["distributions"] = dist
    write_csv(OUT / "form_distributions.csv", dist_rows)

    # ties and rankings
    summary["ranking"] = {b: ranking(rows, b) for b in ("venue", "overall")}

    # outcomes by predeclared band
    band_rows = []
    summary["bands"] = {}
    for basis in ("venue", "overall"):
        sub = [r for r in rows if r.basis == basis]
        for m in MODELS:
            t = outcomes_by_band(sub, m)
            summary["bands"][f"{basis}_{m}"] = {
                "table": t,
                "home_rate_monotone_violations": monotone_violations(t, "home"),
                "away_rate_monotone_violations": sum(
                    b > a
                    for a, b in zip(
                        [r["away"] for r in t if r["n"] >= 30],
                        [r["away"] for r in t if r["n"] >= 30][1:],
                        strict=False,
                    )
                ),
                "quintiles": quintiles(sub, m),
            }
            band_rows += [{"basis": basis, "model": m.upper(), **x} for x in t]
    write_csv(OUT / "form_outcomes_by_band.csv", band_rows)

    # stability by league-season and promoted sides (venue)
    stab = []
    for comp in COMPS:
        for season in SEASONS:
            sub = [r for r in venue if r.competition_id == comp and r.season == season]
            if len(sub) < 100:
                continue
            for m in MODELS:
                q = quintiles(sub, m)
                stab.append(
                    {
                        "league": LEAGUE[comp],
                        "season": season,
                        "model": m.upper(),
                        "n": len(sub),
                        "home_Q1": q[0]["home"],
                        "home_Q5": q[-1]["home"],
                        "spread": round(q[-1]["home"] - q[0]["home"], 3),
                    }
                )
    write_csv(OUT / "form_stability.csv", stab)
    summary["stability"] = {
        m.upper(): {
            "mean_spread": round(mean(s["spread"] for s in stab if s["model"] == m.upper()), 3),
            "min_spread": min(s["spread"] for s in stab if s["model"] == m.upper()),
            "league_seasons": sum(s["model"] == m.upper() for s in stab),
        }
        for m in MODELS
    }
    promoted = [r for r in venue if r.changed_division]
    summary["changed_division_quintiles"] = {
        "n": len(promoted),
        **{m: quintiles(promoted, m) for m in MODELS},
    }

    # out-of-sample walk-forward
    summary["out_of_sample"] = {}
    for basis in ("venue", "overall"):
        res, test_rows, preds = oos(rows, basis)
        summary["out_of_sample"][basis] = res
        if basis == "venue":
            cal = []
            y = [r.outcome for r in test_rows]
            from diski9.research.evaluation import calibration_table

            for m in ("a", "c", "d"):
                for k, name in enumerate(("home", "draw", "away")):
                    for b in calibration_table(preds[m][:, k], [int(v == k) for v in y]):
                        cal.append({"model": m.upper(), "outcome": name, **b})
            write_csv(OUT / "form_oos_calibration_venue.csv", cal)
            by_league = []
            for comp in COMPS:
                idx = [i for i, r in enumerate(test_rows) if r.competition_id == comp]
                yy = [y[i] for i in idx]
                for m in ("base", "a", "b", "c", "d", "ppg_gd"):
                    by_league.append(
                        {
                            "league": LEAGUE[comp],
                            "model": m,
                            "n": len(idx),
                            "log_loss": round(
                                float(log_loss_multiclass(preds[m][idx], yy).mean()), 4
                            ),
                        }
                    )
            write_csv(OUT / "form_oos_by_league_venue.csv", by_league)
    summary["out_of_sample_changed_division_venue"] = oos(
        rows, "venue", ("base", "a", "c", "d"), subset=lambda r: r.changed_division
    )[0]
    summary["out_of_sample_complete_windows_venue"] = oos(
        rows, "venue", ("base", "a", "b", "c", "d"), subset=lambda r: r.complete
    )[0]

    (OUT / "form_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")

    # charts
    panels = {MODEL_NAMES[m]: team_scores(venue, m) for m in MODELS}
    histogram_panels(
        OUT / "form_score_distributions.svg",
        panels,
        bins=[i / 4 for i in range(21)],
        title=f"Team Form Scores, venue basis (n = {len(panels[MODEL_NAMES['a']])} per model)",
        x_label="Form Score",
    )
    tie = summary["ranking"]
    grouped_bars(
        OUT / "form_ties.svg",
        categories=[m.upper() for m in MODELS],
        series={
            "Venue": [tie["venue"][f"{m}_share_fixtures_tied"] * 100 for m in MODELS],
            "Overall": [tie["overall"][f"{m}_share_fixtures_tied"] * 100 for m in MODELS],
        },
        title="Fixtures whose Form Difference ties another in the same weekly list (%)",
        y_label="% of fixtures tied",
        y_max=100,
    )
    print(json.dumps({k: summary[k] for k in ("fixtures", "outcomes", "ranking")}, indent=1))
    for b in ("venue", "overall"):
        o = summary["out_of_sample"][b]
        print(b, o["n"], o["test_period"], {k: v["log_loss"] for k, v in o["models"].items()})
        print({k: (v["mean"], v["ci95"]) for k, v in o["paired"].items()})


if __name__ == "__main__":
    main()
