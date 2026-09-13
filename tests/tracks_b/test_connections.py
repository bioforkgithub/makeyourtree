# SPDX-License-Identifier: MIT
"""Connections: pair binding, zero thickness, the layer, and the bow."""

from __future__ import annotations

import math

import pytest
from _support import node_id

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import Layer, PathMark, Scene, TextMark
from makeyourtree.tracks.connections import LINK_COLUMNS, ConnectionsTrack


def make(tree, links, **options):
    track = ConnectionsTrack(title="links", options=dict(options))
    track.bind(tree, {str(i): rec for i, rec in enumerate(links)})
    return track


def draw(track, tree, context_for, mode=LayoutMode.RECTANGULAR):
    ctx = context_for(tree, mode, offset=20.0)
    scene = Scene()
    track.draw(ctx, scene.sink(track.default_layer))
    return ctx, scene


def curves(scene):
    return [m for m in scene.iter_marks() if isinstance(m, PathMark)]


# ----------------------------------------------------------------- binding


def test_bind_resolves_both_endpoints(tree):
    track = make(tree, [["A", "C", 2.0, "#123456", 0.4, "one"]])
    assert track.data.columns == list(LINK_COLUMNS)
    row = track.data.rows[0]
    assert row[0] == node_id(tree, "A")
    assert row[1] == node_id(tree, "C")
    assert row[2:] == [2.0, "#123456", 0.4, "one"]


def test_bind_accepts_internal_nodes_and_raw_ids(tree):
    internal = node_id(tree, "n1")
    track = make(tree, [["A", "n1"], [internal, "B"]])
    assert track.data.rows[0][1] == internal
    assert track.data.rows[1][0] == internal


def test_short_records_are_padded(tree):
    track = make(tree, [["A", "B"]])
    assert len(track.data.rows[0]) == len(LINK_COLUMNS)
    assert track.data.rows[0][2:] == [None, None, None, None]


def test_a_link_with_an_unknown_endpoint_is_dropped(tree):
    sink = DiagnosticSink()
    track = ConnectionsTrack(title="links")
    track.bind(tree, {"0": ["A", "B"], "1": ["A", "nowhere"]}, sink=sink)
    assert len(track.data.rows) == 1
    assert track.data.unmatched == ["nowhere"]
    assert any(d.code == "track.unmatched" for d in sink)


def test_a_record_with_only_one_endpoint_is_dropped(tree):
    track = ConnectionsTrack()
    track.bind(tree, {"lonely": ["A"]})
    assert track.data.rows == {}
    assert track.data.unmatched == ["lonely"]


# ------------------------------------------------------------ band and layer


def test_connections_consume_no_band_thickness(tree, context_for, mode):
    track = make(tree, [["A", "C"]])
    assert track.measure(context_for(tree, mode)) == 0.0


def test_marks_land_in_the_connections_layer(tree, context_for, mode):
    track = make(tree, [["A", "C"], ["B", "E"]])
    ctx = context_for(tree, mode, offset=20.0)
    scene = Scene()
    track.draw(ctx, scene.sink(track.default_layer))
    assert len(scene.layers[Layer.CONNECTIONS]) == 2
    assert set(scene.layers) == {Layer.CONNECTIONS}


# -------------------------------------------------------------------- bow


def test_linear_links_bow_outward_past_the_tips(tree, context_for):
    track = make(tree, [["A", "E"]], bow=0.85)
    ctx, scene = draw(track, tree, context_for, LayoutMode.RECTANGULAR)
    (_op, cx, cy, _ex, _ey) = curves(scene)[0].segments[1]
    ax, _ay = ctx.frame.xy(node_id(tree, "A"))
    ex, _ey2 = ctx.frame.xy(node_id(tree, "E"))
    assert cx > max(ax, ex), "control point must sit beyond both endpoints"
    assert cy == pytest.approx((ctx.frame.xy(node_id(tree, "A"))[1]
                                + ctx.frame.xy(node_id(tree, "E"))[1]) * 0.5)


def test_polar_links_bow_toward_the_centre(tree, context_for):
    track = make(tree, [["A", "E"]], bow=1.0)
    ctx, scene = draw(track, tree, context_for, LayoutMode.CIRCULAR)
    (_op, cx, cy, _ex, _ey) = curves(scene)[0].segments[1]
    centre = (ctx.projector.cx, ctx.projector.cy)
    assert (cx, cy) == pytest.approx(centre)


def test_a_partial_bow_lands_between_the_chord_and_the_centre(tree, context_for):
    track = make(tree, [["A", "E"]], bow=0.5)
    ctx, scene = draw(track, tree, context_for, LayoutMode.CIRCULAR)
    (_op, cx, cy, _ex, _ey) = curves(scene)[0].segments[1]
    p1 = ctx.frame.xy(node_id(tree, "A"))
    p2 = ctx.frame.xy(node_id(tree, "E"))
    mid = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
    centre = (ctx.projector.cx, ctx.projector.cy)
    assert cx == pytest.approx((mid[0] + centre[0]) * 0.5)
    assert cy == pytest.approx((mid[1] + centre[1]) * 0.5)


