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
def test_engine_version_bumped_for_current_season_baselines():
    assert ENGINE_VERSION == "3.0.0"


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
    assert b["method"].startswith("D")


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
    # engine 2.4.0: normalised by the N matches actually played (cap 1.8 per match)
    two = diski_form_score([(2, 0), (2, 0)])  # 6 of 6 points; GD +4 > cap 3.6
    assert two.score == 5
    three = diski_form_score([(1, 0), (0, 0), (0, 2)])  # 4 of 9 points, GD -1, cap 5.4
    assert three.score == F(5, 2) * F(4, 9) + F(5, 2) * (F(-1) + F(27, 5)) / (2 * F(27, 5))
    one_draw = diski_form_score([(1, 1)])
    assert one_draw.score == F(5, 2) * F(1, 3) + F(5, 4)  # level GD still counts 1.25
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
    assert hv["score"] == ho["score"]  # the basis no longer changes Match Result
    # last eight of ten alternating (newest first): L W L W L W L W -> 12 points,
    # GD 4x(+3) + 4x(-1) = +8
    assert ho["sequence"] == "L-W-L-W-L-W-L-W"
    assert ho["breakdown"]["points"] == 12 and ho["breakdown"]["goal_difference"] == 8
    assert ho["venue_context"]["display"] == "5.00"  # five home wins, display only
    mr = venue["match_result"]
    assert mr["method"] == "D8-current-season"
    assert mr["form_difference"] == pytest.approx(mr["home_form"] - mr["away_form"])


def test_rankings_use_model_d_form_difference():
    """Engine 3.0 ranks by Goal Model probabilities; the Diski Form Score is still
    computed (Match Lab context) with the production Model D formula."""
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
    for r in results:
        h = diski_form_score(
            (t.goals_for, t.goals_against)
            for t in store.team_window(
                r["teams"]["home"]["team_id"], T + timedelta(days=40), None, 8, 39, 2026
            )
        )
        assert r["match_result"]["home_form"] == float(h.score)
        gm = r["goal_model"]
        if gm["available"]:
            ranked = rank(results, "home_win")
            probs = [x["goal_model"]["probabilities"]["home"] for x in ranked]
            assert probs == sorted(probs, reverse=True)


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
    assert lb["available"] and lb["source"] == "current_season" and lb["matches"] == 30
    assert lb["btts"] == pytest.approx(12 / 30) and lb["over_2_5"] == pytest.approx(18 / 30)
    assert lb["btts_display"] == "40%" and lb["over_2_5_display"] == "60%"
    assert "previous_matches" not in lb and "current_weight" not in lb


def test_previous_season_never_blended_below_minimum():
    # 12 current-season matches and a full previous season stored: still unavailable
    store = _store(_league(12, 40, current_btts=6, prev_btts=10))
    lb = league_baseline(store, 39, 2026, T + timedelta(days=60))
    assert lb["available"] is False and lb["matches"] == 12 and lb["min_matches"] == 30
    assert lb["btts"] is None and lb["over_2_5"] is None  # never 0, never a blend
    assert lb["btts_display"] is None
    # no current-season match at all: unavailable, previous season ignored
    lb0 = league_baseline(_store(_league(0, 40, 0, 10)), 39, 2026, T)
    assert lb0["available"] is False and lb0["matches"] == 0 and lb0["btts"] is None
    assert league_baseline(_store([]), 39, 2026, T)["available"] is False


def test_baseline_becomes_available_exactly_at_minimum():
    ms = _league(40, 0, current_btts=20, prev_btts=0)  # one match per day, days 0..39
    store = _store(ms)
    assert league_baseline(store, 39, 2026, T + timedelta(days=29))["available"] is False  # 29
    at30 = league_baseline(store, 39, 2026, T + timedelta(days=30))
    assert at30["available"] and at30["matches"] == 30
    assert at30["btts"] == pytest.approx(20 / 30)  # first 20 are BTTS
    # the threshold is configurable
    assert league_baseline(store, 39, 2026, T + timedelta(days=10), minimum=10)["available"]
    assert not league_baseline(store, 39, 2026, T + timedelta(days=10), minimum=11)["available"]


