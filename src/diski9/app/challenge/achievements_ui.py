"""My Challenge: Achievements (Phase 7, CP3). Presentation only.

Everything shown comes from the accepted backend service
``diski9.backend.services.achievements``: the six counts, the total, the level and the
progress (including which categories are still missing). Nothing here evaluates a
badge, counts badges or decides a level. The viewer comes from the server-side
principal (``persist.participant``). Development data appears only with the server's
own ``Backend.show_development`` setting, never a browser value. Each view is read
afresh when it opens, so a republished correction (including a lost badge or a lower
level) is never hidden by stale state.

An ``AchievementIntegrityError`` shows a clear "unavailable" state, never a Beginner
level or zero counts. Diagnostic details are not shown to participants.
"""

from __future__ import annotations

from dash import dcc, html

from diski9.backend.services import achievements as ac

from .. import icons
from . import components as c
from . import leaderboards_ui as lbu
from . import persist

#: presentation of each badge: (name, icon, colour class, qualification text)
BADGE_INFO = {
    ac.Badge.FOUNDATION_FUNDI: ("Foundation Fundi", "landmark", "found",
                                "All four Foundation selections correct in one round."),
    ac.Badge.BALANCED_BRAWLER: ("Balanced Brawler", "scale", "bal",
                                "All three Balanced selections correct in one round."),
    ac.Badge.CHALLENGER_CHAMP: ("Challenger Champ", "mountain", "chal",
                                "Both Challenger selections correct in one round."),
    ac.Badge.GOALS_GURU: ("Goals Guru", "goal", "goals",
                          "At least three correct Over/Under 2.5 Goals selections in one round."),
    ac.Badge.BTTS_BONANZA: ("BTTS Bonanza", "users", "btts",
                            "At least three correct Both Teams to Score (Yes or No) "
                            "selections in one round."),
    ac.Badge.DRAW_DYNAMO: ("Draw Dynamo", "equal", "draw",
                           "At least two correct draw selections in one round."),
}  # fmt: skip
GROUPS = (
    ("Bucket achievements", "Perfect buckets: every selection in the bucket correct.",
     (ac.Badge.FOUNDATION_FUNDI, ac.Badge.BALANCED_BRAWLER, ac.Badge.CHALLENGER_CHAMP)),
    ("Market achievements", "Correct selections in one market, across all nine predictions.",
     (ac.Badge.GOALS_GURU, ac.Badge.BTTS_BONANZA, ac.Badge.DRAW_DYNAMO)),
)  # fmt: skip
LEVEL_INFO = {ac.Level.BEGINNER: ("sprout", "beginner"), ac.Level.SEMI_PRO: ("award", "semi"),
              ac.Level.PRO: ("crown", "pro")}  # fmt: skip
THRESHOLD = dict(ac.LEVEL_THRESHOLDS)  # from the backend: never restated here

UNAVAILABLE = (
    "Your achievements are temporarily unavailable. Your results are safe; please try again later."
)


def _empty(text: str) -> list:
    return [html.Div(text, className="ch-ribbon")]


def rule_text() -> str:
    semi, pro = THRESHOLD[ac.Level.SEMI_PRO], THRESHOLD[ac.Level.PRO]
    return (
        f"Levels need badges in every category: at least {semi} of each of the six badges for "
        f"Semi-Pro, and at least {pro} of each for Pro. A large total in some categories "
        "does not make up for a category with none."
    )


