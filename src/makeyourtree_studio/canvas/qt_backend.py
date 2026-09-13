# SPDX-License-Identifier: MIT
"""Painting a :class:`~makeyourtree.scene.marks.Scene` with ``QPainter``.

This is the screen half of the render contract; :mod:`makeyourtree.render.svg` is the
file half.  Both consume the identical :class:`~makeyourtree.scene.marks.Scene`
through the same walker, so what the user sees and what they export cannot drift
apart.  Every decision below is therefore made twice on purpose: if the SVG
writer normalises a negative rectangle, so does this; if it fills a polyline, so
does this.

Three conversions are not obvious.

**Dash patterns.**  ``Paint.dash`` is in scene units, matching SVG's
``stroke-dasharray``.  Qt's ``QPen.setDashPattern`` is in *pen widths*, so the
pattern is divided by the stroke width at this boundary.  Getting it wrong makes
guide lines look solid at width 0.6 and gappy at width 3.

**Arcs.**  Scene arcs are centre-parameterised, degrees, with the scene y axis
growing downward, so an increasing angle sweeps *clockwise* on screen.  Qt's
``QPainterPath.arcTo`` measures angles *counter-clockwise* from 3 o'clock in the
same y-down space, so the Qt angle is the negation of the scene angle and the Qt
sweep is the negation of the scene sweep.  :func:`arc_to_qt` is the single place
that knows this, and it is tested against directly computed polar points.

**Text.**  ``QFont`` sizes are integers, so text is drawn through the reference
font of :mod:`makeyourtree_studio.canvas.qt_metrics` under a painter scale.  That is
what makes the painted advance equal the advance the layout engine reserved.

Culling
-------
:attr:`QtBackend.clip_rect` lets the caller skip primitives that fall outside a
region -- the canvas sets it to the exposed rect so a viewport showing 300 of
400 000 branch segments pays for 300.  It only ever *skips* whole primitives, so
the output is identical to an unclipped pass; exporters leave it ``None``.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath,
                           QPen, QPolygonF)

from makeyourtree.render.backend import dispatch_mark
from makeyourtree.scene.marks import (Anchor, Baseline, Cap, EllipseMark, GroupMark,
                                  ImageMark, Join, Layer, LinesMark, Paint,
                                  PathMark, PolygonMark, PolylineMark, RectMark,
                                  RectsMark, Scene, TextMark)
from makeyourtree.style.color import Color

from .qt_metrics import REFERENCE_PIXEL_SIZE, qt_font

__all__ = ["QtBackend", "arc_to_qt", "build_path", "qcolor", "normalise_rect"]

_FULL_TURN_EPS = 1e-6

_CAP = {Cap.BUTT: Qt.PenCapStyle.FlatCap,
        Cap.ROUND: Qt.PenCapStyle.RoundCap,
        Cap.SQUARE: Qt.PenCapStyle.SquareCap}
_JOIN = {Join.MITER: Qt.PenJoinStyle.MiterJoin,
         Join.ROUND: Qt.PenJoinStyle.RoundJoin,
         Join.BEVEL: Qt.PenJoinStyle.BevelJoin}


def qcolor(color: Color | None, opacity: float = 1.0) -> QColor:
    """Convert a core :class:`~makeyourtree.style.color.Color` to ``QColor``.

    ``Paint.opacity`` multiplies into the alpha channel rather than becoming a
    painter opacity, so overlapping strokes inside one batched mark composite the
    way the SVG writer composites them.
    """
    if color is None:
        return QColor(0, 0, 0, 0)
    a = max(0.0, min(1.0, opacity)) * color.a
    return QColor(color.r, color.g, color.b, int(round(a)))


def normalise_rect(x: float, y: float, w: float,
                   h: float) -> tuple[float, float, float, float]:
    """Fold a negative width or height into the origin, as the SVG writer does."""
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    return (x, y, w, h)


def arc_to_qt(cx: float, cy: float, r: float, a0: float, a1: float,
              ccw: bool = False) -> tuple[QRectF, float, float]:
    """Centre-parameterised scene arc to ``(rect, start_deg, sweep_deg)`` for Qt.

    Scene angles grow clockwise on screen (y down); Qt angles grow
    counter-clockwise, so both the start angle and the sweep are negated.  The
    sweep magnitude is folded into ``(0, 360]`` exactly as the SVG writer folds
    it, so a wrap-around arc and a whole turn mean the same thing in both
    backends.  A zero sweep returns 0 and the caller draws nothing.
    """
    rect = QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r)
    raw = (a0 - a1) if ccw else (a1 - a0)
    delta = raw % 360.0
    if delta > 360.0 - _FULL_TURN_EPS or (abs(raw) > _FULL_TURN_EPS
                                          and delta < _FULL_TURN_EPS):
        delta = 360.0
    if delta <= _FULL_TURN_EPS:
        return rect, -a0, 0.0
    # Scene sweep is +delta clockwise (increasing angle) or -delta anticlockwise;
    # Qt measures the opposite way round, hence the flipped sign on both.
    return rect, -a0, (delta if ccw else -delta)


def polar_point(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    """Scene-space point at *angle_deg* on the circle of radius *r*."""
    a = math.radians(angle_deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def build_path(segments: Iterable[tuple]) -> QPainterPath:
    """Turn scene path segments into a ``QPainterPath``.

    A free function so hit-testing and the tests can build a path without a live
    painter.  The fill rule is set to winding because that is SVG's default and
    the two backends must agree about self-intersecting shapes.
    """
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    started = False
    for seg in segments:
        op = seg[0]
        if op == "M":
            path.moveTo(seg[1], seg[2])
            started = True
        elif op == "L":
            if not started:
                path.moveTo(seg[1], seg[2])
                started = True
            else:
                path.lineTo(seg[1], seg[2])
        elif op == "Q":
            if not started:
                path.moveTo(seg[1], seg[2])
                started = True
            path.quadTo(seg[1], seg[2], seg[3], seg[4])
        elif op == "C":
            if not started:
                path.moveTo(seg[1], seg[2])
                started = True
            path.cubicTo(seg[1], seg[2], seg[3], seg[4], seg[5], seg[6])
        elif op == "A":
            cx, cy, r, a0, a1 = seg[1], seg[2], seg[3], seg[4], seg[5]
            ccw = bool(seg[6]) if len(seg) > 6 else False
            start_pt = polar_point(cx, cy, r, a0)
            if not started:
                # arcTo would otherwise join the arc to the implicit origin.
                path.moveTo(*start_pt)
                started = True
            rect, start, sweep = arc_to_qt(cx, cy, r, a0, a1, ccw)
            if r <= 0 or sweep == 0.0:
                path.lineTo(*start_pt)
            else:
                path.arcTo(rect, start, sweep)
        elif op == "Z":
            if started:
                path.closeSubpath()
    return path


class QtBackend:
    """Implements :class:`makeyourtree.render.backend.RenderBackend` over ``QPainter``.

    The painter is borrowed, not owned: the canvas hands over the one Qt gave it
    in ``paint()``, and the raster exporter hands over one bound to a
    ``QImage``.  State is saved and restored around anything that changes the
    transform, so a caller can paint several scenes with one painter.
    """

    def __init__(self, painter: QPainter) -> None:
        self.painter = painter
        self.clip_rect: QRectF | None = None
        """Scene-space region to cull against, or ``None`` to draw everything."""
        self.fill_background = True
        """Whether :meth:`begin` paints the scene background.  The live canvas
        turns this off because the view already painted it."""
        self._scene: Scene | None = None
        self._pens: dict[Paint, QPen] = {}
        self._brushes: dict[tuple, QBrush] = {}
        self._layer: Layer | None = None

    # ------------------------------------------------------------ lifecycle

    def begin(self, scene: Scene) -> None:
        self._scene = scene
        bg = scene.background
        if self.fill_background and bg is not None and bg.a > 0:
            self.painter.fillRect(QRectF(0.0, 0.0, scene.width, scene.height),
                                  QBrush(qcolor(bg)))

    def end(self) -> bytes:
        """Nothing to serialise: a live painter has already produced its output."""
        self._layer = None
        return b""

    def begin_layer(self, layer: Layer) -> None:
        self._layer = layer

    def end_layer(self, layer: Layer) -> None:
        self._layer = None

    # ---------------------------------------------------------------- paint

    def pen_for(self, paint: Paint) -> QPen:
        """``QPen`` for a paint, cached because a batch reuses one pen."""
        hit = self._pens.get(paint)
        if hit is not None:
            return hit
        if paint.stroke is None or paint.stroke.a == 0 or paint.width <= 0:
            pen = QPen(Qt.PenStyle.NoPen)
        else:
            pen = QPen(qcolor(paint.stroke, paint.opacity))
            pen.setWidthF(float(paint.width))
            pen.setCapStyle(_CAP[paint.cap])
            pen.setJoinStyle(_JOIN[paint.join])
            if paint.cosmetic:
                pen.setCosmetic(True)
            if paint.dash:
                # Scene units to pen widths: Qt scales the pattern by the width.
                unit = float(paint.width) if paint.width > 0 else 1.0
                pattern = [max(1e-3, float(d) / unit) for d in paint.dash]
                if len(pattern) % 2:
                    pattern = pattern + pattern
                pen.setDashPattern(pattern)
        self._pens[paint] = pen
        return pen

    def brush_for(self, paint: Paint, fill: Color | None = None) -> QBrush:
        """``QBrush`` for a paint, optionally overriding the fill colour.

        The override is what makes a per-cell heatmap one mark: the pen stays
        put and only the brush changes between rectangles.
        """
        colour = paint.fill if fill is None else fill
        key = (colour, paint.opacity)
        hit = self._brushes.get(key)
        if hit is not None:
            return hit
        if colour is None or colour.a == 0:
            brush = QBrush(Qt.BrushStyle.NoBrush)
        else:
            brush = QBrush(qcolor(colour, paint.opacity))
        self._brushes[key] = brush
        return brush

    def _apply(self, paint: Paint, fill: Color | None = None) -> None:
        self.painter.setPen(self.pen_for(paint))
        self.painter.setBrush(self.brush_for(paint, fill))

    # -------------------------------------------------------------- culling

    def _visible(self, x0: float, y0: float, x1: float, y1: float) -> bool:
        clip = self.clip_rect
        if clip is None:
            return True
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        return not (x1 < clip.left() or x0 > clip.right()
                    or y1 < clip.top() or y0 > clip.bottom())

    def _flat_visible(self, flat: Sequence[float]) -> bool:
        if not flat:
            return False
        xs = flat[0::2]
        ys = flat[1::2]
        return self._visible(min(xs), min(ys), max(xs), max(ys))

    # ---------------------------------------------------------------- marks

    def draw_path(self, mark: PathMark) -> None:
        if not mark.segments:
            return
        path = build_path(mark.segments)
        if self.clip_rect is not None:
            b = path.controlPointRect()
            if not self._visible(b.left(), b.top(), b.right(), b.bottom()):
                return
        self._apply(mark.paint)
        self.painter.drawPath(path)

    def draw_lines(self, mark: LinesMark) -> None:
        """A whole pen bucket in one call.

        Culling happens here rather than in the compositor because the visible
        subset changes on every pan while the scene does not.
        """
        c = mark.coords
        if len(c) < 4:
            return
        clip = self.clip_rect
        lines: list[QLineF] = []
        for i in range(0, len(c) - 3, 4):
            x0, y0, x1, y1 = c[i], c[i + 1], c[i + 2], c[i + 3]
            if clip is not None and not self._visible(x0, y0, x1, y1):
                continue
            lines.append(QLineF(x0, y0, x1, y1))
        if not lines:
            return
        self.painter.setPen(self.pen_for(mark.paint))
        self.painter.setBrush(Qt.BrushStyle.NoBrush)
        self.painter.drawLines(lines)

    def draw_polyline(self, mark: PolylineMark) -> None:
        pts = mark.points
        if len(pts) < 4 or not self._flat_visible(pts):
            return
        poly = _polygon(pts)
        # SVG fills an open polyline as if it were closed; match that or a filled
        # ribbon would appear on export and not on screen.
        if mark.paint.fill is not None and mark.paint.fill.a > 0:
            self.painter.setPen(Qt.PenStyle.NoPen)
            self.painter.setBrush(self.brush_for(mark.paint))
            self.painter.drawPolygon(poly)
        self.painter.setPen(self.pen_for(mark.paint))
        self.painter.setBrush(Qt.BrushStyle.NoBrush)
        self.painter.drawPolyline(poly)

    def draw_polygon(self, mark: PolygonMark) -> None:
        pts = mark.points
        if len(pts) < 6 or not self._flat_visible(pts):
            return
        self._apply(mark.paint)
        self.painter.drawPolygon(_polygon(pts))

    def draw_rect(self, mark: RectMark) -> None:
        x, y, w, h = normalise_rect(mark.x, mark.y, mark.w, mark.h)
        if not self._visible(x, y, x + w, y + h):
            return
        self._apply(mark.paint)
        rect = QRectF(x, y, w, h)
        if mark.rx:
            self.painter.drawRoundedRect(rect, mark.rx, mark.rx)
        else:
            self.painter.drawRect(rect)

    def draw_rects(self, mark: RectsMark) -> None:
        """A batch of rectangles sharing a pen but not a fill.

        The pen is set once outside the loop: rebuilding it per cell is what
        makes a 200-column heatmap feel slow.
        """
        c = mark.coords
        if len(c) < 4:
            return
        painter = self.painter
        painter.setPen(self.pen_for(mark.paint))
        fills = mark.fills
        if fills is None:
            painter.setBrush(self.brush_for(mark.paint))
        clip = self.clip_rect
        for i in range(0, len(c) - 3, 4):
            x, y, w, h = normalise_rect(c[i], c[i + 1], c[i + 2], c[i + 3])
            if clip is not None and not self._visible(x, y, x + w, y + h):
                continue
            if fills is not None:
                idx = i // 4
                colour = fills[idx] if idx < len(fills) else None
                painter.setBrush(self.brush_for(mark.paint, colour))
            painter.drawRect(QRectF(x, y, w, h))

    def draw_ellipse(self, mark: EllipseMark) -> None:
        rx, ry = abs(mark.rx), abs(mark.ry)
        if rx <= 0 or ry <= 0:
            return
        if not self._visible(mark.cx - rx, mark.cy - ry, mark.cx + rx, mark.cy + ry):
            return
        self._apply(mark.paint)
        self.painter.drawEllipse(QPointF(mark.cx, mark.cy), rx, ry)

    def draw_text(self, mark: TextMark) -> None:
        """Anchor, baseline and rotation, drawn through the reference font.

        The painter is scaled from the reference pixel size down to the requested
        scene size so fractional sizes are exact and so the advance matches what
        :class:`~makeyourtree_studio.canvas.qt_metrics.QtMetrics` told the layout.
        """
        st = mark.style
        if not mark.text or st.size <= 0:
            return
        if self.clip_rect is not None and not self._text_visible(mark):
            return
        painter = self.painter
        scale = st.size / REFERENCE_PIXEL_SIZE
        font = qt_font(st.family, bold=st.weight >= 600, italic=st.italic)
        if st.letter_spacing:
            # Spacing is a scene-unit quantity, so it scales into font units
            # like every other length here.  A copy, because the cache is shared.
            font = QFont(font)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                                  st.letter_spacing / scale)
        painter.save()
        try:
            painter.translate(mark.x, mark.y)
            if mark.rotation:
                # Scene rotation is clockwise about the anchor, which is what a
                # positive Qt rotation means in a y-down space.
                painter.rotate(mark.rotation)
            painter.scale(scale, scale)
            painter.setFont(font)
            fm = painter.fontMetrics()
            text = mark.text
            if mark.max_width is not None and mark.max_width > 0:
                text = fm.elidedText(text, Qt.TextElideMode.ElideRight,
                                     int(round(mark.max_width / scale)))
            advance = fm.horizontalAdvance(text)
            if st.anchor is Anchor.MIDDLE:
                ox = -advance / 2.0
            elif st.anchor is Anchor.END:
                ox = -advance
            else:
                ox = 0.0
            if st.baseline is Baseline.MIDDLE:
                oy = (fm.ascent() - fm.descent()) / 2.0
            elif st.baseline is Baseline.HANGING:
                oy = fm.ascent()
            else:
                oy = 0.0
            painter.setPen(QPen(qcolor(st.color, st.opacity)))
            painter.drawText(QPointF(ox, oy), text)
        finally:
            painter.restore()

    def _text_visible(self, mark: TextMark) -> bool:
        """Generous bound for a label, used only to cull.

        Measuring every off-screen label to cull it would cost more than drawing
        it, so the box is estimated from the size and length and padded.
        """
        size = mark.style.size
        width = mark.max_width if mark.max_width else size * (len(mark.text) + 2)
        reach = max(width, size * 2.0)
        if mark.rotation:
            reach = math.hypot(reach, size * 2.0)
        return self._visible(mark.x - reach, mark.y - reach,
                             mark.x + reach, mark.y + reach)

    def draw_image(self, mark: ImageMark) -> None:
        if not mark.data or mark.w <= 0 or mark.h <= 0:
            return
        if not self._visible(mark.x, mark.y, mark.x + mark.w, mark.y + mark.h):
            return
        image = QImage()
        if not image.loadFromData(bytes(mark.data)):
            return
        painter = self.painter
        painter.save()
        try:
            if mark.paint.opacity < 1.0:
                painter.setOpacity(max(0.0, mark.paint.opacity))
            if mark.rotation:
                cx = mark.x + mark.w / 2.0
                cy = mark.y + mark.h / 2.0
                painter.translate(cx, cy)
                painter.rotate(mark.rotation)
                painter.translate(-cx, -cy)
            painter.drawImage(QRectF(mark.x, mark.y, mark.w, mark.h), image)
        finally:
            painter.restore()

    def draw_group(self, mark: GroupMark) -> None:
        """Translate, optionally clip, then dispatch the children.

        The clip is expressed in the group's own space, after the translation,
        which is how SVG resolves ``clip-path`` on a transformed ``<g>``.
        """
        painter = self.painter
        saved_clip = self.clip_rect
        painter.save()
        try:
            if mark.dx or mark.dy:
                painter.translate(mark.dx, mark.dy)
                if saved_clip is not None:
                    self.clip_rect = saved_clip.translated(-mark.dx, -mark.dy)
            if mark.clip is not None:
                x0, y0, x1, y1 = mark.clip
                x, y, w, h = normalise_rect(x0, y0, x1 - x0, y1 - y0)
                painter.setClipRect(QRectF(x, y, w, h), Qt.ClipOperation.IntersectClip)
            for child in mark.marks:
                dispatch_mark(self, child)
        finally:
            self.clip_rect = saved_clip
            painter.restore()


def _polygon(flat: Sequence[float]) -> QPolygonF:
    return QPolygonF([QPointF(flat[i], flat[i + 1])
                      for i in range(0, len(flat) - 1, 2)])
