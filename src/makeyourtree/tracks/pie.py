# SPDX-License-Identifier: MIT
"""Pie and donut charts, one per node.

Each row is a set of parts of a whole -- counts, proportions, percentages --
and becomes a disc whose wedges are proportional to those parts.  The parts are
normalised by their own sum, so the caller does not have to pre-divide, and a
row that sums to zero produces nothing at all rather than an arbitrary
full-circle wedge.

Two decisions worth stating:

**Discs never rotate.**  Even in a polar layout the wedge for column *j* starts
at the same screen angle on every node.  A pie that followed the radius would
be unreadable next to its neighbours, and comparing two pies means comparing
wedge positions, so the glyph is anchored at a projected point but built in
screen space from there.

**Size scales as the square root of the value.**  When ``size_column`` names a
total, radius is ``R * sqrt(v / vmax)``, so the *area* of the disc is
proportional to the total.  Scaling the radius linearly would make a value ten
times larger look a hundred times larger, which is the classic bubble-chart
lie (Cleveland and McGill, "Graphical Perception", *JASA* 79(387), 1984).
"""

from __future__ import annotations

import math
from typing import Any, Iterator, Sequence

from ..scene.marks import MarkSink, Paint, Path, PathMark
from .bars import iter_band_rows, numeric, option_color, resolve_colors
from .base import Legend, LegendItem, Track, TrackContext, register

__all__ = ["PieChartTrack", "wedge_angles"]

_FULL_TURN = 360.0
# A single arc spanning more than a half turn is ambiguous in several path
# encodings, and a 360-degree one is degenerate (its ends coincide), so wide
# wedges are emitted as consecutive sub-arcs.
_MAX_ARC = 180.0


def wedge_angles(values: Sequence[float | None], start: float = -90.0
                 ) -> list[tuple[int, float, float]]:
    """``(column, start_deg, end_deg)`` per non-empty wedge, clockwise.

    The returned sweeps always sum to exactly one turn when any value is
    positive, because each boundary is computed from the cumulative sum rather
    than by adding up rounded per-wedge sweeps.  Missing and non-positive
    entries take no angle at all -- a gap, never a zero-width sliver.
    """
    parts = [v if (v is not None and v > 0) else 0.0 for v in values]
    total = math.fsum(parts)
    if total <= 0:
        return []
    out: list[tuple[int, float, float]] = []
    cumulative = 0.0
    a0 = start
    for i, part in enumerate(parts):
        if part <= 0:
            continue
        cumulative += part
        a1 = start + _FULL_TURN * (cumulative / total)
        out.append((i, a0, a1))
        a0 = a1
    return out


