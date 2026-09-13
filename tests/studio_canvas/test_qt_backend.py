# SPDX-License-Identifier: MIT
"""QtBackend: paint conversion, arc handedness and batched drawing.

The arc tests are the important ones.  Scene arcs are centre-parameterised with
y growing downward, Qt measures angles the other way round, and a sign error
there mirrors every circular tree about its horizontal axis -- a bug that looks
plausible until someone compares an export with the screen.  So the conversion
is checked against points computed straight from the polar definition, including
the two cases that trip up naive implementations: a sweep past 180 degrees and a
whole turn.
"""

from __future__ import annotations

import re

import pytest

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from makeyourtree.render.backend import RenderBackend, render
from makeyourtree.scene.marks import (Anchor, Baseline, Cap, EllipseMark, GroupMark,
                                  Join, Layer, LinesMark, Paint, Path, PathMark,
                                  PolygonMark, PolylineMark, RectMark, RectsMark,
                                  Scene, TextMark, TextStyle)
from makeyourtree.style.color import Color

from makeyourtree_studio.canvas.qt_backend import (QtBackend, arc_to_qt, build_path,
                                               normalise_rect, polar_point,
                                               qcolor)

CX, CY, R = 100.0, 60.0, 40.0
_ENDPOINT_TOL = 0.05
"""Qt approximates a circular arc with cubic beziers; a twentieth of a scene
unit on a 40-unit radius is the shape of that error, not a sign mistake."""


def painter_on(width: int = 120, height: int = 90,
               fill: QColor | None = None) -> tuple[QImage, QPainter]:
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(fill if fill is not None else QColor(255, 255, 255))
    painter = QPainter(image)
    return image, painter


# ------------------------------------------------------------------- protocol


def test_backend_satisfies_the_render_contract(qapp):
    image, painter = painter_on()
    try:
        assert isinstance(QtBackend(painter), RenderBackend)
    finally:
        painter.end()


# ------------------------------------------------------------------ arcs


ARC_CASES = [
    pytest.param(0.0, 90.0, False, id="quarter-clockwise"),
    pytest.param(0.0, 270.0, False, id="three-quarters-past-180"),
    pytest.param(0.0, -90.0, True, id="quarter-anticlockwise"),
    pytest.param(180.0, -20.0, True, id="anticlockwise-past-180"),
    pytest.param(350.0, 10.0, False, id="wraps-through-zero"),
    pytest.param(-90.0, 260.0, False, id="polar-seam-at-twelve-o-clock"),
]


@pytest.mark.parametrize("a0,a1,ccw", ARC_CASES)
def test_arc_endpoints_match_polar_points(qapp, a0, a1, ccw):
    path = build_path([("A", CX, CY, R, a0, a1, ccw)])
    start = path.pointAtPercent(0.0)
    end = path.currentPosition()
    ex0, ey0 = polar_point(CX, CY, R, a0)
    ex1, ey1 = polar_point(CX, CY, R, a1)
    assert start.x() == pytest.approx(ex0, abs=_ENDPOINT_TOL)
    assert start.y() == pytest.approx(ey0, abs=_ENDPOINT_TOL)
    assert end.x() == pytest.approx(ex1, abs=_ENDPOINT_TOL)
    assert end.y() == pytest.approx(ey1, abs=_ENDPOINT_TOL)


@pytest.mark.parametrize("a0,a1,ccw", ARC_CASES)
def test_arc_sweeps_the_right_way_round(qapp, a0, a1, ccw):
    """Every intermediate point must sit on the arc actually requested.

    Endpoint agreement alone cannot distinguish an arc from its mirror image,
    which is exactly the bug this guards.
    """
    path = build_path([("A", CX, CY, R, a0, a1, ccw)])
    raw = (a0 - a1) if ccw else (a1 - a0)
    delta = raw % 360.0
    signed = -delta if ccw else delta
    for t in (0.25, 0.5, 0.75):
        point = path.pointAtPercent(t)
        ex, ey = polar_point(CX, CY, R, a0 + signed * t)
        assert point.x() == pytest.approx(ex, abs=0.5)
        assert point.y() == pytest.approx(ey, abs=0.5)


