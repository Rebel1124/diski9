"""Bridge between the Dash pages and the competition services (Phase 6C.3, Stage F).

For signed-in participants the backend is authoritative for the published round,
the saved draft, the entry and the numerical Your View. The browser stores
(``ch-session``, ``lab-store``) only hold the page's working copy:

* **Hydration** (:func:`hydrate`): on every page load or route change the working
  copy is refreshed from the database unless it holds changes that could not be
  saved (``acct.dirty``), which are kept and flagged, never silently replaced.
* **Saving** (:func:`save_selections`): every change to the predictions is saved
  in the same request that made it, with the draft version the page holds and a
  per-tab writer token, so a superseded request from this tab can never replace
  newer work and another tab or device gets a conflict instead of a lost update.
  "Saved" is shown only after the database confirmed the write.
* **Entries** go through :mod:`diski9.backend.services.entries` (explicit
  confirm, replace, withdraw; the idempotency key is derived from the tab and the
  versions shown, so a double click is one submission).

Guests keep the Phase 6B browser-tab prototype (now on the published round), and
cannot confirm entries in a real round.
"""

from __future__ import annotations

import secrets
import threading
import time
from datetime import UTC
from uuid import UUID

from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.roundsheet import RoundAvailability, RoundStatus, assess_round

from .service import key_str, parse_key


class Backend:
    """The published round from the competition database (cached briefly per
    process: the snapshot itself is immutable; the round status is re-read every
    few seconds so a lock is noticed)."""

    def __init__(self, engine, *, show_development: bool = False, ttl: float = 3.0):
        self.engine = engine
        self.show_development = show_development
        self.ttl = ttl
        self.error = False
        self._lock = threading.Lock()
        self._at = 0.0
        self._found = None

    def published(self):
        with self._lock:
            if time.monotonic() - self._at < self.ttl:
                return self._found
        from diski9.backend.services import rounds as rsvc

        try:
            view = rsvc.current_round(self.engine, include_development=self.show_development)
            found = (view, rsvc.published_snapshot(self.engine, view.id)) if view else None
            error = False
        except Exception:  # noqa: BLE001 - shown as "temporarily unavailable"
            found, error = None, True
        with self._lock:
            self._found, self.error, self._at = found, error, time.monotonic()
        return found

    def refresh(self) -> None:
        with self._lock:
            self._at = 0.0

    def availability(self, now) -> RoundAvailability:
        found = self.published()
        if found is None:
            if self.error:
                return RoundAvailability(
                    RoundStatus.NO_ROUND,
                    "Competition data is temporarily unavailable",
                    "Please try again in a moment. The Match Lab and statistics still work.",
                    None,
                )
            return RoundAvailability(
                RoundStatus.NO_ROUND,
                "No round is open",
                "A new round opens when the published fixtures meet every rule.",
                None,
            )
        view, snap = found
        avail = assess_round(snap, now, DEFAULT_CONFIG)
        if view.status != "open":
            return RoundAvailability(
                RoundStatus.LOCKED,
                "Round locked",
                "The deadline has passed and entries are locked. Results come with "
                "settlement, which is not available yet.",
                avail.report,
            )
        if avail.status is RoundStatus.LOCKED:
            return RoundAvailability(
                RoundStatus.LOCKED,
                "Deadline passed",
                "The submission deadline has passed; entries are being locked.",
                avail.report,
            )
        return avail


# ------------------------------------------------------------------ who
def backend_of(service):
    return getattr(service, "backend", None)


def participant(service):
    """The signed-in participant who may save work, or None (guest, set-up
    incomplete, accounts not configured)."""
    if backend_of(service) is None:
        return None
    from diski9.backend.auth.permissions import Capability, can
    from diski9.backend.auth.web import current_principal

    p = current_principal()
    return p if can(p, Capability.PERSIST_OWN_ANALYSIS) else None


def signed_in_label(service) -> str | None:
    """'guest' / 'setup' when the person cannot save work, else None."""
    if backend_of(service) is None:
        return None
    from diski9.backend.auth.web import current_principal

    p = current_principal()
    if not p.is_authenticated:
        return "guest"
    return None if participant(service) else "setup"


