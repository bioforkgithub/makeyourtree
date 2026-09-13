# SPDX-License-Identifier: MIT
"""The shared shape library and the batching primitive."""

from __future__ import annotations

import math

import pytest

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import PathMark, RectsMark, Scene
from makeyourtree.style.color import parse_color
from makeyourtree.tracks.shapes import (OPEN_SHAPES, SHAPES, QuadBatch,
                                    band_offset_of, is_open_shape, shape_names,
                                    shape_path)
from helpers import (LEVEL_STEP, MODES, ROW_HEIGHT, TOP_Y, make_context,
                     make_frame, path_points)

REQUIRED = ("square", "circle", "triangle", "diamond", "star", "hexagon",
            "pentagon", "cross", "check", "arrow-right", "arrow-left",
            "rounded-rect", "ellipse", "chevron")


def test_registry_covers_the_required_vocabulary():
    assert set(REQUIRED) <= set(SHAPES)
    assert shape_names() == sorted(SHAPES)


@pytest.mark.parametrize("name", REQUIRED)
def test_every_shape_builds_in_every_mode(tree, name):
    for mode in MODES:
        ctx = make_context(tree, mode)
        segs = shape_path(name, 2.5, 30.0, 12.0, ctx.projector)
        assert segs, f"{name} produced an empty path in {mode.value}"
        pts = path_points(segs)
        assert pts
        for x, y in pts:
            assert math.isfinite(x) and math.isfinite(y)
        closed = segs[-1][0] == "Z"
        assert closed is not is_open_shape(name)


def test_open_shapes_are_the_stroked_ones():
    assert OPEN_SHAPES == {"check", "chevron"}


def test_unknown_shape_falls_back_to_square(rect_ctx):
    square = shape_path("square", 1.5, 10.0, 8.0, rect_ctx.projector)
    unknown = shape_path("no-such-shape", 1.5, 10.0, 8.0, rect_ctx.projector)
    assert unknown == square


def test_size_is_the_bounding_box(rect_ctx):
    pts = path_points(shape_path("square", 3.5, 25.0, 10.0, rect_ctx.projector))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert max(xs) - min(xs) == pytest.approx(10.0)
    assert max(ys) - min(ys) == pytest.approx(10.0)
    cx, cy = rect_ctx.projector.point(3.5, 25.0)
    assert (max(xs) + min(xs)) / 2 == pytest.approx(cx)
    assert (max(ys) + min(ys)) / 2 == pytest.approx(cy)


@pytest.mark.parametrize("name,expect_outward", [
    ("triangle", True), ("arrow-right", True), ("chevron", True),
    ("arrow-left", False)])
def test_shapes_point_along_the_outward_axis(tree, name, expect_outward):
    """Orientation comes from the projector, so it survives the polar modes."""
    for mode in MODES:
        ctx = make_context(tree, mode)
        row, offset = 2.5, 30.0
        cx, cy = ctx.projector.point(row, offset)
        ux, uy = ctx.projector.outward(row)
        pts = path_points(shape_path(name, row, offset, 12.0, ctx.projector))
        along = [(x - cx) * ux + (y - cy) * uy for x, y in pts]
        tip = max(along) if expect_outward else min(along)
        # The apex is the single extreme vertex; the base has two at the far end.
        extremes = [a for a in along if abs(a - tip) < 1e-6]
        assert len(extremes) == 1, f"{name} has no unique apex in {mode.value}"


def test_band_offset_recovers_a_node_position(tree):
    """The one inverse tracks are allowed: scene position back to band offset."""
    for mode in MODES:
        frame = make_frame(tree, mode)
        for node in tree.nodes:
            got = band_offset_of(frame, frame.projector, node.id)
            level = len(node.path_to_root(include_self=False))
            expected_along = LEVEL_STEP + level * LEVEL_STEP
            if mode.is_polar:
                want = expected_along - frame.projector.base_r
            else:
                want = expected_along - frame.projector.base_x
            assert got == pytest.approx(want, abs=1e-6)


def test_quad_batch_is_one_mark_in_linear_layouts(rect_ctx):
    scene = Scene()
    batch = QuadBatch(rect_ctx.projector)
    colors = [parse_color("#112233"), parse_color("#445566")]
    for i in range(40):
        batch.add(float(i), float(i + 1), 0.0, 20.0, colors[i % 2])
    assert batch.flush(scene.sink()) == 1
    marks = scene.layers[list(scene.layers)[0]]
    assert len(marks) == 1
    assert isinstance(marks[0], RectsMark)
    assert marks[0].count == 40
    assert len(marks[0].fills) == 40


def test_quad_batch_groups_by_colour_in_polar_layouts(tree):
    ctx = make_context(tree, LayoutMode.CIRCULAR)
    scene = Scene()
    batch = QuadBatch(ctx.projector)
    colors = [parse_color("#112233"), parse_color("#445566")]
    for i in range(40):
        batch.add(float(i), float(i + 1), 0.0, 20.0, colors[i % 2])
    assert batch.flush(scene.sink()) == 2
    marks = scene.layers[list(scene.layers)[0]]
    assert all(isinstance(m, PathMark) for m in marks)
    assert sum(m.segments.count(("Z",)) for m in marks) == 40


def test_quad_batch_rectangles_match_the_projector(rect_ctx):
    scene = Scene()
    batch = QuadBatch(rect_ctx.projector)
    batch.add(2.0, 3.0, 5.0, 25.0, parse_color("#ff0000"))
    batch.flush(scene.sink())
    mark = scene.layers[list(scene.layers)[0]][0]
    x, y, w, h = list(mark.coords)
    assert x == pytest.approx(rect_ctx.projector.base_x + 5.0)
    assert y == pytest.approx(TOP_Y + 2.0 * ROW_HEIGHT)
    assert w == pytest.approx(20.0)
    assert h == pytest.approx(ROW_HEIGHT)


def test_quad_batch_empties_after_flush(rect_ctx):
    batch = QuadBatch(rect_ctx.projector)
    assert batch.empty
    batch.add(0.0, 1.0, 0.0, 5.0, parse_color("#ff0000"))
    assert not batch.empty
    scene = Scene()
    batch.flush(scene.sink())
    assert batch.empty
    assert batch.flush(scene.sink()) == 0
