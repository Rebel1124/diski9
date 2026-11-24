"""Generate the historical v1 settlement regression fixture (Scenario A3, Checkpoint 2).

The fixture records what the PRE-A3 code (commit b01e057, before any A3 change) produced
for deterministic v1 portfolios built from the committed real-market research pool:

* the frozen legs (bucket assigned under broad60-432-v1 at submission, frozen odds);
* the eight-state evaluation stored at confirmation (market and model);
* the settlement for fixed verdict vectors (wins, losses, voids, all void, pending);
* D-31 weekly scoring of a round made of those entries.

``tests/test_challenge_a3.py`` recomputes everything with the current code and requires
exact equality, so historical v1 results stay reproducible after A3 is registered.

It uses only APIs that already existed at b01e057 and passes the configuration
explicitly, so the same script runs unchanged on the old and the new code:

    git worktree add /tmp/pre-a3 b01e057
    PYTHONPATH=/tmp/pre-a3/src uv run python tools/a3_v1_settlement_regression.py \\
        tests/fixtures/challenge/v1_settlement_regression.json

Read-only: the only input is the committed pool; no database, no provider calls.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

from diski9.challenge.config import get_config
from diski9.challenge.roundsheet import snapshot_from_research_pool
from diski9.challenge.scoring import (
    EntryResult,
    RoundClassification,
    RoundResult,
    score_round,
)
from diski9.challenge.settle import Leg, settle_entry
from diski9.challenge.structured import (
    evaluate_market_and_model,
    selection_blocks,
    validate_portfolio,
)

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "docs/research/weekly_challenge_risk/pool_fortnight.json"
VERSION = "broad60-432-v1"
PORTFOLIOS = 12
LEAGUES = {39: "EPL", 40: "Championship", 61: "Ligue 1", 78: "Bundesliga", 135: "Serie A",
           140: "La Liga", 288: "PSL", 289: "PSL 1st Div"}  # fmt: skip


def vectors() -> dict[str, list[str]]:
    """Verdicts by leg position (positions 0-3 Foundation, 4-6 Balanced, 7-8 Challenger)."""
    won = ["won"] * 9

    def with_(**changes):
        v = list(won)
        for pos, verdict in changes.items():
            v[int(pos[1:])] = verdict
        return v

    return {
        "all_won": won,
        "foundation_lost": with_(p0="lost"),
        "balanced_lost": with_(p4="lost"),
        "challenger_lost": with_(p7="lost"),
        "only_foundation": with_(p4="lost", p7="lost"),
        "one_void": with_(p0="void"),
        "voids_each_bucket": with_(p0="void", p4="void", p7="void"),
        "all_void": ["void"] * 9,
        "pending": with_(p8="pending"),
    }


def portfolios(snap, config):
    """Deterministic complete portfolios: greedy over the pool from several offsets."""
    outs = list(snap.outcomes)
    found, seen = [], set()
    step = max(1, len(outs) // (PORTFOLIOS * 3))
    for start in range(0, len(outs), step):
        chosen = []
        for o in outs[start:] + outs[:start]:
            if len(chosen) == config.required_selections:
                break
            if selection_blocks(chosen, snap.outcomes, snap.snapshot_at, config).get(o.key) is None:
                chosen.append(o)
        key = tuple(sorted(o.key for o in chosen))
        if len(chosen) == config.required_selections and key not in seen:
            seen.add(key)
            found.append(chosen)
        if len(found) == PORTFOLIOS:
            break
    return found


def evaluation(ev) -> dict:
    return {
        "p_recover": repr(ev.p_recover),
        "expected_gross": repr(ev.expected_gross),
        "max_gross": str(ev.max_gross),
        "buckets": [
            [b.code, str(b.combined_odds), repr(b.win_probability), str(b.payout)]
            for b in ev.buckets
        ],  # fmt: skip
        "nine_fold": [str(ev.nine_fold.combined_odds), str(ev.nine_fold.payout)],
        "states": [[list(s.wins), str(s.gross), repr(s.probability)] for s in ev.states],
    }


def settlement(es) -> dict:
    return {
        "gross": str(es.gross),
        "complete": es.complete,
        "all_void": es.all_void,
        "recovered": es.recovered,
        "rank_eligible": es.rank_eligible,
        "win_vector": list(es.win_vector) if es.win_vector is not None else None,
        "accumulators": [
            [
                a.code,
                a.stake,
                a.status,
                None if a.effective_odds is None else str(a.effective_odds),
                None if a.payout is None else str(a.payout),
            ]
            for a in es.accumulators
        ],  # fmt: skip
    }


def build() -> dict:
    config = get_config(VERSION)
    pool = json.loads(POOL.read_text())
    snap = snapshot_from_research_pool(pool, "v1-regression", LEAGUES, config)
    vec = vectors()
    entries = []
    for i, chosen in enumerate(portfolios(snap, config)):
        port = validate_portfolio(chosen, snap.snapshot_at, config, pool=snap.outcomes)
        legs = []
        for code, bucket in zip(config.bucket_codes, port.buckets, strict=True):
            for o in bucket:
                legs.append(Leg(len(legs), o.fixture_id, str(o.market), str(o.outcome), code,
                                o.reference_odds))  # fmt: skip
        market, model = evaluate_market_and_model(port)
        settled = {}
        for name, verdicts in vec.items():
            v = {(x.fixture_id, x.market, x.outcome): verdicts[x.position] for x in legs}
            settled[name] = settlement(settle_entry(legs, v, config))
        entries.append({
            "id": f"p{i:02d}",
            "legs": [[x.position, x.fixture_id, x.market, x.outcome, x.bucket, str(x.odds),
                      repr(snap.outcome((x.fixture_id, x.market, x.outcome)).market_probability)]
                     for x in legs],
            "evaluation": {"market": evaluation(market.result), "model": evaluation(model.result)},
            "settlement": settled,
        })  # fmt: skip
    complete = [n for n in vec if n != "pending"]
    round_entries = []
    for i, e in enumerate(entries):
        name = complete[i % len(complete)]
        round_entries.append((e["id"], name, Decimal(e["settlement"][name]["gross"])))
    rr = RoundResult("v1-regression", "ch", RoundClassification.COMPETITIVE,
                     tuple(EntryResult(pid, gross) for pid, _, gross in round_entries),
                     "points-150-75-v2")  # fmt: skip
    scores = {s.participant_id: s for s in score_round(rr).scores}
    return {
        "generated_by": "tools/a3_v1_settlement_regression.py",
        "config_version": VERSION,
        "config_fingerprint": config.fingerprint(),
        "pool": str(POOL.relative_to(ROOT)),
        "pool_as_of": pool["as_of"],
        "verdict_vectors": vec,
        "entries": entries,
        "round": [
            {
                "participant": pid,
                "vector": name,
                "gross": str(g),
                "rank": scores[pid].rank,
                "points": scores[pid].points,
                "recovered": scores[pid].recovered,
                "top10": scores[pid].qualifying_top10,
            }
            for pid, name, g in round_entries
        ],  # fmt: skip
    }


def main(argv=None) -> int:
    out = Path((argv or sys.argv[1:])[0])
    out.write_text(json.dumps(build(), indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
