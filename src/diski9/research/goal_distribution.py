"""Research only: one goal-distribution model for 1X2, BTTS and Over/Under 2.5.

Nothing here is used by the Screener, the cache or the Challenge. No bookmaker
data is read: every input is a completed match result in the local database.

For each fixture the model estimates two numbers, the home and away **estimated
goals** (lambda_home, lambda_away), from goals scored and conceded before kickoff.
Two independent goal distributions then give every market probability.

Point-in-time rules
-------------------
* Team statistics: current season, current competition, matches that kicked off
  strictly before the fixture (``MatchStore.team_window``). Earlier seasons and
  other divisions are never used for a team.
* League averages: current-season league matches before kickoff, blended with
  ``m0`` pseudo-matches at the *previous season's league-level* average of the
  same competition (no team results). Without a previous season stored, the
  current season alone is used once it has ``LEAGUE_MIN`` matches; before that
  the estimate is unavailable.
* Hyperparameters (shrinkage strengths, decay) are chosen on earlier seasons only.

Smoothed venue-aware multiplicative model (all windows)
-------------------------------------------------------
H, A = league home / away goals per match; g = (H + A) / 2.

For a team with n_h home and n_a away matches in the window:

    expected scored   E_for = n_h H + n_a A     (league rates for its venue mix)
    expected conceded E_ag  = n_h A + n_a H

    overall attack   a = (GF + k_o g) / (E_for + k_o g)
    overall defence  d = (GA + k_o g) / (E_ag + k_o g)     (> 1 = concedes more)

    home attack   a_H = (GF_h + k_v H a) / (H (n_h + k_v))
    home defence  d_H = (GA_h + k_v A d) / (A (n_h + k_v))
    away attack   a_A = (GF_a + k_v A a) / (A (n_a + k_v))
    away defence  d_A = (GA_a + k_v H d) / (H (n_a + k_v))

    lambda_home = H x a_H(home team) x d_A(away team)
    lambda_away = A x a_A(away team) x d_H(home team)

k_o pseudo-matches pull the overall factors towards the league (1.0); k_v
pseudo-matches pull the venue factors towards the team's own overall factor.
k_v = infinity means "overall factors only" (venue enters through H and A).

Strength / tempo split (optional ``k_t``)
-----------------------------------------
The overall factors can be rewritten as strength s = sqrt(a / d) and goal tempo
t = sqrt(a d), so that a = s t and d = t / s and

    lambda_home = H x (s_home / s_away) x t_home x t_away
    lambda_away = A x (s_away / s_home) x t_home x t_away

Strength drives who wins; tempo drives how many goals there are. With ``k_t`` set,
s is computed from factors shrunk with k_o and t from factors shrunk with k_t, so
the (weakly predictable) goal level can be shrunk harder than team strength.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from diski9.screener.engine import MatchStore, TeamMatch

LEAGUE_MIN = 30  # current-season league matches needed when no previous season exists
GAMES_PER_TEAM = {39: 38, 40: 46, 288: 30, 289: 30}
LEAGUE_NAME = {39: "EPL", 40: "Championship", 288: "PSL", 289: "PSL 1st Division"}
WINDOWS = ("season", "last8", "last10")
HALF_LIVES = (3, 5, 8, 12, 20)  # recency weighting, in team matches
CATS = 4  # empirical categories 0, 1, 2, 3+
LG_MAX = 10  # league goal histograms 0..10 (more than 10 goals by one side: none stored)
INF = math.inf


# ===================================================================== markets
def goal_grid(max_lambda: float) -> int:
    """Number of goal values (0..G-1) so that the Poisson tail beyond is < 1e-15."""
    lam = max(float(max_lambda), 0.0)
    return int(math.ceil(lam + 12 * math.sqrt(lam) + 26))


def poisson_marginals(lam: np.ndarray | float, size: int | None = None) -> np.ndarray:
    """Rows of Poisson probabilities P(X = 0..G-1); row sums are 1 within 1e-15."""
    lam = np.atleast_1d(np.asarray(lam, dtype=float))
    G = size or goal_grid(lam.max(initial=0.0))
    k = np.arange(G)
    logp = k[None, :] * np.log(np.maximum(lam[:, None], 1e-300)) - lam[:, None]
    logp -= np.array([math.lgamma(i + 1) for i in k])[None, :]
    p = np.exp(logp)
    p[lam == 0] = 0.0
    p[lam == 0, 0] = 1.0
    return p


def markets_from_marginals(ph: np.ndarray, pa: np.ndarray) -> dict[str, np.ndarray]:
    """All market probabilities from independent home / away goal distributions.

    Exact sums over every scoreline in the grid. ``away`` and the complements are
    computed as 1 - (the rest), so each market sums to 1 exactly in floating point;
    ``mass`` reports the grid's captured probability (1 within ~1e-15)."""
    ph, pa = np.atleast_2d(ph), np.atleast_2d(pa)
    G = max(ph.shape[1], pa.shape[1])
    ph = np.pad(ph, ((0, 0), (0, G - ph.shape[1])))
    pa = np.pad(pa, ((0, 0), (0, G - pa.shape[1])))
    mass = ph.sum(axis=1) * pa.sum(axis=1)
    cdf_h = np.cumsum(ph, axis=1)
    home_gt = ph.sum(axis=1, keepdims=True) - cdf_h  # P(H > j)
    home = (pa * home_gt).sum(axis=1)
    draw = (pa * ph).sum(axis=1)
    btts_yes = (ph.sum(axis=1) - ph[:, 0]) * (pa.sum(axis=1) - pa[:, 0])
    under = (
        ph[:, 0] * (pa[:, 0] + pa[:, 1] + pa[:, 2])
        + ph[:, 1] * (pa[:, 0] + pa[:, 1])
        + ph[:, 2] * pa[:, 0]
    )
    return {
        "home": home,
        "draw": draw,
        "away": 1.0 - home - draw,
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
        "under": under,
        "over": 1.0 - under,
        "mass": mass,
    }


