"""Phase 7 CP3: rendering of My Challenge > Achievements and the History-detail badge
chips from backend objects (pure; no database). The backend rules are covered by
``test_achievements.py`` and the PostgreSQL suite; here we check that the UI only
presents what the service derived, never misleading zeros or Beginner on an error,
that guests get nothing, and that development visibility comes from the server's
backend setting."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from plotly.utils import PlotlyJSONEncoder

from diski9.app.challenge import achievements_ui as aui
from diski9.app.challenge import history_ui as hu
from diski9.app.challenge import persist
from diski9.backend.services import achievements as ac

F, B, C = ac.Badge.FOUNDATION_FUNDI, ac.Badge.BALANCED_BRAWLER, ac.Badge.CHALLENGER_CHAMP
GG, BT, DD = ac.Badge.GOALS_GURU, ac.Badge.BTTS_BONANZA, ac.Badge.DRAW_DYNAMO


def text(component) -> str:
    return json.dumps(component, cls=PlotlyJSONEncoder, ensure_ascii=False)


def result(*counts, rounds=5, stream="beta") -> ac.Achievements:
    by = dict(zip(ac.BADGES, counts, strict=True))
    return ac.Achievements(stream=stream, counts=by, total=sum(counts), level=ac.level_for(by),
                           progress=ac.progress_for(by), eligible_rounds=rounds, rounds=())  # fmt: skip


@pytest.fixture
def signed_in(monkeypatch):
    """A backend (server-side ``show_development``) and a signed-in participant."""
    backend = SimpleNamespace(engine=object(), show_development=False)
    me = SimpleNamespace(is_authenticated=True, user_id=uuid4())
    monkeypatch.setattr(persist, "backend_of", lambda service: backend)
    monkeypatch.setattr(persist, "participant", lambda service: me)
    return backend, me


# ------------------------------------------------------------------ the view
def test_tabs_offer_achievements_as_a_third_segment():
    opts = hu.tabs().options
    assert [o["value"] for o in opts] == ["current", "history", "achievements"]


def test_beginner_with_no_badges_is_an_honest_empty_state():
    t = text(aui.view(result(0, 0, 0, 0, 0, 0, rounds=0)))
    assert "Beginner" in t and "Next: Semi-Pro" in t and "You have not earned a badge yet" in t
    assert "0 of 6 categories" in t
    assert t.count("0 of 1 for Semi-Pro") == 6


def test_beginner_names_the_missing_categories():
    t = text(aui.view(result(3, 1, 0, 2, 0, 1)))
    assert "Beginner" in t and "4 of 6 categories have 1 or more" in t
    assert "Still needed: Challenger Champ, BTTS Bonanza." in t
    assert t.count("Semi-Pro target met") == 4 and "You have not earned" not in t


def test_semi_pro_shows_progress_to_pro_per_category():
    t = text(aui.view(result(5, 3, 1, 4, 2, 1)))
    assert "Semi-Pro" in t and "Next: Pro" in t and "16" in t
    assert "Still needed: Challenger Champ, BTTS Bonanza, Draw Dynamo." in t
    assert "2 of 3 for Pro" in t and t.count("1 of 3 for Pro") == 2
    assert t.count("Pro target met") == 3


def test_pro_keeps_counting_with_no_further_level():
    t = text(aui.view(result(9, 6, 3, 5, 4, 3)))
    assert "Top level reached" in t and "no further level to unlock" in t
    assert t.count("Pro target met") == 6 and "Next:" not in t


def test_every_card_and_the_every_category_rule_and_wording():
    t = text(aui.view(result(1, 1, 1, 1, 1, 1)))
    for name, *_ in aui.BADGE_INFO.values():
        assert name in t
    assert "Bucket achievements" in t and "Market achievements" in t
    assert "at least 1 of each of the six badges for Semi-Pro" in t
    assert "at least 3 of each for Pro" in t  # thresholds read from the backend
    assert "not a rating of skill" in t and "skill rating" not in t


def test_level_and_progress_come_from_the_backend_object_not_recomputed():
    # an object whose level disagrees with its counts is presented as given
    a = result(0, 0, 0, 0, 0, 0)
    forced = ac.Achievements(**{**a.__dict__, "level": ac.Level.PRO,
                                "progress": ac.Progress(None, None, 6, ())})  # fmt: skip
    t = text(aui.view(forced))
    assert '"Pro"' in t and "Top level reached" in t and "Beginner" not in t


# ------------------------------------------------------------------ data access
def test_body_uses_the_server_backend_setting_and_the_principal(signed_in, monkeypatch):
    backend, me = signed_in
    seen = {}

    def fake(engine, viewer, *, stream, include_development):
        seen.update(engine=engine, viewer=viewer, stream=stream, dev=include_development)
        return result(1, 1, 1, 1, 1, 1, stream=stream)

    monkeypatch.setattr(ac, "my_achievements", fake)
    backend.show_development = True
    aui.body(None, "development")
    assert seen == {"engine": backend.engine, "viewer": me, "stream": "development", "dev": True}
    backend.show_development = False
    aui.body(None, "beta")
    assert seen["dev"] is False  # never a browser value


def test_integrity_error_shows_unavailable_never_beginner_or_zero(signed_in, monkeypatch):
    def broken(*a, **k):
        raise ac.AchievementIntegrityError(
            "Achievements are temporarily unavailable.",
            details={"reason": "secret detail", "round": "R1"},
        )

    monkeypatch.setattr(ac, "my_achievements", broken)
    t = text(aui.body(None, "beta"))
    assert "Achievements unavailable" in t
    for word in ("Beginner", "Semi-Pro", "earned", "secret detail", "R1"):
        assert word not in t


def test_guests_and_no_database_get_no_achievement_data(monkeypatch):
    called = []
    monkeypatch.setattr(ac, "my_achievements", lambda *a, **k: called.append(1))
    monkeypatch.setattr(
        persist, "backend_of", lambda s: SimpleNamespace(engine=None, show_development=False)
    )
    monkeypatch.setattr(persist, "participant", lambda s: None)
    assert "Sign in to see your achievements" in text(aui.section(None, {}))
    assert "Sign in to see your achievements" in text(aui.body(None, "beta"))
    monkeypatch.setattr(persist, "backend_of", lambda s: None)
    assert "need the competition database" in text(aui.section(None, {}))
    assert not called


# ------------------------------------------------------------------ History chips
def test_round_chips_show_only_the_published_rounds_badges(signed_in, monkeypatch):
    backend, me = signed_in
    rid = uuid4()
    seen = {}

    def fake(engine, viewer, round_id, *, stream, include_development):
        seen.update(viewer=viewer, round_id=round_id, dev=include_development)
        return ac.RoundBadges(round_id, "R1", None, 2, (F, C, DD))

    monkeypatch.setattr(ac, "my_round_badges", fake)
    t = text(aui.round_chips(None, rid, "beta"))
    assert "Badges earned:" in t and "Foundation Fundi" in t and "Draw Dynamo" in t
    assert "Balanced Brawler" not in t
    assert seen == {"viewer": me, "round_id": rid, "dev": False}


def test_round_chips_are_absent_for_ineligible_or_badgeless_rounds(signed_in, monkeypatch):
    monkeypatch.setattr(ac, "my_round_badges", lambda *a, **k: None)
    assert aui.round_chips(None, uuid4(), "beta") is None
    monkeypatch.setattr(ac, "my_round_badges",
                        lambda *a, **k: ac.RoundBadges(uuid4(), "R", None, 1, ()))  # fmt: skip
    assert aui.round_chips(None, uuid4(), "beta") is None


def test_round_chips_integrity_error_is_a_quiet_unavailable_line(signed_in, monkeypatch):
    def broken(*a, **k):
        raise ac.AchievementIntegrityError("x", details={"reason": "internal"})

    monkeypatch.setattr(ac, "my_round_badges", broken)
    t = text(aui.round_chips(None, uuid4(), "beta"))
    assert "temporarily unavailable" in t and "internal" not in t
