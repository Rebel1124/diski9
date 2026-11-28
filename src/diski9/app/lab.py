"""The Match Lab and the statistical baseline (Engine 3.1, Goal Model 1.1).

Detail panel for a selected fixture:

  Heading          fixture, competition, kickoff, market
  The Match Lab    A. Statistical baseline - estimated goals and the selected
                      market's probabilities (with "How it's calculated")
                   B. Match context - Form Score, recent goals record,
                      head-to-head, league positions (never change the model)
                   C. Other factors to consider - an educational checklist
                   D. Your adjustments - estimated-goal sliders, recalculated
                      probabilities for all markets, reset
  Bookmaker card   odds, raw implied, margin, market-implied probabilities and the
                   full model vs market comparison (model baseline: market
                   probability, edge, odds, EV for every outcome)

Section D also shows "Your value check": the user's final probability against the
market (edge and EV at the consensus odds) next to the model's. Edge and EV come
from ``diski9.odds.value`` - the same implementation the Screener ranks with.

Pure rendering functions; callbacks live in ``app.py``. User adjustments are a
plain dict passed in from the browser's memory store and are never persisted.
"""

from __future__ import annotations

import math
from typing import Any

from dash import dcc, html

from diski9.api_football.markets import Outcome
from diski9.odds.value import (
    MarketValue,
    compare,
    edge_text,
    ev_text,
    positive_edge,
    positive_ev,
    sign_class,
)
from diski9.screener import goal_model as gm

