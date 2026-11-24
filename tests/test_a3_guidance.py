"""Scenario A3, Checkpoint 3: user guidance, the high-risk underdog warning and the
educational popovers (presentation only: no calculation, eligibility, scoring or
configuration changes)."""

from __future__ import annotations

import json
import math
import types
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from diski9.app import education, lab, views
from diski9.app.challenge import components as c
from diski9.app.challenge import pages
from diski9.app.challenge.service import DEMO_POOL, DEMO_ROUND_ID, ChallengeService, key_str
from diski9.app.data import LEAGUE_SHORT
from diski9.challenge.config import A3_432_V1, BROAD60_432_V1, DEFAULT_CONFIG
from diski9.challenge.guidance import (
    HIGH_RISK_UNDERDOG,
    high_risk_selections,
    is_high_risk_underdog,
)
from diski9.challenge.roundsheet import snapshot_from_research_pool
from diski9.challenge.structured import make_outcome
from diski9.odds.implied import normalise
from diski9.odds.value import edge_pp, expected_value

POOL = json.loads(Path(DEMO_POOL).read_text())
down, up = (lambda x: math.nextafter(x, 0.0)), (lambda x: math.nextafter(x, 1.0))


def walk(node):
    yield node
    kids = getattr(node, "children", None)
    if kids is None:
        return
    for k in kids if isinstance(kids, list | tuple) else [kids]:
        if k is not None and not isinstance(k, str | int | float):
            yield from walk(k)


def classes(node, cls):
    return [n for n in walk(node) if cls in (getattr(n, "className", "") or "").split()]


def text(node) -> str:
    out = []
    for n in walk(node):
        kids = getattr(n, "children", None)
        for k in kids if isinstance(kids, list | tuple) else [kids]:
            if isinstance(k, str):
                out.append(k)
    return " ".join(out)


# ======================================================================= copy
APPROVED = {
    "market_probability": "The market’s estimated chance of an outcome occurring, after "
    "adjusting for the bookmaker’s margin.",
    "model_probability": "Diski 9’s estimated chance of an outcome occurring, based on its "
    "statistical football model. This is an estimate, not a guarantee.",
    "edge": "The difference between your estimated probability (using Diski 9’s model or your "
    "own adjusted view) and the market probability, measured in percentage points. A positive "
    "estimated edge does not prove a genuine advantage.",
    "ev": "The estimated average net return per unit staked over many similar selections, using "
    "the estimated probability and Diski 9’s reference odds. Positive estimated EV does not "
    "guarantee a profit.",
}


def test_glossary_holds_the_approved_definitions():
    for key, wording in APPROVED.items():
        assert education.short(key) == wording
    assert education.GLOSSARY["model_probability"]["title"] == "Goal Model Probability (D9)"


def test_approved_guidance_and_warning_wording():
    assert education.GUIDANCE_TITLE == "Understanding Model Probabilities"
    assert education.GUIDANCE_P1.startswith(
        "Goal Model probabilities are estimates, not guarantees."
    )
    assert "genuine advantage (Edge) or positive Expected Value (EV)" in education.GUIDANCE_P1
    assert "explore the Match Lab for additional factors" in education.GUIDANCE_P2
    assert "review the match factors on this page" in education.GUIDANCE_P2_LAB
    assert education.UNDERDOG_TITLE == "High-Risk Underdog Selection"
    assert "(at least 10% but below 20%)" in education.UNDERDOG_P1
    assert "often assigned higher probabilities to underdogs" in education.UNDERDOG_P2
    assert "may be overestimating their chances" in education.UNDERDOG_P2
    assert "genuine Edge or positive Expected Value (EV)" in education.UNDERDOG_P3


def test_glossary_is_the_single_source_for_longer_explanations():
    assert education.long("model_probability") == lab.MODEL_PROB_HELP
    assert education.long("market_probability") == lab.MARKET_PROB_HELP
    assert education.long("edge") == lab.EDGE_HELP
    assert education.long("ev") == lab.EV_HELP
    glossary_list = text(lab.value_glossary())
    for k in ("model_probability", "market_probability", "edge", "ev"):
        assert education.long(k) in glossary_list
    assert views.info is education.info  # the existing popover, re-exported


# ------------------------------------------------- explanations match the calculations
def test_market_probability_is_proportional_margin_removal():
    probs = normalise({"H": "2.00", "D": "3.40", "A": "4.00"}, {"H", "D", "A"})
    raw = {"H": 1 / 2.0, "D": 1 / 3.4, "A": 1 / 4.0}
    total = sum(raw.values())
    assert total > 1  # the bookmaker margin
    for k in raw:
        assert float(probs[k]) == pytest.approx(raw[k] / total, abs=1e-12)
    assert float(sum(probs.values())) == pytest.approx(1.0)  # "after adjusting for the margin"


