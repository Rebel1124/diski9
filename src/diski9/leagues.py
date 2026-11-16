"""Supported competitions. Extend this registry to add leagues."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompetitionConfig:
    id: int
    name: str
    tier: int
    parent_id: int | None = None  # top-flight competition this division feeds
    odds_enabled: bool = False  # collect pre-match odds (Challenge candidates)
    # Seasons that `setup` backfills; None = BACKFILL_SEASONS. Engine 3.0 needs the
    # previous season (league-average prior) and the current season.
    backfill_seasons: tuple[int, ...] | None = None
    screener: bool = True  # domestic league shown in the Screener with Goal Model 1.0


COMPETITIONS: dict[int, CompetitionConfig] = {
    39: CompetitionConfig(39, "English Premier League", tier=1, odds_enabled=True),
    40: CompetitionConfig(40, "English Championship", tier=2, parent_id=39),
    288: CompetitionConfig(288, "South African Premiership", tier=1, odds_enabled=True),
    289: CompetitionConfig(289, "South African 1st Division", tier=2, parent_id=288),
    # Engine 3.0: independently validated with frozen Goal Model 1.0 parameters
    # (docs/goal_model_crossleague_validation.md). Odds collection is off so the
    # approved odds trial keeps its original scope.
    140: CompetitionConfig(140, "Spanish La Liga", tier=1, backfill_seasons=(2025, 2026)),
    61: CompetitionConfig(61, "French Ligue 1", tier=1, backfill_seasons=(2025, 2026)),
    78: CompetitionConfig(78, "German Bundesliga", tier=1, backfill_seasons=(2025, 2026)),
    135: CompetitionConfig(135, "Italian Serie A", tier=1, backfill_seasons=(2025, 2026)),
}

CURRENT_SEASON = 2026
HISTORICAL_SEASONS = (2023, 2024, 2025)
BACKFILL_SEASONS = (*HISTORICAL_SEASONS, CURRENT_SEASON)


def seasons_for(competition_id: int) -> tuple[int, ...]:
    cfg = COMPETITIONS.get(competition_id)
    return cfg.backfill_seasons if cfg and cfg.backfill_seasons else BACKFILL_SEASONS


def screener_competitions() -> list[int]:
    """All supported domestic leagues (Engine 3.0 Screener and Goal Model 1.0)."""
    return [c.id for c in COMPETITIONS.values() if c.screener]
