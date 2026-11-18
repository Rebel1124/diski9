"""Risk-structured Weekly Challenge portfolios: eligibility, validation, feasibility and
exact evaluation (Phase 6A.3). Pure and deterministic; standard library only.

Inputs are **frozen round-sheet outcomes** (:class:`ChallengeOutcome`). Each keeps
three separate numbers that are never mixed:

* ``market_probability`` - margin-adjusted market-implied probability. It alone
  decides eligibility and the bucket.
* ``model_probability`` - Goal Model 1.0. Used only for the model-based risk
  estimate.
* ``reference_odds`` - frozen consensus decimal odds. They alone decide payouts.

The bucket of every selection is **derived** from its market probability; callers
never assign buckets. Odds qualification (at least three independent bookmaker
groups, quotes verified within 24 hours of the snapshot) is checked here against
metadata carried on the outcome; nothing in this module performs I/O.

Mathematics (generalising the validated Phase 6A engine):

* Buckets are disjoint sets of fixtures, assumed independent. Bucket j wins with
  probability P_j = product of its legs' probabilities; its combined odds are the
  exact ``Decimal`` product of the reference odds.
* k buckets give exactly 2^k joint states (8 for the 4/3/2 challenge). The
  nine-fold pays **only** in the state where every bucket wins - it is never a
  separate independent event.
* Payout precision follows D-15 (``Precision.SETTLEMENT``): each accumulator's
  gross payout is stake x combined odds rounded half-up to 0.01 credit; a state's
  gross is the sum of its winning accumulators' rounded payouts; recovery is
  ``gross >= Decimal("100.00")``.
* Market-based and model-based evaluations use identical payouts and differ only
  in the state probabilities. Distributions are conditional on the supplied
  probability estimates and on independence between fixtures.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from diski9.api_football.markets import MARKET_OUTCOMES, MAX_VALID_ODDS, MIN_VALID_ODDS, Market
from diski9.api_football.markets import Outcome as MarketOutcome
from diski9.challenge.config import DEFAULT_CONFIG, ChallengeConfig, ProbabilitySource
from diski9.challenge.portfolio import Precision, round_credits

ENGINE_VERSION = "structured/1.0"


# ---------------------------------------------------------------- errors
class IssueCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_MARKET = "unsupported_market"
    PROBABILITY_BELOW_RANGE = "probability_below_range"
    PROBABILITY_ABOVE_RANGE = "probability_above_range"
    PROBABILITY_UNCLASSIFIED = "probability_unclassified"
    ODDS_TOO_FEW_GROUPS = "odds_too_few_groups"
    ODDS_STALE = "odds_stale"
    ODDS_MISSING_TIMESTAMP = "odds_missing_timestamp"
    DUPLICATE_OUTCOME = "duplicate_outcome"
    DUPLICATE_FIXTURE = "duplicate_fixture"
    BUCKET_OVER_CAPACITY = "bucket_over_capacity"
    INCOMPLETE = "incomplete"
    CANNOT_COMPLETE = "cannot_complete"
    NOT_IN_POOL = "not_in_pool"


BLOCKING = frozenset(IssueCode) - {IssueCode.INCOMPLETE}


@dataclass(frozen=True)
class ValidationIssue:
    code: IssueCode
    message: str
    fixture_id: int | str | None = None
    selection: tuple | None = None  # (fixture_id, market, outcome)
    bucket: str | None = None


class ChallengeInputError(ValueError):
    """A malformed outcome (bad type, probability, odds, market or identifier)."""


class PortfolioValidationError(ValueError):
    """A portfolio that cannot enter the complete-portfolio evaluation pathway."""

    def __init__(self, issues: Sequence[ValidationIssue]):
        self.issues = tuple(issues)
        super().__init__("; ".join(i.message for i in self.issues))


# ---------------------------------------------------------------- inputs
@dataclass(frozen=True)
class ChallengeOutcome:
    """One outcome on a frozen round sheet."""

    fixture_id: int | str
    market: Market
    outcome: MarketOutcome
    market_probability: float
    reference_odds: Decimal
    model_probability: float | None
    bookmaker_groups: int
    latest_observation_at: datetime | None
    league_id: int | None = None
    label: str = ""

    @property
    def key(self) -> tuple:
        return (self.fixture_id, str(self.market), str(self.outcome))

    def probability(self, source: ProbabilitySource) -> float:
        if source is ProbabilitySource.MARKET:
            return self.market_probability
        if self.model_probability is None:
            raise ChallengeInputError(
                f"Outcome {self.key}: Goal Model probability is unavailable; "
                "a model-based estimate cannot be produced"
            )
        return self.model_probability


def _probability(v, name: str, who: str, optional: bool = False) -> float | None:
    if v is None and optional:
        return None
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise ChallengeInputError(f"{who}: {name} must be a number, got {v!r}")
    p = float(v)
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise ChallengeInputError(f"{who}: {name} must be within [0, 1], got {v!r}")
    return p


def make_outcome(
    fixture_id,
    market,
    outcome,
    market_probability,
    reference_odds,
    model_probability,
    bookmaker_groups,
    latest_observation_at,
    league_id=None,
    label: str = "",
) -> ChallengeOutcome:
    """Validate and build one round-sheet outcome."""
    if (
        fixture_id is None
        or isinstance(fixture_id, bool)
        or (isinstance(fixture_id, str) and not fixture_id.strip())
    ):
        raise ChallengeInputError(f"fixture_id is required, got {fixture_id!r}")
    if not isinstance(fixture_id, int | str):
        raise ChallengeInputError(f"fixture_id must be an int or str, got {fixture_id!r}")
    who = f"Outcome {fixture_id}/{market}/{outcome}"
    try:
        m = Market(market)
        o = MarketOutcome(outcome)
    except ValueError:
        raise ChallengeInputError(f"{who}: unknown market or outcome") from None
    if o not in MARKET_OUTCOMES[m]:
        raise ChallengeInputError(f"{who}: outcome {o} does not belong to market {m}")
    pm = _probability(market_probability, "market_probability", who)
    pmod = _probability(model_probability, "model_probability", who, optional=True)
    if isinstance(reference_odds, bool | float):
        raise ChallengeInputError(f"{who}: reference_odds must be a Decimal or string, not float")
    try:
        odds = (
            Decimal(str(reference_odds))
            if not isinstance(reference_odds, Decimal)
            else reference_odds
        )
    except Exception:
        raise ChallengeInputError(
            f"{who}: reference_odds {reference_odds!r} is not a number"
        ) from None
    if not odds.is_finite() or not MIN_VALID_ODDS <= odds <= MAX_VALID_ODDS:
        raise ChallengeInputError(
            f"{who}: reference_odds must be within [{MIN_VALID_ODDS}, {MAX_VALID_ODDS}], "
            f"got {reference_odds!r}"
        )
    g = bookmaker_groups
    if isinstance(g, bool) or not isinstance(g, int) or g < 0:
        raise ChallengeInputError(f"{who}: bookmaker_groups must be a non-negative integer")
    if latest_observation_at is not None and (
        not isinstance(latest_observation_at, datetime) or latest_observation_at.tzinfo is None
    ):
        raise ChallengeInputError(f"{who}: latest_observation_at must be a timezone-aware datetime")
    if league_id is not None and (isinstance(league_id, bool) or not isinstance(league_id, int)):
        raise ChallengeInputError(f"{who}: league_id must be an integer")
    return ChallengeOutcome(
        fixture_id, m, o, pm, odds, pmod, g, latest_observation_at, league_id, label
    )


def _check_snapshot(snapshot_at: datetime) -> None:
    if not isinstance(snapshot_at, datetime) or snapshot_at.tzinfo is None:
        raise ChallengeInputError("snapshot_at must be a timezone-aware datetime")


# ---------------------------------------------------------- eligibility
@dataclass(frozen=True)
class OutcomeAssessment:
    outcome: ChallengeOutcome
    bucket: str | None  # None when ineligible
    issues: tuple[ValidationIssue, ...]

    @property
    def eligible(self) -> bool:
        return self.bucket is not None and not self.issues


def classify_probability(
    probability: float, config: ChallengeConfig = DEFAULT_CONFIG
) -> str | None:
    """Bucket code ("A", "B", "C") for a full-precision market probability, else None."""
    p = _probability(probability, "probability", "classify_probability")
    return config.classify(p)


def assess_outcome(
    outcome: ChallengeOutcome, snapshot_at: datetime, config: ChallengeConfig = DEFAULT_CONFIG
) -> OutcomeAssessment:
    """Eligibility at the snapshot: supported market, probability band, odds rules."""
    _check_snapshot(snapshot_at)
    if not isinstance(outcome, ChallengeOutcome):
        raise ChallengeInputError(f"Expected ChallengeOutcome, got {type(outcome).__name__}")
    issues = []
    key = outcome.key
    if outcome.market not in config.supported_markets:
        issues.append(
            ValidationIssue(
                IssueCode.UNSUPPORTED_MARKET,
                f"{key}: market {outcome.market} is not supported",
                outcome.fixture_id,
                key,
            )
        )
    bucket = config.classify(outcome.market_probability)
    if bucket is None:
        lowest = min(b.band.lower for b in config.buckets)
        highest = max(b.band.upper for b in config.buckets)
        p = outcome.market_probability
        code = (
            IssueCode.PROBABILITY_BELOW_RANGE
            if p < lowest
            else IssueCode.PROBABILITY_ABOVE_RANGE
            if p > highest
            else IssueCode.PROBABILITY_UNCLASSIFIED
        )
        issues.append(
            ValidationIssue(
                code,
                f"{key}: market probability {p:.4%} is outside every bucket band",
                outcome.fixture_id,
                key,
            )
        )
    rules = config.odds
    if outcome.bookmaker_groups < rules.min_bookmaker_groups:
        issues.append(
            ValidationIssue(
                IssueCode.ODDS_TOO_FEW_GROUPS,
                f"{key}: odds from {outcome.bookmaker_groups} independent bookmaker group(s); "
                f"{rules.min_bookmaker_groups} required",
                outcome.fixture_id,
                key,
            )
        )
    seen = outcome.latest_observation_at
    if seen is None:
        issues.append(
            ValidationIssue(
                IssueCode.ODDS_MISSING_TIMESTAMP,
                f"{key}: odds have no verified observation time",
                outcome.fixture_id,
                key,
            )
        )
    elif seen > snapshot_at or snapshot_at - seen > rules.max_quote_age:
        issues.append(
            ValidationIssue(
                IssueCode.ODDS_STALE,
                f"{key}: odds were not verified within {rules.max_quote_age} before the snapshot",
                outcome.fixture_id,
                key,
            )
        )
    return OutcomeAssessment(outcome, bucket, tuple(issues))


# ---------------------------------------------------------- feasibility
def _bands_by_fixture(assessments: Iterable[OutcomeAssessment]) -> dict:
    bands: dict = {}
    for a in assessments:
        if a.eligible:
            bands.setdefault(a.outcome.fixture_id, set()).add(a.bucket)
    return bands


def _match(need: dict[str, int], fixture_bands: dict) -> bool:
    """Exact bipartite matching (augmenting paths): can every required slot be filled
    by a distinct fixture holding an eligible outcome in that slot's bucket?"""
    slots = [b for b, k in need.items() for _ in range(k)]
    owner: dict = {}  # fixture -> slot index
    fixtures = sorted(fixture_bands, key=str)

    def augment(s: int, seen: set) -> bool:
        b = slots[s]
        for f in fixtures:
            if b in fixture_bands[f] and f not in seen:
                seen.add(f)
                if f not in owner or augment(owner[f], seen):
                    owner[f] = s
                    return True
        return False

    return all(augment(s, set()) for s in range(len(slots)))


