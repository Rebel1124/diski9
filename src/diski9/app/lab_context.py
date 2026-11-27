"""Which analytical context the Match Lab shows (Phase 6C.3, approved at the
checkpoint), and the matching data, store key and saved Your View.

* **Frozen** - a fixture opened from the Weekly Challenge (Screener universe
  "Weekly Challenge") that is on the published round's snapshot: the baseline is
  the snapshot's frozen estimated goals (and the probabilities calculated from
  them by Goal Model 1.0's own ``markets``), never the latest estimate.
* **Live** - everything else (All Upcoming Fixtures): the latest available data.

When the context has no independent Goal Model prediction, its starting point is a
market-implied fit (Phase 8 State B; ``screener.market_fit``) from that context's
own market data - live: the latest fresh consensus; frozen: the snapshot's frozen
probabilities, never later odds - attached as ``r["_starting_point"]``. Without a
reliable fit the reason is attached instead (State C). The fit runs here, only for
the fixture being opened.

Each context has its own Your View: in the browser store under its own key
(``"<fixture>"`` live, ``"r:<round>:<fixture>"`` frozen) and, for signed-in
participants, in its own database row (``LiveContext`` / ``RoundContext``).
Changing or resetting one never touches the other.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from diski9.screener import goal_model as gm
from diski9.screener import market_fit


@dataclass
class LabContext:
    kind: str  # live | round
    fixture_id: int
    key: str  # browser-store key
    r: dict | None  # analysis payload with the baseline of this context
    round_code: str | None = None
    round_id: object = None  # UUID of the published round (persistent mode)
    frozen_at: object = None  # snapshot time (frozen context)


def frozen_key(round_code: str, fixture_id) -> str:
    return f"r:{round_code}:{fixture_id}"


def frozen_payload(r: dict, estimated_goals: tuple[float, float], model_context: str) -> dict:
    """A copy of the live payload whose baseline is the frozen one."""
    out = copy.deepcopy(r)
    g = out["goal_model"]
    h, a = estimated_goals
    g["available"] = True  # the frozen baseline, whatever the live model says now
    g["estimated_goals"] = {"home": h, "away": a}
    g["probabilities"] = gm.markets(h, a)
    out["_model_context"] = model_context
    out.pop("_starting_point", None)
    return out


FROZEN_NO_MODEL = (
    "No independent Diski 9 prediction was frozen with this Weekly Challenge snapshot."
)


def frozen_market_payload(r: dict, snap, fid: int) -> dict:
    """A copy of the live payload for a round fixture frozen without independent
    estimated goals: the frozen market-implied fit (State B) or, without a reliable
    fit, no starting point (State C). The live model is never shown in this context."""
    out = copy.deepcopy(r)
    out["goal_model"] = {"available": False, "message": FROZEN_NO_MODEL}
    out.pop("_starting_point", None)
    mf = market_fit.frozen_fit(snap, fid)
    if mf.reliable:
        out["_starting_point"] = market_fit.payload(mf)
        out["_model_context"] = mf.stamp()
    else:
        out["_starting_point_unavailable"] = mf.message
    return out


def with_live_starting_point(r: dict, ov) -> dict:
    """The live payload, with the market-implied starting point when the Goal Model
    has no prediction (fitted on demand from the latest fresh consensus)."""
    if (r.get("goal_model") or {}).get("available"):
        return r
    out = dict(r)
    mf = market_fit.live_fit(out["fixture"]["id"], ov)
    if mf.reliable:
        out["_starting_point"] = market_fit.payload(mf)
    else:
        out["_starting_point_unavailable"] = mf.message
    return out


def resolve(service, data, fixture_id, universe: str | None, published=None) -> LabContext | None:
    """The analytical context of a fixture. In the challenge universe, the frozen
    payload, round code, round id, model version and stamp all come from **one**
    published ``(round view, snapshot)`` pair: ``published`` when the caller already
    validated one (``resolve_target``), otherwise a single
    :meth:`ChallengeService.published_pair` read made here."""
    if not fixture_id:
        return None
    r, ov, _ = data.detail(fixture_id)
    if r is None:
        return None
    fid = int(fixture_id)
    rv, snap = None, None
    if universe == "challenge":
        rv, snap = published if published is not None else service.published_pair()
    if snap is not None and not snap.is_demo:
        try:
            fx = snap.fixture(fid)
        except KeyError:
            fx = None
        if fx is not None:
            if fx.estimated_goals is not None:
                version = rv.model_version if rv else f"goal-model-{gm.GOAL_MODEL_VERSION}"
                version = (version or "").removeprefix("goal-model-")
                h, a = (round(x, 2) for x in fx.estimated_goals)
                stamp = f"{version}|{fid}|{h:.2f}|{a:.2f}"
                fr = frozen_payload(r, fx.estimated_goals, stamp)
            else:
                fr = frozen_market_payload(r, snap, fid)
            fr["_context"] = {
                "kind": "round",
                "round": snap.round_id,
                "frozen_at": snap.snapshot_at,
            }
            return LabContext(
                "round",
                fid,
                frozen_key(snap.round_id, fid),
                fr,
                snap.round_id,
                rv.id if rv else None,
                snap.snapshot_at,
            )
    live = with_live_starting_point(r, ov)
    live = live if live is not r else dict(r)
    live["_context"] = {"kind": "live", "updated_at": data.snapshot().cache_calculated_at}
    return LabContext("live", fid, str(fid), live)


def service_context(ctx: LabContext):
    """The backend context for a participant's saved Your View."""
    from diski9.backend.services import your_view as yv

    from . import lab

    if ctx.kind == "round" and ctx.round_id is not None:
        return yv.RoundContext(ctx.round_id, ctx.fixture_id)
    if ctx.kind == "live":
        return yv.LiveContext(ctx.fixture_id, lab.model_context(ctx.r))
    return None