from . import education
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
LAB_GATE = {"type": "lab-gate", "k": 0}  # ML-01 (CP3A-4B), see app.adjust
CONTEXT_NOTE = (
    "Form, league position and head-to-head results provide useful context, but some of this "
    "information may already be reflected in the model. Avoid counting the same information "
    "twice."
)
FROZEN_CONTEXT_NOTE = (
    "Supplementary latest data: form, head-to-head and league positions use the latest "
    "available results, not the snapshot. They never change the frozen estimated goals, "
    "probabilities or odds."
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
# Static guidance per factor: what to look at, how it could move each team's estimated
# goals, and when to leave the adjustment at zero. Written so that it can also frame
# future assisted research (Phase 7) without asking anyone to type notes.
CATEGORY_GUIDANCE = {
    "squad": (
        "Consider which key players are unavailable or likely to be rested, how important "
        "they are to the team's attack or defence, and the quality of their replacements. A "
        "missing first-choice striker may lower that team's estimated goals; an absent central "
        "defender or goalkeeper may raise the opponent's. Recent transfers matter mainly when "
        "this season's results do not yet reflect them."
    ),
    "fitness": (
        "Consider how many matches each team has played recently, their rest days and travel, "
        "and whether heavy rotation is likely. A tired or much-changed side may create fewer "
        "chances and concede more. Small differences in rest rarely justify more than a small "
        "adjustment."
    ),
    "tactics": (
        "Consider managerial or tactical changes that this season's results may not yet "
        "reflect, and how the two styles are likely to interact. A more attacking approach can "
        "raise both a team's estimated goals and its opponent's; a defensive set-up may lower "
        "both. A few matches under a new manager are a small sample."
    ),
    "conditions": (
        "Consider weather and pitch conditions, an unusual venue, and what each team is playing "
        "for. Heavy rain or strong wind often lowers scoring for both sides, and a team with "
        "little to play for may be less sharp. Motivation is hard to measure, so keep any "
        "adjustment modest unless the evidence is clear."
    ),
}
CATEGORY_MAX = 2.0  # largest +/- adjustment one category can carry
FACTORS_NOTE = (
    "These factors are not included in the statistical model. Adjust only for information the "
    "model has not already captured, judge each team separately, and leave an adjustment at "
    "0.00 when the evidence is unclear."
)
FACTORS_CAUTION = (
    "Adjustments are your own estimates, not guaranteed improvements. Related factors can "
    "overlap with each other and with recent results: avoid counting the same information twice."
)
SIDES = ("home", "away")
CONTEXT_MAX = 1.0  # Section B guardrail: +/- 1 goal (not a validated effect size)
CONTEXT_ADJUST_NOTE = (
    "Recent form, league position and head-to-head results are partly reflected in the model's "
    "estimated goals already. Adjust only if the context suggests something this season's goal "
    "data misses, such as a recent run that reflects a genuine change rather than an easy or "
    "difficult set of fixtures. Head-to-head results from earlier seasons often involve "
    "different squads and managers. Judge each team separately, keep adjustments modest, and "
    "leave them at 0.00 if the context only confirms what the model shows."
)


# ------------------------------------------------------------ user state
# Per fixture, in the browser's memory store only (numbers only; no free text):
#   {"context": {"home": float, "away": float},
#    "cats": {category: {"home": float, "away": float}},
#    "manual": {"home": float, "away": float}}
# Notes saved by earlier versions are ignored when a state is read and dropped when it
# is next saved.
# Your estimate = model baseline (rounded to 0.01) + sum of category adjustments
#                 + additional manual adjustment, kept within 0-10 goals.
def new_state() -> dict:
    return {
        "context": {"home": 0.0, "away": 0.0},
        "cats": {k: {"home": 0.0, "away": 0.0} for k in CATEGORY_KEYS},
        "manual": {"home": 0.0, "away": 0.0},
    }


MODEL_SOURCE_LABEL = "Diski 9 Goal Model"
MARKET_SOURCE_LABEL = "Market-implied Model"


def starting_point(r: dict | None) -> dict | None:
    """The fixture's single quantitative starting point (Phase 8 State A/B/C), chosen
    automatically: the independent Goal Model when it is available (State A),
    otherwise a reliable market-implied fit attached by ``lab_context`` (State B),
    otherwise None (State C). Never both, never a selector."""
    if not r:
        return None
    g = r.get("goal_model") or {}
    if g.get("available"):
        return {
            "source": "model",
            "label": MODEL_SOURCE_LABEL,
            "estimated_goals": g["estimated_goals"],
            "probabilities": g["probabilities"],
        }
    sp = r.get("_starting_point")
    if sp and sp.get("estimated_goals"):
        return sp
    return None


def is_market_implied(r: dict | None) -> bool:
    sp = starting_point(r)
    return bool(sp) and sp["source"] == "market"


def baseline_rounded(r: dict) -> dict:
    sp = starting_point(r)
    eg = sp["estimated_goals"] if sp else r["goal_model"]["estimated_goals"]
    return {s: round(eg[s], 2) for s in SIDES}


CONTEXT_KEY = "_ctx"  # in the Match Lab store: {fixture id: model context stamp}


def model_context(r: dict) -> str:
    """What a fixture's adjustments are relative to: the starting point's source and
    version and the rounded baseline estimated goals. Adjustments are deltas from
    this baseline, so they are only reapplied while it is unchanged.

    * Goal Model (State A): ``"<version>|<fixture>|<home>|<away>"`` (unchanged
      since Phase 6C.3, so existing adjustments stay valid);
    * Market-implied (State B): ``"mi<fit version>:<input identity>|<fixture>|..."``
      - the input identity covers the methodology, the live or frozen context and
      the exact market probabilities, so it never matches a Goal Model stamp, the
      other context, or a fit from different prices."""
    if r.get("_model_context"):  # a frozen Weekly Challenge baseline (lab_context)
        return r["_model_context"]
    sp = starting_point(r)
    if sp and sp["source"] == "market":
        return sp["stamp"]
    b = baseline_rounded(r)
    return f"{gm.GOAL_MODEL_VERSION}|{r['fixture']['id']}|{b['home']:.2f}|{b['away']:.2f}"


def stored_adjustment(lab: dict | None, fid, r: dict | None) -> dict | None:
    """The participant's stored state for a fixture, or None when there is none or it
    was made against a different model context (never applied to the wrong baseline)."""
    if not lab or fid is None:
        return None
    stored = lab.get(str(fid))
    if stored is None or r is None or starting_point(r) is None:
        return stored
    stamp = (lab.get(CONTEXT_KEY) or {}).get(str(fid))
    if stamp is not None and stamp != model_context(r):
        return None
    return stored


WAS_KEY = "_was"  # {key: stamp} of a saved Your View that no longer matches (account)


def _stamp_source(stamp: str) -> str:
    return "market" if stamp.split("|", 1)[0].startswith("mi") else "model"


def adjustment_notice(lab: dict | None, fid, r: dict | None) -> str | None:
    """A visible explanation when this fixture has earlier adjustments that are not
    applied because its starting point changed (source, methodology, inputs or
    context). The earlier numbers are never reinterpreted against the new baseline."""
    if not lab or fid is None or r is None:
        return None
    key = str(fid)
    stored = lab.get(key)
    was = (lab.get(CONTEXT_KEY) or {}).get(key) if stored else None
    if was is not None and not has_adjustment(normalise_state(stored)):
        was = None
    if was is None:
        was = (lab.get(WAS_KEY) or {}).get(key)
    if not was:
        return None
    sp = starting_point(r)
    now = model_context(r) if sp else None
    if was == now:
        return None
    before = _stamp_source(was)
    if now is None:
        why = "there is no quantitative starting point for this match now"
    elif before == "model" and sp["source"] == "market":
        why = (
            "the Diski 9 Goal Model has no prediction for this match now, so the starting "
            "point is the Market-implied Model"
        )
    elif before == "market" and sp["source"] == "model":
        why = (
            "the Diski 9 Goal Model now has an independent prediction for this match, which "
            "replaces the market-implied starting point"
        )
    elif before == "market":
        why = "the bookmaker prices behind the market-implied estimate have changed"
    elif was.split("|", 1)[0] != now.split("|", 1)[0]:
        why = "the Goal Model version has changed"
    else:
        why = "the model's estimated goals for this match have changed"
    return (
        f"Your earlier adjustments for this match are not applied because {why}. They were "
        "made against a different starting point; adjusting again starts from the current one."
    )


def store_adjustment(lab: dict | None, fid, r: dict, state: dict | None) -> dict:
    """A new Match Lab store with this fixture's state (or without it, when empty)
    and its model context stamp."""
    lab = dict(lab or {})
    stamps = dict(lab.get(CONTEXT_KEY) or {})
    if state is None:
        lab.pop(str(fid), None)
        stamps.pop(str(fid), None)
    else:
        lab[str(fid)] = state
        stamps[str(fid)] = model_context(r)
        was = dict(lab.get(WAS_KEY) or {})
        if was.pop(str(fid), None) is not None:
            if was:
                lab[WAS_KEY] = was
            else:
                lab.pop(WAS_KEY, None)
    if stamps:
        lab[CONTEXT_KEY] = stamps
    else:
        lab.pop(CONTEXT_KEY, None)
    return lab


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
            "home": float(c.get("home") or 0.0),
            "away": float(c.get("away") or 0.0),
        }
    ctx = stored.get("context") or {}
    state["context"] = {
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
    return not has_adjustment(state)


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


MARKET_IMPLIED_HELP = (
    "Market-implied estimated goals are the goals per team that best reproduce the "
    "bookmakers' consensus probabilities under the same Poisson calculation. They are "
    "estimates derived from bookmaker probabilities: not shot-based xG and not an "
    "independent Diski 9 prediction."
)
FIT_NOTE = {
    "good": "Good fit: these estimated goals reproduce the bookmaker probabilities to within "
    "2 percentage points.",
    "approximate": "Approximate fit: these estimated goals reproduce the bookmaker probabilities "
    "only to within 4 percentage points, so treat them as a rough starting point.",
}
FIT_CAVEAT = (
    "A close fit shows that the estimated goals represent the bookmaker prices; it does not "
    "show that they predict results better than the bookmakers."
)
NO_EDGE_NOTE = (
    "Edge and EV are not shown for this match: the starting point is derived from the same "
    "bookmaker prices, so a difference from the market is not an independent advantage."
)


def source_line(r: dict) -> html.Div | None:
    """'Starting point: Diski 9 Goal Model' / 'Market-implied Model' above the
    estimated goals (State A/B), or nothing (State C)."""
    sp = starting_point(r)
    if sp is None:
        return None
    return html.Div(
        [
            html.Span("Starting point: ", className="muted small"),
            html.Strong(sp["label"], className=f"lab-source {sp['source']}"),
        ],
        className="lab-source-line",
    )


def unavailable_message(r: dict) -> list:
    """State C: why no quantitative starting point exists (no estimate is made up)."""
    g = r.get("goal_model") or {}
    out = [html.Div(g.get("message"), className="unavailable")]
    why = r.get("_starting_point_unavailable")
    if why:
        out.append(
            html.P(f"Market-implied estimate unavailable: {why}", className="muted small mi-why")
        )
    out.append(
        html.P(
            "Estimated goals and adjustments are not available for this match. The fixture "
            "information, statistics and bookmaker prices below remain available.",
            className="muted small",
        )
    )
    return out


def _market_baseline(r: dict, market: str, head) -> html.Div:
    sp = starting_point(r)
    f = r["fixture"]
    eg = sp["estimated_goals"]
    frozen = sp.get("context") == "frozen"
    return html.Div(
        [
            head,
            source_line(r),
            html.Div(
                [_eg_tile(f["home"], eg["home"], None), _eg_tile(f["away"], eg["away"], None)],
                className="tiles",
            ),
            html.Div(
                [
                    html.Span(MARKET_TITLE[market], className="label"),
                    html.Span("Market-implied probabilities (fitted)", className="muted small"),
                ],
                className="label-row",
            ),
            prob_bars(sp["probabilities"], market),
            html.P(FIT_NOTE[sp["quality"]], className=f"small fit-note fit-{sp['quality']}"),
            html.P(
                [
                    "The Diski 9 Goal Model has no independent prediction for this match (",
                    ((r.get("goal_model") or {}).get("message") or "unavailable").rstrip("."),
                    "). ",
                    MARKET_IMPLIED_HELP,
                ],
                className="muted small",
            ),
            html.P(FIT_CAVEAT, className="muted small"),
            html.P(
                "Fitted from the frozen Weekly Challenge snapshot's bookmaker probabilities; "
                "later odds never change it.",
                className="muted small",
            )
            if frozen
            else None,
        ],
        className="lab-section lab-baseline",
    )


def baseline_section(r: dict, market: str) -> html.Div:
    g = r["goal_model"]
    f = r["fixture"]
    market_sp = is_market_implied(r)
    head = html.Div(
        [
            html.Span("A. Statistical baseline", className="lab-step"),
            role_tag("Market-implied estimate" if market_sp else "Model estimate", "model"),
            info(
                MARKET_IMPLIED_HELP if market_sp else ESTIMATED_GOALS_HELP,
                "About estimated goals",
            ),
        ],
        className="label-row",
    )
    if market_sp:
        return _market_baseline(r, market, head)
    if not g.get("available"):
        return html.Div([head, *unavailable_message(r)], className="lab-section lab-baseline")
    notes = {"home": None, "away": None}
    early = (
        html.P(gm.LIMITED_DATA_WARNING, className="muted small limited-note")
        if g.get("early_season")
        else None
    )
    return html.Div(
        [
            head,
            source_line(r),
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
            html.Div([model_calculation(r)], className="acc-group")
            if (r.get("_context") or {}).get("kind") != "round"
            else html.P(
                "These estimated goals were frozen with the Weekly Challenge snapshot. Turn on "
                "Use latest available data to see the latest estimate and its calculation.",
                className="muted small",
            ),
        ],
        className="lab-section lab-baseline",
    )


def model_calculation(r: dict) -> html.Details:
    """The inputs and arithmetic of the Goal Model for this fixture."""
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

    prior = f"{L['current_matches']} league matches this season (current season only)"
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
        html.Div(
            [form_benchmark_block(bench), _recent_summary(r)],
            className="form-summary-grid",
        ),
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
    return out


def slider_value(value: float, limit: float) -> float:
    """The mini slider's position for an adjustment (always within its range)."""
    return round(min(max(float(value or 0.0), -limit), limit), 2)


def _mini_adjust(
    label: str, slider_id, input_id, value: float, limit: float, text: str
) -> html.Div:
    """A compact secondary slider plus the precise number box, both bound to ONE
    adjustment value (the callback writes the same state value back to both)."""
    return html.Div(
        [
            html.Span(label, className="cat-input-label"),
            html.Div(
                [
                    html.Div(
                        dcc.Slider(
                            id=slider_id,
                            min=-limit,
                            max=limit,
                            step=SLIDER_STEP,
                            value=slider_value(value, limit),
                            marks=None,
                            updatemode="drag",
                            allow_direct_input=False,  # the number box beside it is the input
                            tooltip=None,
                        ),
                        className="mini-slider",
                        title=f"{-limit:+.2f} to {limit:+.2f} goals, steps of 0.05",
                    ),
                    dcc.Input(
                        id=input_id,
                        type="text",
                        inputMode="decimal",
                        value=text,
                        debounce=0.4,
                        pattern=r"[+\-]?[0-9]*([.,][0-9]{0,2})?",
                        className="adj-input cat-input goal-input step-005 allow-negative",
                        placeholder="0.00",
                    ),
                ],
                className="mini-adjust",
            ),
        ],
        className="cat-field",
    )


def _ctx_input(side: str, team: str, value: float) -> html.Div:
    return _mini_adjust(
        f"{team} (± goals)",
        f"ctx-{side}-slider",
        f"ctx-{side}",
        value,
        CONTEXT_MAX,
        signed_text(value),
    )


def _split(guide: list, controls: list | None) -> html.Div:
    """Guidance on the left, the home and away controls stacked on the right (desktop);
    one column on small screens, in the same order."""
    kids = [html.Div(guide, className="cat-guide-col")]
    if controls:
        kids.append(html.Div(controls, className="cat-inputs"))
    return html.Div(kids, className="cat-split" if controls else "cat-split single")


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
                    _split(
                        [html.P(CONTEXT_ADJUST_NOTE, className="muted small cat-guide")],
                        [
                            _ctx_input("home", f["home"], c["home"]),
                            _ctx_input("away", f["away"], c["away"]),
                        ],
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
                                "validated effect size.",
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
    if state is not None and starting_point(r) is not None:
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
            html.P(FROZEN_CONTEXT_NOTE, className="muted small context-note frozen-context-note")
            if (r.get("_context") or {}).get("kind") == "round"
            else None,
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
    return [html.Span(text, className=cls)]


def _cat_input(key: str, side: str, team: str, value: float) -> html.Div:
    return _mini_adjust(
        f"{team} (± goals)",
        {"type": "cat-slider", "cat": key, "side": side},
        {"type": "cat-adj", "cat": key, "side": side},
        value,
        CATEGORY_MAX,
        adjustment_text(value),
    )


def factors_section(r: dict, state: dict) -> html.Div:
    f = r["fixture"]
    available = starting_point(r) is not None
    cards = []
    for key, title, items in CATEGORIES:
        c = state["cats"][key]
        guide = [
            html.Ul([html.Li(i) for i in items], className="cat-items"),
            html.P(CATEGORY_GUIDANCE[key], className="muted small cat-guide"),
        ]
        controls = (
            [
                _cat_input(key, "home", f["home"], c["home"]),
                _cat_input(key, "away", f["away"], c["away"]),
            ]
            if available
            else None
        )
        body = [_split(guide, controls)]
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
                        html.Th("Component"),
                        html.Th(f["home"], className="num team-col", title=f["home"]),
                        html.Th(f["away"], className="num team-col", title=f["away"]),
                    ]
                )
            ),
            html.Tbody(
                [
                    row("Model baseline", "base", goals2),
                    row("B · Match context", "context", signed),
                    row("C · Other factors", "cats", signed),
                    row("Manual adjustment", "manual", signed),
                    row("Your final estimate", "final", goals2, "strong final-row"),
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
    sp = starting_point(r)
    market_sp = sp["source"] == "market"
    base = sp["probabilities"]
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
                f" ({'market-implied' if market_sp else 'model'} "
                f"{goals2(b['home']['base'])} – {goals2(b['away']['base'])}).",
            ],
            className="small",
        )
        if mine
        else html.P(
            f"Showing the {'market-implied' if market_sp else 'model'} baseline. Add adjustments "
            "in Section B or C, or move a slider to set your own estimate.",
            className="muted small",
        )
    )
    others = tuple(m for m in ALL_MARKETS if m != market)
    out = html.Div(
        [
            *notes,
            summary,
            # Estimated goals breakdown -> resulting probabilities, side by side on wide
            # screens (stacked on narrow ones); the market comparison follows below.
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Estimated goals breakdown", className="lab-subhead"),
                            breakdown_table(r, b),
                        ],
                        className="lab-pane",
                    ),
                    html.Div(
                        [
                            html.Div(
                                f"{MARKET_TITLE[market]} probabilities", className="lab-subhead"
                            ),
                            comparison_table(base, mine, (market,)),
                        ],
                        className="lab-pane",
                    ),
                ],
                className="lab-tables",
            ),
            html.Details(
                [html.Summary("All markets"), comparison_table(base, mine, others)],
                className="acc all-markets",
            ),
            html.P(NO_EDGE_NOTE, className="muted small no-edge")
            if market_sp
            else value_check(market, ov, base, mine),
        ]
    )
    if market_sp:
        return out, fitted_comparison(market, sp)
    return out, model_comparison(market, ov, base)


