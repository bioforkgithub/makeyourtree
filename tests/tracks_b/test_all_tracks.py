# SPDX-License-Identifier: MIT
"""Contract tests every track in this group has to satisfy.

The point of band space is that one implementation serves every rooted layout,
so the same track object is asked to draw itself in all four of them and the
results are checked for the properties the contract promises: marks appear,
``measure`` does not mutate, absent data leaves a hole rather than a zero, and
the legend says something.
"""

from __future__ import annotations

import copy

import pytest
from _support import ROW_HEIGHT, TOP_Y, build_tree, mark_points, node_id

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import Layer, Scene, TextMark
from makeyourtree.tracks.bars import BarChartTrack
from makeyourtree.tracks.boxplot import BoxPlotTrack
from makeyourtree.tracks.connections import ConnectionsTrack
from makeyourtree.tracks.domains import DomainArchitectureTrack
from makeyourtree.tracks.line import LineChartTrack
from makeyourtree.tracks.pie import PieChartTrack

TIPS = ("A", "B", "C", "D", "E")
WITH_DATA = ("A", "B", "C", "D")
"""Every builder below leaves tip E without data, on purpose."""


def bar(tree, names=WITH_DATA, **options):
    track = BarChartTrack(title="bars", options={"axis": False, **options})
    track.bind(tree, {n: [3.0 + i] for i, n in enumerate(names)}, columns=["count"])
    return track


def stacked_bar(tree, names=WITH_DATA, **options):
    track = BarChartTrack(title="stack", options={"axis": False, **options})
    track.bind(tree, {n: [1.0 + i, 2.0, 0.5] for i, n in enumerate(names)},
               columns=["a", "b", "c"])
    return track


def boxplot(tree, names=WITH_DATA, **options):
    track = BoxPlotTrack(title="spread",
                         options={"axis": False, "source": "raw", **options})
    track.bind(tree, {n: [1.0 + i, 4.0 + i, 6.0 + i, 7.0 + i, 20.0 + i]
                      for i, n in enumerate(names)},
               columns=["o1", "o2", "o3", "o4", "o5"])
    return track


def pie(tree, names=WITH_DATA, **options):
    track = PieChartTrack(title="shares", options={"radius": 6.0, **options})
    track.bind(tree, {n: [1.0 + i, 3.0, 2.0] for i, n in enumerate(names)},
               columns=["red", "green", "blue"])
    return track


def domains(tree, names=WITH_DATA, **options):
    track = DomainArchitectureTrack(title="architecture", options=dict(options))
    track.bind(tree, {n: [400 + 50 * i, "20|150|rect|#cc4444|Kinase",
                          "200|330|ellipse|#4466cc|Helicase"]
                      for i, n in enumerate(names)},
               columns=["length", "f1", "f2"])
    return track


def line(tree, names=WITH_DATA, **options):
    track = LineChartTrack(title="series",
                           options={"zero_line": False, **options})
    track.bind(tree, {n: [1.0 + i, 4.0, -2.0, 3.5] for i, n in enumerate(names)},
               columns=["t1", "t2", "t3", "t4"])
    return track


def connections(tree, names=WITH_DATA, **options):
    track = ConnectionsTrack(title="links", options=dict(options))
    pairs = [(names[i], names[(i + 1) % len(names)]) for i in range(len(names))]
    track.bind(tree, {str(i): [a, b, 1.0 + i, "#aa3355", None, f"link {i}"]
                      for i, (a, b) in enumerate(pairs)})
    return track


BUILDERS = (bar, stacked_bar, boxplot, pie, domains, line, connections)
IDS = [b.__name__ for b in BUILDERS]


@pytest.fixture(params=BUILDERS, ids=IDS)
def builder(request):
    return request.param


def test_draws_in_every_rooted_mode(builder, tree, mode, context_for, scene):
    track = builder(tree)
    ctx = context_for(tree, mode)
    ctx.offset = 24.0
    track.draw(ctx, scene.sink(track.default_layer))
    assert scene.count() > 0, f"{track.type_id} drew nothing in {mode.value}"
    for mark in scene.iter_marks():
        for x, y in mark_points(mark):
            assert x == x and y == y, "NaN in projected geometry"


def test_measure_is_pure(builder, tree, mode, context_for):
    track = builder(tree)
    ctx = context_for(tree, mode)
    before_options = copy.deepcopy(track.options)
    before_rows = copy.deepcopy(track.data.rows)
    first = track.measure(ctx)
    ctx_snapshot = (ctx.offset, ctx.index, len(ctx.frame.tips))
    second = track.measure(ctx)
    assert first == second
    assert track.options == before_options
    assert track.data.rows == before_rows
    assert (ctx.offset, ctx.index, len(ctx.frame.tips)) == ctx_snapshot


def test_legend_is_populated(builder, tree):
    legend = builder(tree).legend()
    assert legend, "track contributed no legend entries"
    assert all(item.label for item in legend.items)


@pytest.mark.parametrize("builder", BUILDERS[:-1], ids=IDS[:-1])
def test_tip_without_data_gets_no_mark(builder, tree, context_for):
    """The row of a tip with no value must stay empty -- a gap, not a zero.

    Checked in a rectangular layout, where a row is a horizontal band and the
    assertion can be stated directly in scene coordinates.
    """
    track = builder(tree)
    ctx = context_for(tree, LayoutMode.RECTANGULAR, offset=24.0)
    scene = Scene()
    track.draw(ctx, scene.sink(track.default_layer))
    empty_row = ctx.frame.row_span(node_id(tree, "E"))
    lo = TOP_Y + empty_row[0] * ROW_HEIGHT
    hi = TOP_Y + empty_row[1] * ROW_HEIGHT
    for mark in scene.iter_marks():
        if isinstance(mark, TextMark):
            continue
        for _x, y in mark_points(mark):
            assert not (lo < y < hi), f"{track.type_id} drew inside the empty row"


def test_every_track_type_is_registered():
    from makeyourtree.tracks.base import get_track_class
    for type_id, klass in (("bar-chart", BarChartTrack),
                           ("box-plot", BoxPlotTrack),
                           ("pie-chart", PieChartTrack),
                           ("domain-architecture", DomainArchitectureTrack),
                           ("line-chart", LineChartTrack),
                           ("connections", ConnectionsTrack)):
        assert get_track_class(type_id) is klass


def test_tracks_round_trip_through_dicts(tree):
    from makeyourtree.tracks.base import Track
    original = stacked_bar(tree, bar_gap=0.35)
    revived = Track.from_dict(original.to_dict())
    assert isinstance(revived, BarChartTrack)
    assert revived.data.rows == original.data.rows
    assert revived.data.columns == original.data.columns
    assert revived.opt("bar_gap") == original.opt("bar_gap")


def test_default_layers():
    """Only connections leaves the track band; everything else stacks."""
    assert ConnectionsTrack.default_layer is Layer.CONNECTIONS
    for klass in (BarChartTrack, BoxPlotTrack, PieChartTrack,
                  DomainArchitectureTrack, LineChartTrack):
        assert klass.default_layer is Layer.TRACKS


def test_builders_leave_one_tip_unbound(tree):
    """Guards the premise of the gap test above."""
    assert set(TIPS) - set(WITH_DATA) == {"E"}
    assert build_tree(TIPS).by_name("E") is not None
