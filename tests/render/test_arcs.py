# SPDX-License-Identifier: MIT
"""Centre-parameterised arcs must survive conversion to SVG's endpoint form.

Every case is checked against polar points computed directly from the arc's own
parameters, so the test never has to trust the writer's own arithmetic.
"""
from __future__ import annotations

import math
import re

import pytest

from makeyourtree.layout.projector import PolarProjector
from makeyourtree.render.svg import SvgBackend, render_svg
from makeyourtree.scene.marks import Layer, Paint, Path, PathMark, Scene
from makeyourtree.style.color import Color

from _render_support import SVG_NS, parse_svg

_ARC = re.compile(
    r"A(-?[\d.]+) (-?[\d.]+) 0 ([01]) ([01]) (-?[\d.]+) (-?[\d.]+)")


def polar(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def arcs_in(d: str) -> list[tuple[float, float, int, int, float, float]]:
    """``(rx, ry, large, sweep, x, y)`` for every ``A`` command in *d*."""
    return [(float(m[0]), float(m[1]), int(m[2]), int(m[3]),
             float(m[4]), float(m[5])) for m in _ARC.findall(d)]


def path_data(*segments) -> str:
    return SvgBackend(precision=6).path_data(segments)


def test_quarter_arc_lands_on_the_computed_endpoint():
    d = path_data(("A", 100.0, 50.0, 20.0, 0.0, 90.0, False))
    assert d.startswith("M120 50")
    (rx, ry, large, sweep, x, y), = arcs_in(d)
    assert (rx, ry) == (20.0, 20.0)
    assert (large, sweep) == (0, 1)
    assert (x, y) == pytest.approx(polar(100, 50, 20, 90), abs=1e-4)


def test_sweep_beyond_half_a_turn_sets_the_large_arc_flag():
    d = path_data(("A", 0.0, 0.0, 10.0, 10.0, 280.0, False))
    (_, _, large, sweep, x, y), = arcs_in(d)
    assert large == 1
    assert sweep == 1
    assert (x, y) == pytest.approx(polar(0, 0, 10, 280), abs=1e-4)


def test_sweep_of_exactly_half_a_turn_keeps_the_small_flag():
    (_, _, large, _, _, _), = arcs_in(path_data(("A", 0.0, 0.0, 5.0, 30.0, 210.0, False)))
    assert large == 0


def test_anticlockwise_arc_flips_the_sweep_flag_only():
    d = path_data(("A", 0.0, 0.0, 8.0, 90.0, 0.0, True))
    (_, _, large, sweep, x, y), = arcs_in(d)
    assert sweep == 0
    assert large == 0
    assert (x, y) == pytest.approx(polar(0, 0, 8, 0), abs=1e-4)


def test_anticlockwise_arc_wrapping_the_seam_measures_the_short_way():
    # 10 degrees back to 350 degrees going anticlockwise is a 20 degree sweep.
    (_, _, large, sweep, x, y), = arcs_in(
        path_data(("A", 0.0, 0.0, 4.0, 10.0, 350.0, True)))
    assert (large, sweep) == (0, 0)
    assert (x, y) == pytest.approx(polar(0, 0, 4, 350), abs=1e-4)


def test_clockwise_arc_wrapping_the_seam_measures_the_short_way():
    (_, _, large, sweep, x, y), = arcs_in(
        path_data(("A", 0.0, 0.0, 4.0, 350.0, 10.0, False)))
    assert (large, sweep) == (0, 1)
    assert (x, y) == pytest.approx(polar(0, 0, 4, 10), abs=1e-4)


def test_full_circle_is_split_into_two_half_turns():
    d = path_data(("A", 3.0, 7.0, 12.0, 0.0, 360.0, False))
    commands = arcs_in(d)
    assert len(commands) == 2
    assert commands[0][4:] == pytest.approx(polar(3, 7, 12, 180), abs=1e-4)
    assert commands[1][4:] == pytest.approx(polar(3, 7, 12, 0), abs=1e-4)
    assert [c[3] for c in commands] == [1, 1]


def test_full_circle_anticlockwise_uses_the_other_sweep():
    commands = arcs_in(path_data(("A", 0.0, 0.0, 5.0, 0.0, 360.0, True)))
    assert len(commands) == 2
    assert [c[3] for c in commands] == [0, 0]
    assert commands[0][4:] == pytest.approx(polar(0, 0, 5, -180), abs=1e-4)


def test_almost_full_circle_from_float_error_still_closes():
    commands = arcs_in(path_data(("A", 0.0, 0.0, 5.0, 0.0, 359.9999999, False)))
    assert len(commands) == 2


def test_zero_sweep_arc_emits_no_command():
    d = path_data(("A", 0.0, 0.0, 5.0, 45.0, 45.0, False))
    assert arcs_in(d) == []
    assert d.startswith("M")


def test_zero_radius_arc_degenerates_to_its_centre():
    d = path_data(("M", 0.0, 0.0), ("A", 9.0, 9.0, 0.0, 0.0, 180.0, False))
    assert arcs_in(d) == []
    assert d.endswith("L9 9")


def test_arc_after_a_gap_gets_an_explicit_line_to_its_start():
    d = path_data(("M", 0.0, 0.0), ("A", 100.0, 0.0, 10.0, 0.0, 90.0, False))
    assert d.startswith("M0 0L110 0A")


def test_arc_continuing_from_the_current_point_adds_no_line():
    start = polar(50.0, 50.0, 10.0, 0.0)
    d = path_data(("M", start[0], start[1]),
                  ("A", 50.0, 50.0, 10.0, 0.0, 90.0, False))
    assert "L" not in d


def test_projector_cell_round_trips_through_the_writer():
    """An annular sector from the frozen projector must reach the same corners."""
    proj = PolarProjector(cx=200.0, cy=180.0, base_r=40.0, start_angle=-90.0,
                          arc=270.0, n_rows=6.0)
    segments = proj.cell(1.0, 4.0, 10.0, 35.0)
    d = SvgBackend(precision=6).path_data(segments)
    commands = arcs_in(d)
    assert len(commands) == 2
    inner_end = polar(200.0, 180.0, 50.0, proj.angle_of(4.0))
    outer_end = polar(200.0, 180.0, 75.0, proj.angle_of(1.0))
    assert commands[0][4:] == pytest.approx(inner_end, abs=1e-4)
    assert commands[1][4:] == pytest.approx(outer_end, abs=1e-4)
    # 3 of 6 rows over a 270 degree fan is 135 degrees: under a half turn.
    assert commands[0][2] == 0
    assert commands[0][3] == 1 and commands[1][3] == 0
    assert d.endswith("Z")


def test_full_ring_inside_a_rendered_scene_is_valid_xml():
    path = Path().arc(60.0, 60.0, 40.0, 0.0, 360.0)
    scene = Scene(width=140, height=140)
    scene.add(PathMark(paint=Paint.stroked(Color(0, 0, 0)), segments=path.freeze()),
              Layer.GRID)
    root = parse_svg(render_svg(scene))
    d = next(root.iter(SVG_NS + "path")).get("d")
    assert len(arcs_in(d)) == 2