def adjust_section(r: dict, market: str, ov: OddsView | None, state: dict) -> html.Div:
    sp = starting_point(r)
    head = html.Div(
        [
            html.Span("D. Your adjustments", className="lab-step"),
            role_tag("Your assumptions", "user"),
        ],
        className="label-row",
    )
    if sp is None:
        return html.Div(
            [head, html.P("Adjustments need a model baseline.", className="muted small")],
            className="lab-section adjust",
        )
    market_sp = sp["source"] == "market"
    f = r["fixture"]
    base_r = baseline_rounded(r)
    b = breakdown(base_r, state)
    out, _ = lab_outputs(r, market, ov, state)
    return html.Div(
        [
            head,
            html.P(ADJUST_NOTE, className="muted small"),
            html.P(
                "Your adjustments start from the market-implied estimated goals, so your view "
                "is relative to the bookmakers' prices rather than an independent prediction.",
                className="muted small",
            )
            if market_sp
            else None,
            html.P(
                "Your estimate = starting point + Section B match context + Section C other "
                "factors + any additional manual adjustment. The sliders and boxes set your final "
                "estimate directly; the manual adjustment is worked out for you, so nothing is "
                "counted twice.",
                className="muted small",
            ),
            _adjust_row("home", f["home"], base_r["home"], b["home"]["final"]),
            _adjust_row("away", f["away"], base_r["away"], b["away"]["final"]),
            html.Div(
                [
                    # ML-01 (CP3A-4B): orders Your View edits; lives with the inputs
                    dcc.Store(id=LAB_GATE),
                    html.Button(
                        "Reset to starting point" if market_sp else "Reset to model",
                        id="lab-reset",
                        n_clicks=0,
                        className="pager-btn reset-btn",
                    ),
                    html.Span(
                        "Clears every adjustment in Sections B, C and D and restores the "
                        f"{'starting-point' if market_sp else 'model'} estimates. Nothing changes "
                        "the starting point itself.",
                        className="muted small",
                    ),
                ],
                className="adj-actions",
            ),
            html.Div(out, id="lab-output", **{"aria-live": "polite"}),
        ],
        className="lab-section adjust",
    )


