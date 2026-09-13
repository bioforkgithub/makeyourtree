# SPDX-License-Identifier: MIT
"""Legend layout: entries must be measured, placed clear of the figure, and
reported back with the space they consume."""
from __future__ import annotations

from makeyourtree.render.svg import render_svg
from makeyourtree.scene.compose import compose
from makeyourtree.scene.legend import build_legend
from makeyourtree.scene.marks import (EllipseMark, Layer, LinesMark, Mark,
                                  RectMark, RectsMark, TextMark)
from makeyourtree.style.color import Color
from makeyourtree.style.theme import Theme
from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics
from makeyourtree.tracks.base import Legend, LegendItem, Track, TrackContext

from _render_support import build_tree, make_document, parse_svg

BOUNDS = (0.0, 0.0, 200.0, 120.0)
METRICS = CachedMetrics(FallbackMetrics())


class FakeTrack(Track):
    """A track that draws nothing; only its legend and thickness matter here."""

    type_id = "test.fake-legend"
    display_name = "Fake"

    def __init__(self, legend: Legend | None = None, thickness: float = 20.0,
                 **kw) -> None:
        super().__init__(**kw)
        self._legend = legend if legend is not None else Legend()
        self.thickness = thickness
        self.measured = 0
        self.drawn: list[float] = []

    def measure(self, ctx: TrackContext) -> float:
        self.measured += 1
        return self.thickness

    def draw(self, ctx: TrackContext, sink) -> None:
        self.drawn.append(ctx.offset)

    def legend(self) -> Legend:
        return self._legend


def categorical(title="Habitat", n=3) -> Legend:
    return Legend(title=title, kind="categorical", items=[
        LegendItem(label=f"category {i}", color=Color(20 * i, 90, 200 - 10 * i))
        for i in range(n)])


def continuous(title="Abundance") -> Legend:
    ramp = (Color(255, 255, 200), Color(60, 20, 120))
    return Legend(title=title, kind="continuous", items=[
        LegendItem(label="", gradient=ramp, value_range=(0.5, 12.75))])


def texts(marks: list[Mark]) -> list[str]:
    return [m.text for m in marks if isinstance(m, TextMark)]


def test_no_tracks_means_no_legend():
    marks, w, h = build_legend([], Theme(), BOUNDS, metrics=METRICS)
    assert marks == [] and w == 0.0 and h == 0.0


def test_tracks_without_legend_items_contribute_nothing():
    marks, w, h = build_legend([FakeTrack(Legend(title="empty"))], Theme(),
                               BOUNDS, metrics=METRICS)
    assert marks == [] and (w, h) == (0.0, 0.0)


def test_categorical_entries_get_a_swatch_and_a_label():
    track = FakeTrack(categorical(n=3))
    marks, width, height = build_legend([track], Theme(), BOUNDS,
                                        metrics=METRICS)
    swatches = [m for m in marks if isinstance(m, RectMark)]
    assert len(swatches) == 3
    assert texts(marks) == ["Habitat", "category 0", "category 1", "category 2"]
    assert width > 0 and height == 0.0
    assert {s.paint.fill for s in swatches} == {
        Color(0, 90, 200), Color(20, 90, 190), Color(40, 90, 180)}


def test_swatch_shapes_follow_the_item():
    legend = Legend(title="Shapes", items=[
        LegendItem(label="dot", color=Color(1, 2, 3), shape="circle"),
        LegendItem(label="rule", color=Color(4, 5, 6), shape="line"),
        LegendItem(label="box", color=Color(7, 8, 9), shape="square")])
    marks, _, _ = build_legend([FakeTrack(legend)], Theme(), BOUNDS,
                               metrics=METRICS)
    kinds = [type(m) for m in marks if not isinstance(m, TextMark)]
    assert kinds == [EllipseMark, LinesMark, RectMark]


def test_continuous_legend_is_a_batched_ramp_with_end_labels():
    marks, _, _ = build_legend([FakeTrack(continuous())], Theme(), BOUNDS,
                               metrics=METRICS)
    bars = [m for m in marks if isinstance(m, RectsMark)]
    assert len(bars) == 1, "a gradient must stay one batched mark"
    assert bars[0].count > 8
    assert bars[0].fills[0] != bars[0].fills[-1]
    assert texts(marks) == ["Abundance", "0.5", "6.62", "12.8"]


def test_labels_start_clear_of_their_swatches():
    theme = Theme()
    track = FakeTrack(categorical(n=2))
    marks, _, _ = build_legend([track], theme, BOUNDS, metrics=METRICS)
    swatch = [m for m in marks if isinstance(m, RectMark)][0]
    label = [m for m in marks if isinstance(m, TextMark)][1]
    assert label.x >= swatch.x + swatch.w + theme.legend_gap * 0.999


def test_reported_width_covers_the_widest_measured_label():
    long_label = Legend(title="t", items=[
        LegendItem(label="a very considerably long category name indeed",
                   color=Color(0, 0, 0))])
    _, width, _ = build_legend([FakeTrack(long_label)], Theme(), BOUNDS,
                               metrics=METRICS)
    expected = METRICS.advance("a very considerably long category name indeed",
                               Theme().legend_size)
    assert width >= expected


def test_right_position_places_the_legend_beside_the_figure():
    marks, width, height = build_legend([FakeTrack(categorical())], Theme(),
                                        BOUNDS, metrics=METRICS)
    assert all(m.x >= BOUNDS[2] for m in marks
               if isinstance(m, (RectMark, TextMark)))
    assert width > 0
    assert height == 0.0, "a right-hand legend must not lengthen the page"


def test_bottom_position_pushes_down_not_sideways():
    theme = Theme(legend_position="bottom")
    marks, width, height = build_legend([FakeTrack(categorical())], theme,
                                        BOUNDS, metrics=METRICS)
    assert width == 0.0 and height > 0.0
    assert all(m.y >= BOUNDS[3] for m in marks if isinstance(m, TextMark))


def test_top_left_position_overlays_and_consumes_nothing():
    theme = Theme(legend_position="top-left")
    marks, width, height = build_legend([FakeTrack(categorical())], theme,
                                        BOUNDS, metrics=METRICS)
    assert marks
    assert (width, height) == (0.0, 0.0)
    assert min(m.y for m in marks if isinstance(m, TextMark)) < BOUNDS[3]


def test_legend_can_be_switched_off_entirely():
    for theme in (Theme(legend_show=False), Theme(legend_position="none")):
        marks, w, h = build_legend([FakeTrack(categorical())], theme, BOUNDS,
                                   metrics=METRICS)
        assert marks == [] and (w, h) == (0.0, 0.0)


def test_several_tracks_stack_without_overlapping():
    tracks = [FakeTrack(categorical(title=f"T{i}", n=2)) for i in range(3)]
    marks, _, _ = build_legend(tracks, Theme(), BOUNDS, metrics=METRICS)
    titles = [m for m in marks if isinstance(m, TextMark)
              and m.text.startswith("T")]
    ys = [m.y for m in titles]
    assert ys == sorted(ys)
    assert all(b - a > Theme().legend_size for a, b in zip(ys, ys[1:]))


# ------------------------------------------------- integration with compose


def test_compose_places_the_legend_and_grows_the_page():
    tree = build_tree()
    bare = compose(make_document(tree))
    document = make_document(tree)
    document.add_track(FakeTrack(categorical(n=4), title="Habitat"))
    with_legend = compose(document)
    assert with_legend.layers.get(Layer.LEGEND)
    assert with_legend.width > bare.width
    assert with_legend.metadata["legend_size"][0] > 0
    parse_svg(render_svg(with_legend))
