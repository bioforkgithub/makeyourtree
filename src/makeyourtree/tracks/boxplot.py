# SPDX-License-Identifier: MIT
"""Box-and-whisker summaries, one distribution per node.

Two shapes of input are accepted, because both are common in the wild:

*summary*
    Five columns already holding the five-number summary -- minimum, first
    quartile, median, third quartile, maximum -- optionally followed by any
    number of columns of individual outlier values.
*raw*
    Every column is one observation and the summary is computed here.

The summary the raw path computes is Tukey's (J. W. Tukey, *Exploratory Data
Analysis*, Addison-Wesley, 1977, ch. 2): the box spans the quartiles, a point
is an **outlier when it lies more than 1.5 x IQR beyond the nearer quartile**,
and the whiskers stop at the most extreme observation that is *not* an outlier
-- they are not the sample's min and max.  Quartiles use linear interpolation
between order statistics (Hyndman and Fan's type 7, the default in R and in
:func:`numpy.percentile`), so the numbers match what analysts see elsewhere.

Draw order is whisker, caps, box, median, outliers: the opaque box hides the
stretch of whisker it covers, and the median line and the outlier dots are the
two things a reader looks for first, so nothing is allowed on top of them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from ..scene.marks import EllipseMark, MarkSink, Paint, PolylineMark
from ..style.color import Color
from .bars import (ValueAxis, add_quad, draw_value_axis, iter_band_rows,
                   numeric, option_color, project_polyline, safe_color)
from .base import Legend, LegendItem, Track, TrackContext, register
from .shapes import QuadBatch

__all__ = ["BoxPlotTrack", "BoxSummary", "quantile", "tukey_summary"]

_SUMMARY_NAMES: tuple[frozenset[str], ...] = (
    frozenset({"min", "minimum", "lower", "lo", "whisker_low"}),
    frozenset({"q1", "lq", "lower_quartile", "p25", "q25"}),
    frozenset({"median", "med", "q2", "p50"}),
    frozenset({"q3", "uq", "upper_quartile", "p75", "q75"}),
    frozenset({"max", "maximum", "upper", "hi", "whisker_high"}),
)


@dataclass(frozen=True, slots=True)
class BoxSummary:
    """One drawable distribution.  ``low`` and ``high`` are whisker ends."""

    low: float
    q1: float
    median: float
    q3: float
    high: float
    outliers: tuple[float, ...] = ()

    @property
    def iqr(self) -> float:
        return self.q3 - self.q1

    def spread(self) -> list[float]:
        """Every number the box, whiskers or dots will reach, for the domain."""
        return [self.low, self.q1, self.median, self.q3, self.high, *self.outliers]


def quantile(sorted_values: Sequence[float], p: float) -> float:
    """*p*-quantile by linear interpolation between order statistics (type 7)."""
    n = len(sorted_values)
    if n == 0:
        raise ValueError("quantile of an empty sample")
    if n == 1:
        return float(sorted_values[0])
    h = (n - 1) * p
    lo = math.floor(h)
    hi = min(lo + 1, n - 1)
    return float(sorted_values[lo] + (h - lo) * (sorted_values[hi] - sorted_values[lo]))


def tukey_summary(values: Sequence[float], whisker: float = 1.5) -> BoxSummary | None:
    """Five-number summary plus outliers under Tukey's 1.5 x IQR fences.

    Points beyond ``Q1 - k*IQR`` or ``Q3 + k*IQR`` are outliers; the whiskers
    retreat to the most extreme observations still inside those fences.
    """
    xs = sorted(float(v) for v in values)
    if not xs:
        return None
    q1 = quantile(xs, 0.25)
    med = quantile(xs, 0.50)
    q3 = quantile(xs, 0.75)
    fence = whisker * (q3 - q1)
    lo_fence, hi_fence = q1 - fence, q3 + fence
    inside = [x for x in xs if lo_fence <= x <= hi_fence]
    outliers = tuple(x for x in xs if x < lo_fence or x > hi_fence)
    return BoxSummary(inside[0] if inside else q1, q1, med, q3,
                      inside[-1] if inside else q3, outliers)


@register
class BoxPlotTrack(Track):
    """A box plot per node, drawn along the offset axis."""

    type_id = "box-plot"
    display_name = "Box plot"
    needs_numeric = True
    multi_column = True

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        opts = super().default_options()
        opts.update({
            "thickness": 120.0,
            "source": "auto",
            "whisker_factor": 1.5,
            "zero_based": False,
            "value_min": None,
            "value_max": None,
            "box_height": 0.62,
            "box_color": None,
            "line_color": None,
            "median_color": None,
            "outlier_color": None,
            "show_outliers": True,
            "outlier_radius": 2.4,
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

    def is_summary_input(self) -> bool:
        """Whether the columns already hold a five-number summary.

        ``auto`` inspects the first five headers rather than guessing from the
        column count: five raw observations per tip is a perfectly ordinary
        dataset, and silently reading it as quartiles would give a
        wrong-but-plausible plot, the worst kind.
        """
        mode = str(self.opt("source", "auto")).lower()
        if mode in ("summary", "five-number"):
            return True
        if mode == "raw":
            return False
        cols = [str(c).strip().lower().replace(" ", "_") for c in self.data.columns]
        if len(cols) < 5:
            return False
        return all(cols[i] in _SUMMARY_NAMES[i] for i in range(5))

    def summary(self, node_id: int) -> BoxSummary | None:
        """The distribution for one node, or ``None`` when it has none usable."""
        row = self.data.rows.get(node_id)
        if not row:
            return None
        if not self.is_summary_input():
            values = [v for v in (numeric(x) for x in row) if v is not None]
            return tukey_summary(values, float(self.opt("whisker_factor", 1.5) or 1.5))
        five = [numeric(row[i]) if i < len(row) else None for i in range(5)]
        if any(v is None for v in five):
            return None
        outliers = tuple(v for v in (numeric(x) for x in row[5:]) if v is not None)
        # The file gives no ordering guarantee; sorting keeps the box drawable.
        lo, q1, med, q3, hi = sorted(float(v) for v in five)  # type: ignore[arg-type]
        return BoxSummary(lo, q1, med, q3, hi, outliers)

    def summaries(self) -> dict[int, BoxSummary]:
        out: dict[int, BoxSummary] = {}
        for nid in self.data.rows:
            s = self.summary(nid)
            if s is not None:
                out[nid] = s
        return out

    def value_axis(self, ctx: TrackContext,
                   summaries: dict[int, BoxSummary] | None = None) -> ValueAxis:
        summaries = self.summaries() if summaries is None else summaries
        values: list[float] = []
        for s in summaries.values():
            values.extend(s.spread())
        return ValueAxis.build(
            values, length=self.measure(ctx), baseline=None,
            zero_based=bool(self.opt("zero_based", False)),
            vmin=self.opt("value_min"), vmax=self.opt("value_max"))

    # --------------------------------------------------------------- draw

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        summaries = self.summaries()
        axis = self.value_axis(ctx, summaries)
        origin = ctx.offset
        if self.opt("axis", True):
            draw_value_axis(
                ctx, sink, axis, axis.ticks(int(self.opt("axis_ticks", 4) or 4)),
                size=float(self.opt("axis_size") or ctx.theme.track_title_size),
                color=ctx.theme.muted, fmt=str(self.opt("axis_format", "{:.4g}")))

        line_color = option_color(self, "line_color", ctx.theme.foreground)
        box_color = option_color(self, "box_color", ctx.theme.accent.lighten(0.45))
        median_color = option_color(self, "median_color", line_color)
        dot_color = option_color(self, "outlier_color", line_color)
        opacity = float(self.opt("opacity", 1.0) or 1.0)
        frac = min(max(float(self.opt("box_height", 0.62) or 0.62), 0.05), 1.0)

        border = self.opt("border_color")
        boxes = QuadBatch(
            ctx.projector, opacity=opacity,
            stroke=safe_color(border, line_color) if border is not None else None,
            stroke_width=float(self.opt("border_width", 0.0) or 0.0))
        dots: list[EllipseMark] = []
        show_dots = bool(self.opt("show_outliers", True))
        # One row's scene width at the middle of the band: stroke weights and
        # dot radii are pixel quantities, and this is what converts rows to px.
        row_px = max(1e-6, ctx.projector.tangential(origin + axis.length * 0.5))

        for nid, centre, extent in iter_band_rows(
                ctx, self.data, bool(self.opt("show_internal", False))):
            s = summaries.get(nid)
            if s is None:
                continue
            half = extent * frac * 0.5
            box_px = extent * frac * row_px
            spine = Paint(stroke=line_color, opacity=opacity,
                          width=max(0.8, box_px * 0.08))
            self._span(ctx, sink, spine, centre, origin + axis.offset(s.low),
                       centre, origin + axis.offset(s.high))
            for end in (s.low, s.high):
                cap = origin + axis.offset(end)
                self._span(ctx, sink, spine, centre - half * 0.5, cap,
                           centre + half * 0.5, cap)
            add_quad(boxes, centre - half, centre + half,
                     origin + axis.offset(s.q1), origin + axis.offset(s.q3),
                     box_color)
            med = origin + axis.offset(s.median)
            self._span(ctx, sink, Paint(stroke=median_color, opacity=opacity,
                                        width=max(1.4, box_px * 0.15)),
                       centre - half, med, centre + half, med)
            if show_dots and s.outliers:
                radius = min(float(self.opt("outlier_radius", 2.4) or 2.4),
                             max(0.6, box_px * 0.25))
                paint = Paint(fill=dot_color, opacity=opacity)
                for value in s.outliers:
                    x, y = ctx.projector.point(centre, origin + axis.offset(value))
                    dots.append(EllipseMark(paint=paint, cx=x, cy=y,
                                            rx=radius, ry=radius))
        boxes.flush(sink)
        for dot in dots:
            sink.add(dot)

    def _span(self, ctx: TrackContext, sink: MarkSink, paint: Paint,
              row0: float, off0: float, row1: float, off1: float) -> None:
        """One band-space segment, resampled so it curves correctly when polar."""
        pts = project_polyline(ctx.projector, [(row0, off0), (row1, off1)])
        if len(pts) >= 4:
            sink.add(PolylineMark(paint=paint, points=tuple(pts)))

    # ------------------------------------------------------------- legend

    def legend(self) -> Legend:
        """A schematic of the glyph rather than a colour key.

        Every box on the track shares one colour, so a swatch per node would
        say nothing.  What a reader needs is which mark means which statistic
        and where the whiskers were cut.
        """
        k = float(self.opt("whisker_factor", 1.5) or 1.5)
        # A legend is built without a theme, so it falls back to the same
        # neutral ink and the same wash the light theme would have produced.
        line = option_color(self, "line_color", Color(24, 24, 27))
        box = option_color(self, "box_color", Color(147, 178, 231))
        items = [
            LegendItem(label="interquartile range (Q1 to Q3)", color=box,
                       shape="square"),
            LegendItem(label="median", color=line, shape="line"),
            LegendItem(label=f"whisker: furthest point within {k:g} x IQR",
                       color=line, shape="line"),
        ]
        if self.opt("show_outliers", True):
            items.append(LegendItem(label="outlier", color=line, shape="circle"))
        return Legend(title=self.title, items=items)
