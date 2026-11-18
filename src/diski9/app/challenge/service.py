"""Round snapshot service for the Weekly Challenge pages.

* The **live** snapshot is built read-only from the local database
  (``build_live_snapshot``) for a rolling seven-day window and frozen for
  ``live_ttl`` seconds; a rebuilt snapshot has a new fingerprint, so a
  participant's draft from an older snapshot is never silently reused.
* The **demonstration** snapshot is the frozen 17 Nov 2026 research pool,
  always assessed at its own snapshot time and always labelled as demo data.

Both are shared, read-only data. Participant state lives only in the browser
session (``dcc.Store``), never in this process.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import timedelta
from pathlib import Path

from diski9.app.data import LEAGUE_SHORT
from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.roundsheet import (
    RoundAvailability,
    RoundSnapshot,
    assess_round,
    build_live_snapshot,
    snapshot_from_research_pool,
)
from diski9.challenge.structured import (
    PortfolioEvaluation,
    PortfolioValidationError,
    evaluate_market_and_model,
    validate_portfolio,
)

DEMO_POOL = (
    Path(__file__).resolve().parents[4] / "docs/research/weekly_challenge_risk/pool_weekend.json"
)
DEMO_ROUND_ID = "DEMO-2026-W47"


def key_str(key: tuple) -> str:
    return "|".join(str(k) for k in key)


def parse_key(s: str) -> tuple:
    fid, market, outcome = s.split("|")
    return (int(fid) if fid.lstrip("-").isdigit() else fid, market, outcome)


class ChallengeService:
    def __init__(self, data, live_ttl: float = 900, demo_pool: Path = DEMO_POOL):
        self.data = data
        self.live_ttl = live_ttl
        self.demo_pool = demo_pool
        self._live: RoundSnapshot | None = None
        self._live_at = 0.0
        self._demo: RoundSnapshot | None = None
        self._lock = threading.Lock()
        self._eval_cache: dict = {}

    # ------------------------------------------------------------ snapshots
    def now(self):
        return self.data.clock()

    def live(self) -> RoundSnapshot | None:
        with self._lock:
            if self._live is None or time.monotonic() - self._live_at > self.live_ttl:
                now = self.now()
                iso = now.isocalendar()
                try:
                    self._live = build_live_snapshot(
                        self.data.engine,
                        now,
                        now,
                        now + timedelta(days=7),
                        f"{iso.year}-W{iso.week:02d}",
                        LEAGUE_SHORT,
                    )
                except Exception:  # noqa: BLE001 - an unreadable database is "no round"
                    self._live = None
                self._live_at = time.monotonic()
            return self._live

    def demo(self) -> RoundSnapshot | None:
        with self._lock:
            if self._demo is None and self.demo_pool.exists():
                pool = json.loads(self.demo_pool.read_text())
                self._demo = snapshot_from_research_pool(pool, DEMO_ROUND_ID, LEAGUE_SHORT)
            return self._demo

    def snapshot(self, mode: str | None) -> RoundSnapshot | None:
        return self.demo() if mode == "demo" else self.live()

    def availability(self, mode: str | None) -> RoundAvailability:
        return assess_round(self.snapshot(mode), self.now(), DEFAULT_CONFIG)

    # ------------------------------------------------------------ portfolio
    def outcomes_for(self, snap: RoundSnapshot, keys: list[str]):
        out = []
        for k in keys:
            o = snap.outcome(parse_key(k))
            if o is not None:
                out.append(o)
        return out

    def evaluate(
        self, snap: RoundSnapshot, keys: list[str]
    ) -> tuple[PortfolioEvaluation, PortfolioEvaluation] | None:
        """(market, model) evaluations of a complete valid portfolio, else None.
        Results are pure functions of (snapshot fingerprint, selections) and cached."""
        ck = (snap.fingerprint, tuple(keys))
        with self._lock:
            if ck in self._eval_cache:
                return self._eval_cache[ck]
        sels = self.outcomes_for(snap, list(keys))
        result = None
        if len(sels) == len(keys):
            try:
                port = validate_portfolio(
                    sels, snap.snapshot_at, DEFAULT_CONFIG, pool=snap.outcomes
                )
                result = evaluate_market_and_model(port)
            except PortfolioValidationError:
                result = None
        with self._lock:
            if len(self._eval_cache) > 512:
                self._eval_cache.clear()
            self._eval_cache[ck] = result
        return result
