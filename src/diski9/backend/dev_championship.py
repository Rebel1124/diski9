"""Development championship tooling (Phase 6C.5 Stage F1; specification §17.2).

**Development only.** Everything here is refused when the competition database
settings say ``production``, and every write targets *development* rounds only.
It never ranks, scores, settles, assigns or publishes anything itself: it drives the
same services as the operator CLI, in the same order a real week would.

Three parts:

* **Development participants** (:func:`ensure_participants`): synthetic accounts
  ``devp-0001`` … with an identity of provider ``development`` (never produced by
  Supabase Auth, so nobody can sign in as them), no e-mail address and no role. They
  are created idempotently (the identity subject is unique) and audited. The only
  way to act for them is :func:`participant_principal`, which refuses anything but a
  development participant, and is only used for development rounds.
* **Bulk test entries** (:func:`submit_all`): one confirmed nine-prediction entry per
  development participant on an open development round, through the ordinary draft
  and entry services (:func:`~diski9.backend.settlement_scenarios.submit_test_entry`),
  with deterministic portfolio variants. Participants that already have an entry
  are skipped, so a repeated or resumed call never duplicates anything.
* **The championship runner** (:func:`run_plan`): a scenario plan of K rounds. Per
  round: open a development round with a short *real* deadline, submit entries, wait
  for the deadline (database clock), lock, choose the synthetic result mode, record a
  6C.4 scenario, settle with ``as_of`` after the cutoff and finalise at the earliest
  finalisation (both development-only overrides that already exist), then verify the
  stream. Plan actions reopen and correct, or invalidate, a finalised round through
  the owner's audited services.

**Resumption from authoritative state.** The runner keeps no state of its own. Round
codes are derived from the run id and the plan's fingerprint
(``dev-<run>-<hash>-r01`` …). Before every operation it reads the round's real state
(status, entries, result mode, observations, settlement, published score sets) and
does only the next missing step. An interrupted run is resumed by running the same
command again; a different plan under the same run id is refused.

**Authentication.** The operator (and, for reopening, the owner) principal comes
from the interactive CLI password check. Before each write the principal is
re-evaluated at the database clock; when the 12-hour operator or 15-minute
sensitive recency has lapsed the runner calls ``reauthenticate`` (the CLI asks for
the password again) or stops safely with the next action. No password is stored.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, select, text

from .auth.permissions import (
    Capability,
    Principal,
    RecentAuthenticationRequired,
    authorize,
)
from .db import BackendDatabaseSettings, db_now, transaction
from .db.schema import profiles, user_identities
from .repositories import accounts as accounts_repo
from .repositories import ops as ops_repo
from .services.common import ServiceError

DEV_PROVIDER = "development"  # never issued by Supabase Auth: these accounts cannot sign in
SUBJECT_PREFIX = "dev-participant-"
NAME_PREFIX = "devp-"
MAX_PARTICIPANTS = 500  # ordinary testing; large-scale generation belongs to Stage F3
#: scenarios that settle and finalise without manual alert handling
RUNNABLE_SCENARIOS = (
    "all-correct",
    "all-incorrect",
    "one-bucket-wins",
    "partial-void",
    "bucket-all-void",
    "entry-all-void",
    "round-invalid-majority",
    "repeat",
)
ACTIONS = ("correct", "invalidate")


class DevToolError(ServiceError):
    """A refused development-tool request (user-safe message)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="usage")


class Stopped(Exception):
    """The run stopped safely before an operation (interruption or re-authentication)."""

    def __init__(self, reason: str, next_action: str) -> None:
        super().__init__(reason)
        self.reason, self.next_action = reason, next_action


def require_development() -> None:
    if BackendDatabaseSettings().environment == "production":
        raise DevToolError("Development tooling is refused in production.")


# ------------------------------------------------------------------ participants
@dataclass(frozen=True)
class DevParticipant:
    user_id: UUID
    index: int
    username: str


def participant_name(i: int) -> str:
    return f"{NAME_PREFIX}{i:04d}"


def dev_participants(conn, limit: int | None = None) -> list[DevParticipant]:
    rows = conn.execute(
        select(user_identities.c.user_id, user_identities.c.subject, profiles.c.username)
        .join(profiles, profiles.c.user_id == user_identities.c.user_id)
        .where(user_identities.c.provider == DEV_PROVIDER)
        .order_by(user_identities.c.subject)
    ).all()
    out = [DevParticipant(r.user_id, int(r.subject.removeprefix(SUBJECT_PREFIX)), r.username)
           for r in rows]  # fmt: skip
    return out[:limit] if limit is not None else out