# ----------------------------------------------------- model vs market
# Longer explanations from the central glossary (diski9.app.education), so the
# popovers, the glossary list and these texts can never disagree.
MODEL_PROB_HELP = education.long("model_probability")
MARKET_PROB_HELP = education.long("market_probability")
EDGE_HELP = education.long("edge")
EV_HELP = education.long("ev")
ODDS_SOURCE = education.long("reference_odds")
EDGE_VS_EV = (
    "A larger edge does not always mean a larger EV: EV also depends on the odds, so a longer-"
    "priced outcome can have a smaller edge but a higher EV. That is why the Match Lab "
    "offers both rankings."
)
EV_SHORT = (
    "Expected Value measures the average theoretical return of a bet based on your estimated "
    "probability and the bookmaker's odds. A positive EV means your estimated probability is "
    "higher than the break-even probability implied by the offered odds."
)
EV_CAUTION = (
    "Positive EV does not guarantee a winning bet or long-term profit. Your estimates may be "
    "wrong, and individual results remain uncertain."
)


def displayed_market(ov: OddsView | None, market: str):
    """The bookmaker card's displayed consensus (fresh or stale), or None."""
    if ov is None or not ov.league_has_odds:
        return None
    dm = ov.markets[MARKET_OF[market]]
    return None if dm.status == "unavailable" else dm


