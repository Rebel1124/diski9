"""Research only: venue-specific vs overall vs blended Diski Form Score (Model D).

Nothing here is used by the Screener. For every eligible completed league fixture
it records, as known at kickoff (cutoff = kickoff, production windows):

* the home team's venue (home-window) and overall Model D scores
* the away team's venue (away-window) and overall Model D scores
* the production league benchmarks: home-form, away-form and overall averages

A blend with venue weight ``w`` is ``w x venue + (1 - w) x overall`` for the team
score and, with the same weight, for its benchmark (home side: home-form average;
away side: away-form average; both blended with the overall average).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from diski9.screener.engine import MatchStore, ScreenerConfig, TeamMatch

WEIGHTS = {"venue": 1.0, "blend_75v": 0.75, "blend_50": 0.5, "blend_25v": 0.25, "overall": 0.0}


@dataclass
class BlendRow:
    fixture_id: int
    competition_id: int
    season: int
    kickoff: datetime
    outcome: int  # 0 home win, 1 draw, 2 away win
    home_venue: float
    home_overall: float
    away_venue: float
    away_overall: float
    n_home_venue: int
    n_home_overall: int
    n_away_venue: int
    n_away_overall: int
    bench_home: float  # league home-form average
    bench_away: float  # league away-form average
    bench_overall: float
    shared_home: int  # matches in both the home team's venue and overall windows
    shared_away: int

    def home(self, w: float) -> float:
        return w * self.home_venue + (1 - w) * self.home_overall

    def away(self, w: float) -> float:
        return w * self.away_venue + (1 - w) * self.away_overall

    def diff(self, w: float) -> float:
        return self.home(w) - self.away(w)

    def rel_home(self, w: float) -> float:
        """Home team's score minus its (equally weighted) league benchmark."""
        return self.home(w) - (w * self.bench_home + (1 - w) * self.bench_overall)

    def rel_away(self, w: float) -> float:
        return self.away(w) - (w * self.bench_away + (1 - w) * self.bench_overall)

    @property
    def complete(self) -> bool:
        return (
            min(self.n_home_venue, self.n_home_overall, self.n_away_venue, self.n_away_overall) == 5
        )


def _score(window: list[TeamMatch]) -> float | None:
    """Milestone 5.3 Model D on a five-match window (partial windows over the fixed
    five-match denominator), independent of later production changes."""
    s = score_n([(t.goals_for, t.goals_against) for t in window], 5)
    return None if s is None else float(s)


def build_rows(
    store: MatchStore,
    competitions: Iterable[int],
    seasons: Iterable[int],
    config: ScreenerConfig | None = None,
) -> tuple[list[BlendRow], dict[str, int]]:
    """Rows where all four scores and all three benchmarks exist; plus exclusion counts."""
    config = config or ScreenerConfig()
    comps, yrs = set(competitions), set(seasons)
    rows: list[BlendRow] = []
    skipped = {"no_score": 0, "no_benchmark": 0}
    for m in store.matches:
        if not m.stats_eligible or m.competition_id not in comps or m.season not in yrs:
            continue
        k = m.kickoff
        hv = store.team_window(m.home_id, k, "home", 5)  # research window: five matches
        ho = store.team_window(m.home_id, k, None, 5)  # research window: five matches
        av = store.team_window(m.away_id, k, "away", 5)  # research window: five matches
        ao = store.team_window(m.away_id, k, None, 5)  # research window: five matches
        scores = [_score(w) for w in (hv, ho, av, ao)]
        if any(s is None for s in scores):
            skipped["no_score"] += 1
            continue
        b_home = window_benchmark(store, m.competition_id, m.season, k, "home", 5, config)
        b_away = window_benchmark(store, m.competition_id, m.season, k, "away", 5, config)
        b_all = window_benchmark(store, m.competition_id, m.season, k, None, 5, config)
        if b_home is None or b_away is None or b_all is None:
            skipped["no_benchmark"] += 1
            continue
        outcome = 0 if m.home_goals > m.away_goals else 1 if m.home_goals == m.away_goals else 2
        ids = lambda w: {t.match.fixture_id for t in w}  # noqa: E731
        rows.append(
            BlendRow(
                m.fixture_id,
                m.competition_id,
                m.season,
                k,
                outcome,
                scores[0],
                scores[1],
                scores[2],
                scores[3],
                len(hv),
                len(ho),
                len(av),
                len(ao),
                b_home,
                b_away,
                b_all,
                len(ids(hv) & ids(ho)),
                len(ids(av) & ids(ao)),
            )
        )
    return rows, skipped


# ------------------------------------------------- longer overall windows (research)
GD_PER_MATCH = Fraction(9, 5)  # production cap: +/-9 over five matches = 1.8 per match


