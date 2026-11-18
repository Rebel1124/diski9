"""Reusable Weekly Challenge components (presentation only)."""

from __future__ import annotations

from decimal import Decimal

from dash import dcc, html

from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.education import Illustration
from diski9.challenge.roundsheet import RoundAvailability, RoundSnapshot, RoundStatus
from diski9.challenge.scoring import POINTS_150_75_V2, RoundClassification
from diski9.challenge.structured import PortfolioEvaluation, SelectionBlock

from .service import key_str

CFG = DEFAULT_CONFIG
BUCKET_CLASS = {"A": "found", "B": "bal", "C": "chal", "NINE": "nine"}
BUCKET_NAME = {b.code: b.name for b in CFG.buckets} | {"NINE": CFG.nine_fold_name}
MARKET_NAME = {"1X2": "Match result", "BTTS": "Both teams to score", "OU25": "Over/Under 2.5"}
OUTCOME_NAME = {
    "HOME": "Home win",
    "DRAW": "Draw",
    "AWAY": "Away win",
    "BTTS_YES": "BTTS: Yes",
    "BTTS_NO": "BTTS: No",
    "OVER_2_5": "Over 2.5 goals",
    "UNDER_2_5": "Under 2.5 goals",
}
BLOCK_TEXT = {
    SelectionBlock.FIXTURE_TAKEN: "Fixture already used",
    SelectionBlock.BUCKET_FULL: "Bucket full",
    SelectionBlock.WOULD_BLOCK_COMPLETION: "Would leave the portfolio impossible to finish",
}
BLOCK_HELP = {
    SelectionBlock.FIXTURE_TAKEN: "You already picked an outcome from this match. Remove it "
    "first to choose this one instead.",
    SelectionBlock.BUCKET_FULL: "This bucket already has all its predictions. Remove one to "
    "swap it.",
    SelectionBlock.WOULD_BLOCK_COMPLETION: "With this pick, the remaining matches could not "
    "fill your other buckets.",
}
BAND_TEXT = {"A": "60%–95%", "B": "40% to under 60%", "C": "20% to under 40%"}


def T(name: str, i: int | str = 0) -> dict:
    """Pattern-matching IDs, so callbacks work whichever page is showing."""
    return {"t": name, "i": i}


def pct(p: float, digits: int = 1) -> str:
    return f"{p:.{digits}%}"


def credits(x) -> str:
    return f"{Decimal(str(x)):,.2f}"


def outcome_text(o) -> str:
    return OUTCOME_NAME.get(str(o.outcome), str(o.outcome))


def chip(code: str, text: str | None = None) -> html.Span:
    return html.Span(text or BUCKET_NAME[code], className=f"bchip b-{BUCKET_CLASS[code]}")


def demo_ribbon(snap: RoundSnapshot | None) -> html.Div | None:
    if snap is None or not snap.is_demo:
        return None
    return html.Div(
        [
            html.Strong("Demonstration round. "),
            "Historical fixtures and reference odds from a frozen snapshot "
            f"({snap.snapshot_at:%d %b %Y, %H:%M} UTC). Practice only: not a live competition.",
        ],
        className="ch-ribbon",
        role="note",
    )


# ------------------------------------------------------------- status
def status_panel(avail: RoundAvailability, snap: RoundSnapshot | None, local) -> html.Div:
    rep = avail.report
    status_cls = {RoundStatus.OPEN: "ok", RoundStatus.DEMO: "demo", RoundStatus.LOCKED: "warn"}
    facts = []
    if snap is not None:
        facts.append(("Round", snap.round_id))
        facts.append(("Snapshot", f"{local(snap.snapshot_at)} SAST"))
        if not snap.is_demo and snap.deadline:
            facts.append(("Deadline", f"{local(snap.deadline)} SAST"))
    if rep is not None:
        facts.append(("Eligible fixtures", str(rep.eligible_fixtures)))
        facts.append(("Leagues", str(rep.eligible_leagues)))
    return html.Div(
        [
            html.Div(
                [
                    html.Span(avail.title, className="ch-status-title"),
                    html.Span(
                        avail.status.value.replace("_", " "),
                        className=f"ch-pill {status_cls.get(avail.status, 'off')}",
                    ),
                ],
                className="ch-status-head",
            ),
            html.P(avail.message, className="muted"),
            html.Dl(
                [el for k, v in facts for el in (html.Dt(k), html.Dd(v))], className="ch-facts"
            ),
        ],
        className="ch-card ch-status",
    )


