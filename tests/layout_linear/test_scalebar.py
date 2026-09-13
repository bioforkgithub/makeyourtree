# SPDX-License-Identifier: MIT
"""Nice-number scale bars and axis ticks."""
from __future__ import annotations

import math

import pytest

from makeyourtree.layout.linear import LinearLayout
from makeyourtree.layout.params import BranchMode, LayoutParams
from makeyourtree.layout.scalebar import MIN_BAR, ScaleBar, axis_ticks, nice_num, scale_bar
from makeyourtree.style.theme import Theme

from .conftest import C, L, build

LADDER = {1.0, 2.0, 5.0}


def lay(tree, metrics, **kw):
    params = LayoutParams(**kw)
    return LinearLayout().compute(tree, params, metrics), params


def mantissa(value: float) -> float:
    exp = math.floor(math.log10(value))
    return round(value / 10.0 ** exp, 10)


@pytest.mark.parametrize("raw", [0.0007, 0.013, 0.15, 0.9, 1.0, 3.4, 47.0, 812.0, 9e5])
def test_nice_num_always_lands_on_the_ladder(raw):
    for round_ in (True, False):
        out = nice_num(raw, round_)
        assert out > 0
        assert mantissa(out) in LADDER


def test_loose_rounding_picks_the_nearest_rung():
    assert nice_num(1.4) == pytest.approx(1.0)
    assert nice_num(1.6) == pytest.approx(2.0)
    assert nice_num(2.9) == pytest.approx(2.0)
    assert nice_num(3.1) == pytest.approx(5.0)
    assert nice_num(6.9) == pytest.approx(5.0)
    assert nice_num(7.1) == pytest.approx(10.0)


def test_tight_rounding_never_goes_below_the_input():
    for raw in (0.11, 1.1, 2.1, 5.1, 8.0, 42.0):
        assert nice_num(raw, round_=False) >= raw


def test_nice_num_guards_the_degenerate_cases():
    assert nice_num(0.0) == 0.0
    assert nice_num(-3.0) == 0.0
    assert nice_num(float("inf")) == 0.0


def test_scale_bar_reports_a_round_length_in_both_units(three_tips, metrics):
    frame, params = lay(three_tips, metrics)
    bar = scale_bar(frame, params, Theme())
    assert isinstance(bar, ScaleBar)
    assert mantissa(bar.units) in LADDER
    assert bar.pixels == pytest.approx(bar.units * frame.scale)
    assert bar.label == "0.1"
    assert bar.units == pytest.approx(0.1)


def test_the_bar_sits_below_the_tree_at_its_left_edge(three_tips, metrics):
    frame, params = lay(three_tips, metrics)
    bar = scale_bar(frame, params, Theme())
    assert bar.position == (bar.x, bar.y)
    assert bar.x == pytest.approx(frame.body_bounds[0])
    assert bar.y > frame.body_bounds[3]


def test_the_bar_never_shrinks_below_a_readable_length(three_tips, metrics):
    frame, params = lay(three_tips, metrics, width=120.0)
    bar = scale_bar(frame, params, Theme())
    assert bar.pixels >= MIN_BAR


def test_the_bar_never_exceeds_half_the_tree(metrics):
    tree = build(C(L("A", 0.001), L("B", 1000.0)))
    frame, params = lay(tree, metrics)
    bar = scale_bar(frame, params, Theme())
    assert bar.units <= frame.metadata["depth_max"] * 0.5 + 1e-12


@pytest.mark.parametrize("length", [0.4, 20.0, 100.0, 400.0, 4000.0])
def test_the_label_reads_back_as_the_bar_length(length, metrics):
    """Regression: trailing zeros were stripped from integer renderings too, so
    a tree measured in days drew a 100-day bar labelled "1"."""
    tree = build(C(L("A", length * 0.5), L("B", length)))
    frame, params = lay(tree, metrics)
    bar = scale_bar(frame, params, Theme())
    assert float(bar.label) == pytest.approx(bar.units)
    if length >= 100.0:
        assert bar.units >= 10.0


@pytest.mark.parametrize("units, label", [(10.0, "10"), (50.0, "50"),
                                          (200.0, "200"), (5000.0, "5000"),
                                          (0.5, "0.5"), (0.02, "0.02")])
def test_ladder_values_format_with_their_zeros(units, label):
    from makeyourtree.layout.scalebar import _format_units
    assert _format_units(units) == label


def test_a_unit_name_is_appended_when_the_caller_supplies_one(three_tips, metrics):
    frame, params = lay(three_tips, metrics, extra={"scale_unit": "subs/site"})
    assert scale_bar(frame, params, Theme()).label == "0.1 subs/site"


@pytest.mark.parametrize("mode", [BranchMode.CLADOGRAM_ALIGNED,
                                  BranchMode.CLADOGRAM_LEVEL])
def test_no_scale_bar_in_cladogram_modes(three_tips, metrics, mode):
    frame, params = lay(three_tips, metrics, branch_mode=mode)
    assert scale_bar(frame, params, Theme()) is None
    assert axis_ticks(frame, params) == []


def test_no_scale_bar_without_lengths(metrics):
    tree = build(C(L("A", None), L("B", None)))
    frame, params = lay(tree, metrics)
    assert frame.scale == 0.0
    assert scale_bar(frame, params, Theme()) is None


def test_a_theme_that_hides_the_bar_gets_no_bar(three_tips, metrics):
    frame, params = lay(three_tips, metrics)
    assert scale_bar(frame, params, Theme(scalebar_show=False)) is None


def test_axis_ticks_start_at_the_root_and_step_evenly(three_tips, metrics):
    frame, params = lay(three_tips, metrics)
    ticks = axis_ticks(frame, params, count=6)
    values = [v for v, _, _ in ticks]
    assert values[0] == 0.0
    assert values[-1] == pytest.approx(1.0)
    steps = {round(b - a, 9) for a, b in zip(values, values[1:])}
    assert len(steps) == 1
    assert mantissa(steps.pop()) in LADDER


def test_axis_tick_positions_track_the_layout_scale(three_tips, metrics):
    frame, params = lay(three_tips, metrics)
    x0 = frame.body_bounds[0]
    for value, pos, _ in axis_ticks(frame, params):
        assert pos == pytest.approx(x0 + value * frame.scale)


def test_axis_tick_labels_carry_no_float_drift(metrics):
    tree = build(C(L("A", 0.3), L("B", 0.9)))
    frame, params = lay(tree, metrics)
    labels = [lab for _, _, lab in axis_ticks(frame, params, count=6)]
    assert labels == ["0.0", "0.2", "0.4", "0.6", "0.8"]


@pytest.mark.parametrize("length", [0.00037, 0.037, 0.4, 3.0, 55.0, 91000.0])
def test_axis_and_bar_draw_from_the_same_ladder(length, metrics):
    """The stated invariant: a bar reading 0.2 must never sit beside an axis
    stepping by 0.25, so both quantities come off the 1/2/5 ladder."""
    tree = build(C(L("A", length * 0.5), L("B", length)))
    frame, params = lay(tree, metrics)
    bar = scale_bar(frame, params, Theme())
    step = axis_ticks(frame, params)[1][0]
    assert mantissa(bar.units) in LADDER
    assert mantissa(step) in LADDER