@register
class PieChartTrack(Track):
    """A pie or donut per node, either in the track band or on the tree."""

    type_id = "pie-chart"
    display_name = "Pie chart"
    needs_numeric = True
    multi_column = True

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        opts = super().default_options()
        opts.update({
            "radius": 9.0,
            "min_radius": 1.5,
            "size_column": None,
            "donut": 0.0,
            "stroke_width": 0.0,
            "stroke_color": None,
            "at_nodes": False,
            "start_angle": -90.0,
            "colors": None,
            "gap": 4.0,
            "show_internal": False,
        })
        return opts

    # -------------------------------------------------------------- shape

    @property
    def at_nodes(self) -> bool:
        return bool(self.opt("at_nodes", False))

    def measure(self, ctx: TrackContext) -> float:
        """Zero when drawing on the tree: the discs live over the branches and
        the track stack must not be pushed outward to make room for them."""
        if self.at_nodes:
            return 0.0
        return 2.0 * self._max_radius() + float(self.opt("gap", 4.0) or 0.0)

    def _max_radius(self) -> float:
        return max(0.0, float(self.opt("radius", 9.0) or 0.0))

    def size_column(self) -> int | None:
        """Index of the total-value column, resolved from a name or an index."""
        raw = self.opt("size_column")
        if raw is None:
            return None
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw if 0 <= raw < len(self.data.columns) else None
        try:
            return self.data.columns.index(str(raw))
        except ValueError:
            return None

    def wedge_columns(self) -> list[int]:
        """Every column that carries a share, i.e. all but the total column."""
        size = self.size_column()
        n = max(1, len(self.data.columns))
        return [c for c in range(n) if c != size]

    def radius_for(self, node_id: int, vmax: float) -> float:
        """Disc radius; ``sqrt`` scaled so area, not radius, tracks the total.

        A row whose total is missing gets no disc at all.  Falling back to the
        full radius would draw a maximum-sized chart for a value nobody
        supplied, which is the loudest possible way to render a gap.
        """
        base = self._max_radius()
        size = self.size_column()
        if size is None:
            return base
        v = numeric(self.data.get(node_id, size))
        if v is None or v <= 0:
            return 0.0
        if vmax <= 0:
            return base
        return max(float(self.opt("min_radius", 1.5) or 0.0),
                   base * math.sqrt(min(v, vmax) / vmax))

    # --------------------------------------------------------------- draw

    def _centres(self, ctx: TrackContext) -> Iterator[tuple[int, float, float]]:
        """``(node_id, cx, cy)`` for every node that gets a disc.

        On-tree placement is the one case where a track reads a scene position
        directly: a disc pinned to a branch has no band row to sit on, and only
        the layout frame knows where that branch ended up.
        """
        if not self.at_nodes:
            radius = self._max_radius()
            for nid, centre, _extent in iter_band_rows(
                    ctx, self.data, bool(self.opt("show_internal", False))):
                x, y = ctx.projector.point(centre, ctx.offset + radius)
                yield nid, x, y
            return
        for nid in sorted(self.data.rows):
            if ctx.frame.has(nid):
                x, y = ctx.frame.xy(nid)
                yield nid, x, y

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        columns = self.wedge_columns()
        colors = resolve_colors(self, max(1, len(self.data.columns)), ctx.theme,
                                self.data.columns)
        vmax = self._size_max()
        hole = min(max(float(self.opt("donut", 0.0) or 0.0), 0.0), 0.95)
        start = float(self.opt("start_angle", -90.0) or 0.0)
        opacity = float(self.opt("opacity", 1.0) or 1.0)
        stroke_w = float(self.opt("stroke_width", 0.0) or 0.0)
        # A hairline in the page colour separates touching wedges; it is only
        # worth drawing when the caller asked for a stroke width.
        stroke = (option_color(self, "stroke_color", ctx.theme.background)
                  if stroke_w > 0 else None)

        for nid, cx, cy in self._centres(ctx):
            radius = self.radius_for(nid, vmax)
            if radius <= 0:
                continue
            values = [numeric(self.data.get(nid, c)) for c in columns]
            for slot, a0, a1 in wedge_angles(values, start):
                paint = Paint(fill=colors[columns[slot]], stroke=stroke,
                              width=stroke_w, opacity=opacity)
                sink.add(PathMark(paint=paint, tag=nid,
                                  segments=_wedge_path(cx, cy, radius,
                                                       radius * hole, a0, a1)))

    def _size_max(self) -> float:
        size = self.size_column()
        if size is None:
            return 0.0
        values = self.data.numeric_column(size)
        return max(values) if values else 0.0

    # ------------------------------------------------------------- legend

    def legend(self) -> Legend:
        columns = self.wedge_columns()
        colors = resolve_colors(self, max(1, len(self.data.columns)), None,
                                self.data.columns)
        names = self.data.columns
        items = [LegendItem(label=names[c] if c < len(names) else f"column {c + 1}",
                            color=colors[c]) for c in columns]
        size = self.size_column()
        if size is not None:
            vmax = self._size_max()
            items.append(LegendItem(
                label=names[size] if size < len(names) else "total",
                shape="circle", value_range=(0.0, vmax)))
        return Legend(title=self.title, items=items)


def _wedge_path(cx: float, cy: float, r_out: float, r_in: float,
                a0: float, a1: float) -> tuple:
    """One wedge, as a pie slice or a donut segment, in scene coordinates."""
    steps = _arc_steps(a1 - a0)
    path = Path()
    if r_in > 0:
        path.move_to(*_polar(cx, cy, r_in, a0))
        path.line_to(*_polar(cx, cy, r_out, a0))
        _sweep(path, cx, cy, r_out, a0, a1, steps, False)
        path.line_to(*_polar(cx, cy, r_in, a1))
        _sweep(path, cx, cy, r_in, a1, a0, steps, True)
    else:
        path.move_to(cx, cy)
        path.line_to(*_polar(cx, cy, r_out, a0))
        _sweep(path, cx, cy, r_out, a0, a1, steps, False)
    return path.close().freeze()


def _sweep(path: Path, cx: float, cy: float, r: float, a0: float, a1: float,
           steps: int, ccw: bool) -> None:
    for i in range(steps):
        b0 = a0 + (a1 - a0) * (i / steps)
        b1 = a0 + (a1 - a0) * ((i + 1) / steps)
        path.arc(cx, cy, r, b0, b1, ccw)


def _arc_steps(sweep: float) -> int:
    return max(1, int(math.ceil(abs(sweep) / _MAX_ARC)))


def _polar(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))
