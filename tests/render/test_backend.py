# SPDX-License-Identifier: MIT
"""The single scene walker: layer order, overlay suppression and dispatch."""
from __future__ import annotations

import pytest

from makeyourtree.core.errors import RenderError
from makeyourtree.render.backend import DISPATCH, dispatch_mark, render
from makeyourtree.scene.marks import (EllipseMark, GroupMark, ImageMark, Layer,
                                  LinesMark, Mark, Paint, PathMark, PolygonMark,
                                  PolylineMark, RectMark, RectsMark, Scene,
                                  TextMark)
from makeyourtree.style.color import Color

BLACK = Color(0, 0, 0)


def test_dispatch_table_covers_every_concrete_mark_type():
    concrete = {PathMark, LinesMark, PolylineMark, PolygonMark, RectMark,
                RectsMark, EllipseMark, TextMark, ImageMark, GroupMark}
    assert set(DISPATCH) == concrete
    assert len(set(DISPATCH.values())) == len(concrete)


def test_render_visits_layers_in_painting_order(recorder):
    scene = Scene(width=10, height=10)
    # Added back-to-front-shuffled; the walker must reorder them.
    scene.add(TextMark(x=0, y=0, text="label"), Layer.LABELS)
    scene.add(LinesMark(paint=Paint.stroked(BLACK), coords=[0, 0, 1, 1]),
              Layer.BRANCHES)
    scene.add(RectMark(paint=Paint.filled(BLACK), w=1, h=1), Layer.UNDERLAY)
    result = render(scene, recorder)
    assert result == b"done"
    assert recorder.began == 1
    assert recorder.layers == [Layer.UNDERLAY, Layer.BRANCHES, Layer.LABELS]
    assert [name for name, _ in recorder.calls] == [
        "draw_rect", "draw_lines", "draw_text"]


def test_render_skips_overlay_unless_asked(recorder):
    scene = Scene(width=10, height=10)
    scene.add(RectMark(paint=Paint.filled(BLACK), w=1, h=1), Layer.OVERLAY)
    scene.add(RectMark(paint=Paint.filled(BLACK), w=1, h=1), Layer.LEGEND)
    render(scene, recorder)
    assert recorder.layers == [Layer.LEGEND]

    recorder.calls.clear()
    recorder.layers.clear()
    render(scene, recorder, include_overlay=True)
    assert recorder.layers == [Layer.OVERLAY, Layer.LEGEND]


def test_empty_layers_are_not_opened(recorder):
    scene = Scene(width=1, height=1)
    scene.layers[Layer.TRACKS] = []
    scene.add(RectMark(paint=Paint.filled(BLACK), w=1, h=1), Layer.DECOR)
    render(scene, recorder)
    assert recorder.layers == [Layer.DECOR]


def test_group_marks_are_handed_over_whole(recorder):
    child = RectMark(paint=Paint.filled(BLACK), w=1, h=1)
    scene = Scene(width=1, height=1)
    scene.add(GroupMark(marks=(child, child), dx=2, dy=3), Layer.TRACKS)
    render(scene, recorder)
    # The walker does not flatten groups: the backend owns the transform.
    assert [name for name, _ in recorder.calls] == ["draw_group"]


def test_unknown_mark_type_is_reported_not_ignored(recorder):
    class Alien(Mark):
        __slots__ = ()

    with pytest.raises(RenderError, match="Alien"):
        dispatch_mark(recorder, Alien())


def test_mark_subclass_falls_back_to_its_base_handler(recorder):
    class TaggedRect(RectMark):
        __slots__ = ()

    dispatch_mark(recorder, TaggedRect(paint=Paint.filled(BLACK), w=1, h=1))
    assert recorder.calls[0][0] == "draw_rect"


def test_backend_without_layer_hooks_still_renders():
    class Bare:
        def __init__(self):
            self.seen = []

        def begin(self, scene):
            pass

        def end(self):
            return b""

        def draw_lines(self, mark):
            self.seen.append(mark)

    scene = Scene(width=1, height=1)
    scene.add(LinesMark(paint=Paint.stroked(BLACK), coords=[0, 0, 1, 1]),
              Layer.BRANCHES)
    bare = Bare()
    assert render(scene, bare) == b""
    assert len(bare.seen) == 1
