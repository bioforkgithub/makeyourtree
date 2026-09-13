# SPDX-License-Identifier: MIT
"""Scale behaviour: domains, transforms, binning, and kind inference."""

from __future__ import annotations

import math

import pytest

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.style.color import Color
from makeyourtree.style.palettes import get_palette
from makeyourtree.style.scales import (BinnedScale, CategoricalScale,
                                   ContinuousScale, LegendItem, Scale,
                                   infer_kind, make_scale, quantile_breaks,
                                   to_float)


# ------------------------------------------------------------------ helpers


@pytest.mark.parametrize("raw,want", [
    (1, 1.0), (2.5, 2.5), ("3.25", 3.25), ("  -4 ", -4.0), ("1e3", 1000.0),
    (None, None), ("", None), ("-", None), ("NA", None), ("n/a", None),
    ("abc", None), (float("nan"), None), (float("inf"), None), (True, None),
])
def test_to_float_is_lenient(raw: object, want: float | None) -> None:
    assert to_float(raw) == want


# ---------------------------------------------------------------- continuous


def test_linear_domain_maps_ends_to_ramp_ends() -> None:
    pal = get_palette("viridis")
    s = ContinuousScale(0.0, 10.0, "viridis")
    assert s.normalise(0.0) == 0.0
    assert s.normalise(10.0) == 1.0
    assert s.normalise(2.5) == 0.25
    assert s.color_of(0.0) is pal.colors[0]
    assert s.color_of(10.0) is pal.colors[-1]


def test_reversed_domain_is_sorted_not_rejected() -> None:
    s = ContinuousScale(10.0, 0.0)
    assert (s.vmin, s.vmax) == (0.0, 10.0)


def test_degenerate_domain_lands_mid_ramp() -> None:
    s = ContinuousScale(5.0, 5.0)
    assert s.normalise(5.0) == 0.5
    assert s.color_of(5.0) == s.palette.sample(0.5)


def test_missing_and_unparseable_values_have_no_colour() -> None:
    s = ContinuousScale(0.0, 1.0)
    for v in (None, "", "-", "NA", "not a number", float("nan")):
        assert s.color_of(v) is None


def test_nan_color_is_returned_when_configured() -> None:
    s = ContinuousScale(0.0, 1.0, nan_color="#dddddd")
    assert s.color_of(None) == Color(0xDD, 0xDD, 0xDD)
    labels = [i.label for i in s.legend_items()]
    assert labels[-1] == "no data"


def test_clamp_off_drops_values_outside_the_domain() -> None:
    clamped = ContinuousScale(0.0, 10.0)
    assert clamped.normalise(-5.0) == 0.0 and clamped.normalise(50.0) == 1.0
    free = ContinuousScale(0.0, 10.0, clamp=False)
    assert free.normalise(-5.0) is None
    assert free.color_of(50.0) is None
    assert free.normalise(5.0) == 0.5


def test_mid_makes_the_domain_symmetric() -> None:
    s = ContinuousScale(-2.0, 8.0, "blue-red", mid=0.0)
    assert (s.vmin, s.vmax) == (-8.0, 8.0)
    assert s.kind == "diverging"
    assert s.normalise(0.0) == 0.5
    assert s.color_of(0.0) is get_palette("blue-red").colors[4]
    # A value and its negation must sit the same distance either side of neutral.
    assert s.normalise(3.0) - 0.5 == pytest.approx(0.5 - s.normalise(-3.0))


def test_mid_can_sit_away_from_zero() -> None:
    s = ContinuousScale(0.0, 3.0, "blue-red", mid=1.0)
    assert (s.vmin, s.vmax) == (-1.0, 3.0)
    assert s.normalise(1.0) == 0.5


# ------------------------------------------------------------- transforms


def test_log_transform_spaces_by_decade() -> None:
    s = ContinuousScale(1.0, 1000.0, transform="log")
    assert not s.degraded
    assert s.normalise(10.0) == pytest.approx(1 / 3)
    assert s.normalise(100.0) == pytest.approx(2 / 3)
    # The linear midpoint of the domain is far past the colour midpoint.
    assert s.normalise(500.5) > 0.85


