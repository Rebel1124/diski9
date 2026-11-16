# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Milestone 5.3: Diski Form Score Model D, league baselines, goals-market
presentation (records / league baseline / market) and cache safety."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from diski9.app import ScreenerData
from diski9.app.app import build_layout, fixture_card, results_payload
from diski9.app.views import record_text, render_detail
from diski9.db.schema import screener_results
from diski9.ingestion.fixtures import store_fixtures
from diski9.screener import cache
from diski9.screener.calc import diski_form_score
from diski9.screener.engine import (
    ENGINE_VERSION,
    Match,
    MatchStore,
    compute_fixture,
    league_baseline,
)
from diski9.screener.rank import rank

from .factories import T0, fixture_item, seed_competition
from .test_app import EPL_FIX, EXTRA, PROMOTED_FIX, PSL_FIX, _text, data, populated  # noqa: F401

T = datetime(2026, 9, 1, 15, tzinfo=UTC)
F = Fraction


# ------------------------------------------------------------- Model D
def test_engine_version_bumped_for_model_d():
    assert ENGINE_VERSION == "2.1.0"


def test_model_d_exact_formula_worked_example():
    # 10 points (W W W D L) and goal difference +4: the example in the brief
    fs = diski_form_score([(3, 0), (1, 0), (2, 1), (1, 1), (0, 1)])
    assert (fs.points, fs.goal_difference) == (10, 4)
    assert fs.points_component == F(5, 2) * F(10, 15)
    assert fs.goal_difference_component == F(5, 2) * F(13, 18)
    b = fs.breakdown()
    assert b["points_component_display"] == "1.67"
    assert b["goal_difference_component_display"] == "1.81"
    assert b["form_score_display"] == "3.47"
    assert b["method"] == "D"


def test_model_d_bounds_and_extremes():
    rng = random.Random(53)
    for _ in range(3000):
        w = [(rng.randint(0, 6), rng.randint(0, 6)) for _ in range(rng.randint(1, 5))]
        assert 0 <= diski_form_score(w).score <= 5
    assert diski_form_score([(4, 0)] * 5).score == 5
    assert diski_form_score([(0, 4)] * 5).score == 0


@pytest.mark.parametrize(
    "gd,component",
    [
        (-12, F(0)),
        (-9, F(0)),
        (-1, F(5, 2) * F(8, 18)),
        (0, F(5, 4)),
        (1, F(5, 2) * F(10, 18)),
        (9, F(5, 2)),
        (14, F(5, 2)),
    ],
)
def test_goal_difference_component_and_clipping(gd, component):
    # five draws (5 points) except the first result carries the goal difference
    first = (gd, 0) if gd > 0 else (0, -gd) if gd < 0 else (0, 0)
    fs = diski_form_score([first, (0, 0), (0, 0), (0, 0), (0, 0)])
    assert fs.goal_difference == gd
    assert fs.goal_difference_capped == max(-9, min(9, gd))
    assert fs.goal_difference_component == component


def test_points_component_is_linear_and_no_bonuses():
    for wins in range(6):
        fs = diski_form_score([(1, 0)] * wins + [(0, 1)] * (5 - wins))
        assert fs.points_component == F(5, 2) * F(3 * wins, 15)
    # identical points and goal difference -> identical score, whatever the streak or goals
    streak = diski_form_score([(3, 0), (3, 1), (2, 1), (0, 0), (3, 0)])  # 3 wins first, 11 scored
    other = diski_form_score([(0, 0), (3, 0), (3, 1), (2, 1), (3, 0)])
    assert streak.points == other.points and streak.goal_difference == other.goal_difference
    assert streak.score == other.score
    assert not any("bonus" in k or k == "raw" for k in streak.breakdown())


def test_partial_window_and_missing_history():
    two = diski_form_score([(2, 0), (2, 0)])  # actual totals: 6 points, GD +4
    assert two.score == F(5, 2) * F(6, 15) + F(5, 2) * F(13, 18)
    assert diski_form_score([(5, 0)] * 4).score < 5  # a short window cannot reach 5
    one_draw = diski_form_score([(1, 1)])
    assert one_draw.score == F(5, 2) * F(1, 15) + F(5, 4)  # level GD still counts 1.25
    assert diski_form_score([]) is None  # Unavailable, never 0


