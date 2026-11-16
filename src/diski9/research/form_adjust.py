"""Research only: overall window length (5-8) and venue adjustments to the Form Score.

Nothing here is used by the Screener. For every eligible completed league fixture,
as known at kickoff (production windows, cutoff = kickoff):

* overall Model D scores for 5, 6, 7 and 8-match windows (``score_n``, same 0-5
  scale, goal-difference cap 1.8 per match) for both teams
* the production venue score (last five home matches for the home team, last five
  away matches for the away team)
* point-in-time league benchmarks for every window (None when not yet available)
* window provenance: whether a window reaches an earlier season or another division

Venue adjustments for base window n (applied to the home team with its home form
and to the away team with its away form):

* raw:            venue - overall_n
* league-relative: (venue - league venue average) - (overall_n - league overall_n average)

A weighted adjustment w changes the team comparison to overall_n + w x adjustment.
For the match-level Form Difference this is identical whether it is applied to each
team or to the difference: (h + w a_h) - (a + w a_a) = (h - a) + w (a_h - a_a).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from diski9.research.form_blend import score_n, window_benchmark
from diski9.screener.engine import MatchStore, ScreenerConfig

WINDOWS = (5, 6, 7, 8)
ADJUST_WEIGHTS = (0.0, 0.25, 0.5)  # predeclared


@dataclass
class AdjustRow:
    fixture_id: int
    competition_id: int
    season: int
    kickoff: datetime
    home_id: int
    away_id: int
    outcome: int
    days_into_season: float
    venue: tuple[float, float]  # home team home form, away team away form
    overall: dict[int, tuple[float, float]]  # n -> (home team, away team)
    bench_venue: tuple[float | None, float | None]  # league home / away averages
    bench_overall: dict[int, float | None]
    window_len: dict[str, tuple[int, int]]  # "venue" / "o5".. -> lengths for both teams
    reaches_back: dict[int, tuple[bool, bool]]  # n -> window has earlier-season/other-division
    oldest_days: dict[int, tuple[float, float]]  # n -> age of oldest match in window
    extra: dict = field(default_factory=dict)

    # ----------------------------------------------------------- features
    def diff(self, n: int) -> float:
        h, a = self.overall[n]
        return h - a

    def adjustment(self, n: int, kind: str) -> tuple[float, float] | None:
        """Venue adjustment for the home and away team; None when a benchmark needed
        for the league-relative version is unavailable."""
        (oh, oa), (vh, va) = self.overall[n], self.venue
        if kind == "raw":
            return vh - oh, va - oa
        bo, (bh, ba) = self.bench_overall[n], self.bench_venue
        if bo is None or bh is None or ba is None:
            return None
        return (vh - bh) - (oh - bo), (va - ba) - (oa - bo)

    def adjusted_diff(self, n: int, kind: str, w: float) -> float | None:
        adj = self.adjustment(n, kind)
        if adj is None:
            return None
        return self.diff(n) + w * (adj[0] - adj[1])

    @property
    def benchmarks_available(self) -> bool:
        return all(v is not None for v in (*self.bench_venue, *self.bench_overall.values()))

    @property
    def complete(self) -> bool:
        return min(min(v) for k, v in self.window_len.items() if k in ("venue", "o5")) == 5


def season_starts(store: MatchStore) -> dict[tuple[int, int], datetime]:
    out: dict[tuple[int, int], datetime] = {}
    for (comp, season), ms in store.by_comp_season.items():
        if ms:
            out[(comp, season)] = min(m.kickoff for m in ms)
    return out


def build_rows(
    store: MatchStore,
    competitions: Iterable[int],
    seasons: Iterable[int],
    config: ScreenerConfig | None = None,
) -> tuple[list[AdjustRow], dict[str, int]]:
    """All fixtures with every score (benchmarks may be None; use
    ``benchmarks_available`` for the identical benchmarked sample)."""
    config = config or ScreenerConfig()
    comps, yrs = set(competitions), set(seasons)
    starts = season_starts(store)
    rows: list[AdjustRow] = []
    skipped = {"no_score": 0}
    for m in store.matches:
        if not m.stats_eligible or m.competition_id not in comps or m.season not in yrs:
            continue
        k, comp, yr = m.kickoff, m.competition_id, m.season
        wins = {}
        for n in WINDOWS:
            wins[n] = (
                store.team_window(m.home_id, k, None, n),
                store.team_window(m.away_id, k, None, n),
            )
        vh = store.team_window(m.home_id, k, "home", 5)
        va = store.team_window(m.away_id, k, "away", 5)

        def pairs(w):
            return [(t.goals_for, t.goals_against) for t in w]

        overall = {n: (score_n(pairs(h), n), score_n(pairs(a), n)) for n, (h, a) in wins.items()}
        venue = (score_n(pairs(vh), 5), score_n(pairs(va), 5))
        if any(s is None for pair in (*overall.values(), venue) for s in pair):
            skipped["no_score"] += 1
            continue

        def back(w, comp=comp, yr=yr):
            return any(t.match.season != yr or t.match.competition_id != comp for t in w)

        def age(w, k=k):
            return (k - w[-1].match.kickoff).total_seconds() / 86400 if w else 0.0

        outcome = 0 if m.home_goals > m.away_goals else 1 if m.home_goals == m.away_goals else 2
        rows.append(
            AdjustRow(
                m.fixture_id,
                comp,
                yr,
                k,
                m.home_id,
                m.away_id,
                outcome,
                (k - starts[(comp, yr)]).total_seconds() / 86400,
                (float(venue[0]), float(venue[1])),
                {n: (float(h), float(a)) for n, (h, a) in overall.items()},
                (
                    window_benchmark(store, comp, yr, k, "home", 5, config),
                    window_benchmark(store, comp, yr, k, "away", 5, config),
                ),
                {n: window_benchmark(store, comp, yr, k, None, n, config) for n in WINDOWS},
                {"venue": (len(vh), len(va))}
                | {f"o{n}": (len(h), len(a)) for n, (h, a) in wins.items()},
                {n: (back(h), back(a)) for n, (h, a) in wins.items()},
                {n: (age(h), age(a)) for n, (h, a) in wins.items()},
            )
        )
    return rows, skipped