def poisson_markets(lh, la) -> dict[str, np.ndarray]:
    lh = np.atleast_1d(np.asarray(lh, dtype=float))
    la = np.atleast_1d(np.asarray(la, dtype=float))
    G = goal_grid(max(lh.max(initial=0), la.max(initial=0)))
    return markets_from_marginals(poisson_marginals(lh, G), poisson_marginals(la, G))


def dixon_coles_adjust(mk: dict[str, np.ndarray], lh, la, rho: float) -> dict[str, np.ndarray]:
    """Dixon-Coles low-score correction applied to Poisson market probabilities
    (diagnostic only). It moves mass between 0-0/1-1 and 1-0/0-1; total mass and
    the Under 2.5 probability are unchanged (all four cells have <= 2 goals)."""
    lh, la = np.asarray(lh, float), np.asarray(la, float)
    p00 = np.exp(-lh - la)
    d00 = -lh * la * rho * p00  # 0-1 gains rho lh p01: absorbed by away = 1 - home - draw
    d10, d11 = rho * la * (p00 * lh), -rho * (p00 * lh * la)
    out = dict(mk)
    out["home"] = mk["home"] + d10
    out["draw"] = mk["draw"] + d00 + d11
    out["away"] = 1.0 - out["home"] - out["draw"]
    out["btts_yes"] = mk["btts_yes"] + d11
    out["btts_no"] = 1.0 - out["btts_yes"]
    return out


def dc_rho_limits(lh, la) -> tuple[np.ndarray, np.ndarray]:
    lh, la = np.asarray(lh, float), np.asarray(la, float)
    return np.maximum(-1 / lh, -1 / la), np.minimum(1 / (lh * la), 1.0)


