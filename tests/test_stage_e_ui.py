"""Phase 6C.5 Stage E: rendering of every Leaderboards and My Challenge History state
from read-service objects (pure; no database). The backend behaviour behind these
objects is covered by the PostgreSQL suites; here we check that each state is
presented with the approved wording, never with misleading zeros or a speculative
result, and with no identifiers."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from plotly.utils import PlotlyJSONEncoder

from diski9.app.challenge import history_ui as hu
from diski9.app.challenge import leaderboards_ui as lbu
from diski9.backend.services import challenge_history as ch
from diski9.backend.services import leaderboards as lb

AT = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def text(component) -> str:
    return json.dumps(component, cls=PlotlyJSONEncoder, ensure_ascii=False)


def row(
    pos, name, gross="150.00", rec="recovered", pts=150, me=False, shared=False, status="ranked"
):
    g = Decimal(gross)
    return lb.WeeklyRow(pos, shared, name, g, g - 100 if rec in ("recovered", "not_recovered")
                        else Decimal("0.00"), rec, pts, None, None, status, me)  # fmt: skip


def wboard(**kw) -> lb.WeeklyBoard:
    base = lb.WeeklyBoard(
        round_code="2026-W48", stream="beta", state="final", classification="competitive",
        round_void=False, void_basis=None, revision=1, corrected=False, published_at=AT,
        entries=3, settled_predictions=None, pending_predictions=None,
        rows=(row(1, "kasi", shared=True), row(1, "lindiwe", shared=True),
              row(3, "dsg", "80.00", "not_recovered", 0, me=True)),
        total=3, page=1, pages=1, page_size=50, me=row(3, "dsg", "80.00", "not_recovered", 0,
                                                       me=True),
        me_page=1, me_status="ranked", championship="Championship Nov-26",
        championship_status="assigned",
        counts_toward_championship=True, championship_round=4, championship_rounds_required=10,
    )  # fmt: skip
    return replace(base, **kw)


def weekly(wb) -> str:
    return text([lbu.weekly_header(wb, wb.stream), lbu.weekly_you(wb), lbu.weekly_banner(wb),
                 lbu.weekly_podium(wb), lbu.weekly_table(wb)])  # fmt: skip


# ------------------------------------------------------------------ weekly
def test_final_competitive_round():
    t = weekly(wboard())
    assert "counted round 4 of 10" in t and "Final · published 20 Nov 2026 12:00 SAST" in t
    assert "Points" in t and "=1" in t and "You · " in t and "Not recovered" in t
    assert "#3" in t and "Beta" in t and not UUID.search(t)


def test_corrected_and_under_review():
    t = weekly(wboard(corrected=True, revision=2))
    assert "Corrected · version 2" in t
    t = weekly(wboard(state="under_review"))
    assert "last published results and are no longer definitive" in t
    assert "Your result (last published)" in t


def test_provisional_shows_settled_so_far_and_no_points():
    p = replace(row(1, "kasi", rec="undecided", pts=None, status="in_progress"), net=None,
                settled=5, pending=4)  # fmt: skip
    t = weekly(wboard(state="provisional", settled_predictions=50, pending_predictions=40,
                      rows=(p,), me=replace(p, is_me=True), revision=None))  # fmt: skip
    assert "Provisional · 50 of 90 predictions settled" in t and "Returned so far" in t
    assert '"Points"' not in t and "Not decided yet" not in t or "Settling" in t
    assert "Your result (provisional)" in t


def test_provisionally_void_round_is_not_presented_as_final():
    me = row(None, "dsg", "100.00", "round_refund", None, me=True, status="round_void")
    t = weekly(wboard(state="provisional", round_void=True, rows=(), me=me))
    assert "Nothing is final yet" in t and "would be void" in t
    assert "Every entry was refunded" not in t


def test_final_void_round_has_no_table():
    me = row(None, "dsg", "100.00", "round_refund", None, me=True, status="round_void")
    t = weekly(wboard(round_void=True, void_basis="operator", rows=(), total=0, me=me,
                      championship_status="void", counts_toward_championship=False,
                      championship_round=None))  # fmt: skip
    assert "Round void: An operator invalidated this round" in t
    assert "your 100 credits were refunded" in t and "ch-table" not in t


def test_practice_round_has_no_points_column():
    rows = (row(1, "kasi", pts=None), row(2, "dsg", "90.00", "not_recovered", None, me=True))
    t = weekly(wboard(classification="practice", rows=rows, me=rows[1],
                      championship_status="practice", counts_toward_championship=False,
                      championship_round=None))  # fmt: skip
    assert "Practice round: fewer than five entries" in t and '"Points"' not in t
    assert "practice: no championship points" in t


def test_refunded_entry_and_not_entered_and_guest():
    me = row(None, "dsg", "100.00", "refunded", None, me=True, status="refunded")
    assert "Void · Refunded · 100 credits returned · not ranked" in weekly(wboard(me=me))
    assert "You did not enter this round" in weekly(wboard(me=None, me_status="not_entered"))
    assert "Sign in to see your position" in weekly(wboard(me=None, me_status=None))


def test_pending_assignment_is_never_speculative():
    t = weekly(wboard(championship=None, championship_status="pending_assignment",
                      counts_toward_championship=None, championship_round=None,
                      championship_note="The championship this round counts toward is "
                      "confirmed when Round W47 is final."))  # fmt: skip
    assert "Championship assignment pending" in t and "Round W47 is final" in t
    assert "Championship Nov-26" not in t


def test_open_and_locked_states_reveal_nothing():
    assert "revealed after the deadline" in weekly(
        wboard(state="open", rows=(), me=None, me_status="not_entered")
    )
    t = weekly(wboard(state="locked", rows=(), me=None, me_status="locked"))
    assert "Entries locked" in t and "Your entry is locked" in t


def test_podium_caps_names_per_place():
    rows = tuple(row(3, f"p{i}", "0.00", "not_recovered", 0) for i in range(8))
    pod = text(lbu.weekly_podium(wboard(rows=(row(1, "kasi"), *rows))))
    assert "and 5 others" in pod and '"p2"' in pod and '"p3"' not in pod


def test_pager_and_rules():
    t = text(lbu.pager(2, 5, 214, 50, 4, "lbw"))
    assert "Showing 51–100 of 214" in t and "Go to my position" in t and "Page 2 of 5" in t
    r = text(lbu.rules())
    for pts in (150, 135, 125, 120, 115, 110, 105, 100, 95, 90):
        assert f": {pts}" in r
    assert "11th and below: 75" in r and "then successful recoveries" in r


# ------------------------------------------------------------------ championship
def crow(pos, name, pts, me=False, shared=False):
    return lb.ChampionshipRow(pos, shared, name, 4, 3, 1, pts, Decimal("0.75"), me)


def cboard(**kw) -> lb.ChampionshipBoard:
    base = lb.ChampionshipBoard(
        stream="beta", name="Championship Nov-26", status="in_progress", start_date=AT.date(),
        counted_rounds=4, rounds_required=10, under_review=False, review_reasons=(),
        corrected_after_completion=False, corrected_with_fewer_rounds=False, version=4,
        published_at=AT, champions=(), no_champion=False, pending_assignment=0,
        rows=(crow(1, "lindiwe", 510), crow(7, "dsg", 300, me=True)), total=2, page=1, pages=1,
        page_size=50, me=crow(7, "dsg", 300, me=True), me_page=1, me_status="ranked",
        championships=(),
    )  # fmt: skip
    return replace(base, **kw)


def champ(cb) -> str:
    return text([lbu.championship_header(cb, cb.stream), lbu.championship_notices(cb),
                 lbu.championship_you(cb), lbu.championship_table(cb)])  # fmt: skip


def test_in_progress_championship():
    t = champ(cboard())
    assert "In progress" in t and "4 of 10 valid rounds" in t and "Champion:" not in t
    assert "#7" in t and "300 pts" in t and "Top 10s" in t and not UUID.search(t)
    assert "1 round played" not in t and "round(s)" not in t and "finish(es)" not in t
    assert t.count("lb-seg on") == 4


def test_completed_joint_champions_and_no_champion():
    t = champ(cboard(status="completed", counted_rounds=10, champions=("lindiwe", "kasi")))
    assert "Joint champions: " in t and "lindiwe, kasi" in t
    t = champ(cboard(status="completed", counted_rounds=10, no_champion=True))
    assert "No champion: no participant scored points" in t


def test_d30a_and_all_rounds_invalidated():
    disc = ("This championship was corrected after completion. One previously counted round "
            "was invalidated and the final standings were recalculated.")  # fmt: skip
    t = champ(cboard(status="completed", counted_rounds=9, corrected_after_completion=True,
                     corrected_with_fewer_rounds=True, disclosure=disc))  # fmt: skip
    assert "Corrected" in t and "Subsequent championships are unaffected" in t
    assert "remaining" not in t.lower() and "Short" not in t
    t = champ(cboard(status="completed", counted_rounds=0, corrected_with_fewer_rounds=True,
                     corrected_after_completion=True, rows=(), total=0, me=None,
                     me_status="invalidated_only", disclosure=disc))  # fmt: skip
    assert lbu.ALL_INVALIDATED in t and "Upcoming" not in t


def test_review_reasons_and_integrity_review():
    t = champ(cboard(under_review=True, review_reasons=("integrity_review", "reopened")))
    assert "Under review" in t and "being checked by the competition team" in t
    assert "reopened for review" in t and "(last published)" in t


def test_not_ranked_reasons_and_upcoming():
    for status, words in (
        ("refunded_only", "were refunded"),
        ("practice_only", "practice"),
        ("awaiting_results", "waiting"),
        ("not_entered", "not entered"),
    ):
        assert words in champ(cboard(me=None, me_status=status))
    t = champ(cboard(status="upcoming", counted_rounds=0, rows=(), total=0, me=None,
                     me_status="not_entered"))  # fmt: skip
    assert "Everyone starts at zero" in t


# ------------------------------------------------------------------ history
def hrow(**kw) -> ch.HistoryRow:
    base = ch.HistoryRow(
        round_code="2026-W48", deadline_at=AT, stream="beta", classification="competitive",
        state="final", round_void=False, void_basis=None, entry_refunded=False, published=True,
        revision=1, corrected=False, gross=Decimal("131.40"), net=Decimal("31.40"),
        recovery="recovered", rank=12, shared=False, weekly_points=75,
        championship="Championship Nov-26", championship_role="counted",
        counts_toward_championship=True, current_gross=None, current_complete=None,
    )  # fmt: skip
    return replace(base, **kw)


def test_history_status_texts():
    assert hu.status_text(hrow()) == "Final"
    assert hu.status_text(hrow(corrected=True, revision=2)) == "Corrected (v2)"
    assert hu.status_text(hrow(state="under_review")) == "Under review"
    assert hu.status_text(hrow(round_void=True)) == "Round void · refunded"
    assert hu.status_text(hrow(entry_refunded=True)) == "Refunded (all void)"
    assert hu.status_text(hrow(state="provisional", published=False)) == "Provisional"
    assert hu.championship_text(hrow(championship=None)) == "Assignment pending"
    assert hu.championship_text(hrow(championship_role="not_counted")).endswith("not counted")


def test_history_table_values():
    page = ch.HistoryPage((hrow(), hrow(round_code="P1", classification="practice",
                                        weekly_points=None, championship_role="practice"),
                           hrow(round_code="W49", state="provisional", published=False,
                                gross=None, net=None, recovery=None, rank=None,
                                weekly_points=None, current_gross=Decimal("40.00"))),
                          3, 1, 1, 20)  # fmt: skip
    t = text(hu.history_table(page, lambda s: s[:10]))
    assert "131.40" in t and "+31.40" in t and '"75"' in t and "40.00 so far" in t
    assert "Practice" in t and "hist-open" in t


def stats(**kw) -> ch.PersonalStats:
    base = ch.PersonalStats(
        stream="beta", scope=None, counted_rounds=4, played=3, missed=1, recoveries=3,
        recovery_rate=Decimal("1.0000"), qualifying_top10=1, allocated=Decimal("300.00"),
        returned=Decimal("412.60"), net=Decimal("112.60"), roi=Decimal("0.3753"),
        refunded_entries=1, void_rounds=0, not_counted_entries=0, awaiting_results=0,
        practice_entries=1, practice_recoveries=0, under_review=False,
        standings=(ch.ChampionshipStanding("Championship Nov-26", "in_progress", 7, False, 300, 3),),
        allocation_series=(), points_championship=None, points_series=(),
    )  # fmt: skip
    return replace(base, **kw)


def test_summary_metrics_and_population_note():
    t = text(hu.summary(stats()))
    assert "3 of 4" in t and "missed 1" in t and "recovery rate 100.0%" in t
    assert "return on allocation " in t and "37.5%" in t and "Competitive population" in t
    assert "Practice: 1 entry" in t and "Refunded (all void): 1" in t
    assert "Championship Nov-26" in t and "#7 · 300 pts" in t
    assert "How your statistics are calculated" in t  # methodology behind a disclosure
    assert t.count("me-stat-head") == 6 and "cat-teal" in t and "pos-val" in t
    t = text(hu.summary(stats(played=0, recoveries=0, recovery_rate=None, roi=None,
                              allocated=Decimal("0.00"), returned=Decimal("0.00"),
                              net=Decimal("0.00"), standings=())))  # fmt: skip
    assert "no rounds played yet" in t and "nothing allocated yet" in t and "%" not in t.split(
        "Competitive population")[0].replace("return on allocation", "")  # fmt: skip


def series(n, eligible=True, start=0):
    return tuple(
        ch.SeriesPoint(f"W{48 + start + k}", AT, Decimal(100 * (k + 1)), Decimal(120 * (k + 1)),
                       "120.00 returned", f"{19 + k}–23 Nov 2026", eligible)
        for k in range(n)
    )  # fmt: skip


def test_charts_wait_for_three_eligible_rounds():
    """Owner refinement: each chart appears only after three eligible rounds; below that
    a compact placeholder shows the progress, never a near-empty chart."""
    for n in (0, 1, 2):
        t = text(hu.allocation_chart(stats(allocation_series=series(n))))
        assert "will become available after 3 eligible rounds" in t
        assert f"{n} of 3 eligible rounds completed" in t and "Scatter" not in t
    t = text(hu.allocation_chart(stats(allocation_series=series(3))))
    assert "Allocated" in t and "Returned" in t and "will become available" not in t
    # headings: bold h2 like "Your statistics", with or without the placeholder
    for card in (hu.allocation_chart(stats(allocation_series=series(1))),
                 hu.allocation_chart(stats(allocation_series=series(3))),
                 hu.points_chart(stats(points_championship="Championship Nov-26",
                                       points_series=series(1)))):  # fmt: skip
        head = card.children[0]
        assert type(head).__name__ == "H2" and "me-chart-title" in head.className
    t = text(hu.allocation_chart(stats(allocation_series=series(5))))
    assert "19–23 Nov 2026 · W48" in t  # friendly label on hover; codes are not axis labels
    assert '"type": "linear"' in t or "linear" in t


def test_points_chart_threshold_counts_only_played_rounds():
    # missed (not entered) and refunded rounds are plotted but never unlock the chart
    pts = series(2) + series(3, eligible=False, start=2)
    s = stats(points_championship="Championship Nov-26", points_series=pts)
    assert s.points_rounds == 2
    t = text(hu.points_chart(s))
    assert "championship points chart will become available" in t and "2 of 3" in t
    s = stats(points_championship="Championship Nov-26", points_series=series(3))
    t = text(hu.points_chart(s))
    assert "Championship Nov-26" in t and '"hv"' in t and "never carry" in t


def test_one_chart_can_unlock_before_the_other():
    s = stats(allocation_series=series(4), points_championship="Championship Nov-26",
              points_series=series(1))  # fmt: skip
    a, p = text(hu.allocation_chart(s)), text(hu.points_chart(s))
    assert "will become available" not in a and "will become available" in p
    # statistics cards are shown regardless of the charts
    assert text(hu.summary(s)).count("me-stat-head") == 6
