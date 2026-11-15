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


COMPETITIONS: dict[int, CompetitionConfig] = {
    39: CompetitionConfig(39, "English Premier League", tier=1, odds_enabled=True),
    40: CompetitionConfig(40, "English Championship", tier=2, parent_id=39),
    288: CompetitionConfig(288, "South African Premiership", tier=1, odds_enabled=True),
    289: CompetitionConfig(289, "South African 1st Division", tier=2, parent_id=288),
}

CURRENT_SEASON = 2026
HISTORICAL_SEASONS = (2023, 2024, 2025)
BACKFILL_SEASONS = (*HISTORICAL_SEASONS, CURRENT_SEASON)
