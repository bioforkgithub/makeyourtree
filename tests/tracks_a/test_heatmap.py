# SPDX-License-Identifier: MIT
"""Heatmap: batching bound, normalisation, missing values, clustering."""

from __future__ import annotations

import pytest

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import PathMark, RectsMark, TextMark
from makeyourtree.style.color import parse_color
from makeyourtree.tracks.base import TrackData
from makeyourtree.tracks.gradient import DEFAULT_MISSING
from makeyourtree.tracks.heatmap import HeatmapTrack, average_linkage_order
from helpers import (all_marks, cell_count, draw, make_context, make_tree)


def matrix(ctx, n_cols: int, *, blanks: bool = False) -> HeatmapTrack:
    rows = {}
    for i, nid in enumerate(ctx.tip_ids()):
        row = [float((i * 7 + c * 3) % 11) for c in range(n_cols)]
        if blanks and i % 4 == 0:
            row[0] = None
        rows[nid] = row
    return HeatmapTrack(title="M", data=TrackData(
        columns=[f"c{c}" for c in range(n_cols)], rows=rows))


@pytest.mark.parametrize("n_tips", [20, 200])
def test_mark_count_is_o_columns_not_o_cells(n_tips):
    """A million cells must not become a million marks."""
    n_cols = 40
    ctx = make_context(make_tree(n_tips), LayoutMode.RECTANGULAR)
    track = matrix(ctx, n_cols)
    scene = draw(track, ctx)
    assert cell_count(scene) == n_tips * n_cols
    assert scene.count() == 1 + n_cols, "one batch plus one label per column"


def test_mark_count_does_not_grow_with_tips():
    small = make_context(make_tree(16), LayoutMode.RECTANGULAR)
    large = make_context(make_tree(256), LayoutMode.RECTANGULAR)
    a = draw(matrix(small, 30), small).count()
    b = draw(matrix(large, 30), large).count()
    assert a == b


def test_polar_batching_is_bounded_by_the_ramp_steps():
    """Annular sectors cannot batch as rectangles, so they batch by colour."""
    n_cols, steps = 30, 32
    ctx = make_context(make_tree(120), LayoutMode.CIRCULAR)
    track = matrix(ctx, n_cols)
    track.options["ramp_steps"] = steps
    scene = draw(track, ctx)
    paths = [m for m in all_marks(scene) if isinstance(m, PathMark)]
    assert paths
    assert len(paths) <= steps + 1
    assert scene.count() <= steps + 1 + n_cols
    assert cell_count(scene) < 120 * n_cols


def test_single_batch_carries_per_cell_fills(rect_ctx):
    track = matrix(rect_ctx, 4)
    scene = draw(track, rect_ctx)
    batches = [m for m in all_marks(scene) if isinstance(m, RectsMark)]
    assert len(batches) == 1
    assert len(batches[0].fills) == batches[0].count
    assert len(set(batches[0].fills)) > 1


def test_measure_counts_every_column(rect_ctx):
    track = matrix(rect_ctx, 6)
    track.options.update({"cell_size": 12.0, "margin": 5.0})
    assert track.measure(rect_ctx) == pytest.approx(5.0 + 6 * 12.0)


def test_column_and_global_normalisation_differ(rect_ctx):
    """Two columns on different scales: per-column normalisation must spread
    the small one across the ramp, global must not."""
    rows = {nid: [float(i), float(i) * 100.0]
            for i, nid in enumerate(rect_ctx.tip_ids())}
    data = TrackData(columns=["small", "large"], rows=rows)
    glob = HeatmapTrack(data=data, options={"normalize": "global"})
    per = HeatmapTrack(data=data, options={"normalize": "column"})

    def small_column_fills(track):
        scene = draw(track, rect_ctx)
        batch = [m for m in all_marks(scene) if isinstance(m, RectsMark)][0]
        return list(batch.fills)[0::2]

    g, p = small_column_fills(glob), small_column_fills(per)
    assert len(set(g)) < len(set(p))
    assert p[0] != p[-1]


def test_row_normalisation_uses_each_rows_own_range(rect_ctx):
    rows = {nid: [1.0 + i, 2.0 + i, 3.0 + i]
            for i, nid in enumerate(rect_ctx.tip_ids())}
    track = HeatmapTrack(data=TrackData(columns=["a", "b", "c"], rows=rows),
                         options={"normalize": "row"})
    scene = draw(track, rect_ctx)
    fills = list([m for m in all_marks(scene) if isinstance(m, RectsMark)][0].fills)
    # Every row spans its own min..max, so every row paints the same triple.
    assert fills[0:3] == fills[3:6]
    assert len(set(fills[0:3])) == 3


