"""Rendering for the match analysis panel (pure functions, no callbacks).

Layout hierarchy (Milestone 5):
  Level 1  summary: fixture, headline indicator, team figures, odds + status
  Level 2  short explanation, with an expandable component breakdown
  Level 3  collapsed sections: matches used, full odds, positions, H2H, other markets
"""

from __future__ import annotations

from typing import Any

from dash import html

from diski9.api_football.markets import Market

from .data import (
    LEAGUE_SHORT,
    MARKET_OF,
    MARKET_OUTCOME_ORDER,
    OUTCOME_LABEL,
    OddsView,
    ScreenerData,
)

FORM_TOOLTIP = (
    "Diski Form Score measures a team's recent performance using points earned, goal "
    "difference and bonuses for winning streaks, goals scored and defensive performance. "
    "Scores range from 0 to 5."
)
LIMITED_FORM = "Fewer than five eligible matches for at least one team, so the score uses only the matches available."
LIMITED_GOALS = (
    "Based on fewer than six relevant current-season matches for at least one team. "
    "Historical percentages may be unstable."
)
PROVENANCE_LABEL = {
    "current_season_same_division": "This season",
    "previous_season_same_division": "Earlier season",
    "other_division": "Other division",
}
MARKET_TITLE = {
    "1X2": "Match result",
    "BTTS": "Both teams to score",
    "OU25": "Over/Under 2.5 goals",
}


def basis_help(market: str) -> list:
    """Form Basis tooltip, contextual to the market's lookback."""
    n = "five" if market == "1X2" else "ten"
    scope = "" if market == "1X2" else " current-season"
    return [
        html.P(
            [
                html.Strong("Venue-specific: "),
                f"uses the home team's last {n}{scope} home matches "
                f"and the away team's last {n}{scope} away matches.",
            ]
        ),
        html.P(
            [
                html.Strong("Overall: "),
                f"uses each team's last {n}{scope} matches, whether played at home or away.",
            ]
        ),
    ] + (
        [
            html.P(
                "Match result looks back five matches; BTTS and Over/Under look back up to ten "
                "current-season matches.",
                className="muted small",
            )
        ]
        if market == "1X2"
        else []
    )


def info(content: Any, label: str = "More information", extra_class: str = "") -> html.Details:
    """Small 'i' popover. Native <details>, so it works with mouse, keyboard and touch."""
    return html.Details(
        [
            html.Summary("i", title=label, **{"aria-label": label}),
            html.Div(content, className="info-pop"),
        ],
        className=f"info {extra_class}".strip(),
    )


def pill(text: str, kind: str = "") -> html.Span:
    return html.Span(text, className=f"pill {kind}".strip())


def section(title: str, *children: Any, open_: bool = False) -> html.Details:
    return html.Details(
        [html.Summary(title), html.Div(children, className="section-body")],
        className="more",
        open=open_,
    )


def sequence(seq: str) -> html.Span:
    if not seq:
        return html.Span("No matches", className="muted")
    return html.Span(
        [html.Span(x, className=f"res res-{x}") for x in seq.split("-")], className="sequence"
    )


def tone(value: float | None) -> str:
    """Colour class for a signed value (no alignment)."""
    if value is None or abs(value) < 1e-12:
        return ""
    return "pos" if value > 0 else "neg"


def signed_class(value: float | None) -> str:
    return f"num {tone(value)}".strip()


