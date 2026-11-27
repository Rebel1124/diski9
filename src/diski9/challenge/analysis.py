"""Portfolio analytics for the Weekly Challenge builder (Phase 6B.1). Pure.

* :func:`bucket_stats` - per-bucket progress for a possibly incomplete portfolio:
  combined probability and combined odds of the selections made **so far**, and
  the gross payout if those selections all succeed. Values for an incomplete
  bucket describe only the picks made so far, never a completed entry.
* :func:`evaluate_with` - the exact eight-state evaluation of a validated
  portfolio with an arbitrary probability per selection (market, Diski 9 model or
  the participant's own view). Payouts always come from the frozen reference odds
  through :func:`diski9.challenge.structured.evaluate_groups`, so they are
  identical for every probability source.
* :func:`correct_count_analysis` - all 2^9 = 512 success/failure combinations of
  the nine predictions. The number of correct predictions follows a
  Poisson-binomial distribution (independent predictions with their own
  probabilities); for each count k it reports the number of combinations C(9, k),
  P(exactly k correct), the conditional expected gross payout, the minimum and
  maximum payout and the conditional recovery probability. A bucket pays only if
  *all* of its predictions are correct, so more correct predictions do not
  necessarily mean a higher payout.

Independence between matches is an assumption; every distribution is conditional
on the supplied probability estimates.

Missing independent predictions (Phase 8 OD-3). Since Goal Model 1.1 a selection may
have no Diski 9 probability (``model_probability`` None). Diski 9 figures are then
produced only where every selection involved has one: per selection, per bucket when
the whole bucket has predictions, and for the portfolio only with all nine. Elsewhere
the value is ``None`` and the number of missing predictions is reported; a market
probability is **never** substituted into a Diski 9 figure. Your View uses, per
selection: the participant's valid adjustment, else the Diski 9 probability, else (an
interim fallback until CP2B) the actual market consensus probability.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from diski9.challenge.config import DEFAULT_CONFIG, ChallengeConfig
from diski9.challenge.portfolio import Precision, round_credits
from diski9.challenge.structured import (
    ChallengeOutcome,
    GroupEvaluation,
    StructuredPortfolio,
    evaluate_groups,
)

SOURCES = ("market", "model", "personal")
SOURCE_LABEL = {"market": "Market", "model": "Diski 9", "personal": "Your View"}

Probability = Callable[[ChallengeOutcome], float]


def market_probability(o: ChallengeOutcome) -> float:
    return o.market_probability


class ModelUnavailable(ValueError):
    """A Diski 9 figure was requested for a selection without an independent
    prediction. Callers show the figure as unavailable; nothing is substituted."""


def has_model(o: ChallengeOutcome) -> bool:
    return o.model_probability is not None


def model_probability(o: ChallengeOutcome) -> float:
    if o.model_probability is None:
        raise ModelUnavailable(f"{o.key}: no Diski 9 probability")
    return o.model_probability


def missing_models(selections) -> int:
    """How many of these selections have no Diski 9 probability."""
    return sum(1 for o in selections if not has_model(o))


# Your View source of each selection (OD-3 hierarchy; CP2B adds the market-implied step)
PERSONAL_SOURCES = ("adjusted", "model", "market")
PERSONAL_SOURCE_LABEL = {
    "adjusted": "your adjustment",
    "model": "Diski 9",
    "market": "market consensus",
}


def personal_source(o: ChallengeOutcome, personal: Mapping[tuple, float] | None) -> str:
    """Which tier of the Your View hierarchy supplies this selection's probability."""
    if personal and personal.get(o.key) is not None:
        return "adjusted"
    return "model" if has_model(o) else "market"


def personal_sources(selections, personal: Mapping[tuple, float] | None) -> dict[str, int]:
    """Count of selections per Your View tier (for the compact source summary)."""
    out = dict.fromkeys(PERSONAL_SOURCES, 0)
    for o in selections:
        out[personal_source(o, personal)] += 1
    return out


