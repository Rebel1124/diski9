from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from diski9.db.schema import fixtures, screener_results
from diski9.ingestion.fixtures import store_fixtures
from diski9.screener import cache
from diski9.screener.engine import MatchStore, ScreenerConfig, compute_fixture, select_benchmark
from diski9.screener.rank import rank

from .factories import T0, fixture_item, seed_competition

DAY = timedelta(days=1)
UPCOMING_ID = 9999


class Builder:
    """Small helper to add completed matches one by one, newest last."""

    def __init__(self, conn, start=T0 - 400 * DAY):
        self.conn = conn
        self.t = start
        self.fid = 1
        self.items = []

    def add(
        self,
        home,
        away,
        hg,
        ag,
        *,
        league=39,
        season=2025,
        status="FT",
        round_name="Regular Season - 1",
        venue_id=None,
        gap=DAY,
    ):
        self.t += gap
        self.items.append(
            fixture_item(
                self.fid,
                home,
                away,
                league=league,
                season=season,
                kickoff=self.t,
                status=status,
                ft=(hg, ag),
                round_name=round_name,
                venue_id=venue_id,
            )
        )
        self.fid += 1
        return self.fid - 1

    def upcoming(self, home, away, *, league=39, season=2026, kickoff=T0 + 3 * DAY):
        self.items.append(
            fixture_item(
                UPCOMING_ID, home, away, league=league, season=season, kickoff=kickoff, status="NS"
            )
        )

    def save(self):
        store_fixtures(self.conn, self.items, lambda: T0)
        self.items = []


@pytest.fixture
def db(conn):
    seed_competition(conn, 39, years=(2023, 2024, 2025, 2026))
    seed_competition(conn, 40, years=(2024, 2025, 2026), name="Championship")
    return conn


def fx(conn, fid=UPCOMING_ID):
    return conn.execute(select(fixtures).where(fixtures.c.id == fid)).one()


def compute(conn, fid=UPCOMING_ID, as_of=T0, basis="venue", config=None):
    return compute_fixture(MatchStore(conn), fx(conn, fid), as_of, basis, config)


def set_venue(conn, fid, cls):
    conn.execute(update(fixtures).where(fixtures.c.id == fid).values(venue_classification=cls))


def test_form_uses_last_eight_current_season_matches_home_or_away(db):
    b = Builder(db)
    for i in range(8):  # last season: never used by the Form Score any more
        b.add(1, 150 + i, 0, 5, season=2025)
    # team 1 this season: 6 home wins 3-0 interleaved with 6 away losses 0-1 (oldest first)
    for i in range(6):
        b.add(1, 50 + i, 3, 0, season=2026)
        b.add(60 + i, 1, 1, 0, season=2026)
    for i in range(6):  # team 2: six away draws 1-1 this season
        b.add(70 + i, 2, 1, 1, season=2026)
    b.upcoming(1, 2)
    b.save()
    for basis in ("venue", "overall"):  # the basis no longer affects Match Result
        r = compute(db, basis=basis)
        home = r["teams"]["home"]["form"]
        # last eight, newest first: L-W-L-W-L-W-L-W -> 12 of 24 pts -> 1.25;
        # GD 4x3 - 4 = +8, cap 14.4 -> 2.5 x 22.4/28.8 = 1.94; total 3.19
        assert home["sequence"] == "L-W-L-W-L-W-L-W" and home["display"] == "3.19"
        assert {m["season"] for m in home["matches"]} == {2026}
        assert home["sample"]["limited_data"] is False  # full eight-match window
        away = r["teams"]["away"]["form"]
        # six draws: 6 of 18 pts -> 0.83; GD 0 -> 1.25; total 2.08 (early season: 6 of 8)
        assert away["display"] == "2.08" and away["sample"]["matches"] == 6
        assert away["sample"]["limited_data_reasons"] == ["fewer_than_8_matches"]
        mr = r["match_result"]
        assert mr["form_difference"] == pytest.approx(mr["home_form"] - mr["away_form"])
        assert "venue_adjusted_difference" not in mr and "benchmark" not in mr
        # venue context: home team's last five home matches (5.00) vs overall (3.19)
        vc = home["venue_context"]
        assert vc["matches"] == 5 and vc["display"] == "5.00" and vc["available"]
        assert vc["difference"] == pytest.approx(5.0 - home["score"])
        assert away["venue_context"]["difference"] == pytest.approx(0.0)


