# SPDX-License-Identifier: MIT
"""Hit-testing and selection gestures.

The canvas deliberately has almost no graphics items, so Qt item picking cannot
answer "which node is under the cursor" -- every query goes to
:meth:`makeyourtree.layout.frame.LayoutFrame.hit`.  The agreement test below samples
a grid across the page in every layout mode and asserts the canvas returns
exactly what the frame does, which is what guarantees the click target and the
drawn branch are the same thing.
"""

from __future__ import annotations

import pytest

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction

from makeyourtree.layout.params import LayoutMode

from makeyourtree_studio.actions import ActionRegistry, ActionSpec, Group
from makeyourtree_studio.canvas.interaction import (CanvasInteractor, HitTester,
                                                active_frame, clade_ids,
                                                scene_origin, tooltip_text)
from makeyourtree_studio.canvas.view import TreeCanvas

from canvas_helpers import ALL_MODES, make_session

NO_MODIFIER = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
CONTROL = Qt.KeyboardModifier.ControlModifier


def sample_points(scene, steps: int = 12):
    """A grid over the page, in Qt scene coordinates."""
    for i in range(steps):
        for j in range(steps):
            yield QPointF(scene.width * (i + 0.5) / steps,
                          scene.height * (j + 0.5) / steps)


# -------------------------------------------------------------- agreement


@pytest.mark.parametrize("mode", ALL_MODES, ids=lambda m: m.value)
def test_hit_testing_agrees_with_the_layout_frame(qapp, mode):
    session = make_session(mode=mode)
    canvas = TreeCanvas(session)
    canvas.resize(600, 500)
    canvas.reset_zoom()
    scene = session.scene
    frame = scene.metadata["frame"]
    dx, dy = scene_origin(session)
    tolerance = 8.0
    checked = 0
    for point in sample_points(scene):
        expected = frame.hit(point.x() - dx, point.y() - dy, tolerance)
        assert canvas.node_at(point, tolerance_px=tolerance) == expected
        checked += 1
    assert checked > 100


@pytest.mark.parametrize("mode", ALL_MODES, ids=lambda m: m.value)
def test_every_node_is_clickable_at_its_own_position(qapp, mode):
    """Clicking exactly where a node is drawn must select that node."""
    session = make_session(mode=mode)
    canvas = TreeCanvas(session)
    scene = session.scene
    frame = scene.metadata["frame"]
    dx, dy = scene_origin(session)
    for node in session.tree.nodes:
        if not frame.has(node.id):
            continue
        x, y = frame.xy(node.id)
        hit = canvas.node_at(QPointF(x + dx, y + dy), tolerance_px=2.0)
        assert hit is not None
        hx, hy = frame.xy(hit)
        assert abs(hx - x) < 1e-6 and abs(hy - y) < 1e-6


def test_tolerance_is_a_screen_quantity(qapp, canvas):
    """Eight pixels of slop is generous zoomed out and unusable zoomed in."""
    session = canvas.session
    frame = session.scene.metadata["frame"]
    dx, dy = scene_origin(session)
    node = frame.tips[0]
    x, y = frame.xy(node)
    probe = QPointF(x + dx + 6.0, y + dy)

    canvas.reset_zoom()
    assert canvas.node_at(probe, tolerance_px=8.0) == node
    canvas.zoom_by(8.0)
    # Same eight pixels, now one scene unit: the probe is out of reach.
    assert canvas.node_at(probe, tolerance_px=8.0) is None


def test_hit_testing_undoes_the_compositor_origin_shift(qapp, canvas):
    """Scene coordinates carry the shift; frame coordinates do not."""
    session = canvas.session
    frame = session.scene.metadata["frame"]
    node = frame.tips[0]
    x, y = frame.xy(node)
    session.scene.metadata["origin"] = (120.0, 45.0)
    hits = HitTester(session)
    assert hits.node_at(x + 120.0, y + 45.0, 2.0) == node
    assert hits.to_frame(x + 120.0, y + 45.0) == pytest.approx((x, y))


def test_active_frame_prefers_the_frame_the_marks_came_from(qapp, canvas):
    session = canvas.session
    assert active_frame(session) is session.scene.metadata["frame"]


def test_hit_testing_without_a_scene_is_none(qapp, session):
    hits = HitTester(session)
    assert hits.node_at(0.0, 0.0) is None
    assert hits.nodes_in(QRectF(0, 0, 100, 100)) == []
    assert scene_origin(session) == (0.0, 0.0)


# --------------------------------------------------------------- selection


def test_click_replaces_shift_adds_and_ctrl_toggles(qapp, canvas):
    session = canvas.session
    frame = session.scene.metadata["frame"]
    a, b = frame.tips[0], frame.tips[1]
    interactor = canvas.interactor

    interactor.click(a, NO_MODIFIER)
    assert session.selection == {a}
    interactor.click(b, NO_MODIFIER)
    assert session.selection == {b}
    interactor.click(a, SHIFT)
    assert session.selection == {a, b}
    interactor.click(a, CONTROL)
    assert session.selection == {b}
    interactor.click(None, NO_MODIFIER)
    assert session.selection == set()


def test_clicking_empty_space_with_a_modifier_keeps_the_selection(qapp, canvas):
    session = canvas.session
    node = session.scene.metadata["frame"].tips[0]
    canvas.interactor.click(node, NO_MODIFIER)
    canvas.interactor.click(None, SHIFT)
    assert session.selection == {node}


