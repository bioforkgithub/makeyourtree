# SPDX-License-Identifier: MIT
"""Box plots: the Tukey summary, the two input shapes, and the drawn glyph."""

from __future__ import annotations

import pytest
from _support import BASE_X, ROW_HEIGHT, TOP_Y

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import (EllipseMark, PolylineMark, RectsMark, Scene)
from makeyourtree.tracks.boxplot import (BoxPlotTrack, BoxSummary, quantile,
                                     tukey_summary)

OFFSET = 20.0

# Nine ordered values plus one far outlier.  Type-7 quartiles over ten points:
# Q1 sits a quarter of the way between the 3rd and 4th, Q3 three quarters of
# the way between the 7th and 8th.
KNOWN = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0]


def draw(track, tree, context_for, mode=LayoutMode.RECTANGULAR):
    ctx = context_for(tree, mode, offset=OFFSET)
    scene = Scene()
    track.draw(ctx, scene.sink(track.default_layer))
    return ctx, scene


# ---------------------------------------------------------------- statistics


def test_quantiles_interpolate_between_order_statistics():
    xs = sorted(KNOWN)
    assert quantile(xs, 0.25) == pytest.approx(3.25)
    assert quantile(xs, 0.50) == pytest.approx(5.5)
    assert quantile(xs, 0.75) == pytest.approx(7.75)
    assert quantile([4.0], 0.9) == 4.0


def test_quantile_rejects_an_empty_sample():
    with pytest.raises(ValueError):
        quantile([], 0.5)


def test_outliers_follow_the_one_and_a_half_iqr_rule():
    s = tukey_summary(KNOWN)
    assert s is not None
    assert s.q1 == pytest.approx(3.25)
    assert s.median == pytest.approx(5.5)
    assert s.q3 == pytest.approx(7.75)
    assert s.iqr == pytest.approx(4.5)
    # Fences at 3.25 - 6.75 = -3.5 and 7.75 + 6.75 = 14.5.
    assert s.outliers == (100.0,)
    # Whiskers retreat to the extreme values inside the fences, not to min/max.
    assert (s.low, s.high) == (1.0, 9.0)


def test_no_outliers_when_everything_is_inside_the_fences():
    s = tukey_summary([1.0, 2.0, 3.0, 4.0, 5.0])
    assert s is not None
    assert s.outliers == ()
    assert (s.low, s.high) == (1.0, 5.0)


def test_whisker_factor_is_configurable():
    tight = tukey_summary(KNOWN, whisker=0.5)
    assert tight is not None
    # Fences at 3.25 - 2.25 = 1.0 and 7.75 + 2.25 = 10.0.
    assert tight.outliers == (100.0,)
    assert tight.low == 1.0 and tight.high == 9.0
    assert tukey_summary([1.0, 2.0, 3.0, 4.0, 100.0], whisker=100.0).outliers == ()


def test_summary_of_an_empty_sample_is_none():
    assert tukey_summary([]) is None


# --------------------------------------------------------------- input shape


def test_raw_columns_are_summarised(tree):
    track = BoxPlotTrack(options={"source": "raw"})
    track.bind(tree, {"A": KNOWN}, columns=[f"o{i}" for i in range(len(KNOWN))])
    s = track.summary(tree.by_name("A").id)
    assert s == BoxSummary(1.0, pytest.approx(3.25), pytest.approx(5.5),
                           pytest.approx(7.75), 9.0, (100.0,))


def test_summary_columns_are_taken_as_given(tree):
    track = BoxPlotTrack(options={"source": "summary"})
    track.bind(tree, {"A": [1.0, 3.0, 5.0, 7.0, 9.0, 20.0, -4.0]},
               columns=["min", "q1", "median", "q3", "max", "e1", "e2"])
    s = track.summary(tree.by_name("A").id)
    assert (s.low, s.q1, s.median, s.q3, s.high) == (1.0, 3.0, 5.0, 7.0, 9.0)
    assert s.outliers == (20.0, -4.0)


def test_auto_detects_five_number_headers(tree):
    track = BoxPlotTrack()
    track.bind(tree, {"A": [1.0, 3.0, 5.0, 7.0, 9.0]},
               columns=["min", "q1", "median", "q3", "max"])
    assert track.is_summary_input() is True


def test_auto_treats_unnamed_columns_as_raw_observations(tree):
    """Five plain observations must not be mistaken for a quartile summary."""
    track = BoxPlotTrack()
    track.bind(tree, {"A": [1.0, 3.0, 5.0, 7.0, 9.0]},
               columns=["r1", "r2", "r3", "r4", "r5"])
    assert track.is_summary_input() is False
    s = track.summary(tree.by_name("A").id)
    assert s.q1 == pytest.approx(3.0) and s.q3 == pytest.approx(7.0)


def test_incomplete_summary_row_is_dropped(tree):
    track = BoxPlotTrack(options={"source": "summary"})
    track.bind(tree, {"A": [1.0, None, 5.0, 7.0, 9.0]},
               columns=["min", "q1", "median", "q3", "max"])
    assert track.summary(tree.by_name("A").id) is None


