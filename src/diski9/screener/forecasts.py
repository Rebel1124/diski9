"""Engine 3.0: official pre-kickoff forecast snapshots and calibration monitoring.

Snapshot policy
---------------
* A snapshot records the Goal Model baseline exactly as published: estimated
  goals, all market probabilities, model version and parameters, data cutoff and
  the league baseline at the same cutoff.
* Recorded only by a *live* refresh (calculation time = now, not a historical
  ``--as-of`` replay), only before kickoff and only when the model is available.
* A new row is written only when the forecast differs from that fixture's latest
  snapshot for the same model version (e.g. after other results changed the
  league averages), so repeated refreshes add no duplicates.
* Rows are never updated or deleted (SQLite triggers enforce this).
* **Official forecast** for performance reporting: the latest snapshot created
  strictly before the fixture's actual kickoff (``fixtures.kickoff_utc`` at
  evaluation time, so a postponed match uses the last forecast before it was
  really played). User adjustments in The Match Lab are never stored.

Monitoring
----------
Settled fixtures only: final, statistically eligible (cancelled, postponed,
abandoned, awarded and play-off fixtures are excluded) and with an official
snapshot. Metrics are grouped by competition, market, calendar month of kickoff
and model version and compared with the league baseline stored in the same
snapshot, so nothing known after kickoff is used. Parameters are never changed
automatically.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, select

from diski9.db.schema import fixtures, forecast_snapshots

from . import goal_model as gm

PRELIMINARY_BELOW = 100  # settled fixtures per group below which results are preliminary
EPS = 1e-12


def forecast_hash(g: dict) -> str:
    body = {
        "v": g["model"]["goal_model_version"],
        "p": g["params_hash"],
        "lh": round(g["lambda_home"], 12),
        "la": round(g["lambda_away"], 12),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def record(
    conn: Connection, fixture: Any, result: dict, now: datetime, live: bool, engine_version: str
) -> str:
    """Store the official forecast for ``fixture`` if allowed and new.
    Returns 'recorded', 'unchanged' or the reason it was not recorded."""
    g = result.get("goal_model") or {}
    if not live:
        return "not_live"
    if not g.get("available"):
        return "unavailable"
    if fixture.kickoff_utc <= now or fixture.status_short not in ("NS", "TBD"):
        return "kicked_off"
    h = forecast_hash(g)
    latest = conn.execute(
        select(forecast_snapshots.c.forecast_hash)
        .where(
            forecast_snapshots.c.fixture_id == fixture.id,
            forecast_snapshots.c.goal_model_version == gm.GOAL_MODEL_VERSION,
        )
        .order_by(forecast_snapshots.c.created_at.desc(), forecast_snapshots.c.id.desc())
        .limit(1)
    ).scalar()
    if latest == h:
        return "unchanged"
    p = g["probabilities"]
    conn.execute(
        forecast_snapshots.insert().values(
            fixture_id=fixture.id,
            competition_id=fixture.competition_id,
            season=fixture.season,
            kickoff_utc=fixture.kickoff_utc,
            created_at=now,
            data_cutoff=datetime.fromisoformat(result["cutoff"]),
            engine_version=engine_version,
            goal_model_version=gm.GOAL_MODEL_VERSION,
            params_hash=g["params_hash"],
            params_json=json.dumps(asdict(gm.PARAMS), sort_keys=True),
            lambda_home=g["lambda_home"],
            lambda_away=g["lambda_away"],
            p_home=p["home"],
            p_draw=p["draw"],
            p_away=p["away"],
            p_btts_yes=p["btts_yes"],
            p_over=p["over"],
            baseline_json=json.dumps(g.get("league_baseline")),
            forecast_hash=h,
        )
    )
    return "recorded"


def official_forecasts(conn: Connection) -> list[dict]:
    """One official forecast per settled fixture and model version: the latest
    snapshot created before the actual kickoff, joined to the 90-minute result."""
    rows = conn.execute(
        select(
            forecast_snapshots,
            fixtures.c.kickoff_utc.label("actual_kickoff"),
            fixtures.c.ft_home,
            fixtures.c.ft_away,
        )
        .join(fixtures, fixtures.c.id == forecast_snapshots.c.fixture_id)
        .where(
            fixtures.c.is_final.is_(True),
            fixtures.c.stats_exclusion_reason.is_(None),
            fixtures.c.ft_home.is_not(None),
        )
        .order_by(forecast_snapshots.c.created_at, forecast_snapshots.c.id)
    ).all()
    best: dict[tuple[int, str], dict] = {}
    for r in rows:
        if r.created_at >= r.actual_kickoff:
            continue  # never evaluate anything recorded at or after kickoff
        best[(r.fixture_id, r.goal_model_version)] = dict(r._mapping)  # later rows win
    return list(best.values())


def _outcome_probs(f: dict) -> dict[str, list[float]]:
    return {
        "1X2": [f["p_home"], f["p_draw"], f["p_away"]],
        "BTTS": [f["p_btts_yes"], 1 - f["p_btts_yes"]],
        "OU25": [f["p_over"], 1 - f["p_over"]],
    }


def _baseline_probs(b: dict | None) -> dict[str, list[float]] | None:
    if not b:
        return None
    return {
        "1X2": [b["home"], b["draw"], b["away"]],
        "BTTS": [b["btts_yes"], 1 - b["btts_yes"]],
        "OU25": [b["over"], 1 - b["over"]],
    }


def _observed(hg: int, ag: int) -> dict[str, int]:
    return {
        "1X2": 0 if hg > ag else 1 if hg == ag else 2,
        "BTTS": 0 if (hg > 0 and ag > 0) else 1,
        "OU25": 0 if hg + ag >= 3 else 1,
    }


def _scores(probs: list[float], y: int) -> tuple[float, float]:
    ll = -math.log(min(max(probs[y], EPS), 1.0))
    brier = sum((p - (1.0 if i == y else 0.0)) ** 2 for i, p in enumerate(probs))
    return ll, brier


def report(conn: Connection, now: datetime) -> dict:
    """Monthly monitoring summary (never changes any parameter)."""
    groups: dict[tuple, dict] = defaultdict(
        lambda: {
            "n": 0,
            "ll": 0.0,
            "brier": 0.0,
            "b_n": 0,
            "b_ll": 0.0,
            "b_brier": 0.0,
            "bins": defaultdict(lambda: [0, 0.0, 0]),
        }
    )
    forecasts = official_forecasts(conn)
    for f in forecasts:
        obs = _observed(f["ft_home"], f["ft_away"])
        model = _outcome_probs(f)
        base = _baseline_probs(json.loads(f["baseline_json"]) if f["baseline_json"] else None)
        month = f["actual_kickoff"].strftime("%Y-%m")
        for market in ("1X2", "BTTS", "OU25"):
            for key in (
                (f["competition_id"], market, month, f["goal_model_version"]),
                ("all", market, "all", f["goal_model_version"]),
            ):
                gr = groups[key]
                ll, br = _scores(model[market], obs[market])
                gr["n"] += 1
                gr["ll"] += ll
                gr["brier"] += br
                if base:
                    bll, bbr = _scores(base[market], obs[market])
                    gr["b_n"] += 1
                    gr["b_ll"] += bll
                    gr["b_brier"] += bbr
                p = model[market][0]  # first outcome: home win / BTTS Yes / Over 2.5
                b = gr["bins"][min(int(p * 10), 9)]
                b[0] += 1
                b[1] += p
                b[2] += int(obs[market] == 0)
    out = []
    for (comp, market, month, version), g in sorted(groups.items(), key=lambda kv: str(kv[0])):
        row = {
            "competition_id": comp,
            "market": market,
            "month": month,
            "goal_model_version": version,
            "settled_fixtures": g["n"],
            "log_loss": round(g["ll"] / g["n"], 4),
            "brier": round(g["brier"] / g["n"], 4),
            "baseline_log_loss": round(g["b_ll"] / g["b_n"], 4) if g["b_n"] else None,
            "baseline_brier": round(g["b_brier"] / g["b_n"], 4) if g["b_n"] else None,
            "preliminary": g["n"] < PRELIMINARY_BELOW,
            "calibration": [
                {
                    "bin": f"{k / 10:.1f}-{(k + 1) / 10:.1f}",
                    "n": n,
                    "mean_forecast": round(s / n, 4),
                    "observed": round(hits / n, 4),
                }
                for k, (n, s, hits) in sorted(g["bins"].items())
            ],
        }
        if row["baseline_log_loss"] is not None:
            row["log_loss_vs_baseline"] = round(row["log_loss"] - row["baseline_log_loss"], 4)
        out.append(row)
    return {
        "generated_at": now.isoformat(),
        "official_forecasts": len(forecasts),
        "policy": "official = latest snapshot recorded before the actual kickoff; settled, "
        "eligible fixtures only; groups with fewer than "
        f"{PRELIMINARY_BELOW} fixtures are preliminary; parameters are never changed "
        "automatically (annual review only)",
        "groups": out,
    }
