"""Phase 5A: bookmaker odds for all eight Goal Model 1.0 leagues - configuration,
collection, market-by-market quality rules, coverage diagnostics and the flow into
the Screener / Match Lab (edge and EV). The odds trial keeps its original scope."""

from __future__ import annotations

import argparse
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from diski9 import cli, workflow
from diski9.api_football.errors import (
    ApiFootballHTTPError,
    ApiFootballQuotaExceededError,
    QuotaGuardError,
)
from diski9.api_football.markets import Market
from diski9.app import ScreenerData
from diski9.app.app import results_payload
from diski9.app.lab import model_comparison
from diski9.db.schema import seasons
from diski9.ingestion.fixtures import store_fixtures
from diski9.leagues import (
    COMPETITIONS,
    ODDS_TRIAL_COMPETITIONS,
    CompetitionConfig,
    odds_competitions,
    screener_competitions,
)
from diski9.odds.collect import FATAL_ERRORS, OddsPage, reconcile_pages
from diski9.odds.consensus import fixture_consensus
from diski9.odds.coverage import coverage_report, format_table
from diski9.odds.value import compare
from diski9.screener import cache
from diski9.screener import goal_model as gm

from .factories import T0, fixture_item, full_book, odds_item, seed_competition

DAY = timedelta(days=1)
EIGHT = {39: "EPL", 40: "Championship", 288: "PSL", 289: "PSL 1st Div", 140: "La Liga",
         61: "Ligue 1", 78: "Bundesliga", 135: "Serie A"}  # fmt: skip
LIGA = 140
FX_FRESH, FX_THIN, FX_STALE, FX_PARTIAL, FX_NONE = 7001, 7002, 7003, 7004, 7005


# ------------------------------------------------------------ configuration
def test_eight_leagues_collect_odds_and_trial_scope_is_unchanged():
    assert set(odds_competitions()) == set(EIGHT) == set(screener_competitions())
    assert {c.id for c in COMPETITIONS.values()} == set(EIGHT)  # no new competitions
    assert ODDS_TRIAL_COMPETITIONS == (39, 288)
    # a league added later does not collect odds unless it says so
    assert CompetitionConfig(999, "x", tier=1).odds_enabled is False


class FakeClient:
    quota_requests_made = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run_collect(monkeypatch, engine, fail: dict[int, Exception] | None = None, comps=None):
    calls: list[int] = []

    def fake_collect(conn, client, cid, season, *a, **k):
        calls.append(cid)
        if fail and cid in fail:
            raise fail[cid]
        return SimpleNamespace()

    monkeypatch.setattr(cli.ApiFootballClient, "from_settings", classmethod(lambda c: FakeClient()))
    monkeypatch.setattr(cli, "collect_odds", fake_collect)
    monkeypatch.setattr(cli, "summarise_fetch", lambda s: {})
    cli.cmd_collect_odds(argparse.Namespace(competitions=comps, season=2026), engine)
    return calls


def test_collect_odds_cli_covers_all_eight(monkeypatch, engine, capsys):
    assert _run_collect(monkeypatch, engine) == odds_competitions()
    assert _run_collect(monkeypatch, engine, comps=[140]) == [140]


def test_one_league_failure_does_not_stop_the_others(monkeypatch, engine, capsys):
    err = ApiFootballHTTPError(500, "server error")
    with pytest.raises(SystemExit, match=r"\[61\]"):
        _run_collect(monkeypatch, engine, fail={61: err})
    out = capsys.readouterr().out
    assert "61/2026: FAILED and rolled back" in out
    assert "135/2026" in out  # later leagues still collected


@pytest.mark.parametrize(
    "fatal",
    [QuotaGuardError("daily remaining at reserve"), ApiFootballQuotaExceededError("odds", {})],
)
def test_quota_errors_stop_the_run(monkeypatch, engine, capsys, fatal):
    assert isinstance(fatal, FATAL_ERRORS)
    with pytest.raises(SystemExit):
        _run_collect(monkeypatch, engine, fail={288: fatal})
    out = capsys.readouterr().out
    assert "288/2026: STOPPED" in out and "140/2026" not in out


def test_monitor_odds_defaults_to_the_trial_leagues(monkeypatch, engine):
    import diski9.odds.monitor as monitor

    seen = {}
    monkeypatch.setattr(cli.ApiFootballClient, "from_settings", classmethod(lambda c: FakeClient()))
    monkeypatch.setattr(
        monitor, "run_monitor", lambda client, targets, *a: seen.setdefault("t", targets) and {}
    )
    cli.cmd_monitor_odds(
        argparse.Namespace(competitions=None, season=2026, out_dir=None, until=None), engine
    )
    assert seen["t"] == [39, 288]