def ensure_participants(
    engine: Engine, actor: Principal, count: int, *, preview: bool = False
) -> tuple[int, int]:
    """Make sure development participants ``devp-0001`` … ``devp-<count>`` exist.
    Returns ``(existing, created)``. Idempotent; audited; development only; needs an
    operator (``RUN_JOBS``)."""
    require_development()
    authorize(actor, Capability.RUN_JOBS)
    if not 1 <= count <= MAX_PARTICIPANTS:
        raise DevToolError(f"--count must be between 1 and {MAX_PARTICIPANTS}.")
    with transaction(engine) as conn:
        have = {p.index for p in dev_participants(conn)}
        missing = [i for i in range(1, count + 1) if i not in have]
        if preview or not missing:
            return len(have & set(range(1, count + 1))), 0
        for i in missing:
            uid = accounts_repo.create_user(conn)
            accounts_repo.link_identity(conn, uid, DEV_PROVIDER, f"{SUBJECT_PREFIX}{i:04d}")
            accounts_repo.create_profile(
                conn, uid, participant_name(i), f"Anonymous {90000000 + i}"
            )
        ops_repo.record_audit(
            conn,
            action="dev_participants_created",
            target_type="dev_participants",
            target_id=f"1-{count}",
            actor=actor.user_id,
            actor_role="operator",
            reason="development tooling (Phase 6C.5 F1)",
            after={"created": [participant_name(i) for i in missing]},
        )
    return count - len(missing), len(missing)


def participant_principal(engine: Engine, user_id: UUID) -> Principal:
    """A server-built principal for a *development participant* only (they have no
    credentials). Refuses any account without the development identity."""
    require_development()
    with transaction(engine) as conn:
        dev = conn.execute(
            select(user_identities.c.subject).where(
                user_identities.c.user_id == user_id, user_identities.c.provider == DEV_PROVIDER
            )
        ).first()
        others = conn.execute(
            select(user_identities.c.provider).where(
                user_identities.c.user_id == user_id, user_identities.c.provider != DEV_PROVIDER
            )
        ).first()
        now = db_now(conn)
    if dev is None or others is not None:
        raise DevToolError("Only development participants can be used by the development tools.")
    return Principal(user_id=user_id, onboarded=True, authenticated_at=now,
                     reauthenticated_at=now, now=now,
                     extra={"via": "dev-participant"})  # fmt: skip


def variant_for(mode: str, i: int, k: int, seed: int, pool: int) -> int:
    """Deterministic portfolio variant for participant ``i`` in round ``k``:
    ``spread`` (every participant different), ``groups`` (``pool`` portfolios shared
    by several participants, so weekly ties), ``pairs`` (participants 2j and 2j+1
    always identical, so championship ties)."""
    if mode == "pairs":
        i = i // 2
    elif mode == "groups":
        i = i % max(1, pool)
    return (seed * 7 + i * 5 + k * 3) % 59


def _round_row(conn, round_id: UUID):
    return conn.execute(
        text("SELECT id, code, status, is_development, deadline_at, settle_cutoff_at "
             "FROM app.rounds WHERE id = :r"), {"r": round_id}).one()  # fmt: skip


def submit_all(
    engine: Engine,
    actor: Principal,
    round_id: UUID,
    *,
    count: int | None = None,
    mode: str = "spread",
    seed: int = 2026,
    k: int = 0,
    pool: int = 3,
) -> tuple[int, int]:
    """Confirm one entry for each of the first ``count`` development participants
    (all when ``None``) on an open development round. Returns ``(skipped, submitted)``;
    participants with an entry already are skipped (idempotent)."""
    from . import settlement_scenarios as sc
    from .services import entries as entries_svc

    require_development()
    authorize(actor, Capability.RUN_JOBS)
    with transaction(engine) as conn:
        r = _round_row(conn, round_id)
        people = dev_participants(conn, count)
    if not r.is_development:
        raise DevToolError("Test entries are only for development rounds.")
    if count is not None and len(people) < count:
        raise DevToolError(f"Only {len(people)} development participants exist; run "
                           f"'dev-results participants --count {count}' first.")  # fmt: skip
    skipped = submitted = 0
    for j, person in enumerate(people):
        p = participant_principal(engine, person.user_id)
        if entries_svc.get_entry(engine, p, round_id).current is not None:
            skipped += 1
            continue
        sc.submit_test_entry(engine, p, round_id, variant_for(mode, j, k, seed, pool))
        submitted += 1
    return skipped, submitted