def test_goals_markets_last_ten_and_complements(db):
    b = Builder(db, start=T0 - 300 * DAY)
    for i in range(
        12
    ):  # 12 current-season home matches: newest 10 -> 8 BTTS & over (2-1), 2 not (1-0)
        b.add(1, 50 + i, 1, 0, season=2026) if i < 4 else b.add(1, 50 + i, 2, 1, season=2026)
    for i in range(10):  # away team: 6 of 10 BTTS (1-1), 4 not (0-1)
        b.add(70 + i, 2, 1, 1, season=2026) if i < 6 else b.add(70 + i, 2, 1, 0, season=2026)
    b.upcoming(1, 2)
    b.save()
    r = compute(db)
    assert r["teams"]["home"]["goals"]["btts"]["display"] == "8/10 (80%)"
    assert r["teams"]["away"]["goals"]["btts"]["display"] == "6/10 (60%)"
    assert r["btts"]["yes_display"] == "70%" and r["btts"]["no_display"] == "30%"
    assert r["teams"]["home"]["goals"]["over_2_5"]["hits"] == 8
    assert r["teams"]["away"]["goals"]["over_2_5"]["hits"] == 0
    assert (
        r["over_under_2_5"]["over_display"] == "40%"
        and r["over_under_2_5"]["under_display"] == "60%"
    )
    assert not r["limited_data"]["goals"]  # full ten-match windows


def test_excluded_fixtures_never_used(db):
    b = Builder(db)
    b.add(1, 50, 5, 0, season=2026)
    b.add(1, 51, 3, 0, status="AWD", season=2026)
    b.add(1, 52, 0, 0, status="CANC", season=2026)
    b.add(1, 53, 4, 0, round_name="Relegation Round - 1", season=2026)
    b.add(1, 54, 4, 4, status="PST", season=2026)
    b.add(70, 2, 0, 0, season=2026)
    b.upcoming(1, 2)
    b.save()
    r = compute(db)
    assert r["teams"]["home"]["form"]["breakdown"]["matches"] == 1
    assert r["teams"]["home"]["form"]["matches"][0]["opponent"] == "Team 50"


def test_neutral_kept_in_form_excluded_from_venue_context_unverified_flagged(db):
    b = Builder(db)
    neutral = b.add(1, 50, 3, 0, season=2026)
    unverified = b.add(1, 51, 1, 0, season=2026)
    b.add(70, 2, 0, 0, season=2026)
    b.upcoming(1, 2)
    b.save()
    set_venue(db, neutral, "neutral")
    set_venue(db, unverified, "unverified_venue")
    r = compute(db)
    home = r["teams"]["home"]["form"]
    assert [m["fixture_id"] for m in home["matches"]] == [unverified, neutral]  # overall
    assert (
        home["matches"][0]["unverified_venue"] and home["sample"]["unverified_venue_matches"] == 1
    )
    assert home["venue_context"]["matches"] == 1  # the neutral-venue match is not a home match
    store = MatchStore(db)
    assert neutral not in {m.fixture_id for m in store.league_matches(39, 2026, T0)}


def test_promoted_team_uses_current_season_only(db):
    b = Builder(db)
    for i in range(8):  # team 3 played last season in the Championship
        b.add(3, 80 + i, 2, 0, league=40)
    b.add(3, 90, 1, 1, season=2026, gap=DAY * 100)  # one top-flight home match this season
    for i in range(6):
        b.add(70 + i, 2, 0, 1, season=2026)
    b.upcoming(3, 2)
    b.save()
    r = compute(db)
    form = r["teams"]["home"]["form"]
    assert form["sample"]["matches"] == 1  # the Championship matches never count
    assert form["sample"]["provenance"] == {"current_season_same_division": 1}
    assert form["sample"]["limited_data_reasons"] == [
        "fewer_than_8_matches",
        "fewer_than_3_current_division_matches",
    ]
    assert form["sample"]["note"] is None
    assert form["matches"][0]["competition"] == "Premier League"
    # one 1-1 draw, normalised by one match: 2.5 x 1/3 + 1.25 = 2.08
    assert form["display"] == "2.08"
    assert r["limited_data"]["form"]


