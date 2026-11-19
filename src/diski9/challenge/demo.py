"""Deterministic demonstration results for the Weekly Challenge prototype (Phase 6B).

Illustrative only: invented display names and settled gross payouts, scored by the
production scoring engine (never hard-coded points). The demonstration
championship has seven completed competitive rounds, one practice round and one
void round, and the latest round includes a shared first place, a three-way tie
at tenth place and an all-void refunded entry.
"""

from __future__ import annotations

import random
from decimal import Decimal
from functools import lru_cache

from diski9.challenge.scoring import (
    POINTS_150_75_V2,
    ChampionshipTable,
    EntryResult,
    RoundClassification,
    RoundResult,
    RoundScore,
    SettlementBasis,
    aggregate_championship,
    score_round,
)

CHAMPIONSHIP_ID = "DEMO-C1"
YOU = "You (demo)"
PLAYERS = (
    "Kasi Kicker",
    "Bafana Believer",
    "Soweto Striker",
    "Cape Tactician",
    "Durban Dribbler",
    "Pretoria Playmaker",
    "Highveld Hopper",
    "Karoo Keeper",
    "Limpopo Lob",
    "Natal Nutmeg",
    "Free State Flair",
    "Vaal Volley",
    "Garden Route Goal",
    "Mzansi Maestro",
    "Table Mountain Tiki",
    "Joburg Juggler",
    "Eastern Cape Engine",
)
_VALUES = (
    "0.00",
    "0.00",
    "0.00",
    "0.00",
    "38.40",
    "61.20",
    "88.20",
    "100.00",
    "112.35",
    "120.00",
    "145.33",
    "160.20",
    "190.40",
    "221.75",
    "238.00",
    "260.44",
    "305.10",
    "382.89",
    "412.80",
    "490.71",
)
LATEST_ROUND = "DEMO-R7"


def _entries(gross: dict[str, str], void: tuple[str, ...] = ()) -> tuple[EntryResult, ...]:
    out = [EntryResult(p, Decimal(g)) for p, g in gross.items()]
    out += [EntryResult(p, Decimal("100.00"), SettlementBasis.ALL_SELECTIONS_VOID) for p in void]
    return tuple(out)


def _latest() -> dict[str, str]:
    names = (YOU, *PLAYERS)
    values = (
        "412.80",
        "412.80",
        "305.10",
        "260.44",
        "238.00",
        "221.75",
        "190.40",
        "160.20",
        "145.33",
        "120.00",
        "120.00",
        "120.00",
        "100.00",
        "88.20",
        "45.60",
        "0.00",
        "0.00",
    )
    order = (1, 2, 3, 0, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)
    return {names[i]: v for i, v in zip(order, values, strict=True)}


@lru_cache(maxsize=1)
def demo_rounds() -> tuple[RoundResult, ...]:
    v = POINTS_150_75_V2.version
    rng = random.Random(6202)
    rounds = []
    everyone = (YOU, *PLAYERS)
    for k in range(1, 7):
        present = [p for p in everyone if rng.random() < 0.88 or p == YOU]
        gross = {p: rng.choice(_VALUES) for p in present}
        rounds.append(
            RoundResult(
                f"DEMO-R{k}", CHAMPIONSHIP_ID, RoundClassification.COMPETITIVE, _entries(gross), v
            )
        )
        if k == 3:  # a quiet week: four entries, a practice round
            rounds.append(
                RoundResult(
                    "DEMO-P1",
                    None,
                    RoundClassification.PRACTICE,
                    _entries(
                        {
                            YOU: "145.33",
                            PLAYERS[0]: "238.00",
                            PLAYERS[1]: "0.00",
                            PLAYERS[2]: "100.00",
                        }
                    ),
                    v,
                )
            )
        if k == 5:  # cancelled after the deadline: stakes returned, nothing counts
            rounds.append(
                RoundResult(
                    "DEMO-V1",
                    CHAMPIONSHIP_ID,
                    RoundClassification.VOID,
                    _entries({p: "100.00" for p in everyone[:12]}),
                    v,
                )
            )
    rounds.append(
        RoundResult(
            LATEST_ROUND,
            CHAMPIONSHIP_ID,
            RoundClassification.COMPETITIVE,
            _entries(_latest(), void=(PLAYERS[16],)),
            v,
        )
    )
    return tuple(rounds)


def round_label(r: RoundResult) -> str:
    kind = {RoundClassification.PRACTICE: "practice round", RoundClassification.VOID: "void round"}
    return f"{r.round_id} ({kind[r.classification]})" if r.classification in kind else r.round_id


def demo_round_score(round_id: str) -> RoundScore:
    r = next(x for x in demo_rounds() if x.round_id == round_id)
    return score_round(r)


def demo_championship() -> ChampionshipTable:
    return aggregate_championship(CHAMPIONSHIP_ID, demo_rounds())


def demo_history(participant: str = YOU) -> list[tuple[RoundResult, object]]:
    """(round, weekly score or None if not entered) for the demo participant."""
    out = []
    for r in demo_rounds():
        s = score_round(r)
        out.append((r, next((x for x in s.scores if x.participant_id == participant), None)))
    return out


def demo_summary(participant: str = YOU) -> dict:
    """Performance summary for the demo participant from engine outputs. Practice and
    void rounds never count toward recoveries, finishes or progress."""
    table = demo_championship()
    me = next((s for s in table.standings if s.participant_id == participant), None)
    timeline = []
    finishes = []
    for r, s in demo_history(participant):
        if r.classification is not RoundClassification.COMPETITIVE:
            continue
        if s is None or not s.counts_for_championship:
            timeline.append({"round": r.round_id, "state": "missed", "points": 0, "rank": None})
            continue
        timeline.append(
            {
                "round": r.round_id,
                "state": "recovered" if s.recovered else "lost",
                "points": s.points,
                "rank": s.rank,
            }
        )
        if s.rank is not None:
            finishes.append(s.rank)
    remaining = table.rounds_required - table.completed_rounds
    timeline += [{"round": None, "state": "remaining", "points": 0, "rank": None}] * remaining
    entered = me.rounds_entered if me else 0
    return {
        "points": me.points if me else 0,
        "rank": me.rank if me else None,
        "field": len(table.standings),
        "recoveries": me.recoveries if me else 0,
        "entered": entered,
        "recovery_rate": (me.recoveries / entered) if me and entered else None,
        "top10": me.qualifying_top10 if me else 0,
        "best_finish": min(finishes) if finishes else None,
        "completed": table.completed_rounds,
        "required": table.rounds_required,
        "timeline": timeline,
    }
