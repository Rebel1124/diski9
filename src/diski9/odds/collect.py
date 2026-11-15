"""On-demand collection of pre-match odds for upcoming fixtures.

Storage model ("price episodes")
--------------------------------
Each ``odds_quotes`` row is one continuous period in which a bookmaker offered
one price for one outcome:

* same price seen again   -> update ``last_seen_at`` / ``times_seen`` (no new row)
* different price         -> end the active row (``price_changed``), insert a new one.
                             This happens even if the provider ``update`` timestamp
                             did not change.
* no longer offered       -> end the active row (``disappeared``). A later
                             reappearance starts a new episode.
* fixture kicked off      -> end the active rows (``kickoff``); no further collection.

The provider ``update`` value is fixture-level (shared by every bookmaker, and
in practice by the whole league), so it is stored but never treated as a
bookmaker-level price-change time. ``first_seen_at`` / ``last_seen_at`` are our
own retrieval times.

Historical odds are never backfilled: only fixtures that have not kicked off are
collected.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, and_, insert, select, true, update

from diski9.api_football import ApiFootballClient
from diski9.api_football.markets import Quote, extract_quotes, parse_provider_timestamp
from diski9.db.schema import fixtures, odds_fetches, odds_fixture_observations, odds_quotes
from diski9.ingestion.classify import UPCOMING_STATUSES
from diski9.ingestion.common import Clock, utcnow
from diski9.ingestion.reference import ensure_bookmaker

QuoteKey = tuple[int, str, str]  # (bookmaker_id, market, outcome)


@dataclass
class FetchStats:
    fetch_id: int = 0
    requests: int = 0
    pages: int = 0
    fixtures_in_response: int = 0
    fixtures_collected: int = 0
    quotes_seen: int = 0
    quotes_inserted: int = 0
    quotes_unchanged: int = 0
    quotes_price_changed: int = 0
    quotes_disappeared: int = 0
    quotes_closed_at_kickoff: int = 0
    skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    warnings: list[str] = field(default_factory=list)


def apply_fixture_quotes(
    conn: Connection,
    fixture_id: int,
    quotes: list[Quote],
    retrieved_at: datetime,
    fetch_id: int,
    stats: FetchStats,
) -> None:
    """Reconcile one fixture's observed quotes against its active episodes."""
    active = {
        (r.bookmaker_id, r.market, r.outcome): r
        for r in conn.execute(
            select(odds_quotes).where(
                odds_quotes.c.fixture_id == fixture_id, odds_quotes.c.ended_at.is_(None)
            )
        )
    }
    seen: set[QuoteKey] = set()
    for q in quotes:
        key = (q.bookmaker_id, q.market.value, q.outcome.value)
        if key in seen:  # extract_quotes already prevents this; defensive
            continue
        seen.add(key)
        stats.quotes_seen += 1
        prev = active.get(key)
        if prev is not None and prev.decimal_odds == q.decimal_odds:
            conn.execute(
                update(odds_quotes)
                .where(odds_quotes.c.id == prev.id)
                .values(
                    last_seen_at=retrieved_at,
                    last_provider_updated_at=q.provider_updated_at,
                    times_seen=prev.times_seen + 1,
                    last_fetch_id=fetch_id,
                )
            )
            stats.quotes_unchanged += 1
            continue
        if prev is not None:
            conn.execute(
                update(odds_quotes)
                .where(odds_quotes.c.id == prev.id)
                .values(ended_at=retrieved_at, end_reason="price_changed")
            )
            stats.quotes_price_changed += 1
        conn.execute(
            insert(odds_quotes).values(
                fixture_id=fixture_id,
                bookmaker_id=q.bookmaker_id,
                market=q.market.value,
                outcome=q.outcome.value,
                decimal_odds=q.decimal_odds,
                first_seen_at=retrieved_at,
                last_seen_at=retrieved_at,
                first_provider_updated_at=q.provider_updated_at,
                last_provider_updated_at=q.provider_updated_at,
                times_seen=1,
                first_fetch_id=fetch_id,
                last_fetch_id=fetch_id,
            )
        )
        stats.quotes_inserted += 1
    gone = [r.id for k, r in active.items() if k not in seen]
    if gone:
        conn.execute(
            update(odds_quotes)
            .where(odds_quotes.c.id.in_(gone))
            .values(ended_at=retrieved_at, end_reason="disappeared")
        )
        stats.quotes_disappeared += len(gone)


def close_started_fixtures(
    conn: Connection, competition_id: int, season: int, now: datetime
) -> int:
    """End active quotes of fixtures that have kicked off (ended_at = kickoff)."""
    started = conn.execute(
        select(fixtures.c.id, fixtures.c.kickoff_utc)
        .where(
            fixtures.c.competition_id == competition_id,
            fixtures.c.season == season,
            fixtures.c.kickoff_utc <= now,
        )
        .where(
            fixtures.c.id.in_(
                select(odds_quotes.c.fixture_id).where(odds_quotes.c.ended_at.is_(None))
            )
        )
    ).all()
    closed = 0
    for f in started:
        res = conn.execute(
            update(odds_quotes)
            .where(odds_quotes.c.fixture_id == f.id, odds_quotes.c.ended_at.is_(None))
            .values(ended_at=f.kickoff_utc, end_reason="kickoff")
        )
        closed += res.rowcount
    return closed


