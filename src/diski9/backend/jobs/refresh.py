"""Automated API-Football data refresh for the upcoming Beta week (Phase 6C.6 Stage
E.1b; design ``docs/architecture/phase6c6_stage_e1b_design.md``, plan
``phase6c6_stage_e1b_plan.md``).

Inside ``jobs tick``, after the lifecycle steps and E.1a draft creation and before
readiness, under the same lock, ownership checks and time budget:

* **Slots** — the Balanced schedule (REF-01/03): a daily time Tuesday–Thursday, the
  Friday times before the publication target, then every ``refresh_grace_interval``
  during the grace while the week is unpublished. Only the **current slot** (the
  latest slot not in the future) is worked; earlier slots are never replayed.
* **Sweep** — for the current slot, one ``scheduler.prepare_refresh`` step per league
  (fixtures, then odds) in a fixed order. A league is *done for the slot* only when
  its step **succeeded** with that slot in ``args``; done leagues are not requested
  again in the slot. A sweep is *complete* when every league is done and a
  ``scheduler.prepare_screener`` step (Screener cache) has succeeded for the slot;
  it is closed as *partial* when the slot is superseded or ``refresh_partial_after``
  has passed since its first league step, with at least one league done. A closed
  sweep (complete or partial) is terminal: nothing more runs for that slot.
* **Fetch, then write** (REF-09) — each league's provider requests run with no
  football-store transaction open; ownership is re-verified; the response is then
  applied in one short SQLite transaction with the existing ingestion functions.
* **Provider safety** — every attempt (retries and ``/status`` included) is reserved
  before sending as class ``preparation`` (it can never use the results reserve),
  paced across ticks and refused below the provider floor; a rate limit stops the
  refresh for the tick and records a cooldown honoured by every scheduler request.

It writes only the football store and its own ``job_runs`` rows: no competition
service, no actor, no publication. A completed sweep never means READY; the E.1a
readiness evaluation (the Stage E validator) decides that.

**Competitive refresh (Phase 8 R2, rolling entry only).** For an *open* round on
rules ``rolling/v1`` the planner works the approved competitive slots instead of
stopping at publication: every 3 hours from Friday 06:15 SAST (the publication
preparation sweep) to Sunday 12:15 SAST, overnight included, 19 in all, and never at
or after the entry close (Sunday 14:00 SAST). Only slots after the manual publication
are worked, for the leagues that still have fixtures to come in the published
universe. The planner then lists **one** edition step per closed sweep
(``scheduler.prepare_edition``), which :mod:`.edition_step` runs from preparation
(outside this module's boundary): the candidate is built from the football store and
written as the next immutable edition, or refused with the reason recorded. The same
request reservation, classes, caps, pacing and continuation apply; nothing is
increased. Historical rounds are unchanged (refresh stops at publication).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select, text
from sqlalchemy import func as sa_func

from ..db import db_now, transaction
from ..db.schema import job_runs
from . import locking
from .config import SchedulerConfig
from .locking import LockLost

PREPARE_REFRESH = "scheduler.prepare_refresh"
PREPARE_SCREENER = "scheduler.prepare_screener"
PREPARE_EDITION = "scheduler.prepare_edition"  # Phase 8 R2 (== editions.EDITION_JOB)
REFRESH_JOBS = (PREPARE_REFRESH, PREPARE_SCREENER, PREPARE_EDITION)
# competitive slots (rolling entry): from the window start (Friday 00:00 SAST)
COMPETITIVE_FIRST = timedelta(hours=6, minutes=15)  # Friday 06:15 SAST
COMPETITIVE_EVERY = timedelta(hours=3)
STREAM = "beta"
LEAGUE_ORDER = (39, 40, 140, 61, 78, 135, 288, 289)
MAX_LEAGUE_NEED = 4  # fixtures 1 + odds 1–3 pages (planning estimate; every attempt
#                      is still checked against the caps when it is reserved)
MAX_ODDS_PAGES = 5  # bounds one league step
SCREENER_DAYS = 21  # as ``refresh-data``
SAFETY_FACTOR = 2.0
MEASURE_LAST = 10
STORE_TABLES = frozenset(
    {"fixtures", "seasons", "odds_quotes", "odds_fetches", "ingestion_runs", "screener_results"}
)


class QuotaFloor(Exception):
    """Preparation is held back to protect the provider's daily allowance."""


class FootballStoreUnavailable(Exception):
    """The football store is missing or not set up (fail closed; never created)."""


def enabled(cfg: SchedulerConfig | None) -> bool:
    return bool(
        cfg and cfg.enabled and cfg.prepare and cfg.prepare_refresh and cfg.provider_calls
        and STREAM in cfg.prepare_streams
    )  # fmt: skip


def leagues() -> list[int]:
    from diski9.leagues import COMPETITIONS

    ordered = [c for c in LEAGUE_ORDER if c in COMPETITIONS]
    return ordered + [c for c in COMPETITIONS if c not in ordered]


def _iso(dt: datetime | None) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ") if dt else "-"


# ------------------------------------------------------------------ slots
@dataclass(frozen=True)
class Slot:
    at: datetime
    kind: str  # daily | publication | grace

    def key(self, code: str) -> str:
        return f"{code}@{_iso(self.at)}"

    @property
    def label(self) -> str:
        return f"{self.kind} {_iso(self.at)}"


