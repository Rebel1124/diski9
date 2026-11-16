"""Research only: is the 50/50 venue/overall blend's advantage just a longer window?

Compares venue (5), overall (5), 50/50 blend, overall 7, overall 8 and overall 10 on
an identical fixture set, with point-in-time league benchmarks for each.

Run: uv run python scripts/research_form_windows.py
Writes docs/research/form_windows/*. Read-only; no API calls; production untouched.
"""

from __future__ import annotations

import json
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
from diski9.research.form_blend import APPROACHES, build_window_rows
from diski9.research.form_score_comparison import write_csv
from diski9.screener.engine import MatchStore

OUT = Path("docs/research/form_windows")
COMPS = (39, 40, 288, 289)
SEASONS = (2024, 2025, 2026)
LEAGUE = {39: "EPL", 40: "Championship", 288: "PSL", 289: "PSL 1st Div"}
FIRST_TEST = datetime(2025, 8, 1, tzinfo=UTC)
REF = "blend50"
WINDOW = {"venue": 5, "overall5": 5, "blend50": 5, "overall7": 7, "overall8": 8, "overall10": 10}


def oos(rows):
    folds = monthly_folds(FIRST_TEST, max(r.kickoff for r in rows))
    feats = {}
    for a in APPROACHES:
        feats[f"{a}:diff"] = lambda r, a=a: [r.diff(a)]
        feats[f"{a}:rel"] = lambda r, a=a: list(r.rel(a))
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


def evaluate(test, preds, mask=None, kind="diff"):
    idx = np.arange(len(test)) if mask is None else np.flatnonzero(mask)
    y = [test[i].outcome for i in idx]
    wk = [iso_week(test[i].kickoff) for i in idx]
    ll = {a: log_loss_multiclass(preds[f"{a}:{kind}"][idx], y) for a in APPROACHES}
    out = {"n": len(idx)}
    for a in APPROACHES:
        out[a] = {
            "log_loss": round(float(ll[a].mean()), 4),
            "brier": round(float(brier_multiclass(preds[f"{a}:{kind}"][idx], y).mean()), 4),
        }
        if a != REF:
            out[a]["minus_blend50"] = paired_bootstrap(ll[a] - ll[REF], wk)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with make_engine().connect() as c:
        store = MatchStore(c)
    rows, skipped = build_window_rows(store, COMPS, SEASONS)
    summary: dict = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "fixtures": len(rows),
        "excluded": skipped,
        "by_league": dict(Counter(LEAGUE[r.competition_id] for r in rows)),
        "outcomes": dict(Counter("HDA"[r.outcome] for r in rows)),
        "incomplete_window_share": {
            a: round(sum(r.min_window[a] < WINDOW[a] for r in rows) / len(rows), 3)
            for a in APPROACHES
        },
    }
    # correlations between approaches (home-team scores)
    m = np.array([[r.values[a][0] for a in APPROACHES] for r in rows])
    summary["corr_home_scores"] = {
        a: {b: round(float(x), 3) for b, x in zip(APPROACHES, row, strict=True)}
        for a, row in zip(APPROACHES, np.corrcoef(m.T), strict=True)
    }

    # ranking / discrimination (full sample, no fitting)
    y_home = [int(r.outcome == 0) for r in rows]
    y_away = [int(r.outcome == 2) for r in rows]
    disc = {}
    for a in APPROACHES:
        rh = [r.rel(a)[0] for r in rows]
        ra = [r.rel(a)[1] for r in rows]
        hw_up = [r.outcome == 0 for r, x in zip(rows, rh, strict=True) if x > 0]
        hw_dn = [r.outcome == 0 for r, x in zip(rows, rh, strict=True) if x < 0]
        aw_up = [r.outcome == 2 for r, x in zip(rows, ra, strict=True) if x > 0]
        aw_dn = [r.outcome == 2 for r, x in zip(rows, ra, strict=True) if x < 0]
        disc[a] = {
            "auc_home_win_diff": round(auc([r.diff(a) for r in rows], y_home), 3),
            "auc_away_win_neg_diff": round(auc([-r.diff(a) for r in rows], y_away), 3),
            "auc_home_win_rel_home": round(auc(rh, y_home), 3),
            "auc_away_win_rel_away": round(auc(ra, y_away), 3),
            "home_win_gap_above_minus_below": round(np.mean(hw_up) - np.mean(hw_dn), 3),
            "away_win_gap_above_minus_below": round(np.mean(aw_up) - np.mean(aw_dn), 3),
        }
    summary["discrimination_full_sample"] = disc

    # out-of-sample
    test, preds = oos(rows)
    summary["oos"] = {
        "test_fixtures": len(test),
        "period": [test[0].kickoff.date().isoformat(), test[-1].kickoff.date().isoformat()],
        "form_difference": evaluate(test, preds, kind="diff"),
        "benchmark_relative": evaluate(test, preds, kind="rel"),
    }
    # subsets
    dis = np.array([r.disagree_home or r.disagree_away for r in test])
    limited = np.array([min(r.min_window["venue"], r.min_window["overall5"]) < 5 for r in test])
    short10 = np.array([r.min_window["overall10"] < 10 for r in test])
    summary["oos_subsets"] = {
        "venue_overall_disagree": evaluate(test, preds, dis),
        "venue_overall_agree": evaluate(test, preds, ~dis),
        "limited_history_5": evaluate(test, preds, limited),
        "overall10_window_incomplete": evaluate(test, preds, short10),
    }
    table = []
    for comp in COMPS:
        mk = np.array([r.competition_id == comp for r in test])
        e = evaluate(test, preds, mk)
        table.append({"subset": LEAGUE[comp], **_flat(e)})
    for label, lo, hi in (
        ("2025/26", datetime(2025, 8, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)),
        ("2026/27 to date", datetime(2026, 7, 1, tzinfo=UTC), datetime(2027, 7, 1, tzinfo=UTC)),
    ):
        mk = np.array([lo <= r.kickoff < hi for r in test])
        e = evaluate(test, preds, mk)
        table.append({"subset": label, **_flat(e)})
    write_csv(OUT / "oos_by_league_and_season.csv", table)
    summary["oos_by_league_and_season"] = table
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "corr_home_scores"}, indent=1, default=str
        )
    )


def _flat(e):
    out = {"n": e["n"]}
    for a in APPROACHES:
        out[a] = e[a]["log_loss"]
    o8 = e["overall8"]["minus_blend50"]
    out["overall8_minus_blend50"] = o8["mean"]
    out["overall8_minus_blend50_ci"] = o8["ci95"]
    return out


if __name__ == "__main__":
    main()
