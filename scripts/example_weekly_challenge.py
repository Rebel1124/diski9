"""Worked example: the Phase 6A.3 Weekly Challenge engines end to end.

    uv run python scripts/example_weekly_challenge.py

1. Build a valid 4/3/2 portfolio from round-sheet outcomes.
2. Evaluate it with market and with model probabilities (same payouts).
3. Print the exact payout distribution.
4. Score a week from illustrative settled results (with ties).
5. Aggregate a ten-round championship with shared positions.

All numbers are illustrative. No database, network or API access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from diski9.challenge.config import BROAD60_432_V1
from diski9.challenge.scoring import (
    POINTS_150_75_V2,
    EntryResult,
    RoundClassification,
    RoundResult,
    aggregate_championship,
    classify_round,
    score_round,
)
from diski9.challenge.structured import (
    evaluate_market_and_model,
    make_outcome,
    portfolio_progress,
    validate_portfolio,
)

SNAPSHOT = datetime(2026, 11, 19, 6, 0, tzinfo=UTC)
SEEN = datetime(2026, 11, 19, 5, 30, tzinfo=UTC)  # odds verified 30 minutes before


def outcome(fid, market, out, p_market, odds, p_model, label):
    return make_outcome(
        fid,
        market,
        out,
        p_market,
        odds,
        p_model,
        bookmaker_groups=6,
        latest_observation_at=SEEN,
        league_id=39,
        label=label,
    )


SELECTIONS = [
    outcome(101, "1X2", "HOME", 0.812, "1.18", 0.744, "Arsenal win"),
    outcome(102, "OU25", "OVER_2_5", 0.701, "1.37", 0.655, "Over 2.5: Bayern v Union"),
    outcome(103, "1X2", "HOME", 0.664, "1.45", 0.602, "Inter win"),
    outcome(104, "BTTS", "BTTS_NO", 0.618, "1.55", 0.590, "BTTS No: Getafe v Alaves"),
    outcome(105, "BTTS", "BTTS_YES", 0.552, "1.74", 0.571, "BTTS Yes: Leeds v Spurs"),
    outcome(106, "1X2", "AWAY", 0.471, "2.05", 0.402, "Lyon win away"),
    outcome(107, "OU25", "UNDER_2_5", 0.433, "2.22", 0.468, "Under 2.5: Celta v Osasuna"),
    outcome(108, "1X2", "DRAW", 0.318, "3.05", 0.289, "Draw: Bologna v Torino"),
    outcome(109, "1X2", "AWAY", 0.231, "4.15", 0.287, "Brentford win away"),
]


def main() -> None:
    cfg = BROAD60_432_V1
    print(
        f"Configuration {cfg.version}: buckets "
        + ", ".join(
            f"{b.name} {b.selections} x {b.band.describe()} @ {b.credits} cr" for b in cfg.buckets
        )
        + f", {cfg.nine_fold_name} @ {cfg.nine_fold_credits} cr"
    )

    # 1. progress while building, then the validated portfolio
    p = portfolio_progress(SELECTIONS[:5], SNAPSHOT)
    print(
        "\nAfter five picks:",
        {cfg.bucket(c).name: f"{p.selected[c]}/{p.required[c]}" for c in cfg.bucket_codes},
        f"total {p.total_selected}/9",
    )
    portfolio = validate_portfolio(SELECTIONS, SNAPSHOT)

    # 2. market and model estimates (same reference-odds payouts)
    market, model = evaluate_market_and_model(portfolio)
    print("\nBucket            odds        payout   P(win) market  P(win) model")
    for bm, bd in zip(
        (*market.buckets, market.nine_fold), (*model.buckets, model.nine_fold), strict=True
    ):
        print(
            f"{bm.name:<13} {bm.combined_odds:>10.4f} {bm.payout:>11}   {bm.win_probability:>11.4%}"
            f"   {bd.win_probability:>11.4%}"
        )
    for ev in (market, model):
        print(
            f"\n[{ev.source} estimate] P(recover 100) {ev.p_recover:.4%} | P(zero) {ev.p_zero:.4%}"
            f" | expected gross {ev.expected_gross:.2f} | expected net {ev.expected_net:+.2f}"
            f" | maximum {ev.max_gross}"
        )

    # 3. exact payout distribution (market estimate)
    print("\nPayout (credits)   P(exactly)   P(at least)   states")
    for pt in market.distribution():
        print(f"{pt.gross:>15}   {pt.probability:>10.4%}   {pt.at_least:>11.4%}   {pt.states}")
    assert market.at_least(Decimal("100.00")) == market.p_recover

    # 4. a week's settled results (ties included)
    gross = {
        "Thandi": "412.80",
        "Sipho": "231.00",
        "Lee": "231.00",
        "Ana": "190.40",
        "Nomsa": "100.00",
        "Ben": "88.20",
        "Zola": "0.00",
    }
    cls = classify_round(len(gross), cancelled=False)
    week = score_round(
        RoundResult(
            "2026-W47",
            "C1",
            cls,
            tuple(EntryResult(p, Decimal(g)) for p, g in gross.items()),
            POINTS_150_75_V2.version,
        )
    )
    print(f"\nWeek 2026-W47 ({week.classification}):")
    for s in week.scores:
        print(
            f"  {s.rank!s:>3}  {s.participant_id:<7} gross {s.gross:>7}  net {s.net:>+8}"
            f"  points {s.points:>3}  {'recovered' if s.recovered else 'not recovered'}"
        )

    # 5. a ten-round championship with a practice round and a joint lead
    rounds = []
    pattern = [
        {"Thandi": 300, "Sipho": 200, "Lee": 200, "Ana": 150, "Nomsa": 100, "Ben": 50},
        {"Thandi": 80, "Sipho": 150, "Lee": 150, "Ana": 120, "Nomsa": 110, "Ben": 400},
    ]
    for i in range(10):
        g = pattern[i % 2]
        rounds.append(
            RoundResult(
                f"R{i + 1}",
                "C1",
                RoundClassification.COMPETITIVE,
                tuple(EntryResult(p, Decimal(v)) for p, v in g.items()),
                POINTS_150_75_V2.version,
            )
        )
    rounds.insert(
        4,
        RoundResult(
            "P1",
            None,
            RoundClassification.PRACTICE,
            (EntryResult("Thandi", Decimal(500)),),
            POINTS_150_75_V2.version,
        ),
    )
    table = aggregate_championship("C1", rounds)
    print(
        f"\nChampionship C1: {table.completed_rounds}/{table.rounds_required} rounds, "
        f"ignored {table.ignored_round_ids}, complete={table.is_complete}"
    )
    print("  Rank  Name    Points  Recoveries  Top-ten  Rounds")
    for s in table.standings:
        print(
            f"  {s.rank:>4}  {s.participant_id:<7} {s.points:>6}  {s.recoveries:>10}  "
            f"{s.qualifying_top10:>7}  {s.rounds_entered:>6}"
        )
    print("  Champion(s):", ", ".join(table.champions))


if __name__ == "__main__":
    main()
