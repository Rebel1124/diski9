"""Phase 6C.3 Stage G: quantitative regression fingerprint.

Computes the numerical outputs of the approved engines on fixed inputs and prints
them as canonical JSON (floats with full ``repr`` precision, Decimals as strings).
Run it on the pre-persistence baseline and on the current branch and compare the
two files byte for byte::

    git worktree add /tmp/base 597ed70
    (cd /tmp/base && uv run python <this file>) > base.json
    uv run python tools/phase6c3_quant_regression.py > head.json
    cmp base.json head.json

Inputs: the frozen demonstration research pool (17 Nov 2026), deterministic
portfolios chosen with the builder's own rules, a Goal Model grid and the
demonstration scoring rounds. Read-only; no network, no database.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import sys
from datetime import date, datetime
from decimal import Decimal

from diski9.app.challenge.service import ChallengeService
from diski9.challenge import analysis, demo, scoring
from diski9.challenge.config import REQUIRED_SELECTIONS, ProbabilitySource
from diski9.challenge.structured import (
    assess_outcome,
    evaluate_market_and_model,
    evaluate_portfolio,
    payout_distribution,
    round_opening_report,
    selection_blocks,
    validate_portfolio,
)
from diski9.screener import goal_model as gm


def canon(x, depth=0):
    if depth > 12:
        return repr(x)
    if isinstance(x, float):
        return repr(x)
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, enum.Enum):
        return canon(x.value, depth + 1)
    if isinstance(x, datetime | date):
        return x.isoformat()
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: canon(getattr(x, f.name), depth + 1) for f in dataclasses.fields(x)}
    if isinstance(x, dict):
        return {str(canon(k, depth + 1)): canon(v, depth + 1) for k, v in x.items()}
    if isinstance(x, list | tuple | set | frozenset):
        items = [canon(v, depth + 1) for v in x]
        return sorted(items, key=json.dumps) if isinstance(x, set | frozenset) else items
    if isinstance(x, str | int | bool) or x is None:
        return x
    return repr(x)


def portfolios(snap, count=6):
    """Deterministic complete portfolios: greedy over the pool from several offsets."""
    outs = list(snap.outcomes)
    found = []
    for start in range(0, len(outs), max(1, len(outs) // (count * 2))):
        chosen = []
        for o in outs[start:] + outs[:start]:
            if len(chosen) == REQUIRED_SELECTIONS:
                break
            if (
                selection_blocks(chosen, snap.outcomes, snap.snapshot_at, snap.config).get(o.key)
                is None
            ):
                chosen.append(o)
        if len(chosen) == REQUIRED_SELECTIONS:
            found.append(chosen)
        if len(found) == count:
            break
    return found


def main() -> None:
    svc = ChallengeService(data=None)
    snap = svc.demo()
    out = {"snapshot": {"round": snap.round_id, "fingerprint": snap.fingerprint}}
    out["assessments"] = [
        canon(assess_outcome(o, snap.snapshot_at, snap.config)) for o in snap.outcomes
    ]
    out["opening_report"] = canon(
        round_opening_report(snap.outcomes, snap.snapshot_at, snap.config)
    )
    out["portfolios"] = []
    for sels in portfolios(snap):
        port = validate_portfolio(sels, snap.snapshot_at, snap.config, pool=snap.outcomes)
        mkt, mdl = evaluate_market_and_model(port)
        personal = {o.key: min(0.99, analysis.market_probability(o) * 1.05) for o in sels}
        srcs = analysis.evaluate_sources(port, personal)
        out["portfolios"].append(
            {
                "keys": [list(map(str, o.key)) for o in sels],
                "market": canon(mkt),
                "model": canon(mdl),
                "market_direct": canon(evaluate_portfolio(port, ProbabilitySource.MARKET)),
                "sources": {k: canon(v) for k, v in srcs.items()},
                "distribution": canon(payout_distribution(srcs["market"])),
                "correct_count": canon(analysis.correct_count_analysis(port)),
                "breakdown": canon(analysis.calculation_breakdown(port)),
                "app_service": canon(svc.evaluate(snap, ["|".join(map(str, o.key)) for o in sels])),
            }
        )
    out["goal_model"] = {
        "params": gm.params_hash(),
        "grid": {
            f"{h:.2f}-{a:.2f}": canon(gm.markets(h, a))
            for h in (0.35, 0.8, 1.27, 1.5, 2.1, 3.4)
            for a in (0.4, 0.95, 1.33, 2.6)
        },
    }
    rounds = demo.demo_rounds()
    out["scoring"] = {
        "classification": [
            canon(scoring.classify_round(n, cancel))
            for n in (0, 4, 5, 6, 200)
            for cancel in (False, True)
        ],
        "round_scores": [canon(scoring.score_round(r)) for r in rounds],
        "summary": canon(demo.demo_summary()),
    }
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