def test_full_turn_returns_to_its_start(qapp):
    """A closed ring is a real case in polar layout, and the one SVG cannot
    express in a single command."""
    rect, start, sweep = arc_to_qt(CX, CY, R, 0.0, 360.0)
    assert start == pytest.approx(0.0)
    assert abs(sweep) == pytest.approx(360.0)
    path = build_path([("A", CX, CY, R, 0.0, 360.0, False)])
    end = path.currentPosition()
    assert end.x() == pytest.approx(CX + R, abs=_ENDPOINT_TOL)
    assert end.y() == pytest.approx(CY, abs=_ENDPOINT_TOL)
    assert path.boundingRect().width() == pytest.approx(2 * R, abs=0.5)


def test_clockwise_scene_sweep_is_negative_in_qt(qapp):
    """Scene y grows downward, so an increasing angle is clockwise on screen;
    Qt calls that a negative sweep."""
    rect, start, sweep = arc_to_qt(CX, CY, R, 10.0, 100.0, False)
    assert rect == QRectF(CX - R, CY - R, 2 * R, 2 * R)
    assert start == pytest.approx(-10.0)
    assert sweep == pytest.approx(-90.0)
    _, _, ccw_sweep = arc_to_qt(CX, CY, R, 100.0, 10.0, True)
    assert ccw_sweep == pytest.approx(90.0)


def test_degenerate_arc_draws_nothing(qapp):
    _, _, sweep = arc_to_qt(CX, CY, R, 45.0, 45.0, False)
    assert sweep == 0.0
    path = build_path([("A", CX, CY, R, 45.0, 45.0, False)])
    assert path.currentPosition().x() == pytest.approx(
        polar_point(CX, CY, R, 45.0)[0], abs=_ENDPOINT_TOL)


def test_arc_after_a_move_does_not_jump_to_the_origin(qapp):
    """arcTo joins the arc to the current point; without an explicit move a
    fresh path would draw a line in from (0, 0)."""
    path = build_path([("A", CX, CY, R, 0.0, 90.0, False)])
    assert path.pointAtPercent(0.0).x() == pytest.approx(CX + R, abs=_ENDPOINT_TOL)
    assert path.boundingRect().left() >= CX - R - 1.0


def test_path_ops_round_trip(qapp):
    path = build_path(Path().move_to(0, 0).line_to(10, 0)
                      .quad_to(15, 5, 10, 10).cubic_to(8, 12, 4, 12, 0, 10)
                      .close().freeze())
    assert path.elementCount() > 4
    assert path.fillRule() == Qt.FillRule.WindingFill


# ------------------------------------------------------------------ paint


def test_dash_pattern_is_converted_from_scene_units_to_pen_widths(qapp):
    """Qt scales the dash pattern by the pen width; the scene does not."""
    image, painter = painter_on()
    try:
        backend = QtBackend(painter)
        pen = backend.pen_for(Paint.stroked(Color(0, 0, 0), width=2.0, dash=(4.0, 2.0)))
        assert [pytest.approx(v) for v in pen.dashPattern()] == [2.0, 1.0]
        thin = backend.pen_for(Paint.stroked(Color(0, 0, 0), width=0.5, dash=(1.0, 3.0)))
        assert [pytest.approx(v) for v in thin.dashPattern()] == [2.0, 6.0]
    finally:
        painter.end()


def test_odd_dash_pattern_is_doubled(qapp):
    """Qt requires an even number of entries; SVG does not."""
    image, painter = painter_on()
    try:
        pen = QtBackend(painter).pen_for(
            Paint.stroked(Color(0, 0, 0), width=1.0, dash=(3.0,)))
        assert len(pen.dashPattern()) % 2 == 0
    finally:
        painter.end()


