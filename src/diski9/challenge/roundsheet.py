"""Frozen Weekly Challenge round snapshots (Phase 6B).

A :class:`RoundSnapshot` is the complete, immutable input of one round: fixture
details, every candidate outcome (market probability, Goal Model 1.0 probability,
consensus reference odds, bookmaker-group count, observation time) and the
snapshot time and configuration version. Everything downstream - classification,
feasibility, evaluation, submission checks - is assessed **against the snapshot's
own timestamp**, never the wall clock, so a historical demonstration snapshot is
judged exactly as it was when it was taken.

Two sources:

* :func:`build_live_snapshot` - read-only, point-in-time, from the local database.
  It applies the existing strict Challenge consensus unchanged
  (``challenge_consensus``: fresh within 24 hours, at least three independent
  bookmaker groups, complete market, pre-kickoff) and the existing margin
  adjustment (``implied``), plus the Goal Model 1.0 probability from the screener
  cache. Outcomes failing the strict consensus or lacking a model forecast are
  left out of the sheet. No API request is made.
* :func:`snapshot_from_research_pool` - a frozen research pool (for example
  ``docs/research/weekly_challenge_risk/pool_weekend.json``), used only for the
  explicitly labelled **demonstration** round.

The snapshot carries a content fingerprint so a participant's selections can
never be silently carried across snapshots.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from diski9.challenge.config import DEFAULT_CONFIG, ChallengeConfig, get_config
from diski9.challenge.structured import (
    ChallengeOutcome,
    RoundOpeningReport,
    make_outcome,
    round_opening_report,
)

DEADLINE_BUFFER = timedelta(minutes=15)  # D-06 recommendation: earliest kickoff - 15 min


class SnapshotKind(StrEnum):
    LIVE = "live"
    DEMO = "demo"  # historical research snapshot; never presented as an open competition


@dataclass(frozen=True)
class RoundFixture:
    fixture_id: int | str
    league_id: int
    league: str
    home: str
    away: str
    kickoff: datetime
    # Goal Model 1.0 expected goals (home, away) frozen with the snapshot, for display
    # in the Weekly Challenge view; None when the source did not record them
    estimated_goals: tuple[float, float] | None = None


@dataclass(frozen=True)
class RoundSnapshot:
    round_id: str
    kind: SnapshotKind
    snapshot_at: datetime
    config_version: str
    window: tuple[datetime, datetime]
    fixtures: tuple[RoundFixture, ...]
    outcomes: tuple[ChallengeOutcome, ...]
    source_note: str = ""
    diagnostics: dict | None = None  # live builder: why markets were left out

    @property
    def fingerprint(self) -> str:
        blob = json.dumps(
            [
                self.round_id,
                str(self.kind),
                self.snapshot_at.isoformat(),
                self.config_version,
                [
                    o.key
                    + (
                        repr(o.market_probability),
                        str(o.reference_odds),
                        repr(o.model_probability),
                        o.bookmaker_groups,
                        o.latest_observation_at.isoformat() if o.latest_observation_at else None,
                    )
                    for o in self.outcomes
                ],
            ],
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    @property
    def is_demo(self) -> bool:
        return self.kind is SnapshotKind.DEMO

    @property
    def config(self) -> ChallengeConfig:
        """The registered configuration this snapshot was frozen under. An unknown
        version raises :class:`~diski9.challenge.config.ConfigError`; it never falls
        back to the default configuration."""
        return get_config(self.config_version)

    def fixture(self, fixture_id) -> RoundFixture:
        return self._fixtures()[fixture_id]

    def _fixtures(self) -> dict:
        return {f.fixture_id: f for f in self.fixtures}

    def outcome(self, key: tuple) -> ChallengeOutcome | None:
        for o in self.outcomes:
            if o.key == key:
                return o
        return None

    @property
    def earliest_kickoff(self) -> datetime | None:
        return min((f.kickoff for f in self.fixtures), default=None)

    @property
    def deadline(self) -> datetime | None:
        k = self.earliest_kickoff
        return k - DEADLINE_BUFFER if k else None

    def opening_report(self, config: ChallengeConfig | None = None) -> RoundOpeningReport:
        """D-28 opening checks under ``config``, by default the snapshot's own."""
        return round_opening_report(self.outcomes, self.snapshot_at, config or self.config)


def _aware(dt: datetime | None) -> datetime | None:
    """Database timestamps are UTC; SQLite returns them naive."""
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def _split_match(match: str) -> tuple[str, str]:
    home, sep, away = match.partition(" v ")
    return (home, away) if sep else (match, "")