def test_log_scale_rejects_a_non_positive_domain_gracefully() -> None:
    sink = DiagnosticSink()
    s = ContinuousScale(0.0, 100.0, transform="log")
    assert s.degraded and s.transform == "linear"
    assert "positive" in (s.degraded_reason or "")
    # Degrading, not crashing: the scale still colours the whole domain.
    assert s.color_of(0.0) is s.palette.colors[0]
    assert s.normalise(50.0) == pytest.approx(0.5)
    s.report(sink)
    assert [d.code for d in sink.items] == ["scale.transform"]
    assert not sink.has_errors


def test_log_scale_with_negative_domain_also_degrades() -> None:
    assert ContinuousScale(-10.0, -1.0, transform="log").degraded
    assert not ContinuousScale(1e-9, 1.0, transform="log").degraded


def test_non_positive_values_on_a_valid_log_scale_are_no_data() -> None:
    s = ContinuousScale(1.0, 100.0, transform="log")
    assert s.color_of(0.0) is None
    assert s.color_of(-3.0) is None
    assert s.color_of(1.0) is not None


def test_unknown_transform_degrades_rather_than_raising() -> None:
    s = ContinuousScale(0.0, 1.0, transform="sqrt")
    assert s.degraded and s.transform == "linear"


def test_symlog_is_linear_near_zero_and_log_beyond() -> None:
    s = ContinuousScale(-1000.0, 1000.0, transform="symlog", linthresh=1.0)
    assert s.normalise(0.0) == pytest.approx(0.5)
    assert s.normalise(-1000.0) == 0.0 and s.normalise(1000.0) == 1.0
    assert s.normalise(1.0) - 0.5 == pytest.approx(0.5 - s.normalise(-1.0))
    ts = [s.normalise(v) for v in (-1000, -100, -1, 0, 1, 100, 1000)]
    assert all(a < b for a, b in zip(ts, ts[1:]))


def test_ticks_are_evenly_spaced_in_transformed_space() -> None:
    lin = ContinuousScale(0.0, 100.0).ticks(5)
    assert lin == pytest.approx([0, 25, 50, 75, 100])
    log = ContinuousScale(1.0, 10000.0, transform="log").ticks(5)
    assert log == pytest.approx([1, 10, 100, 1000, 10000])
    assert ContinuousScale(1.0, 10.0).ticks(1) == [1.0]


def test_symlog_ticks_are_evenly_spaced_in_normalised_space() -> None:
    # The inverse transform has to be a real inverse, or ticks land off the bar.
    s = ContinuousScale(-100.0, 100.0, transform="symlog")
    ticks = s.ticks(5)
    assert [s.normalise(t) for t in ticks] == pytest.approx([0, 0.25, 0.5, 0.75, 1])
    assert ticks[0] == pytest.approx(-100.0)
    assert ticks[2] == pytest.approx(0.0)
    assert ticks[-1] == pytest.approx(100.0)


# ---------------------------------------------------------------- legends


def test_continuous_legend_gradient_matches_the_cells() -> None:
    s = ContinuousScale(0.0, 1.0, "magma")
    (item,) = s.legend_items()
    assert item.shape == "gradient"
    assert item.value_range == (0.0, 1.0)
    assert item.gradient is not None and len(item.gradient) == 9
    assert item.gradient[0] == s.color_of(0.0)
    assert item.gradient[-1] == s.color_of(1.0)
    assert item.gradient[4] == s.color_of(0.5)


def test_legend_items_are_the_shape_tracks_expect() -> None:
    item = CategoricalScale(["a"]).legend_items()[0]
    assert (item.label, item.shape) == ("a", "square")
    assert isinstance(item, LegendItem)


# --------------------------------------------------------------- categorical


def test_categorical_from_values_assigns_and_looks_up() -> None:
    s = CategoricalScale(["b", "a", "b"], "okabe-ito")
    pal = get_palette("okabe-ito")
    assert s.categories == ["b", "a"]
    assert s.color_of("b") is pal.colors[0]
    assert s.color_of(" a ") is pal.colors[1]


def test_categorical_from_an_explicit_mapping_parses_colours() -> None:
    s = CategoricalScale({"x": "#ff0000", "y": Color(0, 0, 255)})
    assert s.color_of("x") == Color(255, 0, 0)
    assert s.color_of("y") == Color(0, 0, 255)