def portfolio_feasible(
    pool: Sequence[ChallengeOutcome],
    snapshot_at: datetime,
    config: ChallengeConfig = DEFAULT_CONFIG,
    fixed: Sequence[ChallengeOutcome] = (),
) -> bool:
    """True iff the eligible pool supports a valid strict portfolio extending ``fixed``.

    ``fixed`` must itself be valid so far (no duplicates, no over-capacity, all
    eligible); otherwise the answer is False. A fixture holding outcomes in
    several bands can fill at most one slot - the matching accounts for that."""
    progress = portfolio_progress(fixed, snapshot_at, config)
    if any(i.code in BLOCKING for i in progress.issues):
        return False
    used = {o.fixture_id for o in fixed}
    pool_assess = [assess_outcome(o, snapshot_at, config) for o in pool]
    bands = {f: b for f, b in _bands_by_fixture(pool_assess).items() if f not in used}
    return _match(dict(progress.remaining), bands)


@dataclass(frozen=True)
class RoundOpeningReport:
    config_version: str
    eligible_outcomes: int
    eligible_outcomes_by_bucket: dict[str, int]
    eligible_fixtures: int
    eligible_leagues: int
    fixtures_missing_league: int
    portfolio_feasible: bool
    checks: dict[str, bool]

    @property
    def opens(self) -> bool:
        return all(self.checks.values())