# ===================================================================== dataset
@dataclass
class Dataset:
    """One row per eligible completed league fixture (point-in-time features)."""

    fixture_id: np.ndarray
    competition: np.ndarray
    season: np.ndarray
    kickoff: list[datetime]
    home_id: np.ndarray
    away_id: np.ndarray
    hg: np.ndarray  # actual goals (outcomes only; never features)
    ag: np.ndarray
    # league state at kickoff
    cur_n: np.ndarray
    cur_hg: np.ndarray
    cur_ag: np.ndarray
    cur_res: np.ndarray  # (N, 5): home wins, draws, away wins, btts, over
    cur_hist_h: np.ndarray  # (N, 11) home-goal histogram 0..10
    cur_hist_a: np.ndarray
    prev_n: np.ndarray  # previous season, league level only (0 = not stored)
    prev_hg: np.ndarray
    prev_ag: np.ndarray
    prev_res: np.ndarray
    prev_hist_h: np.ndarray
    prev_hist_a: np.ndarray
    # team statistics: window -> (N, 12) [home team n_h n_a gf_h ga_h gf_a ga_a, away team ...]
    team: dict[str, np.ndarray] = field(default_factory=dict)
    # empirical category counts, season window: (N, 4 sides, 4 cats)
    # sides: home team scored at home, home team conceded at home,
    #        away team scored away,   away team conceded away
    cats: np.ndarray | None = None
    cats_all: np.ndarray | None = None  # same sides but over all venues

    def __len__(self) -> int:
        return len(self.fixture_id)

    def subset(self, mask: np.ndarray) -> Dataset:
        idx = np.flatnonzero(mask)
        out = {}
        for k, v in self.__dict__.items():
            if k == "kickoff":
                out[k] = [v[i] for i in idx]
            elif k == "team":
                out[k] = {w: a[idx] for w, a in v.items()}
            elif v is None:
                out[k] = None
            else:
                out[k] = v[idx]
        return Dataset(**out)

    @property
    def outcome(self) -> np.ndarray:
        return np.where(self.hg > self.ag, 0, np.where(self.hg == self.ag, 1, 2))

    @property
    def btts(self) -> np.ndarray:
        return ((self.hg > 0) & (self.ag > 0)).astype(int)

    @property
    def over(self) -> np.ndarray:
        return (self.hg + self.ag >= 3).astype(int)

    def matches_played(self, window: str = "season") -> tuple[np.ndarray, np.ndarray]:
        t = self.team[window]
        return t[:, 0] + t[:, 1], t[:, 6] + t[:, 7]

    def progress(self) -> np.ndarray:
        """Season progress: mean matches played by the two teams / games per team."""
        nh, na = self.matches_played()
        games = np.array([GAMES_PER_TEAM[c] for c in self.competition], dtype=float)
        return (nh + na) / 2 / games


def _cat(g: int) -> int:
    return min(g, CATS - 1)


def team_stats(window: list[TeamMatch], weights: Sequence[float] | None = None) -> list[float]:
    """[n_h, n_a, gf_h, ga_h, gf_a, ga_a] (weighted counts when weights are given;
    ``window`` is most recent first, like ``team_window``)."""
    w = weights or [1.0] * len(window)
    s = [0.0] * 6
    for tm, wi in zip(window, w, strict=False):
        if tm.is_home:
            s[0] += wi
            s[2] += wi * tm.goals_for
            s[3] += wi * tm.goals_against
        else:
            s[1] += wi
            s[4] += wi * tm.goals_for
            s[5] += wi * tm.goals_against
    return s


def _league(ms) -> tuple[int, int, int, list[int], list[int], list[int]]:
    n = len(ms)
    hg = sum(m.home_goals for m in ms)
    ag = sum(m.away_goals for m in ms)
    res = [
        sum(m.home_goals > m.away_goals for m in ms),
        sum(m.home_goals == m.away_goals for m in ms),
        sum(m.home_goals < m.away_goals for m in ms),
        sum(m.home_goals > 0 and m.away_goals > 0 for m in ms),
        sum(m.home_goals + m.away_goals >= 3 for m in ms),
    ]
    hh, ha = [0] * (LG_MAX + 1), [0] * (LG_MAX + 1)
    for m in ms:
        hh[min(m.home_goals, LG_MAX)] += 1
        ha[min(m.away_goals, LG_MAX)] += 1
    return n, hg, ag, res, hh, ha


