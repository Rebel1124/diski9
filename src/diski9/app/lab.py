"""The Match Lab and the statistical baseline (Engine 3.0, Goal Model 1.0).

"We calculate the probabilities. You analyse the match. You make the call."

Detail panel for a selected fixture:

  Heading          fixture, competition, kickoff, market
  The Match Lab    A. Statistical baseline - estimated goals and the selected
                      market's probabilities (with "How it's calculated")
                   B. Match context - Form Score, recent goals record,
                      head-to-head, league positions (never change the model)
                   C. Other factors to consider - an educational checklist
                   D. Your adjustments - estimated-goal sliders, recalculated
                      probabilities for all markets, reset
  Bookmaker card   odds, raw implied, margin, market-implied probabilities and a
                   comparison with the model baseline / the user's estimate

Pure rendering functions; callbacks live in ``app.py``. User adjustments are a
plain dict passed in from the browser's memory store and are never persisted.
"""

from __future__ import annotations

import math
from typing import Any

from dash import dcc, html

from diski9.api_football.markets import Outcome
from diski9.screener import goal_model as gm

from .data import LEAGUE_SHORT, MARKET_KEYS, MARKET_OF, OddsView, ScreenerData, goals2, pct1
from .views import (
    FORM_TOOLTIP,
    LIMITED_GOALS,
    MARKET_TITLE,
    _market_card,
    accordion,
    benchmark_explanation,
    card_head,
    form_benchmark_block,
    form_breakdown_table,
    form_tile,
    goals_breakdown_table,
    h2h_section,
    info,
    league_baseline_block,
    matches_section,
    pill,
    positions_section,
    record_tile,
    sequence,
    venue_context_block,
)

ADJUST_MAX = 10.0  # largest estimated-goal value a user can type
SLIDER_STEP = 0.05
OUTCOME_KEY = {
    Outcome.HOME: "home",
    Outcome.DRAW: "draw",
    Outcome.AWAY: "away",
    Outcome.BTTS_YES: "btts_yes",
    Outcome.BTTS_NO: "btts_no",
    Outcome.OVER_25: "over",
    Outcome.UNDER_25: "under",
}
ALL_MARKETS = ("1X2", "BTTS", "OU25")
CONTEXT_NOTE = (
    "Form, league position and head-to-head results provide useful context, but some of this "
    "information may already be reflected in the model. Avoid counting the same information "
    "twice."
)
ADJUST_NOTE = (
    "Changing estimated goals changes the probability of different scorelines. Increasing a "
    "team's estimated goals will generally increase its chance of winning, but the effect on "
    "BTTS and Over/Under depends on both teams."
)
ESTIMATED_GOALS_HELP = (
    "Estimated goals are the model's expected number of goals for each team in this match, "
    "calculated from goals scored and conceded in this season's league matches and the "
    "league's home and away scoring rates. They are not shot-based xG."
)
CATEGORIES = [
    (
        "squad",
        "Squad & Availability",
        ["Injuries", "Suspensions", "Expected starting line-ups", "Transfers and squad changes"],
    ),
    (
        "fitness",
        "Fitness & Scheduling",
        ["Fixture congestion", "Rest days", "Travel demands", "Squad rotation"],
    ),
    (
        "tactics",
        "Tactics & Management",
        [
            "Managerial changes",
            "Tactical changes",
            "Changes in playing style",
            "Relevant tactical matchups",
        ],
    ),
    (
        "conditions",
        "Match Conditions & Motivation",
        [
            "Weather and playing conditions",
            "Unusual venues or home advantage",
            "Title or relegation circumstances",
            "Competition motivation and other match-specific circumstances",
        ],
    ),
]
CATEGORY_KEYS = tuple(k for k, _, _ in CATEGORIES)
CATEGORY_MAX = 2.0  # largest +/- adjustment one category can carry
NOTE_MAX = 280
FACTORS_NOTE = (
    "These factors are not automatically included in the statistical model. You can research "
    "them independently and choose whether they justify adjusting either team's estimated goals."
)
FACTORS_CAUTION = (
    "Some factors may overlap with recent match results. Avoid counting the same information twice."
)
SIDES = ("home", "away")
CONTEXT_MAX = 1.0  # Section B guardrail: +/- 1 goal (not a validated effect size)
CONTEXT_ADJUST_NOTE = (
    "Recent form, league position and head-to-head results can help you assess a match. "
    "However, some of this information is already reflected in the model's goal estimates. "
    "Only adjust if you believe the context reveals something the model has not fully captured."
)