def structure_table() -> html.Div:
    rows = [
        html.Div(
            [
                chip(b.code),
                html.Span(f"{b.selections} predictions"),
                html.Span(BAND_TEXT[b.code]),
                html.Span(f"{b.credits} credits"),
            ],
            className="ch-struct-row",
        )
        for b in CFG.buckets
    ]
    rows.append(
        html.Div(
            [
                chip("NINE"),
                html.Span("All nine"),
                html.Span("The whole portfolio"),
                html.Span(f"{CFG.nine_fold_credits} credits"),
            ],
            className="ch-struct-row",
        )
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Span("Bucket"),
                    html.Span("Predictions"),
                    html.Span("Each prediction's market chance"),
                    html.Span("Credits"),
                ],
                className="ch-struct-row head",
            ),
            *rows,
            html.P(
                "The chance range applies to each prediction on its own, not to the whole "
                "bucket. Every bucket is an accumulator: all of its predictions must succeed "
                "for it to pay.",
                className="muted small",
            ),
        ],
        className="ch-struct",
    )


def rules_details() -> html.Details:
    pts = POINTS_150_75_V2.top_points
    return html.Details(
        [
            html.Summary("Rules and scoring"),
            html.Ul(
                [
                    html.Li(
                        "Every entry has 100 virtual credits with no cash value. The split is "
                        "fixed: 40 / 30 / 20 on the three buckets and 10 on The Diski 9."
                    ),
                    html.Li(
                        "Pick nine outcomes from nine different matches: four Foundation, three "
                        "Balanced and two Challenger. The bucket is set by the market's chance "
                        "for that outcome (bookmaker margin removed)."
                    ),
                    html.Li(
                        "Payouts use the frozen consensus reference odds from the round "
                        "snapshot. The Diski 9 pays only if all nine predictions succeed."
                    ),
                    html.Li(
                        "You recover your credits when your total gross payout is at least "
                        "100.00. No recovery, no championship points."
                    ),
                    html.Li(
                        "With a recovery, weekly ranks 1–10 earn "
                        + " / ".join(str(p) for p in pts)
                        + " championship points; any other recovery earns "
                        f"{POINTS_150_75_V2.recovery_points}. Ties share the rank and the "
                        "full points."
                    ),
                    html.Li(
                        "A championship is ten competitive rounds. Practice rounds (fewer than "
                        "five entries) and void rounds award no points and don't count."
                    ),
                ]
            ),
        ],
        className="ch-details",
    )


def objectives() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Span("1", className="ch-num"),
                    html.Div(
                        [
                            html.Strong("Get your 100 credits back"),
                            html.Span(
                                "Every recovery earns championship points.", className="muted small"
                            ),
                        ]
                    ),
                ],
                className="ch-goal",
            ),
            html.Div(
                [
                    html.Span("2", className="ch-num"),
                    html.Div(
                        [
                            html.Strong("Finish in the top ten, and get your 100 back"),
                            html.Span(
                                "Top-ten finishes earn 90 to 150 points.", className="muted small"
                            ),
                        ]
                    ),
                ],
                className="ch-goal",
            ),
        ],
        className="ch-goals",
    )


