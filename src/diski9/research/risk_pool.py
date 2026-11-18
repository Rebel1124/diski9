"""Research only (Phase 6A.1): build a complete, point-in-time Challenge outcome pool.

For a challenge window, every fixture in the eight supported leagues with an
available Goal Model 1.0 forecast is read, and for every market (1X2, BTTS,
Over/Under 2.5) the **strict** Challenge consensus is evaluated *as of* a fixed
time with the existing rules (``challenge_consensus``: fresh within 24 h, >= 3
independent bookmaker groups, complete market). Nothing is recalculated or
relaxed. Each outcome carries:

* the Goal Model 1.0 probability (screener cache, overall basis, unchanged);
* the consensus decimal odds (2 dp) and the margin-adjusted market probability
  (``implied``: proportional normalisation of the complete outcome set);
* the bookmaker-group count and eligibility.

Each fixture also carries the model's estimated goals and, where the market
supports it, market-implied goal rates (``market_implied_xg.fit``) for the
market-truth simulation scenario.

The database is only read. The output is a research snapshot, not a Challenge
round sheet.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine, select

from diski9.api_football.markets import Market
from diski9.db.schema import fixtures
from diski9.ingestion.classify import UPCOMING_STATUSES
from diski9.leagues import odds_competitions
from diski9.odds.display import challenge_consensus
from diski9.odds.implied import implied
from diski9.odds.value import MARKET_ORDER, OUTCOME_KEY
from diski9.screener import cache

from . import market_implied_xg as mx

MARKETS = (Market.MATCH_RESULT, Market.BTTS, Market.OVER_UNDER_25)


def build_pool(engine: Engine, as_of: datetime, start: datetime, end: datetime) -> dict:
    """Read-only, point-in-time pool of every outcome for fixtures in [start, end)."""
    from diski9.odds.consensus import fixture_consensus, load_bookmakers

    out = []
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
            )
            .order_by(fixtures.c.kickoff_utc, fixtures.c.id)
        ).all()
        for fx in rows:
            r = payloads.get(fx.id)
            gm = (r or {}).get("goal_model") or {}
            strict = challenge_consensus(conn, fx.id, as_of, books=books)
            shown = fixture_consensus(conn, fx.id, as_of, books=books)
            outcomes, market_probs = [], {}
            for m in MARKETS:
                mc = strict[m]
                any_mc = shown[m]
                ip = implied(any_mc) if any_mc.displayable else None
                adj = ip.margin_adjusted if ip else None
                if mc is not None and adj:
                    market_probs[m.value] = tuple(float(adj[o]) for o in MARKET_ORDER[m])
                for o in MARKET_ORDER[m]:
                    oc = any_mc.outcomes.get(o)
                    outcomes.append(
                        {
                            "market": m.value,
                            "outcome": o.value,
                            "key": OUTCOME_KEY[o],
                            "p_model": float(gm["probabilities"][OUTCOME_KEY[o]])
                            if gm.get("available")
                            else None,
                            "p_market": float(adj[o]) if adj else None,
                            "odds": str(oc.consensus_odds) if oc and oc.consensus_odds else None,
                            "groups": any_mc.sources,
                            "eligible": bool(mc is not None and adj and gm.get("available")),
                        }
                    )
            lam_market = None
            if market_probs:
                res = mx.fit(
                    mx.MarketInputs(
                        p1x2=market_probs.get("1X2"),
                        btts=market_probs.get("BTTS"),
                        ou25=market_probs.get("OU25"),
                    )
                )
                if res.lambda_home is not None and res.status in ("good_fit", "approximate_fit"):
                    lam_market = [res.lambda_home, res.lambda_away, res.status]
            eg = gm.get("estimated_goals") or {}
            out.append(
                {
                    "fixture_id": fx.id,
                    "league_id": fx.competition_id,
                    "kickoff": fx.kickoff_utc.isoformat(),
                    "match": f"{r['fixture']['home']} v {r['fixture']['away']}"
                    if r
                    else str(fx.id),
                    "model_available": bool(gm.get("available")),
                    "lambda_model": [eg.get("home"), eg.get("away")] if eg else None,
                    "lambda_market": lam_market,
                    "outcomes": outcomes,
                }
            )
    return {
        "as_of": as_of.isoformat(),
        "window": [start.isoformat(), end.isoformat()],
        "note": "Research snapshot (read-only, point-in-time); not a Challenge round sheet.",
        "fixtures": out,
    }