def market_value(market: str, ov: OddsView | None, probs: dict | None) -> MarketValue | None:
    dm = displayed_market(ov, market)
    if dm is None or not probs:
        return None
    return compare(MARKET_OF[market], probs, dm.consensus)


def _signed_cell(value, text: str, positive) -> html.Td:
    return html.Td(text, className=f"num val-{sign_class(value, positive)}")


def _price(x) -> str:
    return f"{float(x):.2f}"


def _range(ov_row) -> str | None:
    """Spread of the individual bookmaker prices behind a consensus price."""
    if ov_row.min_odds is None or ov_row.max_odds is None:
        return None
    if ov_row.min_odds == ov_row.max_odds:
        return _price(ov_row.min_odds)
    return f"{_price(ov_row.min_odds)}–{_price(ov_row.max_odds)}"


def value_glossary() -> html.Details:
    return html.Details(
        [
            html.Summary("What do model, market, edge and EV mean?"),
            html.Ul(
                [
                    html.Li(MODEL_PROB_HELP),
                    html.Li(MARKET_PROB_HELP),
                    html.Li(EDGE_HELP),
                    html.Li(EV_HELP),
                    html.Li(
                        "Positive EV: a potentially favourable price, but only if the "
                        "estimated probability is accurate."
                    ),
                    html.Li(EDGE_VS_EV),
                    html.Li(ODDS_SOURCE),
                ],
                className="small value-help",
            ),
        ],
        className="acc value-glossary",
    )