def slots(week, cfg: SchedulerConfig) -> list[Slot]:
    """The week's refresh slots (UTC), in order."""
    out: list[Slot] = []
    friday = week.window_start.date()
    day = week.period_start.date()
    while day < friday:
        for t in cfg.refresh_daily:
            at = datetime.combine(day, t, UTC)
            if at >= week.period_start:
                out.append(Slot(at, "daily"))
        day += timedelta(days=1)
    for t in cfg.refresh_publication:
        at = datetime.combine(friday, t, UTC)
        if week.period_start <= at < week.target:
            out.append(Slot(at, "publication"))
    at, end = week.target + timedelta(minutes=15), week.target + cfg.prepare_grace
    while at < end:
        out.append(Slot(at, "grace"))
        at += cfg.refresh_grace_interval
    return sorted(set(out), key=lambda s: s.at)


def competitive_slots(window_start: datetime, close: datetime) -> list[Slot]:
    """The rolling-entry competitive sweep slots: every 3 hours from Friday 06:15 SAST
    (window start + 6 h 15 min) while strictly before the entry close. For schedule
    v4 (window Friday 00:00 SAST, close Sunday 14:00 SAST): 19 slots, Friday 06:15 to
    Sunday 12:15 SAST, overnight included."""
    out, at = [], window_start + COMPETITIVE_FIRST
    while at < close:
        out.append(Slot(at, "competitive"))
        at += COMPETITIVE_EVERY
    return out


def current_and_previous(week, cfg: SchedulerConfig, now: datetime
                         ) -> tuple[Slot | None, Slot | None]:  # fmt: skip
    """The slot to work now (none after the grace) and the slot before it."""
    due = [s for s in slots(week, cfg) if s.at <= now]
    if now >= week.target + cfg.prepare_grace:
        return None, (due[-1] if due else None)
    if not due:
        return None, None
    return due[-1], (due[-2] if len(due) > 1 else None)


def next_slot(week, cfg: SchedulerConfig, now: datetime) -> Slot | None:
    if now >= week.target + cfg.prepare_grace:
        return None
    return next((s for s in slots(week, cfg) if s.at > now), None)


# ------------------------------------------------------------------ sweep state
@dataclass
class SweepState:
    key: str
    slot: Slot
    total: int
    done: list[int] = field(default_factory=list)
    fails: dict[int, int] = field(default_factory=dict)  # consecutive, within the slot
    last_fail_at: dict[int, datetime] = field(default_factory=dict)
    last_error: dict[int, str] = field(default_factory=dict)
    details: dict[int, dict[str, str]] = field(default_factory=dict)  # succeeded steps
    first_at: datetime | None = None  # week clock, from the first league step's args
    closed: str | None = None  # complete | partial (a screener step succeeded)
    closed_at: datetime | None = None

    @property
    def state(self) -> str:
        if self.closed:
            return self.closed
        return "in_progress" if self.done else "none"

    @property
    def counts(self) -> str:
        return f"{len(self.done)}/{self.total}"


def sweep_state(conn, week, slot: Slot, names: list[int] | None = None) -> SweepState:
    key = slot.key(week.code)
    names = leagues() if names is None else names
    st = SweepState(key, slot, len(names))
    jr = job_runs.c
    since = _restore_filter(conn)
    rows = conn.execute(
        select(jr.scope, jr.status, jr.finished_at, jr.error, jr.args)
        .where(jr.job == PREPARE_REFRESH, jr.scope.like(f"{week.code}:%"),
               jr.args["slot"].astext == key, *since)
        .order_by(jr.id)
    ).all()  # fmt: skip
    for r in rows:
        at = r.args.get("at")
        if at and (st.first_at is None or datetime.fromisoformat(at) < st.first_at):
            st.first_at = datetime.fromisoformat(at)
        try:
            league = int(r.scope.rsplit(":", 1)[1])
        except ValueError:
            continue
        if r.status == "succeeded":
            if league not in st.done:
                st.done.append(league)
            st.details[league] = parse_detail(r.error)
            st.fails.pop(league, None)
        elif r.status == "failed":
            st.fails[league] = st.fails.get(league, 0) + 1
            st.last_fail_at[league] = r.finished_at
            st.last_error[league] = r.error or ""
    closed = conn.execute(
        select(jr.args, jr.finished_at)
        .where(jr.job == PREPARE_SCREENER, jr.scope == week.code, jr.status == "succeeded",
               jr.args["slot"].astext == key, *since)
        .order_by(jr.id.desc()).limit(1)
    ).one_or_none()  # fmt: skip
    if closed is not None:
        st.closed, st.closed_at = closed.args.get("kind"), closed.finished_at
    return st


def parse_detail(text_: str | None) -> dict[str, str]:
    return dict(p.split("=", 1) for p in (text_ or "").split() if "=" in p)


def _backoff_until(st: SweepState, league: int, cfg: SchedulerConfig) -> datetime | None:
    """Back-off counts failures within the slot only, so a new slot always retries."""
    n = st.fails.get(league, 0)
    if not n:
        return None
    return st.last_fail_at[league] + min(cfg.retry_base * (2 ** (n - 1)), cfg.retry_max)