def round_opening_report(
    pool: Sequence[ChallengeOutcome],
    snapshot_at: datetime,
    config: ChallengeConfig = DEFAULT_CONFIG,
) -> RoundOpeningReport:
    """The approved opening checks (D-28): >= 15 eligible fixtures, >= 3 eligible
    leagues and exact strict-portfolio feasibility, counting only outcomes that
    pass the odds requirements and fall in a bucket band."""
    assess = [assess_outcome(o, snapshot_at, config) for o in pool]
    elig = [a for a in assess if a.eligible]
    fixtures = {a.outcome.fixture_id for a in elig}
    league_of = {}
    for a in elig:
        league_of.setdefault(a.outcome.fixture_id, a.outcome.league_id)
    leagues = {lg for lg in league_of.values() if lg is not None}
    feasible = _match(
        dict(zip(config.bucket_codes, config.sizes, strict=True)), _bands_by_fixture(elig)
    )
    rules = config.opening
    checks = {
        "min_eligible_fixtures": len(fixtures) >= rules.min_eligible_fixtures,
        "min_eligible_leagues": len(leagues) >= rules.min_eligible_leagues,
        "portfolio_feasible": feasible,
    }
    return RoundOpeningReport(
        config.version,
        len(elig),
        {c: sum(a.bucket == c for a in elig) for c in config.bucket_codes},
        len(fixtures),
        len(leagues),
        sum(lg is None for lg in league_of.values()),
        feasible,
        checks,
    )


