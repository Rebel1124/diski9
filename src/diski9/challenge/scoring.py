"""Weekly Challenge and championship scoring (Phase 6A.3). Pure and deterministic.

Scoring is independent of portfolio probability evaluation: its inputs are
**settled** aggregate gross payouts. Everything is recomputed from validated
inputs - there are no incremental point adjustments - so a corrected settlement
simply re-scores the round and the championship.

Approved rules (``points-150-75-v2``, decision register D-26, D-27, D-28, D-30,
D-31):

* Weekly rank = 1 + the number of championship-eligible entrants with a strictly
  greater settled gross (standard competition ranking; equivalent to ranking by
  net, because every entry starts with 100 credits).
* Recovery = gross >= 100.00 (exactly 100.00 recovers). Without recovery: 0
  points at any rank. With recovery: rank 1-10 earns 150/135/125/120/115/110/
  105/100/95/90; any other rank earns 75. Tied entrants each receive the full
  points of the shared rank; following ranks are skipped. Points are integers and
  non-additive (first place earns 150 in total).
* Only **competitive** rounds award points. Practice rounds (fewer than five valid
  entries at the deadline) and void rounds award none and do not advance the
  championship.
* A championship is exactly ten competitive rounds. Standings: total points, then
  recoveries, then qualifying top-ten finishes; still level = shared rank (joint
  champions allowed). Cumulative credits are never a tie-breaker. Participant
  identifiers only fix a deterministic **display** order among equal ranks.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from diski9.challenge.config import ConfigError

CREDIT_QUANTUM = Decimal("0.01")


class ScoringInputError(ValueError):
    """Invalid round results or championship inputs."""


class RoundClassification(StrEnum):
    COMPETITIVE = "competitive"  # >= min entries at the deadline; awards points
    PRACTICE = "practice"  # fewer than min entries; settles, no points
    VOID = "void"  # cancelled/invalidated as a whole; nothing counts


class SettlementBasis(StrEnum):
    SETTLED = "settled"  # gross produced by settled predictions
    ALL_SELECTIONS_VOID = "all_selections_void"  # every pick void: stakes returned, gross 100.00


class AllVoidPolicy(StrEnum):
    """How an entry whose nine selections were all void is treated (outstanding
    decision; see the engine documentation)."""

    SCORE_AS_SETTLED = "score_as_settled"  # literal approved rule: 100.00 recovers
    NO_POINTS = "no_points"  # ranked, but no points, recovery or top-ten credit


@dataclass(frozen=True)
class ScoringConfig:
    version: str
    top_points: tuple[int, ...]  # points for ranks 1..len(top_points), with recovery
    recovery_points: int  # any other rank, with recovery
    recovery_target: Decimal = Decimal("100.00")
    max_weekly_points: int = 150
    championship_rounds: int = 10
    min_competitive_entries: int = 5
    all_void_policy: AllVoidPolicy = AllVoidPolicy.SCORE_AS_SETTLED

    def __post_init__(self) -> None:
        def pos_int(v):
            return isinstance(v, int) and not isinstance(v, bool) and v > 0

        if not isinstance(self.version, str) or not self.version.strip():
            raise ConfigError("Scoring version must be a non-empty string")
        if not isinstance(self.top_points, tuple) or not self.top_points:
            raise ConfigError("top_points must be a non-empty tuple")
        if not all(pos_int(p) for p in (*self.top_points, self.recovery_points)):
            raise ConfigError("Points must be positive integers")
        if list(self.top_points) != sorted(self.top_points, reverse=True):
            raise ConfigError("top_points must be non-increasing")
        if self.recovery_points > self.top_points[-1]:
            raise ConfigError("recovery_points cannot exceed the last top-ten award")
        if not pos_int(self.max_weekly_points) or self.top_points[0] > self.max_weekly_points:
            raise ConfigError("The first-place award cannot exceed max_weekly_points")
        if self.recovery_target != Decimal("100.00"):
            raise ConfigError("recovery_target must be Decimal('100.00')")
        if not pos_int(self.championship_rounds) or not pos_int(self.min_competitive_entries):
            raise ConfigError("championship_rounds and min_competitive_entries must be positive")
        if not isinstance(self.all_void_policy, AllVoidPolicy):
            raise ConfigError("all_void_policy must be an AllVoidPolicy")

    @property
    def max_championship_points(self) -> int:
        return self.max_weekly_points * self.championship_rounds

    def points_for(self, rank: int, recovered: bool) -> int:
        if not recovered:
            return 0
        return self.top_points[rank - 1] if rank <= len(self.top_points) else self.recovery_points


POINTS_150_75_V2 = ScoringConfig(
    version="points-150-75-v2",
    top_points=(150, 135, 125, 120, 115, 110, 105, 100, 95, 90),
    recovery_points=75,
)
_REGISTRY = {POINTS_150_75_V2.version: POINTS_150_75_V2}


def get_scoring_config(version: str) -> ScoringConfig:
    try:
        return _REGISTRY[version]
    except KeyError:
        raise ConfigError(f"Unknown scoring configuration version {version!r}") from None


# ------------------------------------------------------------------ inputs
@dataclass(frozen=True)
class EntryResult:
    """One participant's settled result for one round.

    ``championship_eligible=False`` marks an entry excluded from championship
    scoring after the deadline (for example a disqualification); it is not
    ranked and earns nothing, and it does not change the round's classification.
    """

    participant_id: str
    gross: Decimal  # settled aggregate gross, exact to 0.01 credit
    basis: SettlementBasis = SettlementBasis.SETTLED
    championship_eligible: bool = True
    ineligible_reason: str | None = None


@dataclass(frozen=True)
class RoundResult:
    """Settled results of one round. ``entries`` are the valid entries at the
    deadline, one per participant (resubmissions already collapsed to the final
    version). ``final=False`` means the settlement is provisional."""

    round_id: str
    championship_id: str | None
    classification: RoundClassification
    entries: tuple[EntryResult, ...]
    scoring_version: str
    final: bool = True


def classify_round(
    valid_entries: int, cancelled: bool, config: ScoringConfig = POINTS_150_75_V2
) -> RoundClassification:
    """The approved designation, fixed at the deadline (D-28)."""
    if isinstance(valid_entries, bool) or not isinstance(valid_entries, int) or valid_entries < 0:
        raise ScoringInputError("valid_entries must be a non-negative integer")
    if cancelled:
        return RoundClassification.VOID
    if valid_entries < config.min_competitive_entries:
        return RoundClassification.PRACTICE
    return RoundClassification.COMPETITIVE


def _nonempty(v, what: str) -> None:
    if not isinstance(v, str) or not v.strip():
        raise ScoringInputError(f"{what} must be a non-empty string, got {v!r}")


def validate_round(r: RoundResult, config: ScoringConfig = POINTS_150_75_V2) -> None:
    if not isinstance(r, RoundResult):
        raise ScoringInputError(f"Expected RoundResult, got {type(r).__name__}")
    _nonempty(r.round_id, "round_id")
    if r.championship_id is not None:
        _nonempty(r.championship_id, "championship_id")
    if r.scoring_version != config.version:
        raise ScoringInputError(
            f"Round {r.round_id}: scoring version {r.scoring_version!r} != {config.version!r}"
        )
    try:
        cls = RoundClassification(r.classification)
    except ValueError:
        raise ScoringInputError(f"Round {r.round_id}: unknown classification") from None
    if not isinstance(r.final, bool):
        raise ScoringInputError(f"Round {r.round_id}: final must be True or False")
    seen = set()
    for e in r.entries:
        if not isinstance(e, EntryResult):
            raise ScoringInputError(f"Round {r.round_id}: entries must be EntryResult objects")
        _nonempty(e.participant_id, "participant_id")
        if e.participant_id in seen:
            raise ScoringInputError(
                f"Round {r.round_id}: duplicate result for participant {e.participant_id!r}"
            )
        seen.add(e.participant_id)
        if e.gross is None:
            raise ScoringInputError(
                f"Round {r.round_id}: {e.participant_id!r} is unsettled; supply a settled "
                "(provisional or final) gross"
            )
        if not isinstance(e.gross, Decimal) or not e.gross.is_finite() or e.gross < 0:
            raise ScoringInputError(f"Round {r.round_id}: gross must be a non-negative Decimal")
        if e.gross != e.gross.quantize(CREDIT_QUANTUM):
            raise ScoringInputError(
                f"Round {r.round_id}: gross {e.gross} is not settled to 0.01 credit"
            )
        if SettlementBasis(e.basis) is SettlementBasis.ALL_SELECTIONS_VOID and e.gross != Decimal(
            "100.00"
        ):
            raise ScoringInputError(
                f"Round {r.round_id}: an all-void entry returns exactly 100.00, got {e.gross}"
            )
        if not isinstance(e.championship_eligible, bool):
            raise ScoringInputError("championship_eligible must be True or False")
        if not e.championship_eligible and not e.ineligible_reason:
            raise ScoringInputError(
                f"Round {r.round_id}: {e.participant_id!r} is ineligible without a reason"
            )
    n = len(r.entries)
    if cls is RoundClassification.COMPETITIVE:
        if r.championship_id is None:
            raise ScoringInputError(f"Round {r.round_id}: a competitive round needs a championship")
        if n < config.min_competitive_entries:
            raise ScoringInputError(
                f"Round {r.round_id}: {n} valid entries; a competitive round needs "
                f"{config.min_competitive_entries} (it is a practice round)"
            )
    elif cls is RoundClassification.PRACTICE and n >= config.min_competitive_entries:
        raise ScoringInputError(
            f"Round {r.round_id}: {n} valid entries make it competitive, not practice"
        )


# ------------------------------------------------------------------ weekly
@dataclass(frozen=True)
class WeeklyScore:
    participant_id: str
    gross: Decimal
    net: Decimal
    rank: int | None  # None when not ranked (void round or ineligible entry)
    points: int
    recovered: bool  # gross >= 100.00 (informational in practice rounds)
    qualifying_top10: bool  # rank <= 10, recovered, competitive round
    counts_for_championship: bool  # contributes to championship aggregates
    basis: SettlementBasis
    display_order: int
    note: str = ""


@dataclass(frozen=True)
class RoundScore:
    round_id: str
    championship_id: str | None
    classification: RoundClassification
    scoring_version: str
    final: bool
    scores: tuple[WeeklyScore, ...]  # in display order

    @property
    def awards_points(self) -> bool:
        return self.classification is RoundClassification.COMPETITIVE

    def score_of(self, participant_id: str) -> WeeklyScore:
        for s in self.scores:
            if s.participant_id == participant_id:
                return s
        raise KeyError(participant_id)


def competition_ranks(values: Sequence[Decimal]) -> list[int]:
    """Standard competition ranking, higher is better: 1 + #strictly greater."""
    order = sorted(values, reverse=True)
    first: dict[Decimal, int] = {}
    for i, v in enumerate(order):
        first.setdefault(v, i + 1)
    return [first[v] for v in values]


