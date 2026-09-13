# SPDX-License-Identifier: MIT
"""Colour strip: category scale, run merging, branch propagation."""

from __future__ import annotations

import pytest

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import RectsMark, TextMark
from makeyourtree.style.color import parse_color
from makeyourtree.tracks.base import TrackData
from makeyourtree.tracks.strip import (CategoryColors, ColorStripTrack,
                                   FALLBACK_CATEGORICAL, looks_like_color,
                                   palette_colors)
from helpers import ROW_HEIGHT, TOP_Y, all_marks, draw, make_context, make_tree


def strip(ctx, values, **options) -> ColorStripTrack:
    rows = {nid: [v] for nid, v in zip(ctx.tip_ids(), values)}
    return ColorStripTrack(title="", data=TrackData(columns=["group"], rows=rows),
                           options=options)


def only_batch(scene) -> RectsMark:
    batches = [m for m in all_marks(scene) if isinstance(m, RectsMark)]
    assert len(batches) == 1
    return batches[0]


# ------------------------------------------------------------------- scale


def test_categories_are_coloured_in_first_seen_order():
    scale = CategoryColors(["b", "a", "b", "c"])
    assert scale.color("b") == FALLBACK_CATEGORICAL[0]
    assert scale.color("a") == FALLBACK_CATEGORICAL[1]
    assert scale.color("c") == FALLBACK_CATEGORICAL[2]
    assert [k for k, _ in scale.items()] == ["b", "a", "c"]
    assert scale("a") == scale.color("a"), "a scale is usable as a plain callable"


def test_explicit_colours_win_over_the_palette():
    scale = CategoryColors(["a", "b"], explicit={"a": "#ff0000"})
    assert scale.color("a") == parse_color("#ff0000")
    assert scale.color("b") != parse_color("#ff0000")


def test_palette_cycles_rather_than_running_out():
    many = [f"c{i}" for i in range(len(FALLBACK_CATEGORICAL) + 3)]
    scale = CategoryColors(many)
    assert scale.color(many[0]) == scale.color(many[len(FALLBACK_CATEGORICAL)])


def test_missing_value_has_no_colour():
    scale = CategoryColors(["a"])
    assert scale.color(None) is None
    assert scale.color("") is None


def test_only_hex_and_functional_notation_count_as_literal_colours():
    assert looks_like_color("#abc")
    assert looks_like_color("rgb(1,2,3)")
    assert not looks_like_color("red"), "a bare name is far more often a category"
    scale = CategoryColors(["#00ff00", "red"])
    assert scale.color("#00ff00") == parse_color("#00ff00")
    assert scale.color("red") in FALLBACK_CATEGORICAL


def test_unknown_palette_name_falls_back_rather_than_raising():
    assert palette_colors("definitely-not-a-palette") == FALLBACK_CATEGORICAL
    assert palette_colors(None) == FALLBACK_CATEGORICAL


# ---------------------------------------------------------------- geometry


def test_band_covers_the_whole_row(rect_ctx):
    track = strip(rect_ctx, ["a"] * 8, merge_runs=False, thickness=25.0)
    batch = only_batch(draw(track, rect_ctx))
    assert batch.count == 8
    coords = list(batch.coords)
    assert coords[1] == pytest.approx(TOP_Y)
    assert coords[3] == pytest.approx(ROW_HEIGHT)
    assert coords[2] == pytest.approx(25.0)


def test_adjacent_equal_colours_merge_into_one_quad(rect_ctx):
    same = strip(rect_ctx, ["a"] * 8)
    assert only_batch(draw(same, rect_ctx)).count == 1

    split = strip(rect_ctx, ["a"] * 4 + ["b"] * 4)
    assert only_batch(draw(split, rect_ctx)).count == 2

    alternating = strip(rect_ctx, ["a", "b"] * 4)
    assert only_batch(draw(alternating, rect_ctx)).count == 8


def test_merging_can_be_turned_off(rect_ctx):
    track = strip(rect_ctx, ["a"] * 8, merge_runs=False)
    assert only_batch(draw(track, rect_ctx)).count == 8


def test_a_gap_breaks_a_run(rect_ctx):
    values = ["a", "a", None, "a", "a", "a", "a", "a"]
    track = strip(rect_ctx, values)
    batch = only_batch(draw(track, rect_ctx))
    assert batch.count == 2
    heights = list(batch.coords)[3::4]
    assert heights == pytest.approx([2 * ROW_HEIGHT, 5 * ROW_HEIGHT])