def test_a_zero_bow_is_a_straight_chord(tree, context_for):
    track = make(tree, [["A", "E"]], bow=0.0)
    ctx, scene = draw(track, tree, context_for, LayoutMode.CIRCULAR)
    (_op, cx, cy, ex, ey) = curves(scene)[0].segments[1]
    p1 = ctx.frame.xy(node_id(tree, "A"))
    assert (cx, cy) == pytest.approx(((p1[0] + ex) * 0.5, (p1[1] + ey) * 0.5))


def test_a_self_link_becomes_a_loop(tree, context_for, mode):
    track = make(tree, [["A", "A"]], loop_size=30.0)
    ctx, scene = draw(track, tree, context_for, mode)
    segments = curves(scene)[0].segments
    assert [s[0] for s in segments] == ["M", "C"]
    start = (segments[0][1], segments[0][2])
    end = (segments[1][5], segments[1][6])
    assert start == pytest.approx(end)
    assert start == pytest.approx(ctx.frame.xy(node_id(tree, "A")))
    # Both control points stand off from the node by the loop size.
    for cx, cy in ((segments[1][1], segments[1][2]),
                   (segments[1][3], segments[1][4])):
        assert math.dist((cx, cy), start) > 30.0 * 0.9


# ------------------------------------------------------- anchors and widths


def test_anchoring_to_the_band_puts_endpoints_on_the_baseline(tree, context_for):
    track = make(tree, [["A", "C"]], anchor="band", band_offset=5.0)
    ctx, scene = draw(track, tree, context_for, LayoutMode.RECTANGULAR)
    move = curves(scene)[0].segments[0]
    assert (move[1], move[2]) == pytest.approx(
        ctx.projector.point(ctx.frame.row(node_id(tree, "A")), 5.0))


def test_widths_are_normalised_to_the_dataset_maximum(tree, context_for):
    track = make(tree, [["A", "B", 1.0], ["A", "C", 4.0]], max_width=8.0)
    _, scene = draw(track, tree, context_for)
    widths = [m.paint.width for m in curves(scene)]
    # Thin links are drawn first so the heavy ones land on top.
    assert widths == pytest.approx([2.0, 8.0])


def test_sqrt_width_scaling_is_available(tree, context_for):
    track = make(tree, [["A", "B", 1.0], ["A", "C", 4.0]], max_width=8.0,
                 width_scale="sqrt")
    _, scene = draw(track, tree, context_for)
    assert [m.paint.width for m in curves(scene)] == pytest.approx([4.0, 8.0])


def test_per_link_colour_and_opacity_win(tree, context_for):
    track = make(tree, [["A", "B", 1.0, "#804020", 0.2]], opacity=0.9)
    _, scene = draw(track, tree, context_for)
    paint = curves(scene)[0].paint
    assert paint.stroke.hex == "#804020"
    assert paint.opacity == pytest.approx(0.2)


def test_the_track_opacity_is_the_default(tree, context_for):
    track = make(tree, [["A", "B", 1.0]], opacity=0.3)
    _, scene = draw(track, tree, context_for)
    assert curves(scene)[0].paint.opacity == pytest.approx(0.3)


# ------------------------------------------------------------ labels, legend


def test_labels_are_placed_on_the_curve_not_on_the_chord(tree, context_for):
    track = make(tree, [["A", "E", 1.0, None, None, "swap"]], show_labels=True,
                 bow=1.0)
    ctx, scene = draw(track, tree, context_for, LayoutMode.RECTANGULAR)
    label = next(m for m in scene.iter_marks() if isinstance(m, TextMark))
    (_op, cx, cy, _ex, _ey) = curves(scene)[0].segments[1]
    p1 = ctx.frame.xy(node_id(tree, "A"))
    p2 = ctx.frame.xy(node_id(tree, "E"))
    assert label.text == "swap"
    assert label.x == pytest.approx(0.25 * p1[0] + 0.5 * cx + 0.25 * p2[0])
    assert label.x != pytest.approx((p1[0] + p2[0]) * 0.5)
    assert label.y == pytest.approx(0.25 * p1[1] + 0.5 * cy + 0.25 * p2[1])


def test_labels_are_off_by_default(tree, context_for):
    track = make(tree, [["A", "E", 1.0, None, None, "swap"]])
    _, scene = draw(track, tree, context_for)
    assert not [m for m in scene.iter_marks() if isinstance(m, TextMark)]


def test_legend_keys_colour_labels_and_the_width_scale(tree):
    track = make(tree, [["A", "B", 1.0, "#804020", None, "transfer"],
                        ["C", "D", 4.0, "#804020", None, "transfer"],
                        ["A", "D", 2.0, "#208040", None, "loss"]])
    items = track.legend().items
    labels = [i.label for i in items]
    assert labels.count("transfer") == 1
    assert "loss" in labels
    weight = items[-1]
    assert weight.value_range == (1.0, 4.0)


def test_no_links_means_no_marks(tree, context_for):
    track = ConnectionsTrack()
    _, scene = draw(track, tree, context_for)
    assert scene.count() == 0


def test_the_track_colour_is_the_default_for_every_link(tree, context_for):
    track = make(tree, [["A", "B"], ["C", "D"]], color="#334455")
    _, scene = draw(track, tree, context_for)
    assert {m.paint.stroke.hex for m in curves(scene)} == {"#334455"}
