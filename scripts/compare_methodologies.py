"""Compare fixture rankings: previous methodology (engine 1.2.x) vs Milestone 5 (2.0.0).

Uses the screener cache: the latest superseded 1.2.x rows (kept for audit) and
the current 2.0.0 rows for the same upcoming fixtures, venue basis.

Run: uv run python scripts/compare_methodologies.py [--out docs/methodology_comparison.json]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from statistics import mean

from sqlalchemy import select

from diski9.db import make_engine
from diski9.db.schema import screener_results
from diski9.screener.engine import ENGINE_VERSION


def ranks(values: dict[int, float]) -> dict[int, float]:
    order = sorted(values, key=lambda k: values[k])
    out, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in order[i : j + 1]:
            out[k] = (i + j) / 2 + 1  # average rank for ties
        i = j + 1
    return out


def spearman(a: dict[int, float], b: dict[int, float]) -> float | None:
    keys = [k for k in a if k in b and a[k] is not None and b[k] is not None]
    if len(keys) < 3:
        return None
    ra, rb = ranks({k: a[k] for k in keys}), ranks({k: b[k] for k in keys})
    ma, mb = mean(ra.values()), mean(rb.values())
    cov = sum((ra[k] - ma) * (rb[k] - mb) for k in keys)
    va = sum((ra[k] - ma) ** 2 for k in keys) ** 0.5
    vb = sum((rb[k] - mb) ** 2 for k in keys) ** 0.5
    return round(cov / (va * vb), 3) if va and vb else None


def top(values: dict[int, float], n: int = 5, reverse: bool = True) -> list[int]:
    keys = [k for k, v in values.items() if v is not None]
    return sorted(keys, key=lambda k: (-values[k] if reverse else values[k], k))[:n]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/methodology_comparison.json")
    args = ap.parse_args()
    with make_engine().connect() as c:
        new_rows = {
            r.fixture_id: json.loads(r.payload)
            for r in c.execute(
                select(screener_results).where(
                    screener_results.c.engine_version == ENGINE_VERSION,
                    screener_results.c.superseded_at.is_(None),
                    screener_results.c.basis == "venue",
                )
            )
        }
        old_rows: dict[int, dict] = {}
        for r in c.execute(
            select(screener_results)
            .where(
                screener_results.c.engine_version.like("1.2.%"), screener_results.c.basis == "venue"
            )
            .order_by(screener_results.c.calculated_at)
        ):
            if r.fixture_id in new_rows:
                old_rows[r.fixture_id] = json.loads(r.payload)  # latest wins
    common = sorted(set(old_rows) & set(new_rows))
    names = {
        f: f"{new_rows[f]['fixture']['home']} v {new_rows[f]['fixture']['away']}" for f in common
    }
    old_vad = {f: old_rows[f]["match_result"]["venue_adjusted_difference"] for f in common}
    old_raw = {f: old_rows[f]["match_result"]["raw_difference"] for f in common}
    new_diff = {f: new_rows[f]["match_result"]["form_difference"] for f in common}
    old_btts = {f: old_rows[f]["btts"]["yes_indicator"] for f in common}
    new_btts = {f: new_rows[f]["btts"]["yes_indicator"] for f in common}
    old_over = {f: old_rows[f]["over_under_2_5"]["over_indicator"] for f in common}
    new_over = {f: new_rows[f]["over_under_2_5"]["over_indicator"] for f in common}

    def shift(a, b):
        ra = {k: i for i, k in enumerate(top(a, len(a)))}
        rb = {k: i for i, k in enumerate(top(b, len(b)))}
        keys = set(ra) & set(rb)
        return round(mean(abs(ra[k] - rb[k]) for k in keys), 2) if keys else None

    scores = [new_rows[f]["teams"][s]["form"]["score"] for f in common for s in ("home", "away")]
    scores = [x for x in scores if x is not None]
    report = {
        "fixtures_compared": len(common),
        "match_result": {
            "spearman_old_venue_adjusted_vs_new_form_difference": spearman(old_vad, new_diff),
            "spearman_old_raw_vs_new_form_difference": spearman(old_raw, new_diff),
            "top5_home_advantage_old": [names[f] for f in top(old_vad)],
            "top5_home_advantage_new": [names[f] for f in top(new_diff)],
            "top5_home_overlap": len(set(top(old_vad)) & set(top(new_diff))),
            "top5_away_advantage_old": [names[f] for f in top(old_vad, reverse=False)],
            "top5_away_advantage_new": [names[f] for f in top(new_diff, reverse=False)],
            "top5_away_overlap": len(
                set(top(old_vad, reverse=False)) & set(top(new_diff, reverse=False))
            ),
            "mean_absolute_rank_shift": shift(old_vad, new_diff),
            "sign_changes": [
                names[f]
                for f in common
                if old_vad[f] is not None
                and new_diff[f] is not None
                and (old_vad[f] > 0) != (new_diff[f] > 0)
                and abs(new_diff[f]) > 1e-9
            ],
            "exact_ties_in_new_difference": sum(
                n - 1 for n in Counter(new_diff.values()).values() if n > 1
            ),
            "distinct_new_difference_values": len(set(new_diff.values())),
        },
        "form_score_distribution": {
            "team_scores": len(scores),
            "counts_by_score": dict(sorted(Counter(round(x, 2) for x in scores).items())),
            "share_at_or_below_0_77": round(sum(x <= 0.77 for x in scores) / len(scores), 3),
            "median": sorted(scores)[len(scores) // 2],
        },
        "btts": {
            "spearman_old_vs_new": spearman(old_btts, new_btts),
            "top5_yes_overlap": len(set(top(old_btts)) & set(top(new_btts))),
            "mean_absolute_change_pct_points": round(
                mean(
                    abs(old_btts[f] - new_btts[f]) * 100
                    for f in common
                    if old_btts[f] is not None and new_btts[f] is not None
                ),
                1,
            ),
            "limited_old": sum(old_rows[f]["limited_data"]["goals"] for f in common),
            "limited_new": sum(new_rows[f]["limited_data"]["goals"] for f in common),
        },
        "over_2_5": {
            "spearman_old_vs_new": spearman(old_over, new_over),
            "top5_over_overlap": len(set(top(old_over)) & set(top(new_over))),
            "mean_absolute_change_pct_points": round(
                mean(
                    abs(old_over[f] - new_over[f]) * 100
                    for f in common
                    if old_over[f] is not None and new_over[f] is not None
                ),
                1,
            ),
        },
    }
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
