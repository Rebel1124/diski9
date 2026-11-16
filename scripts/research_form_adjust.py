"""Research only: overall window length (5-8) and venue adjustments.

Run: uv run python scripts/research_form_adjust.py
Writes docs/research/form_adjust/*. Read-only; no API calls; production untouched.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import numpy as np

from diski9.db import make_engine
from diski9.research.evaluation import (
    auc,
    brier_multiclass,
    fit_multinomial,
    iso_week,
    log_loss_multiclass,
    monthly_folds,
    paired_bootstrap,
    walk_forward,
)
from diski9.research.form_adjust import ADJUST_WEIGHTS, WINDOWS, build_rows
from diski9.research.form_score_comparison import write_csv
from diski9.screener.engine import MatchStore

OUT = Path("docs/research/form_adjust")
COMPS = (39, 40, 288, 289)
SEASONS = (2024, 2025, 2026)
LEAGUE = {39: "EPL", 40: "Championship", 288: "PSL", 289: "PSL 1st Div"}
FIRST_TEST = datetime(2025, 8, 1, tzinfo=UTC)
EARLY_DAYS = 56  # first eight weeks of a competition's season


def run_oos(rows, feats):
    folds = monthly_folds(FIRST_TEST, max(r.kickoff for r in rows))
    preds, test = {}, None
    for name, fx in feats.items():

        def fit(train, fx=fx):
            return fit_multinomial(np.array([fx(r) for r in train]), [r.outcome for r in train])

        def pred(model, rs, fx=fx):
            return model.predict(np.array([fx(r) for r in rs]))

        tr, P = walk_forward(rows, folds, lambda r: r.kickoff, fit, pred)
        if test is None:
            test = tr
        assert [r.fixture_id for r in tr] == [r.fixture_id for r in test]
        preds[name] = P
    return test, preds


def table(test, preds, names, pairs, mask=None):
    idx = np.arange(len(test)) if mask is None else np.flatnonzero(mask)
    y = [test[i].outcome for i in idx]
    wk = [iso_week(test[i].kickoff) for i in idx]
    ll = {n: log_loss_multiclass(preds[n][idx], y) for n in names}
    out = {"n": len(idx), "models": {}, "paired": {}}
    for n in names:
        out["models"][n] = {
            "log_loss": round(float(ll[n].mean()), 4),
            "brier": round(float(brier_multiclass(preds[n][idx], y).mean()), 4),
        }
    for a, b in pairs:
        out["paired"][f"{a} - {b}"] = paired_bootstrap(ll[a] - ll[b], wk)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with make_engine().connect() as c:
        store = MatchStore(c)
    rows, skipped = build_rows(store, COMPS, SEASONS)
    bench_rows = [r for r in rows if r.benchmarks_available]
    summary: dict = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "fixtures_with_scores": len(rows),
        "excluded_no_score": skipped["no_score"],
        "fixtures_with_all_benchmarks": len(bench_rows),
        "excluded_no_benchmark": len(rows) - len(bench_rows),
        "by_league_benchmarked": dict(Counter(LEAGUE[r.competition_id] for r in bench_rows)),
    }

    # ---------------------------------------------------------- Question 1
    # provenance and staleness of windows (both teams, all fixtures with scores)
    prov = {}
    for n in WINDOWS:
        backs = [b for r in rows for b in r.reaches_back[n]]
        early = [b for r in rows if r.days_into_season <= EARLY_DAYS for b in r.reaches_back[n]]
        ages = [a for r in rows for a in r.oldest_days[n]]
        early_ages = [a for r in rows if r.days_into_season <= EARLY_DAYS for a in r.oldest_days[n]]
        prov[f"overall{n}"] = {
            "windows_reaching_earlier_season_or_division": round(mean(backs), 3),
            "same_in_first_8_weeks": round(mean(early), 3),
            "median_age_oldest_match_days": round(float(np.median(ages)), 1),
            "median_age_oldest_match_days_first_8_weeks": round(float(np.median(early_ages)), 1),
        }
    # responsiveness: how much a team's score moves after each new match (same season)
    seq = defaultdict(list)
    for r in rows:
        for side, team in ((0, r.home_id), (1, r.away_id)):
            seq[(team, r.competition_id, r.season)].append(
                (r.kickoff, {n: r.overall[n][side] for n in WINDOWS})
            )
    for n in WINDOWS:
        steps = []
        for s in seq.values():
            s.sort(key=lambda x: x[0])
            steps += [abs(b[1][n] - a[1][n]) for a, b in zip(s, s[1:], strict=False)]
        prov[f"overall{n}"]["mean_abs_change_per_match"] = round(mean(steps), 3)
    summary["q1_windows"] = prov

    q1_feats = {f"o{n}": (lambda r, n=n: [r.diff(n)]) for n in WINDOWS}
    q1_pairs = [(f"o{n}", "o8") for n in (5, 6, 7)] + [("o5", "o6"), ("o7", "o6")]
    names = list(q1_feats)
    test_b, preds_b = run_oos(bench_rows, q1_feats)
    test_a, preds_a = run_oos(rows, q1_feats)
    early = np.array([r.days_into_season <= EARLY_DAYS for r in test_a])
    summary["q1_oos"] = {
        "benchmarked_sample": table(test_b, preds_b, names, q1_pairs),
        "all_fixtures_with_scores": table(test_a, preds_a, names, q1_pairs),
        "first_8_weeks_of_season": table(test_a, preds_a, names, q1_pairs, early),
        "after_first_8_weeks": table(test_a, preds_a, names, q1_pairs, ~early),
    }
    y_home = [int(r.outcome == 0) for r in bench_rows]
    y_away = [int(r.outcome == 2) for r in bench_rows]
    summary["q1_ranking"] = {
        f"o{n}": {
            "auc_home_win": round(auc([r.diff(n) for r in bench_rows], y_home), 3),
            "auc_away_win": round(auc([-r.diff(n) for r in bench_rows], y_away), 3),
        }
        for n in WINDOWS
    }

    # ---------------------------------------------------------- Question 2
    q2_feats = {}
    for n in (6, 8):
        q2_feats[f"o{n}"] = lambda r, n=n: [r.diff(n)]
        for kind in ("raw", "rel"):
            for w in ADJUST_WEIGHTS[1:]:
                q2_feats[f"o{n}+{kind}{w:g}"] = lambda r, n=n, k=kind, w=w: [
                    r.adjusted_diff(n, k, w)
                ]
        # diagnostic only: weight left free (fitted in each fold)
        q2_feats[f"o{n}+raw(free)"] = lambda r, n=n: [
            r.diff(n),
            r.adjusted_diff(n, "raw", 1) - r.diff(n),
        ]
        q2_feats[f"o{n}+rel(free)"] = lambda r, n=n: [
            r.diff(n),
            r.adjusted_diff(n, "rel", 1) - r.diff(n),
        ]
    names2 = list(q2_feats)
    pairs2 = [(k, k.split("+")[0]) for k in names2 if "+" in k] + [("o8", "o6")]
    test2, preds2 = run_oos(bench_rows, q2_feats)
    summary["q2_oos"] = table(test2, preds2, names2, pairs2)

    def disagree(r):
        bo, (bh, ba) = r.bench_overall[8], r.bench_venue
        (oh, oa), (vh, va) = r.overall[8], r.venue
        return ((vh > bh) != (oh > bo)) or ((va > ba) != (oa > bo))

    dis = np.array([disagree(r) for r in test2])
    limited = np.array([not r.complete for r in test2])
    main = ["o6", "o8", "o6+raw0.25", "o8+raw0.25", "o6+rel0.25", "o8+rel0.25", "o8+rel0.5"]
    main_pairs = [(k, k.split("+")[0]) for k in main if "+" in k] + [("o8", "o6")]
    summary["q2_subsets"] = {
        "venue_overall_disagree": table(test2, preds2, main, main_pairs, dis),
        "venue_overall_agree": table(test2, preds2, main, main_pairs, ~dis),
        "limited_history": table(test2, preds2, main, main_pairs, limited),
    }
    by = []
    for comp in COMPS:
        mk = np.array([r.competition_id == comp for r in test2])
        t = table(test2, preds2, main, [("o8+rel0.25", "o8"), ("o8", "o6")], mk)
        by.append(
            {
                "subset": LEAGUE[comp],
                "n": t["n"],
                **{k: t["models"][k]["log_loss"] for k in main},
                "o8_minus_o6": t["paired"]["o8 - o6"]["mean"],
                "o8_minus_o6_ci": t["paired"]["o8 - o6"]["ci95"],
                "rel25_minus_o8": t["paired"]["o8+rel0.25 - o8"]["mean"],
                "rel25_minus_o8_ci": t["paired"]["o8+rel0.25 - o8"]["ci95"],
            }
        )
    for label, lo, hi in (
        ("2025/26", datetime(2025, 8, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)),
        ("2026/27 to date", datetime(2026, 7, 1, tzinfo=UTC), datetime(2027, 7, 1, tzinfo=UTC)),
    ):
        mk = np.array([lo <= r.kickoff < hi for r in test2])
        t = table(test2, preds2, main, [("o8+rel0.25", "o8"), ("o8", "o6")], mk)
        by.append(
            {
                "subset": label,
                "n": t["n"],
                **{k: t["models"][k]["log_loss"] for k in main},
                "o8_minus_o6": t["paired"]["o8 - o6"]["mean"],
                "o8_minus_o6_ci": t["paired"]["o8 - o6"]["ci95"],
                "rel25_minus_o8": t["paired"]["o8+rel0.25 - o8"]["mean"],
                "rel25_minus_o8_ci": t["paired"]["o8+rel0.25 - o8"]["ci95"],
            }
        )
    write_csv(OUT / "q2_by_league_and_season.csv", by)
    summary["q2_by_league_and_season"] = by

    # home vs away ranking (full benchmarked sample, no fitting)
    rank = {}
    for name in main:
        n = int(name[1])
        if "+" in name:
            kind = "raw" if "raw" in name else "rel"
            w = float(name.split(kind)[1])
            d = [r.adjusted_diff(n, kind, w) for r in bench_rows]
        else:
            d = [r.diff(n) for r in bench_rows]
        rank[name] = {
            "auc_home_win": round(auc(d, y_home), 3),
            "auc_away_win": round(auc([-x for x in d], y_away), 3),
        }
    summary["q2_ranking"] = rank
    adj_corr = {}
    for kind in ("raw", "rel"):
        a = np.array([r.adjustment(8, kind)[0] - r.adjustment(8, kind)[1] for r in bench_rows])
        d = np.array([r.diff(8) for r in bench_rows])
        adj_corr[kind] = {
            "corr_with_o8_difference": round(float(np.corrcoef(a, d)[0, 1]), 3),
            "sd": round(float(a.std()), 3),
        }
    summary["q2_adjustment_properties"] = adj_corr
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, indent=1, default=str)[:200])


if __name__ == "__main__":
    main()