# ------------------------------------------------------------------ the tab
def section(service, local) -> list:
    """The Achievements tab: the stream selector (only when there is a choice) and
    the body."""
    b = persist.backend_of(service)
    if b is None:
        return _empty("Achievements need the competition database.")
    if persist.participant(service) is None:
        return _empty("Sign in to see your achievements.")
    from diski9.backend.services import leaderboards as lb

    try:
        streams = lb.stream_options(b.engine, include_development=b.show_development)
    except Exception:  # noqa: BLE001
        return lbu.unavailable(UNAVAILABLE)
    stream = "beta" if "beta" in streams else streams[0]
    stream_ctl = dcc.Dropdown(
        id=c.T("me-astream"), value=stream, clearable=False, searchable=False,
        className="dropdown lb-stream-select",
        options=[{"label": lbu.STREAM_LABEL[s], "value": s} for s in streams],
    )  # fmt: skip
    return [
        html.Div(
            html.Div(stream_ctl, style=None if len(streams) > 1 else {"display": "none"}),
            className="lb-controls me-ach-controls",
        ),
        dcc.Loading(html.Div(id=c.T("me-abody"), children=body(service, stream)), type="dot"),
    ]


def body(service, stream: str) -> list:
    b = persist.backend_of(service)
    p = persist.participant(service)
    if b is None or p is None:
        return _empty("Sign in to see your achievements.")
    try:
        a = ac.my_achievements(b.engine, p, stream=stream,
                               include_development=b.show_development)  # fmt: skip
    except Exception:  # noqa: BLE001 - integrity or any failure: never a misleading view
        return unavailable_view()
    if a is None:
        return _empty("Sign in to see your achievements.")
    return view(a)


def unavailable_view() -> list:
    return [
        html.Div(
            [icons.icon("alert", "ic-lg"), html.Div([html.Strong("Achievements unavailable"),
                                                    html.P(UNAVAILABLE, className="small")])],
            className="ch-card ach-unavailable", role="status",
        )
    ]  # fmt: skip


# ------------------------------------------------------------------ presentation
def view(a: ac.Achievements) -> list:
    """The whole Achievements view for one backend result."""
    return [summary(a), *[group(a, *g) for g in GROUPS], html.P(note(), className="muted small")]


def note() -> str:
    return (
        "Badges come from official published results of competitive rounds. Practice and "
        "void rounds, refunded entries and rounds awaiting results do not count, and a "
        "corrected result can add or remove a badge. Levels recognise badges collected "
        "across categories; they are not a rating of skill. Achievements are private to you "
        "and never affect credits, rankings or championship points."
    )


def emblem(level: ac.Level, size: str = "") -> html.Div:
    ic, cls = LEVEL_INFO[level]
    return html.Div(icons.icon(ic), className=f"ach-emblem lv-{cls} {size}".strip(),
                    **{"aria-hidden": "true"})  # fmt: skip


def summary(a: ac.Achievements) -> html.Div:
    pr = a.progress
    if pr.next_level is None:
        head = "Top level reached"
        line = ("You have at least "
                f"{THRESHOLD[ac.Level.PRO]} of every badge. Keep collecting: badges keep "
                "counting, with no further level to unlock.")  # fmt: skip
    else:
        head = f"Next: {pr.next_level}"
        if pr.missing:
            names = ", ".join(BADGE_INFO[b][0] for b in pr.missing)
            line = (f"{pr.categories_met} of 6 categories have {pr.target} or more. "
                    f"Still needed: {names}.")  # fmt: skip
        else:  # pragma: no cover - a level below Pro always has a missing category
            line = ""
    segments = [
        html.Span(className="ach-seg" + ("" if b in pr.missing else " met"),
                  title=BADGE_INFO[b][0])
        for b in ac.BADGES
    ]  # fmt: skip
    rounds = lbu.plural(a.eligible_rounds, "eligible round", "eligible rounds")
    lv = LEVEL_INFO[a.level][1]
    return html.Div(
        [
            html.Div(
                [
                    emblem(a.level, "lg"),
                    html.Div(
                        [
                            html.Div("Your level", className="ach-kicker"),
                            html.Div(str(a.level), className=f"ach-level lv-{lv}"),
                            html.Div([html.Strong(f"{a.total:,}"),
                                      " badges earned · " + rounds], className="small"),
                        ]
                    ),  # fmt: skip
                    lbu.stream_badge(a.stream),
                ],
                className="ach-head",
            ),
            html.Div(
                [
                    html.Div([html.Strong(head)], className="ach-next"),
                    html.Div(segments, className="ach-segs",
                             **{"aria-label": f"{pr.categories_met} of 6 categories complete"}),
                    html.P(line, className="small"),
                    html.P(rule_text(), className="muted small"),
                ],
                className="ach-progress",
            ),  # fmt: skip
            html.Div("You have not earned a badge yet. Badges appear here once official "
                     "results of a competitive round you entered are published.",
                     className="ch-ribbon small") if a.eligible_rounds == 0 else None,
        ],
        className="ch-card ach-summary",
    )  # fmt: skip