# ------------------------------------------------------------------ plans
@dataclass(frozen=True)
class RoundPlan:
    scenario: str = "all-correct"
    participants: int | None = None  # None: the plan's participants
    variants: str = "spread"  # spread | groups | pairs


@dataclass(frozen=True)
class ActionPlan:
    after: int  # applied once round ``after`` is final (1-based)
    action: str  # correct | invalidate
    target: int  # the round to reopen (1-based, final by then)


@dataclass(frozen=True)
class Plan:
    name: str
    participants: int = 8
    seed: int = 2026
    deadline_seconds: int = 60
    evidence_seconds: int = 480
    fixtures: int = 40  # enough spread that entry-all-void keeps the round valid (6C.4 note)
    rounds: tuple[RoundPlan, ...] = ()
    actions: tuple[ActionPlan, ...] = ()

    def fingerprint(self) -> str:
        body = json.dumps(plan_to_dict(self), sort_keys=True).encode()
        return hashlib.sha256(body).hexdigest()[:6]


def plan_to_dict(plan: Plan) -> dict:
    return {
        "name": plan.name, "participants": plan.participants, "seed": plan.seed,
        "deadline_seconds": plan.deadline_seconds, "evidence_seconds": plan.evidence_seconds,
        "fixtures": plan.fixtures,
        "rounds": [{"scenario": r.scenario, "participants": r.participants,
                    "variants": r.variants} for r in plan.rounds],
        "actions": [{"after": a.after, "action": a.action, "round": a.target}
                    for a in plan.actions],
    }  # fmt: skip


def plan_from_dict(d: dict) -> Plan:
    try:
        plan = Plan(
            name=str(d["name"]),
            participants=int(d.get("participants", 8)),
            seed=int(d.get("seed", 2026)),
            deadline_seconds=int(d.get("deadline_seconds", 60)),
            evidence_seconds=int(d.get("evidence_seconds", 480)),
            fixtures=int(d.get("fixtures", 40)),
            rounds=tuple(RoundPlan(str(r.get("scenario", "all-correct")),
                                   None if r.get("participants") is None
                                   else int(r["participants"]),
                                   str(r.get("variants", "spread")))
                         for r in d["rounds"]),
            actions=tuple(ActionPlan(int(a["after"]), str(a["action"]), int(a["round"]))
                          for a in d.get("actions", ())),
        )  # fmt: skip
    except (KeyError, TypeError, ValueError) as exc:
        raise DevToolError(f"The scenario plan is not valid: {exc}.") from None
    validate_plan(plan)
    return plan


def validate_plan(plan: Plan) -> None:
    problems = []
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", plan.name):
        problems.append("name: lower-case letters, digits and hyphens (at most 40)")
    if not 1 <= len(plan.rounds) <= 40:
        problems.append("rounds: between 1 and 40")
    if not 1 <= plan.participants <= MAX_PARTICIPANTS:
        problems.append(f"participants: between 1 and {MAX_PARTICIPANTS}")
    if plan.deadline_seconds < 5 or plan.evidence_seconds < 2:
        problems.append("deadline_seconds at least 5, evidence_seconds at least 2")
    if not 12 <= plan.fixtures <= 60:
        problems.append("fixtures: between 12 and 60")
    for n, r in enumerate(plan.rounds, 1):
        if r.scenario not in RUNNABLE_SCENARIOS:
            problems.append(f"round {n}: scenario must be one of {', '.join(RUNNABLE_SCENARIOS)}")
        if r.variants not in ("spread", "groups", "pairs"):
            problems.append(f"round {n}: variants must be spread, groups or pairs")
        if r.participants is not None and not 1 <= r.participants <= plan.participants:
            problems.append(f"round {n}: participants between 1 and the plan's participants")
    targets = set()
    for a in plan.actions:
        if a.action not in ACTIONS:
            problems.append(f"action: must be one of {', '.join(ACTIONS)}")
        if not 1 <= a.target <= a.after <= len(plan.rounds):
            problems.append("action: 1 <= round <= after <= number of rounds")
        if a.target in targets:
            problems.append(f"action: round {a.target} is the target of more than one action")
        targets.add(a.target)
    if problems:
        raise DevToolError("The scenario plan is not valid: " + "; ".join(problems) + ".")


