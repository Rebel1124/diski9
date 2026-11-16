"""Research only: venue-specific vs overall vs blended Diski Form Score.

Run: uv run python scripts/research_form_blend.py
Writes docs/research/form_blend/*.json / *.csv. Read-only on the database; no API
calls; production calculations untouched.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

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
from diski9.research.form_blend import WEIGHTS, build_rows
from diski9.research.form_score_comparison import write_csv
from diski9.screener.engine import MatchStore

OUT = Path("docs/research/form_blend")
COMPS = (39, 40, 288, 289)
SEASONS = (2024, 2025, 2026)
LEAGUE = {39: "EPL", 40: "Championship", 288: "PSL", 289: "PSL 1st Div"}
FIRST_TEST = datetime(2025, 8, 1, tzinfo=UTC)


def rate(xs):
    n = len(xs)
    if not n:
        return {"n": 0, "rate": None, "ci95": None}
    p = sum(xs) / n
    h = 1.96 * math.sqrt(p * (1 - p) / n)
    return {"n": n, "rate": round(p, 3), "ci95": [round(p - h, 3), round(p + h, 3)]}


def oos(rows, feats):
    """Walk-forward predictions for each approach; returns test rows and predictions."""
    folds = monthly_folds(FIRST_TEST, max(r.kickoff for r in rows))
    preds, test_rows = {}, None

    def fit_base(train):
        c = Counter(r.outcome for r in train)
        return np.array([c[k] / len(train) for k in range(3)])

    tr, P = walk_forward(
        rows, folds, lambda r: r.kickoff, fit_base, lambda m, t: np.tile(m, (len(t), 1))
    )
    preds["base"], test_rows = P, tr
    for name, fx in feats.items():

        def fit(train, fx=fx):
            return fit_multinomial(np.array([fx(r) for r in train]), [r.outcome for r in train])

        def pred(model, test, fx=fx):
            return model.predict(np.array([fx(r) for r in test]))

        tr, P = walk_forward(rows, folds, lambda r: r.kickoff, fit, pred)
        assert [r.fixture_id for r in tr] == [r.fixture_id for r in test_rows]
        preds[name] = P
    return test_rows, preds


def scores(test_rows, preds, mask=None):
    idx = np.arange(len(test_rows)) if mask is None else np.flatnonzero(mask)
    y = [test_rows[i].outcome for i in idx]
    return {
        name: {
            "log_loss": round(float(log_loss_multiclass(P[idx], y).mean()), 4),
            "brier": round(float(brier_multiclass(P[idx], y).mean()), 4),
            "n": len(idx),
        }
        for name, P in preds.items()
    }


def paired(test_rows, preds, pairs, mask=None):
    idx = np.arange(len(test_rows)) if mask is None else np.flatnonzero(mask)
    y = [test_rows[i].outcome for i in idx]
    wk = [iso_week(test_rows[i].kickoff) for i in idx]
    ll = {k: log_loss_multiclass(P[idx], y) for k, P in preds.items()}
    return {
        f"{a} - {b}": paired_bootstrap(ll[a] - ll[b], wk) for a, b in pairs if a in ll and b in ll
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with make_engine().connect() as c:
        store = MatchStore(c)
    rows, skipped = build_rows(store, COMPS, SEASONS)
    summary: dict = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "fixtures": len(rows),
        "excluded": skipped,
        "by_league": dict(Counter(LEAGUE[r.competition_id] for r in rows)),
        "outcomes": dict(Counter("HDA"[r.outcome] for r in rows)),
        "complete_share": round(sum(r.complete for r in rows) / len(rows), 3),
    }

    # overlap between the venue and overall windows
    hv, ho = np.array([r.home_venue for r in rows]), np.array([r.home_overall for r in rows])
    av, ao = np.array([r.away_venue for r in rows]), np.array([r.away_overall for r in rows])
    summary["overlap"] = {
        "corr_home_venue_overall": round(float(np.corrcoef(hv, ho)[0, 1]), 3),
        "corr_away_venue_overall": round(float(np.corrcoef(av, ao)[0, 1]), 3),
        "mean_shared_matches_home": round(float(np.mean([r.shared_home for r in rows])), 2),
        "mean_shared_matches_away": round(float(np.mean([r.shared_away for r in rows])), 2),
        "shared_distribution_home": dict(sorted(Counter(r.shared_home for r in rows).items())),
    }

    # 1. descriptive, full sample: benchmark-relative indicator (what the app shows)
    desc = {}
    for name, w in WEIGHTS.items():
        home_above = [r.outcome == 0 for r in rows if r.rel_home(w) > 0]
        home_below = [r.outcome == 0 for r in rows if r.rel_home(w) < 0]
        away_above = [r.outcome == 2 for r in rows if r.rel_away(w) > 0]
        away_below = [r.outcome == 2 for r in rows if r.rel_away(w) < 0]
        y_home = [int(r.outcome == 0) for r in rows]
        y_away = [int(r.outcome == 2) for r in rows]
        desc[name] = {
            "home_win_if_home_above": rate(home_above),
            "home_win_if_home_below": rate(home_below),
            "away_win_if_away_above": rate(away_above),
            "away_win_if_away_below": rate(away_below),
            "auc_home_win_rel_home": round(auc([r.rel_home(w) for r in rows], y_home), 3),
            "auc_away_win_rel_away": round(auc([r.rel_away(w) for r in rows], y_away), 3),
            "auc_home_win_diff": round(auc([r.diff(w) for r in rows], y_home), 3),
            "auc_away_win_neg_diff": round(auc([-r.diff(w) for r in rows], y_away), 3),
        }
    summary["indicator_full_sample"] = desc

    # 2. disagreement between the venue and overall indicators
    def side(r, s):
        if s == "home":
            return r.home_venue > r.bench_home, r.home_overall > r.bench_overall, r.outcome == 0
        return r.away_venue > r.bench_away, r.away_overall > r.bench_overall, r.outcome == 2

    dis = {}
    for s in ("home", "away"):
        trip = [side(r, s) for r in rows]
        v_up_o_down = [win for v, o, win in trip if v and not o]
        v_down_o_up = [win for v, o, win in trip if o and not v]
        both_up = [win for v, o, win in trip if v and o]
        both_down = [win for v, o, win in trip if not v and not o]
        dis[s] = {
            "disagree_share": round((len(v_up_o_down) + len(v_down_o_up)) / len(trip), 3),
            "win_rate_venue_above_overall_below": rate(v_up_o_down),
            "win_rate_venue_below_overall_above": rate(v_down_o_up),
            "win_rate_both_above": rate(both_up),
            "win_rate_both_below": rate(both_down),
        }
    either = sum(
        (r.home_venue > r.bench_home) != (r.home_overall > r.bench_overall)
        or (r.away_venue > r.bench_away) != (r.away_overall > r.bench_overall)
        for r in rows
    )
    dis["fixtures_with_any_disagreement_share"] = round(either / len(rows), 3)
    summary["disagreement"] = dis

    # 3. out-of-sample (walk-forward monthly from Aug 2025)
    feats = {}
    for name, w in WEIGHTS.items():
        feats[f"{name}:diff"] = lambda r, w=w: [r.diff(w)]
        feats[f"{name}:rel"] = lambda r, w=w: [r.rel_home(w), r.rel_away(w)]
    feats["venue+overall:diff (2 features)"] = lambda r: [r.diff(1.0), r.diff(0.0)]
    test_rows, preds = oos(rows, feats)
    summary["oos"] = {
        "test_fixtures": len(test_rows),
        "test_period": [
            test_rows[0].kickoff.date().isoformat(),
            test_rows[-1].kickoff.date().isoformat(),
        ],
        "scores": scores(test_rows, preds),
    }
    pairs = []
    for kind in ("diff", "rel"):
        for name in WEIGHTS:
            if name != "venue":
                pairs.append((f"{name}:{kind}", f"venue:{kind}"))
            if name != "overall":
                pairs.append((f"{name}:{kind}", f"overall:{kind}"))
    pairs += [("venue+overall:diff (2 features)", "overall:diff"), ("overall:diff", "base")]
    summary["oos"]["paired_vs"] = paired(test_rows, preds, pairs)

    # 4. subsets: limited history, disagreement fixtures, competitions, periods
    limited = np.array([not r.complete for r in test_rows])
    disagree = np.array(
        [
            (r.home_venue > r.bench_home) != (r.home_overall > r.bench_overall)
            or (r.away_venue > r.bench_away) != (r.away_overall > r.bench_overall)
            for r in test_rows
        ]
    )
    key = ["base"] + [f"{n}:diff" for n in WEIGHTS]
    sub = lambda m: {k: v for k, v in scores(test_rows, preds, m).items() if k in key}  # noqa: E731
    main_pairs = [("venue:diff", "overall:diff"), ("blend_50:diff", "overall:diff")]
    summary["oos_subsets"] = {
        "complete_windows": sub(~limited),
        "limited_history": sub(limited),
        "limited_history_paired": paired(test_rows, preds, main_pairs, limited),
        "indicators_disagree": sub(disagree),
        "indicators_disagree_paired": paired(test_rows, preds, main_pairs, disagree),
        "indicators_agree": sub(~disagree),
    }
    rows_out = []
    for comp in COMPS:
        m = np.array([r.competition_id == comp for r in test_rows])
        sc = scores(test_rows, preds, m)
        pv = paired(test_rows, preds, main_pairs, m)
        rows_out.append(
            {
                "league": LEAGUE[comp],
                "n": int(m.sum()),
                **{k: sc[k]["log_loss"] for k in key},
                "venue_minus_overall": pv["venue:diff - overall:diff"]["mean"],
                "venue_minus_overall_ci": pv["venue:diff - overall:diff"]["ci95"],
            }
        )
    for label, lo, hi in (
        (
            "2025/26 (Aug 2025 - Jun 2026)",
            datetime(2025, 8, 1, tzinfo=UTC),
            datetime(2026, 7, 1, tzinfo=UTC),
        ),
        ("2026/27 to date", datetime(2026, 7, 1, tzinfo=UTC), datetime(2027, 7, 1, tzinfo=UTC)),
    ):
        m = np.array([lo <= r.kickoff < hi for r in test_rows])
        sc = scores(test_rows, preds, m)
        pv = paired(test_rows, preds, main_pairs, m)
        rows_out.append(
            {
                "league": label,
                "n": int(m.sum()),
                **{k: sc[k]["log_loss"] for k in key},
                "venue_minus_overall": pv["venue:diff - overall:diff"]["mean"],
                "venue_minus_overall_ci": pv["venue:diff - overall:diff"]["ci95"],
            }
        )
    write_csv(OUT / "oos_by_league_and_period.csv", rows_out)
    summary["oos_by_league_and_period"] = rows_out
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "indicator_full_sample"},
            indent=1,
            default=str,
        )
    )
    print(json.dumps(summary["indicator_full_sample"], indent=1))


if __name__ == "__main__":
    main()
