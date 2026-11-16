"""Ranking and filtering of screener results.

Every ranking is deterministic: ties are broken by kickoff time, then fixture id.
Kickoff ranking sorts on the actual UTC timestamp, never on formatted strings.
For statistical rankings, fixtures whose indicator is unavailable are listed
after all ranked fixtures (or removed when a threshold is set).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

Direction = Literal[
    "kickoff_earliest",
    "kickoff_latest",
    "home_stronger",
    "away_stronger",
    "evenly_matched",
    "btts_yes",
    "btts_no",
    "over",
    "under",
]
KICKOFF_DIRECTIONS = ("kickoff_earliest", "kickoff_latest")
DEFAULT_DIRECTION: Direction = "kickoff_earliest"


def _kickoff(result: dict) -> datetime:
    return datetime.fromisoformat(result["fixture"]["kickoff"])


def indicator(result: dict, direction: str) -> float | None:
    if direction in ("home_stronger", "away_stronger", "evenly_matched"):
        return result["match_result"]["form_difference"]
    if direction in ("btts_yes", "btts_no"):
        return result["btts"]["yes_indicator"]
    if direction in ("over", "under"):
        return result["over_under_2_5"]["over_indicator"]
    return None


def _passes(value: float, direction: str, threshold: float) -> bool:
    if direction == "home_stronger":
        return value >= threshold
    if direction == "away_stronger":
        return value <= -threshold
    if direction == "evenly_matched":
        return abs(value) <= threshold
    if direction in ("btts_yes", "over"):
        return value >= threshold
    return (1 - value) >= threshold  # btts_no, under: threshold on the complement


def _primary(value: float, direction: str) -> float:
    """Smaller sorts first."""
    if direction in ("home_stronger", "btts_yes", "over"):
        return -value
    if direction == "evenly_matched":
        return abs(value)
    return value  # away_stronger (most negative first), btts_no / under (lowest Yes/Over first)


def rank(results: list[dict], direction: str, threshold: float | None = None) -> list[dict]:
    if direction in KICKOFF_DIRECTIONS:
        return sorted(
            results,
            key=lambda r: (_kickoff(r), r["fixture"]["id"]),
            reverse=direction == "kickoff_latest",
        )
    ranked, unavailable = [], []
    for r in results:
        v = indicator(r, direction)
        if v is None:
            unavailable.append(r)
        elif threshold is None or _passes(v, direction, threshold):
            ranked.append((r, v))
    ranked.sort(key=lambda x: (_primary(x[1], direction), _kickoff(x[0]), x[0]["fixture"]["id"]))
    tail = (
        []
        if threshold is not None
        else sorted(unavailable, key=lambda r: (_kickoff(r), r["fixture"]["id"]))
    )
    return [r for r, _ in ranked] + tail