# ------------------------------------------------------------------- level 1
def summary_card(r: dict, market: str, ov: OddsView | None, data: ScreenerData) -> html.Section:
    f, t, mr = r["fixture"], r["teams"], r["match_result"]
    if market == "1X2":
        headline = html.Div(
            [
                html.Div(
                    [
                        html.Span("Form Difference", className="label"),
                        info(
                            "Home team's Diski Form Score minus the away team's. Positive favours the home "
                            "team's recent form, negative the away team's.",
                            "About Form Difference",
                        ),
                    ],
                    className="label-row",
                ),
                html.Div(
                    mr["form_difference_display"] or "—",
                    className=f"headline {tone(mr['form_difference'])}",
                ),
                html.Div(mr["note"], className="muted small"),
            ]
        )
        tiles = [
            html.Div(
                [
                    html.Div(t[s]["team"], className="tile-team"),
                    html.Div(
                        [
                            html.Span(t[s]["form"]["display"] or "—", className="tile-value"),
                            html.Span(" / 5", className="muted"),
                        ]
                    ),
                    sequence(t[s]["form"]["sequence"]),
                    _sample_note(t[s]["form"]["sample"], "form"),
                ],
                className="tile",
            )
            for s in ("home", "away")
        ]
        label_row = html.Div(
            [
                html.Span("Diski Form Score", className="label"),
                info(FORM_TOOLTIP, "About Diski Form Score"),
            ],
            className="label-row",
        )
        limited = r["limited_data"]["form"]
        limited_text = LIMITED_FORM
    else:
        key = "btts" if market == "BTTS" else "over_2_5"
        block = r["btts"] if market == "BTTS" else r["over_under_2_5"]
        yes_lbl, no_lbl = ("BTTS Yes", "BTTS No") if market == "BTTS" else ("Over 2.5", "Under 2.5")
        yes = block["yes_display"] if market == "BTTS" else block["over_display"]
        no = block["no_display"] if market == "BTTS" else block["under_display"]
        headline = html.Div(
            [
                html.Div(
                    [
                        html.Span("Historical indicator", className="label"),
                        info(
                            "Average of the two teams' historical rates. It describes past matches; "
                            "it is not a predicted probability.",
                            "About the indicator",
                        ),
                    ],
                    className="label-row",
                ),
                html.Div(
                    [
                        html.Span(f"{yes_lbl} ", className="muted"),
                        html.Span(yes or "—", className="headline"),
                        html.Span(f"   {no_lbl} ", className="muted"),
                        html.Span(no or "—", className="headline-2"),
                    ]
                ),
            ]
        )
        tiles = [
            html.Div(
                [
                    html.Div(t[s]["team"], className="tile-team"),
                    html.Div(
                        (t[s]["goals"][key] or {}).get("display", "No matches yet"),
                        className="tile-value",
                    ),
                    html.Div(_goals_scope(t[s]["window"]), className="muted small"),
                ],
                className="tile",
            )
            for s in ("home", "away")
        ]
        label_row = html.Div(html.Span(f"{yes_lbl} rate", className="label"), className="label-row")
        limited = r["limited_data"]["goals"]
        limited_text = LIMITED_GOALS
    return html.Section(
        [
            headline,
            label_row,
            html.Div(tiles, className="tiles"),
            html.Div(pill("Limited data", "warn"), className="limited-row") if limited else None,
            html.P(limited_text, className="muted small") if limited else None,
            odds_strip(
                ov, MARKET_OF[market], data, LEAGUE_SHORT.get(f["competition_id"], f["competition"])
            ),
        ],
        className="card summary",
    )


def _goals_scope(window: str) -> str:
    return {"home": "current-season home matches", "away": "current-season away matches"}.get(
        window, "current-season matches"
    )


def _sample_note(sample: dict, kind: str) -> html.Div:
    n = sample["matches"]
    parts = [f"{n} match{'es' if n != 1 else ''}"]
    if sample.get("note"):
        parts.append(sample["note"].replace("Includes ", "incl. "))
    return html.Div(" · ".join(parts), className="muted small")


def status_badge(status: str) -> html.Span:
    return pill(
        {"fresh": "Fresh", "stale": "Stale", "unavailable": "Unavailable"}[status],
        {"fresh": "ok", "stale": "warn", "unavailable": ""}[status],
    )


