# ruff: noqa: E501  (SVG markup strings)
"""Research only (Phase 5B): dependency-free static SVG charts for the Weekly
Challenge portfolio report. Every point is a calculated portfolio; nothing is
interpolated or smoothed. Dominated points are grey, efficient points coloured.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from html import escape

from .charts import FONT, GRID, SERIES, SURFACE, TEXT, TEXT_2

GREY = "#b9b7b1"


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    span = hi - lo
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 1e-9:
        if t >= lo - step * 1e-9:
            ticks.append(round(t, 10))
        t += step
    return ticks


def _fmt(v: float, pct: bool) -> str:
    if pct:
        return f"{v * 100:.1f}%" if abs(v) < 0.1 else f"{v * 100:.0f}%"
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"


def scatter_panel(
    series: Sequence[dict],
    x_label: str,
    y_label: str,
    title: str,
    x_pct: bool = False,
    y_pct: bool = False,
    width: int = 640,
    height: int = 420,
    note: str | None = None,
) -> str:
    """``series``: dicts with ``name``, ``x``, ``y``, ``efficient`` (bool list) and
    ``color``. Dominated points are drawn grey first; efficient points on top,
    joined in x order by a thin step line (the frontier exactly as calculated)."""
    left, right, top, bottom = 70, 20, 30 + 16 * len(series), 62
    height += 16 * (len(series) - 1)
    xs = [v for s in series for v in s["x"]]
    ys = [v for s in series for v in s["y"]]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad_x = (x1 - x0) * 0.05 or abs(x0) * 0.05 or 0.01
    pad_y = (y1 - y0) * 0.05 or abs(y0) * 0.05 or 1
    x0, x1, y0, y1 = x0 - pad_x, x1 + pad_x, y0 - pad_y, y1 + pad_y
    pw, ph = width - left - right, height - top - bottom

    def px(v):
        return left + (v - x0) / (x1 - x0) * pw

    def py(v):
        return top + ph - (v - y0) / (y1 - y0) * ph

    body = []
    for t in _nice_ticks(y0, y1):
        body.append(
            f"<line x1='{left}' x2='{left + pw}' y1='{py(t):.1f}' y2='{py(t):.1f}' stroke='{GRID}'/>"
        )
        body.append(
            f"<text x='{left - 6}' y='{py(t) + 4:.1f}' font-size='11' text-anchor='end' fill='{TEXT_2}'>{_fmt(t, y_pct)}</text>"
        )
    for t in _nice_ticks(x0, x1):
        body.append(
            f"<line x1='{px(t):.1f}' x2='{px(t):.1f}' y1='{top}' y2='{top + ph}' stroke='{GRID}'/>"
        )
        body.append(
            f"<text x='{px(t):.1f}' y='{top + ph + 16}' font-size='11' text-anchor='middle' fill='{TEXT_2}'>{_fmt(t, x_pct)}</text>"
        )
    body.append(
        f"<text x='{left + pw / 2}' y='{height - 26}' font-size='12' text-anchor='middle' fill='{TEXT}'>{escape(x_label)}</text>"
    )
    body.append(
        f"<text transform='translate(16,{top + ph / 2}) rotate(-90)' font-size='12' text-anchor='middle' fill='{TEXT}'>{escape(y_label)}</text>"
    )
    for s in series:
        for x, y, e in zip(s["x"], s["y"], s["efficient"], strict=True):
            if not e:
                body.append(
                    f"<circle cx='{px(x):.1f}' cy='{py(y):.1f}' r='2.6' fill='{GREY}' fill-opacity='0.55'/>"
                )
    for k, s in enumerate(series):
        pts = sorted((x, y) for x, y, e in zip(s["x"], s["y"], s["efficient"], strict=True) if e)
        if len(pts) > 1:
            d = " ".join(
                f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(y):.1f}" for i, (x, y) in enumerate(pts)
            )
            body.append(
                f"<path d='{d}' fill='none' stroke='{s['color']}' stroke-width='1' stroke-opacity='0.6'/>"
            )
        for x, y in pts:
            body.append(
                f"<circle cx='{px(x):.1f}' cy='{py(y):.1f}' r='4' fill='{s['color']}' stroke='{SURFACE}' stroke-width='1'/>"
            )
        n_eff = sum(s["efficient"])
        label = f"{s['name']}: {n_eff} efficient of {len(s['x'])}"
        ly = 38 + 16 * k  # one legend row per series, under the title
        body.append(f"<circle cx='{left + 12}' cy='{ly - 4}' r='4' fill='{s['color']}'/>")
        body.append(
            f"<text x='{left + 20}' y='{ly}' font-size='11' fill='{TEXT_2}'>{escape(label)}</text>"
        )
    if note:
        body.append(
            f"<text x='{left}' y='{height - 8}' font-size='10.5' fill='{TEXT_2}'>{escape(note)}</text>"
        )
    return _svg(width, height, body, title)


def bars(labels: Sequence[str], values: Sequence[float], title: str, y_label: str,
         pct: bool = True, width: int = 640, height: int = 320, color: str = SERIES[0]) -> str:  # fmt: skip
    left, right, top, bottom = 70, 20, 40, 70
    pw, ph = width - left - right, height - top - bottom
    vmax = max(values) if values else 1
    vmin = min(0.0, min(values)) if values else 0
    ticks = _nice_ticks(vmin, vmax)
    hi = max(ticks[-1], vmax) or 1

    def py(v):
        return top + ph - (v - vmin) / (hi - vmin) * ph

    body = []
    for t in ticks:
        body.append(
            f"<line x1='{left}' x2='{left + pw}' y1='{py(t):.1f}' y2='{py(t):.1f}' stroke='{GRID}'/>"
        )
        body.append(
            f"<text x='{left - 6}' y='{py(t) + 4:.1f}' font-size='11' text-anchor='end' fill='{TEXT_2}'>{_fmt(t, pct)}</text>"
        )
    n = len(values)
    slot = pw / max(n, 1)
    for i, (lab, v) in enumerate(zip(labels, values, strict=True)):
        x = left + i * slot + slot * 0.15
        w = slot * 0.7
        y = py(max(v, 0))
        h = abs(py(v) - py(0))
        body.append(
            f"<rect x='{x:.1f}' y='{min(y, py(0)):.1f}' width='{w:.1f}' height='{max(h, 0.5):.1f}' rx='2' fill='{color}'/>"
        )
        body.append(
            f"<text x='{x + w / 2:.1f}' y='{top + ph + 14}' font-size='10.5' text-anchor='middle' fill='{TEXT_2}'>{escape(lab)}</text>"
        )
    body.append(
        f"<text transform='translate(16,{top + ph / 2}) rotate(-90)' font-size='12' text-anchor='middle' fill='{TEXT}'>{escape(y_label)}</text>"
    )
    return _svg(width, height, body, title)


def _svg(width: int, height: int, body: list[str], title: str) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' role='img' aria-label='{escape(title)}' {FONT}>"
        f"<rect width='100%' height='100%' fill='{SURFACE}'/>"
        f"<text x='16' y='22' font-size='14' font-weight='600' fill='{TEXT}'>{escape(title)}</text>"
        + "".join(body)
        + "</svg>\n"
    )
