"""My Challenge: the participant's actual settlement results (Phase 6C.4, Stage F).

Presentation only. Every number comes from
:func:`diski9.backend.services.participant_results.my_settlement` (the stored,
authoritative settlement); nothing here computes a payout, a verdict or a recovery.
The results extend the existing confirmed-portfolio cards; the frozen pre-match
estimates (Market, Diski 9, Your View) stay where they are and are labelled as
pre-match expectations, distinct from these actual outcomes.

Status is always shown with an icon **and** words (never colour alone); no emoji.
"""

from __future__ import annotations

from dash import html

from . import components as c
from .service import key_str

CFG = c.CFG

#: (icon, label, css class) per prediction verdict
VERDICT = {
    "won": ("check", "Correct", "won"),
    "lost": ("x", "Incorrect", "lost"),
    "void": ("minus", "Void", "void"),
    "pending": ("clock", "Pending", "pending"),
}
#: (icon, label, css class) per accumulator status
ACCUMULATOR = {
    "won": ("check", "Successful", "won"),
    "lost": ("x", "Unsuccessful", "lost"),
    "refunded": ("undo", "Refunded", "void"),
    "pending": ("clock", "Pending", "pending"),
}


def fetch(service, round_uuid):
    """The signed-in participant's own settlement for a server-chosen round, or
    ``None`` (guest, no entry, database unavailable: nothing is fabricated)."""
    from . import persist

    p = persist.participant(service)
    b = persist.backend_of(service)
    if p is None or b is None or round_uuid is None:
        return None
    from diski9.backend.services.participant_results import my_settlement

    try:
        return my_settlement(b.engine, p, round_uuid)
    except Exception:  # noqa: BLE001 - the results panel is simply not shown
        return None


def status(res) -> tuple[str, str, str]:
    """(label, pill class, one-line explanation) for the entry's settlement state."""
    if res.round_void:
        final = res.state == "final"
        why = (
            "An operator invalidated this round."
            if res.round_void_basis == "operator"
            else "Too many predictions in this round were void, or too few entries "
            "remained, for a valid result."
        )
        return (
            "Round void" + (" · final" if final else ""),
            "warn",
            f"{why} Every entry is refunded its 100 credits. A refund is not a recovery.",
        )
    if res.entry_refunded:
        return (
            "Void · refunded" + (" · final" if res.state == "final" else ""),
            "warn",
            "All nine of your predictions were void, so your 100 credits are refunded. "
            "A refund does not count as a recovery and is not ranked.",
        )
    if res.state == "awaiting_lock":
        return (
            "Deadline passed",
            "warn",
            "The deadline has passed; your entry can no longer change and is waiting to be locked.",
        )
    if res.state == "locked":
        return (
            "Locked",
            "warn",
            "Your entry is locked. Results appear here as the matches are settled.",
        )
    if res.state == "awaiting_round":
        return (
            "Settled · round check pending",
            "demo",
            "All your predictions are settled. Other matches in this round are still being "
            "settled, so the round's validity check, your net and recovery are not final yet.",
        )
    if res.state == "in_progress":
        return (
            "Partly settled",
            "demo",
            "Some predictions are settled; the rest are waiting for their matches. Totals "
            "are settled so far.",
        )
    if res.state == "final":
        return "Final result", "ok", "This result is final."
    return (
        "Provisional result",
        "demo",
        "Every prediction is settled. The result becomes final after the correction window.",
    )


def _verdict_tag(verdict: str, table=VERDICT) -> html.Span:
    icon, label, cls = table[verdict]
    return html.Span([c.icon(icon, "ic-sm"), label], className=f"ch-verdict {cls}")


def _money(value) -> str:
    return "Pending" if value is None else c.credits(value)


def notices(res, local) -> list:
    out = []
    if res.reopened_at and res.state != "final":
        out.append(
            f"This round was reopened for review on {local(res.reopened_at)} SAST; the "
            "result below is the current recalculation."
        )
    if res.corrected_at:
        out.append(
            f"Corrected {local(res.corrected_at)} SAST: an official result was corrected and "
            "your entry was recalculated. The figures below are the current ones."
        )
    if res.state == "provisional" and res.earliest_finalisation:
        out.append(
            "Provisional: results can still be corrected until the correction window ends "
            f"(final from {local(res.earliest_finalisation)} SAST at the earliest)."
        )
    elif res.state == "final" and res.finalised_at:
        out.append(f"Final since {local(res.finalised_at)} SAST.")
    return [html.P(t, className="small ch-res-notice") for t in out]


def summary(res, local) -> html.Div:
    """Personal settlement summary: status, credits, prediction counts, recovery."""
    label, cls, line = status(res)
    pending = res.counts.get("pending", 0)
    if res.round_void or res.entry_refunded:
        gross_label, recovery = "Refunded", "Refund (not a recovery)"
    else:
        gross_label = "Returned" if res.complete else "Returned so far"
        recovery = (
            "Not decided yet"
            if res.recovered is None
            else "Recovered 100+"
            if res.recovered
            else "Not recovered"
        )
    net = (
        "Not final yet" if res.net is None else (("+" if res.net > 0 else "") + c.credits(res.net))
    )
    gross_sub = (
        "settled so far"
        if not res.complete and not res.round_void
        else "before the round check"
        if res.state == "awaiting_round"
        else ""
    )
    metrics = html.Div(
        [
            c.metric("Allocated", f"{CFG.total_credits}.00", "virtual credits"),
            c.metric(gross_label, c.credits(res.gross) if res.gross is not None else "—",
                     gross_sub),
            c.metric("Net", net),
            c.metric("Recovery", recovery),
        ],
        className="ch-metrics ch-res-metrics",
    )  # fmt: skip
    counts = html.Ul(
        [
            html.Li(
                [_verdict_tag(k), html.Span(str(res.counts.get(k, 0)), className="num strong")],
                className="ch-res-count",
            )
            for k in ("won", "lost", "void", "pending")
        ],
        className="ch-res-counts small",
        **{"aria-label": "Prediction results"},
    )
    return html.Div(
        [
            html.Div(
                [
                    html.H2("Your result", className="ch-h2"),
                    html.Span(
                        [
                            html.Span(label, className=f"ch-pill {cls}"),
                            html.Span("Corrected", className="ch-pill demo")
                            if res.corrected_at
                            else None,
                        ],
                        className="ch-pill-row",
                    ),
                ],
                className="ch-row-between",
            ),
            html.P(line, className="small ch-round-line"),
            *notices(res, local),
            metrics if res.settled else None,
            counts if res.settled else None,
            html.P(
                f"{pending} prediction{'s' if pending != 1 else ''} still pending."
                if res.settled and pending
                else None,
                className="muted small",
            ),
        ],
        className="ch-card ch-compact ch-res-summary",
    )