def test_cosmetic_paint_becomes_a_cosmetic_pen(qapp):
    image, painter = painter_on()
    try:
        backend = QtBackend(painter)
        assert backend.pen_for(
            Paint.stroked(Color(0, 0, 0), width=1.2, cosmetic=True)).isCosmetic()
        assert not backend.pen_for(
            Paint.stroked(Color(0, 0, 0), width=1.2)).isCosmetic()
    finally:
        painter.end()


def test_caps_joins_and_invisible_strokes(qapp):
    image, painter = painter_on()
    try:
        backend = QtBackend(painter)
        pen = backend.pen_for(Paint.stroked(Color(0, 0, 0), width=1.0,
                                            cap=Cap.ROUND, join=Join.BEVEL))
        assert pen.capStyle() == Qt.PenCapStyle.RoundCap
        assert pen.joinStyle() == Qt.PenJoinStyle.BevelJoin
        assert backend.pen_for(Paint()).style() == Qt.PenStyle.NoPen
        assert backend.pen_for(
            Paint.stroked(Color(0, 0, 0), width=0.0)).style() == Qt.PenStyle.NoPen
    finally:
        painter.end()


def test_pens_and_brushes_are_cached(qapp):
    """A branch bucket reuses one pen for hundreds of thousands of segments."""
    image, painter = painter_on()
    try:
        backend = QtBackend(painter)
        paint = Paint.stroked(Color(1, 2, 3), width=1.0)
        assert backend.pen_for(paint) is backend.pen_for(paint)
        assert backend.brush_for(paint, Color(9, 9, 9)) is backend.brush_for(
            paint, Color(9, 9, 9))
    finally:
        painter.end()


def test_paint_opacity_multiplies_into_alpha(qapp):
    assert qcolor(Color(10, 20, 30, 128), 0.5).alpha() == 64
    assert qcolor(None).alpha() == 0


def test_negative_rectangles_are_normalised_like_svg(qapp):
    assert normalise_rect(10, 10, -4, -6) == (6, 4, 4, 6)


# ------------------------------------------------------------------ drawing


def sample(image: QImage, x: int, y: int) -> tuple[int, int, int]:
    c = image.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def test_batched_rects_take_per_rect_fills(qapp):
    """One mark, one pen, many colours: this is what makes a heatmap cheap."""
    image, painter = painter_on(60, 20)
    try:
        backend = QtBackend(painter)
        backend.draw_rects(RectsMark(
            paint=Paint(fill=Color(0, 0, 0)),
            coords=[0.0, 0.0, 20.0, 20.0, 20.0, 0.0, 20.0, 20.0,
                    40.0, 0.0, 20.0, 20.0],
            fills=[Color(255, 0, 0), Color(0, 255, 0), Color(0, 0, 255)]))
    finally:
        painter.end()
    assert sample(image, 10, 10) == (255, 0, 0)
    assert sample(image, 30, 10) == (0, 255, 0)
    assert sample(image, 50, 10) == (0, 0, 255)


def test_lines_batch_is_culled_against_the_clip_rect(qapp):
    """Culling only ever skips whole primitives, so a clipped pass and an
    unclipped one agree wherever both draw."""
    image, painter = painter_on(60, 60)
    try:
        backend = QtBackend(painter)
        backend.clip_rect = QRectF(0.0, 0.0, 30.0, 60.0)
        backend.draw_lines(LinesMark(
            paint=Paint.stroked(Color(0, 0, 0), width=4.0),
            coords=[0.0, 10.0, 20.0, 10.0, 40.0, 40.0, 55.0, 40.0]))
    finally:
        painter.end()
    assert sample(image, 10, 10) == (0, 0, 0)
    assert sample(image, 47, 40) == (255, 255, 255)


