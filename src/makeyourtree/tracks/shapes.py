# SPDX-License-Identifier: MIT
"""Shared band-space drawing primitives for annotation tracks.

Three things live here because more than one track needs them and none of them
belongs to a particular track:

:data:`SHAPES`
    Named builders producing a path for a symbol centred on a band-space point.
    Symbols are a **constant size in scene units** and are oriented by the
    projector's outward vector rather than by the axes of the page, so a
    triangle points away from the tree in a rectangular layout and away from
    the centre in a circular one without the caller knowing which it is.

:class:`QuadBatch`
    The batching rule for cell-shaped tracks.  See its docstring; it is why a
    200-column heatmap over 5000 tips costs a handful of marks.

:func:`band_offset_of`
    Inverts the projector along one ray, for tracks that must draw at a node's
    own position (clade washes, symbols on branches) while still speaking band
    space.

Polygon outlines are written in a local frame ``(a, t)`` where ``a`` runs
outward -- the direction of increasing ``offset`` -- and ``t`` runs across the
band in the direction of increasing ``row``.  Both are unit half-extents, so an
outline coordinate of 1 lands ``size / 2`` from the centre.  Expressing shapes
this way is what makes them layout-agnostic: the projector supplies the frame,
the outline never changes.
"""

from __future__ import annotations

import math
from typing import Callable, Sequence

from ..layout.projector import Projector
from ..scene.marks import (Layer, MarkSink, Paint, Path, PathMark, RectsMark,
                           Segment)
from ..style.color import Color

__all__ = [
    "ShapeBuilder", "SHAPES", "OPEN_SHAPES", "shape_names", "shape_path",
    "is_open_shape", "band_offset_of", "QuadBatch",
]

ShapeBuilder = Callable[[float, float, float, Projector], "tuple[Segment, ...]"]
"""``builder(row, offset, size, projector)`` -> closed or open path segments."""

# Control-point distance that approximates a quarter circle with one cubic to
# within 0.02 % of the radius; the standard circle-to-bezier constant.
_KAPPA = 0.5522847498307936


def _frame(row: float, offset: float, size: float, projector: Projector
           ) -> tuple[float, float, float, float, float, float, float]:
    """Centre, outward unit vector, cross-band unit vector and half-size."""
    cx, cy = projector.point(row, offset)
    ux, uy = projector.outward(row)
    # Rotating the outward vector by +90 degrees in scene coordinates (y grows
    # downward) gives the direction of increasing row, which is what a shape's
    # ``t`` axis means.  In a linear layout that is straight down the page.
    return cx, cy, ux, uy, -uy, ux, size * 0.5


def _polygon(outline: Sequence[tuple[float, float]], *,
             closed: bool = True) -> ShapeBuilder:
    """Builder for a fixed outline expressed in the local ``(a, t)`` frame."""

    def build(row: float, offset: float, size: float,
              projector: Projector) -> tuple[Segment, ...]:
        cx, cy, ux, uy, tx, ty, h = _frame(row, offset, size, projector)
        p = Path()
        for i, (a, t) in enumerate(outline):
            x = cx + (a * ux + t * tx) * h
            y = cy + (a * uy + t * ty) * h
            if i == 0:
                p.move_to(x, y)
            else:
                p.line_to(x, y)
        if closed:
            p.close()
        return p.freeze()

    return build


def _radial(n: int, start_deg: float,
            radii: Sequence[float] | float = 1.0) -> list[tuple[float, float]]:
    """*n* vertices evenly spaced around a circle, alternating *radii*."""
    rs = [float(radii)] * n if isinstance(radii, (int, float)) else list(radii)
    out: list[tuple[float, float]] = []
    for k in range(n):
        ang = math.radians(start_deg + k * 360.0 / n)
        r = rs[k % len(rs)]
        out.append((r * math.cos(ang), r * math.sin(ang)))
    return out


def _circle(row: float, offset: float, size: float,
            projector: Projector) -> tuple[Segment, ...]:
    """Two half arcs rather than four beziers: exact, and both backends consume
    centre-parameterised arcs directly."""
    cx, cy = projector.point(row, offset)
    r = size * 0.5
    return (Path().move_to(cx + r, cy)
            .arc(cx, cy, r, 0.0, 180.0).arc(cx, cy, r, 180.0, 360.0)
            .close().freeze())