def test_unknown_and_missing_categories() -> None:
    s = CategoricalScale(["a"])
    assert s.color_of("zzz") is None
    assert s.color_of(None) is None and s.color_of("-") is None
    other = CategoricalScale(["a"], other_color="#999999")
    assert other.color_of("zzz") == Color(0x99, 0x99, 0x99)
    assert other.color_of(None) is None, "missing is not the same as 'other'"
    assert [i.label for i in other.legend_items()] == ["a", "other"]


def test_categorical_legend_follows_first_seen_order() -> None:
    s = CategoricalScale(["gamma", "alpha", "beta"])
    assert [i.label for i in s.legend_items()] == ["gamma", "alpha", "beta"]


# -------------------------------------------------------------------- binned


def test_quantile_breaks_split_the_data_evenly() -> None:
    values = list(range(101))
    breaks = quantile_breaks(values, 4)
    assert breaks == (0.0, 25.0, 50.0, 75.0, 100.0)


def test_quantile_breaks_ignore_junk_and_collapse_ties() -> None:
    assert quantile_breaks(["1", "-", None, "3", "x"], 2) == (1.0, 2.0, 3.0)
    assert quantile_breaks([7, 7, 7], 4) == (7.0, 7.0)
    assert quantile_breaks([], 4) == ()


def test_binned_scale_assigns_classes() -> None:
    s = BinnedScale((0.0, 10.0, 20.0, 30.0), "viridis")
    assert s.n_bins == 3
    assert s.bin_of(0.0) == 0
    assert s.bin_of(9.999) == 0
    assert s.bin_of(10.0) == 1
    assert s.bin_of(29.0) == 2
    assert s.bin_of(30.0) == 2, "the top edge belongs to the last class"
    assert s.color_of(5.0) == s.colors[0]
    assert s.color_of("nope") is None


def test_binned_scale_clamping() -> None:
    edges = (0.0, 1.0, 2.0)
    assert BinnedScale(edges).bin_of(-99.0) == 0
    assert BinnedScale(edges).bin_of(99.0) == 1
    free = BinnedScale(edges, clamp=False)
    assert free.bin_of(-99.0) is None and free.bin_of(99.0) is None
    assert free.bin_of(2.0) == 1


def test_binned_colors_come_from_class_centres() -> None:
    pal = get_palette("viridis")
    s = BinnedScale((0.0, 1.0, 2.0, 3.0, 4.0), pal)
    assert s.colors == tuple(pal.sample((i + 0.5) / 4) for i in range(4))
    assert len(set(c.rgba_tuple for c in s.colors)) == 4


def test_binned_with_a_categorical_palette_uses_discrete_swatches() -> None:
    pal = get_palette("okabe-ito")
    s = BinnedScale((0.0, 1.0, 2.0), pal)
    assert s.colors == (pal.colors[0], pal.colors[1])


def test_binned_legend_labels_the_ranges() -> None:
    s = BinnedScale((0.0, 2.5, 5.0))
    labels = [i.label for i in s.legend_items()]
    assert labels == ["0 – 2.5", "2.5 – 5"]
    assert s.legend_items()[1].value_range == (2.5, 5.0)


def test_binned_scale_needs_two_edges() -> None:
    with pytest.raises(ValueError):
        BinnedScale((1.0,))


# ------------------------------------------------------------------ factory


KIND_TABLE = [
    (["alpha", "beta", "gamma"], "categorical"),
    ([], "categorical"),
    ([None, "", "-"], "categorical"),
    (["a", 1, 2], "categorical"),
    ([1, 2, 3, 2, 1], "categorical"),
    ([-1, 0, 1, 1, 0], "categorical"),
    ([0, 1], "categorical"),
    (list(range(1, 21)), "sequential"),
    ([0.1, 2.5, 7.9, 11.2, 4.4, 3.1, 6.6], "sequential"),
    (["1.5", "2.25", "3.75", "9.5", "11", "19", "4.5"], "sequential"),
    ([-9.5, -4.25, -1.5, -0.5, -3.75, -7.25, -2.5], "sequential"),
    ([-3.0, -1.5, 0.5, 2.25, 9.0, 4.2, 7.75], "diverging"),
    ([-0.01, 0.02, 0.5, -0.75, 1.25, 2.5, -3.5], "diverging"),
]


