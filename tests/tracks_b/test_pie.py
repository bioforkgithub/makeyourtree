# SPDX-License-Identifier: MIT
"""Pie and donut charts: wedge arithmetic, sizing and placement."""

from __future__ import annotations

import math

import pytest
from _support import node_id

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import PathMark, Scene
from makeyourtree.tracks.pie import PieChartTrack, wedge_angles

OFFSET = 20.0


def draw(track, tree, context_for, mode=LayoutMode.RECTANGULAR):
    ctx = context_for(tree, mode, offset=OFFSET)
    scene = Scene()
    track.draw(ctx, scene.sink(track.default_layer))
    return ctx, scene


def sweeps(scene) -> list[float]:
    """Total angular sweep of every arc in every wedge path."""
    out = []
    for mark in scene.iter_marks():
        if not isinstance(mark, PathMark):
            continue
        total = 0.0
        for seg in mark.segments:
            if seg[0] == "A":
                total += seg[5] - seg[4]
        out.append(total)
    return out


# ------------------------------------------------------------------- angles


def test_wedges_sum_to_a_full_turn():
    angles = wedge_angles([1.0, 2.0, 3.0, 4.0])
    assert len(angles) == 4
    assert sum(a1 - a0 for _c, a0, a1 in angles) == pytest.approx(360.0)
    assert angles[0][1] == pytest.approx(-90.0)
    assert angles[-1][2] == pytest.approx(270.0)


def test_wedges_are_contiguous_and_proportional():
    angles = wedge_angles([1.0, 3.0])
    assert angles[0][2] == pytest.approx(angles[1][1])
    assert angles[0][2] - angles[0][1] == pytest.approx(90.0)
    assert angles[1][2] - angles[1][1] == pytest.approx(270.0)


def test_missing_and_non_positive_shares_take_no_angle():
    angles = wedge_angles([2.0, None, 0.0, -5.0, 2.0])
    assert [c for c, _a, _b in angles] == [0, 4]
    assert sum(a1 - a0 for _c, a0, a1 in angles) == pytest.approx(360.0)


def test_a_row_that_sums_to_nothing_draws_nothing():
    assert wedge_angles([0.0, None]) == []
    assert wedge_angles([]) == []


def test_start_angle_is_honoured():
    angles = wedge_angles([1.0], start=0.0)
    assert angles[0][1] == 0.0 and angles[0][2] == pytest.approx(360.0)


def test_drawn_wedges_sweep_a_full_turn(tree, context_for, mode):
    track = PieChartTrack(options={"radius": 6.0})
    track.bind(tree, {"A": [1.0, 1.0, 2.0]}, columns=["x", "y", "z"])
    _, scene = draw(track, tree, context_for, mode)
    assert sum(sweeps(scene)) == pytest.approx(360.0)


def test_a_single_share_becomes_a_whole_disc(tree, context_for):
    """A 360-degree arc has coincident ends, so it is emitted as sub-arcs."""
    track = PieChartTrack(options={"radius": 6.0})
    track.bind(tree, {"A": [5.0, 0.0]}, columns=["x", "y"])
    _, scene = draw(track, tree, context_for)
    paths = [m for m in scene.iter_marks() if isinstance(m, PathMark)]
    assert len(paths) == 1
    arcs = [s for s in paths[0].segments if s[0] == "A"]
    assert len(arcs) > 1
    assert sum(s[5] - s[4] for s in arcs) == pytest.approx(360.0)


# ------------------------------------------------------------------- sizing


def test_radius_scales_with_the_square_root_of_the_total(tree):
    track = PieChartTrack(options={"radius": 20.0, "size_column": "total",
                                   "min_radius": 0.0})
    track.bind(tree, {"A": [1.0, 1.0, 16.0], "B": [1.0, 1.0, 4.0],
                      "C": [1.0, 1.0, 1.0]},
               columns=["x", "y", "total"])
    assert track.size_column() == 2
    assert track.wedge_columns() == [0, 1]
    # Areas 16 : 4 : 1 must give radii 4 : 2 : 1.
    assert track.radius_for(node_id(tree, "A"), 16.0) == pytest.approx(20.0)
    assert track.radius_for(node_id(tree, "B"), 16.0) == pytest.approx(10.0)
    assert track.radius_for(node_id(tree, "C"), 16.0) == pytest.approx(5.0)


