"""Research only (Phase 5B): read-only loading of real Challenge-eligible
selections for the portfolio study.

A selection is eligible only if (Phase 5B brief, section 3.3):

* the fixture is in one of the eight supported leagues and in the window,
* it has an available Goal Model 1.0 forecast (screener cache, overall basis),
* the selected market has a fresh consensus that is Challenge-eligible
  (>= 3 independent bookmaker groups, 24 h freshness - the existing rules),
* the selected outcome has a consensus price.

The database is only read (``engine.connect()``); no forecast snapshot, cache row
or odds record is written. The returned snapshot is a *research* snapshot, not
an immutable Weekly Challenge submission snapshot.
"""

from __future__ import annotations

from datetime import datetime
from itertools import zip_longest

from sqlalchemy import Engine, select

from diski9.api_football.markets import Market
from diski9.db.schema import fixtures
from diski9.ingestion.classify import UPCOMING_STATUSES
from diski9.leagues import odds_competitions
from diski9.odds.consensus import fixture_consensus, load_bookmakers
from diski9.odds.implied import implied
from diski9.odds.value import MARKET_ORDER, OUTCOME_KEY
from diski9.screener import cache

from .challenge_portfolio import Selection

MARKETS = (Market.MATCH_RESULT, Market.BTTS, Market.OVER_UNDER_25)


def eligible_candidates(
    engine: Engine, now: datetime, start: datetime, end: datetime
) -> list[dict]:
    """Every eligible (fixture, market, outcome) in the window, read-only.
    Fixtures are returned round-robin across leagues in kickoff order, so slates
    built from the front of the list mix leagues deterministically."""
    with engine.connect() as conn:
        books = load_bookmakers(conn)
        payloads = {r["fixture"]["id"]: r for r in cache.cached(conn, "overall")}
        rows = conn.execute(
            select(fixtures.c.id, fixtures.c.competition_id, fixtures.c.kickoff_utc)
            .where(
                fixtures.c.competition_id.in_(odds_competitions()),
                fixtures.c.status_short.in_(UPCOMING_STATUSES),
                fixtures.c.kickoff_utc >= start,
                fixtures.c.kickoff_utc < end,
                fixtures.c.kickoff_utc > now,
            )
            .order_by(fixtures.c.kickoff_utc, fixtures.c.id)
        ).all()
        by_league: dict[int, list[dict]] = {}
        for fx in rows:
            r = payloads.get(fx.id)
            gm = (r or {}).get("goal_model") or {}
            if not gm.get("available"):
                continue
            cons = fixture_consensus(conn, fx.id, now, books=books)
            markets = {}
            for m in MARKETS:
                mc = cons[m]
                if not (mc.displayable and mc.challenge_eligible):
                    continue
                ip = implied(mc)
                outs = {}
                for o in MARKET_ORDER[m]:
                    oc = mc.outcomes.get(o)
                    if oc is None or oc.consensus_odds is None:
                        continue
                    outs[OUTCOME_KEY[o]] = {
                        "outcome": o.value,
                        "p": float(gm["probabilities"][OUTCOME_KEY[o]]),
                        "odds": float(oc.consensus_odds),
                        "market_p": float(ip.margin_adjusted[o]) if ip.margin_adjusted else None,
                    }
                markets[m.value] = {
                    "groups": mc.sources,
                    "latest_observation": mc.latest_observation.isoformat()
                    if mc.latest_observation
                    else None,
                    "provider_updated_at": mc.provider_updated_at.isoformat()
                    if mc.provider_updated_at
                    else None,
                    "outcomes": outs,
                }
            if markets:
                by_league.setdefault(fx.competition_id, []).append(
                    {
                        "fixture_id": fx.id,
                        "league_id": fx.competition_id,
                        "kickoff": fx.kickoff_utc.isoformat(),
                        "home": r["fixture"]["home"],
                        "away": r["fixture"]["away"],
                        "markets": markets,
                    }
                )
    ordered = []
    for group in zip_longest(*(by_league[k] for k in sorted(by_league))):
        ordered.extend(x for x in group if x is not None)
    return ordered


def build_slate(candidates: list[dict], rule, n: int = 9) -> list[dict]:
    """Walk the candidate list; ``rule(fixture, position)`` returns the chosen
    ``(market, outcome_key)`` or None. Stops at ``n`` distinct fixtures."""
    out = []
    for fx in candidates:
        pick = rule(fx, len(out))
        if pick is None:
            continue
        market, key = pick
        mk = fx["markets"][market]
        o = mk["outcomes"][key]
        out.append(
            {
                "fixture_id": fx["fixture_id"],
                "league_id": fx["league_id"],
                "kickoff": fx["kickoff"],
                "match": f"{fx['home']} v {fx['away']}",
                "market": market,
                "outcome": o["outcome"],
                "p": o["p"],
                "odds": o["odds"],
                "market_p": o["market_p"],
                "bookmaker_groups": mk["groups"],
                "latest_observation": mk["latest_observation"],
                "provider_updated_at": mk["provider_updated_at"],
            }
        )
        if len(out) == n:
            break
    return out


# Deterministic selection rules (documented in the report) ------------------
def rule_model_favourite(fx, _pos):
    m = fx["markets"].get("1X2")
    if not m:
        return None
    return "1X2", max(m["outcomes"], key=lambda k: (m["outcomes"][k]["p"], k))


def rule_mixed_markets(fx, pos):
    market = ("1X2", "BTTS", "OU25")[pos % 3]
    m = fx["markets"].get(market)
    if not m:
        return None
    return market, max(m["outcomes"], key=lambda k: (m["outcomes"][k]["p"], k))


def rule_largest_edge(fx, _pos):
    best = None
    for market, m in fx["markets"].items():
        for k, o in m["outcomes"].items():
            if o["market_p"] is None:
                continue
            e = o["p"] - o["market_p"]
            if e > 0 and (best is None or e > best[0]):
                best = (e, market, k)
    return None if best is None else (best[1], best[2])


def rule_mid_probability(fx, _pos, lo=0.30, hi=0.50, target=0.40):
    best = None
    for market, m in fx["markets"].items():
        for k, o in m["outcomes"].items():
            if lo <= o["p"] <= hi:
                d = abs(o["p"] - target)
                if best is None or d < best[0]:
                    best = (d, market, k)
    return None if best is None else (best[1], best[2])


REAL_RULES = {
    "R1 model favourites (1X2)": rule_model_favourite,
    "R2 mixed markets, most likely outcome": rule_mixed_markets,
    "R3 largest positive model edge": rule_largest_edge,
    "R4 mid-probability outcomes (30-50%)": rule_mid_probability,
}


def to_selections(slate: list[dict], use_market_p: bool = False) -> list[Selection]:
    return [
        Selection(
            f"{s['match']} - {s['market']} {s['outcome']}",
            s["market_p"] if use_market_p else s["p"],
            s["odds"],
            {"fixture_id": s["fixture_id"]},
        )
        for s in slate
    ]
