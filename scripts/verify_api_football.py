"""Milestone 1: controlled, budgeted verification of API-Football coverage.

Run:  uv run python scripts/verify_api_football.py [--out docs/api_verification_summary.json]

Makes a small, capped number of requests (default budget 40) and writes a
sanitised JSON summary (no account details) describing coverage of the
initial leagues, fixture statuses, historical results and odds markets.
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from diski9.api_football import ApiFootballClient
from diski9.api_football.markets import (
    MARKET_MAP,
    Market,
    check_bet_catalogue,
    extract_quotes,
)

LEAGUES = {
    39: {"name": "English Premier League", "lower_division": 40},
    288: {"name": "South African Premiership", "lower_division": 289},
}
CURRENT_SEASON = 2026
HISTORICAL_SEASONS = (2023, 2024, 2025)
UPCOMING = {"TBD", "NS"}


def status_usage(client: ApiFootballClient) -> dict[str, Any]:
    r = client.get("status")
    return {
        "plan": r.response["subscription"]["plan"],
        "active": r.response["subscription"]["active"],
        "requests_current": r.response["requests"]["current"],
        "limit_day": r.response["requests"]["limit_day"],
    }


def season_meta(league_item: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "year": s["year"],
            "start": s["start"],
            "end": s["end"],
            "current": s["current"],
            "coverage_odds_flag": s["coverage"]["odds"],
            "coverage_events": s["coverage"]["fixtures"]["events"],
        }
        for s in league_item["seasons"]
        if s["year"] >= min(HISTORICAL_SEASONS)
    ]


def fixtures_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    finished = [f for f in items if f["fixture"]["status"]["short"] in {"FT", "AET", "PEN"}]
    return {
        "fixtures": len(items),
        "status_counts": dict(collections.Counter(f["fixture"]["status"]["short"] for f in items)),
        "round_types": dict(
            collections.Counter(f["league"]["round"].rsplit(" - ", 1)[0] for f in items)
        ),
        "teams": len(
            {f["teams"]["home"]["id"] for f in items} | {f["teams"]["away"]["id"] for f in items}
        ),
        "finished_missing_fulltime": sum(
            1 for f in finished if f["score"]["fulltime"]["home"] is None
        ),
        "finished_with_extratime": sum(
            1 for f in finished if f["score"]["extratime"]["home"] is not None
        ),
        "goals_differs_from_fulltime": sum(
            1 for f in finished if f["goals"] != f["score"]["fulltime"]
        ),
        "missing_venue_id": sum(1 for f in items if not f["fixture"]["venue"]["id"]),
        "first_date": min((f["fixture"]["date"] for f in items), default=None),
        "last_date": max((f["fixture"]["date"] for f in items), default=None),
    }


def odds_summary(items: list[dict[str, Any]], kickoff_after: datetime) -> dict[str, Any]:
    per_fixture = []
    warnings: list[str] = []
    for item in items:
        kickoff = datetime.fromisoformat(item["fixture"]["date"])
        quotes, w = extract_quotes(item)
        warnings.extend(w)
        books: dict[Market, set[int]] = collections.defaultdict(set)
        for q in quotes:
            books[q.market].add(q.bookmaker_id)
        per_fixture.append(
            {
                "fixture_id": item["fixture"]["id"],
                "kickoff": item["fixture"]["date"],
                "upcoming": kickoff > kickoff_after,
                "provider_update": item["update"],
                "bookmakers_listed": len(item["bookmakers"]),
                "complete_market_bookmakers": {m.value: len(books[m]) for m in Market},
            }
        )
    upcoming = [p for p in per_fixture if p["upcoming"]]
    agg = {}
    for m in Market:
        counts = [p["complete_market_bookmakers"][m.value] for p in upcoming]
        agg[m.value] = {
            "min": min(counts, default=0),
            "max": max(counts, default=0),
            "fixtures_with_3plus": sum(1 for c in counts if c >= 3),
        }
    return {
        "fixtures_with_odds": len(per_fixture),
        "upcoming_fixtures_with_odds": len(upcoming),
        "upcoming_market_bookmaker_counts": agg,
        "distinct_provider_update_values": sorted({p["provider_update"] for p in per_fixture}),
        "parse_warnings": warnings[:50],
        "per_fixture": per_fixture,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/api_verification_summary.json")
    parser.add_argument("--budget", type=int, default=40)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    now = datetime.now(UTC)
    summary: dict[str, Any] = {"run_at": now.isoformat(), "leagues": {}}

    with ApiFootballClient.from_settings(request_budget=args.budget) as client:
        summary["usage_before"] = status_usage(client)

        bets = client.get("odds/bets").items
        summary["odds_bets"] = {
            "total_bet_types": len(bets),
            "null_named": sum(1 for b in bets if not b.get("name")),
            "mapping_problems": check_bet_catalogue(bets),
            "used": {
                m.value: {"id": i, "name": n, "values": list(v)}
                for m, (i, n, v) in MARKET_MAP.items()
            },
        }
        books = client.get("odds/bookmakers").items
        summary["odds_bookmakers"] = books

        for league_id, info in LEAGUES.items():
            entry: dict[str, Any] = {"name": info["name"]}
            for lid in (league_id, info["lower_division"]):
                meta = client.get("leagues", {"id": lid}).items[0]
                entry.setdefault("league_meta", {})[lid] = {
                    "api_name": meta["league"]["name"],
                    "type": meta["league"]["type"],
                    "country": meta["country"]["name"],
                    "seasons": season_meta(meta),
                }
            entry["fixtures"] = {}
            upcoming_fixture = None
            for season in (*HISTORICAL_SEASONS, CURRENT_SEASON):
                items = client.get("fixtures", {"league": league_id, "season": season}).items
                entry["fixtures"][season] = fixtures_summary(items)
                if season == CURRENT_SEASON:
                    nxt = sorted(
                        (f for f in items if f["fixture"]["status"]["short"] in UPCOMING),
                        key=lambda f: f["fixture"]["timestamp"],
                    )
                    upcoming_fixture = nxt[0] if nxt else None
            lower = client.get("fixtures", {"league": info["lower_division"], "season": 2025}).items
            entry["lower_division_2025_fixtures"] = fixtures_summary(lower)

            pages = list(client.paginate("odds", {"league": league_id, "season": CURRENT_SEASON}))
            entry["odds_pages"] = [
                {
                    "page": p.paging_current,
                    "total": p.paging_total,
                    "results": p.results,
                }
                for p in pages
            ]
            entry["odds"] = odds_summary([i for p in pages for i in p.items], now)

            if upcoming_fixture:
                fid = upcoming_fixture["fixture"]["id"]
                r = client.get("odds", {"fixture": fid})
                entry["next_fixture_odds_check"] = {
                    "fixture_id": fid,
                    "kickoff": upcoming_fixture["fixture"]["date"],
                    "results": r.results,
                }
            summary["leagues"][league_id] = entry

        summary["usage_after"] = status_usage(client)
        summary["client_requests_sent"] = client.requests_made
        summary["client_quota_requests"] = client.quota_requests_made
        summary["last_rate_limit_headers"] = client.last_rate_limit.__dict__

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"Wrote {out}  (quota requests used by this run: {summary['client_quota_requests']})")


if __name__ == "__main__":
    main()