def group(a: ac.Achievements, title: str, sub: str, badges) -> html.Div:
    return html.Div(
        [
            html.Div([html.H2(title, className="ch-h2"), html.Span(sub, className="muted small")],
                     className="ach-group-head"),
            html.Div([card(a, b) for b in badges], className="ach-grid"),
        ],
        className="ach-group",
    )  # fmt: skip


def card(a: ac.Achievements, badge: ac.Badge) -> html.Div:
    name, ic, cls, rule = BADGE_INFO[badge]
    n = a.counts[badge]
    pr = a.progress
    if pr.next_level is None:
        prog, frac, state = "Pro target met", 1.0, " met"
    else:
        target = pr.target
        met = badge not in pr.missing
        prog = (f"{pr.next_level} target met" if met
                else f"{min(n, target)} of {target} for {pr.next_level}")  # fmt: skip
        frac, state = min(n, target) / target, " met" if met else ""
    return html.Div(
        [
            html.Div(
                [
                    html.Div(icons.icon(ic), className="ach-badge-ic", **{"aria-hidden": "true"}),
                    html.Div(
                        [
                            html.Div(name, className="ach-badge-name"),
                            html.Div(rule, className="ach-badge-rule small"),
                        ]
                    ),
                    html.Div(
                        [
                            html.Span(f"{n:,}", className="ach-count"),
                            html.Span("earned", className="muted small"),
                        ],
                        className="ach-count-wrap",
                    ),
                ],
                className="ach-card-top",
            ),  # fmt: skip
            html.Div(
                [
                    html.Div(
                        html.Div(className="ach-bar-fill", style={"width": f"{frac:.0%}"}),
                        className="ach-bar",
                    ),
                    html.Span(
                        [icons.icon("check", "ic-sm") if state else None, " " + prog],
                        className="ach-prog small",
                    ),
                ],
                className="ach-card-foot",
            ),  # fmt: skip
        ],
        className=f"ach-card b-{cls}{state}" + (" none" if n == 0 else ""),
    )


# ------------------------------------------------------------------ History detail
def chips(badges) -> html.Div | None:
    """Small chips for the badges one round earned (from ``my_round_badges``)."""
    if not badges:
        return None
    return html.Div(
        [html.Span("Badges earned:", className="muted small")]
        + [html.Span([icons.icon(BADGE_INFO[b][1], "ic-sm"), " " + BADGE_INFO[b][0]],
                     className=f"ach-chip b-{BADGE_INFO[b][2]}") for b in badges],
        className="ach-chips",
    )  # fmt: skip


def round_chips(service, round_id, stream: str):
    """The History detail's badge chips for one of the viewer's rounds: the round's
    authoritative published result (also while it is under review)."""
    b = persist.backend_of(service)
    p = persist.participant(service)
    if b is None or p is None:
        return None
    try:
        r = ac.my_round_badges(b.engine, p, round_id, stream=stream,
                               include_development=b.show_development)  # fmt: skip
    except Exception:  # noqa: BLE001
        return html.P("Badges for this round are temporarily unavailable.",
                      className="muted small")  # fmt: skip
    return chips(r.badges) if r is not None else None


__all__ = ["body", "chips", "round_chips", "section", "unavailable_view", "view"]
