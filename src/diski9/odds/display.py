"""Reference-odds display status for the research Screener (Milestone 5).

Statuses per market:

* ``fresh``        a valid consensus exists *now* under the provisional rules
                   (24 h freshness, eligible/independent bookmakers, complete
                   markets).
* ``stale``        no valid consensus now, but one existed at an earlier
                   retrieval. That earlier consensus is shown, labelled stale,
                   with its age. It is recomputed **as of that single retrieval
                   time** using only the quotes in effect at that moment, so
                   quotes from different collection times are never combined.
* ``unavailable``  no valid consensus has ever been observed before kickoff.

**Display status is not Challenge eligibility.** ``challenge_eligible`` is
true only for a *fresh* consensus that meets the strict Challenge rules.
Challenge snapshots must use :func:`challenge_consensus`, which evaluates the
strict rules at the snapshot time and has no stale fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Connection, select

from diski9.api_football.markets import Market
from diski9.db.schema import fixtures, odds_fixture_observations

from .consensus import (
    BookmakerInfo,
    ConsensusRules,
    MarketConsensus,
    fixture_consensus,
    load_bookmakers,
)
from .implied import ImpliedProbabilities, implied

Status = Literal["fresh", "stale", "unavailable"]
MAX_LOOKBACK_SNAPSHOTS = 500


@dataclass(frozen=True)
class DisplayedMarket:
    market: Market
    status: Status
    consensus: MarketConsensus | None  # the consensus being displayed (None if unavailable)
    implied: ImpliedProbabilities | None
    snapshot_at: datetime | None  # retrieval time of the displayed snapshot
    age_hours: float | None  # now - latest verified observation of the displayed prices
    reason: str | None = None  # why unavailable / why stale

    @property
    def challenge_eligible(self) -> bool:
        """Strict: fresh *and* meets the Challenge rules. Stale is never eligible."""
        return (
            self.status == "fresh"
            and self.consensus is not None
            and self.consensus.challenge_eligible
        )


def display_consensus(
    conn: Connection,
    fixture_id: int,
    now: datetime,
    rules: ConsensusRules | None = None,
    books: dict[int, BookmakerInfo] | None = None,
) -> dict[Market, DisplayedMarket]:
    books = books if books is not None else load_bookmakers(conn)
    current = fixture_consensus(conn, fixture_id, now, rules, books)
    out: dict[Market, DisplayedMarket] = {}
    for market, mc in current.items():
        if mc.displayable:
            out[market] = DisplayedMarket(
                market, "fresh", mc, implied(mc), now, _age(now, mc.latest_observation)
            )
    pending = [m for m in Market if m not in out]
    if pending:
        kickoff = conn.execute(
            select(fixtures.c.kickoff_utc).where(fixtures.c.id == fixture_id)
        ).scalar()
        snapshots = [
            r[0]
            for r in conn.execute(
                select(odds_fixture_observations.c.retrieved_at)
                .where(
                    odds_fixture_observations.c.fixture_id == fixture_id,
                    odds_fixture_observations.c.retrieved_at <= now,
                    odds_fixture_observations.c.retrieved_at < kickoff,
                )
                .distinct()
                .order_by(odds_fixture_observations.c.retrieved_at.desc())
                .limit(MAX_LOOKBACK_SNAPSHOTS)
            )
        ]
        for t in snapshots:
            if not pending:
                break
            past = fixture_consensus(conn, fixture_id, t, rules, books)
            for market in list(pending):
                mc = past[market]
                if mc.displayable:
                    out[market] = DisplayedMarket(
                        market,
                        "stale",
                        mc,
                        implied(mc),
                        t,
                        _age(now, mc.latest_observation),
                        _stale_reason(current[market]),
                    )
                    pending.remove(market)
    for market in pending:
        out[market] = DisplayedMarket(
            market, "unavailable", None, None, None, None, _unavailable_reason(current[market])
        )
    return {m: out[m] for m in Market}


def challenge_consensus(
    conn: Connection,
    fixture_id: int,
    snapshot_time: datetime,
    rules: ConsensusRules | None = None,
    books: dict[int, BookmakerInfo] | None = None,
) -> dict[Market, MarketConsensus | None]:
    """Consensus eligible for a Challenge snapshot at ``snapshot_time``.

    Strict rules only (fresh quotes, eligible independent bookmakers, complete
    market, minimum independent sources, pre-kickoff). There is deliberately no
    stale fallback: a market that is not eligible returns None.
    """
    result = fixture_consensus(conn, fixture_id, snapshot_time, rules, books)
    return {m: (mc if mc.challenge_eligible else None) for m, mc in result.items()}


def _age(now: datetime, observed: datetime | None) -> float | None:
    return None if observed is None else round((now - observed).total_seconds() / 3600, 1)


def _stale_reason(current: MarketConsensus) -> str:
    ex = current.exclusions
    if ex.get("stale_provider_update") and not ex.get("stale_observation"):
        return "The provider has not updated these prices within the last 24 hours."
    return "No price has been verified within the last 24 hours; prices may have changed."


def _unavailable_reason(current: MarketConsensus) -> str:
    ex = current.exclusions
    if not ex:
        return "No bookmaker prices have been collected for this market."
    if ex.get("incomplete_market"):
        return "Bookmakers have not quoted every outcome of this market."
    if ex.get("fixture_started"):
        return "The match has started; pre-match prices are no longer shown."
    return "No valid, eligible bookmaker prices are available for this market."
