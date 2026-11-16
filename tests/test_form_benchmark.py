# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""League Diski Form Score benchmark (engine 2.3.0) and the simplified team cards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from fractions import Fraction
from types import SimpleNamespace

import pytest

from diski9.app.views import (
    analysis_card,
    calculation_section,
    form_comparison,
    render_detail,
)
from diski9.screener.calc import diski_form_score
from diski9.screener.engine import (
    Match,
    MatchStore,
    ScreenerConfig,
    compute_fixture,
    form_benchmark,
    league_members,
)

from .test_app import EPL_FIX, PSL_FIX, _find, _text, data, populated  # noqa: F401

T = datetime(2026, 9, 1, 15, tzinfo=UTC)
CFG = ScreenerConfig()


def _m(fid, days, comp, season, h, a, hg, ag, eligible=True):
    return Match(
        fid,
        T + timedelta(days=days),
        comp,
        season,
        h,
        a,
        hg,
        ag,
        "verified",
        eligible,
        None,
        None,
        "FT",
        str(fid),
    )


def league(n_teams=14, comp=39, season=2026, start=0):
    """Double round robin; team i beats team j at home when i < j (deterministic)."""
    ms, fid, day = [], 10_000 * comp + 1, start
    teams = list(range(1, n_teams + 1))
    for h in teams:
        for a in teams:
            if h == a:
                continue
            ms.append(_m(fid, day, comp, season, h, a, *((2, 0) if h < a else (1, 1))))
            fid += 1
            day += 0.05
    return ms


def store_of(ms):
    names = {i: f"T{i}" for i in range(1, 1000)}
    return MatchStore.from_matches(ms, names, {39: "EPL", 40: "Ch"})


CUT = T + timedelta(days=60)


def _expected(store, teams, venue):
    scores = []
    for t in teams:
        w = store.team_window(t, CUT, venue, 5)
        if len(w) == 5:
            scores.append(diski_form_score((x.goals_for, x.goals_against) for x in w).score)
    return float(sum(scores, Fraction(0)) / len(scores)), len(scores)


def test_overall_average_one_score_per_team():
    store = store_of(league())
    b = form_benchmark(store, 39, 2026, CUT, "overall", CFG)
    avg, n = _expected(store, range(1, 15), None)
    assert b["available"] and b["members"] == 14 and b["overall"]["teams"] == n == 14
    assert b["overall"]["average"] == pytest.approx(avg, abs=1e-12)
    assert b["overall"]["average"] != 2.5  # not a fixed mid-scale value


def test_venue_has_separate_home_and_away_averages():
    store = store_of(league())
    b = form_benchmark(store, 39, 2026, CUT, "venue", CFG)
    home, _ = _expected(store, range(1, 15), "home")
    away, _ = _expected(store, range(1, 15), "away")
    assert b["home"]["average"] == pytest.approx(home) and b["away"]["average"] == pytest.approx(
        away
    )
    assert b["home"]["average"] > b["away"]["average"]  # home sides never lose here


def test_point_in_time_no_future_matches_and_fixture_excluded():
    ms = league()
    store = store_of(ms)
    before = form_benchmark(store, 39, 2026, CUT, "overall", CFG)
    later = store_of(ms + [_m(90_000 + i, 61 + i, 39, 2026, 1, 2, 0, 9) for i in range(5)])
    assert form_benchmark(later, 39, 2026, CUT, "overall", CFG) == before
    # a match kicking off exactly at the cutoff (the fixture itself) is not used
    at_cut = store_of(ms + [_m(99_999, 60, 39, 2026, 3, 4, 0, 9)])
    assert form_benchmark(at_cut, 39, 2026, CUT, "overall", CFG) == before


def test_membership_is_point_in_time_and_competition_specific():
    ms = league()
    ms += league(n_teams=6, comp=40)  # teams 1..6 in the Championship too
    ms += [_m(70_000 + i, -200 + i, 39, 2025, 500, 501 + i, 1, 0) for i in range(6)]  # relegated
    ms += [_m(80_000 + i, i, 40, 2026, 600, 601 + i, 1, 0) for i in range(6)]  # other comp only
    store = store_of(ms)
    members = league_members(store, 39, 2026, CUT)
    assert members == set(range(1, 15))  # neither team 500 (last season) nor 600 (other comp)
    # a team only counts once it has played this season, before the cutoff
    assert league_members(store, 39, 2026, T) == set()


