"""Settlement rules ``settle/v1`` (as amended 19 Nov 2026) as pure functions.

No database, clock or network access: everything is a function of the result
observations, the round's fixed ``deadline_at`` and ``settle_cutoff_at`` and the
evaluation time. Payout arithmetic is **not** reimplemented here; it is delegated to
the tested engine (:func:`diski9.challenge.structured.evaluate_groups`) with void
legs at decimal odds 1.00 (D-32) and per-accumulator half-up rounding (D-15).

Policy references (decision register): D-08 and S-03 (completion-based cutoff,
no grace period), S-04 (V3 branches and evidence), S-05 (conflicting results),
S-02 (blocking alerts), D-32 / D-33 (voids), R-07 (90-minute score).

Key properties, each covered by tests:

* **Cutoff evidence is frozen at the cutoff.** Whether a match completed by the
  cutoff, and which void rule applies to one that did not, depend only on
  observations recorded at or before ``settle_cutoff_at`` (plus audited operator
  corrections). Evaluating later with the same evidence gives the same result.
* **Nothing is invented.** No completion or kickoff time is derived from a
  schedule, half start, elapsed minutes or typical match length.
* **Pending is never void before the cutoff**, and ambiguity is never guessed: it
  is held pending with a settlement-blocking alert for audited resolution.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .config import DEFAULT_CONFIG, ChallengeConfig
from .structured import evaluate_groups

POLICY_VERSION = "settle/v1"  # amended 19 Nov 2026 (S-03, S-04, S-05)

NOT_STARTED = frozenset({"TBD", "NS"})
IN_PLAY = frozenset({"1H", "HT", "2H", "ET", "BT", "P", "LIVE"})
INTERRUPTED = frozenset({"SUSP", "INT"})
FINAL_PLAYED = frozenset({"FT", "AET", "PEN"})
POSTPONED = frozenset({"PST"})
ABANDONED = frozenset({"ABD"})
NO_GENUINE_RESULT = frozenset({"CANC", "AWD", "WO"})  # V2
KNOWN_STATUSES = (
    NOT_STARTED | IN_PLAY | INTERRUPTED | FINAL_PLAYED | POSTPONED | ABANDONED | NO_GENUINE_RESULT
)
# a status we recorded that proves the match had started by then (S-04, branch 1)
STARTED_STATUSES = IN_PLAY | INTERRUPTED | FINAL_PLAYED | ABANDONED
EARLIER_DISRUPTION = POSTPONED | INTERRUPTED | ABANDONED  # V5 when later completed

VOID_RULES = frozenset({"V1", "V1-catch-all", "V2", "V3-started", "V3-rescheduled", "V4"})
SETTLE_RULES = frozenset({"settle", "settle-v5"})

BLOCKING_CODES = frozenset(
    {
        "unknown_status",
        "missing_score",
        "score_conflict",
        "status_regression",
        "schedule_conflict",
        "early_start_unverified",
        "late_notification",
    }
)
INFORMATIONAL_CODES = frozenset({"catch_all_void", "score_corrected", "post_final_change"})

MARKETS = {
    "1X2": ("HOME", "DRAW", "AWAY"),
    "BTTS": ("BTTS_YES", "BTTS_NO"),
    "OU25": ("OVER_2_5", "UNDER_2_5"),
}
VOID_ODDS = Decimal("1.00")


class SettlementInputError(ValueError):
    """Inputs that the rules cannot interpret (never raised for provider quirks,
    which become pending predictions and alerts instead)."""


# ------------------------------------------------------------------ inputs
@dataclass(frozen=True)
class Observation:
    """One stored result observation (``app.result_observations``).

    ``observed_at`` is **our** receipt time (database clock), never a provider
    claim. ``scheduled_kickoff`` is the provider's (possibly revised) schedule;
    ``provider_first_half_at`` is the provider's ``periods.first`` (supporting
    evidence only). ``actual_kickoff_at`` and ``completed_at`` exist only on audited
    operator rows (verified event times with an evidence source)."""

    id: int
    source: str  # "api-football" | "synthetic" | "operator"
    observed_at: datetime
    status: str | None
    scheduled_kickoff: datetime | None = None
    ft_home: int | None = None
    ft_away: int | None = None
    provider_first_half_at: datetime | None = None
    actual_kickoff_at: datetime | None = None
    completed_at: datetime | None = None
    corrects_id: int | None = None
    withdraws_id: int | None = None

    @property
    def is_operator(self) -> bool:
        return self.source == "operator"

    @property
    def score(self) -> tuple[int, int] | None:
        if self.ft_home is None or self.ft_away is None:
            return None
        return (self.ft_home, self.ft_away)


@dataclass(frozen=True)
class Alert:
    code: str
    fixture_id: int | None
    key: str  # stable part of the fingerprint (evidence that raised it)
    detail: dict = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return self.code in BLOCKING_CODES

    @property
    def fingerprint(self) -> str:
        return f"{self.code}:{self.fixture_id}:{self.key}"


@dataclass(frozen=True)
class OutcomeVerdict:
    market: str
    outcome: str
    verdict: str  # won | lost | void | pending
    rule: str  # settle | settle-v5 | V1 | V1-catch-all | V2 | V3-* | V4 | pending

    @property
    def void_code(self) -> str | None:
        return self.rule[:2] if self.verdict == "void" else None


@dataclass(frozen=True)
class Resolution:
    """The settlement state of one fixture for the outcomes selected on it."""

    fixture_id: int
    rule: str
    verdicts: tuple[OutcomeVerdict, ...]
    score: tuple[int, int] | None
    deciding_observation_id: int | None
    evidence_ids: tuple[int, ...]
    alerts: tuple[Alert, ...]
    notes: tuple[str, ...] = ()

    @property
    def pending(self) -> bool:
        return self.rule == "pending"

    def verdict_for(self, market: str, outcome: str) -> OutcomeVerdict:
        for v in self.verdicts:
            if v.market == market and v.outcome == outcome:
                return v
        raise KeyError((market, outcome))


# ------------------------------------------------------------------ market rules
def outcome_wins(market: str, outcome: str, home: int, away: int) -> bool:
    """`settle/v1` §4 on the 90-minute score (extra time and penalties never count)."""
    if home < 0 or away < 0:
        raise SettlementInputError("scores cannot be negative")
    if market not in MARKETS or outcome not in MARKETS[market]:
        raise SettlementInputError(f"unsupported outcome {market}/{outcome}")
    if market == "1X2":
        return {"HOME": home > away, "DRAW": home == away, "AWAY": home < away}[outcome]
    if market == "BTTS":
        both = home >= 1 and away >= 1
        return both if outcome == "BTTS_YES" else not both
    over = home + away >= 3
    return over if outcome == "OVER_2_5" else not over


# ------------------------------------------------------------------ resolution
def _order(o: Observation) -> tuple:
    return (o.observed_at, o.id)


def live_operator_correction(observations: Sequence[Observation]) -> Observation | None:
    """The latest operator correction (or assertion) that no later operator row
    withdraws. Operator rows that only withdraw are never themselves corrections."""
    ops = sorted((o for o in observations if o.is_operator), key=_order)
    withdrawn = {o.withdraws_id for o in ops if o.withdraws_id is not None}
    live = [o for o in ops if o.withdraws_id is None and o.id not in withdrawn]
    return live[-1] if live else None


def resolve_fixture(
    fixture_id: int,
    observations: Iterable[Observation],
    selected: Iterable[tuple[str, str]],
    *,
    deadline_at: datetime,
    settle_cutoff_at: datetime,
    evaluated_at: datetime,
) -> Resolution:
    """Apply `settle/v1` to one fixture.

    Only observations recorded at or before ``evaluated_at`` are considered (a
    development time override therefore sees the evidence that existed then).
    ``selected`` lists the outcomes picked on this fixture in the locked entries;
    a score correction is *material* only if it changes one of their verdicts."""
    if not deadline_at < settle_cutoff_at:
        raise SettlementInputError("the deadline must precede the settlement cutoff")
    sel = tuple(dict.fromkeys(selected))
    for m, o in sel:
        if m not in MARKETS or o not in MARKETS[m]:
            raise SettlementInputError(f"unsupported outcome {m}/{o}")
    seen = sorted((o for o in observations if o.observed_at <= evaluated_at), key=_order)
    provider = [o for o in seen if not o.is_operator]
    op = live_operator_correction(seen)
    after_cutoff = evaluated_at > settle_cutoff_at
    alerts: list[Alert] = []
    notes: list[str] = []
    evidence = tuple(o.id for o in seen)

    def done(rule: str, score=None, deciding=None) -> Resolution:
        verdicts = []
        for m, o in sel:
            if rule in SETTLE_RULES:
                verdict = "won" if outcome_wins(m, o, *score) else "lost"
            elif rule in VOID_RULES:
                verdict = "void"
            else:
                verdict = "pending"
            verdicts.append(OutcomeVerdict(m, o, verdict, rule))
        return Resolution(
            fixture_id,
            rule,
            tuple(verdicts),
            score,
            deciding.id if deciding is not None else None,
            evidence,
            tuple(alerts),
            tuple(notes),
        )

    # ---------------------------------------------------------- V3 (S-04)
    hold = False
    started_obs = next(
        (o for o in provider if o.observed_at < deadline_at and o.status in STARTED_STATUSES), None
    )
    verified_kickoff = op.actual_kickoff_at if op is not None else None
    if verified_kickoff is not None:
        started = verified_kickoff < deadline_at
        notes.append("actual kickoff verified by an audited operator correction")
    else:
        started = started_obs is not None
    if started:
        notes.append("V3: started before the deadline")
        return done("V3-started", deciding=op if verified_kickoff is not None else started_obs)
    if verified_kickoff is None:
        early_half = [
            o
            for o in provider
            if o.provider_first_half_at is not None and o.provider_first_half_at < deadline_at
        ]
        if early_half:  # supporting evidence only: never decides V3 on its own
            alerts.append(
                Alert(
                    "early_start_unverified",
                    fixture_id,
                    str(early_half[0].id),
                    {"first_half_at": early_half[0].provider_first_half_at.isoformat()},
                )
            )
            hold = True
    if op is not None and op.scheduled_kickoff is not None:
        if op.scheduled_kickoff < deadline_at:
            return done("V3-rescheduled", deciding=op)
    else:
        sched = [o for o in provider if o.scheduled_kickoff is not None]
        first_early = next(
            (i for i, o in enumerate(sched) if o.scheduled_kickoff < deadline_at), None
        )
        if first_early is not None:
            later = sched[first_early:]
            if all(o.scheduled_kickoff < deadline_at for o in later):
                notes.append("V3: rescheduled before the deadline (not proof of commencement)")
                return done("V3-rescheduled", deciding=later[-1])
            contra = next(o for o in later if o.scheduled_kickoff >= deadline_at)
            alerts.append(
                Alert(
                    "schedule_conflict",
                    fixture_id,
                    f"{sched[first_early].id}-{contra.id}",
                    {
                        "early": sched[first_early].scheduled_kickoff.isoformat(),
                        "later": contra.scheduled_kickoff.isoformat(),
                    },
                )
            )
            hold = True
    if hold:
        return done("pending")

    # ---------------------------------------------------------- current state
    latest = op if op is not None else (provider[-1] if provider else None)
    if latest is None:
        if not after_cutoff:
            return done("pending")
        alerts.append(Alert("catch_all_void", fixture_id, "no-evidence"))
        notes.append("nothing recorded by the cutoff")
        return done("V1-catch-all")
    status = latest.status

    if status in NO_GENUINE_RESULT:
        return done("V2", deciding=latest)

    finals = [o for o in provider if o.status in FINAL_PLAYED]
    if op is None and status not in FINAL_PLAYED and finals:
        alerts.append(
            Alert("status_regression", fixture_id, f"{finals[-1].id}-{latest.id}", {"to": status})
        )
        return done("pending")

    if status is not None and status not in KNOWN_STATUSES:
        alerts.append(Alert("unknown_status", fixture_id, str(latest.id), {"status": status}))
        if not after_cutoff:
            return done("pending")

    completion_obs = next((o for o in finals if o.observed_at <= settle_cutoff_at), None)
    op_completed = (
        op is not None and op.completed_at is not None and op.completed_at <= settle_cutoff_at
    )
    completed = completion_obs is not None or op_completed

    if status in FINAL_PLAYED and completed:
        if op is not None:
            score, deciding = op.score, op
        else:
            scored = [o for o in finals if o.score is not None]
            score, deciding = (scored[-1].score, scored[-1]) if scored else (None, None)
            distinct = list(dict.fromkeys(o.score for o in scored))
            if len(distinct) > 1:
                first = distinct[0]
                changes = any(
                    outcome_wins(m, o, *first) != outcome_wins(m, o, *score) for m, o in sel
                )
                if changes:  # S-05: never silently replace an authoritative verdict
                    alerts.append(
                        Alert(
                            "score_conflict",
                            fixture_id,
                            "-".join(str(o.id) for o in scored),
                            {"scores": [f"{h}-{a}" for h, a in distinct]},
                        )
                    )
                    score = first
                    deciding = next(o for o in scored if o.score == first)
                else:
                    alerts.append(
                        Alert(
                            "score_corrected",
                            fixture_id,
                            "-".join(str(o.id) for o in scored),
                            {"scores": [f"{h}-{a}" for h, a in distinct]},
                        )
                    )
        if score is None:
            alerts.append(Alert("missing_score", fixture_id, str(latest.id)))
            return done("pending")
        disrupted = any(o.status in EARLIER_DISRUPTION for o in provider)
        if op_completed and completion_obs is None:
            notes.append("completion by the cutoff verified by an audited operator correction")
        return done("settle-v5" if disrupted else "settle", score=score, deciding=deciding)

    if not after_cutoff:
        return done("pending")

    # ---------------------------------------------------------- after the cutoff
    # the status recorded at the cutoff decides the void rule (later evidence never does)
    at_cutoff = (
        op
        if op is not None
        else next((o for o in reversed(provider) if o.observed_at <= settle_cutoff_at), None)
    )
    late_finals = [o for o in finals if o.observed_at > settle_cutoff_at]
    if late_finals and not completed:
        alerts.append(
            Alert(
                "late_notification",
                fixture_id,
                str(late_finals[0].id),
                {"first_final_recorded_at": late_finals[0].observed_at.isoformat()},
            )
        )
        notes.append("final result first received after the cutoff: completion time unknown")
    if at_cutoff is None:
        alerts.append(Alert("catch_all_void", fixture_id, "no-evidence-at-cutoff"))
        return done("V1-catch-all")
    st = at_cutoff.status
    if st in POSTPONED or (
        at_cutoff.scheduled_kickoff is not None and at_cutoff.scheduled_kickoff > settle_cutoff_at
    ):
        return done("V1", deciding=at_cutoff)
    if st in ABANDONED | INTERRUPTED:
        return done("V4", deciding=at_cutoff)
    if st in FINAL_PLAYED and op is not None and not completed:
        notes.append("operator correction without verified completion by the cutoff")
    alerts.append(Alert("catch_all_void", fixture_id, str(at_cutoff.id), {"status": st}))
    return done("V1-catch-all", deciding=at_cutoff)


# ------------------------------------------------------------------ entries
@dataclass(frozen=True)
class Leg:
    position: int
    fixture_id: int
    market: str
    outcome: str
    bucket: str
    odds: Decimal  # frozen consensus odds from the confirmed submission


@dataclass(frozen=True)
class Accumulator:
    code: str  # bucket code or "NINE"
    stake: int
    status: str  # won | lost | pending
    effective_odds: Decimal | None  # void legs at 1.00; None while pending
    payout: Decimal | None  # None while pending; 0.00 when lost


@dataclass(frozen=True)
class EntrySettlement:
    legs: tuple[tuple[Leg, str], ...]  # (leg, verdict)
    accumulators: tuple[Accumulator, ...]  # buckets in config order, then NINE
    gross: Decimal  # settled so far (only resolved winning accumulators)
    complete: bool
    all_void: bool  # D-33

    @property
    def net(self) -> Decimal:
        return self.gross - Decimal("100.00")

    @property
    def rank_eligible(self) -> bool | None:
        """D-33: an all-void entry is excluded from ranking. ``None`` while incomplete."""
        return None if not self.complete else not self.all_void

    @property
    def recovered(self) -> bool | None:
        """Entry-level recovery (gross >= 100.00, not D-33). ``None`` while incomplete;
        a round-level invalidation (D-32b) overrides it."""
        if not self.complete:
            return None
        return (not self.all_void) and self.gross >= DEFAULT_CONFIG.recovery_target

    @property
    def win_vector(self) -> tuple[int, ...] | None:
        if not self.complete:
            return None
        return tuple(1 if a.status == "won" else 0 for a in self.accumulators if a.code != "NINE")


def _acc_status(verdicts: Sequence[str]) -> str:
    if "lost" in verdicts:
        return "lost"  # already certain, even with other legs pending
    if "pending" in verdicts:
        return "pending"
    return "won"


def settle_entry(
    legs: Sequence[Leg],
    verdicts: dict[tuple[int, str, str], str],
    config: ChallengeConfig = DEFAULT_CONFIG,
) -> EntrySettlement:
    """Settle one locked entry from its frozen legs and the current verdicts.

    Payouts come from :func:`evaluate_groups` (the same code that produced the
    confirmed submission's eight states) with void legs at 1.00 (D-32); a bucket
    with an incorrect leg pays 0; a bucket with a pending leg and no incorrect leg
    stays pending (never shown as 0). All nine void returns exactly 100.00 (D-33)."""
    codes = config.bucket_codes
    groups: dict[str, list[Leg]] = {c: [] for c in codes}
    for leg in sorted(legs, key=lambda x: x.position):
        if leg.bucket not in groups:
            raise SettlementInputError(f"unknown bucket {leg.bucket!r}")
        groups[leg.bucket].append(leg)
    sizes = tuple(len(groups[c]) for c in codes)
    expected = config.sizes
    if sizes != expected:
        raise SettlementInputError(f"bucket sizes {sizes} differ from {expected}")
    v = {}
    for leg in legs:
        key = (leg.fixture_id, leg.market, leg.outcome)
        if key not in verdicts:
            raise SettlementInputError(f"no verdict for {key}")
        v[leg] = verdicts[key]
        if v[leg] not in ("won", "lost", "void", "pending"):
            raise SettlementInputError(f"unknown verdict {v[leg]!r}")

    def eff(leg: Leg) -> Decimal:
        return VOID_ODDS if v[leg] == "void" else leg.odds

    ev = evaluate_groups(
        [[(1.0, eff(x)) for x in groups[c]] for c in codes],
        config.stakes,
        config.nine_fold_credits,
        config.recovery_target,
        codes=codes,
        leg_keys=[[x.position for x in groups[c]] for c in codes],
    )
    accs = []
    for c, b in zip(codes, ev.buckets, strict=True):
        st = _acc_status([v[x] for x in groups[c]])
        accs.append(
            Accumulator(
                c,
                b.stake,
                st,
                b.combined_odds if st != "pending" else None,
                b.payout if st == "won" else (Decimal("0.00") if st == "lost" else None),
            )
        )
    st9 = _acc_status([v[x] for x in legs])
    nine = ev.nine_fold
    accs.append(
        Accumulator(
            "NINE",
            nine.stake,
            st9,
            nine.combined_odds if st9 != "pending" else None,
            nine.payout if st9 == "won" else (Decimal("0.00") if st9 == "lost" else None),
        )
    )
    complete = all(a.status != "pending" for a in accs)
    if complete:  # the exact engine state for the realised win vector
        wins = tuple(1 if a.status == "won" else 0 for a in accs[:-1])
        gross = next(s.gross for s in ev.states if s.wins == wins)
    else:
        gross = sum((a.payout for a in accs if a.status == "won"), Decimal("0.00"))
    all_void = all(v[x] == "void" for x in legs)
    if all_void and gross != Decimal("100.00"):  # guaranteed by the engine; checked anyway
        raise SettlementInputError(f"an all-void entry must return 100.00, got {gross}")
    return EntrySettlement(
        tuple((x, v[x]) for x in sorted(legs, key=lambda y: y.position)),
        tuple(accs),
        gross,
        complete,
        all_void,
    )


# ------------------------------------------------------------------ round validity
@dataclass(frozen=True)
class RoundValidity:
    rule: str  # d32b-competitive | d32b-practice
    total: int
    played: int
    void: int
    pending: int
    ranked: int
    outcome: str  # not_evaluated | pass | fail_majority | fail_ranked


def evaluate_round(
    entries: Sequence[EntrySettlement], *, competitive: bool, min_ranked: int = 5
) -> RoundValidity:
    """D-32b with exact integers over the locked set: competitive only if
    ``2 * played > total`` and at least ``min_ranked`` rank-eligible entries;
    practice rounds apply only the majority rule (D-32b-Q1). Not evaluated while
    any prediction is pending."""
    verdicts = [vd for e in entries for _, vd in e.legs]
    total = len(verdicts)
    played = sum(1 for x in verdicts if x in ("won", "lost"))
    void = sum(1 for x in verdicts if x == "void")
    pending = sum(1 for x in verdicts if x == "pending")
    ranked = sum(1 for e in entries if e.complete and not e.all_void)
    rule = "d32b-competitive" if competitive else "d32b-practice"
    if pending:
        outcome = "not_evaluated"
    elif not 2 * played > total:
        outcome = "fail_majority"
    elif competitive and ranked < min_ranked:
        outcome = "fail_ranked"
    else:
        outcome = "pass"
    return RoundValidity(rule, total, played, void, pending, ranked, outcome)
