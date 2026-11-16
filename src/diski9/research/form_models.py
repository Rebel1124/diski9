"""Research only (Milestone 5.2): Diski Form Score candidates A-D.

Nothing here is used by the Screener, its cache or the Challenge. Model A is the
production implementation imported unchanged. The formulas for B-D were fixed in
``docs/research/m52/preregistration.md`` before any evaluation was run.

Shared rules (identical to production):
* window: last five eligible matches before kickoff (venue-specific or overall)
* partial windows: the actual totals of the matches available - nothing is
  prorated, so a short window cannot reach the maximum
* bonuses (B, C): +0.5 won last three (needs >= 3 matches), +0.5 scored >= 11,
  +0.5 conceded <= 2 (needs a full five-match window)
* no eligible match -> None ("unavailable"), never 0

| Model | Score on 0-5 |
|---|---|
| A | production banded score |
| B | 5/6.5 x [2.5 pts/15 + 2.5 min(max(GD, 0)/9, 1) + bonuses] |
| C | 5/6.5 x [2.5 pts/15 + 1.25 + 1.25 clip(GD/9, -1, 1) + bonuses] |
| D | 2.5 pts/15 + 2.5 (clip(GD, -9, 9) + 9)/18 (no bonuses) |
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from diski9.screener.calc import diski_form_score
from diski9.screener.engine import MatchStore, TeamMatch

MODELS = ("a", "b", "c", "d")
MODEL_NAMES = {
    "a": "A: banded (production)",
    "b": "B: continuous, positive GD only",
    "c": "C: continuous, symmetric GD",
    "d": "D: points + symmetric GD, no bonuses",
}
RAW_MAX = Fraction(13, 2)
HALF = Fraction(1, 2)
GD_CAP = 9


@dataclass(frozen=True)
class Window:
    """Totals of a form window (most recent match first)."""

    matches: int
    points: int
    goals_for: int
    goals_against: int
    won_last_three: bool

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    @classmethod
    def of(cls, results: Iterable[tuple[int, int]]) -> Window | None:
        pairs = list(results)
        if not pairs:
            return None
        return cls(
            len(pairs),
            sum(3 if f > a else 1 if f == a else 0 for f, a in pairs),
            sum(f for f, _ in pairs),
            sum(a for _, a in pairs),
            len(pairs) >= 3 and all(f > a for f, a in pairs[:3]),
        )


def bonuses(w: Window) -> Fraction:
    b = Fraction(0)
    if w.matches >= 3 and w.won_last_three:
        b += HALF
    if w.goals_for >= 11:
        b += HALF
    if w.matches >= 5 and w.goals_against <= 2:
        b += HALF
    return b


def points_component(points: int) -> Fraction:
    return Fraction(5, 2) * Fraction(points, 15)


def positive_gd_component(gd: int) -> Fraction:
    return Fraction(5, 2) * min(Fraction(max(gd, 0), GD_CAP), Fraction(1))


def symmetric_gd_component(gd: int) -> Fraction:
    """0 at GD <= -9, 1.25 at GD = 0, 2.5 at GD >= +9; linear in between."""
    return Fraction(5, 4) + Fraction(5, 4) * max(Fraction(-1), min(Fraction(1), Fraction(gd, 9)))


def score_b(w: Window) -> Fraction:
    return (points_component(w.points) + positive_gd_component(w.goal_difference) + bonuses(w)) * (
        5 / RAW_MAX
    )


def score_c(w: Window) -> Fraction:
    return (points_component(w.points) + symmetric_gd_component(w.goal_difference) + bonuses(w)) * (
        5 / RAW_MAX
    )


def score_d(w: Window) -> Fraction:
    return points_component(w.points) + symmetric_gd_component(w.goal_difference)


def score(model: str, results: Iterable[tuple[int, int]]) -> Fraction | None:
    """Form Score for ``results`` ((goals_for, goals_against), most recent first)."""
    pairs = list(results)
    if model == "a":
        fs = diski_form_score(pairs)
        return None if fs is None else fs.score
    w = Window.of(pairs)
    if w is None:
        return None
    return {"b": score_b, "c": score_c, "d": score_d}[model](w)


# ------------------------------------------------------------------ dataset
@dataclass
class FormRow:
    fixture_id: int
    competition_id: int
    season: int
    kickoff: datetime
    basis: str
    outcome: int  # 0 home, 1 draw, 2 away
    home_n: int
    away_n: int
    scores: dict[str, tuple[float | None, float | None]]  # model -> (home, away)
    home_window: Window | None
    away_window: Window | None
    home_bonus_flags: tuple[bool, bool, bool]
    away_bonus_flags: tuple[bool, bool, bool]
    other_division_in_window: bool
    changed_division: bool  # either team played a different division last season
    season_venue_ppg: tuple[float | None, float | None]  # home at home, away away

    def diff(self, model: str) -> float | None:
        h, a = self.scores[model]
        return None if h is None or a is None else h - a

    @property
    def complete(self) -> bool:
        return self.home_n == 5 and self.away_n == 5


def _flags(w: Window | None) -> tuple[bool, bool, bool]:
    if w is None:
        return (False, False, False)
    return (
        w.matches >= 3 and w.won_last_three,
        w.goals_for >= 11,
        w.matches >= 5 and w.goals_against <= 2,
    )


def _ppg(window: list[TeamMatch]) -> float | None:
    if not window:
        return None
    return sum(
        3 if t.goals_for > t.goals_against else t.goals_for == t.goals_against for t in window
    ) / len(window)


def team_divisions(store: MatchStore) -> dict[tuple[int, int], set[int]]:
    """(team, season) -> competitions with eligible matches."""
    out: dict[tuple[int, int], set[int]] = {}
    for m in store.matches:
        if m.stats_eligible:
            for t in (m.home_id, m.away_id):
                out.setdefault((t, m.season), set()).add(m.competition_id)
    return out


def changed_division(divisions: dict, team: int, competition_id: int, season: int) -> bool:
    prev = divisions.get((team, season - 1))
    return bool(prev) and competition_id not in prev


def build_rows(
    store: MatchStore, competitions: Iterable[int], seasons: Iterable[int]
) -> list[FormRow]:
    """Point-in-time rows (cutoff = kickoff) for every eligible completed fixture."""
    comps, yrs = set(competitions), set(seasons)
    divisions = team_divisions(store)
    rows: list[FormRow] = []
    for m in store.matches:
        if not m.stats_eligible or m.competition_id not in comps or m.season not in yrs:
            continue
        outcome = 0 if m.home_goals > m.away_goals else 1 if m.home_goals == m.away_goals else 2
        venue_ppg = (
            _ppg(store.team_window(m.home_id, m.kickoff, "home", 99, m.competition_id, m.season)),
            _ppg(store.team_window(m.away_id, m.kickoff, "away", 99, m.competition_id, m.season)),
        )
        changed = changed_division(
            divisions, m.home_id, m.competition_id, m.season
        ) or changed_division(divisions, m.away_id, m.competition_id, m.season)
        for basis in ("venue", "overall"):
            hw = store.team_window(m.home_id, m.kickoff, "home" if basis == "venue" else None, 5)
            aw = store.team_window(m.away_id, m.kickoff, "away" if basis == "venue" else None, 5)
            hp = [(t.goals_for, t.goals_against) for t in hw]
            ap = [(t.goals_for, t.goals_against) for t in aw]
            sc = {}
            for model in MODELS:
                h, a = score(model, hp), score(model, ap)
                sc[model] = (None if h is None else float(h), None if a is None else float(a))
            hwin, awin = Window.of(hp), Window.of(ap)
            rows.append(
                FormRow(
                    m.fixture_id,
                    m.competition_id,
                    m.season,
                    m.kickoff,
                    basis,
                    outcome,
                    len(hw),
                    len(aw),
                    sc,
                    hwin,
                    awin,
                    _flags(hwin),
                    _flags(awin),
                    any(t.match.competition_id != m.competition_id for t in hw + aw),
                    changed,
                    venue_ppg,
                )
            )
    return rows


# --------------------------------------------------------------- features
def features(row: FormRow, name: str) -> list[float] | None:
    """Feature vector for the secondary (H/D/A) model, or None if unavailable."""
    hw, aw = row.home_window, row.away_window
    if name in MODELS:
        d = row.diff(name)
        return None if d is None else [d]
    if hw is None or aw is None:
        return None
    ppg = hw.points / hw.matches - aw.points / aw.matches
    gd = hw.goal_difference / hw.matches - aw.goal_difference / aw.matches
    if name == "ppg":
        return [ppg]
    if name == "gd":
        return [gd]
    if name == "ppg_gd":
        return [ppg, gd]
    if name == "ppg_gd_gf":
        return [ppg, gd, hw.goals_for / hw.matches - aw.goals_for / aw.matches]
    if name == "d_plus_bonuses":
        d = row.diff("d")
        return [d] + [
            float(x) - float(y)
            for x, y in zip(row.home_bonus_flags, row.away_bonus_flags, strict=True)
        ]
    if name == "venue_ppg":
        h, a = row.season_venue_ppg
        return None if h is None or a is None else [h - a]
    raise ValueError(name)
