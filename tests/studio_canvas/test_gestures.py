# SPDX-License-Identifier: MIT
"""Pointer and keyboard gestures, driven through the widget's event handlers.

The interactor is tested directly elsewhere; this file checks the wiring -- that
a real ``QMouseEvent`` at a real viewport position reaches the right call with
the right modifiers, and that panning moves the camera rather than the document.
"""

from __future__ import annotations

import pytest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from makeyourtree_studio.canvas.view import TreeCanvas

from canvas_helpers import balanced_tree, make_session

NO_MODIFIER = Qt.KeyboardModifier.NoModifier


def mouse(kind, canvas, point: QPointF, button=Qt.MouseButton.LeftButton,
          modifiers=NO_MODIFIER, buttons=None) -> QMouseEvent:
    held = buttons if buttons is not None else button
    return QMouseEvent(kind, point, canvas.mapToGlobal(point.toPoint()).toPointF(),
                       button, held, modifiers)


def viewport_point(canvas: TreeCanvas, node_id: int) -> QPointF:
    session = canvas.session
    frame = session.scene.metadata["frame"]
    dx, dy = session.scene.metadata["origin"]
    x, y = frame.xy(node_id)
    return QPointF(canvas.mapFromScene(QPointF(x + dx, y + dy)))


@pytest.fixture
def big_canvas(qapp):
    canvas = TreeCanvas(make_session(balanced_tree(300)))
    canvas.resize(400, 300)
    canvas.reset_zoom()
    return canvas


def test_left_click_on_a_node_selects_it(qapp, canvas):
    canvas.resize(1200, 400)
    canvas.reset_zoom()
    node = canvas.session.scene.metadata["frame"].tips[0]
    canvas.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, canvas,
                                 viewport_point(canvas, node)))
    assert canvas.session.selection == {node}


def test_shift_click_adds_to_the_selection(qapp, canvas):
    canvas.resize(1200, 400)
    canvas.reset_zoom()
    frame = canvas.session.scene.metadata["frame"]
    a, b = frame.tips[0], frame.tips[1]
    canvas.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, canvas,
                                 viewport_point(canvas, a)))
    canvas.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, canvas,
                                 viewport_point(canvas, b),
                                 modifiers=Qt.KeyboardModifier.ShiftModifier))
    assert canvas.session.selection == {a, b}


def test_double_click_selects_the_clade(qapp, canvas):
    canvas.resize(1200, 400)
    canvas.reset_zoom()
    internal = canvas.session.tree.by_name("ab")
    canvas.mouseDoubleClickEvent(mouse(QMouseEvent.Type.MouseButtonDblClick,
                                       canvas, viewport_point(canvas, internal.id)))
    selected = canvas.session.selection
    assert internal.id in selected
    assert {n.id for n in internal.children} <= selected


def test_moving_the_mouse_sets_hover(qapp, canvas):
    canvas.resize(1200, 400)
    canvas.reset_zoom()
    node = canvas.session.scene.metadata["frame"].tips[0]
    canvas.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, canvas,
                                viewport_point(canvas, node),
                                button=Qt.MouseButton.NoButton,
                                buttons=Qt.MouseButton.NoButton))
    assert canvas.session.hover == node
    canvas.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, canvas,
                                QPointF(2.0, 2.0),
                                button=Qt.MouseButton.NoButton,
                                buttons=Qt.MouseButton.NoButton))
    assert canvas.session.hover is None


def test_middle_drag_pans_without_recomposing(qapp, big_canvas, monkeypatch):
    """Panning is a camera move: the scene must come out untouched."""
    canvas = big_canvas
    canvas.zoom_by(4.0)
    scene_before = canvas.session.scene
    start_h = canvas.horizontalScrollBar().value()
    start_v = canvas.verticalScrollBar().value()
    canvas.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, canvas,
                                 QPointF(200.0, 150.0),
                                 button=Qt.MouseButton.MiddleButton))
    canvas.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, canvas,
                                QPointF(140.0, 100.0),
                                button=Qt.MouseButton.NoButton,
                                buttons=Qt.MouseButton.MiddleButton))
    canvas.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, canvas,
                                   QPointF(140.0, 100.0),
                                   button=Qt.MouseButton.MiddleButton))
    assert canvas.horizontalScrollBar().value() == start_h + 60
    assert canvas.verticalScrollBar().value() == start_v + 50
    assert canvas.session.scene is scene_before


def test_space_drag_pans_with_the_left_button(qapp, big_canvas):
    canvas = big_canvas
    canvas.zoom_by(4.0)
    start_v = canvas.verticalScrollBar().value()
    canvas.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space,
                                   NO_MODIFIER))
    canvas.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, canvas,
                                 QPointF(200.0, 150.0)))
    canvas.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, canvas,
                                QPointF(200.0, 110.0),
                                button=Qt.MouseButton.NoButton,
                                buttons=Qt.MouseButton.LeftButton))
    canvas.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, canvas,
                                   QPointF(200.0, 110.0)))
    canvas.keyReleaseEvent(QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Space,
                                     NO_MODIFIER))
    assert canvas.verticalScrollBar().value() == start_v + 40
    assert canvas.session.selection == set()


def test_rubber_band_drag_selects_a_region(qapp, canvas):
    canvas.resize(1200, 400)
    canvas.reset_zoom()
    frame = canvas.session.scene.metadata["frame"]
    node = frame.tips[0]
    centre = viewport_point(canvas, node)
    start = QPointF(centre.x() - 6.0, centre.y() - 6.0)
    end = QPointF(centre.x() + 6.0, centre.y() + 6.0)
    canvas.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, canvas, start))
    canvas.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, canvas, end,
                                button=Qt.MouseButton.NoButton,
                                buttons=Qt.MouseButton.LeftButton))
    canvas.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease,
                                   canvas, end))
    assert node in canvas.session.selection


def test_a_click_on_empty_space_clears_the_selection(qapp, canvas):
    canvas.resize(1200, 400)
    canvas.reset_zoom()
    node = canvas.session.scene.metadata["frame"].tips[0]
    canvas.session.set_selection({node})
    empty = QPointF(3.0, 3.0)
    canvas.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, canvas, empty))
    canvas.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease,
                                   canvas, empty))
    assert canvas.session.selection == set()


def test_leaving_the_widget_clears_hover(qapp, canvas):
    from PySide6.QtCore import QEvent

    canvas.session.set_hover(canvas.session.scene.metadata["frame"].tips[0])
    canvas.leaveEvent(QEvent(QEvent.Type.Leave))
    assert canvas.session.hover is None
