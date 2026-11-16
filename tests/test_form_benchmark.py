# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Engine 2.4.0: current-season eight-match Form Score, the current-season league
average, display-only venue context and the Match Result team cards."""

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
    ENGINE_VERSION,
    Match,
    MatchStore,
    ScreenerConfig,
    compute_fixture,
    form_benchmark,
    league_members,
)

from .test_app import EPL_FIX, PSL_FIX, _find, _text, data, populated  # noqa: F401

T = datetime(2026, 8, 15, 15, tzinfo=UTC)
CFG = ScreenerConfig()
F = Fraction


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


def store_of(ms):
    names = {i: f"T{i}" for i in range(1, 1000)}
    return MatchStore.from_matches(ms, names, {39: "EPL", 40: "Ch"})


def rounds(n_rounds, n_teams=16, comp=39, season=2026, start=0.0):
    """Round-robin style rounds: in round r team i hosts team i + n/2 (rotated)."""
    ms, fid = [], 100_000 * (comp - 38) + 10_000 * (season - 2024)
    half = n_teams // 2
    for r in range(n_rounds):
        for i in range(half):
            h = 1 + (i + r) % n_teams
            a = 1 + (i + half + r) % n_teams
            score = (2, 1) if (h + r) % 3 == 0 else (1, 1) if (h + r) % 3 == 1 else (0, 1)
            ms.append(_m(fid, start + r * 7 + i * 0.01, comp, season, h, a, *score))
            fid += 1
    return ms


def fixture(home, away, days, comp=39, season=2026):
    return SimpleNamespace(
        id=1,
        competition_id=comp,
        season=season,
        home_team_id=home,
        away_team_id=away,
        kickoff_utc=T + timedelta(days=days),
    )


def test_engine_version():
    assert ENGINE_VERSION == "2.4.0" and CFG.form_window == 8


# ------------------------------------------------------------ team scores
@pytest.mark.parametrize("n", [1, 3, 5, 8])
def test_team_scores_normalised_by_matches_played(n):
    ms = [_m(i, i, 39, 2026, 1, 50 + i, 2, 1) for i in range(n)]  # n wins 2-1
    ms += [_m(500 + i, -300 + i, 39, 2025, 1, 60 + i, 0, 5) for i in range(8)]  # last season
    ms += [_m(600 + i, -200 + i, 40, 2026, 1, 70 + i, 0, 5) for i in range(8)]  # other division
    store = store_of(ms)
    r = compute_fixture(store, fixture(1, 2, 30), T + timedelta(days=30))
    form = r["teams"]["home"]["form"]
    b = form["breakdown"]
    assert b["matches"] == n and b["max_points"] == 3 * n  # current season only
    assert b["gd_cap"] == pytest.approx(1.8 * n)
    # n wins by one goal: 2.5 x 3n/3n + 2.5 x (n + 1.8n)/(3.6n) = 2.5 + 2.5 x 2.8/3.6
    assert form["score"] == pytest.approx(2.5 + 2.5 * 2.8 / 3.6)  # same for every n
    assert {m["season"] for m in form["matches"]} == {2026}
    assert {m["competition"] for m in form["matches"]} == {"EPL"}
    assert form["sample"]["limited_data"] is (n < 8)


def test_first_fixture_of_the_season_is_unavailable_not_zero():
    ms = [_m(i, -300 + i, 39, 2025, 1, 2, 3, 0) for i in range(10)]  # only last season
    store = store_of(ms)
    r = compute_fixture(store, fixture(1, 2, 0), T)
    for side in ("home", "away"):
        f = r["teams"][side]["form"]
        assert f["score"] is None and f["display"] is None and f["sample"]["matches"] == 0
        assert f["venue_context"]["available"] is False and f["venue_context"]["matches"] == 0
    assert r["match_result"]["form_difference"] is None
    bench = r["match_result"]["league_benchmark"]
    assert bench["available"] is False and bench["teams"] == 0 and bench["average"] is None


def test_last_eight_only_and_point_in_time():
    ms = [_m(i, i, 39, 2026, 1, 50 + i, 1 if i < 4 else 0, 0 if i < 4 else 1) for i in range(12)]
    store = store_of(ms)
    r = compute_fixture(store, fixture(1, 2, 30), T + timedelta(days=30))
    assert r["teams"]["home"]["form"]["sequence"] == "L-L-L-L-L-L-L-L"  # newest eight
    later = store_of(ms + [_m(900 + i, 31 + i, 39, 2026, 1, 80 + i, 9, 0) for i in range(5)])
    r2 = compute_fixture(later, fixture(1, 2, 30), T + timedelta(days=60))
    assert r2["teams"]["home"]["form"] == r["teams"]["home"]["form"]
    # a match kicking off exactly at the cutoff (the fixture itself) is not used
    same = store_of(ms + [_m(999, 30, 39, 2026, 1, 99, 9, 0)])
    assert (
        compute_fixture(same, fixture(1, 2, 30), T + timedelta(days=30))["teams"]["home"]["form"]
        == r["teams"]["home"]["form"]
    )


# ------------------------------------------------------------ venue context
@pytest.mark.parametrize(
    "n_home,available,limited",
    [
        (0, False, False),
        (1, False, False),
        (2, True, True),
        (4, True, True),
        (5, True, False),
        (7, True, False),
    ],
)
def test_venue_context_partial_windows(n_home, available, limited):
    ms = [_m(i, i, 39, 2026, 1, 50 + i, 3, 0) for i in range(n_home)]  # home wins 3-0
    ms += [_m(100 + i, 20 + i, 39, 2026, 60 + i, 1, 1, 1) for i in range(3)]  # away draws
    store = store_of(ms)
    r = compute_fixture(store, fixture(1, 2, 40), T + timedelta(days=40))
    vc = r["teams"]["home"]["form"]["venue_context"]
    assert vc["matches"] == min(n_home, 5) and vc["side"] == "home"
    assert vc["available"] is available and vc["limited"] is limited
    if available:
        home = diski_form_score([(3, 0)] * min(n_home, 5)).score
        assert vc["difference"] == pytest.approx(float(home) - r["teams"]["home"]["form"]["score"])
    else:
        assert vc["difference"] is None
    # never changes the headline score, the league average or the Form Difference
    mr = r["match_result"]
    assert (
        mr["form_difference"] == pytest.approx((mr["home_form"] or 0) - (mr["away_form"] or 0))
        or mr["away_form"] is None
    )


def test_away_venue_context_uses_away_matches():
    ms = [_m(i, i, 39, 2026, 50 + i, 2, 0, 2) for i in range(3)]  # team 2 away wins
    ms += [_m(10 + i, 10 + i, 39, 2026, 2, 60 + i, 0, 1) for i in range(3)]  # home losses
    store = store_of(ms)
    r = compute_fixture(store, fixture(1, 2, 30), T + timedelta(days=30))
    vc = r["teams"]["away"]["form"]["venue_context"]
    assert vc["side"] == "away" and vc["matches"] == 3 and vc["limited"]
    assert vc["difference"] > 0  # away form better than overall


# --------------------------------------------------------- league average
def test_league_average_current_season_one_score_per_team():
    ms = rounds(5) + rounds(30, season=2025, start=-400)  # last season never used
    store = store_of(ms)
    cut = T + timedelta(days=40)
    b = form_benchmark(store, 39, 2026, cut, CFG)
    scores = []
    for t in sorted(league_members(store, 39, 2026, cut)):
        w = store.team_window(t, cut, None, 8, competition_id=39, season=2026)
        scores.append(diski_form_score([(x.goals_for, x.goals_against) for x in w]).score)
    assert b["available"] and b["teams"] == 16 == b["league_teams"]
    assert b["average"] == pytest.approx(float(sum(scores, F(0)) / len(scores)))
    assert b["qualified_teams"] == 16 and b["average"] != 2.5


def test_league_average_early_season_policy():
    cut = lambda r: T + timedelta(days=7 * r)  # noqa: E731  after r rounds
    # after two rounds nobody has three matches -> not shown
    two = form_benchmark(store_of(rounds(2)), 39, 2026, cut(2), CFG)
    assert not two["available"] and two["teams"] == 16 and two["qualified_teams"] == 0
    assert two["average"] is None and two["display"] is None
    # after three rounds every team has three -> shown
    three = form_benchmark(store_of(rounds(3)), 39, 2026, cut(3), CFG)
    assert three["available"] and three["qualified_teams"] == 16
    # coverage is measured against the season's team list (schedule), not just teams
    # that have played: 14 of 16 teams with three matches is 87.5%, 12 of 16 is 75%
    ms = [m for m in rounds(3) if not ({m.home_id, m.away_id} & {1, 9})]
    store = store_of(ms)
    store.season_teams[(39, 2026)] = set(range(1, 17))
    b = form_benchmark(store, 39, 2026, cut(3), CFG)
    assert b["league_teams"] == 16 and b["teams"] < 16
    assert b["available"] is (b["qualified_teams"] / 16 >= 0.8 and b["qualified_teams"] >= 12)
    # thresholds are configurable
    strict = ScreenerConfig(form_benchmark_min_matches=4)
    assert not form_benchmark(store_of(rounds(3)), 39, 2026, cut(3), strict)["available"]


def test_league_average_excludes_other_competitions_and_teams_without_matches():
    ms = rounds(4) + rounds(4, comp=40)
    store = store_of(ms)
    store.season_teams[(39, 2026)] = set(range(1, 17)) | {700}  # 700 scheduled, not played
    b = form_benchmark(store, 39, 2026, T + timedelta(days=30), CFG)
    assert b["teams"] == 16 and b["league_teams"] == 17  # 700 counted in coverage only
    assert b["available"]  # 16 / 17 = 94% have three or more matches


def test_league_average_point_in_time():
    ms = rounds(6)
    cut = T + timedelta(days=30)
    a = form_benchmark(store_of(ms), 39, 2026, cut, CFG)
    later = ms + [_m(990_000 + i, 31 + i, 39, 2026, 1 + i, 2 + i, 9, 0) for i in range(5)]
    assert form_benchmark(store_of(later), 39, 2026, cut, CFG) == a


def test_unrounded_comparison():
    bench = {"available": True, "average": 2.4083333333333}
    assert form_comparison(2.41, bench) == "above"  # both display as 2.41
    assert form_comparison(2.4083, bench) == "below"
    exact = {"available": True, "average": float(F(29, 12))}
    assert form_comparison(float(F(58, 24)), exact) == "equal"
    assert form_comparison(None, exact) is None
    assert form_comparison(3.0, {"available": False}) is None


# ------------------------------------------------------------------ display
def _card(n_rounds=6, home=1, away=9):
    store = store_of(rounds(n_rounds))
    r = compute_fixture(store, fixture(home, away, 7 * n_rounds), T + timedelta(days=7 * n_rounds))
    return r, analysis_card(r, "1X2")


def test_cards_early_season_note_and_benchmark():
    r, card = _card(6)
    text = _text(card)
    assert "Based on 6 of 8 matches — early-season results may be volatile." in text
    assert "Early season" in text and "out of 5" in text and "/ 5" not in text
    b = r["match_result"]["league_benchmark"]
    assert f"{b['display']} out of 5" in text and "EPL 2026/27 — 16 teams evaluated" in text
    states = [
        c.className.split()[1]
        for c in _find(card, lambda c: str(getattr(c, "className", "")).startswith("league-cmp"))
    ]
    assert states == [form_comparison(r["teams"][s]["form"]["score"], b) for s in ("home", "away")]
    # a full eight-match window: no early-season note
    r8, card8 = _card(9)
    assert "early-season" not in _text(card8) and "Early season" not in _text(card8)


def test_venue_context_wording():
    r, card = _card(6)
    block = _find(card, lambda c: "venue-context" in str(getattr(c, "className", "")))[0]
    t = _text(block)
    assert t.startswith("Venue context")
    for s, where in (("home", "Home"), ("away", "Away")):
        vc = r["teams"][s]["form"]["venue_context"]
        if not vc["available"]:
            assert "Not enough venue history" in t
        elif abs(vc["difference"]) < 1e-9:
            assert f"{where} form the same as overall" in t
        else:
            word = "higher" if vc["difference"] > 0 else "lower"
            assert f"{where} form {vc['difference_display']} points {word} than overall" in t
    assert "Home Advantage" not in t


def test_venue_context_not_enough_history():
    ms = [_m(1, 0, 39, 2026, 1, 50, 1, 0)] + [_m(2, 1, 39, 2026, 60, 1, 0, 0)]
    r = compute_fixture(store_of(ms), fixture(1, 2, 10), T + timedelta(days=10))
    t = _text(analysis_card(r, "1X2"))
    assert "Not enough venue history (1 home match this season)." in t


def test_unavailable_benchmark_explained(data):
    r, ov, official = data.detail(EPL_FIX, "overall")
    card = analysis_card(r, "1X2")
    text = _text(card)
    if not r["match_result"]["league_benchmark"]["available"]:
        assert "Not enough current-season data yet" in text
        assert "no 2.5 or zero is substituted" in _text(calculation_section(r, "1X2"))


def test_calculation_text_explains_current_season_and_normalisation():
    r, _ = _card(6)
    t = _text(calculation_section(r, "1X2"))
    for phrase in (
        "last eight league matches of the current season",
        "earlier seasons and other divisions are never used",
        "Points part = 2.5 × points ÷ 3N",
        "Goal-difference part = 2.5 × (GD + 1.8N) ÷ 3.6N",
        "Venue context",
        "does not change the headline score",
    ):
        assert phrase in t, phrase


@pytest.mark.parametrize("market", ["1X2", "BTTS", "OU25"])
def test_out_of_5_everywhere_and_simplified_cards(data, market):
    for fid in (EPL_FIX, PSL_FIX):
        r, ov, official = data.detail(fid, "overall")
        d = render_detail(r, ov, official, market, data)
        assert "/ 5" not in _text(d) and "/5" not in _text(d)
