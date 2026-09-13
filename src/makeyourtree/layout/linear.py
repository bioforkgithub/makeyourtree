# SPDX-License-Identifier: MIT
"""Rectangular and slanted layout.

Both modes share every coordinate: they differ only in how an edge is stroked.
A rectangular tree draws each edge as an elbow -- one connector spanning a
node's children plus one perpendicular segment per child -- while a slanted
tree draws one straight segment per edge.  Keeping the coordinates identical is
what lets the studio switch between them without a relayout.

The two passes
--------------
Following the central invariant of :mod:`makeyourtree.layout.params`, the cross and
along coordinates are computed independently:

* **Cross** -- one postorder over the *visible* tree assigns each tip a
  half-open band of rows (one row for a leaf, a budget from
  :func:`~makeyourtree.layout.collapse.collapse_rows` for a collapsed clade) and
  each internal node a position within its children's span, per
  :class:`~makeyourtree.layout.params.ParentRule`.  It depends only on tip order,
  so ladderizing or rotating changes rows and nothing else.
* **Along** -- one preorder accumulates drawn branch length (or level), and a
  single multiplication turns it into ``x``.  It depends only on lengths and
  depth, so switching phylogram/cladogram changes ``x`` and nothing else.

The tidy-drawing formulation -- a parent centred over the extent of its
children, subtrees occupying disjoint contiguous bands -- follows Reingold and
Tilford, "Tidier Drawings of Trees", IEEE Trans. Software Eng. 7(2):223-228,
1981, specialised to the case where the cross axis is discretised into tip
rows.  Label-space solving uses the injected
:class:`~makeyourtree.text.metrics.TextMetrics` rather than a character-count
estimate, because in a proportional font the longest string and the widest
string are usually different taxa.
"""

from __future__ import annotations

import heapq

from ..core.node import Node
from ..core.traversal import descend, postorder, preorder
from ..core.tree import Tree
from ..text.metrics import TextMetrics
from .along import (ALONG_ALIGNED, ALONG_LENGTH, ALONG_LEVEL,
                    ALONG_METADATA_KEY, NEGATIVE_METADATA_KEY,
                    count_negative_lengths)
from .collapse import STATS_METADATA_KEY, collapse_rows, depth_stats
from .frame import LayoutFrame
from .params import BranchMode, LayoutMode, LayoutParams, ParentRule
from .projector import LinearProjector

__all__ = ["LinearLayout"]

DEFAULT_LABEL_SIZE = 11.0
"""Matches :attr:`makeyourtree.style.theme.Theme.label_size`.  The ``Layout``
protocol is not handed a theme, so a caller that has themed the labels passes
the real size through ``LayoutParams.extra['label_size']``."""

MEASURE_ALL_BELOW = 2000
"""Above this many labelled tips, only the longest-by-character-count
candidates are measured.  Measuring 100 000 strings through a real font engine
costs more than the rest of the layout put together, and the result is only
used to reserve one block of width."""

MEASURE_TOP_K = 200

MIN_GUIDE_LENGTH = 2.0
"""Guides shorter than this are visual noise rather than a reading aid."""

MIN_ROW_HEIGHT = 1e-3
"""Floor so that an explicit ``height`` on a huge tree cannot produce a
zero-height scene that no view transform can recover."""


