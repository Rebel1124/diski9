"""Pure rendering helpers for the expanded match analysis (no callbacks here)."""

from __future__ import annotations

from typing import Any

from dash import html

from diski9.api_football.markets import Market

from .data import LEAGUE_SHORT, MARKET_OUTCOME_ORDER, OUTCOME_LABEL, OddsView, ScreenerData

EXPLAIN = {
    "form": (
        "The Form Score summarises recent results: points per game (3 for a win, 1 for a draw) "
        "plus half the average goal difference, with goal difference capped at ±2 per game. "
        "One is then added so the score runs from 0 to 5. "
        "It is a performance index, not a probability or a rating."
    ),
    "vad": (
        "The venue-adjusted difference compares each team with what is typical for home and "
        "away sides in this league. A positive value means the home team's recent home form is "
        "further above the league's typical home form than the away team's away form is above "
        "the typical away form. A value near zero means similar relative form. It does not "
        "mean a draw is likely."
    ),
    "btts": (
        "For each team we count how often both sides scored in its last 10 home (or away) "
        "matches, then average the two rates. It describes what happened before. It is not "
        "the chance that both teams will score in this match."
    ),
    "ou": (
        "For each team we count how often its last 10 home (or away) matches had three or more "
        "goals, then average the two rates. It describes what happened before. It is not the "
        "chance of over 2.5 goals in this match."
    ),
    "odds": (
        "Consensus reference odds are the median price across independent bookmakers with "
        "fresh quotes. They are reference values, not an offer from any bookmaker."
    ),
    "implied": (
        "Market-implied probability is what the reference prices imply after removing the "
        "combined bookmaker margin. It reflects the betting market, not a Diski 9 view, and it "
        "measures something different from the historical indicators above."
    ),
}

PROVENANCE_LABEL = {
    "current_season_same_division": "This season",
    "previous_season_same_division": "Earlier season",
    "other_division": "Other division",
}


def pill(text: str, kind: str = "") -> html.Span:
    return html.Span(text, className=f"pill {kind}".strip())


def card(title: str, *children: Any, extra_class: str = "") -> html.Section:
    return html.Section([html.H3(title), *children], className=f"card {extra_class}".strip())


def explain(key: str) -> html.P:
    return html.P(EXPLAIN[key], className="explain")


def sequence(seq: str) -> html.Div:
    if not seq:
        return html.Div("No matches", className="muted")
    return html.Div(
        [html.Span(x, className=f"res res-{x}") for x in seq.split("-")], className="sequence"
    )


def sample_line(sample: dict, kind: str) -> html.Div:
    parts = [
        f"{sample['matches']} matches",
        f"{sample['current_division_matches']} from current division",
    ]
    if sample.get("previous_season_matches"):
        parts.append(f"{sample['previous_season_matches']} from earlier seasons")
    children: list[Any] = [html.Span(" · ".join(parts), className="muted")]
    if sample.get("note"):
        children.append(pill(sample["note"], "info"))
    if sample.get("unverified_venue_matches"):
        children.append(pill(f"{sample['unverified_venue_matches']} at unverified venue", "info"))
    for reason in sample["limited_data_reasons"]:
        children.append(pill("Limited data: " + reason.replace("_", " "), "warn"))
    return html.Div(children, className="sample-line")


def matches_table(matches: list[dict], market: str) -> html.Table:
    head = ["Date", "Opponent", "H/A", "Score", "Result", "Competition"]
    if market == "BTTS":
        head.append("BTTS")
    elif market == "OU25":
        head.append("Over 2.5")
    rows = []
    for m in matches:
        cells = [
            m["date"],
            m["opponent"],
            m["venue"],
            m["score"],
            html.Span(m["result"], className=f"res res-{m['result']}"),
            html.Span(
                [m["competition"], " ", pill(PROVENANCE_LABEL[m["provenance"]], "subtle")]
                + ([" ", pill("unverified venue", "info")] if m.get("unverified_venue") else [])
            ),
        ]
        if market == "BTTS":
            cells.append("Yes" if m["btts"] else "No")
        elif market == "OU25":
            cells.append("Yes" if m["over_2_5"] else "No")
        rows.append(html.Tr([html.Td(c) for c in cells]))
    return html.Div(
        html.Table(
            [html.Thead(html.Tr([html.Th(h) for h in head])), html.Tbody(rows)], className="mini"
        ),
        className="scroll-x",
    )


