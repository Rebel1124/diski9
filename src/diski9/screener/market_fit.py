"""Market-implied Estimated Goals for production (Phase 8 CP2B.1; CP1-5, OD-2).

The **State B** starting point of the Match Lab and the third tier of the Weekly
Challenge "Your View" hierarchy: when no independent Goal Model prediction exists,
the home and away scoring rates that best reproduce the margin-adjusted bookmaker
consensus under independent Poisson.

* **Methodology.** The accepted CP1 prototype is reused unchanged: its ``fit``
  (KL objective over whole markets, deterministic multi-start bounded L-BFGS-B,
  bounds 0.05-6.0, SVD identifiability check, the 2 pp / 4 pp quality bands) is
  called directly from :mod:`diski9.research.market_implied_xg`. Production adds
  only what CP1 recommended on top of it: the R-3 input rule, rejection of a
  non-converged fit (CP1 report §7), and probabilities for display through the
  production Poisson function (:func:`goal_model.markets`).
* **Inputs (R-3).** A 1X2 consensus plus at least one goals market (BTTS or
  Over/Under 2.5), each from at least three independent bookmaker groups and
  fresh: live markets must be fresh *now* (display status ``fresh`` and Challenge
  eligible); frozen Weekly Challenge markets must have been fresh *at the
  snapshot time* (latest observation no more than 24 h before it). Frozen inputs
  are never re-judged by their present-day age and never topped up from live odds.
* **Status.** ``good`` (largest absolute residual <= 2 pp) or ``approximate``
  (<= 4 pp) are reliable; everything else is ``rejected`` with a reason. A good fit
  only means the Estimated Goals reproduce the supplied market probabilities; it
  says nothing about predictive accuracy.
* **On demand, reused.** Nothing here runs in bulk. Results are kept in a small
  bounded in-process LRU keyed by a deterministic input identity: the methodology
  fingerprint, the context (live or frozen), the fixture and the exact input
  probabilities. Any change to one of them is a different identity, so live and
  frozen results can never be mixed and stale results are never reused.

Market-implied values are never written into Goal Model fields or snapshots.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from diski9.research import market_implied_xg as proto
from diski9.screener import goal_model as gm

FIT_VERSION = "1.0"  # the CP1 prototype methodology, as accepted
SOURCE_LABEL = "Market-implied Model"
MIN_GROUPS = 3  # independent bookmaker groups per market used (R-3)
MAX_INPUT_AGE = timedelta(hours=24)  # quote freshness (R-3; ConsensusRules default)
CACHE_SIZE = 512  # bounded reuse: a few KiB per entry
LIVE, FROZEN = "live", "frozen"
GOOD, APPROXIMATE, REJECTED = "good", "approximate", "rejected"

# Market keys of the prototype -> (production market code, outcome keys in order)
_MARKETS = (
    ("1x2", "1X2", ("home", "draw", "away")),
    ("btts", "BTTS", ("btts_yes", "btts_no")),
    ("ou25", "OU25", ("over", "under")),
)
_OUTCOME_KEY = {
    "HOME": "home",
    "DRAW": "draw",
    "AWAY": "away",
    "BTTS_YES": "btts_yes",
    "BTTS_NO": "btts_no",
    "OVER_2_5": "over",
    "UNDER_2_5": "under",
}

REASONS = {
    "no_odds": "No bookmaker prices are available for this match.",
    "missing_1x2": "A reliable Match Result (1X2) consensus is not available.",
    "missing_goals_market": (
        "A reliable goals market (Both Teams to Score or Over/Under 2.5) is not available."
    ),
    "insufficient_groups": (
        f"Fewer than {MIN_GROUPS} independent bookmaker groups price the required markets."
    ),
    "stale": "The available bookmaker prices are not recent enough.",
    "invalid_input": "The bookmaker probabilities could not be used.",
    "not_converged": "The fit did not converge.",
    "not_identified": "The bookmaker prices do not pin down both teams' estimated goals.",
    "at_boundary": "The bookmaker prices are too extreme for a reliable estimate.",
    "poor_fit": (
        "The bookmaker prices are not consistent enough with each other for a reliable estimate."
    ),
    "optimisation_failure": "The fit failed.",
    "error": "The estimate could not be calculated.",
}


def methodology_fingerprint() -> str:
    """Everything that defines the method; part of every input identity, so a change
    to the methodology can never reuse an earlier result."""
    blob = json.dumps(
        [
            FIT_VERSION,
            proto.LAMBDA_BOUNDS,
            proto.INITIAL_POINTS,
            proto.GOOD_FIT_MAX_RESIDUAL,
            proto.APPROX_FIT_MAX_RESIDUAL,
            proto.MARKETS,
            MIN_GROUPS,
            MAX_INPUT_AGE.total_seconds(),
        ]
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def quality(max_abs_residual: float) -> str:
    """The accepted bands: <= 2 pp good, <= 4 pp approximate, otherwise poor."""
    if max_abs_residual <= proto.GOOD_FIT_MAX_RESIDUAL:
        return GOOD
    if max_abs_residual <= proto.APPROX_FIT_MAX_RESIDUAL:
        return APPROXIMATE
    return "poor"


@dataclass(frozen=True)
class MarketFit:
    context: str  # live | frozen
    fixture_id: int | str
    status: str  # good | approximate | rejected
    reason: str | None = None  # REASONS key when rejected
    input_id: str = ""
    markets_used: tuple[str, ...] = ()
    lambda_home: float | None = None
    lambda_away: float | None = None
    probabilities: dict[str, float] | None = None  # fitted, seven outcomes
    consensus: dict[str, float] | None = None  # the input (actual) probabilities used
    max_abs_residual: float | None = None

    @property
    def reliable(self) -> bool:
        return self.status in (GOOD, APPROXIMATE)

    @property
    def message(self) -> str:
        return REASONS.get(self.reason or "", "")

    @property
    def estimated_goals(self) -> dict[str, float] | None:
        if not self.reliable:
            return None
        return {"home": self.lambda_home, "away": self.lambda_away}

    @property
    def stamp_version(self) -> str:
        """The first field of the Your View context stamp (no ``|`` or spaces)."""
        return f"mi{FIT_VERSION}:{self.input_id[:12]}"

    def stamp(self) -> str | None:
        """Your View context of this starting point: source and methodology version,
        input identity, fixture and the rounded baseline (``lab.model_context``
        format), or None when there is no reliable starting point."""
        if not self.reliable:
            return None
        h, a = round(self.lambda_home, 2), round(self.lambda_away, 2)
        return f"{self.stamp_version}|{self.fixture_id}|{h:.2f}|{a:.2f}"


# --------------------------------------------------------------- identity
def input_id(context: str, fixture_id, inputs: proto.MarketInputs) -> str:
    """Deterministic identity of one fit: methodology, context, fixture and the
    exact input probabilities (full float precision; never rounded estimates or a
    timestamp)."""
    blob = json.dumps(
        [
            methodology_fingerprint(),
            context,
            str(fixture_id),
            {m: [repr(float(x)) for x in v] for m, v in sorted(inputs.available().items())},
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


# ------------------------------------------------------------------ cache
_cache: OrderedDict[str, MarketFit] = OrderedDict()
_lock = threading.Lock()
_stats = {"fits": 0, "hits": 0}


def stats() -> dict[str, int]:
    """Optimisations run and cache hits since the last :func:`clear` (tests, perf)."""
    with _lock:
        return dict(_stats) | {"entries": len(_cache)}


def clear() -> None:
    with _lock:
        _cache.clear()
        _stats.update(fits=0, hits=0)


def _rejected(context, fid, reason, iid="", used=(), consensus=None) -> MarketFit:
    return MarketFit(context, fid, REJECTED, reason, iid, tuple(used), consensus=consensus)


def _consensus(inputs: proto.MarketInputs) -> dict[str, float]:
    out = {}
    for m, _, keys in _MARKETS:
        v = inputs.available().get(m)
        if v is not None:
            out.update({k: float(x) for k, x in zip(keys, v, strict=True)})
    return out


def _run(context: str, fid, inputs: proto.MarketInputs, iid: str) -> MarketFit:
    used = tuple(inputs.available())
    consensus = _consensus(inputs)
    try:
        res = proto.fit(inputs)
    except Exception:  # noqa: BLE001 - a failed fit is State C, never a crash
        return _rejected(context, fid, "error", iid, used, consensus)
    if res.status == "invalid_input":
        return _rejected(context, fid, "invalid_input", iid, used, consensus)
    if res.lambda_home is None or res.lambda_away is None:
        reason = "not_identified" if res.identified is False else "optimisation_failure"
        return _rejected(context, fid, reason, iid, used, consensus)
    if not res.identified:
        return _rejected(context, fid, "not_identified", iid, used, consensus)
    if not res.converged:  # CP1 report §7: rejected in production
        return _rejected(context, fid, "not_converged", iid, used, consensus)
    if res.at_boundary:
        return _rejected(context, fid, "at_boundary", iid, used, consensus)
    if res.status not in ("good_fit", "approximate_fit"):
        reason = "poor_fit" if res.status == "poor_fit" else "optimisation_failure"
        return _rejected(context, fid, reason, iid, used, consensus)
    lh, la = float(res.lambda_home), float(res.lambda_away)
    try:
        probs = gm.markets(lh, la)
    except ValueError:
        return _rejected(context, fid, "optimisation_failure", iid, used, consensus)
    if not all(math.isfinite(p) and 0.0 < p < 1.0 for p in probs.values()):
        return _rejected(context, fid, "optimisation_failure", iid, used, consensus)
    status = quality(res.max_abs_residual)
    return MarketFit(
        context,
        fid,
        status,
        None,
        iid,
        used,
        lh,
        la,
        probs,
        consensus,
        float(res.max_abs_residual),
    )


def fit_inputs(context: str, fixture_id, inputs: proto.MarketInputs) -> MarketFit:
    """Fit (or reuse) one fixture's validated inputs."""
    iid = input_id(context, fixture_id, inputs)
    with _lock:
        hit = _cache.get(iid)
        if hit is not None:
            _cache.move_to_end(iid)
            _stats["hits"] += 1
            return hit
    result = _run(context, fixture_id, inputs, iid)
    with _lock:
        _stats["fits"] += 1
        _cache[iid] = result
        _cache.move_to_end(iid)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def _rule(present: dict[str, tuple], problems: dict[str, str]) -> str | None:
    """R-3: 1X2 plus a goals market. ``problems`` says why a market is missing."""
    if not present and not problems:
        return "no_odds"
    if "1x2" not in present:
        return problems.get("1x2", "missing_1x2")
    if "btts" not in present and "ou25" not in present:
        for why in ("stale", "insufficient_groups"):
            if why in (problems.get("btts"), problems.get("ou25")):
                return why
        return "missing_goals_market"
    return None


