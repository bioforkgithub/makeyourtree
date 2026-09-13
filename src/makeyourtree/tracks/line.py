# SPDX-License-Identifier: MIT
"""A miniature line or area chart per tip, one point per column.

The columns are the x axis -- column *j* sits at ``j / (n - 1)`` of the track's
thickness -- and the values are the y axis, mapped across the rows the tip
occupies.  Column order is therefore meaningful here: these are a series, not a
set of independent measurements.

Sharing the y range
-------------------
``y_range = "track"`` (the default) puts every row on one scale, so the charts
may be compared with each other: a row that sits low really is lower.
``y_range = "row"`` normalises each row to its own extremes, which shows the
*shape* of each series at the cost of any cross-row comparison.  The choice
changes what the picture means, so it is an explicit option rather than a
heuristic, and the legend records which one is in force.

Missing values break the line instead of pulling it to zero: a run of
consecutive present values becomes one polyline, and a gap in the middle of a
series produces two.

Everything is built in band space and resampled before projection, because a
straight segment between two band-space points is a spiral once a polar
projector has had it -- see :func:`makeyourtree.tracks.bars.project_polyline`.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..scene.marks import (LinesMark, MarkSink, Paint, PolygonMark,
                           PolylineMark, RectsMark)
from ..style.color import Color
from .bars import iter_band_rows, numeric, option_color, project_polyline
from .base import Legend, LegendItem, Track, TrackContext, register

__all__ = ["LineChartTrack"]


@register
class LineChartTrack(Track):
    """A sparkline per node: line, optional filled area, optional zero rule."""

    type_id = "line-chart"
    display_name = "Line chart"
    needs_numeric = True
    multi_column = True

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        opts = super().default_options()
        opts.update({
            "thickness": 70.0,
            "y_range": "track",
            "value_min": None,
            "value_max": None,
            "chart_height": 0.8,
            "color": None,
            "line_width": 1.2,
            "area": False,
            "area_opacity": 0.3,
            "zero_line": True,
            "show_dots": False,
            "dot_radius": 1.6,
            "show_internal": False,
        })
        return opts

    # -------------------------------------------------------------- shape

    def measure(self, ctx: TrackContext) -> float:
        return max(0.0, float(self.opt("thickness", 70.0)))

    def _n_columns(self) -> int:
        return max(1, len(self.data.columns))

    def _per_row(self) -> bool:
        return str(self.opt("y_range", "track")).lower() in ("row", "per-row", "local")

    def y_range(self, node_id: int | None = None) -> tuple[float, float]:
        """The value domain in force for *node_id* (or for the whole track)."""
        if node_id is None or not self._per_row():
            values = self.data.numeric_column(0)
            for c in range(1, self._n_columns()):
                values.extend(self.data.numeric_column(c))
        else:
            row = self.data.rows.get(node_id, ())
            values = [v for v in (numeric(x) for x in row) if v is not None]
        lo = min(values) if values else 0.0
        hi = max(values) if values else 1.0
        vmin, vmax = self.opt("value_min"), self.opt("value_max")
        if vmin is not None:
            lo = float(vmin)
        if vmax is not None:
            hi = float(vmax)
        if hi <= lo:
            # A flat series still has to be drawable; centre it in the band.
            lo, hi = lo - 0.5, lo + 0.5
        return lo, hi

    def _column_offset(self, ctx: TrackContext, index: int) -> float:
        n = self._n_columns()
        length = self.measure(ctx)
        if n < 2:
            return ctx.offset + length * 0.5
        return ctx.offset + length * index / (n - 1)

    @staticmethod
    def _row_of(value: float, lo: float, hi: float, centre: float,
                half: float) -> float:
        """Rows grow the way the page reads, so a larger value takes a smaller row."""
        t = (value - lo) / (hi - lo)
        return centre + half * (1.0 - 2.0 * t)

    # --------------------------------------------------------------- draw

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        color = option_color(self, "color", ctx.theme.accent)
        opacity = float(self.opt("opacity", 1.0) or 1.0)
        width = max(0.2, float(self.opt("line_width", 1.2) or 1.2))
        stroke = Paint(stroke=color, width=width, opacity=opacity)
        fill_alpha = min(max(float(self.opt("area_opacity", 0.3) or 0.0), 0.0), 1.0)
        area_paint = Paint(fill=color.with_alpha(fill_alpha), opacity=opacity)
        want_area = bool(self.opt("area", False))
        frac = min(max(float(self.opt("chart_height", 0.8) or 0.8), 0.05), 1.0)
        global_range = self.y_range(None)
        zero_coords: list[float] = []
        dots: list[float] = []
        n = self._n_columns()

        for nid, centre, extent in iter_band_rows(
                ctx, self.data, bool(self.opt("show_internal", False))):
            lo, hi = self.y_range(nid) if self._per_row() else global_range
            half = extent * frac * 0.5
            runs = self._runs(ctx, nid, n, lo, hi, centre, half)
            for run in runs:
                if want_area and len(run) >= 2:
                    sink.add(PolygonMark(paint=area_paint, tag=nid, points=tuple(
                        project_polyline(ctx.projector,
                                         self._close_to_baseline(run, lo, hi,
                                                                 centre, half)))))
                if len(run) >= 2:
                    sink.add(PolylineMark(paint=stroke, tag=nid, points=tuple(
                        project_polyline(ctx.projector, run))))
                if self.opt("show_dots", False):
                    for point in run:
                        dots.extend(ctx.projector.point(*point))
            if self.opt("zero_line", True) and lo <= 0.0 <= hi and runs:
                row = self._row_of(0.0, lo, hi, centre, half)
                # A constant row across varying offsets is radial, so straight
                # in both projections -- one batched mark serves every layout.
                zero_coords.extend(ctx.projector.point(row, ctx.offset))
                zero_coords.extend(
                    ctx.projector.point(row, ctx.offset + self.measure(ctx)))

        if zero_coords:
            sink.add(LinesMark(paint=Paint(stroke=ctx.theme.guide_color, width=0.6,
                                           dash=(2.0, 2.0)),
                               coords=tuple(zero_coords)))
        if dots:
            radius = max(0.4, float(self.opt("dot_radius", 1.6) or 1.6))
            self._emit_dots(sink, dots, radius, Paint(fill=color, opacity=opacity))

    def _runs(self, ctx: TrackContext, node_id: int, n: int, lo: float, hi: float,
              centre: float, half: float) -> list[list[tuple[float, float]]]:
        """Band-space points, split at every missing value."""
        row = self.data.rows.get(node_id, ())
        runs: list[list[tuple[float, float]]] = []
        current: list[tuple[float, float]] = []
        for c in range(n):
            v = numeric(row[c]) if c < len(row) else None
            if v is None:
                if current:
                    runs.append(current)
                    current = []
                continue
            current.append((self._row_of(v, lo, hi, centre, half),
                            self._column_offset(ctx, c)))
        if current:
            runs.append(current)
        return runs

    def _close_to_baseline(self, run: Sequence[tuple[float, float]], lo: float,
                           hi: float, centre: float,
                           half: float) -> list[tuple[float, float]]:
        """The run plus a return along the baseline, ready to fill.

        The baseline is zero when zero is on the axis and the low end of the
        axis otherwise, so a fill never implies an origin the data has not got.
        """
        base = 0.0 if lo <= 0.0 <= hi else lo
        row = self._row_of(base, lo, hi, centre, half)
        return list(run) + [(row, run[-1][1]), (row, run[0][1])]

    def _emit_dots(self, sink: MarkSink, coords: Sequence[float], radius: float,
                   paint: Paint) -> None:
        """Dots as tiny squares in one batched mark; at this size the shape is
        indistinguishable and a per-point ellipse mark is not affordable."""
        flat: list[float] = []
        for i in range(0, len(coords) - 1, 2):
            flat.extend((coords[i] - radius, coords[i + 1] - radius,
                         radius * 2, radius * 2))
        sink.add(RectsMark(paint=paint, coords=tuple(flat)))

    # ------------------------------------------------------------- legend

    def legend(self) -> Legend:
        lo, hi = self.y_range(None)
        color = option_color(self, "color", Color(37, 99, 235))
        scope = "per row" if self._per_row() else "shared across rows"
        items = [LegendItem(label=f"{self.title or 'series'} ({scope})",
                            color=color, shape="line", value_range=(lo, hi))]
        if self.opt("area", False):
            items.append(LegendItem(
                label="filled to baseline",
                color=color.with_alpha(float(self.opt("area_opacity", 0.3) or 0.3)),
                shape="square"))
        return Legend(title=self.title, items=items, kind="scale")
