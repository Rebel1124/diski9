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

from diski9.screener.calc import diski_form_score
from diski9.screener.engine import MatchStore, ScreenerConfig, TeamMatch, form_benchmark

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
    fs = diski_form_score((t.goals_for, t.goals_against) for t in window)
    return None if fs is None else float(fs.score)


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
        hv = store.team_window(m.home_id, k, "home", config.form_window)
        ho = store.team_window(m.home_id, k, None, config.form_window)
        av = store.team_window(m.away_id, k, "away", config.form_window)
        ao = store.team_window(m.away_id, k, None, config.form_window)
        scores = [_score(w) for w in (hv, ho, av, ao)]
        if any(s is None for s in scores):
            skipped["no_score"] += 1
            continue
        bv = form_benchmark(store, m.competition_id, m.season, k, "venue", config)
        bo = form_benchmark(store, m.competition_id, m.season, k, "overall", config)
        if not (bv["available"] and bo["available"]):
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
                bv["home"]["average"],
                bv["away"]["average"],
                bo["overall"]["average"],
                len(ids(hv) & ids(ho)),
                len(ids(av) & ids(ao)),
            )
        )
    return rows, skipped
