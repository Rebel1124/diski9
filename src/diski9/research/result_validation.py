"""Research only (Milestone 5.2): validate market-fitted goal models against results.

Rerunnable pipeline. For every completed fixture with saved odds:

1. take the latest odds snapshot retrieved strictly before kickoff
2. use only markets that were *fresh* at that snapshot (one coherent consensus;
   never quotes from different collection times, never post-kickoff prices)
3. fit each model / market configuration to the margin-adjusted probabilities
4. score the fitted probabilities against the actual result, alongside the
   market-implied probabilities themselves (the baseline)

Excluded: fixtures not final, awarded/walkover/cancelled/abandoned results
(``stats_exclusion_reason`` set), and play-off rounds. Each fixture is used once.

A goal expectation is an average, not a forecast of the exact score: individual
fixture errors are expected to be large; only aggregate calibration is evaluated.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import Connection, func, select

from diski9.db.schema import fixtures, odds_fixture_observations
from diski9.odds.display import display_consensus
from diski9.research.evaluation import (
    brier_binary,
    brier_multiclass,
    calibration_table,
    log_loss_binary,
    log_loss_multiclass,
)
from diski9.research.goal_models import Spec, fit_market, probabilities
from diski9.research.market_implied_xg import from_display

# Evidence needed before any production recommendation (see the report):
MIN_FIXTURES_CALIBRATION = 150  # coarse 3-bin calibration with ~ +/-8 pp intervals
MIN_FIXTURES_COMPARISON = 400  # paired model-vs-market log-loss comparisons
MIN_LEAGUES = 2


@dataclass
class Record:
    fixture_id: int
    competition_id: int
    season: int
    kickoff: datetime
    snapshot_at: datetime
    home_goals: int
    away_goals: int
    market: dict[str, tuple[float, ...]]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def outcome(self) -> int:
        h, a = self.home_goals, self.away_goals
        return 0 if h > a else 1 if h == a else 2

    @property
    def hours_before_kickoff(self) -> float:
        return (self.kickoff - self.snapshot_at).total_seconds() / 3600


def collect_records(conn: Connection, competitions: tuple[int, ...] | None = None) -> list[Record]:
    """One record per settled fixture: the latest fresh pre-kickoff snapshot."""
    last = (
        select(
            odds_fixture_observations.c.fixture_id,
            func.max(odds_fixture_observations.c.retrieved_at).label("snapshot_t"),
        )
        .join(fixtures, fixtures.c.id == odds_fixture_observations.c.fixture_id)
        .where(odds_fixture_observations.c.retrieved_at < fixtures.c.kickoff_utc)
        .group_by(odds_fixture_observations.c.fixture_id)
        .subquery()
    )
    q = (
        select(fixtures, last.c.snapshot_t)
        .join(last, last.c.fixture_id == fixtures.c.id)
        .where(
            fixtures.c.is_final.is_(True),
            fixtures.c.stats_exclusion_reason.is_(None),
            fixtures.c.ft_home.is_not(None),
        )
        .order_by(fixtures.c.kickoff_utc, fixtures.c.id)
    )
    if competitions:
        q = q.where(fixtures.c.competition_id.in_(competitions))
    out = []
    for r in conn.execute(q):
        t = (
            r.snapshot_t
            if isinstance(r.snapshot_t, datetime)
            else datetime.fromisoformat(r.snapshot_t)
        )
        if t >= r.kickoff_utc:  # defensive: never use odds at or after kickoff
            continue
        inputs = from_display(display_consensus(conn, r.id, t), r.id)
        market = inputs.available()
        if not market:
            continue
        out.append(
            Record(
                r.id,
                r.competition_id,
                r.season,
                r.kickoff_utc,
                t,
                r.ft_home,
                r.ft_away,
                market,
                inputs.metadata,
            )
        )
    return out


CONFIGS = (("1x2",), ("1x2", "ou25"), ("1x2", "btts"), ("1x2", "btts", "ou25"))


def evaluate(records: list[Record], specs: tuple[Spec, ...], configs=CONFIGS) -> dict[str, Any]:
    """Score fitted models and the market itself against actual results."""
    n = len(records)
    out: dict[str, Any] = {
        "fixtures": n,
        "leagues": sorted({r.competition_id for r in records}),
        "period": [
            min(r.kickoff for r in records).isoformat(),
            max(r.kickoff for r in records).isoformat(),
        ]
        if records
        else None,
        "sufficient_for_calibration": n >= MIN_FIXTURES_CALIBRATION,
        "sufficient_for_comparison": n >= MIN_FIXTURES_COMPARISON
        and len({r.competition_id for r in records}) >= MIN_LEAGUES,
        "minimum_required": {
            "calibration": MIN_FIXTURES_CALIBRATION,
            "comparison": MIN_FIXTURES_COMPARISON,
            "leagues": MIN_LEAGUES,
        },
        "results": {},
    }
    if not records:
        out["note"] = "no settled fixture has a saved pre-kickoff odds snapshot yet"
        return out
    for config in configs:
        recs = [r for r in records if all(m in r.market for m in config)]
        if not recs:
            continue
        y1 = [r.outcome for r in recs]
        yb = [int(r.home_goals > 0 and r.away_goals > 0) for r in recs]
        yo = [int(r.home_goals + r.away_goals >= 3) for r in recs]
        res: dict[str, Any] = {"fixtures": len(recs)}
        market_1x2 = np.array([r.market["1x2"] for r in recs])
        res["market_baseline"] = {
            "log_loss_1x2": round(float(log_loss_multiclass(market_1x2, y1).mean()), 4),
            "brier_1x2": round(float(brier_multiclass(market_1x2, y1).mean()), 4),
        }
        for m, y in (("btts", yb), ("ou25", yo)):
            have = [i for i, r in enumerate(recs) if m in r.market]
            if have:
                p = [recs[i].market[m][0] for i in have]
                yy = [y[i] for i in have]
                res["market_baseline"][f"brier_{m}"] = round(float(brier_binary(p, yy).mean()), 4)
                res["market_baseline"][f"log_loss_{m}"] = round(
                    float(log_loss_binary(p, yy).mean()), 4
                )
        for spec in specs:
            fits = [fit_market({m: r.market[m] for m in config}, spec) for r in recs]
            ok = [i for i, f in enumerate(fits) if f.usable]
            s: dict[str, Any] = {
                "usable_fits": len(ok),
                "status": dict(_count(f.status for f in fits)),
            }
            if ok:
                probs = [
                    probabilities(fits[i].lambda_home, fits[i].lambda_away, fits[i].rho or 0.0)
                    for i in ok
                ]
                P = np.array([p["1x2"] for p in probs])
                yy = [y1[i] for i in ok]
                s["log_loss_1x2"] = round(float(log_loss_multiclass(P, yy).mean()), 4)
                s["brier_1x2"] = round(float(brier_multiclass(P, yy).mean()), 4)
                s["market_log_loss_1x2_same_fixtures"] = round(
                    float(log_loss_multiclass(market_1x2[ok], yy).mean()), 4
                )
                for m, y in (("btts", yb), ("ou25", yo)):
                    pm = [p[m][0] for p in probs]
                    ym = [y[i] for i in ok]
                    s[f"brier_{m}"] = round(float(brier_binary(pm, ym).mean()), 4)
                    s[f"calibration_{m}"] = calibration_table(pm, ym, [0, 0.4, 0.6, 1.0])
                lam_h = np.array([fits[i].lambda_home for i in ok])
                lam_a = np.array([fits[i].lambda_away for i in ok])
                hg = np.array([recs[i].home_goals for i in ok])
                ag = np.array([recs[i].away_goals for i in ok])
                s["goals"] = {
                    "mean_predicted_home": round(float(lam_h.mean()), 3),
                    "mean_observed_home": round(float(hg.mean()), 3),
                    "mean_predicted_away": round(float(lam_a.mean()), 3),
                    "mean_observed_away": round(float(ag.mean()), 3),
                    "mean_predicted_total": round(float((lam_h + lam_a).mean()), 3),
                    "mean_observed_total": round(float((hg + ag).mean()), 3),
                }
                dist = np.zeros(8)
                for p in probs:
                    tg = p["total_goals"]
                    dist[: min(7, len(tg))] += tg[:7]
                    dist[7] += tg[7:].sum()
                obs = np.bincount(np.minimum(hg + ag, 7), minlength=8)
                s["total_goals_distribution"] = {
                    "goals": [*range(7), "7+"],
                    "predicted": [round(float(x / len(ok)), 4) for x in dist],
                    "observed": [round(float(x / len(ok)), 4) for x in obs],
                }
            res[spec.label] = s
        out["results"]["+".join(config)] = res
    return out


def _count(items):
    c: dict[str, int] = defaultdict(int)
    for i in items:
        c[i] += 1
    return c
