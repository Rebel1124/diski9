"""Research only (Phase 6A.1): risk-structured Weekly Challenge experiments.

Players pick nine outcomes on nine distinct fixtures *into* three probability
bands (buckets A > B > C). Bucket sizes (3/3/3, 4/3/2, 5/3/1), band edges and the
fixed 100-credit allocation are the experimental factors. Payouts follow the
Phase 6A conventions exactly: exact ``Decimal`` combined odds, accumulator payouts
rounded half-up to 0.01 credit (D-15), the nine-fold paid only when all three
buckets win, and an exact eight-state distribution (no simulation for portfolio
metrics). Monte Carlo is used only for realised leaderboard outcomes.

Nothing here is production code.
"""

from __future__ import annotations

import bisect
import itertools
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

STATES = tuple(itertools.product((0, 1), repeat=3))
TARGET = Decimal("100.00")
Q = Decimal("0.01")


# ---------------------------------------------------------------- configuration
@dataclass(frozen=True)
class Band:
    """Half-open probability interval [lo, hi); ``hi_inclusive`` closes the top."""

    lo: float
    hi: float
    hi_inclusive: bool = False

    def contains(self, p: float) -> bool:
        return self.lo <= p <= self.hi if self.hi_inclusive else self.lo <= p < self.hi

    def label(self) -> str:
        return f"[{self.lo:.0%}, {self.hi:.0%}{']' if self.hi_inclusive else ')'}"


BAND_SETS: dict[str, tuple[Band, Band, Band]] = {
    # candidates from the brief (A tops inclusive; B and C half-open, non-overlapping)
    "Conservative": (Band(0.80, 0.95, True), Band(0.65, 0.80), Band(0.55, 0.65)),
    "Moderate": (Band(0.75, 0.90, True), Band(0.60, 0.75), Band(0.50, 0.60)),
    "Broad": (Band(0.65, 0.95, True), Band(0.40, 0.65), Band(0.20, 0.40)),
    # data-driven variants (Goal Model 1.0 rarely exceeds 75% for any outcome)
    "Broad-60": (Band(0.60, 0.95, True), Band(0.40, 0.60), Band(0.20, 0.40)),
    "Broad-55": (Band(0.55, 0.95, True), Band(0.35, 0.55), Band(0.15, 0.35)),
}
SIZES: dict[str, tuple[int, int, int]] = {
    "3/3/3": (3, 3, 3),
    "4/3/2": (4, 3, 2),
    "5/3/1": (5, 3, 1),
}
ALLOCATIONS: dict[str, tuple[int, int, int, int]] = {
    "30/30/30/10": (30, 30, 30, 10),
    "40/30/20/10": (40, 30, 20, 10),
    "50/25/15/10": (50, 25, 15, 10),
}


@dataclass(frozen=True)
class Config:
    bands: str
    sizes: str
    allocation: str

    @property
    def band_tuple(self):
        return BAND_SETS[self.bands]

    @property
    def size_tuple(self):
        return SIZES[self.sizes]

    @property
    def stakes(self):
        return ALLOCATIONS[self.allocation]

    def name(self) -> str:
        return f"{self.bands} · {self.sizes} · {self.allocation}"


# ------------------------------------------------------------------ outcomes
@dataclass(frozen=True)
class Outcome:
    fixture_id: int | str
    market: str
    key: str
    p_model: float
    p_market: float
    odds: Decimal


def pool_outcomes(pool: dict) -> list[Outcome]:
    out = []
    for f in pool["fixtures"]:
        for o in f["outcomes"]:
            if o["eligible"]:
                out.append(
                    Outcome(
                        f["fixture_id"],
                        o["market"],
                        o["key"],
                        o["p_model"],
                        o["p_market"],
                        Decimal(o["odds"]),
                    )  # fmt: skip
                )
    return out


def classify(p: float, bands: Sequence[Band]) -> int | None:
    for i, b in enumerate(bands):
        if b.contains(p):
            return i
    return None


