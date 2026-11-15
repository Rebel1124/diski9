"""Point-in-time historical sanity check (calculation integrity, not a backtest).

For each historical fixture, the screener result is computed as it would have
been at kickoff, then checked:

1. ``no_future_matches``: every match used (windows, benchmark, head-to-head)
   kicked off before the fixture.
2. ``independent_reconstruction``: recomputing from a store that physically
   contains only matches before kickoff gives an identical result hash, so
   later results cannot have influenced it.
3. ``independent_form_check``: the home team's venue Form Score is re-derived
   with a separate SQL query and separate arithmetic.
4. ``bounds``: Form Scores within [0, 5]; rates and combined indicators in [0, 1].
5. ``deterministic``: computing twice gives the same hash.
6. ``benchmark_count``: the benchmark's current-season sample equals the number
   of eligible, non-neutral league matches before kickoff (SQL count).

No bookmaker odds are used.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, func, select

from diski9.db.schema import fixtures

from .engine import MatchStore, ScreenerConfig, compute_fixture


def _sql_home_form(conn: Connection, team_id: int, before: datetime, n: int = 5) -> float | None:
    rows = conn.execute(
        select(fixtures.c.ft_home, fixtures.c.ft_away)
        .where(
            fixtures.c.home_team_id == team_id,
            fixtures.c.kickoff_utc < before,
            fixtures.c.stats_exclusion_reason.is_(None),
            fixtures.c.venue_classification != "neutral",
        )
        .order_by(fixtures.c.kickoff_utc.desc(), fixtures.c.id.desc())
        .limit(n)
    ).all()
    if not rows:
        return None
    pts = sum(3 if h > a else 1 if h == a else 0 for h, a in rows)
    gd = sum(h - a for h, a in rows) / len(rows)
    return 1.0 + pts / len(rows) + 0.5 * max(-2.0, min(2.0, gd))  # independent, 0-5 scale


def _sql_league_count(conn: Connection, comp: int, season: int, before: datetime) -> int:
    return conn.execute(
        select(func.count()).where(
            fixtures.c.competition_id == comp,
            fixtures.c.season == season,
            fixtures.c.kickoff_utc < before,
            fixtures.c.stats_exclusion_reason.is_(None),
            fixtures.c.venue_classification != "neutral",
        )
    ).scalar()


def check_fixture(conn: Connection, store: MatchStore, fx: Any, config: ScreenerConfig) -> dict:
    kickoff = fx.kickoff_utc
    r = compute_fixture(store, fx, kickoff, "venue", config)
    failures: list[str] = []

    dates = []
    for side in ("home", "away"):
        for key in ("form", "goals"):
            dates += [m["date"] for m in r["teams"][side][key]["matches"]]
    dates += [m["date"] for m in r["head_to_head"]]
    if any(d > kickoff.date().isoformat() for d in dates):
        failures.append("no_future_matches")
    used_ids = {
        m["fixture_id"]
        for side in ("home", "away")
        for key in ("form", "goals")
        for m in r["teams"][side][key]["matches"]
    } | {m["fixture_id"] for m in r["head_to_head"]}
    if fx.id in used_ids:
        failures.append("no_future_matches")  # the fixture itself must never be used

    truncated = compute_fixture(store.truncated(kickoff), fx, kickoff, "venue", config)
    if truncated["inputs_hash"] != r["inputs_hash"]:
        failures.append("independent_reconstruction")

    sql_form = _sql_home_form(conn, fx.home_team_id, kickoff, config.form_window)
    engine_form = r["match_result"]["home_form"]
    if (sql_form is None) != (engine_form is None) or (
        sql_form is not None and abs(sql_form - engine_form) > 1e-9
    ):
        failures.append("independent_form_check")

    for side in ("home", "away"):
        f = r["teams"][side]["form"]["score"]
        if f is not None and not 0 <= f <= 5:
            failures.append("bounds")
        for key in ("btts", "over_2_5"):
            rate = r["teams"][side]["goals"][key]
            if rate and not 0 <= rate["rate"] <= 1:
                failures.append("bounds")
    for v in (r["btts"]["yes_indicator"], r["over_under_2_5"]["over_indicator"]):
        if v is not None and not 0 <= v <= 1:
            failures.append("bounds")

    if compute_fixture(store, fx, kickoff, "venue", config)["inputs_hash"] != r["inputs_hash"]:
        failures.append("deterministic")

    bench = r["match_result"]["benchmark"]
    if bench and bench["current_season_matches"] != _sql_league_count(
        conn, fx.competition_id, fx.season, kickoff
    ):
        failures.append("benchmark_count")

    return {
        "fixture_id": fx.id,
        "failures": sorted(set(failures)),
        "benchmark_source": bench["source"] if bench else None,
        "limited_form": r["limited_data"]["form"],
        "limited_goals": r["limited_data"]["goals"],
        "has_form_difference": r["match_result"]["venue_adjusted_difference"] is not None,
    }


def run(
    conn: Connection,
    competitions: list[int],
    seasons: list[int],
    config: ScreenerConfig | None = None,
    limit: int | None = None,
) -> dict:
    config = config or ScreenerConfig()
    store = MatchStore(conn)
    q = (
        select(fixtures)
        .where(
            fixtures.c.competition_id.in_(competitions),
            fixtures.c.season.in_(seasons),
            fixtures.c.is_final.is_(True),
            fixtures.c.round_type == "regular",
        )
        .order_by(fixtures.c.kickoff_utc)
    )
    rows = conn.execute(q.limit(limit) if limit else q).all()
    results = [check_fixture(conn, store, fx, config) for fx in rows]
    failures = Counter(f for r in results for f in r["failures"])
    by_comp: dict[str, Any] = {}
    for fx, res in zip(rows, results, strict=True):
        key = f"{fx.competition_id}/{fx.season}"
        c = by_comp.setdefault(key, Counter())
        c["fixtures"] += 1
        c["limited_form"] += res["limited_form"]
        c["limited_goals"] += res["limited_goals"]
        c["no_form_difference"] += not res["has_form_difference"]
        c[f"benchmark_{res['benchmark_source']}"] += 1
    return {
        "fixtures_checked": len(results),
        "checks": [
            "no_future_matches",
            "independent_reconstruction",
            "independent_form_check",
            "bounds",
            "deterministic",
            "benchmark_count",
        ],
        "failures": dict(failures),
        "failed_fixtures": [r for r in results if r["failures"]][:50],
        "by_competition_season": {k: dict(v) for k, v in by_comp.items()},
    }


__all__ = ["check_fixture", "run"]
