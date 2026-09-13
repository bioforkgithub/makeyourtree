# SPDX-License-Identifier: MIT
"""Palette table invariants.

The tables are data, so the tests check the properties the data is chosen for
rather than the individual values: monotone luminance for the sequential ramps,
mutual distinguishability for the categorical sets, and exact endpoints for the
interpolator.
"""

from __future__ import annotations

import itertools

import pytest

from makeyourtree.style.color import Color
from makeyourtree.style.palettes import (CATEGORICAL, DIVERGING, SEQUENTIAL,
                                     Palette, assign_categories,
                                     distinct_colors, from_oklab, get_palette,
                                     list_palettes, oklab_distance, oklab_mix,
                                     to_oklab)
from makeyourtree.style.theme import LIGHT

ALL = [p for table in (CATEGORICAL, SEQUENTIAL, DIVERGING) for p in table.values()]


def _monotone(xs: list[float]) -> bool:
    d = [b - a for a, b in zip(xs, xs[1:])]
    return all(x > 0 for x in d) or all(x < 0 for x in d)


# ------------------------------------------------------------------ tables


@pytest.mark.parametrize("p", ALL, ids=lambda p: p.name)
def test_palette_is_well_formed(p: Palette) -> None:
    assert len(p.colors) >= 3
    assert p.origin, f"{p.name} must record where its values came from"
    assert all(isinstance(c, Color) and c.a == 255 for c in p.colors)


def test_theme_default_palette_names_resolve() -> None:
    # Theme ships these names as defaults; a typo here breaks every document.
    assert get_palette(LIGHT.categorical_palette, "categorical").name == "okabe-ito"
    assert get_palette(LIGHT.sequential_palette, "sequential").name == "viridis"
    assert get_palette(LIGHT.diverging_palette, "diverging").name == "blue-red"


def test_list_palettes_groups_by_kind() -> None:
    seq = list_palettes("sequential")
    assert seq == sorted(seq)
    assert "viridis" in seq and "cividis" in seq and "greys" in seq
    assert set(list_palettes()) == set(CATEGORICAL) | set(SEQUENTIAL) | set(DIVERGING)
    with pytest.raises(KeyError):
        list_palettes("nonsense")


def test_get_palette_normalises_names_and_reverses() -> None:
    assert get_palette("Okabe_Ito") is CATEGORICAL["okabe-ito"]
    assert get_palette("  VIRIDIS ") is SEQUENTIAL["viridis"]
    assert get_palette("cud").name == "okabe-ito"
    rev = get_palette("viridis-r")
    assert rev.colors == tuple(reversed(SEQUENTIAL["viridis"].colors))
    assert get_palette(rev) is rev
    with pytest.raises(KeyError):
        get_palette("viridis", "categorical")
    with pytest.raises(KeyError):
        get_palette("no-such-palette")


# -------------------------------------------------------------- sequential


@pytest.mark.parametrize("p", list(SEQUENTIAL.values()), ids=lambda p: p.name)
def test_sequential_control_points_are_monotone_in_luminance(p: Palette) -> None:
    # This is the testable half of "perceptually uniform": the ordering of the
    # data survives greyscale printing and every form of colour deficiency.
    assert _monotone([c.luminance for c in p.colors])


@pytest.mark.parametrize("p", list(SEQUENTIAL.values()), ids=lambda p: p.name)
def test_sequential_stays_monotone_when_densely_sampled(p: Palette) -> None:
    # Monotone control points do not by themselves guarantee a monotone ramp;
    # the OKLab interpolation between them has to preserve it too.
    assert _monotone([p.sample(i / 63).luminance for i in range(64)])


@pytest.mark.parametrize("p", list(SEQUENTIAL.values()), ids=lambda p: p.name)
def test_sequential_endpoints_span_a_wide_luminance_range(p: Palette) -> None:
    lo, hi = sorted((p.colors[0].luminance, p.colors[-1].luminance))
    assert hi - lo > 0.5


# ------------------------------------------------------------- categorical


@pytest.mark.parametrize("p", [q for q in CATEGORICAL.values() if q.encoding],
                         ids=lambda p: p.name)
def test_encoding_categorical_colors_are_mutually_distinguishable(p: Palette) -> None:
    worst = min(oklab_distance(a, b) for a, b in itertools.combinations(p.colors, 2))
    assert worst > 0.085, f"{p.name}: closest pair is only {worst:.3f} apart in OKLab"


@pytest.mark.parametrize("p", [q for q in CATEGORICAL.values() if not q.encoding],
                         ids=lambda p: p.name)
def test_accent_categorical_colors_are_at_least_separate(p: Palette) -> None:
    # Washes and text accents sit closer together on purpose, but two members
    # that read as the same colour would still be a table error.
    worst = min(oklab_distance(a, b) for a, b in itertools.combinations(p.colors, 2))
    assert worst > 0.05


def test_categorical_bad_color_is_outside_the_palette() -> None:
    for p in CATEGORICAL.values():
        assert p.bad is not None
        assert min(oklab_distance(p.bad, c) for c in p.colors) > 0.04


def test_cycle_wraps_in_both_directions() -> None:
    p = get_palette("okabe-ito")
    assert p.cycle(0) is p.colors[0]
    assert p.cycle(len(p)) is p.colors[0]
    assert p.cycle(len(p) + 2) is p.colors[2]
    assert p.cycle(-1) is p.colors[-1]


def test_distinct_colors_repeats_past_the_palette_length() -> None:
    got = distinct_colors(10, "tol-bright")
    assert len(got) == 10
    assert got[6] == got[0]


