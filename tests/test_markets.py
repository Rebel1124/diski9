from __future__ import annotations

import copy
from decimal import Decimal

from diski9.api_football.markets import (
    ALL_OUTCOMES,
    MARKET_OUTCOMES,
    Market,
    Outcome,
    check_bet_catalogue,
    extract_quotes,
    parse_odds,
)

from .conftest import load_fixture


def odds_item():
    return copy.deepcopy(load_fixture("odds_fixture_sample.json")["response"][0])


def test_seven_outcomes_across_three_markets():
    assert len(ALL_OUTCOMES) == 7
    assert sum(len(v) for v in MARKET_OUTCOMES.values()) == 7
    assert set().union(*MARKET_OUTCOMES.values()) == ALL_OUTCOMES


def test_bet_catalogue_matches_verified_ids():
    bets = load_fixture("odds_bets_sample.json")["response"]
    assert check_bet_catalogue(bets) == []
    broken = [b if b["id"] != 8 else {"id": 8, "name": "Something Else"} for b in bets]
    assert check_bet_catalogue(broken)


def test_extract_quotes_from_real_sample():
    quotes, warnings = extract_quotes(odds_item())
    assert warnings == []
    by_book: dict[int, set[Market]] = {}
    for q in quotes:
        by_book.setdefault(q.bookmaker_id, set()).add(q.market)
        assert q.fixture_id == 1557474 and q.league_id == 39 and q.season == 2026
        assert q.provider_updated_at is not None and q.provider_updated_at.tzinfo is not None
        assert isinstance(q.decimal_odds, Decimal)
    assert by_book[8] == set(Market)  # Bet365: all three markets
    assert Market.BTTS not in by_book[4]  # Pinnacle: no BTTS in sample
    assert Market.OVER_UNDER_25 not in by_book[7]  # William Hill: no O/U in sample
    # each complete market yields exactly its outcomes
    bet365 = {q.outcome for q in quotes if q.bookmaker_id == 8}
    assert bet365 == ALL_OUTCOMES


def test_only_25_line_used():
    quotes, _ = extract_quotes(odds_item())
    ou = [q for q in quotes if q.market is Market.OVER_UNDER_25]
    assert {q.outcome for q in ou} == {Outcome.OVER_25, Outcome.UNDER_25}
    assert len(ou) == 2 * len({q.bookmaker_id for q in ou})


def test_incomplete_market_skipped_with_warning():
    item = odds_item()
    bk = next(b for b in item["bookmakers"] if b["id"] == 8)
    bet = next(b for b in bk["bets"] if b["id"] == 1)
    bet["values"] = [v for v in bet["values"] if v["value"] != "Draw"]
    quotes, warnings = extract_quotes(item)
    assert not any(q.bookmaker_id == 8 and q.market is Market.MATCH_RESULT for q in quotes)
    assert any("incomplete 1X2" in w for w in warnings)


def test_invalid_odds_rejected():
    assert parse_odds("1.85") == Decimal("1.85")
    for bad in ("", "abc", "1.00", "0", "-2", "NaN", None, "inf"):
        assert parse_odds(bad) is None
    item = odds_item()
    bk = next(b for b in item["bookmakers"] if b["id"] == 8)
    next(b for b in bk["bets"] if b["id"] == 8)["values"][0]["odd"] = "n/a"
    quotes, warnings = extract_quotes(item)
    assert not any(q.bookmaker_id == 8 and q.market is Market.BTTS for q in quotes)
    assert any("invalid odds" in w for w in warnings)


def test_duplicate_market_block_ignored():
    item = odds_item()
    bk = next(b for b in item["bookmakers"] if b["id"] == 8)
    bk["bets"].append(copy.deepcopy(next(b for b in bk["bets"] if b["id"] == 1)))
    quotes, warnings = extract_quotes(item)
    assert len([q for q in quotes if q.bookmaker_id == 8 and q.market is Market.MATCH_RESULT]) == 3
    assert any("duplicate" in w for w in warnings)


def test_empty_bookmakers():
    item = odds_item()
    item["bookmakers"] = []
    assert extract_quotes(item) == ([], [])
