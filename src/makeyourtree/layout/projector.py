# SPDX-License-Identifier: MIT
"""Band projection: the single abstraction that makes tracks layout-agnostic.

Annotation tracks are written once, against a two-dimensional **band space**:

``row``
    Continuous tip-row coordinate.  Visible tip *i* occupies ``[i, i+1]`` and
    its centre is ``i + 0.5``.  A collapsed clade occupies as many rows as the
    layout gave it, so tracks never need to know it was collapsed.
``offset``
    Distance outward from the track baseline -- the far edge of the tree body,
    past the tip labels.  Grows away from the tree in every layout mode.

A :class:`Projector` maps band space into scene coordinates.  In a linear
layout that mapping is an affine transform and a cell is a rectangle; in a
polar layout it is a polar transform and the same cell is an annular sector.
Because tracks only ever speak band space, **every track works in every layout
mode without a single conditional**, and adding a layout mode does not touch
track code.

This is the contract every track in :mod:`makeyourtree.tracks` codes against.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..scene.marks import Anchor, Path, Segment

__all__ = ["Projector", "LinearProjector", "PolarProjector", "TextPlacement"]


@dataclass(frozen=True, slots=True)
class TextPlacement:
    """Where and how to draw one string in band space."""

    x: float
    y: float
    rotation: float
    """Degrees clockwise about (``x``, ``y``)."""
    anchor: Anchor
    flipped: bool = False
    """True when the text was rotated 180 degrees to stay right-way-up."""


@runtime_checkable
class Projector(Protocol):
    """Maps band space ``(row, offset)`` to scene coordinates."""

    n_rows: float
    """Total tip rows.  Row coordinates outside ``[0, n_rows]`` are legal but
    will fall outside the tree in polar mode."""
    is_polar: bool

    def point(self, row: float, offset: float) -> tuple[float, float]:
        """Scene position of a single band-space point."""
        ...

    def cell(self, row0: float, row1: float, off0: float, off1: float) -> tuple[Segment, ...]:
        """Closed path for the band-space quad ``[row0, row1] x [off0, off1]``."""
        ...

    def rect(self, row0: float, row1: float, off0: float,
             off1: float) -> tuple[float, float, float, float] | None:
        """Axis-aligned ``(x, y, w, h)`` for the same quad, or ``None`` when the
        projection is not axis-aligned.  Lets linear layouts take the batched
        rectangle fast path; polar callers fall back to :meth:`cell`."""
        ...

    def tangential(self, offset: float) -> float:
        """Scene-space width of ONE row measured across the band at *offset*.

        Constant in linear mode; grows with radius in polar mode.  Tracks use
        it to decide whether a symbol or a piece of text still fits.
        """
        ...

    def outward(self, row: float) -> tuple[float, float]:
        """Unit vector pointing away from the tree at *row*."""
        ...

    def text(self, row: float, offset: float, align: Anchor = Anchor.START,
             rotate: bool = True) -> TextPlacement:
        """Placement for a label sitting at *offset* on *row*."""
        ...

    def extent(self, off0: float, off1: float) -> tuple[float, float, float, float]:
        """Scene bounding box ``(x0, y0, x1, y1)`` of the full band slab."""
        ...


# ---------------------------------------------------------------- linear


@dataclass(slots=True)
class LinearProjector:
    """Band space for rectangular and slanted layouts.

    ``row`` maps to ``y``, ``offset`` maps to ``x``.  Rows run top to bottom,
    offsets run left to right, matching the reading direction of the tree.
    """

    base_x: float
    """Scene x at ``offset = 0``: the far edge of the tree body plus labels."""
    top_y: float
    """Scene y at ``row = 0``."""
    row_height: float
    n_rows: float
    is_polar: bool = False

    def point(self, row: float, offset: float) -> tuple[float, float]:
        return (self.base_x + offset, self.top_y + row * self.row_height)

    def rect(self, row0: float, row1: float, off0: float,
             off1: float) -> tuple[float, float, float, float]:
        y0 = self.top_y + row0 * self.row_height
        y1 = self.top_y + row1 * self.row_height
        return (self.base_x + off0, y0, off1 - off0, y1 - y0)

    def cell(self, row0: float, row1: float, off0: float, off1: float) -> tuple[Segment, ...]:
        x, y, w, h = self.rect(row0, row1, off0, off1)
        return (Path().move_to(x, y).line_to(x + w, y)
                .line_to(x + w, y + h).line_to(x, y + h).close().freeze())

    def tangential(self, offset: float) -> float:
        return self.row_height

    def outward(self, row: float) -> tuple[float, float]:
        return (1.0, 0.0)

    def text(self, row: float, offset: float, align: Anchor = Anchor.START,
             rotate: bool = True) -> TextPlacement:
        x, y = self.point(row, offset)
        return TextPlacement(x, y, 0.0, align, False)

    def extent(self, off0: float, off1: float) -> tuple[float, float, float, float]:
        return (self.base_x + off0, self.top_y,
                self.base_x + off1, self.top_y + self.n_rows * self.row_height)


# ----------------------------------------------------------------- polar


@dataclass(slots=True)
class PolarProjector:
    """Band space for circular and radial layouts.

    ``row`` maps to angle, ``offset`` maps to radius.  Angles are in degrees
    and measured in scene space, where y grows downward -- so with
    ``direction = +1`` increasing rows sweep clockwise on screen, which is what
    a reader expects when the seam is at the top.
    """

    cx: float
    cy: float
    base_r: float
    """Scene radius at ``offset = 0``."""
    start_angle: float
    """Degrees at ``row = 0``."""
    arc: float
    """Total sweep in degrees across all rows."""
    n_rows: float
    direction: int = 1
    is_polar: bool = True

    # ------------------------------------------------------------- helpers

    def angle_of(self, row: float) -> float:
        """Degrees at band-space *row*."""
        if self.n_rows <= 0:
            return self.start_angle
        return self.start_angle + self.direction * (row / self.n_rows) * self.arc

    def radius_of(self, offset: float) -> float:
        return self.base_r + offset

    # --------------------------------------------------------------- proto

    def point(self, row: float, offset: float) -> tuple[float, float]:
        a = math.radians(self.angle_of(row))
        r = self.radius_of(offset)
        return (self.cx + r * math.cos(a), self.cy + r * math.sin(a))

    def rect(self, row0: float, row1: float, off0: float, off1: float) -> None:
        return None  # an annular sector is never axis-aligned

    def cell(self, row0: float, row1: float, off0: float, off1: float) -> tuple[Segment, ...]:
        a0 = self.angle_of(row0)
        a1 = self.angle_of(row1)
        r0 = self.radius_of(off0)
        r1 = self.radius_of(off1)
        ccw = a1 < a0
        p = Path()
        p.move_to(*self._pt(a0, r0))
        p.arc(self.cx, self.cy, r0, a0, a1, ccw)
        p.line_to(*self._pt(a1, r1))
        p.arc(self.cx, self.cy, r1, a1, a0, not ccw)
        p.close()
        return p.freeze()

    def _pt(self, angle_deg: float, r: float) -> tuple[float, float]:
        a = math.radians(angle_deg)
        return (self.cx + r * math.cos(a), self.cy + r * math.sin(a))

    def tangential(self, offset: float) -> float:
        if self.n_rows <= 0:
            return 0.0
        per_row = math.radians(abs(self.arc) / self.n_rows)
        return per_row * self.radius_of(offset)

    def outward(self, row: float) -> tuple[float, float]:
        a = math.radians(self.angle_of(row))
        return (math.cos(a), math.sin(a))

    def text(self, row: float, offset: float, align: Anchor = Anchor.START,
             rotate: bool = True) -> TextPlacement:
        ang = self.angle_of(row)
        x, y = self.point(row, offset)
        if not rotate:
            return TextPlacement(x, y, 0.0, align, False)
        # Normalise to (-180, 180] so we can test which half of the fan we are on.
        norm = (ang + 180.0) % 360.0 - 180.0
        flip = norm > 90.0 or norm < -90.0
        if flip:
            return TextPlacement(x, y, norm + 180.0, _mirror(align), True)
        return TextPlacement(x, y, norm, align, False)

    def extent(self, off0: float, off1: float) -> tuple[float, float, float, float]:
        r = self.radius_of(max(off0, off1))
        # A band that spans a full turn touches the bounding circle on every
        # side; a partial fan is bounded more tightly, but the circle is a
        # correct and cheap over-estimate that never clips content.
        return (self.cx - r, self.cy - r, self.cx + r, self.cy + r)


def _mirror(a: Anchor) -> Anchor:
    if a is Anchor.START:
        return Anchor.END
    if a is Anchor.END:
        return Anchor.START
    return Anchor.MIDDLE