def snapshot_from_research_pool(
    pool: dict,
    round_id: str,
    league_names: dict[int, str],
    config: ChallengeConfig = DEFAULT_CONFIG,
) -> RoundSnapshot:
    """A demonstration snapshot from a frozen research pool.

    Only outcomes the research flagged as strict-consensus eligible with a Goal
    Model forecast are included. The pool records no per-outcome observation
    time; its strict consensus was evaluated *as of* the pool timestamp, so that
    timestamp is used as the observation time (documented limitation)."""
    as_of = datetime.fromisoformat(pool["as_of"])
    start, end = (datetime.fromisoformat(x) for x in pool["window"])
    fixtures, outcomes = [], []
    for f in pool["fixtures"]:
        chosen = [o for o in f["outcomes"] if o.get("eligible") and o.get("odds")]
        if not chosen:
            continue
        home, away = _split_match(f.get("match", str(f["fixture_id"])))
        lam = f.get("lambda_model")
        fixtures.append(
            RoundFixture(
                f["fixture_id"],
                f["league_id"],
                league_names.get(f["league_id"], str(f["league_id"])),
                home,
                away,
                datetime.fromisoformat(f["kickoff"]),
                (float(lam[0]), float(lam[1])) if lam and f.get("model_available", True) else None,
            )
        )
        for o in chosen:
            outcomes.append(
                make_outcome(
                    f["fixture_id"],
                    o["market"],
                    o["outcome"],
                    o["p_market"],
                    o["odds"],
                    o["p_model"],
                    o["groups"],
                    as_of,
                    f["league_id"],
                )
            )
    return RoundSnapshot(
        round_id,
        SnapshotKind.DEMO,
        as_of,
        config.version,
        (start, end),
        tuple(sorted(fixtures, key=lambda x: (x.kickoff, str(x.fixture_id)))),
        tuple(outcomes),
        pool.get("note", ""),
    )


def build_live_snapshot(
    engine,
    as_of: datetime,
    start: datetime,
    end: datetime,
    round_id: str,
    league_names: dict[int, str],
    config: ChallengeConfig = DEFAULT_CONFIG,
) -> RoundSnapshot:
    """Read-only, point-in-time round snapshot from the local database."""
    from sqlalchemy import select

    from diski9.api_football.markets import Market
    from diski9.db.schema import fixtures as fx_table
    from diski9.ingestion.classify import UPCOMING_STATUSES
    from diski9.leagues import odds_competitions
    from diski9.odds.consensus import fixture_consensus, load_bookmakers
    from diski9.odds.implied import implied
    from diski9.odds.value import MARKET_ORDER, OUTCOME_KEY
    from diski9.screener import cache

    fixtures, outcomes = [], []
    diag = {
        "fixtures_in_window": 0,
        "fixtures_with_model": 0,
        "markets_checked": 0,
        "markets_eligible": 0,
        "exclusions": {},
    }
    with engine.connect() as conn:
        books = load_bookmakers(conn)
        payloads = {r["fixture"]["id"]: r for r in cache.cached(conn, "overall")}
        rows = conn.execute(
            select(fx_table.c.id, fx_table.c.competition_id, fx_table.c.kickoff_utc)
            .where(
                fx_table.c.competition_id.in_(odds_competitions()),
                fx_table.c.status_short.in_(UPCOMING_STATUSES),
                fx_table.c.kickoff_utc >= start,
                fx_table.c.kickoff_utc < end,
            )
            .order_by(fx_table.c.kickoff_utc, fx_table.c.id)
        ).all()
        for row in rows:
            diag["fixtures_in_window"] += 1
            payload = payloads.get(row.id)
            gm = (payload or {}).get("goal_model") or {}
            kickoff = _aware(row.kickoff_utc)
            if not gm.get("available") or kickoff <= as_of:
                continue
            diag["fixtures_with_model"] += 1
            # identical to challenge_consensus (strict, no stale fallback), but keeps the
            # exclusion reasons so the UI can explain an unavailable round
            consensus = fixture_consensus(conn, row.id, as_of, books=books)
            chosen = []
            for m in (Market.MATCH_RESULT, Market.BTTS, Market.OVER_UNDER_25):
                mc = consensus.get(m)
                diag["markets_checked"] += 1
                if mc is None or not mc.challenge_eligible:
                    for reason, n in ((mc.exclusions if mc else {}) or {"no_prices": 1}).items():
                        diag["exclusions"][reason] = diag["exclusions"].get(reason, 0) + n
                    continue
                diag["markets_eligible"] += 1
                adj = implied(mc).margin_adjusted
                if not adj:
                    continue
                for o in MARKET_ORDER[m]:
                    oc = mc.outcomes.get(o)
                    if oc is None or oc.consensus_odds is None:
                        continue
                    chosen.append(
                        make_outcome(
                            row.id,
                            m,
                            o,
                            float(adj[o]),
                            oc.consensus_odds,
                            float(gm["probabilities"][OUTCOME_KEY[o]]),
                            mc.sources,
                            _aware(mc.latest_observation),
                            row.competition_id,
                        )
                    )
            if not chosen:
                continue
            eg = gm.get("estimated_goals") or {}
            fixtures.append(
                RoundFixture(
                    row.id,
                    row.competition_id,
                    league_names.get(row.competition_id, str(row.competition_id)),
                    payload["fixture"]["home"],
                    payload["fixture"]["away"],
                    kickoff,
                    (float(eg["home"]), float(eg["away"]))
                    if eg.get("home") is not None and eg.get("away") is not None
                    else None,
                )
            )
            outcomes.extend(chosen)
    return RoundSnapshot(
        round_id,
        SnapshotKind.LIVE,
        as_of,
        config.version,
        (start, end),
        tuple(fixtures),
        tuple(outcomes),
        "Strict Challenge consensus at the snapshot time; read-only.",
        diag,
    )