# ------------------------------------------------------------ user state
# Per fixture, in the browser's memory store only:
#   {"cats": {category: {"note": str, "home": float, "away": float}},
#    "manual": {"home": float, "away": float}}
# Your estimate = model baseline (rounded to 0.01) + sum of category adjustments
#                 + additional manual adjustment, kept within 0-10 goals.
def new_state() -> dict:
    return {
        "context": {"note": "", "home": 0.0, "away": 0.0},
        "cats": {k: {"note": "", "home": 0.0, "away": 0.0} for k in CATEGORY_KEYS},
        "manual": {"home": 0.0, "away": 0.0},
    }


def baseline_rounded(r: dict) -> dict:
    eg = r["goal_model"]["estimated_goals"]
    return {s: round(eg[s], 2) for s in SIDES}


def normalise_state(stored: dict | None, base_r: dict | None = None) -> dict:
    """A complete, independent copy of a fixture's state (handles missing keys and the
    earlier {"home": final, "away": final} format)."""
    state = new_state()
    if not stored:
        return state
    if "cats" not in stored and "manual" not in stored and "context" not in stored:
        if base_r:
            for s in SIDES:  # earlier format: final estimates only
                if s in stored:
                    state["manual"][s] = round(float(stored[s]) - base_r[s], 2)
        return state
    for k in CATEGORY_KEYS:
        c = (stored.get("cats") or {}).get(k) or {}
        state["cats"][k] = {
            "note": str(c.get("note") or "")[:NOTE_MAX],
            "home": float(c.get("home") or 0.0),
            "away": float(c.get("away") or 0.0),
        }
    ctx = stored.get("context") or {}
    state["context"] = {
        "note": str(ctx.get("note") or "")[:NOTE_MAX],
        "home": float(ctx.get("home") or 0.0),
        "away": float(ctx.get("away") or 0.0),
    }
    for s in SIDES:
        state["manual"][s] = float((stored.get("manual") or {}).get(s) or 0.0)
    return state


def category_total(state: dict, side: str) -> float:
    return round(sum(state["cats"][k][side] for k in CATEGORY_KEYS), 2)


def context_total(state: dict, side: str) -> float:
    return round(state["context"][side], 2)


def has_adjustment(state: dict | None) -> bool:
    if not state:
        return False
    return any(
        abs(state["manual"][s]) > 1e-9
        or abs(category_total(state, s)) > 1e-9
        or abs(context_total(state, s)) > 1e-9
        for s in SIDES
    )


def is_empty(state: dict) -> bool:
    notes = [state["context"]["note"], *(state["cats"][k]["note"] for k in CATEGORY_KEYS)]
    return not has_adjustment(state) and not any(notes)


def breakdown(base_r: dict, state: dict) -> dict:
    """Per side: baseline, Section B (match context), Section C total, manual adjustment
    and the final estimate (kept within 0-10 goals; ``clipped`` says when that limit
    applied)."""
    out = {}
    for s in SIDES:
        ctx = context_total(state, s)
        cats = category_total(state, s)
        raw = round(base_r[s] + ctx + cats + state["manual"][s], 2)
        final = round(min(max(raw, 0.0), ADJUST_MAX), 2)
        out[s] = {
            "base": base_r[s],
            "context": ctx,
            "cats": cats,
            "manual": round(state["manual"][s], 2),
            "raw": raw,
            "final": final,
            "clipped": final != raw,
        }
    return out


def user_estimates(r: dict, state: dict | None) -> dict | None:
    """Final user estimates, or None when nothing is adjusted (the model is shown)."""
    if not has_adjustment(state):
        return None
    b = breakdown(baseline_rounded(r), state)
    return {s: b[s]["final"] for s in SIDES}


def adjustment_text(x: float) -> str:
    """Category adjustment as shown in its box: 0.00, -0.15, 0.05 (two decimals)."""
    return "0.00" if abs(x) < 0.005 else f"{x:.2f}"


def signed_text(x: float) -> str:
    """Section B box value with an explicit sign: +0.15, -0.20, 0.00."""
    return "0.00" if abs(x) < 0.005 else f"{x:+.2f}"


def signed(x: float) -> str:
    return "0.00" if abs(x) < 0.005 else f"{x:+.2f}"


def slider_max(baseline: float, current: float | None = None) -> float:
    """Slider range: at least 0-5 goals and always above the baseline and the current
    value (the model's baseline is never capped)."""
    top = max(baseline, current or 0.0)
    return float(min(ADJUST_MAX, max(5.0, math.ceil(top + 1.0))))