def breakdown_table(b: dict | None) -> html.Div:
    if not b:
        return html.Div("No eligible matches: no Form Score can be calculated.", className="muted")
    rows = [
        ("Wins / draws / losses", f"{b['wins']} / {b['draws']} / {b['losses']}"),
        ("Points (per game)", f"{b['points']} ({b['points_per_game']:.2f})"),
        (
            "Goals for – against",
            f"{b['goals_for']} – {b['goals_against']} (GD {b['goal_difference']:+d})",
        ),
        (
            "Goal difference per game",
            f"{b['gd_per_game']:+.2f} → capped {b['capped_gd_per_game']:+.2f}",
        ),
        ("Half of capped GD per game", f"{b['weighted_gd_contribution']:+.2f}"),
        ("Scale offset", f"{b.get('scale_offset', 0):+.2f}"),
        ("Form Score", b["form_score_display"]),
    ]
    return html.Table(
        [html.Tr([html.Td(k), html.Td(v, className="num")]) for k, v in rows], className="kv"
    )


# --------------------------------------------------------------------- sections
def header(r: dict, data: ScreenerData) -> html.Div:
    f = r["fixture"]
    basis = "Venue-specific form" if r["basis"] == "venue" else "Overall form"
    return html.Div(
        [
            html.H2(f"{f['home']} v {f['away']}"),
            html.Div(
                f"{LEAGUE_SHORT.get(f['competition_id'], f['competition'])} · "
                f"{data.local(f['kickoff'], '%a %d %b %Y, %H:%M')} {data.tz_label} · {basis}",
                className="muted",
            ),
            html.Div(
                f"Statistics use only results before {data.local(r['cutoff'], '%d %b %Y %H:%M')} "
                f"{data.tz_label}. {r['indicator_note']}",
                className="muted small",
            ),
        ],
        className="detail-header",
    )


def form_section(r: dict) -> html.Section:
    mr, t = r["match_result"], r["teams"]
    team_cards = []
    for side in ("home", "away"):
        tm = t[side]
        label = {
            "home": "last 5 home matches",
            "away": "last 5 away matches",
            "overall": "last 5 matches",
        }[tm["window"]]
        team_cards.append(
            html.Div(
                [
                    html.H4(tm["team"]),
                    html.Div(
                        [
                            html.Span(tm["form"]["display"] or "—", className="big"),
                            html.Span(label, className="muted"),
                        ]
                    ),
                    sequence(tm["form"]["sequence"]),
                    breakdown_table(tm["form"]["breakdown"]),
                    sample_line(tm["form"]["sample"], "form"),
                ],
                className="team-col",
            )
        )
    bench = mr["benchmark"]
    diff_rows = [
        html.Tr(
            [
                html.Td("Raw difference (home − away)"),
                html.Td(mr["raw_difference_display"] or "—", className="num"),
            ]
        )
    ]
    if r["basis"] == "venue":
        diff_rows.append(
            html.Tr(
                [
                    html.Td("Venue-adjusted difference"),
                    html.Td(mr["venue_adjusted_difference_display"] or "—", className="num strong"),
                ]
            )
        )
    bench_block: list[Any] = []
    if bench:
        bench_block = [
            html.Div(bench["label"], className="muted"),
            html.Table(
                [
                    html.Tr(
                        [
                            html.Td("League home benchmark"),
                            html.Td(bench["home"]["form_score_display"], className="num"),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td("League away benchmark"),
                            html.Td(bench["away"]["form_score_display"], className="num"),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td("League draw rate (context only)"),
                            html.Td(bench["draw_rate_display"], className="num"),
                        ]
                    ),
                ],
                className="kv",
            ),
        ]
        if bench["source"] != "current_season":
            bench_block.append(
                pill(
                    f"This season has {bench['current_season_matches']} eligible matches "
                    f"(needs {bench['min_current_matches']}), so the previous season is used"
                    if bench["source"] == "previous_season"
                    else "Partial current season: no previous season available",
                    "info",
                )
            )
    elif r["basis"] == "venue":
        bench_block = [html.Div("No league benchmark available.", className="muted")]
    return card(
        "Match result: Form Scores",
        explain("form"),
        html.Div(team_cards, className="two-col"),
        html.Table(diff_rows, className="kv diff"),
        explain("vad")
        if r["basis"] == "venue"
        else html.P(
            "On the overall basis only the raw difference is shown, because the league benchmark "
            "would be the same for both teams.",
            className="explain",
        ),
        *bench_block,
    )