class LinearLayout:
    """Layout for :attr:`~makeyourtree.layout.params.LayoutMode.RECTANGULAR` and
    :attr:`~makeyourtree.layout.params.LayoutMode.SLANTED`."""

    __slots__ = ("mode",)

    def __init__(self, mode: LayoutMode = LayoutMode.RECTANGULAR) -> None:
        if not mode.is_linear:
            raise ValueError(f"{mode!r} is not a linear layout mode")
        self.mode = mode

    # ------------------------------------------------------------- compute

    def compute(self, tree: Tree, params: LayoutParams,
                metrics: TextMetrics) -> LayoutFrame:
        if not params.mode.is_linear:
            raise ValueError(f"LinearLayout cannot draw {params.mode!r}")
        self.mode = params.mode
        # Reading a derived property forces Tree._ensure(): depth_len, height,
        # level and n_leaves must be current before any pass below trusts them,
        # and this is the public way to say so without a gratuitous refresh().
        _ = tree.n_leaves

        frame = LayoutFrame(tree, params)
        visible = list(postorder(tree.root, visible_only=True))
        frame.allocate(visible)
        if not visible:
            self._finish_empty(frame, params)
            return frame

        rows, tips, tip_nodes, collapsed, vheight = self._assign_rows(visible, params)
        n_rows = rows[tree.root.id][2]
        row_height = self._row_height(params, n_rows)

        depth, level = self._assign_depth(tree.root, params)
        stats = {n.id: depth_stats(n) for n in collapsed}
        overhang = {n.id: max(0.0, stats[n.id][1] - n.depth_len) for n in collapsed}

        x0 = params.margin
        top_y = params.margin
        scale, body_w = self._along_scale(params, tips, depth, overhang)
        x_of = self._along_mapper(params, x0, body_w, scale, depth, level,
                                  vheight, vheight[tree.root.id])

        for n in visible:
            row, lo, hi = rows[n.id]
            frame.set_rows(n.id, row, lo, hi)
            frame.set_xy(n.id, x_of(n.id), top_y + row * row_height)

        self._emit_edges(frame, visible, params.mode)

        x_align = x0 + body_w
        max_label = self._measure_labels(frame, tip_nodes, params, metrics)

        frame.tips = tips
        frame.n_rows = n_rows
        frame.row_height = row_height
        frame.scale = scale
        frame.body_bounds = (x0, top_y, x_align, top_y + n_rows * row_height)
        frame.center = ((x0 + x_align) * 0.5, top_y + n_rows * row_height * 0.5)
        frame.tip_offset = params.tip_label_gap + max_label
        frame.projector = LinearProjector(base_x=x_align, top_y=top_y,
                                          row_height=row_height, n_rows=n_rows)
        frame.metadata.update({
            "align_x": x_align,
            "collapsed": [n.id for n in collapsed],
            "label_size": float(params.extra.get("label_size", DEFAULT_LABEL_SIZE)),
            "max_label_width": max_label,
            "depth_max": (body_w / scale) if scale > 0 else 0.0,
            ALONG_METADATA_KEY: self._along_rule(params, scale),
            STATS_METADATA_KEY: stats,
        })
        if params.align_tips and params.guide_lines:
            frame.metadata["guides"] = self._guides(
                frame, tips, x_align, params, scale, overhang)
        # Negative lengths are real data (NJ, BioNJ, least squares) that the
        # drawing cannot show; the count travels on the frame so the
        # compositor can say so, since a layout has no sink of its own.
        if params.ignore_negative_lengths:
            frame.metadata[NEGATIVE_METADATA_KEY] = count_negative_lengths(tree.root)
        return frame

    # ---------------------------------------------------------------- cross

    def _assign_rows(self, visible: list[Node], params: LayoutParams):
        """Postorder row allocation.

        Returns the row triples, the visible tip ids in row order, the tip
        nodes, the collapsed clades and the visible edge-height of every node.
        Row budgets are resolved here, before the row height is known, because
        the row height divides the total -- collapsing a clade has to make the
        remaining rows taller, not leave the drawing unchanged.
        """
        rows: dict[int, tuple[float, float, float]] = {}
        tips: list[int] = []
        tip_nodes: list[Node] = []
        collapsed: list[Node] = []
        vheight: dict[int, int] = {}
        rule = params.parent_rule
        cursor = 0.0
        for n in visible:
            kids = descend(n, True)
            if n.collapsed and n.children:
                lo = cursor
                cursor += collapse_rows(n, params)
                rows[n.id] = ((lo + cursor) * 0.5, lo, cursor)
                vheight[n.id] = 0
                tips.append(n.id)
                tip_nodes.append(n)
                collapsed.append(n)
            elif not kids:
                lo = cursor
                cursor += 1.0
                rows[n.id] = (lo + 0.5, lo, cursor)
                vheight[n.id] = 0
                tips.append(n.id)
                tip_nodes.append(n)
            else:
                lo = rows[kids[0].id][1]
                hi = rows[kids[-1].id][2]
                rows[n.id] = (_parent_row(kids, rows, rule), lo, hi)
                vheight[n.id] = 1 + max(vheight[c.id] for c in kids)
        return rows, tips, tip_nodes, collapsed, vheight

    @staticmethod
    def _row_height(params: LayoutParams, n_rows: float) -> float:
        if params.height is not None and n_rows > 0:
            return max(MIN_ROW_HEIGHT, params.height / n_rows)
        return params.row_spacing

    # ---------------------------------------------------------------- along

    @staticmethod
    def _assign_depth(root: Node, params: LayoutParams):
        """Preorder accumulation of drawn branch length and visible level.

        The root's own edge length, if the file carried one, is deliberately
        not drawn: including it would shift ``max(depth)`` and therefore the
        scale bar for a quantity that describes an edge to a parent the tree
        does not have.
        """
        depth: dict[int, float] = {root.id: 0.0}
        level: dict[int, int] = {root.id: 0}
        ignore_neg = params.ignore_negative_lengths
        floor = params.min_branch_length
        for n in preorder(root, visible_only=True):
            d = depth[n.id]
            lv = level[n.id]
            for c in descend(n, True):
                v = c.branch_length
                v = 0.0 if v is None else float(v)
                if ignore_neg and v < 0.0:
                    v = 0.0
                # The floor applies only when the user asked for one, so that
                # min_branch_length = 0 does not silently double as "clamp
                # negatives" for a user who turned that off on purpose.
                if floor > 0.0 and v < floor:
                    v = floor
                depth[c.id] = d + v
                level[c.id] = lv + 1
        return depth, level

    @staticmethod
    def _along_scale(params: LayoutParams, tips: list[int], depth: dict[int, float],
                     overhang: dict[int, float]) -> tuple[float, float]:
        """``(scale, body_width)`` in scene units per unit of branch length.

        The extent is taken over visible *tips* -- and, for a collapsed clade,
        over the far edge of its summary glyph -- so the glyph never spills
        past the body it was sized to fit inside.
        """
        if not params.branch_mode.uses_lengths:
            return (1.0, params.width)
        span = 0.0
        for tid in tips:
            d = depth[tid] + overhang.get(tid, 0.0)
            if d > span:
                span = d
        if span <= 0.0:
            # A star tree, or a topology-only file read as a phylogram: there
            # is no length to scale by.  Every node stacks at the root and the
            # body keeps its nominal width so labels and tracks still land.
            return (0.0, params.width)
        scale = float(params.x_scale) if params.x_scale is not None else params.width / span
        return (scale, span * scale)

    @staticmethod
    def _along_rule(params: LayoutParams, scale: float) -> str:
        """The along rule this pass actually realised.

        A phylogram over a file with no branch lengths cannot deliver one: the
        scale comes back as zero and every node stacks on the root, so the pass
        reports ``aligned`` rather than letting a scale bar be built from a
        scale of zero.  See :mod:`makeyourtree.layout.along`.
        """
        mode = params.branch_mode
        if mode is BranchMode.CLADOGRAM_LEVEL:
            return ALONG_LEVEL
        if mode is BranchMode.CLADOGRAM_ALIGNED:
            return ALONG_ALIGNED
        return ALONG_LENGTH if scale > 0.0 else ALONG_ALIGNED

    @staticmethod
    def _along_mapper(params: LayoutParams, x0: float, body_w: float, scale: float,
                      depth: dict[int, float], level: dict[int, int],
                      vheight: dict[int, int], root_height: int):
        mode = params.branch_mode
        if mode is BranchMode.PHYLOGRAM:
            return lambda nid: x0 + depth[nid] * scale
        if mode is BranchMode.CLADOGRAM_ALIGNED:
            if root_height <= 0:
                return lambda nid: x0 + body_w
            # Offset by the distance to the FARTHEST visible descendant tip, so
            # every tip lands flush at the far edge whatever its own depth.
            return lambda nid: x0 + body_w * (1.0 - vheight[nid] / root_height)
        max_level = max(level.values())
        if max_level <= 0:
            return lambda nid: x0
        return lambda nid: x0 + body_w * (level[nid] / max_level)

    # ---------------------------------------------------------------- edges

    @staticmethod
    def _emit_edges(frame: LayoutFrame, visible: list[Node], mode: LayoutMode) -> None:
        rectangular = mode is LayoutMode.RECTANGULAR
        for n in visible:
            kids = descend(n, True)
            if not kids:
                continue
            nx, ny = frame.xy(n.id)
            if rectangular:
                # One connector spanning the whole child fan plus one segment
                # per child: 1 + k primitives instead of 2k, which halves the
                # segment count on a 100 000-leaf tree.  It is emitted even
                # when it is degenerate, because hit-testing relies on it.
                frame.add_segment(nx, frame.y(kids[0].id), nx, frame.y(kids[-1].id))
                for c in kids:
                    cx, cy = frame.xy(c.id)
                    frame.add_segment(nx, cy, cx, cy)
            else:
                for c in kids:
                    cx, cy = frame.xy(c.id)
                    frame.add_segment(nx, ny, cx, cy)

    # --------------------------------------------------------------- labels

    @staticmethod
    def _measure_labels(frame: LayoutFrame, tip_nodes: list[Node],
                        params: LayoutParams, metrics: TextMetrics) -> float:
        """Widest tip label, caching every width it measured on the frame."""
        if not params.show_tip_labels:
            return 0.0
        size = float(params.extra.get("label_size", DEFAULT_LABEL_SIZE))
        family = params.extra.get("label_family")
        named = [n for n in tip_nodes if n.name]
        if len(named) > MEASURE_ALL_BELOW:
            named = heapq.nlargest(MEASURE_TOP_K, named, key=lambda n: len(n.name or ""))
        cap = params.max_label_width
        widest = 0.0
        widths = frame.label_widths
        for n in named:
            w = metrics.advance(n.name, size, family=family)
            if cap is not None and w > cap:
                w = cap
            widths[n.id] = w
            if w > widest:
                widest = w
        return widest

    @staticmethod
    def _guides(frame: LayoutFrame, tips: list[int], x_align: float,
                params: LayoutParams, scale: float,
                overhang: dict[int, float]) -> list[float]:
        """Flat ``x0, y0, x1, y1`` for the dotted run from each tip to the
        label column.  Geometry only: the compositor owns the dash pattern and
        the colour, both of which live on the theme.
        """
        gap = params.tip_label_gap
        out: list[float] = []
        for tid in tips:
            tx, ty = frame.xy(tid)
            start = tx + overhang.get(tid, 0.0) * scale + gap
            if x_align - start > MIN_GUIDE_LENGTH:
                out.extend((start, ty, x_align, ty))
        return out

    # ---------------------------------------------------------------- empty

    @staticmethod
    def _finish_empty(frame: LayoutFrame, params: LayoutParams) -> None:
        """A wholly hidden tree still has to yield a frame a renderer can use."""
        m = params.margin
        frame.n_rows = 0.0
        frame.row_height = params.row_spacing
        frame.scale = 1.0
        frame.body_bounds = (m, m, m + params.width, m)
        frame.center = (m + params.width * 0.5, m)
        frame.projector = LinearProjector(base_x=m + params.width, top_y=m,
                                          row_height=params.row_spacing, n_rows=0.0)


# --------------------------------------------------------------- internals


def _parent_row(kids: list[Node], rows: dict[int, tuple[float, float, float]],
                rule: ParentRule) -> float:
    """Cross coordinate of an internal node, from its children's.

    MIDPOINT depends only on the extremes and hence only on the tip span, which
    is what makes a subtree rotation a purely local update -- no ancestor
    moves.  MEAN and WEIGHTED lack that property and exist because they read
    better at wide polytomies: MEAN centres on the child count, WEIGHTED on the
    number of rows the children actually occupy.
    """
    if rule is ParentRule.MIDPOINT:
        return 0.5 * (rows[kids[0].id][0] + rows[kids[-1].id][0])
    if rule is ParentRule.MEAN:
        return sum(rows[c.id][0] for c in kids) / len(kids)
    total = 0.0
    weight = 0.0
    for c in kids:
        r, lo, hi = rows[c.id]
        w = hi - lo
        total += r * w
        weight += w
    return total / weight if weight > 0 else rows[kids[0].id][0]
