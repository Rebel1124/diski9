"""Research only: dependency-free static SVG charts for the Milestone 5.2 reports.

Static figures embedded in Markdown (no hover layer is possible there; every
chart's numbers are also tabulated in the report or a CSV). Light surface with
recessive grid, thin marks, rounded data ends, 2px gaps, categorical slots in
fixed order from the reference palette.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from pathlib import Path

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
FONT = "font-family='system-ui,-apple-system,Segoe UI,Roboto,sans-serif'"


def _svg(width: int, height: int, body: list[str], title: str) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' role='img' aria-label='{escape(title)}' {FONT}>"
        f"<rect width='100%' height='100%' fill='{SURFACE}'/>"
        f"<text x='16' y='24' font-size='15' font-weight='600' fill='{TEXT}'>{escape(title)}</text>"
        + "".join(body)
        + "</svg>\n"
    )


def _bar(x: float, y: float, w: float, h: float, color: str) -> str:
    """Bar with a 4px rounded top anchored to the baseline."""
    if h <= 0:
        return ""
    r = min(4, w / 2, h)
    return (
        f"<path d='M{x:.1f},{y + h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h:.1f} Z' "
        f"fill='{color}'/>"
    )


def histogram_panels(
    path: Path,
    panels: dict[str, Sequence[float]],
    bins: Sequence[float],
    title: str,
    x_label: str,
) -> None:
    """Small multiples (one per model) of the share of values in each bin, shared y-axis."""
    names = list(panels)
    shares = {}
    for name, values in panels.items():
        counts = [0] * (len(bins) - 1)
        for v in values:
            for i in range(len(bins) - 1):
                if bins[i] <= v < bins[i + 1] or (i == len(bins) - 2 and v == bins[-1]):
                    counts[i] += 1
                    break
        shares[name] = [100 * c / max(1, len(values)) for c in counts]
    ymax = max(max(s) for s in shares.values())
    ymax = (int(ymax / 5) + 1) * 5
    pw, ph, left, top, gap = 330, 170, 56, 52, 46
    cols = 2
    rows = (len(names) + cols - 1) // cols
    width = left + cols * pw + (cols - 1) * 40 + 20
    height = top + rows * (ph + gap) + 30
    body = []
    for k, name in enumerate(names):
        ox = left + (k % cols) * (pw + 40)
        oy = top + (k // cols) * (ph + gap) + 18
        body.append(
            f"<text x='{ox}' y='{oy - 8}' font-size='13' font-weight='600' fill='{TEXT}'>{escape(name)}</text>"
        )
        for t in range(0, ymax + 1, max(5, ymax // 4 // 5 * 5)):
            y = oy + ph - ph * t / ymax
            body.append(
                f"<line x1='{ox}' x2='{ox + pw}' y1='{y:.1f}' y2='{y:.1f}' stroke='{GRID}'/>"
            )
            body.append(
                f"<text x='{ox - 6}' y='{y + 4:.1f}' font-size='11' text-anchor='end' fill='{TEXT_2}'>{t}%</text>"
            )
        n = len(bins) - 1
        bw = pw / n
        for i, s in enumerate(shares[name]):
            h = ph * s / ymax
            body.append(_bar(ox + i * bw + 1, oy + ph - h, bw - 2, h, SERIES[0]))
        for i in range(0, n + 1, 4):
            x = ox + i * bw
            body.append(
                f"<text x='{x:.1f}' y='{oy + ph + 15}' font-size='11' text-anchor='middle' fill='{TEXT_2}'>{bins[i]:g}</text>"
            )
    body.append(
        f"<text x='{width / 2:.0f}' y='{height - 8}' font-size='12' text-anchor='middle' fill='{TEXT_2}'>"
        f"{escape(x_label)} (bin width {bins[1] - bins[0]:g}); bar = share of team scores</text>"
    )
    path.write_text(_svg(width, height, body, title))


def grouped_bars(
    path: Path,
    categories: Sequence[str],
    series: dict[str, Sequence[float]],
    title: str,
    y_label: str,
    y_max: float | None = None,
) -> None:
    """Grouped vertical bars with a legend and a value label on each bar (few bars)."""
    width, height, left, top, ph = 640, 330, 60, 70, 210
    pw = width - left - 24
    ymax = y_max or max(max(v) for v in series.values())
    ymax = (int(ymax / 10) + 1) * 10 if y_max is None else ymax
    body = []
    lx = left
    for k, name in enumerate(series):
        body.append(f"<rect x='{lx}' y='38' width='12' height='12' rx='2' fill='{SERIES[k]}'/>")
        body.append(
            f"<text x='{lx + 18}' y='48' font-size='12' fill='{TEXT}'>{escape(name)}</text>"
        )
        lx += 30 + 8 * len(name)
    for t in range(0, int(ymax) + 1, max(1, int(ymax) // 5)):
        y = top + ph - ph * t / ymax
        body.append(
            f"<line x1='{left}' x2='{left + pw}' y1='{y:.1f}' y2='{y:.1f}' stroke='{GRID}'/>"
        )
        body.append(
            f"<text x='{left - 6}' y='{y + 4:.1f}' font-size='11' text-anchor='end' fill='{TEXT_2}'>{t:g}</text>"
        )
    group = pw / len(categories)
    bw = min(48, (group - 24) / len(series))
    for i, cat in enumerate(categories):
        gx = left + i * group + (group - bw * len(series)) / 2
        for k, (_, vals) in enumerate(series.items()):
            v = vals[i]
            h = ph * v / ymax
            x = gx + k * bw
            body.append(_bar(x + 1, top + ph - h, bw - 2, h, SERIES[k]))
            body.append(
                f"<text x='{x + bw / 2:.1f}' y='{top + ph - h - 5:.1f}' font-size='11' text-anchor='middle' fill='{TEXT}'>{v:.0f}</text>"
            )
        body.append(
            f"<text x='{left + i * group + group / 2:.1f}' y='{top + ph + 18}' font-size='12' text-anchor='middle' fill='{TEXT}'>{escape(cat)}</text>"
        )
    body.append(
        f"<text x='14' y='{top + ph / 2}' font-size='11' fill='{TEXT_2}' transform='rotate(-90 14 {top + ph / 2})' text-anchor='middle'>{escape(y_label)}</text>"
    )
    path.write_text(_svg(width, height, body, title))


def calibration_panels(
    path: Path,
    panels: dict[str, dict[str, Sequence[tuple[float, float, int]]]],
    title: str,
) -> None:
    """Reliability diagrams: per panel, up to three series of (forecast, observed, n)."""
    names = list(panels)
    pw, ph, left, top, gap = 260, 260, 56, 78, 60
    width = left + len(names) * (pw + gap)
    height = top + ph + 54
    body = []
    series_names = list(dict.fromkeys(s for p in panels.values() for s in p))
    lx = left
    for k, s in enumerate(series_names):
        body.append(f"<rect x='{lx}' y='38' width='12' height='12' rx='2' fill='{SERIES[k]}'/>")
        body.append(f"<text x='{lx + 18}' y='48' font-size='12' fill='{TEXT}'>{escape(s)}</text>")
        lx += 34 + 7 * len(s)
    for i, name in enumerate(names):
        ox = left + i * (pw + gap)
        body.append(
            f"<text x='{ox}' y='{top - 10}' font-size='13' font-weight='600' fill='{TEXT}'>{escape(name)}</text>"
        )
        for t in (0, 0.25, 0.5, 0.75, 1):
            y = top + ph - ph * t
            x = ox + pw * t
            body.append(
                f"<line x1='{ox}' x2='{ox + pw}' y1='{y:.1f}' y2='{y:.1f}' stroke='{GRID}'/>"
            )
            body.append(
                f"<text x='{ox - 6}' y='{y + 4:.1f}' font-size='11' text-anchor='end' fill='{TEXT_2}'>{t:g}</text>"
            )
            body.append(
                f"<text x='{x:.1f}' y='{top + ph + 16}' font-size='11' text-anchor='middle' fill='{TEXT_2}'>{t:g}</text>"
            )
        body.append(
            f"<line x1='{ox}' y1='{top + ph}' x2='{ox + pw}' y2='{top}' stroke='{TEXT_2}' stroke-dasharray='4 4'/>"
        )
        for k, s in enumerate(series_names):
            pts = [(f, o) for f, o, n in panels[name].get(s, []) if n >= 30]
            if not pts:
                continue
            d = " ".join(
                f"{'M' if j == 0 else 'L'}{ox + pw * f:.1f},{top + ph - ph * o:.1f}"
                for j, (f, o) in enumerate(pts)
            )
            body.append(f"<path d='{d}' fill='none' stroke='{SERIES[k]}' stroke-width='2'/>")
            for f, o in pts:
                body.append(
                    f"<circle cx='{ox + pw * f:.1f}' cy='{top + ph - ph * o:.1f}' r='4' fill='{SERIES[k]}' stroke='{SURFACE}' stroke-width='2'/>"
                )
        body.append(
            f"<text x='{ox + pw / 2}' y='{top + ph + 36}' font-size='11' text-anchor='middle' fill='{TEXT_2}'>forecast (bins with n ≥ 30); dashed = perfect calibration</text>"
        )
    path.write_text(_svg(width, height, body, title))