def model_comparison(market: str, ov: OddsView | None, base: dict) -> html.Div:
    """Full model vs market breakdown for every outcome of the selected market, using
    the model baseline (as the Screener does). Comparison only: no recommendation."""
    mv = market_value(market, ov, base)
    head_row = html.Div(html.Span("Model vs market", className="label"), className="label-row")
    if mv is None:
        return html.Div(
            [
                head_row,
                html.P(
                    "Market data unavailable: no bookmaker prices to compare with.",
                    className="muted small",
                ),
            ],
            className="model-compare",
        )
    dm = displayed_market(ov, market)
    rows = []
    for o in mv.outcomes:
        label = dict(MARKET_KEYS[market])[o.key]
        rows.append(
            html.Tr(
                [
                    html.Td(label),
                    html.Td(pct1(o.probability), className="num"),
                    html.Td(pct1(o.market_probability), className="num"),
                    _signed_cell(o.edge, edge_text(o.edge), positive_edge),
                    html.Td(
                        str(o.odds) if o.odds else "—",
                        className="num",
                        title=f"Bookmaker prices {_range(o)}" if _range(o) else None,
                    ),
                    _signed_cell(o.ev, ev_text(o.ev) if o.odds else "EV unavailable", positive_ev),
                ]
            )
        )
    head = html.Tr(
        [
            html.Th("Outcome"),
            # one accessible popover per concept (keyboard and touch, not hover-only)
            html.Th(education.term("Model", "model_probability"), className="num"),
            html.Th(education.term("Market", "market_probability"), className="num"),
            html.Th(education.term("Edge", "edge"), className="num"),
            html.Th(education.term("Odds", "reference_odds"), className="num"),
            html.Th(education.term("EV", "ev"), className="num"),
        ]
    )
    notes = []
    if not mv.complete:
        notes.append(
            "Not every outcome is priced, so market probabilities and edges are "
            "unavailable. EV is shown only where a price exists."
        )
    ranges = [f"{dict(MARKET_KEYS[market])[o.key]} {r}" for o in mv.outcomes if (r := _range(o))]
    src = (
        f"Model baseline vs consensus reference odds from {dm.consensus.sources} independent "
        f"bookmaker group{'s' if dm.consensus.sources != 1 else ''}."
    )
    if ranges:
        src += " Individual bookmaker prices: " + "; ".join(ranges) + "."
    notes.append(src)
    if dm.status == "stale":
        notes.append(
            "These prices are stale and may no longer be available; the Match Lab "
            "does not rank stale prices."
        )
    notes.append(
        "Differences show where the model and the market disagree; they are not "
        "betting advice and not proof that the market is wrong."
    )
    return html.Div(
        [
            head_row,
            html.Div(
                html.Table(
                    [html.Thead(head), html.Tbody(rows)], className="grid compact value-table"
                ),
                className="scroll-x",
            ),
            *[html.P(n, className="muted small") for n in notes],
            education.model_guidance("lab"),
            value_glossary(),
        ],
        className="model-compare",
    )


def ev_explainer() -> html.Details:
    return html.Details(
        [
            html.Summary("What is Expected Value (EV)?"),
            html.P(EV_SHORT, className="small"),
            html.P(
                [
                    "Example: you estimate a 55% chance and the odds are 2.10. ",
                    html.Strong("(0.55 × 2.10) − 1 = +15.5%"),
                    ". This suggests a positive theoretical return over many comparable bets, "
                    "provided your probability estimates are accurate. The break-even "
                    "probability at 2.10 is 1 ÷ 2.10 = 47.6%.",
                ],
                className="small",
            ),
            html.P(
                "EV uses the original bookmaker odds. The market probability (margin removed) "
                "is used only for the probability edge.",
                className="muted small",
            ),
            html.P(EV_CAUTION, className="small ev-caution"),
        ],
        className="acc ev-explainer",
    )


