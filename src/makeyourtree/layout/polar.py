# SPDX-License-Identifier: MIT
"""Circular and radial layouts: the polar half of the layout engine.

Both modes here are the polar image of the linear layout.  The cross
coordinate is an ANGLE derived only from the order of the visible tips, and the
along coordinate is a RADIUS derived only from branch length or topological
depth -- exactly the split described in :mod:`makeyourtree.layout.params`.  Every
formula below is the linear one with ``y -> angle`` and ``x -> radius``.

Two distinct products are produced, and keeping them distinct matters because
they promise different things (Bachmaier & Brandes, *Drawing Phylogenetic
Trees*, ISAAC 2005, put the trade-off exactly this way: circular spreads the
labels perfectly and distorts lengths, radial preserves lengths and distorts
label spacing):

``CIRCULAR``
    Fan phylogram.  Tips are equally spaced on angle; radius is cumulative
    branch length.  Tip spacing is perfect; an arc connector is a connector,
    not data, and its drawn length means nothing.
``RADIAL``
    Circular cladogram.  Same angles; radius comes from topology so that every
    tip lands on the outer ring and the labels form a clean circle.  Branch
    lengths are discarded, so ``scale`` stays 1.0 and the compositor must not
    draw a scale bar.

Edge geometry uses the standard two-primitive decomposition: one arc per
internal node, at that node's radius, spanning its children's angles, plus one
radial spoke per child.  That is ``1 + k`` primitives per internal node instead
of ``2k``, which is what keeps a 100 000-tip fan affordable.

Angles are never normalised into ``[0, 360)`` during the passes.  A clade
straddling the seam would otherwise get its bisector computed on the wrong half
of the circle.  Working in row space and converting affinely at the very end
makes the wrap-around question disappear.
"""

from __future__ import annotations

import math

from ..core.node import Node
from ..core.traversal import descend, postorder, preorder
from ..core.tree import Tree
from ..text.metrics import TextMetrics
from .along import (ALONG_LENGTH, ALONG_METADATA_KEY, NEGATIVE_METADATA_KEY,
                    count_negative_lengths)
from .collapse import STATS_METADATA_KEY, collapse_rows, depth_stats
from .frame import LayoutFrame
from .linear import MIN_GUIDE_LENGTH
from .params import BranchMode, LayoutMode, LayoutParams, ParentRule
from .projector import PolarProjector

__all__ = ["PolarLayout", "assign_rows", "drawn_length", "refresh_stats",
           "DEFAULT_LABEL_SIZE"]


DEFAULT_LABEL_SIZE = 11.0
"""Point size assumed for tip labels when the caller does not say otherwise.

Matches :class:`makeyourtree.scene.marks.TextStyle`'s default so the space the
layout reserves is the space the compositor paints into.  Override through
``params.extra['label_font_size']``.
"""

_DEGENERATE = 1e-12


def drawn_length(node: Node, params: LayoutParams) -> float:
    """Branch length as the drawing should use it.

    The data is never touched: negatives are clamped for the picture only, and
    ``min_branch_length`` floors the drawn value so zero-length edges keep a
    clickable extent.
    """
    bl = node.branch_length
    v = 0.0 if bl is None else float(bl)
    if v < 0.0 and params.ignore_negative_lengths:
        v = 0.0
    if v < params.min_branch_length:
        v = params.min_branch_length
    return v


def refresh_stats(tree: Tree) -> int:
    """Make sure the derived caches a layout reads are current.

    Reading ``Tree.n_leaves`` runs ``Tree.refresh`` when the tree is stale and
    costs nothing when it is not.  Collapse row budgets and clade depth
    statistics both read those caches, and a layout cannot assume its caller
    refreshed first.  Returns the leaf count so the call reads as a query.
    """
    return tree.n_leaves


def assign_rows(root: Node, params: LayoutParams,
                frame: LayoutFrame) -> tuple[list[int], float]:
    """The cross-axis pass, shared by the polar and the unrooted layouts.

    One visible postorder: each visible tip takes the next block of rows -- one
    row for a leaf, ``collapse_rows`` rows for a collapsed clade -- and each
    internal node takes the row its ``parent_rule`` dictates plus the union of
    its children's spans.  Because a collapsed clade simply consumes more rows,
    nothing downstream needs a special case for it.

    Returns ``(tip_ids_in_row_order, total_rows)``.
    """
    cursor = 0.0
    tips: list[int] = []
    for n in postorder(root, visible_only=True):
        kids = descend(n, True)
        if not kids:
            k = float(collapse_rows(n, params)) if n.collapsed else 1.0
            lo, hi = cursor, cursor + k
            frame.set_rows(n.id, 0.5 * (lo + hi), lo, hi)
            cursor = hi
            tips.append(n.id)
        else:
            lo = frame.row_span(kids[0].id)[0]
            hi = frame.row_span(kids[-1].id)[1]
            row = _parent_row(frame, kids, params.parent_rule, lo, hi)
            frame.set_rows(n.id, row, lo, hi)
    return tips, cursor


