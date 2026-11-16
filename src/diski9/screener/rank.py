"""Ranking and filtering of screener results.

Every ranking is deterministic: ties are broken by kickoff time, then fixture id.
Kickoff ranking sorts on the actual UTC timestamp, never on formatted strings.
Statistical rankings order fixtures by the Goal Model 1.0 probability of the
chosen outcome; fixtures without model probabilities are listed after all ranked
fixtures (or removed when a threshold is set).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

Direction = Literal[
    "kickoff_earliest",
    "kickoff_latest",
    "home_win",
    "draw",
    "away_win",
    "btts_yes",
    "btts_no",
    "over",
    "under",
]
KICKOFF_DIRECTIONS = ("kickoff_earliest", "kickoff_latest")
DEFAULT_DIRECTION: Direction = "kickoff_earliest"
# Engine 3.0: rank by the Goal Model 1.0 probability of the chosen outcome
OUTCOME_OF = {
    "home_win": "home",
    "draw": "draw",
    "away_win": "away",
    "btts_yes": "btts_yes",
    "btts_no": "btts_no",
    "over": "over",
    "under": "under",
}


def _kickoff(result: dict) -> datetime:
    return datetime.fromisoformat(result["fixture"]["kickoff"])


def indicator(result: dict, direction: str) -> float | None:
    """Model probability of the direction's outcome; None when unavailable."""
    gm = result.get("goal_model") or {}
    if direction not in OUTCOME_OF or not gm.get("available"):
        return None
    return gm["probabilities"][OUTCOME_OF[direction]]


def _passes(value: float, direction: str, threshold: float) -> bool:
    return value >= threshold  # threshold = minimum probability of the outcome


def _primary(value: float, direction: str) -> float:
    """Smaller sorts first: highest probability first."""
    return -value


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
