# SPDX-License-Identifier: MIT
"""Line and area charts: the y mapping, shared ranges, gaps and the zero rule."""

from __future__ import annotations

import pytest
from _support import BASE_X, ROW_HEIGHT, TOP_Y

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import (LinesMark, PolygonMark, PolylineMark,
                                  RectsMark, Scene)
from makeyourtree.tracks.line import LineChartTrack

OFFSET = 20.0
THICKNESS = 80.0


def make(tree, rows, columns=None, **options):
    track = LineChartTrack(title="series",
                           options={"thickness": THICKNESS, **options})
    columns = columns or [f"t{i}" for i in range(len(next(iter(rows.values()))))]
    track.bind(tree, rows, columns=columns)
    return track


def draw(track, tree, context_for, mode=LayoutMode.RECTANGULAR):
    ctx = context_for(tree, mode, offset=OFFSET)
    scene = Scene()
    track.draw(ctx, scene.sink(track.default_layer))
    return ctx, scene


def polylines(scene):
    return [m for m in scene.iter_marks() if isinstance(m, PolylineMark)]


def points_of(mark):
    return [(mark.points[i], mark.points[i + 1])
            for i in range(0, len(mark.points) - 1, 2)]


# ---------------------------------------------------------------- geometry


def test_columns_are_spread_across_the_track(tree, context_for):
    track = make(tree, {"A": [0.0, 1.0, 2.0, 3.0]})
    _, scene = draw(track, tree, context_for)
    xs = [x for x, _y in points_of(polylines(scene)[0])]
    assert xs == pytest.approx([BASE_X + OFFSET + THICKNESS * j / 3
                                for j in range(4)])


def test_a_larger_value_takes_a_higher_row(tree, context_for):
    """Rows grow down the page, so the biggest value must have the smallest y."""
    track = make(tree, {"A": [0.0, 5.0, 10.0]})
    _, scene = draw(track, tree, context_for)
    ys = [y for _x, y in points_of(polylines(scene)[0])]
    assert ys[0] > ys[1] > ys[2]
    centre = TOP_Y + 0.5 * ROW_HEIGHT
    assert ys[1] == pytest.approx(centre)
    half = 0.8 * ROW_HEIGHT * 0.5
    assert ys[0] == pytest.approx(centre + half)
    assert ys[2] == pytest.approx(centre - half)


# ------------------------------------------------------------------- range


def test_a_shared_range_makes_rows_comparable(tree, context_for):
    track = make(tree, {"A": [0.0, 10.0], "B": [4.0, 6.0]})
    assert track.y_range(None) == (0.0, 10.0)
    _, scene = draw(track, tree, context_for)
    a, b = polylines(scene)
    # B's values sit inside A's, so B's line must be flatter.
    spread = lambda m: max(y for _x, y in points_of(m)) - min(y for _x, y in points_of(m))  # noqa: E731
    assert spread(b) < spread(a)


def test_a_per_row_range_normalises_each_row(tree, context_for):
    track = make(tree, {"A": [0.0, 10.0], "B": [4.0, 6.0]}, y_range="row")
    assert track.y_range(tree.by_name("B").id) == (4.0, 6.0)
    _, scene = draw(track, tree, context_for)
    a, b = polylines(scene)
    spread = lambda m: max(y for _x, y in points_of(m)) - min(y for _x, y in points_of(m))  # noqa: E731
    assert spread(b) == pytest.approx(spread(a))


def test_explicit_bounds_override_the_data(tree, context_for):
    track = make(tree, {"A": [1.0, 2.0]}, value_min=-10.0, value_max=10.0)
    assert track.y_range(None) == (-10.0, 10.0)


def test_a_flat_series_still_draws(tree, context_for):
    track = make(tree, {"A": [3.0, 3.0, 3.0]})
    lo, hi = track.y_range(None)
    assert hi > lo
    _, scene = draw(track, tree, context_for)
    ys = {round(y, 6) for _x, y in points_of(polylines(scene)[0])}
    assert len(ys) == 1


# -------------------------------------------------------------------- gaps


def test_a_missing_value_breaks_the_line(tree, context_for):
    track = make(tree, {"A": [1.0, 2.0, None, 4.0, 5.0]})
    _, scene = draw(track, tree, context_for)
    runs = polylines(scene)
    assert len(runs) == 2
    assert [len(points_of(r)) for r in runs] == [2, 2]
    # Nothing is drawn at the missing column's x position.
    gap_x = BASE_X + OFFSET + THICKNESS * 2 / 4
    assert all(x != pytest.approx(gap_x)
               for run in runs for x, _y in points_of(run))