def score_round(r: RoundResult, config: ScoringConfig = POINTS_150_75_V2) -> RoundScore:
    """Weekly ranks and championship points for one round."""
    validate_round(r, config)
    cls = RoundClassification(r.classification)
    target = config.recovery_target
    ranked = (
        [e for e in r.entries if e.championship_eligible]
        if cls is not RoundClassification.VOID
        else []
    )
    ranks = dict(
        zip(
            (e.participant_id for e in ranked),
            competition_ranks([e.gross for e in ranked]),
            strict=True,
        )
    )
    rows = []
    for e in r.entries:
        basis = SettlementBasis(e.basis)
        rank = ranks.get(e.participant_id)
        recovered = e.gross >= target and cls is not RoundClassification.VOID
        counted = cls is RoundClassification.COMPETITIVE and e.championship_eligible
        note = ""
        if cls is RoundClassification.VOID:
            note = "void round: stakes returned, nothing counts"
        elif cls is RoundClassification.PRACTICE:
            note = "practice round: no championship points"
        elif not e.championship_eligible:
            note = f"not eligible for championship scoring: {e.ineligible_reason}"
        scoring_recovery = recovered
        if (
            counted
            and basis is SettlementBasis.ALL_SELECTIONS_VOID
            and config.all_void_policy is AllVoidPolicy.NO_POINTS
        ):
            scoring_recovery = False
            note = "all selections void: no championship points (policy)"
        points = config.points_for(rank, scoring_recovery) if counted else 0
        top10 = counted and scoring_recovery and rank is not None and rank <= len(config.top_points)
        assert 0 <= points <= config.max_weekly_points
        rows.append(
            WeeklyScore(
                e.participant_id,
                e.gross,
                e.gross - target,
                rank,
                points,
                recovered if not counted else scoring_recovery,
                top10,
                counted,
                basis,
                0,
                note,
            )
        )
    rows.sort(key=lambda s: (s.rank is None, s.rank or 0, -s.gross, s.participant_id))
    rows = [
        WeeklyScore(
            s.participant_id,
            s.gross,
            s.net,
            s.rank,
            s.points,
            s.recovered,
            s.qualifying_top10,
            s.counts_for_championship,
            s.basis,
            i + 1,
            s.note,
        )
        for i, s in enumerate(rows)
    ]
    return RoundScore(r.round_id, r.championship_id, cls, config.version, r.final, tuple(rows))