def test_promoted_team_window_uses_other_division_history_like_production():
    ms = league()
    ms += [_m(60_000 + i, -100 + i, 40, 2025, 77, 700 + i, 3, 0) for i in range(5)]  # tier 2
    ms.append(_m(61_000, 50, 39, 2026, 77, 1, 0, 1))  # one top-flight match this season
    store = store_of(ms)
    b = form_benchmark(store, 39, 2026, CUT, "overall", CFG)
    assert b["members"] == 15 and b["overall"]["teams"] == 15  # 77 included, full window
    w = store.team_window(77, CUT, None, 5)
    assert {x.match.competition_id for x in w} == {39, 40}
    avg, _ = _expected(store, list(range(1, 15)) + [77], None)
    assert b["overall"]["average"] == pytest.approx(avg)


def test_short_windows_excluded_not_zero_and_minimum_rules():
    # 14 teams, 6 matches total: nobody has five matches -> unavailable, nothing averaged
    few = store_of([_m(i, i, 39, 2026, 2 * i + 1, 2 * i + 2, 1, 0) for i in range(6)])
    b = form_benchmark(few, 39, 2026, CUT, "overall", CFG)
    assert not b["available"] and b["overall"]["teams"] == 0
    assert b["overall"]["average"] is None and b["overall"]["display"] is None
    # 14-team league: available at the default 12-team / 80% rule
    store = store_of(league())
    assert form_benchmark(store, 39, 2026, CUT, "overall", CFG)["available"]
    # thresholds are configurable
    strict = ScreenerConfig(form_benchmark_min_teams=15)
    assert not form_benchmark(store, 39, 2026, CUT, "overall", strict)["available"]
    # members without a full window lower the share: 14 full + 6 new teams with 1 match
    extra = league() + [_m(50_000 + i, 59, 39, 2026, 200 + i, 300 + i, 1, 0) for i in range(3)]
    b = form_benchmark(store_of(extra), 39, 2026, CUT, "overall", CFG)
    assert b["members"] == 20 and b["overall"]["teams"] == 14
    assert not b["available"]  # 14 / 20 = 70% < 80%


def test_benchmark_in_compute_fixture_and_teams_with_few_matches():
    ms = league() + [_m(51_000, 59, 39, 2026, 900, 1, 0, 0)]  # team 900: one match
    store = store_of(ms)
    fx = SimpleNamespace(
        id=1,
        competition_id=39,
        season=2026,
        home_team_id=900,
        away_team_id=2,
        kickoff_utc=CUT,
    )
    r = compute_fixture(store, fx, CUT, "overall")
    bench = r["match_result"]["league_benchmark"]
    assert bench["available"] and bench["overall"]["teams"] == 14  # 900 not averaged
    assert r["teams"]["home"]["form"]["score"] is not None  # its own score is unchanged
    assert r["config"]["form_benchmark_min_teams"] == 12


def test_unrounded_comparison_and_tolerance():
    bench = {"available": True, "basis": "overall", "overall": {"average": 2.4083333333333}}
    assert form_comparison(2.41, bench, "overall") == "above"  # both display as 2.41
    assert form_comparison(2.4083, bench, "overall") == "below"
    exact = {"available": True, "basis": "overall", "overall": {"average": float(Fraction(29, 12))}}
    assert form_comparison(float(Fraction(58, 24)), exact, "overall") == "equal"
    assert form_comparison(float(Fraction(29, 12)) + 1e-12, exact, "overall") == "equal"
    assert form_comparison(None, exact, "overall") is None
    assert form_comparison(3.0, {"available": False}, "overall") is None
    venue = {
        "available": True,
        "basis": "venue",
        "home": {"average": 2.7},
        "away": {"average": 2.0},
    }
    assert form_comparison(2.5, venue, "home") == "below"
    assert form_comparison(2.5, venue, "away") == "above"  # like with like