# ------------------------------------------------------------- builder
def outcome_button(o, bucket, block, prob_model, locked: bool) -> html.Button:
    k = key_str(o.key)
    selected = block is SelectionBlock.SELECTED
    disabled = locked or (block is not None and not selected)
    reason = None
    if block is SelectionBlock.INELIGIBLE:
        reason = "Not eligible"
    elif block in BLOCK_TEXT:
        reason = BLOCK_TEXT[block]
    cls = "ch-out" + (f" b-{BUCKET_CLASS[bucket]}" if bucket else " b-none")
    cls += " is-selected" if selected else ""
    cls += " is-blocked" if disabled else ""
    model = pct(prob_model, 0) if prob_model is not None else "—"
    title = BLOCK_HELP.get(block) or (
        "Outside the 20%–95% market range, or the odds don't qualify"
        if block is SelectionBlock.INELIGIBLE
        else "Tap to add"
        if not selected
        else "Tap to remove"
    )
    return html.Button(
        [
            html.Span(outcome_text(o), className="ch-out-name"),
            html.Span(
                [
                    html.Span(f"Mkt {pct(o.market_probability, 0)}"),
                    html.Span(f"D9 {model}", className="muted"),
                    html.Span(f"{o.reference_odds:.2f}", className="ch-odds"),
                ],
                className="ch-out-nums",
            ),
            html.Span(
                ("✓ " + BUCKET_NAME[bucket])
                if selected
                else (reason or BUCKET_NAME.get(bucket, "Not eligible")),
                className="ch-out-tag",
            ),
        ],
        id={"t": "pick", "k": k},
        n_clicks=0,
        disabled=disabled,
        className=cls,
        title=title,
        **{"aria-pressed": "true" if selected else "false"},
    )


def fixture_card(fx, outs, assess, blocks, local, locked) -> html.Div:
    by_market: dict[str, list] = {}
    for o in outs:
        by_market.setdefault(str(o.market), []).append(o)
    groups = []
    for m in ("1X2", "BTTS", "OU25"):
        if m not in by_market:
            continue
        groups.append(
            html.Div(
                [
                    html.Div(MARKET_NAME[m], className="ch-mkt"),
                    html.Div(
                        [
                            outcome_button(
                                o,
                                assess[o.key].bucket if assess[o.key].eligible else None,
                                blocks.get(o.key),
                                o.model_probability,
                                locked,
                            )
                            for o in by_market[m]
                        ],
                        className="ch-outs",
                    ),
                ],
                className="ch-mkt-group",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Span(fx.league, className="ch-league"),
                    html.Span(local(fx.kickoff), className="muted small"),
                ],
                className="ch-fx-meta",
            ),
            html.Div(f"{fx.home} v {fx.away}", className="ch-fx-teams"),
            *groups,
        ],
        className="ch-fx",
    )


def segment_bar(code: str, filled: int, total: int) -> html.Div:
    return html.Div(
        [html.Span(className="seg on" if i < filled else "seg") for i in range(total)],
        className=f"ch-seg b-{BUCKET_CLASS[code]}",
        role="img",
        **{"aria-label": f"{filled} of {total}"},
    )