def _ellipse(row: float, offset: float, size: float,
             projector: Projector) -> tuple[Segment, ...]:
    """Flattened along the outward axis, so a column of them reads as a band."""
    cx, cy, ux, uy, tx, ty, h = _frame(row, offset, size, projector)
    ra, rt = h * 0.66, h
    k = _KAPPA

    def pt(a: float, t: float) -> tuple[float, float]:
        return (cx + a * ra * ux + t * rt * tx, cy + a * ra * uy + t * rt * ty)

    quarters = ((1.0, 0.0, 0.0, 1.0), (0.0, 1.0, -1.0, 0.0),
                (-1.0, 0.0, 0.0, -1.0), (0.0, -1.0, 1.0, 0.0))
    p = Path().move_to(*pt(1.0, 0.0))
    for a0, t0, a1, t1 in quarters:
        # Each control point sits one kappa-step along the tangent at its end.
        p.cubic_to(*pt(a0 + k * a1, t0 + k * t1),
                   *pt(a1 + k * a0, t1 + k * t0), *pt(a1, t1))
    return p.close().freeze()


def _rounded_rect(row: float, offset: float, size: float,
                  projector: Projector) -> tuple[Segment, ...]:
    cx, cy, ux, uy, tx, ty, h = _frame(row, offset, size, projector)
    r = 0.34

    def pt(a: float, t: float) -> tuple[float, float]:
        return (cx + (a * ux + t * tx) * h, cy + (a * uy + t * ty) * h)

    # Walk the four edges, rounding each corner with a quadratic whose control
    # point is the corner itself.
    p = Path().move_to(*pt(1.0 - r, -1.0))
    p.line_to(*pt(-1.0 + r, -1.0)).quad_to(*pt(-1.0, -1.0), *pt(-1.0, -1.0 + r))
    p.line_to(*pt(-1.0, 1.0 - r)).quad_to(*pt(-1.0, 1.0), *pt(-1.0 + r, 1.0))
    p.line_to(*pt(1.0 - r, 1.0)).quad_to(*pt(1.0, 1.0), *pt(1.0, 1.0 - r))
    p.line_to(*pt(1.0, -1.0 + r)).quad_to(*pt(1.0, -1.0), *pt(1.0 - r, -1.0))
    return p.close().freeze()