# --------------------------------------------------------------- live fits
def live_fit(fixture_id, odds_view) -> MarketFit:
    """State B for All Upcoming Fixtures and general Match Lab research, from the
    latest display consensus (``app.data.OddsView``): only markets that are fresh
    now and priced by at least three independent bookmaker groups."""
    from diski9.api_football.markets import Market, Outcome

    markets = getattr(odds_view, "markets", None)
    if not markets or not getattr(odds_view, "league_has_odds", True):
        return _rejected(LIVE, fixture_id, "no_odds")
    order = {
        "1x2": (Market.MATCH_RESULT, (Outcome.HOME, Outcome.DRAW, Outcome.AWAY)),
        "btts": (Market.BTTS, (Outcome.BTTS_YES, Outcome.BTTS_NO)),
        "ou25": (Market.OVER_UNDER_25, (Outcome.OVER_25, Outcome.UNDER_25)),
    }
    present, problems = {}, {}
    for key, (market, outcomes) in order.items():
        dm = markets.get(market)
        if dm is None or dm.status == "unavailable":
            continue
        if dm.status != "fresh":
            problems[key] = "stale"
            continue
        mc = dm.consensus
        if mc is None or mc.sources < MIN_GROUPS or not dm.challenge_eligible:
            problems[key] = "insufficient_groups"
            continue
        adj = dm.implied.margin_adjusted if dm.implied else None
        if not adj or any(o not in adj for o in outcomes):
            continue
        present[key] = tuple(float(adj[o]) for o in outcomes)
    reason = _rule(present, problems)
    inputs = proto.MarketInputs(present.get("1x2"), present.get("btts"), present.get("ou25"))
    if reason:
        return _rejected(LIVE, fixture_id, reason, used=tuple(present))
    return fit_inputs(LIVE, fixture_id, inputs)


