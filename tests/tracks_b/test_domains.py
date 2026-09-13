# SPDX-License-Identifier: MIT
"""Domain architecture: parsing, the global scale, clipping and labels."""

from __future__ import annotations

import pytest
from _support import BASE_X, ROW_HEIGHT, TOP_Y, mark_points

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import PolygonMark, RectsMark, Scene, TextMark
from makeyourtree.style.color import Color
from makeyourtree.tracks.domains import (SHAPE_NAMES, DomainArchitectureTrack,
                                     DomainFeature, legend_shape,
                                     parse_feature, shape_outline)

OFFSET = 20.0
THICKNESS = 200.0


def make(tree, rows, **options):
    track = DomainArchitectureTrack(
        title="architecture", options={"thickness": THICKNESS, **options})
    columns = ["length"] + [f"f{i}" for i in range(max(len(v) for v in rows.values()) - 1)]
    track.bind(tree, rows, columns=columns)
    return track


def draw(track, tree, context_for, mode=LayoutMode.RECTANGULAR):
    ctx = context_for(tree, mode, offset=OFFSET)
    scene = Scene()
    track.draw(ctx, scene.sink(track.default_layer))
    return ctx, scene


# ------------------------------------------------------------------ parsing


def test_features_parse_from_a_delimited_string():
    f = parse_feature("100|250|hexagon|#ff0000|SH2")
    assert f == DomainFeature(100.0, 250.0, "hexagon", Color(255, 0, 0), "SH2")


def test_trailing_fields_are_optional():
    assert parse_feature("10|20") == DomainFeature(10.0, 20.0, "rect", None, "")


def test_features_parse_from_a_mapping_and_a_sequence():
    mapping = parse_feature({"start": 1, "end": 9, "shape": "diamond",
                             "colour": "#00ff00", "label": "X"})
    assert mapping == DomainFeature(1.0, 9.0, "diamond", Color(0, 255, 0), "X")
    assert parse_feature((3, 4, "ellipse")) == DomainFeature(3.0, 4.0, "ellipse")


def test_a_feature_without_coordinates_is_dropped():
    assert parse_feature("") is None
    assert parse_feature(None) is None
    assert parse_feature("||rect") is None
    assert parse_feature("x|y|rect") is None


def test_unknown_shape_names_fall_back_to_a_rectangle():
    assert parse_feature("1|2|nonsuch").shape == "rect"
    assert parse_feature("1|2|square").shape == "rect"
    assert parse_feature("1|2|triangle").shape == "triangle-right"


def test_every_named_shape_has_an_outline():
    for name in SHAPE_NAMES:
        points = shape_outline(name, 0.0, 1.0, 0.0, 10.0)
        assert len(points) >= 3
        assert all(0.0 <= r <= 1.0 and 0.0 <= o <= 10.0 for r, o in points)


def test_legend_shapes_are_registered_symbols():
    from makeyourtree.tracks.shapes import SHAPES
    for name in SHAPE_NAMES:
        assert legend_shape(name) in SHAPES


# ------------------------------------------------------------------ scaling


def test_backbone_length_is_proportional_to_sequence_length(tree, context_for):
    track = make(tree, {"A": [1000, "1|10|rect"], "B": [500, "1|10|rect"]})
    _, scene = draw(track, tree, context_for)
    bars = [m for m in scene.iter_marks() if isinstance(m, RectsMark)]
    assert len(bars) == 1
    widths = sorted(bars[0].coords[i + 2] for i in range(0, len(bars[0].coords), 4))
    assert widths == pytest.approx([THICKNESS * 0.5, THICKNESS])


def test_the_scale_is_global_across_rows(tree, context_for):
    track = make(tree, {"A": [1000, "1|500|rect"], "B": [500, "1|500|rect"]})
    ctx, scene = draw(track, tree, context_for)
    polygons = [m for m in scene.iter_marks() if isinstance(m, PolygonMark)]
    spans = [max(x for x, _y in mark_points(p)) - min(x for x, _y in mark_points(p))
             for p in polygons]
    # The same residue range is the same physical length on every row.
    assert spans[0] == pytest.approx(spans[1])
    assert spans[0] == pytest.approx(THICKNESS * 500 / 1000)


# ----------------------------------------------------------------- clipping


def test_a_feature_never_renders_outside_its_own_bar(tree, context_for, mode):
    """Overhanging features are clipped, not allowed to run past the sequence."""
    track = make(tree, {"A": [1000, "1|400|rect|#aa0000|one"],
                        "B": [400, "300|900|ellipse|#00aa00|two"],
                        "C": [200, "-50|60|diamond|#0000aa|three"]})
    ctx, scene = draw(track, tree, context_for, mode)
    scale = THICKNESS / 1000.0
    lengths = {0: 1000.0, 1: 400.0, 2: 200.0}
    for row_index, length in lengths.items():
        limit = OFFSET + length * scale
        for point in _polygon_offsets(ctx, scene, row_index):
            assert -1e-6 <= point - OFFSET <= (limit - OFFSET) + 1e-6