def test_double_click_selects_the_whole_clade(qapp, canvas):
    session = canvas.session
    internal = session.tree.by_name("cde")
    canvas.interactor.double_click(internal.id, NO_MODIFIER)
    expected = set(clade_ids(session.tree, internal.id))
    assert session.selection == expected
    assert len(expected) > 1
    assert {n.id for n in session.tree.leaves if n.name in ("c", "d", "e")} <= expected


def test_double_click_on_nothing_is_a_no_op(qapp, canvas):
    canvas.interactor.double_click(None, NO_MODIFIER)
    assert canvas.session.selection == set()


def test_rubber_band_selects_what_it_covers(qapp, canvas):
    session = canvas.session
    frame = session.scene.metadata["frame"]
    dx, dy = scene_origin(session)
    node = frame.tips[0]
    x, y = frame.xy(node)
    box = QRectF(x + dx - 3.0, y + dy - 3.0, 6.0, 6.0)

    canvas.interactor.rubber_band(box, NO_MODIFIER)
    assert session.selection == {node}
    other = frame.tips[1]
    session.set_selection({other})
    canvas.interactor.rubber_band(box, SHIFT)
    assert session.selection == {node, other}
    canvas.interactor.rubber_band(box, CONTROL)
    assert session.selection == {other}


def test_rubber_band_over_the_whole_page_takes_everything(qapp, canvas):
    session = canvas.session
    frame = session.scene.metadata["frame"]
    canvas.interactor.rubber_band(
        QRectF(-1e5, -1e5, 2e5, 2e5), NO_MODIFIER)
    visible = {n.id for n in session.tree.nodes if frame.has(n.id)}
    assert session.selection == visible


def test_context_click_takes_over_an_unselected_node(qapp, canvas):
    """Acting on a node other than the one right-clicked loses work."""
    session = canvas.session
    frame = session.scene.metadata["frame"]
    a, b = frame.tips[0], frame.tips[1]
    session.set_selection({a})
    canvas.interactor.prepare_context(b)
    assert session.selection == {b}
    # Right-clicking inside an existing selection leaves it alone.
    session.set_selection({a, b})
    canvas.interactor.prepare_context(b)
    assert session.selection == {a, b}


# ------------------------------------------------------------------- hover


def test_hover_sets_the_session_and_returns_a_tooltip_card(qapp, canvas):
    session = canvas.session
    node = session.tree.by_name("cd")
    node.support = 0.97
    text = canvas.interactor.hover(node.id)
    assert session.hover == node.id
    assert "cd" in text
    assert "0.2" in text          # branch length
    assert "0.97" in text         # support
    assert "2 descendant tips" in text
    assert canvas.interactor.hover(None) == ""
    assert session.hover is None


def test_tooltip_escapes_markup_from_the_file(qapp, canvas):
    """Tree files really do contain angle brackets and ampersands."""
    session = canvas.session
    node = session.tree.by_name("a")
    node.name = "<i>Vibrio</i> & co"
    text = tooltip_text(session, node.id)
    assert "&lt;i&gt;" in text
    assert "&amp;" in text


def test_tooltip_of_an_unknown_node_is_empty(qapp, canvas):
    assert tooltip_text(canvas.session, -1) == ""


def test_descendant_counts_are_cached_until_topology_changes(qapp, canvas):
    interactor = canvas.interactor
    node = canvas.session.tree.by_name("cde")
    first = interactor.hover(node.id)
    assert interactor._leaf_counts[node.id] == 3
    interactor.invalidate()
    assert interactor._leaf_counts == {}
    assert interactor.hover(node.id) == first


# ------------------------------------------------------------ context menu


def build_registry(parent) -> ActionRegistry:
    registry = ActionRegistry()
    registry.extend([
        ActionSpec(id="tree.reroot", text="Reroot Here", group=Group.TREE,
                   context_menu=True),
        ActionSpec(id="tree.collapse", text="Collapse Clade", group=Group.TREE,
                   context_menu=True),
        ActionSpec(id="file.open", text="Open", group=Group.FILE),
    ])
    registry.build(parent)
    return registry


def test_context_menu_is_built_from_the_registry(qapp, canvas):
    """One declaration, four views: the canvas menu cannot drift from the rest."""
    registry = build_registry(canvas)
    canvas.set_action_registry(registry)
    menu = canvas.interactor.build_context_menu(registry, canvas)
    assert menu is not None
    labels = [a.text() for a in menu.actions()]
    assert labels == ["Reroot Here", "Collapse Clade"]
    assert all(isinstance(a, QAction) for a in menu.actions())


def test_no_registry_means_no_menu(qapp, canvas):
    assert canvas.interactor.build_context_menu(None) is None
    empty = ActionRegistry()
    empty.build(canvas)
    assert canvas.interactor.build_context_menu(empty) is None


# ------------------------------------------------------------------ frames


def test_clade_ids_covers_the_visible_subtree(qapp, canvas):
    tree = canvas.session.tree
    root = tree.root
    assert set(clade_ids(tree, root.id)) == {n.id for n in tree.nodes}
    leaf = tree.by_name("a")
    assert clade_ids(tree, leaf.id) == [leaf.id]
    assert clade_ids(tree, -1) == []


def test_interactor_works_without_a_widget(qapp, session):
    """The gesture semantics are testable with no view attached."""
    session.recompose()
    interactor = CanvasInteractor(session)
    frame = session.scene.metadata["frame"]
    node = frame.tips[0]
    x, y = frame.xy(node)
    dx, dy = scene_origin(session)
    assert interactor.node_at(QPointF(x + dx, y + dy)) == node
    interactor.click(node, NO_MODIFIER)
    assert session.selection == {node}
