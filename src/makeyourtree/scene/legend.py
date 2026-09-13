# SPDX-License-Identifier: MIT
"""Legend construction.

Every track declares what it means through
:meth:`makeyourtree.tracks.base.Track.legend`; this module turns that declaration
into marks.  It is separate from the compositor because the legend is the one
part of a figure whose size depends on measured text rather than on the tree:
it has to be laid out before the page can be sized, and the compositor wants
that as a single call returning both the marks and the space consumed.

Continuous scales are drawn as a strip of adjacent rectangles in one batched
:class:`~makeyourtree.scene.marks.RectsMark` rather than as a gradient object.
That keeps the mark vocabulary small -- no backend needs to grow gradient
support -- and it renders identically in SVG and in Qt.

Nothing here measures text by guessing: every width comes from the injected
:class:`~makeyourtree.text.metrics.TextMetrics`, so a swatch column never runs into
its labels.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Iterable, NamedTuple, Sequence

from ..style.color import Color
from ..style.theme import Theme
from ..text.metrics import TextMetrics, default_metrics
from .marks import (Anchor, Baseline, EllipseMark, LinesMark, Mark, Paint,
                    RectMark, RectsMark, TextMark, TextStyle)

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported for annotations only: makeyourtree.layout.projector imports
    # makeyourtree.scene, so a runtime import of the frame here would be a cycle.
    from ..layout.frame import Bounds
    from ..tracks.base import Legend, Track

__all__ = ["build_legend", "LegendResult"]

_GRADIENT_SLICES = 48
"""Rectangles per continuous bar.  Fine enough to read as continuous at print
resolution, coarse enough that the bar stays one small mark."""

_BAR_LENGTH = 9.0
"""Continuous bar length, in multiples of the swatch size."""


class LegendResult(NamedTuple):
    """Marks plus the page space they consume.

    A tuple rather than a bare list because the compositor needs both halves to
    size the page, and unpacking ``marks, w, h = build_legend(...)`` reads
    better than a second call to ask how big the result was.
    """

    marks: list[Mark]
    width: float
    height: float


def build_legend(tracks: Iterable["Track"], theme: Theme, bounds: "Bounds", *,
                 metrics: TextMetrics | None = None,
                 position: str | None = None) -> LegendResult:
    """Lay out the legends of *tracks* just outside *bounds*.

    *bounds* is the scene-space extent of everything drawn so far, so the
    legend can sit beside or below the figure without overlapping it.
    ``theme.legend_position`` picks the side: ``right`` and ``bottom`` push the
    page out, ``top-left`` overlays the figure's own corner and therefore
    consumes no extra space.
    """
    metrics = metrics or default_metrics()
    pos = (position or theme.legend_position or "right").strip().lower()
    if not theme.legend_show or pos == "none":
        return LegendResult([], 0.0, 0.0)

    blocks: list[tuple["Legend", float, float]] = []
    for track in tracks:
        legend = track.legend()
        if not legend or not legend.items:
            continue
        w, h = _block_size(legend, theme, metrics)
        blocks.append((legend, w, h))
    if not blocks:
        return LegendResult([], 0.0, 0.0)

    x0, y0, x1, y1 = bounds
    pad = max(theme.legend_gap * 2.0, theme.track_margin)
    marks: list[Mark] = []

    if pos == "bottom":
        # Blocks flow left to right and wrap inside the figure's own width, so
        # the legend never makes the page wider than the tree already made it.
        avail = max(x1 - x0, max(b[1] for b in blocks))
        cx, cy = x0, y1 + pad
        row_h = 0.0
        for legend, w, h in blocks:
            if cx > x0 and cx + w > x0 + avail:
                cx = x0
                cy += row_h + theme.legend_gap * 2.0
                row_h = 0.0
            marks.extend(_emit_block(legend, cx, cy, theme, metrics))
            cx += w + theme.legend_gap * 3.0
            row_h = max(row_h, h)
        total_h = (cy + row_h) - y1
        return LegendResult(marks, 0.0, total_h)

    if pos in ("top-left", "topleft", "inside"):
        cx, cy = x0, y0
        for legend, w, h in blocks:
            marks.extend(_emit_block(legend, cx, cy, theme, metrics))
            cy += h + theme.legend_gap * 2.0
        return LegendResult(marks, 0.0, 0.0)

    # Default: a single column to the right of the figure.
    cx, cy = x1 + pad, y0
    width = 0.0
    for legend, w, h in blocks:
        marks.extend(_emit_block(legend, cx, cy, theme, metrics))
        cy += h + theme.legend_gap * 2.0
        width = max(width, w)
    return LegendResult(marks, width + pad, 0.0)


# ------------------------------------------------------------------ sizing


def _block_size(legend: "Legend", theme: Theme,
                metrics: TextMetrics) -> tuple[float, float]:
    """Width and height of one track's legend block."""
    sw = theme.legend_swatch
    gap = theme.legend_gap
    fs = theme.legend_size
    line = max(sw, metrics.line_height(fs))
    w = 0.0
    h = 0.0
    if legend.title:
        ts = theme.track_title_size
        w = metrics.advance(legend.title, ts, bold=True)
        h = metrics.line_height(ts)
    if legend.kind == "continuous":
        bar = sw * _BAR_LENGTH
        w = max(w, bar)
        h += sw + metrics.line_height(fs) * 1.1
        for item in legend.items:
            if item.gradient is None and item.label:
                w = max(w, sw + gap + metrics.advance(item.label, fs))
                h += line
    else:
        for item in legend.items:
            w = max(w, sw + gap + metrics.advance(item.label, fs))
            h += line
    return (w, h)