STORE_RESTORE_JOB = "ops.restore_store"  # == diski9.backup.records.RESTORE_STORE


def _restore_filter(conn) -> tuple:
    """Stage F2 consistency safeguard: after a football-store restore for recovery
    (an ``ops.restore_store`` record), refresh steps that started before it describe
    the old store, so they no longer count (the slot is swept again; readiness says
    ``data=none`` until then)."""
    jr = job_runs.c
    cutoff = conn.execute(
        select(sa_func.max(jr.finished_at))
        .where(jr.job == STORE_RESTORE_JOB, jr.status == "succeeded")
    ).scalar_one()  # fmt: skip
    return () if cutoff is None else (jr.started_at > cutoff,)


def latest_closed(conn, code: str) -> dict | None:
    """The most recent closed sweep of the week (for readiness labels and status),
    ignoring sweeps from before the latest football-store restore."""
    jr = job_runs.c
    row = conn.execute(
        select(jr.args, jr.finished_at)
        .where(jr.job == PREPARE_SCREENER, jr.scope == code, jr.status == "succeeded",
               *_restore_filter(conn))
        .order_by(jr.id.desc()).limit(1)
    ).one_or_none()  # fmt: skip
    if row is None:
        return None
    return dict(row.args) | {"finished_at": row.finished_at}


def data_label(closed: dict | None) -> str:
    """``complete@...`` or ``partial@...(n/8)``: what a readiness verdict was based on."""
    if not closed:
        return "none"
    slot = str(closed.get("slot", "")).rsplit("@", 1)[-1]
    if closed.get("kind") == "complete":
        return f"complete@{slot}"
    return f"partial@{slot}({closed.get('leagues', '?')}/{closed.get('total', '?')})"


# ------------------------------------------------------------------ planning
@dataclass(frozen=True)
class Planned:
    kind: str  # league | screener | edition
    slot: Slot
    league: int | None = None
    close_as: str | None = None  # complete | partial (screener)

    @property
    def step(self) -> str:
        return {"league": "prepare_refresh", "edition": "prepare_edition"}.get(
            self.kind, "prepare_screener"
        )

    def detail(self, code: str) -> str:
        if self.kind == "league":
            return f"league {self.league} for {self.slot.label}"
        if self.kind == "edition":
            return f"price edition after the {self.slot.label} sweep"
        return f"Screener cache; closes the {self.slot.label} sweep as {self.close_as}"


def plan(conn, cfg: SchedulerConfig, week, round_status: str | None,
         now: datetime, real: datetime) -> tuple[list[Planned], str]:  # fmt: skip
    """The refresh work due now and a one-line reason when there is none."""
    if not enabled(cfg):
        return [], "refresh off"
    if round_status == "open":
        rr = _round_row(conn, week.code)
        if rr is not None and rr.rules_version == ROLLING_RULES_VERSION:
            return plan_competitive(conn, cfg, week, rr, now, real)
    if round_status not in (None, "draft"):
        return [], f"week already {round_status}; refresh stops at publication"
    cur, prev = current_and_previous(week, cfg, now)
    steps: list[Planned] = []
    if prev is not None:
        ps = sweep_state(conn, week, prev)
        if ps.done and not ps.closed:  # superseded (or the grace ended) part-way
            steps.append(Planned("screener", prev, close_as="partial"))
    if cur is None:
        why = "the grace period has ended" if now >= week.target else "no refresh slot yet"
        return steps, why
    cs = sweep_state(conn, week, cur)
    if cs.closed:
        return steps, f"{cur.label} sweep {cs.closed} ({cs.counts})"
    if len(cs.done) == cs.total:
        return steps + [Planned("screener", cur, close_as="complete")], ""
    if cs.done and cs.first_at is not None and now >= cs.first_at + cfg.refresh_partial_after:
        return steps + [Planned("screener", cur, close_as="partial")], ""
    waiting = []
    for league in leagues():
        if league in cs.done:
            continue
        until = _backoff_until(cs, league, cfg)
        if until is not None and real < until:
            waiting.append(league)
            continue
        steps.append(Planned("league", cur, league))
    if not steps and waiting:
        return steps, f"leagues {waiting} back off after failures in this slot"
    return steps, ""


ROLLING_RULES_VERSION = "rolling/v1"  # the rolling-entry rules version (Phase 8 R1)


def _round_row(conn, code: str):
    return conn.execute(
        text("SELECT id, rules_version, status, published_at, deadline_at, window_start_at "
             "FROM app.rounds WHERE code = :c"), {"c": code}
    ).one_or_none()  # fmt: skip


def competitive_leagues(conn, round_id, now: datetime) -> list[int]:
    """Leagues with fixtures still to kick off in the round's published universe
    (edition 1), in the usual league order: only these are requested."""
    rows = conn.execute(
        text("SELECT DISTINCT f.competition_id FROM app.snapshot_fixtures f "
             "JOIN app.round_snapshots s ON s.id = f.snapshot_id "
             "WHERE s.round_id = :r AND s.edition = 1 AND f.kickoff_at_publish > :now"),
        {"r": round_id, "now": now},
    ).scalars().all()  # fmt: skip
    wanted = {int(c) for c in rows}
    return [c for c in leagues() if c in wanted]


