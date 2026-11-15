"""Refreshable cache of screener results (``screener_results``).

* A result is a pure function of (fixture, cutoff, stored data, engine version).
* Refreshing recomputes; if the content hash matches the active row only
  ``verified_at`` is updated, otherwise the active row is superseded and a new
  row inserted. Rows are never deleted, so the cache state at any past moment
  can be reconstructed (``calculated_at <= t < superseded_at``).
* Live consensus odds are deliberately *not* cached here; they change far more
  often and are computed at display time from the odds tables.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, and_, or_, select, update

from diski9.db.schema import fixtures, screener_results

from .engine import ENGINE_VERSION, Basis, MatchStore, ScreenerConfig, compute_fixture


def _row_values(result: dict) -> dict[str, Any]:
    mr = result["match_result"]
    bench = mr["benchmark"] or {}
    return {
        "home_form": mr["home_form"],
        "away_form": mr["away_form"],
        "raw_difference": mr["raw_difference"],
        "venue_adjusted_difference": mr["venue_adjusted_difference"],
        "benchmark_season": bench.get("season"),
        "benchmark_source": bench.get("source"),
        "benchmark_matches": bench.get("matches"),
        "btts_yes_indicator": result["btts"]["yes_indicator"],
        "over25_indicator": result["over_under_2_5"]["over_indicator"],
        "limited_data": bool(result["limited_data"]["form"] or result["limited_data"]["goals"]),
    }


def refresh(
    conn: Connection,
    fixture_ids: Iterable[int],
    as_of: datetime,
    now: datetime,
    bases: tuple[Basis, ...] = ("venue", "overall"),
    config: ScreenerConfig | None = None,
    store: MatchStore | None = None,
) -> dict[str, int]:
    store = store or MatchStore(conn)
    counts = {"inserted": 0, "unchanged": 0, "superseded": 0}
    counts["retired_old_version"] = retire_other_versions(conn, now)
    rows = conn.execute(select(fixtures).where(fixtures.c.id.in_(list(fixture_ids)))).all()
    for fx in rows:
        for basis in bases:
            result = compute_fixture(store, fx, as_of, basis, config)
            active = conn.execute(
                select(screener_results.c.id, screener_results.c.inputs_hash).where(
                    screener_results.c.fixture_id == fx.id,
                    screener_results.c.basis == basis,
                    screener_results.c.engine_version == ENGINE_VERSION,
                    screener_results.c.superseded_at.is_(None),
                )
            ).first()
            if active is not None and active.inputs_hash == result["inputs_hash"]:
                conn.execute(
                    update(screener_results)
                    .where(screener_results.c.id == active.id)
                    .values(verified_at=now)
                )
                counts["unchanged"] += 1
                continue
            if active is not None:
                conn.execute(
                    update(screener_results)
                    .where(screener_results.c.id == active.id)
                    .values(superseded_at=now)
                )
                counts["superseded"] += 1
            conn.execute(
                screener_results.insert().values(
                    fixture_id=fx.id,
                    basis=basis,
                    engine_version=ENGINE_VERSION,
                    as_of=as_of,
                    cutoff=datetime.fromisoformat(result["cutoff"]),
                    calculated_at=now,
                    verified_at=now,
                    inputs_hash=result["inputs_hash"],
                    payload=json.dumps(result, default=str),
                    **_row_values(result),
                )
            )
            counts["inserted"] += 1
    return counts


def retire_other_versions(conn: Connection, now: datetime) -> int:
    """Supersede every active row computed by a different engine version, so
    results from an older calculation (e.g. the previous Form Score scale) are
    never served alongside current ones."""
    return conn.execute(
        update(screener_results)
        .where(
            screener_results.c.superseded_at.is_(None),
            screener_results.c.engine_version != ENGINE_VERSION,
        )
        .values(superseded_at=now)
    ).rowcount


def invalidate(conn: Connection, now: datetime, fixture_ids: Iterable[int] | None = None) -> int:
    """Supersede active rows (all, or for given fixtures) so the next refresh recomputes."""
    stmt = update(screener_results).where(screener_results.c.superseded_at.is_(None))
    if fixture_ids is not None:
        stmt = stmt.where(screener_results.c.fixture_id.in_(list(fixture_ids)))
    return conn.execute(stmt.values(superseded_at=now)).rowcount


def cached(
    conn: Connection, basis: Basis = "venue", at: datetime | None = None
) -> list[dict[str, Any]]:
    """Cached results for the current engine version. With ``at``, the rows
    that were current at that moment (point-in-time view of the cache)."""
    q = select(screener_results).where(
        screener_results.c.basis == basis, screener_results.c.engine_version == ENGINE_VERSION
    )
    if at is None:
        q = q.where(screener_results.c.superseded_at.is_(None))
    else:
        q = q.where(
            and_(
                screener_results.c.calculated_at <= at,
                or_(
                    screener_results.c.superseded_at.is_(None),
                    screener_results.c.superseded_at > at,
                ),
            )
        )
    return [json.loads(r.payload) for r in conn.execute(q)]


def upcoming_fixture_ids(
    conn: Connection, competition_ids: Iterable[int], start: datetime, end: datetime
) -> list[int]:
    q = select(fixtures.c.id).where(
        fixtures.c.competition_id.in_(list(competition_ids)),
        fixtures.c.kickoff_utc >= start,
        fixtures.c.kickoff_utc < end,
        fixtures.c.status_short.in_(["NS", "TBD"]),
    )
    return [r.id for r in conn.execute(q.order_by(fixtures.c.kickoff_utc))]
