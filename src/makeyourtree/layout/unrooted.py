# SPDX-License-Identifier: MIT
"""Unrooted layouts: Felsenstein's equal-angle and equal-daylight.

An unrooted drawing makes one promise that no other layout in MakeYourTree makes:
**every edge is drawn at exactly its own length**.  Both algorithms here keep
that promise -- equal-angle by construction, equal-daylight because every step
it takes is a rotation, and a rotation is an isometry.

equal-angle (Felsenstein, *Inferring Phylogenies*, 2004, pp. 578-580; the
formulation used here is Bachmaier & Brandes, ISAAC 2005)
    Give each subtree an infinite wedge with its apex at the parent's position
    and an angular width proportional to the subtree's share of the tips, then
    put the child on the wedge's bisector at its true branch length.  Sibling
    wedges are angle-disjoint and each subtree stays inside its own wedge, so
    the drawing is planar by construction.  One preorder pass, O(V).

equal-daylight (Felsenstein, pp. 582-584)
    Equal-angle's weakness is that wedge width tracks tip COUNT, so a
    two-taxon clade of very long branches gets a sliver and its branches nearly
    overlap.  Equal-daylight repairs it: at each internal node, measure the
    angle each component subtends as seen from that node, then rigidly rotate
    the components so the leftover "daylight" is shared equally between them.
    It offers no planarity guarantee -- it is a heuristic with a pass cap and a
    tolerance -- but it keeps every length exact.

The subtle part is measuring the angle a component subtends.  Angles are
circular, so a min/max over raw ``atan2`` values silently breaks the moment a
component straddles the branch cut at +/- pi.  Every hull below is therefore
measured RELATIVE to the direction of the component's own incident edge and
wrapped into ``(-pi, pi]``, which is correct whenever a component subtends less
than pi from the node -- always true for an equal-angle initialisation, and
checked explicitly so a pathological case bails out instead of producing
nonsense.

Band space is a fiction in this mode: there is no left-to-right tip order in the
drawing.  Rows are still assigned in tree order and a linear projector is still
attached, past the bounding box, so that annotation tracks degrade to a plain
column beside the figure rather than failing.  ``frame.metadata`` says so.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Mapping

import numpy as np

from ..core.node import Node
from ..core.traversal import descend, preorder
from ..core.tree import Tree
from ..text.metrics import TextMetrics
from .along import (ALONG_ALIGNED, ALONG_LENGTH, ALONG_METADATA_KEY,
                    NEGATIVE_METADATA_KEY, count_negative_lengths)
from .frame import LayoutFrame
from .params import BranchMode, LayoutMode, LayoutParams, UnrootedMethod
from .polar import (DEFAULT_LABEL_SIZE, assign_rows, collapse_rows,
                    drawn_length, refresh_stats)
from .projector import LinearProjector

__all__ = ["UnrootedLayout", "equal_angle", "equal_daylight", "daylight_gaps",
           "Skeleton", "build_skeleton"]

TWO_PI = 2.0 * math.pi
_COINCIDENT2 = 1e-24
"""Squared distance below which a point is treated as sitting on the node, and
so as carrying no direction at all."""

_MAX_SUBTENSE = math.pi - 1e-9
"""A component subtending this much or more breaks the angular-hull method, so
equalisation is skipped at that node rather than guessed at."""


@dataclass(slots=True)
class Skeleton:
    """The tree as an unrooted drawing sees it, re-rooted at a drawing start.

    Indices are a DFS preorder from ``start``, which makes every subtree a
    CONTIGUOUS index range ``[i, i + size[i])``.  That is what lets
    equal-daylight rotate a whole component with two numpy slice operations
    instead of materialising a member set per node.
    """

    ids: list[int] = field(default_factory=list)
    """Node id at each index."""
    index: dict[int, int] = field(default_factory=dict)
    parent: list[int] = field(default_factory=list)
    """Index of the parent in the re-rooted orientation; -1 at the start node."""
    children: list[list[int]] = field(default_factory=list)
    length: list[float] = field(default_factory=list)
    """Drawn length of the edge from ``parent[i]`` to ``i``."""
    size: list[int] = field(default_factory=list)
    weight: list[float] = field(default_factory=list)
    """Tip weight of the subtree: one per leaf, ``collapse_rows`` per collapsed clade."""
    total: float = 0.0

    def __len__(self) -> int:
        return len(self.ids)

    @property
    def degree(self) -> list[int]:
        return [len(self.children[i]) + (0 if self.parent[i] < 0 else 1)
                for i in range(len(self.ids))]


def _edge_length(node: Node, params: LayoutParams) -> float:
    """Length to draw for the edge above *node*.

    With branch lengths switched off every edge becomes unit length, which is
    exactly the classic radial cladogram: equal-angle on pure topology.
    """
    if params.branch_mode is BranchMode.PHYLOGRAM:
        return drawn_length(node, params)
    return 1.0


def build_skeleton(tree: Tree, params: LayoutParams) -> Skeleton:
    """Re-root the visible tree at a drawing start and index it for the layout.

    A rooted binary tree has a degree-2 root, and drawing it as-is puts both
    halves on exactly opposite bisectors: a bilaterally split picture that is a
    rooted drawing in disguise.  Starting the walk at the heavier of the root's
    two children suppresses that -- the old root becomes an ordinary degree-2
    node lying exactly on the merged edge, so the two lengths still read as one
    straight branch of their sum, and the whole circle of wedges is now shared
    out from the new start.
    """
    skel = Skeleton()
    visible = list(preorder(tree.root, visible_only=True))
    if not visible:
        return skel

    adjacency: dict[int, list[tuple[Node, float]]] = {n.id: [] for n in visible}
    for n in visible:
        for c in descend(n, True):
            ln = _edge_length(c, params)
            adjacency[n.id].append((c, ln))
            adjacency[c.id].append((n, ln))

    root_kids = descend(tree.root, True)
    start = tree.root
    if len(root_kids) == 2:
        start = max(root_kids, key=lambda c: c.n_leaves)

    # Iterative DFS: children are pushed reversed so they pop in order, which
    # keeps sibling wedges in the tree's own left-to-right order.
    order: list[Node] = []
    parent: list[int] = []
    length: list[float] = []
    index: dict[int, int] = {}
    stack: list[tuple[Node, int, float]] = [(start, -1, 0.0)]
    while stack:
        node, par, ln = stack.pop()
        i = len(order)
        index[node.id] = i
        order.append(node)
        parent.append(par)
        length.append(ln)
        neighbours = adjacency[node.id]
        for nb, nl in reversed(neighbours):
            if par >= 0 and nb.id == order[par].id:
                continue
            stack.append((nb, i, nl))

    n = len(order)
    children: list[list[int]] = [[] for _ in range(n)]
    for i in range(1, n):
        children[parent[i]].append(i)

    size = [1] * n
    weight = [0.0] * n
    for i in range(n - 1, -1, -1):
        if children[i]:
            for c in children[i]:
                size[i] += size[c]
                weight[i] += weight[c]
        else:
            node = order[i]
            weight[i] = float(collapse_rows(node, params)) if node.collapsed else 1.0

    skel.ids = [node.id for node in order]
    skel.index = index
    skel.parent = parent
    skel.children = children
    skel.length = length
    skel.size = size
    skel.weight = weight
    skel.total = weight[0] if n else 0.0
    return skel


# ------------------------------------------------------------- equal angle


def _equal_angle_positions(skel: Skeleton, phi0: float
                           ) -> tuple[np.ndarray, np.ndarray]:
    """Felsenstein's equal-angle pass over an indexed skeleton.

    Index order IS preorder, so a single forward sweep suffices: a child is
    always visited after its parent has a position.  The wedge width uses the
    GLOBAL tip total, which makes the children's widths sum to their parent's
    automatically and needs no parent state.
    """
    n = len(skel)
    xs = np.zeros(n, dtype=float)
    ys = np.zeros(n, dtype=float)
    if n == 0:
        return xs, ys
    total = skel.total if skel.total > 0 else 1.0
    eta = [0.0] * n
    eta[0] = phi0
    for i in range(n):
        cursor = eta[i]
        xi = xs[i]
        yi = ys[i]
        for c in skel.children[i]:
            omega = TWO_PI * skel.weight[c] / total
            eta[c] = cursor
            theta = cursor + 0.5 * omega
            xs[c] = xi + skel.length[c] * math.cos(theta)
            ys[c] = yi + skel.length[c] * math.sin(theta)
            cursor += omega
    return xs, ys


def equal_angle(tree: Tree, params: LayoutParams) -> dict[int, tuple[float, float]]:
    """Equal-angle positions, in branch-length units, keyed by node id.

    The drawing start sits at the origin and ``params.start_angle`` rotates the
    whole figure rigidly.  Positions are NOT fitted to the page: the caller
    applies a single uniform scale, because scaling x and y independently would
    destroy the length proportionality that is the point of the drawing.
    """
    skel = build_skeleton(tree, params)
    xs, ys = _equal_angle_positions(skel, params.start_radians)
    return {nid: (float(xs[i]), float(ys[i])) for i, nid in enumerate(skel.ids)}


# ---------------------------------------------------------- equal daylight


def _wrap_pi(a: float) -> float:
    return (a + math.pi) % TWO_PI - math.pi


def _spans_for(skel: Skeleton, i: int) -> list[tuple[int, list[tuple[int, int]]]]:
    """The components of ``T - i``, as ``(neighbour_index, index_ranges)``.

    The parent-side component is returned FIRST and is the one that stays
    pinned: rotating it instead would cost O(V) per node and turn the pass into
    O(V^2) even on a balanced tree, and leaving nothing pinned lets the whole
    drawing drift a little on every pass.
    """
    n = len(skel)
    comps: list[tuple[int, list[tuple[int, int]]]] = []
    lo, hi = i, i + skel.size[i]
    if skel.parent[i] >= 0:
        comps.append((skel.parent[i], [(0, lo), (hi, n)]))
    for c in skel.children[i]:
        comps.append((c, [(c, c + skel.size[c])]))
    return comps


def _hull(xs: np.ndarray, ys: np.ndarray, vx: float, vy: float, d0: float,
          spans: list[tuple[int, int]]) -> tuple[float, float] | None:
    """Angular hull of a component as seen from ``(vx, vy)``.

    Measured relative to *d0*, the direction of the component's own incident
    edge, and wrapped into ``(-pi, pi]``.  That is what makes the result correct
    across the branch cut; a raw min/max of ``atan2`` is not.
    """
    lo = 0.0
    hi = 0.0
    seen = False
    for a, b in spans:
        if b <= a:
            continue
        dx = xs[a:b] - vx
        dy = ys[a:b] - vy
        keep = (dx * dx + dy * dy) > _COINCIDENT2
        if not keep.any():
            continue
        rel = np.arctan2(dy[keep], dx[keep]) - d0
        rel = (rel + math.pi) % TWO_PI - math.pi
        lo = min(lo, float(rel.min()))
        hi = max(hi, float(rel.max()))
        seen = True
    if not seen:
        return None
    return (d0 + lo, d0 + hi)


def _arcs_at(skel: Skeleton, xs: np.ndarray, ys: np.ndarray,
             i: int) -> list[list] | None:
    """Hulls of every component around node *i*, unrolled around the anchor.

    Returns ``[[lo, hi, spans], ...]`` with the pinned component first and the
    rest sorted by where they start, each shifted by whole turns so that the
    starts increase monotonically from the anchor.  Working on an unrolled copy
    of the circle is what makes the wrap-around gap fall out of the arithmetic
    instead of needing a special case.
    """
    comps = _spans_for(skel, i)
    if len(comps) < 2:
        return None
    vx = float(xs[i])
    vy = float(ys[i])
    arcs: list[list] = []
    for nb, spans in comps:
        d0 = math.atan2(float(ys[nb]) - vy, float(xs[nb]) - vx)
        hull = _hull(xs, ys, vx, vy, d0, spans)
        if hull is None:
            return None
        lo, hi = hull
        if hi - lo >= _MAX_SUBTENSE:
            return None
        arcs.append([lo, hi, spans])
    base = arcs[0][1]
    rest = []
    for lo, hi, spans in arcs[1:]:
        shifted = base + (lo - base) % TWO_PI
        rest.append([shifted, shifted + (hi - lo), spans])
    rest.sort(key=lambda a: a[0])
    return [arcs[0]] + rest


def _rotate(xs: np.ndarray, ys: np.ndarray, vx: float, vy: float, delta: float,
            spans: list[tuple[int, int]]) -> None:
    """Rigidly rotate the points in *spans* about ``(vx, vy)``.

    Branch lengths are untouched: a rotation is an isometry, which is the whole
    reason equal-daylight is allowed to move things at all.
    """
    c = math.cos(delta)
    s = math.sin(delta)
    for a, b in spans:
        if b <= a:
            continue
        dx = xs[a:b] - vx
        dy = ys[a:b] - vy
        xs[a:b] = vx + dx * c - dy * s
        ys[a:b] = vy + dx * s + dy * c


def _equalize_at(skel: Skeleton, xs: np.ndarray, ys: np.ndarray, i: int,
                 damping: float) -> float:
    """Share the daylight at node *i* equally.  Returns the largest rotation."""
    arcs = _arcs_at(skel, xs, ys, i)
    if arcs is None:
        return 0.0
    d = len(arcs)
    covered = sum(a[1] - a[0] for a in arcs)
    daylight = TWO_PI - covered
    if daylight <= 0.0:
        return 0.0
    gap = daylight / d
    vx = float(xs[i])
    vy = float(ys[i])
    cursor = arcs[0][1] + gap
    worst = 0.0
    for k in range(1, d):
        lo, hi, spans = arcs[k]
        delta = (cursor - lo) * damping
        if abs(delta) > 1e-12:
            _rotate(xs, ys, vx, vy, delta, spans)
        cursor = lo + delta + (hi - lo) + gap
        worst = max(worst, abs(delta))
    return worst


def _centroid(skel: Skeleton) -> int:
    """Index of the tree centroid: the node whose largest component is smallest.

    Felsenstein sweeps outward from the middle of the tree because a rotation
    made near a leaf is undone by the next rotation nearer the centre; starting
    central converges in noticeably fewer passes.
    """
    best = 0
    best_max = math.inf
    for i in range(len(skel)):
        worst = skel.total - skel.weight[i] if skel.parent[i] >= 0 else 0.0
        for c in skel.children[i]:
            worst = max(worst, skel.weight[c])
        if worst < best_max:
            best_max = worst
            best = i
    return best


def _visit_order(skel: Skeleton) -> list[int]:
    """Internal nodes, breadth-first from the centroid.

    Leaves have nothing to equalise, and a degree-2 node would only split its
    daylight into two equal halves without improving anything, so both are
    skipped -- equal-daylight is defined on the unrooted topology.
    """
    n = len(skel)
    if n == 0:
        return []
    adjacency: list[list[int]] = [[] for _ in range(n)]
    for i in range(1, n):
        adjacency[i].append(skel.parent[i])
        adjacency[skel.parent[i]].append(i)
    seen = [False] * n
    start = _centroid(skel)
    seen[start] = True
    queue = deque([start])
    order: list[int] = []
    while queue:
        i = queue.popleft()
        if len(adjacency[i]) >= 3:
            order.append(i)
        for j in adjacency[i]:
            if not seen[j]:
                seen[j] = True
                queue.append(j)
    return order


def _daylight_positions(skel: Skeleton, params: LayoutParams, iterations: int,
                        tolerance: float) -> tuple[np.ndarray, np.ndarray, dict]:
    xs, ys = _equal_angle_positions(skel, params.start_radians)
    order = _visit_order(skel)
    damping = float(params.extra.get("daylight_damping", 1.0))
    info = {"passes": 0, "converged": not order, "residual": 0.0}
    for it in range(max(0, iterations)):
        worst = 0.0
        sweep = order if it % 2 == 0 else list(reversed(order))
        for i in sweep:
            worst = max(worst, _equalize_at(skel, xs, ys, i, damping))
        info["passes"] = it + 1
        info["residual"] = worst
        if worst < tolerance:
            info["converged"] = True
            break
    return xs, ys, info


def equal_daylight(tree: Tree, params: LayoutParams, iterations: int | None = None,
                   tolerance: float | None = None) -> dict[int, tuple[float, float]]:
    """Equal-daylight positions, in branch-length units, keyed by node id.

    Initialised from equal-angle -- the algorithm equalises an existing drawing,
    it does not create one -- then swept alternately forward and backward from
    the centroid until the largest rotation in a pass falls under *tolerance*
    (radians) or the pass cap is reached.  Convergence is not guaranteed on
    pathological trees, which is why the cap is not optional.
    """
    skel = build_skeleton(tree, params)
    its = params.daylight_iterations if iterations is None else iterations
    tol = params.daylight_tolerance if tolerance is None else tolerance
    xs, ys, _ = _daylight_positions(skel, params, its, tol)
    return {nid: (float(xs[i]), float(ys[i])) for i, nid in enumerate(skel.ids)}


def daylight_gaps(tree: Tree, params: LayoutParams,
                  positions: Mapping[int, tuple[float, float]]
                  ) -> dict[int, list[float]]:
    """Uncovered angular gaps around every internal node, in radians.

    Exposed because "is the daylight actually more even?" is the only honest
    test of the equalisation, and because the studio's layout inspector wants
    the same numbers.
    """
    skel = build_skeleton(tree, params)
    n = len(skel)
    xs = np.zeros(n, dtype=float)
    ys = np.zeros(n, dtype=float)
    for i, nid in enumerate(skel.ids):
        x, y = positions[nid]
        xs[i] = x
        ys[i] = y
    out: dict[int, list[float]] = {}
    for i in range(n):
        arcs = _arcs_at(skel, xs, ys, i)
        if arcs is None or len(arcs) < 3:
            continue
        gaps = [arcs[k + 1][0] - arcs[k][1] for k in range(len(arcs) - 1)]
        gaps.append(arcs[0][0] + TWO_PI - arcs[-1][1])
        out[skel.ids[i]] = gaps
    return out


# ---------------------------------------------------------------- the layout


class UnrootedLayout:
    """Equal-angle and equal-daylight drawings, selected by ``unrooted_method``."""

    mode: LayoutMode = LayoutMode.UNROOTED

    def compute(self, tree: Tree, params: LayoutParams,
                metrics: TextMetrics) -> LayoutFrame:
        if params.mode is not LayoutMode.UNROOTED:
            raise ValueError(f"UnrootedLayout cannot draw {params.mode!r}")

        # The skeleton reads n_leaves to pick a drawing start and collapse_rows
        # to weight the wedges; both come from the derived caches.
        refresh_stats(tree)

        frame = LayoutFrame(tree, params)
        nodes = list(preorder(tree.root, visible_only=True))
        frame.allocate(nodes)
        if not nodes:
            frame.projector = LinearProjector(0.0, 0.0, params.row_spacing, 0.0)
            return frame

        skel = build_skeleton(tree, params)
        if params.unrooted_method is UnrootedMethod.EQUAL_DAYLIGHT:
            xs, ys, info = _daylight_positions(skel, params,
                                               params.daylight_iterations,
                                               params.daylight_tolerance)
        else:
            xs, ys = _equal_angle_positions(skel, params.start_radians)
            info = {"passes": 0, "converged": True, "residual": 0.0}

        tips, n_rows = assign_rows(tree.root, params, frame)
        frame.tips = tips
        frame.n_rows = n_rows

        label_w = self._measure_labels(tree, tips, params, metrics, frame)
        pad = params.tip_label_gap + label_w
        scale, ox, oy, bounds = self._fit(xs, ys, params, pad)
        xs = xs * scale + ox
        ys = ys * scale + oy

        for i, nid in enumerate(skel.ids):
            frame.set_xy(nid, float(xs[i]), float(ys[i]))
        for i in range(1, len(skel)):
            p = skel.parent[i]
            frame.add_segment(float(xs[p]), float(ys[p]), float(xs[i]), float(ys[i]))

        _, y0, x1, y1 = bounds
        frame.body_bounds = bounds
        frame.tip_offset = (params.tip_label_gap + label_w + params.tip_label_gap
                            if label_w > 0 else params.tip_label_gap)
        frame.scale = scale if params.branch_mode is BranchMode.PHYLOGRAM else 1.0
        frame.row_height = ((y1 - y0) / n_rows if n_rows > 0 and y1 > y0
                            else params.row_spacing)
        frame.projector = LinearProjector(x1, y0, frame.row_height, n_rows)
        frame.metadata.update({
            # An unrooted drawing has no along axis, but its coordinates ARE in
            # branch-length units scaled by ``scale``, so a scale bar remains
            # meaningful and is the conventional way to read one.  A tick
            # ladder is not: there is no origin to measure from.
            ALONG_METADATA_KEY: (ALONG_LENGTH
                                 if params.branch_mode is BranchMode.PHYLOGRAM
                                 and scale > 0.0 else ALONG_ALIGNED),
            "band_space": "approximate",
            "band_space_note": (
                "An unrooted drawing has no tip order, so rows are assigned in "
                "tree order and projected as a plain column past the bounding "
                "box.  Track positions are indicative, not geometric."),
            "method": params.unrooted_method.value,
            "daylight": info,
            "label_font_size": float(params.extra.get("label_font_size",
                                                      DEFAULT_LABEL_SIZE)),
        })
        # Negative lengths are real data (NJ, BioNJ, least squares) that the
        # drawing cannot show; the count travels on the frame so the
        # compositor can say so, since a layout has no sink of its own.
        if params.ignore_negative_lengths:
            frame.metadata[NEGATIVE_METADATA_KEY] = count_negative_lengths(tree.root)
        return frame

    def equal_angle(self, tree: Tree, params: LayoutParams
                    ) -> dict[int, tuple[float, float]]:
        """See the module-level :func:`equal_angle`."""
        return equal_angle(tree, params)

    def equal_daylight(self, tree: Tree, params: LayoutParams,
                       iterations: int | None = None,
                       tolerance: float | None = None
                       ) -> dict[int, tuple[float, float]]:
        """See the module-level :func:`equal_daylight`."""
        return equal_daylight(tree, params, iterations, tolerance)

    # ------------------------------------------------------------- helpers

    def _fit(self, xs: np.ndarray, ys: np.ndarray, params: LayoutParams,
             pad: float) -> tuple[float, float, float, tuple[float, ...]]:
        """One UNIFORM scale and a translation.

        Scaling the axes independently would stretch some branches and squash
        others, which destroys the only property an unrooted drawing has.
        Labels radiate in every direction here, so the margin is padded on all
        four sides rather than only on the label side.
        """
        w = float(xs.max() - xs.min()) if len(xs) else 0.0
        h = float(ys.max() - ys.min()) if len(ys) else 0.0
        extent = max(w, h)
        scale = float(params.width) / extent if extent > 1e-12 else 1.0
        left = params.margin + pad
        ox = left - float(xs.min()) * scale
        oy = left - float(ys.min()) * scale
        bounds = (left, left, left + w * scale, left + h * scale)
        return scale, ox, oy, bounds

    def _measure_labels(self, tree: Tree, tips: list[int], params: LayoutParams,
                        metrics: TextMetrics, frame: LayoutFrame) -> float:
        """Widest tip label.  Labels in an unrooted drawing point outward along
        their own branch, so the advance is again the space to reserve."""
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