def _edition_attempted(conn, code: str, key: str) -> bool:
    jr = job_runs.c
    return conn.execute(
        select(sa_func.count()).where(jr.job == PREPARE_EDITION, jr.scope == code,
                                      jr.args["slot"].astext == key,
                                      jr.status.in_(("succeeded", "failed", "skipped")),
                                      *_restore_filter(conn))
    ).scalar_one() > 0  # fmt: skip


def plan_competitive(conn, cfg: SchedulerConfig, week, rr, now: datetime,
                     real: datetime) -> tuple[list[Planned], str]:  # fmt: skip
    """Competitive refresh of an open rolling-entry round (R2): the current slot after
    publication, its leagues with fixtures to come, then one edition step."""
    if now >= rr.deadline_at:
        return [], "competitive refresh stops at the entry close"
    due = [s for s in competitive_slots(rr.window_start_at, rr.deadline_at)
           if rr.published_at <= s.at <= now]  # fmt: skip
    if not due:
        return [], "no competitive slot since publication yet"
    names = competitive_leagues(conn, rr.id, now)
    steps: list[Planned] = []
    if len(due) > 1:
        prev = due[-2]
        ps = sweep_state(conn, week, prev, names)
        if ps.done and not ps.closed:
            steps.append(Planned("screener", prev, close_as="partial"))
        elif ps.closed and not _edition_attempted(conn, week.code, prev.key(week.code)):
            steps.append(Planned("edition", prev))
    cur = due[-1]
    if not names:
        return steps, "no fixtures left to price"
    cs = sweep_state(conn, week, cur, names)
    if cs.closed:
        if not _edition_attempted(conn, week.code, cur.key(week.code)):
            return steps + [Planned("edition", cur)], ""
        return steps, f"{cur.label} sweep {cs.closed} ({cs.counts}); edition attempted"
    if len([d for d in cs.done if d in names]) >= len(names):
        return steps + [Planned("screener", cur, close_as="complete")], ""
    if cs.done and cs.first_at is not None and now >= cs.first_at + cfg.refresh_partial_after:
        return steps + [Planned("screener", cur, close_as="partial")], ""
    waiting = []
    for league in names:
        if league in cs.done:
            continue
        until = _backoff_until(cs, league, cfg)
        if until is not None and real < until:
            waiting.append(league)
            continue
        steps.append(Planned("league", cur, league))
    if not steps and waiting:
        return steps, f"leagues {waiting} back off after failures in this slot"
    return steps, ""


def in_progress(conn, cfg: SchedulerConfig, week, now: datetime) -> bool:
    """A sweep for the current slot has committed leagues but is not closed: the
    scheduler's readiness waits (bounded: the sweep closes as partial at the latest
    ``refresh_partial_after`` after its first league step)."""
    if not enabled(cfg):
        return False
    cur, _ = current_and_previous(week, cfg, now)
    if cur is None:
        return False
    st = sweep_state(conn, week, cur)
    return bool(st.done) and not st.closed


# ------------------------------------------------------------------ football store
def football_store(url: str | None = None) -> Engine:
    """An engine on the football store, checked first; never creates the store."""
    from pathlib import Path

    from sqlalchemy import inspect

    from diski9.config import get_settings
    from diski9.db.engine import make_engine

    target = url or get_settings().database_url
    local = target.startswith("sqlite:///") and not target.startswith("sqlite:///:memory:")
    if local and not Path(target.removeprefix("sqlite:///")).is_file():
        raise FootballStoreUnavailable("football store file not found")
    try:
        engine = make_engine(target)
        names = set(inspect(engine).get_table_names())
    except Exception as exc:  # noqa: BLE001 - never echo the URL
        raise FootballStoreUnavailable(type(exc).__name__) from None
    if not names >= STORE_TABLES:
        engine.dispose()
        raise FootballStoreUnavailable("football store is not set up (run diski9 setup)")
    return engine


def _store(run) -> Engine:
    factory: Callable[[], Engine] = run.store_factory or football_store
    return factory()


# ------------------------------------------------------------------ provider quota
def _status_quota(run, provider, reserve) -> tuple[int, int]:
    """One ``/status`` request (quota-free at the provider; reserved and counted as
    one preparation request here)."""
    resp = provider.call(lambda c: c.get("status"), reserve)
    body = resp.response if isinstance(resp.response, dict) else {}
    req = body.get("requests") or {}
    try:
        current, limit = int(req["current"]), int(req["limit_day"])
    except (KeyError, TypeError, ValueError):
        raise QuotaFloor("provider status did not report the daily usage") from None
    return max(limit - current, 0), limit


def _low_limit(limit: int, expected: int) -> str:
    return (
        f"provider reports a daily limit of {limit} (expected {expected}); preparation stops today"
    )


