"""Research only (Milestone 5.2): point-in-time goals-market dataset.

For every eligible completed league fixture, using only matches that kicked off
before it:

* the production BTTS and Over 2.5 indicators (current season, current
  competition, up to 10 matches per team, mean of the two team rates), computed
  with the production ``rate``/``combined_indicator`` functions
* a shrinkage candidate: each team rate shrunk to the league rate with k = 5
  pseudo-matches
* a historical goal-rate model (research only):
      overall basis: g = (H + A) / 2 goals per team per match
          attack_t  = ((GF_t + k g) / (n_t + k)) / g
          defence_t = ((GA_t + k g) / (n_t + k)) / g
          lambda_H = H attack_home defence_away ; lambda_A = A attack_away defence_home
      venue basis: the home side's home matches are compared with the league home
      average H, the away side's away matches with A (and conceding likewise)
  where H, A are league goals per match for home and away sides.

League prior (league level only, provenance recorded): current-season league
matches before kickoff; with fewer than 30 they are blended with the previous
season of the same competition (weight n/30). Team-level rates never use earlier
seasons or other divisions.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from diski9.screener.calc import combined_indicator, rate
from diski9.screener.engine import MatchStore, TeamMatch

K_SHRINK = 5
LEAGUE_MIN = 30
GOALS_WINDOW = 10


@dataclass(frozen=True)
class League:
    home_goals: float  # per match
    away_goals: float
    btts: float
    over: float
    current_matches: int
    source: str  # current | blended_previous | previous_only


def league_prior(
    store: MatchStore, competition_id: int, season: int, cutoff: datetime
) -> League | None:
    def stats(ms):
        n = len(ms)
        return (
            n,
            sum(m.home_goals for m in ms) / n,
            sum(m.away_goals for m in ms) / n,
            sum(m.home_goals > 0 and m.away_goals > 0 for m in ms) / n,
            sum(m.home_goals + m.away_goals >= 3 for m in ms) / n,
        )

    cur = store.league_matches(competition_id, season, cutoff)
    prev = store.league_matches(competition_id, season - 1, cutoff)
    if len(cur) >= LEAGUE_MIN:
        n, *v = stats(cur)
        return League(*v, n, "current")
    if not prev:
        return None  # thin current season and no earlier season stored: no reliable prior
    _, *p = stats(prev)
    if not cur:
        return League(*p, 0, "previous_only")
    n, *c = stats(cur)
    w = n / LEAGUE_MIN
    return League(*(w * a + (1 - w) * b for a, b in zip(c, p, strict=True)), n, "blended_previous")


@dataclass
class GoalsRow:
    fixture_id: int
    competition_id: int
    season: int
    kickoff: datetime
    basis: str
    home_goals: int
    away_goals: int
    n_home: int
    n_away: int
    btts_home: float | None
    btts_away: float | None
    over_home: float | None
    over_away: float | None
    btts_indicator: float | None  # production definition
    over_indicator: float | None
    btts_shrunk: float | None
    over_shrunk: float | None
    league: League | None
    lambda_home: float | None
    lambda_away: float | None

    @property
    def btts(self) -> int:
        return int(self.home_goals > 0 and self.away_goals > 0)

    @property
    def over(self) -> int:
        return int(self.home_goals + self.away_goals >= 3)

    @property
    def outcome(self) -> int:
        h, a = self.home_goals, self.away_goals
        return 0 if h > a else 1 if h == a else 2

    @property
    def min_n(self) -> int:
        return min(self.n_home, self.n_away)


def _shrunk(hits: int, n: int, prior: float, k: int = K_SHRINK) -> float:
    return (hits + k * prior) / (n + k)


def goal_rates(
    hw: list[TeamMatch], aw: list[TeamMatch], lg: League, basis: str, k: int = K_SHRINK
) -> tuple[float, float]:
    H, A = lg.home_goals, lg.away_goals
    gf_h, ga_h = sum(t.goals_for for t in hw), sum(t.goals_against for t in hw)
    gf_a, ga_a = sum(t.goals_for for t in aw), sum(t.goals_against for t in aw)
    nh, na = len(hw), len(aw)
    if basis == "venue":
        att_h = (gf_h + k * H) / (nh + k) / H
        def_a = (ga_a + k * H) / (na + k) / H
        att_a = (gf_a + k * A) / (na + k) / A
        def_h = (ga_h + k * A) / (nh + k) / A
    else:
        g = (H + A) / 2
        att_h = (gf_h + k * g) / (nh + k) / g
        def_h = (ga_h + k * g) / (nh + k) / g
        att_a = (gf_a + k * g) / (na + k) / g
        def_a = (ga_a + k * g) / (na + k) / g
    return H * att_h * def_a, A * att_a * def_h


def build_rows(
    store: MatchStore, competitions: Iterable[int], seasons: Iterable[int]
) -> list[GoalsRow]:
    comps, yrs = set(competitions), set(seasons)
    rows = []
    for m in store.matches:
        if not m.stats_eligible or m.competition_id not in comps or m.season not in yrs:
            continue
        lg = league_prior(store, m.competition_id, m.season, m.kickoff)
        for basis in ("overall", "venue"):
            hw = store.team_window(
                m.home_id,
                m.kickoff,
                "home" if basis == "venue" else None,
                GOALS_WINDOW,
                competition_id=m.competition_id,
                season=m.season,
            )
            aw = store.team_window(
                m.away_id,
                m.kickoff,
                "away" if basis == "venue" else None,
                GOALS_WINDOW,
                competition_id=m.competition_id,
                season=m.season,
            )
            bh = rate([t.goals_for > 0 and t.goals_against > 0 for t in hw])
            ba = rate([t.goals_for > 0 and t.goals_against > 0 for t in aw])
            oh = rate([t.goals_for + t.goals_against >= 3 for t in hw])
            oa = rate([t.goals_for + t.goals_against >= 3 for t in aw])
            bi, oi = combined_indicator(bh, ba), combined_indicator(oh, oa)
            if lg is not None:
                bs = (
                    _shrunk(bh.hits if bh else 0, len(hw), lg.btts)
                    + _shrunk(ba.hits if ba else 0, len(aw), lg.btts)
                ) / 2
                os_ = (
                    _shrunk(oh.hits if oh else 0, len(hw), lg.over)
                    + _shrunk(oa.hits if oa else 0, len(aw), lg.over)
                ) / 2
                lh, la = goal_rates(hw, aw, lg, basis)
            else:
                bs = os_ = lh = la = None
            rows.append(
                GoalsRow(
                    m.fixture_id,
                    m.competition_id,
                    m.season,
                    m.kickoff,
                    basis,
                    m.home_goals,
                    m.away_goals,
                    len(hw),
                    len(aw),
                    float(bh.value) if bh else None,
                    float(ba.value) if ba else None,
                    float(oh.value) if oh else None,
                    float(oa.value) if oa else None,
                    None if bi is None else float(bi),
                    None if oi is None else float(oi),
                    bs,
                    os_,
                    lg,
                    lh,
                    la,
                )
            )
    return rows


def fit_rho(rows: list[GoalsRow], bounds=(-0.3, 0.3)) -> float:
    """Maximum-likelihood Dixon-Coles rho given each row's goal rates. Only the
    four low scores carry information about rho; other scores' tau is 1."""
    from scipy.optimize import minimize_scalar

    lh = np.array([r.lambda_home for r in rows])
    la = np.array([r.lambda_away for r in rows])
    h = np.array([r.home_goals for r in rows])
    a = np.array([r.away_goals for r in rows])
    lo_lim = np.maximum(-1 / lh, -1 / la)
    hi_lim = np.minimum(1 / (lh * la), 1)

    def nll(rho):
        r = np.clip(rho, lo_lim, hi_lim)
        t = np.ones(len(rows))
        t = np.where((h == 0) & (a == 0), 1 - lh * la * r, t)
        t = np.where((h == 0) & (a == 1), 1 + lh * r, t)
        t = np.where((h == 1) & (a == 0), 1 + la * r, t)
        t = np.where((h == 1) & (a == 1), 1 - r, t)
        return -np.log(np.clip(t, 1e-12, None)).sum()

    return float(minimize_scalar(nll, bounds=bounds, method="bounded", options={"xatol": 1e-6}).x)
