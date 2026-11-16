from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from diski9.api_football.markets import Market, Outcome
from diski9.ingestion.fixtures import store_fixtures
from diski9.odds.consensus import BookmakerInfo, QuoteEpisode, market_consensus
from diski9.odds.implied import implied
from diski9.screener.engine import MatchStore, ScreenerConfig
from diski9.screener.sanity import check_fixture, run

from .factories import T0, fixture_item, seed_competition

D = Decimal


def _mc(prices: dict[str, str], market=Market.BTTS):
    eps = [
        QuoteEpisode(
            b,
            market.value,
            o,
            D(p),
            T0 - timedelta(hours=1),
            T0 - timedelta(hours=1),
            T0 - timedelta(hours=2),
            T0 - timedelta(hours=2),
        )
        for b in (1, 2, 3)
        for o, p in prices.items()
    ]
    books = {b: BookmakerInfo(b) for b in (1, 2, 3)}
    return market_consensus(1, market, eps, books, T0 + timedelta(days=1), T0)


def test_spec_7_5_raw_implied_example():
    ip = implied(_mc({"BTTS_YES": "1.85", "BTTS_NO": "2.00"}))
    assert f"{ip.raw[Outcome.BTTS_YES] * 100:.1f}" == "54.1"


def test_margin_adjusted_normalises_complete_set():
    ip = implied(_mc({"BTTS_YES": "1.80", "BTTS_NO": "2.00"}))
    total = D(1) / D("1.80") + D(1) / D("2.00")
    assert ip.margin_adjusted[Outcome.BTTS_YES] == (D(1) / D("1.80")) / total
    assert sum(ip.margin_adjusted.values()) == pytest.approx(D(1))
    assert ip.overround == pytest.approx(total - 1)


def test_margin_adjusted_requires_all_outcomes():
    ip = implied(_mc({}))
    assert ip.margin_adjusted is None and ip.reason_unavailable == "no consensus prices"


def test_consensus_reports_observation_and_provider_time_separately():
    mc = _mc({"BTTS_YES": "1.80", "BTTS_NO": "2.00"})
    assert mc.latest_observation == T0 - timedelta(hours=1)
    assert mc.provider_updated_at == T0 - timedelta(hours=2)


@pytest.fixture
def history(conn):
    seed_competition(conn, 39, years=(2025, 2026))
    items, fid, t = [], 1, T0 - 300 * 86400 * timedelta(seconds=1)
    for i in range(30):
        h, a = 1 + i % 4, 1 + (i + 1) % 4
        t += timedelta(days=3)
        items.append(
            fixture_item(
                fid, h, a, kickoff=t, ft=(i % 3, (i + 1) % 2), season=2025 if i < 20 else 2026
            )
        )
        fid += 1
    store_fixtures(conn, items, lambda: T0)
    return conn


def test_sanity_check_passes_on_clean_data(history):
    report = run(history, [39], [2025, 2026])
    assert report["fixtures_checked"] == 30 and report["failures"] == {}


def test_sanity_check_detects_leakage(history, monkeypatch):
    """If the engine ignored the cutoff, the independent reconstruction check must fail."""
    import diski9.screener.engine as eng

    original = eng.MatchStore.team_window

    def leaky(self, team_id, cutoff, venue, n, **kw):
        return original(self, team_id, cutoff + timedelta(days=60), venue, n, **kw)

    monkeypatch.setattr(eng.MatchStore, "team_window", leaky)
    from sqlalchemy import select

    from diski9.db.schema import fixtures

    fx = history.execute(select(fixtures).where(fixtures.c.id == 10)).one()
    res = check_fixture(history, MatchStore(history), fx, ScreenerConfig())
    assert "independent_reconstruction" in res["failures"]
    assert "no_future_matches" in res["failures"]