def pp(delta: float) -> str:
    """Percentage-point change, e.g. '+6.0 pp'; '0.0 pp' when unchanged."""
    v = round(delta * 100, 1)
    return "0.0 pp" if v == 0 else f"{v:+.1f} pp"


# ----------------------------------------------------------- A. baseline
def _eg_tile(team: str, value: float, note: str | None) -> html.Div:
    return html.Div(
        [
            html.Div(team, className="tile-team"),
            html.Div(
                [
                    html.Span(goals2(value), className="tile-value"),
                    html.Span("estimated goals", className="tile-unit"),
                ],
                className="tile-score",
            ),
            html.Div(note, className="muted small") if note else None,
        ],
        className="tile eg-tile",
    )


def role_tag(text: str, kind: str) -> html.Span:
    """Keeps the four kinds of information apart: model estimate, context, your
    research / assumptions and market."""
    return html.Span(text, className=f"role-tag role-{kind}")


def prob_bars(probs: dict, market: str, cls: str = "") -> html.Div:
    rows = []
    for key, label in MARKET_KEYS[market]:
        p = probs[key]
        rows.append(
            html.Div(
                [
                    html.Span(label, className="bar-label"),
                    html.Div(
                        html.Div(className="bar-fill", style={"width": f"{p * 100:.1f}%"}),
                        className="bar-track",
                        **{"aria-hidden": "true"},
                    ),
                    html.Span(pct1(p), className="bar-value"),
                ],
                className="bar-row",
            )
        )
    return html.Div(rows, className=f"prob-bars {cls}".strip())


def baseline_section(r: dict, market: str) -> html.Div:
    g = r["goal_model"]
    f = r["fixture"]
    head = html.Div(
        [
            html.Span("A. Statistical baseline", className="lab-step"),
            role_tag("Model estimate", "model"),
            info(ESTIMATED_GOALS_HELP, "About estimated goals"),
        ],
        className="label-row",
    )
    if not g.get("available"):
        return html.Div(
            [head, html.Div(g.get("message"), className="unavailable")],
            className="lab-section lab-baseline",
        )
    only = set(g.get("league_average_only") or [])
    notes = {
        side: "League average only: no league matches yet this season" if side in only else None
        for side in ("home", "away")
    }
    early = (
        html.P(
            "Early season: at least one team has played fewer than five league matches, so the "
            "estimates still lean heavily on league averages.",
            className="muted small limited-note",
        )
        if g.get("early_season")
        else None
    )
    return html.Div(
        [
            head,
            html.Div(
                [
                    _eg_tile(f["home"], g["estimated_goals"]["home"], notes["home"]),
                    _eg_tile(f["away"], g["estimated_goals"]["away"], notes["away"]),
                ],
                className="tiles",
            ),
            html.Div(
                [
                    html.Span(MARKET_TITLE[market], className="label"),
                    html.Span("Diski 9 model probabilities", className="muted small"),
                ],
                className="label-row",
            ),
            prob_bars(g["probabilities"], market),
            early,
            html.P(
                "Calculated from this season's league goals scored and conceded, adjusted for "
                "the opponent and the league's home and away scoring. Not adjusted for team "
                "news.",
                className="muted small",
            ),
            html.Div([model_calculation(r)], className="acc-group"),
        ],
        className="lab-section lab-baseline",
    )


