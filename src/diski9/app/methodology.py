"""In-app methodology: "How Diski 9 Calculates Probabilities".

Plain English first, technical detail in nested expanders. Facts come from
docs/goal_distribution_research.md and docs/goal_model_crossleague_validation.md;
the worked example is computed live by Goal Model 1.0.
"""

from __future__ import annotations

from dash import html

from diski9.screener import goal_model as gm

from .data import goals2, pct1

CHANGELOG = [
    (
        "Goal Model 1.0",
        "November 2026",
        "First release with Engine 3.0. Season-to-date Poisson model with strength/tempo "
        "smoothing (k_s 12, k_t 96, m0 30).",
    ),
]

LIMITATIONS = [
    "The model does not know about team news: injuries, suspensions, line-ups or transfers.",
    "Draws have historically been slightly underestimated (by about 1–2 percentage points).",
    "Strong favourites may be estimated too cautiously in some leagues, such as La Liga and "
    "Serie A.",
    "BTTS and Over/Under probabilities usually stay close to the league average, because past "
    "goals say less about these markets.",
    "The model is not validated for UEFA competitions, so no probabilities are shown for them.",
    "Probabilities are uncertain estimates. They do not guarantee outcomes or betting profits.",
]


def _p(text: str, cls: str = "") -> html.P:
    return html.P(text, className=cls or None)


def worked_example() -> html.Div:
    home, away = 1.93, 0.96
    p = gm.markets(home, away)
    return html.Div(
        [
            _p(
                f"Suppose the model estimates {goals2(home)} goals for the home team and "
                f"{goals2(away)} for the away team. A Poisson distribution turns each number "
                "into the chance of scoring 0, 1, 2, 3 … goals. Multiplying the two teams' "
                "chances gives every scoreline, and adding up the right scorelines gives:"
            ),
            html.Table(
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td("Home win · Draw · Away win"),
                                html.Td(
                                    f"{pct1(p['home'])} · {pct1(p['draw'])} · {pct1(p['away'])}",
                                    className="num",
                                ),
                            ]
                        ),
                        html.Tr(
                            [
                                html.Td("Both teams score: Yes · No"),
                                html.Td(
                                    f"{pct1(p['btts_yes'])} · {pct1(p['btts_no'])}", className="num"
                                ),
                            ]
                        ),
                        html.Tr(
                            [
                                html.Td("Over 2.5 · Under 2.5"),
                                html.Td(f"{pct1(p['over'])} · {pct1(p['under'])}", className="num"),
                            ]
                        ),
                    ]
                ),
                className="grid compact",
            ),
            _p(
                "If you think the home team will score less, say 1.55 instead of 1.93, every "
                "market is recalculated from the new number in The Match Lab.",
                "muted small",
            ),
        ]
    )


def technical_detail() -> html.Details:
    k = gm.PARAMS
    return html.Details(
        [
            html.Summary("Technical detail (formulas)"),
            html.Div(
                [
                    _p("League averages before kickoff (H home, A away goals per match):"),
                    html.Pre(
                        f"H = (current-season home goals + {k.m0:g} × last season's home goals "
                        "per match)\n    / (current-season matches + "
                        f"{k.m0:g})            (A likewise)"
                    ),
                    _p("For each team, with n_h home and n_a away matches this season:"),
                    html.Pre(
                        "expected scored   E_for = n_h × H + n_a × A\n"
                        "expected conceded E_ag  = n_h × A + n_a × H\n"
                        "g = (H + A) / 2\n"
                        "attack(k)  = (goals scored   + k × g) / (E_for + k × g)\n"
                        "defence(k) = (goals conceded + k × g) / (E_ag  + k × g)\n"
                        f"strength s = √(attack(k_s) / defence(k_s)),  k_s = {k.k_s:g}\n"
                        f"tempo    t = √(attack(k_t) × defence(k_t)),  k_t = {k.k_t:g}"
                    ),
                    _p("Estimated goals:"),
                    html.Pre(
                        "λ_home = H × (s_home / s_away) × t_home × t_away\n"
                        "λ_away = A × (s_away / s_home) × t_home × t_away"
                    ),
                    _p(
                        "Home and away goals are independent Poisson variables. Each market is "
                        "an exact sum over every scoreline (the ignored tail is below 10⁻¹⁵); "
                        "complements are 1 minus the rest, so each market adds up to 100%."
                    ),
                    _p(
                        "Only completed, regular-season league matches of the current season "
                        "and competition, played before kickoff, are used. Earlier seasons and "
                        "other divisions never enter a team's numbers; last season's league "
                        "average is the only historical input.",
                        "muted small",
                    ),
                ],
                className="acc-body",
            ),
        ],
        className="acc",
    )


