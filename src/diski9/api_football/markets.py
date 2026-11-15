"""Verified mapping of API-Football odds markets to the seven Diski 9 outcomes.

Verified against ``/odds/bets`` and live ``/odds`` responses (November 2026):

==========  =================  ======  ===========================
Market      API bet name       bet id  API ``value`` strings used
==========  =================  ======  ===========================
1X2         Match Winner       1       "Home", "Draw", "Away"
BTTS        Both Teams Score   8       "Yes", "No"
OU25        Goals Over/Under   5       "Over 2.5", "Under 2.5"
==========  =================  ======  ===========================

Bet ``5`` carries many lines (0.5 … 6.5, and quarter lines such as 2.75);
only the 2.5 line is used. Odds arrive as decimal strings (e.g. ``"1.85"``).

This module only *normalises* a provider payload into flat quotes. It does not
persist anything; ingestion is a later milestone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


class Market(StrEnum):
    MATCH_RESULT = "1X2"
    BTTS = "BTTS"
    OVER_UNDER_25 = "OU25"


class Outcome(StrEnum):
    HOME = "HOME"
    DRAW = "DRAW"
    AWAY = "AWAY"
    BTTS_YES = "BTTS_YES"
    BTTS_NO = "BTTS_NO"
    OVER_25 = "OVER_2_5"
    UNDER_25 = "UNDER_2_5"


# market -> (api bet id, api bet name, {api value string: outcome})
MARKET_MAP: dict[Market, tuple[int, str, dict[str, Outcome]]] = {
    Market.MATCH_RESULT: (
        1,
        "Match Winner",
        {"Home": Outcome.HOME, "Draw": Outcome.DRAW, "Away": Outcome.AWAY},
    ),
    Market.BTTS: (
        8,
        "Both Teams Score",
        {"Yes": Outcome.BTTS_YES, "No": Outcome.BTTS_NO},
    ),
    Market.OVER_UNDER_25: (
        5,
        "Goals Over/Under",
        {"Over 2.5": Outcome.OVER_25, "Under 2.5": Outcome.UNDER_25},
    ),
}

BET_ID_TO_MARKET: dict[int, Market] = {bet_id: m for m, (bet_id, _, _) in MARKET_MAP.items()}
ALL_OUTCOMES: frozenset[Outcome] = frozenset(Outcome)
MARKET_OUTCOMES: dict[Market, frozenset[Outcome]] = {
    m: frozenset(values.values()) for m, (_, _, values) in MARKET_MAP.items()
}

# Sanity bounds for decimal odds; values outside are treated as invalid.
MIN_VALID_ODDS = Decimal("1.01")
MAX_VALID_ODDS = Decimal(1000)


@dataclass(frozen=True)
class Quote:
    fixture_id: int
    league_id: int
    season: int
    bookmaker_id: int
    bookmaker_name: str | None
    market: Market
    outcome: Outcome
    decimal_odds: Decimal
    provider_updated_at: datetime | None  # API "update" (fixture-level, not per bookmaker)


def parse_odds(raw: Any) -> Decimal | None:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value < MIN_VALID_ODDS or value > MAX_VALID_ODDS:
        return None
    return value


def parse_provider_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def check_bet_catalogue(bets: list[dict[str, Any]]) -> list[str]:
    """Validate ``/odds/bets`` against MARKET_MAP. Returns a list of problems."""
    by_id = {b.get("id"): b.get("name") for b in bets}
    problems = []
    for market, (bet_id, name, _) in MARKET_MAP.items():
        if by_id.get(bet_id) != name:
            problems.append(f"{market}: expected bet {bet_id}={name!r}, got {by_id.get(bet_id)!r}")
    return problems


def extract_quotes(odds_item: dict[str, Any]) -> tuple[list[Quote], list[str]]:
    """Flatten one ``/odds`` response item into Diski 9 quotes.

    Returns ``(quotes, warnings)``. A bookmaker's market is only emitted when
    *all* outcomes of that market are present with valid odds, so incomplete
    or malformed markets never produce partial quotes.
    """
    warnings: list[str] = []
    fixture_id = int(odds_item["fixture"]["id"])
    league = odds_item.get("league") or {}
    updated = parse_provider_timestamp(odds_item.get("update"))
    quotes: list[Quote] = []

    for bookmaker in odds_item.get("bookmakers") or []:
        bk_id = int(bookmaker["id"])
        seen_markets: set[Market] = set()
        for bet in bookmaker.get("bets") or []:
            market = BET_ID_TO_MARKET.get(bet.get("id"))
            if market is None:
                continue
            if market in seen_markets:
                warnings.append(
                    f"fixture {fixture_id} bookmaker {bk_id}: duplicate {market} block ignored"
                )
                continue
            seen_markets.add(market)
            _, _, value_map = MARKET_MAP[market]
            found: dict[Outcome, Decimal] = {}
            for v in bet.get("values") or []:
                outcome = value_map.get(str(v.get("value")))
                if outcome is None:
                    continue
                odds = parse_odds(v.get("odd"))
                if odds is None:
                    warnings.append(
                        f"fixture {fixture_id} bookmaker {bk_id}: "
                        f"invalid odds {v.get('odd')!r} for {outcome}"
                    )
                    continue
                if outcome in found and found[outcome] != odds:
                    warnings.append(
                        f"fixture {fixture_id} bookmaker {bk_id}: conflicting {outcome} prices"
                    )
                    found.pop(outcome)
                    break
                found[outcome] = odds
            if set(found) != MARKET_OUTCOMES[market]:
                if found:
                    warnings.append(
                        f"fixture {fixture_id} bookmaker {bk_id}: incomplete {market} skipped"
                    )
                continue
            for outcome, odds in found.items():
                quotes.append(
                    Quote(
                        fixture_id=fixture_id,
                        league_id=int(league.get("id") or 0),
                        season=int(league.get("season") or 0),
                        bookmaker_id=bk_id,
                        bookmaker_name=bookmaker.get("name"),
                        market=market,
                        outcome=outcome,
                        decimal_odds=odds,
                        provider_updated_at=updated,
                    )
                )
    return quotes, warnings
