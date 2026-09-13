# SPDX-License-Identifier: MIT
"""Hit-testing, selection gestures, tooltips and the canvas context menu.

Qt's item picking is unavailable to us by construction: the canvas has ten
items, not two hundred thousand, so ``itemAt`` can only ever answer "the
branches layer".  Every query therefore goes to
:meth:`makeyourtree.layout.frame.LayoutFrame.hit`, the same nearest-node query the
core uses, which means the click target and the drawn branch can never disagree
-- they are derived from one array of coordinates.

Two coordinate details bite here.

*The origin shift.*  When content would overhang the page edge the compositor
translates each layer with a :class:`~makeyourtree.scene.marks.GroupMark` rather than
rewriting hundreds of thousands of floats, and records the offset in
``scene.metadata["origin"]``.  Qt scene coordinates therefore include that shift
and frame coordinates do not, so it is subtracted before every hit query.

*Tolerance is a screen quantity.*  A six-unit tolerance is generous zoomed out
and unusable zoomed in, so callers pass the tolerance in pixels and it is
divided by the view scale.
"""

from __future__ import annotations

import html
from typing import Iterable, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QWidget

from makeyourtree.core.node import Node
from makeyourtree.core.traversal import iter_leaves, preorder
from makeyourtree.layout.frame import LayoutFrame

__all__ = ["active_frame", "scene_origin", "HitTester", "CanvasInteractor",
           "clade_ids", "tooltip_text", "DEFAULT_TOLERANCE_PX"]

DEFAULT_TOLERANCE_PX = 8.0
"""Click slop in pixels.  Wide enough for a trackpad, tight enough that two
adjacent tip rows at default spacing stay separable."""


def active_frame(session) -> LayoutFrame | None:
    """The frame the current scene was drawn from.

    Prefers ``scene.metadata["frame"]`` over ``session.frame``: the compositor
    lays out again internally, and it is that result the marks came from, so it
    is that result a click must be resolved against.
    """
    scene = session.scene
    if scene is not None:
        frame = scene.metadata.get("frame")
        if frame is not None:
            return frame
    return session.frame


def scene_origin(session) -> tuple[float, float]:
    """Translation the compositor applied to keep content on the page."""
    scene = session.scene
    if scene is None:
        return (0.0, 0.0)
    origin = scene.metadata.get("origin")
    if not origin:
        return (0.0, 0.0)
    return (float(origin[0]), float(origin[1]))


def clade_ids(tree, node_id: int) -> list[int]:
    """Node ids of *node_id* and everything visible below it."""
    node = tree.by_id(node_id)
    if node is None:
        return []
    return [n.id for n in preorder(node, visible_only=True)]


def tooltip_text(session, node_id: int, *, leaf_count: int | None = None) -> str:
    """The hover card: what the node is, how long its branch is, how big it is.

    Rich text rather than plain so the name reads as the title of the card; the
    name is escaped because tree files routinely contain ``<`` and ``&``.
    """
    node = session.tree.by_id(node_id)
    if node is None:
        return ""
    rows: list[str] = []
    name = node.name or ("root" if node.is_root else "unnamed node")
    rows.append("<b>" + html.escape(str(name)) + "</b>")
    if node.branch_length is not None:
        rows.append("branch length " + _fmt(node.branch_length))
    if node.support is not None:
        rows.append("support " + _fmt(node.support))
    if not node.is_leaf:
        n = leaf_count if leaf_count is not None else sum(1 for _ in iter_leaves(node))
        rows.append(f"{n} descendant tips")
    return "<br>".join(rows)


def _fmt(value: float) -> str:
    return f"{float(value):.6g}"


class HitTester:
    """Nearest-node queries in Qt scene coordinates."""

    __slots__ = ("_session",)

    def __init__(self, session) -> None:
        self._session = session

    @property
    def frame(self) -> LayoutFrame | None:
        return active_frame(self._session)

    def to_frame(self, x: float, y: float) -> tuple[float, float]:
        """Undo the compositor's origin shift."""
        dx, dy = scene_origin(self._session)
        return (x - dx, y - dy)

    def node_at(self, x: float, y: float,
                tolerance: float = DEFAULT_TOLERANCE_PX) -> int | None:
        """Node under a scene-space point, or ``None``.

        *tolerance* is in scene units here; the canvas converts from pixels.
        """
        frame = self.frame
        if frame is None:
            return None
        fx, fy = self.to_frame(x, y)
        return frame.hit(fx, fy, tolerance)

    def nodes_in(self, rect: QRectF) -> list[int]:
        """Every node whose position falls inside a scene-space rectangle."""
        frame = self.frame
        if frame is None:
            return []
        dx, dy = scene_origin(self._session)
        box = rect.normalized()
        x0, y0 = box.left() - dx, box.top() - dy
        x1, y1 = box.right() - dx, box.bottom() - dy
        out: list[int] = []
        for node in self._session.tree.nodes:
            nid = node.id
            if not frame.has(nid):
                continue
            x, y = frame.xy(nid)
            if x0 <= x <= x1 and y0 <= y <= y1:
                out.append(nid)
        return out