def quota_gate(run, provider) -> tuple[int, int | None]:
    """Before a refresh step: the most pessimistic usable remaining figure must leave
    the step's maximum need above the floor; a lower reported daily limit stops
    preparation for the provider day. Returns (remaining, limit)."""
    cfg = run.cfg
    with transaction(run.engine) as conn:
        obs = locking.quota_observations(conn, cfg.provider_observation_max_age)
        lowest_limit = locking.limit_today(conn)
    expected = cfg.provider_expected_daily_limit
    if lowest_limit is not None and lowest_limit < expected:
        raise QuotaFloor(_low_limit(lowest_limit, expected))
    if not obs:
        reserve = run.reserver("provider-status", locking.PREPARATION)
        remaining, limit = _status_quota(run, provider, reserve)
        locking.record_quota(run.engine, remaining, limit, "status")
        obs = [locking.QuotaObservation(remaining, limit, "status", datetime.now(UTC))]
        if limit < expected:
            raise QuotaFloor(_low_limit(limit, expected))
    remaining = min(o.remaining for o in obs)
    live, _ = provider.quota
    if live is not None:
        remaining = min(remaining, live)
    if remaining - MAX_LEAGUE_NEED < cfg.prepare_provider_floor:
        raise QuotaFloor(f"provider daily remaining {remaining} is too close to the "
                         f"preparation floor {cfg.prepare_provider_floor}")  # fmt: skip
    limits = [o.limit for o in obs if o.limit is not None]
    return remaining, (min(limits) if limits else None)


def _floor_check(run, provider) -> Callable[[], None]:
    """Before every further attempt of a step: the latest response headers."""

    def check() -> None:
        remaining, limit = provider.quota
        if limit is not None and limit < run.cfg.provider_expected_daily_limit:
            raise QuotaFloor(f"provider reports a daily limit of {limit}")
        if remaining is not None and remaining - 1 < run.cfg.prepare_provider_floor:
            raise QuotaFloor(f"provider daily remaining {remaining} reached the preparation "
                             f"floor {run.cfg.prepare_provider_floor}")  # fmt: skip

    return check


def _observe(run, provider) -> None:
    remaining, limit = provider.quota
    if remaining is not None:
        locking.record_quota(run.engine, remaining, limit, "header")


# ------------------------------------------------------------------ steps
def _slowest(conn) -> float | None:
    from sqlalchemy import func

    jr = job_runs.c
    recent = (
        select((func.extract("epoch", jr.finished_at - jr.started_at)).label("s"))
        .where(jr.job == PREPARE_REFRESH, jr.status == "succeeded", jr.finished_at.isnot(None))
        .order_by(jr.id.desc())
        .limit(MEASURE_LAST)
        .subquery()
    )
    v = conn.execute(select(func.max(recent.c.s))).scalar_one_or_none()
    return float(v) if v is not None else None


def _newest_update(pages) -> datetime | None:
    from diski9.api_football.markets import parse_provider_timestamp

    newest = None
    for page in pages or []:
        for item in page.items:
            u = parse_provider_timestamp(item.get("update"))
            if u is not None and (newest is None or u > newest):
                newest = u
    return newest


def _detail(league: int, fx, odds, newest: datetime | None) -> str:
    parts = [f"league={league}", f"fixtures=+{fx.inserted}~{fx.updated}={fx.unchanged}"]
    if odds is not None:
        status = "inconsistent" if odds.inconsistent_pagination else "ok"
        parts += [f"odds_pages={odds.pages}", f"odds_fixtures={odds.fixtures_collected}",
                  f"quotes={odds.quotes_seen}", f"odds_status={status}",
                  f"provider_update={_iso(newest)}"]  # fmt: skip
    return " ".join(parts)