# ------------------------------------------------------------- frozen fits
def frozen_inputs(
    outcomes: Iterable, fixture_id, snapshot_at: datetime
) -> tuple[proto.MarketInputs, str | None]:
    """Fitting inputs from one fixture's frozen round-sheet outcomes (actual frozen
    margin-adjusted probabilities). Freshness is judged at ``snapshot_at``, never now."""
    by_market: dict[str, dict[str, object]] = {}
    for o in outcomes:
        if o.fixture_id != fixture_id:
            continue
        by_market.setdefault(str(o.market), {})[_OUTCOME_KEY.get(str(o.outcome), "")] = o
    present, problems = {}, {}
    for key, code, keys in _MARKETS:
        got = by_market.get(code) or {}
        if not got:
            continue
        if any(k not in got for k in keys):
            continue  # an incomplete market is not a distribution
        rows = [got[k] for k in keys]
        if min(int(r.bookmaker_groups or 0) for r in rows) < MIN_GROUPS:
            problems[key] = "insufficient_groups"
            continue
        seen = [r.latest_observation_at for r in rows]
        if any(t is None or t > snapshot_at or snapshot_at - t > MAX_INPUT_AGE for t in seen):
            problems[key] = "stale"
            continue
        present[key] = tuple(float(r.market_probability) for r in rows)
    inputs = proto.MarketInputs(present.get("1x2"), present.get("btts"), present.get("ou25"))
    return inputs, _rule(present, problems)


