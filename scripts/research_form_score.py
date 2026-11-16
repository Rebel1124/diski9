"""Milestone 5.1 research: Method A (banded, production) vs Method B (continuous).

Run: uv run python scripts/research_form_score.py
Writes docs/research/form_score_summary.json and CSV tables in docs/research/.
Read-only on the database; no API calls; production results untouched.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from diski9.db import make_engine
from diski9.research.form_score_comparison import (
    bootstrap_logloss_difference,
    build_dataset,
    describe,
    out_of_sample,
    outcome_by_band,
    outcome_by_quantile,
    ranking_discrimination,
    write_csv,
)
from diski9.screener.engine import MatchStore

OUT = Path("docs/research")
COMPS = (39, 40, 288, 289)
SEASONS = (2024, 2025, 2026)
LEAGUE = {39: "EPL", 40: "Championship", 288: "PSL", 289: "PSL 1st Div"}
BANDS = [(-5.01, -2), (-2, -1), (-1, -0.25), (-0.25, 0.25), (0.25, 1), (1, 2), (2, 5.01)]


def team_scores(rows, method, side=None, **filters):
    out = []
    for r in rows:
        if any(getattr(r, k) != v for k, v in filters.items()):
            continue
        for s in ("home", "away") if side is None else (side,):
            v = getattr(r, f"{method}_{s}")
            if v is not None:
                out.append(v)
    return out


def main() -> None:
    with make_engine().connect() as c:
        store = MatchStore(c)
    rows = build_dataset(store, COMPS, SEASONS)
    summary: dict = {"fixtures": len({r.fixture_id for r in rows}), "rows": len(rows)}
    summary["coverage"] = {
        f"{LEAGUE[c]} {s}": len(
            {r.fixture_id for r in rows if r.competition_id == c and r.season == s}
        )
        for c in COMPS
        for s in SEASONS
    }
    summary["outcomes"] = dict(Counter(r.outcome for r in rows if r.basis == "venue"))

    # distributions
    dist = {}
    for basis in ("venue", "overall"):
        for m in ("a", "b"):
            dist[f"{basis}_{m}_all"] = describe(team_scores(rows, m, basis=basis))
            dist[f"{basis}_{m}_home_team"] = describe(team_scores(rows, m, "home", basis=basis))
            dist[f"{basis}_{m}_away_team"] = describe(team_scores(rows, m, "away", basis=basis))
            dist[f"{basis}_{m}_diff"] = describe(
                [
                    getattr(r, f"{m}_diff")
                    for r in rows
                    if r.basis == basis and getattr(r, f"{m}_diff") is not None
                ]
            )
    summary["distributions"] = dist
    by_league = []
    for comp in COMPS:
        for season in SEASONS:
            for m in ("a", "b"):
                d = describe(
                    team_scores(rows, m, basis="venue", competition_id=comp, season=season)
                )
                by_league.append(
                    {
                        "league": LEAGUE[comp],
                        "season": season,
                        "method": m.upper(),
                        **{
                            k: d.get(k)
                            for k in (
                                "n",
                                "mean",
                                "median",
                                "sd",
                                "distinct",
                                "share_tied",
                                "share_lowest_20pct_of_scale",
                            )
                        },
                    }
                )
    write_csv(OUT / "form_score_distribution_by_league_season.csv", by_league)

    # ranking discrimination
    summary["ranking"] = {b: ranking_discrimination(rows, b) for b in ("venue", "overall")}

    # outcomes
    outcome_rows = []
    for basis in ("venue", "overall"):
        sub = [r for r in rows if r.basis == basis]
        for m in ("a", "b"):
            for x in outcome_by_band(sub, m, BANDS):
                outcome_rows.append({"basis": basis, "method": m.upper(), "kind": "band", **x})
            for x in outcome_by_quantile(sub, m):
                outcome_rows.append(
                    {
                        "basis": basis,
                        "method": m.upper(),
                        "kind": "quintile",
                        "band": f"Q{x['quantile']} {x['diff_range']}",
                        **{k: x[k] for k in ("n", "home", "draw", "away")},
                    }
                )
    write_csv(OUT / "form_score_outcomes_by_band.csv", outcome_rows)
    summary["outcome_quintiles_venue"] = {
        m: outcome_by_quantile([r for r in rows if r.basis == "venue"], m) for m in ("a", "b")
    }

    # stability: home-win rate in top vs bottom quintile, by league and season (venue basis)
    stability = []
    for comp in COMPS:
        for season in SEASONS:
            sub = [
                r
                for r in rows
                if r.basis == "venue" and r.competition_id == comp and r.season == season
            ]
            if len(sub) < 100:
                continue
            for m in ("a", "b"):
                q = outcome_by_quantile(sub, m)
                stability.append(
                    {
                        "league": LEAGUE[comp],
                        "season": season,
                        "method": m.upper(),
                        "n": len(sub),
                        "home_rate_Q1": q[0]["home"],
                        "home_rate_Q5": q[-1]["home"],
                        "away_rate_Q1": q[0]["away"],
                        "away_rate_Q5": q[-1]["away"],
                        "home_spread_Q5_minus_Q1": round(q[-1]["home"] - q[0]["home"], 3),
                    }
                )
    write_csv(OUT / "form_score_stability.csv", stability)
    summary["stability_mean_home_spread"] = {
        m: round(
            sum(s["home_spread_Q5_minus_Q1"] for s in stability if s["method"] == m.upper())
            / max(1, sum(1 for s in stability if s["method"] == m.upper())),
            3,
        )
        for m in ("a", "b")
    }

    # out-of-sample (chronological)
    oos = {}
    for label, tr, te in (
        ("train_2024_test_2025_2026", {2024}, {2025, 2026}),
        ("train_2024_2025_test_2026", {2024, 2025}, {2026}),
    ):
        for basis in ("venue", "overall"):
            oos[f"{label}_{basis}"] = out_of_sample(rows, tr, te, basis)
            oos[f"{label}_{basis}"]["paired_bootstrap"] = bootstrap_logloss_difference(
                rows, tr, te, basis
            )
    summary["out_of_sample"] = oos
    summary["exploratory_c_distribution_venue"] = describe(team_scores(rows, "c", basis="venue"))
    summary["exploratory_c_quintiles_venue"] = outcome_by_quantile(
        [r for r in rows if r.basis == "venue"], "c"
    )

    # sensitivity
    sens = {}
    for name, pred in (
        ("complete_windows", lambda r: r.complete),
        ("partial_windows", lambda r: not r.complete),
        ("promoted_involved", lambda r: r.promoted_involved),
        ("no_promoted", lambda r: not r.promoted_involved),
    ):
        sub = [r for r in rows if pred(r)]
        sens[name] = {
            "rows_venue": sum(r.basis == "venue" for r in sub),
            "share_of_venue_rows": round(
                sum(r.basis == "venue" for r in sub)
                / max(1, sum(r.basis == "venue" for r in rows)),
                3,
            ),
            "oos_train_2024_test_2025_2026_venue": out_of_sample(sub, {2024}, {2025, 2026}, "venue")
            if sum(r.basis == "venue" and r.season == 2024 for r in sub) > 200
            else None,
        }
    venue_rows = [r for r in rows if r.basis == "venue"]
    team_windows = [(r.home_bonuses, r.home_gd) for r in venue_rows] + [
        (r.away_bonuses, r.away_gd) for r in venue_rows
    ]
    sens["bonus_trigger_rates_venue"] = {
        "won_last_three": round(sum(b[0] for b, _ in team_windows) / len(team_windows), 3),
        "scored_11_plus": round(sum(b[1] for b, _ in team_windows) / len(team_windows), 3),
        "conceded_2_or_fewer": round(sum(b[2] for b, _ in team_windows) / len(team_windows), 3),
    }
    gds = [g for _, g in team_windows if g is not None]
    sens["goal_difference_venue"] = {
        "share_gd_le_0": round(sum(g <= 0 for g in gds) / len(gds), 3),
        "share_gd_ge_9_capped": round(sum(g >= 9 for g in gds) / len(gds), 3),
        "gd_distribution": dict(sorted(Counter(max(min(g, 12), -12) for g in gds).items())),
    }
    pts = defaultdict(int)
    summary["sensitivity"] = sens
    del pts
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "form_score_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({k: summary[k] for k in ("fixtures", "rows", "outcomes")}, indent=1))
    print(json.dumps(summary["ranking"], indent=1))
    print(
        json.dumps(
            {k: v for k, v in summary["distributions"].items() if k.endswith(("_all", "_diff"))},
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
