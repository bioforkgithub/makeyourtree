# SPDX-License-Identifier: MIT
"""Binary matrix: three states, three renderings."""

from __future__ import annotations

import math

import pytest

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import PathMark, TextMark
from makeyourtree.style.color import parse_color
from makeyourtree.tracks.base import TrackData
from makeyourtree.tracks.binary import (ABSENT, PRESENT, UNKNOWN,
                                    BinaryMatrixTrack, classify)
from helpers import all_marks, draw, make_context


def binary(ctx, rows_by_tip, columns=("a", "b", "c"), **options):
    rows = {nid: list(v) for nid, v in zip(ctx.tip_ids(), rows_by_tip)}
    return BinaryMatrixTrack(title="", data=TrackData(columns=list(columns),
                                                      rows=rows),
                             options=dict(options))


def symbols(scene):
    return [m for m in all_marks(scene) if isinstance(m, PathMark)]


@pytest.mark.parametrize("value,state", [
    (1, PRESENT), (0, ABSENT), (-1, UNKNOWN), (None, UNKNOWN),
    ("1", PRESENT), ("0", ABSENT), ("", UNKNOWN), ("-", UNKNOWN),
    (True, PRESENT), (False, ABSENT),
    ("yes", PRESENT), ("NO", ABSENT), ("+", PRESENT), ("absent", ABSENT),
    ("maybe", UNKNOWN), (0.5, UNKNOWN)])
def test_classify_is_lenient_but_never_invents_a_negative(value, state):
    assert classify(value) == state


def test_three_states_get_three_renderings(rect_ctx):
    track = binary(rect_ctx, [[1, 0, None]], columns=("a", "b", "c"),
                   column_labels=False)
    marks = symbols(draw(track, rect_ctx))
    assert len(marks) == 2, "the unknown cell draws nothing at all"
    present, absent = marks
    assert present.paint.fill is not None and present.paint.stroke is None
    assert absent.paint.fill is None and absent.paint.stroke is not None
    assert absent.paint.width > 0


def test_absence_can_be_hidden_entirely(rect_ctx):
    track = binary(rect_ctx, [[1, 0, None]], column_labels=False,
                   show_absent=False)
    assert len(symbols(draw(track, rect_ctx))) == 1


def test_columns_are_spaced_across_the_measured_width(rect_ctx):
    track = binary(rect_ctx, [[1, 1, 1]], column_labels=False,
                   cell_size=20.0, margin=6.0)
    assert track.measure(rect_ctx) == pytest.approx(6.0 + 3 * 20.0)
    xs = []
    for mark in symbols(draw(track, rect_ctx)):
        pts = [(s[1], s[2]) for s in mark.segments if s[0] in ("M", "L")]
        xs.append(sum(p[0] for p in pts) / len(pts))
    base = rect_ctx.projector.base_x + 6.0
    assert xs == pytest.approx([base + 10.0, base + 30.0, base + 50.0])


def test_symbol_fits_inside_its_cell(rect_ctx):
    track = binary(rect_ctx, [[1, 1, 1]], column_labels=False, cell_size=40.0)
    mark = symbols(draw(track, rect_ctx))[0]
    ys = [s[2] for s in mark.segments if s[0] in ("M", "L")]
    assert max(ys) - min(ys) <= 16.0, "a symbol may not spill into the next row"


def test_per_column_shapes_and_colours(rect_ctx):
    track = binary(rect_ctx, [[1, 1]], columns=("a", "b"), column_labels=False,
                   column_shapes=["circle", "star"],
                   column_colors=["#ff0000", "#00ff00"])
    marks = symbols(draw(track, rect_ctx))
    assert marks[0].paint.fill == parse_color("#ff0000")
    assert marks[1].paint.fill == parse_color("#00ff00")
    # A star is a twelve-vertex polygon; a circle is two arcs.
    assert any(s[0] == "A" for s in marks[0].segments)
    assert not any(s[0] == "A" for s in marks[1].segments)


def test_columns_get_distinct_palette_colours_by_default(rect_ctx):
    track = binary(rect_ctx, [[1, 1, 1]])
    colors = track.column_colors()
    assert len(set(colors)) == 3


def test_column_labels_are_one_mark_each(rect_ctx):
    track = binary(rect_ctx, [[1, 1, 1]])
    texts = [m for m in all_marks(draw(track, rect_ctx)) if isinstance(m, TextMark)]
    assert [m.text for m in texts] == ["a", "b", "c"]
    assert all(m.rotation != 0.0 for m in texts), "linear column labels are rotated"


def test_polar_column_labels_follow_the_band(tree):
    """The same band-relative rotation reads as radial-vs-arc in each mode."""
    ctx = make_context(tree, LayoutMode.CIRCULAR)
    track = binary(ctx, [[1, 1, 1]])
    texts = [m for m in all_marks(draw(track, ctx)) if isinstance(m, TextMark)]
    assert len(texts) == 3
    # Rotation is whatever the projector chose for that row -- including its
    # flip on the left half -- plus the band-relative label rotation.
    placed = ctx.projector.text(-0.3, 0.0)
    assert all(m.rotation == pytest.approx(placed.rotation - 90.0) for m in texts)
    # -90 from the outward direction is the arc, so the text runs across rows.
    ux, uy = ctx.projector.outward(-0.3)
    dx = math.cos(math.radians(texts[0].rotation))
    dy = math.sin(math.radians(texts[0].rotation))
    assert abs(dx * ux + dy * uy) < 1e-9


def test_legend_has_one_entry_per_column(rect_ctx):
    track = binary(rect_ctx, [[1, 0, 1]], column_shapes=["circle", "star", "check"])
    legend = track.legend()
    assert [i.label for i in legend.items] == ["a", "b", "c"]
    assert [i.shape for i in legend.items] == ["circle", "star", "check"]
    assert all(i.color is not None for i in legend.items)


def test_rows_shorter_than_the_header_are_unknown_not_absent(rect_ctx):
    track = binary(rect_ctx, [[1]], columns=("a", "b", "c"), column_labels=False)
    assert len(symbols(draw(track, rect_ctx))) == 1