def _m(fid, days, comp, season, h, a, hg, ag, eligible=True, venue="verified"):
    return Match(
        fid,
        T + timedelta(days=days),
        comp,
        season,
        h,
        a,
        hg,
        ag,
        venue,
        eligible,
        None,
        None,
        "FT",
        str(fid),
    )


def _store(ms):
    return MatchStore.from_matches(ms, {i: f"T{i}" for i in range(1, 400)}, {39: "EPL", 40: "Ch"})


def _fixture(fid, home, away, days, comp=39, season=2026):
    return SimpleNamespace(
        id=fid,
        competition_id=comp,
        season=season,
        home_team_id=home,
        away_team_id=away,
        kickoff_utc=T + timedelta(days=days),
    )


def test_venue_and_overall_windows_and_form_difference():
    ms = []
    for i in range(5):
        ms.append(_m(10 + i, i * 2, 39, 2026, 1, 50 + i, 3, 0))  # team 1 home wins
        ms.append(_m(30 + i, i * 2 + 1, 39, 2026, 60 + i, 1, 1, 0))  # team 1 away losses
        ms.append(_m(70 + i, i * 2, 39, 2026, 80 + i, 2, 0, 2))  # team 2 away wins
    store = _store(ms)
    fx = _fixture(999, 1, 2, 30)
    venue = compute_fixture(store, fx, fx.kickoff_utc, "venue")
    overall = compute_fixture(store, fx, fx.kickoff_utc, "overall")
    hv, ho = venue["teams"]["home"]["form"], overall["teams"]["home"]["form"]
    assert hv["sequence"] == "W-W-W-W-W" and hv["display"] == "5.00"
    # overall: last five of ten alternating -> L W L W L, 6 points, GD 3x(-1) + 2x(+3) = +3
    assert ho["sequence"] == "L-W-L-W-L"
    assert ho["breakdown"]["points"] == 6 and ho["breakdown"]["goal_difference"] == 3
    mr = venue["match_result"]
    assert mr["method"] == "D"
    assert mr["form_difference"] == pytest.approx(mr["home_form"] - mr["away_form"])


def test_rankings_use_model_d_form_difference():
    ms = []
    teams = list(range(1, 13))
    for k, t in enumerate(teams):  # team t: k wins, 5-k losses, at home and away
        for i in range(5):
            win = i < k % 6
            ms.append(
                _m(1000 + k * 10 + i, i, 39, 2026, t, 300 + i, 1 if win else 0, 0 if win else 1)
            )
            ms.append(
                _m(2000 + k * 10 + i, i, 39, 2026, 310 + i, t, 0 if win else 1, 1 if win else 0)
            )
    store = _store(ms)
    results = [
        compute_fixture(
            store, _fixture(5000 + j, teams[j], teams[-1 - j], 40), T + timedelta(days=40)
        )
        for j in range(6)
    ]
    ranked = rank(results, "home_stronger")
    diffs = [r["match_result"]["form_difference"] for r in ranked]
    assert diffs == sorted(diffs, reverse=True)
    for r in results:
        h = diski_form_score(
            (t.goals_for, t.goals_against)
            for t in store.team_window(
                r["teams"]["home"]["team_id"], T + timedelta(days=40), "home", 5
            )
        )
        assert r["match_result"]["home_form"] == float(h.score)


def test_no_lookahead_in_form_or_baseline():
    ms = [_m(i, i, 39, 2026, 1 + i % 4, 5 + i % 4, i % 3, 1) for i in range(40)]
    store = _store(ms)
    fx = _fixture(999, 1, 5, 20)
    before = compute_fixture(store, fx, fx.kickoff_utc)
    later = _store(ms + [_m(500 + i, 25 + i, 39, 2026, 1, 5, 9, 0) for i in range(5)])
    after = compute_fixture(later, fx, fx.kickoff_utc + timedelta(days=30))
    assert before["inputs_hash"] == after["inputs_hash"]
    assert before["league_baseline"] == after["league_baseline"]


