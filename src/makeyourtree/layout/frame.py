# SPDX-License-Identifier: MIT
"""The layout result: one shared coordinate space for renderers and tracks.

A :class:`LayoutFrame` is what every layout produces and what every consumer --
the compositor, the annotation tracks, hit-testing, the exporters -- reads.
Nothing downstream re-derives geometry, so the canvas, the SVG export and the
click target can never disagree about where a branch is.

Storage shape
-------------
Node positions live in **parallel arrays indexed by row-major slot**, not in a
dict of objects, and edges are stored as flat coordinate lists.  A 100 000-leaf
tree has ~200 000 nodes and ~400 000 line segments; one Python object per edge
would cost more than the layout itself.  :meth:`LayoutFrame.coord` rehydrates a
:class:`NodeCoord` when a caller genuinely wants one (inspector panels, tests),
and the batched renderers consume the flat arrays directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator, Protocol

from ..core.node import Node
from ..core.tree import Tree
from .params import LayoutMode, LayoutParams
from .projector import Projector

__all__ = ["NodeCoord", "LayoutFrame", "Layout", "Bounds"]

Bounds = tuple[float, float, float, float]
"""``(x0, y0, x1, y1)`` in scene coordinates."""


@dataclass(frozen=True, slots=True)
class NodeCoord:
    """Position of one node, in whichever terms its layout speaks.

    ``x``/``y`` are always populated -- they are what gets drawn.  ``angle`` and
    ``radius`` are populated only by polar layouts, where they are the primary
    quantities and ``x``/``y`` are derived from them.
    """

    node_id: int
    x: float
    y: float
    angle: float = 0.0
    """Degrees, polar layouts only."""
    radius: float = 0.0
    """Polar layouts only."""
    row: float = 0.0
    """Band-space centre row.  Meaningful for tips and, under the midpoint
    parent rule, for internal nodes too."""
    row_lo: float = 0.0
    row_hi: float = 0.0
    """Half-open band-space row span occupied by this node's visible subtree."""
    is_tip: bool = False


