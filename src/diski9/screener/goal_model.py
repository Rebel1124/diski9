"""Goal Model 1.1: estimated goals and market probabilities (Engine 3.1).

Goal Model 1.1 is the approved Phase 8 "C1-2-20" model (owner decisions CP1-1/CP1-2
and OD-1, 27 Nov 2026; evidence ``docs/research/phase8_cp1/``). It keeps the Goal
Model 1.0 strength / tempo shrinkage (``k_s`` 12, ``k_t`` 96) and removes every
previous-season input: the competition averages come from the current season alone.
Tests check agreement with the accepted research reference
(``scripts/research_phase8_cp1.py``, candidate C1-2-20) to 1e-12.

Inputs: completed, statistically eligible league matches of the current season
and competition that kicked off before the cutoff. No bookmaker data, no
earlier-season team or competition results.

Availability: both teams have at least ``TEAM_MIN`` (2) such matches and the
competition has at least ``COMPETITION_MIN`` (20). Otherwise nothing is estimated
and nothing is substituted. Below ``EARLY_SEASON_MATCHES`` (5) for either team the
estimate carries the limited-data warning.

    H, A = current-season competition home / away goals per match
    g    = (H + A) / 2
    E_for = n_h H + n_a A ;  E_ag = n_h A + n_a H         (venue-normalised)
    attack(k)  = (goals scored   + k g) / (E_for + k g)
    defence(k) = (goals conceded + k g) / (E_ag  + k g)
    strength s = sqrt(attack(k_s) / defence(k_s))
    tempo    t = sqrt(attack(k_t) x defence(k_t))
    lambda_home = H x (s_home / s_away) x t_home x t_away
    lambda_away = A x (s_away / s_home) x t_home x t_away

Goals are independent Poisson; every market probability is an exact sum over the
scoreline grid, whose truncated tail is below 1e-15.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

GOAL_MODEL_VERSION = "1.1"
UEFA_COMPETITIONS = frozenset({2, 3})  # Champions League, Europa League: never modelled
UEFA_MESSAGE = "Diski 9 model probabilities are not yet available for European competitions."
TEAM_MIN = 2  # eligible current-season matches each team needs
COMPETITION_MIN = 20  # eligible current-season competition matches needed
EARLY_SEASON_MATCHES = 5  # below this (either team) the limited-data warning is shown
LIMITED_DATA_WARNING = (
    "Limited current-season data. These estimates are based on a small number of matches "
    "and may be more volatile than usual. Consider additional team news and qualitative "
    "factors when forming your view."
)


@dataclass(frozen=True)
class GoalModelParams:
    """Frozen for Goal Model 1.1. Never change these in place: a new parameter set
    is a new model version with its own evidence report."""

    k_s: float = 12.0  # team strength smoothing (pseudo-matches)
    k_t: float = 96.0  # goal tempo smoothing (pseudo-matches)
    team_min: int = TEAM_MIN
    competition_min: int = COMPETITION_MIN


@dataclass(frozen=True)
class GoalModel10Params:
    """Goal Model 1.0 (Nov 2026 - Phase 8), kept only so that stored 1.0 forecasts,
    cache rows and round snapshots stay identifiable and reproducible
    (``params_hash(PARAMS_1_0)`` is the stored 1.0 hash). Not used for new estimates."""

    k_s: float = 12.0
    k_t: float = 96.0
    m0: float = 30.0  # previous-season league-average prior (pseudo-matches)


PARAMS = GoalModelParams()
PARAMS_1_0 = GoalModel10Params()
LEAGUE_MIN_1_0 = 30  # Goal Model 1.0: current-season matches needed without a previous season
MODEL_INFO = {
    "goal_model_version": GOAL_MODEL_VERSION,
    "parameters": asdict(PARAMS),
    "method": "current-season independent Poisson, strength/tempo shrinkage",
    "calibrated_on": "EPL, Championship, PSL, PSL 1st Division (2023/24-2025/26)",
    "validated_on": "Phase 8 CP1: eight domestic leagues, confirmation 2025/26-2026/27",
}


def params_hash(p: GoalModelParams | GoalModel10Params = PARAMS) -> str:
    return hashlib.sha256(json.dumps(asdict(p), sort_keys=True).encode()).hexdigest()[:16]


# ===================================================================== markets
def goal_grid(max_lambda: float) -> int:
    """Number of goal values 0..G-1 so that the Poisson tail beyond is < 1e-15."""
    lam = max(float(max_lambda), 0.0)
    return int(math.ceil(lam + 12 * math.sqrt(lam) + 26))


def poisson_pmf(lam: float, size: int) -> list[float]:
    if lam <= 0:
        return [1.0] + [0.0] * (size - 1)
    log_lam = math.log(lam)
    return [math.exp(k * log_lam - lam - math.lgamma(k + 1)) for k in range(size)]


def markets(lambda_home: float, lambda_away: float) -> dict[str, float]:
    """All seven market probabilities from one pair of estimated goals.

    Each market sums to exactly 1 (complements are 1 - the rest). Raises
    ValueError for negative or non-finite inputs."""
    for v in (lambda_home, lambda_away):
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"estimated goals must be finite and >= 0, got {v!r}")
    G = goal_grid(max(lambda_home, lambda_away))
    ph, pa = poisson_pmf(lambda_home, G), poisson_pmf(lambda_away, G)
    home = draw = 0.0
    home_gt = sum(ph)  # P(home > j), updated as j increases
    for j in range(G):
        home_gt -= ph[j]
        home += pa[j] * max(home_gt, 0.0)
        draw += pa[j] * ph[j]
    btts_yes = (1.0 - ph[0]) * (1.0 - pa[0])
    under = ph[0] * (pa[0] + pa[1] + pa[2]) + ph[1] * (pa[0] + pa[1]) + ph[2] * pa[0]
    return {
        "home": home,
        "draw": draw,
        "away": 1.0 - home - draw,
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
        "over": 1.0 - under,
        "under": under,
    }


def goal_distribution(lam: float, upto: int = 6) -> list[float]:
    """P(0), ..., P(upto - 1) and P(upto or more) for display."""
    p = poisson_pmf(lam, upto)
    return [*p, max(0.0, 1.0 - sum(p))]


# =============================================================== statistics
@dataclass(frozen=True)
class TeamRecord:
    """Current-season league record before the cutoff."""

    home_played: int = 0
    away_played: int = 0
    home_scored: int = 0
    home_conceded: int = 0
    away_scored: int = 0
    away_conceded: int = 0

    @property
    def played(self) -> int:
        return self.home_played + self.away_played

    @property
    def scored(self) -> int:
        return self.home_scored + self.away_scored

    @property
    def conceded(self) -> int:
        return self.home_conceded + self.away_conceded

    @classmethod
    def of(cls, window) -> TeamRecord:
        """From ``TeamMatch`` objects (``MatchStore.team_window``)."""
        h = [t for t in window if t.is_home]
        a = [t for t in window if not t.is_home]
        return cls(
            len(h),
            len(a),
            sum(t.goals_for for t in h),
            sum(t.goals_against for t in h),
            sum(t.goals_for for t in a),
            sum(t.goals_against for t in a),
        )


@dataclass(frozen=True)
class LeagueRates:
    home: float  # H: home goals per match
    away: float  # A: away goals per match
    current_matches: int
    current_home_goals: int
    current_away_goals: int


def league_rates(current: list, minimum: int = COMPETITION_MIN) -> LeagueRates | None:
    """Goal Model 1.1 H and A from the current season's ``Match`` list alone. None
    when the competition has fewer than ``minimum`` matches (or no goals at all)."""
    n, hg = len(current), sum(m.home_goals for m in current)
    ag = sum(m.away_goals for m in current)
    if n < max(minimum, 1) or hg + ag == 0:
        return None
    return LeagueRates(hg / n, ag / n, n, hg, ag)


def league_frequencies(current: list, minimum: int = COMPETITION_MIN) -> dict | None:
    """Current-season competition baseline used in monitoring: home win / draw / away
    win, BTTS and Over 2.5 frequencies. None below ``minimum`` matches."""
    n = len(current)
    if n < max(minimum, 1):
        return None
    f = [
        sum(m.home_goals > m.away_goals for m in current) / n,
        sum(m.home_goals == m.away_goals for m in current) / n,
        sum(m.home_goals < m.away_goals for m in current) / n,
        sum(m.home_goals > 0 and m.away_goals > 0 for m in current) / n,
        sum(m.home_goals + m.away_goals >= 3 for m in current) / n,
    ]
    return {"home": f[0], "draw": f[1], "away": f[2], "btts_yes": f[3], "over": f[4]}


def league_rates_1_0(current: list, previous: list, m0: float = PARAMS_1_0.m0):
    """Goal Model 1.0 competition rates (previous-season prior), for reproducing stored
    1.0 records only. Returns (H, A) or None."""
    n, hg = len(current), sum(m.home_goals for m in current)
    ag = sum(m.away_goals for m in current)
    if previous:
        pn = len(previous)
        ph = sum(m.home_goals for m in previous) / pn
        pa = sum(m.away_goals for m in previous) / pn
        return (hg + m0 * ph) / (n + m0), (ag + m0 * pa) / (n + m0)
    if n >= LEAGUE_MIN_1_0:
        return hg / n, ag / n
    return None


def factors(rec: TeamRecord, H: float, A: float, k: float) -> tuple[float, float]:
    """Venue-normalised attack and defence shrunk with k pseudo-matches."""
    g = (H + A) / 2
    e_for = rec.home_played * H + rec.away_played * A
    e_ag = rec.home_played * A + rec.away_played * H
    return (rec.scored + k * g) / (e_for + k * g), (rec.conceded + k * g) / (e_ag + k * g)


def strength_tempo(rec: TeamRecord, H: float, A: float, p=PARAMS):
    a_s, d_s = factors(rec, H, A, p.k_s)
    a_t, d_t = factors(rec, H, A, p.k_t)
    return math.sqrt(a_s / d_s), math.sqrt(a_t * d_t), (a_s, d_s, a_t, d_t)


def estimate(home: TeamRecord, away: TeamRecord, league, p=PARAMS) -> dict[str, Any]:
    """Estimated goals, probabilities and the intermediate values for one fixture.
    ``league`` is a ``LeagueRates`` or an ``(H, A)`` pair (Goal Model 1.0 replay)."""
    H, A = (league.home, league.away) if isinstance(league, LeagueRates) else league
    s_h, t_h, f_h = strength_tempo(home, H, A, p)
    s_a, t_a, f_a = strength_tempo(away, H, A, p)
    lh = H * (s_h / s_a) * t_h * t_a
    la = A * (s_a / s_h) * t_h * t_a
    probs = markets(lh, la)

    def team(rec, s, t, f):
        return {
            "record": asdict(rec),
            "played": rec.played,
            "attack_strength_k_s": f[0],
            "defence_strength_k_s": f[1],
            "attack_tempo_k_t": f[2],
            "defence_tempo_k_t": f[3],
            "strength": s,
            "tempo": t,
        }

    return {
        "lambda_home": lh,
        "lambda_away": la,
        "probabilities": probs,
        "home_team": team(home, s_h, t_h, f_h),
        "away_team": team(away, s_a, t_a, f_a),
    }


def fixture_estimate(
    store, competition_id: int, season: int, home_id: int, away_id: int, cutoff: datetime
) -> dict[str, Any]:
    """Goal Model 1.1 block for the Engine 3.1 payload (always JSON-serialisable).

    ``available`` is False, with a ``reason`` and ``message``, for European
    competitions, below ``COMPETITION_MIN`` competition matches and below
    ``TEAM_MIN`` matches for either team; nothing is substituted."""
    base = {"model": MODEL_INFO, "params_hash": params_hash()}
    if competition_id in UEFA_COMPETITIONS:
        return {
            **base,
            "available": False,
            "reason": "european_competition",
            "message": UEFA_MESSAGE,
        }
    current = store.league_matches(competition_id, season, cutoff)
    league = league_rates(current)
    if league is None:
        return {
            **base,
            "available": False,
            "reason": "competition_matches_insufficient",
            "message": f"Not enough current-season data yet: {len(current)} of "
            f"{COMPETITION_MIN} competition matches have been played.",
        }
    recs = {}
    for side, team_id in (("home", home_id), ("away", away_id)):
        w = store.team_window(
            team_id, cutoff, None, 10_000, competition_id=competition_id, season=season
        )
        recs[side] = TeamRecord.of(w)
    played = (recs["home"].played, recs["away"].played)
    if min(played) < TEAM_MIN:
        return {
            **base,
            "available": False,
            "reason": "team_matches_insufficient",
            "message": f"Not enough current-season data yet: each team needs at least "
            f"{TEAM_MIN} league matches (home {played[0]}, away {played[1]}).",
            "team_matches": {"home": played[0], "away": played[1]},
        }
    est = estimate(recs["home"], recs["away"], league)
    return {
        **base,
        "available": True,
        "league": asdict(league),
        "league_baseline": league_frequencies(current),
        **est,
        "estimated_goals": {"home": est["lambda_home"], "away": est["lambda_away"]},
        "early_season": min(played) < EARLY_SEASON_MATCHES,
    }