def test_clipped_and_unclipped_agree_where_both_draw(qapp):
    mark = LinesMark(paint=Paint.stroked(Color(0, 0, 0), width=3.0),
                     coords=[0.0, 10.0, 60.0, 10.0])
    out = []
    for clip in (None, QRectF(0.0, 0.0, 60.0, 60.0)):
        image, painter = painter_on(60, 60)
        try:
            backend = QtBackend(painter)
            backend.clip_rect = clip
            backend.draw_lines(mark)
        finally:
            painter.end()
        out.append(image.copy())
    assert out[0] == out[1]


def test_rect_ellipse_polygon_and_polyline_draw(qapp):
    image, painter = painter_on(60, 60)
    try:
        backend = QtBackend(painter)
        backend.draw_rect(RectMark(paint=Paint.filled(Color(255, 0, 0)),
                                   x=0.0, y=0.0, w=10.0, h=10.0))
        backend.draw_rect(RectMark(paint=Paint.filled(Color(0, 128, 0)),
                                   x=20.0, y=0.0, w=10.0, h=10.0, rx=2.0))
        backend.draw_ellipse(EllipseMark(paint=Paint.filled(Color(0, 0, 255)),
                                         cx=45.0, cy=5.0, rx=4.0, ry=4.0))
        backend.draw_polygon(PolygonMark(paint=Paint.filled(Color(255, 255, 0)),
                                         points=[0.0, 20.0, 10.0, 20.0, 10.0, 30.0]))
        backend.draw_polyline(PolylineMark(
            paint=Paint.stroked(Color(0, 0, 0), width=2.0),
            points=[0.0, 50.0, 50.0, 50.0]))
    finally:
        painter.end()
    assert sample(image, 5, 5) == (255, 0, 0)
    assert sample(image, 25, 5) == (0, 128, 0)
    assert sample(image, 45, 5) == (0, 0, 255)
    assert sample(image, 8, 27) == (255, 255, 0)
    assert sample(image, 25, 50) == (0, 0, 0)


def test_group_translation_and_clip(qapp):
    """The compositor shifts content with a group rather than rewriting floats,
    so the translation has to be honoured exactly."""
    image, painter = painter_on(60, 60)
    try:
        backend = QtBackend(painter)
        backend.draw_group(GroupMark(
            marks=(RectMark(paint=Paint.filled(Color(255, 0, 0)),
                            x=0.0, y=0.0, w=10.0, h=10.0),),
            dx=20.0, dy=20.0))
        backend.draw_group(GroupMark(
            marks=(RectMark(paint=Paint.filled(Color(0, 0, 255)),
                            x=0.0, y=0.0, w=20.0, h=20.0),),
            dx=40.0, dy=40.0, clip=(0.0, 0.0, 5.0, 5.0)))
    finally:
        painter.end()
    assert sample(image, 25, 25) == (255, 0, 0)
    assert sample(image, 5, 5) == (255, 255, 255)
    assert sample(image, 42, 42) == (0, 0, 255)
    assert sample(image, 48, 48) == (255, 255, 255)


def test_text_restores_the_painter_state(qapp):
    """Rotation and the reference-font scale must not leak into the next mark."""
    image, painter = painter_on()
    try:
        backend = QtBackend(painter)
        before = painter.transform()
        backend.draw_text(TextMark(x=10.0, y=10.0, text="Bacillus",
                                   rotation=37.0,
                                   style=TextStyle(anchor=Anchor.MIDDLE,
                                                   baseline=Baseline.HANGING)))
        assert painter.transform() == before
        backend.draw_text(TextMark(x=10.0, y=10.0, text="", rotation=0.0))
        assert painter.transform() == before
    finally:
        painter.end()