def test_previous_season_results_do_not_change_an_available_baseline():
    with_prev = _store(_league(30, 300, current_btts=15, prev_btts=300))
    without = _store(_league(30, 0, current_btts=15, prev_btts=0))
    cut = T + timedelta(days=60)
    a, b = league_baseline(with_prev, 39, 2026, cut), league_baseline(without, 39, 2026, cut)
    assert a == b and a["btts"] == pytest.approx(0.5)


def test_baseline_excludes_future_ineligible_and_other_competitions():
    ms = _league(30, 0, current_btts=30, prev_btts=0)  # 30 BTTS matches, days 0..29
    ms.append(_m(900, 15, 39, 2026, 1, 2, 3, 0, eligible=False))  # awarded: excluded
    ms += [_m(901 + i, 10, 40, 2026, 3, 4, 3, 0) for i in range(10)]  # other competition
    ms += [_m(950 + i, 40 + i, 39, 2026, 5, 6, 3, 0) for i in range(10)]  # after cutoff
    ms.append(_m(999, 35, 39, 2026, 7, 8, 3, 0))  # the fixture itself, kickoff == cutoff
    store = _store(ms)
    lb = league_baseline(store, 39, 2026, T + timedelta(days=35))
    assert lb["matches"] == 30 and lb["btts"] == 1.0 and lb["over_2_5"] == 0.0


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
    assert lb["matches"] == 30 and lb["btts"] == 1.0


def test_baseline_compute_fixture_and_config_threshold():
    ms = _league(20, 40, current_btts=10, prev_btts=40)
    store = _store(ms)
    fx = _fixture(999, 100, 101, 60)
    r = compute_fixture(store, fx, fx.kickoff_utc)
    assert r["league_baseline"]["available"] is False and r["league_baseline"]["matches"] == 20
    assert r["config"]["league_baseline_min"] == 30
    from diski9.screener.engine import ScreenerConfig

    r20 = compute_fixture(store, fx, fx.kickoff_utc, config=ScreenerConfig(league_baseline_min=20))
    assert r20["league_baseline"]["btts"] == pytest.approx(0.5)
    assert r20["inputs_hash"] != r["inputs_hash"]


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
    assert r["league_baseline"]["available"] and r["league_baseline"]["matches"] == 42


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
    lab = _text(d.children[1])  # The Match Lab
    market = _text(d.children[2])  # Bookmaker Market Reference
    # team 1: ten 3-0 home wins; team 2: ten 1-1 away draws (Match Lab context)
    assert "BTTS in 0 of 10" in lab and "BTTS in 10 of 10" in lab
    # 21 current-season EPL matches in the fixture: below 30, so no league percentage
    assert "League BTTS baseline" in lab and "Not enough current-season data yet" in lab
    assert "21 of 30 eligible completed league matches" in lab
    # the model's own probabilities in the baseline, market figures in the odds card
    p = r["goal_model"]["probabilities"]
    assert f"{p['btts_yes'] * 100:.1f}%" in lab and f"{p['btts_no'] * 100:.1f}%" in lab
    assert "Market-implied probabilities" not in lab
    # full_book: Yes 1.80, No 2.00 -> 52.6% / 47.4%, from the same consensus as before
    assert "Market-implied probabilities" in market and "52.6%" in market and "47.4%" in market


