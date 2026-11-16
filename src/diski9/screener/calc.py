"""Pure Screener calculations.

Match result: the **Diski Form Score**, Model D (Milestone 5.3): half points,
half goal difference, 0-5, no bonuses. The banded Milestone 5 score ("Model A",
``banded_form_score``), the spec v1.2 formula (``FormScore``/``form_score``) and
pooled league benchmarks are kept only as legacy helpers for research
reproducibility and regression comparison; the Screener engine does not use them.

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
# Scale offset (Nov 2026 decision): spec v1.2 Form Score + 1, so the scale runs
# 0 to 5 instead of -1 to 4. Differences between Form Scores, and therefore all
# rankings, are unchanged because the offset cancels.
FORM_OFFSET = Fraction(1)
FORM_MIN = Fraction(0)
FORM_MAX = Fraction(5)


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


# ------------------------------------------- Diski Form Score (Model D, 5.3)
FULL_WINDOW = 5
GD_LIMIT = 9
HALF_SCALE = Fraction(5, 2)


@dataclass(frozen=True)
class DiskiFormScore:
    """Diski Form Score, Model D (engine 2.1.0, Milestone 5.3), from up to five
    eligible matches, most recent first.

        points component        = 2.5 x P / 15
        goal-difference component = 2.5 x (clip(GD, -9, +9) + 9) / 18
        Diski Form Score        = points component + goal-difference component

    P is the points earned (3 per win, 1 per draw), GD goals for minus goals
    against. Bounded 0 to 5; no bonuses. Partial windows use the actual totals of
    the matches available - nothing is prorated - so a short window cannot reach
    5. Because the goal-difference component is symmetric (1.25 at GD 0), a team
    with very few matches can still score above 0; the Limited-data flag marks
    such windows. Not a probability.
    """

    results: tuple[str, ...]  # "W"/"D"/"L", most recent first
    goals_for: int
    goals_against: int

    @property
    def matches(self) -> int:
        return len(self.results)

    @property
    def wins(self) -> int:
        return self.results.count("W")

    @property
    def draws(self) -> int:
        return self.results.count("D")

    @property
    def losses(self) -> int:
        return self.results.count("L")

    @property
    def points(self) -> int:
        return 3 * self.wins + self.draws

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def goal_difference_capped(self) -> int:
        return max(-GD_LIMIT, min(GD_LIMIT, self.goal_difference))

    @property
    def full_window(self) -> bool:
        return self.matches >= FULL_WINDOW

    @property
    def points_component(self) -> Fraction:
        return HALF_SCALE * Fraction(self.points, 15)

    @property
    def goal_difference_component(self) -> Fraction:
        return HALF_SCALE * Fraction(self.goal_difference_capped + GD_LIMIT, 2 * GD_LIMIT)

    @property
    def score(self) -> Fraction:
        return self.points_component + self.goal_difference_component

    def breakdown(self) -> dict:
        return {
            "method": "D",
            "matches": self.matches,
            "full_window": self.full_window,
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "points": self.points,
            "goals_for": self.goals_for,
            "goals_against": self.goals_against,
            "goal_difference": self.goal_difference,
            "goal_difference_capped": self.goal_difference_capped,
            "points_component": float(self.points_component),
            "points_component_display": display(self.points_component),
            "goal_difference_component": float(self.goal_difference_component),
            "goal_difference_component_display": display(self.goal_difference_component),
            "form_score": float(self.score),
            "form_score_display": display(self.score),
        }


def _tally(results: Iterable[tuple[int, int]]) -> tuple[tuple[str, ...], int, int] | None:
    seq: list[str] = []
    gf = ga = 0
    for f, a in results:
        gf += f
        ga += a
        seq.append("W" if f > a else "D" if f == a else "L")
    return (tuple(seq), gf, ga) if seq else None


def diski_form_score(results: Iterable[tuple[int, int]]) -> DiskiFormScore | None:
    """Model D from (goals_for, goals_against) pairs, most recent first; None
    (Unavailable, never 0) if there are no matches."""
    t = _tally(results)
    return None if t is None else DiskiFormScore(*t)


# ------------------------------------- legacy banded Diski Form Score (Model A)
FORM_RAW_MAX = Fraction(13, 2)  # 2.5 + 2.5 + 0.5 + 0.5 + 0.5
FORM_SCALE = Fraction(5)
BONUS = Fraction(1, 2)


def points_award(points: int) -> Fraction:
    """0-2: 0, 3-5: 0.5, 6-8: 1.0, 9-11: 1.5, 12-14: 2.0, 15: 2.5."""
    return Fraction(min(max(points, 0) // 3, 5), 2)


def goal_difference_award(gd: int) -> Fraction:
    """<=0: 0, +1-2: 0.5, +3-4: 1.0, +5-6: 1.5, +7-8: 2.0, >=+9: 2.5."""
    if gd <= 0:
        return Fraction(0)
    return Fraction(min((gd + 1) // 2, 5), 2)


@dataclass(frozen=True)
class BandedFormScore:
    """LEGACY (engine 2.0.0, Milestone 5): banded Diski Form Score, "Model A".

    Replaced in production by Model D (engine 2.1.0, Milestone 5.3). Kept only so
    the Milestone 5.1/5.2 research remains reproducible.


    raw = points award + goal-difference award + bonuses (each +0.5):
      * won the three most recent matches (needs at least 3 matches)
      * scored at least 11 goals in the window
      * conceded at most 2 goals (only with a full five-match window)
    score = raw / 6.5 x 5, in [0, 5]. Partial windows use the actual matches
    with the same thresholds and are never scaled up.
    """

    results: tuple[str, ...]  # "W"/"D"/"L", most recent first
    goals_for: int
    goals_against: int

    @property
    def matches(self) -> int:
        return len(self.results)

    @property
    def wins(self) -> int:
        return self.results.count("W")

    @property
    def draws(self) -> int:
        return self.results.count("D")

    @property
    def losses(self) -> int:
        return self.results.count("L")

    @property
    def points(self) -> int:
        return 3 * self.wins + self.draws

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def full_window(self) -> bool:
        return self.matches >= FULL_WINDOW

    @property
    def points_award(self) -> Fraction:
        return points_award(self.points)

    @property
    def goal_difference_award(self) -> Fraction:
        return goal_difference_award(self.goal_difference)

    @property
    def bonus_last_three_wins(self) -> Fraction:
        return BONUS if self.matches >= 3 and self.results[:3] == ("W", "W", "W") else Fraction(0)

    @property
    def bonus_goals_scored(self) -> Fraction:
        return BONUS if self.goals_for >= 11 else Fraction(0)

    @property
    def bonus_goals_conceded(self) -> Fraction:
        return BONUS if self.full_window and self.goals_against <= 2 else Fraction(0)

    @property
    def raw(self) -> Fraction:
        return (
            self.points_award
            + self.goal_difference_award
            + self.bonus_last_three_wins
            + self.bonus_goals_scored
            + self.bonus_goals_conceded
        )

    @property
    def score(self) -> Fraction:
        return self.raw / FORM_RAW_MAX * FORM_SCALE

    def breakdown(self) -> dict:
        return {
            "matches": self.matches,
            "full_window": self.full_window,
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "points": self.points,
            "goals_for": self.goals_for,
            "goals_against": self.goals_against,
            "goal_difference": self.goal_difference,
            "points_award": float(self.points_award),
            "goal_difference_award": float(self.goal_difference_award),
            "bonus_last_three_wins": float(self.bonus_last_three_wins),
            "bonus_goals_scored": float(self.bonus_goals_scored),
            "bonus_goals_conceded": float(self.bonus_goals_conceded),
            "bonus_last_three_wins_possible": self.matches >= 3,
            "bonus_goals_conceded_possible": self.full_window,
            "raw": float(self.raw),
            "raw_max": float(FORM_RAW_MAX),
            "form_score": float(self.score),
            "form_score_display": display(self.score),
        }


def banded_form_score(results: Iterable[tuple[int, int]]) -> BandedFormScore | None:
    """LEGACY Model A. From (goals_for, goals_against) pairs, most recent first."""
    seq: list[str] = []
    gf = ga = 0
    for f, a in results:
        gf += f
        ga += a
        seq.append("W" if f > a else "D" if f == a else "L")
    if not seq:
        return None
    return BandedFormScore(tuple(seq), gf, ga)


# ------------------------------------------------- legacy (spec v1.2) formula
@dataclass(frozen=True)
class FormScore:
    """Form Score = 1 + PPG + 0.5 x clip(GD/G, -2, +2). Range [0, 5].

    Spec 4.2 formula plus a constant +1 scale offset (``FORM_OFFSET``).
    """

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
        return FORM_OFFSET + self.ppg + self.gd_contribution

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
            "scale_offset": float(FORM_OFFSET),
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
FORM_MIN_MATCHES = 5  # Diski Form Score: Limited data below a full five-match window
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