def _block(title: str, *children, cls: str = "") -> html.Div:
    return html.Div([html.H4(title), *children], className=f"meth-block {cls}".strip())


def _params_table() -> html.Table:
    k = gm.PARAMS
    rows = [
        (
            "Strength smoothing",
            k.k_s,
            "After 12 matches, half of a team's strength comes from its own results.",
        ),
        (
            "Goal tempo smoothing",
            k.k_t,
            "Goal totals vary a lot by chance, so they move towards a team's record slowly.",
        ),
        (
            "League-average prior",
            k.m0,
            "Last season's league averages count as 30 matches at the start of a season.",
        ),
    ]
    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [html.Th("Setting"), html.Th("Value", className="num"), html.Th("What it does")]
                )
            ),
            html.Tbody(
                [
                    html.Tr([html.Td(a), html.Td(f"{v:g}", className="num"), html.Td(c)])
                    for a, v, c in rows
                ]
            ),
        ],
        className="grid compact meth-table",
    )


def market_value_block() -> html.Div:
    """Downstream bookmaker comparison - kept apart from the model's calibration and
    validation: odds are never a model input and nothing here recalibrates the model."""
    return _block(
        "Understanding Market Probabilities and Expected Value",
        _p(
            "This is a comparison layer on top of the model, not part of it. Bookmaker odds "
            "never change Goal Model 1.0's estimated goals or probabilities, and the model's "
            "settings, calibration and validation above are unaffected.",
            "muted small",
        ),
        html.Ul(
            [
                html.Li(
                    [
                        html.Strong("Model probability: "),
                        "the probability estimated by Goal Model 1.0.",
                    ]
                ),
                html.Li(
                    [
                        html.Strong("Market probability: "),
                        "1 ÷ odds for each outcome, then scaled so the outcomes of a market add "
                        "up to 100% (Home, Draw and Away together; BTTS Yes and No; Over and "
                        "Under 2.5). This removes the bookmaker margin. It is a simple "
                        "proportional method, not a perfect estimate of what the market "
                        "really believes, and it needs a price for every outcome.",
                    ]
                ),
                html.Li(
                    [
                        html.Strong("Probability edge: "),
                        "model (or your) probability minus market probability, in percentage "
                        "points. 45% vs 38% is +7.0 pp, not +18%.",
                    ]
                ),
                html.Li(
                    [
                        html.Strong("Expected value (EV): "),
                        "probability × decimal odds − 1, using the original odds, margin "
                        "included. 55% at 2.10 gives (0.55 × 2.10) − 1 = +15.5%: a theoretical "
                        "average return per unit staked if the probability is right. It is not "
                        "a 15.5% chance of winning and not a guaranteed return.",
                    ]
                ),
                html.Li(
                    [
                        html.Strong("Positive EV "),
                        "means a potentially favourable price, conditional on the probability "
                        "being accurate. A positive edge is not proof the bookmaker is wrong.",
                    ]
                ),
            ]
        ),
        _p(
            "A larger edge does not always give a larger EV, because EV also depends on the "
            "price: a long-priced outcome with a small edge can have a higher EV than a short-"
            "priced outcome with a big edge. That is why the Screener can rank by either."
        ),
        _p(
            "The odds are Diski 9 consensus reference odds: for each outcome, the median price "
            "across independent bookmakers that each quote the whole market (brands under common "
            "ownership count once). They are the prices shown in the app, but not an offer from "
            "any single bookmaker, so EV is a reference figure. The Screener ranks fresh prices "
            "only and uses the model's own probabilities; The Match Lab's value check uses your "
            "adjusted probabilities. Odds are collected for all eight leagues; where the "
            "provider has no qualifying prices (currently the PSL and PSL 1st Division), "
            "no odds are shown.",
            "muted small",
        ),
        cls="wide",
    )