# ------------------------------------------------------- league baselines
def _league(n_current, n_prev, current_btts, prev_btts, comp=39):
    """n matches; the first `*_btts` of each set are 1-1 (BTTS, under), the rest 3-0 (over)."""
    ms, fid = [], 1
    for i in range(n_prev):
        ms.append(
            _m(fid, -300 + i, comp, 2025, 100 + i, 200 + i, *((1, 1) if i < prev_btts else (3, 0)))
        )
        fid += 1
    for i in range(n_current):
        ms.append(
            _m(fid, i, comp, 2026, 100 + i, 200 + i, *((1, 1) if i < current_btts else (3, 0)))
        )
        fid += 1
    return ms


def test_baseline_current_season_only_from_30_matches():
    store = _store(_league(30, 40, current_btts=12, prev_btts=40))
    lb = league_baseline(store, 39, 2026, T + timedelta(days=60))
    assert lb["source"] == "current_season" and lb["current_matches"] == 30
    assert lb["btts"] == pytest.approx(12 / 30) and lb["over_2_5"] == pytest.approx(18 / 30)
    assert lb["previous_matches"] == 0 and lb["current_weight"] == 1


def test_baseline_early_season_blend_weight_n_over_30():
    store = _store(_league(12, 40, current_btts=6, prev_btts=10))
    lb = league_baseline(store, 39, 2026, T + timedelta(days=60))
    w = F(12, 30)
    assert lb["source"] == "blended_previous_season"
    assert lb["current_weight"] == pytest.approx(float(w))
    assert lb["btts"] == pytest.approx(float(w * F(6, 12) + (1 - w) * F(10, 40)))
    assert lb["over_2_5"] == pytest.approx(float(w * F(6, 12) + (1 - w) * F(30, 40)))
    assert (lb["current_matches"], lb["previous_matches"]) == (12, 40)
    assert lb["season_label"] == "2026/27" and lb["previous_season_label"] == "2025/26"


def test_baseline_previous_season_only_and_unavailable():
    store = _store(_league(0, 40, 0, 10))
    lb = league_baseline(store, 39, 2026, T)
    assert lb["source"] == "previous_season_only" and lb["btts"] == pytest.approx(0.25)
    # thin current season and no previous season stored -> Unavailable, not a made-up value
    assert league_baseline(_store(_league(10, 0, 5, 0)), 39, 2026, T + timedelta(days=60)) is None
    assert league_baseline(_store([]), 39, 2026, T) is None


def test_baseline_excludes_future_ineligible_and_other_competitions():
    ms = _league(30, 0, current_btts=30, prev_btts=0)  # 30 BTTS matches, days 0..29
    ms.append(_m(900, 15, 39, 2026, 1, 2, 3, 0, eligible=False))  # awarded: excluded
    ms += [_m(901 + i, 10, 40, 2026, 3, 4, 3, 0) for i in range(10)]  # other competition
    ms += [_m(950 + i, 40 + i, 39, 2026, 5, 6, 3, 0) for i in range(10)]  # after cutoff
    ms.append(_m(999, 35, 39, 2026, 7, 8, 3, 0))  # the fixture itself, kickoff == cutoff
    store = _store(ms)
    lb = league_baseline(store, 39, 2026, T + timedelta(days=35))
    assert lb["current_matches"] == 30 and lb["btts"] == 1.0 and lb["over_2_5"] == 0.0


def test_baseline_ignores_postponed_fixtures(conn):
    seed_competition(conn, 39, years=(2025, 2026))
    T0x = T0 - timedelta(days=100)
    items = [
        fixture_item(i + 1, 10 + i, 50 + i, season=2026, kickoff=T0x + timedelta(days=i), ft=(1, 1))
        for i in range(30)
    ] + [
        fixture_item(
            100 + i, 10 + i, 60 + i, season=2026, kickoff=T0x + timedelta(days=i), status=st
        )
        for i, st in enumerate(("PST", "CANC", "ABD", "AWD"))
    ]
    store_fixtures(conn, items, lambda: T0)
    lb = league_baseline(MatchStore(conn), 39, 2026, T0)
    assert lb["current_matches"] == 30 and lb["btts"] == 1.0


