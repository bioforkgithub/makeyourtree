# SPDX-License-Identifier: MIT
"""Graphics items: one per scene layer, never one per node.

This module is where the application's performance is decided.

A 100 000-leaf document is ~200 000 nodes and ~400 000 branch segments.
``QGraphicsScene`` degrades badly past roughly 50 000 items -- indexing, change
notification and per-item paint dispatch all become the bottleneck -- so putting
a ``QGraphicsItem`` on each node is not a slow design, it is an unusable one.
Instead there is exactly one :class:`SceneLayerItem` per
:class:`makeyourtree.scene.Layer`, ten items at most, each painting every mark in
its layer through :class:`~makeyourtree_studio.canvas.qt_backend.QtBackend`.  The
compositor has already bucketed hundreds of thousands of segments into a handful
of batched marks, so a full repaint is a few dozen ``QPainter`` calls.

Three rules follow from that shape and are load-bearing:

* ``boundingRect()`` must be O(1).  It is called on every paint, every
  intersection test and every scene-rect recalculation, and with items this
  large a walk over the marks would dominate.  The rect is supplied by the
  builder and cached; changes go through ``prepareGeometryChange()`` so Qt does
  not keep a stale entry.
* Painting must cull.  With no per-item culling left to Qt, the item asks for
  ``option.exposedRect`` -- meaningful only because
  ``ItemUsesExtendedStyleOption`` is set -- and hands it to the backend, which
  skips primitives outside it.
* Selection and hover live in their own item.  :class:`OverlayLayerItem` reads
  the session directly and repaints without recomposing anything, which is the
  entire reason :class:`~makeyourtree_studio.session.Dirty.OVERLAY` exists as a
  separate level.
"""

from __future__ import annotations

import math
from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QPainter, QPen
from PySide6.QtWidgets import (QGraphicsItem, QStyleOptionGraphicsItem, QWidget)

from makeyourtree.layout.frame import LayoutFrame
from makeyourtree.render.backend import dispatch_mark
from makeyourtree.scene.marks import Layer, Mark
from makeyourtree.style.theme import Theme

from .qt_backend import QtBackend, qcolor

__all__ = ["SceneLayerItem", "OverlayLayerItem", "OVERLAY_Z", "layer_z"]

OVERLAY_Z = 1000.0
"""Z above every scene layer, so interaction affordances are never buried."""

_SELECTION_RADIUS = 5.0
"""Ring radius in *pixels*; scaled into scene units at paint time so the
affordance stays the same size at every zoom level."""
_HOVER_RADIUS = 6.5
_SEARCH_RADIUS = 8.0


def layer_z(layer: Layer) -> float:
    """Stacking order of a layer, following :meth:`makeyourtree.scene.Layer.order`."""
    order = Layer.order()
    return float(order.index(layer)) if layer in order else 0.0