def personal_summary(selections, personal: Mapping[tuple, float] | None) -> str:
    """'Your View: 2 your adjustment · 6 Diski 9 · 1 market consensus' (non-zero tiers)."""
    counts = personal_sources(selections, personal)
    parts = [f"{n} {PERSONAL_SOURCE_LABEL[k]}" for k, n in counts.items() if n]
    return "Your View: " + " · ".join(parts) if parts else ""


def personal_probability(personal: Mapping[tuple, float] | None) -> Probability:
    """The participant's view per selection: their own valid adjustment, otherwise the
    Diski 9 probability, otherwise the actual market consensus probability (interim
    fallback; the market-implied step arrives in CP2B)."""
    personal = personal or {}

    def prob(o: ChallengeOutcome) -> float:
        p = personal.get(o.key)
        if p is not None:
            return float(p)
        return o.model_probability if has_model(o) else o.market_probability

    return prob


def probability_for(source: str, personal: Mapping[tuple, float] | None = None) -> Probability:
    if source == "market":
        return market_probability
    if source == "model":
        return model_probability
    if source == "personal":
        return personal_probability(personal)
    raise ValueError(f"Unknown probability source {source!r}")


# ------------------------------------------------------------- bucket progress
@dataclass(frozen=True)
class BucketStat:
    code: str
    name: str
    selected: int
    required: int
    credits: int
    combined_probability: float | None  # product over the selections so far
    combined_odds: Decimal | None
    payout: Decimal | None  # gross if every selection so far succeeds (D-15 rounding)
    # selections so far without a probability from the chosen source (Diski 9 only);
    # when > 0, combined_probability is None (OD-3: never part-substituted)
    unavailable: int = 0

    @property
    def complete(self) -> bool:
        return self.selected == self.required


def bucket_stats(
    selections: Sequence[ChallengeOutcome],
    probability: Probability = market_probability,
    config: ChallengeConfig = DEFAULT_CONFIG,
) -> tuple[tuple[BucketStat, ...], BucketStat]:
    """(per-bucket stats, The Diski 9 stats) for the current selections.

    Selections are grouped by their market-probability bucket; outcomes outside
    every band are ignored here (validation reports them separately). Empty
    buckets have ``None`` values. A bucket (or The Diski 9) with a selection the
    source cannot price has ``combined_probability`` None and ``unavailable`` > 0;
    odds and payout still come from the frozen reference odds."""
    groups: dict[str, list[ChallengeOutcome]] = {c: [] for c in config.bucket_codes}
    for o in selections:
        code = config.classify(o.market_probability)
        if code is not None:
            groups[code].append(o)
    out = []
    for b in config.buckets:
        legs = groups[b.code]
        miss = 0
        if legs:
            odds = math.prod((o.reference_odds for o in legs), start=Decimal(1))
            prob, miss = _combined(legs, probability)
            pay = round_credits(b.credits * odds)
        else:
            odds = prob = pay = None
        out.append(
            BucketStat(b.code, b.name, len(legs), b.selections, b.credits, prob, odds, pay, miss)
        )
    legs = [o for c in config.bucket_codes for o in groups[c]]
    miss9 = 0
    if legs:
        odds9 = math.prod((o.reference_odds for o in legs), start=Decimal(1))
        p9, miss9 = _combined(legs, probability)
        pay9 = round_credits(config.nine_fold_credits * odds9)
    else:
        odds9 = p9 = pay9 = None
    nine = BucketStat("NINE", config.nine_fold_name, len(legs), config.required_selections,
                      config.nine_fold_credits, p9, odds9, pay9, miss9)  # fmt: skip
    return tuple(out), nine


def _combined(legs, probability: Probability) -> tuple[float | None, int]:
    """(product of the legs' probabilities, legs the source cannot price). The product
    is None as soon as one leg is unavailable: never a partial or substituted value."""
    probs, miss = [], 0
    for o in legs:
        try:
            probs.append(probability(o))
        except ModelUnavailable:
            miss += 1
    return (None, miss) if miss else (math.prod(probs), 0)


def available(portfolio: StructuredPortfolio, source: str) -> bool:
    """Whether a whole-portfolio estimate exists for ``source`` (Diski 9 needs all
    nine independent predictions; Market and Your View always exist)."""
    return source != "model" or missing_models(portfolio.selections) == 0


