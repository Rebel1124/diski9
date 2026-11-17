"""Read-only data service for the Dash app.

Reads the screener cache, the odds tables and official standings from the local
database. It never calls API-Football, so page interactions (tabs, ranking,
filters, pagination, expanding details) cost no requests. Loaded data is kept in
memory for ``ttl_seconds`` (default 5 minutes).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, false, func, select

from diski9.api_football.markets import Market, Outcome
from diski9.db.schema import competitions, fixtures, odds_quotes, screener_results
from diski9.ingestion.reference import latest_standings
from diski9.odds.consensus import load_bookmakers
from diski9.odds.display import DisplayedMarket, display_consensus
from diski9.odds.value import (
    MarketValue,
    OutcomeValue,
    compare,
    edge_text,
    ev_text,
    positive_edge,
    positive_ev,
    sign_class,
)
from diski9.screener import cache
from diski9.screener.engine import ENGINE_VERSION
from diski9.screener.rank import DEFAULT_DIRECTION, VALUE_DIRECTIONS, rank, rank_by_value

PAGE_SIZE = 10
LEAGUE_SHORT = {
    39: "EPL",
    40: "Championship",
    288: "PSL",
    289: "PSL 1st Div",
    140: "La Liga",
    61: "Ligue 1",
    78: "Bundesliga",
    135: "Serie A",
}
MARKET_OF = {"1X2": Market.MATCH_RESULT, "BTTS": Market.BTTS, "OU25": Market.OVER_UNDER_25}
MARKET_OUTCOME_ORDER = {
    Market.MATCH_RESULT: (Outcome.HOME, Outcome.DRAW, Outcome.AWAY),
    Market.BTTS: (Outcome.BTTS_YES, Outcome.BTTS_NO),
    Market.OVER_UNDER_25: (Outcome.OVER_25, Outcome.UNDER_25),
}
OUTCOME_LABEL = {
    Outcome.HOME: "Home",
    Outcome.DRAW: "Draw",
    Outcome.AWAY: "Away",
    Outcome.BTTS_YES: "Yes",
    Outcome.BTTS_NO: "No",
    Outcome.OVER_25: "Over 2.5",
    Outcome.UNDER_25: "Under 2.5",
}
KICKOFF_OPTIONS = [
    ("kickoff_earliest", "Kickoff: earliest first"),
    ("kickoff_latest", "Kickoff: latest first"),
]
# Model vs market rankings (model baseline vs fresh consensus odds; see odds/value.py)
VALUE_OPTIONS = [
    ("edge", "Highest model vs market edge"),
    ("ev", "Highest expected value (EV)"),
]
DIRECTIONS = {
    # Engine 3.0: ranked by the Goal Model 1.0 probability of the outcome
    "1X2": KICKOFF_OPTIONS
    + [
        ("home_win", "Highest home-win probability"),
        ("draw", "Highest draw probability"),
        ("away_win", "Highest away-win probability"),
    ]
    + VALUE_OPTIONS,
    "BTTS": KICKOFF_OPTIONS
    + [
        ("btts_yes", "Highest BTTS Yes probability"),
        ("btts_no", "Highest BTTS No probability"),
    ]
    + VALUE_OPTIONS,
    "OU25": KICKOFF_OPTIONS
    + [
        ("over", "Highest Over 2.5 probability"),
        ("under", "Highest Under 2.5 probability"),
    ]
    + VALUE_OPTIONS,
}
MARKET_KEYS = {  # model probability keys per market, in display order
    "1X2": (("home", "Home win"), ("draw", "Draw"), ("away", "Away win")),
    "BTTS": (("btts_yes", "Yes"), ("btts_no", "No")),
    "OU25": (("over", "Over 2.5"), ("under", "Under 2.5")),
}


def pct1(p: float | None) -> str:
    """Probability as a percentage with one decimal (e.g. 60.1%)."""
    return "—" if p is None else f"{p * 100:.1f}%"


def goals2(x: float | None) -> str:
    return "—" if x is None else f"{x:.2f}"


def record_short(rate: dict | None) -> str:
    """'7/10' for a team record; '—' when the team has no current-season history."""
    if not rate or not rate["matches"]:
        return "—"
    return f"{rate['hits']}/{rate['matches']}"


# Outcome identity colours (style.css --out-home / --out-draw / --out-away). They name
# the outcome; they never signal that a value is positive or profitable.
OUTCOME_COLOUR_KEY = {Outcome.HOME: "home", Outcome.DRAW: "draw", Outcome.AWAY: "away"}
_ODDS_ORDER = {"1X2": "home · draw · away", "BTTS": "yes · no", "OU25": "over · under"}


def valid_direction(market: str, direction: str | None) -> str:
    return direction if direction in dict(DIRECTIONS[market]) else DEFAULT_DIRECTION


@dataclass
class OddsView:
    markets: dict[Market, DisplayedMarket]
    league_has_odds: bool


@dataclass
class Snapshot:
    loaded_at: datetime
    results: dict[str, dict[int, dict]]  # basis -> fixture_id -> payload
    odds: dict[int, OddsView]
    standings: dict[int, dict]  # competition_id -> team_id -> official row
    cache_calculated_at: datetime | None
    cache_verified_at: datetime | None
    fixtures_updated_at: datetime | None
    leagues: dict[int, str] = field(default_factory=dict)
    outdated_rows: int = 0  # active cache rows from another engine version

    @property
    def stale(self) -> bool:
        """True when fixtures were ingested after the cache was last refreshed."""
        return bool(
            self.cache_verified_at
            and self.fixtures_updated_at
            and self.fixtures_updated_at > self.cache_verified_at
        )


@dataclass(frozen=True)
class Page:
    results: list[dict]
    page: int
    pages: int
    total: int
    first: int  # 1-based index of the first fixture on the page (0 if empty)
    last: int

    @property
    def summary(self) -> str:
        if not self.total:
            return ""
        noun = "fixture" if self.total == 1 else "fixtures"
        return f"Showing {self.first}–{self.last} of {self.total} {noun}"


def paginate(results: list[dict], page: int, size: int = PAGE_SIZE) -> Page:
    total = len(results)
    pages = max(1, -(-total // size))
    page = min(max(1, page), pages)
    start = (page - 1) * size
    chunk = results[start : start + size]
    return Page(chunk, page, pages, total, start + 1 if chunk else 0, start + len(chunk))


class ScreenerData:
    def __init__(
        self,
        engine: Engine,
        ttl_seconds: float = 300,
        tz: str = "Africa/Johannesburg",
        clock=None,
    ):
        self.engine = engine
        self.clock = clock or (lambda: datetime.now(UTC))
        self.ttl = ttl_seconds
        self.tz = ZoneInfo(tz)
        self._snap: Snapshot | None = None
        self._loaded_monotonic = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------- loading
    def snapshot(self, force: bool = False) -> Snapshot:
        with self._lock:
            if force or self._snap is None or time.monotonic() - self._loaded_monotonic > self.ttl:
                self._snap = self._load()
                self._loaded_monotonic = time.monotonic()
            return self._snap

    def _load(self) -> Snapshot:
        now = self.clock()
        with self.engine.connect() as conn:
            results = {
                basis: {
                    r["fixture"]["id"]: r
                    for r in cache.cached(conn, basis)
                    if datetime.fromisoformat(r["fixture"]["kickoff"]) > now
                }
                for basis in ("overall",)  # Engine 3.0 computes the overall basis only
            }
            ids = set(results["overall"])
            books = load_bookmakers(conn)
            comps_with_odds = {
                r[0]
                for r in conn.execute(
                    select(fixtures.c.competition_id)
                    .join(odds_quotes, odds_quotes.c.fixture_id == fixtures.c.id)
                    .distinct()
                )
            }
            odds: dict[int, OddsView] = {}
            seasons: set[tuple[int, int]] = set()
            for fid in ids:
                payload = results["overall"][fid]
                comp = payload["fixture"]["competition_id"]
                seasons.add((comp, payload["fixture"]["season"]))
                odds[fid] = OddsView(
                    display_consensus(conn, fid, now, books=books), comp in comps_with_odds
                )
            standings = {comp: latest_standings(conn, comp, season) for comp, season in seasons}
            meta = conn.execute(
                select(
                    func.max(screener_results.c.calculated_at),
                    func.min(screener_results.c.verified_at),
                ).where(
                    screener_results.c.superseded_at.is_(None),
                    screener_results.c.engine_version == ENGINE_VERSION,
                    screener_results.c.fixture_id.in_(ids) if ids else false(),
                )
            ).one()
            comp_ids = {c for c, _ in seasons}
            fx_updated = (
                conn.execute(
                    select(func.max(fixtures.c.updated_at)).where(
                        fixtures.c.competition_id.in_(comp_ids)
                    )
                ).scalar()
                if comp_ids
                else None
            )
            leagues = dict(conn.execute(select(competitions.c.id, competitions.c.name)).all())
            outdated = conn.execute(
                select(func.count()).where(
                    screener_results.c.superseded_at.is_(None),
                    screener_results.c.engine_version != ENGINE_VERSION,
                )
            ).scalar()
        return Snapshot(
            now, results, odds, standings, meta[0], meta[1], fx_updated, leagues, outdated or 0
        )

    # ------------------------------------------------------------ formatting
    def local(self, dt: datetime | str | None, fmt: str = "%a %d %b, %H:%M") -> str:
        """Readable local time, e.g. 'Sat 21 Nov, 14:30' (UTC values are unchanged)."""
        if dt is None:
            return "—"
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        return dt.astimezone(self.tz).strftime(fmt)

    @property
    def tz_label(self) -> str:
        return self.clock().astimezone(self.tz).strftime("%Z") or str(self.tz)

    def available_leagues(self) -> list[tuple[int, str]]:
        snap = self.snapshot()
        comps = sorted({r["fixture"]["competition_id"] for r in snap.results["overall"].values()})
        return [(c, LEAGUE_SHORT.get(c, snap.leagues.get(c, str(c)))) for c in comps]

    # ------------------------------------------------------------------ rows
    def filtered(
        self,
        market: str,
        leagues: list[int] | None,
        start: date | None,
        end: date | None,
        basis: str,
        direction: str,
        threshold: float | None,
        odds_only: bool = False,
    ) -> list[dict]:
        """Filter first, then rank (deterministic). ``odds_only`` keeps fixtures whose
        selected market has usable bookmaker odds (fresh or stale), using the same
        availability as the odds column (``odds_summary``)."""
        snap = self.snapshot()
        results = list(snap.results.get("overall", {}).values())
        if leagues is not None:
            results = [r for r in results if r["fixture"]["competition_id"] in leagues]
        if start or end:

            def in_range(r: dict) -> bool:
                d = datetime.fromisoformat(r["fixture"]["kickoff"]).astimezone(self.tz).date()
                return (start is None or d >= start) and (end is None or d <= end)

            results = [r for r in results if in_range(r)]
        if odds_only:
            results = [r for r in results if self.has_odds(market, r)]
        direction = valid_direction(market, direction)
        if direction in VALUE_DIRECTIONS:
            return self.rank_value(market, results, direction, threshold)
        return rank(results, direction, threshold)

    # --------------------------------------------------- model vs market value
    def market_value(self, market: str, r: dict, fresh_only: bool = True) -> MarketValue | None:
        """Model baseline vs consensus odds for the fixture's market. The Screener uses
        fresh consensus only (``fresh_only``); the match detail also shows stale prices."""
        gm = r.get("goal_model") or {}
        if not gm.get("available"):
            return None
        ov = self.snapshot().odds.get(r["fixture"]["id"])
        if ov is None:
            return None
        dm = ov.markets[MARKET_OF[market]]
        if dm.status == "unavailable" or (fresh_only and dm.status != "fresh"):
            return None
        return compare(MARKET_OF[market], gm["probabilities"], dm.consensus)

    def value_pick(
        self, market: str, r: dict, direction: str, threshold: float | None
    ) -> tuple[MarketValue | None, OutcomeValue | None]:
        """(market comparison, highlighted outcome). Edge and EV are chosen
        independently over every outcome the model rates at least ``threshold``."""
        mv = self.market_value(market, r)
        if mv is None:
            return None, None
        return mv, (mv.best_ev(threshold) if direction == "ev" else mv.best_edge(threshold))

    def rank_value(
        self, market: str, results: list[dict], direction: str, threshold: float | None
    ) -> list[dict]:
        """Edge / EV ranking over the full filtered set (before pagination). The
        threshold keeps its meaning - a minimum *model* probability: fixtures with no
        outcome that likely are removed, and only such outcomes are considered."""
        if threshold is not None:
            keys = [k for k, _ in MARKET_KEYS[market]]

            def qualifies(r: dict) -> bool:
                gm = r.get("goal_model") or {}
                probs = gm.get("probabilities") or {}
                return bool(gm.get("available")) and any(probs.get(k, 0) >= threshold for k in keys)

            results = [r for r in results if qualifies(r)]

        def value_of(r: dict) -> tuple[bool, float | None]:
            mv, pick = self.value_pick(market, r, direction, threshold)
            has = mv is not None and (mv.complete if direction == "edge" else True)
            if pick is None:
                return has, None
            return True, pick.ev if direction == "ev" else pick.edge

        return rank_by_value(results, value_of)

    def value_cell(
        self, market: str, r: dict, direction: str, threshold: float | None = None
    ) -> dict[str, Any]:
        """The compact final column: the single strongest outcome (best edge, or best
        EV when ranking by EV). Two short lines plus a hover title with the odds."""
        ov = self.snapshot().odds.get(r["fixture"]["id"])
        status, odds_text = self.odds_summary(ov, MARKET_OF[market])
        mode = "ev" if direction == "ev" else "edge"
        cell: dict[str, Any] = {
            "mode": mode,
            "status": status,
            "main": None,
            "sub": None,
            "cls": "na",
            "title": None,
            "outcome": None,  # 1X2 outcome colour key, set only for a positive value
        }
        if status == "unavailable":
            cell["main"] = odds_text  # "No odds" (league without odds) or "—"
            return cell
        cell["title"] = (
            f"Consensus odds {odds_text} ({_ODDS_ORDER[market]}). Market % has the bookmaker "
            "margin removed. Reference prices, not an offer from any single bookmaker."
        )
        if status == "stale":
            cell.update(main="Prices stale", sub="Not ranked")
            return cell
        mv, pick = self.value_pick(market, r, mode, threshold)
        if mv is None:
            cell["main"] = "No model" if not (r.get("goal_model") or {}).get("available") else "—"
            return cell
        if mode == "edge" and not mv.complete:
            cell.update(main="Incomplete market", sub="Edge unavailable")
            return cell
        if pick is None:
            cell.update(main="No positive edge" if mode == "edge" else "No positive EV")
            cell["cls"] = "zero"
            return cell
        label = OUTCOME_LABEL[pick.outcome]
        if market == "1X2":  # Home / Draw / Away colours identify the outcome only
            cell["outcome"] = OUTCOME_COLOUR_KEY.get(pick.outcome)
        if mode == "edge":
            cell.update(
                main=f"{label} {edge_text(pick.edge)}",
                sub=f"Market {pct1(pick.market_probability)}",
                cls=sign_class(pick.edge, positive_edge),
            )
        else:
            cell.update(
                main=f"{label} {ev_text(pick.ev)} EV",
                sub=f"at {pick.odds}",
                cls=sign_class(pick.ev, positive_ev),
            )
        return cell

    def has_odds(self, market: str, r: dict) -> bool:
        """True when the fixture shows usable odds for the market (fresh or stale),
        i.e. anything but the 'No odds' / unavailable state."""
        ov = self.snapshot().odds.get(r["fixture"]["id"])
        status, _ = self.odds_summary(ov, MARKET_OF[market])
        return status in ("fresh", "stale")

    def row(self, market: str, r: dict) -> dict[str, Any]:
        """Display-ready values for one fixture row/card (Goal Model 1.0)."""
        snap = self.snapshot()
        f = r["fixture"]
        gm = r.get("goal_model") or {}
        ov = snap.odds.get(f["id"])
        available = bool(gm.get("available"))
        probs = gm.get("probabilities") or {}
        eg = gm.get("estimated_goals") or {}
        out: dict[str, Any] = {
            "id": f["id"],
            "kickoff": self.local(f["kickoff"]),
            "league": LEAGUE_SHORT.get(f["competition_id"], f["competition"]),
            "home": f["home"],
            "away": f["away"],
            "available": available,
            "unavailable_reason": None if available else gm.get("message", "Not available"),
            "estimated_goals": f"{goals2(eg.get('home'))} – {goals2(eg.get('away'))}"
            if available
            else "—",
            "limited": bool(gm.get("early_season")),
        }
        for key, _ in MARKET_KEYS[market]:
            out[f"p_{key}"] = pct1(probs.get(key)) if available else "—"
        mstatus, mtext = self.market_summary(ov, MARKET_OF[market])
        status, odds_text = self.odds_summary(ov, MARKET_OF[market])
        out.update(market=mtext, market_status=mstatus, odds=odds_text, odds_status=status)
        return out

    def odds_summary(self, ov: OddsView | None, market: Market) -> tuple[str, str]:
        if ov is None:
            return "unavailable", "—"
        dm = ov.markets[market]
        if dm.status == "unavailable":
            return "unavailable", "No odds" if not ov.league_has_odds else "—"
        prices = " · ".join(
            str(dm.consensus.outcomes[o].consensus_odds)
            if dm.consensus.outcomes[o].consensus_odds
            else "—"
            for o in MARKET_OUTCOME_ORDER[market]
        )
        return dm.status, prices

    def market_summary(self, ov: OddsView | None, market: Market) -> tuple[str, str]:
        """Market-implied probabilities for the table (same consensus as the odds strip)."""
        if ov is None:
            return "unavailable", "—"
        dm = ov.markets[market]
        if dm.status == "unavailable":
            return "unavailable", "No odds" if not ov.league_has_odds else "—"
        adj = dm.implied.margin_adjusted if dm.implied else None
        if not adj:
            return "unavailable", "—"
        return dm.status, " · ".join(
            f"{float(adj[o]) * 100:.0f}%" for o in MARKET_OUTCOME_ORDER[market]
        )

    def detail(
        self, fixture_id: int, basis: str = "overall"
    ) -> tuple[dict | None, OddsView | None, dict]:
        snap = self.snapshot()
        r = snap.results.get("overall", {}).get(fixture_id)
        if r is None:
            return None, None, {}
        return r, snap.odds.get(fixture_id), snap.standings.get(r["fixture"]["competition_id"], {})
