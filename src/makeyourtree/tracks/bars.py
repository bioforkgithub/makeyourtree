# SPDX-License-Identifier: MIT
"""Bar charts: one value per node, or several columns grouped or stacked.

This module also owns the shared numeric plumbing that the other chart-like
tracks in this package reuse -- a band-space value axis, tick selection and
band-space polyline projection -- because bars, box plots, domain diagrams and
line charts all reduce to "map a number onto the offset axis and draw a quad".
One implementation of that mapping is what stops the axis a box plot draws from
disagreeing with the axis a bar chart draws over the same numbers.  Quad
batching itself comes from :class:`makeyourtree.tracks.shapes.QuadBatch`, which
every cell-shaped track in the package already shares.

Tick values come from Heckbert's nice-number algorithm (P. S. Heckbert, "Nice
Numbers for Graph Labels", *Graphics Gems*, Academic Press, 1990, pp. 61-63),
which picks the coarsest of 1/2/5 x 10^k that still yields roughly the
requested number of intervals.

Axis honesty
------------
``zero_based`` defaults to true, so the value domain is widened to include zero
and bar *lengths* stay proportional to the values they encode.  A truncated
axis makes a 2 % difference look like a 200 % one; it is available, but only
when the user asks for it.

Negative values
---------------
A bar runs between the offset of the baseline value and the offset of the
datum, in whichever order those fall, so a value below the baseline extends
toward the tree on the same scale.  Stacked bars accumulate positives outward
and negatives inward from the baseline independently -- the only accumulation
rule under which the outer end of an all-positive stack equals the stack total.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

from ..layout.projector import Projector
from ..scene.marks import (Anchor, Baseline, MarkSink, Paint, PolylineMark,
                           TextMark, TextStyle)
from ..style.color import Color, parse_color
from ..style.theme import Theme
from .base import (Legend, LegendItem, Track, TrackContext, TrackData,
                   register)
from .shapes import QuadBatch

__all__ = [
    "BarChartTrack", "ValueAxis", "nice_ticks", "column_colors", "safe_color",
    "resolve_colors", "iter_band_rows", "project_polyline", "draw_value_axis",
    "numeric", "add_quad", "option_color",
]


# ----------------------------------------------------------------- palette

# Okabe and Ito's eight-colour qualitative set ("Color Universal Design", 2008),
# which stays distinguishable under the common forms of colour vision
# deficiency.  Used when the palette module -- a separate unit -- is absent.
_FALLBACK_CYCLE: tuple[Color, ...] = (
    Color(0, 114, 178), Color(230, 159, 0), Color(0, 158, 115),
    Color(204, 121, 167), Color(86, 180, 233), Color(213, 94, 0),
    Color(240, 228, 66), Color(100, 100, 110),
)


def column_colors(n: int, theme: Theme | None = None) -> list[Color]:
    """*n* series colours, cycling the theme's categorical palette.

    Falling back to the built-in cycle keeps every multi-column track
    renderable rather than failing a whole draw for want of a colour table.
    """
    ramp = _theme_cycle(theme)
    return [ramp[i % len(ramp)] for i in range(max(0, n))]


def _theme_cycle(theme: Theme | None) -> tuple[Color, ...]:
    from ..style.palettes import get_palette

    name = theme.categorical_palette if theme is not None else "okabe-ito"
    try:
        ramp = tuple(get_palette(name))
    except (TypeError, KeyError, ValueError):
        return _FALLBACK_CYCLE
    if ramp and all(isinstance(c, Color) for c in ramp):
        return ramp
    return _FALLBACK_CYCLE


def resolve_colors(track: Track, n: int, theme: Theme | None,
                   columns: Sequence[str] = ()) -> list[Color]:
    """Per-column colours: explicit options first, then the palette cycle.

    ``colors`` accepts a list positional to the columns or a mapping keyed by
    column name or index; ``color`` covers the single-column case.  An
    unparseable spec falls back to the palette entry instead of aborting the
    render, because a bad colour cell is a data problem, not a fatal one.
    """
    out = column_colors(n, theme)
    spec = track.opt("colors")
    if isinstance(spec, dict):
        for i in range(n):
            key = columns[i] if i < len(columns) else None
            raw = spec.get(key, spec.get(i, spec.get(str(i))))
            if raw is not None:
                out[i] = safe_color(raw, out[i])
    elif isinstance(spec, (list, tuple)):
        for i, raw in enumerate(spec[:n]):
            if raw is not None:
                out[i] = safe_color(raw, out[i])
    single = track.opt("color")
    if single is not None and n >= 1 and not spec:
        out[0] = safe_color(single, out[0])
    return out


def safe_color(raw: Any, fallback: Color) -> Color:
    try:
        return parse_color(raw)
    except ValueError:
        return fallback


def option_color(track: Track, key: str, fallback: Color) -> Color:
    """A colour option, falling back when it is unset or unparseable."""
    raw = track.opt(key)
    return safe_color(raw, fallback) if raw is not None else fallback


def numeric(value: Any) -> float | None:
    """Finite float, or ``None`` for anything that must render as a gap."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# --------------------------------------------------------------- band rows