def value_check(market: str, ov: OddsView | None, base: dict, mine: dict | None) -> html.Div:
    """Section D: your final probability vs the market. Final EV = your probability ×
    consensus odds − 1; with no adjustments your probability is the model's."""
    yours = mine or base
    mv = market_value(market, ov, yours)
    model_mv = market_value(market, ov, base)
    head = html.Div(
        [html.Span("Your value check", className="label"), role_tag("Market", "market")],
        className="label-row",
    )
    if mv is None:
        return html.Div(
            [
                head,
                html.P(
                    "Market data unavailable: EV unavailable for this market.",
                    className="muted small",
                ),
                ev_explainer(),
            ],
            className="value-check",
        )
    model_by_key = {o.key: o for o in model_mv.outcomes}
    rows = []
    for o in mv.outcomes:
        m = model_by_key[o.key]
        cells = [
            html.Td(  # the odds the EV uses sit under the outcome (keeps phones scroll-free)
                [
                    html.Span(dict(MARKET_KEYS[market])[o.key]),
                    html.Span(
                        f"at {o.odds}" if o.odds else "no price", className="muted small odds-at"
                    ),
                ]
            ),
            html.Td(pct1(o.probability), className="num strong"),
            html.Td(pct1(o.market_probability), className="num"),
            _signed_cell(o.edge, edge_text(o.edge), positive_edge),
        ]
        if mine:
            cells.append(
                _signed_cell(m.ev, ev_text(m.ev) if m.odds else "EV unavailable", positive_ev)
            )
        cells.append(_signed_cell(o.ev, ev_text(o.ev) if o.odds else "EV unavailable", positive_ev))
        rows.append(html.Tr(cells))
    th = [
        html.Th("Outcome · odds", title=ODDS_SOURCE),
        html.Th(
            "Your final probability" if mine else "Your probability",
            className="num",
            title="Probability after your optional adjustments",
        ),
        html.Th("Market", className="num", title=MARKET_PROB_HELP),
        html.Th("Your edge", className="num", title=EDGE_HELP),
    ]
    if mine:
        th.append(html.Th("Model EV", className="num", title="EV at the model baseline"))
    th.append(html.Th("Your EV", className="num", title=EV_HELP))
    best = mv.best_ev()
    if best is not None:
        label = dict(MARKET_KEYS[market])[best.key]
        verdict = html.P(
            [
                f"Positive estimated EV based on {'your estimate' if mine else 'the model'}: ",
                html.Strong(
                    f"{label} {ev_text(best.ev)}",
                    # 1X2: the outcome's identity colour (style.css --out-*); two-way
                    # markets keep the neutral positive colour
                    className=f"out-{best.key}" if market == "1X2" else None,
                ),
                " at the consensus odds. Potential value only if the probability is right.",
            ],
            className="small val-pos-text",
        )
    else:
        verdict = html.P("No positive estimated EV at these odds.", className="small")
    notes = [verdict]
    if not mine:
        notes.append(
            html.P(
                "No adjustments yet: your probability equals the model "
                "probability. Adjust the estimated goals above to see how the "
                "probability, edge and EV change.",
                className="muted small",
            )
        )
    if not mv.complete:
        notes.append(
            html.P(
                "Not every outcome is priced, so the market probability and edge are unavailable.",
                className="muted small",
            )
        )
    dm = displayed_market(ov, market)
    if dm is not None and dm.status == "stale":
        notes.append(
            html.P(
                "Based on stale prices that may no longer be available.",
                className="small stale-note",
            )
        )
    return html.Div(
        [
            head,
            html.Div(
                html.Table(
                    [html.Thead(html.Tr(th)), html.Tbody(rows)],
                    className="grid compact value-table",
                ),
                className="scroll-x",
            ),
            *notes,
            ev_explainer(),
        ],
        className="value-check",
    )


_MARKET_KEYS = {
    "1X2": (("home", "Home"), ("draw", "Draw"), ("away", "Away")),
    "BTTS": (("btts_yes", "BTTS Yes"), ("btts_no", "BTTS No")),
    "OU25": (("over", "Over 2.5"), ("under", "Under 2.5")),
}


def fitted_comparison(market: str, sp: dict) -> html.Div:
    """State B: the actual bookmaker consensus the fit used, beside the probabilities
    fitted through the market-implied estimated goals, as separate rows (CP1 §7).
    No edge or EV: the two come from the same prices."""
    cons, fit = sp.get("consensus") or {}, sp["probabilities"]
    keys = _MARKET_KEYS[market]
    used = all(k in cons for k, _ in keys)

    def row(label, cls, values):
        return html.Tr(
            [html.Th(label, scope="row", className=cls)]
            + [html.Td(pct1(v) if v is not None else "—", className="num") for v in values]
        )

    table = html.Table(
        [
            html.Thead(html.Tr([html.Th("")] + [html.Th(t, className="num") for _, t in keys])),
            html.Tbody(
                [
                    row(
                        "Bookmaker consensus (actual)",
                        "actual",
                        [cons.get(k) if used else None for k, _ in keys],
                    ),
                    row(f"{MARKET_SOURCE_LABEL} (fitted)", "fitted", [fit[k] for k, _ in keys]),
                ]
            ),
        ],
        className="grid compact lab-table fitted-cmp",
    )
    frozen = sp.get("context") == "frozen"
    return html.Div(
        [
            html.Div("Bookmaker consensus and fitted probabilities", className="lab-subhead"),
            table,
            html.P(
                ("Frozen Weekly Challenge consensus. " if frozen else "")
                + (
                    "The fit did not use this market; the fitted row follows from the other "
                    "markets."
                    if not used
                    else "The two rows differ because one pair of estimated goals cannot match "
                    "every bookmaker price exactly."
                ),
                className="muted small",
            ),
            html.P(NO_EDGE_NOTE, className="muted small no-edge"),
        ],
        className="fitted-compare",
    )