# ------------------------------------------------------------- evaluation
def evaluate_with(portfolio: StructuredPortfolio, probability: Probability) -> GroupEvaluation:
    """Exact eight-state evaluation with a chosen probability per selection."""
    cfg = portfolio.config
    groups = [[(probability(o), o.reference_odds) for o in b] for b in portfolio.buckets]
    return evaluate_groups(
        groups,
        cfg.stakes,
        cfg.nine_fold_credits,
        cfg.recovery_target,
        Precision.SETTLEMENT,
        names=[b.name for b in cfg.buckets],
        codes=cfg.bucket_codes,
        leg_keys=[[o.key for o in b] for b in portfolio.buckets],
    )


def evaluate_sources(
    portfolio: StructuredPortfolio, personal: Mapping[tuple, float] | None = None
) -> dict[str, GroupEvaluation | None]:
    """Market, Diski 9 and Your View evaluations of one portfolio (same payouts).
    Diski 9 is None unless all nine selections have an independent prediction."""
    return {
        s: evaluate_with(portfolio, probability_for(s, personal))
        if available(portfolio, s)
        else None
        for s in SOURCES
    }


# ------------------------------------------------------- 512-state analysis
@dataclass(frozen=True)
class PredictionState:
    correct: tuple[bool, ...]  # per selection, in portfolio order (bucket A, B, C)
    probability: float
    n_correct: int
    buckets_won: tuple[bool, ...]
    gross: Decimal


@dataclass(frozen=True)
class CorrectCountRow:
    k: int
    combinations: int
    probability: float  # P(exactly k correct)
    expected_gross: float | None  # E[gross | exactly k correct]; None when P = 0
    min_gross: Decimal
    max_gross: Decimal
    p_recover: float | None  # P(gross >= 100 | exactly k correct); None when P = 0
    contribution: float  # unconditional contribution to E[gross]


@dataclass(frozen=True)
class CorrectCountAnalysis:
    states: tuple[PredictionState, ...]
    rows: tuple[CorrectCountRow, ...]
    expected_correct: float
    most_likely: int  # smallest k among the most probable counts
    target: Decimal

    @property
    def expected_gross(self) -> float:
        return sum(s.probability * float(s.gross) for s in self.states)

    @property
    def p_recover(self) -> float:
        return sum(s.probability for s in self.states if s.gross >= self.target)

    @property
    def p_zero(self) -> float:
        return sum(s.probability for s in self.states if s.gross == 0)

    def payout_distribution(self) -> dict[Decimal, float]:
        out: dict[Decimal, float] = {}
        for s in self.states:
            out[s.gross] = out.get(s.gross, 0.0) + s.probability
        return out


def correct_count_analysis(
    portfolio: StructuredPortfolio, probability: Probability = market_probability
) -> CorrectCountAnalysis:
    """Exact enumeration of all 2^n success/failure combinations (n = 9)."""
    ev = evaluate_with(portfolio, probability)  # payouts with the approved rounding
    pays = [b.payout for b in ev.buckets]
    pay9 = ev.nine_fold.payout
    legs = [(j, probability(o)) for j, b in enumerate(portfolio.buckets) for o in b]
    sizes = [len(b) for b in portfolio.buckets]
    n = len(legs)
    target = portfolio.config.recovery_target
    states = []
    for bits in itertools.product((False, True), repeat=n):
        prob = math.prod(p if hit else 1.0 - p for (_, p), hit in zip(legs, bits, strict=True))
        won, i = [], 0
        for size in sizes:
            won.append(all(bits[i : i + size]))
            i += size
        gross = sum((pays[j] for j, w in enumerate(won) if w), Decimal(0))
        if all(won):
            gross += pay9  # the nine-fold pays only when every bucket wins
        states.append(PredictionState(bits, prob, sum(bits), tuple(won), gross))
    rows = []
    for k in range(n + 1):
        group = [s for s in states if s.n_correct == k]
        pk = sum(s.probability for s in group)
        contrib = sum(s.probability * float(s.gross) for s in group)
        rec = sum(s.probability for s in group if s.gross >= target)
        rows.append(CorrectCountRow(
            k, len(group), pk, contrib / pk if pk > 0 else None,
            min(s.gross for s in group), max(s.gross for s in group),
            rec / pk if pk > 0 else None, contrib,
        ))  # fmt: skip
    expected = sum(p for _, p in legs)
    best = max(r.probability for r in rows)
    mode = min(r.k for r in rows if r.probability == best)
    return CorrectCountAnalysis(tuple(states), tuple(rows), expected, mode, target)