def iter_band_rows(ctx: TrackContext, data: TrackData,
                   include_internal: bool = False) -> Iterator[tuple[int, float, float]]:
    """``(node_id, centre_row, row_extent)`` for every node that has data.

    Visible tips take the row span the layout gave them, so a collapsed clade
    gets a proportionally taller band with no special case here.  Internal
    nodes own no row -- their centre row is derived from their descendants --
    so they are opt-in and are allotted a single row of thickness.
    """
    frame = ctx.frame
    rows = data.rows
    for nid in frame.tips:
        if nid not in rows:
            continue
        lo, hi = frame.row_span(nid)
        extent = hi - lo
        yield nid, (lo + hi) * 0.5, extent if extent > 0 else 1.0
    if not include_internal:
        return
    tips = set(frame.tips)
    extra = [nid for nid in rows if nid not in tips and frame.has(nid)]
    extra.sort(key=frame.row)
    for nid in extra:
        yield nid, frame.row(nid), 1.0


# -------------------------------------------------------------- value axis


@dataclass(frozen=True, slots=True)
class ValueAxis:
    """Linear map from data values onto band-space offsets within one track."""

    lo: float
    hi: float
    length: float
    baseline: float = 0.0

    @staticmethod
    def build(values: Sequence[float], *, length: float,
              baseline: float | None = 0.0, zero_based: bool = True,
              vmin: float | None = None, vmax: float | None = None) -> "ValueAxis":
        """*baseline* of ``None`` means the track draws no bars from an anchor,
        so the domain is free to exclude it (a box plot summarises a
        distribution; it does not encode length from a zero)."""
        lo = min(values) if values else 0.0
        hi = max(values) if values else 0.0
        # A baseline has to be on the axis or bars have nothing to start from.
        if baseline is not None:
            lo, hi = min(lo, baseline), max(hi, baseline)
        if zero_based:
            lo, hi = min(lo, 0.0), max(hi, 0.0)
        if vmin is not None:
            lo = float(vmin)
        if vmax is not None:
            hi = float(vmax)
        if hi <= lo:
            hi = lo + 1.0
        return ValueAxis(lo, hi, length, baseline if baseline is not None else lo)

    @property
    def span(self) -> float:
        return self.hi - self.lo

    def offset(self, value: float) -> float:
        span = self.span
        if span <= 0:
            return 0.0
        return (value - self.lo) / span * self.length

    @property
    def base_offset(self) -> float:
        return self.offset(self.baseline)

    def ticks(self, count: int = 4) -> list[float]:
        return nice_ticks(self.lo, self.hi, count)


def nice_ticks(lo: float, hi: float, count: int = 4) -> list[float]:
    """Round tick values inside ``[lo, hi]``; Heckbert's nice-number rule."""
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo or count < 1:
        return [lo] if math.isfinite(lo) else []
    step = _nice(_nice(hi - lo, False) / count, True)
    if step <= 0:
        return [lo, hi]
    out: list[float] = []
    eps = step * 1e-9
    k = math.ceil((lo - eps) / step)
    while len(out) < 64:
        v = k * step
        if v > hi + eps:
            break
        out.append(0.0 if abs(v) < eps else v)
        k += 1
    return out


def _nice(x: float, round_down: bool) -> float:
    if x <= 0:
        return 0.0
    exp = math.floor(math.log10(x))
    f = x / (10.0 ** exp)
    if round_down:
        nf = 1.0 if f < 1.5 else 2.0 if f < 3.0 else 5.0 if f < 7.0 else 10.0
    else:
        nf = 1.0 if f <= 1.0 else 2.0 if f <= 2.0 else 5.0 if f <= 5.0 else 10.0
    return nf * (10.0 ** exp)


# --------------------------------------------------------- band-space paths


