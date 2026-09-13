# SPDX-License-Identifier: MIT
"""Physical size and resolution arithmetic.

These pin the one convention the whole output path rests on: **a scene unit is
a point, 1/72 inch**. If that slips, an SVG, a PDF and a PNG of the same figure
stop being the same size, and the failure is invisible until someone measures a
printed figure.
"""

from __future__ import annotations

import math

import pytest

from makeyourtree.render.sizing import (POINTS_PER_INCH, UNITS, LengthError,
                                        fit_scale, format_length, page_size,
                                        parse_length, pixels_for,
                                        scale_for_dpi)


# ------------------------------------------------------------------ parsing


def test_a_bare_number_is_points():
    """Every pre-existing ``--width 900`` must keep meaning what it meant."""
    assert parse_length("900") == 900.0
    assert parse_length(900) == 900.0
    assert parse_length(900.5) == 900.5


@pytest.mark.parametrize("text,inches", [
    ("1in", 1.0),
    ("72pt", 1.0),
    ("25.4mm", 1.0),
    ("2.54cm", 1.0),
    ("96px", 1.0),
])
def test_every_unit_agrees_on_one_inch(text, inches):
    assert parse_length(text) == pytest.approx(inches * POINTS_PER_INCH)


def test_a_css_pixel_is_not_a_point():
    """The distinction the SVG header exists to make explicit."""
    assert parse_length("96px") == pytest.approx(72.0)
    assert parse_length("96pt") == 96.0


def test_units_are_case_insensitive_and_tolerate_spaces():
    assert parse_length(" 180 MM ") == pytest.approx(parse_length("180mm"))


def test_negative_and_exponent_forms_parse():
    assert parse_length("-10pt") == -10.0
    assert parse_length("1e2") == 100.0


@pytest.mark.parametrize("bad", ["", "wide", "10furlongs", "mm", "10 20", "nan"])
def test_nonsense_is_rejected_with_the_legal_units_named(bad):
    with pytest.raises(LengthError) as excinfo:
        parse_length(bad)
    assert "mm" in str(excinfo.value)


def test_non_finite_numbers_are_rejected():
    for value in (math.inf, -math.inf, math.nan):
        with pytest.raises(LengthError):
            parse_length(value)


def test_format_length_round_trips():
    assert parse_length(format_length(510.24, "mm")) == pytest.approx(510.24,
                                                                     abs=0.3)


# --------------------------------------------------------------- resolution


def test_72_dpi_is_one_to_one():
    assert scale_for_dpi(72) == 1.0


def test_300_dpi_is_the_ratio_to_72():
    assert scale_for_dpi(300) == pytest.approx(300.0 / 72.0)


@pytest.mark.parametrize("dpi", [0, -1, math.nan, math.inf])
def test_a_useless_dpi_is_refused(dpi):
    with pytest.raises(ValueError):
        scale_for_dpi(dpi)


def test_pixels_for_matches_the_physical_intent():
    """180 mm at 300 dpi is 2126 pixels, and nothing about the code path may
    quietly turn that into 2125 or 2127."""
    assert pixels_for(parse_length("180mm"), 300) == round(180 / 25.4 * 300)


def test_doubling_dpi_doubles_the_pixels():
    points = parse_length("100mm")
    assert pixels_for(points, 600) == 2 * pixels_for(points, 300)


def test_pixels_never_collapse_to_zero():
    assert pixels_for(0.0, 300) == 1
    assert pixels_for(0.001, 1) == 1


def test_pixels_round_half_up_not_ceiling():
    # 1.5 points at 72 dpi is 1.5 px, which must land on 2, while 1.4 lands on 1.
    assert pixels_for(1.5, 72) == 2
    assert pixels_for(1.4, 72) == 1


# -------------------------------------------------------------- page sizes


def test_a4_is_the_iso_size_within_a_point():
    width, height = page_size("a4")
    assert width == pytest.approx(210 / 25.4 * 72, abs=1.0)
    assert height == pytest.approx(297 / 25.4 * 72, abs=1.0)


def test_page_names_are_case_insensitive():
    assert page_size("A4") == page_size("a4")


def test_column_presets_leave_the_height_open():
    """A journal fixes how wide a figure may be, not how tall."""
    _, height = page_size("column")
    assert height == 0.0


def test_an_unknown_page_names_the_alternatives():
    with pytest.raises(LengthError) as excinfo:
        page_size("a9")
    assert "a4" in str(excinfo.value)


# ------------------------------------------------------------------ fitting


def test_fit_scale_is_one_when_unconstrained():
    assert fit_scale(100, 50) == 1.0


def test_fit_scale_takes_the_tighter_axis():
    assert fit_scale(100, 50, max_width=50, max_height=40) == 0.5


def test_fit_scale_never_returns_zero():
    assert fit_scale(100, 50, max_width=0) > 0
