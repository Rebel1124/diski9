"""Portfolio review fingerprint (Phase 8 CP3A-R, R2; refinement §14.4 and §14.12).

A rolling-entry participant reviews nine selections; prices may move between
editions before they confirm. The **review fingerprint** decides whether what they
reviewed is still what they would accept:

* one canonical **item** per position, in the participant's own position order:
  fixture, market, outcome, odds (2 decimals), market probability (percent, 1
  decimal), A3 bucket, the analytical **baseline** (source, methodology identity and
  estimated goals, §14.4) and a **Your View** slot (P8-YV);
* each item is hashed (SHA-256 of canonical JSON); the fingerprint is the SHA-256 of
  ``review/v1`` and the nine item digests.

Display precision decides *whether re-review is needed* only. Accepted values are
always copied from the authoritative edition at full storage precision (and the
database checks the copies, ``app_0010``). Nothing here trusts a client value: the
client returns only the item digests it was shown.

**Baseline (refinement §14.4, the OD-3 hierarchy).** Each item names where the
fixture's analytical estimate comes from, with distinct identities:

* ``goal_model``: the independent Goal Model frozen with the edition. Identity: the
  round's ``model_version`` and the fixture's estimated goals (2 decimals); the
  outcome's model probability (percent, 1 decimal);
* ``market_implied``: no independent estimate, but a reliable market-implied fit of
  the edition's own market probabilities (``market_fit.frozen_fit``, the State B
  computation Your View and Match Lab already use; nothing recalculated here).
  Identity: the fit methodology version and input identity
  (``MarketFit.stamp_version``), the fitted estimated goals (2 decimals) and the
  outcome's fitted probability (percent, 1 decimal);
* ``none``: neither is available (State C; the market probability is the reference).

A switch between sources, a methodology or input change that moves a displayed
value, or an estimated-goals change at 2 decimals changes the item and so requires
re-review; sub-display changes do not.

Re-review is needed exactly when one of the participant's own reviewed values
changes; a new edition number, an unrelated fixture or offer, or a refresh that
leaves the reviewed values identical never requires it. Changed positions are named.

**Your View slot (R2 foundation).** The canonical item has a ``view`` field for the
participant's preserved absolute estimated goals and resulting probability, or
``fallback`` (P8-YV). In R2 the server records ``None`` (no Your View value enters the
review yet); R3 populates it from the revised Your View storage without changing the
format version, since ``None`` is never produced once R3 supplies values.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, select, text

from diski9.challenge.config import ChallengeConfig, get_config
from diski9.challenge.roundsheet import RoundSnapshot
from diski9.challenge.structured import ChallengeOutcome
from diski9.screener import market_fit

from ..auth.permissions import Capability, Principal, authorize
from ..db import read_only
from ..db.schema import portfolio_drafts, round_schedules, rounds
from . import drafts as drafts_svc
from . import editions, rolling, snapshots
from .common import ValidationFailed

FINGERPRINT_VERSION = "review/v1"
GOAL_MODEL = "goal_model"
MARKET_IMPLIED = "market_implied"
NO_BASELINE = "none"


def _pct(p: float | None) -> str | None:
    return None if p is None else f"{Decimal(repr(p)) * 100:.1f}"


def _goals(eg) -> list[str] | None:
    return None if eg is None else [f"{float(eg[0]):.2f}", f"{float(eg[1]):.2f}"]


def baseline(o: ChallengeOutcome, model_version: str, snapshot: RoundSnapshot | None,
             fits: dict | None = None) -> dict:  # fmt: skip
    """The analytical baseline identity of one selection (§14.4), at display
    precision. ``fits`` caches market-implied fits per fixture within one review."""
    fixture = None
    if snapshot is not None:
        try:
            fixture = snapshot.fixture(o.fixture_id)
        except KeyError:
            fixture = None
    eg = fixture.estimated_goals if fixture is not None else None
    if o.model_probability is not None or eg is not None:
        return {"src": GOAL_MODEL, "ver": model_version, "eg": _goals(eg),
                "bp": _pct(o.model_probability)}  # fmt: skip
    if snapshot is not None and fixture is not None:
        fits = {} if fits is None else fits
        mf = fits.get(o.fixture_id)
        if mf is None:
            mf = fits[o.fixture_id] = market_fit.frozen_fit(snapshot, o.fixture_id)
        if mf.reliable:
            k = market_fit._OUTCOME_KEY.get(str(o.outcome))
            p = (mf.probabilities or {}).get(k)
            return {"src": MARKET_IMPLIED, "ver": mf.stamp_version,
                    "eg": _goals((mf.lambda_home, mf.lambda_away)),
                    "bp": _pct(None if p is None else float(p))}  # fmt: skip
    return {"src": NO_BASELINE, "ver": None, "eg": None, "bp": None}


def item(o: ChallengeOutcome, config: ChallengeConfig, model_version: str,
         view: Mapping | None = None, *, snapshot: RoundSnapshot | None = None,
         fits: dict | None = None) -> dict:  # fmt: skip
    """The canonical reviewed item of one selection, at display precision. Callers
    pass the authoritative edition as ``snapshot`` so the baseline identity is
    complete (without it only an outcome's own Goal Model probability is known)."""
    return {
        "f": int(o.fixture_id),
        "m": str(o.market),
        "o": str(o.outcome),
        "odds": f"{Decimal(o.reference_odds):.2f}",
        "p": _pct(o.market_probability),
        "b": config.classify(o.market_probability),
        "base": baseline(o, model_version, snapshot, fits),
        "view": dict(view) if view else None,
    }


def digest(it: Mapping) -> str:
    return hashlib.sha256(
        json.dumps(it, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fingerprint(digests: Sequence[str]) -> str:
    return hashlib.sha256((FINGERPRINT_VERSION + ":" + ":".join(digests)).encode()).hexdigest()


def changed_positions(reviewed: Sequence[str], current: Sequence[str]) -> list[int]:
    """Positions whose reviewed item differs (or is missing on either side)."""
    n = max(len(reviewed), len(current))
    return [
        i for i in range(n) if i >= len(reviewed) or i >= len(current) or reviewed[i] != current[i]
    ]


def items_for(outcomes: Sequence[ChallengeOutcome], config: ChallengeConfig,
              model_version: str, snapshot: RoundSnapshot) -> list[dict]:  # fmt: skip
    fits: dict = {}
    return [item(o, config, model_version, snapshot=snapshot, fits=fits) for o in outcomes]


@dataclass(frozen=True)
class Review:
    """What a rolling-entry participant reviews now (read-only)."""

    round_id: UUID
    snapshot_id: int
    edition: int
    items: tuple[dict, ...]  # canonical items, position order
    digests: tuple[str, ...]
    fingerprint: str
    problems: tuple[dict, ...]  # per position: not_on_sheet, ineligible, fixture_closed, stale

    @property
    def ready(self) -> bool:
        return len(self.items) == 9 and not self.problems


def review_portfolio(engine: Engine, principal: Principal, round_id: UUID) -> Review:
    """The participant's saved draft evaluated against the round's current edition at
    the database clock: the canonical items and digests to show and send back with
    the confirmation, plus every selection that could not be confirmed now and why.
    Never changes the draft."""
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    with read_only(engine) as conn:
        r = conn.execute(
            select(rounds.c.config_version, rounds.c.model_version, rounds.c.rules_version,
                   round_schedules.c.deadline_buffer_minutes.label("buffer"))
            .select_from(rounds.join(round_schedules, round_schedules.c.id == rounds.c.schedule_id))
            .where(rounds.c.id == round_id)
        ).one()  # fmt: skip
        sid, edition, snap = snapshots.CACHE.current(conn, round_id)
        draft = conn.execute(
            select(portfolio_drafts.c.selections).where(
                portfolio_drafts.c.user_id == principal.user_id,
                portfolio_drafts.c.round_id == round_id,
            )
        ).scalar_one_or_none()
        now = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
    config = get_config(r.config_version)
    competitive = rolling.is_rolling(r.rules_version)
    return evaluate(round_id, sid, edition, snap, config, r.model_version or "",
                    list(draft or []), now, r.buffer, competitive)  # fmt: skip


def evaluate(round_id, sid, edition, snap: RoundSnapshot, config, model_version, selections,
             now, buffer, competitive: bool) -> Review:  # fmt: skip
    problems, items, fits = [], [], {}
    kickoff = {f.fixture_id: f.kickoff for f in snap.fixtures}
    try:
        parsed = drafts_svc.parse_selections(selections)
    except ValidationFailed as exc:
        parsed, problems = [], list(exc.issues)
    for pos, s in enumerate(parsed):
        key = (s["fixture_id"], s["market"], s["outcome"])
        o = snap.outcome(key)
        why = None
        if o is None:
            why = "not_on_sheet"
        else:
            from diski9.challenge.structured import assess_outcome

            if not assess_outcome(o, snap.snapshot_at, config).eligible:
                why = "ineligible"
            elif competitive:
                if rolling.closed_fixtures(kickoff, [o.fixture_id], now, buffer):
                    why = "fixture_closed"
                else:
                    why = editions.offer_problem(o, now)
        if o is not None:
            items.append(item(o, config, model_version, snapshot=snap, fits=fits))
        if why is not None:
            problems.append({"position": pos, "key": "|".join(map(str, key)), "reason": why})
    digests = tuple(digest(i) for i in items)
    return Review(round_id, sid, edition, tuple(items), digests, fingerprint(digests),
                  tuple(problems))  # fmt: skip


__all__ = [
    "FINGERPRINT_VERSION",
    "Review",
    "baseline",
    "changed_positions",
    "digest",
    "evaluate",
    "fingerprint",
    "item",
    "items_for",
    "review_portfolio",
]
