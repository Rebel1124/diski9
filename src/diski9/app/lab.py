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
FACTORS = [
    ("Injuries and suspensions", "Who is missing, and how important are they?"),
    ("Expected starting line-ups", "Will key players start, or be rested?"),
    ("Fixture congestion and rest days", "A midweek match or long travel can tire a squad."),
    ("Squad rotation", "Cup or European matches nearby may change the team selected."),
    ("Managerial or tactical changes", "A new coach or system may not show in the results yet."),
    ("Transfers and squad changes", "New signings or departures since the results were played."),
    ("Home advantage and unusual venues", "A neutral, shared or temporary ground."),
    ("Weather and playing conditions", "Heavy rain, wind, heat or a poor pitch."),
    ("Motivation and competition circumstances", "Title races, relegation, dead rubbers."),
]


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
def context_section(r: dict, market: str, official: dict) -> html.Div:
    t = r["teams"]
    bench = r["match_result"].get("league_benchmark")
    form = accordion(
        "Recent form (Diski Form Score)",
        html.P(FORM_TOOLTIP, className="muted small"),
        html.Div([form_tile(t[s], bench) for s in ("home", "away")], className="tiles"),
        form_benchmark_block(bench),
        venue_context_block(r),
        form_breakdown_table(r),
        benchmark_explanation(r),
        matches_section(r, "1X2"),
    )
    parts = [form]
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
                html.Div(
                    [record_tile(t[s], key, market, lb) for s in ("home", "away")],
                    className="tiles",
                ),
                html.P(LIMITED_GOALS, className="muted small")
                if r["limited_data"]["goals"]
                else None,
                league_baseline_block(r, market),
                goals_breakdown_table(r, market),
                matches_section(r, market),
            )
        )
    parts += [h2h_section(r), positions_section(r, official)]
    return html.Div(
        [
            html.Div(html.Span("B. Match context", className="lab-step"), className="label-row"),
            html.P(CONTEXT_NOTE, className="muted small context-note"),
            html.Div(parts, className="acc-group"),
        ],
        className="lab-section context",
    )


# ------------------------------------------------------------ C. factors
def factors_section() -> html.Div:
    return html.Div(
        [
            html.Div(
                html.Span("C. Other factors to consider", className="lab-step"),
                className="label-row",
            ),
            html.Details(
                [
                    html.Summary("Checklist: what the model cannot see"),
                    html.Ul(
                        [
                            html.Li([html.Strong(a), html.Span(f" — {b}", className="muted")])
                            for a, b in FACTORS
                        ],
                        className="factors",
                    ),
                    html.P(
                        "These factors need your own research. They are not included in the "
                        "statistical model, and Diski 9 does not supply team news.",
                        className="muted small",
                    ),
                ],
                className="acc factors-acc",
            ),
        ],
        className="lab-section factors-section",
    )


# ------------------------------------------------------ D. adjustments
def _adjust_row(side: str, team: str, base: float, cur: float) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Label(team, htmlFor=f"lab-{side}-input", className="adj-team"),
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
                        type="number",
                        min=0,
                        max=ADJUST_MAX,
                        step=0.01,
                        value=round(cur, 2),
                        debounce=True,
                        className="adj-input",
                    ),
                ],
                className="adj-controls",
            ),
        ],
        className="adj-row",
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


def adjusted_probabilities(adj: dict | None) -> dict | None:
    return gm.markets(adj["home"], adj["away"]) if adj else None


def lab_outputs(r: dict, market: str, ov: OddsView | None, adj: dict | None):
    """(adjustment results, bookmaker comparison) for the current adjustment."""
    g = r["goal_model"]
    base = g["probabilities"]
    mine = adjusted_probabilities(adj)
    f = r["fixture"]
    if mine:
        summary = html.P(
            [
                "Your estimate: ",
                html.Strong(f"{f['home']} {goals2(adj['home'])}"),
                " – ",
                html.Strong(f"{f['away']} {goals2(adj['away'])}"),
                f" (model {goals2(g['estimated_goals']['home'])} – "
                f"{goals2(g['estimated_goals']['away'])}).",
            ],
            className="small",
        )
    else:
        summary = html.P(
            "Showing the model baseline. Move a slider or type a value to explore your own view.",
            className="muted small",
        )
    others = tuple(m for m in ALL_MARKETS if m != market)
    out = html.Div(
        [
            summary,
            comparison_table(base, mine, (market,)),
            html.Details(
                [html.Summary("All markets"), comparison_table(base, mine, others)],
                className="acc all-markets",
            ),
        ]
    )
    return out, model_comparison(market, ov, base, mine)


def adjust_section(r: dict, market: str, ov: OddsView | None, adj: dict | None) -> html.Div:
    g = r["goal_model"]
    head = html.Div(html.Span("D. Your adjustments", className="lab-step"), className="label-row")
    if not g.get("available"):
        return html.Div(
            [head, html.P("Adjustments need a model baseline.", className="muted small")],
            className="lab-section adjust",
        )
    f, base = r["fixture"], g["estimated_goals"]
    cur = adj or {"home": round(base["home"], 2), "away": round(base["away"], 2)}
    out, _ = lab_outputs(r, market, ov, adj)
    return html.Div(
        [
            head,
            html.P(ADJUST_NOTE, className="muted small"),
            _adjust_row("home", f["home"], base["home"], cur["home"]),
            _adjust_row("away", f["away"], base["away"], cur["away"]),
            html.Div(
                [
                    html.Button(
                        "Reset to model",
                        id="lab-reset",
                        n_clicks=0,
                        className="pager-btn reset-btn",
                    ),
                    html.Span(
                        "Your changes stay in this browser tab only and never change the model.",
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
    adj: dict | None,
) -> html.Section:
    card = _market_card(ov, MARKET_OF[market], data, league)
    g = r["goal_model"]
    if g.get("available"):
        compare = model_comparison(market, ov, g["probabilities"], adjusted_probabilities(adj))
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
    if r is None:
        return html.Div("Select a fixture to open The Match Lab.", className="empty")
    f = r["fixture"]
    league = LEAGUE_SHORT.get(f["competition_id"], f["competition"])
    g = r.get("goal_model") or {}
    if not g.get("available"):
        adj = None
    lab = html.Section(
        [
            card_head(
                "The Match Lab",
                "We calculate the probabilities. You analyse the match. You make the call.",
            ),
            baseline_section(r, market),
            context_section(r, market, official),
            factors_section(),
            adjust_section(r, market, ov, adj),
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
                        className="muted",
                    ),
                    pill("Adjusted by you", "accent") if adj else None,
                ],
                className="detail-header",
            ),
            lab,
            bookmaker_card(r, ov, market, data, league, adj),
            html.P(
                f"Statistics use only results before {data.local(r['cutoff'])} {data.tz_label}. "
                f"Goal Model {gm.GOAL_MODEL_VERSION}.",
                className="muted small",
            ),
        ],
        className="detail",
    )