def build_dataset(
    store: MatchStore, competitions: Iterable[int], seasons: Iterable[int]
) -> Dataset:
    comps, yrs = set(competitions), set(seasons)
    cols: dict[str, list] = {
        k: [] for k in (f for f in Dataset.__dataclass_fields__ if f != "team")
    }
    team: dict[str, list] = {w: [] for w in (*WINDOWS, *(f"decay{h}" for h in HALF_LIVES))}
    prev_cache: dict[tuple[int, int], tuple] = {}
    for m in store.matches:
        if not m.stats_eligible or m.competition_id not in comps or m.season not in yrs:
            continue
        comp, yr, k = m.competition_id, m.season, m.kickoff
        cur = _league(store.league_matches(comp, yr, k))
        key = (comp, yr - 1)
        if key not in prev_cache:  # previous season is complete before this one starts
            prev_cache[key] = _league(store.league_matches(comp, yr - 1, k))
        prev = prev_cache[key]
        hw = store.team_window(m.home_id, k, None, 999, competition_id=comp, season=yr)
        aw = store.team_window(m.away_id, k, None, 999, competition_id=comp, season=yr)
        for name, n in (("season", None), ("last8", 8), ("last10", 10)):
            team[name].append(team_stats(hw[:n]) + team_stats(aw[:n]))
        for h in HALF_LIVES:
            wh = [0.5 ** (i / h) for i in range(len(hw))]
            wa = [0.5 ** (i / h) for i in range(len(aw))]
            team[f"decay{h}"].append(team_stats(hw, wh) + team_stats(aw, wa))
        c = np.zeros((4, CATS))
        call = np.zeros((4, CATS))
        for tm in hw:
            call[0, _cat(tm.goals_for)] += 1
            call[1, _cat(tm.goals_against)] += 1
            if tm.is_home:
                c[0, _cat(tm.goals_for)] += 1
                c[1, _cat(tm.goals_against)] += 1
        for tm in aw:
            call[2, _cat(tm.goals_for)] += 1
            call[3, _cat(tm.goals_against)] += 1
            if not tm.is_home:
                c[2, _cat(tm.goals_for)] += 1
                c[3, _cat(tm.goals_against)] += 1
        vals = dict(
            fixture_id=m.fixture_id,
            competition=comp,
            season=yr,
            kickoff=k,
            home_id=m.home_id,
            away_id=m.away_id,
            hg=m.home_goals,
            ag=m.away_goals,
            cur_n=cur[0],
            cur_hg=cur[1],
            cur_ag=cur[2],
            cur_res=cur[3],
            cur_hist_h=cur[4],
            cur_hist_a=cur[5],
            prev_n=prev[0],
            prev_hg=prev[1],
            prev_ag=prev[2],
            prev_res=prev[3],
            prev_hist_h=prev[4],
            prev_hist_a=prev[5],
            cats=c,
            cats_all=call,
        )
        for kk, v in vals.items():
            cols[kk].append(v)
    arr = {k: (v if k == "kickoff" else np.array(v)) for k, v in cols.items()}
    return Dataset(**arr, team={w: np.array(v, dtype=float) for w, v in team.items()})


