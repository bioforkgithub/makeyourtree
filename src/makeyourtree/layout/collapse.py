# SPDX-License-Identifier: MIT
"""Collapsed-clade row accounting and summary-glyph geometry.

A collapsed clade is drawn as one summary shape instead of its subtree.  Two
questions have to be answered, and they are deliberately kept apart because
they belong to different passes of the layout:

1. **How many tip rows does it consume?**  This feeds the cross-coordinate
   pass, and it must be answered *before* the row height is known -- otherwise
   collapsing a clade would not actually make the rest of the tree bigger,
   which is the whole point of collapsing.
2. **What shape summarises it?**  This needs the along coordinate and the tip
   depth statistics of the hidden subtree.

Everything here is expressed in **band space** -- ``(row, along)`` pairs, never
scene coordinates -- so the polar layout reuses it verbatim: a linear caller
reads the second coordinate as a scene ``x``, a polar caller reads it as a
radius, and the shape comes out as a triangle in one and an annular wedge in
the other with no separate implementation.

The row-budget ladders (fixed / sqrt / log / proportional) and the
triangle-trapezoid-bar vocabulary are the standard summary devices for
dendrograms; see e.g. Munzner, *Visualization Analysis and Design* (2014),
ch. 13 on aggregation, and the tidy-drawing conventions of Reingold and
Tilford, "Tidier Drawings of Trees", IEEE TSE 7(2), 1981.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..core.node import Node
from ..scene.marks import Path, Segment
from .along import along_is_length
from .params import CollapseShape, LayoutParams

if TYPE_CHECKING:  # pragma: no cover
    from .frame import LayoutFrame

__all__ = ["collapse_rows", "depth_stats", "collapse_outline",
           "STATS_METADATA_KEY"]

STATS_METADATA_KEY = "collapse_depth_stats"
"""``LayoutFrame.metadata`` key under which a layout may cache
``{node_id: (d_min, d_max, d_mean)}``.  :func:`collapse_outline` reads it so
the glyph and the layout's own extent calculation can never disagree, and
falls back to recomputing when the key is absent."""

_INSET_ROWS = 0.15
"""Band-space inset applied to each side of the glyph's base so that two
adjacent collapsed clades read as two shapes rather than one blob."""


def collapse_rows(node: Node, params: LayoutParams) -> float:
    """Tip rows consumed by *node* when it is drawn collapsed.

    The policy itself lives on :class:`~makeyourtree.layout.params.LayoutParams` so
    that every layout mode -- and the studio's preview of the setting -- asks
    exactly one question and gets exactly one answer.  Requires ``n_leaves`` to
    be current, i.e. ``Tree.refresh()`` to have run since the last edit.
    """
    return params.rows_for_collapsed(node.n_leaves)


def depth_stats(node: Node) -> tuple[float, float, float]:
    """``(d_min, d_max, d_mean)`` root-to-tip lengths of the leaves under *node*.

    These shape the summary glyph: a clade whose tips all sit at the same depth
    deserves a flat-based triangle, one with a ragged edge deserves a trapezoid
    that shows the spread.  Iterative, because a collapsed clade may itself be
    a 100 000-leaf caterpillar.

    Depths are absolute (measured from the tree root) so they are directly
    comparable with ``Node.depth_len``; the walk below re-accumulates the
    relative part from raw edge lengths rather than trusting ``depth_len``
    caches inside a subtree that no layout pass has visited.  Hidden
    descendants are skipped, matching what the layout would have drawn.

    A node with no visible descendants reports its own depth three times,
    which degenerates the glyph to a zero-extent shape rather than raising.
    """
    base = node.depth_len
    d_min = math.inf
    d_max = -math.inf
    total = 0.0
    count = 0
    stack: list[tuple[Node, float]] = [(node, 0.0)]
    while stack:
        n, d = stack.pop()
        kids = [c for c in n.children if not c.hidden]
        if not kids:
            if d < d_min:
                d_min = d
            if d > d_max:
                d_max = d
            total += d
            count += 1
            continue
        for c in kids:
            stack.append((c, d + c.edge_length(0.0)))
    if count == 0:
        return (base, base, base)
    return (base + d_min, base + d_max, base + total / count)


def collapse_outline(node: Node, frame: "LayoutFrame",
                     params: LayoutParams) -> tuple[Segment, ...]:
    """Summary shape for collapsed *node*, in band space.

    The returned path segments carry ``(row, along)`` pairs in place of the
    usual ``(x, y)``: ``row`` is the band-space tip row and ``along`` is the
    layout's along coordinate -- scene ``x`` for a linear frame, radius for a
    polar one.  Callers project them; nothing here knows about the plane, which
    is what lets one implementation serve both families.

    The apex sits at the node's own position rather than its parent's, so the
    stem branch stays visible and the glyph reads as hanging off it.

    Which depth statistic the outer edge uses depends on the shape:
    :attr:`~makeyourtree.layout.params.CollapseShape.TRIANGLE` uses the mean tip
    depth (the classic textbook triangle -- representative, but half the
    clade's tips would have reached further),
    :attr:`~makeyourtree.layout.params.CollapseShape.TRAPEZOID` shows the min and
    max explicitly and is the honest default when tip depths vary, and
    :attr:`~makeyourtree.layout.params.CollapseShape.BAR` is a plain rectangle out
    to the maximum.  In cladogram modes no depth is meaningful, so every shape
    runs out to the far edge of the tree body.
    """
    row_lo, row_hi = frame.row_span(node.id)
    apex_row = frame.row(node.id)
    apex = _along(frame, node.id)
    inset = min(_INSET_ROWS, 0.25 * max(0.0, row_hi - row_lo))
    lo = row_lo + inset
    hi = row_hi - inset
    a_min, a_max, a_mean = _outer_along(node, frame, params, apex)

    p = Path()
    shape = params.collapse_shape
    if shape is CollapseShape.BAR:
        p.move_to(lo, apex).line_to(lo, a_max).line_to(hi, a_max).line_to(hi, apex)
    elif shape is CollapseShape.TRAPEZOID:
        (p.move_to(apex_row, apex)
          .line_to(lo, a_min).line_to(lo, a_max)
          .line_to(hi, a_max).line_to(hi, a_min))
    else:
        p.move_to(apex_row, apex).line_to(lo, a_mean).line_to(hi, a_mean)
    return p.close().freeze()


# --------------------------------------------------------------- internals


def _along(frame: "LayoutFrame", node_id: int) -> float:
    """The along coordinate of a node: radius in polar frames, x in linear ones."""
    if frame.mode.is_polar:
        return frame.radius(node_id)
    return frame.x(node_id)


def _far_along(frame: "LayoutFrame") -> float:
    """Along coordinate of the far edge of the tree body."""
    if frame.mode.is_polar:
        return frame.max_radius
    return frame.body_bounds[2]


def _outer_along(node: Node, frame: "LayoutFrame", params: LayoutParams,
                 apex: float) -> tuple[float, float, float]:
    """Along coordinates of the glyph's min, max and mean outer edges."""
    # What the user asked for is not always what the layout delivered: a
    # RADIAL fan lays its along axis out topologically whatever the branch mode
    # says, and sizing a glyph from tip depths at its sentinel scale of 1.0
    # yields a wedge a fraction of a pixel wide.  Ask what was realised.
    if not along_is_length(frame, params):
        far = max(_far_along(frame), apex)
        return (far, far, far)
    cache = frame.metadata.get(STATS_METADATA_KEY)
    stats = cache.get(node.id) if cache else None
    if stats is None:
        stats = depth_stats(node)
    base = node.depth_len
    scale = frame.scale
    return tuple(apex + max(0.0, d - base) * scale for d in stats)  # type: ignore[return-value]