# --------------------------------------------------------------- feasibility
def count_portfolios(outcomes: Sequence[Outcome], cfg: Config, source: str = "p_model") -> int:
    """Exact number of valid portfolios: choose nA, nB, nC outcomes in bands A, B, C
    on distinct fixtures (one outcome per fixture). Generating-function DP over
    fixtures: each fixture contributes 1 + kA·x + kB·y + kC·z."""
    na, nb, nc = cfg.size_tuple
    per_fixture: dict = {}
    for o in outcomes:
        i = classify(getattr(o, source), cfg.band_tuple)
        if i is not None:
            per_fixture.setdefault(o.fixture_id, [0, 0, 0])[i] += 1
    dp = {(0, 0, 0): 1}
    for ka, kb, kc in per_fixture.values():
        nxt = dict(dp)
        for (a, b, c), v in dp.items():
            if a < na and ka:
                nxt[(a + 1, b, c)] = nxt.get((a + 1, b, c), 0) + v * ka
            if b < nb and kb:
                nxt[(a, b + 1, c)] = nxt.get((a, b + 1, c), 0) + v * kb
            if c < nc and kc:
                nxt[(a, b, c + 1)] = nxt.get((a, b, c + 1), 0) + v * kc
        dp = nxt
    return dp.get((na, nb, nc), 0)


def band_availability(outcomes, cfg: Config, source="p_model") -> dict:
    res = {}
    for i, lbl in enumerate("ABC"):
        hits = [o for o in outcomes if classify(getattr(o, source), cfg.band_tuple) == i]
        res[lbl] = {"outcomes": len(hits), "fixtures": len({o.fixture_id for o in hits})}
    return res


# ----------------------------------------------------------- portfolio maths
def _round(x: Decimal) -> Decimal:
    return x.quantize(Q, rounding=ROUND_HALF_UP)


@dataclass
class PortfolioMetrics:
    p_bucket: tuple[float, float, float]
    payout_bucket: tuple[Decimal, Decimal, Decimal]
    payout_nine: Decimal
    p_nine: float
    p_recover: float
    p_profit: float
    p_zero: float
    expected: float
    median: Decimal
    q75: Decimal
    q90: Decimal
    max_payout: Decimal
    p_wins: tuple[float, float, float, float]  # P(0/1/2/3 buckets win)
    only_all_nine_recovers: bool
    a_alone_recovers: bool
    dist: list = field(default_factory=list)  # [(gross, prob)]


def evaluate(buckets: Sequence[Sequence[tuple[float, Decimal]]], stakes) -> PortfolioMetrics:
    """Exact eight-state metrics for buckets of (probability, odds) legs."""
    sa = stakes[:3]
    s9 = stakes[3]
    P = [math.prod(p for p, _ in b) for b in buckets]
    O = [math.prod((o for _, o in b), start=Decimal(1)) for b in buckets]  # noqa: E741
    pay = [_round(s * o) for s, o in zip(sa, O, strict=True)]
    o9 = math.prod(O, start=Decimal(1))
    pay9 = _round(s9 * o9)
    states = []
    for w in STATES:
        pr = math.prod(P[j] if w[j] else 1 - P[j] for j in range(3))
        g = sum((pay[j] for j in range(3) if w[j]), Decimal(0)) + (pay9 if all(w) else 0)
        states.append((w, pr, g))
    dist: dict[Decimal, float] = {}
    for _, pr, g in states:
        dist[g] = dist.get(g, 0.0) + pr
    values = sorted(dist)
    cum = list(itertools.accumulate(dist[v] for v in values))

    def quantile(q):
        i = bisect.bisect_left(cum, q - 1e-12)
        return values[min(i, len(values) - 1)]

    p_wins = [0.0] * 4
    for w, pr, _ in states:
        p_wins[sum(w)] += pr
    recovering = [w for w, _, g in states if g >= TARGET]
    return PortfolioMetrics(
        p_bucket=tuple(P),
        payout_bucket=tuple(pay),
        payout_nine=pay9,
        p_nine=math.prod(P),
        p_recover=sum(pr for _, pr, g in states if g >= TARGET),
        p_profit=sum(pr for _, pr, g in states if g > TARGET),
        p_zero=sum(pr for _, pr, g in states if g == 0),
        expected=sum(pr * float(g) for _, pr, g in states),
        median=quantile(0.5),
        q75=quantile(0.75),
        q90=quantile(0.90),
        max_payout=states[-1][2],
        p_wins=tuple(p_wins),
        only_all_nine_recovers=recovering == [(1, 1, 1)],
        a_alone_recovers=pay[0] >= TARGET,
        dist=[(v, dist[v]) for v in values],
    )