# ------------------------------------------------- calculation breakdown
@dataclass(frozen=True)
class LegLine:
    key: tuple
    probability: float  # the active source's probability for this prediction
    odds: Decimal  # frozen reference odds


@dataclass(frozen=True)
class BucketLine:
    code: str
    name: str
    stake: int
    legs: tuple[LegLine, ...]
    probability: float  # product of the leg probabilities (engine value)
    combined_odds: Decimal  # exact product of the frozen odds
    payout: Decimal  # stake x combined odds, approved rounding


@dataclass(frozen=True)
class StateLine:
    wins: tuple[int, ...]
    label: str
    probability: float
    gross: Decimal
    weighted: float  # probability x gross
    recovers: bool  # gross >= 100.00


@dataclass(frozen=True)
class CalculationBreakdown:
    """Every number behind the recovery and expected-payout summary, taken from the
    exact eight-state engine (``evaluate_with``) for one probability source. The
    totals are the engine's own values, so they reconcile with the summary metrics."""

    buckets: tuple[BucketLine, ...]
    nine_fold: BucketLine
    states: tuple[StateLine, ...]  # the eight mutually exclusive outcomes
    target: Decimal
    total_stake: int
    p_recover: float  # sum of probabilities of states with gross >= target
    p_partial: float
    p_zero: float
    expected_gross: float  # sum(probability x gross)
    expected_net: float

    @property
    def has_partial(self) -> bool:
        """True when some outcome pays something but less than the target, i.e. when
        P(recover) is not simply 1 - P(nothing back)."""
        return any(0 < s.gross < self.target for s in self.states)


def calculation_breakdown(
    portfolio: StructuredPortfolio, probability: Probability = market_probability
) -> CalculationBreakdown:
    ev = evaluate_with(portfolio, probability)
    lines = []
    for b, res in zip(portfolio.buckets, ev.buckets, strict=True):
        legs = tuple(LegLine(o.key, probability(o), o.reference_odds) for o in b)
        lines.append(BucketLine(res.code, res.name, res.stake, legs, res.win_probability,
                                res.combined_odds, res.payout))  # fmt: skip
    nf = ev.nine_fold
    all_legs = tuple(leg for line in lines for leg in line.legs)
    nine = BucketLine(nf.code, nf.name, nf.stake, all_legs, nf.win_probability,
                      nf.combined_odds, nf.payout)  # fmt: skip
    order = sorted(ev.states, key=lambda st: (sum(st.wins), st.gross))
    states = tuple(
        StateLine(
            st.wins,
            state_label(st.wins, portfolio.config),
            st.probability,
            st.gross,
            st.probability * float(st.gross),
            st.gross >= ev.target,
        )  # fmt: skip
        for st in order
    )
    return CalculationBreakdown(
        tuple(lines), nine, states, ev.target, ev.total_stake, ev.p_recover, ev.p_partial,
        ev.p_zero, ev.expected_gross, ev.expected_net,
    )  # fmt: skip


def state_label(wins: Sequence[int | bool], config: ChallengeConfig = DEFAULT_CONFIG) -> str:
    """Plain words for an eight-state outcome, e.g. 'Foundation + Challenger'."""
    return state_label_for(wins, [b.name for b in config.buckets])


def state_label_for(wins: Sequence[int | bool], bucket_names: Sequence[str]) -> str:
    """:func:`state_label` from the bucket names an evaluation carries (taken from
    the portfolio's own configuration), so no configuration lookup is needed."""
    names = [n for n, w in zip(bucket_names, wins, strict=True) if w]
    if not names:
        return "No buckets complete"
    if len(names) == len(bucket_names):
        return "All nine correct"
    return " + ".join(names) + (" only" if len(names) == 1 else "")
