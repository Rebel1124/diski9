"""Deterministic development fixtures for local rounds (Phase 6C.3).

**Synthetic data, not real football.** Team names are "Dev …", the snapshot note
says "Development fixtures", and these snapshots can only be published into
development rounds (``rounds.is_development``; codes start with ``dev-``). They
let the owner and the tests publish, play and lock a round without any live
API request or football database.

The same ``seed``, ``as_of`` and ``first_kickoff`` always produce the same
snapshot (and fingerprint). Prices follow the strict-consensus shape: complete
markets, five independent bookmaker groups, observed ten minutes before the
snapshot, margin-adjusted probabilities at full precision and consensus odds
quantised to 0.01.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.roundsheet import RoundFixture, RoundSnapshot, SnapshotKind
from diski9.challenge.structured import make_outcome

DEV_LEAGUES = {39: "EPL", 140: "La Liga", 78: "Bundesliga", 288: "PSL"}
DEV_NOTE = "Development fixtures (synthetic, not real football data)."
MARGIN = Decimal("1.05")


def _odds(p: float) -> Decimal:
    return max(
        Decimal("1.01"), (Decimal(1) / (Decimal(repr(p)) * MARGIN)).quantize(Decimal("0.01"))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _split(rng: random.Random, n: int) -> list[float]:
    w = [rng.uniform(0.6, 3.0) for _ in range(n)]
    total = sum(w)
    return [x / total for x in w]


def dev_snapshot(
    code: str,
    as_of: datetime,
    first_kickoff: datetime,
    *,
    fixtures: int = 20,
    seed: int = 2026,
    spacing: timedelta = timedelta(hours=2),
) -> RoundSnapshot:
    """A deterministic synthetic round snapshot for a development round."""
    if not code.startswith("dev-"):
        raise ValueError("development snapshots are only for 'dev-' rounds")
    rng = random.Random(seed)
    leagues = list(DEV_LEAGUES)
    observed = as_of - timedelta(minutes=10)
    fx, outs = [], []
    base_id = 9_000_000_000 + seed * 1000
    for i in range(fixtures):
        fid = base_id + i
        league = leagues[i % len(leagues)]
        kickoff = first_kickoff + spacing * i
        p = _split(rng, 3)  # 1X2
        btts = rng.uniform(0.35, 0.65)
        over = rng.uniform(0.35, 0.65)
        eg = (round(rng.uniform(0.8, 2.2), 6), round(rng.uniform(0.6, 1.9), 6))
        fx.append(
            RoundFixture(
                fid,
                league,
                DEV_LEAGUES[league],
                f"Dev Home {i + 1:02d}",
                f"Dev Away {i + 1:02d}",
                kickoff,
                eg,
            )
        )
        markets = (
            ("1X2", (("HOME", p[0]), ("DRAW", p[1]), ("AWAY", p[2]))),
            ("BTTS", (("BTTS_YES", btts), ("BTTS_NO", 1 - btts))),
            ("OU25", (("OVER_2_5", over), ("UNDER_2_5", 1 - over))),
        )
        for market, pairs in markets:
            for outcome, prob in pairs:
                model = min(0.99, max(0.01, prob + rng.uniform(-0.04, 0.04)))
                outs.append(
                    make_outcome(
                        fid, market, outcome, prob, _odds(prob), model, 5, observed, league
                    )
                )
    window = (first_kickoff - timedelta(days=1), first_kickoff + spacing * fixtures + timedelta(1))
    return RoundSnapshot(
        code,
        SnapshotKind.LIVE,
        as_of,
        DEFAULT_CONFIG.version,
        window,
        tuple(fx),
        tuple(outs),
        DEV_NOTE,
        {"development": True, "seed": seed},
    )