def _league_step(run, week, slot: Slot, league: int, week_now: datetime):
    from diski9.ingestion.common import MissingReferenceData
    from diski9.ingestion.fixtures import apply_season_fixtures, fetch_season_fixtures
    from diski9.leagues import CURRENT_SEASON, odds_competitions
    from diski9.odds.collect import fetch_odds_pages, reconcile_pages

    from .reconciler import JOB_STATUS, Outcome, StepReport, _begin, _classify, _end, _safe

    scope = f"{week.code}:{league}"
    run.check()  # owner and tick budget before starting
    run_id = _begin(run.engine, PREPARE_REFRESH, scope,
                    {"stream": STREAM, "slot": slot.key(week.code), "league": league,
                     "at": week_now.isoformat(), "tick": run.tick_id, "run_token": run.token,
                     "step": "prepare_refresh"}, run.host)  # fmt: skip
    provider, before, store = None, 0, None
    lost: LockLost | None = None
    try:
        store = _store(run)
        provider = run.get_provider()
        before = provider.requests_made
        quota_gate(run, provider)
        reserve = run.reserver(scope, locking.PREPARATION, check=_floor_check(run, provider))
        started = datetime.now(UTC)
        # 1. fetch: no football-store transaction is open during any provider request
        items = provider.call(lambda c: fetch_season_fixtures(c, league, CURRENT_SEASON), reserve)
        pages = None
        if league in odds_competitions():
            pages = provider.call(
                lambda c: fetch_odds_pages(c, league, CURRENT_SEASON, max_pages=MAX_ODDS_PAGES),
                reserve,
            )
        # 2. still the owner: a tick that lost its lock writes nothing
        run.lock.verify()
        # 3. write: one short transaction with the existing ingestion functions
        with store.begin() as conn:
            fx = apply_season_fixtures(conn, items, league, CURRENT_SEASON,
                                       requests=1)  # fmt: skip
            odds = (
                reconcile_pages(conn, league, CURRENT_SEASON, pages, started=started)
                if pages is not None else None
            )  # fmt: skip
        requests = provider.requests_made - before
        detail = _detail(league, fx, odds, _newest_update(pages))
        with transaction(run.engine) as conn:
            from ..repositories import ops

            ops.finish_job(conn, run_id, JOB_STATUS[Outcome.SUCCEEDED], api_requests=requests,
                           error=detail[:500])  # fmt: skip
        _safe(lambda: _observe(run, provider), [], "recording provider quota")
        return StepReport(week.code, STREAM, "prepare_refresh", Outcome.SUCCEEDED,
                          f"{slot.label}: {detail}", run_id, requests)  # fmt: skip
    except LockLost as exc:
        lost = exc
        outcome, detail = Outcome.RETRYABLE, f"lock lost: {exc}"
    except QuotaFloor as exc:
        outcome, detail = Outcome.DEFERRED, f"provider allowance protected: {exc}"
    except FootballStoreUnavailable as exc:
        outcome, detail = Outcome.BLOCKING, f"football store unavailable ({exc})"
    except MissingReferenceData:
        outcome, detail = Outcome.BLOCKING, "football store setup incomplete (MissingReferenceData)"
    except Exception as exc:  # noqa: BLE001 - classified, recorded, never fatal
        outcome, detail = _classify(exc)
        if "locked" in str(exc).lower() and "database" in str(exc).lower():
            outcome, detail = Outcome.RETRYABLE, "football store busy (another writer)"
        _safe(lambda e=exc: run.note_rate_limit(e, scope), [], "recording a cooldown")
    finally:
        if store is not None:
            store.dispose()
    requests = (provider.requests_made - before) if provider is not None else 0
    if provider is not None:
        _safe(lambda: _observe(run, provider), [], "recording provider quota")
    _end(run.engine, run_id, outcome, detail, requests)
    if lost is not None:
        raise lost
    return StepReport(week.code, STREAM, "prepare_refresh", outcome, detail, run_id, requests)


def _screener_step(run, week, slot: Slot, close_as: str):
    from diski9.leagues import screener_competitions
    from diski9.screener import cache

    from .reconciler import JOB_STATUS, Outcome, StepReport, _begin, _classify, _end

    with transaction(run.engine) as conn:
        st = sweep_state(conn, week, slot)
    run.check()
    run_id = _begin(run.engine, PREPARE_SCREENER, week.code,
                    {"stream": STREAM, "slot": slot.key(week.code), "kind": close_as,
                     "leagues": len(st.done), "total": st.total, "tick": run.tick_id,
                     "run_token": run.token, "step": "prepare_screener"}, run.host)  # fmt: skip
    store = None
    lost: LockLost | None = None
    try:
        store = _store(run)
        run.lock.verify()
        now = datetime.now(UTC)
        with store.begin() as conn:
            ids = cache.upcoming_fixture_ids(conn, screener_competitions(), now,
                                             now + timedelta(days=SCREENER_DAYS))  # fmt: skip
            counts = cache.refresh(conn, ids, now, now)
        detail = (f"{close_as} sweep {len(st.done)}/{st.total} for {slot.label}; Screener "
                  f"cache {len(ids)} fixtures, {counts.get('inserted', 0)} new, "
                  f"{counts.get('superseded', 0)} superseded")  # fmt: skip
        with transaction(run.engine) as conn:
            from ..repositories import ops

            ops.finish_job(conn, run_id, JOB_STATUS[Outcome.SUCCEEDED], error=detail[:500])
        return StepReport(week.code, STREAM, "prepare_screener", Outcome.SUCCEEDED, detail,
                          run_id)  # fmt: skip
    except LockLost as exc:
        lost = exc
        outcome, detail = Outcome.RETRYABLE, f"lock lost: {exc}"
    except FootballStoreUnavailable as exc:
        outcome, detail = Outcome.BLOCKING, f"football store unavailable ({exc})"
    except Exception as exc:  # noqa: BLE001
        outcome, detail = _classify(exc)
    finally:
        if store is not None:
            store.dispose()
    _end(run.engine, run_id, outcome, detail)
    if lost is not None:
        raise lost
    return StepReport(week.code, STREAM, "prepare_screener", outcome, detail, run_id)


def needed_seconds(slowest: float | None, cfg: SchedulerConfig) -> float:
    return max(cfg.prepare_min_seconds, SAFETY_FACTOR * (slowest or 0.0))


