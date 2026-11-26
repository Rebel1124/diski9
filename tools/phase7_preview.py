"""Phase 7 CP3 visual preview (development only; synthetic data, no database).

Renders the real My Challenge > Achievements components and the History-detail badge
chips with the application's own stylesheets, for the owner's visual review. Every
page carries a "Synthetic preview data" banner. The achievement values are built
with the accepted backend functions (``level_for`` and ``progress_for``), so the level
and progress shown are exactly what the service would derive from those counts.

    uv run python tools/phase7_preview.py            # http://127.0.0.1:8077/?state=pro

States: beginner-empty, beginner-progress, semi-pro, pro, history, unavailable.
Real-data screenshots come from the end-to-end run after visual approval.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

from dash import Dash, Input, Output, dcc, html

from diski9.app.challenge import achievements_ui as aui
from diski9.app.challenge import components as c
from diski9.app.challenge import history_ui
from diski9.app.challenge import leaderboards_ui as lbu
from diski9.app.challenge.callbacks import nav_links
from diski9.backend.services import achievements as ac

ASSETS = Path(__file__).resolve().parents[1] / "src" / "diski9" / "app" / "assets"
F, B, C = ac.Badge.FOUNDATION_FUNDI, ac.Badge.BALANCED_BRAWLER, ac.Badge.CHALLENGER_CHAMP
GG, BT, DD = ac.Badge.GOALS_GURU, ac.Badge.BTTS_BONANZA, ac.Badge.DRAW_DYNAMO

#: synthetic counts per state, in display order (F, B, C, GG, BT, DD), and eligible rounds
STATES = {
    "beginner-empty": ((0, 0, 0, 0, 0, 0), 0),
    "beginner-progress": ((3, 1, 0, 2, 0, 1), 6),
    "semi-pro": ((5, 3, 1, 4, 2, 1), 14),
    "pro": ((9, 6, 3, 5, 4, 3), 31),
}


def synthetic(counts, rounds) -> ac.Achievements:
    by = dict(zip(ac.BADGES, counts, strict=True))
    return ac.Achievements(
        stream="beta", counts=by, total=sum(counts), level=ac.level_for(by),
        progress=ac.progress_for(by), eligible_rounds=rounds, rounds=(),
    )  # fmt: skip


def banner() -> html.Div:
    return html.Div("Synthetic preview data for the visual review: not real results.",
                    className="banner warn")  # fmt: skip


def page(state: str):
    if state == "unavailable":
        content = aui.unavailable_view()
    elif state == "history":
        content = [
            html.Div(
                [
                    html.H2(lbu.round_title("Sat 21 Nov – Mon 23 Nov", "preview"),
                            className="ch-h2"),
                    html.Div([html.Strong("Official result: "),
                              "rank #4 · returned 162.40 · 125 pts"],
                             className="ch-ribbon ok"),
                    aui.chips((F, C, GG, DD)),
                    html.P("(The round's prediction-by-prediction panel follows here, "
                           "unchanged.)", className="muted small"),
                ],
                className="me-hist-detail ch-card",
            )
        ]  # fmt: skip
    else:
        counts, rounds = STATES[state]
        content = aui.view(synthetic(counts, rounds))
    tab = "history" if state == "history" else "achievements"
    return html.Div(
        [
            c.page_header("My Challenge"),
            banner(),
            html.Div(history_ui.tabs(tab), className="ch-row-between me-tabs"),
            html.Div(content),
        ],
        className="ch-page",
    )


def make_app() -> Dash:
    app = Dash(__name__, assets_folder=str(ASSETS), suppress_callback_exceptions=True)
    app.layout = html.Div(
        [
            dcc.Location(id="url", refresh=False),
            html.Nav(
                html.Div(
                    [
                        html.Span("Diski 9", className="nav-brand"),
                        html.Div(nav_links("/challenge/me"), className="nav-links"),
                    ],
                    className="nav-inner",
                ),
                className="site-nav",
            ),  # fmt: skip
            html.Div(id="ch-root"),
        ]
    )

    @app.callback(Output("ch-root", "children"), Input("url", "search"))
    def render(search):
        state = (parse_qs((search or "").lstrip("?")).get("state") or ["pro"])[0]
        return page(state if state in (*STATES, "history", "unavailable") else "pro")

    return app


if __name__ == "__main__":
    make_app().run(host="127.0.0.1", port=8077, debug=False)