ROTATION = ("all-correct", "one-bucket-wins", "partial-void", "entry-all-void", "bucket-all-void")
PRESETS = {
    "ten-round-complete": "a full championship: R valid competitive rounds with varied results",
    "with-practice": "R+1 rounds, round 2 has three entries (practice): it does not count",
    "with-invalidated": "R+1 rounds, round 2 fails D-32b (void): it does not count",
    "weekly-ties": "R rounds; participants share three portfolios, so weekly ranks are shared",
    "championship-tie": "R rounds; pairs of participants always identical: joint champions",
    "zero-points": "R rounds in which nobody recovers: completed with no champion",
    "rollover": "R+2 rounds: the championship completes and the next one starts",
    "historical-invalidation-before-next": "R rounds, then round 2 is invalidated before the "
    "next championship starts (L-33: it reopens), then one more round completes it again",
    "historical-invalidation-after-next": "R+1 rounds (the next championship has started), then "
    "round 2 is invalidated (D-30a: the completed championship keeps its boundary)",
    "reopen-and-correct": "3 rounds; round 2 is reopened by the owner and corrected (valid to "
    "valid), so the standings are recalculated",
}


def preset(name: str, required: int = 10, **overrides) -> Plan:
    """A documented scenario plan; ``required`` is the stream's rounds per championship
    (10 for real; automated tests use a smaller value for speed)."""
    if name not in PRESETS:
        raise DevToolError(f"Unknown preset; choose one of: {', '.join(PRESETS)}.")
    rot = [RoundPlan(ROTATION[k % len(ROTATION)]) for k in range(required + 3)]
    R = required
    rounds, actions = rot[:R], ()
    if name == "with-practice":
        rounds = rot[:1] + [RoundPlan("all-correct", 3)] + rot[1:R]
    elif name == "with-invalidated":
        rounds = rot[:1] + [RoundPlan("round-invalid-majority")] + rot[1:R]
    elif name == "weekly-ties":
        rounds = [replace(r, variants="groups") for r in rot[:R]]
    elif name == "championship-tie":
        rounds = [replace(r, variants="pairs") for r in rot[:R]]
    elif name == "zero-points":
        rounds = [RoundPlan("all-incorrect")] * R
    elif name == "rollover":
        rounds = rot[: R + 2]
    elif name == "historical-invalidation-before-next":
        rounds = rot[: R + 1]
        actions = (ActionPlan(R, "invalidate", 2),)
    elif name == "historical-invalidation-after-next":
        rounds = rot[: R + 1]
        actions = (ActionPlan(R + 1, "invalidate", 2),)
    elif name == "reopen-and-correct":
        rounds = [RoundPlan("all-correct")] * 3
        actions = (ActionPlan(2, "correct", 2),)
    plan = Plan(name=name, rounds=tuple(rounds), actions=actions)
    plan = replace(plan, **overrides)
    validate_plan(plan)
    return plan


# ------------------------------------------------------------------ state (read-only)
@dataclass(frozen=True)
class RoundState:
    number: int
    code: str
    round_id: UUID | None = None
    status: str | None = None  # None: not created yet
    entries: int = 0
    result_mode: str | None = None
    observations: int = 0
    settled: bool = False
    score_sets: int = 0
    latest_kind: str | None = None  # championship | practice | void
    deadline_at: datetime | None = None
    cutoff_at: datetime | None = None
    max_evidence_at: datetime | None = None

    @property
    def stage(self) -> str:
        if self.status is None:
            return "not created"
        if self.status == "final":
            return f"final ({self.latest_kind}, {self.score_sets} publication(s))"
        if self.status == "settling" and self.score_sets:
            return "reopened (under review)"
        return {"open": "open", "locked": "locked", "settling": "settled (provisional)"}.get(
            self.status, self.status
        )


def run_prefix(run_id: str, plan: Plan) -> str:
    return f"dev-{run_id}-{plan.fingerprint()}"


