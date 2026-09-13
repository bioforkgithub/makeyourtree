# SPDX-License-Identifier: MIT
"""The tree canvas: camera, repaint scheduling and pointer gestures.

``TreeCanvas`` owns a ``QGraphicsScene`` containing a handful of
:class:`~makeyourtree_studio.canvas.layers.SceneLayerItem` objects and one
:class:`~makeyourtree_studio.canvas.layers.OverlayLayerItem` -- see that module for
why the item count is fixed rather than proportional to the tree.

Two invariants make the canvas feel fast.

**Zoom is a camera move, not a recomposition.**  Scaling the view changes a
``QTransform`` and nothing else: no layout, no compositing, no new marks.  A
wheel gesture that triggered a relayout would stall for seconds on a large tree,
so there is a test that spins two hundred wheel events through the widget and
asserts ``compute_layout`` was never called.

**Invalidation coalesces.**  Dragging a slider emits ``dirtied`` on every
pixel.  The canvas records the worst :class:`~makeyourtree_studio.session.Dirty`
level seen and flushes once on a zero-timer, so a burst costs one
recomposition.  ``Dirty.OVERLAY`` never reaches the compositor at all -- it
repaints the overlay item and returns, which is the whole reason the level
exists.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QColor, QImage, QKeyEvent, QMouseEvent, QPainter,
                           QTransform, QWheelEvent)
from PySide6.QtWidgets import (QGraphicsScene, QGraphicsView, QRubberBand,
                               QToolTip, QWidget)

from makeyourtree.scene.marks import Layer

from ..session import Dirty, Session
from .interaction import DEFAULT_TOLERANCE_PX, CanvasInteractor, scene_origin
from .layers import OverlayLayerItem, SceneLayerItem
from .qt_backend import qcolor

__all__ = ["TreeCanvas", "MIN_ZOOM", "MAX_ZOOM"]

MIN_ZOOM = 0.01
MAX_ZOOM = 400.0

SLOW_LAYOUT_TIPS = 2000
"""Tip count above which a recomposition is announced before it starts.

