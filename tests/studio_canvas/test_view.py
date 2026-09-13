# SPDX-License-Identifier: MIT
"""TreeCanvas: camera, repaint scheduling and export.

The zoom test is the one that matters most.  Zoom is a view transform; if it
ever reaches the layout engine, spinning a wheel on a 100 000-leaf tree stalls
the application for seconds per notch.  Two hundred wheel events are pushed
through the widget with ``compute_layout`` under a spy, and the spy must not
fire once.
"""

from __future__ import annotations

import pytest

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene

import makeyourtree.layout as layout_module

from makeyourtree.layout.params import LayoutMode
from makeyourtree.scene.marks import Layer

from makeyourtree_studio.canvas.view import MAX_ZOOM, MIN_ZOOM, TreeCanvas
from makeyourtree_studio.session import Dirty

from canvas_helpers import ALL_MODES, balanced_tree, make_session


class LayoutSpy:
    """Counts every call to the layout engine, wherever it is reached from."""

    def __init__(self, monkeypatch) -> None:
        self.calls = 0
        real = layout_module.compute_layout

        def counted(*args, **kw):
            self.calls += 1
            return real(*args, **kw)

        monkeypatch.setattr(layout_module, "compute_layout", counted)


def wheel(canvas: TreeCanvas, delta: int, at: QPointF | None = None) -> None:
    point = at if at is not None else QPointF(canvas.viewport().rect().center())
    canvas.wheelEvent(QWheelEvent(
        point, canvas.mapToGlobal(point.toPoint()).toPointF(), QPoint(0, 0),
        QPoint(0, delta), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))