def score_n(results: list[tuple[int, int]], n: int) -> Fraction | None:
    """Model D generalised to an n-match window, on the same 0-5 scale:

        points part = 2.5 x P / (3n)
        GD part     = 2.5 x (clip(GD, -c, c) + c) / (2c),  c = 1.8 n

    i.e. the production per-match scale (+/-9 over five matches). With n = 5 this is
    exactly the production Diski Form Score. Partial windows use actual totals over
    the n-match denominator (no prorating), as in production. None if no matches."""
    if not results:
        return None
    pts = sum(3 if f > a else 1 if f == a else 0 for f, a in results)
    gd = sum(f - a for f, a in results)
    c = GD_PER_MATCH * n
    capped = max(-c, min(c, Fraction(gd)))
    half = Fraction(5, 2)
    return half * Fraction(pts, 3 * n) + half * (capped + c) / (2 * c)


def window_benchmark(
    store: MatchStore,
    competition_id: int,
    season: int,
    cutoff: datetime,
    venue: str | None,
    n: int,
    config: ScreenerConfig,
) -> float | None:
    """League average of ``score_n`` over point-in-time league members with a full
    n-match window (same population and availability rule as production)."""
    from diski9.screener.engine import league_members

    members = league_members(store, competition_id, season, cutoff)
    scores = []
    for team in sorted(members):
        w = store.team_window(team, cutoff, venue, n)
        if len(w) == n:
            scores.append(score_n([(t.goals_for, t.goals_against) for t in w], n))
    k = len(scores)
    if not members or k < config.form_benchmark_min_teams:
        return None
    if k / len(members) < config.form_benchmark_min_share:
        return None
    return float(sum(scores, Fraction(0)) / k)


APPROACHES = ("venue", "overall5", "blend50", "overall7", "overall8", "overall10")


@dataclass
class WindowRow:
    fixture_id: int
    competition_id: int
    season: int
    kickoff: datetime
    outcome: int
    # approach -> (home score, away score, home benchmark, away benchmark)
    values: dict[str, tuple[float, float, float, float]]
    min_window: dict[str, int]  # approach-relevant smallest window length of the two teams
    disagree_home: bool  # venue vs overall-5 indicators disagree for the home team
    disagree_away: bool

    def diff(self, a: str) -> float:
        h, aw, _, _ = self.values[a]
        return h - aw

    def rel(self, a: str) -> tuple[float, float]:
        h, aw, bh, ba = self.values[a]
        return h - bh, aw - ba


def build_window_rows(
    store: MatchStore,
    competitions: Iterable[int],
    seasons: Iterable[int],
    config: ScreenerConfig | None = None,
) -> tuple[list[WindowRow], dict[str, int]]:
    """Identical fixture set: rows only where every approach has both scores and both
    benchmarks (point in time, cutoff = kickoff)."""
    config = config or ScreenerConfig()
    comps, yrs = set(competitions), set(seasons)
    rows: list[WindowRow] = []
    skipped = {"no_score": 0, "no_benchmark": 0}
    for m in store.matches:
        if not m.stats_eligible or m.competition_id not in comps or m.season not in yrs:
            continue
        k, comp, yr = m.kickoff, m.competition_id, m.season

        def pairs(team, venue, n, k=k):
            return [(t.goals_for, t.goals_against) for t in store.team_window(team, k, venue, n)]

        win = {
            "venue": (pairs(m.home_id, "home", 5), pairs(m.away_id, "away", 5), 5),
            **{
                f"overall{n}": (pairs(m.home_id, None, n), pairs(m.away_id, None, n), n)
                for n in (5, 7, 8, 10)
            },
        }
        sc = {a: (score_n(h, n), score_n(aw, n)) for a, (h, aw, n) in win.items()}
        if any(s is None for pair in sc.values() for s in pair):
            skipped["no_score"] += 1
            continue
        bench = {
            "venue": (
                window_benchmark(store, comp, yr, k, "home", 5, config),
                window_benchmark(store, comp, yr, k, "away", 5, config),
            ),
            **{
                f"overall{n}": (window_benchmark(store, comp, yr, k, None, n, config),) * 2
                for n in (5, 7, 8, 10)
            },
        }
        if any(b is None for pair in bench.values() for b in pair):
            skipped["no_benchmark"] += 1
            continue
        values = {a: (float(sc[a][0]), float(sc[a][1]), bench[a][0], bench[a][1]) for a in win}
        v, o = values["venue"], values["overall5"]
        values["blend50"] = tuple(0.5 * x + 0.5 * y for x, y in zip(v, o, strict=True))
        min_window = {a: min(len(h), len(aw)) for a, (h, aw, _) in win.items()}
        min_window["blend50"] = min(min_window["venue"], min_window["overall5"])
        outcome = 0 if m.home_goals > m.away_goals else 1 if m.home_goals == m.away_goals else 2
        rows.append(
            WindowRow(
                m.fixture_id,
                comp,
                yr,
                k,
                outcome,
                values,
                min_window,
                (v[0] > v[2]) != (o[0] > o[2]),
                (v[1] > v[3]) != (o[1] > o[3]),
            )
        )
    return rows, skipped