def model_calculation(r: dict) -> html.Details:
    """The inputs and arithmetic of Goal Model 1.0 for this fixture."""
    g = r["goal_model"]
    L, f = g["league"], r["fixture"]
    p = g["model"]["parameters"]

    def team_rows(side: str, name: str) -> list:
        t = g[f"{side}_team"]
        rec = t["record"]
        return [
            html.Tr([html.Td(name, colSpan=2, className="grid-sub")]),
            html.Tr(
                [
                    html.Td("Home: played · scored · conceded"),
                    html.Td(
                        f"{rec['home_played']} · {rec['home_scored']} · {rec['home_conceded']}",
                        className="num",
                    ),
                ]
            ),
            html.Tr(
                [
                    html.Td("Away: played · scored · conceded"),
                    html.Td(
                        f"{rec['away_played']} · {rec['away_scored']} · {rec['away_conceded']}",
                        className="num",
                    ),
                ]
            ),
            html.Tr(
                [
                    html.Td("Strength (1.00 = league average)"),
                    html.Td(f"{t['strength']:.3f}", className="num"),
                ]
            ),
            html.Tr(
                [
                    html.Td("Goal tempo (1.00 = league average)"),
                    html.Td(f"{t['tempo']:.3f}", className="num"),
                ]
            ),
        ]

    prior = (
        f"{L['current_matches']} league matches this season, plus {p['m0']:g} pseudo-matches at "
        f"last season's averages ({L['previous_home_per_match']:.2f} home, "
        f"{L['previous_away_per_match']:.2f} away)"
        if L["source"] == "current+previous"
        else f"{L['current_matches']} league matches this season (no earlier season stored)"
    )
    dist = []
    for side, lam in (
        ("home", g["estimated_goals"]["home"]),
        ("away", g["estimated_goals"]["away"]),
    ):
        d = gm.goal_distribution(lam)
        dist.append(
            html.Tr([html.Td(f[side])] + [html.Td(f"{x * 100:.0f}%", className="num") for x in d])
        )
    return accordion(
        "How it's calculated",
        html.P(
            "1. League averages: home teams score "
            f"{L['home']:.2f} and away teams {L['away']:.2f} goals per match ({prior}).",
            className="explain",
        ),
        html.P(
            "2. Each team's goals scored and conceded this season are compared with what an "
            "average team would score and concede at the same venues. Strength says how much a "
            "team outscores the league; goal tempo says how high-scoring its matches are. Both "
            f"start at the league average and move towards the team's own record: strength "
            f"with {p['k_s']:g} pseudo-matches of smoothing, tempo with {p['k_t']:g}.",
            className="explain",
        ),
        html.Table(
            html.Tbody(team_rows("home", f["home"]) + team_rows("away", f["away"])),
            className="grid compact",
        ),
        html.P(
            f"3. Estimated goals: {f['home']} = {L['home']:.2f} × (strength ratio) × (both tempos) "
            f"= {goals2(g['estimated_goals']['home'])}; {f['away']} = {L['away']:.2f} × (inverse "
            f"ratio) × (both tempos) = {goals2(g['estimated_goals']['away'])}.",
            className="explain",
        ),
        html.P("4. Goals follow a Poisson distribution for each team:", className="explain"),
        html.Div(
            html.Table(
                [
                    html.Thead(
                        html.Tr(
                            [html.Th("Goals")]
                            + [html.Th(str(k), className="num") for k in range(6)]
                            + [html.Th("6+", className="num")]
                        )
                    ),
                    html.Tbody(dist),
                ],
                className="grid compact",
            ),
            className="scroll-x",
        ),
        html.P(
            "Every scoreline's probability is the product of the two teams' probabilities; "
            "adding up the right scorelines gives each market. All three markets come from the "
            "same two numbers, so they always agree.",
            className="explain",
        ),
        html.P(
            f"Goal Model {g['model']['goal_model_version']} · data up to "
            f"{r['cutoff'][:16].replace('T', ' ')} UTC · parameters fixed for the season.",
            className="muted small",
        ),
    )


# ------------------------------------------------------------ B. context
def _recent_summary(r: dict) -> html.Div:
    """Last results for each team, most recent first (primary Form Score view)."""
    rows = []
    for s in SIDES:
        tm = r["teams"][s]
        seq = tm["form"]["sequence"]
        rows.append(
            html.Div(
                [
                    html.Span(tm["team"], className="recent-team"),
                    sequence(seq) if seq else html.Span("No matches yet", className="muted small"),
                ],
                className="recent-row",
            )
        )
    return html.Div(
        [html.Div("Recent results (most recent first)", className="muted small"), *rows],
        className="recent-summary",
    )


def form_context(r: dict) -> html.Details:
    """Form Score in two levels: scores, league average and recent results first; the
    arithmetic, venue context, explanations and match lists one click deeper."""
    t = r["teams"]
    bench = r["match_result"].get("league_benchmark")
    detail = html.Details(
        [
            html.Summary("Calculation and detail"),
            html.Div(
                [
                    html.P(FORM_TOOLTIP, className="muted small"),
                    form_breakdown_table(r),
                    venue_context_block(r),
                    benchmark_explanation(r),
                    matches_section(r, "1X2"),
                ],
                className="acc-body",
            ),
        ],
        className="acc form-detail",
    )
    return accordion(
        "Recent form (Diski Form Score)",
        html.Div([form_tile(t[s], bench) for s in SIDES], className="tiles"),
        form_benchmark_block(bench),
        _recent_summary(r),
        detail,
    )


def context_summary(state: dict) -> list:
    c = state["context"]
    if abs(c["home"]) < 1e-9 and abs(c["away"]) < 1e-9:
        out = [html.Span("No adjustment", className="cat-sum muted")]
    else:
        out = [
            html.Span(
                f"Home {signed_text(c['home'])} · Away {signed_text(c['away'])}",
                className="cat-sum active",
            )
        ]
    if c["note"]:
        out.append(html.Span("Note", className="cat-note-flag", title=c["note"]))
    return out