def test_fixed_radius_when_no_size_column(tree):
    track = PieChartTrack(options={"radius": 7.0})
    track.bind(tree, {"A": [1.0, 1.0]}, columns=["x", "y"])
    assert track.size_column() is None
    assert track.radius_for(node_id(tree, "A"), 0.0) == 7.0


def test_a_row_with_no_size_draws_no_disc(tree, context_for):
    track = PieChartTrack(options={"radius": 8.0, "size_column": "total"})
    track.bind(tree, {"A": [1.0, 1.0, None]}, columns=["x", "y", "total"])
    _, scene = draw(track, tree, context_for)
    assert scene.count() == 0


def test_band_thickness_covers_the_widest_disc(tree, context_for):
    track = PieChartTrack(options={"radius": 9.0, "gap": 4.0})
    track.bind(tree, {"A": [1.0]}, columns=["x"])
    ctx = context_for(tree, LayoutMode.RECTANGULAR)
    assert track.measure(ctx) == pytest.approx(22.0)


# ---------------------------------------------------------------- placement


def test_at_nodes_consumes_no_band_and_sits_on_the_tree(tree, context_for, mode):
    track = PieChartTrack(options={"at_nodes": True, "radius": 5.0})
    track.bind(tree, {"n1": [2.0, 2.0]}, columns=["x", "y"])
    ctx = context_for(tree, mode, offset=OFFSET)
    assert track.measure(ctx) == 0.0

    scene = Scene()
    track.draw(ctx, scene.sink(track.default_layer))
    paths = [m for m in scene.iter_marks() if isinstance(m, PathMark)]
    assert len(paths) == 2
    expected = ctx.frame.xy(node_id(tree, "n1"))
    for path in paths:
        move = path.segments[0]
        assert (move[1], move[2]) == pytest.approx(expected)


def test_band_placement_centres_the_disc_on_the_tip_row(tree, context_for):
    track = PieChartTrack(options={"radius": 6.0})
    track.bind(tree, {"B": [1.0, 1.0]}, columns=["x", "y"])
    ctx, scene = draw(track, tree, context_for)
    expected = ctx.projector.point(1.5, OFFSET + 6.0)
    for mark in scene.iter_marks():
        assert (mark.segments[0][1], mark.segments[0][2]) == pytest.approx(expected)


def test_donut_leaves_a_hole(tree, context_for):
    plain = PieChartTrack(options={"radius": 10.0})
    plain.bind(tree, {"A": [1.0, 1.0]}, columns=["x", "y"])
    _, flat = draw(plain, tree, context_for)
    ring = PieChartTrack(options={"radius": 10.0, "donut": 0.5})
    ring.bind(tree, {"A": [1.0, 1.0]}, columns=["x", "y"])
    ctx, holed = draw(ring, tree, context_for)

    centre = ctx.projector.point(0.5, OFFSET + 10.0)
    wedge = next(iter(holed.iter_marks()))
    radii = {round(math.dist(centre, (s[1], s[2])), 6)
             for s in wedge.segments if s[0] in ("M", "L")}
    assert radii == {10.0, 5.0}
    # A pie wedge instead touches its own centre.
    plain_wedge = next(iter(flat.iter_marks()))
    assert any(math.dist(centre, (s[1], s[2])) < 1e-9
               for s in plain_wedge.segments if s[0] == "M")


def test_legend_names_every_share_and_the_size_column(tree):
    track = PieChartTrack(options={"size_column": "total"})
    track.bind(tree, {"A": [1.0, 2.0, 3.0]}, columns=["x", "y", "total"])
    legend = track.legend()
    labels = [i.label for i in legend.items]
    assert labels[:2] == ["x", "y"]
    assert labels[-1] == "total"
    assert legend.items[-1].value_range == (0.0, 3.0)
    assert all(i.color is not None for i in legend.items[:2])


def test_a_stroke_is_drawn_only_when_a_width_is_given(tree, context_for):
    plain = PieChartTrack(options={"radius": 6.0})
    plain.bind(tree, {"A": [1.0, 1.0]}, columns=["x", "y"])
    _, scene = draw(plain, tree, context_for)
    assert all(m.paint.stroke is None for m in scene.iter_marks())

    outlined = PieChartTrack(options={"radius": 6.0, "stroke_width": 1.5,
                                      "stroke_color": "#101820"})
    outlined.bind(tree, {"A": [1.0, 1.0]}, columns=["x", "y"])
    _, scene = draw(outlined, tree, context_for)
    for mark in scene.iter_marks():
        assert mark.paint.stroke.hex == "#101820"
        assert mark.paint.width == pytest.approx(1.5)