def project_polyline(projector: Projector, points: Sequence[tuple[float, float]],
                     max_px: float = 3.0) -> list[float]:
    """Project a band-space polyline, subdividing each edge before projecting.

    A straight edge in ``(row, offset)`` is straight in a linear layout but a
    spiral arc in a polar one, so each edge is resampled finely enough that the
    projected chords stay within roughly *max_px* of the true curve.  The step
    comes from :meth:`Projector.tangential`, which already knows how wide one
    row is at a given offset, so no polar arithmetic appears here.
    """
    flat: list[float] = []
    if not points:
        return flat
    flat.extend(projector.point(*points[0]))
    for i in range(1, len(points)):
        r0, o0 = points[i - 1]
        r1, o1 = points[i]
        n = _subdivisions(projector, r0, o0, r1, o1, max_px)
        for step in range(1, n + 1):
            t = step / n
            flat.extend(projector.point(r0 + (r1 - r0) * t, o0 + (o1 - o0) * t))
    return flat


def _subdivisions(projector: Projector, r0: float, o0: float, r1: float,
                  o1: float, max_px: float) -> int:
    if not projector.is_polar:
        return 1
    per_row = projector.tangential((o0 + o1) * 0.5)
    if per_row <= 0 or max_px <= 0:
        return 1
    return max(1, min(512, int(math.ceil(abs(r1 - r0) * per_row / max_px))))


def add_quad(batch: QuadBatch, row0: float, row1: float, off0: float,
             off1: float, color: Color) -> None:
    """Queue a band-space quad, letting callers name corners in any order.

    The normalisation this used to do locally now lives in
    :meth:`~makeyourtree.tracks.shapes.QuadBatch.add`, where every cell-shaped
    track gets it rather than only the three that went through here.  Kept as
    the name the chart tracks call so the intent -- "from the baseline to the
    value, whichever direction that turns out to be" -- stays readable at the
    call site.
    """
    batch.add(row0, row1, off0, off1, color)


# ------------------------------------------------------------- the axis art


def draw_value_axis(ctx: TrackContext, sink: MarkSink, axis: ValueAxis,
                    ticks: Sequence[float], *, size: float, color: Color,
                    label_row: float = -0.6, fmt: str = "{:.4g}") -> None:
    """Grid lines at *ticks* spanning the band, labelled once at the band head.

    The lines are band-space verticals, so the identical call yields concentric
    circles in a polar layout.  They are emitted before the data so the data
    always wins the overlap.
    """
    projector = ctx.projector
    n_rows = max(float(projector.n_rows), 1.0)
    line_paint = Paint(stroke=color, width=0.6, dash=(1.5, 3.0))
    style = TextStyle(family=ctx.theme.font_family, size=size, color=color,
                      anchor=Anchor.MIDDLE, baseline=Baseline.ALPHABETIC)
    for value in ticks:
        off = ctx.offset + axis.offset(value)
        pts = project_polyline(projector, [(0.0, off), (n_rows, off)])
        if len(pts) >= 4:
            sink.add(PolylineMark(paint=line_paint, points=tuple(pts)))
        place = projector.text(label_row, off, Anchor.MIDDLE)
        sink.add(TextMark(paint=Paint(), x=place.x, y=place.y,
                          text=fmt.format(value), rotation=place.rotation,
                          style=dataclasses.replace(style, anchor=place.anchor)))


# ---------------------------------------------------------------- the track