def _ctx_input(side: str, team: str, value: float) -> html.Label:
    return html.Label(
        [
            html.Span(f"{team} (± goals)", className="cat-input-label"),
            dcc.Input(
                id=f"ctx-{side}",
                type="text",
                inputMode="decimal",
                value=signed_text(value),
                debounce=0.4,
                pattern=r"[-+]?[0-9]*([.,][0-9]{0,2})?",
                className="adj-input cat-input goal-input step-005 allow-negative",
                placeholder="0.00",
            ),
        ],
        className="cat-field",
    )


def context_adjustment(r: dict, state: dict) -> html.Details:
    """One overall, optional adjustment per team from the user's reading of Section B.
    Never derived from the Form Score, head-to-head or positions: the user chooses."""
    f, c = r["fixture"], state["context"]
    return html.Details(
        [
            html.Summary(
                [
                    html.Span(
                        ["Your Match Context Adjustment ", role_tag("Your assumptions", "user")],
                        className="cat-title",
                    ),
                    html.Span(context_summary(state), id="ctx-sum", className="cat-sum-wrap"),
                ]
            ),
            html.Div(
                [
                    html.P(CONTEXT_ADJUST_NOTE, className="muted small"),
                    html.Div(
                        [
                            _ctx_input("home", f["home"], c["home"]),
                            _ctx_input("away", f["away"], c["away"]),
                        ],
                        className="cat-inputs",
                    ),
                    html.Label(
                        [
                            html.Span(
                                "Why are you making this adjustment? (optional)",
                                className="cat-input-label",
                            ),
                            dcc.Input(
                                id="ctx-note",
                                type="text",
                                value=c["note"],
                                maxLength=NOTE_MAX,
                                debounce=True,
                                placeholder="e.g. what in the context the model may have missed",
                                className="cat-note",
                            ),
                        ],
                        className="cat-field wide ctx-note-field",
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Clear Section B adjustments",
                                id="ctx-clear",
                                n_clicks=0,
                                className="pager-btn reset-btn",
                            ),
                            html.Span(
                                f"Each team: between -{CONTEXT_MAX:.2f} and +{CONTEXT_MAX:.2f} "
                                "goals, in steps of 0.05. This range is a guardrail, not a "
                                "validated effect size. Your note is kept.",
                                className="muted small",
                            ),
                        ],
                        className="adj-actions",
                    ),
                ],
                className="acc-body",
            ),
        ],
        className="acc cat-acc ctx-acc",
    )


def context_section(r: dict, market: str, official: dict, state: dict | None = None) -> html.Div:
    t = r["teams"]
    parts = [form_context(r)]
    if market != "1X2":
        key = "btts" if market == "BTTS" else "over_2_5"
        lb = r.get("league_baseline")
        word = "BTTS" if market == "BTTS" else "Over 2.5"
        parts.append(
            accordion(
                f"Recent {word} record",
                html.P(
                    "What happened in each team's last (up to ten) league matches this season. "
                    "A record describes the past; it is not a probability.",
                    className="muted small",
                ),
                html.Div([record_tile(t[s], key, market, lb) for s in SIDES], className="tiles"),
                html.P(LIMITED_GOALS, className="muted small")
                if r["limited_data"]["goals"]
                else None,
                league_baseline_block(r, market),
                goals_breakdown_table(r, market),
                matches_section(r, market),
            )
        )
    parts += [h2h_section(r), positions_section(r, official)]
    if state is not None and r.get("goal_model", {}).get("available"):
        parts.append(context_adjustment(r, state))
    return html.Div(
        [
            html.Div(
                [
                    html.Span("B. Match context", className="lab-step"),
                    role_tag("Context", "context"),
                ],
                className="label-row",
            ),
            html.P(CONTEXT_NOTE, className="muted small context-note"),
            html.Div(parts, className="acc-group"),
        ],
        className="lab-section context",
    )


# ------------------------------------------------------------ C. factors
def category_summary(state: dict, key: str) -> list:
    c = state["cats"][key]
    if abs(c["home"]) < 1e-9 and abs(c["away"]) < 1e-9:
        text, cls = "No adjustment", "cat-sum muted"
    else:
        text, cls = f"Home {signed(c['home'])} · Away {signed(c['away'])}", "cat-sum active"
    out = [html.Span(text, className=cls)]
    if c["note"]:
        out.append(html.Span("Note", className="cat-note-flag", title=c["note"]))
    return out


