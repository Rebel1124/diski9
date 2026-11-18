"""Explore Your Bucket Risk: illustrative compounding maths (Phase 6B). Pure.

Educational only. Every leg in a bucket gets the same hypothetical probability,
outcomes are independent and odds are *fair* (no bookmaker margin):

* combined probability = p ** legs
* fair decimal odds = 1 / combined probability
* illustrative fair gross payout = bucket credits x fair odds

Nothing here reads or changes a real portfolio, real probabilities, reference
odds, allocations or scoring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from diski9.challenge.config import DEFAULT_CONFIG, ChallengeConfig

DEFAULT_ILLUSTRATION = {"A": 0.70, "B": 0.50, "C": 0.30}


@dataclass(frozen=True)
class BucketIllustration:
    code: str
    name: str
    legs: int
    credits: int
    individual: float
    combined: float
    fair_odds: float
    fair_payout: float


@dataclass(frozen=True)
class Illustration:
    buckets: tuple[BucketIllustration, ...]
    all_nine: float  # every prediction succeeds


def illustrate(
    probabilities: dict[str, float], config: ChallengeConfig = DEFAULT_CONFIG
) -> Illustration:
    rows = []
    for b in config.buckets:
        p = float(probabilities.get(b.code, DEFAULT_ILLUSTRATION.get(b.code, 0.5)))
        if not math.isfinite(p) or not 0 < p <= 1:
            raise ValueError(f"Illustrative probability for {b.name} must be in (0, 1], got {p!r}")
        combined = p**b.selections
        odds = 1 / combined
        rows.append(
            BucketIllustration(
                b.code, b.name, b.selections, b.credits, p, combined, odds, b.credits * odds
            )
        )
    return Illustration(tuple(rows), math.prod(r.combined for r in rows))