def tracker(progress, picks, local_fixture, message, can_continue: bool, locked: bool) -> html.Div:
    rows = []
    for b in CFG.buckets:
        n, req = progress.selected[b.code], progress.required[b.code]
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            chip(b.code),
                            html.Span(f"{n}/{req}", className="ch-count"),
                            html.Span(f"{b.credits} cr", className="muted small"),
                        ],
                        className="ch-trk-head",
                    ),
                    segment_bar(b.code, min(n, req), req),
                ],
                className="ch-trk-row",
            )
        )
    rows.append(
        html.Div(
            [
                html.Div(
                    [
                        chip("NINE"),
                        html.Span("all nine", className="ch-count"),
                        html.Span(f"{CFG.nine_fold_credits} cr", className="muted small"),
                    ],
                    className="ch-trk-head",
                )
            ],
            className="ch-trk-row",
        )
    )
    total = progress.total_selected
    mini = html.A(
        [
            html.Span(
                f"{BUCKET_NAME[b.code][0]} {progress.selected[b.code]}/{b.selections}",
                className=f"mini-{BUCKET_CLASS[b.code]}",
            )
            for b in CFG.buckets
        ]
        + [html.Strong(f"{total}/9"), html.Span("View ▴", className="muted")],
        href="#ch-tracker-top",
        className="ch-mini",
        **{"aria-label": "Portfolio progress"},
    )
    items = [
        html.Li(
            [
                chip(code, code),
                html.Div(
                    [
                        html.Span(local_fixture(o), className="small"),
                        html.Span(
                            f"{outcome_text(o)} · Mkt "
                            f"{pct(o.market_probability, 0)} · "
                            f"{o.reference_odds:.2f}",
                            className="muted small",
                        ),
                    ],
                    className="ch-pick-text",
                ),
                html.Button(
                    "✕",
                    id={"t": "remove", "k": key_str(o.key)},
                    n_clicks=0,
                    className="ch-x",
                    title="Remove this prediction",
                    disabled=locked,
                    **{"aria-label": "Remove"},
                ),
            ]
        )
        for code, o in picks
    ]
    return html.Div(
        [
            mini,
            html.Div(
                [
                    html.Span("Your portfolio", className="ch-h3"),
                    html.Span(f"{total}/9", className="ch-total"),
                ],
                className="ch-trk-top",
                id="ch-tracker-top",
            ),
            html.Div(
                className="ch-total-bar",
                children=html.Div(className="fill", style={"width": f"{min(total, 9) / 9:.0%}"}),
            ),
            *rows,
            html.Div(message, className="ch-trk-msg", role="status", **{"aria-live": "polite"}),
            html.Ul(items, className="ch-picks")
            if items
            else html.P(
                "No predictions yet. Pick outcomes from the matches.", className="muted small"
            ),
            html.Div(
                [
                    html.Button(
                        "Clear all",
                        id=T("clear"),
                        n_clicks=0,
                        className="ch-btn ghost",
                        disabled=not items or locked,
                    ),
                    html.Button(
                        "Continue to analysis →",
                        id={"t": "nav", "to": "analyse", "i": "tracker"},
                        n_clicks=0,
                        className="ch-btn primary",
                        disabled=not can_continue,
                    ),
                ],
                className="ch-trk-actions",
            ),
        ],
        className="ch-card ch-tracker",
    )


# ------------------------------------------------------------- explorer
def explorer(values: dict) -> html.Details:
    sliders = []
    for b in CFG.buckets:
        lo, hi = (
            round(b.band.lower * 100),
            round(b.band.upper * 100) - (0 if b.band.upper_inclusive else 1),
        )
        sliders.append(
            html.Div(
                [
                    html.Label([chip(b.code), " each prediction: "], className="small"),
                    dcc.Slider(
                        id={"t": "edu", "b": b.code},
                        min=lo,
                        max=hi,
                        step=1,
                        value=values.get(b.code),
                        marks={lo: f"{lo}%", hi: f"{hi}%"},
                        tooltip={
                            "always_visible": True,
                            "placement": "top",
                            "template": "{value}%",
                        },
                        className="slider",
                    ),
                ],
                className="ch-edu-slider",
            )
        )
    return html.Details(
        [
            html.Summary("Explore Your Bucket Risk"),
            html.P(
                [
                    "An ",
                    html.Strong("educational illustration"),
                    " with made-up chances, "
                    "independent outcomes and fair odds (no bookmaker margin). It never changes "
                    "your portfolio, the real chances or the reference odds.",
                ],
                className="muted small",
            ),
            html.Div(sliders, className="ch-edu-sliders"),
            html.Button(
                "Reset to 70% / 50% / 30%",
                id=T("edu-reset"),
                n_clicks=0,
                className="ch-btn ghost small",
            ),
            html.Div(id=T("edu-out")),
        ],
        className="ch-details ch-edu",
        open=False,
    )