def round_code(run_id: str, plan: Plan, k: int) -> str:
    return f"{run_prefix(run_id, plan)}-r{k:02d}"


def inspect_run(engine: Engine, run_id: str, plan: Plan) -> list[RoundState]:
    """Every planned round's authoritative state, read from the database."""
    out = []
    with transaction(engine) as conn:
        clash = conn.execute(
            text("SELECT code FROM app.rounds WHERE code LIKE :p AND code NOT LIKE :q LIMIT 1"),
            {"p": f"dev-{run_id}-%", "q": f"{run_prefix(run_id, plan)}-r%"},
        ).scalar()
        if clash:
            raise DevToolError(
                f"Run '{run_id}' already exists with a different scenario plan (round "
                f"{clash}). Use the original plan, or a new --run-id."
            )
        for k in range(1, len(plan.rounds) + 1):
            code = round_code(run_id, plan, k)
            r = conn.execute(
                text(
                    "SELECT r.id, r.status, r.deadline_at, r.settle_cutoff_at, r.result_mode, "
                    "(SELECT count(*) FROM app.entries e WHERE e.round_id = r.id "
                    " AND (e.current_submission_id IS NOT NULL "
                    "      OR e.locked_submission_id IS NOT NULL)) AS entries, "
                    "(SELECT count(*) FROM app.result_observations o "
                    " WHERE o.scope_round_id = r.id) AS obs, "
                    "(SELECT max(o.observed_at) FROM app.result_observations o "
                    " WHERE o.scope_round_id = r.id) AS max_obs, "
                    "EXISTS (SELECT 1 FROM app.entry_settlements s JOIN app.entries e "
                    " ON e.id = s.entry_id WHERE e.round_id = r.id) AS settled, "
                    "(SELECT count(*) FROM app.score_sets x WHERE x.round_id = r.id) AS sets, "
                    "(SELECT x.kind FROM app.score_sets x WHERE x.round_id = r.id "
                    " ORDER BY x.revision DESC LIMIT 1) AS kind "
                    "FROM app.rounds r WHERE r.code = :c"
                ),
                {"c": code},
            ).one_or_none()
            if r is None:
                out.append(RoundState(k, code))
                continue
            out.append(RoundState(k, code, r.id, r.status, r.entries, r.result_mode, r.obs,
                                  r.settled, r.sets, r.kind, r.deadline_at,
                                  r.settle_cutoff_at, r.max_obs))  # fmt: skip
    return out


@dataclass(frozen=True)
class ChampionshipView:
    name: str
    status: str
    counted: int
    required: int
    champions: tuple[str, ...]
    under_review: bool


def championships(engine: Engine) -> list[ChampionshipView]:
    from .services import leaderboards as lb

    out = []
    for c in lb.championship_list(engine, stream="development", include_development=True):
        b = lb.championship_board(engine, stream="development", name=c.name, page_size=1,
                                  include_development=True)  # fmt: skip
        out.append(ChampionshipView(b.name, b.status, b.counted_rounds, b.rounds_required,
                                    tuple(b.champions), b.under_review))  # fmt: skip
    return out


# ------------------------------------------------------------------ runner
@dataclass
class RunReport:
    run_id: str
    plan: Plan
    done: bool = False
    paused: bool = False  # stopped on purpose after ``rounds`` rounds
    stopped: Stopped | None = None
    log: list[str] = field(default_factory=list)


Reauth = Callable[[str], Principal]  # role ("operator" | "owner") -> a fresh principal


class _Session:
    """The operator and owner principals for one run, re-evaluated before each write."""

    def __init__(self, engine, operator: Principal, owner: Principal | None,
                 reauthenticate: Reauth | None) -> None:  # fmt: skip
        self.engine, self.principals, self.reauth = engine, {"operator": operator}, reauthenticate
        if owner is not None:
            self.principals["owner"] = owner

    def get(self, role: str, capability: Capability) -> Principal:
        from .auth.operator_cli import refresh_clock

        p = self.principals.get(role)
        if p is not None:
            p = refresh_clock(self.engine, p)
            try:
                authorize(p, capability)
                return p
            except RecentAuthenticationRequired:
                pass
        if self.reauth is None:
            what = "the owner's" if role == "owner" else "the operator's"
            raise Stopped(
                f"re-authentication required ({what} password)",
                "run the same command again in a terminal and enter the password",
            )
        p = self.reauth(role)
        authorize(p, capability)
        self.principals[role] = p
        return p