Measured on this machine: a 5,000-tip tree takes about six seconds to lay out
in circular mode and nine in unrooted, and the window does not repaint for the
duration.  Two thousand is comfortably below the point where the pause becomes
noticeable, and announcing a recomposition that turns out to be quick costs
only a cursor flicker."""
_WHEEL_STEP = 480.0
"""Wheel delta for one doubling.  A notch is 120, so four notches double the
scale -- fine enough to land on a readable size without over-shooting."""

_BOUNDS_PAD = 48.0
"""Slack added to the page rect for the layer bounding rects.  Cosmetic strokes
and rotated labels can reach past the page edge, and an item that under-reports
its bounds leaves paint droppings behind."""


class TreeCanvas(QGraphicsView):
    """The central widget: draws the session's scene and edits its selection."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._items: dict[Layer, SceneLayerItem] = {}
        self._layer_marks: dict[Layer, Any] = {}
        self._pending = Dirty.NOTHING
        self._registry = None
        self._panning = False
        self._pan_origin = QPoint()
        self._space_held = False
        self._band_origin: QPoint | None = None
        self._band: QRubberBand | None = None

        self._gscene = QGraphicsScene(self)
        # With ten enormous items the BSP index is pure overhead: every repaint
        # would rebuild a tree whose every query returns everything.
        self._gscene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.setScene(self._gscene)

        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setOptimizationFlag(
            QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # Anchoring is done by hand in zoom_by so the point under the cursor
        # stays put even when the scroll bars are already at their limit.
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        self.interactor = CanvasInteractor(session, self)
        self._overlay = OverlayLayerItem(session)
        self._gscene.addItem(self._overlay)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._flush)

        session.dirtied.connect(self._on_dirtied)
        session.recomposed.connect(self._rebuild)
        session.documentReplaced.connect(self._on_document_replaced)
        session.selectionChanged.connect(self._overlay.refresh)

        self._sync_metrics()
        # Compose once synchronously so a freshly built canvas already has
        # content, with no dependency on an event loop having run.
        self.refresh()

    # ------------------------------------------------------------- plumbing

    @property
    def session(self) -> Session:
        return self._session

    @property
    def overlay(self) -> OverlayLayerItem:
        return self._overlay

    def layer_items(self) -> dict[Layer, SceneLayerItem]:
        """The live layer items, keyed by layer.  Read-only; used by tests."""
        return dict(self._items)

    def set_action_registry(self, registry) -> None:
        """Supply the registry the context menu is built from."""
        self._registry = registry

    def _sync_metrics(self) -> None:
        """Make the compositor measure text the way the canvas will paint it.

        ``compose`` reads its metrics from the document, while the session holds
        the injected Qt implementation.  Left unsynchronised, label widths on
        screen would differ from the widths the layout reserved.
        """
        metrics = getattr(self._session, "metrics", None)
        if metrics is None:
            return
        meta = self._session.document.metadata
        if meta.get("text_metrics") is None:
            meta["text_metrics"] = metrics

    # -------------------------------------------------------- recomposition

    def _on_dirtied(self, level: int) -> None:
        if level > self._pending:
            self._pending = Dirty(level)
        if not self._timer.isActive():
            self._timer.start()

    def _on_document_replaced(self) -> None:
        self.interactor.invalidate()
        self._sync_metrics()
        self._pending = Dirty.TOPOLOGY
        self.refresh()
        self.fit_to_view()

    def refresh(self) -> None:
        """Flush any pending invalidation now instead of on the next tick."""
        self._timer.stop()
        self._flush()

    def _flush(self) -> None:
        level = self._pending
        self._pending = Dirty.NOTHING
        session = self._session
        if session.scene is not None and level <= Dirty.OVERLAY:
            # Selection and hover changed nothing the compositor produced.
            self._overlay.refresh()
            return
        if session.tree.root is None:
            self._clear_items()
            return
        if level >= Dirty.TOPOLOGY:
            self.interactor.invalidate()
        self._recompose_with_feedback(session)

    def _recompose_with_feedback(self, session: Session) -> None:
        """Recompose, saying so first when it will take a visible moment.

        Layout and composition run on this thread, so above a few thousand tips
        the window stops repainting for several seconds.  It is working, not
        hung, but the two look identical from outside.  A wait cursor and a
        status line cost nothing and tell the difference; moving the work off
        the thread is the real fix and needs a change to the frozen
        ``Session`` contract.
        """
        n_leaves = getattr(session.tree, "n_leaves", 0) or 0
        if n_leaves < SLOW_LAYOUT_TIPS:
            session.recompose()
            return

        from PySide6.QtWidgets import QApplication

        session.statusMessage.emit(
            f"Laying out {n_leaves:,} tips…", 0)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        # One pass so the cursor and the message are actually painted before
        # the thread disappears into the layout.
        QApplication.processEvents()
        try:
            session.recompose()
        finally:
            QApplication.restoreOverrideCursor()
            session.statusMessage.emit("", 0)

    def _clear_items(self) -> None:
        for item in self._items.values():
            self._gscene.removeItem(item)
        self._items.clear()
        self._layer_marks.clear()
        self._overlay.set_frame(None)
        self._overlay.set_marks(())

    def _rebuild(self) -> None:
        """Mirror the recomposed scene into the graphics items.

        Layers whose mark list is the very object already on screen are left
        alone; a recomposition that only touched the labels does not force the
        branch layer to invalidate its cached geometry and repaint.
        """
        scene = self._session.scene
        if scene is None:
            self._clear_items()
            return
        page = QRectF(0.0, 0.0, max(1.0, scene.width), max(1.0, scene.height))
        bounds = page.adjusted(-_BOUNDS_PAD, -_BOUNDS_PAD, _BOUNDS_PAD, _BOUNDS_PAD)
        if self._gscene.sceneRect() != page:
            self._gscene.setSceneRect(page)
        self.setBackgroundBrush(qcolor(scene.background)
                                if scene.background.a > 0
                                else QColor(0, 0, 0, 0))

        for layer in Layer.order():
            marks = scene.layers.get(layer) or ()
            if layer is Layer.OVERLAY:
                self._overlay.set_marks(marks)
                continue
            item = self._items.get(layer)
            if not marks:
                if item is not None:
                    self._gscene.removeItem(item)
                    del self._items[layer]
                    self._layer_marks.pop(layer, None)
                continue
            if item is None:
                item = SceneLayerItem(layer, marks, bounds)
                self._gscene.addItem(item)
                self._items[layer] = item
                self._layer_marks[layer] = marks
                continue
            if self._layer_marks.get(layer) is marks:
                item.set_bounds(bounds)
            else:
                item.set_marks(marks, bounds)
                self._layer_marks[layer] = marks

        self._overlay.set_bounds(bounds)
        self._overlay.set_frame(scene.metadata.get("frame"), scene_origin(self._session))

    # ----------------------------------------------------------------- camera

    @property
    def zoom(self) -> float:
        """Current uniform scale factor of the view transform."""
        t = self.transform()
        return math.sqrt(abs(t.determinant())) or 1.0

    def fit_to_view(self) -> None:
        """Scale so the whole page is visible, preserving aspect."""
        rect = self._gscene.sceneRect()
        if rect.isEmpty():
            return
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_by(self, factor: float, anchor: QPointF | QPoint | None = None) -> None:
        """Scale by *factor* about *anchor*, a point in viewport coordinates.

        Pure camera work: nothing here touches the session, so no relayout can
        be triggered however fast the wheel spins.
        """
        if factor <= 0 or not math.isfinite(factor):
            return
        current = self.zoom
        target = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        factor = target / current
        if abs(factor - 1.0) < 1e-9:
            return
        if anchor is None:
            anchor = QPointF(self.viewport().rect().center())
        point = anchor.toPoint() if isinstance(anchor, QPointF) else anchor
        before = self.mapToScene(point)
        self.scale(factor, factor)
        after = self.mapToScene(point)
        # QGraphicsView drives scrolling from the scroll bars and ignores the
        # translation component of the view transform, so the anchor is restored
        # by moving the camera centre rather than by translating the matrix.
        centre = self.mapToScene(self.viewport().rect().center())
        self.centerOn(centre + (before - after))

    def reset_zoom(self) -> None:
        """Back to one scene unit per pixel."""
        self.setTransform(QTransform())

    def center_on_node(self, node_id: int) -> None:
        """Scroll so a node sits in the middle of the viewport."""
        frame = self.interactor.hits.frame
        if frame is None or not frame.has(node_id):
            return
        dx, dy = scene_origin(self._session)
        x, y = frame.xy(node_id)
        self.centerOn(QPointF(x + dx, y + dy))

    # ----------------------------------------------------------------- export

    def export_image(self, path: str, *, scale: float = 2.0) -> None:
        """Render the current scene to a raster file at *scale* times size.

        The overlay is hidden for the duration: selection rings are interaction
        state, and an exported figure that carries them is a support ticket.
        """
        rect = self._gscene.sceneRect()
        if rect.isEmpty():
            raise ValueError("nothing to export: the scene is empty")
        scale = max(0.01, float(scale))
        size = QSize(max(1, int(round(rect.width() * scale))),
                     max(1, int(round(rect.height() * scale))))
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        background = self._session.document.theme.background
        image.fill(qcolor(background) if background.a > 0 else Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        was_visible = self._overlay.isVisible()
        self._overlay.setVisible(False)
        try:
            self._gscene.render(painter, QRectF(QPointF(0.0, 0.0), QPointF(
                float(size.width()), float(size.height()))), rect)
        finally:
            painter.end()
            self._overlay.setVisible(was_visible)
        if not image.save(path):
            raise OSError(f"could not write image to {path!r}")

    # -------------------------------------------------------------- gestures

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
            event.ignore()
            return
        self.zoom_by(2.0 ** (delta / _WHEEL_STEP), event.position())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        button = event.button()
        pan = (button == Qt.MouseButton.MiddleButton
               or (button == Qt.MouseButton.LeftButton and self._space_held))
        if pan:
            self._panning = True
            self._pan_origin = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton:
            node = self._node_at(event.position())
            if node is None:
                self._band_origin = event.position().toPoint()
                if self._band is None:
                    self._band = QRubberBand(QRubberBand.Shape.Rectangle,
                                             self.viewport())
                self._band.setGeometry(QRect(self._band_origin, QSize()))
                self._band.show()
            else:
                self.interactor.click(node, event.modifiers())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._panning:
            point = pos.toPoint()
            delta = point - self._pan_origin
            self._pan_origin = point
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            h.setValue(h.value() - delta.x())
            v.setValue(v.value() - delta.y())
            event.accept()
            return
        if self._band_origin is not None and self._band is not None:
            self._band.setGeometry(
                QRect(self._band_origin, pos.toPoint()).normalized())
            event.accept()
            return
        node = self._node_at(pos)
        text = self.interactor.hover(node)
        if text:
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        else:
            QToolTip.hideText()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._panning and event.button() in (Qt.MouseButton.MiddleButton,
                                                Qt.MouseButton.LeftButton):
            self._panning = False
            self.viewport().unsetCursor()
            event.accept()
            return
        if self._band_origin is not None and event.button() == Qt.MouseButton.LeftButton:
            rect = QRect(self._band_origin, event.position().toPoint()).normalized()
            self._band_origin = None
            if self._band is not None:
                self._band.hide()
            if rect.width() > 2 and rect.height() > 2:
                self.interactor.rubber_band(
                    self.mapToScene(rect).boundingRect(), event.modifiers())
            else:
                self.interactor.click(None, event.modifiers())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        self.interactor.double_click(self._node_at(event.position()),
                                     event.modifiers())
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        node = self._node_at(QPointF(event.pos()))
        self.interactor.prepare_context(node)
        menu = self.interactor.build_context_menu(self._registry, self)
        if menu is None:
            event.ignore()
            return
        menu.exec(event.globalPos())
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            if not self._panning:
                self.viewport().unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.interactor.hover(None)
        QToolTip.hideText()
        super().leaveEvent(event)

    # ------------------------------------------------------------ hit-testing

    def node_at(self, scene_pos: QPointF,
                tolerance_px: float = DEFAULT_TOLERANCE_PX) -> int | None:
        """Node nearest a *scene*-space point, within a pixel tolerance."""
        return self.interactor.node_at(scene_pos, view_scale=self.zoom,
                                       tolerance_px=tolerance_px)

    def _node_at(self, viewport_pos: QPointF) -> int | None:
        return self.node_at(self.mapToScene(viewport_pos.toPoint()))