# --------------------------------------------------------------------- display
def _card(basis):
    store = store_of(league())
    fx = SimpleNamespace(
        id=1,
        competition_id=39,
        season=2026,
        home_team_id=1,
        away_team_id=14,
        kickoff_utc=CUT,
    )
    r = compute_fixture(store, fx, CUT, basis)
    return r, analysis_card(r, "1X2")


def _states(card):
    return [
        c.className.split()[1]
        for c in _find(card, lambda c: str(getattr(c, "className", "")).startswith("league-cmp"))
    ]


def test_cards_show_indicator_and_benchmark_overall():
    r, card = _card("overall")
    text = _text(card)
    bench = r["match_result"]["league_benchmark"]
    assert f"{bench['overall']['display']} out of 5" in text
    assert "EPL 2026/27 — 14 teams evaluated" in text
    exp = [
        form_comparison(r["teams"][s]["form"]["score"], bench, "overall") for s in ("home", "away")
    ]
    assert _states(card) == exp and set(exp) <= {"above", "below", "equal"}
    # spot-check against the raw numbers (unrounded)
    for s, state in zip(("home", "away"), exp, strict=True):
        score = r["teams"][s]["form"]["score"]
        assert (score > bench["overall"]["average"]) == (state == "above")
    assert "/ 5" not in text


def test_cards_venue_compare_home_and_away_averages():
    r, card = _card("venue")
    b = r["match_result"]["league_benchmark"]
    text = _text(card)
    assert f"Home: {b['home']['display']} out of 5" in text
    assert f"Away: {b['away']['display']} out of 5" in text
    exp = [form_comparison(r["teams"][s]["form"]["score"], b, s) for s in ("home", "away")]
    assert _states(card) == exp
    explain = _text(calculation_section(r, "1X2"))
    assert "home team is compared with the average of every team's home Form Score" in explain
    assert "full five-match window" in explain and "not the probability of winning" in explain


def test_unavailable_benchmark_omits_indicator_and_explains(data):
    r, ov, official = data.detail(EPL_FIX, "overall")
    assert r["match_result"]["league_benchmark"]["available"] is False  # tiny test league
    card = analysis_card(r, "1X2")
    assert _states(card) == []
    text = _text(card)
    assert "Not enough league data yet" in text and "2.5 out of 5" not in text
    assert "no 2.5 or zero is substituted" in _text(calculation_section(r, "1X2"))


@pytest.mark.parametrize("market", ["1X2", "BTTS", "OU25"])
def test_simplified_cards_and_out_of_5_everywhere(data, market):
    for fid in (EPL_FIX, PSL_FIX):
        r, ov, official = data.detail(fid, "venue")
        d = render_detail(r, ov, official, market, data)
        text = _text(d)
        assert "/ 5" not in text and "/5" not in text
        tiles = _find(d, lambda c: getattr(c, "className", "") == "tiles")[0]
        t = _text(tiles)
        assert "current-season matches" not in t
        assert "Historical performance score" not in t
        assert "No BTTS in" not in t and "Under 2.5 in" not in t
        if market == "1X2":
            assert "out of 5" in t and " matches" not in t


def test_benchmark_block_layout_separator_and_source_line():
    r, card = _card("venue")
    block = _find(card, lambda c: "form-benchmark" in str(getattr(c, "className", "")))[0]
    values = _find(block, lambda c: getattr(c, "className", "") == "bench-values")[0]
    parts = [getattr(c, "className", "") for c in values.children]
    assert parts == ["bench-value", "bench-sep", "bench-value"]  # Home | Away
    assert _text(values).replace(" ", "").count("|") == 1
    source = _find(block, lambda c: "bench-source" in str(getattr(c, "className", "")))[0]
    assert _text(source) == "EPL 2026/27 — 14 teams evaluated"
    assert "out of 5" not in _text(source)
    _, overall = _card("overall")
    block = _find(overall, lambda c: "form-benchmark" in str(getattr(c, "className", "")))[0]
    values = _find(block, lambda c: getattr(c, "className", "") == "bench-values")[0]
    assert [getattr(c, "className", "") for c in values.children] == ["bench-value"]  # no sep
    css = (
        __import__("pathlib").Path(__file__).parents[1] / "src/diski9/app/assets/style.css"
    ).read_text()
    assert ".bench-sep { display: none; }" in css  # hidden when stacked on narrow screens