def odds_strip(ov: OddsView | None, market: Market, data: ScreenerData, league: str) -> html.Div:
    if ov is None or not ov.league_has_odds:
        return html.Div(
            [
                html.Span("Reference odds", className="label"),
                html.Div(
                    f"API-Football does not currently provide bookmaker odds for the {league}.",
                    className="muted small",
                ),
            ],
            className="odds-strip",
        )
    dm = ov.markets[market]
    if dm.status == "unavailable":
        return html.Div(
            [
                html.Div(
                    [html.Span("Reference odds", className="label"), status_badge("unavailable")],
                    className="label-row",
                ),
                html.Div(dm.reason, className="muted small"),
            ],
            className="odds-strip",
        )
    mc, ip = dm.consensus, dm.implied
    cells = []
    for o in MARKET_OUTCOME_ORDER[market]:
        oc = mc.outcomes[o]
        adj = ip.margin_adjusted.get(o) if ip and ip.margin_adjusted else None
        cells.append(
            html.Div(
                [
                    html.Div(OUTCOME_LABEL[o], className="muted small"),
                    html.Div(
                        str(oc.consensus_odds) if oc.consensus_odds else "—", className="price"
                    ),
                    html.Div(f"{adj * 100:.1f}% implied" if adj else "", className="muted small"),
                ],
                className="price-cell",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Span("Reference odds", className="label"),
                    status_badge(dm.status),
                    html.Span(freshness_text(dm, data), className="muted small"),
                ],
                className="label-row",
            ),
            html.Div(cells, className="prices"),
            html.Div(
                "Consensus reference odds — not an offer from any bookmaker.",
                className="muted small",
            ),
        ],
        className=f"odds-strip {dm.status}",
    )


def _ago(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    return "under 1 h ago" if hours < 1 else f"{hours:.0f} h ago"


def freshness_text(dm, data: ScreenerData) -> str:
    """Separates Diski 9's own verification time from the provider's feed time."""
    mc = dm.consensus
    now = data.snapshot().loaded_at
    checked = f"checked by Diski 9 {data.local(mc.latest_observation)} ({_ago(dm.age_hours)})"
    provider_age = (
        (now - mc.provider_updated_at).total_seconds() / 3600 if mc.provider_updated_at else None
    )
    provider = f"provider update {data.local(mc.provider_updated_at)} ({_ago(provider_age)})"
    if dm.status == "stale":
        return f"{provider}; {checked}. Prices may have changed."
    return f"{checked}; {provider}"


# ------------------------------------------------------------------- level 2
def explanation_card(r: dict, market: str) -> html.Section:
    if market == "1X2":
        basis = (
            "last five home (home team) and away (away team) matches"
            if r["basis"] == "venue"
            else "each team's last five matches"
        )
        text = (
            f"Each team gets a Diski Form Score (0–5) from its {basis}: points earned, goal "
            "difference and three bonuses. Form Difference is home score minus away score."
        )
        body = section("How is Form Score calculated?", form_breakdown_table(r))
    else:
        what = "both teams scored" if market == "BTTS" else "there were three or more goals"
        basis = "home (home team) and away (away team)" if r["basis"] == "venue" else "all"
        text = (
            f"For each team: the share of its last (up to ten) current-season {basis} matches in which "
            f"{what}. The two rates are averaged. Earlier seasons and other divisions are not used."
        )
        body = section("How is the indicator calculated?", goals_breakdown_table(r, market))
    return html.Section(
        [html.H3("How it's calculated"), html.P(text, className="explain"), body], className="card"
    )


def form_breakdown_table(r: dict) -> html.Div:
    t = r["teams"]
    b = {s: t[s]["form"]["breakdown"] for s in ("home", "away")}

    def cell(side: str, fn) -> html.Td:
        return html.Td(fn(b[side]) if b[side] else "—", className="num")

    def award(x: float) -> str:
        return f"+{x:.1f}" if x else "0.0"

    rows = [
        ("Matches used", lambda x: str(x["matches"])),
        ("Points earned → award", lambda x: f"{x['points']} → {award(x['points_award'])}"),
        (
            "Goal difference → award",
            lambda x: f"{x['goal_difference']:+d} → {award(x['goal_difference_award'])}",
        ),
        (
            "Won last 3 matches",
            lambda x: (
                award(x["bonus_last_three_wins"])
                if x["bonus_last_three_wins_possible"]
                else "n/a (<3 matches)"
            ),
        ),
        ("Scored 11+ goals", lambda x: f"{x['goals_for']} → {award(x['bonus_goals_scored'])}"),
        (
            "Conceded 2 or fewer",
            lambda x: (
                f"{x['goals_against']} → {award(x['bonus_goals_conceded'])}"
                if x["bonus_goals_conceded_possible"]
                else "n/a (needs 5 matches)"
            ),
        ),
        ("Raw total (max 6.5)", lambda x: f"{x['raw']:.1f}"),
        ("Diski Form Score = raw ÷ 6.5 × 5", lambda x: x["form_score_display"]),
    ]
    body = [
        html.Tr([html.Td(label)] + [cell(s, fn) for s in ("home", "away")]) for label, fn in rows
    ]
    return html.Div(
        [
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [html.Th("")]
                                + [html.Th(t[s]["team"], className="num") for s in ("home", "away")]
                            )
                        ),
                        html.Tbody(body),
                    ],
                    className="grid compact",
                ),
                className="scroll-x",
            ),
            html.P(
                "Points: 0–2 → 0, 3–5 → 0.5, 6–8 → 1.0, 9–11 → 1.5, 12–14 → 2.0, 15 → 2.5. "
                "Goal difference: 0 or less → 0, +1–2 → 0.5, +3–4 → 1.0, +5–6 → 1.5, +7–8 → 2.0, "
                "+9 or more → 2.5. Bonuses +0.5 each.",
                className="muted small",
            ),
        ]
    )