def test_render_walks_a_whole_scene(qapp):
    """The shared walker drives this backend exactly as it drives the SVG one."""
    scene = Scene(width=60.0, height=60.0, background=Color(255, 255, 255))
    scene.add(RectMark(paint=Paint.filled(Color(255, 0, 0)),
                       x=0.0, y=0.0, w=10.0, h=10.0), Layer.BRANCHES)
    scene.add(RectMark(paint=Paint.filled(Color(0, 255, 0)),
                       x=20.0, y=0.0, w=10.0, h=10.0), Layer.OVERLAY)
    image, painter = painter_on(60, 60, QColor(0, 0, 0, 0))
    try:
        assert render(scene, QtBackend(painter)) == b""
    finally:
        painter.end()
    assert sample(image, 5, 5) == (255, 0, 0)
    # Overlay is interaction state: the walker must not have painted it, so the
    # background begin() laid down is still showing.
    assert sample(image, 25, 5) == (255, 255, 255)


def test_path_mark_with_arcs_draws(qapp):
    image, painter = painter_on(140, 140)
    try:
        backend = QtBackend(painter)
        backend.draw_path(PathMark(
            paint=Paint.stroked(Color(0, 0, 0), width=3.0),
            segments=Path().arc(70.0, 70.0, 40.0, 0.0, 90.0).freeze()))
    finally:
        painter.end()
    x, y = polar_point(70.0, 70.0, 40.0, 45.0)
    assert sample(image, int(round(x)), int(round(y))) == (0, 0, 0)
    assert sample(image, 70, 70) == (255, 255, 255)


def test_scene_background_is_filled_on_begin(qapp):
    image, painter = painter_on(20, 20, QColor(0, 0, 0, 0))
    try:
        backend = QtBackend(painter)
        backend.begin(Scene(width=20.0, height=20.0, background=Color(1, 2, 3)))
        assert backend.end() == b""
    finally:
        painter.end()
    assert sample(image, 10, 10) == (1, 2, 3)


def test_backend_can_skip_the_background_for_the_live_canvas(qapp):
    image, painter = painter_on(20, 20, QColor(255, 255, 255))
    try:
        backend = QtBackend(painter)
        backend.fill_background = False
        backend.begin(Scene(width=20.0, height=20.0, background=Color(1, 2, 3)))
    finally:
        painter.end()
    assert sample(image, 10, 10) == (255, 255, 255)


# ------------------------------------------------- agreement with the export


def svg_path_endpoint(segments) -> tuple[float, float]:
    """Last coordinate pair of the SVG writer's ``d`` string."""
    from makeyourtree.render.svg import SvgBackend

    data = SvgBackend(precision=6).path_data(segments)
    numbers = re.findall(r"-?\d+(?:\.\d+)?", data)
    return (float(numbers[-2]), float(numbers[-1]))


@pytest.mark.parametrize("a0,a1,ccw", ARC_CASES)
def test_screen_and_export_land_on_the_same_arc_endpoint(qapp, a0, a1, ccw):
    """The two backends consume one Scene and must not disagree about geometry.

    They convert the same centre-parameterised arc in opposite directions --
    Qt to a sweep, SVG to an endpoint with flags -- which is exactly where a
    silent divergence between the canvas and the exported figure would hide.
    """
    segments = [("A", CX, CY, R, a0, a1, ccw)]
    qt_end = build_path(segments).currentPosition()
    sx, sy = svg_path_endpoint(segments)
    assert qt_end.x() == pytest.approx(sx, abs=_ENDPOINT_TOL)
    assert qt_end.y() == pytest.approx(sy, abs=_ENDPOINT_TOL)


def test_dash_lengths_survive_the_round_trip_into_pen_widths(qapp):
    """Multiplying the Qt pattern back by the width must give the scene dash."""
    paint = Paint.stroked(Color(0, 0, 0), width=2.5, dash=(5.0, 2.5))
    image, painter = painter_on()
    try:
        pattern = QtBackend(painter).pen_for(paint).dashPattern()
    finally:
        painter.end()
    assert [p * paint.width for p in pattern] == [pytest.approx(v)
                                                 for v in paint.dash]