def run_refresh(run, report, week, round_status: str | None) -> None:
    """Work the current slot until done, out of allowance or out of tick time."""
    from .prepare import _now
    from .reconciler import Outcome, StepReport

    cfg = run.cfg
    caps = locking.Caps(cfg.max_requests_per_tick, cfg.max_requests_per_day,
                        cfg.nonessential_per_day, cfg.results_reserve)  # fmt: skip
    attempted: set[tuple[str, str, int | None]] = set()
    for _ in range(4 * len(leagues()) + 4):
        if run.rate_limited:
            report.steps.append(StepReport(week.code, STREAM, "prepare_refresh",
                                           Outcome.DEFERRED, "provider rate limit this tick; "
                                           "refresh continues after the cooldown"))  # fmt: skip
            return
        with transaction(run.engine) as conn:
            now, real = _now(conn), db_now(conn)
            todo, why = plan(conn, cfg, week, round_status, now, real)
            slowest = _slowest(conn)
        # edition steps run outside this module (``jobs.edition_step``, after the sweep):
        # the refresh code itself never touches competition data
        todo = [p for p in todo if p.kind != "edition"
                and (p.slot.key(week.code), p.kind, p.league) not in attempted]  # fmt: skip
        if not todo:
            return
        p = todo[0]
        attempted.add((p.slot.key(week.code), p.kind, p.league))
        if p.kind == "screener":
            report.steps.append(_screener_step(run, week, p.slot, p.close_as or "partial"))
            continue
        left, scope = locking.allowance(run.engine, run.token, cfg.max_requests_per_tick,
                                        cfg.max_requests_per_day, klass=locking.PREPARATION,
                                        caps=caps)  # fmt: skip
        if left < MAX_LEAGUE_NEED:
            why = (f"{left} request(s) left ({scope}); league {p.league} and the rest of "
                   "the sweep continue next tick")  # fmt: skip
            report.steps.append(StepReport(week.code, STREAM, "prepare_refresh",
                                           Outcome.DEFERRED, why))  # fmt: skip
            return
        need = needed_seconds(slowest, cfg)
        if run.deadline - time.monotonic() < need:
            report.steps.append(StepReport(week.code, STREAM, "prepare_refresh",
                                           Outcome.DEFERRED,
                                           f"needs about {need:.0f} s of tick time; the sweep "
                                           "continues next tick"))  # fmt: skip
            return
        rep = _league_step(run, week, p.slot, p.league, now)
        report.steps.append(rep)
        if rep.outcome in (Outcome.BLOCKING, Outcome.DEFERRED):
            return  # store unavailable, access refused, budget, floor or cooldown


# ------------------------------------------------------------------ status (derived)
@dataclass
class RefreshStatus:
    enabled: bool
    slot: Slot | None = None
    sweep: SweepState | None = None
    next_slot: Slot | None = None
    last_complete: dict | None = None
    last_closed: dict | None = None
    failing: dict[int, tuple[int, str]] = field(default_factory=dict)
    cooldown_until: datetime | None = None
    quota_remaining: int | None = None
    quota_limit: int | None = None
    quota_source: str | None = None
    quota_at: datetime | None = None
    quota_gap: float | None = None  # relative disagreement between sources
    limit_today: int | None = None
    used_day: int = 0
    used_preparation: int = 0
    throttled_24h: int = 0
    coverage_drop: list[int] = field(default_factory=list)  # odds vanished this slot
    update_not_today: list[int] = field(default_factory=list)  # provider update older
    caps: dict[str, int] = field(default_factory=dict)
    week_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "slot": None if self.slot is None else self.slot.label,
            "sweep": None if self.sweep is None else {
                "state": self.sweep.state, "done": len(self.sweep.done),
                "total": self.sweep.total, "failing": sorted(self.sweep.fails),
            },
            "next_slot": None if self.next_slot is None else self.next_slot.label,
            "last_complete": self.last_complete,
            "last_closed": self.last_closed,
            "cooldown_until": self.cooldown_until,
            "quota": {"remaining": self.quota_remaining, "limit": self.quota_limit,
                      "source": self.quota_source, "observed_at": self.quota_at},
            "usage_24h": {"total": self.used_day, "preparation": self.used_preparation,
                          "results": self.used_day - self.used_preparation},
            "caps": self.caps,
        }  # fmt: skip


def refresh_status(conn, cfg: SchedulerConfig | None, week, now: datetime) -> RefreshStatus:
    """Read-only refresh state of the week (job records only)."""
    st = RefreshStatus(enabled=enabled(cfg), week_code=week.code)
    _, day, prep = locking.usage_by_class(conn, "")
    st.used_day, st.used_preparation = day, prep
    if cfg is not None:
        st.caps = {"per_tick": cfg.max_requests_per_tick, "per_day": cfg.max_requests_per_day,
                   "nonessential": cfg.nonessential_per_day,
                   "results_reserve": cfg.results_reserve}  # fmt: skip
    st.cooldown_until = locking.cooldown_until(conn)
    age = cfg.provider_observation_max_age if cfg else timedelta(minutes=30)
    obs = locking.quota_observations(conn, age)
    if obs:
        low = min(obs, key=lambda o: o.remaining)
        st.quota_remaining, st.quota_limit = low.remaining, low.limit
        st.quota_source, st.quota_at = low.source, low.observed_at
        srcs = {o.source: o.remaining for o in obs}
        if "header" in srcs and "status" in srcs and max(srcs.values()):
            st.quota_gap = abs(srcs["header"] - srcs["status"]) / max(srcs.values())
    st.limit_today = locking.limit_today(conn)
    st.throttled_24h = int(conn.execute(
        text("SELECT count(*) FROM app.job_runs WHERE job = :j AND started_at >= "
             "clock_timestamp() - interval '24 hours'"), {"j": locking.COOLDOWN_JOB},
    ).scalar_one())  # fmt: skip
    st.last_closed = latest_closed(conn, week.code)
    jr = job_runs.c
    row = conn.execute(
        select(jr.args, jr.finished_at)
        .where(jr.job == PREPARE_SCREENER, jr.scope == week.code, jr.status == "succeeded",
               jr.args["kind"].astext == "complete")
        .order_by(jr.id.desc()).limit(1)
    ).one_or_none()  # fmt: skip
    if row is not None:
        st.last_complete = dict(row.args) | {"finished_at": row.finished_at}
    if cfg is None:
        return st
    cur, _ = current_and_previous(week, cfg, now)
    st.slot, st.next_slot = cur, next_slot(week, cfg, now)
    if cur is not None:
        st.sweep = sweep_state(conn, week, cur)
        for league, n in st.sweep.fails.items():
            st.failing[league] = (n, st.sweep.last_error.get(league, ""))
        earlier = _leagues_with_odds_before(conn, week.code, st.sweep.key)
        for league, d in st.sweep.details.items():
            if d.get("odds_fixtures") == "0" and league in earlier:
                st.coverage_drop.append(league)
            upd = d.get("provider_update", "-")
            if (
                d.get("odds_fixtures", "0") != "0"
                and upd != "-"
                and upd[:10] < cur.at.strftime("%Y-%m-%d")
            ):
                st.update_not_today.append(league)
    return st