def collect_odds(
    conn: Connection,
    client: ApiFootballClient,
    competition_id: int,
    season: int,
    clock: Clock = utcnow,
    max_pages: int | None = None,
) -> FetchStats:
    """Fetch ``/odds?league&season`` (all pages) and reconcile upcoming fixtures.

    Fixtures must already be stored (run fixture ingestion first). Items for
    fixtures that are unknown, already kicked off or not in an upcoming status
    are skipped and counted.
    """
    started = clock()
    stats = FetchStats()
    stats.fetch_id = conn.execute(
        insert(odds_fetches).values(
            competition_id=competition_id, season=season, retrieved_at=started, status="running"
        )
    ).inserted_primary_key[0]

    known = {
        r.id: r
        for r in conn.execute(
            select(fixtures.c.id, fixtures.c.kickoff_utc, fixtures.c.status_short).where(
                fixtures.c.competition_id == competition_id, fixtures.c.season == season
            )
        )
    }
    in_response: set[int] = set()
    complete = True
    for page in client.paginate(
        "odds", {"league": competition_id, "season": season}, max_pages=max_pages
    ):
        stats.requests += 1
        stats.pages += 1
        if (
            page.paging_current < page.paging_total
            and max_pages is not None
            and stats.pages >= max_pages
        ):
            complete = False
        retrieved_at = page.retrieved_at
        for item in page.items:
            stats.fixtures_in_response += 1
            fid = int(item["fixture"]["id"])
            in_response.add(fid)
            fx = known.get(fid)
            if fx is None:
                stats.skipped["unknown_fixture"] += 1
                continue
            if fx.kickoff_utc <= retrieved_at:
                stats.skipped["kicked_off"] += 1
                continue
            if fx.status_short not in UPCOMING_STATUSES:
                stats.skipped[f"status_{fx.status_short}"] += 1
                continue
            quotes, warnings = extract_quotes(item)
            stats.warnings.extend(warnings)
            for b in item.get("bookmakers") or []:
                ensure_bookmaker(conn, int(b["id"]), b.get("name"), retrieved_at)
            conn.execute(
                insert(odds_fixture_observations).values(
                    fetch_id=stats.fetch_id,
                    fixture_id=fid,
                    retrieved_at=retrieved_at,
                    provider_updated_at=parse_provider_timestamp(item.get("update")),
                    bookmakers_listed=len(item.get("bookmakers") or []),
                    quotes_parsed=len(quotes),
                )
            )
            apply_fixture_quotes(conn, fid, quotes, retrieved_at, stats.fetch_id, stats)
            stats.fixtures_collected += 1

    now = clock()
    if complete:
        # Upcoming fixtures absent from a complete response no longer have odds.
        missing = conn.execute(
            select(odds_quotes.c.id)
            .join(fixtures, fixtures.c.id == odds_quotes.c.fixture_id)
            .where(
                and_(
                    fixtures.c.competition_id == competition_id,
                    fixtures.c.season == season,
                    fixtures.c.kickoff_utc > now,
                    odds_quotes.c.ended_at.is_(None),
                    odds_quotes.c.fixture_id.not_in(in_response) if in_response else true(),
                )
            )
        ).all()
        if missing:
            conn.execute(
                update(odds_quotes)
                .where(odds_quotes.c.id.in_([r.id for r in missing]))
                .values(ended_at=started, end_reason="disappeared")
            )
            stats.quotes_disappeared += len(missing)
    stats.quotes_closed_at_kickoff = close_started_fixtures(conn, competition_id, season, now)

    conn.execute(
        update(odds_fetches)
        .where(odds_fetches.c.id == stats.fetch_id)
        .values(
            finished_at=now,
            status="complete" if complete else "partial",
            requests=stats.requests,
            pages=stats.pages,
            fixtures_in_response=stats.fixtures_in_response,
            fixtures_collected=stats.fixtures_collected,
            quotes_seen=stats.quotes_seen,
            quotes_inserted=stats.quotes_inserted,
            quotes_unchanged=stats.quotes_unchanged,
            quotes_price_changed=stats.quotes_price_changed,
            quotes_disappeared=stats.quotes_disappeared,
            quotes_closed_at_kickoff=stats.quotes_closed_at_kickoff,
            warnings="\n".join(stats.warnings[:200]) or None,
        )
    )
    return stats


def summarise_fetch(stats: FetchStats) -> dict[str, Any]:
    return {
        k: (dict(v) if isinstance(v, defaultdict) else v)
        for k, v in stats.__dict__.items()
        if k != "warnings"
    } | {"warnings": len(stats.warnings)}
