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
    RoundStatus,
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


class ScheduleConfigUnavailable(Exception):
    """The configuration of the schedule valid now could not be read (database or
    schedule resolution error). Shown as temporarily unavailable; never replaced by
    another configuration."""


def key_str(key: tuple) -> str:
    return "|".join(str(k) for k in key)


def parse_key(s: str) -> tuple:
    fid, market, outcome = s.split("|")
    return (int(fid) if fid.lstrip("-").isdigit() else fid, market, outcome)


class ChallengeService:
    """With ``backend`` (Phase 6C.3), the live round is the **published** round from
    the competition database: its frozen snapshot is what everyone sees, and there
    is never a fallback to a snapshot built on the fly. Without it the Phase 6B
    prototype behaviour is unchanged (used when accounts are not configured)."""

    def __init__(self, data, live_ttl: float = 900, demo_pool: Path = DEMO_POOL, backend=None):
        self.data = data
        self.backend = backend
        self.live_ttl = live_ttl
        self.demo_pool = demo_pool
        self._live: RoundSnapshot | None = None
        self._live_at = 0.0
        self._demo: RoundSnapshot | None = None
        self.demo_error: str | None = None
        self._lock = threading.Lock()
        self._eval_cache: dict = {}
        self._pinned: dict[str, RoundSnapshot] = {}

    # ------------------------------------------------------------ snapshots
    def now(self):
        return self.data.clock()

    def live(self) -> RoundSnapshot | None:
        """The live round's snapshot. Once a round's snapshot passes the opening checks
        it is **pinned** for that round (one official frozen snapshot per round), so it
        is never rebuilt during the round; an unplayable snapshot (for example stale
        odds at publication) is retried every ``live_ttl`` seconds."""
        if self.backend is not None:
            found = self.backend.published()
            return found[1] if found else None
        with self._lock:
            now = self.now()
            iso = now.isocalendar()
            round_id = f"{iso.year}-W{iso.week:02d}"
            pinned = self._pinned.get(round_id)
            if pinned is not None:
                return pinned
            if self._live is None or time.monotonic() - self._live_at > self.live_ttl:
                try:
                    # prototype mode: no competition database is configured (no
                    # backend, no schedule, no round record), the only case where the
                    # library default is the legitimate configuration
                    self._live = build_live_snapshot(
                        self.data.engine,
                        now,
                        now,
                        now + timedelta(days=7),
                        round_id,
                        LEAGUE_SHORT,
                        DEFAULT_CONFIG,
                    )
                except Exception:  # noqa: BLE001 - an unreadable database is "no round"
                    self._live = None
                self._live_at = time.monotonic()
                if self._live is not None and assess_round(self._live, now).playable:
                    self._pinned[round_id] = self._live
            return self._live

    def rules_config(self):
        """The configuration explanatory text describes when no round applies: with
        a competition database, the configuration of the ``weekend`` schedule row
        valid now; without one (prototype), the library default. A database or
        schedule error raises :class:`ScheduleConfigUnavailable` (no fallback)."""
        if self.backend is not None:
            return self.backend.schedule_config()
        return DEFAULT_CONFIG  # no competition database configured (prototype only)

    def demo(self) -> RoundSnapshot | None:
        """The demonstration round, built under :meth:`rules_config` (so it follows
        the schedule valid now) and rebuilt when that configuration changes. None,
        with ``demo_error`` set, when the configuration cannot be resolved."""
        try:
            config = self.rules_config()
        except ScheduleConfigUnavailable as exc:
            with self._lock:
                self.demo_error = str(exc)
            return None
        with self._lock:
            self.demo_error = None
            if self._demo is not None and self._demo.config is not config:
                self._demo = None
            if self._demo is None and self.demo_pool.exists():
                pool = json.loads(self.demo_pool.read_text())
                self._demo = snapshot_from_research_pool(pool, DEMO_ROUND_ID, LEAGUE_SHORT, config)
            return self._demo

    def snapshot(self, mode: str | None) -> RoundSnapshot | None:
        return self.demo() if mode == "demo" else self.live()

    def availability(self, mode: str | None) -> RoundAvailability:
        if mode != "demo" and self.backend is not None:
            return self.backend.availability(self.now())
        snap = self.snapshot(mode)
        if mode == "demo" and snap is None and self.demo_error:
            return RoundAvailability(
                RoundStatus.NO_ROUND,
                "Demonstration round temporarily unavailable",
                "The current competition rules could not be read. Please try again in a "
                "moment. The Match Lab and statistics still work.",
                None,
            )
        return assess_round(snap, self.now())  # the snapshot's own config

    def round_view(self):
        """The published round's record (status, deadline, frozen time) or None."""
        if self.backend is None:
            return None
        found = self.backend.published()
        return found[0] if found else None

    # ------------------------------------------------------------ portfolio
    def outcomes_for(self, snap: RoundSnapshot, keys: list[str]):
        out = []
        for k in keys:
            o = snap.outcome(parse_key(k))
            if o is not None:
                out.append(o)
        return out

    def portfolio(self, snap: RoundSnapshot, keys: list[str]):
        """The validated StructuredPortfolio for these selections, or None."""
        sels = self.outcomes_for(snap, list(keys))
        if len(sels) != len(keys) or not keys:
            return None
        try:
            return validate_portfolio(sels, snap.snapshot_at, snap.config, pool=snap.outcomes)
        except PortfolioValidationError:
            return None

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
                port = validate_portfolio(sels, snap.snapshot_at, snap.config, pool=snap.outcomes)
                result = evaluate_market_and_model(port)
            except PortfolioValidationError:
                result = None
        with self._lock:
            if len(self._eval_cache) > 512:
                self._eval_cache.clear()
            self._eval_cache[ck] = result
        return result