def test_a_lone_surviving_point_draws_no_line(tree, context_for):
    track = make(tree, {"A": [1.0, None, None]})
    _, scene = draw(track, tree, context_for)
    assert polylines(scene) == []


def test_dots_can_mark_the_lone_point(tree, context_for):
    track = make(tree, {"A": [1.0, None, None]}, show_dots=True)
    _, scene = draw(track, tree, context_for)
    dots = [m for m in scene.iter_marks() if isinstance(m, RectsMark)]
    assert len(dots) == 1 and dots[0].count == 1


# -------------------------------------------------------------- area, zero


def test_the_area_variant_adds_a_filled_polygon(tree, context_for):
    plain = make(tree, {"A": [1.0, 2.0, 3.0]})
    _, scene = draw(plain, tree, context_for)
    assert not [m for m in scene.iter_marks() if isinstance(m, PolygonMark)]

    filled = make(tree, {"A": [1.0, 2.0, 3.0]}, area=True)
    _, scene = draw(filled, tree, context_for)
    polygons = [m for m in scene.iter_marks() if isinstance(m, PolygonMark)]
    assert len(polygons) == 1
    assert polygons[0].paint.fill is not None
    assert polygons[0].paint.fill.a < 255
    # The fill closes back along the baseline, so it has two extra vertices.
    assert len(polygons[0].points) == len(polylines(scene)[0].points) + 4


def test_the_zero_rule_appears_only_when_zero_is_on_the_axis(tree, context_for):
    crossing = make(tree, {"A": [-2.0, 3.0]}, zero_line=True)
    ctx, scene = draw(crossing, tree, context_for)
    rules = [m for m in scene.iter_marks() if isinstance(m, LinesMark)]
    assert len(rules) == 1 and rules[0].count == 1
    x0, y0, x1, y1 = rules[0].coords
    assert y0 == pytest.approx(y1)
    assert (x0, x1) == pytest.approx((BASE_X + OFFSET,
                                      BASE_X + OFFSET + THICKNESS))

    above = make(tree, {"A": [2.0, 3.0]}, zero_line=True)
    _, scene = draw(above, tree, context_for)
    assert not [m for m in scene.iter_marks() if isinstance(m, LinesMark)]


def test_the_zero_rule_is_a_straight_radial_line_when_polar(tree, context_for):
    """A constant row across offsets projects straight in every rooted mode."""
    track = make(tree, {"A": [-2.0, 3.0]}, zero_line=True)
    ctx, scene = draw(track, tree, context_for, LayoutMode.CIRCULAR)
    rule = next(m for m in scene.iter_marks() if isinstance(m, LinesMark))
    x0, y0, x1, y1 = rule.coords
    import math
    a0 = math.atan2(y0 - ctx.projector.cy, x0 - ctx.projector.cx)
    a1 = math.atan2(y1 - ctx.projector.cy, x1 - ctx.projector.cx)
    assert a0 == pytest.approx(a1)


def test_polar_lines_are_resampled(tree, context_for):
    """A band-space segment is a spiral once projected, so it needs samples."""
    track = make(tree, {"A": [0.0, 10.0]})
    _, linear = draw(track, tree, context_for, LayoutMode.RECTANGULAR)
    _, polar = draw(track, tree, context_for, LayoutMode.CIRCULAR)
    assert len(points_of(polylines(linear)[0])) == 2
    assert len(points_of(polylines(polar)[0])) > 2


def test_legend_records_the_range_and_its_scope(tree):
    track = make(tree, {"A": [0.0, 4.0]})
    legend = track.legend()
    assert legend.kind == "scale"
    assert legend.items[0].value_range == (0.0, 4.0)
    assert "shared across rows" in legend.items[0].label

    track.options["y_range"] = "row"
    assert "per row" in track.legend().items[0].label


def test_the_line_colour_is_configurable(tree, context_for):
    track = make(tree, {"A": [1.0, 2.0]}, color="#7733aa")
    _, scene = draw(track, tree, context_for)
    assert polylines(scene)[0].paint.stroke.hex == "#7733aa"
    assert track.legend().items[0].color.hex == "#7733aa"
