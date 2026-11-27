"""Model vs market comparison: probability edge and expected value (EV).

A downstream analytical layer. It reads Goal Model 1.0 probabilities (or a Match
Lab user's adjusted probabilities) and the displayed consensus reference odds,
and never feeds anything back into the model, its cache or forecast snapshots.

Definitions (one implementation, used by the Screener and The Match Lab):

* **Market probability** - the margin-adjusted probability from
  :func:`diski9.odds.implied.normalise`: (1 / odds_i) / sum(1 / odds) over the
  complete outcome set (1X2: Home/Draw/Away; BTTS: Yes/No; OU 2.5: Over/Under).
  Unavailable unless every outcome has a valid price.
* **Probability edge (pp)** = 100 x (probability - market probability), in
  percentage points.
* **Expected value** = probability x decimal odds - 1, using the *original*
  displayed odds (never margin-adjusted). Needs only that outcome's price.

Odds source policy: the odds are Diski 9's **consensus reference odds** - for each
outcome, the median price across independent, eligible bookmakers that each quote
the complete market within the freshness window (``diski9.odds.consensus``). They
are the odds displayed in the app, but they are not an offer from any single
bookmaker, so EV is a *reference* value at those odds, not a directly obtainable
return. Screener rankings use fresh consensus only; stale prices are shown only in
the match detail, labelled stale.

A value that rounds to zero at display precision (0.1 pp / 0.1%) is treated as
zero, so nothing shown as "+0.0" is ever called positive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from diski9.api_football.markets import MARKET_OUTCOMES, Market, Outcome

from .implied import normalise

OUTCOME_KEY = {
    Outcome.HOME: "home",
    Outcome.DRAW: "draw",
    Outcome.AWAY: "away",
    Outcome.BTTS_YES: "btts_yes",
    Outcome.BTTS_NO: "btts_no",
    Outcome.OVER_25: "over",
    Outcome.UNDER_25: "under",
}
MARKET_ORDER = {
    Market.MATCH_RESULT: (Outcome.HOME, Outcome.DRAW, Outcome.AWAY),
    Market.BTTS: (Outcome.BTTS_YES, Outcome.BTTS_NO),
    Market.OVER_UNDER_25: (Outcome.OVER_25, Outcome.UNDER_25),
}


def edge_pp(probability: float, market_probability: float) -> float:
    """Probability edge in percentage points (55% vs 48% -> +7.0)."""
    return (probability - market_probability) * 100


def expected_value(probability: float, odds: float | Decimal | None) -> float | None:
    """EV per unit staked at the given decimal odds: p x odds - 1 (0.55 @ 2.10 -> 0.155).

    None when there is no valid price (missing, non-numeric or <= 1)."""
    try:
        o = float(odds) if odds is not None else None
    except (TypeError, ValueError):
        return None
    if o is None or not math.isfinite(o) or o <= 1:
        return None
    return probability * o - 1


def positive_edge(value: float | None) -> bool:
    return value is not None and round(value, 1) > 0


def positive_ev(value: float | None) -> bool:
    return value is not None and round(value * 100, 1) > 0


@dataclass(frozen=True)
class OutcomeValue:
    key: str  # model probability key: home, draw, away, btts_yes, ...
    outcome: Outcome
    probability: float  # the model's (or user's) probability, 0-1
    odds: Decimal | None  # displayed consensus odds (original, with margin)
    market_probability: float | None  # margin-adjusted, 0-1
    edge: float | None  # percentage points
    ev: float | None  # per unit staked, e.g. 0.155
    min_odds: Decimal | None = None  # lowest bookmaker price behind the consensus
    max_odds: Decimal | None = None  # highest bookmaker price behind the consensus


@dataclass(frozen=True)
class MarketValue:
    market: Market
    outcomes: tuple[OutcomeValue, ...]
    complete: bool  # every outcome priced, so market probabilities and edges exist

    def best_edge(self, min_market_probability: float | None = None) -> OutcomeValue | None:
        """Outcome with the largest positive edge (None if no positive edge)."""
        return _best(self.outcomes, "edge", positive_edge, min_market_probability)

    def best_ev(self, min_market_probability: float | None = None) -> OutcomeValue | None:
        """Outcome with the highest positive EV, chosen independently of the edge."""
        return _best(self.outcomes, "ev", positive_ev, min_market_probability)

    def considered(self, min_market_probability: float | None = None) -> tuple[OutcomeValue, ...]:
        return tuple(o for o in self.outcomes if meets_market(o, min_market_probability))


def meets_market(o: OutcomeValue, minimum: float | None) -> bool:
    """Phase 8 CP3A-3 (OD-4): the Minimum Market Probability applies to the outcome's
    actual margin-adjusted market probability, inclusively; never to the model's.
    Without a minimum every outcome qualifies; with one, an outcome without a market
    probability does not."""
    if minimum is None:
        return True
    return o.market_probability is not None and o.market_probability >= minimum - 1e-12


def _best(outcomes, attr, is_positive, min_market_probability) -> OutcomeValue | None:
    candidates = [
        o
        for o in outcomes
        if meets_market(o, min_market_probability) and is_positive(getattr(o, attr))
    ]
    # ties: market order (first outcome listed wins), via max's stability
    return max(candidates, key=lambda o: getattr(o, attr), default=None)


def compare(market: Market, probabilities: dict, consensus) -> MarketValue | None:
    """Edge and EV for every outcome of ``market``.

    ``probabilities`` maps model keys (home, draw, ...) to 0-1 values. ``consensus``
    is a :class:`~diski9.odds.consensus.MarketConsensus` (or None). Returns None when
    there are no probabilities or no consensus prices at all.
    """
    if not probabilities or consensus is None:
        return None
    order = MARKET_ORDER[market]
    prices = {o: consensus.outcomes[o].consensus_odds for o in order if o in consensus.outcomes}
    adjusted = normalise(prices, MARKET_OUTCOMES[market])
    rows = []
    for o in order:
        key = OUTCOME_KEY[o]
        p = probabilities.get(key)
        if p is None:
            return None
        oc = consensus.outcomes.get(o)
        price = oc.consensus_odds if oc else None
        mp = float(adjusted[o]) if adjusted else None
        rows.append(
            OutcomeValue(
                key=key,
                outcome=o,
                probability=float(p),
                odds=price,
                market_probability=mp,
                edge=edge_pp(float(p), mp) if mp is not None else None,
                ev=expected_value(float(p), price),
                min_odds=oc.min_odds if oc else None,
                max_odds=oc.max_odds if oc else None,
            )
        )
    if not any(r.odds for r in rows):
        return None
    return MarketValue(market, tuple(rows), adjusted is not None)


# ------------------------------------------------------------ formatting
def edge_text(value: float | None) -> str:
    if value is None:
        return "—"
    v = round(value, 1)
    return f"{v:+.1f} pp" if v else "0.0 pp"


def ev_text(value: float | None) -> str:
    if value is None:
        return "EV unavailable"
    v = round(value * 100, 1)
    return f"{v:+.1f}%" if v else "0.0%"


def sign_class(value: float | None, positive) -> str:
    """'pos' / 'neg' / 'zero' / 'na' for styling (signs are always in the text too)."""
    if value is None:
        return "na"
    if positive(value):
        return "pos"
    return "neg" if positive(-value) else "zero"
