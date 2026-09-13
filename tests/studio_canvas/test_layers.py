# SPDX-License-Identifier: MIT
"""Layer items: O(layers) not O(nodes), O(1) bounds, and real culling.

These are the tests that keep the canvas usable on a large tree.  The item-count
test is the load-bearing one: the moment somebody adds a ``QGraphicsItem`` per
node, a 100 000-leaf document stops opening at all, and no amount of profiling
afterwards recovers the design.
"""

from __future__ import annotations

import pytest

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsScene,
                               QStyleOptionGraphicsItem)

from makeyourtree.scene.marks import Layer, LinesMark, Paint, RectMark
from makeyourtree.style.color import Color

from makeyourtree_studio.canvas.layers import (OVERLAY_Z, OverlayLayerItem,
                                           SceneLayerItem, layer_z)
from makeyourtree_studio.canvas.view import TreeCanvas

from canvas_helpers import balanced_tree, make_session


class Exploding:
    """Stands in for the mark list; any access at all fails the test."""

    def __iter__(self):
        raise AssertionError("boundingRect must not walk the marks")

    def __len__(self):
        raise AssertionError("boundingRect must not walk the marks")


def option_for(rect: QRectF) -> QStyleOptionGraphicsItem:
    option = QStyleOptionGraphicsItem()
    option.exposedRect = rect
    return option


# ---------------------------------------------------------------- item count


def test_a_five_thousand_leaf_tree_makes_a_handful_of_items(qapp):
    """Item count must scale with layers, not nodes.

    QGraphicsScene degrades badly past ~50 000 items; 5000 leaves is ~10 000
    nodes and ~20 000 segments, all of which must land inside a few items.
    """
    tree = balanced_tree(5000)
    assert tree.n_nodes > 9000
    session = make_session(tree)
    canvas = TreeCanvas(session)
    items = canvas.scene().items()
    assert len(items) <= len(Layer.order()) + 1
    assert len(items) < 20
    # And they really do hold the whole tree.
    assert canvas.session.scene.metadata["frame"].n_segments > 14000


def test_layer_items_are_one_per_populated_layer(qapp, canvas):
    scene = canvas.session.scene
    populated = [lay for lay in Layer.order()
                 if lay is not Layer.OVERLAY and scene.layers.get(lay)]
    assert populated
    assert sorted(canvas.layer_items(), key=lambda lay: lay.value) == sorted(
        populated, key=lambda lay: lay.value)


def test_layers_are_stacked_in_painting_order(qapp, canvas):
    items = canvas.layer_items()
    for layer, item in items.items():
        assert item.zValue() == layer_z(layer)
    assert canvas.overlay.zValue() == OVERLAY_Z
    assert all(item.zValue() < OVERLAY_Z for item in items.values())


# ------------------------------------------------------------- bounding rect


def test_bounding_rect_never_computes(qapp):
    """It is called on every paint and every intersection test.

    Replacing the marks with an object that raises on access proves the rect is
    served from the cache rather than derived from the contents.
    """
    rect = QRectF(0.0, 0.0, 100.0, 40.0)
    item = SceneLayerItem(Layer.BRANCHES, (), rect)
    item._marks = Exploding()
    for _ in range(1000):
        assert item.boundingRect() == rect


def test_bounds_change_goes_through_prepare_geometry_change(qapp):
    """Qt caches the bounding rect; a silent change leaves paint droppings."""
    calls = []
    scene = QGraphicsScene()
    item = SceneLayerItem(Layer.BRANCHES, (), QRectF(0, 0, 10, 10))
    scene.addItem(item)
    original = item.prepareGeometryChange
    item.prepareGeometryChange = lambda: (calls.append(1), original())[1]
    item.set_bounds(QRectF(0, 0, 200, 100))
    assert calls == [1]
    assert item.boundingRect() == QRectF(0, 0, 200, 100)
    # An unchanged rect must not invalidate anything.
    item.set_bounds(QRectF(0, 0, 200, 100))
    assert calls == [1]


def test_items_ask_for_the_exposed_rect(qapp, canvas):
    """``option.exposedRect`` is meaningless without this flag, and culling
    silently becomes a no-op."""
    flag = QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption
    assert canvas.overlay.flags() & flag
    for item in canvas.layer_items().values():
        assert item.flags() & flag


# ------------------------------------------------------------------ painting


def paint_item(item, rect: QRectF, size: int = 60) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    try:
        item.paint(painter, option_for(rect), None)
    finally:
        painter.end()
    return image