class SceneLayerItem(QGraphicsItem):
    """Every mark of one :class:`makeyourtree.scene.Layer`, painted by one item.

    The item owns no geometry of its own: it is handed the marks and a
    pre-computed bounding rect by the canvas, because the canvas already knows
    the page size and computing a tight bound would mean measuring text.
    """

    def __init__(self, layer: Layer, marks: Sequence[Mark] = (),
                 rect: QRectF | None = None,
                 parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self._layer = layer
        self._marks: Sequence[Mark] = tuple(marks)
        self._rect = QRectF(rect) if rect is not None else QRectF()
        self._backend: QtBackend | None = None
        # exposedRect is only filled in when the item asks for it.
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        self.setZValue(layer_z(layer))
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    # ------------------------------------------------------------- contents

    @property
    def layer(self) -> Layer:
        return self._layer

    @property
    def marks(self) -> Sequence[Mark]:
        return self._marks

    def mark_count(self) -> int:
        return len(self._marks)

    def set_marks(self, marks: Sequence[Mark],
                  rect: QRectF | None = None) -> None:
        """Swap in a recomposed layer.

        ``prepareGeometryChange`` is mandatory whenever *rect* moves: Qt caches
        the bounding rect and will paint into the old one otherwise.
        """
        new_rect = QRectF(rect) if rect is not None else self._rect
        if new_rect != self._rect:
            self.prepareGeometryChange()
            self._rect = new_rect
        self._marks = tuple(marks)
        self.update()

    def set_bounds(self, rect: QRectF) -> None:
        if QRectF(rect) != self._rect:
            self.prepareGeometryChange()
            self._rect = QRectF(rect)

    # -------------------------------------------------------------- drawing

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        """The cached rect.  Deliberately no computation: see the module docstring."""
        return self._rect

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:  # noqa: N802 - Qt override
        if not self._marks:
            return
        backend = self._backend
        if backend is None:
            backend = self._backend = QtBackend(painter)
            # The view has already painted the page; a second fill per layer
            # would erase everything beneath it.
            backend.fill_background = False
        else:
            backend.painter = painter
        exposed = getattr(option, "exposedRect", None)
        backend.clip_rect = exposed if exposed is not None and exposed.isValid() else None
        for mark in self._marks:
            dispatch_mark(backend, mark)
        backend.clip_rect = None


class OverlayLayerItem(QGraphicsItem):
    """Selection, hover and search hits, repainted without recomposing.

    Reads the session live rather than caching a copy, so a selection change
    costs one ``update()`` and one repaint of the exposed region.  Nothing here
    is ever exported: the overlay layer is interaction state, and
    :func:`makeyourtree.render.render` skips it by default for that reason.
    """

    def __init__(self, session, rect: QRectF | None = None,
                 parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._rect = QRectF(rect) if rect is not None else QRectF()
        self._frame: LayoutFrame | None = None
        self._origin = (0.0, 0.0)
        self._marks: Sequence[Mark] = ()
        self._backend: QtBackend | None = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        self.setZValue(OVERLAY_Z)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    # ------------------------------------------------------------- contents

    def set_frame(self, frame: LayoutFrame | None,
                  origin: tuple[float, float] = (0.0, 0.0)) -> None:
        """Bind the geometry the overlay reads node positions from.

        *origin* is ``scene.metadata["origin"]``: the compositor shifts content
        away from the page edge with a group translation instead of rewriting
        every coordinate, so the overlay has to apply the same shift by hand.
        """
        self._frame = frame
        self._origin = origin
        self.update()

    def set_marks(self, marks: Sequence[Mark]) -> None:
        """Overlay marks the compositor or a track contributed."""
        self._marks = tuple(marks)
        self.update()

    def set_bounds(self, rect: QRectF) -> None:
        if QRectF(rect) != self._rect:
            self.prepareGeometryChange()
            self._rect = QRectF(rect)

    def refresh(self) -> None:
        """Repaint the affordances.  Never touches the layout or the scene."""
        self.update()

    # -------------------------------------------------------------- drawing

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        return self._rect

    def _theme(self) -> Theme:
        return self._session.document.theme

    def _position(self, node_id: int) -> QPointF | None:
        frame = self._frame
        if frame is None or not frame.has(node_id):
            return None
        x, y = frame.xy(node_id)
        return QPointF(x + self._origin[0], y + self._origin[1])

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:  # noqa: N802 - Qt override
        if self._marks:
            backend = self._backend
            if backend is None:
                backend = self._backend = QtBackend(painter)
                backend.fill_background = False
            else:
                backend.painter = painter
            exposed = getattr(option, "exposedRect", None)
            backend.clip_rect = (exposed if exposed is not None
                                 and exposed.isValid() else None)
            for mark in self._marks:
                dispatch_mark(backend, mark)
            backend.clip_rect = None

        frame = self._frame
        if frame is None:
            return
        session = self._session
        theme = self._theme()
        # One scene unit is this many pixels; ring radii are specified in pixels
        # so they neither vanish when zoomed out nor swallow the tree zoomed in.
        transform = painter.worldTransform()
        det = abs(transform.determinant())
        unit = 1.0 / math.sqrt(det) if det > 1e-12 else 1.0

        exposed = getattr(option, "exposedRect", None)
        clip = exposed if exposed is not None and exposed.isValid() else None

        painter.setBrush(Qt.BrushStyle.NoBrush)

        hits = session.search_hits
        if hits:
            pen = QPen(qcolor(theme.search_hit_color))
            pen.setWidthF(2.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            radius = _SEARCH_RADIUS * unit
            for node_id in hits:
                pos = self._position(node_id)
                if pos is not None and _inside(pos, radius, clip):
                    painter.drawEllipse(pos, radius, radius)

        hover = session.hover
        if hover is not None:
            pos = self._position(hover)
            if pos is not None:
                radius = _HOVER_RADIUS * unit
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(qcolor(theme.hover_color)))
                painter.drawEllipse(pos, radius, radius)
                painter.setBrush(Qt.BrushStyle.NoBrush)

        selection = session.selection
        if selection:
            pen = QPen(qcolor(theme.selection_color))
            pen.setWidthF(max(1.0, theme.selection_width))
            pen.setCosmetic(True)
            painter.setPen(pen)
            radius = _SELECTION_RADIUS * unit
            for node_id in selection:
                pos = self._position(node_id)
                if pos is not None and _inside(pos, radius, clip):
                    painter.drawEllipse(pos, radius, radius)


def _inside(pos: QPointF, radius: float, clip: QRectF | None) -> bool:
    if clip is None:
        return True
    return (clip.left() - radius <= pos.x() <= clip.right() + radius
            and clip.top() - radius <= pos.y() <= clip.bottom() + radius)
