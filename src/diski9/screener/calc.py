"""Pure Screener calculations (Statistical Screener Specification v1.2).

All arithmetic uses exact fractions; floats appear only at the presentation edge.
None of these values are probabilities or predictions.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

GD_CAP = Fraction(2)
GD_WEIGHT = Fraction(1, 2)


def clip(x: Fraction, lo: Fraction, hi: Fraction) -> Fraction:
    return max(lo, min(hi, x))


def display(value: Fraction | float | None, places: int = 2) -> str | None:
    """Round half-up for display (e.g. 2.505 -> 2.51)."""
    if value is None:
        return None
    if isinstance(value, Fraction):
        d = Decimal(value.numerator) / Decimal(value.denominator)
    else:
        d = Decimal(str(value))
    return str(d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ Form Score
@dataclass(frozen=True)
class FormScore:
    """Spec 4.2: Form Score = PPG + 0.5 x clip(GD/G, -2, +2). Range [-1, 4]."""

    matches: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int

    @property
    def points(self) -> int:
        return 3 * self.wins + self.draws

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def ppg(self) -> Fraction:
        return Fraction(self.points, self.matches)

    @property
    def gd_per_game(self) -> Fraction:
        return Fraction(self.goal_difference, self.matches)

    @property
    def capped_gd_per_game(self) -> Fraction:
        return clip(self.gd_per_game, -GD_CAP, GD_CAP)

    @property
    def gd_contribution(self) -> Fraction:
        return GD_WEIGHT * self.capped_gd_per_game

    @property
    def score(self) -> Fraction:
        return self.ppg + self.gd_contribution

    def breakdown(self) -> dict:
        return {
            "matches": self.matches,
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "points": self.points,
            "goals_for": self.goals_for,
            "goals_against": self.goals_against,
            "goal_difference": self.goal_difference,
            "points_per_game": float(self.ppg),
            "gd_per_game": float(self.gd_per_game),
            "capped_gd_per_game": float(self.capped_gd_per_game),
            "weighted_gd_contribution": float(self.gd_contribution),
            "form_score": float(self.score),
            "form_score_display": display(self.score),
        }


def form_score(results: Iterable[tuple[int, int]]) -> FormScore | None:
    """Form Score from (goals_for, goals_against) pairs; None if no matches."""
    w = d = lo = gf = ga = n = 0
    for f, a in results:
        n += 1
        gf += f
        ga += a
        if f > a:
            w += 1
        elif f == a:
            d += 1
        else:
            lo += 1
    if n == 0:
        return None
    return FormScore(n, w, d, lo, gf, ga)


# ------------------------------------------------------------ league benchmark
@dataclass(frozen=True)
class PooledBenchmark:
    """Spec 4.7: the Form Score formula applied to pooled league results.

    Home benchmark uses all home results (home wins, draws, home goals minus
    away goals); away benchmark the mirror image. Not an average of team scores.
    """

    competition_id: int
    season: int
    matches: int
    home_wins: int
    draws: int
    away_wins: int
    home_goals: int
    away_goals: int

    @property
    def home(self) -> FormScore:
        return FormScore(
            self.matches,
            self.home_wins,
            self.draws,
            self.away_wins,
            self.home_goals,
            self.away_goals,
        )

    @property
    def away(self) -> FormScore:
        return FormScore(
            self.matches,
            self.away_wins,
            self.draws,
            self.home_wins,
            self.away_goals,
            self.home_goals,
        )

    @property
    def draw_rate(self) -> Fraction:
        return Fraction(self.draws, self.matches)


def pooled_benchmark(
    competition_id: int, season: int, scores: Iterable[tuple[int, int]]
) -> PooledBenchmark | None:
    """Benchmark from (home_goals, away_goals) of eligible league matches."""
    n = hw = dr = aw = hg = ag = 0
    for h, a in scores:
        n += 1
        hg += h
        ag += a
        if h > a:
            hw += 1
        elif h == a:
            dr += 1
        else:
            aw += 1
    if n == 0:
        return None
    return PooledBenchmark(competition_id, season, n, hw, dr, aw, hg, ag)


def venue_adjusted_difference(
    home_score: Fraction, away_score: Fraction, bench_home: Fraction, bench_away: Fraction
) -> Fraction:
    """Spec 4.6: (Home - League Home) - (Away - League Away)."""
    return (home_score - bench_home) - (away_score - bench_away)


# --------------------------------------------------------------- goals markets
@dataclass(frozen=True)
class Rate:
    """A historical rate shown as k/n (pct). Not a probability."""

    hits: int
    matches: int

    @property
    def value(self) -> Fraction:
        return Fraction(self.hits, self.matches)

    def as_dict(self) -> dict:
        return {
            "hits": self.hits,
            "matches": self.matches,
            "rate": float(self.value),
            "display": f"{self.hits}/{self.matches} ({display(self.value * 100, 0)}%)",
        }


def rate(flags: Sequence[bool]) -> Rate | None:
    return Rate(sum(flags), len(flags)) if flags else None


def combined_indicator(home: Rate | None, away: Rate | None) -> Fraction | None:
    """Spec 5.2 / 6.2: simple average of the two team rates (None if either missing)."""
    if home is None or away is None:
        return None
    return (home.value + away.value) / 2


# ------------------------------------------------------------- limited data
FORM_MIN_MATCHES = 3
GOALS_MIN_MATCHES = 6
CURRENT_DIVISION_MIN = 3


def limited_data_reasons(total: int, current_division: int, minimum_total: int) -> list[str]:
    """Spec 10.4: independent conditions; any one triggers 'Limited data'."""
    reasons = []
    if total < minimum_total:
        reasons.append(f"fewer_than_{minimum_total}_matches")
    if current_division < CURRENT_DIVISION_MIN:
        reasons.append(f"fewer_than_{CURRENT_DIVISION_MIN}_current_division_matches")
    return reasons
