# SPDX-License-Identifier: MIT
"""Fixtures, track factories and scene inspection for the group-A track tests.

Tracks are exercised against a hand-built :class:`LayoutFrame` rather than a
real layout: the layout engine is a separate unit, and a track's contract is
with the *frame and the projector*, not with any particular way of filling
them.  Building the frame here also lets the tests state the band-space
geometry they expect exactly, which is what the assertions are about.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Iterable

import makeyourtree
from makeyourtree.core.node import Node
from makeyourtree.core.traversal import postorder, preorder
from makeyourtree.core.tree import Tree
from makeyourtree.layout.frame import LayoutFrame
from makeyourtree.layout.params import LayoutMode, LayoutParams
from makeyourtree.layout.projector import LinearProjector, PolarProjector
from makeyourtree.style.theme import LIGHT
from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics


# ``makeyourtree.tracks.__init__`` imports every built-in track for its registration
# side effect.  Importing it here, eagerly and without a guard, is deliberate:
# during parallel development this was wrapped in a fallback that bound the
# package to its directory when a sibling module failed to import, so that this
# unit's suite reported on this unit's code.  All the siblings have landed, and
# keeping the fallback would now hide a real breakage in the package -- the
# tests would quietly pass against a differently-wired package.
import makeyourtree.tracks  # noqa: F401,E402

from makeyourtree.scene.marks import (EllipseMark, Mark, PathMark,  # noqa: E402
                                  PolygonMark, PolylineMark, RectMark,
                                  RectsMark, Scene, TextMark)
from makeyourtree.tracks.base import (Track, TrackContext,  # noqa: E402
                                  TrackData)
from makeyourtree.tracks.binary import BinaryMatrixTrack  # noqa: E402
from makeyourtree.tracks.gradient import GradientTrack  # noqa: E402
from makeyourtree.tracks.heatmap import HeatmapTrack  # noqa: E402
from makeyourtree.tracks.ranges import CladeRangeTrack  # noqa: E402
from makeyourtree.tracks.strip import ColorStripTrack  # noqa: E402
from makeyourtree.tracks.symbols import SymbolTrack  # noqa: E402
from makeyourtree.tracks.text import TextLabelTrack  # noqa: E402

MODES = (LayoutMode.RECTANGULAR, LayoutMode.SLANTED,
         LayoutMode.CIRCULAR, LayoutMode.RADIAL)

TOP_Y = 10.0
ROW_HEIGHT = 16.0
LEVEL_STEP = 40.0
LABEL_SPACE = 60.0
CENTER = (300.0, 300.0)
START_ANGLE = -90.0
ARC = 350.0


# ----------------------------------------------------------------- geometry


def make_tree(n_leaves: int = 8) -> Tree:
    """Balanced tree with named leaves ``t0..`` and named internal nodes."""
    level: list[Node] = [Node(f"t{i}", 1.0) for i in range(n_leaves)]
    k = 0
    while len(level) > 1:
        nxt: list[Node] = []
        for i in range(0, len(level) - 1, 2):
            parent = Node(f"n{k}", 1.0)
            k += 1
            parent.add_child(level[i])
            parent.add_child(level[i + 1])
            nxt.append(parent)
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    tree = Tree(root=level[0])
    tree.refresh()
    return tree


def make_frame(tree: Tree, mode: LayoutMode) -> LayoutFrame:
    """A frame filled the way a real layout fills one: rows from tip order,
    the along axis from level, and a projector attached."""
    params = LayoutParams(mode=mode, row_spacing=ROW_HEIGHT)
    frame = LayoutFrame(tree, params)
    nodes = list(preorder(tree.root))
    frame.allocate(nodes)

    tips = [n for n in nodes if not n.children]
    frame.tips = [n.id for n in tips]
    frame.n_rows = float(len(tips))
    frame.row_height = ROW_HEIGHT
    for i, n in enumerate(tips):
        frame.set_rows(n.id, i + 0.5, float(i), float(i + 1))
    for n in postorder(tree.root):
        if n.children:
            lo = min(frame.row_span(c.id)[0] for c in n.children)
            hi = max(frame.row_span(c.id)[1] for c in n.children)
            frame.set_rows(n.id, (lo + hi) * 0.5, lo, hi)

    level: dict[int, int] = {}
    for n in preorder(tree.root):
        level[n.id] = 0 if n.parent is None else level[n.parent.id] + 1
    body = max(level.values()) * LEVEL_STEP

    if mode.is_polar:
        cx, cy = CENTER
        base_r = LEVEL_STEP + body + LABEL_SPACE
        proj: Any = PolarProjector(cx=cx, cy=cy, base_r=base_r,
                                   start_angle=START_ANGLE, arc=ARC,
                                   n_rows=frame.n_rows)
        for n in nodes:
            frame.set_polar(n.id, proj.angle_of(frame.row(n.id)),
                            LEVEL_STEP + level[n.id] * LEVEL_STEP, cx, cy)
        frame.center = (cx, cy)
        frame.max_radius = base_r
        frame.body_bounds = (cx - base_r, cy - base_r, cx + base_r, cy + base_r)
    else:
        base_x = LEVEL_STEP + body + LABEL_SPACE
        proj = LinearProjector(base_x=base_x, top_y=TOP_Y,
                               row_height=ROW_HEIGHT, n_rows=frame.n_rows)
        for n in nodes:
            frame.set_xy(n.id, LEVEL_STEP + level[n.id] * LEVEL_STEP,
                         TOP_Y + frame.row(n.id) * ROW_HEIGHT)
        frame.body_bounds = (LEVEL_STEP, TOP_Y, LEVEL_STEP + body,
                             TOP_Y + frame.n_rows * ROW_HEIGHT)

    frame.projector = proj
    frame.tip_offset = 0.0
    return frame


def make_context(tree: Tree, mode: LayoutMode,
                 offset: float = 0.0) -> TrackContext:
    frame = make_frame(tree, mode)
    return TrackContext(tree=tree, frame=frame, projector=frame.projector,
                        theme=LIGHT, metrics=CachedMetrics(FallbackMetrics()),
                        offset=offset)


# ------------------------------------------------------------- track fixtures

GROUPS = ("alpha", "beta", "gamma")


def strip_track(ctx: TrackContext) -> Track:
    rows = {nid: [GROUPS[i % 3], f"Group {GROUPS[i % 3]}"]
            for i, nid in enumerate(ctx.tip_ids())}
    return ColorStripTrack(title="Group",
                           data=TrackData(columns=["group", "label"], rows=rows))


def range_track(ctx: TrackContext) -> Track:
    internal = [n.id for n in ctx.tree.nodes if n.children and n.parent is not None]
    picks = internal[:2] or [ctx.tree.root.id]
    palette = ("#3366cc", "#cc6633")
    rows = {nid: [palette[i % 2], f"Clade {i}"] for i, nid in enumerate(picks)}
    return CladeRangeTrack(title="Clades",
                           data=TrackData(columns=["color", "label"], rows=rows))


def binary_track(ctx: TrackContext) -> Track:
    states = ([1, 0, None], [0, 1, 1], [1, 1, 0])
    rows = {nid: list(states[i % 3]) for i, nid in enumerate(ctx.tip_ids())}
    return BinaryMatrixTrack(title="Genes",
                             data=TrackData(columns=["gyrA", "gyrB", "parC"],
                                            rows=rows))


def gradient_track(ctx: TrackContext) -> Track:
    rows = {nid: [float(i) * 1.5] for i, nid in enumerate(ctx.tip_ids())}
    return GradientTrack(title="Depth",
                         data=TrackData(columns=["depth"], rows=rows))


def heatmap_track(ctx: TrackContext) -> Track:
    rows = {nid: [float(i), float(i) * 2.0, None, float(i) * 0.5]
            for i, nid in enumerate(ctx.tip_ids())}
    return HeatmapTrack(title="Expression",
                        data=TrackData(columns=["c1", "c2", "c3", "c4"],
                                       rows=rows))


def text_track(ctx: TrackContext) -> Track:
    rows = {nid: [f"sample {i:02d}"] for i, nid in enumerate(ctx.tip_ids())}
    return TextLabelTrack(title="Accession",
                          data=TrackData(columns=["label"], rows=rows))


def symbol_track(ctx: TrackContext) -> Track:
    rows = {nid: [GROUPS[i % 3], float(i + 1)]
            for i, nid in enumerate(ctx.tip_ids())}
    return SymbolTrack(title="Sampling",
                       data=TrackData(columns=["group", "count"], rows=rows),
                       options={"color_column": 0, "size_column": 1})


TRACK_FACTORIES: dict[str, Callable[[TrackContext], Track]] = {
    "clade-range": range_track,
    "color-strip": strip_track,
    "binary-matrix": binary_track,
    "gradient": gradient_track,
    "heatmap": heatmap_track,
    "text-labels": text_track,
    "symbols": symbol_track,
}

TIP_TRACKS = tuple(k for k in TRACK_FACTORIES if k != "clade-range")
"""Tracks whose rows are the visible tips."""


# ------------------------------------------------------------ scene readers


def draw(track: Track, ctx: TrackContext) -> Scene:
    scene = Scene(width=800, height=600)
    track.draw(ctx, scene.sink(track.default_layer))
    return scene


def all_marks(scene: Scene) -> list[Mark]:
    out: list[Mark] = []
    for marks in scene.layers.values():
        out.extend(marks)
    return out


def mark_points(mark: Mark) -> list[tuple[float, float]]:
    """Every scene point a mark visibly touches, for geometric assertions."""
    if isinstance(mark, RectsMark):
        c = list(mark.coords)
        return [(c[i] + dx, c[i + 1] + dy)
                for i in range(0, len(c), 4)
                for dx, dy in ((0.0, 0.0), (c[i + 2], c[i + 3]))]
    if isinstance(mark, RectMark):
        return [(mark.x, mark.y), (mark.x + mark.w, mark.y + mark.h)]
    if isinstance(mark, EllipseMark):
        return [(mark.cx, mark.cy - mark.ry), (mark.cx, mark.cy + mark.ry)]
    if isinstance(mark, TextMark):
        return [(mark.x, mark.y)]
    if isinstance(mark, (PolygonMark, PolylineMark)):
        p = list(mark.points)
        return [(p[i], p[i + 1]) for i in range(0, len(p), 2)]
    if isinstance(mark, PathMark):
        return path_points(mark.segments)
    return []


def path_points(segments: Iterable[tuple]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for seg in segments:
        op = seg[0]
        if op in ("M", "L"):
            out.append((seg[1], seg[2]))
        elif op == "Q":
            out.append((seg[3], seg[4]))
        elif op == "C":
            out.append((seg[5], seg[6]))
        elif op == "A":
            # The arc's vertical extremes bound it, which is what row-band
            # assertions need; the horizontal ones never matter here.
            cx, cy, r = seg[1], seg[2], seg[3]
            out.extend([(cx, cy - r), (cx, cy + r)])
    return out


def scene_points(scene: Scene) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for mark in all_marks(scene):
        out.extend(mark_points(mark))
    return out


def cell_count(scene: Scene) -> int:
    """Drawn cells, counting a batched mark as its rectangles."""
    total = 0
    for mark in all_marks(scene):
        if isinstance(mark, RectsMark):
            total += mark.count
        elif isinstance(mark, (PathMark, RectMark, EllipseMark, PolygonMark)):
            total += 1
    return total


def snapshot(track: Track) -> dict[str, Any]:
    """Copy of everything ``measure`` is forbidden to touch."""
    return {
        "options": copy.deepcopy(track.options),
        "columns": list(track.data.columns),
        "rows": copy.deepcopy(track.data.rows),
        "title": track.title,
        "id": track.id,
        "visible": track.visible,
    }
