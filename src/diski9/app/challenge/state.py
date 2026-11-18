"""Participant state for the Weekly Challenge prototype: one source of truth.

The only store of participant state is the browser-session store ``ch-session``
(``sessionStorage``: this browser tab only; it survives page navigation, a page
refresh and a restart of the app server, and is gone when the tab is closed). It
is never sent to other users and never kept on the server, so a prototype
"submission" is browser-scoped and non-authoritative until Phase 6C introduces
server-side round records.

Shape (``DEFAULT_STATE``):

* ``mode`` / ``fp`` / ``selections`` / ``meta`` / ``notes`` / ``stage`` - the
  **working draft** for the active mode, tied to one round snapshot (``fp``).
* ``submitted`` - the **confirmed submission** for the active mode: a frozen
  record that is only written by Submit and only removed by Withdraw.
* ``parked`` - the draft and submission of the other mode (demo vs live), so the
  two are isolated and switching mode never mixes or drops either.
* ``withdrawn`` - a note of the last withdrawal (round and time), for display.

Every read and every write goes through :func:`reconcile`, which brings a stored
state up to date with the current round snapshot **eagerly and identically** on
both paths. (Phase 6B.1 reconciled only on the next write, so after a server
restart rebuilt the live snapshot with a new fingerprint the pages showed an
empty draft and "not confirmed", and the next unrelated click resurrected the old
portfolio. See ``docs/weekly_challenge_ui.md``.)
"""

from __future__ import annotations

from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.structured import selection_blocks

from .service import parse_key

STAGES = (("build", "Build portfolio"), ("review", "Review & Submit"))
DRAFT_KEYS = ("fp", "selections", "meta", "notes", "stage")
DEFAULT_STATE = {
    "mode": None,
    "fp": None,
    "selections": [],
    "stage": "build",
    "submitted": None,
    "meta": {},
    "notes": [],
    "modal": None,
    "parked": {},
    "withdrawn": None,
}


def normal_state(state: dict | None) -> dict:
    """A complete, independent copy of ``state`` with defaults filled in (pure)."""
    s = dict(DEFAULT_STATE)
    s.update(state or {})
    s["selections"] = list(s.get("selections") or [])
    s["meta"] = dict(s.get("meta") or {})
    s["notes"] = list(s.get("notes") or [])
    s["parked"] = dict(s.get("parked") or {})
    if s.get("stage") not in {k for k, _ in STAGES}:
        s["stage"] = "build"  # Phase 6B "overview"/"analyse" steps no longer exist
    return s


def mode_key(snap_or_mode) -> str:
    if snap_or_mode is None or isinstance(snap_or_mode, str):
        return "demo" if snap_or_mode == "demo" else "live"
    return "demo" if snap_or_mode.is_demo else "live"


def migrate_draft(service, s, snap) -> tuple[list[str], list[dict]]:
    """Revalidate a draft against a different snapshot. Selections whose outcome, odds
    and market chance are unchanged and still fit are kept; every other selection is
    taken out of the draft and listed for the participant to review. Nothing is ever
    moved to different odds or probabilities silently."""
    kept, notes, meta = [], [], s.get("meta") or {}
    for k in s["selections"]:
        o = snap.outcome(parse_key(k))
        m = meta.get(k)
        label = (m or {}).get("label", k)
        if o is None:
            notes.append({"label": label, "reason": "no longer on the round sheet"})
            continue
        if m and (
            m.get("odds") != str(o.reference_odds) or m.get("p") != repr(o.market_probability)
        ):
            notes.append(
                {
                    "label": label,
                    "reason": f"odds or market chance changed (odds "
                    f"{m.get('odds')} → {o.reference_odds})",
                }
            )
            continue
        blocks = selection_blocks(
            service.outcomes_for(snap, kept), snap.outcomes, snap.snapshot_at, DEFAULT_CONFIG
        )
        if blocks.get(o.key) is not None:
            notes.append({"label": label, "reason": "no longer eligible or no longer fits"})
            continue
        kept.append(k)
    return kept, notes


def submission_for(state: dict, snap) -> dict | None:
    """The confirmed submission if it belongs to this snapshot's round and mode."""
    sub = state.get("submitted")
    if not sub or snap is None:
        return None
    if sub.get("round_id") != snap.round_id or sub.get("mode") != mode_key(snap):
        return None
    return sub


def same_portfolio(sub: dict | None, sels: list[str]) -> bool:
    """True when the working draft is exactly the confirmed portfolio (order-free)."""
    return bool(sub) and sorted(sub.get("selections") or []) == sorted(sels)


def reconcile(service, state: dict | None) -> dict:
    """The stored state brought up to date with the current snapshot (pure; the
    same function is used by every page render and by every action):

    1. a confirmed submission from the other mode is parked, never shown in this one;
    2. a draft from an older snapshot of the same round is revalidated
       (:func:`migrate_draft`): unchanged picks are kept, changed ones are listed;
    3. a submission or draft from an earlier round is closed (the submission is
       kept as ``earlier`` for display only; the draft is cleared).
    """
    s = normal_state(state)
    mode = s["mode"] if s.get("mode") else None
    if mode is None and not service.availability("live").playable:
        return s
    snap = service.snapshot(mode or "live")
    if snap is None:
        return s
    mk = mode_key(snap)
    sub = s.get("submitted")
    if sub and sub.get("mode") and sub["mode"] != mk:
        other = dict(s["parked"].get(sub["mode"]) or {})
        other.setdefault("submitted", sub)
        s["parked"] = {**s["parked"], sub["mode"]: other}
        s["submitted"] = None
    sub = s.get("submitted")
    if sub and sub.get("round_id") != snap.round_id:
        s["earlier"] = sub
        s["submitted"] = None
    if s.get("fp") != snap.fingerprint:
        if s["selections"]:
            same_round = (s.get("round_id") in (None, snap.round_id)) and mode_key(
                s.get("mode")
            ) == mk
            if same_round:
                kept, notes = migrate_draft(service, s, snap)
            else:
                kept, notes = [], []
            s["selections"] = kept
            s["notes"] = [*s["notes"], *notes]
            s["meta"] = {k: v for k, v in s["meta"].items() if k in kept}
        s["fp"] = snap.fingerprint
    s["round_id"] = snap.round_id
    return s


def switch_mode(service, state: dict, new_mode: str | None) -> dict:
    """Park the active mode's draft and submission; restore the other mode's."""
    s = normal_state(state)
    cur = mode_key(s.get("mode"))
    target = mode_key(new_mode)
    parked = dict(s["parked"])
    parked[cur] = {k: s.get(k) for k in (*DRAFT_KEYS, "submitted", "round_id")}
    restored = dict(parked.pop(target, None) or {})
    new = normal_state(
        {
            **{k: v for k, v in restored.items() if k in (*DRAFT_KEYS, "submitted", "round_id")},
            "mode": "demo" if target == "demo" else None,
            "parked": parked,
            "withdrawn": s.get("withdrawn"),
        }
    )
    return reconcile(service, new)