# ------------------------------------------------------------- strategies
STRATEGIES = ("random", "favourite", "longshot", "midband", "model_value")


def _score(o: Outcome, strategy: str, band: Band | None, source: str, rng: random.Random,
           noise: float = 0.0) -> float:  # fmt: skip
    """Ranking key (smaller = preferred). ``noise`` adds a participant-specific
    Gaussian jitter (probability units) so players sharing a strategy differ."""
    return _base_score(o, strategy, band, source, rng) + (rng.gauss(0, noise) if noise else 0.0)


def _base_score(o: Outcome, strategy: str, band: Band | None, source: str, rng) -> float:
    p = getattr(o, source)
    if strategy == "random":
        return rng.random()
    if strategy == "favourite":
        return -p
    if strategy == "longshot":
        return p
    if strategy == "midband":
        centre = 0.45 if band is None else (band.lo + band.hi) / 2
        return abs(p - centre)
    if strategy == "model_value":  # highest modelled EV per unit: p_model x odds
        return -(o.p_model * float(o.odds))
    raise ValueError(strategy)


def build_structured(outcomes, cfg: Config, strategy: str, rng: random.Random,
                     source: str = "p_model", noise: float = 0.0, tries: int = 50):  # fmt: skip
    """A valid risk-structured portfolio for a strategy, or None if infeasible.
    Buckets are filled scarcest-first by strategy ranking; on a deadlock over
    shared fixtures the ranking is re-drawn (random/noise) or rotated."""
    bands = cfg.band_tuple
    need = list(cfg.size_tuple)
    by_band = [[o for o in outcomes if classify(getattr(o, source), bands) == i] for i in range(3)]
    if any(len({o.fixture_id for o in by_band[i]}) < need[i] for i in range(3)):
        return None
    order = sorted(range(3), key=lambda i: len({o.fixture_id for o in by_band[i]}) - need[i])
    for attempt in range(tries):
        used, picks = set(), [[], [], []]
        for i in order:
            cands = sorted(
                by_band[i],
                key=lambda o, i=i: (
                    _score(o, strategy, bands[i], source, rng, noise),
                    str(o.fixture_id),
                    o.key,
                ),  # fmt: skip
            )
            if attempt and strategy != "random" and not noise:
                k = attempt % len(cands)
                cands = cands[k:] + cands[:k]
            for o in cands:
                if len(picks[i]) == need[i]:
                    break
                if o.fixture_id not in used:
                    picks[i].append(o)
                    used.add(o.fixture_id)
            if len(picks[i]) < need[i]:
                break
        else:
            return picks
    return None


def build_free(outcomes, strategy: str, rng: random.Random, source: str = "p_model",
               noise: float = 0.0, floor: float = 0.0):  # fmt: skip
    """Original design: any nine outcomes on nine distinct fixtures (one per fixture)."""
    cands = sorted(
        (o for o in outcomes if getattr(o, source) >= floor),
        key=lambda o: (_score(o, strategy, None, source, rng, noise), str(o.fixture_id), o.key),
    )
    used, picks = set(), []
    for o in cands:
        if o.fixture_id not in used:
            picks.append(o)
            used.add(o.fixture_id)
            if len(picks) == 9:
                return picks
    return None


def legs(picks, source="p_model"):
    return [[(getattr(o, source), o.odds) for o in b] for b in picks]


# --------------------------------------------------- flexible-rule candidates
@dataclass(frozen=True)
class FlexRule:
    name: str
    description: str
    min_high: int  # at least this many selections with p >= high
    high: float
    max_low: int  # at most this many with p < low
    low: float
    floor: float  # no selection below this probability

    def ok(self, ps: Sequence[float]) -> bool:
        return (
            sum(p >= self.high for p in ps) >= self.min_high
            and sum(p < self.low for p in ps) <= self.max_low
            and min(ps) >= self.floor
        )


FLEX_RULES = (
    FlexRule(
        "F1 anchor", "≥4 picks at ≥55%, ≤2 picks below 30%, none below 15%", 4, 0.55, 2, 0.30, 0.15
    ),  # fmt: skip
    FlexRule("F2 floor", "≥3 picks at ≥50%, none below 20%", 3, 0.50, 9, 0.0, 0.20),
)