def accumulators(res) -> html.Div | None:
    if not res.settled:
        return None
    if res.round_void:  # nothing is paid on accumulators; every entry gets 100.00 back
        return html.Div(
            [
                html.H3("Accumulators", className="ch-h3"),
                html.P(
                    [
                        _verdict_tag("refunded", ACCUMULATOR),
                        " Not paid: the round is void, so instead of accumulator returns every "
                        "entry receives its 100 credits back. Your predictions' results below "
                        "are shown for information only.",
                    ],
                    className="small",
                ),
            ],
            className="ch-card ch-compact ch-res-accs",
        )
    rows = []
    for a in res.accumulators:
        legs = html.Span(
            [
                html.Span(
                    c.icon(VERDICT[v][0], "ic-sm"),
                    className=f"ch-leg {VERDICT[v][2]}",
                    title=VERDICT[v][1],
                )
                for v in a.legs
            ],
            className="ch-legs",
            **{"aria-label": ", ".join(VERDICT[v][1] for v in a.legs)},
        )
        rows.append(
            html.Tr(
                [
                    html.Td(c.chip(a.code)),
                    html.Td(f"{a.stake}", className="num"),
                    html.Td(legs),
                    html.Td(_verdict_tag(a.status, ACCUMULATOR)),
                    html.Td(_money(a.payout), className="num strong"),
                ]
            )
        )
    gross_note = (
        "Returns are the actual credits paid. A void prediction counts at odds 1.00; an "
        "accumulator with an incorrect prediction pays nothing even if others are pending."
    )
    return html.Div(
        [
            html.H3("Accumulators", className="ch-h3"),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th("Accumulator"),
                                    html.Th("Credits", className="num"),
                                    html.Th("Predictions"),
                                    html.Th("Outcome"),
                                    html.Th("Returned", className="num"),
                                ]
                            )
                        ),
                        html.Tbody(rows),
                    ],
                    className="ch-table ch-res-table",
                ),
                className="ch-table-wrap",
            ),
            html.P(gross_note, className="muted small"),
        ],
        className="ch-card ch-compact ch-res-accs",
    )


def predictions(res, rec, summary_text: str = "Show my nine predictions and results"):
    """The confirmed predictions with their verdicts: fixture, original pick, frozen
    odds, official 90-minute score and result (and the reason for a void)."""
    picks = {p["key"]: p for p in (rec or {}).get("picks", [])}
    groups = []
    for b in CFG.buckets:
        items = []
        for p in res.predictions:
            if p.bucket != b.code:
                continue
            pick = picks.get(key_str((p.fixture_id, p.market, p.outcome)), {})
            score = f"90 min {p.score}" if p.score else "Score not available yet"
            items.append(
                html.Li(
                    [
                        html.Span(pick.get("match", f"Fixture {p.fixture_id}"),
                                  className="ch-pick-fx"),
                        html.Span(
                            [
                                html.Span(pick.get("outcome", p.outcome)),
                                html.Span(f"odds {p.odds}", className="muted"),
                            ],
                            className="ch-pick-sub small",
                        ),
                        html.Span(
                            [_verdict_tag(p.verdict), html.Span(score, className="muted")],
                            className="ch-pick-res small",
                        ),
                        html.Span(p.void_reason, className="muted small ch-void-why")
                        if p.void_reason
                        else None,
                    ],
                    className=f"ch-pick-text ch-res-{VERDICT[p.verdict][2]}",
                )
            )  # fmt: skip
        groups.append(
            html.Div(
                [
                    html.Div(
                        [
                            c.chip(b.code),
                            html.Span(f"{b.credits} credits", className="muted small"),
                        ],
                        className="ch-trk-head",
                    ),
                    html.Ul(items, className="ch-conf-list"),
                ],
                className=f"ch-conf-bucket b-{c.BUCKET_CLASS[b.code]}",
            )
        )
    return html.Details(
        [
            html.Summary(summary_text),
            html.Div(groups, className="ch-conf-grid"),
            html.P(
                "Your predictions, buckets and frozen odds are exactly as confirmed. Scores "
                "are official 90-minute results (extra time and penalties do not count).",
                className="muted small",
            ),
        ],
        className="ch-details ch-card ch-conf-card ch-res-preds",
        open=True,
    )


def panel(res, rec, local, summary_text: str | None = None) -> list:
    """Summary, accumulators and predictions for a locked or settled entry."""
    if res is None:
        return []
    out = [summary(res, local), accumulators(res)]
    if res.settled:
        out.append(predictions(res, rec, summary_text or "Show my nine predictions and results"))
    return [x for x in out if x is not None]