class LayoutFrame:
    """Everything the renderers need, computed once per layout pass."""

    __slots__ = (
        "tree", "params", "mode", "projector",
        "_x", "_y", "_angle", "_radius", "_row", "_row_lo", "_row_hi", "_slot",
        "tips", "n_rows", "row_height", "scale",
        "straight", "arcs", "curves",
        "body_bounds", "center", "max_radius",
        "tip_offset", "label_widths", "metadata",
    )

    def __init__(self, tree: Tree, params: LayoutParams) -> None:
        self.tree = tree
        self.params = params
        self.mode: LayoutMode = params.mode
        self.projector: Projector | None = None

        n = len(tree.nodes)
        self._slot: dict[int, int] = {}
        self._x = [0.0] * n
        self._y = [0.0] * n
        self._angle = [0.0] * n
        self._radius = [0.0] * n
        self._row = [0.0] * n
        self._row_lo = [0.0] * n
        self._row_hi = [0.0] * n

        self.tips: list[int] = []
        """Visible tip node ids, in row order."""
        self.n_rows: float = 0.0
        self.row_height: float = params.row_spacing
        self.scale: float = 1.0
        """Scene units per unit of branch length.  1.0 in cladogram modes."""

        # Edge geometry, flat and batchable.
        self.straight: list[float] = []
        """Flat ``x0, y0, x1, y1`` per segment."""
        self.arcs: list[tuple[float, float, float, float, float]] = []
        """``(cx, cy, r, a0_deg, a1_deg)`` per arc connector."""
        self.curves: list[tuple[int, tuple]] = []
        """``(node_id, path_segments)`` for smoothed or custom branch shapes."""

        self.body_bounds: Bounds = (0.0, 0.0, 0.0, 0.0)
        """Extent of the drawn tree, excluding labels, tracks and legend."""
        self.center: tuple[float, float] = (0.0, 0.0)
        self.max_radius: float = 0.0
        self.tip_offset: float = 0.0
        """Band-space offset at which tracks may begin: past the longest label."""
        self.label_widths: dict[int, float] = {}
        self.metadata: dict = {}

    # ------------------------------------------------------------- writing
    # Called by layout implementations only.

    def allocate(self, nodes: list[Node]) -> None:
        """Assign array slots.  Must be called before any position is written."""
        self._slot = {n.id: i for i, n in enumerate(nodes)}
        size = len(nodes)
        for name in ("_x", "_y", "_angle", "_radius", "_row", "_row_lo", "_row_hi"):
            setattr(self, name, [0.0] * size)

    def set_xy(self, node_id: int, x: float, y: float) -> None:
        i = self._slot[node_id]
        self._x[i] = x
        self._y[i] = y

    def set_polar(self, node_id: int, angle: float, radius: float,
                  cx: float, cy: float) -> None:
        """Write polar primaries and the Cartesian position they imply."""
        i = self._slot[node_id]
        self._angle[i] = angle
        self._radius[i] = radius
        a = math.radians(angle)
        self._x[i] = cx + radius * math.cos(a)
        self._y[i] = cy + radius * math.sin(a)

    def set_rows(self, node_id: int, row: float, lo: float, hi: float) -> None:
        i = self._slot[node_id]
        self._row[i] = row
        self._row_lo[i] = lo
        self._row_hi[i] = hi

    def add_segment(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.straight.extend((x0, y0, x1, y1))

    def add_arc(self, cx: float, cy: float, r: float, a0: float, a1: float) -> None:
        self.arcs.append((cx, cy, r, a0, a1))

    # ------------------------------------------------------------- reading

    def has(self, node_id: int) -> bool:
        return node_id in self._slot

    def x(self, node_id: int) -> float:
        return self._x[self._slot[node_id]]

    def y(self, node_id: int) -> float:
        return self._y[self._slot[node_id]]

    def xy(self, node_id: int) -> tuple[float, float]:
        i = self._slot[node_id]
        return (self._x[i], self._y[i])

    def angle(self, node_id: int) -> float:
        return self._angle[self._slot[node_id]]

    def radius(self, node_id: int) -> float:
        return self._radius[self._slot[node_id]]

    def row(self, node_id: int) -> float:
        return self._row[self._slot[node_id]]

    def row_span(self, node_id: int) -> tuple[float, float]:
        i = self._slot[node_id]
        return (self._row_lo[i], self._row_hi[i])

    def coord(self, node_id: int) -> NodeCoord:
        """Rehydrate a full coordinate record.  Convenience, not a hot path."""
        i = self._slot[node_id]
        return NodeCoord(
            node_id=node_id, x=self._x[i], y=self._y[i],
            angle=self._angle[i], radius=self._radius[i],
            row=self._row[i], row_lo=self._row_lo[i], row_hi=self._row_hi[i],
            is_tip=node_id in self._tip_set(),
        )

    def _tip_set(self) -> set[int]:
        cached = self.metadata.get("_tip_set")
        if cached is None or len(cached) != len(self.tips):
            cached = set(self.tips)
            self.metadata["_tip_set"] = cached
        return cached

    def iter_coords(self) -> Iterator[NodeCoord]:
        for node_id in self._slot:
            yield self.coord(node_id)

    @property
    def n_segments(self) -> int:
        return len(self.straight) // 4

    # ------------------------------------------------------------ geometry

    def tip_row(self, node_id: int) -> tuple[float, float]:
        """Band-space rows occupied by a visible tip.  One row for a real leaf,
        several for a collapsed clade."""
        return self.row_span(node_id)

    def content_bounds(self, include_tracks: float = 0.0) -> Bounds:
        """Body bounds grown by a band-space offset, for sizing the page."""
        if self.projector is None or include_tracks <= 0:
            return self.body_bounds
        tx0, ty0, tx1, ty1 = self.projector.extent(0.0, include_tracks)
        bx0, by0, bx1, by1 = self.body_bounds
        return (min(bx0, tx0), min(by0, ty0), max(bx1, tx1), max(by1, ty1))

    def hit(self, x: float, y: float, tolerance: float = 6.0) -> int | None:
        """Node whose position is nearest to (*x*, *y*) within *tolerance*.

        Deliberately a point query against node positions rather than a stroke
        query against branches: users click at labels and junctions, and a
        nearest-node answer matches that intent while staying O(rows) after the
        row-band narrowing below.
        """
        best_id: int | None = None
        best_d2 = tolerance * tolerance
        for node_id, i in self._slot.items():
            dx = self._x[i] - x
            if dx * dx > best_d2:
                continue
            dy = self._y[i] - y
            d2 = dx * dx + dy * dy
            if d2 <= best_d2:
                best_d2 = d2
                best_id = node_id
        return best_id

    def __repr__(self) -> str:
        return (f"<LayoutFrame {self.mode.value} tips={len(self.tips)} "
                f"rows={self.n_rows:g} segments={self.n_segments} arcs={len(self.arcs)}>")


class Layout(Protocol):
    """What every layout implementation provides.

    Implementations live in :mod:`makeyourtree.layout.linear`,
    :mod:`makeyourtree.layout.polar` and :mod:`makeyourtree.layout.unrooted`, and are
    reached through :func:`makeyourtree.layout.compute_layout`.
    """

    mode: LayoutMode

    def compute(self, tree: Tree, params: LayoutParams,
                metrics: "TextMetricsLike") -> LayoutFrame:
        """Lay *tree* out and return a fully populated frame.

        Implementations must, in order:

        1. assign band-space rows to visible tips (cross coordinate),
        2. assign the along coordinate from branch length or depth,
        3. write positions, edge geometry and ``tips``,
        4. build and attach a :class:`~makeyourtree.layout.projector.Projector`,
        5. set ``body_bounds``, ``n_rows``, ``row_height``, ``scale`` and
           ``tip_offset``.

        The layout must never mutate *tree*.
        """
        ...


class TextMetricsLike(Protocol):
    """Minimal font measurement interface; see :mod:`makeyourtree.text.metrics`."""

    def advance(self, text: str, size: float, *, bold: bool = False,
                italic: bool = False, family: str | None = None) -> float: ...

    def line_height(self, size: float, family: str | None = None) -> float: ...
