"""Plotly figures for the portfolio analysis (Phase 6B.1).

Every number comes from the engines (``GroupEvaluation`` and
``CorrectCountAnalysis``); this module only draws them. The Phase 6B survival and
exact-payout charts were removed from the participant interface; the underlying
engine calculations (``payout_distribution``, ``probability_at_least``) remain.
"""

from __future__ import annotations

import math

import plotly.graph_objects as go

from diski9.challenge.analysis import CorrectCountAnalysis, state_label
from diski9.challenge.structured import GroupEvaluation

BG = "#151b23"
GRID = "#2a3441"
TEXT = "#e6edf3"
MUTED = "#8b98a5"
TEAL = "#2dd4bf"
AMBER = "#f2b84b"
GREY = "#3a4656"
BUCKET = {"A": "#34d399", "B": "#60a5fa", "C": "#f2b84b", "NINE": "#b392f0"}


def _base(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font={"color": TEXT, "size": 12},
        height=height,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        showlegend=False,
        hoverlabel={"bgcolor": "#1b232d", "bordercolor": GRID, "font": {"color": TEXT}},
    )
    return fig


def recovery_donut(ev: GroupEvaluation) -> go.Figure:
    """Recover 100+ / something but under 100 / nothing (they sum to 100%)."""
    labels = ["100+ back", "Under 100 back", "Nothing back"]
    values = [ev.p_recover, ev.p_partial, ev.p_zero]
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.68,
            sort=False,
            direction="clockwise",
            marker={"colors": [TEAL, AMBER, GREY], "line": {"color": BG, "width": 2}},
            textinfo="none",
            hovertemplate="%{label}: %{percent:.1%}<extra></extra>",
        )
    )
    fig.add_annotation(
        text=f"<b>{ev.p_recover:.1%}</b><br><span style='font-size:11px'>get 100+ back</span>",
        showarrow=False,
        font={"size": 20, "color": TEAL},
    )
    return _base(fig, 210)


def state_rows(ev: GroupEvaluation) -> list:
    """The eight bucket-success states sorted by gross payout (stable on state order)."""
    return sorted(ev.states, key=lambda s: s.gross)


def states_figure(ev: GroupEvaluation) -> go.Figure:
    rows = state_rows(ev)
    labels = [f"{state_label(s.wins)}  ·  {s.gross:,.2f}" for s in rows]
    colours = [TEAL if s.gross >= ev.target else (AMBER if s.gross > 0 else GREY) for s in rows]
    fig = go.Figure(
        go.Bar(
            y=list(range(len(rows))),
            x=[s.probability for s in rows],
            orientation="h",
            marker={"color": colours},
            text=[f"{s.probability:.1%}" for s in rows],
            textposition="outside",
            cliponaxis=False,
            customdata=[
                [state_label(s.wins), f"{s.gross:,.2f}", f"{s.probability:.2%}"] for s in rows
            ],
            hovertemplate="%{customdata[0]}: total payout %{customdata[1]}, chance "
            "%{customdata[2]}<extra></extra>",
        )
    )
    fig.update_yaxes(
        tickvals=list(range(len(rows))),
        ticktext=labels,
        color=TEXT,
        automargin=True,
        showgrid=False,
        autorange="reversed",
    )
    fig.update_xaxes(
        tickformat=".0%",
        gridcolor=GRID,
        color=MUTED,
        zeroline=False,
        range=[0, max(s.probability for s in rows) * 1.25],
    )
    return _base(fig, 300)


PURPLE = "#b392f0"


def _nice_step(raw: float) -> float:
    """A readable axis step (1, 2, 2.5 or 5 times a power of ten) of at least ``raw``."""
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def correct_combined(
    cc: CorrectCountAnalysis, selected: int | None = None, view: str = "focus"
) -> go.Figure:
    """One chart for the number of correct predictions (0-9):

    * bars (left axis): P(exactly k correct), the unconditional Poisson-binomial
      probabilities - never renormalised, whatever the view;
    * line with markers (right axis): E[gross payout | exactly k correct], the
      probability-weighted average over that count's combinations (the engine's
      value); impossible counts are left as gaps, never drawn as zero;
    * a dotted reference at 100 on the payout axis.

    ``view="focus"`` hides the nine-correct point from the payout line (its value is
    usually far larger and would flatten the rest) and says so on the chart;
    ``view="all"`` plots every point.
    """
    ks = [r.k for r in cc.rows]
    probs = [r.probability for r in cc.rows]
    pay = [r.expected_gross for r in cc.rows]
    focus = view != "all"
    shown = [None if (focus and r.k == 9) else v for r, v in zip(cc.rows, pay, strict=True)]
    bar_cols = [TEAL if k == selected else "#2a6f66" for k in ks]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=ks,
            y=probs,
            name="Chance of exactly this many correct",
            marker={"color": bar_cols},
            customdata=[[r.combinations, f"{r.probability:.2%}"] for r in cc.rows],
            hovertemplate="%{x} correct: chance %{customdata[1]} "
            "(%{customdata[0]} combinations)<extra></extra>",
            yaxis="y",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ks,
            y=shown,
            name="Average payout if exactly this many correct",
            mode="lines+markers",
            line={"color": PURPLE, "width": 2},
            marker={"size": [10 if k == selected else 7 for k in ks], "color": PURPLE},
            connectgaps=False,
            customdata=[[f"{v:,.2f}" if v is not None else "impossible"] for v in pay],
            hovertemplate="%{x} correct: average payout %{customdata[0]}<extra></extra>",
            yaxis="y2",
        )
    )
    visible = [v for v in shown if v is not None]
    step = _nice_step(max([*visible, 100.0]) * 1.08 / 4)
    top = step * math.ceil(max([*visible, 100.0]) * 1.08 / step)
    fig.add_shape(
        type="line", xref="paper", x0=0, x1=1, yref="y2", y0=100, y1=100,
        line={"color": TEAL, "width": 1, "dash": "dot"},
    )  # fmt: skip
    fig.add_annotation(
        xref="paper", x=0, yref="y2", y=100, text="100 back", showarrow=False,
        xanchor="left", yanchor="bottom", font={"size": 10, "color": TEAL},
    )  # fmt: skip
    if focus and pay[9] is not None:
        fig.add_annotation(
            xref="paper", yref="paper", x=1, y=1.0, xanchor="right", yanchor="bottom",
            text=f"9 correct hidden from the payout line (average {pay[9]:,.2f})",
            showarrow=False, font={"size": 10.5, "color": MUTED},
        )  # fmt: skip
    _base(fig, 300)
    fig.update_layout(
        showlegend=True,
        legend={"orientation": "h", "x": 0, "y": -0.28, "font": {"size": 11, "color": MUTED}},
        margin={"l": 8, "r": 8, "t": 22, "b": 8},
        bargap=0.25,
        xaxis={"tickvals": ks, "title": "Correct predictions", "color": MUTED, "showgrid": False},
        yaxis={
            "title": {"text": "Chance", "font": {"color": TEAL}},
            "tickformat": ".0%",
            "gridcolor": GRID,
            "color": MUTED,
            "zeroline": False,
            "range": [0, max(probs) * 1.2],
        },
        yaxis2={
            "title": {"text": "Average payout", "font": {"color": PURPLE}},
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
            "color": MUTED,
            "zeroline": False,
            "range": [0, top],
            "dtick": step,
            "tickformat": ",.0f",
        },
    )
    return fig
