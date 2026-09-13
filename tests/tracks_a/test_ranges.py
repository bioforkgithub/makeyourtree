# SPDX-License-Identifier: MIT
"""Clade ranges: underlay placement, clade span, inward reach."""

from __future__ import annotations

import pytest

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import Layer, PathMark, RectsMark, TextMark
from makeyourtree.style.color import parse_color
from makeyourtree.tracks.base import TrackData
from makeyourtree.tracks.ranges import CladeRangeTrack
from makeyourtree.tracks.shapes import band_offset_of
from helpers import ROW_HEIGHT, TOP_Y, all_marks, draw, make_context


def clade(ctx, index: int = 0):
    """An internal node with a real span, and its two flanking tips."""
    tips = ctx.tip_ids()
    node = ctx.tree.mrca([tips[index * 4], tips[index * 4 + 3]])
    return node


def ranges(ctx, nodes, **options) -> CladeRangeTrack:
    rows = {n.id: ["#3366cc", f"Clade {i}"] for i, n in enumerate(nodes)}
    return CladeRangeTrack(title="Ranges",
                           data=TrackData(columns=["color", "label"], rows=rows),
                           options=dict(options))


def test_ranges_paint_behind_the_branches(rect_ctx):
    track = ranges(rect_ctx, [clade(rect_ctx)])
    assert track.default_layer is Layer.UNDERLAY
    scene = draw(track, rect_ctx)
    assert set(scene.layers) == {Layer.UNDERLAY}
    assert Layer.order().index(Layer.UNDERLAY) < Layer.order().index(Layer.BRANCHES)


def test_a_range_takes_no_room_in_the_stack(rect_ctx):
    assert ranges(rect_ctx, [clade(rect_ctx)]).measure(rect_ctx) == 0.0


def test_the_wash_spans_the_whole_clade(rect_ctx):
    node = clade(rect_ctx)
    scene = draw(ranges(rect_ctx, [node], show_labels=False), rect_ctx)
    batch = [m for m in all_marks(scene) if isinstance(m, RectsMark)][0]
    x, y, w, h = list(batch.coords)
    lo, hi = rect_ctx.rows_of(node.id)
    assert y == pytest.approx(TOP_Y + lo * ROW_HEIGHT)
    assert h == pytest.approx((hi - lo) * ROW_HEIGHT)
    assert h == pytest.approx(4 * ROW_HEIGHT)


def test_the_wash_reaches_back_over_the_tree_body(rect_ctx):
    node = clade(rect_ctx)
    scene = draw(ranges(rect_ctx, [node], show_labels=False), rect_ctx)
    x, _, w, _ = list([m for m in all_marks(scene)
                       if isinstance(m, RectsMark)][0].coords)
    assert x == pytest.approx(rect_ctx.frame.x(node.id))
    assert x + w == pytest.approx(rect_ctx.projector.base_x)
    assert w > 0


def test_cover_tree_starts_at_the_root(rect_ctx):
    node = clade(rect_ctx)
    scene = draw(ranges(rect_ctx, [node], cover="tree", show_labels=False),
                 rect_ctx)
    x = list([m for m in all_marks(scene) if isinstance(m, RectsMark)][0].coords)[0]
    assert x == pytest.approx(rect_ctx.frame.x(rect_ctx.tree.root.id))


def test_extend_pushes_the_outer_edge_past_the_tracks(rect_ctx):
    node = clade(rect_ctx)
    scene = draw(ranges(rect_ctx, [node], extend=120.0, show_labels=False),
                 rect_ctx)
    coords = list([m for m in all_marks(scene) if isinstance(m, RectsMark)][0].coords)
    assert coords[0] + coords[2] == pytest.approx(
        rect_ctx.projector.base_x + 120.0)