def test_new_club_without_history(db):
    b = Builder(db)
    for i in range(6):
        b.add(70 + i, 2, 0, 1, season=2026)
    b.upcoming(777, 2)  # e.g. a club that acquired a league status: no inherited history
    b.save()
    r = compute(db)
    home = r["teams"]["home"]
    assert home["form"]["score"] is None and home["goals"]["btts"] is None  # unavailable, never 0
    assert home["form"]["display"] is None and home["form"]["breakdown"] is None
    assert home["form"]["sample"]["limited_data_reasons"] == [
        "fewer_than_8_matches",
        "fewer_than_3_current_division_matches",
    ]
    assert r["match_result"]["form_difference"] is None and r["btts"]["yes_indicator"] is None


def test_small_samples_still_calculated_and_flagged(db):
    b = Builder(db)
    for hg, ag in ((2, 0), (1, 1), (1, 0), (0, 1)):  # 4 home matches, newest last
        b.add(1, 50 + hg * 10 + ag, hg, ag, season=2026)
    for i in range(4):
        b.add(70 + i, 2, 1, 1, season=2026)
    b.upcoming(1, 2)
    b.save()
    r = compute(db)
    form = r["teams"]["home"]["form"]
    # normalised by the 4 matches played: 7 of 12 pts -> 2.5 x 7/12 = 1.46;
    # GD +2, cap 7.2 -> 2.5 x 9.2/14.4 = 1.60; total 3.06 (no bonuses)
    bd = form["breakdown"]
    assert bd["points"] == 7 and bd["goal_difference"] == 2 and bd["matches"] == 4
    assert bd["max_points"] == 12 and bd["gd_cap"] == pytest.approx(7.2)
    assert bd["points_component_display"] == "1.46"
    assert bd["goal_difference_component_display"] == "1.60"
    assert form["display"] == "3.06"
    assert not any(k.startswith("bonus") for k in bd)
    assert form["sample"]["limited_data_reasons"] == ["fewer_than_8_matches"]  # early season
    assert r["teams"]["home"]["goals"]["btts"]["display"] == "1/4 (25%)"
    assert r["teams"]["home"]["goals"]["sample"]["limited_data_reasons"] == ["fewer_than_6_matches"]


def test_benchmark_current_previous_and_partial(db):
    b = Builder(db)
    for i in range(10):
        b.add(100 + i, 200 + i, 2, 1, season=2025)  # previous season: all home wins
    for i in range(4):
        b.add(
            300 + i, 400 + i, 0, 0, season=2026, gap=DAY * (20 if i == 0 else 1)
        )  # current: draws
    b.upcoming(100, 200)
    b.save()
    store = MatchStore(db)
    prev = select_benchmark(store, 39, 2026, T0, ScreenerConfig(benchmark_min_matches=5))
    assert prev["source"] == "previous_season" and prev["season"] == 2025 and prev["matches"] == 10
    assert prev["home"]["form_score"] == 4.5 and prev["current_season_matches"] == 4
    cur = select_benchmark(store, 39, 2026, T0, ScreenerConfig(benchmark_min_matches=4))
    assert cur["source"] == "current_season" and cur["home"]["form_score"] == 2.0
    assert cur["draw_rate"] == 1.0
    assert "2026/27 averages (4 matches)" in cur["label"]
    # no previous season stored for the Championship -> partial current season, flagged by source
    b.add(500, 501, 1, 0, league=40, season=2026)
    b.save()
    part = select_benchmark(MatchStore(db), 40, 2026, T0, ScreenerConfig(benchmark_min_matches=5))
    assert part["source"] == "current_season_partial"
    assert select_benchmark(MatchStore(db), 40, 2024, T0, ScreenerConfig()) is None


def test_form_difference_is_plain_home_minus_away(db):
    b = Builder(db)
    for i in range(5):
        b.add(1, 50 + i, 2, 0, season=2026)  # 15 of 15 pts -> 2.5, GD +10 capped at +9 -> 2.5
        b.add(60 + i, 2, 1, 0, season=2026)  # away team: 0 pts, GD -5 -> 2.5 x 4/18
    b.upcoming(1, 2)
    b.save()
    r = compute(db)
    mr = r["match_result"]
    assert mr["home_form"] == 5.0 and mr["away_form"] == pytest.approx(2.5 * 4 / 18)
    assert mr["form_difference"] == pytest.approx(mr["home_form"] - mr["away_form"])
    assert mr["form_difference_display"] == "+4.44"
    # benchmarks no longer influence anything: a league full of home wins changes nothing
    for i in range(20):
        b.add(300 + i, 400 + i, 5, 0)
    b.save()
    assert compute(db)["match_result"]["form_difference"] == mr["form_difference"]