# ------------------------------------------------- validation / progress
@dataclass(frozen=True)
class PortfolioProgress:
    config_version: str
    selected: dict[str, int]  # bucket -> count of eligible selections
    required: dict[str, int]
    remaining: dict[str, int]  # bucket -> still needed (never negative)
    total_selected: int
    total_required: int
    issues: tuple[ValidationIssue, ...]
    can_complete: bool | None  # None when no pool was supplied

    @property
    def is_complete(self) -> bool:
        """Every bucket filled exactly and no blocking issue."""
        return self.is_valid and all(v == 0 for v in self.remaining.values())

    @property
    def is_valid(self) -> bool:
        return not any(i.code in BLOCKING for i in self.issues)

    def issues_of(self, code: IssueCode) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.code is code)


def portfolio_progress(
    selections: Sequence[ChallengeOutcome],
    snapshot_at: datetime,
    config: ChallengeConfig = DEFAULT_CONFIG,
    pool: Sequence[ChallengeOutcome] | None = None,
) -> PortfolioProgress:
    """Progress of a (possibly partial) selection set, with structured issues.

    Reports bucket counts, remaining requirements, duplicate fixtures/outcomes,
    over-capacity buckets and ineligible selections. When ``pool`` is supplied it
    also reports whether the selections can still be completed, and flags
    selections that are not on the supplied round sheet."""
    _check_snapshot(snapshot_at)
    sels = tuple(selections)
    issues: list[ValidationIssue] = []
    counts = dict.fromkeys(config.bucket_codes, 0)
    seen_keys: set = set()
    by_fixture: dict = {}
    for o in sels:
        if not isinstance(o, ChallengeOutcome):
            raise ChallengeInputError(f"Expected ChallengeOutcome, got {type(o).__name__}")
        if o.key in seen_keys:
            issues.append(
                ValidationIssue(
                    IssueCode.DUPLICATE_OUTCOME,
                    f"{o.key} is selected more than once",
                    o.fixture_id,
                    o.key,
                )
            )
            continue
        seen_keys.add(o.key)
        by_fixture.setdefault(o.fixture_id, []).append(o)
        a = assess_outcome(o, snapshot_at, config)
        issues.extend(a.issues)
        if a.eligible:
            counts[a.bucket] += 1
    for f, outs in by_fixture.items():
        if len(outs) > 1:
            issues.append(
                ValidationIssue(
                    IssueCode.DUPLICATE_FIXTURE,
                    f"Fixture {f} has {len(outs)} selections; only one "
                    "outcome per fixture is allowed",
                    f,
                )
            )
    required = dict(zip(config.bucket_codes, config.sizes, strict=True))
    for b in config.buckets:
        if counts[b.code] > b.selections:
            issues.append(
                ValidationIssue(
                    IssueCode.BUCKET_OVER_CAPACITY,
                    f"{b.name} has {counts[b.code]} selections; exactly {b.selections} allowed",
                    bucket=b.code,
                )
            )
    remaining = {c: max(required[c] - counts[c], 0) for c in required}
    if pool is not None:
        sheet = {o.key: o for o in pool}
        for o in sels:
            if sheet.get(o.key) != o:
                issues.append(
                    ValidationIssue(
                        IssueCode.NOT_IN_POOL,
                        f"{o.key} is not on the supplied round sheet (or differs from it)",
                        o.fixture_id,
                        o.key,
                    )
                )
    if any(remaining.values()):
        issues.append(
            ValidationIssue(
                IssueCode.INCOMPLETE,
                "Incomplete: still needed "
                + ", ".join(f"{config.bucket(c).name} {k}" for c, k in remaining.items() if k),
            )
        )
    can_complete = None
    if pool is not None:
        blocking = any(i.code in BLOCKING for i in issues)
        if blocking:
            can_complete = False
        else:
            used = set(by_fixture)
            pool_assess = [assess_outcome(o, snapshot_at, config) for o in pool]
            bands = {f: b for f, b in _bands_by_fixture(pool_assess).items() if f not in used}
            can_complete = _match(remaining, bands)
        if not can_complete and not blocking:
            issues.append(
                ValidationIssue(
                    IssueCode.CANNOT_COMPLETE,
                    "These selections cannot be completed from the "
                    "remaining fixtures; change a selection",
                )
            )
    total = sum(counts.values())
    return PortfolioProgress(
        config.version,
        counts,
        required,
        remaining,
        total,
        config.required_selections,
        tuple(issues),
        can_complete,
    )


