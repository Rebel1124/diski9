"""Versioned, immutable Weekly Challenge configurations (pure, standard library only).

Two configurations are versioned separately:

* :class:`ChallengeConfig` - the portfolio structure: probability bands, bucket
  sizes, credit allocation, probability sources and odds requirements. The
  approved MVP configuration is :data:`BROAD60_432_V1` (``"broad60-432-v1"``).
* :class:`ScoringConfig` (in :mod:`diski9.challenge.scoring`) - championship
  points, versioned as ``"points-150-75-v2"``.

A configuration is a frozen dataclass validated on construction. Participants
never supply one: production code looks a configuration up by version with
:func:`get_config`. A version string identifies exactly one configuration;
registering a different configuration under an existing version is refused.

Probability bands compare **full-precision binary floats** with float bounds.
The bounds are the doubles nearest to the decimal values (0.20, 0.40, 0.60,
0.95), so a stored probability of exactly ``0.6`` belongs to the band whose
lower bound is ``0.6`` inclusive. Never classify a rounded display value.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum

from diski9.api_football.markets import MARKET_OUTCOMES, Market


class ConfigError(ValueError):
    """An invalid challenge or scoring configuration."""


# Invariants of every Weekly Challenge configuration (enforced by _validate_config):
# exactly nine selections on nine distinct fixtures (C-01) and 100 virtual credits.
REQUIRED_SELECTIONS = 9
TOTAL_CREDITS = 100


class ProbabilitySource(StrEnum):
    MARKET = "market"  # margin-adjusted market-implied probability (consensus odds)
    MODEL = "model"  # Goal Model 1.0 probability


@dataclass(frozen=True)
class ProbabilityBand:
    """An interval of probabilities with explicit boundary inclusion."""

    lower: float
    upper: float
    lower_inclusive: bool = True
    upper_inclusive: bool = False

    def __post_init__(self) -> None:
        for name in ("lower", "upper"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
                raise ConfigError(f"Band {name} must be a finite number, got {v!r}")
        if not 0.0 <= self.lower < self.upper <= 1.0:
            raise ConfigError(f"Band needs 0 <= lower < upper <= 1, got {self.lower}-{self.upper}")
        for name in ("lower_inclusive", "upper_inclusive"):
            if not isinstance(getattr(self, name), bool):
                raise ConfigError(f"Band {name} must be True or False")

    def contains(self, p: float) -> bool:
        above = p >= self.lower if self.lower_inclusive else p > self.lower
        below = p <= self.upper if self.upper_inclusive else p < self.upper
        return above and below

    def describe(self) -> str:
        lo = "[" if self.lower_inclusive else "("
        hi = "]" if self.upper_inclusive else ")"
        return f"{lo}{self.lower:g}, {self.upper:g}{hi}"

    def overlaps(self, other: ProbabilityBand) -> bool:
        a, b = sorted((self, other), key=lambda x: (x.lower, x.upper))
        if b.lower < a.upper:
            return True
        return b.lower == a.upper and a.upper_inclusive and b.lower_inclusive


@dataclass(frozen=True)
class BucketSpec:
    code: str  # "A", "B", "C"
    name: str  # "Foundation", ...
    band: ProbabilityBand
    selections: int  # required picks
    credits: int  # fixed stake on the bucket accumulator


@dataclass(frozen=True)
class OddsRequirements:
    """Snapshot-boundary odds rules. Defaults equal the existing strict consensus
    rules (``diski9.odds.consensus.ConsensusRules``): at least three independent
    bookmaker groups, quotes verified within 24 hours. Market completeness and
    pre-kickoff checks stay with the consensus layer that builds the snapshot."""

    min_bookmaker_groups: int = 3
    max_quote_age: timedelta = timedelta(hours=24)

    def __post_init__(self) -> None:
        g = self.min_bookmaker_groups
        if isinstance(g, bool) or not isinstance(g, int) or g < 1:
            raise ConfigError(f"min_bookmaker_groups must be a positive integer, got {g!r}")
        if not isinstance(self.max_quote_age, timedelta) or self.max_quote_age <= timedelta(0):
            raise ConfigError("max_quote_age must be a positive timedelta")


@dataclass(frozen=True)
class RoundOpeningRules:
    """Approved opening thresholds (D-28)."""

    min_eligible_fixtures: int = 15
    min_eligible_leagues: int = 3

    def __post_init__(self) -> None:
        for name in ("min_eligible_fixtures", "min_eligible_leagues"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise ConfigError(f"{name} must be a positive integer, got {v!r}")


@dataclass(frozen=True)
class ChallengeConfig:
    version: str
    buckets: tuple[BucketSpec, ...]
    nine_fold_name: str
    nine_fold_credits: int
    total_credits: int = TOTAL_CREDITS
    required_selections: int = REQUIRED_SELECTIONS
    recovery_target: Decimal = Decimal("100.00")
    classification_source: ProbabilitySource = ProbabilitySource.MARKET
    supported_sources: tuple[ProbabilitySource, ...] = (
        ProbabilitySource.MARKET,
        ProbabilitySource.MODEL,
    )
    supported_markets: tuple[Market, ...] = tuple(Market)
    odds: OddsRequirements = field(default_factory=OddsRequirements)
    opening: RoundOpeningRules = field(default_factory=RoundOpeningRules)

    def __post_init__(self) -> None:
        _validate_config(self)

    # ------------------------------------------------------------- helpers
    @property
    def bucket_codes(self) -> tuple[str, ...]:
        return tuple(b.code for b in self.buckets)

    @property
    def sizes(self) -> tuple[int, ...]:
        return tuple(b.selections for b in self.buckets)

    @property
    def stakes(self) -> tuple[int, ...]:
        return tuple(b.credits for b in self.buckets)

    def bucket(self, code: str) -> BucketSpec:
        for b in self.buckets:
            if b.code == code:
                return b
        raise KeyError(code)

    def classify(self, probability: float) -> str | None:
        """Bucket code for a full-precision probability, or None if ineligible."""
        for b in self.buckets:
            if b.band.contains(probability):
                return b.code
        return None

    def canonical(self) -> dict:
        return {
            "version": self.version,
            "buckets": [
                {
                    "code": b.code,
                    "name": b.name,
                    "band": [
                        repr(b.band.lower),
                        repr(b.band.upper),
                        b.band.lower_inclusive,
                        b.band.upper_inclusive,
                    ],
                    "selections": b.selections,
                    "credits": b.credits,
                }
                for b in self.buckets
            ],
            "nine_fold": [self.nine_fold_name, self.nine_fold_credits],
            "total_credits": self.total_credits,
            "required_selections": self.required_selections,
            "recovery_target": str(self.recovery_target),
            "classification_source": str(self.classification_source),
            "supported_sources": [str(s) for s in self.supported_sources],
            "supported_markets": [str(m) for m in self.supported_markets],
            "odds": [
                self.odds.min_bookmaker_groups,
                self.odds.max_quote_age.total_seconds(),
            ],
            "opening": [self.opening.min_eligible_fixtures, self.opening.min_eligible_leagues],
        }

    def fingerprint(self) -> str:
        blob = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


def _positive_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _validate_config(c: ChallengeConfig) -> None:
    if not isinstance(c.version, str) or not c.version.strip() or c.version != c.version.strip():
        raise ConfigError(f"Configuration version must be a non-empty string, got {c.version!r}")
    if not isinstance(c.buckets, tuple) or not c.buckets:
        raise ConfigError("At least one bucket is required (as a tuple)")
    codes = [b.code for b in c.buckets]
    if len(set(codes)) != len(codes) or not all(isinstance(x, str) and x for x in codes):
        raise ConfigError(f"Bucket codes must be unique non-empty strings, got {codes}")
    if "NINE" in codes:
        raise ConfigError("'NINE' is reserved for the nine-fold")
    for b in c.buckets:
        if not isinstance(b.band, ProbabilityBand):
            raise ConfigError(f"Bucket {b.code}: band must be a ProbabilityBand")
        if not _positive_int(b.selections):
            raise ConfigError(f"Bucket {b.code}: selections must be a positive integer")
        if not _positive_int(b.credits):
            raise ConfigError(f"Bucket {b.code}: credits must be a positive integer")
    for i, a in enumerate(c.buckets):
        for b in c.buckets[i + 1 :]:
            if a.band.overlaps(b.band):
                raise ConfigError(
                    f"Bands overlap: {a.code} {a.band.describe()} and {b.code} {b.band.describe()}"
                )
    if not _positive_int(c.required_selections):
        raise ConfigError("required_selections must be a positive integer")
    if c.required_selections != REQUIRED_SELECTIONS:
        raise ConfigError(
            f"The Weekly Challenge needs exactly 9 selections, got {c.required_selections}"
        )
    if sum(c.sizes) != c.required_selections:
        raise ConfigError(
            f"Bucket sizes {c.sizes} sum to {sum(c.sizes)}, not {c.required_selections}"
        )
    if not _positive_int(c.nine_fold_credits):
        raise ConfigError("nine_fold_credits must be a positive integer")
    if not _positive_int(c.total_credits) or c.total_credits != TOTAL_CREDITS:
        raise ConfigError(f"total_credits must be 100, got {c.total_credits!r}")
    allocated = sum(c.stakes) + c.nine_fold_credits
    if allocated != c.total_credits:
        raise ConfigError(f"Allocated credits {allocated} do not equal {c.total_credits}")
    if not isinstance(c.recovery_target, Decimal) or c.recovery_target != Decimal(c.total_credits):
        raise ConfigError("recovery_target must be Decimal('100.00') (the total allocation)")
    sources = tuple(c.supported_sources)
    if not sources or any(not isinstance(s, ProbabilitySource) for s in sources):
        raise ConfigError("supported_sources must be ProbabilitySource values")
    if c.classification_source not in sources:
        raise ConfigError("classification_source must be one of the supported sources")
    if c.classification_source is not ProbabilitySource.MARKET:
        raise ConfigError("Bucket classification must use market probabilities")
    if not c.supported_markets or any(m not in MARKET_OUTCOMES for m in c.supported_markets):
        raise ConfigError("supported_markets must be known markets")
    if not isinstance(c.odds, OddsRequirements) or not isinstance(c.opening, RoundOpeningRules):
        raise ConfigError("odds and opening must be OddsRequirements and RoundOpeningRules")


# ------------------------------------------------------------- approved MVP
BROAD60_432_V1 = ChallengeConfig(
    version="broad60-432-v1",
    buckets=(
        BucketSpec("A", "Foundation", ProbabilityBand(0.60, 0.95, True, True), 4, 40),
        BucketSpec("B", "Balanced", ProbabilityBand(0.40, 0.60, True, False), 3, 30),
        BucketSpec("C", "Challenger", ProbabilityBand(0.20, 0.40, True, False), 2, 20),
    ),
    nine_fold_name="The Diski 9",
    nine_fold_credits=10,
)

# Scenario A3 (owner-approved; research: docs/research/weekly_challenge_bucket_review.md).
# Identical to broad60-432-v1 except two bands: Foundation 60%-90% (both ends included)
# and Challenger 10% to under 40%. The launch configuration: the default, and the
# weekend schedule's configuration from migration app_0009 (A3 Checkpoint 4C).
A3_432_V1 = ChallengeConfig(
    version="a3-432-v1",
    buckets=(
        BucketSpec("A", "Foundation", ProbabilityBand(0.60, 0.90, True, True), 4, 40),
        BucketSpec("B", "Balanced", ProbabilityBand(0.40, 0.60, True, False), 3, 30),
        BucketSpec("C", "Challenger", ProbabilityBand(0.10, 0.40, True, False), 2, 20),
    ),
    nine_fold_name="The Diski 9",
    nine_fold_credits=10,
)

_REGISTRY: dict[str, ChallengeConfig] = {}


def register_config(config: ChallengeConfig) -> ChallengeConfig:
    """Register a configuration; a version may never change meaning."""
    existing = _REGISTRY.get(config.version)
    if existing is not None and existing.fingerprint() != config.fingerprint():
        raise ConfigError(
            f"Version {config.version!r} is already registered with a different configuration"
        )
    _REGISTRY[config.version] = config
    return config


def get_config(version: str) -> ChallengeConfig:
    try:
        return _REGISTRY[version]
    except KeyError:
        raise ConfigError(f"Unknown challenge configuration version {version!r}") from None


register_config(BROAD60_432_V1)
register_config(A3_432_V1)  # permanent once registered; never redefined
# Scenario A3 is the launch configuration (Checkpoint 4C, Option D). This default is
# used ONLY where no competition database is configured (prototype mode) and for
# free-standing illustrations. Database-backed rounds use their schedule row (weekend
# v3 = a3-432-v1 from migration app_0009) or their own pinned configuration.
DEFAULT_CONFIG = A3_432_V1
