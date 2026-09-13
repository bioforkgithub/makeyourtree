# SPDX-License-Identifier: MIT
"""External text labels: measurement, alignment and the polar flip."""

from __future__ import annotations

import pytest

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import Anchor, TextMark
from makeyourtree.style.color import parse_color
from makeyourtree.tracks.base import TrackData
from makeyourtree.tracks.text import TextLabelTrack
from helpers import ROW_HEIGHT, TOP_Y, all_marks, draw, make_context

LABELS = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")


def labels(ctx, texts=LABELS, **options) -> TextLabelTrack:
    rows = {nid: [t] for nid, t in zip(ctx.tip_ids(), texts) if t is not None}
    return TextLabelTrack(title="", data=TrackData(columns=["label"], rows=rows),
                          options=dict(options))


def texts(scene) -> list[TextMark]:
    return [m for m in all_marks(scene) if isinstance(m, TextMark)]


def test_measure_is_the_widest_label_plus_the_margin(rect_ctx):
    track = labels(rect_ctx, margin=5.0, size=12.0)
    widest = max(rect_ctx.metrics.advance(t, 12.0,
                                          family=rect_ctx.theme.font_family)
                 for t in LABELS)
    assert track.measure(rect_ctx) == pytest.approx(5.0 + widest)


def test_measure_respects_a_width_cap(rect_ctx):
    track = labels(rect_ctx, margin=0.0, max_width=10.0)
    assert track.measure(rect_ctx) == pytest.approx(10.0)


def test_one_mark_per_labelled_tip(rect_ctx):
    track = labels(rect_ctx)
    marks = texts(draw(track, rect_ctx))
    assert [m.text for m in marks] == list(LABELS)
    assert [m.tag for m in marks] == rect_ctx.tip_ids()


def test_labels_sit_on_their_row_centres(rect_ctx):
    marks = texts(draw(labels(rect_ctx), rect_ctx))
    assert [m.y for m in marks] == pytest.approx(
        [TOP_Y + (i + 0.5) * ROW_HEIGHT for i in range(8)])


def test_empty_and_absent_values_draw_nothing(rect_ctx):
    track = labels(rect_ctx, ("alpha", "", None, "delta", "e", "f", "g", "h"))
    assert len(texts(draw(track, rect_ctx))) == 6


def test_alignment_moves_the_anchor_across_the_column(rect_ctx):
    left = texts(draw(labels(rect_ctx, align="start", margin=0.0), rect_ctx))
    right = texts(draw(labels(rect_ctx, align="end", margin=0.0), rect_ctx))
    width = labels(rect_ctx).text_width(rect_ctx)
    assert left[0].style.anchor is Anchor.START
    assert right[0].style.anchor is Anchor.END
    assert right[0].x - left[0].x == pytest.approx(width)


def test_style_options_reach_the_mark(rect_ctx):
    track = labels(rect_ctx, bold=True, italic=True, size=13.0,
                   color="#123456", letter_spacing=0.5, rotation=30.0)
    mark = texts(draw(track, rect_ctx))[0]
    assert mark.style.weight == 700
    assert mark.style.italic is True
    assert mark.style.size == 13.0
    assert mark.style.color == parse_color("#123456")
    assert mark.style.letter_spacing == 0.5
    assert mark.rotation == pytest.approx(30.0)


def test_per_row_colour_column_overrides_the_default(rect_ctx):
    rows = {nid: [f"s{i}", "#ff0000" if i == 0 else None]
            for i, nid in enumerate(rect_ctx.tip_ids())}
    track = TextLabelTrack(data=TrackData(columns=["label", "color"], rows=rows),
                           options={"color_column": 1, "color": "#000000"})
    marks = texts(draw(track, rect_ctx))
    assert marks[0].style.color == parse_color("#ff0000")
    assert marks[1].style.color == parse_color("#000000")


def test_labels_are_ellipsised_to_the_cap(rect_ctx):
    cap = 18.0
    track = labels(rect_ctx, max_width=cap)
    rendered = [m.text for m in texts(draw(track, rect_ctx))]
    assert any(t.endswith("…") for t in rendered)
    for text in rendered:
        assert rect_ctx.metrics.advance(
            text, rect_ctx.theme.label_size,
            family=rect_ctx.theme.font_family) <= cap


def test_polar_labels_flip_on_the_left_half(tree):
    """Without the flip half a circular figure reads upside down."""
    ctx = make_context(tree, LayoutMode.CIRCULAR)
    marks = texts(draw(labels(ctx, align="start"), ctx))
    flipped = []
    for i, m in enumerate(marks):
        place = ctx.projector.text(i + 0.5, 0.0, Anchor.START)
        assert m.rotation == pytest.approx(place.rotation)
        assert m.style.anchor is place.anchor
        flipped.append(place.flipped)
    assert any(flipped) and not all(flipped), "the fixture must span both halves"
    for m, was_flipped in zip(marks, flipped):
        assert (m.style.anchor is Anchor.END) is was_flipped
        upright = (m.rotation + 180.0) % 360.0 - 180.0
        assert -90.0 <= upright <= 90.0, "no label ends up upside down"


def test_rotation_can_be_pinned_to_the_page(tree):
    ctx = make_context(tree, LayoutMode.RADIAL)
    marks = texts(draw(labels(ctx, rotate_with_layout=False), ctx))
    assert all(m.rotation == 0.0 for m in marks)


def test_legend_is_empty(rect_ctx):
    assert not labels(rect_ctx).legend()