SHAPES: dict[str, ShapeBuilder] = {
    "square": _polygon([(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]),
    "circle": _circle,
    "triangle": _polygon([(1.0, 0.0), (-1.0, -0.92), (-1.0, 0.92)]),
    "diamond": _polygon([(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]),
    "star": _polygon(_radial(10, 0.0, (1.0, 0.382))),
    "hexagon": _polygon(_radial(6, 0.0)),
    "pentagon": _polygon(_radial(5, 0.0)),
    "cross": _polygon([
        (1.0, -0.34), (0.34, -0.34), (0.34, -1.0), (-0.34, -1.0),
        (-0.34, -0.34), (-1.0, -0.34), (-1.0, 0.34), (-0.34, 0.34),
        (-0.34, 1.0), (0.34, 1.0), (0.34, 0.34), (1.0, 0.34)]),
    "check": _polygon([(-0.85, 0.0), (-0.25, 0.62), (0.9, -0.72)], closed=False),
    "arrow-right": _polygon([
        (-1.0, -0.34), (0.15, -0.34), (0.15, -0.85), (1.0, 0.0),
        (0.15, 0.85), (0.15, 0.34), (-1.0, 0.34)]),
    "arrow-left": _polygon([
        (1.0, -0.34), (-0.15, -0.34), (-0.15, -0.85), (-1.0, 0.0),
        (-0.15, 0.85), (-0.15, 0.34), (1.0, 0.34)]),
    "rounded-rect": _rounded_rect,
    "ellipse": _ellipse,
    "chevron": _polygon([(-0.55, -0.85), (0.55, 0.0), (-0.55, 0.85)],
                        closed=False),
}

OPEN_SHAPES: frozenset[str] = frozenset({"check", "chevron"})
"""Shapes that are a stroked stem rather than an outline: filling them is
meaningless, so callers must give them a stroke."""


def shape_names() -> list[str]:
    return sorted(SHAPES)


def is_open_shape(name: str) -> bool:
    return name in OPEN_SHAPES


def shape_path(name: str, row: float, offset: float, size: float,
               projector: Projector) -> tuple[Segment, ...]:
    """Path for *name* centred at band-space ``(row, offset)``.

    An unknown name falls back to a square rather than raising: a track driven
    by a user-supplied table should still draw something for a mistyped shape
    code, and the loader reports the typo separately.
    """
    return SHAPES.get(name, SHAPES["square"])(row, offset, size, projector)


def band_offset_of(frame, projector: Projector, node_id: int) -> float:
    """Band-space offset of a node the layout placed in scene space.

    ``offset`` is arc length along the outward ray in every projector -- x in a
    linear layout, radius in a polar one -- so projecting the node's scene
    position onto the outward vector at its own row recovers it with no
    knowledge of the layout mode.  Tracks that reach back over the tree body
    (clade washes) or sit on a branch (node symbols) need this; nothing else
    should.
    """
    row = frame.row(node_id)
    ox, oy = projector.point(row, 0.0)
    ux, uy = projector.outward(row)
    nx, ny = frame.xy(node_id)
    return (nx - ox) * ux + (ny - oy) * uy


class QuadBatch:
    """Collects band-space quads and emits as few marks as the projection allows.

    A linear projection turns every quad into an axis-aligned rectangle, so the
    whole batch collapses into one :class:`~makeyourtree.scene.marks.RectsMark`
    carrying per-rectangle fills -- one mark for a million heatmap cells.

    A polar projection cannot: an annular sector is never axis-aligned.  There
    the batch groups quads by fill colour and concatenates their sub-paths into
    one :class:`~makeyourtree.scene.marks.PathMark` per colour.  That is why the
    colour ramps quantise -- it bounds the polar mark count by the number of
    distinct colours rather than by the number of cells.
    """

    __slots__ = ("_proj", "_coords", "_fills", "_by_color", "_stroke",
                 "_stroke_width", "_opacity")

    def __init__(self, projector: Projector, *, opacity: float = 1.0,
                 stroke: Color | None = None, stroke_width: float = 0.0) -> None:
        self._proj = projector
        self._opacity = opacity
        self._stroke = stroke if stroke_width > 0 else None
        self._stroke_width = float(stroke_width) if stroke_width > 0 else 0.0
        self._coords: list[float] = []
        self._fills: list[Color] = []
        self._by_color: dict[Color, Path] = {}

    @property
    def empty(self) -> bool:
        return not self._coords and not self._by_color

    def add(self, row0: float, row1: float, off0: float, off1: float,
            color: Color) -> None:
        """Queue the quad ``[row0, row1] x [off0, off1]`` filled with *color*.

        Corners are normalised first.  A caller that names the far corner first
        -- which is the natural way to write a bar running back from a baseline
        to a negative value -- otherwise produces ``off1 - off0 < 0``, and
        ``LinearProjector.rect`` reports that width verbatim.  A negative width
        is an error in SVG and the quad simply disappears, so a negative bar
        would silently render as nothing at all.  The polar branch is immune
        (its arcs carry the direction), which is exactly the kind of
        discrepancy that survives a test suite run in one projection only.
        """
        if row1 < row0:
            row0, row1 = row1, row0
        if off1 < off0:
            off0, off1 = off1, off0
        r = self._proj.rect(row0, row1, off0, off1)
        if r is not None:
            self._coords.extend(r)
            self._fills.append(color)
            return
        path = self._by_color.get(color)
        if path is None:
            path = self._by_color[color] = Path()
        path.segments.extend(self._proj.cell(row0, row1, off0, off1))

    def flush(self, sink: MarkSink, layer: Layer | None = None) -> int:
        """Emit the queued quads and reset.  Returns the number of marks added."""
        n = 0
        if self._coords:
            # The per-rect fill list overrides ``paint.fill``, but the paint
            # still has to look visible to backends that test it before drawing.
            paint = Paint(fill=self._fills[0], stroke=self._stroke,
                          width=self._stroke_width, opacity=self._opacity)
            sink.add(RectsMark(paint=paint, coords=tuple(self._coords),
                               fills=tuple(self._fills)), layer)
            n += 1
        for color, path in self._by_color.items():
            paint = Paint(fill=color, stroke=self._stroke,
                          width=self._stroke_width, opacity=self._opacity)
            sink.add(PathMark(paint=paint, segments=path.freeze()), layer)
            n += 1
        self._coords.clear()
        self._fills.clear()
        self._by_color.clear()
        return n
