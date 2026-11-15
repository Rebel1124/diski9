"""Read-only data service for the Dash app.

Reads the screener cache, the odds tables and official standings from the local
database. It never calls API-Football, so page interactions cost no requests.
Loaded data is kept in memory for ``ttl_seconds`` (default 5 minutes).
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
from diski9.odds.consensus import MarketConsensus, fixture_consensus, load_bookmakers
from diski9.odds.implied import ImpliedProbabilities, implied
from diski9.screener import cache
from diski9.screener.engine import ENGINE_VERSION
from diski9.screener.rank import rank

LEAGUE_SHORT = {39: "EPL", 288: "PSL", 40: "Championship", 289: "PSL 1st Div"}
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
DIRECTIONS = {
    "1X2": [
        ("home_stronger", "Strongest home-team advantage"),
        ("away_stronger", "Strongest away-team advantage"),
        ("evenly_matched", "Most evenly matched"),
    ],
    "BTTS": [
        ("btts_yes", "BTTS Yes: highest indicator first"),
        ("btts_no", "BTTS No: lowest indicator first"),
    ],
    "OU25": [
        ("over", "Over 2.5: highest indicator first"),
        ("under", "Under 2.5: lowest indicator first"),
    ],
}


@dataclass
class OddsView:
    markets: dict[Market, MarketConsensus]
    implied: dict[Market, ImpliedProbabilities]
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

    @property
    def stale(self) -> bool:
        """True when fixtures were ingested after the cache was last refreshed."""
        return bool(
            self.cache_verified_at
            and self.fixtures_updated_at
            and self.fixtures_updated_at > self.cache_verified_at
        )


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
                for basis in ("venue", "overall")
            }
            ids = set(results["venue"]) | set(results["overall"])
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
                payload = results["venue"].get(fid) or results["overall"][fid]
                comp = payload["fixture"]["competition_id"]
                seasons.add((comp, payload["fixture"]["season"]))
                markets = fixture_consensus(conn, fid, now, books=books)
                odds[fid] = OddsView(
                    markets, {m: implied(mc) for m, mc in markets.items()}, comp in comps_with_odds
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
        return Snapshot(now, results, odds, standings, meta[0], meta[1], fx_updated, leagues)

    # ------------------------------------------------------------ formatting
    def local(self, dt: datetime | str | None, fmt: str = "%a %d %b %H:%M") -> str:
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
        comps = sorted({r["fixture"]["competition_id"] for r in snap.results["venue"].values()})
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
    ) -> list[dict]:
        snap = self.snapshot()
        results = list(snap.results.get(basis, {}).values())
        if leagues:
            results = [r for r in results if r["fixture"]["competition_id"] in leagues]
        if start or end:

            def in_range(r: dict) -> bool:
                d = datetime.fromisoformat(r["fixture"]["kickoff"]).astimezone(self.tz).date()
                return (start is None or d >= start) and (end is None or d <= end)

            results = [r for r in results if in_range(r)]
        return rank(results, direction, threshold)  # type: ignore[arg-type]

    def table_rows(self, market: str, results: list[dict]) -> list[dict[str, Any]]:
        snap = self.snapshot()
        rows = []
        for r in results:
            f, t, mr = r["fixture"], r["teams"], r["match_result"]
            ov = snap.odds.get(f["id"])
            row: dict[str, Any] = {
                "id": f["id"],
                "kickoff": self.local(f["kickoff"], "%Y-%m-%d %H:%M"),
                "league": LEAGUE_SHORT.get(f["competition_id"], f["competition"]),
                "home": f["home"],
                "away": f["away"],
            }
            if market == "1X2":
                diff = (
                    mr["venue_adjusted_difference"]
                    if r["basis"] == "venue"
                    else mr["raw_difference"]
                )
                row.update(
                    home_metric=_round(mr["home_form"]),
                    away_metric=_round(mr["away_form"]),
                    indicator=_round(diff),
                    sample=_samples(t, "form"),
                    limited="⚠ Limited data" if r["limited_data"]["form"] else "",
                )
                key = Market.MATCH_RESULT
            else:
                gk = "btts" if market == "BTTS" else "over_2_5"
                block = r["btts"] if market == "BTTS" else r["over_under_2_5"]
                yes = block["yes_indicator"] if market == "BTTS" else block["over_indicator"]
                row.update(
                    home_metric=(t["home"]["goals"][gk] or {}).get("display", "—"),
                    away_metric=(t["away"]["goals"][gk] or {}).get("display", "—"),
                    indicator=_round(yes, 4),
                    complement=_round(1 - yes, 4) if yes is not None else None,
                    sample=_samples(t, "goals"),
                    limited="⚠ Limited data" if r["limited_data"]["goals"] else "",
                )
                key = Market.BTTS if market == "BTTS" else Market.OVER_UNDER_25
            row["odds"] = self.odds_cell(ov, key)
            rows.append(row)
        return rows

    def odds_cell(self, ov: OddsView | None, market: Market) -> str:
        if ov is None or not ov.markets[market].displayable:
            return "No odds" if ov is None or not ov.league_has_odds else "Unavailable"
        mc = ov.markets[market]
        return " · ".join(
            str(mc.outcomes[o].consensus_odds) if mc.outcomes[o].consensus_odds else "—"
            for o in MARKET_OUTCOME_ORDER[market]
        )

    def detail(self, fixture_id: int, basis: str) -> tuple[dict | None, OddsView | None, dict]:
        snap = self.snapshot()
        r = snap.results.get(basis, {}).get(fixture_id)
        if r is None:
            return None, None, {}
        return r, snap.odds.get(fixture_id), snap.standings.get(r["fixture"]["competition_id"], {})


def _samples(teams: dict, key: str) -> str:
    return f"{teams['home'][key]['sample']['matches']} / {teams['away'][key]['sample']['matches']}"


def _round(x: float | None, places: int = 2) -> float | None:
    return None if x is None else round(x, places)