def test_refresh_collects_all_eight_and_isolates_failures(monkeypatch, engine):
    calls, logs = [], []

    def fake_collect(conn, client, cid, season, clock):
        calls.append(cid)
        if cid == 40:
            raise ApiFootballHTTPError(502, "bad gateway")
        if cid == 78:
            raise QuotaGuardError("reserve reached")
        return SimpleNamespace(fixtures_collected=1, quotes_seen=3, inconsistent_pagination=False)

    monkeypatch.setattr(workflow, "collect_odds", fake_collect)
    workflow._standings_and_odds(engine, None, True, lambda: T0, logs.append, standings=False)
    assert calls == odds_competitions()[: odds_competitions().index(78) + 1]
    text = "\n".join(logs)
    assert "WARNING odds 40: collection failed" in text and "odds 288:" in text
    assert "WARNING odds 78: stopped" in text and "odds 135" not in text


# ----------------------------------------------------- collection + quality
@pytest.fixture
def liga(engine):
    """La Liga (one of the newly enabled leagues) with history for Goal Model 1.0
    and five upcoming fixtures covering every odds state."""
    with engine.begin() as conn:
        seed_competition(conn, LIGA, years=(2025, 2026), name="La Liga")
        seed_competition(conn, 288, years=(2025, 2026), name="Premier Soccer League")
        conn.execute(
            update(seasons)
            .where(seasons.c.competition_id == 288, seasons.c.year == 2026)
            .values(coverage_odds=False)
        )
        items, fid, t = [], 1, T0 - 200 * DAY

        def add(h, a, hg, ag, season=2026):
            nonlocal fid, t
            t += DAY
            items.append(
                fixture_item(fid, h, a, league=LIGA, season=season, kickoff=t, ft=(hg, ag))
            )
            fid += 1

        for i in range(10):
            add(1, 100 + i, 3, 0)
            add(110 + i, 2, 1, 1)
            add(3, 120 + i, 2, 1)
            add(130 + i, 4, 1, 0)
        for i in range(20):
            add(600 + i % 10, 650 + i % 10, (2, 1, 0, 3)[i % 4], (1, 1, 2, 0)[i % 4], season=2025)
        upcoming = [(FX_FRESH, 1, 2), (FX_THIN, 3, 4), (FX_STALE, 1, 4), (FX_PARTIAL, 3, 2),
                    (FX_NONE, 2, 1)]  # fmt: skip
        for i, (f, h, a) in enumerate(upcoming):
            items.append(
                fixture_item(
                    f, h, a, league=LIGA, season=2026, kickoff=T0 + (2 + i) * DAY, status="NS"
                )  # fmt: skip
            )
        items.append(
            fixture_item(8001, 10, 11, league=288, season=2026, kickoff=T0 + 3 * DAY, status="NS")
        )
        store_fixtures(conn, items, lambda: T0)
        three = {b: full_book(home=h) for b, h in ((8, "1.80"), (11, "1.85"), (4, "1.90"))}
        partial = {b: full_book() for b in (8, 11, 4)}
        for b in partial.values():
            b["8"] = [("Yes", "1.80")]  # BTTS incomplete (no "No" price)
        fresh_upd = "2026-11-15T10:00:00+00:00"
        page = OddsPage(
            T0 - timedelta(hours=1),
            [
                odds_item(FX_FRESH, three, league=LIGA, kickoff=T0 + 2 * DAY, update=fresh_upd),
                odds_item(
                    FX_THIN,
                    {8: full_book(), 11: full_book()},
                    league=LIGA,
                    kickoff=T0 + 3 * DAY,
                    update=fresh_upd,
                ),  # fmt: skip
                odds_item(
                    FX_STALE,
                    three,
                    league=LIGA,
                    kickoff=T0 + 4 * DAY,
                    update="2026-11-10T10:00:00+00:00",
                ),  # fmt: skip
                odds_item(FX_PARTIAL, partial, league=LIGA, kickoff=T0 + 5 * DAY, update=fresh_upd),
            ],
        )
        stats = reconcile_pages(conn, LIGA, 2026, [page], clock=lambda: T0 - timedelta(hours=1))
        assert stats.fixtures_collected == 4 and not stats.skipped
        cache.refresh(conn, [FX_FRESH, FX_THIN, FX_STALE, FX_PARTIAL, FX_NONE, 8001], T0, T0)
    return engine


def test_new_league_quality_rules_market_by_market(liga):
    with liga.connect() as conn:
        fresh = fixture_consensus(conn, FX_FRESH, T0)
        thin = fixture_consensus(conn, FX_THIN, T0)
        stale = fixture_consensus(conn, FX_STALE, T0)
        partial = fixture_consensus(conn, FX_PARTIAL, T0)
    for m in Market:
        assert fresh[m].displayable and fresh[m].challenge_eligible  # 3 independent books
        assert thin[m].displayable and not thin[m].challenge_eligible  # only 2
        assert not stale[m].displayable  # provider update older than 24 h
        assert stale[m].exclusions.get("stale_provider_update")
    # median of distinct bookmakers' prices
    assert str(fresh[Market.MATCH_RESULT].outcomes[next(iter(
        fresh[Market.MATCH_RESULT].outcomes))].consensus_odds) in {"1.85", "3.40", "3.80"}  # fmt: skip
    # each market judged on its own: BTTS incomplete, 1X2 and OU 2.5 still valid
    assert partial[Market.MATCH_RESULT].displayable and partial[Market.OVER_UNDER_25].displayable
    # incomplete bookmaker markets are dropped when parsing, so BTTS has no source
    assert not partial[Market.BTTS].displayable and partial[Market.BTTS].sources == 0


