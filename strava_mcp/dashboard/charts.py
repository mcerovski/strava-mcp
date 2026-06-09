"""Inline-SVG line charts generated from stored streams (no JS, no CDN).

Streams are downsampled to a bounded number of points before plotting so chart
size and render time stay bounded regardless of activity length (spec SC-003,
Constitution IV). Only stream types that are present and carry a non-zero signal
produce a chart; all-zero series (e.g. indoor altitude/grade) are suppressed.
"""

from __future__ import annotations

from html import escape
from typing import Any

MAX_POINTS = 1000
_W = 720
_H = 200
_PAD_L = 48
_PAD_R = 12
_PAD_T = 10
_PAD_B = 24

# Plottable stream type -> (display label, unit). Order defines chart order.
# Axis/positional streams (time, distance, latlng, moving) are never plotted.
_SERIES: tuple[tuple[str, str, str], ...] = (
    ("heartrate", "Heart rate", "bpm"),
    ("watts", "Power", "W"),
    ("velocity_smooth", "Speed", "m/s"),
    ("altitude", "Elevation", "m"),
    ("cadence", "Cadence", "rpm"),
    ("temp", "Temperature", "°C"),
    ("grade_smooth", "Grade", "%"),
)


def _data(streams: dict[str, Any], key: str) -> list[Any] | None:
    """Return the sample list for a stream key, if present and non-empty."""
    s = streams.get(key)
    if not isinstance(s, dict):
        return None
    data = s.get("data")
    if isinstance(data, list) and data:
        return data
    return None


def downsample(
    xs: list[float], ys: list[float], max_points: int = MAX_POINTS
) -> tuple[list[float], list[float]]:
    """Stride-reduce paired series to at most ``max_points`` points (keeps the last)."""
    n = len(ys)
    if n <= max_points:
        return xs, ys
    stride = (n + max_points - 1) // max_points
    rx = xs[::stride]
    ry = ys[::stride]
    if rx[-1] != xs[-1]:
        rx.append(xs[-1])
        ry.append(ys[-1])
    return rx, ry


def _x_axis(streams: dict[str, Any], n: int) -> tuple[list[float], str]:
    """Pick the x basis: distance (km) if present, else time (min), else index."""
    dist = _data(streams, "distance")
    if dist is not None and len(dist) == n:
        return [float(v) / 1000.0 for v in dist], "Distance (km)"
    tim = _data(streams, "time")
    if tim is not None and len(tim) == n:
        return [float(v) / 60.0 for v in tim], "Time (min)"
    return [float(i) for i in range(n)], "Sample"


def _polyline(xs: list[float], ys: list[float]) -> str:
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    xspan = (xmax - xmin) or 1.0
    yspan = (ymax - ymin) or 1.0
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    pts = []
    for x, y in zip(xs, ys, strict=True):
        px = _PAD_L + (x - xmin) / xspan * plot_w
        py = _PAD_T + (1.0 - (y - ymin) / yspan) * plot_h
        pts.append(f"{px:.1f},{py:.1f}")
    return " ".join(pts)


def _chart_svg(label: str, unit: str, xs: list[float], ys: list[float], x_label: str) -> str:
    xs, ys = downsample(xs, ys)
    points = _polyline(xs, ys)
    ymin, ymax = min(ys), max(ys)
    baseline = _H - _PAD_B
    title = escape(f"{label} ({unit})")
    return (
        f'<div class="chart"><div class="chart-title">{title}</div>'
        f'<svg viewBox="0 0 {_W} {_H}" preserveAspectRatio="none" '
        f'role="img" aria-label="{title}">'
        f'<line x1="{_PAD_L}" y1="{_PAD_T}" x2="{_PAD_L}" y2="{baseline}" '
        f'stroke="#2a2f3a"/>'
        f'<line x1="{_PAD_L}" y1="{baseline}" x2="{_W - _PAD_R}" y2="{baseline}" '
        f'stroke="#2a2f3a"/>'
        f'<polyline fill="none" stroke="#fc4c02" stroke-width="1.5" points="{points}"/>'
        f'<text x="4" y="{_PAD_T + 8}" fill="#9aa3af" font-size="10">{ymax:g}</text>'
        f'<text x="4" y="{baseline}" fill="#9aa3af" font-size="10">{ymin:g}</text>'
        f'<text x="{_W - _PAD_R}" y="{_H - 6}" fill="#9aa3af" font-size="10" '
        f'text-anchor="end">{escape(x_label)}</text>'
        f"</svg></div>"
    )


def build_activity_charts(streams_payload: dict[str, Any] | None) -> list[str]:
    """Return one inline-SVG chart per present plottable stream type.

    ``streams_payload`` is the ``StreamsRepository.read`` shape
    (``{"streams": {...}}``) or None. Absent types yield no chart (never faked).
    """
    if not streams_payload:
        return []
    streams = streams_payload.get("streams") or {}
    charts: list[str] = []
    for key, label, unit in _SERIES:
        ys_raw = _data(streams, key)
        if ys_raw is None:
            continue
        try:
            ys = [float(v) for v in ys_raw]
        except (TypeError, ValueError):
            continue
        # Strava returns altitude/grade_smooth (and sometimes speed) for every
        # activity, filling them with zeros when the device had no barometer/GPS.
        # An all-zero series carries no plottable signal regardless of sport, so
        # suppress it rather than render a dead-flat line. Streams with any
        # non-zero sample (incl. negatives, or zeros mixed with real values) stay.
        if not any(ys):
            continue
        xs, x_label = _x_axis(streams, len(ys))
        charts.append(_chart_svg(label, unit, xs, ys, x_label))
    return charts
