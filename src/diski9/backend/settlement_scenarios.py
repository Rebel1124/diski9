"""Deterministic settlement scenarios for development rounds (Phase 6C.4, S-08).

**Development and acceptance-testing utilities only** — not a participant feature,
not a simulation: no probabilities, no random draws, no hypothetical payouts. A
scenario is a fixed timeline of synthetic observations built from a development
round's own deadline, cutoff and locked selections, recorded through
:func:`diski9.backend.services.results.record_synthetic_observation` (development
round, synthetic result mode, never production). The operator CLI wrapper is
Stage E.

Times are placed relative to the round so every scenario works for any span
between deadline and cutoff: ``t1`` (not started), ``t2`` (in play), ``t3``
(final) lie strictly between them. With ``horizon`` (the ``prompt`` timeline of
the CLI) the span used for ``t1``–``t3`` is capped, so the evidence lies minutes
after the deadline and becomes visible at the database clock almost at once;
operations that always evaluate at the database clock (corrections, alert
resolutions, reopening) can then be exercised without waiting days. The cutoff
itself never moves: ``cutoff-boundary`` and ``late-notification`` still place
evidence at the real cutoff and need ``settle run --as-of`` after it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine

from ..challenge.settle import outcome_wins
from .auth.permissions import Principal
from .db import transaction
from .services import results as results_svc

SCENARIOS = (
    "all-correct",
    "all-incorrect",
    "one-bucket-wins",
    "partial-void",
    "bucket-all-void",
    "all-nine-void",
    "round-invalid-majority",
    "pending",
    "cutoff-boundary",
    "late-notification",
    "provider-correction",
    "status-regression",
    "early-start-unverified",
    "repeat",
)
SCORES = [(h, a) for h in range(5) for a in range(5)]


@dataclass(frozen=True)
class SyntheticObservation:
    fixture_id: int
    observed_at: datetime
    status: str
    kickoff_at: datetime
    ft_home: int | None = None
    ft_away: int | None = None
    first_half_at: datetime | None = None


@dataclass(frozen=True)
class ScenarioLeg:
    fixture_id: int
    market: str
    outcome: str
    bucket: str


def _score(outcomes: Sequence[tuple[str, str]], *, win: bool) -> tuple[int, int]:
    """The first score (in a fixed order) giving the most selected outcomes the
    wanted result; with consistent picks, all of them."""
    return max(
        SCORES,
        key=lambda s: (sum(outcome_wins(m, o, *s) == win for m, o in outcomes), -SCORES.index(s)),
    )


def build(
    name: str,
    *,
    deadline: datetime,
    cutoff: datetime,
    entries: Sequence[Sequence[ScenarioLeg]],
    horizon: timedelta | None = None,
) -> list[SyntheticObservation]:
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}; choose one of {', '.join(SCENARIOS)}")
    if not entries:
        raise ValueError("the round has no locked entries")
    span = cutoff - deadline if horizon is None else min(cutoff - deadline, horizon)
    if span <= timedelta(0):
        raise ValueError("the timeline needs a positive span after the deadline")
    t1, t2, t3 = deadline + span / 8, deadline + span / 4, deadline + span / 2
    ko = t2 - span / 16
    outcomes: dict[int, list[tuple[str, str]]] = {}
    for legs in entries:
        for leg in legs:
            outcomes.setdefault(leg.fixture_id, [])
            if (leg.market, leg.outcome) not in outcomes[leg.fixture_id]:
                outcomes[leg.fixture_id].append((leg.market, leg.outcome))
    fixtures = sorted(outcomes)
    first = list(entries[0])
    by_bucket = {b: [x.fixture_id for x in first if x.bucket == b] for b in ("A", "B", "C")}

    def played(fid, win=True, at=t3):
        h, a = _score(outcomes[fid], win=win)
        return [
            SyntheticObservation(fid, t1, "NS", ko),
            SyntheticObservation(fid, t2, "1H", ko),
            SyntheticObservation(fid, at, "FT", ko, h, a),
        ]

    def void(fid):
        return [SyntheticObservation(fid, t1, "NS", ko), SyntheticObservation(fid, t3, "CANC", ko)]

    out: list[SyntheticObservation] = []
    special: dict[int, list[SyntheticObservation]] = {}
    win = {fid: True for fid in fixtures}
    if name == "all-incorrect":
        win = {fid: False for fid in fixtures}
    elif name == "one-bucket-wins":
        win = {fid: fid in by_bucket["A"] for fid in fixtures}
    elif name == "partial-void":
        special[by_bucket["A"][0]] = void(by_bucket["A"][0])
    elif name == "bucket-all-void":
        for fid in by_bucket["B"]:
            special[fid] = void(fid)
    elif name == "all-nine-void":
        for fid in fixtures:
            special[fid] = void(fid)
    elif name == "round-invalid-majority":
        counts = {
            fid: sum(1 for legs in entries for x in legs if x.fixture_id == fid) for fid in fixtures
        }
        total, voided = sum(counts.values()), 0
        for fid in fixtures:
            if 2 * voided >= total:
                break
            special[fid] = void(fid)
            voided += counts[fid]
    elif name == "pending":
        for fid in fixtures[len(fixtures) // 2 :]:
            special[fid] = [
                SyntheticObservation(fid, t1, "NS", ko),
                SyntheticObservation(fid, t3, "2H", ko),
            ]
    elif name == "cutoff-boundary":
        f0, f1 = fixtures[0], fixtures[1]
        special[f0] = played(f0, at=cutoff)
        h, a = _score(outcomes[f1], win=True)
        special[f1] = [
            SyntheticObservation(f1, t2, "1H", ko),
            SyntheticObservation(f1, cutoff - timedelta(seconds=1), "2H", ko),
            SyntheticObservation(f1, cutoff + timedelta(seconds=1), "FT", ko, h, a),
        ]
    elif name == "late-notification":
        f0 = fixtures[0]
        h, a = _score(outcomes[f0], win=True)
        special[f0] = [
            SyntheticObservation(f0, t1, "NS", ko),
            SyntheticObservation(f0, cutoff + timedelta(hours=1), "FT", ko, h, a),
        ]
    elif name == "provider-correction":
        f0 = fixtures[0]
        lh, la = _score(outcomes[f0], win=False)
        special[f0] = played(f0) + [
            SyntheticObservation(f0, t3 + timedelta(minutes=1), "FT", ko, lh, la)
        ]
    elif name == "status-regression":
        f0 = fixtures[0]
        special[f0] = played(f0) + [SyntheticObservation(f0, t3 + timedelta(minutes=1), "NS", ko)]
    elif name == "early-start-unverified":
        f0 = fixtures[0]
        h, a = _score(outcomes[f0], win=True)
        early = deadline - timedelta(minutes=5)
        special[f0] = [
            SyntheticObservation(f0, t1, "NS", ko, first_half_at=early),
            SyntheticObservation(f0, t3, "FT", ko, h, a, first_half_at=early),
        ]
    for fid in fixtures:
        obs = special.get(fid) or played(fid, win=win[fid])
        out.extend(obs)
        if name == "repeat":  # every final delivered twice, identically
            out.append(
                obs[-1].__class__(
                    **{
                        **obs[-1].__dict__,
                        "observed_at": obs[-1].observed_at + timedelta(seconds=30),
                    }
                )
            )
    return sorted(out, key=lambda o: (o.observed_at, o.fixture_id))


#: the CLI's ``prompt`` timeline: final evidence four minutes after the deadline
PROMPT_HORIZON = timedelta(minutes=8)

#: what each scenario demonstrates (operator documentation and ``dev-results scenarios``)
DESCRIPTIONS = {
    "all-correct": "every selected outcome wins; all four accumulators succeed",
    "all-incorrect": "every selected outcome loses; gross 0.00, not recovered",
    "one-bucket-wins": "bucket A fixtures win, the rest lose: Foundation pays, others 0.00",
    "partial-void": "one Foundation fixture is cancelled (void at 1.00), the rest win",
    "bucket-all-void": "every Balanced fixture is cancelled: its stake is returned at 1.00",
    "all-nine-void": "every selected fixture is cancelled: refund 100.00, not rank-eligible",
    "round-invalid-majority": "at least half of all locked predictions void: the round is "
    "void (D-32b) and every entry is refunded",
    "pending": "half the fixtures stay in play: partial settlement, totals settled so far",
    "cutoff-boundary": "one final exactly at the cutoff (settles) and one a second after "
    "(void V1); needs settle run --as-of after the cutoff",
    "late-notification": "a final first received an hour after the cutoff: void stands, "
    "blocking alert; needs settle run --as-of after the cutoff",
    "provider-correction": "a final score later changed by the provider so the verdict "
    "flips: the first score is kept and a blocking conflict alert is raised",
    "status-regression": "a final later reported as not started: held pending with a "
    "blocking alert",
    "early-start-unverified": "the provider's first-half time is before the deadline "
    "without corroboration: pending with a blocking alert",
    "repeat": "every final delivered twice, identically: stored once (idempotent)",
}


def apply_scenario(
    engine: Engine,
    actor: Principal,
    round_id: UUID,
    name: str,
    *,
    horizon: timedelta | None = None,
) -> int:
    """Record a scenario for a locked development round in synthetic mode. Returns
    the number of observations stored (identical repeats are not stored)."""
    from .services.settlement import locked_legs

    with transaction(engine) as conn:
        r = results_svc.round_row(conn, round_id)
        legs = locked_legs(conn, round_id)
    entries = [
        [ScenarioLeg(x.fixture_id, x.market, x.outcome, x.bucket) for x in ls]
        for _, ls, _ in legs.values()
    ]
    stored = 0
    for o in build(
        name, deadline=r.deadline_at, cutoff=r.settle_cutoff_at, entries=entries, horizon=horizon
    ):
        new = results_svc.record_synthetic_observation(
            engine,
            actor,
            round_id,
            o.fixture_id,
            observed_at=o.observed_at,
            status=o.status,
            kickoff_at=o.kickoff_at,
            ft_home=o.ft_home,
            ft_away=o.ft_away,
            provider_first_half_at=o.first_half_at,
        )
        stored += new is not None
    return stored


# ------------------------------------------------------------------ test entries
def test_selections(snapshot, variant: int = 0) -> list[dict]:
    """A deterministic, complete set of nine selections for development testing,
    chosen with the builder's own rules from the round's outcomes rotated by
    ``variant`` (so several test accounts get different portfolios)."""
    from ..challenge.config import DEFAULT_CONFIG
    from ..challenge.structured import selection_blocks

    outcomes = list(snapshot.outcomes)
    if not outcomes:
        raise ValueError("the round has no outcomes")
    shift = (variant * 7) % len(outcomes)
    ordered = outcomes[shift:] + outcomes[:shift]
    chosen: list = []
    for o in ordered:
        if len(chosen) == 9:
            break
        blocks = selection_blocks(chosen, outcomes, snapshot.snapshot_at, DEFAULT_CONFIG)
        if blocks.get(o.key) is None:
            chosen.append(o)
    if len(chosen) != 9:
        raise ValueError("no complete portfolio could be built for this variant")
    return [
        {"fixture_id": o.fixture_id, "market": str(o.market), "outcome": str(o.outcome)}
        for o in chosen
    ]


def submit_test_entry(engine: Engine, participant: Principal, round_id: UUID, variant: int = 0):
    """Confirm a deterministic portfolio for an **authenticated** participant on an
    open development round, through the ordinary draft and entry services (their
    authorisation, deadline and integrity checks all apply). Refused in production
    and for real rounds. Returns the entry view."""
    import uuid as _uuid

    from .db import BackendDatabaseSettings
    from .services import drafts as drafts_svc
    from .services import entries as entries_svc
    from .services.common import ServiceError
    from .services.snapshots import load_snapshot

    if BackendDatabaseSettings().environment == "production":
        raise ServiceError("Test entries are disabled in production.", code="usage")
    with transaction(engine) as conn:
        r = results_svc.round_row(conn, round_id)
        if not r.is_development:
            raise ServiceError("Test entries are only for development rounds.", code="usage")
        snap = load_snapshot(conn, round_id)
    current = drafts_svc.get_draft(engine, participant, round_id)
    draft = drafts_svc.save_draft(
        engine,
        participant,
        round_id,
        test_selections(snap, variant),
        expected_version=current.version,
    )
    entry = entries_svc.get_entry(engine, participant, round_id)
    return entries_svc.confirm_entry(
        engine,
        participant,
        round_id,
        draft_version=draft.version,
        expected_entry_version=entry.version,
        idempotency_key=f"dev-test-entry-{_uuid.uuid4().hex}",
        replace=entry.current is not None,
    )