def _cat_input(key: str, side: str, team: str, value: float) -> html.Label:
    """The label wraps its box, so screen readers announce which team it adjusts."""
    return html.Label(
        [
            html.Span(f"{team} (± goals)", className="cat-input-label"),
            dcc.Input(
                id={"type": "cat-adj", "cat": key, "side": side},
                type="text",
                inputMode="decimal",
                value=adjustment_text(value),
                debounce=0.4,
                pattern=r"[-+]?[0-9]*([.,][0-9]{0,2})?",
                className="adj-input cat-input goal-input step-005 allow-negative",
                placeholder="0.00",
            ),
        ],
        className="cat-field",
    )


def factors_section(r: dict, state: dict) -> html.Div:
    f = r["fixture"]
    available = bool(r.get("goal_model", {}).get("available"))
    cards = []
    for key, title, items in CATEGORIES:
        c = state["cats"][key]
        body = [
            html.Ul([html.Li(i) for i in items], className="cat-items"),
            html.Label(
                [
                    html.Span("Research notes (optional)", className="cat-input-label"),
                    dcc.Input(
                        id={"type": "cat-note", "cat": key},
                        type="text",
                        value=c["note"],
                        maxLength=NOTE_MAX,
                        debounce=True,
                        placeholder="e.g. what you found and where",
                        className="cat-note",
                    ),
                ],
                className="cat-field wide",
            ),
        ]
        if available:
            body.append(
                html.Div(
                    [
                        _cat_input(key, "home", f["home"], c["home"]),
                        _cat_input(key, "away", f["away"], c["away"]),
                    ],
                    className="cat-inputs",
                )
            )
        cards.append(
            html.Details(
                [
                    html.Summary(
                        [
                            html.Span(title, className="cat-title"),
                            html.Span(
                                category_summary(state, key),
                                id={"type": "cat-sum", "cat": key},
                                className="cat-sum-wrap",
                            ),
                        ]
                    ),
                    html.Div(body, className="acc-body"),
                ],
                className="acc cat-acc",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Span("C. Other factors to consider", className="lab-step"),
                    role_tag("Your research", "user"),
                ],
                className="label-row",
            ),
            html.P(FACTORS_NOTE, className="muted small"),
            html.P(FACTORS_CAUTION, className="muted small caution"),
            html.Div(cards, className="acc-group cat-group"),
            html.P(
                "Adjustments are optional and start at 0.00. Enter them in goals per team "
                "(steps of 0.05); Diski 9 never assigns a value to a factor for you.",
                className="muted small",
            )
            if available
            else html.P("Adjustments need a model baseline.", className="muted small"),
        ],
        className="lab-section factors-section",
    )


# ------------------------------------------------------ D. adjustments
def _adjust_row(side: str, team: str, base: float, cur: float) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Label(
                        f"{team}: your estimate", htmlFor=f"lab-{side}-input", className="adj-team"
                    ),
                    html.Span(f"model {goals2(base)}", className="muted small"),
                ],
                className="adj-head",
            ),
            html.Div(
                [
                    html.Div(
                        dcc.Slider(
                            id=f"lab-{side}-slider",
                            min=0,
                            max=slider_max(base, cur),
                            step=SLIDER_STEP,
                            value=round(cur, 2),
                            marks=None,
                            updatemode="drag",
                            allow_direct_input=False,  # the number box beside it is the input
                            tooltip={"placement": "bottom", "always_visible": False},
                        ),
                        className="adj-slider",
                    ),
                    dcc.Input(
                        id=f"lab-{side}-input",
                        type="text",
                        inputMode="decimal",
                        value=goals2(cur),
                        debounce=True,
                        pattern=r"[0-9]+([.,][0-9]{0,2})?",
                        className="adj-input goal-input step-001",
                    ),
                ],
                className="adj-controls",
            ),
        ],
        className="adj-row",
    )


def breakdown_table(r: dict, b: dict) -> html.Table:
    f = r["fixture"]

    def row(label, key, fmt, cls=""):
        return html.Tr(
            [html.Td(label)]
            + [html.Td(fmt(b[s][key]), className=f"num {cls}".strip()) for s in SIDES]
        )

    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th(""),
                        html.Th(f["home"], className="num"),
                        html.Th(f["away"], className="num"),
                    ]
                )
            ),
            html.Tbody(
                [
                    row("Model baseline", "base", goals2),
                    row("Section B — Match context", "context", signed),
                    row("Section C — Other factors", "cats", signed),
                    row("Additional manual adjustment", "manual", signed),
                    row("Your final estimate", "final", goals2, "strong"),
                ]
            ),
        ],
        className="grid compact breakdown",
    )