# ------------------------------------------------------------------ drawing


def test_glyph_has_a_box_whiskers_a_median_and_dots(tree, context_for):
    track = BoxPlotTrack(options={"source": "raw", "axis": False})
    track.bind(tree, {"A": KNOWN}, columns=[f"o{i}" for i in range(len(KNOWN))])
    ctx, scene = draw(track, tree, context_for)
    axis = track.value_axis(ctx)
    marks = list(scene.iter_marks())

    boxes = [m for m in marks if isinstance(m, RectsMark)]
    assert len(boxes) == 1 and boxes[0].count == 1
    x, y, w, h = boxes[0].coords
    assert x == pytest.approx(BASE_X + OFFSET + axis.offset(3.25))
    assert w == pytest.approx(axis.offset(7.75) - axis.offset(3.25))
    assert y + h * 0.5 == pytest.approx(TOP_Y + 0.5 * ROW_HEIGHT)

    # One spine, two caps and one median line.
    lines = [m for m in marks if isinstance(m, PolylineMark)]
    assert len(lines) == 4
    dots = [m for m in marks if isinstance(m, EllipseMark)]
    assert len(dots) == 1
    assert dots[0].cx == pytest.approx(BASE_X + OFFSET + axis.offset(100.0))


def test_box_is_painted_over_the_whisker(tree, context_for):
    """Draw order matters: the opaque box must hide the whisker beneath it."""
    track = BoxPlotTrack(options={"source": "raw", "axis": False})
    track.bind(tree, {"A": KNOWN}, columns=[f"o{i}" for i in range(len(KNOWN))])
    _, scene = draw(track, tree, context_for)
    kinds = [type(m).__name__ for m in scene.iter_marks()]
    assert kinds.index("PolylineMark") < kinds.index("RectsMark")
    assert kinds.index("RectsMark") < kinds.index("EllipseMark")


def test_outlier_dots_can_be_suppressed(tree, context_for):
    track = BoxPlotTrack(options={"source": "raw", "axis": False,
                                  "show_outliers": False})
    track.bind(tree, {"A": KNOWN}, columns=[f"o{i}" for i in range(len(KNOWN))])
    _, scene = draw(track, tree, context_for)
    assert not [m for m in scene.iter_marks() if isinstance(m, EllipseMark)]


def test_domain_spans_the_outliers_too(tree, context_for):
    track = BoxPlotTrack(options={"source": "raw", "axis": False})
    track.bind(tree, {"A": KNOWN}, columns=[f"o{i}" for i in range(len(KNOWN))])
    ctx, _ = draw(track, tree, context_for)
    axis = track.value_axis(ctx)
    assert axis.hi == pytest.approx(100.0)
    assert axis.lo == pytest.approx(1.0)


def test_a_box_plot_does_not_force_zero_onto_the_axis(tree, context_for):
    """A distribution encodes position, not length, so the axis may be tight."""
    track = BoxPlotTrack(options={"source": "raw", "axis": False})
    track.bind(tree, {"A": [40.0, 41.0, 42.0, 43.0, 44.0]},
               columns=list("abcde"))
    ctx, _ = draw(track, tree, context_for)
    assert track.value_axis(ctx).lo == pytest.approx(40.0)


def test_legend_explains_the_glyph_and_the_whisker_rule():
    track = BoxPlotTrack(options={"whisker_factor": 2.0})
    labels = [i.label for i in track.legend().items]
    assert any("2 x IQR" in label for label in labels)
    assert any("median" in label for label in labels)
    assert any("outlier" in label for label in labels)


def test_glyph_colours_are_configurable(tree, context_for):
    track = BoxPlotTrack(options={
        "source": "raw", "axis": False, "box_color": "#c8d8ff",
        "line_color": "#203040", "median_color": "#ff0000",
        "outlier_color": "#00aa00", "border_color": "#000000",
        "border_width": 0.8})
    track.bind(tree, {"A": KNOWN}, columns=[f"o{i}" for i in range(len(KNOWN))])
    _, scene = draw(track, tree, context_for)
    box = next(m for m in scene.iter_marks() if isinstance(m, RectsMark))
    assert box.fills[0].hex == "#c8d8ff"
    assert box.paint.stroke.hex == "#000000"
    strokes = [m.paint.stroke.hex for m in scene.iter_marks()
               if isinstance(m, PolylineMark)]
    assert strokes.count("#ff0000") == 1
    assert strokes.count("#203040") == 3
    dot = next(m for m in scene.iter_marks() if isinstance(m, EllipseMark))
    assert dot.paint.fill.hex == "#00aa00"


def test_legend_swatches_follow_the_configured_colours():
    track = BoxPlotTrack(options={"box_color": "#c8d8ff", "line_color": "#203040"})
    colors = {i.label: i.color.hex for i in track.legend().items}
    assert colors["median"] == "#203040"
    assert colors["interquartile range (Q1 to Q3)"] == "#c8d8ff"