def test_missing_cell_gets_a_colour_no_value_can_produce(rect_ctx):
    track = matrix(rect_ctx, 3, blanks=True)
    ramp = track._ramp()
    miss = parse_color(DEFAULT_MISSING)
    scene = draw(track, rect_ctx)
    fills = list([m for m in all_marks(scene) if isinstance(m, RectsMark)][0].fills)
    assert miss in fills
    for c in ramp.sample(64):
        d = ((c.r - miss.r) ** 2 + (c.g - miss.g) ** 2 + (c.b - miss.b) ** 2) ** 0.5
        assert d > 40, f"missing colour is confusable with ramp colour {c.hex}"


def test_missing_can_be_left_as_a_hole(rect_ctx):
    track = matrix(rect_ctx, 3, blanks=True)
    track.options["missing"] = "skip"
    filled = cell_count(draw(matrix(rect_ctx, 3), rect_ctx))
    assert cell_count(draw(track, rect_ctx)) < filled


def test_clustering_is_off_by_default(rect_ctx):
    track = matrix(rect_ctx, 6)
    assert track.opt("cluster_columns") is False
    assert track.opt("cluster_rows") is False
    assert track.column_order() == list(range(6))
    assert track.suggest_row_order() == list(track.data.rows)


def test_column_clustering_permutes_and_groups(rect_ctx):
    """Duplicate columns must end up adjacent once clustering is asked for."""
    rows = {}
    for i, nid in enumerate(rect_ctx.tip_ids()):
        a, b = float(i), float(i) * -1.0
        rows[nid] = [a, b, a, b]
    track = HeatmapTrack(data=TrackData(columns=["a1", "b1", "a2", "b2"],
                                        rows=rows),
                         options={"cluster_columns": True})
    order = track.column_order()
    assert sorted(order) == [0, 1, 2, 3]
    assert abs(order.index(0) - order.index(2)) == 1
    assert abs(order.index(1) - order.index(3)) == 1


def test_row_clustering_is_advisory_only(rect_ctx):
    track = matrix(rect_ctx, 4)
    track.options["cluster_rows"] = True
    suggested = track.suggest_row_order()
    assert sorted(suggested) == sorted(track.data.rows)
    scene = draw(track, rect_ctx)
    batch = [m for m in all_marks(scene) if isinstance(m, RectsMark)][0]
    ys = list(batch.coords)[1::4]
    assert ys == sorted(ys), "drawing must follow the layout's rows, not the clustering"


def test_average_linkage_handles_degenerate_input():
    assert average_linkage_order([]) == []
    assert average_linkage_order([[1.0], [2.0]]) == [0, 1]
    order = average_linkage_order([[None], [None], [None]])
    assert sorted(order) == [0, 1, 2]


def test_column_labels_can_be_turned_off(rect_ctx):
    track = matrix(rect_ctx, 5)
    with_labels = draw(track, rect_ctx)
    assert len([m for m in all_marks(with_labels) if isinstance(m, TextMark)]) == 5
    track.options["column_labels"] = False
    assert not [m for m in all_marks(draw(track, rect_ctx))
                if isinstance(m, TextMark)]


def test_cell_gap_insets_every_cell(rect_ctx):
    track = matrix(rect_ctx, 3)
    track.options.update({"cell_size": 20.0, "cell_gap": 4.0})
    batch = [m for m in all_marks(draw(track, rect_ctx)) if isinstance(m, RectsMark)][0]
    coords = list(batch.coords)
    assert coords[2] == pytest.approx(16.0)
    assert coords[0] == pytest.approx(rect_ctx.projector.base_x + 2.0)
    assert coords[4] == pytest.approx(rect_ctx.projector.base_x + 22.0)


def test_printed_values_are_optional_and_contrast_with_their_cell(rect_ctx):
    track = matrix(rect_ctx, 2)
    assert not [m for m in all_marks(draw(track, rect_ctx))
                if isinstance(m, TextMark) and m.text not in ("c0", "c1")]
    track.options.update({"show_values": True, "column_labels": False,
                          "value_format": "{:.0f}"})
    scene = draw(track, rect_ctx)
    values = [m for m in all_marks(scene) if isinstance(m, TextMark)]
    assert len(values) == len(rect_ctx.tip_ids()) * 2
    fills = list([m for m in all_marks(scene) if isinstance(m, RectsMark)][0].fills)
    for mark, fill in zip(values, fills):
        assert mark.style.color == fill.readable_text()
        assert mark.text == str(int(float(mark.text)))


def test_legend_reports_the_normalisation_in_force(rect_ctx):
    track = matrix(rect_ctx, 4)
    legend = track.legend()
    assert legend.kind == "continuous"
    assert legend.items[0].gradient
    assert legend.items[0].value_range == track.display_domain()
    assert any(i.label == "no value" for i in legend.items)

    track.options["normalize"] = "column"
    per = track.legend()
    assert "column" in per.items[0].label
    assert per.items[0].value_range == (0.0, 1.0)