# ------------------------------------------------------------------ drawing


def _emit_block(legend: "Legend", x: float, y: float, theme: Theme,
                metrics: TextMetrics) -> list[Mark]:
    """Marks for one block, with its top-left corner at (*x*, *y*)."""
    sw = theme.legend_swatch
    gap = theme.legend_gap
    fs = theme.legend_size
    line = max(sw, metrics.line_height(fs))
    fg = theme.foreground
    out: list[Mark] = []
    cy = y

    if legend.title:
        ts = theme.track_title_size
        lh = metrics.line_height(ts)
        out.append(TextMark(
            x=x, y=cy + lh * 0.5, text=legend.title,
            style=TextStyle(family=theme.font_family, size=ts, weight=600,
                            color=fg, anchor=Anchor.START,
                            baseline=Baseline.MIDDLE)))
        cy += lh

    label_style = TextStyle(family=theme.font_family, size=fs, color=fg,
                            anchor=Anchor.START, baseline=Baseline.MIDDLE)

    for item in legend.items:
        if legend.kind == "continuous" and item.gradient:
            cy = _emit_gradient(out, item, x, cy, sw, fs, theme, metrics)
            continue
        _emit_swatch(out, item, x, cy, sw, line, theme)
        if item.label:
            out.append(TextMark(x=x + sw + gap, y=cy + line * 0.5,
                                text=item.label, style=label_style))
        cy += line
    return out


def _emit_swatch(out: list[Mark], item, x: float, y: float, sw: float,
                 line: float, theme: Theme) -> None:
    color = item.color if item.color is not None else theme.muted
    top = y + (line - sw) * 0.5
    border = theme.track_border
    paint = Paint(fill=color, stroke=border, width=0.6 if border else 0.0)
    shape = (item.shape or "square").lower()
    if shape == "circle":
        out.append(EllipseMark(paint=paint, cx=x + sw * 0.5, cy=y + line * 0.5,
                               rx=sw * 0.5, ry=sw * 0.5))
    elif shape == "line":
        out.append(LinesMark(paint=Paint.stroked(color, max(1.5, sw * 0.2)),
                             coords=[x, y + line * 0.5, x + sw, y + line * 0.5]))
    else:
        out.append(RectMark(paint=paint, x=x, y=top, w=sw, h=sw, rx=sw * 0.15))


def _emit_gradient(out: list[Mark], item, x: float, y: float, sw: float,
                   fs: float, theme: Theme, metrics: TextMetrics) -> float:
    """Draw one continuous bar with min / mid / max labels; return the new y."""
    stops: Sequence[Color] = item.gradient or ()
    bar = sw * _BAR_LENGTH
    if len(stops) < 2:
        stops = tuple(stops) * 2 if stops else (theme.muted, theme.muted)
    slice_w = bar / _GRADIENT_SLICES
    coords: list[float] = []
    fills: list[Color] = []
    for i in range(_GRADIENT_SLICES):
        t = (i + 0.5) / _GRADIENT_SLICES
        coords.extend((x + i * slice_w, y, slice_w * 1.02, sw))
        fills.append(_sample(stops, t))
    border = theme.track_border
    out.append(RectsMark(paint=Paint(fill=None, stroke=border,
                                     width=0.6 if border else 0.0),
                         coords=coords, fills=fills))

    lo, hi = item.value_range if item.value_range else (0.0, 1.0)
    mid = (lo + hi) * 0.5
    lh = metrics.line_height(fs)
    ty = y + sw + lh * 0.6
    base = TextStyle(family=theme.font_family, size=fs, color=theme.muted,
                     baseline=Baseline.MIDDLE)
    for value, tx, anchor in ((lo, x, Anchor.START),
                              (mid, x + bar * 0.5, Anchor.MIDDLE),
                              (hi, x + bar, Anchor.END)):
        out.append(TextMark(x=tx, y=ty, text=_fmt_value(value),
                            style=dataclasses.replace(base, anchor=anchor)))
    return y + sw + lh * 1.1


def _sample(stops: Sequence[Color], t: float) -> Color:
    """Piecewise-linear sample of a colour ramp at *t* in ``[0, 1]``."""
    if len(stops) == 1:
        return stops[0]
    t = max(0.0, min(1.0, t))
    span = t * (len(stops) - 1)
    i = min(int(span), len(stops) - 2)
    return stops[i].lerp(stops[i + 1], span - i)


def _fmt_value(v: float) -> str:
    return f"{v:.3g}"