@register
class BarChartTrack(Track):
    """Bars along the offset axis: one column, or several grouped or stacked."""

    type_id = "bar-chart"
    display_name = "Bar chart"
    needs_numeric = True
    multi_column = True

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        opts = super().default_options()
        opts.update({
            "thickness": 120.0,
            "baseline": 0.0,
            "zero_based": True,
            "value_min": None,
            "value_max": None,
            "stack": "stacked",
            "bar_gap": 0.2,
            "series_gap": 0.1,
            "colors": None,
            "color": None,
            "axis": True,
            "axis_ticks": 4,
            "axis_size": None,
            "axis_format": "{:.4g}",
            "show_internal": False,
        })
        return opts

    # -------------------------------------------------------------- shape

    def measure(self, ctx: TrackContext) -> float:
        return max(0.0, float(self.opt("thickness", 120.0)))

    def _n_columns(self) -> int:
        return max(1, len(self.data.columns))

    def _grouped(self) -> bool:
        mode = str(self.opt("stack", "stacked")).lower()
        return mode in ("grouped", "side", "side-by-side")

    def value_axis(self, ctx: TrackContext) -> ValueAxis:
        """Value domain over every quantity a bar will actually reach.

        Stacked bars need the domain of the running totals, not of the single
        values, or the tallest stack runs off the end of the track.
        """
        n = self._n_columns()
        baseline = float(self.opt("baseline", 0.0) or 0.0)
        values: list[float] = []
        if n > 1 and not self._grouped():
            for row in self.data.rows.values():
                up = down = baseline
                for c in range(min(n, len(row))):
                    v = numeric(row[c])
                    if v is None:
                        continue
                    if v >= 0:
                        up += v
                    else:
                        down += v
                values.extend((up, down))
        else:
            for c in range(n):
                values.extend(self.data.numeric_column(c))
        return ValueAxis.build(
            values, length=self.measure(ctx), baseline=baseline,
            zero_based=bool(self.opt("zero_based", True)),
            vmin=self.opt("value_min"), vmax=self.opt("value_max"),
        )

    # --------------------------------------------------------------- draw

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        n = self._n_columns()
        axis = self.value_axis(ctx)
        colors = resolve_colors(self, n, ctx.theme, self.data.columns)
        if self.opt("axis", True):
            draw_value_axis(
                ctx, sink, axis, axis.ticks(int(self.opt("axis_ticks", 4) or 4)),
                size=float(self.opt("axis_size") or ctx.theme.track_title_size),
                color=ctx.theme.muted, fmt=str(self.opt("axis_format", "{:.4g}")))

        border = self.opt("border_color")
        batch = QuadBatch(
            ctx.projector, opacity=float(self.opt("opacity", 1.0) or 1.0),
            stroke=safe_color(border, ctx.theme.foreground) if border else None,
            stroke_width=float(self.opt("border_width", 0.0) or 0.0))

        gap = min(max(float(self.opt("bar_gap", 0.2) or 0.0), 0.0), 0.9)
        grouped = n > 1 and self._grouped()
        base_off = ctx.offset + axis.base_offset

        for nid, centre, extent in iter_band_rows(
                ctx, self.data, bool(self.opt("show_internal", False))):
            row = self.data.rows[nid]
            height = extent * (1.0 - gap)
            top = centre - height * 0.5
            if grouped:
                self._grouped_bars(batch, row, n, colors, axis, ctx.offset,
                                   base_off, top, height)
            elif n > 1:
                self._stacked_bars(batch, row, n, colors, axis, ctx.offset,
                                   top, height)
            else:
                v = numeric(row[0]) if row else None
                if v is not None:
                    add_quad(batch, top, top + height, base_off,
                             ctx.offset + axis.offset(v), colors[0])
        batch.flush(sink)

    def _grouped_bars(self, batch: QuadBatch, row: Sequence[Any], n: int,
                      colors: Sequence[Color], axis: ValueAxis, origin: float,
                      base_off: float, top: float, height: float) -> None:
        """Every column gets its own sub-row and starts from the baseline."""
        sub = height / n
        pad = sub * min(max(float(self.opt("series_gap", 0.1) or 0.0), 0.0), 0.45) * 0.5
        for c in range(n):
            v = numeric(row[c]) if c < len(row) else None
            if v is None:
                continue
            lo = top + c * sub + pad
            add_quad(batch, lo, lo + sub - 2 * pad, base_off,
                     origin + axis.offset(v), colors[c])

    def _stacked_bars(self, batch: QuadBatch, row: Sequence[Any], n: int,
                      colors: Sequence[Color], axis: ValueAxis, origin: float,
                      top: float, height: float) -> None:
        """Positives accumulate outward, negatives inward, both from the baseline."""
        up = down = axis.baseline
        for c in range(n):
            v = numeric(row[c]) if c < len(row) else None
            if v is None or v == 0.0:
                continue
            if v > 0:
                start, up = up, up + v
                end = up
            else:
                start, down = down, down + v
                end = down
            add_quad(batch, top, top + height, origin + axis.offset(start),
                     origin + axis.offset(end), colors[c])

    # ------------------------------------------------------------- legend

    def legend(self) -> Legend:
        n = self._n_columns()
        colors = resolve_colors(self, n, None, self.data.columns)
        if n == 1:
            label = self.data.columns[0] if self.data.columns else (self.title or "value")
            return Legend(title=self.title,
                          items=[LegendItem(label=label, color=colors[0])])
        items = [LegendItem(label=self.data.columns[i], color=colors[i])
                 for i in range(n)]
        if not self._grouped():
            # A stack reads outward, so the legend reads in the same direction.
            items.reverse()
        return Legend(title=self.title, items=items)
