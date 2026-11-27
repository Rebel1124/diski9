"""Educational copy and the reusable information component (Scenario A3, Checkpoint 3).

One place for the glossary, the general Goal Model guidance and the high-risk underdog
warning text, so every view shows the same words.

* :func:`info` is the existing native ``<details>`` popover (moved here from
  ``views``, which re-exports it). Native disclosure works with mouse, keyboard
  (Tab, then Enter or Space) and touch; it never depends on hover.
* :func:`term` puts one popover beside a term (a column heading, a legend or a
  label), once per concept per view; never in repeated cells or cards.

The definitions describe the calculations in ``diski9.odds.value`` and
``diski9.odds.implied`` exactly (tests/test_a3_guidance.py checks the worked
examples): market probability = (1/odds) / sum(1/odds) over the complete market;
edge = 100 x (estimated probability - market probability) in percentage points;
EV = estimated probability x consensus reference odds - 1, per unit staked; reference
odds = the median price across qualifying independent bookmaker groups
(``diski9.odds.consensus``). The
estimated probability is Diski 9's (Goal Model 1.0) or, in the Match Lab, the
participant's adjusted view.
"""

from __future__ import annotations

from typing import Any

from dash import dcc, html

from .icons import icon

GLOSSARY: dict[str, dict[str, str]] = {
    "market_probability": {
        "title": "Market Probability",
        "short": "The market’s estimated chance of an outcome occurring, after adjusting for "
        "the bookmaker’s margin.",
        "long": "Market probability: inferred from the bookmaker odds (1 ÷ odds), then scaled "
        "so the outcomes add up to 100% to remove the bookmaker margin. A simple "
        "proportional method, not a perfect reading of the market's true beliefs.",
    },
    "model_probability": {
        "title": "Goal Model Probability (D9)",
        "short": "Diski 9’s estimated chance of an outcome occurring, based on its statistical "
        "football model. This is an estimate, not a guarantee.",
        "long": "Model probability: the probability estimated by Goal Model 1.0.",
    },
    "edge": {
        "title": "Edge",
        "short": "The difference between your estimated probability (using Diski 9’s model or "
        "your own adjusted view) and the market probability, measured in percentage "
        "points. A positive estimated edge does not prove a genuine advantage.",
        "long": "Probability edge: probability minus market probability, in percentage points "
        "(pp). 55% vs 48% is +7.0 pp. An edge is not proof that the bookmaker is wrong.",
    },
    "ev": {
        "title": "Expected Value (EV)",
        "short": "The estimated average net return per unit staked over many similar "
        "selections, using the estimated probability and Diski 9’s reference odds. "
        "Positive estimated EV does not guarantee a profit.",
        "long": "Expected value (EV): probability × decimal odds − 1, using the original odds "
        "(with the margin). A theoretical average return per unit staked, assuming the "
        "probability is right.",
    },
    # diski9.odds.consensus: one source per qualifying independent bookmaker group (fresh,
    # eligible, complete market), median price rounded half-up to two decimals.
    "reference_odds": {
        "title": "Reference Odds",
        "short": "Decimal odds derived from the median odds across qualifying independent "
        "bookmaker groups. These are reference odds used for calculations and may differ "
        "from the odds offered by an individual bookmaker.",
        "long": "Odds are Diski 9 consensus reference odds: for each outcome, the median price "
        "across independent bookmakers that quote the whole market. They are not an offer "
        "from any single bookmaker, so EV is a reference figure; individual bookmakers' "
        "prices (range shown) differ.",
    },
}


def short(key: str) -> str:
    return GLOSSARY[key]["short"]


def long(key: str) -> str:
    return GLOSSARY[key]["long"]


# ------------------------------------------------------------------ components
def info(content: Any, label: str = "More information", extra_class: str = "") -> html.Details:
    """Small 'i' popover. Native <details>, so it works with mouse, keyboard and touch."""
    return html.Details(
        [
            html.Summary("i", title=label, **{"aria-label": label}),
            html.Div(content, className="info-pop"),
        ],
        className=f"info {extra_class}".strip(),
    )


def explanation(*keys: str) -> list:
    """Popover content: the title and short definition of each glossary entry."""
    out = []
    for k in keys:
        out.append(html.P([html.Strong(GLOSSARY[k]["title"]), html.Br(), short(k)]))
    return out