def _wait_until(engine, moment: datetime, say, stop: Callable[[], bool], label: str) -> None:
    last = None
    while True:
        with transaction(engine) as conn:
            now = db_now(conn)
        left = (moment - now).total_seconds()
        if left <= 0:
            return
        if stop():
            raise Stopped("interrupted while waiting", "run the same command again to resume")
        secs = int(left) + 1
        if last is None or last - secs >= 10:
            say(f"  waiting for {label}: {secs} s")
            last = secs
        time.sleep(min(1.0, max(0.05, left)))


def run_plan(
    engine: Engine,
    plan: Plan,
    run_id: str,
    operator: Principal,
    *,
    owner: Principal | None = None,
    reauthenticate: Reauth | None = None,
    say: Callable[[str], None] = print,
    stop: Callable[[], bool] = lambda: False,
    hook: Callable[[str, int], None] | None = None,
    rounds: int | None = None,
) -> RunReport:
    """Run (or resume) ``plan`` under ``run_id`` against the development stream.

    ``stop()`` is checked before every operation (graceful interruption); ``hook``
    (tests) is called with ``("before:<step>", k)`` and ``("after:<step>", k)``
    around every operation. Returns a :class:`RunReport`; a safe stop is reported in
    ``report.stopped`` (nothing is left half-done: each step is one service call)."""
    require_development()
    if not re.fullmatch(r"[a-z0-9]{1,12}", run_id):
        raise DevToolError("--run-id: 1 to 12 lower-case letters or digits.")
    validate_plan(plan)
    report = RunReport(run_id, plan)
    session = _Session(engine, operator, owner, reauthenticate)

    def step(name: str, k: int, fn):
        if stop():
            raise Stopped(f"interrupted before {name} of round {k}",
                          "run the same command again to resume")  # fmt: skip
        if hook:
            hook(f"before:{name}", k)
        out = fn()
        if hook:
            hook(f"after:{name}", k)
        return out

    def log(msg: str) -> None:
        report.log.append(msg)
        say(msg)

    try:
        states = inspect_run(engine, run_id, plan)
        log(f"Scenario '{plan.name}' · run {run_id} · development stream · "
            f"{plan.participants} participants · {len(plan.rounds)} rounds")  # fmt: skip
        if all(s.status is None for s in states):
            _ensure_people(engine, session, plan, log)
        limit = len(plan.rounds) if rounds is None else rounds
        for k, rp in enumerate(plan.rounds[:limit], 1):
            _run_round(engine, session, plan, run_id, k, rp, step, log, stop)
            for a in plan.actions:
                if a.after == k:
                    _run_action(engine, session, plan, run_id, a, step, log, stop)
        report.done = limit == len(plan.rounds)
        report.paused = not report.done
        log(_summary(engine))
    except Stopped as s:
        report.stopped = s
        log(f"Stopped safely: {s.reason}. Next: {s.next_action}.")
    return report


def _ensure_people(engine, session, plan, log) -> None:
    p = session.get("operator", Capability.RUN_JOBS)
    existing, created = ensure_participants(engine, p, plan.participants)
    log(f"Participants: {existing} existing, {created} created")


def _state(engine, run_id, plan, k) -> RoundState:
    return inspect_run(engine, run_id, plan)[k - 1]