def test_baseline_matches_milestone_5_2_research_method():
    from diski9.research.historical_goals import league_prior

    rng = random.Random(7)
    ms = [
        _m(i, -365 + i, 39, 2025, 1 + i % 9, 20 + i % 9, rng.randint(0, 3), rng.randint(0, 3))
        for i in range(300)
    ]
    ms += [
        _m(1000 + i, i, 39, 2026, 1 + i % 9, 20 + i % 9, rng.randint(0, 3), rng.randint(0, 3))
        for i in range(60)
    ]
    store = _store(ms)
    for day in (0, 5, 17, 29, 31, 59):
        cut = T + timedelta(days=day)
        prod, research = league_baseline(store, 39, 2026, cut), league_prior(store, 39, 2026, cut)
        assert prod["btts"] == pytest.approx(research.btts)
        assert prod["over_2_5"] == pytest.approx(research.over)


def test_team_histories_stay_current_season_only():
    ms = [_m(i, -300 + i, 39, 2025, 1, 100 + i, 1, 1) for i in range(10)]  # last season
    ms += [_m(100 + i, -200 + i, 40, 2026, 1, 200 + i, 1, 1) for i in range(3)]  # other comp
    ms += [_m(200 + i, i, 39, 2026, 1, 300 + i, 2, 0) for i in range(2)]  # this season
    ms += [_m(300 + i, i, 39, 2026, 2, 400 + i, 0, 0) for i in range(40)]
    store = _store(ms)
    r = compute_fixture(store, _fixture(999, 1, 2, 60), T + timedelta(days=60), "overall")
    g = r["teams"]["home"]["goals"]
    assert (
        g["btts"]["matches"] == 2 and g["btts"]["hits"] == 0
    )  # never the 2025 or other-comp draws
    assert g["sample"]["limited_data"] is True
    assert r["league_baseline"]["source"] == "current_season"


# ---------------------------------------------------- records presentation
def test_record_text_counts_and_missing_history():
    assert record_text({"hits": 7, "matches": 10}, "BTTS") == (
        "BTTS in 7 of 10",
        "No BTTS in 3 of 10",
    )
    assert record_text({"hits": 4, "matches": 9}, "OU25") == (
        "Over 2.5 in 4 of 9",
        "Under 2.5 in 5 of 9",
    )
    assert record_text(None, "BTTS") == ("No current-season history", None)
    assert record_text({"hits": 0, "matches": 0}, "OU25") == ("No current-season history", None)


def test_btts_detail_shows_three_layers_with_market_matching_odds_table(data):
    r, ov, official = data.detail(EPL_FIX, "overall")
    d = render_detail(r, ov, official, "BTTS", data)
    summary = _text(d.children[1])
    # team 1: ten 3-0 home wins; team 2: ten 1-1 away draws
    assert "BTTS in 0 of 10" in summary and "No BTTS in 10 of 10" in summary
    assert "BTTS in 10 of 10" in summary
    assert "League BTTS baseline" in summary and "Unavailable" in summary  # no 2025 EPL stored
    assert "Market-implied probabilities" in summary
    # full_book: Yes 1.80, No 2.00 -> 52.6% / 47.4%; identical to the expanded table
    assert "52.6%" in summary and "47.4%" in summary
    full = _text(d)
    assert full.count("52.6%") >= 2
    assert "Historical indicator" not in summary  # no longer the headline
    assert "predicted probabilit" not in summary.lower().replace("not predicted probabilit", "")


def test_over_under_detail_and_equal_pair(data):
    from diski9.api_football.markets import Market
    from diski9.app.views import goals_market_probabilities

    r, ov, official = data.detail(EPL_FIX, "overall")
    summary = _text(render_detail(r, ov, official, "OU25", data).children[1])
    assert "Over 2.5 in 10 of 10" in summary and "Under 2.5 in 10 of 10" in summary
    assert "League Over 2.5 baseline" in summary
    block = goals_market_probabilities(
        ov.markets[Market.OVER_UNDER_25].implied, Market.OVER_UNDER_25
    )
    pair = block.children[1]
    assert pair.className == "pair-row compact"
    values = [c.children[1] for c in pair.children if getattr(c, "className", "") == "pair"]
    assert [v.className for v in values] == ["pair-value", "pair-value"]
    over, under = (float(v.children.rstrip("%")) for v in values)
    assert over + under == pytest.approx(100, abs=0.11)


