"""Plotly figures for "Your Payout Probability" (Phase 6B).

Every number comes from the production engine (``PortfolioEvaluation.distribution``
and ``at_least``); this module only turns those exact values into drawing
coordinates. No probabilities are interpolated or smoothed.

**"At least" view (survival function).** For distinct attainable payouts
v0 = 0 < v1 < ... < vn with S(v) = P(gross >= v):

* the curve is 1.0 at 0 credits (S(v0) = 1, a closed dot);
* for a threshold t in (v(i-1), v(i)] the value is S(v(i)) - the payout v(i) is
  attainable, so a threshold *equal* to it still counts it (closed dot at the
  right end of each level);
* just above v(i) the curve drops to S(v(i+1)); above the maximum it is 0.

Vertices: (0, 1) -> (0, S(v1)) -> (v1, S(v1)) -> (v1, S(v2)) -> ... -> (vn, S(vn))
-> (vn, 0) -> (x_end, 0): vertical drops sit at the attainable payouts, horizontal
levels between them.
"""

from __future__ import annotations

from decimal import Decimal

import plotly.graph_objects as go

from diski9.challenge.structured import PortfolioEvaluation

TARGET = Decimal("100.00")
BG = "#151b23"
GRID = "#2a3441"
TEXT = "#e6edf3"
MUTED = "#8b98a5"
LINE = "#2dd4bf"
MARK = "#f2b84b"


def survival_vertices(points, x_end: float) -> tuple[list[float], list[float]]:
    """Step-function vertices for the "at least" curve (see module docstring)."""
    xs, ys = [0.0], [1.0]
    for p in points[1:]:
        x = float(p.gross)
        xs += [xs[-1], x]
        ys += [p.at_least, p.at_least]
    last = xs[-1]
    xs += [last, max(x_end, last)]
    ys += [0.0, 0.0]
    return xs, ys


def focus_range(ev: PortfolioEvaluation) -> float:
    """Upper x limit that shows every payout except the all-win state (the primary
    bucket payouts), with headroom, and never hides the 100-credit marker."""
    non_all = [float(s.gross) for s in ev.states if not all(s.wins)]
    return max(max(non_all, default=0.0), float(TARGET)) * 1.12


def _layout(fig: go.Figure, title: str, x_max: float, y_title: str) -> go.Figure:
    fig.update_layout(
        title={"text": title, "font": {"size": 14, "color": TEXT}, "x": 0, "xanchor": "left"},
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font={"color": TEXT, "size": 12},
        margin={"l": 52, "r": 16, "t": 40, "b": 46},
        height=320,
        showlegend=False,
        hoverlabel={"bgcolor": "#1b232d", "bordercolor": GRID, "font": {"color": TEXT}},
    )
    fig.update_xaxes(
        title="Gross payout (virtual credits)",
        range=[0, x_max],
        gridcolor=GRID,
        zeroline=False,
        color=MUTED,
    )
    fig.update_yaxes(
        title=y_title,
        tickformat=".0%",
        gridcolor=GRID,
        zeroline=False,
        color=MUTED,
        rangemode="tozero",
    )
    return fig


def at_least_figure(ev: PortfolioEvaluation, x_max: float, threshold: float | None = None):
    points = ev.distribution()
    xs, ys = survival_vertices(points, x_max * 1.05)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            line={"color": LINE, "width": 2.5, "shape": "linear"},
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[float(p.gross) for p in points],
            y=[p.at_least for p in points],
            mode="markers",
            marker={"color": LINE, "size": 8, "line": {"color": BG, "width": 1}},
            customdata=[[f"{p.gross:,.2f}", f"{p.at_least:.2%}"] for p in points],
            hovertemplate="At least %{customdata[0]} credits: %{customdata[1]}<extra></extra>",
        )
    )
    rec = ev.at_least(TARGET)
    fig.add_vline(x=100, line={"color": MARK, "width": 1.5, "dash": "dash"})
    fig.add_trace(
        go.Scatter(
            x=[100],
            y=[rec],
            mode="markers",
            marker={"color": MARK, "size": 10, "symbol": "diamond"},
            hovertemplate=f"Recover 100 credits: {rec:.2%}<extra></extra>",
        )
    )
    fig.add_annotation(
        x=100,
        y=rec,
        text=f"Recover 100: {rec:.1%}",
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        xshift=8,
        font={"color": MARK},
    )
    if threshold is not None and threshold > 0:
        p = ev.at_least(Decimal(str(round(threshold, 2))))
        fig.add_vline(x=threshold, line={"color": MUTED, "width": 1, "dash": "dot"})
        fig.add_trace(
            go.Scatter(
                x=[threshold],
                y=[p],
                mode="markers",
                marker={"color": TEXT, "size": 8},
                hovertemplate=f"At least {threshold:,.0f} credits: {p:.2%}<extra></extra>",
            )
        )
    return _layout(fig, "Chance of getting at least this payout", x_max, "Probability")


def exact_figure(ev: PortfolioEvaluation, x_max: float):
    points = ev.distribution()
    width = max(x_max / 90, 1.0)
    fig = go.Figure(
        go.Bar(
            x=[float(p.gross) for p in points],
            y=[p.probability for p in points],
            width=width,
            marker={"color": [MARK if p.gross >= TARGET else LINE for p in points]},
            customdata=[[f"{p.gross:,.2f}", f"{p.probability:.2%}", len(p.states)] for p in points],
            hovertemplate="Exactly %{customdata[0]} credits: %{customdata[1]}"
            "<br>Outcome combinations: %{customdata[2]}<extra></extra>",
        )
    )
    fig.add_vline(x=100, line={"color": MARK, "width": 1.5, "dash": "dash"})
    return _layout(fig, "Chance of each exact payout", x_max, "Probability")
