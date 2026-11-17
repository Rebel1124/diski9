"""Odds coverage diagnostics across the supported leagues (Phase 5A).

Reads the local database only - it never calls API-Football - and evaluates every
upcoming fixture with the same consensus rules the app uses
(:func:`diski9.odds.consensus.fixture_consensus`), so the figures match what the
Screener and The Match Lab show. Nothing here relaxes a quality rule:

* **Fresh** (``qualifying``): a valid consensus exists now - quotes observed and
  provider-updated within 24 h, eligible independent bookmakers, complete market.
  This is what the app displays and what Edge / EV ranking uses.
* **Challenge-eligible**: fresh *and* at least ``min_bookmakers`` (3) independent
  bookmaker groups.

Each market (1X2, BTTS, Over/Under 2.5) is assessed independently. Figures are
counts of fixtures actually observed; leagues the provider does not cover show 0,
never an estimate.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, select

from diski9.api_football.markets import Market
from diski9.db.schema import fixtures, odds_fetches, odds_fixture_observations, seasons
from diski9.ingestion.classify import UPCOMING_STATUSES
from diski9.leagues import COMPETITIONS, CURRENT_SEASON, odds_competitions

from .consensus import ConsensusRules, fixture_consensus, load_bookmakers

MARKETS = (Market.MATCH_RESULT, Market.BTTS, Market.OVER_UNDER_25)
LEAD_BUCKETS = (  # (label, lower hours inclusive, upper hours exclusive)
    ("0-24h", 0, 24),
    ("1-3d", 24, 72),
    ("3-7d", 72, 168),
    ("7-14d", 168, 336),
    ("14d+", 336, None),
)


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def _spread(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {
        "min": round(min(values), 1),
        "median": round(statistics.median(values), 1),
        "max": round(max(values), 1),
    }


def _bucket(hours: float) -> str:
    for label, lo, hi in LEAD_BUCKETS:
        if hours >= lo and (hi is None or hours < hi):
            return label
    return LEAD_BUCKETS[-1][0]


def league_coverage(
    conn: Connection,
    competition_id: int,
    now: datetime,
    horizon_days: int = 14,
    rules: ConsensusRules | None = None,
    books=None,
) -> dict[str, Any]:
    rules = rules or ConsensusRules()
    books = books if books is not None else load_bookmakers(conn)
    cfg = COMPETITIONS.get(competition_id)
    upcoming = conn.execute(
        select(fixtures.c.id, fixtures.c.kickoff_utc)
        .where(
            fixtures.c.competition_id == competition_id,
            fixtures.c.season == CURRENT_SEASON,
            fixtures.c.status_short.in_(UPCOMING_STATUSES),
            fixtures.c.kickoff_utc > now,
            fixtures.c.kickoff_utc <= now + timedelta(days=horizon_days),
        )
        .order_by(fixtures.c.kickoff_utc, fixtures.c.id)
    ).all()
    observed = (
        {
            r[0]
            for r in conn.execute(
                select(odds_fixture_observations.c.fixture_id)
                .where(odds_fixture_observations.c.fixture_id.in_([f.id for f in upcoming]))
                .distinct()
            )
        }
        if upcoming
        else set()
    )

    fresh = dict.fromkeys(MARKETS, 0)
    eligible = dict.fromkeys(MARKETS, 0)
    any_fresh = any_eligible = 0
    groups: list[float] = []
    obs_age: list[float] = []
    provider_age: list[float] = []
    lead = {label: {"fixtures": 0, "with_quotes": 0, "fresh_any": 0} for label, *_ in LEAD_BUCKETS}
    exclusions: dict[str, int] = {}
    for fx in upcoming:
        result = fixture_consensus(conn, fx.id, now, rules, books)
        hours = (fx.kickoff_utc - now).total_seconds() / 3600
        b = lead[_bucket(hours)]
        b["fixtures"] += 1
        b["with_quotes"] += fx.id in observed
        f_any = e_any = False
        best_groups = 0
        latest_obs = latest_provider = None
        for m in MARKETS:
            mc = result[m]
            for k, v in mc.exclusions.items():
                exclusions[k] = exclusions.get(k, 0) + v
            if mc.displayable:
                fresh[m] += 1
                f_any = True
                best_groups = max(best_groups, mc.sources)
                if mc.latest_observation and (
                    latest_obs is None or mc.latest_observation > latest_obs
                ):
                    latest_obs = mc.latest_observation
                if mc.provider_updated_at and (
                    latest_provider is None or mc.provider_updated_at > latest_provider
                ):
                    latest_provider = mc.provider_updated_at
            if mc.displayable and mc.challenge_eligible:
                eligible[m] += 1
                e_any = True
        any_fresh += f_any
        any_eligible += e_any
        b["fresh_any"] += f_any
        if f_any:
            groups.append(best_groups)
            if latest_obs:
                obs_age.append((now - latest_obs).total_seconds() / 3600)
            if latest_provider:
                provider_age.append((now - latest_provider).total_seconds() / 3600)

    n = len(upcoming)
    last_fetch = conn.execute(
        select(odds_fetches.c.retrieved_at, odds_fetches.c.status)
        .where(odds_fetches.c.competition_id == competition_id)
        .order_by(odds_fetches.c.retrieved_at.desc())
        .limit(1)
    ).first()
    api_flag = conn.execute(
        select(seasons.c.coverage_odds).where(
            seasons.c.competition_id == competition_id, seasons.c.year == CURRENT_SEASON
        )
    ).scalar()
    return {
        "league": cfg.name if cfg else str(competition_id),
        "league_id": competition_id,
        "odds_enabled": bool(cfg and cfg.odds_enabled),
        "provider_odds_coverage": None if api_flag is None else bool(api_flag),
        "last_collection": last_fetch.retrieved_at.isoformat() if last_fetch else None,
        "last_collection_status": last_fetch.status if last_fetch else None,
        "upcoming_fixtures": n,
        "fixtures_with_any_quotes": len(observed),
        "fresh": {m.value: {"fixtures": fresh[m], "pct": _pct(fresh[m], n)} for m in MARKETS},
        "fresh_any_market": {"fixtures": any_fresh, "pct": _pct(any_fresh, n)},
        "challenge_eligible": {
            m.value: {"fixtures": eligible[m], "pct": _pct(eligible[m], n)} for m in MARKETS
        },
        "challenge_eligible_any_market": {"fixtures": any_eligible, "pct": _pct(any_eligible, n)},
        "bookmaker_groups": _spread(groups),
        "quote_age_hours": _spread(obs_age),
        "provider_update_age_hours": _spread(provider_age),
        "by_time_to_kickoff": lead,
        "exclusions": dict(sorted(exclusions.items())),
    }


def coverage_report(
    conn: Connection,
    now: datetime,
    competitions: list[int] | None = None,
    horizon_days: int = 14,
    rules: ConsensusRules | None = None,
) -> dict[str, Any]:
    rules = rules or ConsensusRules()
    books = load_bookmakers(conn)
    comps = competitions or odds_competitions()
    leagues = [league_coverage(conn, c, now, horizon_days, rules, books) for c in comps]
    total = sum(x["upcoming_fixtures"] for x in leagues)
    any_fresh = sum(x["fresh_any_market"]["fixtures"] for x in leagues)
    any_elig = sum(x["challenge_eligible_any_market"]["fixtures"] for x in leagues)
    return {
        "as_of": now.isoformat(),
        "horizon_days": horizon_days,
        "rules": {
            "max_quote_age_hours": rules.max_quote_age.total_seconds() / 3600,
            "challenge_min_bookmakers": rules.min_bookmakers,
        },
        "totals": {
            "upcoming_fixtures": total,
            "fresh_any_market": {"fixtures": any_fresh, "pct": _pct(any_fresh, total)},
            "challenge_eligible_any_market": {"fixtures": any_elig, "pct": _pct(any_elig, total)},
        },
        "leagues": leagues,
    }


def format_table(report: dict[str, Any]) -> str:
    """Compact plain-text summary (one row per league)."""

    def cell(d: dict) -> str:
        return "—" if d["pct"] is None else f"{d['fixtures']} ({d['pct']:.0f}%)"

    head = (
        f"{'League':<28}{'ID':>5}{'Fixt':>6}{'1X2':>11}{'BTTS':>11}{'OU2.5':>11}"
        f"{'Any':>11}{'Chal≥3':>11}{'Books':>7}{'Age h':>7}"
    )
    lines = [
        f"Odds coverage as of {report['as_of']} (next {report['horizon_days']} days; fresh = "
        f"valid consensus within {report['rules']['max_quote_age_hours']:.0f} h)",
        head,
        "-" * len(head),
    ]
    for x in report["leagues"]:
        fr = x["fresh"]
        books = x["bookmaker_groups"]["median"]
        age = x["quote_age_hours"]["median"]
        flag = "" if x["provider_odds_coverage"] is not False else " *"
        lines.append(
            f"{(x['league'] + flag)[:27]:<28}{x['league_id']:>5}{x['upcoming_fixtures']:>6}"
            f"{cell(fr['1X2']):>11}{cell(fr['BTTS']):>11}{cell(fr['OU25']):>11}"
            f"{cell(x['fresh_any_market']):>11}{cell(x['challenge_eligible_any_market']):>11}"
            f"{'—' if books is None else f'{books:g}':>7}{'—' if age is None else f'{age:.1f}':>7}"
        )
    lines.append("-" * len(head))
    t = report["totals"]
    lines.append(
        f"{'All leagues':<33}{t['upcoming_fixtures']:>6}{'':>33}{cell(t['fresh_any_market']):>11}"
        f"{cell(t['challenge_eligible_any_market']):>11}"
    )
    if any(x["provider_odds_coverage"] is False for x in report["leagues"]):
        lines.append("* API-Football reports no odds coverage for this league-season.")
    lines.append("Books = median independent bookmaker groups; Age h = median hours since a")
    lines.append("contributing price was last verified. No API requests were made.")
    return "\n".join(lines)
