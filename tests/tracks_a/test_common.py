# SPDX-License-Identifier: MIT
"""Contract tests every group-A track must satisfy."""

from __future__ import annotations

import pytest

from makeyourtree.layout.params import LayoutMode
from makeyourtree.tracks.base import Track, get_track_class, track_types
from helpers import (MODES, ROW_HEIGHT, TIP_TRACKS, TOP_Y, TRACK_FACTORIES,
                     draw, make_context, scene_points, snapshot)

ALL_TRACKS = tuple(TRACK_FACTORIES)


@pytest.mark.parametrize("kind", ALL_TRACKS)
def test_draws_in_every_rooted_mode(tree, kind):
    """The band-space contract: one implementation, four layouts, no branches."""
    for mode in MODES:
        ctx = make_context(tree, mode)
        track = TRACK_FACTORIES[kind](ctx)
        scene = draw(track, ctx)
        assert scene.count() > 0, f"{kind} drew nothing in {mode.value}"
        for x, y in scene_points(scene):
            assert x == x and y == y, f"{kind} produced a NaN in {mode.value}"
            assert abs(x) < 1e6 and abs(y) < 1e6


@pytest.mark.parametrize("kind", ALL_TRACKS)
def test_measure_is_pure(tree, kind):
    """``measure`` runs before offsets are final and must be repeatable."""
    for mode in MODES:
        ctx = make_context(tree, mode)
        track = TRACK_FACTORIES[kind](ctx)
        before = snapshot(track)
        first = track.measure(ctx)
        second = track.measure(ctx)
        assert first == second
        assert first >= 0.0
        assert snapshot(track) == before


@pytest.mark.parametrize("kind", ALL_TRACKS)
def test_measure_does_not_depend_on_draw(tree, kind):
    """Drawing must not change what the track claims to need next time."""
    ctx = make_context(tree, LayoutMode.RECTANGULAR)
    track = TRACK_FACTORIES[kind](ctx)
    before = track.measure(ctx)
    draw(track, ctx)
    assert track.measure(ctx) == before


@pytest.mark.parametrize("kind", TIP_TRACKS)
def test_tip_without_data_leaves_a_gap(tree, kind):
    """Missing data is a hole, never a zero and never a default colour."""
    ctx = make_context(tree, LayoutMode.RECTANGULAR)
    track = TRACK_FACTORIES[kind](ctx)
    blank = ctx.tip_ids()[3]
    track.data.rows.pop(blank)

    lo, hi = ctx.rows_of(blank)
    y0 = TOP_Y + lo * ROW_HEIGHT + 2.0
    y1 = TOP_Y + hi * ROW_HEIGHT - 2.0
    scene = draw(track, ctx)
    assert scene.count() > 0
    intruders = [p for p in scene_points(scene) if y0 < p[1] < y1]
    assert not intruders, f"{kind} drew into the empty row: {intruders[:3]}"


@pytest.mark.parametrize("kind", ALL_TRACKS)
def test_legend_matches_content(tree, kind):
    ctx = make_context(tree, LayoutMode.RECTANGULAR)
    track = TRACK_FACTORIES[kind](ctx)
    legend = track.legend()
    if kind == "text-labels":
        assert not legend, "a prose column has nothing to put in a swatch"
        return
    assert legend, f"{kind} has categories but produced no legend"
    assert legend.kind in ("categorical", "continuous", "scale")
    for item in legend.items:
        assert item.label
        assert item.color is not None or item.gradient or item.value_range


@pytest.mark.parametrize("kind", ALL_TRACKS)
def test_registered_and_round_trips(tree, kind):
    ctx = make_context(tree, LayoutMode.RECTANGULAR)
    track = TRACK_FACTORIES[kind](ctx)
    assert get_track_class(kind) is type(track)
    assert type(track) in track_types()
    assert track.display_name

    clone = Track.from_dict(track.to_dict())
    assert type(clone) is type(track)
    assert clone.data.columns == track.data.columns
    assert set(clone.data.rows) == set(track.data.rows)


@pytest.mark.parametrize("kind", ALL_TRACKS)
def test_options_extend_the_base_schema(tree, kind):
    ctx = make_context(tree, LayoutMode.RECTANGULAR)
    track = TRACK_FACTORIES[kind](ctx)
    for key in Track.default_options():
        assert key in track.options, f"{kind} dropped base option {key}"
    assert len(track.options) > len(Track.default_options())


@pytest.mark.parametrize("kind", ALL_TRACKS)
def test_empty_data_draws_nothing_and_measures(tree, kind):
    """An unbound track is a normal state in the UI, not an error."""
    ctx = make_context(tree, LayoutMode.RECTANGULAR)
    empty = type(TRACK_FACTORIES[kind](ctx))(title="empty")
    assert empty.measure(ctx) >= 0.0
    scene = draw(empty, ctx)
    assert scene.count() == 0
