"""Ranking and filtering (spec 4.8, 5.3, 6.3, 8)."""

from __future__ import annotations

from typing import Literal

Direction = Literal[
    "home_stronger", "away_stronger", "evenly_matched", "btts_yes", "btts_no", "over", "under"
]


def _key(result: dict, direction: Direction) -> float | None:
    mr = result["match_result"]
    diff = mr["venue_adjusted_difference"] if result["basis"] == "venue" else mr["raw_difference"]
    if direction in ("home_stronger", "away_stronger", "evenly_matched"):
        return diff
    if direction in ("btts_yes", "btts_no"):
        return result["btts"]["yes_indicator"]
    return result["over_under_2_5"]["over_indicator"]


def rank(results: list[dict], direction: Direction, threshold: float | None = None) -> list[dict]:
    """Order results for a ranking direction. Results whose indicator cannot be
    calculated are omitted. ``threshold`` filters (difference for 1X2, indicator
    level 0-1 for goals markets, applied to the selected outcome)."""
    scored = [(r, _key(r, direction)) for r in results]
    scored = [(r, k) for r, k in scored if k is not None]
    if direction == "home_stronger":
        keep = [(r, k) for r, k in scored if threshold is None or k >= threshold]
        keep.sort(key=lambda x: -x[1])
    elif direction == "away_stronger":
        keep = [(r, k) for r, k in scored if threshold is None or k <= -threshold]
        keep.sort(key=lambda x: x[1])
    elif direction == "evenly_matched":
        keep = [(r, k) for r, k in scored if threshold is None or abs(k) <= threshold]
        keep.sort(key=lambda x: abs(x[1]))
    elif direction in ("btts_yes", "over"):
        keep = [(r, k) for r, k in scored if threshold is None or k >= threshold]
        keep.sort(key=lambda x: -x[1])
    else:  # btts_no, under: lowest Yes/Over indicator first
        keep = [(r, k) for r, k in scored if threshold is None or (1 - k) >= threshold]
        keep.sort(key=lambda x: x[1])
    return [r for r, _ in keep]