def render_canvas(canvas: TreeCanvas) -> QImage:
    image = QImage(canvas.viewport().size(),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    try:
        canvas.render(painter)
    finally:
        painter.end()
    return image


# --------------------------------------------------------------- construction


def test_scene_is_configured_for_a_few_huge_items(qapp, canvas):
    scene = canvas.scene()
    assert scene.itemIndexMethod() == QGraphicsScene.ItemIndexMethod.NoIndex
    assert canvas.viewportUpdateMode() == (
        TreeCanvas.ViewportUpdateMode.SmartViewportUpdate)
    assert canvas.optimizationFlags() & (
        TreeCanvas.OptimizationFlag.DontSavePainterState)
    assert canvas.renderHints() & QPainter.RenderHint.Antialiasing


@pytest.mark.parametrize("mode", ALL_MODES, ids=lambda m: m.value)
def test_a_real_document_builds_and_paints(qapp, mode):
    """Every layout mode must survive a full compose-and-paint offscreen."""
    session = make_session(mode=mode)
    canvas = TreeCanvas(session)
    canvas.resize(640, 480)
    assert session.scene is not None
    assert canvas.layer_items()
    image = render_canvas(canvas)
    assert not image.isNull()
    canvas.fit_to_view()
    assert not render_canvas(canvas).isNull()


def test_a_large_document_paints_at_several_zoom_levels(qapp):
    session = make_session(balanced_tree(2000))
    canvas = TreeCanvas(session)
    canvas.resize(600, 400)
    canvas.fit_to_view()
    for factor in (1.0, 4.0, 0.25):
        canvas.zoom_by(factor)
        assert not render_canvas(canvas).isNull()


def test_an_empty_document_does_not_explode(qapp):
    from makeyourtree.core.tree import Tree
    from makeyourtree.doc.document import Document

    from makeyourtree_studio.session import Session

    canvas = TreeCanvas(Session(Document(tree=Tree())))
    assert canvas.layer_items() == {}
    assert not render_canvas(canvas).isNull()


# ---------------------------------------------------------------------- zoom


def test_two_hundred_wheel_events_never_relayout(qapp, canvas, monkeypatch):
    canvas.fit_to_view()
    spy = LayoutSpy(monkeypatch)
    before = canvas.zoom
    for i in range(200):
        wheel(canvas, 120 if i % 2 == 0 else -120)
    wheel(canvas, 120)
    assert spy.calls == 0
    assert canvas.zoom != before
    assert canvas.session.dirty == Dirty.NOTHING


def test_zoom_by_scales_and_clamps(qapp, canvas):
    canvas.reset_zoom()
    canvas.zoom_by(2.0)
    assert canvas.zoom == pytest.approx(2.0)
    canvas.zoom_by(0.5)
    assert canvas.zoom == pytest.approx(1.0)
    canvas.zoom_by(1e9)
    assert canvas.zoom == pytest.approx(MAX_ZOOM)
    canvas.zoom_by(1e-12)
    assert canvas.zoom == pytest.approx(MIN_ZOOM)
    canvas.zoom_by(0.0)
    assert canvas.zoom == pytest.approx(MIN_ZOOM)


def test_zoom_is_anchored_under_the_cursor(qapp):
    """The point you point at is the point that stays put."""
    session = make_session(balanced_tree(400))
    canvas = TreeCanvas(session)
    canvas.resize(400, 300)
    canvas.reset_zoom()
    canvas.zoom_by(4.0)
    anchor = QPointF(120.0, 90.0)
    before = canvas.mapToScene(anchor.toPoint())
    canvas.zoom_by(2.0, anchor)
    after = canvas.mapToScene(anchor.toPoint())
    # Scroll offsets are whole pixels, so a fraction of a scene unit of slip is
    # unavoidable; a mis-anchored zoom slips by hundreds.
    assert abs(after.x() - before.x()) < 2.0
    assert abs(after.y() - before.y()) < 2.0


def test_reset_zoom_and_fit(qapp, canvas):
    canvas.zoom_by(3.0)
    canvas.reset_zoom()
    assert canvas.zoom == pytest.approx(1.0)
    canvas.fit_to_view()
    rect = canvas.scene().sceneRect()
    visible = canvas.mapToScene(canvas.viewport().rect()).boundingRect()
    assert visible.width() >= rect.width() - 1.0
    assert visible.height() >= rect.height() - 1.0


def test_center_on_node(qapp, canvas):
    canvas.reset_zoom()
    canvas.zoom_by(6.0)
    frame = canvas.session.scene.metadata["frame"]
    tip = frame.tips[-1]
    canvas.center_on_node(tip)
    dx, dy = canvas.session.scene.metadata["origin"]
    x, y = frame.xy(tip)
    centre = canvas.mapToScene(canvas.viewport().rect().center())
    assert abs(centre.x() - (x + dx)) < 4.0
    assert abs(centre.y() - (y + dy)) < 4.0
    # An unknown node is a no-op, not a crash.
    canvas.center_on_node(-1)


# ------------------------------------------------------------ recomposition


def test_overlay_dirt_never_reaches_the_compositor(qapp, canvas, monkeypatch):
    """``Dirty.OVERLAY`` exists precisely so selection is not a recomposition."""
    spy = LayoutSpy(monkeypatch)
    scene_before = canvas.session.scene
    frame = scene_before.metadata["frame"]
    canvas.session.set_selection({frame.tips[0]})
    canvas.session.set_hover(frame.tips[1])
    canvas.session.set_search_hits([frame.tips[2]])
    canvas.refresh()
    assert spy.calls == 0
    assert canvas.session.scene is scene_before


def test_a_burst_of_changes_costs_one_recomposition(qapp, canvas, monkeypatch):
    """Dragging a slider emits ``dirtied`` per pixel; the canvas coalesces."""
    recomposed = []
    canvas.session.recomposed.connect(lambda: recomposed.append(1))
    spy = LayoutSpy(monkeypatch)
    for spacing in range(16, 24):
        canvas.session.set_params(row_spacing=float(spacing))
    assert recomposed == []
    qapp.processEvents()
    assert len(recomposed) == 1
    # One recomposition, not eight.  It is two layout passes rather than one
    # because ``Session.recompose`` builds the frame it exposes for hit-testing
    # and ``compose`` builds the one the marks come from.
    assert spy.calls <= 2


def test_style_change_rebuilds_the_layer_items(qapp, canvas):
    before = canvas.layer_items()[Layer.BRANCHES]
    canvas.session.set_theme_attr(branch_width=4.0)
    canvas.refresh()
    after = canvas.layer_items()[Layer.BRANCHES]
    # The item is reused; only its contents are replaced.
    assert after is before
    assert after.mark_count() >= 1


def test_layout_mode_change_recomposes(qapp, canvas):
    canvas.session.set_params(mode=LayoutMode.CIRCULAR)
    canvas.refresh()
    assert canvas.session.frame.mode is LayoutMode.CIRCULAR
    assert not render_canvas(canvas).isNull()


def test_replacing_the_document_rebuilds_from_scratch(qapp, canvas):
    from makeyourtree.doc.document import Document

    canvas.session.set_document(Document(tree=balanced_tree(64)))
    canvas.refresh()
    assert len(canvas.session.scene.metadata["frame"].tips) == 64
    assert canvas.layer_items()


def test_scene_rect_follows_the_page(qapp, canvas):
    scene = canvas.session.scene
    assert canvas.scene().sceneRect() == QRectF(0.0, 0.0, scene.width, scene.height)


# -------------------------------------------------------------------- export


def test_export_image_writes_a_scaled_raster(qapp, canvas, tmp_path):
    path = tmp_path / "tree.png"
    canvas.export_image(str(path), scale=2.0)
    assert path.exists()
    image = QImage(str(path))
    scene = canvas.session.scene
    assert image.width() == pytest.approx(round(scene.width * 2.0), abs=1)
    assert image.height() == pytest.approx(round(scene.height * 2.0), abs=1)


def test_export_image_omits_the_overlay(qapp, canvas, tmp_path):
    """Selection rings are interaction state and must never reach a file."""
    frame = canvas.session.scene.metadata["frame"]
    clean = tmp_path / "clean.png"
    canvas.export_image(str(clean), scale=1.0)
    canvas.session.set_selection(set(frame.tips))
    canvas.refresh()
    selected = tmp_path / "selected.png"
    canvas.export_image(str(selected), scale=1.0)
    assert QImage(str(clean)) == QImage(str(selected))
    assert canvas.overlay.isVisible()


def test_export_image_reports_a_failed_write(qapp, canvas, tmp_path):
    """A silent failure here loses the user's figure with no way to tell."""
    with pytest.raises(OSError):
        canvas.export_image(str(tmp_path / "no-such-directory" / "tree.png"))


# ------------------------------------------------- feedback on a slow layout


def test_a_small_tree_recomposes_without_announcing_itself(qapp):
    """The announcement is for pauses long enough to look like a hang."""
    session = make_session()
    canvas = TreeCanvas(session)
    said: list[str] = []
    session.statusMessage.connect(lambda text, _ms: said.append(text))
    session.invalidate(Dirty.LAYOUT)
    canvas.refresh()
    assert not [text for text in said if "Laying out" in text]
    canvas.deleteLater()


def test_a_large_tree_says_what_it_is_doing_before_it_blocks(qapp):
    from PySide6.QtWidgets import QApplication

    from makeyourtree_studio.canvas.view import SLOW_LAYOUT_TIPS

    session = make_session(balanced_tree(SLOW_LAYOUT_TIPS + 8))
    canvas = TreeCanvas(session)
    said: list[str] = []
    session.statusMessage.connect(lambda text, _ms: said.append(text))

    session.invalidate(Dirty.LAYOUT)
    canvas.refresh()

    assert any("Laying out" in text for text in said), said
    assert said[-1] == "", "the message must be cleared once the work is done"
    # An override cursor left behind would make the whole application look busy.
    assert QApplication.overrideCursor() is None
    canvas.deleteLater()


def test_the_cursor_is_restored_even_if_recomposition_raises(qapp, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from makeyourtree_studio.canvas.view import SLOW_LAYOUT_TIPS

    session = make_session(balanced_tree(SLOW_LAYOUT_TIPS + 8))
    canvas = TreeCanvas(session)

    def boom(*_a, **_kw):
        raise RuntimeError("layout exploded")

    monkeypatch.setattr(session, "recompose", boom)
    session.invalidate(Dirty.LAYOUT)
    with pytest.raises(RuntimeError):
        canvas.refresh()
    assert QApplication.overrideCursor() is None
    canvas.deleteLater()
