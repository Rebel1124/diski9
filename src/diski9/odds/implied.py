"""Bookmaker-implied probabilities from consensus reference odds (spec 7.4).

* Raw implied probability = 1 / decimal odds.
* Margin-adjusted probability = (1 / odds_i) / sum(1 / odds) over the market's
  outcomes, computed only when *every* outcome has a valid consensus price.

Calculated from the displayed (2 dp) consensus odds so users can verify them.
These describe the reference market price. They are never compared with, or
subtracted from, the historical indicators (no edge / EV).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from diski9.api_football.markets import MARKET_OUTCOMES, Outcome

from .consensus import MarketConsensus


@dataclass(frozen=True)
class ImpliedProbabilities:
    raw: dict[Outcome, Decimal]
    margin_adjusted: dict[Outcome, Decimal] | None
    overround: Decimal | None  # sum of raw implied probabilities minus 1
    reason_unavailable: str | None = None


def implied(mc: MarketConsensus) -> ImpliedProbabilities:
    prices = {o: oc.consensus_odds for o, oc in mc.outcomes.items() if oc.consensus_odds}
    raw = {o: Decimal(1) / p for o, p in prices.items()}
    required = MARKET_OUTCOMES[mc.market]
    if set(prices) != required:
        reason = "no consensus prices" if not prices else "incomplete outcome set"
        return ImpliedProbabilities(raw, None, None, reason)
    total = sum(raw.values())
    return ImpliedProbabilities(raw, {o: r / total for o, r in raw.items()}, total - 1)
