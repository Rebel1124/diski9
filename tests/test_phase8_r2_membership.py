"""Phase 8 R2 (P8-MEMBER): the live snapshot builder keeps fixtures that have no
eligible offer yet only for rolling-entry rounds (freeze fixture membership, not
fixture eligibility); every other round is built exactly as before."""

from __future__ import annotations

from datetime import timedelta

from diski9.challenge.roundsheet import build_live_snapshot

from .factories import T0
from .test_app import EPL_FIX, data, populated  # noqa: F401  (fixtures)


def test_unpriced_fixtures_join_the_universe_only_when_asked(data):  # noqa: F811
    """The recorded store has one fixture with qualifying prices and others without:
    the default build is unchanged; ``include_unpriced`` adds the others with no
    outcomes (never market-filled), identical offers otherwise."""
    window = (T0, T0, T0 + timedelta(days=30), "W", {})
    old = build_live_snapshot(data.engine, *window)
    new = build_live_snapshot(data.engine, *window, include_unpriced=True)
    priced = {o.fixture_id for o in old.outcomes}
    assert {f.fixture_id for f in old.fixtures} == priced and priced
    unpriced = {f.fixture_id for f in new.fixtures} - priced
    assert len(unpriced) == old.diagnostics["fixtures_unpriced"] > 0
    assert [o.key for o in new.outcomes] == [o.key for o in old.outcomes]
    assert [o.market_probability for o in new.outcomes] == [
        o.market_probability for o in old.outcomes
    ]
    assert not {o.fixture_id for o in new.outcomes} & unpriced
    assert old.fingerprint == new.fingerprint  # the offer fingerprint is unchanged