def test_point_in_time_later_results_do_not_leak(db):
    b = Builder(db, start=T0 - 30 * DAY)
    for i in range(5):
        b.add(1, 50 + i, 1, 1, season=2026)
        b.add(60 + i, 2, 1, 1, season=2026)
    b.upcoming(1, 2, kickoff=T0)
    b.save()
    before = compute(db, as_of=T0 + 10 * DAY)  # cutoff = kickoff
    late = [
        fixture_item(5000 + i, 1, 50 + i, kickoff=T0 + (i + 1) * DAY, ft=(5, 0), season=2026)
        for i in range(5)
    ]
    store_fixtures(db, late, lambda: T0)
    after = compute(db, as_of=T0 + 10 * DAY)
    assert before["cutoff"] == T0.isoformat()
    assert before["inputs_hash"] == after["inputs_hash"]
    assert after["teams"]["home"]["form"]["display"] == "2.08"  # 5 draws: 0.83 + 1.25
    assert after["teams"]["home"]["goals"]["btts"]["matches"] == 5
    # a later fixture does see them
    db.execute(
        update(fixtures).where(fixtures.c.id == UPCOMING_ID).values(kickoff_utc=T0 + 9 * DAY)
    )
    # now eight matches: 5 later wins 5-0 and the three latest draws -> 18/24 -> 1.875;
    # GD +25 capped at +14.4 -> 2.5: 4.38
    assert compute(db, as_of=T0 + 10 * DAY)["teams"]["home"]["form"]["display"] == "4.38"


def test_as_of_before_kickoff_uses_only_known_results(db):
    b = Builder(db, start=T0 - 10 * DAY)
    first = b.add(1, 50, 3, 0, season=2026)
    b.add(1, 51, 0, 3, season=2026)
    b.upcoming(1, 2)
    b.save()
    r = compute(db, as_of=fx(db, first).kickoff_utc + timedelta(hours=1))
    assert r["teams"]["home"]["form"]["breakdown"]["matches"] == 1


