# SPDX-License-Identifier: MIT
"""Gradient strip and the OKLab colour ramp."""

from __future__ import annotations

import pytest

from makeyourtree.scene.marks import RectsMark
from makeyourtree.style.color import parse_color
from makeyourtree.tracks.base import TrackData
from makeyourtree.tracks.gradient import (DEFAULT_MISSING, DEFAULT_SEQUENTIAL,
                                      ColorRamp, GradientTrack, to_float)
from helpers import ROW_HEIGHT, all_marks, draw


def gradient(ctx, values, **options) -> GradientTrack:
    rows = {nid: [v] for nid, v in zip(ctx.tip_ids(), values)}
    return GradientTrack(title="", data=TrackData(columns=["v"], rows=rows),
                         options=options)


def only_batch(scene) -> RectsMark:
    batches = [m for m in all_marks(scene) if isinstance(m, RectsMark)]
    assert len(batches) == 1
    return batches[0]


# -------------------------------------------------------------------- ramp


def test_lightness_is_monotone_along_the_ramp():
    """The point of interpolating in OKLab: no dark band in the middle."""
    ramp = ColorRamp()
    lums = [c.luminance for c in ramp.sample(32)]
    assert all(a > b for a, b in zip(lums, lums[1:]))


def test_ends_are_the_requested_stops():
    ramp = ColorRamp(("#ffffff", "#000000"))
    assert ramp.at(0.0) == parse_color("#ffffff")
    assert ramp.at(1.0) == parse_color("#000000")


def test_midpoint_is_not_the_srgb_average():
    """An sRGB midpoint of a saturated pair is darker than the OKLab one."""
    ramp = ColorRamp(("#ff0000", "#0000ff"))
    mid = ramp.at(0.5)
    naive = parse_color("#ff0000").lerp(parse_color("#0000ff"), 0.5)
    assert mid != naive
    assert mid.luminance > naive.luminance


def test_domain_maps_and_clamps():
    ramp = ColorRamp(("#ffffff", "#000000"), (10.0, 20.0))
    assert ramp.normalise(10.0) == pytest.approx(0.0)
    assert ramp.normalise(15.0) == pytest.approx(0.5)
    assert ramp.normalise(-100.0) == 0.0
    assert ramp.normalise(1e9) == 1.0
    assert ramp.normalise("not a number") is None


def test_degenerate_domain_lands_in_the_middle():
    ramp = ColorRamp(("#ffffff", "#000000"), (5.0, 5.0))
    assert ramp.normalise(5.0) == pytest.approx(0.5)
    assert ramp.color(5.0) == ramp.at(0.5)
    assert ramp(5.0) == ramp.color(5.0), "a ramp is usable as a plain callable"


def test_quantisation_bounds_the_distinct_colours():
    ramp = ColorRamp(DEFAULT_SEQUENTIAL, (0.0, 1000.0), steps=16)
    seen = {ramp.color(v) for v in range(1000)}
    assert len(seen) <= 16


def test_missing_colour_is_far_from_every_ramp_colour():
    """"No value" must not read as "a low value"."""
    miss = parse_color(DEFAULT_MISSING)
    for c in ColorRamp().sample(128):
        d = ((c.r - miss.r) ** 2 + (c.g - miss.g) ** 2 + (c.b - miss.b) ** 2) ** 0.5
        assert d > 40, f"{c.hex} is confusable with the missing colour"


def test_to_float_rejects_non_numbers():
    assert to_float("3.5") == 3.5
    assert to_float(None) is None
    assert to_float("n/a") is None
    assert to_float(float("nan")) is None
    assert to_float(float("inf")) is None
    assert to_float(True) is None, "a flag is not a magnitude"


# ------------------------------------------------------------------- track


def test_values_span_the_ramp(rect_ctx):
    track = gradient(rect_ctx, [float(i) for i in range(8)])
    fills = list(only_batch(draw(track, rect_ctx)).fills)
    ramp = track.ramp()
    assert fills[0] == ramp.at(0.0)
    assert fills[-1] == ramp.at(1.0)
    assert track.domain() == (0.0, 7.0)


def test_user_domain_overrides_the_data(rect_ctx):
    track = gradient(rect_ctx, [float(i) for i in range(8)],
                     min_value=-10.0, max_value=10.0)
    assert track.domain() == (-10.0, 10.0)
    fills = list(only_batch(draw(track, rect_ctx)).fills)
    assert fills[0] != track.ramp().at(0.0)


def test_missing_is_a_gap_by_default(rect_ctx):
    track = gradient(rect_ctx, [0.0, 1.0, None, 3.0, 4.0, 5.0, 6.0, 7.0])
    batch = only_batch(draw(track, rect_ctx))
    ys = list(batch.coords)[1::4]
    hs = list(batch.coords)[3::4]
    covered = sum(hs)
    assert covered == pytest.approx(7 * ROW_HEIGHT)
    assert all(h > 0 for h in hs)
    assert ys == sorted(ys)


def test_non_numeric_value_is_a_gap_not_a_zero(rect_ctx):
    track = gradient(rect_ctx, [0.0, 1.0, "n/a", 3.0, 4.0, 5.0, 6.0, 7.0])
    hs = list(only_batch(draw(track, rect_ctx)).coords)[3::4]
    assert sum(hs) == pytest.approx(7 * ROW_HEIGHT)


def test_missing_fill_policy_paints_the_named_colour(rect_ctx):
    track = gradient(rect_ctx, [0.0, 1.0, None, 3.0, 4.0, 5.0, 6.0, 7.0],
                     missing="fill")
    fills = list(only_batch(draw(track, rect_ctx)).fills)
    assert parse_color(DEFAULT_MISSING) in fills


def test_legend_is_a_continuous_bar(rect_ctx):
    track = gradient(rect_ctx, [float(i) for i in range(8)])
    legend = track.legend()
    assert legend.kind == "continuous"
    assert len(legend.items) == 1
    item = legend.items[0]
    assert item.shape == "gradient"
    assert len(item.gradient) == 24
    assert item.value_range == (0.0, 7.0)


def test_legend_gains_a_detached_swatch_when_missing_is_painted(rect_ctx):
    track = gradient(rect_ctx, [float(i) for i in range(8)], missing="fill")
    labels = [i.label for i in track.legend().items]
    assert labels[-1] == "no value"


def test_two_stop_ramp_when_the_mid_colour_is_disabled(rect_ctx):
    track = gradient(rect_ctx, [float(i) for i in range(8)], use_mid=False)
    assert len(track.ramp().stops) == 2
    assert len(gradient(rect_ctx, [1.0]).ramp().stops) == 3
