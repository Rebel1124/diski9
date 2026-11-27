"""Your View persistence for the Match Lab (Phase 6C.3, Stage F).

For a signed-in participant the account holds one current numerical state per
analytical context (live, or a published round's frozen snapshot); the browser
store ``lab-store`` keeps the page's working copy under the context's key, with:

* ``_owner``: the opaque owner marker of the account the copy belongs to (guest
  work has none and is left alone until the guest-work choice is made);
* ``_ver``: {key: saved version} for optimistic concurrency;
* ``_tab``: a random per-tab token so this tab's own saves are ordered.

Nothing here changes the Match Lab's numbers or limits.
"""

from __future__ import annotations

import secrets
import time

from . import persist


def _owner() -> str:
    from diski9.backend.auth.web import owner_tag

    return owner_tag()


def has_guest_work(lab: dict | None) -> bool:
    lab = lab or {}
    return not lab.get("_owner") and any(not k.startswith("_") for k in lab)


def load(service, lab: dict | None, lc) -> dict | None:
    """A copy of ``lab`` with the account's saved state for this context, or None
    when nothing applies (guest, no backend, unsaved guest work pending)."""
    from diski9.backend.services import your_view as yv

    from .. import lab as labmod
    from .. import lab_context

    p = persist.participant(service)
    if p is None:
        return None
    lab = dict(lab or {})
    if has_guest_work(lab):
        return None
    if lab.get("_owner") not in (None, _owner()):
        lab = {}
    ctx = lab_context.service_context(lc)
    if ctx is None:
        return None
    try:
        view = yv.get_your_view(service.backend.engine, p, ctx)
    except Exception:  # noqa: BLE001 - the page still works from the tab copy
        return None
    ver = dict(lab.get("_ver") or {})
    ver[lc.key] = view.version
    lab = labmod.store_adjustment(lab, lc.key, lc.r, view.state if view.status == yv.ACTIVE
                                  else None)  # fmt: skip
    was = dict(lab.get(labmod.WAS_KEY) or {})  # saved numbers for another starting point
    if view.status == yv.INCOMPATIBLE and view.stored_context:
        was[lc.key] = view.stored_context
    else:
        was.pop(lc.key, None)
    if was:
        lab[labmod.WAS_KEY] = was
    else:
        lab.pop(labmod.WAS_KEY, None)
    lab["_ver"] = ver
    lab["_owner"] = _owner()
    return lab


def save(service, lab: dict, lc, state: dict) -> tuple[dict, str | None]:
    """Save this context's numbers for a participant; (lab, problem message)."""
    from diski9.backend.services import your_view as yv
    from diski9.backend.services.common import ServiceError, VersionConflict, Writer

    from .. import lab_context

    p = persist.participant(service)
    if p is None or has_guest_work(lab):
        return lab, None
    ctx = lab_context.service_context(lc)
    if ctx is None:
        return lab, None
    lab = dict(lab)
    if not lab.get("_tab"):
        lab["_tab"] = secrets.token_urlsafe(18)
    ver = dict(lab.get("_ver") or {})
    try:
        saved = yv.save_your_view(
            service.backend.engine,
            p,
            ctx,
            state,
            expected_version=int(ver.get(lc.key, 0)),
            writer=Writer(lab["_tab"], time.time_ns() // 1000),
        )
    except VersionConflict:
        return lab, (
            "Your View for this match was changed in another tab or on another device, so "
            "this change is not saved. Open the match again to load the saved numbers."
        )
    except ServiceError as exc:
        return lab, exc.message
    ver[lc.key] = saved.version
    lab["_ver"] = ver
    lab["_owner"] = _owner()
    return lab, None


def load_round(service, lab: dict | None) -> dict | None:
    """All frozen-context states of the published round for a participant (so the
    Weekly Challenge 'Your View' source works on any device)."""
    from diski9.backend.services import your_view as yv

    from .. import lab as labmod
    from .. import lab_context

    p = persist.participant(service)
    found = persist.backend_of(service).published() if p else None
    if p is None or found is None:
        return None
    lab = dict(lab or {})
    if has_guest_work(lab):
        return None
    if lab.get("_owner") not in (None, _owner()):
        lab = {}
    view, snap = found
    from diski9.screener import market_fit

    # frozen baselines: independent estimated goals, or a reliable frozen market fit -
    # only for matches with a saved Your View (never a fit across the whole pool)
    try:
        saved = yv.saved_round_fixtures(service.backend.engine, p, view.id)
    except Exception:  # noqa: BLE001
        return None
    bases = {
        f.fixture_id: market_fit.frozen_baseline(snap, f.fixture_id)
        for f in snap.fixtures
        if f.fixture_id in saved
    }
    ctxs = {fid: yv.RoundContext(view.id, fid) for fid, base in bases.items() if base is not None}
    try:
        got = yv.get_many(service.backend.engine, p, list(ctxs.values()))
    except Exception:  # noqa: BLE001
        return None
    ver = dict(lab.get("_ver") or {})
    for fid, ctx in ctxs.items():
        v = got.get(ctx)
        if v is None:
            continue
        key = lab_context.frozen_key(view.code, fid)
        h, a = bases[fid][1]
        stamp = yv.frozen_context(snap, fid, view.model_version)
        r = {"_model_context": stamp, "fixture": {"id": fid},
             "goal_model": {"estimated_goals": {"home": h, "away": a}}}  # fmt: skip
        lab = labmod.store_adjustment(lab, key, r, v.state if v.status == yv.ACTIVE else None)
        ver[key] = v.version
    lab["_ver"] = ver
    lab["_owner"] = _owner()
    return lab