def term(label: Any, *keys: str, extra_class: str = "", suffix: str = "") -> html.Span:
    """A term with one educational popover (one or more glossary entries).

    ``suffix`` (punctuation such as ":") is kept on the same line as the label and
    button: the group never wraps internally, while the surrounding text still wraps."""
    titles = " and ".join(GLOSSARY[k]["title"] for k in keys)
    span = html.Span(
        [label, info(explanation(*keys), f"What is {titles}?", "term-info")],
        className=f"term {extra_class}".strip(),
    )
    return html.Span([span, suffix], className="term-keep") if suffix else span


# --------------------------------------------------------------- general guidance
GUIDANCE_TITLE = "Understanding Model Probabilities"
GUIDANCE_P1 = (
    "Goal Model probabilities are estimates, not guarantees. A model probability that is "
    "higher than the market probability does not necessarily mean you have a genuine "
    "advantage (Edge) or positive Expected Value (EV)."
)
GUIDANCE_P2 = (
    "Use these probabilities as a starting point for your own analysis and explore the "
    "Match Lab for additional factors that could influence the outcome."
)
# The Match Lab variant refers to the match factors on the current page.
GUIDANCE_P2_LAB = (
    "Use these probabilities as a starting point for your own analysis and review the match "
    "factors on this page that could influence the outcome."
)


def model_guidance(where: str = "challenge") -> html.Details:
    """The general guidance, collapsed by default (once per view)."""
    p2 = GUIDANCE_P2_LAB if where == "lab" else GUIDANCE_P2
    return html.Details(
        [
            html.Summary([icon("info", "ic-sm"), GUIDANCE_TITLE]),
            html.Div([html.P(GUIDANCE_P1), html.P(p2)], className="small"),
        ],
        className=f"acc model-guidance mg-{where}",
    )


# ------------------------------------------------------- high-risk underdog warning
UNDERDOG_TITLE = "High-Risk Underdog Selection"
UNDERDOG_P1 = (
    "This outcome has a low market-implied probability of occurring (at least 10% but below 20%)."
)
UNDERDOG_P2 = (
    "In our testing, the Goal Model has often assigned higher probabilities to underdogs in "
    "this range than the market. The model may be overestimating their chances."
)
UNDERDOG_P3 = (
    "A higher model probability does not necessarily indicate a genuine Edge or positive "
    "Expected Value (EV). Review the Match Lab factors and consider the uncertainty "
    "carefully before making your selection."
)
UNDERDOG_TAG = "High risk"
UNDERDOG_SHORT = "High-risk underdog: market chance at least 10% but below 20%"


def underdog_panel(picks: list[tuple[str, int]], where: str) -> html.Div | None:
    """One warning block for every selected high-risk underdog (never duplicated):
    a one-line reminder, the full text collapsed, and an existing Match Lab link per
    pick. ``picks`` = [(label, fixture_id)]. Nothing for no picks; never blocks."""
    if not picks:
        return None
    n = len(picks)
    line = (
        "Includes a high-risk underdog (market chance under 20%)."
        if n == 1
        else f"Includes {n} high-risk underdogs (market chance under 20%)."
    )
    links = [
        html.Li(
            [
                html.Span(label),
                " · ",
                dcc.Link(
                    ["Match Lab ", icon("arrow-right", "ic-sm")],
                    href=f"/lab?fixture={fid}",
                    className="ch-lab-link",
                    title="Analyse this match in the Match Lab",
                ),
            ]
        )
        for label, fid in picks
    ]
    return html.Div(
        [
            html.P([icon("alert", "ic-sm"), html.Strong(" " + line)], className="small"),
            html.Details(
                [
                    html.Summary(f"Why? {UNDERDOG_TITLE}"),
                    html.Div(
                        [
                            html.P(UNDERDOG_P1),
                            html.P(UNDERDOG_P2),
                            html.P(UNDERDOG_P3),
                            html.Ul(links, className="small ch-risk-links"),
                        ],
                        className="small",
                    ),  # fmt: skip
                ],
                className="acc",
            ),
        ],
        className=f"ch-risk-panel ch-risk-{where}",
        role="note",
    )
