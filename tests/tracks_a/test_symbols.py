# SPDX-License-Identifier: MIT
"""Symbols: honest size encoding, node placement, size legend."""

from __future__ import annotations

import math

import pytest

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import PathMark
from makeyourtree.style.color import parse_color
from makeyourtree.tracks.base import TrackData
from makeyourtree.tracks.symbols import SymbolTrack
from helpers import ROW_HEIGHT, TOP_Y, all_marks, draw, make_context


def sized(ctx, values, **options) -> SymbolTrack:
    rows = {nid: [v] for nid, v in zip(ctx.tip_ids(), values)}
    opts = {"size_column": 0, "shape": "square", "max_size": 20.0,
            "min_size": 0.0}
    opts.update(options)
    return SymbolTrack(data=TrackData(columns=["n"], rows=rows), options=opts)


def marks(scene) -> list[PathMark]:
    return [m for m in all_marks(scene) if isinstance(m, PathMark)]


def extent(mark: PathMark) -> float:
    ys = [s[2] for s in mark.segments if s[0] in ("M", "L")]
    return max(ys) - min(ys)


def test_sqrt_is_the_default_and_makes_area_proportional(rect_ctx):
    """Four times the value must be twice the diameter, not four times."""
    track = sized(rect_ctx, [16.0, 4.0, 1.0] + [None] * 5)
    assert track.opt("size_mode") == "sqrt"
    a, b, c = (extent(m) for m in marks(draw(track, rect_ctx)))
    assert a == pytest.approx(20.0)
    assert b == pytest.approx(10.0)
    assert c == pytest.approx(5.0)


def test_linear_mode_is_available_for_radius_encoded_tables(rect_ctx):
    track = sized(rect_ctx, [16.0, 4.0, 1.0] + [None] * 5, size_mode="linear")
    a, b, c = (extent(m) for m in marks(draw(track, rect_ctx)))
    assert (a, b, c) == pytest.approx((20.0, 5.0, 1.25))


def test_minimum_size_keeps_tiny_values_visible(rect_ctx):
    track = sized(rect_ctx, [100.0, 0.01] + [None] * 6, min_size=6.0)
    _, small = marks(draw(track, rect_ctx))
    assert extent(small) == pytest.approx(6.0)


def test_a_row_without_a_magnitude_draws_no_symbol(rect_ctx):
    track = sized(rect_ctx, [1.0, None, "n/a", 4.0] + [None] * 4)
    assert len(marks(draw(track, rect_ctx))) == 2


def test_without_a_size_column_every_symbol_is_full_size(rect_ctx):
    rows = {nid: ["x"] for nid in rect_ctx.tip_ids()}
    track = SymbolTrack(data=TrackData(columns=["tag"], rows=rows),
                        options={"shape": "square", "max_size": 12.0})
    drawn = marks(draw(track, rect_ctx))
    assert len(drawn) == 8
    assert all(extent(m) == pytest.approx(12.0) for m in drawn)


def test_external_symbols_sit_in_their_own_column(rect_ctx):
    track = sized(rect_ctx, [1.0] * 8, margin=6.0, max_size=20.0)
    assert track.measure(rect_ctx) == pytest.approx(26.0)
    mark = marks(draw(track, rect_ctx))[0]
    xs = [s[1] for s in mark.segments if s[0] in ("M", "L")]
    centre = (max(xs) + min(xs)) / 2
    assert centre == pytest.approx(rect_ctx.projector.base_x + 6.0 + 10.0)
    ys = [s[2] for s in mark.segments if s[0] in ("M", "L")]
    assert (max(ys) + min(ys)) / 2 == pytest.approx(TOP_Y + 0.5 * ROW_HEIGHT)