# ------------------------------------------------------------ round states
class RoundStatus(StrEnum):
    OPEN = "open"  # live round accepting (prototype) submissions
    LOCKED = "locked"  # live round past its deadline
    DEMO = "demo"  # historical demonstration round
    NO_ROUND = "no_round"  # no fixtures in the round window
    MISSING_MARKETS = "missing_markets"  # fixtures, but no qualifying market data
    STALE_ODDS = "stale_odds"  # prices exist but are not fresh enough
    INSUFFICIENT = "insufficient"  # fewer than 15 eligible fixtures or 3 leagues
    INFEASIBLE = "infeasible"  # no strict 4/3/2 portfolio can be built


@dataclass(frozen=True)
class RoundAvailability:
    status: RoundStatus
    title: str
    message: str
    report: RoundOpeningReport | None

    @property
    def playable(self) -> bool:
        return self.status in (RoundStatus.OPEN, RoundStatus.DEMO)


_STALE = {"stale_observation", "stale_provider_update"}


def assess_round(
    snapshot: RoundSnapshot | None, now: datetime, config: ChallengeConfig | None = None
) -> RoundAvailability:
    """The round's status for display. Opening checks use the snapshot time; only
    the live deadline compares with ``now``. ``config`` defaults to the snapshot's own
    configuration (never the global default)."""
    if snapshot is None or (
        not snapshot.outcomes and not (snapshot.diagnostics or {}).get("fixtures_in_window")
    ):
        return RoundAvailability(
            RoundStatus.NO_ROUND,
            "No round this week",
            "There are no supported fixtures in the next round window.",
            None,
        )
    config = config or snapshot.config
    report = snapshot.opening_report(config)
    if not report.eligible_outcomes:
        exclusions = (snapshot.diagnostics or {}).get("exclusions", {})
        stale = sum(n for r, n in exclusions.items() if r in _STALE)
        if stale and stale >= sum(exclusions.values()) / 2:
            return RoundAvailability(
                RoundStatus.STALE_ODDS,
                "Reference odds are out of date",
                "The bookmaker prices have not been verified within the "
                "last 24 hours, so no round can open.",
                report,
            )
        return RoundAvailability(
            RoundStatus.MISSING_MARKETS,
            "Not enough market data",
            "No fixture has complete, independently priced markets yet.",
            report,
        )
    if not (report.checks["min_eligible_fixtures"] and report.checks["min_eligible_leagues"]):
        return RoundAvailability(
            RoundStatus.INSUFFICIENT,
            "Not enough eligible fixtures",
            f"{report.eligible_fixtures} eligible fixtures in "
            f"{report.eligible_leagues} leagues; a round needs at least "
            f"{config.opening.min_eligible_fixtures} fixtures in "
            f"{config.opening.min_eligible_leagues} leagues.",
            report,
        )
    if not report.portfolio_feasible:
        return RoundAvailability(
            RoundStatus.INFEASIBLE,
            "A full portfolio is not possible",
            "The eligible fixtures cannot fill four Foundation, three "
            "Balanced and two Challenger predictions.",
            report,
        )
    if snapshot.is_demo:
        return RoundAvailability(
            RoundStatus.DEMO,
            "Demonstration round",
            "Historical fixtures and prices, for practice only.",
            report,
        )
    deadline = snapshot.deadline
    if deadline is not None and now >= deadline:
        return RoundAvailability(
            RoundStatus.LOCKED, "Round locked", "The submission deadline has passed.", report
        )
    return RoundAvailability(
        RoundStatus.OPEN, "Round open", "Build your portfolio before the deadline.", report
    )