def test_coverage_report_counts_real_states_without_api(liga):
    with liga.connect() as conn:
        rep = coverage_report(conn, T0, [LIGA, 288], horizon_days=14)
    liga_row, psl = rep["leagues"]
    assert liga_row["league_id"] == LIGA and liga_row["upcoming_fixtures"] == 5
    assert liga_row["fixtures_with_any_quotes"] == 4
    assert liga_row["fresh"]["1X2"] == {"fixtures": 3, "pct": 60.0}  # fresh, thin, partial
    assert liga_row["fresh"]["BTTS"] == {"fixtures": 2, "pct": 40.0}  # partial excluded
    assert liga_row["fresh_any_market"]["fixtures"] == 3
    assert liga_row["challenge_eligible"]["1X2"]["fixtures"] == 2  # fresh + partial (3 books)
    assert liga_row["challenge_eligible"]["BTTS"]["fixtures"] == 1
    assert liga_row["bookmaker_groups"] == {"min": 2, "median": 3, "max": 3}
    assert liga_row["quote_age_hours"]["median"] == 1.0
    assert liga_row["exclusions"]["stale_provider_update"] > 0
    lead = liga_row["by_time_to_kickoff"]
    assert lead["1-3d"]["fixtures"] == 1 and lead["3-7d"]["fixtures"] == 4
    assert sum(b["fixtures"] for b in lead.values()) == 5
    assert psl["upcoming_fixtures"] == 1 and psl["fresh_any_market"]["fixtures"] == 0
    assert psl["provider_odds_coverage"] is False and psl["bookmaker_groups"]["median"] is None
    assert rep["totals"]["upcoming_fixtures"] == 6
    assert rep["rules"] == {"max_quote_age_hours": 24.0, "challenge_min_bookmakers": 3}
    table = format_table(rep)
    assert "La Liga" in table and "3 (60%)" in table and "No API requests were made" in table
    assert "* API-Football reports no odds coverage" in table


def test_screener_and_match_lab_use_new_league_odds(liga):
    d = ScreenerData(liga, ttl_seconds=0, clock=lambda: T0)
    snap = d.snapshot()
    assert set(snap.results["overall"]) >= {FX_FRESH, FX_NONE}  # no-odds fixture kept
    r = snap.results["overall"][FX_FRESH]
    assert d.odds_summary(snap.odds[FX_FRESH], Market.MATCH_RESULT)[0] == "fresh"
    st, text = d.odds_summary(snap.odds[FX_STALE], Market.MATCH_RESULT)
    assert st in ("stale", "unavailable")  # never shown as valid
    assert d.value_cell("1X2", snap.results["overall"][FX_STALE], "ev")["cls"] == "na"
    # edge / EV use the same shared layer as for EPL
    mv = compare(Market.MATCH_RESULT, r["goal_model"]["probabilities"],
                 snap.odds[FX_FRESH].markets[Market.MATCH_RESULT].consensus)  # fmt: skip
    for o in mv.outcomes:
        assert o.ev == pytest.approx(o.probability * float(o.odds) - 1)
    cell = d.value_cell("1X2", r, "edge")
    assert cell["status"] == "fresh" and cell["main"] is not None
    # rankings include the new league; unpriced fixtures stay listed, ranked last
    for direction in ("edge", "ev"):
        p = results_payload(d, "1X2", [LIGA], None, "2026-12-31", "overall", direction, 0, 1)
        ids = [row.id["index"] for row in p[0].children[1].children]
        assert set(ids) == {FX_FRESH, FX_THIN, FX_STALE, FX_PARTIAL, FX_NONE}
        p = results_payload(d, "BTTS", [LIGA], None, "2026-12-31", "overall", direction, 0, 1)
        ids = [row.id["index"] for row in p[0].children[1].children]
        assert ids.index(FX_FRESH) < ids.index(FX_NONE) and FX_PARTIAL in ids
    text = str(model_comparison("1X2", snap.odds[FX_FRESH], r["goal_model"]["probabilities"]))
    assert "independent bookmaker group" in text
    # PSL: provider has no odds - the fixture stays visible with the existing state
    psl = snap.results["overall"][8001]
    assert d.row("1X2", psl)["odds"] == "No odds"
    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.competition_min, gm.GOAL_MODEL_VERSION) == (
        12,
        96,
        20,
        "1.1",
    )  # Goal Model 1.1 (Phase 8 CP2A)
