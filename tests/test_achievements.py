"""Phase 7 achievements: the pure badge rules, levels and stored-leg validation
(no database). Integration: ``tests/backend/test_backend_achievements.py``."""

from __future__ import annotations

import pytest

from diski9.backend.services.achievements import (
    BADGES,
    AchievementIntegrityError,
    Badge,
    Leg,
    Level,
    badges_for,
    level_for,
    parse_legs,
    progress_for,
)

F, B, C = Badge.FOUNDATION_FUNDI, Badge.BALANCED_BRAWLER, Badge.CHALLENGER_CHAMP
GG, BT, DD = Badge.GOALS_GURU, Badge.BTTS_BONANZA, Badge.DRAW_DYNAMO
BUCKETS = "AAAABBBCC"  # positions 0-3 Foundation, 4-6 Balanced, 7-8 Challenger


def legs(*specs, verdicts="WWWWWWWWW"):
    """Nine legs: ``specs`` = nine (market, outcome); verdicts W/L/V per position."""
    v = {"W": "won", "L": "lost", "V": "void"}
    return [Leg(i, BUCKETS[i], m, o, v[verdicts[i]]) for i, (m, o) in enumerate(specs)]


HOME, AWAY, DRAW = ("1X2", "HOME"), ("1X2", "AWAY"), ("1X2", "DRAW")
OVER, UNDER = ("OU25", "OVER_2_5"), ("OU25", "UNDER_2_5")
YES, NO = ("BTTS", "BTTS_YES"), ("BTTS", "BTTS_NO")
PLAIN = (HOME,) * 4 + (YES, NO, UNDER) + (AWAY, AWAY)


# ------------------------------------------------------------------ bucket badges
def test_perfect_buckets():
    assert badges_for(legs(*PLAIN)) == {F, B, C}
    assert badges_for(legs(*PLAIN, verdicts="LWWWWWWWW")) == {B, C}
    assert badges_for(legs(*PLAIN, verdicts="WWWWWWLWW")) == {F, C}
    assert badges_for(legs(*PLAIN, verdicts="WWWWWWWWL")) == {F, B}
    assert badges_for(legs(*PLAIN, verdicts="LLLLLLLLL")) == set()


def test_a_void_selection_never_completes_its_bucket_but_others_still_count():
    assert badges_for(legs(*PLAIN, verdicts="VWWWWWWWW")) == {B, C}
    assert badges_for(legs(*PLAIN, verdicts="WWWWWWWWV")) == {F, B}
    # a void market selection is not correct either (3 Over picks, one void)
    s = (HOME,) * 4 + (OVER, OVER, OVER) + (AWAY, AWAY)
    assert GG not in badges_for(legs(*s, verdicts="WWWWWVWWW"))


# ------------------------------------------------------------------ market badges
@pytest.mark.parametrize(
    ("specs", "verdicts", "earned"),
    [
        # Goals Guru: at least three correct Over/Under, any mix, across buckets
        ((OVER, UNDER, HOME, HOME, OVER, YES, NO, AWAY, AWAY), "WWWWWWWWW", True),
        ((OVER, UNDER, HOME, HOME, YES, YES, NO, AWAY, AWAY), "WWWWWWWWW", False),
        ((OVER, UNDER, HOME, HOME, UNDER, YES, NO, AWAY, AWAY), "WWWWLWWWW", False),
        ((UNDER, UNDER, UNDER, UNDER, OVER, OVER, OVER, OVER, OVER), "WWWLLLLLL", True),
    ],
)
def test_goals_guru(specs, verdicts, earned):
    assert (GG in badges_for(legs(*specs, verdicts=verdicts))) is earned


@pytest.mark.parametrize(
    ("specs", "verdicts", "earned"),
    [
        ((YES, NO, HOME, HOME, YES, OVER, UNDER, AWAY, AWAY), "WWWWWWWWW", True),
        ((YES, NO, HOME, HOME, OVER, OVER, UNDER, AWAY, AWAY), "WWWWWWWWW", False),
        ((YES, NO, HOME, HOME, NO, OVER, UNDER, AWAY, NO), "WWWWLWWWL", False),
        ((HOME, HOME, HOME, HOME, YES, NO, YES, NO, YES), "WWWWLWLWW", True),
    ],
)
def test_btts_bonanza(specs, verdicts, earned):
    assert (BT in badges_for(legs(*specs, verdicts=verdicts))) is earned


def test_draw_dynamo_needs_two_correct_draws():
    s = (HOME,) * 4 + (YES, NO, UNDER) + (DRAW, DRAW)
    assert DD in badges_for(legs(*s))
    assert DD not in badges_for(legs(*s, verdicts="WWWWWWWWL"))
    assert DD not in badges_for(legs(*s, verdicts="WWWWWWWVW"))
    one = (HOME,) * 4 + (YES, NO, UNDER) + (DRAW, AWAY)
    assert DD not in badges_for(legs(*one))
    # a draw outside Challenger counts the same (market badges ignore buckets)
    spread = (DRAW,) + (HOME,) * 3 + (YES, NO, UNDER) + (AWAY, DRAW)
    assert DD in badges_for(legs(*spread))


def test_several_badges_in_one_round_each_at_most_once():
    # every bucket correct plus 3 Over/Under; the Challenger draws give Draw Dynamo too
    s = (HOME, HOME, OVER, UNDER) + (OVER, YES, NO) + (DRAW, DRAW)
    got = badges_for(legs(*s))
    assert got == {F, B, C, GG, DD}
    # far above a threshold still earns one badge of that type
    many = (UNDER,) * 4 + (OVER,) * 3 + (DRAW, DRAW)
    assert badges_for(legs(*many)) == {F, B, C, GG, DD} and isinstance(got, frozenset)


