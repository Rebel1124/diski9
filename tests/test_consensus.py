from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from diski9.api_football.markets import Market, Outcome
from diski9.odds.consensus import (
    BookmakerInfo,
    ConsensusRules,
    MarketConsensus,
    QuoteEpisode,
    exclusion_reason,
    fixture_consensus,
    market_consensus,
)

from .factories import T0

KICK = T0 + timedelta(days=2)
D = Decimal


def ep(
    bid,
    outcome,
    odds,
    *,
    market="BTTS",
    seen=T0 - timedelta(hours=1),
    first=None,
    provider=None,
    ended=None,
):
    provider = provider if provider is not None else seen - timedelta(hours=2)
    return QuoteEpisode(
        bid, market, outcome, D(odds), first or seen, seen, provider, provider, ended
    )


def btts(bid, yes, no, **kw):
    return [ep(bid, "BTTS_YES", yes, **kw), ep(bid, "BTTS_NO", no, **kw)]


def books(*ids, **overrides):
    out = {i: BookmakerInfo(i, f"B{i}") for i in ids}
    out.update(overrides)
    return out


def consensus(episodes, bk, market=Market.BTTS, **kw) -> MarketConsensus:
    return market_consensus(1, market, episodes, bk, KICK, T0, **kw)


def test_median_of_odd_count_matches_spec_example():
    # Screener spec 7.2: 1.75, 1.80, 1.85, 1.90, 2.10 -> 1.85
    prices = ["1.75", "1.80", "1.85", "1.90", "2.10"]
    eps = [e for i, p in enumerate(prices, 1) for e in btts(i, p, "2.00")]
    mc = consensus(eps, books(1, 2, 3, 4, 5))
    yes = mc.outcomes[Outcome.BTTS_YES]
    assert yes.consensus_odds == D("1.85") and yes.sources == 5
    assert (yes.min_odds, yes.max_odds) == (D("1.75"), D("2.10"))
    assert mc.challenge_eligible and mc.displayable


def test_median_of_even_count_and_rounding():
    eps = [*btts(1, "1.85", "2.0"), *btts(2, "1.90", "2.0")]
    yes = consensus(eps, books(1, 2)).outcomes[Outcome.BTTS_YES]
    assert yes.median_odds == D("1.875") and yes.consensus_odds == D("1.88")


def test_min_bookmakers_threshold_and_override():
    eps = [*btts(1, "1.8", "2.0"), *btts(2, "1.9", "2.0")]
    mc = consensus(eps, books(1, 2))
    assert mc.displayable and not mc.challenge_eligible and mc.min_required == 3
    rules = ConsensusRules(min_bookmakers_by_competition={288: 2})
    assert consensus(eps, books(1, 2), rules=rules, competition_id=288).challenge_eligible


def test_no_quotes_not_displayable():
    mc = consensus([], books())
    assert not mc.displayable and mc.outcomes[Outcome.BTTS_YES].consensus_odds is None


def test_stale_observation_excluded():
    old = T0 - timedelta(hours=25)
    eps = [
        *btts(1, "1.8", "2.0"),
        *btts(2, "1.9", "2.0", seen=old, provider=T0 - timedelta(hours=1)),
    ]
    mc = consensus(eps, books(1, 2))
    assert mc.sources == 1 and mc.exclusions == {"stale_observation": 2}


def test_stale_provider_update_excluded():
    eps = btts(1, "1.8", "2.0", provider=T0 - timedelta(hours=30))
    assert consensus(eps, books(1)).exclusions == {"stale_provider_update": 2}


def test_exactly_24h_is_fresh():
    eps = btts(1, "1.8", "2.0", seen=T0 - timedelta(hours=24), provider=T0 - timedelta(hours=24))
    assert consensus(eps, books(1)).sources == 1


def test_missing_provider_timestamp_excluded():
    e = QuoteEpisode(1, "BTTS", "BTTS_YES", D("1.8"), T0, T0, None, None)
    assert (
        exclusion_reason(e, BookmakerInfo(1), T0, KICK, ConsensusRules())
        == "missing_provider_timestamp"
    )


def test_ended_and_future_and_started_excluded():
    rules = ConsensusRules()
    b = BookmakerInfo(1)
    ended = ep(1, "BTTS_YES", "1.8", ended=T0 - timedelta(minutes=1))
    assert exclusion_reason(ended, b, T0, KICK, rules) == "no_longer_offered"
    future = ep(1, "BTTS_YES", "1.8", seen=T0 + timedelta(hours=1))
    assert exclusion_reason(future, b, T0, KICK, rules) == "not_yet_observed"
    ok = ep(1, "BTTS_YES", "1.8")
    assert exclusion_reason(ok, b, KICK, KICK, rules) == "fixture_started"
    assert exclusion_reason(ok, b, T0, KICK, rules) is None


