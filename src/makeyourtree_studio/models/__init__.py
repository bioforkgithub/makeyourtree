# SPDX-License-Identifier: MIT
"""Qt item models over the document, and the undoable edits the panels issue.

The two edit commands live here rather than in a panel module because three
different views need them -- the inspector edits a field, the tree model edits a
name in place, the style panel restyles a whole selection -- and a command class
owned by one panel and imported by another would make the panels depend on each
other, which is exactly what the session contract forbids.  This package sits
below every panel, so importing from it creates no cycle.

Both commands re-read the previous value inside :meth:`apply` rather than only in
``__init__``.  That is what makes redo correct: a command may be applied, undone,
and applied again, and the "old" value it must restore is the one that was in
place at the last apply, not at construction time.
"""

from __future__ import annotations

from typing import Any, Iterable

from makeyourtree.core.node import Node
from makeyourtree.core.tree import Tree
from makeyourtree.ops.command import Command

__all__ = ["SetFieldCommand", "SetNodeStyleCommand", "EDITABLE_FIELDS"]

EDITABLE_FIELDS: tuple[str, ...] = ("name", "branch_length", "support")
"""Node fields the inspector and the tree model may edit directly."""


class SetFieldCommand(Command):
    """Set one scalar field on one node, reversibly.

    ``branch_length`` is declared as touching topology even though no link moves:
    it changes the along coordinate of every descendant, and the session maps
    anything short of ``touches_topology`` to a style-only invalidation, which
    would leave the drawing showing the old geometry.  ``name`` and ``support``
    are genuinely style-level -- nothing in the layout depends on them.
    """

    touches_order = False

    def __init__(self, node: Node, field: str, value: Any,
                 label: str | None = None) -> None:
        if field not in EDITABLE_FIELDS:
            raise ValueError(f"not an editable node field: {field!r}")
        self._node = node
        self._field = field
        self._new = value
        self._old = getattr(node, field)
        self.touches_topology = field == "branch_length"
        self.label = label or f"set {field.replace('_', ' ')}"

    def apply(self, tree: Tree) -> None:
        self._old = getattr(self._node, self._field)
        setattr(self._node, self._field, self._new)
        tree.touch()

    def undo(self, tree: Tree) -> None:
        setattr(self._node, self._field, self._old)
        tree.touch()

    def merge_with(self, later: "Command") -> "Command | None":
        """Absorb a later edit of the same field on the same node.

        Spin boxes fire once per step while a user holds the arrow key or drags;
        without this, a single gesture would fill the history with noise.
        """
        if (isinstance(later, SetFieldCommand)
                and later._node is self._node and later._field == self._field):
            self._new = later._new
            return self
        return None


class SetNodeStyleCommand(Command):
    """Set one :class:`~makeyourtree.style.theme.NodeStyle` key across a selection.

    Style overrides are a sparse dict on each node, so "no override" and "an
    override whose value happens to equal the theme default" are different
    states.  Undo therefore records the previous value *per node*, including the
    absence of one, and restores it by writing ``None`` back through
    :meth:`Node.set_style`, which deletes the key.
    """

    touches_topology = False
    touches_order = False

    def __init__(self, nodes: Iterable[Node], key: str, value: Any,
                 label: str | None = None) -> None:
        self._nodes: list[Node] = list(nodes)
        self._key = key
        self._new = value
        self._old: list[Any] = [None] * len(self._nodes)
        pretty = key.replace("_", " ")
        self.label = label or (f"clear {pretty}" if value is None else f"set {pretty}")

    def apply(self, tree: Tree) -> None:
        self._old = [None if n.style is None else n.style.get(self._key)
                     for n in self._nodes]
        for n in self._nodes:
            n.set_style(**{self._key: self._new})

    def undo(self, tree: Tree) -> None:
        for n, old in zip(self._nodes, self._old):
            n.set_style(**{self._key: old})

    def merge_with(self, later: "Command") -> "Command | None":
        """Absorb a later change of the same key over the same nodes.

        This is what turns a fifty-step slider drag into one history entry: the
        merged command keeps the original ``_old`` values and adopts the newest
        value, so undoing it jumps straight back to where the drag started.
        """
        if (isinstance(later, SetNodeStyleCommand)
                and later._key == self._key
                and [id(n) for n in later._nodes] == [id(n) for n in self._nodes]):
            self._new = later._new
            self.label = later.label
            return self
        return None