def test_inner_offset_can_be_pinned(rect_ctx):
    node = clade(rect_ctx)
    scene = draw(ranges(rect_ctx, [node], inner_offset=-30.0, show_labels=False),
                 rect_ctx)
    x = list([m for m in all_marks(scene) if isinstance(m, RectsMark)][0].coords)[0]
    assert x == pytest.approx(rect_ctx.projector.base_x - 30.0)


def test_row_shrink_insets_the_band(rect_ctx):
    node = clade(rect_ctx)
    scene = draw(ranges(rect_ctx, [node], row_shrink=0.25, show_labels=False),
                 rect_ctx)
    _, y, _, h = list([m for m in all_marks(scene)
                       if isinstance(m, RectsMark)][0].coords)
    lo, hi = rect_ctx.rows_of(node.id)
    assert y == pytest.approx(TOP_Y + (lo + 0.25) * ROW_HEIGHT)
    assert h == pytest.approx((hi - lo - 0.5) * ROW_HEIGHT)


def test_pale_by_default_so_branches_stay_legible(rect_ctx):
    track = ranges(rect_ctx, [clade(rect_ctx)])
    assert 0.0 < track.opt("opacity") < 0.5
    batch = [m for m in all_marks(draw(track, rect_ctx))
             if isinstance(m, RectsMark)][0]
    assert batch.paint.opacity == track.opt("opacity")


def test_labels_are_optional_and_land_in_the_underlay(rect_ctx):
    node = clade(rect_ctx)
    with_label = draw(ranges(rect_ctx, [node]), rect_ctx)
    marks = [m for m in all_marks(with_label) if isinstance(m, TextMark)]
    assert [m.text for m in marks] == ["Clade 0"]
    assert with_label.layers[Layer.UNDERLAY][-1] is marks[0]
    without = draw(ranges(rect_ctx, [node], show_labels=False), rect_ctx)
    assert not [m for m in all_marks(without) if isinstance(m, TextMark)]


def test_a_row_without_a_colour_draws_nothing(rect_ctx):
    node = clade(rect_ctx)
    track = CladeRangeTrack(data=TrackData(columns=["color", "label"],
                                           rows={node.id: [None, "unpainted"]}))
    assert draw(track, rect_ctx).count() == 0


def test_a_node_the_layout_never_placed_is_skipped(rect_ctx):
    track = CladeRangeTrack(data=TrackData(columns=["color"],
                                           rows={9999: ["#ff0000"]}))
    assert draw(track, rect_ctx).count() == 0


def test_two_ranges_share_one_batch(rect_ctx):
    nodes = [clade(rect_ctx, 0), clade(rect_ctx, 1)]
    scene = draw(ranges(rect_ctx, nodes, show_labels=False), rect_ctx)
    batches = [m for m in all_marks(scene) if isinstance(m, RectsMark)]
    assert len(batches) == 1
    assert batches[0].count == 2


def test_polar_range_is_an_annular_sector(tree):
    ctx = make_context(tree, LayoutMode.CIRCULAR)
    node = clade(ctx)
    scene = draw(ranges(ctx, [node], show_labels=False), ctx)
    paths = [m for m in all_marks(scene) if isinstance(m, PathMark)]
    assert len(paths) == 1
    arcs = [s for s in paths[0].segments if s[0] == "A"]
    assert len(arcs) == 2
    inner = ctx.projector.base_r + band_offset_of(ctx.frame, ctx.projector, node.id)
    radii = sorted(a[3] for a in arcs)
    assert radii[0] == pytest.approx(inner)
    assert radii[1] == pytest.approx(ctx.projector.base_r)


def test_legend_deduplicates_identical_ranges(rect_ctx):
    nodes = [clade(rect_ctx, 0), clade(rect_ctx, 1)]
    rows = {n.id: ["#3366cc", "Same"] for n in nodes}
    track = CladeRangeTrack(title="R",
                            data=TrackData(columns=["color", "label"], rows=rows))
    legend = track.legend()
    assert len(legend.items) == 1
    assert legend.items[0].label == "Same"
    assert legend.items[0].color == parse_color("#3366cc")