def test_margin_shifts_the_band_and_is_measured(rect_ctx):
    track = strip(rect_ctx, ["a"] * 8, margin=7.0, thickness=20.0)
    assert track.measure(rect_ctx) == pytest.approx(27.0)
    batch = only_batch(draw(track, rect_ctx))
    assert list(batch.coords)[0] == pytest.approx(rect_ctx.projector.base_x + 7.0)


def test_title_is_drawn_at_the_head(rect_ctx):
    track = strip(rect_ctx, ["a"] * 8)
    track.title = "Lineage"
    texts = [m for m in all_marks(draw(track, rect_ctx)) if isinstance(m, TextMark)]
    assert [m.text for m in texts] == ["Lineage"]
    assert texts[0].y < TOP_Y, "the title sits before the first row"


def test_border_becomes_a_stroke(rect_ctx):
    track = strip(rect_ctx, ["a"] * 8, border_width=1.5, border_color="#000000")
    batch = only_batch(draw(track, rect_ctx))
    assert batch.paint.stroke == parse_color("#000000")
    assert batch.paint.width == pytest.approx(1.5)


# --------------------------------------------------------------- behaviour


def test_branch_colours_propagate_only_where_a_clade_agrees(rect_ctx):
    tree = rect_ctx.tree
    track = strip(rect_ctx, ["a", "a", "b", "b", "c", "c", "c", "c"],
                  color_branches=True)
    colors = track.branch_colors(rect_ctx)
    tips = rect_ctx.tip_ids()

    def parent_of(*ids):
        return tree.mrca(list(ids)).id

    assert colors[parent_of(tips[0], tips[1])] == colors[tips[0]]
    assert parent_of(tips[0], tips[3]) not in colors, "a mixed clade stays neutral"
    assert colors[parent_of(tips[4], tips[7])] == colors[tips[4]]
    assert tree.root.id not in colors


def test_branch_and_label_colouring_are_opt_in(rect_ctx):
    """Neither branches nor labels belong to this track; it only offers them."""
    off = strip(rect_ctx, ["a"] * 8)
    assert off.branch_colors(rect_ctx) == {}
    assert off.label_colors(rect_ctx) == {}
    on = strip(rect_ctx, ["a"] * 8, color_labels=True, color_branches=True)
    assert on.label_colors(rect_ctx) == on.tip_colors(rect_ctx)
    assert on.branch_colors(rect_ctx)[rect_ctx.tree.root.id] ==         on.tip_colors(rect_ctx)[rect_ctx.tip_ids()[0]]


def test_tip_colours_skip_tips_with_no_row(rect_ctx):
    track = strip(rect_ctx, ["a", None, "b", None, "c", "c", "c", "c"])
    colors = track.tip_colors(rect_ctx)
    assert len(colors) == 6


def test_missing_fill_policy_paints_a_named_colour(rect_ctx):
    track = strip(rect_ctx, ["a", None, "a", "a", "a", "a", "a", "a"],
                  missing="fill", missing_color="#123456")
    fills = list(only_batch(draw(track, rect_ctx)).fills)
    assert parse_color("#123456") in fills


def test_legend_deduplicates_and_uses_the_label_column(rect_ctx):
    rows = {nid: ["a", "Alpha"] if i % 2 else ["b", "Beta"]
            for i, nid in enumerate(rect_ctx.tip_ids())}
    track = ColorStripTrack(title="Group",
                            data=TrackData(columns=["group", "label"], rows=rows))
    legend = track.legend()
    assert [i.label for i in legend.items] == ["Beta", "Alpha"]
    assert all(i.shape == "square" for i in legend.items)


def test_polar_strip_covers_every_row_as_a_sector(tree):
    ctx = make_context(tree, LayoutMode.CIRCULAR)
    track = strip(ctx, [f"g{i}" for i in range(8)])
    scene = draw(track, ctx)
    assert not [m for m in all_marks(scene) if isinstance(m, RectsMark)]
    assert scene.count() == 8


def test_large_strip_stays_cheap():
    ctx = make_context(make_tree(512), LayoutMode.RECTANGULAR)
    track = strip(ctx, ["a"] * 512)
    scene = draw(track, ctx)
    assert scene.count() == 1
    assert only_batch(scene).count == 1
