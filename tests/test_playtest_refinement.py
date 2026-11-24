"""Phase 6B.2 playtest refinements: presentation, icons and formatting."""

from __future__ import annotations

import re
from pathlib import Path

from diski9.app import icons
from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import components as comp
from diski9.app.challenge import integration
from diski9.app.challenge.service import key_str, parse_key
from diski9.challenge.config import DEFAULT_CONFIG as CFG
from diski9.challenge.structured import SelectionBlock, assess_outcome, selection_blocks

from .test_app import data, populated  # noqa: E402, F401  (fixtures)
from .test_challenge_ui import (  # noqa: F401
    _DataWithResults,
    _lab_state,
    jtext,
    snap,  # noqa: F401
    svc,
    valid_keys,
)

ROOT = Path(__file__).parents[1]
APP = ROOT / "src/diski9/app"


def _walk(node):
    yield node
    kids = getattr(node, "children", None)
    if isinstance(kids, list | tuple):
        for k in kids:
            yield from _walk(k)
    elif kids is not None and not isinstance(kids, str | int | float):
        yield from _walk(kids)


def lab_cards(panel):
    return [n for n in _walk(panel) if isinstance(getattr(n, "id", None), dict)
            and n.id.get("t") in ("labpick", "labreplace")]  # fmt: skip