def comparison_table(base: dict, mine: dict | None, markets: tuple[str, ...]) -> html.Table:
    rows = []
    for market in markets:
        if len(markets) > 1:
            rows.append(html.Tr(html.Td(MARKET_TITLE[market], colSpan=4, className="grid-sub")))
        for key, label in MARKET_KEYS[market]:
            b = base[key]
            m = mine[key] if mine else b
            rows.append(
                html.Tr(
                    [
                        html.Td(label),
                        html.Td(pct1(b), className="num"),
                        html.Td(pct1(m), className="num strong" if mine else "num"),
                        html.Td(pp(m - b), className="num delta"),
                    ]
                )
            )
    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Outcome"),
                        html.Th("Model", className="num"),
                        html.Th("Yours", className="num"),
                        html.Th("Change", className="num"),
                    ]
                )
            ),
            html.Tbody(rows),
        ],
        className="grid compact lab-table",
    )


def adjusted_probabilities(est: dict | None) -> dict | None:
    return gm.markets(est["home"], est["away"]) if est else None


def lab_outputs(
    r: dict, market: str, ov: OddsView | None, state: dict | None, messages: list | None = None
):
    """(Section D results, bookmaker comparison) for a fixture's user state."""
    g = r["goal_model"]
    base = g["probabilities"]
    state = state or new_state()
    b = breakdown(baseline_rounded(r), state)
    est = user_estimates(r, state)
    mine = adjusted_probabilities(est)
    f = r["fixture"]
    notes = [html.P(m, className="lab-message") for m in (messages or [])]
    for s in SIDES:
        if b[s]["clipped"]:
            team = f[s]
            notes.append(
                html.P(
                    f"Your adjustments would take {team} to {b[s]['raw']:.2f} goals; the estimate "
                    f"is held at {b[s]['final']:.2f} (estimated goals must be between 0 and "
                    f"{ADJUST_MAX:g}).",
                    className="lab-message",
                )
            )
    summary = (
        html.P(
            [
                "Your estimate: ",
                html.Strong(f"{f['home']} {goals2(est['home'])}"),
                " – ",
                html.Strong(f"{f['away']} {goals2(est['away'])}"),
                f" (model {goals2(b['home']['base'])} – {goals2(b['away']['base'])}).",
            ],
            className="small",
        )
        if mine
        else html.P(
            "Showing the model baseline. Add adjustments in Section B or C, or move a slider to "
            "set your own estimate.",
            className="muted small",
        )
    )
    others = tuple(m for m in ALL_MARKETS if m != market)
    out = html.Div(
        [
            *notes,
            breakdown_table(r, b),
            summary,
            comparison_table(base, mine, (market,)),
            html.Details(
                [html.Summary("All markets"), comparison_table(base, mine, others)],
                className="acc all-markets",
            ),
        ]
    )
    return out, model_comparison(market, ov, base, mine)


def adjust_section(r: dict, market: str, ov: OddsView | None, state: dict) -> html.Div:
    g = r["goal_model"]
    head = html.Div(
        [
            html.Span("D. Your adjustments", className="lab-step"),
            role_tag("Your assumptions", "user"),
        ],
        className="label-row",
    )
    if not g.get("available"):
        return html.Div(
            [head, html.P("Adjustments need a model baseline.", className="muted small")],
            className="lab-section adjust",
        )
    f = r["fixture"]
    base_r = baseline_rounded(r)
    b = breakdown(base_r, state)
    out, _ = lab_outputs(r, market, ov, state)
    return html.Div(
        [
            head,
            html.P(ADJUST_NOTE, className="muted small"),
            html.P(
                "Your estimate = model baseline + Section B match context + Section C other "
                "factors + any additional manual adjustment. The sliders and boxes set your final "
                "estimate directly; the manual adjustment is worked out for you, so nothing is "
                "counted twice.",
                className="muted small",
            ),
            _adjust_row("home", f["home"], base_r["home"], b["home"]["final"]),
            _adjust_row("away", f["away"], base_r["away"], b["away"]["final"]),
            html.Div(
                [
                    html.Button(
                        "Reset to model",
                        id="lab-reset",
                        n_clicks=0,
                        className="pager-btn reset-btn",
                    ),
                    html.Span(
                        "Clears every adjustment in Sections B, C and D and restores the model "
                        "estimates. Your notes in Sections B and C are kept. Nothing leaves this "
                        "browser tab or changes the model.",
                        className="muted small",
                    ),
                ],
                className="adj-actions",
            ),
            html.Div(out, id="lab-output", **{"aria-live": "polite"}),
        ],
        className="lab-section adjust",
    )


