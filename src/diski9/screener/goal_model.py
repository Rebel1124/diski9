"""Goal Model 1.0: estimated goals and market probabilities (Engine 3.0).

The production version of the validated research model
(``docs/goal_distribution_research.md``, cross-league validation in
``docs/goal_model_crossleague_validation.md``). The formulas are those of
``diski9.research.goal_distribution`` (season-to-date window, no venue-specific
team factors, strength / tempo shrinkage); tests check agreement to 1e-12.

Inputs: completed, statistically eligible league matches of the current season
and competition that kicked off before the cutoff, plus the previous season's
league-level averages. No bookmaker data, no earlier-season team results.

    H, A = league home / away goals per match:
           (current-season goals + m0 x previous-season goals per match)
           / (current-season matches + m0)
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

GOAL_MODEL_VERSION = "1.0"
UEFA_COMPETITIONS = frozenset({2, 3})  # Champions League, Europa League: never modelled
UEFA_MESSAGE = "Diski 9 model probabilities are not yet available for European competitions."
LEAGUE_MIN = 30  # current-season matches needed when no previous season is stored
EARLY_SEASON_MATCHES = 5  # below this (either team) the estimate is flagged "early season"


@dataclass(frozen=True)
class GoalModelParams:
    """Frozen for Goal Model 1.0. Never change these in place: a new parameter set
    is a new model version with its own evidence report."""

    k_s: float = 12.0  # team strength smoothing (pseudo-matches)
    k_t: float = 96.0  # goal tempo smoothing (pseudo-matches)
    m0: float = 30.0  # previous-season league-average prior (pseudo-matches)


PARAMS = GoalModelParams()
MODEL_INFO = {
    "goal_model_version": GOAL_MODEL_VERSION,
    "parameters": asdict(PARAMS),
    "method": "season-to-date independent Poisson, strength/tempo shrinkage",
    "calibrated_on": "EPL, Championship, PSL, PSL 1st Division (2023/24-2025/26)",
    "validated_on": "La Liga, Ligue 1, Bundesliga, Serie A (2023/24-2026/27, 4,515 fixtures)",
}


def params_hash(p: GoalModelParams = PARAMS) -> str:
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
    previous_matches: int
    previous_home_per_match: float | None
    previous_away_per_match: float | None
    source: str  # "current+previous" | "current only"


def league_rates(current: list, previous: list, m0: float = PARAMS.m0) -> LeagueRates | None:
    """H and A from ``Match`` lists (current season before cutoff; previous season).
    None when no previous season is stored and fewer than LEAGUE_MIN current matches."""
    n, hg = len(current), sum(m.home_goals for m in current)
    ag = sum(m.away_goals for m in current)
    if previous:
        pn = len(previous)
        ph = sum(m.home_goals for m in previous) / pn
        pa = sum(m.away_goals for m in previous) / pn
        return LeagueRates(
            (hg + m0 * ph) / (n + m0),
            (ag + m0 * pa) / (n + m0),
            n,
            hg,
            ag,
            pn,
            ph,
            pa,
            "current+previous",
        )
    if n >= LEAGUE_MIN:
        return LeagueRates(hg / n, ag / n, n, hg, ag, 0, None, None, "current only")
    return None


def league_frequencies(current: list, previous: list, m0: float = PARAMS.m0) -> dict | None:
    """League baseline used in monitoring: home win / draw / away win, BTTS and Over
    2.5 frequencies with the same previous-season pseudo-match blend."""

    def counts(ms):
        return [
            sum(m.home_goals > m.away_goals for m in ms),
            sum(m.home_goals == m.away_goals for m in ms),
            sum(m.home_goals < m.away_goals for m in ms),
            sum(m.home_goals > 0 and m.away_goals > 0 for m in ms),
            sum(m.home_goals + m.away_goals >= 3 for m in ms),
        ]

    n = len(current)
    cur = counts(current)
    if previous:
        prev = [c / len(previous) for c in counts(previous)]
        f = [(c + m0 * p) / (n + m0) for c, p in zip(cur, prev, strict=True)]
    elif n >= LEAGUE_MIN:
        f = [c / n for c in cur]
    else:
        return None
    return {"home": f[0], "draw": f[1], "away": f[2], "btts_yes": f[3], "over": f[4]}


def factors(rec: TeamRecord, H: float, A: float, k: float) -> tuple[float, float]:
    """Venue-normalised attack and defence shrunk with k pseudo-matches."""
    g = (H + A) / 2
    e_for = rec.home_played * H + rec.away_played * A
    e_ag = rec.home_played * A + rec.away_played * H
    return (rec.scored + k * g) / (e_for + k * g), (rec.conceded + k * g) / (e_ag + k * g)


def strength_tempo(rec: TeamRecord, H: float, A: float, p: GoalModelParams = PARAMS):
    a_s, d_s = factors(rec, H, A, p.k_s)
    a_t, d_t = factors(rec, H, A, p.k_t)
    return math.sqrt(a_s / d_s), math.sqrt(a_t * d_t), (a_s, d_s, a_t, d_t)


def estimate(
    home: TeamRecord, away: TeamRecord, league: LeagueRates, p: GoalModelParams = PARAMS
) -> dict[str, Any]:
    """Estimated goals, probabilities and the intermediate values for one fixture."""
    H, A = league.home, league.away
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
    """Goal Model 1.0 block for the Engine 3.0 payload (always JSON-serialisable).

    ``available`` is False, with a ``reason`` and ``message``, for European
    competitions and when no league prior exists; nothing is substituted."""
    base = {"model": MODEL_INFO, "params_hash": params_hash()}
    if competition_id in UEFA_COMPETITIONS:
        return {
            **base,
            "available": False,
            "reason": "european_competition",
            "message": UEFA_MESSAGE,
        }
    current = store.league_matches(competition_id, season, cutoff)
    previous = store.league_matches(competition_id, season - 1, cutoff)
    league = league_rates(current, previous)
    if league is None:
        return {
            **base,
            "available": False,
            "reason": "league_prior_unavailable",
            "message": f"Not enough league data yet: no previous season is stored and only "
            f"{len(current)} of {LEAGUE_MIN} current-season league matches have been played.",
        }
    recs = {}
    for side, team_id in (("home", home_id), ("away", away_id)):
        w = store.team_window(
            team_id, cutoff, None, 10_000, competition_id=competition_id, season=season
        )
        recs[side] = TeamRecord.of(w)
    est = estimate(recs["home"], recs["away"], league)
    played = (recs["home"].played, recs["away"].played)
    return {
        **base,
        "available": True,
        "league": asdict(league),
        "league_baseline": league_frequencies(current, previous),
        **est,
        "estimated_goals": {"home": est["lambda_home"], "away": est["lambda_away"]},
        "league_average_only": [
            side for side, n in zip(("home", "away"), played, strict=True) if n == 0
        ],
        "early_season": min(played) < EARLY_SEASON_MATCHES,
        "data_cutoff": cutoff.isoformat(),
    }