def bookmaker_card(
    r: dict,
    ov: OddsView | None,
    market: str,
    data: ScreenerData,
    league: str,
    state: dict | None,
) -> html.Section:
    c = r.get("_context") or {}
    frozen_at = c.get("frozen_at") if c.get("kind") == "round" else None
    card = _market_card(ov, MARKET_OF[market], data, league, frozen_at=frozen_at)
    head = card.children[0]
    head.children.append(html.Div(role_tag("Market", "market"), className="card-tag"))
    g = r["goal_model"]
    sp = starting_point(r)
    if g.get("available"):
        compare = model_comparison(market, ov, g["probabilities"])
    elif sp is not None:
        compare = fitted_comparison(market, sp)
    else:
        compare = html.P(g.get("message"), className="muted small")
    card.children.append(html.Div(compare, id="lab-compare"))
    return card


def context_line(r: dict, data, ov=None, market: str | None = None) -> html.Div | None:
    """Which analytical context is shown, with its own stored times (Phase 8 CP3A-4):
    the Weekly Challenge snapshot (round and frozen time) or the latest available data
    (the model's calculation time and, where available, when the market's bookmaker
    prices were observed). Never called live or real-time."""
    c = r.get("_context") or {}
    note = lambda text: html.P(text, className="muted small lab-context-note")  # noqa: E731
    if c.get("kind") == "round":
        parts = [html.Span("Weekly Challenge snapshot", className="ctx-tag frozen")]
        if c.get("round"):
            parts.append(html.Span(f"Round {c['round']}", className="muted small"))
        parts.append(html.Span(f"Frozen: {data.local(c.get('frozen_at'))} {data.tz_label}",
                               className="muted small"))  # fmt: skip
        return html.Div(
            [
                html.Div(parts, className="lab-context-line"),
                note(
                    "All participants use these frozen odds and estimates. Current market "
                    "prices and model estimates may differ from these frozen values."
                ),  # fmt: skip
            ],
            className="lab-context",
        )
    if c.get("kind") == "live":
        parts = [html.Span("Latest available data", className="ctx-tag latest")]
        when = c.get("updated_at")
        if when:
            parts.append(html.Span(f"Model calculated: {data.local(when)} {data.tz_label}",
                                   className="muted small"))  # fmt: skip
        seen = _observed(ov, market)
        parts.append(html.Span(
            f"Odds observed: {data.local(seen)} {data.tz_label}" if seen
            else "No current bookmaker prices", className="muted small"))  # fmt: skip
        return html.Div(
            [
                html.Div(parts, className="lab-context-line"),
                note(
                    "Research only: this analysis does not affect the Weekly Challenge or "
                    "your portfolio."
                ),  # fmt: skip
            ],
            className="lab-context",
        )
    return None


def _observed(ov, market):
    """When the market's displayed bookmaker prices were retrieved, or None."""
    try:
        dm = ov.markets[MARKET_OF[market]]
    except (AttributeError, KeyError, TypeError):
        return None
    return dm.snapshot_at if dm is not None and dm.consensus is not None else None


def statistics_note(r: dict, data) -> str:
    """The footnote's time basis (CP3A-4): in the frozen context the estimates are the
    snapshot's, not calculated at the latest data's cut-off; the form, head-to-head and
    league context still use the latest results."""
    cutoff = f"{data.local(r['cutoff'])} {data.tz_label}"
    if (r.get("_context") or {}).get("kind") == "round":
        return (
            f"Estimated goals and probabilities are the frozen Weekly Challenge values. "
            f"Form, head-to-head and league positions use results before {cutoff}."
        )
    return f"Statistics use only results before {cutoff}. Goal Model {gm.GOAL_MODEL_VERSION}."


# ----------------------------------------------------------------- panel
def render_detail(
    r: dict | None,
    ov: OddsView | None,
    official: dict,
    market: str,
    data: ScreenerData,
    adj: dict | None = None,
    notice: str | None = None,
) -> Any:
    """``adj`` is the fixture's user state from the browser store (or None);
    ``notice`` explains earlier adjustments that no longer apply."""
    if r is None:
        return html.Div("Select a fixture to open The Match Lab.", className="empty")
    f = r["fixture"]
    league = LEAGUE_SHORT.get(f["competition_id"], f["competition"])
    available = starting_point(r) is not None
    state = normalise_state(adj, baseline_rounded(r) if available else None)
    if not available:
        state = new_state() | {"cats": state["cats"]}  # notes kept, no adjustments
        for k in CATEGORY_KEYS:
            state["cats"][k]["home"] = state["cats"][k]["away"] = 0.0
    lab = html.Section(
        [
            card_head("Match analysis"),
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
                    context_line(r, data, ov, market),
                    html.P(notice, className="lab-message adj-reset", role="status")
                    if notice
                    else None,
                ],
                className="detail-header",
            ),
            lab,
            bookmaker_card(r, ov, market, data, league, state if available else None),
            html.P(statistics_note(r, data), className="muted small"),
        ],
        className="detail",
    )
