# SPDX-License-Identifier: MIT
"""Shared scaffolding for the chart-track tests.

:class:`~makeyourtree.layout.frame.LayoutFrame` objects and their projectors are
built here directly rather than by running the layout engine.  A track only
ever sees rows, a projector and a theme, so a hand-assembled frame is a
complete stand-in for a laid-out tree -- and it keeps every coordinate in these
tests something a reader can check with arithmetic instead of having to trust a
second subsystem.
"""

from __future__ import annotations

from makeyourtree.core.traversal import postorder, preorder
from makeyourtree.core.tree import Tree
from makeyourtree.layout.frame import LayoutFrame
from makeyourtree.layout.params import LayoutMode, LayoutParams
from makeyourtree.layout.projector import LinearProjector, PolarProjector
from makeyourtree.scene.marks import Scene
from makeyourtree.style.theme import LIGHT
from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics
from makeyourtree.tracks.base import TrackContext

ROOTED_MODES = (LayoutMode.RECTANGULAR, LayoutMode.SLANTED,
                LayoutMode.CIRCULAR, LayoutMode.RADIAL)

BASE_X = 300.0
TOP_Y = 40.0
ROW_HEIGHT = 16.0
CENTRE = (400.0, 400.0)
BASE_R = 180.0


def build_tree(names: tuple[str, ...] = ("A", "B", "C", "D", "E")) -> Tree:
    """A caterpillar over *names*: every tip hangs off a spine of internal nodes."""
    tree = Tree()
    tree.root.name = "root"
    parent = tree.root
    for i, name in enumerate(names):
        tip = tree.new_node(name, branch_length=0.1 * (i + 1))
        parent.add_child(tip)
        if i < len(names) - 1:
            nxt = tree.new_node(f"n{i}", branch_length=0.05)
            parent.add_child(nxt)
            parent = nxt
    tree.refresh()
    return tree


def build_frame(tree: Tree, mode: LayoutMode) -> LayoutFrame:
    """A frame with rows, positions and a projector, laid out by hand."""
    params = LayoutParams(mode=mode, row_spacing=ROW_HEIGHT)
    frame = LayoutFrame(tree, params)
    nodes = list(preorder(tree.root))
    frame.allocate(nodes)

    tips = [n for n in nodes if n.is_leaf]
    frame.tips = [n.id for n in tips]
    frame.n_rows = float(len(tips))
    frame.row_height = ROW_HEIGHT
    for i, tip in enumerate(tips):
        frame.set_rows(tip.id, i + 0.5, float(i), float(i + 1))
    for node in postorder(tree.root):
        if node.is_leaf:
            continue
        spans = [frame.row_span(c.id) for c in node.children]
        lo = min(s[0] for s in spans)
        hi = max(s[1] for s in spans)
        frame.set_rows(node.id, (lo + hi) * 0.5, lo, hi)

    depth = {tree.root.id: 0.0}
    for node in preorder(tree.root):
        for child in node.children:
            depth[child.id] = depth[node.id] + child.edge_length(0.05)
    deepest = max(depth.values()) or 1.0

    if mode.is_polar:
        frame.center = CENTRE
        frame.max_radius = BASE_R
        for node in nodes:
            row = frame.row(node.id)
            angle = -90.0 + (row / frame.n_rows) * 350.0
            frame.set_polar(node.id, angle, BASE_R * depth[node.id] / deepest,
                            *CENTRE)
        frame.projector = PolarProjector(cx=CENTRE[0], cy=CENTRE[1],
                                         base_r=BASE_R, start_angle=-90.0,
                                         arc=350.0, n_rows=frame.n_rows)
    else:
        for node in nodes:
            frame.set_xy(node.id,
                         40.0 + (BASE_X - 80.0) * depth[node.id] / deepest,
                         TOP_Y + frame.row(node.id) * ROW_HEIGHT)
        frame.projector = LinearProjector(base_x=BASE_X, top_y=TOP_Y,
                                          row_height=ROW_HEIGHT,
                                          n_rows=frame.n_rows)
    frame.body_bounds = (40.0, TOP_Y, BASE_X, TOP_Y + frame.n_rows * ROW_HEIGHT)
    frame.tip_offset = 0.0
    return frame


def make_context(tree: Tree, mode: LayoutMode, offset: float = 20.0,
                 sink=None) -> TrackContext:
    frame = build_frame(tree, mode)
    return TrackContext(tree=tree, frame=frame, projector=frame.projector,
                        theme=LIGHT, metrics=CachedMetrics(FallbackMetrics()),
                        offset=offset, sink=sink)


def node_id(tree: Tree, name: str) -> int:
    node = tree.by_name(name)
    assert node is not None, f"no node named {name!r}"
    return node.id


def all_marks(scene: Scene) -> list:
    return list(scene.iter_marks())


def mark_points(mark) -> list[tuple[float, float]]:
    """Every scene point a mark puts on the page, whatever its kind."""
    from makeyourtree.scene.marks import (EllipseMark, LinesMark, PathMark,
                                      PolygonMark, PolylineMark, RectMark,
                                      RectsMark, TextMark)
    out: list[tuple[float, float]] = []
    if isinstance(mark, RectsMark):
        # Flat x, y, w, h groups: report both corners of every rectangle.
        for i in range(0, len(mark.coords) - 3, 4):
            x, y, w, h = mark.coords[i:i + 4]
            out.extend(((x, y), (x + w, y + h)))
        return out
    if isinstance(mark, (PolylineMark, PolygonMark)):
        flat = mark.points
    elif isinstance(mark, LinesMark):
        flat = mark.coords
    elif isinstance(mark, RectMark):
        flat = (mark.x, mark.y, mark.x + mark.w, mark.y + mark.h)
    elif isinstance(mark, EllipseMark):
        flat = (mark.cx, mark.cy)
    elif isinstance(mark, TextMark):
        flat = (mark.x, mark.y)
    elif isinstance(mark, PathMark):
        for seg in mark.segments:
            if seg[0] in ("M", "L"):
                out.append((seg[1], seg[2]))
            elif seg[0] == "Q":
                out.extend(((seg[1], seg[2]), (seg[3], seg[4])))
            elif seg[0] == "C":
                out.extend(((seg[1], seg[2]), (seg[3], seg[4]), (seg[5], seg[6])))
        return out
    else:
        flat = ()
    for i in range(0, len(flat) - 1, 2):
        out.append((flat[i], flat[i + 1]))
    return out
