# SPDX-License-Identifier: MIT
"""Bar geometry: the value scale, stacking, grouping and the axis."""

from __future__ import annotations

import pytest
from _support import BASE_X, ROW_HEIGHT, TOP_Y, node_id

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import RectsMark, Scene, TextMark
from makeyourtree.tracks.bars import BarChartTrack, ValueAxis, nice_ticks

OFFSET = 20.0


def draw(track, tree, context_for, mode=LayoutMode.RECTANGULAR):
    ctx = context_for(tree, mode, offset=OFFSET)
    scene = Scene()
    track.draw(ctx, scene.sink(track.default_layer))
    return ctx, scene


def rects(scene) -> list[tuple[float, float, float, float]]:
    out = []
    for mark in scene.iter_marks():
        if isinstance(mark, RectsMark):
            for i in range(0, len(mark.coords) - 3, 4):
                out.append(tuple(mark.coords[i:i + 4]))
    return out


def rects_in_row(scene, row_index: int):
    """Rectangles whose vertical centre falls in tip row *row_index*."""
    lo = TOP_Y + row_index * ROW_HEIGHT
    hi = lo + ROW_HEIGHT
    picked = [r for r in rects(scene) if lo <= r[1] + r[3] * 0.5 <= hi]
    picked.sort(key=lambda r: r[0])
    return picked


# ------------------------------------------------------------------- scale


def test_zero_is_included_by_default():
    axis = ValueAxis.build([40.0, 44.0], length=100.0)
    assert axis.lo == 0.0 and axis.hi == 44.0


def test_truncated_axis_only_on_request():
    axis = ValueAxis.build([40.0, 44.0], length=100.0, baseline=40.0,
                           zero_based=False)
    assert axis.lo == 40.0 and axis.hi == 44.0


def test_the_baseline_is_always_on_the_axis():
    """Bars start at the baseline, so it cannot be truncated away."""
    axis = ValueAxis.build([40.0, 44.0], length=100.0, baseline=0.0,
                           zero_based=False)
    assert axis.lo == 0.0
    assert axis.offset(0.0) == 0.0


def test_offsets_are_linear_in_the_value():
    axis = ValueAxis.build([0.0, 10.0], length=120.0)
    assert axis.offset(0.0) == 0.0
    assert axis.offset(10.0) == pytest.approx(120.0)
    assert axis.offset(2.5) == pytest.approx(30.0)