def test_edge_is_percentage_points_and_ev_is_per_unit_staked_with_reference_odds():
    assert edge_pp(0.55, 0.48) == pytest.approx(7.0)  # "measured in percentage points"
    assert expected_value(0.55, Decimal("2.10")) == pytest.approx(0.155)  # p x odds - 1
    # EV uses the displayed reference odds (with margin), not the margin-free market price
    assert expected_value(0.476, Decimal("2.10")) == pytest.approx(0.476 * 2.10 - 1)
    assert expected_value(0.5, None) is None and expected_value(0.5, "1.00") is None


# ===================================================================== components
def test_term_renders_one_accessible_popover():
    t = education.term("Edge", "edge")
    det = classes(t, "term-info")
    assert len(det) == 1 and type(det[0]).__name__ == "Details"  # native disclosure
    summary = det[0].children[0]
    assert type(summary).__name__ == "Summary"
    assert getattr(summary, "aria-label") == "What is Edge?"
    assert education.short("edge") in text(det[0])
    both = education.term("Rank by", "edge", "ev")
    assert education.short("edge") in text(both) and education.short("ev") in text(both)


# =============================================================== underdog warning
AT = POOL and snapshot_from_research_pool(POOL, DEMO_ROUND_ID, LEAGUE_SHORT, A3_432_V1).snapshot_at


def _o(p, model=None, fid=1, outcome="AWAY", seen=None):
    return make_outcome(fid, "1X2", outcome, p, Decimal(str(round(0.95 / p, 2))),
                        model if model is not None else p, 5, seen or AT, 39)  # fmt: skip


@pytest.mark.parametrize(
    ("p", "expected"),
    [(down(0.10), False), (0.10, True), (up(0.10), True), (0.15, True),
     (down(0.20), True), (0.20, False), (up(0.20), False), (0.35, False)],
)  # fmt: skip
def test_warning_boundaries_at_adjacent_floats(p, expected):
    assert HIGH_RISK_UNDERDOG.contains(p) is expected
    assert is_high_risk_underdog(_o(p), AT, A3_432_V1) is expected


def test_warning_uses_the_market_probability_not_the_goal_model():
    assert is_high_risk_underdog(_o(0.15, model=0.40), AT, A3_432_V1)  # market 15%
    assert not is_high_risk_underdog(_o(0.25, model=0.12), AT, A3_432_V1)  # market 25%


def test_warning_needs_eligibility_in_the_rounds_configuration():
    assert not is_high_risk_underdog(_o(0.15), AT, BROAD60_432_V1)  # ineligible under v1
    stale = _o(0.15, seen=AT - timedelta(days=2))  # quotes too old: not eligible
    assert not is_high_risk_underdog(stale, AT, A3_432_V1)


def test_selected_outcomes_only_each_once_and_never_fixture_level():
    risky = _o(0.15, fid=7, outcome="AWAY")
    safe_same_fixture = _o(0.70, fid=7, outcome="HOME")
    assert high_risk_selections([safe_same_fixture], AT, A3_432_V1) == []
    assert high_risk_selections([risky, risky], AT, A3_432_V1) == [risky]


# ----------------------------------------------------------- application views
def _service(snap):
    data = types.SimpleNamespace(clock=lambda: snap.snapshot_at + timedelta(hours=1), engine=None)
    return ChallengeService(data=data)


@pytest.fixture(scope="module")
def snaps():
    v1 = snapshot_from_research_pool(POOL, DEMO_ROUND_ID, LEAGUE_SHORT, BROAD60_432_V1)
    a3 = snapshot_from_research_pool(POOL, DEMO_ROUND_ID, LEAGUE_SHORT, A3_432_V1)
    return v1, a3


def a3_keys(snap, n_risky=2, only=None):
    """A valid A3 portfolio with ``n_risky`` Challenger picks at 10%-20% (optionally only
    from the fixture ids in ``only``, e.g. the builder's first page)."""
    need = {"A": 4, "B": 3, "C": 2}
    picks, used = {"A": [], "B": [], "C": []}, set()
    outcomes = [o for o in snap.outcomes if only is None or o.fixture_id in only]
    for o in outcomes:  # the high-risk picks first
        if (
            len(picks["C"]) < n_risky
            and HIGH_RISK_UNDERDOG.contains(o.market_probability)
            and o.fixture_id not in used
        ):
            picks["C"].append(o)
            used.add(o.fixture_id)
    for o in outcomes:
        b = A3_432_V1.classify(o.market_probability)
        if b is None or o.fixture_id in used or len(picks[b]) >= need[b]:
            continue
        if b == "C" and HIGH_RISK_UNDERDOG.contains(o.market_probability):
            continue
        picks[b].append(o)
        used.add(o.fixture_id)
    chosen = [o for b in "ABC" for o in picks[b]]
    assert len(chosen) == 9
    return [key_str(o.key) for o in chosen], picks["C"][:n_risky]