def goals_section(r: dict, market: str) -> html.Section:
    key, block = ("btts", r["btts"]) if market == "BTTS" else ("over_2_5", r["over_under_2_5"])
    yes_label, no_label = ("BTTS Yes", "BTTS No") if market == "BTTS" else ("Over 2.5", "Under 2.5")
    yes = block["yes_display"] if market == "BTTS" else block["over_display"]
    no = block["no_display"] if market == "BTTS" else block["under_display"]
    cols = []
    for side in ("home", "away"):
        g = r["teams"][side]["goals"]
        rate = g[key]
        cols.append(
            html.Div(
                [
                    html.H4(r["teams"][side]["team"]),
                    html.Div(rate["display"] if rate else "—", className="big"),
                    html.Table(
                        [
                            html.Tr(
                                [
                                    html.Td("Avg goals scored"),
                                    html.Td(_num(g["avg_goals_for"]), className="num"),
                                ]
                            ),
                            html.Tr(
                                [
                                    html.Td("Avg goals conceded"),
                                    html.Td(_num(g["avg_goals_against"]), className="num"),
                                ]
                            ),
                            html.Tr(
                                [
                                    html.Td("Avg total goals"),
                                    html.Td(_num(g["avg_total_goals"]), className="num"),
                                ]
                            ),
                            html.Tr(
                                [
                                    html.Td("Clean sheets"),
                                    html.Td(str(g["clean_sheets"]), className="num"),
                                ]
                            ),
                            html.Tr(
                                [
                                    html.Td("Failed to score"),
                                    html.Td(str(g["failed_to_score"]), className="num"),
                                ]
                            ),
                        ],
                        className="kv",
                    ),
                    sample_line(g["sample"], "goals"),
                ],
                className="team-col",
            )
        )
    title = "Both teams to score" if market == "BTTS" else "Over/Under 2.5 goals"
    return card(
        f"{title}: historical indicator",
        explain("btts" if market == "BTTS" else "ou"),
        html.Div(cols, className="two-col"),
        html.Div(
            [
                html.Div(
                    [
                        html.Span(f"Combined {yes_label}", className="muted"),
                        html.Span(yes or "—", className="big"),
                    ]
                ),
                html.Div(
                    [
                        html.Span(f"Combined {no_label}", className="muted"),
                        html.Span(no or "—", className="big"),
                    ]
                ),
            ],
            className="combined",
        ),
    )


def recent_matches_section(r: dict, market: str) -> html.Section:
    key = "form" if market == "1X2" else "goals"
    parts = []
    for side in ("home", "away"):
        tm = r["teams"][side]
        parts += [
            html.H4(f"{tm['team']}: {len(tm[key]['matches'])} matches used"),
            matches_table(tm[key]["matches"], market),
        ]
    return card("Matches used in this calculation", *parts)


def positions_section(r: dict, official: dict) -> html.Section:
    f = r["fixture"]
    home_id, away_id = r["teams"]["home"]["team_id"], r["teams"]["away"]["team_id"]
    if official and home_id in official and away_id in official:
        rows = [official[home_id], official[away_id]]
        updated = max(
            (x["provider_updated_at"] for x in rows if x["provider_updated_at"]), default=None
        )
        label = "Official standings from API-Football" + (
            f", updated {updated:%d %b %Y}" if updated else ""
        )
        body = [
            html.Tr(
                [
                    html.Td(name),
                    html.Td(f"{x['rank']}", className="num"),
                    html.Td(f"{x['points']} pts", className="num"),
                    html.Td(f"P{x['played']}", className="num"),
                    html.Td(f"GD {x['goal_difference']:+d}", className="num"),
                ]
            )
            for name, x in ((f["home"], rows[0]), (f["away"], rows[1]))
        ]
        kind = ""
    else:
        lp = r["league_position"]
        label = "Calculated from Diski 9's eligible results (not the official table)"
        body = [
            html.Tr(
                [
                    html.Td(name),
                    html.Td(f"{x['position']}" if x else "—", className="num"),
                    html.Td(f"{x['pts']} pts" if x else "", className="num"),
                    html.Td(f"P{x['p']}" if x else "", className="num"),
                    html.Td(f"GD {x['gf'] - x['ga']:+d}" if x else "", className="num"),
                ]
            )
            for name, x in ((f["home"], lp["home"]), (f["away"], lp["away"]))
        ]
        kind = "info"
    return card(
        "League positions",
        pill(label, kind) if kind else html.Div(label, className="muted"),
        html.Table(body, className="kv"),
        html.P("Context only: league position does not affect any indicator.", className="explain"),
    )