def writer(state: dict):
    from diski9.backend.services.common import Writer

    return Writer(state["tab"], time.time_ns() // 1000)


def ensure_tab(state: dict) -> dict:
    if not state.get("tab"):
        state["tab"] = secrets.token_urlsafe(18)
    return state


def _owner() -> str:
    from diski9.backend.auth.web import owner_tag

    return owner_tag()


# ------------------------------------------------------------------ entries -> page
def submitted_record(service, view, snap, entry) -> dict | None:
    """The page's confirmed-entry record for an active persistent entry (values
    from the stored submission; estimates from the engine on the frozen snapshot)."""
    sub = entry.current
    if sub is None:
        return None
    keys = sub.keys
    evs = service.evaluate(snap, keys)
    picks = []
    for s in sub.selections:
        o = snap.outcome((s["fixture_id"], s["market"], s["outcome"]))
        fx = snap.fixture(s["fixture_id"])
        from . import components as c

        picks.append(
            {
                "key": key_str(o.key),
                "bucket": s["bucket"],
                "match": f"{fx.home} v {fx.away}",
                "outcome": c.outcome_text(o),
                "odds": s["consensus_odds"],
                "market": s["market_prob"],
                "model": s["model_prob"],
                "personal": None,
                "personal_adjusted": False,
            }
        )
    estimates = {}
    if evs is not None:
        for name, ev in zip(("market", "model"), evs, strict=True):
            estimates[name] = {
                "p_recover": ev.p_recover,
                "p_zero": ev.p_zero,
                "expected": ev.expected_gross,
            }
    return {
        "at": sub.submitted_at.astimezone(UTC).isoformat(),
        "round_id": view.code,
        "fp": snap.fingerprint,
        "snapshot_at": snap.snapshot_at.isoformat(),
        "mode": "live",
        "config": view.config_version,
        "selections": keys,
        "picks": picks,
        "estimates": estimates,
        "max_gross": str(sub.max_gross),
        "p_recover_market": sub.p_recover_market,
        "p_recover_model": sub.p_recover_model,
        "expected_market": sub.expected_gross_market,
        "persistent": True,
        "version": sub.version,
    }


def _meta_for(snap, keys) -> dict:
    from . import components as c

    out = {}
    for k in keys:
        o = snap.outcome(parse_key(k))
        if o is None:
            continue
        fx = snap.fixture(o.fixture_id)
        out[k] = {
            "odds": str(o.reference_odds),
            "p": repr(o.market_probability),
            "label": f"{fx.home} v {fx.away}: {c.outcome_text(o)}",
        }
    return out


def has_guest_work(state: dict | None) -> bool:
    """Predictions made as a guest in this tab (no account marker yet): never
    replaced by account data until the person has chosen to keep or discard them."""
    s = state or {}
    return bool(s.get("selections")) and not (s.get("acct") or {}).get("owner")


def hydrate(service, state: dict | None, *, force: bool = False) -> dict | None:
    """The working copy refreshed from the account (see module notes). Returns
    None when nothing applies (guest, no backend, no round, or guest work waiting
    for the keep/discard choice)."""
    p = participant(service)
    if p is None or (has_guest_work(state) and not force):
        return None
    found = backend_of(service).published()
    s = dict(state or {})
    owner = _owner()
    acct = dict(s.get("acct") or {})
    if acct.get("owner") not in (None, owner):  # another account's leftovers
        s, acct = {}, {}
    ensure_tab(s)
    if found is None:
        s["acct"] = {"owner": owner}
        return s
    view, snap = found
    from diski9.backend.services import drafts, entries

    d = drafts.get_draft(service.backend.engine, p, view.id)
    e = entries.get_entry(service.backend.engine, p, view.id)
    same_round = acct.get("round") == str(view.id)
    keep_local = same_round and acct.get("dirty") and not force
    if not keep_local:
        s.update(
            mode=None,
            selections=d.keys,
            fp=snap.fingerprint,
            round_id=view.code,
            meta=_meta_for(snap, d.keys),
        )
        if not same_round:
            s.update(stage="build", notes=[], modal=None, confirm=None)
        acct.update(dirty=False, status="saved" if d.version else None)
    acct.update(
        owner=owner,
        round=str(view.id),
        code=view.code,
        dv=d.version,
        ev=e.version,
        saved=d.keys,
        entry=e.state,
        locked=e.locked,
    )
    s["acct"] = acct
    s["submitted"] = submitted_record(service, view, snap, e) if e.active else None
    last_withdrawal = next((h for h in reversed(e.history) if h.kind == "withdrawn"), None)
    s["withdrawn"] = (
        {
            "round_id": view.code,
            "mode": "live",
            "at": last_withdrawal.at.astimezone(UTC).isoformat(),
            "confirmed_at": None,
        }
        if e.state == "withdrawn" and last_withdrawal
        else None
    )
    return s


def round_uuid(state: dict) -> UUID | None:
    rid = (state.get("acct") or {}).get("round")
    return UUID(rid) if rid else None


def save_selections(service, state: dict) -> tuple[dict, dict | None]:
    """Save the working copy's predictions (participant, live round). Returns the
    state with the save status and a flash for problems (or None)."""
    from diski9.backend.services import drafts
    from diski9.backend.services.common import (
        RoundClosed,
        ServiceError,
        ValidationFailed,
        VersionConflict,
    )

    p = participant(service)
    rid = round_uuid(state)
    if p is None or rid is None or state.get("mode") == "demo":
        return state, None
    acct = dict(state.get("acct") or {})
    if list(state.get("selections") or []) == list(acct.get("saved") or []):
        acct.update(dirty=False)
        state["acct"] = acct
        return state, None
    ensure_tab(state)
    try:
        d = drafts.save_draft(
            service.backend.engine,
            p,
            rid,
            state["selections"],
            expected_version=int(acct.get("dv") or 0),
            writer=writer(state),
        )
    except VersionConflict:
        acct.update(dirty=True, status="conflict")
        state["acct"] = acct
        return state, {
            "text": "Your saved portfolio was changed in another tab or on another device. "
            "Your latest change here is not saved.",
            "kind": "warn",
            "recover": "reload",
        }
    except RoundClosed as exc:
        acct.update(dirty=True, status="closed")
        state["acct"] = acct
        return state, {"text": exc.message, "kind": "warn"}
    except ValidationFailed as exc:
        acct.update(dirty=True, status="failed")
        state["acct"] = acct
        return state, {"text": exc.message, "kind": "warn", "recover": "reload"}
    except ServiceError as exc:
        acct.update(dirty=True, status="failed")
        state["acct"] = acct
        return state, {"text": exc.message, "kind": "warn", "recover": "retry"}
    acct.update(dv=d.version, saved=d.keys, dirty=False, status="saved")
    state["acct"] = acct
    return state, None


def confirm(service, state: dict) -> tuple[dict, dict]:
    """Confirm (or explicitly replace) the saved draft as the participant's entry."""
    from diski9.backend.services import entries
    from diski9.backend.services.common import ServiceError

    p = participant(service)
    rid = round_uuid(state)
    acct = state.get("acct") or {}
    if acct.get("dirty"):
        return state, {
            "text": "Your latest changes are not saved yet. Save or reload them first.",
            "kind": "warn",
            "recover": "retry",
        }
    replacing = acct.get("entry") == "confirmed"
    key = f"{state['tab']}-d{acct.get('dv', 0)}-e{acct.get('ev', 0)}"
    try:
        entries.confirm_entry(
            service.backend.engine,
            p,
            rid,
            draft_version=int(acct.get("dv") or 0),
            expected_entry_version=int(acct.get("ev") or 0),
            idempotency_key=key,
            replace=replacing,
        )
    except ServiceError as exc:
        fresh = hydrate(service, state) or state
        return fresh, {"text": exc.message, "kind": "warn"}
    fresh = hydrate(service, state, force=True) or state
    fresh["modal"] = (fresh.get("submitted") or {}).get("at")
    return fresh, {
        "text": "Your entry was replaced." if replacing else "Your entry is confirmed.",
        "kind": "ok",
    }


def withdraw(service, state: dict) -> tuple[dict, dict]:
    from diski9.backend.services import entries
    from diski9.backend.services.common import ServiceError

    p = participant(service)
    acct = state.get("acct") or {}
    try:
        entries.withdraw_entry(
            service.backend.engine, p, round_uuid(state), expected_entry_version=int(acct["ev"])
        )
    except ServiceError as exc:
        fresh = hydrate(service, state) or state
        fresh["confirm"] = None
        return fresh, {"text": exc.message, "kind": "warn"}
    fresh = hydrate(service, state, force=True) or state
    fresh.update(confirm=None, stage="build")
    return fresh, {
        "text": "Your entry was withdrawn. Your saved portfolio is still here; you can confirm "
        "again before the deadline.",
        "kind": "ok",
    }


# ------------------------------------------------------------------ most recent locked entry
def most_recent_locked(service, exclude_round_id: UUID | None = None) -> dict | None:
    """The signed-in participant's most recent confirmed entry in a round whose
    deadline has passed, other than the round the page shows (read-only; from the
    stored immutable submission and the round's frozen snapshot). None for
    guests, accounts without such an entry, or when the database is unavailable
    (nothing is fabricated)."""
    p = participant(service)
    b = backend_of(service)
    if p is None or b is None:
        return None
    from diski9.backend.services import entries
    from diski9.backend.services import rounds as rsvc

    try:
        found = entries.latest_locked_entry(
            b.engine, p, exclude_round_id=exclude_round_id, include_development=b.show_development
        )
        if found is None:
            return None
        view, e = found
        rec = submitted_record(service, view, rsvc.published_snapshot(b.engine, view.id), e)
    except Exception:  # noqa: BLE001 - the card is simply not shown
        return None
    if rec is None:
        return None
    rec.update(
        round_status=view.status,
        entry_locked=e.locked,
        deadline=view.deadline_at.astimezone(UTC).isoformat() if view.deadline_at else None,
        classification=view.classification,
        development=view.is_development,
    )
    return rec