def _run_round(engine, session, plan, run_id, k, rp, step, log, stop) -> None:
    from .devdata import dev_snapshot
    from .services import results as rs
    from .services import rounds as rounds_svc
    from .services import settlement as st
    from .settlement_scenarios import apply_scenario

    s = _state(engine, run_id, plan, k)
    head = f"Round {k}/{len(plan.rounds)} {s.code}"
    if s.status == "final" and s.score_sets:
        log(f"{head}: already {s.stage}")
        return
    n = rp.participants or plan.participants
    if s.status is None:

        def open_round():
            p = session.get("operator", Capability.PUBLISH_ROUND)
            with transaction(engine) as conn:
                now = db_now(conn)
                buffer = conn.execute(text(
                    "SELECT deadline_buffer_minutes FROM app.round_schedules "
                    "ORDER BY id LIMIT 1")).scalar_one()  # fmt: skip
            first = now + timedelta(seconds=plan.deadline_seconds, minutes=buffer)
            snap = dev_snapshot(s.code, now, first, seed=plan.seed + k, fixtures=plan.fixtures,
                                spacing=timedelta(minutes=1))  # fmt: skip
            v = rounds_svc.create_round(engine, p, code=s.code, window_start=snap.window[0],
                                        window_end=snap.window[1], development=True)  # fmt: skip
            rounds_svc.publish_round(engine, p, v.id, snap, source="development")

        step("open", k, open_round)
        s = _state(engine, run_id, plan, k)
        log(f"{head}: opened, deadline {s.deadline_at:%H:%M:%S} UTC ({rp.scenario}, {n} entries)")
    if s.status == "open":
        if s.entries < n:

            def enter():
                p = session.get("operator", Capability.RUN_JOBS)
                return submit_all(engine, p, s.round_id, count=n, mode=rp.variants,
                                  seed=plan.seed, k=k)  # fmt: skip

            skipped, made = step("entries", k, enter)
            log(f"{head}: entries submitted {made} (already there {skipped})")
        elif s.entries > n:
            raise DevToolError(f"{s.code} has {s.entries} entries; the plan expects {n}.")
        _wait_until(engine, s.deadline_at, log, stop, f"the {s.code} deadline")
        step(
            "lock",
            k,
            lambda: rounds_svc.lock_round(
                engine, session.get("operator", Capability.RUN_JOBS), s.round_id
            ),
        )
        s = _state(engine, run_id, plan, k)
        log(f"{head}: locked ({s.entries} entries)")
    if s.status in ("locked", "settling") and not s.score_sets:
        if s.result_mode is None:
            step(
                "result-mode",
                k,
                lambda: rs.set_result_mode(
                    engine, session.get("operator", Capability.RUN_JOBS), s.round_id, "synthetic"
                ),
            )
        if s.observations == 0:
            horizon = timedelta(seconds=plan.evidence_seconds)
            step(
                "results",
                k,
                lambda: apply_scenario(
                    engine,
                    session.get("operator", Capability.RUN_JOBS),
                    s.round_id,
                    rp.scenario,
                    horizon=horizon,
                ),
            )
            log(f"{head}: synthetic results recorded ({rp.scenario})")
        s = _state(engine, run_id, plan, k)
        as_of = s.cutoff_at + timedelta(seconds=1)
        if not s.settled:
            step(
                "settle",
                k,
                lambda: st.settle_round(
                    engine, session.get("operator", Capability.RUN_JOBS), s.round_id, as_of=as_of
                ),
            )
            log(f"{head}: settled (as of the cutoff, development override)")
        step("finalise", k, lambda: _finalise(engine, session, s.round_id))
        s = _state(engine, run_id, plan, k)
        log(f"{head}: {s.stage}")
        if s.latest_kind == "void" and rp.scenario != "round-invalid-majority":
            log(
                f"  note: this round is void under D-32b (at least half of the locked "
                f"predictions void after '{rp.scenario}'); it does not count. Use more "
                "fixtures or fewer shared portfolios if you expected a valid round."
            )
        elif s.latest_kind == "practice" and n >= 5:
            log("  note: fewer than five valid entries at lock: practice round")
        _verify(engine, log)
    elif s.status == "settling" and s.score_sets:
        raise DevToolError(f"{s.code} is reopened (under review); finish its correction "
                           "with the original plan before continuing.")  # fmt: skip


def _finalise(engine, session, round_id):
    from .services import corrections as co
    from .services import settlement as st

    with transaction(engine) as conn:
        r = conn.execute(text("SELECT * FROM app.rounds WHERE id = :r"), {"r": round_id}).one()
        earliest = st.earliest_finalisation(conn, r)
    if earliest is None:
        raise DevToolError("The round has not been settled, so it cannot be finalised.")
    as_of = earliest.replace(microsecond=0) + timedelta(seconds=1)
    out = co.finalise_round(engine, session.get("operator", Capability.RUN_JOBS),
                            round_id, as_of=as_of)  # fmt: skip
    if not out.finalised:
        raise DevToolError(f"Finalisation was refused: {out.reason}")
    return out