def explorer_output(ill: Illustration) -> html.Div:
    cards = []
    for b in ill.buckets:
        dots = [html.Span(className="dot") for _ in range(b.legs)]
        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            chip(b.code),
                            html.Span(
                                f"{b.legs} × {pct(b.individual, 0)}", className="muted small"
                            ),
                        ],
                        className="ch-edu-head",
                    ),
                    html.Div(dots, className=f"ch-dots b-{BUCKET_CLASS[b.code]}"),
                    html.Div(
                        [
                            html.Span("All succeed", className="muted small"),
                            html.Span(pct(b.combined, 2), className="ch-edu-big"),
                        ]
                    ),
                    html.Div(
                        className="ch-meter",
                        children=html.Div(
                            className=f"fill b-{BUCKET_CLASS[b.code]}",
                            style={"width": f"{b.combined:.2%}"},
                        ),
                    ),
                    html.Div(
                        f"Fair odds {b.fair_odds:,.2f} · {b.credits} credits would pay "
                        f"{b.fair_payout:,.2f}",
                        className="muted small",
                    ),
                ],
                className="ch-edu-card",
            )
        )
    return html.Div(
        [
            html.Div(cards, className="ch-edu-cards"),
            html.P(
                [
                    "All nine succeed: ",
                    html.Strong(pct(ill.all_nine, 3)),
                    ". Each prediction can look likely while the combined chance is small.",
                ],
                className="small",
            ),
        ],
    )


# ------------------------------------------------------------- analysis
def metric(label: str, value: str, sub: str = "", primary: bool = False) -> html.Div:
    return html.Div(
        [
            html.Span(label, className="ch-metric-label"),
            html.Span(value, className="ch-metric-val"),
            html.Span(sub, className="muted small"),
        ],
        className="ch-metric" + (" primary" if primary else ""),
    )


def metrics_row(ev: PortfolioEvaluation) -> html.Div:
    src = "market" if ev.source.value == "market" else "Diski 9 model"
    return html.Div(
        [
            metric(
                "Chance of getting 100+ credits back",
                pct(ev.p_recover),
                f"{src} estimate",
                primary=True,
            ),
            metric(
                "Something back, but under 100", pct(ev.p_partial), "a payout above 0 and below 100"
            ),
            metric("Nothing back", pct(ev.p_zero), "no bucket succeeds"),
            metric(
                "Expected return",
                f"{ev.expected_gross:,.2f} cr",
                f"{ev.expected_net:+,.2f} net · an average, not a promise",
            ),
        ],
        className="ch-metrics",
    )


def accumulator_table(ev: PortfolioEvaluation, snap: RoundSnapshot) -> html.Div:
    rows = []
    for acc in (*ev.buckets, ev.nine_fold):
        legs = [snap.outcome(k) for k in acc.legs]
        names = (
            "All nine predictions"
            if acc.code == "NINE"
            else "; ".join(
                f"{snap.fixture(o.fixture_id).home} v {snap.fixture(o.fixture_id).away}: "
                f"{outcome_text(o)}"
                for o in legs
            )
        )
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            chip(acc.code),
                            html.Span(f"{acc.stake} credits", className="muted small"),
                        ],
                        className="ch-acc-name",
                    ),
                    html.Div(names, className="ch-acc-legs small"),
                    html.Div(
                        [html.Span("Odds", className="lbl"), f"{acc.combined_odds:,.2f}"],
                        className="ch-acc-num",
                    ),
                    html.Div(
                        [html.Span("Chance", className="lbl"), pct(acc.win_probability, 2)],
                        className="ch-acc-num",
                    ),
                    html.Div(
                        [html.Span("Pays", className="lbl"), credits(acc.payout)],
                        className="ch-acc-num strong",
                    ),
                ],
                className=f"ch-acc b-{BUCKET_CLASS[acc.code]}",
            )
        )
    return html.Div(rows, className="ch-accs")


def states_table(ev: PortfolioEvaluation) -> html.Details:
    head = html.Tr(
        [
            html.Th(x)
            for x in ("Foundation", "Balanced", "Challenger", "Diski 9", "Gross payout", "Chance")
        ]
    )
    body = [
        html.Tr(
            [
                *[html.Td("wins" if w else "—") for w in s.wins],
                html.Td("wins" if all(s.wins) else "—"),
                html.Td(credits(s.gross), className="num"),
                html.Td(pct(s.probability, 3), className="num"),
            ]
        )
        for s in ev.states
    ]
    return html.Details(
        [
            html.Summary("All eight possible outcomes"),
            html.Table([html.Thead(head), html.Tbody(body)], className="ch-table"),
            html.P(
                "The Diski 9 can only win when all three buckets win, so there are eight "
                "combinations, not sixteen.",
                className="muted small",
            ),
        ],
        className="ch-details",
    )