def goals_breakdown_table(r: dict, market: str) -> html.Div:
    key = "btts" if market == "BTTS" else "over_2_5"
    t = r["teams"]
    rows = []
    for s in ("home", "away"):
        rate = t[s]["goals"][key]
        rows.append(
            html.Tr(
                [
                    html.Td(t[s]["team"]),
                    html.Td(str(rate["hits"]) if rate else "—", className="num"),
                    html.Td(str(rate["matches"]) if rate else "0", className="num"),
                    html.Td(
                        rate["display"].split(" ")[-1].strip("()") if rate else "—", className="num"
                    ),
                ]
            )
        )
    block = r["btts"] if market == "BTTS" else r["over_under_2_5"]
    yes = block["yes_display"] if market == "BTTS" else block["over_display"]
    lbl = "BTTS matches" if market == "BTTS" else "3+ goal matches"
    return html.Div(
        [
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th("Team"),
                                    html.Th(lbl, className="num"),
                                    html.Th("Matches", className="num"),
                                    html.Th("Rate", className="num"),
                                ]
                            )
                        ),
                        html.Tbody(rows),
                    ],
                    className="grid compact",
                ),
                className="scroll-x",
            ),
            html.P(
                f"Combined = (home rate + away rate) ÷ 2 = {yes or '—'}. The opposite outcome is 100% minus this.",
                className="muted small",
            ),
        ]
    )


# ------------------------------------------------------------------- level 3
def matches_section(r: dict, market: str) -> html.Details:
    key = "form" if market == "1X2" else "goals"
    parts = []
    for s in ("home", "away"):
        tm = r["teams"][s]
        parts.append(html.H4(f"{tm['team']} ({len(tm[key]['matches'])} matches)"))
        parts.append(matches_table(tm[key]["matches"], market))
    return section("Matches used", *parts)


def matches_table(matches: list[dict], market: str) -> html.Div:
    if not matches:
        return html.Div("No eligible matches.", className="muted small")
    extra = {"BTTS": "BTTS", "OU25": "3+ goals"}.get(market)
    head = ["Date", "Opponent", "H/A", "Score", "Result", "Competition"] + (
        [extra] if extra else []
    )
    rows = []
    for m in matches:
        comp = [m["competition"]]
        if m["provenance"] != "current_season_same_division":
            comp += [" ", pill(PROVENANCE_LABEL[m["provenance"]], "subtle")]
        if m.get("unverified_venue"):
            comp += [" ", pill("unverified venue", "subtle")]
        cells = [
            html.Td(m["date"]),
            html.Td(m["opponent"]),
            html.Td(m["venue"]),
            html.Td(m["score"], className="num"),
            html.Td(html.Span(m["result"], className=f"res res-{m['result']}")),
            html.Td(comp),
        ]
        if extra:
            flag = m["btts"] if market == "BTTS" else m["over_2_5"]
            cells.append(html.Td("Yes" if flag else "No"))
        rows.append(html.Tr(cells))
    return html.Div(
        html.Table(
            [
                html.Thead(
                    html.Tr([html.Th(h, className="num" if h == "Score" else None) for h in head])
                ),
                html.Tbody(rows),
            ],
            className="grid compact",
        ),
        className="scroll-x",
    )


