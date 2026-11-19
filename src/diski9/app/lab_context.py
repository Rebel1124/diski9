"""Which analytical context the Match Lab shows (Phase 6C.3, approved at the
checkpoint), and the matching data, store key and saved Your View.

* **Frozen** - a fixture opened from the Weekly Challenge (Screener universe
  "Weekly Challenge") that is on the published round's snapshot: the baseline is
  the snapshot's frozen estimated goals (and the probabilities calculated from
  them by Goal Model 1.0's own ``markets``), never the latest estimate.
* **Live** - everything else (All Upcoming Fixtures): the latest available data.

Each context has its own Your View: in the browser store under its own key
(``"<fixture>"`` live, ``"r:<round>:<fixture>"`` frozen) and, for signed-in
participants, in its own database row (``LiveContext`` / ``RoundContext``).
Changing or resetting one never touches the other.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from diski9.screener import goal_model as gm


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
    g["estimated_goals"] = {"home": h, "away": a}
    g["probabilities"] = gm.markets(h, a)
    out["_model_context"] = model_context
    return out


def resolve(service, data, fixture_id, universe: str | None) -> LabContext | None:
    if not fixture_id:
        return None
    r, _, _ = data.detail(fixture_id)
    if r is None:
        return None
    fid = int(fixture_id)
    snap = service.snapshot("live") if universe == "challenge" else None
    if snap is not None and not snap.is_demo and (r.get("goal_model") or {}).get("available"):
        try:
            fx = snap.fixture(fid)
        except KeyError:
            fx = None
        if fx is not None and fx.estimated_goals is not None:
            rv = service.round_view()
            version = rv.model_version if rv else f"goal-model-{gm.GOAL_MODEL_VERSION}"
            version = (version or "").removeprefix("goal-model-")
            h, a = (round(x, 2) for x in fx.estimated_goals)
            stamp = f"{version}|{fid}|{h:.2f}|{a:.2f}"
            fr = frozen_payload(r, fx.estimated_goals, stamp)
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
    live = dict(r)
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
