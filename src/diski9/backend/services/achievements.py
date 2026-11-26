"""My Challenge: Achievements (Phase 7, recognition only).

Read-only and participant-scoped, like ``challenge_history``: the viewer always
comes from the authenticated server-side principal, never from the browser, and
guests get nothing. Development rounds need ``include_development``. Callers pass
the server's own setting (``Backend.show_development``, enabled only outside
production), never a value supplied by the browser. Design and decisions:
``docs/architecture/phase7_achievements.md``.

**Nothing is stored.** Achievements are worked out on every read from the
authoritative published results, so corrections, republication and history are
reflected automatically, with no table, migration, job or back-fill:

1. For each round the viewer entered in the stream, the round's **latest**
   published score set is chosen first, whatever its kind. Only then is
   eligibility applied: the latest score set must be competitive
   (``kind = 'championship'``) and the viewer's entry must be ``ranked``.
   Practice rounds, void rounds (including a competitive round later republished
   as void), all-void refunded entries and rounds with no published results award
   nothing. Championship membership plays no part (D-2).
2. The predictions evaluated are the entry settlement revision that the published
   score set was built from: the latest revision written by a settlement run no
   later than the score set's run. An unchanged entry keeps an earlier revision.
   Provisional revisions written after a reopening are later runs, so they never
   count until the round is republished (D-4).
3. The nine stored legs (frozen bucket, market, outcome and verdict) are checked
   against the round's own frozen configuration, then the six rules are applied.
   A void leg is never correct. Missing or malformed authoritative records raise
   ``AchievementIntegrityError`` rather than being shown as zero achievements.

Achievements never affect credits, rankings, points, eligibility, settlement,
scoring or entitlements.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Engine, text

from diski9.challenge.config import ConfigError, get_config

from ..auth.permissions import Principal
from . import championships as championships_svc
from .common import ServiceError
from .leaderboards import _snapshot, _viewer, _visible


class Badge(StrEnum):
    FOUNDATION_FUNDI = "foundation_fundi"
    BALANCED_BRAWLER = "balanced_brawler"
    CHALLENGER_CHAMP = "challenger_champ"
    GOALS_GURU = "goals_guru"
    BTTS_BONANZA = "btts_bonanza"
    DRAW_DYNAMO = "draw_dynamo"


#: display order: bucket achievements, then market achievements
BADGES: tuple[Badge, ...] = tuple(Badge)
BUCKET_BADGES = {"A": Badge.FOUNDATION_FUNDI, "B": Badge.BALANCED_BRAWLER,
                 "C": Badge.CHALLENGER_CHAMP}  # fmt: skip
#: market badges: (market, outcomes counted, minimum correct selections in one round)
MARKET_BADGES = {
    Badge.GOALS_GURU: ("OU25", frozenset({"OVER_2_5", "UNDER_2_5"}), 3),
    Badge.BTTS_BONANZA: ("BTTS", frozenset({"BTTS_YES", "BTTS_NO"}), 3),
    Badge.DRAW_DYNAMO: ("1X2", frozenset({"DRAW"}), 2),  # D-1: two, not three
}


class Level(StrEnum):
    BEGINNER = "Beginner"
    SEMI_PRO = "Semi-Pro"
    PRO = "Pro"


#: minimum count needed in EVERY one of the six categories (D-1, revised)
LEVEL_THRESHOLDS: tuple[tuple[Level, int], ...] = ((Level.SEMI_PRO, 1), (Level.PRO, 3))
LEVEL_ORDER = {Level.BEGINNER: 0, Level.SEMI_PRO: 1, Level.PRO: 2}

VERDICTS = frozenset({"won", "lost", "void"})  # "pending" never appears in a final result
MARKETS = frozenset({"1X2", "BTTS", "OU25"})


class AchievementIntegrityError(ServiceError):
    """An eligible published entry has no usable authoritative settlement record."""

    code = "achievement_integrity"


# ------------------------------------------------------------------ pure rules
@dataclass(frozen=True)
class Leg:
    position: int
    bucket: str
    market: str
    outcome: str
    verdict: str


def badges_for(legs: Sequence[Leg]) -> frozenset[Badge]:
    """The badges one validated entry earns in one round (at most one of each)."""
    won = [leg for leg in legs if leg.verdict == "won"]
    earned = set()
    for code, badge in BUCKET_BADGES.items():
        bucket = [leg for leg in legs if leg.bucket == code]
        if bucket and all(leg.verdict == "won" for leg in bucket):
            earned.add(badge)
    for badge, (market, outcomes, minimum) in MARKET_BADGES.items():
        if sum(1 for leg in won if leg.market == market and leg.outcome in outcomes) >= minimum:
            earned.add(badge)
    return frozenset(earned)


def level_for(counts: Mapping[Badge, int]) -> Level:
    """Beginner, Semi-Pro (at least 1 of each badge) or Pro (at least 3 of each).
    Every category counts, including those with no badges."""
    lowest = min(counts.get(b, 0) for b in BADGES)
    level = Level.BEGINNER
    for candidate, minimum in LEVEL_THRESHOLDS:
        if lowest >= minimum:
            level = candidate
    return level


@dataclass(frozen=True)
class Progress:
    next_level: Level | None  # None at Pro (badges keep accumulating)
    target: int | None  # badges needed in each category for the next level
    categories_met: int  # categories already at the target
    missing: tuple[Badge, ...]  # categories still below the target


def progress_for(counts: Mapping[Badge, int]) -> Progress:
    current = level_for(counts)
    for candidate, minimum in LEVEL_THRESHOLDS:
        if LEVEL_ORDER[candidate] > LEVEL_ORDER[current]:
            missing = tuple(b for b in BADGES if counts.get(b, 0) < minimum)
            return Progress(candidate, minimum, len(BADGES) - len(missing), missing)
    return Progress(None, None, len(BADGES), ())


def parse_legs(legs_json, config_version: str) -> tuple[Leg, ...]:
    """Validate the stored legs of one final entry settlement against the round's
    own frozen configuration (never the current default). Raises
    ``AchievementIntegrityError``; nothing is guessed or reconstructed."""

    def bad(why: str) -> AchievementIntegrityError:
        return AchievementIntegrityError(
            "Achievements are temporarily unavailable.", details={"reason": why}
        )

    try:
        config = get_config(config_version)
    except ConfigError:
        raise bad(f"unknown configuration {config_version!r}") from None
    raw = legs_json.get("legs") if isinstance(legs_json, dict) else None
    if not isinstance(raw, list) or len(raw) != config.required_selections:
        raise bad("unexpected number of predictions")
    legs = []
    for item in raw:
        if not isinstance(item, dict):
            raise bad("malformed prediction")
        try:
            leg = Leg(int(item["position"]), item["bucket"], item["market"], item["outcome"],
                      item["verdict"])  # fmt: skip
        except (KeyError, TypeError, ValueError):
            raise bad("malformed prediction") from None
        if leg.market not in MARKETS or leg.verdict not in VERDICTS:
            raise bad("unexpected market or verdict")
        legs.append(leg)
    if sorted(leg.position for leg in legs) != list(range(config.required_selections)):
        raise bad("unexpected prediction positions")
    for spec in config.buckets:
        if sum(1 for leg in legs if leg.bucket == spec.code) != spec.selections:
            raise bad("bucket assignments do not match the round's configuration")
    return tuple(sorted(legs, key=lambda leg: leg.position))


# ------------------------------------------------------------------ read model
@dataclass(frozen=True)
class RoundBadges:
    round_id: UUID
    round_code: str
    deadline_at: datetime
    revision: int  # published score set revision the badges come from
    badges: tuple[Badge, ...]  # in display order


@dataclass(frozen=True)
class Achievements:
    stream: str
    counts: Mapping[Badge, int]  # all six, zeros included
    total: int
    level: Level
    progress: Progress
    eligible_rounds: int
    rounds: tuple[RoundBadges, ...]  # every eligible round, oldest first


_ELIGIBLE = """
WITH mine AS (
  SELECT e.id AS entry_id, e.round_id, e.locked_submission_id
    FROM app.entries e
    JOIN app.rounds r ON r.id = e.round_id
    JOIN app.championship_series s ON s.id = r.series_id
   WHERE e.user_id = :me AND e.locked_submission_id IS NOT NULL AND {where}{one}
), latest AS (
  -- the round's latest publication first, whatever its kind (safeguard 3.1)
  SELECT DISTINCT ON (x.round_id) x.round_id, x.id, x.revision, x.kind, x.run_id
    FROM app.score_sets x
   WHERE x.round_id IN (SELECT round_id FROM mine)
   ORDER BY x.round_id, x.revision DESC
)
SELECT r.id AS round_id, r.code, r.deadline_at, r.config_version,
       l.revision, rs.status AS score_status, m.locked_submission_id,
       es.submission_id AS es_submission, es.complete AS es_complete, es.legs
  FROM latest l
  JOIN mine m ON m.round_id = l.round_id
  JOIN app.rounds r ON r.id = l.round_id
  LEFT JOIN app.round_scores rs ON rs.score_set_id = l.id AND rs.entry_id = m.entry_id
  -- the entry settlement the publication was built from (safeguard 3.2)
  LEFT JOIN LATERAL (SELECT submission_id, complete, legs FROM app.entry_settlements es
                      WHERE es.entry_id = m.entry_id AND es.run_id <= l.run_id
                      ORDER BY es.revision DESC LIMIT 1) es ON true
 WHERE l.kind = 'championship'
 ORDER BY r.deadline_at, r.id