def odds_section(ov: OddsView | None, data: ScreenerData, league: str) -> html.Details:
    if ov is None or not ov.league_has_odds:
        return section(
            "Reference odds and market-implied probabilities",
            html.P(
                f"API-Football does not currently provide bookmaker odds for the {league}. "
                "The statistics are unaffected.",
                className="muted",
            ),
        )
    blocks = []
    for market, title in (
        (Market.MATCH_RESULT, "Match result"),
        (Market.BTTS, "Both teams to score"),
        (Market.OVER_UNDER_25, "Over/Under 2.5"),
    ):
        dm = ov.markets[market]
        head = html.Div([html.H4(title), status_badge(dm.status)], className="label-row")
        if dm.status == "unavailable":
            blocks.append(
                html.Div([head, html.P(dm.reason, className="muted small")], className="odds-block")
            )
            continue
        mc, ip = dm.consensus, dm.implied
        rows = []
        for o in MARKET_OUTCOME_ORDER[market]:
            oc = mc.outcomes[o]
            raw = ip.raw.get(o)
            adj = ip.margin_adjusted.get(o) if ip.margin_adjusted else None
            rows.append(
                html.Tr(
                    [
                        html.Td(OUTCOME_LABEL[o]),
                        html.Td(
                            str(oc.consensus_odds) if oc.consensus_odds else "—",
                            className="num strong",
                        ),
                        html.Td(f"{raw * 100:.1f}%" if raw else "—", className="num"),
                        html.Td(f"{adj * 100:.1f}%" if adj else "—", className="num"),
                    ]
                )
            )
        table = html.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Outcome"),
                            html.Th("Consensus odds", className="num"),
                            html.Th("Raw implied", className="num"),
                            html.Th("Market-implied", className="num"),
                        ]
                    )
                ),
                html.Tbody(rows),
            ],
            className="grid compact",
        )
        notes = [f"{mc.sources} independent bookmaker group{'s' if mc.sources != 1 else ''}"]
        if ip.overround is not None:
            notes.append(f"combined margin removed {ip.overround * 100:.1f}%")
        blocks.append(
            html.Div(
                [
                    head,
                    html.Div(table, className="scroll-x"),
                    html.P(" · ".join(notes), className="muted small"),
                    html.P(
                        f"{freshness_text(dm, data)} Times in {data.tz_label}; the provider time is "
                        "feed-level, not a bookmaker price-change time.",
                        className="muted small",
                    ),
                ],
                className="odds-block",
            )
        )
    about = section(
        "About these figures",
        html.P(
            "Consensus odds are the median price across independent bookmakers (brands under common "
            "ownership count once). Raw implied probability is 1 ÷ odds; market-implied probability "
            "removes the combined bookmaker margin. Stale prices are shown for reference only and may "
            "have changed. The provider feed time is a feed-level timestamp, not the moment a bookmaker "
            "changed a price. Freshness rules are provisional until the odds monitoring trial completes. "
            "These figures describe the betting market and are kept separate from Diski 9's historical "
            "indicators; no betting value is calculated.",
            className="muted small",
        ),
    )
    return section("Reference odds and market-implied probabilities", *blocks, about)


def positions_section(r: dict, official: dict) -> html.Details:
    f = r["fixture"]
    home_id, away_id = r["teams"]["home"]["team_id"], r["teams"]["away"]["team_id"]
    if official and home_id in official and away_id in official:
        rows = [official[home_id], official[away_id]]
        updated = max(
            (x["provider_updated_at"] for x in rows if x["provider_updated_at"]), default=None
        )
        label = "Official standings (API-Football" + (
            f", updated {updated:%d %b %Y})" if updated else ")"
        )
        body = [
            html.Tr(
                [
                    html.Td(n),
                    html.Td(str(x["rank"]), className="num"),
                    html.Td(str(x["points"]), className="num"),
                    html.Td(str(x["played"]), className="num"),
                    html.Td(f"{x['goal_difference']:+d}", className="num"),
                ]
            )
            for n, x in ((f["home"], rows[0]), (f["away"], rows[1]))
        ]
    else:
        lp = r["league_position"]
        label = "Calculated from Diski 9's eligible results (not the official table)"
        body = [
            html.Tr(
                [
                    html.Td(n),
                    html.Td(str(x["position"]) if x else "—", className="num"),
                    html.Td(str(x["pts"]) if x else "", className="num"),
                    html.Td(str(x["p"]) if x else "", className="num"),
                    html.Td(f"{x['gf'] - x['ga']:+d}" if x else "", className="num"),
                ]
            )
            for n, x in ((f["home"], lp["home"]), (f["away"], lp["away"]))
        ]
    head = html.Thead(
        html.Tr(
            [
                html.Th("Team"),
                html.Th("Pos", className="num"),
                html.Th("Pts", className="num"),
                html.Th("P", className="num"),
                html.Th("GD", className="num"),
            ]
        )
    )
    return section(
        "League positions",
        html.P(label, className="muted small"),
        html.Table([head, html.Tbody(body)], className="grid compact"),
        html.P(
            "Context only; league position does not affect any indicator.", className="muted small"
        ),
    )