# ------------------------------------------------------------ championship
@dataclass(frozen=True)
class ChampionshipStanding:
    rank: int
    participant_id: str
    points: int
    rounds_entered: int
    recoveries: int
    qualifying_top10: int
    display_order: int


@dataclass(frozen=True)
class ChampionshipTable:
    championship_id: str
    scoring_version: str
    competitive_round_ids: tuple[str, ...]
    ignored_round_ids: tuple[str, ...]  # practice and void rounds supplied
    rounds_required: int
    provisional: bool  # any competitive round not final
    standings: tuple[ChampionshipStanding, ...]  # display order

    @property
    def completed_rounds(self) -> int:
        return len(self.competitive_round_ids)

    @property
    def is_complete(self) -> bool:
        return self.completed_rounds == self.rounds_required and not self.provisional

    @property
    def champions(self) -> tuple[str, ...]:
        """Champion(s) once complete; empty while in progress (see ``leaders``)."""
        return self.leaders if self.is_complete else ()

    @property
    def leaders(self) -> tuple[str, ...]:
        return tuple(s.participant_id for s in self.standings if s.rank == 1)


def aggregate_championship(
    championship_id: str,
    rounds: Sequence[RoundResult],
    config: ScoringConfig = POINTS_150_75_V2,
) -> ChampionshipTable:
    """Recompute a championship from its rounds' settled results.

    Practice and void rounds may be supplied; they are ignored. Rejects duplicate
    round IDs, rounds of another championship and more than the required number of
    competitive rounds. Re-running with corrected inputs gives the corrected table."""
    _nonempty(championship_id, "championship_id")
    seen: set[str] = set()
    competitive, ignored = [], []
    for r in rounds:
        validate_round(r, config)
        if r.round_id in seen:
            raise ScoringInputError(f"Round {r.round_id} supplied more than once")
        seen.add(r.round_id)
        if r.championship_id not in (None, championship_id):
            raise ScoringInputError(
                f"Round {r.round_id} belongs to championship {r.championship_id!r}"
            )
        if RoundClassification(r.classification) is RoundClassification.COMPETITIVE:
            competitive.append(score_round(r, config))
        else:
            ignored.append(r.round_id)
    if len(competitive) > config.championship_rounds:
        raise ScoringInputError(
            f"{len(competitive)} competitive rounds; a championship has exactly "
            f"{config.championship_rounds}"
        )
    agg: dict[str, list[int]] = {}  # points, rounds, recoveries, top10
    for rs in competitive:
        for s in rs.scores:
            if not s.counts_for_championship:
                continue
            a = agg.setdefault(s.participant_id, [0, 0, 0, 0])
            a[0] += s.points
            a[1] += 1
            a[2] += s.recovered
            a[3] += s.qualifying_top10
    keys = {p: (a[0], a[2], a[3]) for p, a in agg.items()}
    ordered = sorted(agg, key=lambda p: (tuple(-x for x in keys[p]), p))
    standings = []
    rank = 0
    for i, p in enumerate(ordered):
        if i == 0 or keys[p] != keys[ordered[i - 1]]:
            rank = i + 1
        a = agg[p]
        assert a[0] <= config.max_weekly_points * len(competitive) <= config.max_championship_points
        standings.append(ChampionshipStanding(rank, p, a[0], a[1], a[2], a[3], i + 1))
    return ChampionshipTable(
        championship_id,
        config.version,
        tuple(rs.round_id for rs in competitive),
        tuple(ignored),
        config.championship_rounds,
        any(not rs.final for rs in competitive),
        tuple(standings),
    )
