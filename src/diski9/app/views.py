"""Rendering building blocks for the match panel (pure functions, no callbacks).

Engine 3.0: the panel itself is assembled in ``lab.py`` (The Match Lab); the
historical context pieces below (Form Score, records, head-to-head, positions)
and the bookmaker card are reused there.

Legacy layout notes (Engine 2.x):

Layout (final UI refinement, after Milestone 5.3):
  Heading  fixture, competition, kickoff, market, form basis
  Card 1   Diski 9 Match Analysis - historical statistics only (team figures, league
           baseline for goals markets, sample warnings), with collapsed
           "How it's calculated" and "Matches used" rows
  Card 2   Bookmaker Market Reference - the selected market only: status,
           timestamps, market-implied probabilities, consensus odds (raw implied),
           bookmaker groups, margin removed and a short margin note
           At its foot, under "Match context" (historical, not bookmaker data):
           collapsed League positions and Head-to-head rows
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from dash import html

from diski9.api_football.markets import Market

from .data import (
    MARKET_OUTCOME_ORDER,
    OUTCOME_LABEL,
    OddsView,
    ScreenerData,
)

FORM_TOOLTIP = (
    "Diski Form Score (0–5) measures recent performance using points earned and goal "
    "difference in each team's last eight league matches of the current season (fewer early "
    "in the season, scored on the matches actually played). Earlier seasons and other "
    "divisions are never used. The league comparison shows whether a team's score is above "
    "or below the current-season average of the league's teams. It describes historical "
    "performance, not the probability of winning."
)
LIMITED_GOALS = (
    "Fewer than six current-season matches for at least one team: the records are a small sample."
)
RECORD_WORD = {"BTTS": "BTTS", "OU25": "Over 2.5"}
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


# ------------------------------------------------------------- card helpers
def card_head(title: str, subtitle: str) -> html.Div:
    return html.Div(
        [html.H3(title), html.Div(subtitle, className="card-sub muted small")],
        className="card-head",
    )


def accordion(title: str, *children: Any) -> html.Details:
    """Compact, collapsed-by-default row inside a card (divider style, not a nested card)."""
    return html.Details(
        [html.Summary(title), html.Div(children, className="acc-body")],
        className="acc",
        open=False,
    )


# ------------------------------------------------- card 1: Diski 9 Match Analysis
def analysis_card(r: dict, market: str) -> html.Section:
    """Historical statistics only: team figures, league baseline (goals markets),
    sample warnings, then collapsible calculation and matches."""
    t = r["teams"]
    if market == "1X2":
        label_row = html.Div(
            [
                html.Span("Diski Form Score", className="label"),
                info(FORM_TOOLTIP, "About Diski Form Score"),
            ],
            className="label-row",
        )
        bench = r["match_result"].get("league_benchmark")
        tiles = [form_tile(t[s], bench) for s in ("home", "away")]
        warning = []
        baseline = html.Div([form_benchmark_block(bench), venue_context_block(r)])
    else:
        key = "btts" if market == "BTTS" else "over_2_5"
        label_row = html.Div(
            [
                html.Span("Historical records", className="label"),
                info(
                    "What actually happened in each team's recent current-season matches "
                    "(up to ten, this competition only). A record describes the past; it is "
                    "not a prediction for this fixture.",
                    "About historical records",
                ),
            ],
            className="label-row",
        )
        lb = r.get("league_baseline")
        tiles = [record_tile(t[s], key, market, lb) for s in ("home", "away")]
        limited = r["limited_data"]["goals"]
        warning = [html.P(LIMITED_GOALS, className="muted small limited-note") if limited else None]
        baseline = league_baseline_block(r, market)
    return html.Section(
        [
            card_head("Diski 9 Match Analysis", "Historical statistics"),
            label_row,
            html.Div(tiles, className="tiles"),
            *warning,
            baseline,
            html.Div(
                [calculation_section(r, market), matches_section(r, market)],
                className="acc-group",
            ),
        ],
        className="card summary analysis" + (" goals-summary" if market != "1X2" else ""),
    )


def paired_outcomes(yes_lbl: str, yes: str | None, no_lbl: str, no: str | None) -> html.Div:
    """Both outcomes with identical typography: neither is visually favoured."""
    return html.Div(
        [
            html.Div(
                [
                    html.Span(yes_lbl, className="pair-label"),
                    html.Span(yes or "—", className="pair-value"),
                ],
                className="pair",
            ),
            html.Span("|", className="pair-sep", **{"aria-hidden": "true"}),
            html.Div(
                [
                    html.Span(no_lbl, className="pair-label"),
                    html.Span(no or "—", className="pair-value"),
                ],
                className="pair",
            ),
        ],
        className="pair-row",
    )


def record_text(rate: dict | None, market: str) -> tuple[str, str | None]:
    """'BTTS in 7 of 10' and its complement ('No BTTS in 3 of 10'); never a 0% for no data."""
    if not rate or not rate["matches"]:
        return "No current-season history", None
    k, n = rate["hits"], rate["matches"]
    if market == "BTTS":
        return f"BTTS in {k} of {n}", f"No BTTS in {n - k} of {n}"
    return f"Over 2.5 in {k} of {n}", f"Under 2.5 in {n - k} of {n}"


FORM_TOLERANCE = 1e-9  # floating-point only: scores are exact fractions before caching


def form_comparison(score: float | None, bench: dict | None) -> str | None:
    """'above' / 'below' / 'equal' versus the current-season league Form Score average
    (unrounded values), or None when the score or the average is unavailable."""
    if score is None or not bench or not bench.get("available"):
        return None
    avg = bench.get("average")
    if avg is None:
        return None
    if abs(score - avg) <= FORM_TOLERANCE:
        return "equal"
    return "above" if score > avg else "below"


def form_tile(team: dict, bench: dict | None) -> html.Div:
    form = team["form"]
    n = form["sample"]["matches"]
    window = (form.get("breakdown") or {}).get("window", 8)
    early = 0 < n < window
    return html.Div(
        [
            html.Div(team["team"], className="tile-team"),
            html.Div(
                [
                    html.Span(form["display"], className="tile-value"),
                    html.Span(" out of 5", className="muted"),
                    " ",
                    pill("Early season", "warn subtle") if early else None,
                ]
                if form["display"]
                else html.Span("Unavailable", className="tile-value muted"),
                className="record-row",
            ),
            html.Div(
                f"Based on {n} of {window} matches — early-season results may be volatile.",
                className="muted small early-note",
            )
            if early
            else None,
            html.Div("No current-season matches yet.", className="muted small") if n == 0 else None,
            comparison_indicator(form_comparison(form["score"], bench)),
        ],
        className="tile",
    )


FORM_BENCH_HELP = (
    "The average Diski Form Score of the league's teams this season, before this fixture: "
    "every team that has played at least one league match contributes one score, from its "
    "last (up to) eight current-season matches. Shown once enough of the league has played "
    "a few matches."
)


def form_benchmark_block(bench: dict | None) -> html.Div:
    head = html.Div(
        [
            html.Span("League Form Score average", className="label"),
            info(FORM_BENCH_HELP, "About the league Form Score average"),
        ],
        className="label-row",
    )
    if not bench or not bench.get("available"):
        if bench and bench.get("teams"):
            detail = (
                f"{bench['qualified_teams']} of {bench['league_teams']} teams have played at "
                f"least {bench['min_matches']} league matches this season (at least "
                f"{bench['min_teams']} teams and {bench['min_share']:.0%} of the league needed)."
            )
        else:
            detail = "No league matches have been played this season yet."
        return html.Div(
            [
                head,
                html.Div("Not enough current-season data yet", className="baseline-value muted"),
                html.Div(detail, className="muted small"),
            ],
            className="baseline",
        )
    return html.Div(
        [
            head,
            html.Div(
                html.Span(f"{bench['display']} out of 5", className="bench-value"),
                className="bench-values",
            ),
            html.Div(
                f"{bench['competition']} {bench['season_label']} — {bench['teams']} teams evaluated",
                className="muted small bench-source",
            ),
        ],
        className="baseline form-benchmark",
    )


VENUE_HELP = (
    "Display only. The home team's Form Score from up to its last five home league matches "
    "this season, and the away team's from up to its last five away matches, each compared "
    "with that team's overall Form Score. It does not change the headline score, the league "
    "comparison or any ranking, and it does not predict how the team will play."
)


def venue_line(team: dict) -> html.Div:
    vc = team["form"].get("venue_context") or {}
    where = "home" if vc.get("side") == "home" else "away"
    n = vc.get("matches", 0)
    count = f"{n} {where} match{'es' if n != 1 else ''}"
    if not vc.get("available"):
        text = f"Not enough venue history ({count} this season)."
        return html.Div(
            [html.Span(team["team"], className="venue-team"), html.Span(text, className="muted")],
            className="venue-line",
        )
    diff = vc["difference"]
    if abs(diff) <= FORM_TOLERANCE:
        phrase = f"{where.capitalize()} form the same as overall"
    else:
        phrase = (
            f"{where.capitalize()} form {vc['difference_display']} points "
            f"{'higher' if diff > 0 else 'lower'} than overall"
        )
    return html.Div(
        [
            html.Span(team["team"], className="venue-team"),
            html.Span(f"{phrase} ({count}).", className="muted"),
            " ",
            pill("Limited history", "warn subtle") if vc.get("limited") else None,
        ],
        className="venue-line",
    )


def venue_context_block(r: dict) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Span("Venue context", className="label"),
                    info(VENUE_HELP, "About venue context"),
                ],
                className="label-row",
            ),
            venue_line(r["teams"]["home"]),
            venue_line(r["teams"]["away"]),
        ],
        className="baseline venue-context",
    )


def league_comparison(rate: dict | None, lb: dict | None, key: str) -> str | None:
    """'above' / 'below' / 'equal' versus the league baseline, or None when either side
    is unavailable (no team match, or baseline below its minimum sample).

    The team rate is the exact fraction hits / matches; the baseline is the cached
    float of an exact fraction. Two different fractions with denominators this small
    differ by far more than float precision, so the comparison is exact: no rounding
    and no tolerance or minimum difference."""
    if not rate or not rate.get("matches") or not lb or not lb.get("available"):
        return None
    baseline = lb.get(key)
    if baseline is None:
        return None
    team = float(Fraction(rate["hits"], rate["matches"]))
    if team > baseline:
        return "above"
    if team < baseline:
        return "below"
    return "equal"


COMPARISON_TEXT = {
    "above": ("✓", "Above league average"),
    "below": ("↓", "Below league average"),
    "equal": ("=", "Equal to league average"),
}


def comparison_indicator(state: str | None) -> html.Div | None:
    if state is None:
        return None
    icon, text = COMPARISON_TEXT[state]
    return html.Div(
        [html.Span(icon, className="cmp-icon", **{"aria-hidden": "true"}), html.Span(text)],
        className=f"league-cmp {state} small",
    )


def record_tile(team: dict, key: str, market: str, lb: dict | None = None) -> html.Div:
    rate = team["goals"][key]
    main, _ = record_text(rate, market)  # the complement stays in "Matches used"
    limited = team["goals"]["sample"]["limited_data"]
    return html.Div(
        [
            html.Div(team["team"], className="tile-team"),
            html.Div(
                [
                    html.Span(main, className="record-value"),
                    " ",
                    pill("Limited", "warn subtle") if limited else None,
                ],
                className="record-row",
            ),
            comparison_indicator(league_comparison(rate, lb, key)),
        ],
        className="tile record",
    )


BASELINE_HELP = (
    "This is the percentage of completed matches in the current league season where the "
    "outcome occurred. Only matches played before this fixture are included. A baseline is "
    "shown once at least 30 eligible matches are available. League context, not a "
    "prediction for this fixture."
)


def baseline_available(lb: dict | None) -> bool:
    return bool(lb and lb.get("available"))


def baseline_source(lb: dict) -> str:
    n = lb["matches"]
    return f"{lb['competition']} {lb['season_label']} — {n} completed match{'es' if n != 1 else ''} before kickoff"


def league_baseline_block(r: dict, market: str) -> html.Div:
    lb = r.get("league_baseline")
    key = "btts" if market == "BTTS" else "over_2_5"
    title = "League BTTS baseline" if market == "BTTS" else "League Over 2.5 baseline"
    head = html.Div(
        [html.Span(title, className="label"), info(BASELINE_HELP, "About the league baseline")],
        className="label-row",
    )
    if not baseline_available(lb):
        n = lb["matches"] if lb else 0
        need = lb["min_matches"] if lb else 30
        return html.Div(
            [
                head,
                html.Div("Not enough current-season data yet", className="baseline-value muted"),
                html.Div(
                    f"{n} of {need} eligible completed league matches before kickoff.",
                    className="muted small",
                ),
            ],
            className="baseline",
        )
    return html.Div(
        [
            head,
            html.Div(
                [
                    html.Span(lb[f"{key}_display"], className="baseline-value"),
                    html.Span(baseline_source(lb), className="muted small"),
                ],
                className="baseline-row",
            ),
        ],
        className="baseline",
    )


def status_badge(status: str) -> html.Span:
    return pill(
        {"fresh": "Fresh", "stale": "Stale", "unavailable": "Unavailable"}[status],
        {"fresh": "ok", "stale": "warn", "unavailable": ""}[status],
    )


# --------------------------------------------- card 2: Bookmaker Market Reference
MARKET_NOTE = (
    "Market-implied probabilities are derived from bookmaker prices, not Diski 9 predictions."
)


MARGIN_NOTE = (
    "Bookmaker odds include a margin, so their implied probabilities add up to more than "
    "100%. We remove this margin by proportionally adjusting the probabilities to total 100%, "
    "making the market's expectations easier to compare."
)


RAW_NOTE = (
    "Each card shows the consensus price and its raw implied probability (1 ÷ odds). The "
    "market-implied probabilities on the left remove the bookmaker margin, so each market adds "
    "up to 100%."
)
STALE_NOTE = (
    "These prices are the last valid consensus and are no longer current: they may have "
    "changed and are shown for reference only."
)


def context_group(*sections: Any) -> html.Div:
    """League positions and head-to-head: historical context shown at the foot of the
    bookmaker card for a compact layout, labelled so it is never read as market data."""
    return html.Div(
        [
            html.Div(
                [
                    html.Span("Match context", className="label"),
                    html.Span("Historical results, not bookmaker data", className="muted small"),
                ],
                className="label-row context-head",
            ),
            *sections,
        ],
        className="acc-group context-group",
    )


def market_card(
    ov: OddsView | None,
    market: Market,
    data: ScreenerData,
    league: str,
    context: list | None = None,
) -> html.Section:
    """Bookmaker card with the historical context rows appended at the bottom (always,
    whatever the odds status)."""
    card = _market_card(ov, market, data, league)
    if context:
        card.children.append(context_group(*context))
    return card


def _market_card(
    ov: OddsView | None, market: Market, data: ScreenerData, league: str
) -> html.Section:
    """The selected market only: status, times, market-implied probabilities, consensus
    odds with their raw implied probabilities, sources and the margin removed."""
    head = card_head("Bookmaker Market Reference", MARKET_NOTE)
    if ov is None or not ov.league_has_odds:
        return html.Section(
            [
                head,
                html.Div(
                    f"No bookmaker odds are available for the {league} from API-Football, so "
                    "market-implied probabilities are unavailable. The Diski 9 model "
                    "probabilities are unaffected.",
                    className="muted small",
                ),
            ],
            className="card market compact",
        )
    dm = ov.markets[market]
    if dm.status == "unavailable":
        return html.Section(
            [
                head,
                html.Div(
                    [html.Span("Reference odds", className="label"), status_badge("unavailable")],
                    className="label-row",
                ),
                html.Div(
                    "Market-implied probabilities unavailable. " + dm.reason,
                    className="muted small",
                ),
            ],
            className="card market compact",
        )
    mc, ip = dm.consensus, dm.implied
    cells = []
    for o in MARKET_OUTCOME_ORDER[market]:
        price = mc.outcomes[o].consensus_odds
        raw = ip.raw.get(o) if ip else None
        cells.append(
            html.Div(
                [
                    html.Div(OUTCOME_LABEL[o], className="muted small"),
                    html.Div(str(price) if price else "—", className="price"),
                    html.Div(
                        f"raw {float(raw) * 100:.1f}%" if raw else "", className="muted small raw"
                    ),
                ],
                className="price-cell",
            )
        )
    probs = (
        market_probabilities(ip)
        if market is Market.MATCH_RESULT
        else goals_market_probabilities(ip, market)
    )
    facts = [f"{mc.sources} independent bookmaker group{'s' if mc.sources != 1 else ''}"]
    if ip is not None and ip.overround is not None:
        facts.append(f"combined margin removed {float(ip.overround) * 100:.1f}%")
    return html.Section(
        [
            head,
            html.Div(
                [
                    status_badge(dm.status),
                    html.Span(freshness_text(dm, data), className="muted small"),
                ],
                className="label-row status-row",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            probs,
                            html.Div(
                                [
                                    html.Span("Consensus reference odds", className="label"),
                                    info(
                                        "The median price across independent bookmakers "
                                        "(brands under common ownership count once). Raw "
                                        "implied probability = 1 ÷ odds, before the margin is "
                                        "removed. Not an offer from any bookmaker.",
                                        "About reference odds",
                                    ),
                                ],
                                className="label-row",
                            ),
                            html.Div(cells, className=f"prices cols-{len(cells)}"),
                            html.P(" · ".join(facts), className="muted small market-facts"),
                        ],
                        className="market-main",
                    ),
                    html.Div(
                        [
                            html.Div("Reading these numbers", className="label"),
                            html.P(RAW_NOTE, className="muted small"),
                            html.P(MARGIN_NOTE, className="muted small margin-note")
                            if ip is not None and ip.overround is not None
                            else None,
                            html.P(STALE_NOTE, className="small stale-note")
                            if dm.status == "stale"
                            else None,
                        ],
                        className="market-side",
                    ),
                ],
                className="market-grid",
            ),
        ],
        className=f"card market {dm.status}",
    )


def market_probabilities(ip) -> html.Div | None:
    """Home/Draw/Away margin-adjusted probabilities from the consensus odds.

    Market information (bookmaker-implied), not a Diski 9 prediction. Uses the same
    values as the expanded reference-odds table. Shown only for a complete 1X2 set.
    """
    if ip is None or ip.margin_adjusted is None:
        return html.Div(
            "Market-implied probabilities need prices for home, draw and away.",
            className="muted small",
        )
    order = MARKET_OUTCOME_ORDER[Market.MATCH_RESULT]
    pct = {o: float(ip.margin_adjusted[o]) * 100 for o in order}
    segments = [
        html.Div(
            className=f"seg seg-{o.value.lower()}",
            style={"width": f"{pct[o]:.1f}%"},
            title=f"{OUTCOME_LABEL[o]} {pct[o]:.1f}%",
        )
        for o in order
    ]
    values = []
    for i, o in enumerate(order):
        if i:
            values.append(html.Span("|", className="sep"))
        values.append(
            html.Span(
                [html.Span(OUTCOME_LABEL[o], className="muted"), f" {pct[o]:.1f}%"],
                className="prob",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Span("Market-implied probabilities", className="label"),
                    info(
                        "Derived from the consensus bookmaker odds after removing the combined "
                        "bookmaker margin. They describe the betting market, not a Diski 9 "
                        "prediction.",
                        "About market-implied probabilities",
                    ),
                ],
                className="label-row",
            ),
            html.Div(
                segments,
                className="prob-bar",
                role="img",
                **{"aria-label": ", ".join(f"{OUTCOME_LABEL[o]} {pct[o]:.1f}%" for o in order)},
            ),
            html.Div(values, className="prob-values"),
        ],
        className="market-probs",
    )


def goals_market_probabilities(ip, market: Market) -> html.Div:
    """BTTS Yes/No or Over/Under 2.5 margin-adjusted probabilities, equal typography.
    The same values as the expanded reference-odds table; never a baseline or history."""
    yes_o, no_o = MARKET_OUTCOME_ORDER[market]
    labels = ("BTTS Yes", "BTTS No") if market is Market.BTTS else ("Over 2.5", "Under 2.5")
    head = html.Div(
        [
            html.Span("Market-implied probabilities", className="label"),
            info(
                "Derived from the consensus bookmaker odds after removing the combined "
                "bookmaker margin, so the two outcomes add up to 100%. They describe the "
                "betting market, not a Diski 9 prediction.",
                "About market-implied probabilities",
            ),
        ],
        className="label-row",
    )
    if ip is None or ip.margin_adjusted is None:
        need = "yes and no" if market is Market.BTTS else "over and under"
        return html.Div(
            [head, html.Div(f"Needs prices for both {need}.", className="muted small")],
            className="market-probs",
        )
    yes = f"{float(ip.margin_adjusted[yes_o]) * 100:.1f}%"
    no = f"{float(ip.margin_adjusted[no_o]) * 100:.1f}%"
    pair = paired_outcomes(labels[0], yes, labels[1], no)
    pair.className = "pair-row compact"
    return html.Div([head, pair], className="market-probs")


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


# ----------------------------------------------------- collapsible explanations
def benchmark_explanation(r: dict) -> html.Div:
    bench = r["match_result"].get("league_benchmark") or {}
    if bench.get("available"):
        now = f"This fixture: league average {bench['display']} out of 5 ({bench['teams']} teams)."
    else:
        now = (
            "This fixture: not enough current-season data yet, so no comparison is shown "
            "(no 2.5 or zero is substituted)."
        )
    return html.Div(
        [
            html.H4("League comparison"),
            html.P(
                "The league Form Score average uses current-season results only: every team "
                "that has played at least one league match in this competition this season "
                "before kickoff contributes one score, from its last (up to) eight matches, "
                "normalised by the matches it has played. Teams with no match are left out. "
                f"The average is shown once at least {bench.get('min_teams', 12)} teams and "
                f"{bench.get('min_share', 0.8):.0%} of the league's teams have played at least "
                f"{bench.get('min_matches', 3)} matches. Comparisons use unrounded scores. They "
                "describe historical performance, not the probability of winning.",
                className="muted small",
            ),
            html.P(now, className="muted small"),
            html.H4("Venue context"),
            html.P(
                "Display only: each team's Form Score from up to its last five home (home team) "
                "or away (away team) league matches this season, compared with its overall "
                "Form Score. With fewer than two such matches no difference is shown; with two "
                "to four it is marked as limited history. It does not change the headline "
                "score, the league comparison or the rankings.",
                className="muted small",
            ),
        ]
    )


def calculation_section(r: dict, market: str) -> html.Details:
    if market == "1X2":
        text = (
            "Each team gets a Diski Form Score (0–5) from its last eight league matches of the "
            "current season, home or away; earlier seasons and other divisions are never used. "
            "Early in the season it uses the matches played so far and is scored on that "
            "number, so a team is not penalised for having played fewer. Half the score comes "
            "from points earned and half from goal difference. The screener's Form Difference "
            "is home score minus away score."
        )
        body = html.Div([form_breakdown_table(r), benchmark_explanation(r)])
    else:
        what = "both teams scored" if market == "BTTS" else "there were three or more goals"
        basis = (
            "home matches (home team) or away matches (away team)"
            if r["basis"] == "venue"
            else "matches"
        )
        text = (
            f"Historical records count, among each team's last (up to ten) current-season {basis} "
            f"in this competition, those in which {what}. The league baseline is the "
            "competition's rate before this fixture. Neither is a Diski 9 prediction."
        )
        body = goals_breakdown_table(r, market)
    return accordion("How it's calculated", html.P(text, className="explain"), body)


def form_breakdown_table(r: dict) -> html.Div:
    """Model D, with the actual arithmetic for each team."""
    t = r["teams"]
    b = {s: t[s]["form"]["breakdown"] for s in ("home", "away")}

    def cell(side: str, fn) -> html.Td:
        return html.Td(fn(b[side]) if b[side] else "—", className="num")

    def gd_capped(x: dict) -> str:
        capped = x["goal_difference_capped"]
        return f"{x['goal_difference']:+d}" + (
            f" (capped at {capped:+g})" if capped != x["goal_difference"] else ""
        )

    def gd_part(x: dict) -> str:
        c = x["gd_cap_display"]
        return (
            f"2.5 × ({x['goal_difference_capped']:+g} + {c})/(2 × {c}) = "
            f"{x['goal_difference_component_display']}"
        )

    rows = [
        ("Matches used (N, of 8)", lambda x: str(x["matches"])),
        ("Won · drawn · lost", lambda x: f"{x['wins']} · {x['draws']} · {x['losses']}"),
        ("Points earned (of 3N)", lambda x: f"{x['points']} of {x['max_points']}"),
        (
            "Points part = 2.5 × points ÷ 3N",
            lambda x: f"2.5 × {x['points']}/{x['max_points']} = {x['points_component_display']}",
        ),
        ("Goal difference (cap ±1.8N)", gd_capped),
        ("Goal-difference part = 2.5 × (GD + 1.8N) ÷ 3.6N", gd_part),
        ("Diski Form Score (0–5)", lambda x: x["form_score_display"]),
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
                    className="grid compact form-calc",
                ),
                className="scroll-x",
            ),
            html.P(
                "N is the number of current-season matches used (at most 8). Each part is worth "
                "up to 2.5. Goal difference is capped at 1.8 goals per match (±14.4 over eight "
                "matches): −1.8N scores 0, level scores 1.25 and +1.8N or better scores 2.5. "
                "No bonuses are added.",
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
        n = rate["matches"] if rate else 0
        rows.append(
            html.Tr(
                [
                    html.Td(t[s]["team"]),
                    html.Td(str(rate["hits"]) if rate else "—", className="num"),
                    html.Td(str(n), className="num"),
                    html.Td(
                        rate["display"].split(" ")[-1].strip("()") if rate else "No history",
                        className="num",
                    ),
                ]
            )
        )
    block = r["btts"] if market == "BTTS" else r["over_under_2_5"]
    combined = block["yes_display"] if market == "BTTS" else block["over_display"]
    lbl = "BTTS matches" if market == "BTTS" else "3+ goal matches"
    word = RECORD_WORD[market]
    lb = r.get("league_baseline")
    if not baseline_available(lb):
        n = lb["matches"] if lb else 0
        need = lb["min_matches"] if lb else 30
        baseline = (
            f"League baseline: not shown yet — {n} of {need} eligible completed current-season "
            "league matches before kickoff. Earlier seasons are never used."
        )
    else:
        value = lb["btts_display" if market == "BTTS" else "over_2_5_display"]
        baseline = (
            f"League baseline {value}: {lb['matches']} completed {lb['competition']} "
            f"{lb['season_label']} matches before kickoff (current season only)."
        )
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
                                    html.Th("Share", className="num"),
                                ]
                            )
                        ),
                        html.Tbody(rows),
                    ],
                    className="grid compact",
                ),
                className="scroll-x",
            ),
            html.P(baseline, className="muted small"),
            html.P(
                "The league comparison shows whether each team's recent historical rate is "
                "above or below the current-season league average. It describes past results "
                "and is not a prediction of the upcoming match.",
                className="muted small",
            ),
            html.P(
                f"Recent {word} occurrence (average of the two shares): {combined or '—'}. Used "
                "only to order fixtures in the 'recent occurrence' rankings. It describes past "
                "matches and is not a probability for this fixture.",
                className="muted small",
            ),
        ]
    )


# ------------------------------------------------------------------- level 3
def matches_section(r: dict, market: str) -> html.Details:
    key = "form" if market == "1X2" else "goals"
    venue = r["basis"] == "venue"
    if market == "1X2":
        scope = (
            "Each team's last eight league matches of the current season, home or away "
            "(fewer early in the season); earlier seasons and other divisions are never used."
        )
    else:
        scope = (
            "Up to ten current-season matches in this competition: home team at home, "
            "away team away"
            if venue
            else "Up to ten current-season matches in this competition, home or away"
        ) + "."
    parts = [html.P(f"{scope} Only matches played before kickoff.", className="muted small")]
    for s in ("home", "away"):
        tm = r["teams"][s]
        n = len(tm[key]["matches"])
        limited = tm[key]["sample"]["limited_data"]
        tag = "Early season" if market == "1X2" else "Limited"
        parts.append(
            html.H4(
                [f"{tm['team']} ({n} match{'es' if n != 1 else ''})"]
                + ([" ", pill(tag, "warn subtle")] if limited and n else [])
            )
        )
        parts.append(matches_table(tm[key]["matches"], market))
    return accordion("Matches used", *parts)


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
    return accordion(
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
        return accordion(
            "Head-to-head",
            html.P("No previous meetings in the stored leagues.", className="muted small"),
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
    return accordion(
        "Head-to-head (last 5 meetings)",
        html.Div(html.Table(html.Tbody(rows), className="grid compact"), className="scroll-x"),
        html.P(
            "Context only; head-to-head does not affect any indicator. "
            "'Older' means more than one season ago.",
            className="muted small",
        ),
    )


def render_detail(
    r: dict | None,
    ov: OddsView | None,
    official: dict,
    market: str,
    data: ScreenerData,
    adj: dict | None = None,
) -> Any:
    """Engine 3.0 detail panel: The Match Lab and the bookmaker card (``lab.py``)."""
    from .lab import render_detail as lab_render

    return lab_render(r, ov, official, market, data, adj)
