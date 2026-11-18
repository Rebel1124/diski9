"""Research only (Phase 6A.2 / 6A.2.1): Weekly Challenge championship scoring and round feasibility.

Phase 6A.2.1 adds the revised candidate schedule (150/135/125/120/115/110/105/100/95/90,
75 for other recoveries), standard competition ranking for ties (full points, no
averaging), a generic ``position_points`` used to compare scoring scenarios, and a
``ChampionshipSeries`` model of practice rounds, void rounds and the ten-round cycle.

* Four weekly scoring systems for comparison:
  * ``cumulative_net``: the earlier baseline; net credits summed.
  * ``f1``: 25/18/15/12/10/8/6/4/2/1 for the top ten, with no recovery requirement.
  * ``percentile``: 100 x (N - rank) / (N - 1), tied ranks averaged.
  * ``proposed``: 150/135/120/110/100/95/90/85/80/75 for positions 1-10 and 50
    outside the top ten, **only when gross >= 100.00**; otherwise 0.
* Weekly ties (proposed and F1): participants with an identical gross payout
  share the average of the points for the positions they jointly occupy. Points
  are kept as exact ``Fraction`` values.
* Championship standings: total points, then recoveries, then qualifying top-ten
  finishes. Players still equal share the position (joint).
* Round feasibility: an exact max-flow check that a strict 4/3/2 portfolio with
  nine distinct fixtures exists, plus the operational minimums (15 eligible
  fixtures, 3 leagues).

Nothing here is production code, and nothing gives selection advice. The
selection behaviours exist only to diagnose competition incentives.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

TARGET = Decimal("100.00")
PROPOSED_TOP10 = (150, 135, 120, 110, 100, 95, 90, 85, 80, 75)
RECOVERY_FLOOR = 50
F1_TOP10 = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
REVISED_TOP10 = (150, 135, 125, 120, 115, 110, 105, 100, 95, 90)
REVISED_FLOOR = 75
MIN_ENTRANTS = 5
CHAMPIONSHIP_ROUNDS = 10


# ------------------------------------------------------------- weekly scoring
def _tie_groups(gross: Sequence[Decimal]) -> list[list[int]]:
    """Participant indices grouped by identical gross, best first."""
    order = sorted(range(len(gross)), key=lambda i: -gross[i])
    groups: list[list[int]] = []
    for i in order:
        if groups and gross[groups[-1][0]] == gross[i]:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def proposed_points(gross: Sequence[Decimal], floor: int = RECOVERY_FLOOR,
                    top10: Sequence[int] = PROPOSED_TOP10) -> list[Fraction]:  # fmt: skip
    """Proposed rule: position points if gross >= 100.00, else 0.

    Positions are by gross among all entrants (identical to ranking by net).
    Tied participants share the average of the position values they occupy, where
    the value of position p is ``top10[p-1]`` for p <= 10, otherwise ``floor``.
    Every recovering participant ranks above every non-recovering one, so top-ten
    points never pass to a non-recovering entrant, and every tie group is either
    wholly recovering or wholly not."""
    pts = [Fraction(0)] * len(gross)
    pos = 1
    for g in _tie_groups(gross):
        occupied = range(pos, pos + len(g))
        if gross[g[0]] >= TARGET:
            vals = [top10[p - 1] if p <= len(top10) else floor for p in occupied]
            share = Fraction(sum(vals), len(vals))
            for i in g:
                pts[i] = share
        pos += len(g)
    return pts


def f1_points(gross: Sequence[Decimal]) -> list[Fraction]:
    pts = [Fraction(0)] * len(gross)
    pos = 1
    for g in _tie_groups(gross):
        vals = [F1_TOP10[p - 1] if p <= 10 else 0 for p in range(pos, pos + len(g))]
        for i in g:
            pts[i] = Fraction(sum(vals), len(vals))
        pos += len(g)
    return pts


def percentile_points(gross: Sequence[Decimal]) -> list[Fraction]:
    n = len(gross)
    if n == 1:
        return [Fraction(100)]
    pts = [Fraction(0)] * n
    pos = 1
    for g in _tie_groups(gross):
        avg_rank = Fraction(sum(range(pos, pos + len(g))), len(g))
        for i in g:
            pts[i] = 100 * (n - avg_rank) / (n - 1)
        pos += len(g)
    return pts


def net_points(gross: Sequence[Decimal]) -> list[Fraction]:
    return [Fraction(g - TARGET) for g in gross]


def competition_ranks(gross: Sequence[Decimal]) -> list[int]:
    """Standard competition ranking: 1 + the number of entrants with strictly greater gross."""
    ranks = [0] * len(gross)
    pos = 1
    for g in _tie_groups(gross):
        for i in g:
            ranks[i] = pos
        pos += len(g)
    return ranks


def position_points(gross: Sequence[Decimal], top10: Sequence[int] = REVISED_TOP10,
                    floor: int = REVISED_FLOOR, ties: str = "competition") -> list:  # fmt: skip
    """Recovery-gated position points under either tie rule.

    * ``ties="competition"`` (approved D-26 revision): tied entrants share the rank
      ``1 + #strictly greater`` and each receives that rank's full points; later
      ranks are skipped. More than ten entrants can receive top-ten points.
      Returns ``int`` points.
    * ``ties="average"`` (superseded Phase 6A.2 proposal): the mean of the occupied
      positions' values, as exact ``Fraction`` values.

    Gross below 100.00 always scores 0."""
    if ties == "average":
        return proposed_points(gross, floor=floor, top10=top10)
    if ties != "competition":
        raise ValueError(ties)
    return [
        (top10[r - 1] if r <= len(top10) else floor) if g >= TARGET else 0
        for g, r in zip(gross, competition_ranks(gross), strict=True)
    ]


def final_points(gross: Sequence[Decimal]) -> list[int]:
    """The preferred Phase 6A.2.1 configuration (scenario D)."""
    return position_points(gross, REVISED_TOP10, REVISED_FLOOR, "competition")


SYSTEMS = {
    "cumulative_net": net_points,
    "f1": f1_points,
    "percentile": percentile_points,
    "proposed": proposed_points,
    "final": final_points,
}


# ------------------------------------------------------- championship table
@dataclass
class Record:
    points: int | Fraction = 0
    entered: int = 0
    recoveries: int = 0
    qualifying_top10: int = 0
    best_round: int | Fraction = 0


def add_round(table: dict, entrants: Sequence, gross: Sequence[Decimal], system) -> None:
    """Add one completed round to a championship table (non-entrants score 0).

    ``system`` is a name in ``SYSTEMS`` or a callable ``gross -> points``."""
    pts = (SYSTEMS[system] if isinstance(system, str) else system)(gross)
    positions = competition_ranks(gross)  # tied players share the best occupied position
    for i, who in enumerate(entrants):
        r = table.setdefault(who, Record())
        r.points += pts[i]
        r.entered += 1
        rec = gross[i] >= TARGET
        r.recoveries += rec
        r.qualifying_top10 += rec and positions[i] <= 10
        r.best_round = max(r.best_round, pts[i])


def standings(table: dict) -> list[tuple[int, object, Record]]:
    """(position, participant, record), sorted by points, recoveries, then
    qualifying top-ten finishes. Players still equal share the position."""
    key = {w: (r.points, r.recoveries, r.qualifying_top10) for w, r in table.items()}
    order = sorted(table, key=lambda w: (tuple(-x for x in key[w]), str(w)))
    out, pos = [], 0
    for k, w in enumerate(order):
        if k == 0 or key[w] != key[order[k - 1]]:
            pos = k + 1
        out.append((pos, w, table[w]))
    return out


# ------------------------------------------------------- championship series
@dataclass
class Championship:
    number: int
    rounds: list = field(default_factory=list)
    table: dict = field(default_factory=dict)
    status: str = "active"  # active | complete
    champions: tuple = ()


class ChampionshipSeries:
    """Ten-round championships with practice and void rounds (D-28, D-30).

    * ``valid entries`` are distinct participants with a complete, valid final
      submission at the deadline; repeated submissions by one participant count
      once (the last one listed is the final submission).
    * Fewer than ``min_entrants`` valid entries: a **practice** round. It settles,
      it is kept in ``practice_rounds``, but it awards no points, does not touch
      tie-breakers and does not advance the counter.
    * A round cancelled or invalidated as a whole after the deadline: a **void**
      round, recorded in ``void_rounds`` only.
    * After ``length`` championship rounds the championship is finalised (the
      champions are everyone ranked 1 after the D-27 hierarchy) and archived, and a
      new one starts from zero. There is no time limit: a championship pauses
      across breaks and resumes with the next eligible round."""

    def __init__(self, points=final_points, min_entrants=MIN_ENTRANTS,
                 length=CHAMPIONSHIP_ROUNDS):  # fmt: skip
        self.points, self.min_entrants, self.length = points, min_entrants, length
        self.archive: list[Championship] = []
        self.current = Championship(1)
        self.practice_rounds: list = []
        self.void_rounds: list = []

    @staticmethod
    def valid_entries(submissions) -> dict:
        entries: dict = {}
        for who, gross in submissions:  # later submissions replace earlier ones
            entries.pop(who, None)
            entries[who] = Decimal(gross)
        return entries

    def record_round(self, round_id, submissions, cancelled: bool = False) -> str:
        if cancelled:
            self.void_rounds.append(round_id)
            return "void"
        entries = self.valid_entries(submissions)
        if len(entries) < self.min_entrants:
            self.practice_rounds.append((round_id, entries))
            return "practice"
        c = self.current
        add_round(c.table, list(entries), list(entries.values()), self.points)
        c.rounds.append(round_id)
        if len(c.rounds) == self.length:
            c.status = "complete"
            c.champions = tuple(w for pos, w, _ in standings(c.table) if pos == 1)
            self.archive.append(c)
            self.current = Championship(c.number + 1)
        return "championship"


# ------------------------------------------------------- round feasibility
def strict_portfolio_exists(outcomes, classify, need=(4, 3, 2)) -> bool:
    """Exact check that nine distinct fixtures can fill buckets A/B/C with
    ``need`` selections each, using one outcome per fixture.

    This is max-flow on source -> bucket (capacity need[b]) -> fixture (capacity 1
    if any of the fixture's outcomes falls in band b) -> sink (capacity 1). A
    portfolio exists iff the max flow is sum(need). Counting outcomes per bucket is
    not enough, because different buckets can compete for the same fixture."""
    fixture_bands: dict = {}
    for o in outcomes:
        b = classify(o)
        if b is not None:
            fixture_bands.setdefault(o.fixture_id, set()).add(b)
    match: dict = {}  # fixture -> (bucket, slot)
    slots = [(b, s) for b in range(len(need)) for s in range(need[b])]

    def augment(slot, seen):
        b = slot[0]
        for f, bands in fixture_bands.items():
            if b in bands and f not in seen:
                seen.add(f)
                if f not in match or augment(match[f], seen):
                    match[f] = slot
                    return True
        return False

    return all(augment(s, set()) for s in slots)


def round_feasibility(outcomes, classify, league_of, min_fixtures=15, min_leagues=3,
                      need=(4, 3, 2)) -> dict:  # fmt: skip
    """The proposed opening checks for a round (all three must pass)."""
    banded = {o.fixture_id for o in outcomes if classify(o) is not None}
    leagues = {league_of[f] for f in banded}
    exists = strict_portfolio_exists(outcomes, classify, need)
    return {
        "eligible_fixtures": len(banded),
        "eligible_leagues": len(leagues),
        "portfolio_exists": exists,
        "opens": len(banded) >= min_fixtures and len(leagues) >= min_leagues and exists,
    }