# ------------------------------------------------- Phase 8 CP3A-3: Match Lab targets
NO_TARGET, INVALID, MISSING, CHALLENGE_GONE = "none", "invalid", "missing", "challenge_gone"


def resolve_target(service, data, target) -> tuple[LabContext | None, str | None]:
    """The analytical context for a Match Lab target, or ``(None, reason)``.

    A target names the fixture and the context it was opened from (``ctx``):
    ``research`` resolves against the latest data; ``challenge`` only against the
    **same** published round (``round``) and, when recorded, the same snapshot
    (``fp``), and only to its frozen context. A challenge match whose round or
    snapshot is no longer the published one fails safely: it is never silently
    analysed with latest data, nor attached to another round."""
    from .links import CHALLENGE, CONTEXTS, RESEARCH

    if not target:
        return None, NO_TARGET
    fid, ctx = target.get("fixture"), target.get("ctx")
    if target.get("invalid") or not isinstance(fid, int) or ctx not in CONTEXTS:
        return None, INVALID
    if ctx == RESEARCH:
        lc = resolve(service, data, fid, "all")
        return (lc, None) if lc is not None else (None, MISSING)
    assert ctx == CHALLENGE
    pair = service.published_pair()  # one read: validated and analysed together
    snap = pair[1]
    if (snap is None or snap.is_demo or snap.round_id != target.get("round")
            or (target.get("fp") and snap.fingerprint != target["fp"])):  # fmt: skip
        return None, CHALLENGE_GONE
    try:
        snap.fixture(fid)
    except KeyError:
        return None, CHALLENGE_GONE
    lc = resolve(service, data, fid, "challenge", published=pair)
    if lc is None:  # the snapshot holds it, but the football store has no analysis for it
        return None, MISSING
    if lc.kind != "round" or lc.round_code != target.get("round"):  # never another round
        return None, CHALLENGE_GONE
    return lc, None