# --------------------------------------------------------------- diverging


@pytest.mark.parametrize("p", list(DIVERGING.values()), ids=lambda p: p.name)
def test_diverging_is_lightest_in_the_middle(p: Palette) -> None:
    assert len(p.colors) % 2 == 1, "an even ramp has no exact midpoint colour"
    mid = len(p.colors) // 2
    lums = [c.luminance for c in p.colors]
    assert lums[mid] == max(lums)
    assert _monotone(lums[:mid + 1]) and _monotone(lums[mid:])


@pytest.mark.parametrize("p", list(DIVERGING.values()), ids=lambda p: p.name)
def test_diverging_midpoint_is_sampled_exactly(p: Palette) -> None:
    # A scale centred on zero draws sample(0.5) for every zero-valued cell; if
    # that were one blend away from the neutral stop the centre would drift.
    assert p.sample(0.5) is p.colors[len(p.colors) // 2]


# ------------------------------------------------------------- interpolate


@pytest.mark.parametrize("p", ALL, ids=lambda p: p.name)
def test_sample_hits_the_ramp_endpoints_exactly(p: Palette) -> None:
    assert p.sample(0.0) is p.colors[0]
    assert p.sample(1.0) is p.colors[-1]
    assert p.sample(-4.0) is p.colors[0]
    assert p.sample(9.0) is p.colors[-1]


@pytest.mark.parametrize("p", ALL, ids=lambda p: p.name)
def test_sample_hits_every_control_point_exactly(p: Palette) -> None:
    n = len(p.colors)
    for i, c in enumerate(p.colors):
        assert p.sample(i / (n - 1)) is c


def test_sample_is_continuous_across_a_control_point() -> None:
    p = get_palette("viridis")
    n = len(p.colors)
    eps = 1e-4
    before, after = p.sample(3 / (n - 1) - eps), p.sample(3 / (n - 1) + eps)
    assert oklab_distance(before, after) < 0.01


def test_resample_preserves_endpoints_and_length() -> None:
    p = get_palette("magma")
    got = p.resample(5)
    assert len(got) == 5
    assert got[0] is p.colors[0] and got[-1] is p.colors[-1]
    assert p.resample(1) == (p.sample(0.5),)
    assert p.resample(0) == ()


def test_single_colour_palette_samples_flat() -> None:
    p = Palette("mono", "sequential", (Color(10, 20, 30),), "test")
    assert p.sample(0.0) is p.colors[0] and p.sample(1.0) is p.colors[0]


def test_oklab_round_trip_is_within_one_bit() -> None:
    for c in get_palette("okabe-ito"):
        back = from_oklab(to_oklab(c))
        assert max(abs(a - b) for a, b in zip(c.rgba_tuple, back.rgba_tuple)) <= 1


def test_oklab_mix_keeps_midpoint_lightness_between_the_ends() -> None:
    a, b = Color(0, 114, 178), Color(240, 228, 66)
    mid = oklab_mix(a, b, 0.5)
    assert a.luminance < mid.luminance < b.luminance
    # sRGB blending of these two dips towards grey; OKLab keeps the chroma up.
    assert mid.luminance > a.lerp(b, 0.5).luminance * 0.8
    assert oklab_mix(a, b, 0.0) is a and oklab_mix(a, b, 1.0) is b


def test_mix_carries_alpha() -> None:
    a, b = Color(0, 0, 0, 0), Color(255, 255, 255, 255)
    assert oklab_mix(a, b, 0.5).a == 128


# ----------------------------------------------------- category assignment


def test_assignment_is_stable_across_repeated_calls() -> None:
    vals = ["gamma", "alpha", "beta", "alpha", "gamma"]
    first = assign_categories(vals, "okabe-ito")
    for _ in range(3):
        assert assign_categories(vals, "okabe-ito") == first
    assert list(first) == ["gamma", "alpha", "beta"]


def test_assignment_survives_appended_rows() -> None:
    base = ["a", "b", "c"]
    first = assign_categories(base, "tol-bright")
    later = assign_categories(base + ["d", "a"], "tol-bright")
    assert all(later[k] == v for k, v in first.items())
    assert "d" in later


def test_assignment_skips_missing_cells() -> None:
    got = assign_categories(["a", None, "", "  ", "-", "b"], "okabe-ito")
    assert list(got) == ["a", "b"]


def test_fixed_colors_win_and_are_not_reused() -> None:
    pal = get_palette("okabe-ito")
    # Pin the palette's own second colour onto a late category: the automatic
    # assignment must step over it rather than hand it to an earlier one.
    got = assign_categories(["a", "b", "c"], pal, {"c": pal.colors[1].hex})
    assert got["c"] == pal.colors[1]
    assert got["a"] == pal.colors[0]
    assert got["b"] == pal.colors[2]
    assert len(set(c.rgba_tuple for c in got.values())) == 3


def test_fixed_category_absent_from_the_data_is_kept() -> None:
    got = assign_categories(["a"], "okabe-ito", {"z": "#123456"})
    assert got["z"] == Color(0x12, 0x34, 0x56)
    assert list(got) == ["a", "z"]


def test_assignment_terminates_when_every_colour_is_pinned() -> None:
    pal = get_palette("tol-high-contrast")
    fixed = {f"p{i}": c.hex for i, c in enumerate(pal.colors)}
    got = assign_categories(["x", "y"], pal, fixed)
    assert len(got) == 5
    assert got["x"] in pal.colors and got["y"] in pal.colors