"""


def _rounds(conn, me: UUID, stream: str, round_id: UUID | None) -> list[RoundBadges]:
    where, params = championships_svc._stream_where(stream)
    one = " AND e.round_id = :rid" if round_id is not None else ""
    params = params | {"me": me} | ({"rid": round_id} if round_id is not None else {})
    out = []
    for x in conn.execute(text(_ELIGIBLE.format(where=where, one=one)), params):
        if x.score_status is None:
            raise AchievementIntegrityError(
                "Achievements are temporarily unavailable.",
                details={"reason": "locked entry missing from the published results",
                         "round": x.code},
            )  # fmt: skip
        if x.score_status != "ranked":  # void_refunded (all nine void): excluded (D-5)
            continue
        if (
            x.es_submission is None
            or x.es_submission != x.locked_submission_id
            or (not x.es_complete)
        ):
            raise AchievementIntegrityError(
                "Achievements are temporarily unavailable.",
                details={"reason": "no complete settlement of the locked submission",
                         "round": x.code},
            )  # fmt: skip
        earned = badges_for(parse_legs(x.legs, x.config_version))
        out.append(RoundBadges(x.round_id, x.code, x.deadline_at, x.revision,
                               tuple(b for b in BADGES if b in earned)))  # fmt: skip
    return out


def my_achievements(
    engine: Engine,
    viewer: Principal | None,
    *,
    stream: str = "beta",
    include_development: bool = False,
) -> Achievements | None:
    """The viewer's achievements in one stream (streams never mix, D-3).
    ``None`` for guests."""
    me = _viewer(viewer)
    if me is None:
        return None
    _visible(stream, include_development)
    with _snapshot(engine) as conn:  # one consistent read (safeguard 3.2)
        rounds = _rounds(conn, me, stream, None)
    counts = {b: 0 for b in BADGES}
    for r in rounds:
        for b in r.badges:
            counts[b] += 1
    return Achievements(
        stream=stream,
        counts=counts,
        total=sum(counts.values()),
        level=level_for(counts),
        progress=progress_for(counts),
        eligible_rounds=len(rounds),
        rounds=tuple(rounds),
    )


def my_round_badges(
    engine: Engine,
    viewer: Principal | None,
    round_id: UUID,
    *,
    stream: str = "beta",
    include_development: bool = False,
) -> RoundBadges | None:
    """The viewer's badges for one round (History detail), with the same ownership,
    stream and eligibility rules as ``my_achievements``. ``None`` for guests and
    for rounds that are not eligible or not the viewer's."""
    me = _viewer(viewer)
    if me is None:
        return None
    _visible(stream, include_development)
    with _snapshot(engine) as conn:
        rounds = _rounds(conn, me, stream, round_id)
    return rounds[0] if rounds else None


__all__ = [
    "BADGES",
    "AchievementIntegrityError",
    "Achievements",
    "Badge",
    "Leg",
    "Level",
    "Progress",
    "RoundBadges",
    "badges_for",
    "level_for",
    "my_achievements",
    "my_round_badges",
    "parse_legs",
    "progress_for",
]