# =============================================================== league prior
def league_rates(ds: Dataset, m0: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """League home / away goals per match at kickoff and an availability mask.

    Current-season matches plus ``m0`` pseudo-matches at the previous season's
    league average (league level only). Without a stored previous season the
    current season alone is used once it has LEAGUE_MIN matches."""
    has_prev = ds.prev_n > 0
    with np.errstate(invalid="ignore", divide="ignore"):
        ph = np.where(has_prev, ds.prev_hg / np.maximum(ds.prev_n, 1), 0.0)
        pa = np.where(has_prev, ds.prev_ag / np.maximum(ds.prev_n, 1), 0.0)
        w = np.where(has_prev, m0, 0.0)
        H = (ds.cur_hg + w * ph) / (ds.cur_n + w)
        A = (ds.cur_ag + w * pa) / (ds.cur_n + w)
    avail = np.where(has_prev & (m0 > 0), True, ds.cur_n >= LEAGUE_MIN)
    return np.where(avail, H, np.nan), np.where(avail, A, np.nan), avail


def league_frequencies(ds: Dataset, m0: float) -> dict[str, np.ndarray]:
    """League-level baseline: current-season H/D/A, BTTS and Over 2.5 frequencies,
    with the same previous-season pseudo-match blend as ``league_rates``."""
    has_prev = ds.prev_n > 0
    w = np.where(has_prev, m0, 0.0)[:, None]
    prev = np.where(has_prev[:, None], ds.prev_res / np.maximum(ds.prev_n, 1)[:, None], 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        f = (ds.cur_res + w * prev) / (ds.cur_n[:, None] + w)
    _, _, avail = league_rates(ds, m0)
    f[~avail] = np.nan
    return {
        "home": f[:, 0],
        "draw": f[:, 1],
        "away": f[:, 2],
        "btts_yes": f[:, 3],
        "over": f[:, 4],
        "available": avail,
    }


# ============================================================ Poisson lambdas
@dataclass(frozen=True)
class Params:
    window: str = "season"
    k_o: float = 4.0
    k_v: float = INF
    m0: float = 30.0
    k_t: float | None = None  # tempo shrinkage; None = same as k_o (no split)

    def label(self) -> str:
        kv = "inf" if math.isinf(self.k_v) else f"{self.k_v:g}"
        kt = "" if self.k_t is None else f" k_t={self.k_t:g}"
        return f"{self.window} k_o={self.k_o:g}{kt} k_v={kv} m0={self.m0:g}"


def overall_factors(stats: np.ndarray, H, A, k: float) -> tuple[np.ndarray, np.ndarray]:
    """Overall attack and defence factors shrunk with k pseudo-matches."""
    n_h, n_a, gf_h, ga_h, gf_a, ga_a = (stats[:, i] for i in range(6))
    g = (H + A) / 2
    e_for = n_h * H + n_a * A
    e_ag = n_h * A + n_a * H
    with np.errstate(invalid="ignore", divide="ignore"):
        a = (gf_h + gf_a + k * g) / (e_for + k * g)
        d = (ga_h + ga_a + k * g) / (e_ag + k * g)
        if k == 0:  # raw rates: no matches -> league average (factor 1)
            a = np.where(e_for > 0, a, 1.0)
            d = np.where(e_ag > 0, d, 1.0)
    return a, d


def strength_tempo(stats: np.ndarray, H, A, k_s: float, k_t: float):
    """(strength, tempo): s from factors shrunk with k_s, t from factors shrunk with k_t."""
    a, d = overall_factors(stats, H, A, k_s)
    a2, d2 = overall_factors(stats, H, A, k_t)
    return np.sqrt(a / d), np.sqrt(a2 * d2)


def _factors(stats: np.ndarray, H, A, k_o: float, k_v: float, k_t: float | None = None):
    """Attack / defence factors (home and away versions) for one team block of
    ``stats`` columns [n_h, n_a, gf_h, ga_h, gf_a, ga_a]."""
    n_h, n_a, gf_h, ga_h, gf_a, ga_a = (stats[:, i] for i in range(6))
    if k_t is None:
        a, d = overall_factors(stats, H, A, k_o)
    else:
        st, te = strength_tempo(stats, H, A, k_o, k_t)
        a, d = st * te, te / st
    with np.errstate(invalid="ignore", divide="ignore"):
        if math.isinf(k_v):
            return a, d, a, d
        aH = (gf_h + k_v * H * a) / (H * (n_h + k_v))
        dH = (ga_h + k_v * A * d) / (A * (n_h + k_v))
        aA = (gf_a + k_v * A * a) / (A * (n_a + k_v))
        dA = (ga_a + k_v * H * d) / (H * (n_a + k_v))
        if k_v == 0:  # raw venue rates: no venue matches -> overall factor
            aH, dH = np.where(n_h > 0, aH, a), np.where(n_h > 0, dH, d)
            aA, dA = np.where(n_a > 0, aA, a), np.where(n_a > 0, dA, d)
    return aH, dH, aA, dA


def lambdas(ds: Dataset, p: Params) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(lambda_home, lambda_away, available). Unavailable rows are NaN."""
    H, A, avail = league_rates(ds, p.m0)
    t = ds.team[p.window]
    aH, _, _, dH = _factors(t[:, :6], H, A, p.k_o, p.k_v, p.k_t)
    _, _, aA, dA = _factors(t[:, 6:], H, A, p.k_o, p.k_v, p.k_t)
    return H * aH * dA, A * aA * dH, avail


def poisson_score_logprob(lh, la, hg, ag) -> np.ndarray:
    """log P(observed scoreline) under independent Poisson."""
    from scipy.special import gammaln

    out = np.full(len(hg), np.nan)
    ok = np.isfinite(lh) & np.isfinite(la)
    lh, la, hg, ag = lh[ok], la[ok], hg[ok], ag[ok]
    with np.errstate(divide="ignore"):
        lp = (
            hg * np.log(np.maximum(lh, 1e-300))
            - lh
            - gammaln(hg + 1)
            + ag * np.log(np.maximum(la, 1e-300))
            - la
            - gammaln(ag + 1)
        )
    out[ok] = np.maximum(lp, math.log(1e-12))  # zero-probability scorelines: clipped
    return out


# ===================================================== smoothed empirical model
def league_goal_dists(ds: Dataset, m0: float) -> tuple[np.ndarray, np.ndarray]:
    """League home / away goal distributions over 0..10 (same blend as the rates)."""
    has_prev = ds.prev_n > 0
    w = np.where(has_prev, m0, 0.0)[:, None]
    out = []
    for cur, prev in ((ds.cur_hist_h, ds.prev_hist_h), (ds.cur_hist_a, ds.prev_hist_a)):
        pv = np.where(has_prev[:, None], prev / np.maximum(ds.prev_n, 1)[:, None], 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            out.append((cur + w * pv) / (ds.cur_n[:, None] + w))
    return out[0], out[1]


def _to_cats(dist: np.ndarray) -> np.ndarray:
    return np.column_stack([dist[:, 0], dist[:, 1], dist[:, 2], dist[:, 3:].sum(axis=1)])


def _expand_tail(cats: np.ndarray, league: np.ndarray) -> np.ndarray:
    """0, 1, 2, 3+ -> exact goals 0..10: the 3+ mass is split using the league's
    own conditional distribution of 3+ goals for that side (empirical tail)."""
    tail = league[:, 3:]
    tail = tail / np.maximum(tail.sum(axis=1, keepdims=True), 1e-300)
    return np.column_stack([cats[:, :3], cats[:, 3:4] * tail])


def empirical_marginals(
    ds: Dataset, k_o: float, k_v: float, m0: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Smoothed, opponent-adjusted empirical goal distributions (0..10 goals).

    For the home side's goals:
      attack view  = home team's scoring distribution at home, shrunk (k_v) to its
                     scoring distribution in all venues, itself shrunk (k_o) to the
                     league home-goals distribution
      defence view = away team's conceding distribution away, shrunk likewise to
                     its all-venue conceding distribution and the league home-goals
                     distribution
      P(home goals) = (attack view + defence view) / 2
    and symmetrically for the away side (league away-goals distribution)."""
    LH, LA = league_goal_dists(ds, m0)
    _, _, avail = league_rates(ds, m0)
    cH, cA = _to_cats(LH), _to_cats(LA)
    out = []
    for side, league in ((0, cH), (1, cH), (2, cA), (3, cA)):
        venue, allv = ds.cats[:, side, :], ds.cats_all[:, side, :]
        nv, na = venue.sum(axis=1, keepdims=True), allv.sum(axis=1, keepdims=True)
        overall = (allv + k_o * league) / (na + k_o)
        out.append((venue + k_v * overall) / (nv + k_v) if not math.isinf(k_v) else overall)
    home_cats = (out[0] + out[3]) / 2  # home team scoring at home + away team conceding away
    away_cats = (out[2] + out[1]) / 2  # away team scoring away + home team conceding at home
    return _expand_tail(home_cats, LH), _expand_tail(away_cats, LA), avail


# ====================================================================== tuning
def mean_score_logprob(lp: np.ndarray) -> float:
    lp = lp[np.isfinite(lp)]
    return float(lp.mean()) if len(lp) else -INF


def tune_poisson(ds: Dataset, grid: Iterable[Params]) -> tuple[Params, list[dict]]:
    """Pick the parameters with the highest mean log P(observed scoreline) on ``ds``
    (the model's own likelihood: one criterion for all three markets)."""
    table = []
    for p in grid:
        lh, la, _ = lambdas(ds, p)
        table.append(
            {
                "params": p,
                "score_loglik": mean_score_logprob(poisson_score_logprob(lh, la, ds.hg, ds.ag)),
            }
        )
    best = max(table, key=lambda r: r["score_loglik"])
    return best["params"], table


def empirical_score_logprob(ph: np.ndarray, pa: np.ndarray, hg, ag) -> np.ndarray:
    i = np.arange(len(hg))
    with np.errstate(divide="ignore", invalid="ignore"):
        p = ph[i, np.minimum(hg, LG_MAX)] * pa[i, np.minimum(ag, LG_MAX)]
        return np.log(np.clip(p, 1e-12, 1))


def tune_empirical(ds: Dataset, grid: Iterable[tuple[float, float]], m0: float):
    table = []
    for k_o, k_v in grid:
        ph, pa, av = empirical_marginals(ds, k_o, k_v, m0)
        lp = empirical_score_logprob(ph, pa, ds.hg, ds.ag)
        lp[~av] = np.nan
        table.append({"k_o": k_o, "k_v": k_v, "score_loglik": mean_score_logprob(lp)})
    best = max(table, key=lambda r: r["score_loglik"])
    return (best["k_o"], best["k_v"]), table


# ================================================================ explanation
def league_weight(n_matches: float, k_o: float, k_v: float, venue_share: float = 0.5) -> dict:
    """Share of a venue factor that comes from the league average, the team's
    overall record and its venue record after ``n_matches`` (half at the venue)."""
    n_v = n_matches * venue_share
    w_v = n_v / (n_v + k_v) if not math.isinf(k_v) else 0.0
    w_o = n_matches / (n_matches + k_o) if k_o > 0 else (1.0 if n_matches else 0.0)
    return {
        "matches": n_matches,
        "venue_record": w_v,
        "overall_record": (1 - w_v) * w_o,
        "league_average": (1 - w_v) * (1 - w_o),
    }