def test_exchange_and_ineligible_bookmakers_excluded():
    eps = [*btts(1, "1.8", "2.0"), *btts(2, "1.9", "2.0"), *btts(3, "1.7", "2.1")]
    bk = books(1, 2, 3, **{})
    bk[2] = BookmakerInfo(2, is_exchange=True)
    bk[3] = BookmakerInfo(3, eligible=False)
    mc = consensus(eps, bk)
    assert mc.sources == 1
    assert mc.exclusions == {"exchange_price": 2, "bookmaker_ineligible": 2}
    assert consensus(btts(9, "1.8", "2.0"), bk).exclusions == {
        "bookmaker_ineligible": 2
    }  # unknown id


def test_incomplete_outcome_set_drops_whole_market_for_bookmaker():
    eps = [
        *btts(1, "1.8", "2.0"),
        ep(2, "BTTS_YES", "1.9"),
        ep(2, "BTTS_NO", "2.0", seen=T0 - timedelta(hours=30)),
    ]
    mc = consensus(eps, books(1, 2))
    assert mc.sources == 1
    assert mc.exclusions == {"stale_observation": 1, "incomplete_market": 1}
    assert mc.outcomes[Outcome.BTTS_YES].bookmaker_ids == (1,)


def test_affiliated_bookmakers_count_once():
    eps = [
        *btts(1, "1.80", "2.0"),
        *btts(2, "1.90", "2.0", seen=T0 - timedelta(minutes=5)),
        *btts(3, "2.00", "2.0"),
    ]
    bk = books(1, 2, 3)
    bk[1] = BookmakerInfo(1, affiliation_group="entain")
    bk[2] = BookmakerInfo(2, affiliation_group="entain")
    mc = consensus(eps, bk)
    assert mc.sources == 2 and not mc.challenge_eligible
    yes = mc.outcomes[Outcome.BTTS_YES]
    assert yes.bookmaker_ids == (2, 3)  # 2 observed more recently than 1
    assert mc.exclusions == {"affiliated_duplicate": 2}


def test_three_way_market_requires_all_three():
    eps = [
        ep(1, o, p, market="1X2") for o, p in (("HOME", "2.0"), ("DRAW", "3.4"), ("AWAY", "3.9"))
    ]
    eps += [ep(2, o, p, market="1X2") for o, p in (("HOME", "2.1"), ("AWAY", "3.7"))]
    mc = consensus(eps, books(1, 2), market=Market.MATCH_RESULT)
    assert mc.sources == 1 and set(mc.outcomes) == {Outcome.HOME, Outcome.DRAW, Outcome.AWAY}


def test_no_probability_or_value_fields():
    mc = consensus(btts(1, "1.8", "2.0"), books(1))
    fields = set(vars(mc)) | set(vars(mc.outcomes[Outcome.BTTS_YES]))
    assert not {f for f in fields if any(w in f for w in ("prob", "ev", "edge", "value"))}


@pytest.mark.parametrize("hours,expected_sources", [(1, 1), (30, 0)])
def test_spanning_episode_uses_fixture_observation_time(hours, expected_sources):
    # Episode first seen 40h ago and still seen now; as_of in between.
    first, last = T0 - timedelta(hours=40), T0
    as_of = T0 - timedelta(hours=2)
    obs = as_of - timedelta(hours=hours)
    e = [
        QuoteEpisode(1, "BTTS", o, D("1.9"), first, last, first, last)
        for o in ("BTTS_YES", "BTTS_NO")
    ]
    # provider timestamp known at as_of is the first one (40h old) -> refresh it
    e = [
        QuoteEpisode(
            1, "BTTS", q.outcome, q.decimal_odds, first, last, as_of - timedelta(hours=1), last
        )
        for q in e
    ]
    mc = market_consensus(1, Market.BTTS, e, books(1), KICK, as_of, fixture_observed_at=obs)
    assert mc.sources == expected_sources


def test_fixture_consensus_from_database_is_point_in_time(conn, make_client, monkeypatch):
    from tests.test_odds_collect import KICK as K2
    from tests.test_odds_collect import run, setup

    from .factories import full_book, odds_item

    setup(conn)
    books_ = {b: full_book(yes=y) for b, y in ((1, "1.70"), (2, "1.80"), (3, "1.90"))}
    run(
        conn,
        make_client,
        [[odds_item(1, books_, update="2026-11-15T11:00:00+00:00")]],
        monkeypatch,
        at=T0,
    )
    books_[3] = full_book(yes="2.50")
    t1 = T0 + timedelta(hours=3)
    run(
        conn,
        make_client,
        [[odds_item(1, books_, update="2026-11-15T14:00:00+00:00")]],
        monkeypatch,
        at=t1,
    )

    now = fixture_consensus(conn, 1, t1)
    assert now[Market.BTTS].outcomes[Outcome.BTTS_YES].consensus_odds == D("1.80")
    assert now[Market.BTTS].outcomes[Outcome.BTTS_YES].max_odds == D("2.50")
    assert all(mc.challenge_eligible for mc in now.values())
    before = fixture_consensus(conn, 1, T0 + timedelta(hours=1))
    assert before[Market.BTTS].outcomes[Outcome.BTTS_YES].max_odds == D("1.90")  # no look-ahead
    stale = fixture_consensus(conn, 1, t1 + timedelta(hours=25))
    assert not stale[Market.BTTS].displayable
    assert fixture_consensus(conn, 1, K2)[Market.BTTS].exclusions.get("fixture_started")
