# SPDX-License-Identifier: MIT
"""Two-phase track stacking.

``measure`` is declared pure by :mod:`makeyourtree.tracks.base`; the compositor has
to freeze every offset before the first ``draw`` so that a badly behaved track
cannot shift the tracks that follow it.
"""
from __future__ import annotations

import pytest

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.layout.params import LayoutMode
from makeyourtree.render.svg import render_svg
from makeyourtree.scene.compose import compose
from makeyourtree.scene.marks import Layer, Paint, RectMark
from makeyourtree.style.color import Color
from makeyourtree.style.theme import Theme
from makeyourtree.tracks.base import Legend, Track, TrackContext

from _render_support import build_tree, make_document, parse_svg


class ProbeTrack(Track):
    """Records the order and the offsets the compositor hands it."""

    type_id = "test.probe"
    display_name = "Probe"

    def __init__(self, thickness: float = 20.0, *, log: list | None = None,
                 greedy: bool = False, **kw) -> None:
        super().__init__(**kw)
        self.thickness = thickness
        self.log = log if log is not None else []
        self.greedy = greedy
        self.draw_offsets: list[float] = []

    def measure(self, ctx: TrackContext) -> float:
        self.log.append(("measure", self.id, ctx.offset, ctx.index))
        return self.thickness

    def draw(self, ctx: TrackContext, sink) -> None:
        self.log.append(("draw", self.id, ctx.offset, ctx.index))
        self.draw_offsets.append(ctx.offset)
        if self.greedy:
            # A track trying to grow mid-draw must not move anyone else.
            self.thickness *= 4.0
        box = ctx.projector.rect(0.0, ctx.frame.n_rows, ctx.offset,
                                 ctx.offset + self.thickness)
        if box is not None:
            sink.add(RectMark(paint=Paint.filled(Color(200, 220, 240)),
                              x=box[0], y=box[1], w=box[2], h=box[3]))

    def legend(self) -> Legend:
        return Legend(title=self.title)


def stacked_document(*thicknesses: float, **kw):
    document = make_document(build_tree(), **kw)
    log: list = []
    for i, thickness in enumerate(thicknesses):
        document.add_track(ProbeTrack(thickness, log=log, id=f"probe{i}",
                                      title=f"probe{i}"))
    return document, log


def test_all_measures_run_before_any_draw():
    document, log = stacked_document(10.0, 20.0, 30.0)
    compose(document)
    phases = [entry[0] for entry in log]
    assert phases == ["measure"] * 3 + ["draw"] * 3


def test_offsets_accumulate_with_the_theme_gap():
    theme = Theme(track_margin=14.0, track_gap=8.0)
    document, log = stacked_document(10.0, 20.0, 30.0, theme=theme)
    scene = compose(document)
    frame = scene.metadata["frame"]
    draws = [entry[2] for entry in log if entry[0] == "draw"]
    first = frame.tip_offset + theme.track_margin
    assert draws == pytest.approx([
        first,
        first + 10.0 + theme.track_gap,
        first + 10.0 + theme.track_gap + 20.0 + theme.track_gap,
    ])


def test_measure_offsets_match_the_offsets_drawing_receives():
    document, log = stacked_document(12.0, 7.0)
    compose(document)
    measured = [entry[2] for entry in log if entry[0] == "measure"]
    drawn = [entry[2] for entry in log if entry[0] == "draw"]
    assert measured == pytest.approx(drawn)


def test_a_track_growing_during_draw_cannot_move_the_next_one():
    document, log = stacked_document(10.0, 10.0)
    document.tracks[0].greedy = True
    compose(document)
    drawn = [entry[2] for entry in log if entry[0] == "draw"]
    assert drawn[1] - drawn[0] == pytest.approx(10.0 + Theme().track_gap)


def test_per_track_gap_before_overrides_the_theme_gap():
    theme = Theme(track_gap=8.0)
    document, log = stacked_document(10.0, 10.0, theme=theme)
    document.tracks[1].options["gap_before"] = 40.0
    compose(document)
    drawn = [entry[2] for entry in log if entry[0] == "draw"]
    assert drawn[1] - drawn[0] == pytest.approx(50.0)


def test_hidden_tracks_are_neither_measured_nor_drawn():
    document, log = stacked_document(10.0, 10.0)
    document.tracks[0].visible = False
    compose(document)
    assert {entry[1] for entry in log} == {"probe1"}


def test_track_index_is_its_position_in_the_visible_stack():
    document, log = stacked_document(5.0, 5.0, 5.0)
    compose(document)
    assert [entry[3] for entry in log if entry[0] == "draw"] == [0, 1, 2]


def test_track_marks_land_in_the_declared_layer():
    document, _ = stacked_document(15.0)
    scene = compose(document)
    assert scene.layers.get(Layer.TRACKS)
    parse_svg(render_svg(scene))


def test_tracks_widen_the_page_they_are_drawn_on():
    bare = compose(make_document(build_tree()))
    document, _ = stacked_document(120.0)
    assert compose(document).width > bare.width


def test_interactive_flag_reaches_the_track():
    seen: list[bool] = []

    class Watcher(ProbeTrack):
        type_id = "test.probe-watch"

        def draw(self, ctx, sink):
            seen.append(ctx.interactive)

    document = make_document(build_tree())
    document.add_track(Watcher(10.0))
    compose(document, interactive=True)
    compose(document, interactive=False)
    assert seen == [True, False]


def test_missing_projector_is_reported_rather_than_silently_dropping_tracks():
    document, _ = stacked_document(10.0, mode=LayoutMode.UNROOTED)
    sink = DiagnosticSink()
    scene = compose(document, sink=sink)
    frame = scene.metadata["frame"]
    if frame.projector is None:
        assert any(d.code == "compose.no-projector" for d in sink)
    else:
        assert scene.layers.get(Layer.TRACKS)
