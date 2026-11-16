"""Reference-odds display statuses (fresh / stale / unavailable) and strict
Challenge eligibility."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from diski9.api_football.markets import Market, Outcome
from diski9.odds.collect import OddsPage, reconcile_pages
from diski9.odds.display import challenge_consensus, display_consensus

from .factories import T0, full_book, odds_item
from .test_odds_collect import KICK, setup

H = timedelta(hours=1)


def collect(conn, at, books, update):
    item = odds_item(1, books, kickoff=KICK, update=update.isoformat())
    reconcile_pages(conn, 39, 2026, [OddsPage(at, [item])], clock=lambda: at)


def three_books(home=("1.40", "1.45", "1.50")):
    return {b: full_book(home=h) for b, h in zip((8, 11, 4), home, strict=True)}


def test_fresh_consensus(conn):
    setup(conn)
    collect(conn, T0, three_books(), T0 - H)
    d = display_consensus(conn, 1, T0 + 2 * H)
    m = d[Market.MATCH_RESULT]
    assert m.status == "fresh" and m.challenge_eligible
    assert m.consensus.outcomes[Outcome.HOME].consensus_odds == Decimal("1.45")
    assert m.consensus.latest_observation == T0 and m.consensus.provider_updated_at == T0 - H
    assert m.age_hours == 2.0
    assert m.implied.margin_adjusted is not None


def test_stale_consensus_shown_but_never_challenge_eligible(conn):
    setup(conn)
    collect(conn, T0, three_books(), T0 - H)
    later = T0 + 30 * H
    d = display_consensus(conn, 1, later)
    m = d[Market.MATCH_RESULT]
    assert m.status == "stale"
    assert m.consensus.sources == 3 and m.consensus.challenge_eligible  # was valid at its own time
    assert m.challenge_eligible is False  # but stale display can never be eligible
    assert m.snapshot_at == T0 and m.age_hours == 30.0
    assert m.consensus.outcomes[Outcome.HOME].consensus_odds == Decimal("1.45")
    assert m.consensus.outcomes[Outcome.HOME].median_odds == Decimal("1.45")
    assert "may have changed" in m.reason or "24 hours" in m.reason
    # the Challenge path has no stale fallback
    assert challenge_consensus(conn, 1, later)[Market.MATCH_RESULT] is None
    assert challenge_consensus(conn, 1, T0 + H)[Market.MATCH_RESULT] is not None


def test_stale_when_provider_timestamp_old_even_if_recently_checked(conn):
    setup(conn)
    collect(conn, T0, three_books(), T0 - H)  # valid at T0
    collect(conn, T0 + 20 * H, three_books(), T0 - H)  # re-checked, provider still at T0-1h
    d = display_consensus(conn, 1, T0 + 26 * H)  # provider 27 h old, our check 6 h old
    m = d[Market.MATCH_RESULT]
    assert m.status == "stale" and not m.challenge_eligible
    assert "provider" in m.reason.lower()


def test_unavailable_when_no_valid_consensus(conn):
    setup(conn)
    d = display_consensus(conn, 1, T0)
    assert all(m.status == "unavailable" and m.consensus is None for m in d.values())
    assert all(not m.challenge_eligible for m in d.values())


def test_stale_snapshot_is_coherent_never_mixed(conn):
    setup(conn)
    collect(conn, T0, three_books(), T0 - H)
    # 10 h later only bookmaker 8 quotes, at a new price; 11 and 4 disappear
    collect(conn, T0 + 10 * H, {8: full_book(home="2.00")}, T0 + 9 * H)
    d = display_consensus(conn, 1, T0 + 40 * H)
    m = d[Market.MATCH_RESULT]
    assert m.status == "stale" and m.snapshot_at == T0 + 10 * H
    # exactly the snapshot at T0+10h: one source at 2.00 - not 2.00 mixed with 1.45/1.50 from T0
    assert m.consensus.sources == 1
    assert m.consensus.outcomes[Outcome.HOME].consensus_odds == Decimal("2.00")
    assert m.consensus.outcomes[Outcome.HOME].bookmaker_ids == (8,)


def test_independent_groups_still_count_once_in_display(conn):
    from diski9.db.schema import bookmakers

    setup(conn)
    collect(conn, T0, three_books(), T0 - H)
    conn.execute(
        bookmakers.update().where(bookmakers.c.id.in_([8, 11])).values(affiliation_group="g")
    )
    m = display_consensus(conn, 1, T0 + H)[Market.MATCH_RESULT]
    assert m.status == "fresh" and m.consensus.sources == 2 and not m.challenge_eligible


def test_implied_probabilities_from_displayed_prices(conn):
    setup(conn)
    collect(conn, T0, three_books(), T0 - H)
    m = display_consensus(conn, 1, T0 + 30 * H)[Market.BTTS]
    ip = m.implied
    yes, no = (
        m.consensus.outcomes[Outcome.BTTS_YES].consensus_odds,
        m.consensus.outcomes[Outcome.BTTS_NO].consensus_odds,
    )
    assert ip.raw[Outcome.BTTS_YES] == Decimal(1) / yes
    total = Decimal(1) / yes + Decimal(1) / no
    assert ip.margin_adjusted[Outcome.BTTS_YES] == (Decimal(1) / yes) / total
    assert sum(ip.margin_adjusted.values()) == pytest.approx(Decimal(1))