def h2h_section(r: dict) -> html.Section:
    h = r["head_to_head"]
    if not h:
        return card(
            "Head-to-head",
            html.Div("No previous meetings in the stored leagues.", className="muted"),
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
    return card(
        "Head-to-head: last 5 meetings",
        html.Div(html.Table(html.Tbody(rows), className="mini"), className="scroll-x"),
        html.P(
            r["head_to_head_note"] + ' "Older" means more than one season ago.', className="explain"
        ),
    )


def odds_section(ov: OddsView | None, league: str, data: ScreenerData) -> html.Section:
    if ov is None:
        return card(
            "Reference odds", html.Div("Odds information is not loaded.", className="muted")
        )
    if not ov.league_has_odds:
        return card(
            "Reference odds",
            html.Div(
                f"API-Football currently provides no bookmaker odds for the {league}. "
                "The statistics above are unaffected.",
                className="empty",
            ),
        )
    blocks = []
    for market, title in (
        (Market.MATCH_RESULT, "Match result"),
        (Market.BTTS, "Both teams to score"),
        (Market.OVER_UNDER_25, "Over/Under 2.5"),
    ):
        mc, ip = ov.markets[market], ov.implied[market]
        if not mc.displayable:
            reason = _no_odds_reason(mc)
            blocks.append(
                html.Div(
                    [html.H4(title), html.Div(reason, className="muted")], className="odds-block"
                )
            )
            continue
        head = html.Tr(
            [
                html.Th("Outcome"),
                html.Th("Consensus odds"),
                html.Th("Raw implied"),
                html.Th("Market-implied"),
            ]
        )
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
        support = (
            pill(f"{mc.sources} independent bookmakers", "ok")
            if mc.challenge_eligible
            else pill(
                f"Limited bookmaker support: {mc.sources} (3 needed for Challenge pricing)", "warn"
            )
        )
        notes = [support]
        if ip.margin_adjusted is None:
            notes.append(pill("Market-implied not shown: " + (ip.reason_unavailable or ""), "info"))
        else:
            notes.append(
                html.Span(
                    f"Combined margin removed: {ip.overround * 100:.1f}%", className="muted small"
                )
            )
        blocks.append(
            html.Div(
                [
                    html.H4(title),
                    html.Div(
                        html.Table([html.Thead(head), html.Tbody(rows)], className="mini"),
                        className="scroll-x",
                    ),
                    html.Div(notes, className="sample-line"),
                    _freshness(mc, data),
                ],
                className="odds-block",
            )
        )
    return card(
        "Reference odds and market-implied probabilities",
        html.P(
            "Consensus reference odds — not an offer from any bookmaker. "
            "Shown separately from the historical indicators; Diski 9 does not compare them "
            "or calculate betting value.",
            className="notice",
        ),
        explain("odds"),
        explain("implied"),
        *blocks,
        html.P(
            "Odds freshness rules are provisional until the odds monitoring trial completes.",
            className="muted small",
        ),
    )


def _freshness(mc, data: ScreenerData) -> html.Div:
    return html.Div(
        [
            html.Div(
                "Prices last verified by Diski 9: "
                f"{data.local(mc.latest_observation)} {data.tz_label}"
            ),
            html.Div(
                f"Provider feed update: {data.local(mc.provider_updated_at)} {data.tz_label} "
                "(feed-level timestamp shared across fixtures; not a bookmaker price-change time)"
            ),
        ],
        className="muted small freshness",
    )


def _no_odds_reason(mc) -> str:
    ex = mc.exclusions
    if not ex:
        return "No bookmaker odds have been collected for this market yet."
    if ex.get("stale_observation") or ex.get("stale_provider_update"):
        return "Bookmaker prices exist but are older than 24 hours, so no consensus is shown."
    if ex.get("fixture_started"):
        return "The match has started; pre-match prices are no longer shown."
    if ex.get("incomplete_market"):
        return "Bookmakers did not quote every outcome of this market, so no consensus is shown."
    return "No valid, eligible bookmaker prices are available, so no consensus is shown."


def _num(x: float | None) -> str:
    return "—" if x is None else f"{x:.2f}"


def render_detail(
    r: dict | None, ov: OddsView | None, official: dict, market: str, data: ScreenerData
) -> Any:
    if r is None:
        return html.Div(
            "Select a fixture in the table to see how its indicators were calculated.",
            className="empty",
        )
    league = LEAGUE_SHORT.get(r["fixture"]["competition_id"], r["fixture"]["competition"])
    primary = form_section(r) if market == "1X2" else goals_section(r, market)
    others = [
        html.Details([html.Summary(title), section], className="more")
        for m, title, section in (
            ("1X2", "Match result: Form Scores", None),
            ("BTTS", "Both teams to score", None),
            ("OU25", "Over/Under 2.5 goals", None),
        )
        if m != market
        for section in [form_section(r) if m == "1X2" else goals_section(r, m)]
    ]
    return html.Div(
        [
            header(r, data),
            primary,
            recent_matches_section(r, market),
            odds_section(ov, league, data),
            positions_section(r, official),
            h2h_section(r),
            *others,
        ],
        className="detail",
    )
