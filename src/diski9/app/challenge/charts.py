"""Plotly figures for the portfolio analysis (Phase 6B.1).

Every number comes from the engines (``GroupEvaluation`` and
``CorrectCountAnalysis``); this module only draws them. The Phase 6B survival and
exact-payout charts were removed from the participant interface; the underlying
engine calculations (``payout_distribution``, ``probability_at_least``) remain.
"""

from __future__ import annotations

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
    labels = [f"{state_label(s.wins)}  ·  {s.gross:,.2f} cr" for s in rows]
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
            hovertemplate="%{customdata[0]}: total %{customdata[1]} credits, chance "
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


def correct_histogram(cc: CorrectCountAnalysis, selected: int | None = None) -> go.Figure:
    ks = [r.k for r in cc.rows]
    colours = [TEAL if k == selected else "#2a6f66" for k in ks]
    fig = go.Figure(
        go.Bar(
            x=ks,
            y=[r.probability for r in cc.rows],
            marker={"color": colours},
            text=[f"{r.probability:.0%}" if r.probability >= 0.005 else "" for r in cc.rows],
            textposition="outside",
            cliponaxis=False,
            customdata=[[r.combinations, f"{r.probability:.2%}"] for r in cc.rows],
            hovertemplate="%{x} correct: %{customdata[1]} (%{customdata[0]} combinations)"
            "<extra></extra>",
        )
    )
    fig.update_xaxes(tickvals=ks, title="Correct predictions", color=MUTED, showgrid=False)
    fig.update_yaxes(
        tickformat=".0%",
        gridcolor=GRID,
        color=MUTED,
        zeroline=False,
        range=[0, max(r.probability for r in cc.rows) * 1.2],
    )
    fig.update_layout(margin={"l": 8, "r": 8, "t": 8, "b": 40})
    return _base(fig, 230)


def conditional_payout_figure(cc: CorrectCountAnalysis, selected: int | None = None) -> go.Figure:
    """Average gross payout if exactly k predictions are correct (a separate chart, not a
    second axis)."""
    ks = [r.k for r in cc.rows]
    vals = [r.expected_gross or 0.0 for r in cc.rows]
    fig = go.Figure(
        go.Bar(
            x=ks,
            y=vals,
            marker={"color": [AMBER if k == selected else "#7a6233" for k in ks]},
            customdata=[
                [f"{v:,.2f}" if r.expected_gross is not None else "impossible"]
                for v, r in zip(vals, cc.rows, strict=True)
            ],
            hovertemplate="%{x} correct: average %{customdata[0]} credits<extra></extra>",
        )
    )
    fig.add_hline(y=100, line={"color": TEAL, "width": 1, "dash": "dash"})
    fig.update_xaxes(tickvals=ks, title="Correct predictions", color=MUTED, showgrid=False)
    fig.update_yaxes(title="Average payout (cr)", gridcolor=GRID, color=MUTED, zeroline=False)
    fig.update_layout(margin={"l": 8, "r": 8, "t": 8, "b": 40})
    return _base(fig, 200)
