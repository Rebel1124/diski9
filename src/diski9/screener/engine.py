"""Screener engine: builds the full, explainable result for one fixture.

Point-in-time rule
------------------
Every statistic for a fixture uses only matches with ``kickoff_utc < cutoff``,
where ``cutoff = min(as_of, fixture kickoff)``. So a result computed for a past
fixture never sees later results, and a result for an upcoming fixture uses
what is known now. Benchmarks follow the same rule.

Relevant matches
----------------
* Domestic league matches eligible for statistics (``stats_exclusion_reason IS
  NULL``): completed, regular-season, not awarded/cancelled/walkover/abandoned.
  Play-off, relegation and promotion rounds are excluded.
* From any stored domestic league (current division, previous divisions), any
  season, to complete rolling windows. Provenance is recorded per match.
* Venue windows (home/away) exclude matches at a confirmed ``neutral`` venue.
  ``unverified_venue`` matches are included (the provider's home/away
  designation) and flagged in the output.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any, Literal

from sqlalchemy import Connection, select

from diski9.db.schema import competitions, fixtures, teams

from .calc import (
    FORM_MIN_MATCHES,
    GOALS_MIN_MATCHES,
    combined_indicator,
    display,
    form_score,
    limited_data_reasons,
    pooled_benchmark,
    rate,
    venue_adjusted_difference,
)

ENGINE_VERSION = "1.2.0"  # tracks Statistical Screener Specification v1.2
Basis = Literal["venue", "overall"]


@dataclass(frozen=True)
class ScreenerConfig:
    form_window: int = 5
    goals_window: int = 10
    # Minimum eligible current-season league matches before the current season
    # supplies the benchmark (spec 4.7). Default validated in
    # docs/benchmark_threshold_validation.json; override per competition.
    benchmark_min_matches: int = 120
    benchmark_min_by_competition: dict[int, int] = field(default_factory=dict)
    h2h_count: int = 5

    def benchmark_min(self, competition_id: int) -> int:
        return self.benchmark_min_by_competition.get(competition_id, self.benchmark_min_matches)


@dataclass(frozen=True)
class Match:
    fixture_id: int
    kickoff: datetime
    competition_id: int
    season: int
    home_id: int
    away_id: int
    home_goals: int
    away_goals: int
    venue_classification: str
    stats_eligible: bool
    round_name: str | None
    venue_name: str | None
    status: str
    content_hash: str


@dataclass(frozen=True)
class TeamMatch:
    match: Match
    team_id: int
    is_home: bool

    @property
    def goals_for(self) -> int:
        return self.match.home_goals if self.is_home else self.match.away_goals

    @property
    def goals_against(self) -> int:
        return self.match.away_goals if self.is_home else self.match.home_goals

    @property
    def opponent_id(self) -> int:
        return self.match.away_id if self.is_home else self.match.home_id

    @property
    def result(self) -> str:
        if self.goals_for > self.goals_against:
            return "W"
        return "D" if self.goals_for == self.goals_against else "L"


class MatchStore:
    """All completed matches, indexed for fast point-in-time window queries."""

    def __init__(self, conn: Connection):
        self.team_names = dict(conn.execute(select(teams.c.id, teams.c.name)).all())
        self.competition_names = dict(
            conn.execute(select(competitions.c.id, competitions.c.name)).all()
        )
        rows = conn.execute(
            select(fixtures)
            .where(fixtures.c.is_final.is_(True))
            .order_by(fixtures.c.kickoff_utc, fixtures.c.id)
        ).all()
        self.matches: list[Match] = [
            Match(
                r.id,
                r.kickoff_utc,
                r.competition_id,
                r.season,
                r.home_team_id,
                r.away_team_id,
                r.ft_home,
                r.ft_away,
                r.venue_classification,
                r.stats_exclusion_reason is None,
                r.round_name,
                r.venue_name,
                r.status_short,
                r.content_hash,
            )
            for r in rows
        ]
        self.by_team: dict[int, list[TeamMatch]] = defaultdict(list)
        self.by_comp_season: dict[tuple[int, int], list[Match]] = defaultdict(list)
        for m in self.matches:
            if m.stats_eligible:
                self.by_team[m.home_id].append(TeamMatch(m, m.home_id, True))
                self.by_team[m.away_id].append(TeamMatch(m, m.away_id, False))
                self.by_comp_season[(m.competition_id, m.season)].append(m)
        self._team_kickoffs = {t: [tm.match.kickoff for tm in v] for t, v in self.by_team.items()}

    def team_window(
        self, team_id: int, cutoff: datetime, venue: Literal["home", "away"] | None, n: int
    ) -> list[TeamMatch]:
        """Last ``n`` eligible matches before ``cutoff``, most recent first."""
        history = self.by_team.get(team_id, [])
        end = bisect_left(self._team_kickoffs.get(team_id, []), cutoff)
        out: list[TeamMatch] = []
        for tm in reversed(history[:end]):
            if venue is not None:
                if tm.is_home != (venue == "home"):
                    continue
                if tm.match.venue_classification == "neutral":
                    continue
            out.append(tm)
            if len(out) == n:
                break
        return out

    def league_matches(self, competition_id: int, season: int, cutoff: datetime) -> list[Match]:
        """Eligible league matches for a benchmark, excluding confirmed neutral venues."""
        return [
            m
            for m in self.by_comp_season.get((competition_id, season), [])
            if m.kickoff < cutoff and m.venue_classification != "neutral"
        ]

    def head_to_head(self, a: int, b: int, cutoff: datetime, n: int) -> list[Match]:
        """Most recent completed meetings (any stored competition, any round)."""
        out = [
            m
            for m in reversed(self.matches)
            if m.kickoff < cutoff and {m.home_id, m.away_id} == {a, b}
        ]
        return out[:n]


# ------------------------------------------------------------------ helpers
def provenance(tm: TeamMatch, competition_id: int, season: int) -> str:
    if tm.match.competition_id == competition_id:
        return (
            "current_season_same_division"
            if tm.match.season == season
            else "previous_season_same_division"
        )
    return "other_division"


def _match_row(store: MatchStore, tm: TeamMatch, competition_id: int, season: int) -> dict:
    m = tm.match
    return {
        "fixture_id": m.fixture_id,
        "date": m.kickoff.date().isoformat(),
        "opponent": store.team_names.get(tm.opponent_id, str(tm.opponent_id)),
        "competition": store.competition_names.get(m.competition_id, str(m.competition_id)),
        "season": m.season,
        "venue": "H" if tm.is_home else "A",
        "score": f"{tm.goals_for}-{tm.goals_against}",
        "result": tm.result,
        "btts": tm.goals_for > 0 and tm.goals_against > 0,
        "over_2_5": tm.goals_for + tm.goals_against >= 3,
        "provenance": provenance(tm, competition_id, season),
        "unverified_venue": m.venue_classification == "unverified_venue",
    }


def _sample_info(window: list[TeamMatch], competition_id: int, season: int, minimum: int) -> dict:
    counts = defaultdict(int)
    for tm in window:
        counts[provenance(tm, competition_id, season)] += 1
    current_division = counts.get("current_season_same_division", 0) + counts.get(
        "previous_season_same_division", 0
    )
    reasons = limited_data_reasons(len(window), current_division, minimum)
    other = counts.get("other_division", 0)
    return {
        "matches": len(window),
        "current_division_matches": current_division,
        "provenance": dict(counts),
        "unverified_venue_matches": sum(
            tm.match.venue_classification == "unverified_venue" for tm in window
        ),
        "previous_season_matches": sum(tm.match.season != season for tm in window),
        "limited_data": bool(reasons),
        "limited_data_reasons": reasons,
        "note": f"Includes {other} previous-division/other-competition matches" if other else None,
    }


def select_benchmark(
    store: MatchStore, competition_id: int, season: int, cutoff: datetime, config: ScreenerConfig
) -> dict | None:
    """Current season if enough eligible matches, else previous completed season,
    else current-season partial (flagged). None if no data."""
    current = store.league_matches(competition_id, season, cutoff)
    minimum = config.benchmark_min(competition_id)
    previous = store.league_matches(competition_id, season - 1, cutoff)
    if len(current) >= minimum:
        chosen, source, yr = current, "current_season", season
    elif previous:
        chosen, source, yr = previous, "previous_season", season - 1
    elif current:
        chosen, source, yr = current, "current_season_partial", season
    else:
        return None
    b = pooled_benchmark(competition_id, yr, ((m.home_goals, m.away_goals) for m in chosen))
    assert b is not None
    return {
        "object": b,
        "competition": store.competition_names.get(competition_id),
        "season": yr,
        "source": source,
        "matches": b.matches,
        "current_season_matches": len(current),
        "min_current_matches": minimum,
        "home": b.home.breakdown(),
        "away": b.away.breakdown(),
        "draw_rate": float(b.draw_rate),
        "draw_rate_display": f"{display(b.draw_rate * 100, 1)}%",
        "label": f"Venue-adjusted using {store.competition_names.get(competition_id)} "
        f"{yr}/{str(yr + 1)[-2:]} averages ({b.matches} matches)",
    }


def computed_table(store: MatchStore, competition_id: int, season: int, cutoff: datetime) -> dict:
    """League table computed from eligible results before cutoff (context only)."""
    table: dict[int, dict[str, int]] = defaultdict(lambda: {"p": 0, "pts": 0, "gf": 0, "ga": 0})
    for m in store.league_matches(competition_id, season, cutoff):
        for team, gf, ga in (
            (m.home_id, m.home_goals, m.away_goals),
            (m.away_id, m.away_goals, m.home_goals),
        ):
            row = table[team]
            row["p"] += 1
            row["gf"] += gf
            row["ga"] += ga
            row["pts"] += 3 if gf > ga else 1 if gf == ga else 0
    order = sorted(
        table,
        key=lambda t: (
            -table[t]["pts"],
            -(table[t]["gf"] - table[t]["ga"]),
            -table[t]["gf"],
            store.team_names.get(t, ""),
        ),
    )
    return {t: {"position": i + 1, **table[t]} for i, t in enumerate(order)}


# ------------------------------------------------------------------- engine
def compute_fixture(
    store: MatchStore,
    fixture: Any,
    as_of: datetime,
    basis: Basis = "venue",
    config: ScreenerConfig | None = None,
) -> dict:
    """Full screener result for one fixture row (needs id, competition_id,
    season, home_team_id, away_team_id, kickoff_utc)."""
    config = config or ScreenerConfig()
    cutoff = min(as_of, fixture.kickoff_utc)
    comp, season = fixture.competition_id, fixture.season
    home_id, away_id = fixture.home_team_id, fixture.away_team_id
    home_venue = "home" if basis == "venue" else None
    away_venue = "away" if basis == "venue" else None

    teams_out: dict[str, dict] = {}
    forms: dict[str, Any] = {}
    goal_rates: dict[str, dict[str, Any]] = {}
    for side, team_id, venue in (("home", home_id, home_venue), ("away", away_id, away_venue)):
        fw = store.team_window(team_id, cutoff, venue, config.form_window)
        gw = store.team_window(team_id, cutoff, venue, config.goals_window)
        fs = form_score((tm.goals_for, tm.goals_against) for tm in fw)
        btts = rate([tm.goals_for > 0 and tm.goals_against > 0 for tm in gw])
        over = rate([tm.goals_for + tm.goals_against >= 3 for tm in gw])
        forms[side] = fs
        goal_rates[side] = {"btts": btts, "over": over}
        n = len(gw)
        teams_out[side] = {
            "team_id": team_id,
            "team": store.team_names.get(team_id, str(team_id)),
            "window": venue or "overall",
            "form": {
                "score": float(fs.score) if fs else None,
                "display": display(fs.score) if fs else None,
                "sequence": "-".join(tm.result for tm in fw),
                "breakdown": fs.breakdown() if fs else None,
                "sample": _sample_info(fw, comp, season, FORM_MIN_MATCHES),
                "matches": [_match_row(store, tm, comp, season) for tm in fw],
            },
            "goals": {
                "btts": btts.as_dict() if btts else None,
                "over_2_5": over.as_dict() if over else None,
                "avg_goals_for": round(sum(tm.goals_for for tm in gw) / n, 3) if n else None,
                "avg_goals_against": round(sum(tm.goals_against for tm in gw) / n, 3)
                if n
                else None,
                "avg_total_goals": (
                    round(sum(tm.goals_for + tm.goals_against for tm in gw) / n, 3) if n else None
                ),
                "clean_sheets": sum(tm.goals_against == 0 for tm in gw),
                "failed_to_score": sum(tm.goals_for == 0 for tm in gw),
                "sample": _sample_info(gw, comp, season, GOALS_MIN_MATCHES),
                "matches": [_match_row(store, tm, comp, season) for tm in gw],
            },
        }

    # 1X2
    hf, af = forms["home"], forms["away"]
    raw = (hf.score - af.score) if hf and af else None
    bench = select_benchmark(store, comp, season, cutoff, config)
    vad: Fraction | None = None
    if basis == "venue" and raw is not None and bench is not None:
        b = bench["object"]
        vad = venue_adjusted_difference(hf.score, af.score, b.home.score, b.away.score)
    bench_out = {k: v for k, v in bench.items() if k != "object"} if bench else None

    # Goals markets
    btts_yes = combined_indicator(goal_rates["home"]["btts"], goal_rates["away"]["btts"])
    over25 = combined_indicator(goal_rates["home"]["over"], goal_rates["away"]["over"])

    table = computed_table(store, comp, season, cutoff)
    h2h = store.head_to_head(home_id, away_id, cutoff, config.h2h_count)

    limited = {
        "form": teams_out["home"]["form"]["sample"]["limited_data"]
        or teams_out["away"]["form"]["sample"]["limited_data"],
        "goals": teams_out["home"]["goals"]["sample"]["limited_data"]
        or teams_out["away"]["goals"]["sample"]["limited_data"],
    }
    result = {
        "engine_version": ENGINE_VERSION,
        "fixture": {
            "id": fixture.id,
            "competition_id": comp,
            "competition": store.competition_names.get(comp),
            "season": season,
            "kickoff": fixture.kickoff_utc.isoformat(),
            "home": teams_out["home"]["team"],
            "away": teams_out["away"]["team"],
        },
        "as_of": as_of.isoformat(),
        "cutoff": cutoff.isoformat(),
        "basis": basis,
        "config": {
            "form_window": config.form_window,
            "goals_window": config.goals_window,
            "benchmark_min_matches": config.benchmark_min(comp),
        },
        "teams": teams_out,
        "match_result": {
            "home_form": float(hf.score) if hf else None,
            "away_form": float(af.score) if af else None,
            "raw_difference": float(raw) if raw is not None else None,
            "raw_difference_display": display(raw),
            "venue_adjusted_difference": float(vad) if vad is not None else None,
            "venue_adjusted_difference_display": display(vad),
            "benchmark": bench_out,
            "note": "A near-zero difference indicates similar relative historical "
            "performance; it does not imply that a draw is likely.",
        },
        "btts": {
            "yes_indicator": float(btts_yes) if btts_yes is not None else None,
            "yes_display": f"{display(btts_yes * 100, 0)}%" if btts_yes is not None else None,
            "no_indicator": float(1 - btts_yes) if btts_yes is not None else None,
            "no_display": f"{display((1 - btts_yes) * 100, 0)}%" if btts_yes is not None else None,
        },
        "over_under_2_5": {
            "over_indicator": float(over25) if over25 is not None else None,
            "over_display": f"{display(over25 * 100, 0)}%" if over25 is not None else None,
            "under_indicator": float(1 - over25) if over25 is not None else None,
            "under_display": f"{display((1 - over25) * 100, 0)}%" if over25 is not None else None,
        },
        "indicator_note": "Historical indicators, not predicted probabilities.",
        "limited_data": limited,
        "league_position": {
            "source": "computed from eligible results before cutoff (excludes awarded "
            "results and points deductions; may differ from official standings)",
            "home": table.get(home_id),
            "away": table.get(away_id),
        },
        "head_to_head": [
            {
                "fixture_id": m.fixture_id,
                "date": m.kickoff.date().isoformat(),
                "competition": store.competition_names.get(m.competition_id),
                "season": m.season,
                "round": m.round_name,
                "home": store.team_names.get(m.home_id),
                "away": store.team_names.get(m.away_id),
                "venue": m.venue_name,
                "score": f"{m.home_goals}-{m.away_goals}",
                "older": m.season < season - 1,
            }
            for m in h2h
        ],
        "head_to_head_note": "Context only; head-to-head does not affect any indicator.",
    }
    result["inputs_hash"] = inputs_hash(result)
    return result


def inputs_hash(result: dict) -> str:
    """Hash of the result content, excluding when it was requested."""
    body = {k: v for k, v in result.items() if k not in ("as_of", "cutoff", "inputs_hash")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
