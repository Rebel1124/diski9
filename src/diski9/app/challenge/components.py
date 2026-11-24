"""Reusable Weekly Challenge components (presentation only)."""

from __future__ import annotations

from decimal import Decimal

from dash import dcc, html

from diski9.challenge.config import ChallengeConfig, ProbabilityBand
from diski9.challenge.roundsheet import RoundAvailability, RoundSnapshot, RoundStatus
from diski9.challenge.scoring import POINTS_150_75_V2, RoundClassification
from diski9.challenge.structured import PortfolioEvaluation, SelectionBlock

from ..icons import icon
from .service import key_str

BUCKET_CLASS = {"A": "found", "B": "bal", "C": "chal", "NINE": "nine"}
# Bucket names are structural (C-10, C-15) and identical in every registered
# configuration; tests/test_config_version_guard.py checks that, so presentation code
# needs no configuration lookup for them. Probability bands differ between versions and
# always come from the round's own configuration (band_text, eligible_range_text).
BUCKET_NAME = {"A": "Foundation", "B": "Balanced", "C": "Challenger", "NINE": "The Diski 9"}
MARKET_NAME = {"1X2": "Match result", "BTTS": "Both teams to score", "OU25": "Over/Under 2.5"}
MARKET_SHORT = {"1X2": "Match result", "BTTS": "Both teams score", "OU25": "Total goals"}
OUTCOME_NAME = {
    "HOME": "Home win",
    "DRAW": "Draw",
    "AWAY": "Away win",
    "BTTS_YES": "BTTS: Yes",
    "BTTS_NO": "BTTS: No",
    "OVER_2_5": "Over 2.5 goals",
    "UNDER_2_5": "Under 2.5 goals",
}
OUTCOME_SHORT = {
    "HOME": "Home",
    "DRAW": "Draw",
    "AWAY": "Away",
    "BTTS_YES": "Yes",
    "BTTS_NO": "No",
    "OVER_2_5": "Over 2.5",
    "UNDER_2_5": "Under 2.5",
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
BLOCK_SHORT = {
    SelectionBlock.FIXTURE_TAKEN: "Match used",
    SelectionBlock.BUCKET_FULL: "Bucket full",
    SelectionBlock.WOULD_BLOCK_COMPLETION: "Can't complete",
}


def _pct_number(x: float) -> str:
    return f"{round(x * 100, 6):g}"


def band_text(band: ProbabilityBand) -> str:
    """A bucket's market-probability range in words: "60%–95%" (both ends included),
    "40% to under 60%" (upper end excluded)."""
    lo, hi = _pct_number(band.lower), _pct_number(band.upper)
    if band.lower_inclusive and band.upper_inclusive:
        return f"{lo}%–{hi}%"
    if band.lower_inclusive:
        return f"{lo}% to under {hi}%"
    return f"above {lo}% to {hi}%" + ("" if band.upper_inclusive else " (exclusive)")


def eligible_range_text(config: ChallengeConfig) -> str:
    """The overall eligible market range of a configuration, e.g. "20%–95%"."""
    lo = min(b.band.lower for b in config.buckets)
    hi = max(b.band.upper for b in config.buckets)
    return f"{_pct_number(lo)}%–{_pct_number(hi)}%"


def T(name: str, i: int | str = 0) -> dict:
    """Pattern-matching IDs, so callbacks work whichever page is showing."""
    return {"t": name, "i": i}


def pct(p: float, digits: int = 1) -> str:
    return f"{p:.{digits}%}"


def credits(x) -> str:
    return f"{Decimal(str(x)):,.2f}"


def outcome_text(o) -> str:
    return OUTCOME_NAME.get(str(o.outcome), str(o.outcome))


def page_header(title: str, meta=None) -> html.Div:
    """The one heading used by all four main pages (Match Lab, Weekly Challenge, My
    Challenge, Leaderboards): same element, size, weight, colour and spacing."""
    return html.Div(
        [
            html.H1(title, className="ch-h1"),
            html.Span(meta, className="muted small page-meta") if meta else None,
        ],
        className="ch-title page-head",
    )


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


def structure_table(config: ChallengeConfig) -> html.Div:
    rows = [
        html.Div(
            [
                chip(b.code),
                html.Span(f"{b.selections} predictions"),
                html.Span(band_text(b.band)),
                html.Span(f"{b.credits} credits"),
            ],
            className="ch-struct-row",
        )
        for b in config.buckets
    ]
    rows.append(
        html.Div(
            [
                chip("NINE"),
                html.Span("All nine"),
                html.Span("The whole portfolio"),
                html.Span(f"{config.nine_fold_credits} credits"),
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


BUILD_STEPS = (
    ("layers", "Choose nine different matches",
     "Four Foundation, three Balanced and two Challenger predictions, with one prediction "
     "per match."),
    ("scale", "Compare probabilities and assess your risk",
     "Explore Market, Diski 9 and Your View, and analyse your potential portfolio outcomes. "
     "Market probability determines bucket eligibility."),
    ("circle-check", "Review and submit",
     "Confirm your portfolio before the deadline. You can replace or withdraw it before the "
     "round locks."),
)  # fmt: skip


def build_steps() -> html.Div:
    """How to play: the four steps of building a portfolio (icons with short text)."""
    return html.Div(
        [
            html.H3("Build your portfolio", className="ch-h3"),
            html.Div(
                [
                    html.Div(
                        [
                            icon(name, "ic-lg ch-step-ic"),
                            html.Div(
                                [html.Strong(title), html.Span(text, className="muted small")]
                            ),
                        ],
                        className="ch-build-step",
                    )
                    for name, title, text in BUILD_STEPS
                ],
                className="ch-build-steps",
            ),
        ],
        className="ch-build",
    )


def segment_bar(code: str, filled: int, total: int) -> html.Div:
    return html.Div(
        [html.Span(className="seg on" if i < filled else "seg") for i in range(total)],
        className=f"ch-seg b-{BUCKET_CLASS[code]}",
        role="img",
        **{"aria-label": f"{filled} of {total}"},
    )


# ------------------------------------------------------------- builder
def pct_in_band(p: float, bucket: str | None, config: ChallengeConfig) -> str:
    """One-decimal percentage that never contradicts the bucket: when rounding would
    put a value on the other side of a band boundary (e.g. 59.96% shown as 60.0% in
    Balanced), more decimals are shown."""
    for digits in (1, 2, 3, 4):
        text = f"{p * 100:.{digits}f}%"
        if bucket is None or config.classify(float(text[:-1]) / 100) == bucket:
            return text
    return f"{p * 100:.6f}%"


STATE_CLASS = {
    None: "st-open",
    SelectionBlock.SELECTED: "st-selected",
    SelectionBlock.INELIGIBLE: "st-ineligible",
    SelectionBlock.FIXTURE_TAKEN: "st-fixture_taken",
    SelectionBlock.BUCKET_FULL: "st-bucket_full",
    SelectionBlock.WOULD_BLOCK_COMPLETION: "st-would_block_completion",
}


def outcome_state(
    o, bucket, block, locked: bool, personal=None, *, config: ChallengeConfig
) -> tuple[str, bool, str]:
    """(className, disabled, title) for an outcome button. Every possible tag is
    rendered once and CSS shows the one matching the state class, so selection
    changes update only these three properties (fast in the browser)."""
    if bucket is None and block is None:
        block = SelectionBlock.INELIGIBLE
    selected = block is SelectionBlock.SELECTED
    disabled = locked or (block is not None and not selected)
    cls = "ch-out " + (f"b-{BUCKET_CLASS[bucket]}" if bucket else "b-none")
    cls += " " + STATE_CLASS.get(block, "st-open")
    cls += " is-selected" if selected else ""
    cls += " is-blocked" if disabled else ""
    short = {
        SelectionBlock.SELECTED: f"Selected, {BUCKET_NAME.get(bucket, '')}",
        SelectionBlock.INELIGIBLE: "Not eligible",
        **BLOCK_SHORT,
    }.get(block, BUCKET_NAME.get(bucket, ""))
    title = BLOCK_HELP.get(block) or (
        f"Outside the {eligible_range_text(config)} market range, or the odds don't qualify"
        if block is SelectionBlock.INELIGIBLE
        else "Tap to remove"
        if selected
        else "Tap to add"
    )
    title = f"{outcome_text(o)} ({short}): {title}"
    if personal is not None:
        title += f" · Your View {pct(personal, 1)}"
    return cls, disabled, title


def you_line(o, personal, show_you: bool):
    """The Your View number on an outcome card: the participant's own probability, or
    a clear "= D9" when they have not adjusted this match (Your View then equals the
    unadjusted Diski 9 probability)."""
    if not show_you:
        return None
    if personal is None:
        return html.Span("You = D9", className="ch-out-you same", title="No adjustments for this "
                         "match yet: Your View equals Diski 9")  # fmt: skip
    return html.Span(
        f"You {pct(personal, 1)}",
        className="ch-out-you",
        title="Your View: Goal Model 1.0 with your adjusted expected goals",
    )


def outcome_button(
    o,
    bucket,
    block,
    locked: bool,
    personal=None,
    *,
    id_type: str = "pick",
    show_you: bool = False,
    replace_from: str | None = None,
    config: ChallengeConfig,
) -> html.Button:
    """One outcome card (builder and Match Lab): name, frozen odds, market (Mkt, which
    decides the bucket), Diski 9 (D9) and optionally Your View (You) probabilities,
    bucket label and selection state. Disabled outcomes say why in text with an icon,
    never by colour alone. ``replace_from`` marks a valid one-tap replacement of the
    pick already made on this match (Match Lab)."""
    cls, disabled, title = outcome_state(o, bucket, block, locked, personal, config=config)
    name = BUCKET_NAME[bucket] if bucket else ""
    if replace_from and not locked:
        cls = cls.replace("st-fixture_taken", "st-replace").replace(" is-blocked", "")
        disabled = False
        title = (
            f"{outcome_text(o)} (Replace, {name}): replace your pick on this match ({replace_from})"
        )
    model = (
        pct_in_band(o.model_probability, None, config) if o.model_probability is not None else "—"
    )
    return html.Button(
        [
            html.Span(
                [
                    html.Span(
                        OUTCOME_SHORT.get(str(o.outcome), outcome_text(o)), className="ch-out-name"
                    ),
                    html.Span(f"{o.reference_odds:.2f}", className="ch-odds"),
                ],
                className="ch-out-top",
            ),
            html.Span(
                [
                    html.Span(
                        f"Mkt {pct_in_band(o.market_probability, bucket, config)}",
                        title="Market probability (bookmaker margin removed): sets the bucket",
                    ),
                    html.Span(f"D9 {model}", className="muted", title="Diski 9 (Goal Model 1.0)"),
                    you_line(o, personal, show_you),
                ],
                className="ch-out-nums",
            ),
            # one state tag: its label and icon come from the button's state and bucket
            # classes (style.css), so a selection change updates only className, disabled
            # and title; the same words are in the title / aria-label for assistive tech
            html.Span(className="ch-tag ch-tag-s", **{"aria-hidden": "true"}),
        ],
        id={"t": id_type, "k": key_str(o.key)},
        n_clicks=0,
        disabled=disabled,
        className=cls,
        title=title,
        **{"aria-label": title},
    )


def fixture_card(
    fx, outs, assess, blocks, local, locked, personal=None, *, config: ChallengeConfig
) -> html.Div:
    personal = personal or {}
    adjusted = any(o.key in personal for o in outs)  # Your View shown where it differs
    by_market: dict[str, list] = {}
    for o in outs:
        by_market.setdefault(str(o.market), []).append(o)
    groups = []
    for m in ("1X2", "BTTS", "OU25"):
        items = by_market.get(m, [])
        groups.append(
            html.Div(
                [
                    html.Div(MARKET_SHORT[m], className="ch-mkt"),
                    html.Div(
                        [
                            outcome_button(
                                o,
                                assess[o.key].bucket if assess[o.key].eligible else None,
                                blocks.get(o.key),
                                locked,
                                personal.get(o.key),
                                show_you=adjusted,
                                config=config,
                            )
                            for o in items
                        ]
                        or [html.Span("—", className="muted small")],
                        className=f"ch-outs n{max(len(items), 1)}",
                    ),
                ],
                className=f"ch-mkt-group m-{m.lower()}",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(fx.league, className="ch-league"),
                            html.Span(local(fx.kickoff), className="muted small"),
                        ],
                        className="ch-fx-meta",
                    ),
                    html.Div(f"{fx.home} v {fx.away}", className="ch-fx-teams"),
                    dcc.Link(
                        ["Match Lab ", icon("arrow-right", "ic-sm")],
                        href=f"/?fixture={fx.fixture_id}",
                        className="ch-lab-link",
                        title="Analyse this match in the Match Lab",
                    ),
                ],
                className="ch-fx-head",
            ),
            html.Div(groups, className="ch-mkts"),
        ],
        className="ch-fx",
    )