# ------------------------------------------------------------------ levels
def counts(*values):
    return dict(zip(BADGES, values, strict=True))


@pytest.mark.parametrize(
    ("values", "level"),
    [
        ((0, 0, 0, 0, 0, 0), Level.BEGINNER),
        ((10, 10, 10, 10, 10, 0), Level.BEGINNER),
        ((1, 1, 1, 1, 1, 1), Level.SEMI_PRO),
        ((3, 3, 3, 3, 3, 2), Level.SEMI_PRO),
        ((3, 3, 3, 3, 3, 3), Level.PRO),
        ((40, 9, 7, 3, 5, 3), Level.PRO),  # badges keep accumulating after Pro
    ],
)
def test_levels_need_every_category(values, level):
    assert level_for(counts(*values)) is level


def test_missing_categories_count_as_zero():
    assert level_for({}) is Level.BEGINNER
    assert level_for({b: 5 for b in BADGES if b is not DD}) is Level.BEGINNER


def test_progress_names_the_categories_holding_the_user_back():
    p = progress_for(counts(2, 1, 0, 4, 0, 1))
    assert (p.next_level, p.target, p.categories_met, p.missing) == (Level.SEMI_PRO, 1, 4,
                                                                     (C, BT))  # fmt: skip
    p = progress_for(counts(3, 1, 3, 4, 5, 2))
    assert (p.next_level, p.target, p.categories_met, p.missing) == (Level.PRO, 3, 4, (B, DD))
    p = progress_for(counts(3, 3, 3, 3, 3, 3))
    assert (p.next_level, p.target, p.categories_met, p.missing) == (None, None, 6, ())


# ------------------------------------------------------------------ stored legs
def stored(n=9, override=None):
    out = []
    for i in range(n):
        leg = {"position": i, "fixture_id": 100 + i, "market": "1X2", "outcome": "HOME",
               "bucket": BUCKETS[i % 9], "odds": "1.50", "verdict": "won"}  # fmt: skip
        out.append(leg | (override or {}).get(i, {}))
    return {"legs": out, "accumulators": []}


@pytest.mark.parametrize("version", ["broad60-432-v1", "a3-432-v1"])
def test_stored_legs_validate_against_the_rounds_own_configuration(version):
    parsed = parse_legs(stored(), version)
    assert [leg.position for leg in parsed] == list(range(9))
    assert "".join(leg.bucket for leg in parsed) == BUCKETS  # frozen labels, never reclassified


def test_every_valid_market_outcome_pair_is_accepted():
    pairs = [("1X2", "HOME"), ("1X2", "DRAW"), ("1X2", "AWAY"), ("BTTS", "BTTS_YES"),
             ("BTTS", "BTTS_NO"), ("OU25", "OVER_2_5"), ("OU25", "UNDER_2_5")]  # fmt: skip
    for m, o in pairs:
        parsed = parse_legs(stored(override={0: {"market": m, "outcome": o}}), "a3-432-v1")
        assert (parsed[0].market, parsed[0].outcome) == (m, o)


def test_a_missing_field_is_refused():
    data = stored()
    del data["legs"][2]["outcome"]
    with pytest.raises(AchievementIntegrityError):
        parse_legs(data, "a3-432-v1")


@pytest.mark.parametrize(
    ("data", "version"),
    [
        (stored(8), "a3-432-v1"),  # a prediction missing
        (stored(10), "a3-432-v1"),
        (stored(override={8: {"bucket": "A"}}), "a3-432-v1"),  # buckets 5/2/2, not 4/3/2
        (stored(override={3: {"verdict": "pending"}}), "a3-432-v1"),  # never in a final result
        (stored(override={3: {"market": "AH"}}), "a3-432-v1"),
        # outcome not valid for its market
        (stored(override={3: {"market": "BTTS", "outcome": "DRAW"}}), "a3-432-v1"),
        (stored(override={3: {"market": "1X2", "outcome": "OVER_2_5"}}), "a3-432-v1"),
        (stored(override={3: {"market": "OU25", "outcome": "BTTS_YES"}}), "a3-432-v1"),
        (stored(override={3: {"outcome": "home"}}), "a3-432-v1"),  # case matters
        # missing fields and unexpected JSON types
        (stored(override={3: {"outcome": None}}), "a3-432-v1"),
        (stored(override={3: {"market": ["1X2"]}}), "a3-432-v1"),
        (stored(override={3: {"verdict": {"won": True}}}), "a3-432-v1"),
        (stored(override={3: {"bucket": 1}}), "a3-432-v1"),
        (stored(override={3: {"position": "3"}}), "a3-432-v1"),
        (stored(override={3: {"position": 3.0}}), "a3-432-v1"),
        (stored(override={1: {"position": True}}), "a3-432-v1"),
        (stored(override={3: {"position": 0}}), "a3-432-v1"),  # duplicate position
        ({"legs": [None] * 9}, "a3-432-v1"),
        ({"accumulators": []}, "a3-432-v1"),
        (None, "a3-432-v1"),
        (stored(), "unknown-v9"),  # no configuration to check against
    ],
)
def test_malformed_records_are_refused_not_counted_as_zero(data, version):
    with pytest.raises(AchievementIntegrityError) as e:
        parse_legs(data, version)
    assert e.value.code == "achievement_integrity"
    assert "temporarily unavailable" in e.value.message