def _leagues_with_odds_before(conn, code: str, key: str) -> set[int]:
    """Leagues whose earlier successful refresh this week collected odds fixtures."""
    jr = job_runs.c
    rows = conn.execute(
        select(jr.scope, jr.error).where(
            jr.job == PREPARE_REFRESH,
            jr.scope.like(f"{code}:%"),
            jr.status == "succeeded",
            jr.args["slot"].astext != key,
        )
    ).all()
    out: set[int] = set()
    for r in rows:
        if parse_detail(r.error).get("odds_fixtures", "0") != "0":
            out.add(int(r.scope.rsplit(":", 1)[1]))
    return out


def refresh_lines(st: RefreshStatus | None) -> list[str]:
    if st is None:
        return []
    lines = [f"  data refresh ({'on' if st.enabled else 'off'})"]
    if st.slot is not None and st.sweep is not None:
        lines.append(f"    current slot {st.slot.label}: sweep {st.sweep.state} "
                     f"({st.sweep.counts} leagues)")  # fmt: skip
    if st.last_complete:
        lines.append(f"    last complete sweep {data_label(st.last_complete)} at "
                     f"{_iso(st.last_complete.get('finished_at'))}")  # fmt: skip
    if st.last_closed and st.last_closed.get("kind") == "partial":
        lines.append(f"    last sweep closed partial: {data_label(st.last_closed)}")
    for league, (n, err) in sorted(st.failing.items()):
        lines.append(f"    league {league} failing {n} time(s) in this slot: {err}")
    if st.next_slot is not None:
        lines.append(f"    next slot {st.next_slot.label}")
    if st.cooldown_until is not None:
        lines.append(f"    provider cooldown until {_iso(st.cooldown_until)}")
    if st.quota_remaining is not None:
        lines.append(f"    provider remaining {st.quota_remaining}"
                     + (f" of {st.quota_limit}" if st.quota_limit else "")
                     + f" ({st.quota_source}, {_iso(st.quota_at)})")  # fmt: skip
    caps = st.caps
    if caps:
        lines.append(f"    scheduler requests in 24 h: {st.used_day}/{caps['per_day']} "
                     f"(preparation {st.used_preparation}/{caps['nonessential']}, results "
                     f"reserve {caps['results_reserve']})")  # fmt: skip
    return lines


def readiness_line(engine: Engine, code: str) -> str:
    """One display-only line for ``round readiness`` (owner decision D-3): which
    automated data sweep the football store reflects. Reads job records only; it
    never affects the checks, the snapshot, its fingerprint or publication."""
    jr = job_runs.c
    with transaction(engine) as conn:
        closed = latest_closed(conn, code)
        last = conn.execute(
            select(jr.args).where(jr.job == PREPARE_REFRESH, jr.scope.like(f"{code}:%"))
            .order_by(jr.id.desc()).limit(1)
        ).scalar_one_or_none()  # fmt: skip
        if last is None and closed is None:
            return "no automated refresh recorded for this week (manual refresh-data)"
        open_key = last.get("slot") if last else None
        if open_key and (closed is None or open_key != closed.get("slot")):
            done = conn.execute(
                select(func_count()).where(
                    jr.job == PREPARE_REFRESH, jr.scope.like(f"{code}:%"),
                    jr.status == "succeeded", jr.args["slot"].astext == open_key,
                )
            ).scalar_one()  # fmt: skip
            slot = str(open_key).rsplit("@", 1)[-1]
            return (f"sweep for {slot} in progress ({done}/{len(leagues())} leagues); "
                    "check again when it completes")  # fmt: skip
    when = _iso(closed.get("finished_at")) if closed else "-"
    return f"{data_label(closed)} (closed {when})"


def func_count():
    from sqlalchemy import func

    return func.count()