def test_head_to_head_most_recent_five_without_affecting_indicators(db):
    b = Builder(db, start=T0 - 1000 * DAY)
    ids = []
    for i in range(6):
        ids.append(
            b.add(1, 2, i, 0, season=2023 + (i // 3))
            if i % 2 == 0
            else b.add(2, 1, 0, i, season=2023 + (i // 3))
        )
    b.add(1, 2, 3, 0, status="AWD")  # awarded: not a valid meeting
    playoff = b.add(2, 1, 1, 1, round_name="Playoffs - 1", season=2025)
    b.upcoming(1, 2)
    b.save()
    r = compute(db)
    h2h = r["head_to_head"]
    assert len(h2h) == 5 and h2h[0]["fixture_id"] == playoff and h2h[0]["round"] == "Playoffs - 1"
    assert ids[0] not in [m["fixture_id"] for m in h2h]
    assert h2h[-1]["older"] is True and h2h[0]["older"] is False
    # removing H2H meetings from the picture leaves the primary indicators unchanged
    home_matches = {m["fixture_id"] for m in r["teams"]["home"]["form"]["matches"]}
    assert playoff not in home_matches


def test_cache_refresh_unchanged_superseded_and_point_in_time(db):
    b = Builder(db)
    for i in range(5):
        b.add(1, 50 + i, 1, 0, season=2026)
        b.add(60 + i, 2, 0, 0, season=2026)
    b.upcoming(1, 2)
    b.save()
    t1, t2, t3 = T0, T0 + timedelta(hours=1), T0 + timedelta(hours=2)
    assert cache.refresh(db, [UPCOMING_ID], t1, t1) == {
        "inserted": 2,
        "unchanged": 0,
        "superseded": 0,
        "retired_old_version": 0,
    }
    assert cache.refresh(db, [UPCOMING_ID], t2, t2) == {
        "inserted": 0,
        "unchanged": 2,
        "superseded": 0,
        "retired_old_version": 0,
    }
    # a new result for the home team arrives -> venue-basis result changes
    store_fixtures(
        db,
        [fixture_item(4000, 1, 99, kickoff=T0 - timedelta(hours=3), ft=(0, 4), season=2026)],
        lambda: t3,
    )
    counts = cache.refresh(db, [UPCOMING_ID], t3, t3)
    assert counts["superseded"] == 2 and counts["inserted"] == 2
    rows = db.execute(select(screener_results).order_by(screener_results.c.id)).all()
    assert len(rows) == 4 and rows[0].superseded_at == t3 and rows[0].verified_at == t2
    now_view = cache.cached(db, "venue")
    assert len(now_view) == 1 and now_view[0]["teams"]["home"]["form"]["sequence"].startswith("L")
    past_view = cache.cached(db, "venue", at=t2)
    assert past_view[0]["teams"]["home"]["form"]["sequence"] == "W-W-W-W-W"
    assert json.loads(rows[0].payload)["inputs_hash"] == rows[0].inputs_hash
    assert cache.invalidate(db, t3) == 2
    assert cache.refresh(db, [UPCOMING_ID], t3, t3)["inserted"] == 2


def test_ranking_directions():
    from datetime import timedelta as td

    def res(fid, diff, btts, over, hours):
        return {
            "fixture": {"id": fid, "kickoff": (T0 + td(hours=hours)).isoformat()},
            "basis": "venue",
            "match_result": {"form_difference": diff},
            "btts": {"yes_indicator": btts},
            "over_under_2_5": {"over_indicator": over},
        }

    rs = [
        res(1, 1.2, 0.7, 0.4, 30),
        res(2, -0.8, 0.3, 0.8, 10),
        res(3, 0.05, 0.5, None, 20),
        res(4, None, None, 0.6, 5),
        res(
            5, 1.2, 0.7, 0.4, 30
        ),  # ties fixture 1 on everything, incl. kickoff -> id breaks the tie
    ]
    ids = lambda xs: [r["fixture"]["id"] for r in xs]  # noqa: E731
    assert ids(rank(rs, "kickoff_earliest")) == [4, 2, 3, 1, 5]
    assert ids(rank(rs, "kickoff_latest")) == [5, 1, 3, 2, 4]
    assert ids(rank(rs, "home_stronger")) == [1, 5, 3, 2, 4]  # unavailable (4) listed last
    assert ids(rank(rs, "away_stronger")) == [2, 3, 1, 5, 4]
    assert ids(rank(rs, "evenly_matched")) == [3, 2, 1, 5, 4]
    assert ids(rank(rs, "btts_yes")) == [1, 5, 3, 2, 4]
    assert ids(rank(rs, "btts_no")) == [2, 3, 1, 5, 4]
    assert ids(rank(rs, "over")) == [2, 4, 1, 5, 3]
    assert ids(rank(rs, "under")) == [1, 5, 4, 2, 3]
    # thresholds filter and drop unavailable values
    assert ids(rank(rs, "home_stronger", threshold=0.5)) == [1, 5]
    assert ids(rank(rs, "evenly_matched", threshold=0.1)) == [3]
    assert ids(rank(rs, "btts_no", threshold=0.6)) == [2]
    # deterministic: input order does not matter
    assert ids(rank(list(reversed(rs)), "home_stronger")) == ids(rank(rs, "home_stronger"))


def test_old_engine_version_rows_are_retired(db):
    from diski9.db.schema import screener_results
    from diski9.screener.engine import ENGINE_VERSION

    b = Builder(db)
    for i in range(3):
        b.add(1, 50 + i, 1, 0)
        b.add(60 + i, 2, 0, 0)
    b.upcoming(1, 2)
    b.save()
    cache.refresh(db, [UPCOMING_ID], T0, T0)
    # simulate rows calculated on the previous (-1 to 4) scale
    db.execute(update(screener_results).values(engine_version="1.2.0"))
    assert cache.cached(db, "venue") == []  # old-version rows are never served
    later = T0 + timedelta(hours=1)
    counts = cache.refresh(db, [UPCOMING_ID], later, later)
    assert counts["retired_old_version"] == 2 and counts["inserted"] == 2
    active = db.execute(
        select(screener_results).where(screener_results.c.superseded_at.is_(None))
    ).all()
    assert {r.engine_version for r in active} == {ENGINE_VERSION}


# ------------------------------------------------- current-season goals markets
def test_goals_use_current_season_and_division_only(db):
    b = Builder(db, start=T0 - 300 * DAY)
    for i in range(8):
        b.add(1, 50 + i, 3, 3, season=2025)  # previous season: BTTS + over every time
    for i in range(4):
        b.add(1, 80 + i, 2, 2, league=40, season=2026)  # other division, current season year
    b.add(1, 90, 4, 4, season=2026, round_name="Relegation Round - 1")  # excluded round
    b.add(1, 91, 4, 4, season=2026, status="AWD")  # awarded: excluded
    for i, (h, a) in enumerate(((1, 0), (2, 1), (0, 0), (1, 1))):
        b.add(1, 100 + i, h, a, season=2026, gap=DAY * 2)  # 4 current-season home matches
    for i in range(5):
        b.add(200 + i, 2, 2, 1 if i < 2 else 0, season=2026)  # away team: 5 current-season away
    b.upcoming(1, 2)
    b.save()
    r = compute(db)
    home = r["teams"]["home"]["goals"]
    assert home["btts"]["display"] == "2/4 (50%)"  # 2-1 and 1-1 only; never 3/10 or padded
    assert {m["season"] for m in home["matches"]} == {2026}
    assert {m["competition"] for m in home["matches"]} == {"Premier League"}
    away = r["teams"]["away"]["goals"]
    assert away["btts"]["display"] == "2/5 (40%)"
    # combined = (50% + 40%) / 2 = 45%; complement 55%
    assert r["btts"]["yes_display"] == "45%" and r["btts"]["no_display"] == "55%"
    assert r["limited_data"]["goals"]
    assert home["sample"]["limited_data_reasons"] == ["fewer_than_6_matches"]
    # the Form Score (engine 2.4.0) is current-season, current-competition only too
    assert r["teams"]["home"]["form"]["sample"]["matches"] == 4
    assert all(
        m["provenance"] == "current_season_same_division"
        for m in r["teams"]["home"]["form"]["matches"]
    )


def test_spec_example_four_and_five_match_samples(db):
    """Home 3/4 BTTS (75%), away 2/5 (40%) -> combined 57.5%, No 42.5%."""
    b = Builder(db)
    for h, a in ((1, 1), (2, 1), (1, 2), (1, 0)):
        b.add(1, 50 + h * 10 + a, h, a, season=2026)
    for h, a in ((1, 1), (2, 2), (1, 0), (2, 0), (3, 0)):
        b.add(60 + h * 10 + a, 2, h, a, season=2026)
    b.upcoming(1, 2)
    b.save()
    r = compute(db)
    assert r["teams"]["home"]["goals"]["btts"]["display"] == "3/4 (75%)"
    assert r["teams"]["away"]["goals"]["btts"]["display"] == "2/5 (40%)"
    assert r["btts"]["yes_display"] == "57.5%" and r["btts"]["no_display"] == "42.5%"
    assert r["btts"]["yes_indicator"] + r["btts"]["no_indicator"] == pytest.approx(1)
    o = r["over_under_2_5"]
    assert o["over_indicator"] + o["under_indicator"] == pytest.approx(1)


@pytest.mark.parametrize("n,limited", [(5, True), (6, False), (9, False), (10, False), (12, False)])
def test_goals_limited_data_thresholds(db, n, limited):
    b = Builder(db)
    for i in range(n):
        b.add(1, 50 + i, 1, 1, season=2026)
        b.add(70 + i, 2, 1, 1, season=2026)
    b.upcoming(1, 2)
    b.save()
    r = compute(db)
    assert r["limited_data"]["goals"] is limited
    assert r["teams"]["home"]["goals"]["btts"]["matches"] == min(n, 10)


def test_goals_zero_observations_unavailable(db):
    b = Builder(db)
    for i in range(6):
        b.add(1, 50 + i, 1, 1, season=2025)  # only previous-season history
        b.add(70 + i, 2, 1, 1, season=2026)
    b.upcoming(1, 2)
    b.save()
    r = compute(db)
    assert r["teams"]["home"]["goals"]["btts"] is None  # never filled from earlier seasons
    assert r["btts"]["yes_indicator"] is None and r["btts"]["yes_display"] is None
    assert r["over_under_2_5"]["over_indicator"] is None


def test_current_season_rule_is_point_in_time(db):
    b = Builder(db, start=T0 - 60 * DAY)
    for i in range(3):
        b.add(1, 50 + i, 2, 2, season=2026)
        b.add(70 + i, 2, 1, 1, season=2026)
    b.upcoming(1, 2, kickoff=T0)
    b.save()
    store_fixtures(
        db, [fixture_item(6000, 1, 99, kickoff=T0 + DAY, ft=(0, 0), season=2026)], lambda: T0
    )
    r = compute(db, as_of=T0 + 5 * DAY)
    assert r["teams"]["home"]["goals"]["btts"]["display"] == "3/3 (100%)"  # later 0-0 ignored