def test_paint_culls_to_the_exposed_rect(qapp):
    """A viewport showing a hundred of four hundred thousand segments must pay
    for a hundred."""
    marks = [LinesMark(paint=Paint.stroked(Color(0, 0, 0), width=4.0),
                       coords=[0.0, 10.0, 60.0, 10.0, 0.0, 50.0, 60.0, 50.0])]
    item = SceneLayerItem(Layer.BRANCHES, marks, QRectF(0, 0, 60, 60))
    image = paint_item(item, QRectF(0.0, 0.0, 60.0, 30.0))
    assert image.pixelColor(30, 10) == QColor(0, 0, 0)
    assert image.pixelColor(30, 50) == QColor(255, 255, 255)
    whole = paint_item(item, QRectF(0.0, 0.0, 60.0, 60.0))
    assert whole.pixelColor(30, 10) == QColor(0, 0, 0)
    assert whole.pixelColor(30, 50) == QColor(0, 0, 0)


def test_empty_layer_paints_nothing(qapp):
    item = SceneLayerItem(Layer.GRID, (), QRectF(0, 0, 60, 60))
    image = paint_item(item, QRectF(0.0, 0.0, 60.0, 60.0))
    assert image.pixelColor(30, 30) == QColor(255, 255, 255)


def test_set_marks_swaps_the_contents(qapp):
    item = SceneLayerItem(Layer.BRANCHES, (), QRectF(0, 0, 60, 60))
    assert item.mark_count() == 0
    item.set_marks([RectMark(paint=Paint.filled(Color(255, 0, 0)),
                             x=0.0, y=0.0, w=20.0, h=20.0)])
    assert item.mark_count() == 1
    assert item.layer is Layer.BRANCHES
    image = paint_item(item, QRectF(0.0, 0.0, 60.0, 60.0))
    assert image.pixelColor(10, 10) == QColor(255, 0, 0)


# ------------------------------------------------------------------- overlay


def paint_overlay(canvas) -> QImage:
    """Paint the overlay over the whole page, so a ring anywhere is visible."""
    scene = canvas.session.scene
    w = int(scene.width) + 2
    h = int(scene.height) + 2
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    try:
        canvas.overlay.paint(painter, option_for(QRectF(0, 0, w, h)), None)
    finally:
        painter.end()
    return image


def test_overlay_draws_selection_hover_and_search_without_recomposing(qapp,
                                                                     canvas):
    """This is the entire point of ``Dirty.OVERLAY``.

    The overlay reads the session live, so changing the selection is one
    repaint, never a recomposition.
    """
    session = canvas.session
    frame = session.scene.metadata["frame"]
    tip = frame.tips[0]
    scene_before = session.scene

    blank = paint_overlay(canvas)
    session.set_selection({tip})
    canvas.refresh()
    assert paint_overlay(canvas) != blank
    assert session.scene is scene_before

    session.clear_selection()
    session.set_hover(tip)
    canvas.refresh()
    assert paint_overlay(canvas) != blank
    assert session.scene is scene_before

    session.set_hover(None)
    session.set_search_hits([tip])
    canvas.refresh()
    assert paint_overlay(canvas) != blank
    assert session.scene is scene_before


def test_overlay_without_a_frame_paints_nothing(qapp, session):
    overlay = OverlayLayerItem(session, QRectF(0, 0, 60, 60))
    image = paint_item(overlay, QRectF(0, 0, 60, 60))
    assert image.pixelColor(30, 30) == QColor(255, 255, 255)


def test_overlay_applies_the_compositor_origin_shift(qapp, canvas):
    """Content is shifted onto the page with a group translation, not by
    rewriting coordinates, so the overlay has to shift by hand.

    The shift is driven directly here rather than through a document that
    happens to overhang, so the test fails if the offset is ever dropped
    regardless of what the compositor decides to do that day.
    """
    session = canvas.session
    frame = session.scene.metadata["frame"]
    tip = frame.tips[0]
    x, y = frame.xy(tip)
    session.set_selection({tip})
    overlay = OverlayLayerItem(session, QRectF(0, 0, 400, 400))
    overlay.set_frame(frame, (40.0, 25.0))

    width, height = int(x) + 120, int(y) + 120
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    try:
        overlay.paint(painter, option_for(QRectF(0, 0, width, height)), None)
    finally:
        painter.end()

    colour = session.document.theme.selection_color
    ring = (colour.r, colour.g, colour.b)
    assert ring in _nearest_colour(image, int(round(x + 40.0)), int(round(y + 25.0)))
    assert ring not in _nearest_colour(image, int(round(x)), int(round(y)))


def _nearest_colour(image: QImage, cx: int, cy: int,
                    reach: int = 8) -> set[tuple[int, int, int]]:
    """Opaque colours found near a point, as plain RGB triples."""
    out: set[tuple[int, int, int]] = set()
    for dx in range(-reach, reach + 1):
        for dy in range(-reach, reach + 1):
            x, y = cx + dx, cy + dy
            if 0 <= x < image.width() and 0 <= y < image.height():
                c = image.pixelColor(x, y)
                if c.alpha() == 255:
                    out.add((c.red(), c.green(), c.blue()))
    return out