@dataclass(frozen=True)
class StructuredPortfolio:
    """A validated complete portfolio: the only input to :func:`evaluate_portfolio`."""

    config: ChallengeConfig
    snapshot_at: datetime
    buckets: tuple[tuple[ChallengeOutcome, ...], ...]  # in config bucket order

    @property
    def selections(self) -> tuple[ChallengeOutcome, ...]:
        return tuple(o for b in self.buckets for o in b)


def validate_portfolio(
    selections: Sequence[ChallengeOutcome],
    snapshot_at: datetime,
    config: ChallengeConfig = DEFAULT_CONFIG,
    pool: Sequence[ChallengeOutcome] | None = None,
) -> StructuredPortfolio:
    """Validate a complete strict portfolio; raise :class:`PortfolioValidationError`
    with every issue otherwise. Buckets are derived from market probabilities and
    selections keep their input order within each bucket."""
    progress = portfolio_progress(selections, snapshot_at, config, pool)
    if not progress.is_complete:
        raise PortfolioValidationError(progress.issues)
    groups = {c: [] for c in config.bucket_codes}
    for o in selections:
        groups[config.classify(o.market_probability)].append(o)
    return StructuredPortfolio(
        config, snapshot_at, tuple(tuple(groups[c]) for c in config.bucket_codes)
    )


# ------------------------------------------------------------ mathematics
@dataclass(frozen=True)
class AccumulatorResult:
    code: str  # bucket code or "NINE"
    name: str
    legs: tuple[tuple, ...]  # outcome keys
    stake: int
    combined_odds: Decimal
    win_probability: float
    payout: Decimal  # gross if it wins
    recovers_alone: bool


@dataclass(frozen=True)
class JointState:
    wins: tuple[int, ...]  # 1 = bucket won, in bucket order
    probability: float
    gross: Decimal


@dataclass(frozen=True)
class PayoutPoint:
    gross: Decimal
    probability: float  # P(gross == value)
    at_least: float  # P(gross >= value)
    states: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class GroupEvaluation:
    """Configuration-free result of the exact joint-state calculation."""

    buckets: tuple[AccumulatorResult, ...]
    nine_fold: AccumulatorResult
    states: tuple[JointState, ...]
    target: Decimal
    total_stake: int
    precision: Precision

    @property
    def p_recover(self) -> float:
        return probability_at_least(self, self.target)

    @property
    def p_profit(self) -> float:
        return sum(s.probability for s in self.states if s.gross > self.target)

    @property
    def p_zero(self) -> float:
        return sum(s.probability for s in self.states if s.gross == 0)

    @property
    def expected_gross(self) -> float:
        return sum(s.probability * float(s.gross) for s in self.states)

    @property
    def expected_net(self) -> float:
        return self.expected_gross - self.total_stake

    @property
    def sd_gross(self) -> float:
        m = self.expected_gross
        return math.sqrt(
            max(sum(s.probability * (float(s.gross) - m) ** 2 for s in self.states), 0.0)
        )

    @property
    def max_gross(self) -> Decimal:
        return max(s.gross for s in self.states)

    @property
    def p_all_win(self) -> float:
        return self.nine_fold.win_probability