@pytest.mark.parametrize("values,want", KIND_TABLE,
                         ids=[w + "-" + str(i) for i, (_, w) in enumerate(KIND_TABLE)])
def test_make_scale_picks_the_expected_kind(values: list, want: str) -> None:
    assert infer_kind(values) == want
    assert make_scale(values).kind == want


def test_make_scale_returns_the_matching_class() -> None:
    assert isinstance(make_scale(["a", "b"]), CategoricalScale)
    assert isinstance(make_scale([0.5, 2.5, 7.5, 1.5, 9.5, 3.5]), ContinuousScale)
    assert isinstance(make_scale([1.0, 2.0, 3.0], kind="binned"), BinnedScale)


def test_every_scale_satisfies_the_protocol() -> None:
    for s in (make_scale(["a"]), make_scale([1.5, 2.5, 3.5, 9.5, 0.5, 4.5]),
              make_scale([1.0, 5.0], kind="binned")):
        assert isinstance(s, Scale)
        assert isinstance(s.legend_items(), list)


def test_make_scale_derives_the_domain_from_the_values() -> None:
    s = make_scale([3.5, 1.25, 9.75, 4.5, 6.5, 2.25])
    assert isinstance(s, ContinuousScale)
    assert (s.vmin, s.vmax) == (1.25, 9.75)
    assert s.palette.name == "viridis"


def test_make_scale_symmetrises_a_diverging_domain() -> None:
    s = make_scale([-2.5, 1.5, 8.5, 0.5, 4.25, -0.75])
    assert isinstance(s, ContinuousScale)
    assert s.kind == "diverging"
    assert (s.vmin, s.vmax) == (-8.5, 8.5)
    assert s.palette.name == "blue-red"


def test_make_scale_honours_a_forced_kind_and_palette() -> None:
    s = make_scale([1, 2, 3], kind="sequential", palette="cividis")
    assert isinstance(s, ContinuousScale)
    assert s.palette.name == "cividis"
    c = make_scale([1.5, 2.5, 3.5, 4.5, 9.5, 0.5], kind="categorical")
    assert isinstance(c, CategoricalScale) and len(c.categories) == 6


def test_make_scale_passes_options_through() -> None:
    s = make_scale([1.0, 3.5, 10.0, 35.0, 100.0, 350.0, 1000.0], transform="log")
    assert isinstance(s, ContinuousScale)
    assert s.transform == "log" and not s.degraded
    b = make_scale(list(range(101)), kind="binned", bins=4)
    assert isinstance(b, BinnedScale) and b.n_bins == 4


def test_make_scale_honours_fixed_category_colours() -> None:
    s = make_scale(["a", "b"], kind="categorical", fixed={"b": "#010203"})
    assert s.color_of("b") == Color(1, 2, 3)


def test_make_scale_widens_a_constant_column() -> None:
    s = make_scale([4.5, 4.5, 4.5], kind="sequential")
    assert isinstance(s, ContinuousScale)
    assert s.vmin < 4.5 < s.vmax
    assert s.color_of(4.5) == s.palette.sample(0.5)


def test_make_scale_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValueError):
        make_scale([1.0], kind="rainbow")


def test_infer_kind_can_move_the_centre() -> None:
    values = [1.5, 2.25, 3.5, 4.75, 5.5, 6.25]
    assert infer_kind(values) == "sequential"
    assert infer_kind(values, mid=4.0) == "diverging"


def test_make_scale_ignores_missing_cells_when_sizing_the_domain() -> None:
    s = make_scale([1.5, None, "-", 2.5, "", 9.5, 3.5, 4.5, 5.5])
    assert isinstance(s, ContinuousScale)
    assert (s.vmin, s.vmax) == (1.5, 9.5)


def test_scale_colours_are_reproducible() -> None:
    values = ["x", "y", "z", "x"]
    a, b = make_scale(values), make_scale(values)
    assert [a.color_of(v) for v in values] == [b.color_of(v) for v in values]


def test_continuous_colour_changes_monotonically_with_value() -> None:
    s = ContinuousScale(0.0, 1.0, "viridis")
    lums = [s.color_of(i / 20).luminance for i in range(21)]  # type: ignore[union-attr]
    assert all(b > a for a, b in zip(lums, lums[1:]))
    assert not any(math.isnan(x) for x in lums)