# ----------------------------------------------------- bookmaker compare
def model_comparison(market: str, ov: OddsView | None, base: dict, mine: dict | None) -> html.Div:
    """Model baseline, the user's estimate and the margin-adjusted market probabilities,
    side by side. A comparison only: no recommendation is made from the differences."""
    implied = None
    if ov is not None and ov.league_has_odds:
        dm = ov.markets[MARKET_OF[market]]
        if dm.status != "unavailable" and dm.implied and dm.implied.margin_adjusted:
            implied = {OUTCOME_KEY[o]: float(v) for o, v in dm.implied.margin_adjusted.items()}
    head = [html.Th("Outcome"), html.Th("Diski 9", className="num", title="Model baseline")]
    if mine:
        head.append(html.Th("Yours", className="num", title="Your adjusted estimate"))
    head.append(html.Th("Market", className="num", title="Market-implied, margin removed"))
    rows = []
    for key, label in MARKET_KEYS[market]:
        cells = [html.Td(label), html.Td(pct1(base[key]), className="num")]
        if mine:
            cells.append(html.Td(pct1(mine[key]), className="num strong"))
        cells.append(html.Td(pct1(implied[key]) if implied else "—", className="num"))
        rows.append(html.Tr(cells))
    note = (
        "Market-implied probabilities remove the bookmaker margin. Differences show where your "
        "view and the market's differ; they are not betting advice."
        if implied
        else "No current bookmaker prices to compare with."
    )
    return html.Div(
        [
            html.Div(html.Span("Compare with Diski 9", className="label"), className="label-row"),
            html.Div(
                html.Table([html.Thead(html.Tr(head)), html.Tbody(rows)], className="grid compact"),
                className="scroll-x",
            ),
            html.P(note, className="muted small"),
        ],
        className="model-compare",
    )


def bookmaker_card(
    r: dict,
    ov: OddsView | None,
    market: str,
    data: ScreenerData,
    league: str,
    state: dict | None,
) -> html.Section:
    card = _market_card(ov, MARKET_OF[market], data, league)
    head = card.children[0]
    head.children.append(html.Div(role_tag("Market", "market"), className="card-tag"))
    g = r["goal_model"]
    if g.get("available"):
        compare = model_comparison(
            market, ov, g["probabilities"], adjusted_probabilities(user_estimates(r, state))
        )
    else:
        compare = html.P(g.get("message"), className="muted small")
    card.children.append(html.Div(compare, id="lab-compare"))
    return card


# ----------------------------------------------------------------- panel
def render_detail(
    r: dict | None,
    ov: OddsView | None,
    official: dict,
    market: str,
    data: ScreenerData,
    adj: dict | None = None,
) -> Any:
    """``adj`` is the fixture's user state from the browser store (or None)."""
    if r is None:
        return html.Div("Select a fixture to open The Match Lab.", className="empty")
    f = r["fixture"]
    league = LEAGUE_SHORT.get(f["competition_id"], f["competition"])
    g = r.get("goal_model") or {}
    available = bool(g.get("available"))
    state = normalise_state(adj, baseline_rounded(r) if available else None)
    if not available:
        state = new_state() | {"cats": state["cats"]}  # notes kept, no adjustments
        for k in CATEGORY_KEYS:
            state["cats"][k]["home"] = state["cats"][k]["away"] = 0.0
    lab = html.Section(
        [
            card_head(
                "The Match Lab",
                "We calculate the probabilities. You analyse the match. You make the call.",
            ),
            baseline_section(r, market),
            context_section(r, market, official, state),
            factors_section(r, state),
            adjust_section(r, market, ov, state),
        ],
        className="card lab",
    )
    return html.Div(
        [
            html.Div(
                [
                    html.H2(f"{f['home']} v {f['away']}"),
                    html.Div(
                        f"{league} · {data.local(f['kickoff'])} {data.tz_label} · "
                        f"{MARKET_TITLE[market]}",
                        className="muted match-meta",
                    ),
                    pill("Adjusted by you", "accent")
                    if available and has_adjustment(state)
                    else None,
                ],
                className="detail-header",
            ),
            lab,
            bookmaker_card(r, ov, market, data, league, state if available else None),
            html.P(
                f"Statistics use only results before {data.local(r['cutoff'])} {data.tz_label}. "
                f"Goal Model {gm.GOAL_MODEL_VERSION}.",
                className="muted small",
            ),
        ],
        className="detail",
    )