def _run_action(engine, session, plan, run_id, a, step, log, stop) -> None:
    from .services import corrections as co

    s = _state(engine, run_id, plan, a.target)
    label = f"Action after round {a.after}: {a.action} round {a.target} ({s.code})"
    done = (
        (s.status == "final" and s.score_sets >= 2)
        if a.action == "correct"
        else (s.status == "final" and s.latest_kind == "void")
    )
    if done:
        log(f"{label}: already done ({s.stage})")
        return
    if s.status == "final":
        if s.max_evidence_at is not None:  # a correction must come after the evidence
            _wait_until(engine, s.max_evidence_at + timedelta(seconds=1), log, stop,
                        "the round's last synthetic evidence")  # fmt: skip
        correction = _flip(engine, s) if a.action == "correct" else None

        def reopen():
            own = session.get("owner", Capability.REOPEN_ROUND)
            imp = co.preview_reopen(engine, own, s.round_id, correction=correction)
            co.reopen_round(engine, own, s.round_id, reason=f"dev scenario {plan.name}",
                            evidence="development scenario plan", confirmation=imp.token,
                            correction=correction)  # fmt: skip

        step("reopen", a.target, reopen)
        log(f"{label}: reopened by the owner" + (" with a correction" if correction else ""))
        s = _state(engine, run_id, plan, a.target)
    if a.action == "invalidate" and s.latest_kind != "void":
        cur = _designation(engine, s.round_id)
        if cur != "void":

            def void():
                p = session.get("operator", Capability.VOID_ROUND)
                imp = co.preview_invalidation(engine, p, s.round_id,
                                              reason=f"dev scenario {plan.name}")  # fmt: skip
                co.invalidate_round(engine, p, s.round_id, reason=f"dev scenario {plan.name}",
                                    confirmation=imp.token)  # fmt: skip

            step("invalidate", a.target, void)
            log(f"{label}: invalidated by the operator")
    step("refinalise", a.target, lambda: _finalise(engine, session, s.round_id))
    s = _state(engine, run_id, plan, a.target)
    log(f"{label}: {s.stage}")
    _verify(engine, log)


def _designation(engine, round_id) -> str | None:
    with transaction(engine) as conn:
        return conn.execute(text(
            "SELECT designation FROM app.designations WHERE round_id = :r "
            "ORDER BY created_at DESC, id DESC LIMIT 1"), {"r": round_id}).scalar()  # fmt: skip


def _flip(engine, s: RoundState):
    """A valid-to-valid correction: the first selected fixture's final score changed
    so that its selections lose (deterministic)."""
    from ..challenge.settle import outcome_wins
    from .services.corrections import CorrectionInput
    from .services.settlement import locked_legs

    with transaction(engine) as conn:
        legs = locked_legs(conn, s.round_id)
    picks: dict[int, set] = {}
    for _, ls, _ in legs.values():
        for x in ls:
            picks.setdefault(x.fixture_id, set()).add((x.market, x.outcome))
    fid = min(picks)
    for h in range(5):
        for aw in range(5):
            if not any(outcome_wins(m, o, h, aw) for m, o in picks[fid]):
                return CorrectionInput(fid, "FT", h, aw)
    return CorrectionInput(fid, "FT", 0, 0)


def _verify(engine, log) -> None:
    from .services.championships import verify_stream

    with transaction(engine) as conn:
        problems = verify_stream(conn, "development")
    if problems:
        raise Stopped("verification failed: " + "; ".join(problems[:3]),
                      "inspect with 'competition verify'; do not continue until it is "
                      "consistent")  # fmt: skip
    log("  verify: development stream consistent")


def _summary(engine) -> str:
    parts = []
    for c in championships(engine):
        champ = (f", champion(s): {', '.join(c.champions)}" if c.champions
                 else ", no champion" if c.status == "completed" else "")  # fmt: skip
        parts.append(f"{c.name}: {c.status} {c.counted}/{c.required}{champ}"
                     + (" [under review]" if c.under_review else ""))  # fmt: skip
    return "Championships (development): " + ("; ".join(parts) if parts else "none")


def random_run_id() -> str:
    return "".join(random.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(6))


__all__ = [
    "DEV_PROVIDER",
    "PRESETS",
    "DevToolError",
    "Plan",
    "Stopped",
    "championships",
    "ensure_participants",
    "inspect_run",
    "participant_principal",
    "plan_from_dict",
    "preset",
    "run_plan",
    "submit_all",
]