def test_tracker_shows_one_warning_and_follows_selection_and_deselection(snaps):
    _, a3 = snaps
    svc = _service(a3)
    keys, risky = a3_keys(a3, 2)
    t = pages.tracker_view(svc, a3, keys, False)
    panels = classes(t, "ch-risk-panel")
    assert len(panels) == 1  # two qualifying picks: one panel, not two
    assert "Includes 2 high-risk underdogs" in text(panels[0])
    assert education.UNDERDOG_P2 in text(panels[0])
    hrefs = [n.href for n in walk(panels[0]) if getattr(n, "href", None)]
    assert sorted(hrefs) == sorted(f"/?fixture={o.fixture_id}" for o in risky)  # Match Lab
    one = [k for k in keys if k != key_str(risky[0].key)]
    t1 = pages.tracker_view(svc, a3, one, False)
    assert "Includes a high-risk underdog" in text(classes(t1, "ch-risk-panel")[0])
    none = [k for k in one if k != key_str(risky[1].key)]
    assert classes(pages.tracker_view(svc, a3, none, False), "ch-risk-panel") == []


def test_no_warning_on_a_v1_round(snaps):
    v1, a3 = snaps
    keys, risky = a3_keys(a3, 1)
    # under v1 the 10-20% outcome is not eligible: no tag, no panel
    assert classes(pages.tracker_view(_service(v1), v1, keys, False), "ch-risk-panel") == []
    o = risky[0]
    btn = c.outcome_button(o, None, None, False, config=v1.config)
    assert classes(btn, "ch-risk-tag") == []


def test_review_reminder_once_with_the_full_text_collapsed(snaps):
    _, a3 = snaps
    svc = _service(a3)
    keys, _ = a3_keys(a3, 2)
    state = dict(pages.DEFAULT_STATE, mode="demo", fp=a3.fingerprint, selections=keys)
    r = pages.review(svc, a3, keys, svc.availability("demo"), state, lambda d, f="": "")
    panels = classes(r, "ch-risk-panel")
    assert len(panels) == 1 and "ch-risk-review" in panels[0].className
    details = [n for n in walk(panels[0]) if type(n).__name__ == "Details"]
    assert details and not getattr(details[0], "open", False)  # collapsed by default
    # no forced acknowledgement: the submit control has no extra gating element
    assert not [n for n in walk(r) if "acknowledge" in str(getattr(n, "id", "")).lower()]


def test_outcome_card_tag_only_for_eligible_high_risk_outcomes(snaps):
    _, a3 = snaps
    risky = next(o for o in a3.outcomes if HIGH_RISK_UNDERDOG.contains(o.market_probability))
    safe = next(o for o in a3.outcomes if 0.30 <= o.market_probability < 0.40)
    rb = c.outcome_button(risky, "C", None, False, config=a3.config)
    sb = c.outcome_button(safe, "C", None, False, config=a3.config)
    assert len(classes(rb, "ch-risk-tag")) == 1 and education.UNDERDOG_SHORT in rb.title
    assert classes(sb, "ch-risk-tag") == [] and education.UNDERDOG_SHORT not in sb.title
    _, _, title = c.outcome_state(risky, "C", None, False, config=a3.config)
    assert education.UNDERDOG_SHORT in title  # in-place updates keep the explanation


# ------------------------------------------------------ one explanation per view
def test_builder_legend_terms_and_guidance_once(snaps):
    _, a3 = snaps
    svc = _service(a3)
    state = dict(pages.DEFAULT_STATE, mode="demo", fp=a3.fingerprint, selections=[])
    b = pages.builder(svc, a3, [], svc.availability("demo"), {"source": "market"},
                      lambda d, f="": "", None, state)  # fmt: skip
    assert len(classes(b, "model-guidance")) == 1
    legend = classes(b, "ch-legend")[0]
    assert len(classes(legend, "term-info")) == 2  # Mkt and D9, once each
    assert education.GUIDANCE_P2 in text(classes(b, "model-guidance")[0])


def test_review_headers_have_one_term_each(snaps):
    _, a3 = snaps
    head = pages.picks_table([])
    assert len(classes(head, "term-info")) == 2  # Market and Diski 9


def test_match_lab_comparison_has_four_terms_and_lab_guidance():
    # the rendered table is checked in tests/test_a3_guidance_browser.py
    src = Path(lab.__file__).read_text()
    assert src.count('education.term("Model", "model_probability")') == 1
    assert src.count('education.model_guidance("lab")') == 1
    g = education.model_guidance("lab")
    assert education.GUIDANCE_P2_LAB in text(g) and education.GUIDANCE_P2 not in text(g)


def test_configuration_and_fingerprints_unchanged():
    assert DEFAULT_CONFIG is BROAD60_432_V1
    assert BROAD60_432_V1.fingerprint().startswith("b8cb7c0372e6")
    assert A3_432_V1.fingerprint().startswith("91dba48a002a")
    assert replace(A3_432_V1) == A3_432_V1