# ------------------------------------------------------------- Match Lab cards
def test_match_lab_cards_offer_only_valid_replacements(svc, snap):  # noqa: F811
    fake = _DataWithResults(snap)
    keys = valid_keys(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    for k in keys:
        s, _ = cb.apply_action(svc, s, "pick", k)
    fid = parse_key(keys[0])[0]
    cards = lab_cards(integration.lab_panel(svc, fake, s, fid, {}, None))
    outs = {key_str(o.key): o for o in snap.outcomes if o.fixture_id == fid}
    assert {c.id["k"] for c in cards} == set(outs)  # all seven (or fewer) outcomes
    chosen = svc.outcomes_for(snap, keys)
    rest = [o for o in chosen if o.fixture_id != fid]
    swap = selection_blocks(rest, snap.outcomes, snap.snapshot_at, CFG)
    for card in cards:
        o = outs[card.id["k"]]
        a = assess_outcome(o, snap.snapshot_at, CFG)
        valid = a.eligible and swap.get(o.key) is None and card.id["k"] != keys[0]
        assert (card.id["t"] == "labreplace") == valid, card.id
        if card.id["t"] == "labreplace":
            assert not card.disabled and "st-replace" in card.className
            s2, flash = cb.apply_action(svc, s, cb.ACTION_OF["labreplace"], card.id["k"])
            assert flash["kind"] == "confirm" and s2["selections"] == s["selections"]
            s3, _ = cb.apply_action(svc, s, "replace", card.id["k"])
            assert card.id["k"] in s3["selections"] and keys[0] not in s3["selections"]
        elif card.id["k"] != keys[0]:
            assert card.disabled and card.title  # the reason is stated
    selected = next(c for c in cards if c.id["k"] == keys[0])
    assert "is-selected" in selected.className and not selected.disabled  # tap removes


def test_match_lab_cards_show_three_probabilities(svc, snap):  # noqa: F811
    fake = _DataWithResults(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    fid = snap.fixtures[0].fixture_id
    plain = jtext(integration.lab_panel(svc, fake, s, fid, {}, None))
    assert "Mkt " in plain and "D9 " in plain and "You = D9" in plain
    from tests.test_your_view_persistence import _frozen

    store = _frozen(snap, fid, _lab_state(0.6))  # Phase 6C.3: the frozen context
    personal = integration.personal_probabilities(fake, snap, store)
    adj = jtext(integration.lab_panel(svc, fake, s, fid, store, None))
    assert "You = D9" not in adj
    for o in snap.outcomes:
        if o.fixture_id == fid:
            assert f"You {comp.pct(personal[o.key], 1)}" in adj


def test_builder_cards_show_your_view_only_for_adjusted_matches(snap):  # noqa: F811
    o = snap.outcomes[0]
    a = assess_outcome(o, snap.snapshot_at, CFG)
    bucket = a.bucket if a.eligible else None
    off = jtext(comp.outcome_button(o, bucket, None, False, None, config=CFG))
    on = jtext(comp.outcome_button(o, bucket, None, False, 0.512, show_you=True, config=CFG))
    assert "You " not in off and "You 51.2%" in on
    assert f"Mkt {comp.pct_in_band(o.market_probability, bucket, CFG)}" in on  # Mkt always shown


def test_disabled_outcomes_explain_with_icon_and_text(snap):  # noqa: F811
    o = snap.outcomes[0]
    btn = comp.outcome_button(o, "A", SelectionBlock.BUCKET_FULL, False, config=CFG)
    assert "st-bucket_full" in btn.className and btn.disabled
    assert "Bucket full" in btn.title and "Bucket full" in getattr(btn, "aria-label")
    css = (APP / "assets/style.css").read_text()  # visible label and ban icon follow state
    assert '.ch-out.st-bucket_full .ch-tag-s::after { content: "Bucket full"; }' in css
    assert (
        "--tag-ic: var(--ic-ban)" in css and "--ic-ban:" in (APP / "assets/icons.css").read_text()
    )
    assert len(list(_walk(btn))) <= 9  # compact: one tag element, not six variants


# ------------------------------------------------------------- icons, no emoji
def test_icon_stylesheet_is_generated_from_the_icon_set():
    assert (APP / "assets/icons.css").read_text() == icons.css()
    assert set(icons.ICONS) >= {"trophy", "medal", "circle-check", "undo", "calculator"}


# ------------------------------------------------------------- analytics
def _port(svc, snap):  # noqa: F811
    return svc.portfolio(snap, valid_keys(snap))


def test_calculation_breakdown_reconciles_with_engine(svc, snap):  # noqa: F811
    import math

    from diski9.challenge import analysis as pa

    port = _port(svc, snap)
    for source in pa.SOURCES:
        prob = pa.probability_for(source, {port.buckets[0][0].key: 0.9})
        ev = pa.evaluate_with(port, prob)
        bd = pa.calculation_breakdown(port, prob)
        assert len(bd.states) == 8
        assert math.isclose(sum(s.probability for s in bd.states), 1.0, abs_tol=1e-12)
        for line in bd.buckets:  # step 1: product of the constituent probabilities
            assert math.isclose(line.probability, math.prod(g.probability for g in line.legs),
                                rel_tol=1e-12)  # fmt: skip
            assert line.payout == round(line.stake * line.combined_odds, 2)
        for st in bd.states:  # step 2: weighted = probability x gross
            assert st.weighted == st.probability * float(st.gross)
            assert st.recovers == (st.gross >= 100)
        allnine = next(st for st in bd.states if all(st.wins))
        assert allnine.gross == sum(b.payout for b in bd.buckets) + bd.nine_fold.payout
        others = [st for st in bd.states if not all(st.wins)]
        assert all(st.gross == sum(b.payout for b, w in zip(bd.buckets, st.wins, strict=True)
                                   if w) for st in others)  # fmt: skip
        # step 3 and 4 reconcile with the summary metrics
        assert math.isclose(bd.p_recover, sum(s.probability for s in bd.states if s.recovers),
                            abs_tol=1e-12)  # fmt: skip
        assert math.isclose(bd.p_recover, ev.p_recover, abs_tol=1e-12)
        assert math.isclose(bd.expected_gross, sum(s.weighted for s in bd.states), rel_tol=1e-12)
        assert math.isclose(bd.expected_gross, ev.expected_gross, rel_tol=1e-12)
        assert math.isclose(bd.expected_net, bd.expected_gross - 100, abs_tol=1e-9)
        assert bd.has_partial == (ev.p_partial > 0)
        if bd.has_partial:
            assert not math.isclose(bd.p_recover, 1 - bd.p_zero, abs_tol=1e-12)


def test_conditional_payout_is_probability_weighted(svc, snap):  # noqa: F811
    import math

    from diski9.challenge import analysis as pa

    cc = pa.correct_count_analysis(_port(svc, snap))
    for row in cc.rows:
        group = [s for s in cc.states if s.n_correct == row.k]
        weighted = sum(s.probability * float(s.gross) for s in group) / row.probability
        assert math.isclose(row.expected_gross, weighted, rel_tol=1e-12)
    # differs from a plain average of the combinations where payouts vary
    k = next(r.k for r in cc.rows if r.min_gross != r.max_gross)
    group = [s for s in cc.states if s.n_correct == k]
    plain = sum(float(s.gross) for s in group) / len(group)
    assert not math.isclose(cc.rows[k].expected_gross, plain, rel_tol=1e-6)


def test_combined_chart_focus_and_full_views(svc, snap):  # noqa: F811
    from diski9.app.challenge import charts
    from diski9.challenge import analysis as pa

    cc = pa.correct_count_analysis(_port(svc, snap))
    focus, full = charts.correct_combined(cc, 3, "focus"), charts.correct_combined(cc, 3, "all")
    assert list(focus.data[0].y) == list(full.data[0].y) == [r.probability for r in cc.rows]
    assert focus.data[1].y[9] is None and full.data[1].y[9] == cc.rows[9].expected_gross
    assert list(focus.data[1].y[:9]) == [r.expected_gross for r in cc.rows[:9]]
    assert any("9 correct hidden" in a.text for a in focus.layout.annotations)
    assert not any("hidden" in a.text for a in full.layout.annotations)
    assert focus.layout.yaxis2.range[1] < full.layout.yaxis2.range[1]
    assert any(sh.y0 == 100 and sh.yref == "y2" for sh in full.layout.shapes)


def test_zero_probability_counts_are_gaps_not_zeros(svc, snap):  # noqa: F811
    from diski9.app.challenge import charts, pages
    from diski9.challenge import analysis as pa

    port = _port(svc, snap)
    first = port.buckets[0][0].key

    def prob(o):  # one certain prediction: zero correct becomes impossible
        return 1.0 if o.key == first else o.market_probability

    cc = pa.correct_count_analysis(port, prob)
    assert cc.rows[0].probability == 0 and cc.rows[0].expected_gross is None
    assert cc.rows[0].p_recover is None
    fig = charts.correct_combined(cc, 0, "all")
    assert fig.data[1].y[0] is None and fig.data[1].customdata[0][0] == "impossible"
    assert "can't happen" in jtext(pages.k_detail(cc, 0))


def test_analysis_panel_has_calculation_details_and_no_cr_suffix(svc, snap):  # noqa: F811
    from diski9.app.challenge import pages

    for source in ("market", "model", "personal"):
        text = jtext(pages.analysis_panel(svc, snap, valid_keys(snap), {"source": source}))
        label = {"market": "Market", "model": "Diski 9", "personal": "Your View"}[source]
        assert "How are these calculated?" in text and "Using the " in text and label in text
        assert "Focus on 0\\u20138 correct" in text and "Show all nine" in text
        assert "Average payout by number correct" not in text  # merged into one chart
        assert re.search(r"\d cr\b", text) is None


def test_stepper_never_shows_review_for_an_incomplete_draft(svc, snap):  # noqa: F811
    from diski9.app.challenge import pages

    keys = valid_keys(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    for k in keys[:5]:
        s, _ = cb.apply_action(svc, s, "pick", k)
    s["stage"] = "review"  # e.g. a stale stored step
    nav = pages.stepper(svc, s)
    build, review = nav.children
    assert "is-current" in build.className and "is-current" not in review.className
    assert review.disabled and getattr(build, "aria-current", None) == "step"
    for k in keys[5:]:
        s, _ = cb.apply_action(svc, s, "pick", k)
    build, review = pages.stepper(svc, s).children
    assert "is-current" in review.className and "is-done" in build.className
    assert "is-available" in build.className and not review.disabled


def test_how_to_play_has_build_steps_and_two_objectives():
    """Phase 6B.3: three build steps (superseding the four of 6B.2)."""
    from diski9.app.challenge import pages

    text = jtext(pages.how_to_play(True, CFG))
    for t in ("Get your 100 credits back", "Finish in the top ten", "Build your portfolio",
              "Choose nine different matches", "Compare probabilities and assess your risk",
              "Review and submit", "Market probability determines bucket eligibility",
              "competitive rounds only, never in demonstration or practice rounds",
              "Rules and scoring"):  # fmt: skip
        assert t in text, t
    assert text.count('"ch-goal"') == 2  # no extra competitive objectives
    assert text.count('"ch-build-step"') == 3
    assert "Understand your portfolio risk" not in text


EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f2ff⭐⭕✅❌]")


def test_no_emojis_in_application_source():
    hits = []
    for path in list(APP.rglob("*.py")) + list(APP.rglob("*.css")) + list(APP.rglob("*.js")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if EMOJI.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert hits == []


# ------------------------------------------------------------- rank icons
def test_shared_ranks_get_identical_icons_and_no_manufactured_place():
    rows = [(1, "Ann", "150"), (1, "Bob", "150"), (3, "Cat", "125"), (4, "Dee", "120")]
    text = jtext(comp.podium(rows))
    assert text.count("ic-trophy") == 1 and "1st (shared)" in text  # one shared 1st place
    assert "rank-ic bronze" in text and "silver" not in text and "2nd" not in text
    assert jtext(comp.rank_cell(1, True)).count("ic-trophy") == 1
    assert "=1" in jtext(comp.rank_cell(1, True)) and "gold" in jtext(comp.rank_cell(1, False))
    assert "ic-medal" in jtext(comp.rank_cell(2, False)) and "silver" in jtext(
        comp.rank_cell(2, False)
    )
    assert comp.rank_cell(4, False) == "4" and comp.rank_cell(11, True) == "=11"


def test_leaderboards_use_rank_icons_for_top_three_only():
    from diski9.app.challenge import pages
    from diski9.challenge import demo

    weekly = jtext(pages.leaderboard_body("weekly", demo.LATEST_ROUND))
    champ = jtext(pages.leaderboard_body("championship", None))
    for text in (weekly, champ):
        assert "rank-ic" in text and "ic-trophy" in text
        assert re.search(r"\d cr\b", text) is None


# ------------------------------------------------------------- Phase 6B.3 headings
def test_navigation_and_page_headings_are_consistent(data):  # noqa: F811
    from diski9.app import create_app
    from diski9.app.challenge import callbacks
    from diski9.app.challenge import pages as pg
    from diski9.app.challenge.service import ChallengeService

    assert [label for _, label in callbacks.NAV] == [
        "Match Lab", "Weekly Challenge", "My Challenge", "Leaderboards"]  # fmt: skip
    app = create_app(data)
    layout = app.server.test_client().get("/_dash-layout").get_data(as_text=True)
    assert "Screener & Match Lab" not in layout
    assert "We calculate the probabilities" not in layout  # slogan removed (final amendment)
    assert "tagline" not in layout
    service = ChallengeService(data)
    heads = {
        "Match Lab": layout,
        "Weekly Challenge": jtext(pg.challenge_shell(service, None, None, data.local)),
        "My Challenge": jtext(pg.my_challenge(service, None, data.local)),
        "Leaderboards": jtext(pg.leaderboards()),
    }
    for title, text in heads.items():  # the same heading component everywhere
        h1 = rf'"children":\s*"{title}"[^}}]*"className":\s*"ch-h1"'
        alt = rf'"className":\s*"ch-h1"[^}}]*"children":\s*"{title}"'
        assert re.search(h1, text) or re.search(alt, text), title
        assert "ch-title page-head" in text, title


def test_my_challenge_round_card_facts_follow_state(svc, snap):  # noqa: F811
    from diski9.app.challenge import pages

    keys = valid_keys(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    text = jtext(pages.my_challenge(svc, s, _Local()))
    assert "0 of 9 in your draft" in text and "Not confirmed" in text
    assert "None: demonstration round" in text and "100 virtual (40 / 30 / 20 / 10)" in text
    for k in keys:
        s, _ = cb.apply_action(svc, s, "pick", k)
    s, _ = cb.apply_action(svc, s, "submit")
    text = jtext(pages.my_challenge(svc, s, _Local()))
    assert "9 of 9 submitted" in text and "Confirmed " in text
    assert "replace or withdraw until the round locks" in text and "browser tab" in text
    assert "ch-round-card" in text and "ch-conf-summary" in text
    s, _ = cb.apply_action(svc, s, "ask_withdraw")
    s, _ = cb.apply_action(svc, s, "withdraw")
    text = jtext(pages.my_challenge(svc, s, _Local()))
    assert "Withdrawn " in text and "Build a new portfolio" in text


class _Local:
    def __call__(self, dt, fmt="%a %d %b, %H:%M"):
        from datetime import datetime

        return (datetime.fromisoformat(dt) if isinstance(dt, str) else dt).strftime(fmt)