def _polygon_offsets(ctx, scene, row_index):
    """Band-space offsets of a row's feature vertices, recovered by projection."""
    lo, hi = float(row_index), float(row_index + 1)
    out = []
    for mark in scene.iter_marks():
        if not isinstance(mark, PolygonMark):
            continue
        for x, y in mark_points(mark):
            offset, row = _invert(ctx, x, y)
            if lo - 0.01 <= row <= hi + 0.01:
                out.append(offset)
    return out


def _invert(ctx, x, y):
    """Recover ``(offset, row)`` from a scene point for the current projector."""
    import math
    if not ctx.projector.is_polar:
        return (x - BASE_X, (y - TOP_Y) / ROW_HEIGHT)
    p = ctx.projector
    dx, dy = x - p.cx, y - p.cy
    radius = math.hypot(dx, dy)
    angle = math.degrees(math.atan2(dy, dx))
    # angle_of() is affine in row; invert it, wrapping onto the drawn fan.
    row = (angle - p.start_angle) / p.arc * p.n_rows
    while row < -0.5:
        row += 360.0 / p.arc * p.n_rows
    return (radius - p.base_r, row)


def test_clipping_is_visible_in_the_model_too():
    feature = DomainFeature(300.0, 900.0, "rect")
    clipped = feature.clipped(400.0)
    assert clipped is not None
    assert (clipped.start, clipped.end) == (300.0, 400.0)
    assert DomainFeature(500.0, 900.0, "rect").clipped(400.0) is None


# ------------------------------------------------------------------- labels


def test_labels_appear_only_when_they_fit(tree, context_for):
    rows = {"A": [1000, "1|1000|rect|#aa0000|Kinase"]}
    roomy = make(tree, rows, thickness=400.0)
    _, scene = draw(roomy, tree, context_for)
    assert [m.text for m in scene.iter_marks() if isinstance(m, TextMark)] == ["Kinase"]

    cramped = make(tree, rows, thickness=6.0)
    _, scene = draw(cramped, tree, context_for)
    assert not [m for m in scene.iter_marks() if isinstance(m, TextMark)]


def test_labels_can_be_switched_off(tree, context_for):
    track = make(tree, {"A": [1000, "1|1000|rect|#aa0000|Kinase"]},
                 thickness=400.0, show_labels=False)
    _, scene = draw(track, tree, context_for)
    assert not [m for m in scene.iter_marks() if isinstance(m, TextMark)]


def test_label_sits_at_the_centre_of_its_feature(tree, context_for):
    track = make(tree, {"A": [1000, "201|400|rect|#aa0000|Mid"]}, thickness=400.0)
    ctx, scene = draw(track, tree, context_for)
    label = next(m for m in scene.iter_marks() if isinstance(m, TextMark))
    scale = 400.0 / 1000.0
    expected = OFFSET + (200.0 * scale + 400.0 * scale) * 0.5
    assert label.x == pytest.approx(BASE_X + expected)


# ------------------------------------------------------------------ legend


def test_legend_lists_families_once(tree):
    track = make(tree, {"A": [500, "1|100|rect|#aa0000|Kinase",
                              "200|300|ellipse|#00aa00|Helicase"],
                        "B": [500, "1|100|rect|#aa0000|Kinase",
                              "150|180|rect|#aa0000|Kinase"]})
    items = track.legend().items
    assert [i.label for i in items] == ["Helicase", "Kinase"]
    assert {i.color.hex for i in items} == {"#aa0000", "#00aa00"}


def test_unlabelled_features_do_not_enter_the_legend(tree):
    track = make(tree, {"A": [500, "1|100|rect|#aa0000"]})
    assert track.legend().items == []


def test_rows_without_a_length_draw_nothing(tree, context_for):
    track = make(tree, {"A": [1000, "1|100|rect"], "B": [None, "1|100|rect"]})
    _, scene = draw(track, tree, context_for)
    polygons = [m for m in scene.iter_marks() if isinstance(m, PolygonMark)]
    assert len(polygons) == 1


def test_backbone_and_border_colours_are_configurable(tree, context_for):
    track = make(tree, {"A": [500, "1|100|rect|#aa0000|Kinase"]},
                 backbone_color="#123456", border_color="#654321",
                 border_width=1.0)
    _, scene = draw(track, tree, context_for)
    backbone = next(m for m in scene.iter_marks() if isinstance(m, RectsMark))
    assert backbone.fills[0].hex == "#123456"
    feature = next(m for m in scene.iter_marks() if isinstance(m, PolygonMark))
    assert feature.paint.stroke.hex == "#654321"