def test_nice_ticks_are_round_numbers():
    assert nice_ticks(0.0, 100.0, 4) == [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    assert nice_ticks(-3.0, 5.0, 4) == [-2.0, 0.0, 2.0, 4.0]
    assert nice_ticks(5.0, 5.0, 4) == [5.0]


# ------------------------------------------------------------------ stacks


def test_stacked_segments_tile_and_sum_to_the_stack_total(tree, context_for):
    track = BarChartTrack(options={"axis": False, "thickness": 120.0})
    track.bind(tree, {"A": [2.0, 3.0, 5.0]}, columns=["a", "b", "c"])
    ctx, scene = draw(track, tree, context_for)
    axis = track.value_axis(ctx)
    assert (axis.lo, axis.hi) == (0.0, 10.0)

    segments = rects_in_row(scene, 0)
    assert len(segments) == 3
    widths = [r[2] for r in segments]
    assert sum(widths) == pytest.approx(axis.offset(10.0) - axis.offset(0.0))
    assert widths == pytest.approx([axis.offset(2.0), axis.offset(3.0),
                                    axis.offset(5.0)])
    # Contiguous: each segment starts exactly where the previous one ended.
    for left, right in zip(segments, segments[1:]):
        assert left[0] + left[2] == pytest.approx(right[0])
    assert segments[0][0] == pytest.approx(BASE_X + OFFSET + axis.base_offset)
    assert segments[-1][0] + segments[-1][2] == pytest.approx(
        BASE_X + OFFSET + axis.offset(10.0))


def test_stack_domain_covers_totals_not_single_values(tree, context_for):
    track = BarChartTrack(options={"axis": False})
    track.bind(tree, {"A": [4.0, 4.0], "B": [1.0, 1.0]}, columns=["a", "b"])
    ctx, _ = draw(track, tree, context_for)
    assert track.value_axis(ctx).hi == pytest.approx(8.0)


def test_negative_value_extends_across_the_baseline(tree, context_for):
    track = BarChartTrack(options={"axis": False, "thickness": 120.0})
    track.bind(tree, {"A": [5.0], "B": [-3.0]}, columns=["v"])
    ctx, scene = draw(track, tree, context_for)
    axis = track.value_axis(ctx)
    base = BASE_X + OFFSET + axis.base_offset
    assert (axis.lo, axis.hi) == (-3.0, 5.0)

    positive = rects_in_row(scene, 0)[0]
    negative = rects_in_row(scene, 1)[0]
    assert positive[0] == pytest.approx(base)
    assert positive[0] + positive[2] > base
    # The negative bar runs the other way from the same baseline.
    assert negative[0] + negative[2] == pytest.approx(base)
    assert negative[0] < base
    assert negative[2] == pytest.approx(axis.offset(0.0) - axis.offset(-3.0))


def test_negative_and_positive_stack_from_the_same_baseline(tree, context_for):
    track = BarChartTrack(options={"axis": False})
    track.bind(tree, {"A": [3.0, -2.0, 1.0]}, columns=["a", "b", "c"])
    ctx, scene = draw(track, tree, context_for)
    axis = track.value_axis(ctx)
    base = BASE_X + OFFSET + axis.base_offset
    segments = rects_in_row(scene, 0)
    assert len(segments) == 3
    below = [r for r in segments if r[0] + r[2] <= base + 1e-9]
    above = [r for r in segments if r[0] >= base - 1e-9]
    assert len(below) == 1 and len(above) == 2
    assert below[0][2] == pytest.approx(axis.offset(0.0) - axis.offset(-2.0))


# ----------------------------------------------------------------- grouped


def test_grouped_bars_split_the_row_and_share_a_baseline(tree, context_for):
    track = BarChartTrack(options={"axis": False, "stack": "grouped",
                                   "bar_gap": 0.0, "series_gap": 0.0})
    track.bind(tree, {"A": [2.0, 4.0, 6.0]}, columns=["a", "b", "c"])
    ctx, scene = draw(track, tree, context_for)
    axis = track.value_axis(ctx)
    base = BASE_X + OFFSET + axis.base_offset
    segments = sorted(rects_in_row(scene, 0), key=lambda r: r[1])
    assert len(segments) == 3
    assert all(r[0] == pytest.approx(base) for r in segments)
    assert [r[2] for r in segments] == pytest.approx(
        [axis.offset(2.0), axis.offset(4.0), axis.offset(6.0)])
    # Sub-rows tile the tip row without overlapping.
    for upper, lower in zip(segments, segments[1:]):
        assert upper[1] + upper[3] == pytest.approx(lower[1])
    assert segments[0][1] == pytest.approx(TOP_Y)
    assert segments[-1][1] + segments[-1][3] == pytest.approx(TOP_Y + ROW_HEIGHT)


def test_grouped_domain_uses_single_values(tree, context_for):
    track = BarChartTrack(options={"axis": False, "stack": "grouped"})
    track.bind(tree, {"A": [4.0, 4.0]}, columns=["a", "b"])
    ctx, _ = draw(track, tree, context_for)
    assert track.value_axis(ctx).hi == pytest.approx(4.0)


# -------------------------------------------------------------------- axis


def test_axis_labels_are_drawn_once_at_the_head(tree, context_for):
    track = BarChartTrack(options={"axis": True, "axis_ticks": 4})
    track.bind(tree, {n: [10.0] for n in "ABCD"}, columns=["v"])
    ctx, scene = draw(track, tree, context_for)
    axis = track.value_axis(ctx)
    labels = [m for m in scene.iter_marks() if isinstance(m, TextMark)]
    assert len(labels) == len(axis.ticks(4))
    assert {m.text for m in labels} == {f"{t:.4g}" for t in axis.ticks(4)}
    # One label per tick, not one per row.
    assert len({(m.x, m.y) for m in labels}) == len(labels)
    assert all(m.y < TOP_Y for m in labels)


def test_axis_can_be_switched_off(tree, context_for):
    track = BarChartTrack(options={"axis": False})
    track.bind(tree, {"A": [1.0]}, columns=["v"])
    _, scene = draw(track, tree, context_for)
    assert not [m for m in scene.iter_marks() if isinstance(m, TextMark)]


# ---------------------------------------------------------------- colours


def test_explicit_column_colours_win(tree):
    track = BarChartTrack(options={"colors": ["#112233", None, "#445566"]})
    track.bind(tree, {"A": [1.0, 2.0, 3.0]}, columns=["a", "b", "c"])
    items = {i.label: i.color.hex for i in track.legend().items}
    assert items["a"] == "#112233"
    assert items["c"] == "#445566"
    assert items["b"] not in ("#112233", "#445566")


def test_stacked_legend_reads_outward(tree):
    track = BarChartTrack()
    track.bind(tree, {"A": [1.0, 2.0, 3.0]}, columns=["a", "b", "c"])
    assert [i.label for i in track.legend().items] == ["c", "b", "a"]
    track.options["stack"] = "grouped"
    assert [i.label for i in track.legend().items] == ["a", "b", "c"]


def test_row_with_only_missing_values_draws_nothing(tree, context_for):
    track = BarChartTrack(options={"axis": False})
    track.bind(tree, {"A": [1.0], "B": [None]}, columns=["v"])
    _, scene = draw(track, tree, context_for)
    assert len(rects_in_row(scene, 0)) == 1
    assert rects_in_row(scene, 1) == []


def test_internal_nodes_are_opt_in(tree, context_for):
    track = BarChartTrack(options={"axis": False})
    track.bind(tree, {"n1": [4.0]}, columns=["v"])
    _, scene = draw(track, tree, context_for)
    assert rects(scene) == []
    track.options["show_internal"] = True
    ctx, scene = draw(track, tree, context_for)
    drawn = rects(scene)
    assert len(drawn) == 1
    centre = ctx.frame.row(node_id(tree, "n1"))
    assert drawn[0][1] + drawn[0][3] * 0.5 == pytest.approx(
        TOP_Y + centre * ROW_HEIGHT)