def _payout(stake: int, odds: Decimal, precision: Precision) -> Decimal:
    raw = stake * odds
    return round_credits(raw) if precision is Precision.SETTLEMENT else raw


def evaluate_groups(
    groups: Sequence[Sequence[tuple[float, Decimal]]],
    stakes: Sequence[int],
    nine_stake: int,
    target: Decimal = Decimal("100.00"),
    precision: Precision = Precision.SETTLEMENT,
    names: Sequence[str] | None = None,
    codes: Sequence[str] | None = None,
    leg_keys: Sequence[Sequence[tuple]] | None = None,
    nine_fold_legs: Sequence[tuple[float, Decimal]] | None = None,
) -> GroupEvaluation:
    """Exact joint distribution for disjoint buckets of (probability, odds) legs plus
    a nine-fold over every leg that pays only when every bucket wins.

    Bucket sizes may differ; stakes are fixed integers. With three groups of three
    and stakes 30/30/30/10 this reproduces the Phase 6A engine exactly; pass
    ``nine_fold_legs`` in the original selection order to reproduce its nine-fold
    win probability bit for bit (floating-point products depend on order)."""
    k = len(groups)
    if k < 1 or len(stakes) != k:
        raise ChallengeInputError("One stake is required per bucket")
    codes = tuple(codes) if codes else tuple(chr(65 + i) for i in range(k))
    names = tuple(names) if names else codes
    leg_keys = leg_keys or [tuple(range(len(g))) for g in groups]
    precision = Precision(precision)
    buckets = []
    for j, g in enumerate(groups):
        if not g:
            raise ChallengeInputError("Buckets must not be empty")
        odds = math.prod((o for _, o in g), start=Decimal(1))
        prob = math.prod(p for p, _ in g)
        pay = _payout(stakes[j], odds, precision)
        buckets.append(
            AccumulatorResult(
                codes[j], names[j], tuple(leg_keys[j]), stakes[j], odds, prob, pay, pay >= target
            )
        )
    all_legs = (
        list(nine_fold_legs) if nine_fold_legs is not None else [x for g in groups for x in g]
    )
    if sorted(map(repr, all_legs)) != sorted(repr(x) for g in groups for x in g):
        raise ChallengeInputError("nine_fold_legs must contain exactly the buckets' legs")
    odds9 = math.prod((o for _, o in all_legs), start=Decimal(1))
    prob9 = math.prod(p for p, _ in all_legs)  # as Phase 6A: product of every leg
    pay9 = _payout(nine_stake, odds9, precision)
    nine = AccumulatorResult(
        "NINE",
        "Nine-fold",
        tuple(x for ks in leg_keys for x in ks),
        nine_stake,
        odds9,
        prob9,
        pay9,
        pay9 >= target,
    )
    P = [b.win_probability for b in buckets]
    states = []
    for wins in itertools.product((0, 1), repeat=k):
        prob = math.prod(P[j] if wins[j] else 1.0 - P[j] for j in range(k))
        gross = sum((buckets[j].payout for j in range(k) if wins[j]), Decimal(0))
        if all(wins):
            gross += pay9  # the nine-fold wins only when every bucket wins
        states.append(JointState(wins, prob, gross))
    return GroupEvaluation(
        tuple(buckets), nine, tuple(states), target, sum(stakes) + nine_stake, precision
    )


def probability_at_least(evaluation: GroupEvaluation, threshold) -> float:
    """P(gross >= threshold). Thresholds at or below the smallest attainable gross
    (always 0.00) return exactly 1.0; attainable payouts equal to the threshold are
    included. At 100 credits this is the reported recovery probability."""
    if isinstance(threshold, float | bool):
        raise ChallengeInputError("threshold must be a Decimal, int or string, not float")
    t = Decimal(str(threshold)) if not isinstance(threshold, Decimal) else threshold
    if not t.is_finite() or t < 0:
        raise ChallengeInputError(f"threshold must be a non-negative number, got {threshold!r}")
    if t <= min(s.gross for s in evaluation.states):
        return 1.0
    return min(sum(s.probability for s in evaluation.states if s.gross >= t), 1.0)


