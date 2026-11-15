"""Pure classification rules for fixtures: status, round type, statistical
eligibility and venue. Kept free of I/O so they are easy to test and audit.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

# API-Football status codes (documentation + observed values).
FINAL_STATUSES = frozenset({"FT", "AET", "PEN"})
UPCOMING_STATUSES = frozenset({"TBD", "NS"})
LIVE_STATUSES = frozenset({"1H", "HT", "2H", "ET", "BT", "P", "LIVE"})
EXCLUDED_STATUS_REASONS = {
    "PST": "postponed",
    "CANC": "cancelled",
    "ABD": "abandoned",
    "AWD": "awarded",
    "WO": "walkover",
    "SUSP": "suspended",
    "INT": "interrupted",
}

_REGULAR = re.compile(r"^regular season\b", re.I)
_RELEGATION = re.compile(r"relegation", re.I)
_PROMOTION = re.compile(r"promotion", re.I)
_PLAYOFF = re.compile(r"play-?offs?|finals?\b|semi-finals?|quarter-finals?", re.I)


def classify_round(round_name: str | None) -> str:
    """Map an API round label to regular | relegation | promotion | playoff | other.

    Observed labels: "Regular Season - 12", "Playoffs - 1", "Finals - 1",
    "Relegation Round - 1", "Semi-finals", "Final".
    """
    if not round_name:
        return "other"
    if _REGULAR.search(round_name):
        return "regular"
    if _RELEGATION.search(round_name):
        return "relegation"
    if _PROMOTION.search(round_name):
        return "promotion"
    if _PLAYOFF.search(round_name):
        return "playoff"
    return "other"


def stats_exclusion_reason(
    status_short: str,
    round_type: str,
    ft_home: int | None,
    ft_away: int | None,
) -> str | None:
    """Reason a fixture is excluded from default statistical windows, or None.

    Order matters: an unplayed or void match is reported as such before the
    round-type exclusion, so the reason is the most fundamental one.
    """
    if status_short in EXCLUDED_STATUS_REASONS:
        return EXCLUDED_STATUS_REASONS[status_short]
    if status_short in UPCOMING_STATUSES:
        return "not_started"
    if status_short in LIVE_STATUSES:
        return "in_progress"
    if status_short not in FINAL_STATUSES:
        return "unknown_status"
    if ft_home is None or ft_away is None:
        return "missing_score"
    if round_type != "regular":
        return f"{round_type}_round" if round_type != "other" else "non_regular_round"
    return None


def is_final(status_short: str, ft_home: int | None, ft_away: int | None) -> bool:
    return status_short in FINAL_STATUSES and ft_home is not None and ft_away is not None


# ------------------------------------------------------------------- venues
@dataclass(frozen=True)
class TeamGround:
    registered_venue_id: int | None = None
    modal_venue_id: int | None = None

    @property
    def ids(self) -> set[int]:
        return {v for v in (self.registered_venue_id, self.modal_venue_id) if v is not None}


def modal_home_venue(venue_ids: Iterable[int | None], min_matches: int = 3, min_share: float = 0.5):
    """Most common non-null venue among a team's home fixtures, if dominant enough."""
    counts = Counter(v for v in venue_ids if v is not None)
    if not counts:
        return None
    venue, n = counts.most_common(1)[0]
    total = sum(counts.values())
    if n >= min_matches and n / total >= min_share:
        return venue
    return None


def classify_venue(
    venue_id: int | None,
    home: TeamGround,
    away: TeamGround,
    override: str | None = None,
) -> tuple[str, str]:
    """Return (classification, reason).

    * ``home_ground``        venue is the home team's registered or usual ground
    * ``potential_neutral``  venue known, but not a recognised home ground of the home team
    * ``neutral``            only via an explicit override
    * ``unknown``            venue missing, or the home team's grounds are unknown

    Never invents a classification: missing information yields ``unknown``.
    """
    if override:
        return override, "explicit_override"
    if venue_id is None:
        return "unknown", "venue_missing"
    if not home.ids:
        return "unknown", "home_ground_unknown"
    if venue_id in home.ids:
        return "home_ground", (
            "registered_ground" if venue_id == home.registered_venue_id else "usual_ground"
        )
    if venue_id in away.ids:
        return "potential_neutral", "away_team_ground"
    return "potential_neutral", "not_home_team_ground"