def test_limited_and_missing_history_states(data):
    r, ov, official = data.detail(PROMOTED_FIX, "overall")
    summary = _text(render_detail(r, ov, official, "BTTS", data).children[1])
    assert "BTTS in 0 of 1" in summary and "Limited" in summary  # promoted team: 1 match
    r, ov, official = data.detail(EXTRA[0], "overall")
    summary = _text(render_detail(r, ov, official, "BTTS", data).children[1])
    assert summary.count("No current-season history") == 2
    assert "0%" not in summary
    row = data.row("BTTS", r)
    assert row["home_metric"] == "—" and row["indicator"] is None


def test_overall_and_venue_records_differ():
    ms = [_m(i, i, 39, 2026, 1, 100 + i, 1, 1) for i in range(3)]  # home BTTS
    ms += [_m(10 + i, 5 + i, 39, 2026, 110 + i, 1, 1, 0) for i in range(4)]  # away, no BTTS
    store = _store(ms)
    fx = _fixture(999, 1, 2, 20)
    v = compute_fixture(store, fx, fx.kickoff_utc, "venue")["teams"]["home"]["goals"]["btts"]
    o = compute_fixture(store, fx, fx.kickoff_utc, "overall")["teams"]["home"]["goals"]["btts"]
    assert (v["hits"], v["matches"]) == (3, 3) and (o["hits"], o["matches"]) == (3, 7)


def test_stale_and_unavailable_goals_markets(populated):
    stale = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0 + 2 * timedelta(days=1))
    r, ov, official = stale.detail(EPL_FIX, "overall")
    summary = _text(render_detail(r, ov, official, "BTTS", stale).children[1])
    assert "Stale" in summary and "Prices may have changed" in summary and "52.6%" in summary
    assert stale.row("BTTS", r)["market_status"] == "stale"
    fresh = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    r, ov, official = fresh.detail(PSL_FIX, "overall")
    summary = _text(render_detail(r, ov, official, "OU25", fresh).children[1])
    assert "market-implied probabilities are unavailable" in summary
    assert "%" not in summary.split("League Over 2.5 baseline")[-1].split("Reference odds")[-1]
    assert fresh.row("OU25", r)["market"] == "No odds"


def test_table_columns_show_records_baseline_and_market(data):
    p = results_payload(data, "BTTS", [39, 288], None, "2026-12-31", "overall", "btts_yes", 0, 1)
    rows = p[0].children[1].children
    row = next(r for r in rows if r.id["index"] == EPL_FIX)
    cells = [_text(c) for c in row.children]
    assert cells[4:9] == ["0/10", "10/10", "50%", "—", "53% · 47%"]
    card = fixture_card("BTTS", data.row("BTTS", data.detail(EPL_FIX, "overall")[0]), None)
    assert "BTTS records 0/10 · 10/10" in _text(card) and "Market 53% · 47%" in _text(card)


def test_challenge_eligibility_unchanged(populated):
    from diski9.api_football.markets import Market
    from diski9.odds.display import challenge_consensus

    with populated.connect() as conn:
        assert challenge_consensus(conn, EPL_FIX, T0)[Market.BTTS] is not None
        assert challenge_consensus(conn, EPL_FIX, T0 + timedelta(days=2))[Market.BTTS] is None


# ------------------------------------------------------------ cache safety
def test_old_engine_rows_never_served_and_banner_until_rebuilt(populated):
    with populated.begin() as conn:
        conn.execute(update(screener_results).values(engine_version="2.0.0"))
    d = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    snap = d.snapshot()
    assert snap.outdated_rows > 0 and not snap.results["venue"]  # nothing mixed in
    assert "earlier method" in _text(build_layout(d))
    with populated.begin() as conn:
        counts = cache.refresh(conn, [EPL_FIX, PSL_FIX, PROMOTED_FIX, *EXTRA], T0, T0)
        assert counts["retired_old_version"] > 0
        active = conn.execute(
            select(screener_results.c.engine_version).where(
                screener_results.c.superseded_at.is_(None)
            )
        ).all()
    assert {a[0] for a in active} == {"2.1.0"}
    snap = d.snapshot(force=True)
    assert snap.outdated_rows == 0 and EPL_FIX in snap.results["venue"]
    assert "earlier method" not in _text(build_layout(d))
    payload = json.loads(json.dumps(snap.results["venue"][EPL_FIX]))
    assert payload["engine_version"] == "2.1.0" and payload["match_result"]["method"] == "D"