def probability_exactly(evaluation: GroupEvaluation, payout) -> float:
    v = Decimal(str(payout)) if not isinstance(payout, Decimal) else payout
    return sum(s.probability for s in evaluation.states if s.gross == v)


def payout_distribution(evaluation: GroupEvaluation) -> tuple[PayoutPoint, ...]:
    """Distinct gross payouts ascending, aggregating equal-payout states exactly
    (``Decimal`` equality), with P(exactly) and P(at least)."""
    groups: dict[Decimal, list[JointState]] = {}
    for s in evaluation.states:
        groups.setdefault(s.gross, []).append(s)
    return tuple(
        PayoutPoint(
            v,
            sum(s.probability for s in groups[v]),
            probability_at_least(evaluation, v),
            tuple(s.wins for s in groups[v]),
        )
        for v in sorted(groups)
    )


@dataclass(frozen=True)
class PortfolioEvaluation:
    config_version: str
    engine_version: str
    source: ProbabilitySource
    snapshot_at: datetime
    result: GroupEvaluation

    # convenience pass-throughs
    @property
    def buckets(self) -> tuple[AccumulatorResult, ...]:
        return self.result.buckets

    @property
    def nine_fold(self) -> AccumulatorResult:
        return self.result.nine_fold

    @property
    def states(self) -> tuple[JointState, ...]:
        return self.result.states

    @property
    def p_recover(self) -> float:
        return self.result.p_recover

    @property
    def p_zero(self) -> float:
        return self.result.p_zero

    @property
    def expected_gross(self) -> float:
        return self.result.expected_gross

    @property
    def expected_net(self) -> float:
        return self.result.expected_net

    @property
    def max_gross(self) -> Decimal:
        return self.result.max_gross

    def at_least(self, threshold) -> float:
        return probability_at_least(self.result, threshold)

    def distribution(self) -> tuple[PayoutPoint, ...]:
        return payout_distribution(self.result)


def evaluate_portfolio(
    portfolio: StructuredPortfolio, source: ProbabilitySource = ProbabilitySource.MARKET
) -> PortfolioEvaluation:
    """Exact evaluation of a validated portfolio under one probability source.

    Payouts come only from the frozen reference odds, so they are identical for
    every source. Unvalidated selections are rejected."""
    if not isinstance(portfolio, StructuredPortfolio):
        raise PortfolioValidationError(
            [
                ValidationIssue(
                    IssueCode.INVALID_INPUT, "Only a validated StructuredPortfolio can be evaluated"
                )
            ]
        )
    cfg = portfolio.config
    source = ProbabilitySource(source)
    if source not in cfg.supported_sources:
        raise ChallengeInputError(f"Probability source {source} is not supported by {cfg.version}")
    groups = [[(o.probability(source), o.reference_odds) for o in b] for b in portfolio.buckets]
    res = evaluate_groups(
        groups,
        cfg.stakes,
        cfg.nine_fold_credits,
        cfg.recovery_target,
        Precision.SETTLEMENT,
        names=[b.name for b in cfg.buckets],
        codes=cfg.bucket_codes,
        leg_keys=[[o.key for o in b] for b in portfolio.buckets],
    )
    nine = res.nine_fold
    res = GroupEvaluation(
        res.buckets,
        AccumulatorResult(
            nine.code,
            cfg.nine_fold_name,
            nine.legs,
            nine.stake,
            nine.combined_odds,
            nine.win_probability,
            nine.payout,
            nine.recovers_alone,
        ),
        res.states,
        res.target,
        res.total_stake,
        res.precision,
    )
    return PortfolioEvaluation(cfg.version, ENGINE_VERSION, source, portfolio.snapshot_at, res)


def evaluate_market_and_model(
    portfolio: StructuredPortfolio,
) -> tuple[PortfolioEvaluation, PortfolioEvaluation]:
    """Separate market-based and model-based estimates (never averaged)."""
    return (
        evaluate_portfolio(portfolio, ProbabilitySource.MARKET),
        evaluate_portfolio(portfolio, ProbabilitySource.MODEL),
    )