def h2h_section(r: dict) -> html.Details:
    h = r["head_to_head"]
    if not h:
        return section(
            "Head-to-head", html.P("No previous meetings in the stored leagues.", className="muted")
        )
    rows = [
        html.Tr(
            [
                html.Td(m["date"]),
                html.Td(f"{m['home']} {m['score']} {m['away']}"),
                html.Td(
                    [m["competition"]]
                    + (
                        [" ", pill(m["round"], "subtle")]
                        if m["round"] and not m["round"].startswith("Regular")
                        else []
                    )
                ),
                html.Td(pill("older", "subtle") if m["older"] else ""),
            ]
        )
        for m in h
    ]
    return section(
        "Head-to-head (last 5 meetings)",
        html.Div(html.Table(html.Tbody(rows), className="grid compact"), className="scroll-x"),
        html.P(
            "Context only; head-to-head does not affect any indicator. "
            "'Older' means more than one season ago.",
            className="muted small",
        ),
    )


def other_markets_section(r: dict, market: str) -> html.Details:
    lines = []
    if market != "1X2":
        mr = r["match_result"]
        lines.append(
            html.P(
                [
                    html.Strong("Match result: "),
                    f"Form {r['teams']['home']['form']['display'] or '—'} v "
                    f"{r['teams']['away']['form']['display'] or '—'} "
                    f"(difference {mr['form_difference_display'] or '—'})",
                ]
            )
        )
    if market != "BTTS":
        lines.append(
            html.P(
                [
                    html.Strong("BTTS: "),
                    f"Yes {r['btts']['yes_display'] or '—'} · No {r['btts']['no_display'] or '—'}",
                ]
            )
        )
    if market != "OU25":
        o = r["over_under_2_5"]
        lines.append(
            html.P(
                [
                    html.Strong("Over/Under 2.5: "),
                    f"Over {o['over_display'] or '—'} · Under {o['under_display'] or '—'}",
                ]
            )
        )
    return section("Other markets", *lines)


def render_detail(
    r: dict | None, ov: OddsView | None, official: dict, market: str, data: ScreenerData
) -> Any:
    if r is None:
        return html.Div("Select a fixture to see its analysis.", className="empty")
    f = r["fixture"]
    league = LEAGUE_SHORT.get(f["competition_id"], f["competition"])
    basis = "Venue-specific form" if r["basis"] == "venue" else "Overall form"
    return html.Div(
        [
            html.Div(
                [
                    html.H2(f"{f['home']} v {f['away']}"),
                    html.Div(
                        f"{league} · {data.local(f['kickoff'])} {data.tz_label} · {MARKET_TITLE[market]} · {basis}",
                        className="muted",
                    ),
                ],
                className="detail-header",
            ),
            summary_card(r, market, ov, data),
            explanation_card(r, market),
            html.Div(
                [
                    matches_section(r, market),
                    odds_section(ov, data, league),
                    positions_section(r, official),
                    h2h_section(r),
                    other_markets_section(r, market),
                ],
                className="sections",
            ),
            html.P(
                f"{r['indicator_note']} Uses only results before {data.local(r['cutoff'])} {data.tz_label}.",
                className="muted small",
            ),
        ],
        className="detail",
    )
