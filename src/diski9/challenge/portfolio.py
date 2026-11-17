"""Weekly Challenge portfolio engine: 280 groupings, exact payouts, efficient frontier.

Pure, deterministic and dependency-free (standard library only). No database,
network or API access. A player's nine selections are grouped into three
three-fold **buckets** (A, B, C) plus one **nine-fold** containing all nine, with
the fixed allocation of 100 virtual credits: 30 / 30 / 30 / 10.

Mathematics (validated in Phase 5B, ``docs/research/weekly_challenge_portfolio_
optimisation.md`` on branch ``research/weekly-challenge-optimisation``):

* Fixtures are independent. A bucket wins with probability P_j = product of its
  three selection probabilities; its combined odds O_j = product of their odds.
* Three bucket outcomes give exactly 2^3 = 8 states. State (a, b, c) has
  probability prod(P_j if won else 1 - P_j). Its gross payout is the sum of the
  winning buckets' payouts, plus the nine-fold payout **only** in (1, 1, 1): the
  nine-fold wins exactly when all three buckets win. No simulation is used.
* Recovery = P(gross >= 100 credits); expected gross = sum of P(s) x gross(s).

Payout precision (decision D-15, approved):

* ``SETTLEMENT`` (the product convention): every accumulator's gross payout is
  stake x exact combined odds, rounded **half-up to 0.01 credit**; a state's gross
  is the sum of its winning accumulators' rounded payouts; recovery compares that
  value with ``Decimal("100.00")`` exactly. Settlement uses the same rule, so the
  modelled payouts are what a winning entry is paid.
* ``EXACT`` (comparison only): unrounded payouts, the Phase 5B research convention,
  used to verify the 5x scaling of the research results.

Odds and combined odds are exact ``Decimal`` values; probabilities are binary
floats at full precision and are never rounded by the engine.

Efficient frontier: Pareto efficiency on (recovery probability, expected gross
return), both higher-is-better. Coordinates are snapped to grids first
(probability 1e-12, credits 5e-6 - Phase 5B's 1e-6 at 20 credits, scaled with the
stakes) so floating-point noise never decides dominance; points with identical
snapped coordinates never dominate each other. The recommendation is the
efficient grouping with the highest recovery probability, then the highest
expected gross return, then the lowest canonical partition ID - always efficient.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

# ----------------------------------------------------------------- constants
BUCKET_STAKE = 30  # credits per bucket (fixed; not adjustable)
NINE_FOLD_STAKE = 10  # credits on the nine-fold (fixed)
TOTAL_STAKE = 3 * BUCKET_STAKE + NINE_FOLD_STAKE  # 100 credits
RECOVERY_TARGET = Decimal("100.00")
CREDIT_QUANTUM = Decimal("0.01")
ALLOCATION_VERSION = "30-30-30-10/v1"
ENGINE_VERSION = "portfolio/1.0"
N_SELECTIONS = 9
N_PARTITIONS = 280  # 9! / ((3!)^3 * 3!)
BUCKET_LABELS = ("A", "B", "C")
STATES: tuple[tuple[int, int, int], ...] = tuple(itertools.product((0, 1), repeat=3))
PROB_GRID = 1e-12  # Pareto snapping for probabilities
CREDIT_GRID = 5e-6  # Pareto snapping for expected credits (1e-6 at Phase 5B's 20 credits)

assert TOTAL_STAKE == 100


class Precision(StrEnum):
    SETTLEMENT = "settlement"  # D-15: accumulator payouts rounded half-up to 0.01
    EXACT = "exact"  # unrounded (Phase 5B research convention)


class PortfolioInputError(ValueError):
    """Invalid selections or partition passed to the engine."""


# ------------------------------------------------------------------- inputs
@dataclass(frozen=True)
class Selection:
    """One chosen outcome: model probability and reference decimal odds."""

    selection_id: str
    fixture_id: int | str
    probability: float
    odds: Decimal
    label: str = ""


def _to_decimal(value, field: str, who: str) -> Decimal:
    if isinstance(value, bool):
        raise PortfolioInputError(f"{who}: {field} must be a number, got {value!r}")
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise PortfolioInputError(f"{who}: {field} {value!r} is not a valid number") from None
    if not d.is_finite():
        raise PortfolioInputError(f"{who}: {field} must be finite, got {value!r}")
    return d


def make_selection(selection_id, fixture_id, probability, odds, label: str = "") -> Selection:
    """Validate and build one selection (odds accepted as Decimal, str or number)."""
    if selection_id is None or not str(selection_id).strip():
        raise PortfolioInputError("Each selection needs a non-empty selection_id")
    who = f"Selection {selection_id!r}"
    if fixture_id is None or (isinstance(fixture_id, str) and not fixture_id.strip()):
        raise PortfolioInputError(f"{who}: fixture_id is required")
    if isinstance(probability, bool) or not isinstance(probability, int | float):
        raise PortfolioInputError(f"{who}: probability must be a number, got {probability!r}")
    p = float(probability)
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise PortfolioInputError(f"{who}: probability must be within [0, 1], got {probability!r}")
    o = _to_decimal(odds, "odds", who)
    if o < 1:
        raise PortfolioInputError(f"{who}: decimal odds must be at least 1.00, got {odds!r}")
    return Selection(str(selection_id), fixture_id, p, o, label)


def validate_selections(selections: Sequence[Selection]) -> tuple[Selection, ...]:
    """Exactly nine valid selections on nine distinct fixtures with unique IDs."""
    sels = tuple(selections)
    if len(sels) != N_SELECTIONS:
        raise PortfolioInputError(
            f"A Weekly Challenge entry needs exactly {N_SELECTIONS} selections, got {len(sels)}"
        )
    checked = []
    for s in sels:
        if not isinstance(s, Selection):
            raise PortfolioInputError(f"Expected Selection objects, got {type(s).__name__}")
        checked.append(make_selection(s.selection_id, s.fixture_id, s.probability, s.odds, s.label))
    ids = [s.selection_id for s in checked]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise PortfolioInputError(f"Duplicate selection_id(s): {', '.join(dup)}")
    fixtures = [s.fixture_id for s in checked]
    if len(set(fixtures)) != len(fixtures):
        dup = sorted({str(f) for f in fixtures if fixtures.count(f) > 1})
        raise PortfolioInputError(
            f"Each fixture can be selected only once; duplicate fixture_id(s): {', '.join(dup)}"
        )
    return tuple(checked)


# --------------------------------------------------------------- partitions
Partition = tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]


def _generate() -> tuple[Partition, ...]:
    def rec(items: tuple[int, ...]):
        if not items:
            yield ()
            return
        first, rest = items[0], items[1:]
        for pair in itertools.combinations(rest, 2):
            remaining = tuple(x for x in rest if x not in pair)
            for tail in rec(remaining):
                yield ((first, *pair), *tail)

    return tuple(rec(tuple(range(N_SELECTIONS))))


_PARTITIONS = _generate()


def partitions() -> tuple[Partition, ...]:
    """The 280 canonical partitions of selections 0-8 into three groups of three:
    groups sorted, ordered by smallest element, lexicographic order (as Phase 5B)."""
    return _PARTITIONS


def partition_id(part: Sequence[Sequence[int]]) -> str:
    """Canonical ID, e.g. '012|345|678' (selection positions 0-8)."""
    return "|".join("".join(str(i) for i in g) for g in part)


def parse_partition_id(pid: str) -> Partition:
    try:
        groups = tuple(tuple(int(c) for c in g) for g in pid.split("|"))
    except ValueError:
        raise PortfolioInputError(f"Invalid partition ID {pid!r}") from None
    return validate_partition(groups)


def validate_partition(part: Sequence[Sequence[int]]) -> Partition:
    """Three disjoint groups of three covering positions 0-8, returned canonical."""
    try:
        groups = [tuple(int(i) for i in g) for g in part]
    except (TypeError, ValueError):
        raise PortfolioInputError(f"Invalid partition structure: {part!r}") from None
    if len(groups) != 3 or any(len(g) != 3 for g in groups):
        raise PortfolioInputError("A partition needs exactly three buckets of three selections")
    flat = [i for g in groups for i in g]
    if sorted(flat) != list(range(N_SELECTIONS)):
        raise PortfolioInputError(
            "A partition must use each selection position 0-8 exactly once across the buckets"
        )
    canonical = tuple(sorted(tuple(sorted(g)) for g in groups))
    return canonical  # type: ignore[return-value]


# -------------------------------------------------------------- arithmetic
def round_credits(x: Decimal) -> Decimal:
    """Half-up to 0.01 credit (the D-15 settlement rule)."""
    return x.quantize(CREDIT_QUANTUM, rounding=ROUND_HALF_UP)


def _payout(stake: int, odds: Decimal, precision: Precision) -> Decimal:
    raw = stake * odds
    return round_credits(raw) if precision is Precision.SETTLEMENT else raw


# -------------------------------------------------------------- results
@dataclass(frozen=True)
class Accumulator:
    label: str  # "A" | "B" | "C" | "NINE"
    positions: tuple[int, ...]
    selection_ids: tuple[str, ...]
    stake: int
    combined_odds: Decimal  # exact product of the selections' odds
    win_probability: float
    payout: Decimal  # gross if it wins, under the chosen precision
    recovers_alone: bool  # payout >= 100 credits


@dataclass(frozen=True)
class State:
    wins: tuple[int, int, int]  # (A, B, C): 1 = won
    probability: float
    gross: Decimal  # winning accumulators' payouts (+ nine-fold only in (1, 1, 1))


@dataclass(frozen=True)
class PayoutOutcome:
    gross: Decimal
    probability: float  # P(gross == this value)
    at_least: float  # P(gross >= this value)
    states: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class PortfolioResult:
    partition_id: str
    buckets: tuple[Accumulator, Accumulator, Accumulator]
    nine_fold: Accumulator
    states: tuple[State, ...]  # the eight states, in STATES order
    p_recover: float  # P(gross >= 100.00)
    p_profit: float  # P(gross > 100.00)
    p_zero: float  # P(gross == 0): no bucket wins
    expected_gross: float
    expected_net: float
    sd_gross: float  # internal analysis only
    max_gross: Decimal  # all nine win: three buckets + nine-fold
    precision: Precision
    efficient: bool = False
    recommended: bool = False


@dataclass(frozen=True)
class PortfolioSet:
    """All 280 evaluated groupings for one set of nine selections."""

    selections: tuple[Selection, ...]
    results: tuple[PortfolioResult, ...]  # canonical partition order
    efficient_ids: tuple[str, ...]
    recommended_id: str
    precision: Precision
    allocation_version: str = ALLOCATION_VERSION
    engine_version: str = ENGINE_VERSION

    def get(self, pid: str) -> PortfolioResult:
        return self._by_id()[pid]

    def _by_id(self) -> dict[str, PortfolioResult]:
        return {r.partition_id: r for r in self.results}

    @property
    def recommended(self) -> PortfolioResult:
        return self.get(self.recommended_id)


# -------------------------------------------------------------- evaluation
def _accumulator(label, positions, sels, stake, precision) -> Accumulator:
    odds = math.prod((sels[i].odds for i in positions), start=Decimal(1))
    prob = math.prod(sels[i].probability for i in positions)
    pay = _payout(stake, odds, precision)
    return Accumulator(
        label,
        tuple(positions),
        tuple(sels[i].selection_id for i in positions),
        stake,
        odds,
        prob,
        pay,
        pay >= RECOVERY_TARGET,
    )


def _evaluate(
    sels: tuple[Selection, ...], part: Partition, precision: Precision
) -> PortfolioResult:
    buckets = tuple(
        _accumulator(lbl, g, sels, BUCKET_STAKE, precision)
        for lbl, g in zip(BUCKET_LABELS, part, strict=True)
    )
    nine = _accumulator("NINE", tuple(range(N_SELECTIONS)), sels, NINE_FOLD_STAKE, precision)
    P = [b.win_probability for b in buckets]
    states = []
    for wins in STATES:
        prob = math.prod(P[j] if wins[j] else 1.0 - P[j] for j in range(3))
        gross = sum((buckets[j].payout for j in range(3) if wins[j]), Decimal(0))
        if all(wins):
            gross += nine.payout  # the nine-fold wins only when all three buckets win
        states.append(State(wins, prob, gross))
    mean = sum(s.probability * float(s.gross) for s in states)
    var = sum(s.probability * (float(s.gross) - mean) ** 2 for s in states)
    return PortfolioResult(
        partition_id=partition_id(part),
        buckets=buckets,  # type: ignore[arg-type]
        nine_fold=nine,
        states=tuple(states),
        p_recover=sum(s.probability for s in states if s.gross >= RECOVERY_TARGET),
        p_profit=sum(s.probability for s in states if s.gross > RECOVERY_TARGET),
        p_zero=sum(s.probability for s in states if s.gross == 0),
        expected_gross=mean,
        expected_net=mean - TOTAL_STAKE,
        sd_gross=math.sqrt(max(var, 0.0)),
        max_gross=states[-1].gross,
        precision=precision,
    )


def evaluate_partition(
    selections: Sequence[Selection],
    part: Sequence[Sequence[int]] | str,
    precision: Precision = Precision.SETTLEMENT,
) -> PortfolioResult:
    """Evaluate one grouping (efficiency flags are set by :func:`evaluate_all`)."""
    sels = validate_selections(selections)
    canon = parse_partition_id(part) if isinstance(part, str) else validate_partition(part)
    return _evaluate(sels, canon, Precision(precision))


def _snap(x: float, grid: float) -> int:
    return round(x / grid)


def efficient_mask(points: Iterable[tuple[float, float]]) -> list[bool]:
    """Pareto efficiency for (recovery, expected), both higher-is-better, on
    snapped coordinates. Order-independent; identical coordinates never dominate
    each other."""
    pts = [(_snap(x, PROB_GRID), _snap(y, CREDIT_GRID)) for x, y in points]
    # sweep: sort by x desc, y desc; a point is dominated if some point with
    # x >= its x has a larger y, or the same y with a larger x.
    order = sorted(range(len(pts)), key=lambda i: (-pts[i][0], -pts[i][1]))
    mask = [True] * len(pts)
    best_y_strictly_greater_x = None  # max y among points with strictly greater x
    i = 0
    while i < len(order):
        j = i
        x = pts[order[i]][0]
        while j < len(order) and pts[order[j]][0] == x:
            j += 1
        group = order[i:j]  # same x, sorted by y desc
        top_y = pts[group[0]][1]
        for k in group:
            y = pts[k][1]
            dominated = y < top_y or (
                best_y_strictly_greater_x is not None and best_y_strictly_greater_x >= y
            )
            mask[k] = not dominated
        best_y_strictly_greater_x = (
            top_y if best_y_strictly_greater_x is None else max(best_y_strictly_greater_x, top_y)
        )
        i = j
    return mask


def recommend(results: Sequence[PortfolioResult], mask: Sequence[bool]) -> str:
    """Efficient grouping with the highest recovery, then the highest expected
    gross return, then the lowest canonical partition ID."""
    candidates = [r for r, e in zip(results, mask, strict=True) if e]
    if not candidates:  # impossible for a non-empty set; kept as a guard
        raise PortfolioInputError("No efficient grouping found")
    best = min(
        candidates,
        key=lambda r: (
            -_snap(r.p_recover, PROB_GRID),
            -_snap(r.expected_gross, CREDIT_GRID),
            r.partition_id,
        ),
    )
    return best.partition_id


def evaluate_all(
    selections: Sequence[Selection], precision: Precision = Precision.SETTLEMENT
) -> PortfolioSet:
    """Evaluate all 280 groupings, classify efficiency and pick the recommendation."""
    sels = validate_selections(selections)
    precision = Precision(precision)
    raw = [_evaluate(sels, part, precision) for part in _PARTITIONS]
    mask = efficient_mask((r.p_recover, r.expected_gross) for r in raw)
    rec = recommend(raw, mask)
    results = tuple(
        replace(r, efficient=e, recommended=(r.partition_id == rec))
        for r, e in zip(raw, mask, strict=True)
    )
    return PortfolioSet(
        selections=sels,
        results=results,
        efficient_ids=tuple(r.partition_id for r in results if r.efficient),
        recommended_id=rec,
        precision=precision,
    )


# ------------------------------------------------------- payout distribution
def payout_distribution(result: PortfolioResult) -> tuple[PayoutOutcome, ...]:
    """Distinct gross payouts (ascending) with P(exactly) and P(at least).

    States with identical gross payouts (exact ``Decimal`` equality, at the
    result's precision) are aggregated. ``at_least`` for a payout v is summed
    over the states with gross >= v **in the same state order as**
    ``p_recover``, so the value at the first payout >= 100 credits is bitwise
    identical to ``result.p_recover``. Sums of non-negative floats over nested
    state sets are non-increasing; values are capped at 1 and the smallest
    payout's value is exactly 1 (a gross of at least the minimum is certain)."""
    groups: dict[Decimal, list[State]] = {}
    for s in result.states:
        groups.setdefault(s.gross, []).append(s)
    out = []
    for k, v in enumerate(sorted(groups)):
        exact = sum(s.probability for s in result.states if s.gross == v)
        at_least = 1.0 if k == 0 else min(probability_at_least(result, v), 1.0)
        out.append(PayoutOutcome(v, exact, at_least, tuple(s.wins for s in groups[v])))
    return tuple(out)


def probability_at_least(result: PortfolioResult, threshold) -> float:
    """P(gross >= threshold), summed over the eight states (threshold in credits)."""
    t = _to_decimal(threshold, "threshold", "probability_at_least")
    return sum(s.probability for s in result.states if s.gross >= t)


def probability_exactly(result: PortfolioResult, payout) -> float:
    """P(gross == payout) at the result's precision (0 if no state pays exactly that)."""
    v = _to_decimal(payout, "payout", "probability_exactly")
    return sum(s.probability for s in result.states if s.gross == v)