class CanvasInteractor:
    """Turns pointer gestures into session state changes.

    Kept out of :class:`~makeyourtree_studio.canvas.view.TreeCanvas` so the gesture
    semantics -- what shift-click means, what a double-click selects -- can be
    tested without a widget, and so the view stays about painting and camera.
    """

    def __init__(self, session, parent: QWidget | None = None) -> None:
        self.session = session
        self.parent = parent
        self.hits = HitTester(session)
        self._leaf_counts: dict[int, int] = {}

    # ------------------------------------------------------------- geometry

    def invalidate(self) -> None:
        """Drop derived caches after a topology change."""
        self._leaf_counts.clear()

    def node_at(self, scene_pos: QPointF, *, view_scale: float = 1.0,
                tolerance_px: float = DEFAULT_TOLERANCE_PX) -> int | None:
        scale = view_scale if view_scale > 1e-9 else 1.0
        return self.hits.node_at(scene_pos.x(), scene_pos.y(), tolerance_px / scale)

    # ------------------------------------------------------------ selection

    def click(self, node_id: int | None, modifiers: Qt.KeyboardModifier) -> None:
        """Plain click replaces the selection; shift adds; ctrl toggles."""
        if node_id is None:
            if not (modifiers & (Qt.KeyboardModifier.ShiftModifier
                                 | Qt.KeyboardModifier.ControlModifier)):
                self.session.clear_selection()
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self.session.toggle_selection(node_id)
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.session.set_selection(set(self.session.selection) | {node_id})
        else:
            self.session.set_selection({node_id})

    def double_click(self, node_id: int | None,
                     modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
                     ) -> None:
        """Select the whole clade below the node.

        The obvious follow-up to selecting a node is wanting everything under
        it; making that a double-click saves a trip to the context menu.
        """
        if node_id is None:
            return
        ids = set(clade_ids(self.session.tree, node_id))
        if not ids:
            return
        if modifiers & (Qt.KeyboardModifier.ShiftModifier
                        | Qt.KeyboardModifier.ControlModifier):
            ids |= set(self.session.selection)
        self.session.set_selection(ids)

    def rubber_band(self, rect: QRectF, modifiers: Qt.KeyboardModifier) -> None:
        """Rectangle selection: shift adds to the selection, ctrl toggles."""
        found = set(self.hits.nodes_in(rect))
        current = set(self.session.selection)
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self.session.set_selection(current ^ found)
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.session.set_selection(current | found)
        else:
            self.session.set_selection(found)

    # ---------------------------------------------------------------- hover

    def hover(self, node_id: int | None) -> str:
        """Record the hovered node and return its tooltip, empty if none."""
        self.session.set_hover(node_id)
        if node_id is None:
            return ""
        return tooltip_text(self.session, node_id,
                            leaf_count=self._leaf_count(node_id))

    def _leaf_count(self, node_id: int) -> int | None:
        node = self.session.tree.by_id(node_id)
        if node is None or node.is_leaf:
            return None
        hit = self._leaf_counts.get(node_id)
        if hit is None:
            hit = sum(1 for _ in iter_leaves(node))
            self._leaf_counts[node_id] = hit
        return hit

    # ----------------------------------------------------------- context menu

    def build_context_menu(self, registry, parent: QWidget | None = None
                           ) -> QMenu | None:
        """A menu of exactly the actions the registry marked ``context_menu``.

        Built from the registry rather than assembled by hand so the canvas menu
        can never drift out of step with the menu bar or the palette.
        """
        if registry is None:
            return None
        actions: Sequence[QAction] = registry.context_actions()
        if not actions:
            return None
        menu = QMenu(parent if parent is not None else self.parent)
        for act in actions:
            menu.addAction(act)
        return menu

    def prepare_context(self, node_id: int | None,
                        modifiers: Qt.KeyboardModifier
                        = Qt.KeyboardModifier.NoModifier) -> None:
        """Make the node under the cursor the selection, unless it already is.

        Right-clicking an unselected node and getting an action applied to a
        different, previously selected node is a classic way to lose work.
        """
        if node_id is None:
            return
        if node_id not in self.session.selection:
            self.click(node_id, modifiers)


def visible_nodes(tree) -> Iterable[Node]:
    """Preorder over the visible tree.  Convenience for panels sharing this module."""
    return preorder(tree.root, visible_only=True)