def frozen_fit(snapshot, fixture_id) -> MarketFit:
    """State B for the Weekly Challenge, from the round snapshot's frozen market
    probabilities only (OD-2). Deterministic: the same snapshot always gives the same
    result, whatever the live odds or today's date."""
    inputs, reason = frozen_inputs(snapshot.outcomes, fixture_id, snapshot.snapshot_at)
    if reason:
        return _rejected(FROZEN, fixture_id, reason, used=tuple(inputs.available()))
    return fit_inputs(FROZEN, fixture_id, inputs)


def frozen_baseline(snapshot, fixture_id) -> tuple[str, tuple[float, float]] | None:
    """The frozen starting point of a round fixture: ``("model", eg)`` when the
    snapshot froze independent estimated goals, ``("market", λ)`` for a reliable
    frozen market-implied fit, otherwise None (State C)."""
    try:
        f = snapshot.fixture(fixture_id)
    except KeyError:
        return None
    if f.estimated_goals is not None:
        return "model", tuple(f.estimated_goals)
    mf = frozen_fit(snapshot, fixture_id)
    if not mf.reliable:
        return None
    return "market", (mf.lambda_home, mf.lambda_away)


def implied_probabilities(snapshot, selections: Iterable) -> dict[tuple, float]:
    """{outcome key: frozen market-implied probability} for the given selections that
    have no independent Diski 9 probability and a reliable frozen fit. Fits only
    those selections' fixtures (never the whole pool)."""
    out: dict[tuple, float] = {}
    fits: dict[object, MarketFit] = {}
    for o in selections:
        if o.model_probability is not None:
            continue
        mf = fits.get(o.fixture_id)
        if mf is None:
            mf = fits[o.fixture_id] = frozen_fit(snapshot, o.fixture_id)
        key = _OUTCOME_KEY.get(str(o.outcome))
        if mf.reliable and key in (mf.probabilities or {}):
            out[o.key] = float(mf.probabilities[key])
    return out


def payload(mf: MarketFit) -> Mapping:
    """The Match Lab starting point for a reliable fit (``r["_starting_point"]``)."""
    return {
        "source": "market",
        "label": SOURCE_LABEL,
        "quality": mf.status,
        "estimated_goals": mf.estimated_goals,
        "probabilities": dict(mf.probabilities or {}),
        "consensus": dict(mf.consensus or {}),
        "max_abs_residual": mf.max_abs_residual,
        "markets_used": mf.markets_used,
        "stamp": mf.stamp(),
        "context": mf.context,
    }
