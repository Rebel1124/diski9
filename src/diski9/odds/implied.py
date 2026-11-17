"""Bookmaker-implied probabilities from consensus reference odds (spec 7.4).

* Raw implied probability = 1 / decimal odds.
* Margin-adjusted probability = (1 / odds_i) / sum(1 / odds) over the market's
  outcomes, computed only when *every* outcome has a valid consensus price.

Calculated from the displayed (2 dp) consensus odds so users can verify them.
These describe the reference market price and are never a Goal Model input.
:func:`normalise` is the single implementation of margin removal; the downstream
model-vs-market comparison (``diski9.odds.value``) reuses these values.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from diski9.api_football.markets import MARKET_OUTCOMES, Outcome

from .consensus import MarketConsensus


@dataclass(frozen=True)
class ImpliedProbabilities:
    raw: dict[Outcome, Decimal]
    margin_adjusted: dict[Outcome, Decimal] | None
    overround: Decimal | None  # sum of raw implied probabilities minus 1
    reason_unavailable: str | None = None


def normalise(prices: dict, required: set | frozenset) -> dict | None:
    """Proportional margin removal: (1 / odds_i) / sum(1 / odds).

    Returns None unless every required outcome has a valid decimal price (> 1).
    Missing prices are never treated as zero.
    """
    valid = {}
    for o, p in prices.items():
        try:
            d = Decimal(str(p)) if p is not None else None
        except InvalidOperation:
            d = None
        if d is not None and d.is_finite() and d > 1:
            valid[o] = d
    if set(valid) != set(required):
        return None
    raw = {o: Decimal(1) / p for o, p in valid.items()}
    total = sum(raw.values())
    return {o: r / total for o, r in raw.items()}


def implied(mc: MarketConsensus) -> ImpliedProbabilities:
    prices = {o: oc.consensus_odds for o, oc in mc.outcomes.items() if oc.consensus_odds}
    raw = {o: Decimal(1) / p for o, p in prices.items()}
    required = MARKET_OUTCOMES[mc.market]
    if set(prices) != required:
        reason = "no consensus prices" if not prices else "incomplete outcome set"
        return ImpliedProbabilities(raw, None, None, reason)
    return ImpliedProbabilities(raw, normalise(prices, required), sum(raw.values()) - 1)