def _parent_row(frame: LayoutFrame, kids: list[Node], rule: ParentRule,
                lo: float, hi: float) -> float:
    """Cross coordinate of an internal node under *rule*.

    The three rules agree on binary trees.  MIDPOINT depends only on the outer
    children, so it is invariant under any reordering inside the subtree; that
    invariance is what makes interactive rotation cheap, hence the default.
    """
    if rule is ParentRule.MIDPOINT:
        return 0.5 * (frame.row(kids[0].id) + frame.row(kids[-1].id))
    if rule is ParentRule.MEAN:
        return sum(frame.row(c.id) for c in kids) / len(kids)
    # WEIGHTED: weight by visible tip count, which is exactly the row span.
    total = 0.0
    acc = 0.0
    for c in kids:
        c_lo, c_hi = frame.row_span(c.id)
        w = c_hi - c_lo
        total += w
        acc += w * frame.row(c.id)
    if total <= 0.0:
        return 0.5 * (lo + hi)
    return acc / total


def _outer_radius(params: LayoutParams, n_rows: float) -> float:
    """Outer radius of the fan, honouring both budgets.

    ``params.width`` is the along-axis budget and in polar mode the along axis
    IS the radius.  The cross budget -- ``params.height`` when given, else
    ``n_rows * row_spacing`` -- is an arc length at the tip circle, so it
    implies a minimum radius of ``cross / arc_radians``.  Taking the larger of
    the two lets a big fan grow rather than crushing rows below a pixel, the
    same choice the linear layout makes on its cross axis.
    """
    r = max(1e-6, float(params.width))
    span = abs(params.arc_radians)
    if span > 1e-9 and n_rows > 0:
        cross = (params.height if params.height is not None and params.height > 0
                 else n_rows * params.row_spacing)
        r = max(r, cross / span)
    return r