def test_node_symbols_take_no_stack_width_and_land_on_the_branch(rect_ctx):
    internal = [n for n in rect_ctx.tree.nodes if n.children]
    rows = {n.id: [1.0] for n in internal}
    track = SymbolTrack(data=TrackData(columns=["n"], rows=rows),
                        options={"at_nodes": True, "shape": "square",
                                 "max_size": 8.0, "size_column": 0})
    assert track.measure(rect_ctx) == 0.0
    drawn = marks(draw(track, rect_ctx))
    assert len(drawn) == len(internal)
    for node, mark in zip(internal, drawn):
        xs = [s[1] for s in mark.segments if s[0] in ("M", "L")]
        ys = [s[2] for s in mark.segments if s[0] in ("M", "L")]
        assert (max(xs) + min(xs)) / 2 == pytest.approx(rect_ctx.frame.x(node.id))
        assert (max(ys) + min(ys)) / 2 == pytest.approx(rect_ctx.frame.y(node.id))


def test_a_fractional_position_walks_back_along_the_branch(rect_ctx):
    node = [n for n in rect_ctx.tree.nodes if n.children and n.parent][0]
    track = SymbolTrack(data=TrackData(columns=["n"], rows={node.id: [1.0]}),
                        options={"at_nodes": True, "position": 0.0,
                                 "shape": "square", "max_size": 6.0})
    mark = marks(draw(track, rect_ctx))[0]
    xs = [s[1] for s in mark.segments if s[0] in ("M", "L")]
    assert (max(xs) + min(xs)) / 2 == pytest.approx(rect_ctx.frame.x(node.parent.id))


def test_outline_only_symbols_are_stroked(rect_ctx):
    filled = marks(draw(sized(rect_ctx, [1.0] * 8), rect_ctx))[0]
    hollow = marks(draw(sized(rect_ctx, [1.0] * 8, fill=False), rect_ctx))[0]
    assert filled.paint.fill is not None and filled.paint.stroke is None
    assert hollow.paint.fill is None and hollow.paint.stroke is not None
    assert hollow.paint.width > 0


def test_colour_column_drives_a_categorical_scale(rect_ctx):
    rows = {nid: ["a" if i < 4 else "b", 1.0]
            for i, nid in enumerate(rect_ctx.tip_ids())}
    track = SymbolTrack(data=TrackData(columns=["g", "n"], rows=rows),
                        options={"color_column": 0, "size_column": 1,
                                 "colors": {"a": "#ff0000", "b": "#00ff00"}})
    drawn = marks(draw(track, rect_ctx))
    assert drawn[0].paint.fill == parse_color("#ff0000")
    assert drawn[7].paint.fill == parse_color("#00ff00")

    legend = track.legend()
    assert legend.kind == "categorical"
    assert [i.label for i in legend.items] == ["a", "b"]


def test_size_legend_steps_evenly_in_drawn_size(rect_ctx):
    track = sized(rect_ctx, [16.0, 4.0, 1.0] + [None] * 5)
    legend = track.legend()
    assert legend.kind == "scale"
    values = [i.value_range[0] for i in legend.items]
    assert values == pytest.approx([16.0, 4.0, 1.0])
    diameters = [math.sqrt(v / 16.0) for v in values]
    assert diameters == pytest.approx([1.0, 0.5, 0.25])


def test_shapes_stay_shapes_in_polar_layouts(tree):
    ctx = make_context(tree, LayoutMode.CIRCULAR)
    track = sized(ctx, [1.0] * 8, shape="circle")
    for mark in marks(draw(track, ctx)):
        arcs = [s for s in mark.segments if s[0] == "A"]
        assert len(arcs) == 2
        # Both halves share one radius, so the symbol is a true circle rather
        # than an annular wedge stretched by the projection.
        assert arcs[0][3] == pytest.approx(10.0)
        assert arcs[1][3] == pytest.approx(10.0)
        assert (arcs[0][4], arcs[0][5]) == (0.0, 180.0)
        assert (arcs[1][4], arcs[1][5]) == (180.0, 360.0)
