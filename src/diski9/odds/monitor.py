"""Odds monitoring trial: capture raw odds pages, then replay and analyse them.

Capture (``diski9 monitor-odds``) needs no database: it fetches ``/odds`` for the
odds-enabled competitions and writes one gzipped JSON file per run containing
the pages exactly as received (restricted to the three Diski 9 markets), the
retrieval time of each page, rate-limit headers and any errors. A one-line
summary is appended to ``runs.jsonl``. Files are small and committed, so the
trial survives ephemeral containers.

Analysis (``diski9 analyse-odds-trial``) replays every saved run, in order,
through the same reconciliation code used by live collection, then measures
provider-timestamp behaviour, price changes, availability and coverage.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import Connection, select

from diski9.api_football import ApiFootballClient, ApiFootballError
from diski9.api_football.markets import BET_ID_TO_MARKET, extract_quotes
from diski9.db.schema import fixtures, odds_fetches, odds_fixture_observations, odds_quotes

from .collect import OddsPage, reconcile_pages

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "monitoring" / "odds_trial"
KEEP_BETS = frozenset(BET_ID_TO_MARKET)


def _slim(item: dict[str, Any]) -> dict[str, Any]:
    """Keep only the fields and markets Diski 9 uses (bets 1, 5, 8)."""
    return {
        "league": {k: item["league"].get(k) for k in ("id", "season")},
        "fixture": {k: item["fixture"].get(k) for k in ("id", "date", "timestamp")},
        "update": item.get("update"),
        "bookmakers": [
            {
                "id": b["id"],
                "name": b.get("name"),
                "bets": [bet for bet in b.get("bets") or [] if bet.get("id") in KEEP_BETS],
            }
            for b in item.get("bookmakers") or []
        ],
    }


def run_monitor(
    client: ApiFootballClient,
    competitions: list[int],
    season: int,
    out_dir: Path = DEFAULT_DIR,
    until: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    if until is not None and now > until:
        raise RuntimeError(f"monitoring trial ended at {until.isoformat()}; not collecting")
    out_dir.mkdir(parents=True, exist_ok=True)
    run: dict[str, Any] = {"run_at": now.isoformat(), "season": season, "competitions": {}}
    summary: dict[str, Any] = {"run_at": now.isoformat(), "competitions": {}}
    for cid in competitions:
        entry: dict[str, Any] = {"pages": [], "error": None}
        try:
            for page in client.paginate("odds", {"league": cid, "season": season}):
                entry["pages"].append(
                    {
                        "retrieved_at": page.retrieved_at.isoformat(),
                        "paging": [page.paging_current, page.paging_total],
                        "results": page.results,
                        "rate_limit": page.rate_limit.__dict__,
                        "items": [_slim(i) for i in page.items],
                    }
                )
        except ApiFootballError as exc:  # record and continue with other leagues
            entry["error"] = repr(exc)
        items = [i for p in entry["pages"] for i in p["items"]]
        n_quotes = sum(len(extract_quotes(i)[0]) for i in items)
        summary["competitions"][cid] = {
            "pages": len(entry["pages"]),
            "fixtures": len(items),
            "quotes": n_quotes,
            "provider_updates": sorted({i["update"] for i in items if i.get("update")}),
            "error": entry["error"],
        }
        run["competitions"][cid] = entry
    summary["requests"] = client.quota_requests_made
    summary["daily_remaining_header"] = client.last_rate_limit.daily_remaining
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    with gzip.open(out_dir / f"{stamp}.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(run, fh, separators=(",", ":"))
    with (out_dir / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary) + "\n")
    return summary


def load_runs(out_dir: Path = DEFAULT_DIR) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(out_dir.glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            runs.append(json.load(fh))
    return sorted(runs, key=lambda r: r["run_at"])


@dataclass
class ReplayResult:
    runs: int
    fetches: int
    errors: list[str]


def replay(conn: Connection, runs: list[dict[str, Any]]) -> ReplayResult:
    """Replay saved runs into the odds tables (which should start empty)."""
    errors: list[str] = []
    fetches = 0
    for run in runs:
        run_at = datetime.fromisoformat(run["run_at"])
        for cid, entry in run["competitions"].items():
            if entry.get("error"):
                errors.append(f"{run['run_at']} {cid}: {entry['error']}")
            if not entry["pages"]:
                continue
            pages = [
                OddsPage(
                    datetime.fromisoformat(p["retrieved_at"]),
                    p["items"],
                    p["paging"][0],
                    p["paging"][1],
                )
                for p in entry["pages"]
            ]
            reconcile_pages(conn, int(cid), int(run["season"]), pages, clock=lambda t=run_at: t)
            fetches += 1
    return ReplayResult(len(runs), fetches, errors)


def _hours(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 3600


def analyse(conn: Connection, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics over replayed data. Call after ``replay``."""
    out: dict[str, Any] = {
        "runs": len(runs),
        "first_run": runs[0]["run_at"] if runs else None,
        "last_run": runs[-1]["run_at"] if runs else None,
    }

    # --- provider timestamp behaviour (from raw files)
    per_fixture_updates: dict[int, list[tuple[datetime, str]]] = defaultdict(list)
    distinct_per_run: list[int] = []
    lag_hours: list[float] = []
    psl_by_run: list[dict[str, Any]] = []
    requests: list[int] = []
    errors = 0
    for run in runs:
        run_at = datetime.fromisoformat(run["run_at"])
        values: set[str] = set()
        for cid, entry in run["competitions"].items():
            errors += bool(entry.get("error"))
            items = [i for p in entry["pages"] for i in p["items"]]
            requests.append(len(entry["pages"]))
            if int(cid) == 288:
                psl_by_run.append({"run_at": run["run_at"], "fixtures_with_odds": len(items)})
            for i in items:
                upd = i.get("update")
                # only pre-match fixtures: odds of played fixtures linger in responses
                if not upd or datetime.fromisoformat(i["fixture"]["date"]) <= run_at:
                    continue
                values.add(upd)
                per_fixture_updates[i["fixture"]["id"]].append((run_at, upd))
                lag_hours.append(_hours(run_at, datetime.fromisoformat(upd)))
        distinct_per_run.append(len(values))
    changes = 0
    observations = 0
    for seq in per_fixture_updates.values():
        observations += len(seq) - 1
        changes += sum(1 for a, b in zip(seq, seq[1:], strict=False) if a[1] != b[1])
    all_updates = sorted(
        {datetime.fromisoformat(u) for seq in per_fixture_updates.values() for _, u in seq}
    )
    gaps = [_hours(b, a) for a, b in zip(all_updates, all_updates[1:], strict=False)]
    out["provider_update"] = {
        "distinct_values_per_run": distinct_per_run,
        "distinct_values_total": len(all_updates),
        "fixture_level_changes_between_runs": changes,
        "fixture_level_comparisons": observations,
        "median_gap_between_distinct_values_h": round(median(gaps), 2) if gaps else None,
        "max_gap_between_distinct_values_h": round(max(gaps), 2) if gaps else None,
        "median_age_at_retrieval_h": round(median(lag_hours), 2) if lag_hours else None,
        "max_age_at_retrieval_h": round(max(lag_hours), 2) if lag_hours else None,
    }

    # --- price changes vs provider timestamp (from replayed episodes)
    rows = conn.execute(select(odds_quotes)).all()
    changed = [r for r in rows if r.end_reason == "price_changed"]
    out["quotes"] = {
        "episodes": len(rows),
        "end_reasons": dict(Counter(r.end_reason for r in rows)),
        "distinct_quote_keys": len(
            {(r.fixture_id, r.bookmaker_id, r.market, r.outcome) for r in rows}
        ),
    }
    # price changes where the provider timestamp did not change between the two sightings
    by_key: dict[tuple, list] = defaultdict(list)
    for r in rows:
        by_key[(r.fixture_id, r.bookmaker_id, r.market, r.outcome)].append(r)
    same_update_changes = 0
    for eps in by_key.values():
        eps.sort(key=lambda r: r.first_seen_at)
        for a, b in zip(eps, eps[1:], strict=False):
            if (
                a.end_reason == "price_changed"
                and a.last_provider_updated_at == b.first_provider_updated_at
            ):
                same_update_changes += 1
    out["quotes"]["price_changes"] = len(changed)
    out["quotes"]["price_changes_without_provider_update_change"] = same_update_changes

    # --- per-fetch activity
    fetch_rows = conn.execute(select(odds_fetches).order_by(odds_fetches.c.id)).all()
    out["fetches"] = [
        {
            "competition_id": f.competition_id,
            "retrieved_at": f.retrieved_at.isoformat(),
            "fixtures_collected": f.fixtures_collected,
            "quotes_seen": f.quotes_seen,
            "inserted": f.quotes_inserted,
            "price_changed": f.quotes_price_changed,
            "disappeared": f.quotes_disappeared,
        }
        for f in fetch_rows
    ]

    # --- coverage by lead time (bookmakers with complete markets per fixture)
    kick = dict(conn.execute(select(fixtures.c.id, fixtures.c.kickoff_utc)).all())
    obs = conn.execute(select(odds_fixture_observations)).all()
    buckets: dict[str, list[int]] = defaultdict(list)
    for o in obs:
        days = _hours(kick[o.fixture_id], o.retrieved_at) / 24
        label = "<1d" if days < 1 else "1-3d" if days < 3 else "3-7d" if days < 7 else "7-14d"
        buckets[label].append(o.bookmakers_listed)
    out["bookmakers_listed_by_lead_time"] = {
        k: {"observations": len(v), "median": median(v), "min": min(v), "max": max(v)}
        for k, v in sorted(buckets.items())
    }
    out["psl_availability"] = psl_by_run
    out["requests_total"] = sum(requests)
    out["runs_with_errors"] = errors
    return out