def test_over_under_detail_and_equal_pair(data):
    from diski9.api_football.markets import Market
    from diski9.app.views import goals_market_probabilities

    r, ov, official = data.detail(EPL_FIX, "overall")
    summary = _text(render_detail(r, ov, official, "OU25", data).children[1])
    assert "Over 2.5 in 10 of 10" in summary and "Under 2.5 in" not in summary
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
    lab = _text(render_detail(r, ov, official, "BTTS", data).children[1])
    assert "BTTS in 0 of 1" in lab and "Limited" in lab  # promoted team: 1 match
    r, ov, official = data.detail(EXTRA[0], "overall")
    lab = _text(render_detail(r, ov, official, "BTTS", data).children[1])
    assert lab.count("No current-season history") == 2
    # no matches at all: the model uses league averages only, and says so
    assert lab.count("League average only") == 2
    row = data.row("BTTS", r)
    assert row["available"] and row["limited"]


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
    card = render_detail(r, ov, official, "BTTS", stale).children[2]
    summary = _text(card)
    assert "Stale" in summary and "Prices may have changed" in summary and "52.6%" in summary
    assert stale.row("BTTS", r)["market_status"] == "stale"
    fresh = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    r, ov, official = fresh.detail(PSL_FIX, "overall")
    card = render_detail(r, ov, official, "OU25", fresh).children[2]
    assert "market-implied probabilities are unavailable" in _text(card)
    assert "%" not in _text(card.children[:-1])  # no market figure invented
    assert fresh.row("OU25", r)["market"] == "No odds"


def test_table_columns_show_records_baseline_and_market(data):
    p = results_payload(data, "BTTS", [39], None, "2026-11-18", "overall", "kickoff_earliest", 0, 1)
    rows = p[0].children[1].children
    row = next(r for r in rows if r.id["index"] == EPL_FIX)
    cells = [_text(c) for c in row.children]
    g = data.detail(EPL_FIX)[0]["goal_model"]
    eg = g["estimated_goals"]
    assert cells[4] == f"{eg['home']:.2f} – {eg['away']:.2f}"
    assert cells[5:7] == [
        f"{g['probabilities']['btts_yes'] * 100:.1f}%",
        f"{g['probabilities']['btts_no'] * 100:.1f}%",
    ]
    # final column: the single best positive edge (model vs margin-adjusted market)
    market_no = (1 / 2.00) / (1 / 1.80 + 1 / 2.00)
    market_yes = 1 - market_no
    edges = {
        "Yes": (g["probabilities"]["btts_yes"] - market_yes) * 100,
        "No": (g["probabilities"]["btts_no"] - market_no) * 100,
    }
    best = max(edges, key=edges.get)
    mkt = market_no if best == "No" else market_yes
    assert cells[7] == f"{best} {edges[best]:+.1f} pp Market {mkt * 100:.1f}%"
    assert "Consensus odds 1.80 · 2.00" in row.children[7].title
    card = fixture_card("BTTS", data.row("BTTS", data.detail(EPL_FIX, "overall")[0]), None)
    assert "Est. goals" in _text(card) and "Odds 1.80 · 2.00" in _text(card)


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
    assert snap.outdated_rows > 0 and not snap.results["overall"]  # nothing mixed in
    assert "earlier method" in _text(build_layout(d))
    with populated.begin() as conn:
        counts = cache.refresh(conn, [EPL_FIX, PSL_FIX, PROMOTED_FIX, *EXTRA], T0, T0)
        assert counts["retired_old_version"] > 0
        active = conn.execute(
            select(screener_results.c.engine_version).where(
                screener_results.c.superseded_at.is_(None)
            )
        ).all()
    assert {a[0] for a in active} == {"3.0.0"}
    snap = d.snapshot(force=True)
    assert snap.outdated_rows == 0 and EPL_FIX in snap.results["overall"]
    assert "earlier method" not in _text(build_layout(d))
    payload = json.loads(json.dumps(snap.results["overall"][EPL_FIX]))
    assert payload["engine_version"] == "3.0.0"
    assert payload["goal_model"]["model"]["goal_model_version"] == "1.0"
    assert payload["match_result"]["method"] == "D8-current-season"