class PolarLayout:
    """Fan phylogram (``CIRCULAR``) and circular cladogram (``RADIAL``)."""

    mode: LayoutMode = LayoutMode.CIRCULAR

    def __init__(self, mode: LayoutMode = LayoutMode.CIRCULAR) -> None:
        if not mode.is_polar:
            raise ValueError(f"{mode!r} is not a polar layout mode")
        self.mode = mode

    def compute(self, tree: Tree, params: LayoutParams,
                metrics: TextMetrics) -> LayoutFrame:
        if not params.mode.is_polar:
            raise ValueError(f"PolarLayout cannot draw {params.mode!r}")
        self.mode = params.mode

        refresh_stats(tree)

        frame = LayoutFrame(tree, params)
        nodes = list(preorder(tree.root, visible_only=True))
        frame.allocate(nodes)
        if not nodes:
            frame.projector = PolarProjector(0.0, 0.0, 0.0, params.start_angle,
                                             params.arc, 0.0, params.direction)
            return frame

        tips, n_rows = assign_rows(tree.root, params, frame)
        frame.tips = tips
        frame.n_rows = n_rows

        depth, level, height = self._along_stats(nodes, params)
        label_w = self._measure_labels(tree, tips, params, metrics, frame)
        tip_offset = self._tip_offset(params, label_w)

        outer = _outer_radius(params, n_rows)
        inner = min(max(params.inner_radius, 0.0), 0.95) * outer
        radius, scale, along = self._radii(tree, nodes, tips, params, outer,
                                           inner, depth, level, height)
        cx = cy = params.margin + outer + tip_offset

        proj = PolarProjector(cx, cy, outer, params.start_angle, params.arc,
                              n_rows, params.direction)
        angle = {n.id: proj.angle_of(frame.row(n.id)) for n in nodes}
        for n in nodes:
            frame.set_polar(n.id, angle[n.id], radius[n.id], cx, cy)

        self._edges(nodes, frame, angle, radius, cx, cy)
        self._root_stub(tree.root, frame, params, angle, radius, cx, cy, scale)

        stats = self._collapse_stats(tree, tips)
        frame.projector = proj
        frame.center = (cx, cy)
        frame.max_radius = outer
        frame.body_bounds = (cx - outer, cy - outer, cx + outer, cy + outer)
        frame.tip_offset = tip_offset
        frame.scale = scale
        frame.row_height = proj.tangential(0.0)
        frame.metadata.update({
            "inner_radius": inner,
            "outer_radius": outer,
            ALONG_METADATA_KEY: along,
            # The along axis starts at the inner circle, not at the centre: a
            # tick ladder measured from (cx, cy) puts every ring one hole
            # radius too far out.  ``depth_max`` is the along span in TREE
            # units, matching what the linear pass publishes, so the scale bar
            # clamps itself to the tree in either family.
            "base_radius": inner,
            "depth_max": ((outer - inner) / scale
                          if along == ALONG_LENGTH and scale > 0.0 else 0.0),
            "rotate_labels": params.rotate_labels,
            "label_font_size": float(params.extra.get("label_font_size",
                                                      DEFAULT_LABEL_SIZE)),
            STATS_METADATA_KEY: stats,
        })
        if params.align_tips and params.guide_lines:
            frame.metadata["guides"] = self._guides(
                tree, tips, params, angle, radius, stats, outer, cx, cy,
                scale, along)
        # Negative lengths are real data (NJ, BioNJ, least squares) that the
        # drawing cannot show; the count travels on the frame so the
        # compositor can say so, since a layout has no sink of its own.
        if params.ignore_negative_lengths:
            frame.metadata[NEGATIVE_METADATA_KEY] = count_negative_lengths(tree.root)
        return frame

    # ----------------------------------------------------------- along axis

    def _along_stats(self, nodes: list[Node], params: LayoutParams
                     ) -> tuple[dict[int, float], dict[int, int], dict[int, int]]:
        """Cumulative drawn depth, topological level and visible height.

        Derived over the VISIBLE tree rather than read off the ``Node`` caches:
        a collapsed clade is a tip here, so its height is zero and its depth is
        its own, which is what the radius rules below need.  *nodes* is in
        preorder, so one forward sweep gives the top-down quantities and one
        reverse sweep gives the bottom-up one.
        """
        root = nodes[0]
        depth = {root.id: 0.0}
        level = {root.id: 0}
        for n in nodes:
            d = depth[n.id]
            lv = level[n.id]
            for c in descend(n, True):
                depth[c.id] = d + drawn_length(c, params)
                level[c.id] = lv + 1
        height: dict[int, int] = {}
        for n in reversed(nodes):
            kids = descend(n, True)
            height[n.id] = (1 + max(height[c.id] for c in kids)) if kids else 0
        return depth, level, height

    def _radii(self, tree: Tree, nodes: list[Node], tips: list[int],
               params: LayoutParams, outer: float, inner: float,
               depth: dict[int, float], level: dict[int, int],
               height: dict[int, int]) -> tuple[dict[int, float], float, str]:
        """Radius per node, the units-per-length scale, and which rule won.

        ``RADIAL`` always takes the tip-aligned topological rule: its entire
        contract is that the tips form a ring, and honouring a level-based or
        length-based radius there would break it.  Cladogram radii are not
        proportional to anything, so ``scale`` stays 1.0 and the compositor can
        tell that a scale bar would be a lie.
        """
        band = outer - inner
        along = "aligned"
        if params.mode is not LayoutMode.RADIAL:
            if params.branch_mode is BranchMode.PHYLOGRAM:
                along = "length"
            elif params.branch_mode is BranchMode.CLADOGRAM_LEVEL:
                along = "level"

        if along == "length":
            span = max((depth[t] for t in tips), default=0.0)
            if span > 0.0:
                scale = band / span
                return ({n.id: inner + depth[n.id] * scale for n in nodes},
                        scale, "length")
            # No usable lengths at all: fall through to the topological rule
            # rather than stacking every node on the inner circle.
            along = "aligned"

        if along == "level":
            top = max(level.values()) or 1
            return ({n.id: inner + band * (level[n.id] / top) for n in nodes},
                    1.0, "level")

        top_h = height[tree.root.id]
        if top_h <= 0:
            return ({n.id: outer for n in nodes}, 1.0, "aligned")
        return ({n.id: inner + band * (1.0 - height[n.id] / top_h) for n in nodes},
                1.0, "aligned")

    # ---------------------------------------------------------------- edges

    def _edges(self, nodes: list[Node], frame: LayoutFrame,
               angle: dict[int, float], radius: dict[int, float],
               cx: float, cy: float) -> None:
        """One arc connector per internal node plus one radial spoke per child."""
        for n in nodes:
            kids = descend(n, True)
            if not kids:
                continue
            rn = radius[n.id]
            a0 = angle[kids[0].id]
            a1 = angle[kids[-1].id]
            if abs(a1 - a0) > _DEGENERATE:
                # a0 and a1 are un-normalised, so their difference carries the
                # sweep and the arc can never take the long way round.
                frame.add_arc(cx, cy, rn, a0, a1)
            for c in kids:
                a = math.radians(angle[c.id])
                ca, sa = math.cos(a), math.sin(a)
                rc = radius[c.id]
                frame.add_segment(cx + rn * ca, cy + rn * sa,
                                  cx + rc * ca, cy + rc * sa)

    def _root_stub(self, root: Node, frame: LayoutFrame, params: LayoutParams,
                   angle: dict[int, float], radius: dict[int, float],
                   cx: float, cy: float, scale: float) -> None:
        """Draw the root's own edge inward, clipped to the central hole.

        Without this a rooted fan with a root branch simply starts at the inner
        circle and the root edge is invisible; clipping keeps it from crossing
        the centre and reappearing on the far side.
        """
        r_root = radius[root.id]
        if r_root <= _DEGENERATE or root.branch_length is None:
            return
        stub = min(drawn_length(root, params) * scale, r_root)
        if stub <= _DEGENERATE:
            return
        a = math.radians(angle[root.id])
        ca, sa = math.cos(a), math.sin(a)
        frame.add_segment(cx + (r_root - stub) * ca, cy + (r_root - stub) * sa,
                          cx + r_root * ca, cy + r_root * sa)

    # --------------------------------------------------------------- labels

    def _measure_labels(self, tree: Tree, tips: list[int], params: LayoutParams,
                        metrics: TextMetrics, frame: LayoutFrame) -> float:
        """Widest tip label, measured once through *metrics*, cached on the frame.

        A tip label in a fan is rotated onto its own radius, so its ADVANCE --
        not its line height -- is what it costs in RADIAL space.  An unrotated
        label costs no more than that, so the one budget covers both cases.
        """
        if not params.show_tip_labels:
            return 0.0
        size = float(params.extra.get("label_font_size", DEFAULT_LABEL_SIZE))
        cap = params.max_label_width
        widest = 0.0
        for tid in tips:
            node = tree.by_id(tid)
            name = node.name if node is not None else None
            if not name:
                continue
            w = metrics.advance(name, size)
            if cap is not None and w > cap:
                w = cap
            frame.label_widths[tid] = w
            if w > widest:
                widest = w
        return widest

    def _guides(self, tree: Tree, tips: list[int], params: LayoutParams,
                angle: dict[int, float], radius: dict[int, float],
                stats: dict[int, tuple[float, float, float]], outer: float,
                cx: float, cy: float, scale: float,
                along: str) -> list[float]:
        """Flat ``x0, y0, x1, y1`` for the radial leader from each tip to the ring.

        The polar image of :meth:`makeyourtree.layout.linear.LinearLayout._guides`,
        and deliberately the same contract: the same flat quadruple form, the
        same start rule (past the tip's own branch end, past a collapsed
        clade's summary glyph, plus ``tip_label_gap``) and the same minimum
        length.  Emitting scene coordinates rather than band-space radii is
        what lets the compositor consume both families with one code path.

        Aligning tips does NOT move them -- a tip keeps the radius its branch
        length earned, exactly as in the linear pass -- so the gap between the
        branch end and the aligned label ring is real, and the leader is what
        bridges it.
        """
        gap = params.tip_label_gap
        out: list[float] = []
        for tid in tips:
            start = radius[tid]
            stat = stats.get(tid)
            if stat is not None:
                # A collapsed clade is drawn as a glyph reaching past its own
                # node; a leader starting at the node would run through it.
                if along == ALONG_LENGTH:
                    node = tree.by_id(tid)
                    base = node.depth_len if node is not None else 0.0
                    start += max(0.0, stat[1] - base) * scale
                else:
                    start = max(start, outer)
            start += gap
            if outer - start <= MIN_GUIDE_LENGTH:
                continue
            a = math.radians(angle[tid])
            ca, sa = math.cos(a), math.sin(a)
            out.extend((cx + start * ca, cy + start * sa,
                        cx + outer * ca, cy + outer * sa))
        return out

    def _tip_offset(self, params: LayoutParams, label_w: float) -> float:
        """Band-space offset at which tracks may begin: past the longest label."""
        if label_w <= 0.0:
            return params.tip_label_gap
        return params.tip_label_gap + label_w + params.tip_label_gap

    def _collapse_stats(self, tree: Tree, tips: list[int]
                        ) -> dict[int, tuple[float, float, float]]:
        """Leaf-depth statistics of every collapsed clade, cached on the frame.

        :func:`makeyourtree.layout.collapse.collapse_outline` reads this key so the
        summary glyph and the layout's own extent calculation are computed from
        one set of numbers instead of two.
        """
        out: dict[int, tuple[float, float, float]] = {}
        for tid in tips:
            node = tree.by_id(tid)
            if node is not None and node.collapsed:
                out[tid] = depth_stats(node)
        return out