def methodology_section() -> html.Details:
    return html.Details(
        [
            html.Summary("How Diski 9 Calculates Probabilities"),
            html.Div(
                [
                    html.Div(
                        [
                            _block(
                                "The short version",
                                _p(
                                    "We estimate how many goals each team is likely to score "
                                    "using goals scored and conceded this season, adjusted for "
                                    "the opponent and the league's home and away scoring "
                                    "patterns. We then use a Poisson goal distribution to "
                                    "calculate the probabilities of different match outcomes."
                                ),
                                _p(
                                    "Early in the season, teams have played relatively few "
                                    "matches. We therefore rely more on league averages until "
                                    "enough results become available. One 4–0 win does not make "
                                    "a team world-beaters."
                                ),
                                _p(
                                    "We do not use betting odds to build these numbers. "
                                    "Bookmaker odds are shown separately, for comparison only. "
                                    "Estimated goals are model-based goal expectations from "
                                    "match results, not shot-based xG."
                                ),
                            ),
                            _block("A worked example", worked_example()),
                        ],
                        className="meth-grid",
                    ),
                    html.Div(
                        [
                            _block(
                                "What changes and what stays fixed",
                                html.Ul(
                                    [
                                        html.Li(
                                            [
                                                html.Strong("Match statistics update "),
                                                "after every completed match: league averages, "
                                                "goals scored and conceded, and so the estimated "
                                                "goals.",
                                            ]
                                        ),
                                        html.Li(
                                            [
                                                html.Strong("Model settings stay fixed "),
                                                "for the whole season, so a team's numbers only "
                                                "change because of results, never because we "
                                                "tweaked the model.",
                                            ]
                                        ),
                                    ]
                                ),
                            ),
                            _block("The fixed settings", _params_table()),
                        ],
                        className="meth-grid",
                    ),
                    _block(
                        "How the settings were chosen and tested",
                        _p(
                            "Strength smoothing (12) and goal tempo smoothing (96) were chosen "
                            "by comparing candidate values on earlier seasons of the English "
                            "Premier League, Championship, South African Premiership and First "
                            "Division (2023/24–2025/26), keeping the values that best explained "
                            "the actual scorelines in those seasons. The same values were picked "
                            "in each of three tuning periods, and they were then tested on later "
                            "seasons they had not seen (3,237 matches)."
                        ),
                        _p(
                            "The league-average prior (30) was not tuned in the same way: it "
                            "was set to match the 30-match minimum Diski 9 uses for league "
                            "averages elsewhere, and a sensitivity check (10, 30 and 100 "
                            "matches) gave very similar early-season results."
                        ),
                        _p(
                            "The settings were then independently validated, without any "
                            "change, on 4,515 matches from La Liga, Ligue 1, the Bundesliga and "
                            "Serie A (2023/24–2026/27). In every league the model's Match Result "
                            "probabilities beat a simple league-average baseline. One shared set "
                            "of settings is used because league-specific tuning added almost "
                            "nothing. Not every competition was used to choose the settings."
                        ),
                        _p(
                            "The Champions League and Europa League were tested too, but teams "
                            "play too few matches in them for this model to be reliable, so no "
                            "probabilities are shown for European competitions yet.",
                            "muted small",
                        ),
                        cls="wide",
                    ),
                    html.Div(
                        [
                            _block("Known limitations", html.Ul([html.Li(x) for x in LIMITATIONS])),
                            _block(
                                "How the model is maintained",
                                html.Ul(
                                    [
                                        html.Li(
                                            "Results and statistics update after completed matches."
                                        ),
                                        html.Li("Settings stay fixed during the season."),
                                        html.Li(
                                            "Accuracy is monitored monthly against the "
                                            "league-average baseline, using only forecasts "
                                            "recorded before kickoff."
                                        ),
                                        html.Li(
                                            "A formal review takes place once a year after "
                                            "the domestic seasons end. Settings change only "
                                            "if a held-out season shows a clear improvement "
                                            "(at least 0.005 in Match Result log loss, "
                                            "statistically supported, with no league or "
                                            "market clearly worse)."
                                        ),
                                        html.Li(
                                            "Every model version, change and its evidence "
                                            "is published."
                                        ),
                                    ]
                                ),
                            ),
                        ],
                        className="meth-grid",
                    ),
                    market_value_block(),
                    _block(
                        "Model version",
                        html.Table(
                            [
                                html.Thead(
                                    html.Tr(
                                        [html.Th("Version"), html.Th("Released"), html.Th("Notes")]
                                    )
                                ),
                                html.Tbody(
                                    [
                                        html.Tr([html.Td(v), html.Td(d), html.Td(n)])
                                        for v, d, n in CHANGELOG
                                    ]
                                ),
                            ],
                            className="grid compact meth-table",
                        ),
                        _p(
                            f"Current: Goal Model {gm.GOAL_MODEL_VERSION} in Engine 3.0. Full "
                            "methodology: docs/methodology.md.",
                            "muted small",
                        ),
                        cls="wide",
                    ),
                    technical_detail(),
                ],
                className="acc-body methodology-body",
            ),
        ],
        className="methodology card",
        id="methodology",
    )
