"""Median consensus reference odds with transparent freshness and eligibility rules.

Consensus prices are *reference values*, not offers from any bookmaker, and
this module deliberately computes no probabilities, expected values or edges.

Rules applied at a reference time ``as_of`` (all configurable):

1. **In effect** - the price episode covers ``as_of``
   (``first_seen_at <= as_of`` and not ended at or before ``as_of``).
2. **Pre-match** - the fixture has not kicked off at ``as_of``.
3. **Recently observed** - our latest retrieval that saw this price, at or
   before ``as_of``, is no older than ``max_quote_age`` (24 h).
4. **Recently updated by the provider** - the provider's fixture-level
   ``update`` timestamp known at ``as_of`` is no older than ``max_quote_age``.
   It is shared by all bookmakers, so it is a coarse feed-level check only.
   A missing provider timestamp makes the quote ineligible.
5. **Eligible bookmaker** - bookmaker flagged eligible and not an exchange.
6. **Complete market** - the bookmaker has valid prices for *every* outcome of
   the market (e.g. Home, Draw and Away); otherwise its whole market is dropped.
7. **One source per independent group** - bookmakers sharing an
   ``affiliation_group`` count once. The group is represented by its most
   recently observed bookmaker (ties: lowest id), for all outcomes of the market.

The consensus for an outcome is the median of the remaining sources' prices
(mean of the two middle values for an even count). ``consensus_odds`` is that
median rounded half-up to two decimals; ``median_odds`` keeps the exact value.

* Displayable when at least one source remains.
* Challenge-eligible when the number of independent sources is at least
  ``min_bookmakers`` (3; overridable per competition).
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Connection, and_, func, or_, select

from diski9.api_football.markets import MARKET_OUTCOMES, Market, Outcome
from diski9.db.schema import bookmakers, fixtures, odds_fixture_observations, odds_quotes


@dataclass(frozen=True)
class ConsensusRules:
    max_quote_age: timedelta = timedelta(hours=24)
    min_bookmakers: int = 3
    min_bookmakers_by_competition: dict[int, int] = field(default_factory=dict)

    def min_for(self, competition_id: int | None) -> int:
        if competition_id is None:
            return self.min_bookmakers
        return self.min_bookmakers_by_competition.get(competition_id, self.min_bookmakers)


@dataclass(frozen=True)
class BookmakerInfo:
    id: int
    name: str | None = None
    eligible: bool = True
    is_exchange: bool = False
    affiliation_group: str | None = None

    @property
    def group_key(self) -> str:
        return (
            f"group:{self.affiliation_group}" if self.affiliation_group else f"bookmaker:{self.id}"
        )


@dataclass(frozen=True)
class QuoteEpisode:
    bookmaker_id: int
    market: str
    outcome: str
    decimal_odds: Decimal
    first_seen_at: datetime
    last_seen_at: datetime
    first_provider_updated_at: datetime | None
    last_provider_updated_at: datetime | None
    ended_at: datetime | None = None


@dataclass(frozen=True)
class OutcomeConsensus:
    outcome: Outcome
    consensus_odds: Decimal | None
    median_odds: Decimal | None
    sources: int
    bookmaker_ids: tuple[int, ...]
    min_odds: Decimal | None
    max_odds: Decimal | None


@dataclass(frozen=True)
class MarketConsensus:
    fixture_id: int
    market: Market
    as_of: datetime
    outcomes: dict[Outcome, OutcomeConsensus]
    sources: int
    min_required: int
    exclusions: dict[str, int]
    # Our own most recent retrieval that saw a contributing price (verified observation).
    latest_observation: datetime | None = None
    # Provider feed timestamp: fixture/league-level, NOT a bookmaker price-change time.
    provider_updated_at: datetime | None = None
    # Phase 8 R2: the oldest contributing observation and provider timestamps (the
    # competitive freshness evidence: a price is only as fresh as its oldest source).
    oldest_observation: datetime | None = None
    oldest_provider_updated_at: datetime | None = None

    @property
    def displayable(self) -> bool:
        return self.sources >= 1

    @property
    def challenge_eligible(self) -> bool:
        return self.sources >= self.min_required


def _observed_at(
    q: QuoteEpisode, as_of: datetime, fixture_observed_at: datetime | None
) -> datetime:
    """Latest retrieval at or before ``as_of`` that saw this price."""
    if q.last_seen_at <= as_of:
        return q.last_seen_at
    # Episode spans as_of: the price was seen at the fixture's latest observation
    # at or before as_of (conservatively, at least at first sighting).
    if fixture_observed_at is not None and q.first_seen_at <= fixture_observed_at <= as_of:
        return fixture_observed_at
    return q.first_seen_at


def _provider_at(q: QuoteEpisode, as_of: datetime) -> datetime | None:
    return q.last_provider_updated_at if q.last_seen_at <= as_of else q.first_provider_updated_at


def exclusion_reason(
    q: QuoteEpisode,
    book: BookmakerInfo | None,
    as_of: datetime,
    kickoff: datetime,
    rules: ConsensusRules,
    fixture_observed_at: datetime | None = None,
) -> str | None:
    """Why a single quote is not usable at ``as_of`` (None = usable)."""
    if q.first_seen_at > as_of:
        return "not_yet_observed"
    if q.ended_at is not None and q.ended_at <= as_of:
        return "no_longer_offered"
    if kickoff <= as_of:
        return "fixture_started"
    if book is None or not book.eligible:
        return "bookmaker_ineligible"
    if book.is_exchange:
        return "exchange_price"
    if q.decimal_odds is None or q.decimal_odds <= 1:
        return "invalid_odds"
    if as_of - _observed_at(q, as_of, fixture_observed_at) > rules.max_quote_age:
        return "stale_observation"
    provider = _provider_at(q, as_of)
    if provider is None:
        return "missing_provider_timestamp"
    if as_of - provider > rules.max_quote_age:
        return "stale_provider_update"
    return None


def _median(values: list[Decimal]) -> Decimal:
    return Decimal(statistics.median(values))


def market_consensus(
    fixture_id: int,
    market: Market,
    episodes: Iterable[QuoteEpisode],
    books: dict[int, BookmakerInfo],
    kickoff: datetime,
    as_of: datetime,
    rules: ConsensusRules | None = None,
    competition_id: int | None = None,
    fixture_observed_at: datetime | None = None,
) -> MarketConsensus:
    rules = rules or ConsensusRules()
    required = MARKET_OUTCOMES[market]
    exclusions: Counter[str] = Counter()

    # 1-5: per-quote filters; keep one episode per (bookmaker, outcome)
    usable: dict[int, dict[Outcome, QuoteEpisode]] = defaultdict(dict)
    for q in episodes:
        if q.market != market.value:
            continue
        reason = exclusion_reason(
            q, books.get(q.bookmaker_id), as_of, kickoff, rules, fixture_observed_at
        )
        if reason:
            exclusions[reason] += 1
            continue
        outcome = Outcome(q.outcome)
        current = usable[q.bookmaker_id].get(outcome)
        if current is None or q.first_seen_at > current.first_seen_at:
            usable[q.bookmaker_id][outcome] = q

    # 6: complete outcome sets only
    complete: dict[int, dict[Outcome, QuoteEpisode]] = {}
    for bid, by_outcome in usable.items():
        if set(by_outcome) == required:
            complete[bid] = by_outcome
        else:
            exclusions["incomplete_market"] += len(by_outcome)

    # 7: one representative per independent group
    def recency(bid: int) -> tuple[datetime, int]:
        latest = max(_observed_at(q, as_of, fixture_observed_at) for q in complete[bid].values())
        return (latest, -bid)

    groups: dict[str, list[int]] = defaultdict(list)
    for bid in complete:
        groups[books[bid].group_key].append(bid)
    chosen: list[int] = []
    for members in groups.values():
        best = max(members, key=recency)
        chosen.append(best)
        if len(members) > 1:
            exclusions["affiliated_duplicate"] += (len(members) - 1) * len(required)
    chosen.sort()

    outcomes: dict[Outcome, OutcomeConsensus] = {}
    for outcome in sorted(required):
        prices = [complete[b][outcome].decimal_odds for b in chosen]
        if prices:
            med = _median(prices)
            outcomes[outcome] = OutcomeConsensus(
                outcome=outcome,
                consensus_odds=med.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                median_odds=med,
                sources=len(prices),
                bookmaker_ids=tuple(chosen),
                min_odds=min(prices),
                max_odds=max(prices),
            )
        else:
            outcomes[outcome] = OutcomeConsensus(outcome, None, None, 0, (), None, None)
    used = [q for b in chosen for q in complete[b].values()]
    return MarketConsensus(
        fixture_id=fixture_id,
        market=market,
        as_of=as_of,
        outcomes=outcomes,
        sources=len(chosen),
        min_required=rules.min_for(competition_id),
        exclusions=dict(exclusions),
        latest_observation=max(
            (_observed_at(q, as_of, fixture_observed_at) for q in used), default=None
        ),
        provider_updated_at=max(
            (p for q in used if (p := _provider_at(q, as_of)) is not None), default=None
        ),
        oldest_observation=min(
            (_observed_at(q, as_of, fixture_observed_at) for q in used), default=None
        ),
        oldest_provider_updated_at=min(
            (p for q in used if (p := _provider_at(q, as_of)) is not None), default=None
        ),
    )


# ------------------------------------------------------------------ DB access
def load_bookmakers(conn: Connection) -> dict[int, BookmakerInfo]:
    return {
        r.id: BookmakerInfo(
            r.id, r.name, bool(r.eligible), bool(r.is_exchange), r.affiliation_group
        )
        for r in conn.execute(select(bookmakers))
    }


def fixture_consensus(
    conn: Connection,
    fixture_id: int,
    as_of: datetime,
    rules: ConsensusRules | None = None,
    books: dict[int, BookmakerInfo] | None = None,
) -> dict[Market, MarketConsensus]:
    """Consensus for all three markets of one fixture, as of ``as_of``.

    Uses only quote episodes first observed at or before ``as_of`` (no
    look-ahead), so the same call reproduces a past snapshot.
    """
    books = books if books is not None else load_bookmakers(conn)
    fx = conn.execute(
        select(fixtures.c.kickoff_utc, fixtures.c.competition_id).where(fixtures.c.id == fixture_id)
    ).one()
    observed_at = conn.execute(
        select(func.max(odds_fixture_observations.c.retrieved_at)).where(
            odds_fixture_observations.c.fixture_id == fixture_id,
            odds_fixture_observations.c.retrieved_at <= as_of,
        )
    ).scalar()
    rows = conn.execute(
        select(odds_quotes).where(
            and_(
                odds_quotes.c.fixture_id == fixture_id,
                odds_quotes.c.first_seen_at <= as_of,
                or_(odds_quotes.c.ended_at.is_(None), odds_quotes.c.ended_at > as_of),
            )
        )
    ).all()
    episodes = [
        QuoteEpisode(
            r.bookmaker_id,
            r.market,
            r.outcome,
            r.decimal_odds,
            r.first_seen_at,
            r.last_seen_at,
            r.first_provider_updated_at,
            r.last_provider_updated_at,
            r.ended_at,
        )
        for r in rows
    ]
    return {
        m: market_consensus(
            fixture_id,
            m,
            episodes,
            books,
            fx.kickoff_utc,
            as_of,
            rules,
            fx.competition_id,
            observed_at,
        )
        for m in Market
    }
