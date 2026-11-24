"""Scenario A3 user guidance: the high-risk underdog rule (pure, no UI).

The warning applies to a **selected** outcome whose own margin-adjusted market-implied
probability is at least 10% and below 20%, and only when that outcome is eligible under
the round's configuration (``a3-432-v1``; under ``broad60-432-v1`` such outcomes are
ineligible, so the warning never appears there). It never looks at the Goal Model
probability and never at other outcomes of the same fixture.

It is presentation guidance only: it changes no eligibility, probability, scoring or
settlement, and it never blocks a selection. The threshold lives here, outside the
challenge configuration (and its fingerprint), so wording or threshold reviews never
need a new rules version.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from diski9.challenge.config import ChallengeConfig, ProbabilityBand
from diski9.challenge.structured import ChallengeOutcome, assess_outcome

# 10% inclusive to below 20% (owner-approved; research:
# docs/research/weekly_challenge_bucket_review.md section 8).
HIGH_RISK_UNDERDOG = ProbabilityBand(0.10, 0.20, True, False)


def is_high_risk_underdog(
    outcome: ChallengeOutcome, snapshot_at: datetime, config: ChallengeConfig
) -> bool:
    """True when this outcome's market probability is in [10%, 20%) and the outcome is
    eligible under ``config`` (the round's own configuration)."""
    if not HIGH_RISK_UNDERDOG.contains(outcome.market_probability):
        return False
    return assess_outcome(outcome, snapshot_at, config).eligible


def high_risk_selections(
    selections: Iterable[ChallengeOutcome], snapshot_at: datetime, config: ChallengeConfig
) -> list[ChallengeOutcome]:
    """The selected outcomes that carry the warning, in selection order, each once."""
    seen, out = set(), []
    for o in selections:
        if o.key not in seen and is_high_risk_underdog(o, snapshot_at, config):
            seen.add(o.key)
            out.append(o)
    return out