# ------------------------------------------------------------- leaderboards
def weekly_table(score, round_result) -> html.Div:
    cls = round_result.classification
    banner = None
    if cls is RoundClassification.PRACTICE:
        banner = html.Div(
            "Practice round: fewer than five entries, so no championship points "
            "and the championship counter does not move.",
            className="ch-ribbon",
        )
    elif cls is RoundClassification.VOID:
        banner = html.Div(
            "Void round: cancelled after the deadline. Every entry got its 100 "
            "credits back; nothing counts.",
            className="ch-ribbon",
        )
    ranked = [s for s in score.scores if s.rank is not None]
    others = [s for s in score.scores if s.rank is None]
    rows = []
    prev = None
    for s in ranked:
        shared = sum(1 for x in ranked if x.rank == s.rank) > 1
        label = ("=" if shared else "") + str(s.rank)
        status = "Recovered" if s.recovered else "Not recovered"
        rows.append(
            html.Tr(
                [
                    html.Td(label if s.rank != prev or not shared else label, className="num"),
                    html.Td(s.participant_id),
                    html.Td(credits(s.gross), className="num"),
                    html.Td(f"{s.net:+,.2f}", className="num"),
                    html.Td(status, className="ok" if s.recovered else "muted"),
                    html.Td(str(s.points), className="num strong"),
                ],
                className="me" if s.participant_id.startswith("You") else "",
            )
        )
        prev = s.rank
    for s in others:
        label = "Void — Refunded" if s.refunded else "—"
        rows.append(
            html.Tr(
                [
                    html.Td("—", className="num"),
                    html.Td(s.participant_id),
                    html.Td(credits(s.gross), className="num"),
                    html.Td(f"{s.net:+,.2f}", className="num"),
                    html.Td(label, className="muted"),
                    html.Td("0", className="num"),
                ],
                className="refund",
            )
        )
    head = html.Tr(
        [
            html.Th("Rank"),
            html.Th("Player"),
            html.Th("Gross", className="num"),
            html.Th("Net", className="num"),
            html.Th("Status"),
            html.Th("Points", className="num"),
        ]
    )
    return html.Div(
        [
            banner,
            html.Div(
                html.Table([html.Thead(head), html.Tbody(rows)], className="ch-table lb"),
                className="ch-table-wrap",
            ),
        ],
    )


def championship_table(table) -> html.Div:
    rows = []
    for s in table.standings:
        shared = sum(1 for x in table.standings if x.rank == s.rank) > 1
        rows.append(
            html.Tr(
                [
                    html.Td(("=" if shared else "") + str(s.rank), className="num"),
                    html.Td(s.participant_id),
                    html.Td(str(s.points), className="num strong"),
                    html.Td(str(s.rounds_entered), className="num"),
                    html.Td(str(s.recoveries), className="num"),
                    html.Td(str(s.qualifying_top10), className="num"),
                ],
                className="me" if s.participant_id.startswith("You") else "",
            )
        )
    head = html.Tr(
        [
            html.Th("Rank"),
            html.Th("Player"),
            html.Th("Points", className="num"),
            html.Th("Rounds", className="num"),
            html.Th("Recoveries", className="num"),
            html.Th("Top-ten finishes", className="num"),
        ]
    )
    done = table.completed_rounds
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        f"Round {done} of {table.rounds_required} completed", className="strong"
                    ),
                    html.Div(
                        className="ch-total-bar",
                        children=html.Div(
                            className="fill", style={"width": f"{done / table.rounds_required:.0%}"}
                        ),
                    ),
                ],
                className="ch-progress",
            ),
            html.Div(
                html.Table([html.Thead(head), html.Tbody(rows)], className="ch-table lb"),
                className="ch-table-wrap",
            ),
            html.P(
                "Ranked by points, then recoveries, then top-ten finishes; players still level "
                "share the position.",
                className="muted small",
            ),
        ],
    )
