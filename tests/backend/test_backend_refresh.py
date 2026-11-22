"""Phase 6C.6 Stage E.1b: automated API-Football refresh inside ``jobs tick``.

Isolated PostgreSQL databases, a temporary SQLite football store and a mock
API-Football transport (no live provider call: the transport answers every request
itself). The week clock is placed on a chosen weekday as in the E.1a tests; the
football store and the ledger use the real clock. Sweeps span several ticks, as they
do in production.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from champ_helpers import drop, isolated_engine
from test_backend_prepare import PREP, builder, place_clock

from diski9.api_football import ApiFootballClient
from diski9.api_football.ratelimit import RateLimiter
from diski9.backend.db import transaction
from diski9.backend.jobs import locking, plan_tick, prepare, refresh, tick
from diski9.backend.jobs.config import ConfigError
from diski9.backend.jobs.locking import LockLost, TickLock
from diski9.backend.jobs.provider import ApiFootballProvider
from diski9.backend.ops import OpsConfig, collect, evaluate
from diski9.backend.ops.checks import Severity
from diski9.db import make_engine, upgrade
from diski9.db.schema import fixtures, odds_fetches, odds_quotes
from tests.conftest import envelope
from tests.factories import fixture_item, full_book, odds_item, seed_competition

LEAGUES = refresh.leagues()
NO_ODDS = (288, 289)  # the provider returns an empty odds page for these (observed)
REFRESH = replace(PREP, provider_calls=True, prepare_refresh=True, max_requests_per_tick=20,
                  max_requests_per_day=450)  # fmt: skip
FRI_0420 = 3 * 24 + 4 + 20 / 60  # hours after Tuesday 00:00 UTC
SRC = Path(__file__).resolve().parents[2] / "src" / "diski9" / "backend" / "jobs" / "refresh.py"


@pytest.fixture
def db(pg_url, request):
    name = f"diski9_rf_{request.node.name[:33].lower()}_test".replace("[", "_").replace("]", "")
    eng, url = isolated_engine(pg_url, name)
    try:
        yield eng
    finally:
        eng.dispose()
        drop(pg_url, name)


@pytest.fixture
def store(tmp_path):
    """An empty, set-up football store: competitions and seasons, no fixtures."""
    url = f"sqlite:///{tmp_path / 'football.sqlite'}"
    upgrade(url)
    eng = make_engine(url)
    with eng.begin() as c:
        for cid in LEAGUES:
            seed_competition(c, cid, name=f"League {cid}")
    eng.dispose()
    return url


class Api:
    """The mock provider: per-league fixtures (12 each: odds come in 2 pages of 10),
    odds, and ``/status``. Records every request; ``fail(path, league, n)`` may
    return a response to send instead (n = earlier requests of that path/league)."""

    def __init__(self, week, *, per_league=12, remaining=7000, limit=7500, update=None):
        self.calls: list[tuple[str, int]] = []
        self.fail = lambda path, league, n: None
        self.remaining, self.limit = remaining, limit
        self.update = update or datetime.now(UTC).isoformat()
        self.fixtures = {
            cid: [fixture_item(cid * 1000 + i, cid * 100 + 2 * i, cid * 100 + 2 * i + 1,
                               league=cid, status="NS",
                               kickoff=week.window_start + timedelta(hours=18 + 2 * i))
                  for i in range(per_league)]
            for cid in LEAGUES
        }  # fmt: skip

    def headers(self):
        return {"x-ratelimit-requests-limit": str(self.limit),
                "x-ratelimit-requests-remaining": str(self.remaining),
                "X-RateLimit-Limit": "300", "X-RateLimit-Remaining": "299"}  # fmt: skip

    def handler(self, request):
        path = request.url.path.strip("/")
        league = int(request.url.params.get("league", 0) or 0)
        n = self.calls.count((path, league))
        self.calls.append((path, league))
        override = self.fail(path, league, n)
        if override is not None:
            return override
        if path == "status":
            body = {"get": "status", "errors": [], "results": 1, "paging": {"current": 1,
                    "total": 1}, "response": {"requests": {"current": self.limit -
                    self.remaining, "limit_day": self.limit}}}  # fmt: skip
            return httpx.Response(200, json=body, headers=self.headers())
        if path == "fixtures":
            return httpx.Response(200, json=envelope(self.fixtures[league]),
                                  headers=self.headers())  # fmt: skip
        items = [] if league in NO_ODDS else [
            odds_item(f["fixture"]["id"], {8: full_book(), 11: full_book(home="2.10"),
                                           16: full_book(home="1.95")},
                      league=league, update=self.update,
                      kickoff=datetime.fromisoformat(f["fixture"]["date"]))
            for f in self.fixtures[league] if f["fixture"]["status"]["short"] == "NS"
        ]  # fmt: skip
        page = int(request.url.params.get("page", 1))
        total = max(1, -(-len(items) // 10))
        return httpx.Response(200, json=envelope(items[(page - 1) * 10 : page * 10],
                                                 current=page, total=total),
                              headers=self.headers())  # fmt: skip

    def provider(self):
        client = ApiFootballClient(
            transport=httpx.MockTransport(self.handler), sleep=lambda s: None,
            rate_limiter=RateLimiter(min_interval_seconds=0.0, sleep=lambda s: None),
            backoff_seconds=0.0, max_retries=1, max_wait_seconds=30,
        )  # fmt: skip
        return ApiFootballProvider(client)

    def count(self, path, league=None):
        return sum(1 for p, lg in self.calls if p == path and (league is None or lg == league))


def run(eng, api, store_url, cfg=REFRESH, *, store_factory=None, sleep=None, snap=None):
    return tick(eng, cfg, provider_factory=api.provider,
                store_factory=store_factory or (lambda: refresh.football_store(store_url)),
                snapshot_builder=snap or builder(), sleep=sleep or (lambda s: None))  # fmt: skip


def steps(report, name=None):
    return [s for s in report.steps if name is None or s.step == name]


def sweep(eng, week, cfg=REFRESH):
    with transaction(eng) as conn:
        cur, _ = refresh.current_and_previous(week, cfg, prepare._now(conn))
        return refresh.sweep_state(conn, week, cur)


def ledger(eng, token=None):
    with transaction(eng) as conn:
        return conn.execute(sa.text(
            "SELECT args, scope FROM app.job_runs WHERE job = 'scheduler.provider' "
            + ("AND args->>'run_token' = :t " if token else "") + "ORDER BY id"),
            {"t": token} if token else {}).all()  # fmt: skip


def store_count(url, table, *where):
    eng = make_engine(url)
    try:
        with eng.connect() as c:
            return c.execute(sa.select(sa.func.count()).select_from(table).where(*where)
                             ).scalar_one()  # fmt: skip
    finally:
        eng.dispose()


def readiness_rows(eng, code):
    with transaction(eng) as conn:
        return conn.execute(sa.text(
            "SELECT status, error FROM app.job_runs WHERE job = 'scheduler.prepare_readiness' "
            "AND scope = :c ORDER BY id"), {"c": code}).all()  # fmt: skip


def findings(eng, cfg=REFRESH):
    snap = collect(eng, environment="test", finalise_warning=timedelta(hours=6), jobs=cfg)
    return {f.code: f for f in evaluate(snap, OpsConfig(), cfg)}


# ------------------------------------------------------------------ sweeps across ticks
def test_friday_sweep_spans_two_ticks_and_closes_complete(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    r1 = run(db, api, store)
    done1 = [s for s in steps(r1, "prepare_refresh") if s.outcome == "succeeded"]
    assert len(done1) == 6  # /status 1 + 6 x 3 = 19; the next league needs up to 4
    assert any("continue next tick" in s.detail for s in steps(r1, "prepare_refresh"))
    assert sweep(db, w).state == "in_progress"
    assert not steps(r1, "prepare_readiness")  # waits for the sweep
    r2 = run(db, api, store)
    assert [s.outcome for s in steps(r2, "prepare_refresh")] == ["succeeded"] * 2
    assert [s.step for s in r2.steps][-2:] == ["prepare_screener", "prepare_readiness"]
    st = sweep(db, w)
    assert st.state == "complete" and len(st.done) == 8
    assert "data=complete@" in readiness_rows(db, w.code)[-1].error
    # each league's fixtures and odds requested exactly once in the slot
    assert all(api.count("fixtures", cid) == 1 for cid in LEAGUES)
    assert api.count("status") == 1 and len(api.calls) == 23
    assert len(ledger(db)) == 23  # every request reserved, nothing more
    assert {r.args["class"] for r in ledger(db)} == {"preparation"}
    assert store_count(store, fixtures) == 96
    assert store_count(store, odds_quotes) > 0


def test_ten_per_tick_takes_three_ticks(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    cfg = replace(REFRESH, max_requests_per_tick=10)
    states = []
    for _ in range(3):
        r = run(db, api, store, cfg)
        assert len(ledger(db, r.steps and _token(db, r))) <= 10
        states.append(sweep(db, w, cfg).state)
    assert states == ["in_progress", "in_progress", "complete"]
    assert all(api.count("fixtures", cid) == 1 for cid in LEAGUES)


def _token(eng, report):
    with transaction(eng) as conn:
        return conn.execute(sa.text("SELECT args->>'run_token' FROM app.job_runs WHERE id = :i"),
                            {"i": report.tick_run_id}).scalar_one()  # fmt: skip


def test_a_closed_sweep_is_terminal_for_its_slot(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    run(db, api, store)
    run(db, api, store)
    before = len(api.calls)
    r3 = run(db, api, store)
    assert len(api.calls) == before and not steps(r3, "prepare_refresh")


# ------------------------------------------------------------------ partial sweeps
def test_failed_0415_sweep_closes_partial_then_0515_recovers(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    api.fail = lambda path, league, n: (httpx.Response(503) if (path, league) ==
                                        ("fixtures", 39) and api.mode == "broken" else None)  # fmt: skip
    api.mode = "broken"
    nowait = replace(REFRESH, retry_base=timedelta(0), retry_max=timedelta(0))
    run(db, api, store, nowait)
    run(db, api, store, nowait)  # the failing league is retried (no back-off here)
    st = sweep(db, w)
    assert st.state == "in_progress" and 39 not in st.done and len(st.done) == 7
    assert st.fails[39] >= 2
    assert {f for f in findings(db)} >= {"refresh_failing"}
    place_clock(monkeypatch, db, FRI_0420 + 31 / 60)  # 04:51: 30 min after the first step
    r = run(db, api, store)
    assert [s.step for s in r.steps if s.step.startswith("prepare_s")] == ["prepare_screener"]
    st = sweep(db, w)
    assert st.state == "partial" and st.counts == "7/8"
    label = readiness_rows(db, w.code)[-1].error
    assert "data=partial@" in label and "(7/8)" in label and "complete" not in label
    assert "refresh_partial" in findings(db)
    r = run(db, api, store)  # terminal: nothing more for the 04:15 slot
    assert not steps(r, "prepare_refresh")
    # 05:20: the confirmation slot refreshes every league again, the provider recovered
    api.mode = "ok"
    place_clock(monkeypatch, db, FRI_0420 + 1)
    run(db, api, store)
    run(db, api, store)
    st = sweep(db, w)
    assert st.state == "complete" and st.slot.label.endswith("05:15Z")
    assert all(api.count("fixtures", cid) >= 2 for cid in LEAGUES if cid != 39)
    assert "data=complete@" in readiness_rows(db, w.code)[-1].error


def test_superseded_sweep_is_closed_partial_and_bounded(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    cfg = replace(REFRESH, max_requests_per_tick=10)
    run(db, api, store, cfg)  # /status + 2 leagues (9 left, then 3 < the 4 a league may need)
    place_clock(monkeypatch, db, FRI_0420 + 1)  # 05:20: the next slot is current
    r = run(db, api, store, cfg)
    scr = steps(r, "prepare_screener")
    assert scr and scr[0].outcome == "succeeded" and "partial sweep 2/8" in scr[0].detail
    with transaction(db) as conn:
        old = refresh.sweep_state(conn, w, refresh.slots(w, cfg)[3])  # Friday 04:15
    assert old.state == "partial" and len(old.done) == 2
    assert sweep(db, w, cfg).slot.label.endswith("05:15Z")
    assert len(sweep(db, w, cfg).done) >= 1  # the new slot starts from the first league


# ------------------------------------------------------------------ retries and budgets
def test_retries_are_reserved_and_count_against_preparation(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    api.fail = lambda path, league, n: (httpx.Response(503) if (path, league, n) ==
                                        ("fixtures", 40, 0) else None)  # fmt: skip
    run(db, api, store)
    run(db, api, store)
    assert api.count("fixtures", 40) == 2  # the failed attempt and its retry
    assert len(ledger(db)) == len(api.calls) == 24
    assert all(r.args["class"] == "preparation" for r in ledger(db))


def test_capacity_exhausted_mid_league_leaves_it_incomplete(db, store, monkeypatch):
    """The four-request estimate is not a guarantee: a retry plus three odds pages
    needs six. The per-tick cap is enforced on every attempt; the league stops,
    writes nothing and is not counted towards the sweep."""
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w, per_league=25)  # 3 odds pages
    api.fail = lambda path, league, n: (httpx.Response(503) if (path, league, n) ==
                                        ("fixtures", 39, 0) else None)  # fmt: skip
    cfg = replace(REFRESH, max_requests_per_tick=5)
    r = run(db, api, store, cfg)
    step = steps(r, "prepare_refresh")[0]
    assert step.outcome == "deferred" and "budget exhausted" in step.detail
    assert len(ledger(db, _token(db, r))) == 5  # never more than the cap
    assert 39 not in sweep(db, w, cfg).done
    assert store_count(store, fixtures) == 0 and store_count(store, odds_fetches) == 0


def test_rate_limit_records_a_cooldown_and_stops_refresh(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    api.fail = lambda path, league, n: (httpx.Response(429, headers={"Retry-After": "600"})
                                        if (path, league) == ("fixtures", 40) else None)  # fmt: skip
    r = run(db, api, store)
    outcomes = [(s.detail[:40], s.outcome) for s in steps(r, "prepare_refresh")]
    assert outcomes[1][1] == "retryable_failure" and "rate limited" in outcomes[1][0]
    assert "rate limit" in steps(r, "prepare_refresh")[-1].detail  # nothing more this tick
    assert api.count("fixtures") == 2  # league 39, then the rate-limited league 40
    with transaction(db) as conn:
        assert locking.cooldown_until(conn) is not None
    r2 = run(db, api, store)  # the cooldown is honoured: no request at all
    assert api.count("fixtures") == 2
    assert steps(r2, "prepare_refresh")[0].outcome == "deferred"
    assert "provider_throttled" in findings(db)


# ------------------------------------------------------------------ provider quota
def test_status_preflight_is_reserved_and_recorded(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    run(db, api, store)
    assert api.calls[0] == ("status", 0)
    first = ledger(db)[0]
    assert first.scope == "provider-status" and first.args["class"] == "preparation"
    with transaction(db) as conn:
        obs = locking.quota_observations(conn, timedelta(minutes=30))
    assert {o.source for o in obs} == {"status", "header"}


def test_quota_floor_defers_refresh_without_requesting_data(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w, remaining=1500)
    r = run(db, api, store)
    step = steps(r, "prepare_refresh")[0]
    assert step.outcome == "deferred" and "preparation floor" in step.detail
    assert api.calls == [("status", 0)]
    assert findings(db)["provider_quota_low"].severity == Severity.WARNING


def test_a_lower_daily_limit_stops_preparation(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w, remaining=90, limit=100)
    r = run(db, api, store)
    assert "daily limit of 100" in steps(r, "prepare_refresh")[0].detail
    assert findings(db)["provider_limit_mismatch"].severity == Severity.CRITICAL
    run(db, api, store)
    assert api.count("status") == 1 and api.count("fixtures") == 0  # stopped for the day


# ------------------------------------------------------------------ recovery
def test_lock_lost_between_fetch_and_write_writes_nothing(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    import diski9.odds.collect as collect_mod

    state = {"fetched": False}
    original_fetch, original_verify = collect_mod.fetch_odds_pages, TickLock.verify

    def fetch(*a, **k):
        out = original_fetch(*a, **k)
        state["fetched"] = True
        return out

    def verify(self):
        if state["fetched"]:
            raise LockLost("server session ended")
        return original_verify(self)

    monkeypatch.setattr(collect_mod, "fetch_odds_pages", fetch)
    monkeypatch.setattr(TickLock, "verify", verify)
    r = run(db, api, store)
    assert r.status == "lock_lost"
    assert store_count(store, fixtures) == 0 and store_count(store, odds_fetches) == 0
    assert sweep(db, w).done == []


def test_a_failure_while_writing_rolls_the_league_back(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    import diski9.odds.collect as collect_mod

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(collect_mod, "reconcile_pages", boom)
    r = run(db, api, store)
    first = steps(r, "prepare_refresh")[0]
    assert first.outcome == "retryable_failure"
    assert store_count(store, fixtures) == 0  # the fixtures of the same transaction too
    assert sweep(db, w).done == []


def test_a_busy_store_is_retryable_and_recovers(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    holder = sa.create_engine(store)
    conn = holder.connect()
    conn.exec_driver_sql("BEGIN IMMEDIATE")  # another writer holds the store

    def busy_store():
        eng = sa.create_engine(store, connect_args={"timeout": 0.1})
        return eng

    try:
        r = run(db, api, store, store_factory=busy_store)
        first = steps(r, "prepare_refresh")[0]
        assert first.outcome == "retryable_failure" and "busy" in first.detail
    finally:
        conn.exec_driver_sql("ROLLBACK")
        conn.close()
        holder.dispose()
    assert sweep(db, w).done == []


def test_interruption_during_a_pacing_wait_is_recovered(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    cfg = replace(REFRESH, provider_min_interval=1.0)

    def interrupted(seconds):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(db, api, store, cfg, sleep=interrupted)
    with transaction(db) as conn:
        marked = conn.execute(sa.text(
            "SELECT count(*) FROM app.job_runs WHERE job = 'scheduler.prepare_refresh' "
            "AND status = 'failed' AND error LIKE 'abandoned: interrupted%'")).scalar_one()  # fmt: skip
        running = conn.execute(sa.text(
            "SELECT count(*) FROM app.job_runs WHERE status = 'running'")).scalar_one()  # fmt: skip
    assert marked == 1 and running == 0
    # the interrupted league backs off like any failed step (here: no delay)
    again = replace(REFRESH, retry_base=timedelta(0), retry_max=timedelta(0))
    for _ in range(3):
        run(db, api, store, again)
    assert sweep(db, w).state == "complete"
    assert store_count(store, fixtures) == 96  # no duplicates after the rerun


def test_a_second_sweep_is_idempotent(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    run(db, api, store)
    run(db, api, store)
    quotes = store_count(store, odds_quotes)
    place_clock(monkeypatch, db, FRI_0420 + 1)
    run(db, api, store)
    run(db, api, store)
    assert sweep(db, w).state == "complete"
    assert store_count(store, fixtures) == 96
    assert store_count(store, odds_quotes) == quotes  # unchanged prices extend episodes


# ------------------------------------------------------------------ data and readiness
def test_refresh_never_makes_a_round_ready_by_itself(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    thin = builder(fixtures=3)  # the validator says NOT READY
    run(db, api, store, snap=thin)
    run(db, api, store, snap=thin)
    assert sweep(db, w).state == "complete"
    last = readiness_rows(db, w.code)[-1].error
    assert last.startswith("not_ready[") and "data=complete@" in last


def test_stale_odds_become_eligible_after_a_post_update_sweep(db, store, monkeypatch):
    from diski9.api_football.markets import Market
    from diski9.odds.consensus import fixture_consensus

    w = place_clock(monkeypatch, db, FRI_0420)
    stale = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
    api = Api(w, update=stale)
    run(db, api, store)
    run(db, api, store)
    eng = make_engine(store)

    def eligible():
        with eng.connect() as c:
            cons = fixture_consensus(c, 39000, datetime.now(UTC))
            return cons[Market.MATCH_RESULT].challenge_eligible

    try:
        assert not eligible()  # the provider update is older than 24 hours
        api.update = datetime.now(UTC).isoformat()  # today's provider update
        api.fixtures[39][1]["fixture"]["status"] = {"short": "PST", "long": "Postponed"}
        place_clock(monkeypatch, db, FRI_0420 + 1)
        run(db, api, store)
        run(db, api, store)
        assert eligible()
        with eng.connect() as c:
            status = c.execute(sa.select(fixtures.c.status_short).where(
                fixtures.c.id == 39001)).scalar_one()  # fmt: skip
        assert status == "PST"  # a postponed fixture leaves the upcoming pool
    finally:
        eng.dispose()


def test_refresh_off_keeps_e1a_behaviour(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    r = run(db, api, store, replace(REFRESH, prepare_refresh=False))
    assert api.calls == [] and not steps(r, "prepare_refresh")
    assert [s.step for s in r.steps] == ["prepare_draft", "prepare_readiness"]
    assert "data=refresh-off" in readiness_rows(db, w.code)[-1].error
    assert "refresh_disabled" in findings(db, replace(REFRESH, prepare_refresh=False))


def test_no_refresh_after_publication_or_outside_beta(db, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    with transaction(db) as conn:
        now = prepare._now(conn)
        assert refresh.plan(conn, REFRESH, w, "open", now, now)[0] == []
        assert refresh.plan(conn, REFRESH, w, "draft", now, now)[0]
        assert refresh.plan(conn, replace(REFRESH, prepare_refresh=False), w, None, now,
                            now)[0] == []  # fmt: skip
        after_grace = w.target + REFRESH.prepare_grace
        assert refresh.plan(conn, REFRESH, w, "draft", after_grace, now)[0] == []
    assert not refresh.enabled(None)
    with pytest.raises(ConfigError):  # refresh is Beta-only and needs preparation
        replace(REFRESH, prepare_streams=())


# ------------------------------------------------------------------ monitoring
def test_monitoring_status_dry_run_and_readiness_line(db, store, monkeypatch):
    w = place_clock(monkeypatch, db, FRI_0420)
    api = Api(w)
    assert refresh.readiness_line(db, w.code).startswith("no automated refresh")
    plan = plan_tick(db, REFRESH)
    assert [s.step for s in plan.steps if s.step == "prepare_refresh"]  # dry run lists it
    assert api.calls == []  # a dry run sends nothing
    run(db, api, store)
    assert "in progress (6/8 leagues)" in refresh.readiness_line(db, w.code)
    run(db, api, store)
    assert refresh.readiness_line(db, w.code).startswith("complete@")
    st = prepare.preparation_status(db, REFRESH)
    lines = "\n".join(prepare.preparation_lines(st))
    assert "data refresh (on)" in lines and "sweep complete (8/8 leagues)" in lines
    assert "scheduler requests in 24 h: 23/450 (preparation 23/300" in lines
    found = findings(db)
    assert found["refresh_ok"].severity == Severity.INFO
    assert not {"store_not_current", "refresh_partial", "refresh_failing"} & set(found)


def test_store_not_current_escalates_before_the_target(db, monkeypatch):
    place_clock(monkeypatch, db, 3 * 24 + 4.6)  # Friday 04:36: no sweep closed today
    assert findings(db)["store_not_current"].severity == Severity.WARNING
    place_clock(monkeypatch, db, 3 * 24 + 5.6)  # 05:36: 24 minutes before the target
    assert findings(db)["store_not_current"].severity == Severity.CRITICAL
    place_clock(monkeypatch, db, 2 * 24 + 12)  # Thursday: quiet
    assert "store_not_current" not in findings(db)


def test_preparation_cannot_breach_the_results_reserve(db, monkeypatch):
    place_clock(monkeypatch, db, FRI_0420)
    caps = locking.Caps(100, 450, 300, 150)
    for _ in range(3):
        locking.reserve(db, token="x", tick_id=1, scope="s", per_tick=100, per_day=450,
                        klass="preparation", caps=caps)  # fmt: skip
    found = findings(db)
    assert "results_reserve_breached" not in found and "budget_nonessential_exhausted" not in found


# ------------------------------------------------------------------ security boundary
FORBIDDEN = {"publish_round", "create_round", "create_scheduled_draft", "build_live_snapshot",
             "corrections", "settlement", "championships", "accounts", "auth", "SYSTEM",
             "finalise_round", "settle_round", "lock_round"}  # fmt: skip
ALLOWED_PREFIXES = ("diski9.ingestion", "diski9.odds.collect", "diski9.screener",
                    "diski9.leagues", "diski9.db", "diski9.config", "diski9.api_football",
                    "sqlalchemy", "pathlib", "time", "collections", "dataclasses", "datetime",
                    "typing", "__future__")  # fmt: skip
ALLOWED_RELATIVE = {"db", "db.schema", "repositories", "locking", "config", "prepare",
                    "reconciler"}  # fmt: skip


def test_refresh_code_stays_inside_its_boundary():
    tree = ast.parse(SRC.read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                assert mod in ALLOWED_RELATIVE or mod == "", mod
            else:
                assert mod.startswith(ALLOWED_PREFIXES), mod
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.startswith(ALLOWED_PREFIXES), a.name
    assert not FORBIDDEN & (names | attrs | imported)
    # from prepare and reconciler only the clock seam and step plumbing are used
    text = SRC.read_text()
    assert "from .prepare import _now" in text
    assert "rounds_svc" not in text and "services" not in text


# ------------------------------------------------------------------ results imports
def _results_world(eng):
    from test_backend_scheduler import FakeProvider, after, world

    w = world(eng)
    fake = FakeProvider()
    fake.add(w)
    after(eng, w["deadline"])
    return fake


def test_results_imports_honour_a_provider_cooldown(db):
    from test_backend_scheduler import BASE

    fake = _results_world(db)
    locking.record_cooldown(db, 300, "provider", "provider rate limit")
    r = tick(db, BASE, provider_factory=lambda: fake)
    res = steps(r, "results")
    assert res and res[0].outcome == "deferred" and "cooldown" in res[0].detail
    assert fake.requests_made == 0 and ledger(db) == []


def test_results_keep_their_reserve_when_preparation_used_its_share(db):
    from test_backend_scheduler import BASE

    fake = _results_world(db)
    caps = locking.Caps(400, 450, 300, 150)
    for _ in range(300):  # preparation's whole share of the 24 hours
        locking.reserve(db, token="prep", tick_id=1, scope="s", per_tick=400, per_day=450,
                        klass="preparation", caps=caps)  # fmt: skip
    with pytest.raises(locking.BudgetExhausted):
        locking.reserve(db, token="prep", tick_id=1, scope="s", per_tick=400, per_day=450,
                        klass="preparation", caps=caps)  # fmt: skip
    cfg = replace(BASE, max_requests_per_day=450, max_requests_per_tick=20)
    r = tick(db, cfg, provider_factory=lambda: fake)
    assert [s.outcome for s in steps(r, "results")] == ["succeeded"]
    assert ledger(db)[-1].args["class"] == "results"
