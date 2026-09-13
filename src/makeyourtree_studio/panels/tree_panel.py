# SPDX-License-Identifier: MIT
"""The tree dock: a row per node, and the structural edits.

Every button here builds a command from :mod:`makeyourtree.ops` and hands it to
:meth:`Session.do`. None of them mutates the tree, and none of them calls
``Command.apply``: an edit that skipped the session would be invisible to undo
and to every other view, and the bug would only show up later as a history that
silently loses an operation.

Structural edits raise ``OperationError`` for things a user can plausibly ask for
and the tree cannot do -- rerooting on the root, pruning every taxon. Those are
reported on the status bar through ``session.statusMessage`` rather than raised,
because a modal error box for "you selected the root" is not information, it is
an interruption.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                               QPushButton, QTreeView, QVBoxLayout, QWidget)

from makeyourtree.core.errors import OperationError
from makeyourtree.core.node import Node
from makeyourtree.ops.command import Command, CompositeCommand
from makeyourtree.ops.edit import collapse, prune
from makeyourtree.ops.order import ladderize, rotate
from makeyourtree.ops.rooting import reroot_on_edge

from ..models.tree_model import TreeModel
from ..session import Session

__all__ = ["TreePanel"]

_STATUS_MS = 4000


class TreePanel(QWidget):
    """Hierarchical view of the tree with the structural edit buttons."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session

        self.model = TreeModel(session, self)
        self.view = QTreeView(self)
        self.view.setModel(self.model)
        self.view.setSelectionModel(self.model.selection_model)
        self.view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setUniformRowHeights(True)
        self.view.setAlternatingRowColors(True)
        self.view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.view.setExpandsOnDoubleClick(False)
        header = self.view.header()
        header.setSectionResizeMode(TreeModel.COL_NAME,
                                    QHeaderView.ResizeMode.Stretch)
        for col in (TreeModel.COL_LENGTH, TreeModel.COL_SUPPORT,
                    TreeModel.COL_LEAVES):
            header.setSectionResizeMode(col,
                                        QHeaderView.ResizeMode.ResizeToContents)

        self.collapse_button = QPushButton("Collapse", self)
        self.collapse_button.setToolTip(
            "Draw the selected clades as a single summary shape, or expand them "
            "again")
        self.ladderize_button = QPushButton("Ladderize", self)
        self.ladderize_button.setToolTip("Comb every clade to one side")
        self.rotate_button = QPushButton("Rotate", self)
        self.rotate_button.setToolTip(
            "Reverse the child order of the selected nodes")
        self.reroot_button = QPushButton("Reroot", self)
        self.reroot_button.setToolTip(
            "Place the root on the edge above the selected node")
        self.prune_button = QPushButton("Prune", self)
        self.prune_button.setToolTip("Remove the selected taxa or clades")

        self.collapse_button.clicked.connect(self.toggle_collapse)
        # Bound through a lambda because ``clicked`` supplies a ``checked``
        # boolean that would otherwise land in ``ascending`` and silently
        # ladderize the wrong way.
        self.ladderize_button.clicked.connect(lambda: self.ladderize(True))
        self.rotate_button.clicked.connect(self.rotate_selection)
        self.reroot_button.clicked.connect(self.reroot_selection)
        self.prune_button.clicked.connect(self.prune_selection)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        for b in (self.collapse_button, self.ladderize_button,
                  self.rotate_button, self.reroot_button, self.prune_button):
            buttons.addWidget(b)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.view, 1)
        layout.addLayout(buttons)

        session.selectionChanged.connect(self._on_selection_changed)
        session.documentReplaced.connect(self._on_document_replaced)
        # An edit can change what the buttons should offer without changing the
        # selection: collapsing a clade turns the same button into "Expand", and
        # undoing it turns it back.
        session.historyChanged.connect(self._update_buttons)
        self._update_buttons()

    # ---------------------------------------------------------------- state

    @property
    def session(self) -> Session:
        return self._session

    def selected_nodes(self) -> list[Node]:
        return self._session.selected_nodes()

    # -------------------------------------------------------------- editing

    def toggle_collapse(self) -> None:
        """Collapse the selected clades, or expand them if all are collapsed.

        One command for the whole selection, so a user who collapsed twelve
        clades in one gesture undoes it in one keystroke.
        """
        nodes = [n for n in self.selected_nodes() if n.children]
        if not nodes:
            self._say("Select an internal node to collapse")
            return
        want = not all(n.collapsed for n in nodes)
        cmds = [collapse(self._session.tree, n, want) for n in nodes]
        self._do_many(cmds, "collapse" if want else "expand")

    def ladderize(self, ascending: bool = True) -> None:
        self._guard(lambda: self._session.do(
            ladderize(self._session.tree, ascending)))

    def rotate_selection(self) -> None:
        nodes = [n for n in self.selected_nodes() if len(n.children) > 1]
        if not nodes:
            self._say("Select a node with at least two children to rotate")
            return
        self._do_many([rotate(self._session.tree, n) for n in nodes], "rotate")

    def reroot_selection(self) -> None:
        nodes = self.selected_nodes()
        if len(nodes) != 1:
            self._say("Select exactly one node to reroot on")
            return
        self._guard(lambda: self._session.do(
            reroot_on_edge(self._session.tree, nodes[0])))

    def prune_selection(self) -> None:
        nodes = self.selected_nodes()
        if not nodes:
            self._say("Select the taxa to remove")
            return

        def run() -> None:
            cmd = prune(self._session.tree, nodes)
            self._session.do(cmd)
            self._session.clear_selection()

        self._guard(run)

    # ------------------------------------------------------------- plumbing

    def _do_many(self, commands: list[Command], label: str) -> None:
        if not commands:
            return
        if len(commands) == 1:
            self._guard(lambda: self._session.do(commands[0]))
            return
        composite = CompositeCommand(
            label="%s %d nodes" % (label, len(commands)),
            commands=commands,
            touches_topology=any(c.touches_topology for c in commands),
            touches_order=any(c.touches_order for c in commands),
        )
        self._guard(lambda: self._session.do(composite))

    def _guard(self, fn) -> None:
        """Run an edit, turning a refused operation into a status message."""
        try:
            fn()
        except OperationError as exc:
            self._say(str(exc))

    def _say(self, message: str) -> None:
        self._session.statusMessage.emit(message, _STATUS_MS)

    # -------------------------------------------------------------- refresh

    def _on_document_replaced(self) -> None:
        self.view.collapseAll()
        root = self.model.index(0, 0, QModelIndex())
        if root.isValid():
            self.view.expand(root)
        self._update_buttons()

    def _on_selection_changed(self) -> None:
        self.reveal_selection()
        self._update_buttons()

    def reveal_selection(self) -> None:
        """Expand down to the first selected node and scroll it into view.

        Only the ancestors of that one node are expanded, so revealing a hit in a
        200 000-node tree stays O(depth) rather than expanding the whole subtree.
        """
        ids = self._session.selection
        if not ids:
            return
        idx = self.model.index_for_node(min(ids))
        if not idx.isValid():
            return
        parent = idx.parent()
        while parent.isValid():
            self.view.expand(parent)
            parent = parent.parent()
        self.view.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)

    def _update_buttons(self) -> None:
        nodes = self.selected_nodes()
        internal = [n for n in nodes if n.children]
        self.collapse_button.setEnabled(bool(internal))
        self.collapse_button.setText(
            "Expand" if internal and all(n.collapsed for n in internal)
            else "Collapse")
        self.rotate_button.setEnabled(
            any(len(n.children) > 1 for n in nodes))
        self.reroot_button.setEnabled(
            len(nodes) == 1 and nodes[0].parent is not None)
        self.prune_button.setEnabled(
            bool(nodes) and all(n.parent is not None for n in nodes))