def bucket_line(stat) -> html.Div:
    """Combined chance and payout for a bucket's selections so far."""
    if stat.combined_probability is None:
        return html.Div("No picks yet", className="muted small ch-bstat")
    scope = "" if stat.complete else f" (so far: {stat.selected} of {stat.required} picks)"
    return html.Div(
        [
            html.Span(["All succeed ", html.Strong(pct(stat.combined_probability, 1))]),
            html.Span(["pays ", html.Strong(credits(stat.payout))]),
            html.Span(scope, className="muted") if scope else None,
        ],
        className="ch-bstat small",
    )


def tracker(
    stats,
    nine,
    picks_by_bucket,
    label,
    prob,
    message,
    complete_ev,
    can_continue,
    locked,
    review_enabled_label="Review & Submit →",
) -> html.Div:
    rows = []
    for st in stats:
        picks = picks_by_bucket.get(st.code, [])
        items = [
            html.Li(
                [
                    html.Div(
                        [
                            html.Span(label(o), className="ch-pick-fx"),
                            html.Span(
                                f"{outcome_text(o)} · {pct(prob(o), 1)} · {o.reference_odds:.2f}",
                                className="muted",
                            ),
                        ],
                        className="ch-pick-text",
                    ),
                    html.Button(
                        icon("x"),
                        id={"t": "remove", "k": key_str(o.key)},
                        n_clicks=0,
                        className="ch-x",
                        title="Remove this prediction",
                        disabled=locked,
                        **{"aria-label": f"Remove {outcome_text(o)}"},
                    ),
                ]
            )
            for o in picks
        ]
        rows.append(
            html.Details(
                [
                    html.Summary(
                        [
                            chip(st.code),
                            html.Span(f"{st.selected}/{st.required}", className="ch-count"),
                            html.Span(f"{st.credits} credits", className="muted small"),
                        ],
                        className="ch-trk-head",
                    ),
                    segment_bar(st.code, min(st.selected, st.required), st.required),
                    bucket_line(st),
                    html.Ul(items, className="ch-picks") if items else None,
                ],
                open=True,
                className=f"ch-trk-row b-{BUCKET_CLASS[st.code]}",
            )
        )
    rows.append(
        html.Div(
            [
                html.Div(
                    [
                        chip("NINE"),
                        html.Span(f"{nine.selected}/9", className="ch-count"),
                        html.Span(f"{nine.credits} credits", className="muted small"),
                    ],
                    className="ch-trk-head",
                ),
                bucket_line(nine),
            ],
            className="ch-trk-row b-nine",
        )
    )
    total = nine.selected
    summary = None
    if complete_ev is not None:
        summary = html.Div(
            [
                html.Div(
                    [
                        html.Span("Get 100+ back", className="muted small"),
                        html.Strong(pct(complete_ev.p_recover, 1), className="ch-big"),
                    ]
                ),
                html.Div(
                    [
                        html.Span("Expected gross", className="muted small"),
                        html.Strong(f"{complete_ev.expected_gross:,.2f}", className="ch-big"),
                    ]
                ),
            ],
            className="ch-trk-summary",
        )
    mini = html.A(
        [
            html.Span(
                f"{BUCKET_NAME[s.code][0]} {s.selected}/{s.required}",
                className=f"mini-{BUCKET_CLASS[s.code]}",
            )
            for s in stats
        ]
        + [html.Strong(f"{total}/9"), html.Span("View ▴", className="muted")],
        href="#ch-tracker-top",
        className="ch-mini",
        **{"aria-label": "Portfolio progress"},
    )
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
            summary,
            html.Div(message, className="ch-trk-msg", role="status", **{"aria-live": "polite"}),
            html.Div(
                [
                    html.Button(
                        "Clear all",
                        id=T("clear"),
                        n_clicks=0,
                        className="ch-btn ghost",
                        disabled=not total or locked,
                    ),
                    html.Button(
                        review_enabled_label,
                        id={"t": "nav", "to": "review", "i": "tracker"},
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


def source_selector(value: str) -> html.Div:
    return html.Div(
        [
            dcc.RadioItems(
                id=T("source"),
                value=value,
                className="segmented ch-source",
                options=[
                    {"label": "Market", "value": "market"},
                    {"label": "Diski 9", "value": "model"},
                    {"label": "Your View", "value": "personal"},
                ],
                inline=True,
            ),
            html.Details(
                [
                    html.Summary("What do these mean?"),
                    html.Ul(
                        [
                            html.Li(
                                [
                                    html.Strong("Market: "),
                                    "the bookmakers' consensus "
                                    "chance with their margin removed. It sets the buckets.",
                                ]
                            ),
                            html.Li([html.Strong("Diski 9: "), "Goal Model 1.0, unadjusted."]),
                            html.Li(
                                [
                                    html.Strong("Your View: "),
                                    "your own expected goals from "
                                    "the Match Lab; matches you haven't adjusted use Diski 9.",
                                ]
                            ),
                            html.Li(
                                "Matches are treated as independent. Every chance is an "
                                "estimate; payouts never change with the source."
                            ),
                        ]
                    ),
                ],
                className="ch-details small",
            ),
        ],
        className="ch-source-box",
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
                f"{ev.expected_gross:,.2f}",
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
    for s in ranked:
        shared = sum(1 for x in ranked if x.rank == s.rank) > 1
        status = "Recovered" if s.recovered else "Not recovered"
        rows.append(
            html.Tr(
                [
                    html.Td(rank_cell(s.rank, shared), className="num rank"),
                    html.Td(s.participant_id),
                    html.Td(credits(s.gross), className="num"),
                    html.Td(f"{s.net:+,.2f}", className="num"),
                    html.Td(status, className="ok" if s.recovered else "muted"),
                    html.Td(str(s.points), className="num strong"),
                ],
                className="me" if s.participant_id.startswith("You") else "",
            )
        )
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
            html.Th("Rank", className="num"),
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
                    html.Td(rank_cell(s.rank, shared), className="num rank"),
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
            html.Th("Rank", className="num"),
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


def you_summary(rank: str, main: str, sub: str) -> html.Div:
    return html.Div(
        [
            html.Span("You (demo)", className="muted small"),
            html.Strong(rank, className="ch-you-rank"),
            html.Span(main),
            html.Span(sub, className="muted small"),
        ],
        className="ch-you",
    )


MEDAL = {1: ("gold", "1st"), 2: ("silver", "2nd"), 3: ("bronze", "3rd")}
RANK_ICON = {1: "trophy", 2: "medal", 3: "medal"}  # gold trophy, silver and bronze medals


def rank_icon(rank: int | None, extra: str = "") -> html.Span | None:
    """The top-three icon for a competition rank (shared ranks get the same icon; no
    position is manufactured, e.g. ranks 1, 1, 3 show two trophies and a bronze)."""
    if rank not in RANK_ICON:
        return None
    return icon(RANK_ICON[rank], f"rank-ic {MEDAL[rank][0]} {extra}".strip())


def rank_cell(rank: int, shared: bool):
    """Leaderboard rank: the numeric label (kept for clarity) with a top-three icon."""
    label = ("=" if shared else "") + str(rank)
    ic = rank_icon(rank)
    if ic is None:
        return label
    title = f"{MEDAL[rank][1]} place" + (" (shared)" if shared else "")
    return html.Span([ic, html.Span(label)], className="rank-wrap", title=title)


def tone(value) -> str:
    """Performance colour class for a signed amount (always also written with its sign):
    ``pos-val`` (green), ``neg-val`` (red) or ``zero`` (neutral)."""
    if value is None or value == 0:
        return "zero"
    return "pos-val" if value > 0 else "neg-val"


def stat_card(label: str, category: str, value, sub="", value_cls: str = "") -> html.Div:
    """A metric card in the Build Portfolio card style (Phase 6C.5 Stage E): a tinted
    header in the metric's category colour, then the value and a supporting line. The
    category colour identifies the metric; a performance colour (``value_cls``) applies
    to the value only, never to the header."""
    return html.Div(
        [
            html.Div(label, className="me-stat-head"),
            html.Div(
                [
                    html.Span(value, className=f"me-stat-val {value_cls}".strip()),
                    html.Span(sub, className="me-stat-sub") if sub else None,
                ],
                className="me-stat-body",
            ),  # fmt: skip
        ],
        className=f"me-stat cat-{category}",
    )


def podium(rows, value_label: str | None = None) -> html.Div | None:
    """Top three *positions* by competition rank. Tied players share their position;
    nobody is reordered or split to force three places (ranks 1, 1, 3 show 1st with
    two players and 3rd, with no 2nd). With ``value_label`` each row's detail is a bare
    value, labelled once per card (compact podium, Phase 6C.5 Stage E)."""
    places = {}
    for rank, name, detail in rows:
        if rank in MEDAL:
            places.setdefault(rank, []).append((name, detail))
    if not places:
        return None
    cols = []
    for rank in sorted(places):
        cls, label = MEDAL[rank]
        cols.append(
            html.Div(
                [
                    html.Div(
                        [
                            rank_icon(rank, "ic-lg"),
                            label + (" (shared)" if len(places[rank]) > 1 else ""),
                        ],
                        className="ch-pod-rank",
                    ),
                    html.Span(value_label, className="ch-pod-col") if value_label else None,
                    *[
                        html.Div(
                            [
                                html.Strong(n),
                                html.Span(
                                    d, className="ch-pod-val" if value_label else "muted small"
                                ),
                            ],
                            className="ch-pod-name",
                        )
                        for n, d in places[rank]
                    ],  # fmt: skip
                ],
                className=f"ch-pod {cls}" + (" compact" if value_label else ""),
            )
        )
    return html.Div(
        cols,
        className="ch-podium" + (" compact" if value_label else ""),
        **{"aria-label": "Top three positions"},
    )
