# SPDX-License-Identifier: MIT
"""Finding nodes, and getting the view to them.

Search deliberately looks *through* collapsed clades. ``Tree.search`` walks the
whole tree, not the visible tips, so a taxon inside a clade the user collapsed an
hour ago is still found. The alternative -- searching only what is drawn -- means
a name that is demonstrably in the file reports "no matches", which reads as a
bug in the search rather than as a consequence of a collapse.

Finding it is only half the job: the hit cannot be shown while its ancestors are
collapsed. So the panel reports how many hits are hidden and offers one command
that expands exactly the collapsed ancestors involved, and no others -- expanding
everything would throw away the shape the user built.

Centring is a request, not a call. The panel emits :attr:`centerOnNode` and the
window connects it to the canvas. A panel that reached for the canvas directly
would be the first crack in the rule that all state flows through the session.
"""

from __future__ import annotations

import re
from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout,
                               QWidget)

from makeyourtree.core.node import Node
from makeyourtree.core.traversal import preorder
from makeyourtree.ops.command import CompositeCommand
from makeyourtree.ops.edit import expand

from ..session import Session

__all__ = ["SearchPanel"]

MODE_SUBSTRING = "substring"
MODE_REGEX = "regex"
MODE_WHOLE_WORD = "whole"

_MAX_RESULT_ROWS = 500
"""Rows put in the list widget. Every hit is still selected and highlighted; only
the scrollable listing is capped, because a QListWidget with 80 000 items costs
seconds to populate and nobody scrolls one."""


class SearchPanel(QWidget):
    """Query box, result list, navigation, and bulk selection."""

    centerOnNode = Signal(int)
    """Ask the view to centre on a node id. Wired to the canvas by the window."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._hits: list[int] = []
        self._cursor = -1
        self._loading = False

        self.query_edit = QLineEdit(self)
        self.query_edit.setPlaceholderText("Find nodes...")
        self.query_edit.setClearButtonEnabled(True)

        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("Substring", MODE_SUBSTRING)
        self.mode_combo.addItem("Regular expression", MODE_REGEX)
        self.mode_combo.addItem("Whole word", MODE_WHOLE_WORD)

        self.case_check = QCheckBox("Case sensitive", self)
        self.leaves_check = QCheckBox("Leaves only", self)
        self.field_combo = QComboBox(self)

        self.results = QListWidget(self)
        self.results.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results.setUniformItemSizes(True)

        self.status_label = QLabel("", self)
        self.prev_button = QPushButton("Previous", self)
        self.next_button = QPushButton("Next", self)
        self.select_all_button = QPushButton("Select all matches", self)
        self.expand_button = QPushButton("Expand to hits", self)
        self.expand_button.setToolTip(
            "Expand only the collapsed clades that contain a match")

        self.query_edit.textChanged.connect(lambda _t: self.run_search())
        self.query_edit.returnPressed.connect(self.go_next)
        self.mode_combo.currentIndexChanged.connect(lambda _i: self.run_search())
        self.case_check.toggled.connect(lambda _b: self.run_search())
        self.leaves_check.toggled.connect(lambda _b: self.run_search())
        self.field_combo.currentIndexChanged.connect(lambda _i: self.run_search())
        self.results.itemSelectionChanged.connect(self._on_result_clicked)
        self.prev_button.clicked.connect(self.go_previous)
        self.next_button.clicked.connect(self.go_next)
        self.select_all_button.clicked.connect(self.select_all_matches)
        self.expand_button.clicked.connect(self.expand_to_hits)

        options = QHBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        options.addWidget(self.mode_combo, 1)
        options.addWidget(self.field_combo, 1)

        toggles = QHBoxLayout()
        toggles.setContentsMargins(0, 0, 0, 0)
        toggles.addWidget(self.case_check)
        toggles.addWidget(self.leaves_check)
        toggles.addStretch(1)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.addWidget(self.prev_button)
        nav.addWidget(self.next_button)
        nav.addWidget(self.select_all_button)
        nav.addWidget(self.expand_button)
        nav.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.query_edit)
        layout.addLayout(options)
        layout.addLayout(toggles)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(nav)

        session.documentReplaced.connect(self._on_document_replaced)
        self.reload_fields()
        self._update_buttons()

    # ---------------------------------------------------------------- state

    @property
    def session(self) -> Session:
        return self._session

    @property
    def hits(self) -> list[int]:
        return list(self._hits)

    # --------------------------------------------------------------- fields

    def reload_fields(self) -> None:
        """Offer ``name``, ``comment`` and whatever attribute keys exist.

        The key list is gathered from a bounded prefix of the tree rather than
        from every node: NHX and NEXUS files use the same keys throughout, and
        scanning 200 000 nodes to populate a combo box on every document load is
        a cost with no matching benefit.
        """
        self._loading = True
        try:
            previous = self.field_combo.currentData()
            self.field_combo.clear()
            self.field_combo.addItem("Name", "name")
            self.field_combo.addItem("Comment", "comment")
            keys: list[str] = []
            seen: set[str] = set()
            for i, node in enumerate(preorder(self._session.tree.root)):
                if i >= 2000:
                    break
                for k in node.attrs:
                    if k not in seen:
                        seen.add(k)
                        keys.append(str(k))
            for k in sorted(keys):
                self.field_combo.addItem(k, k)
            idx = self.field_combo.findData(previous)
            self.field_combo.setCurrentIndex(max(0, idx))
        finally:
            self._loading = False

    # --------------------------------------------------------------- search

    def run_search(self) -> list[int]:
        """Re-run the query and publish the hits to the session."""
        if self._loading:
            return self._hits
        query = self.query_edit.text()
        mode = str(self.mode_combo.currentData() or MODE_SUBSTRING)
        field = str(self.field_combo.currentData() or "name")
        if not query:
            self._set_hits([])
            self.status_label.setText("")
            return self._hits
        try:
            nodes = self._session.tree.search(
                query,
                regex=mode == MODE_REGEX,
                whole_word=mode == MODE_WHOLE_WORD,
                case_sensitive=self.case_check.isChecked(),
                fields=(field,),
                leaves_only=self.leaves_check.isChecked(),
            )
        except re.error as exc:
            # A half-typed regular expression is the normal state of the box
            # while someone is typing one; it is a prompt, not an error.
            self.status_label.setText("Incomplete expression: %s" % exc.msg)
            self._set_hits([])
            return self._hits
        self._set_hits([n.id for n in nodes])
        hidden = len(self.collapsed_ancestors())
        text = "%d match%s" % (len(self._hits),
                               "" if len(self._hits) == 1 else "es")
        if hidden:
            text += " - %d inside collapsed clades" % hidden
        self.status_label.setText(text)
        return self._hits

    def _set_hits(self, ids: Iterable[int]) -> None:
        self._hits = list(ids)
        self._cursor = -1
        self._session.set_search_hits(self._hits)
        self._fill_results()
        self._update_buttons()

    def _fill_results(self) -> None:
        self._loading = True
        try:
            self.results.clear()
            tree = self._session.tree
            for nid in self._hits[:_MAX_RESULT_ROWS]:
                node = tree.by_id(nid)
                if node is None:
                    continue
                item = QListWidgetItem(self._describe(node))
                item.setData(Qt.ItemDataRole.UserRole, nid)
                self.results.addItem(item)
            if len(self._hits) > _MAX_RESULT_ROWS:
                more = QListWidgetItem(
                    "... %d more not listed" % (len(self._hits) - _MAX_RESULT_ROWS))
                more.setFlags(Qt.ItemFlag.NoItemFlags)
                self.results.addItem(more)
        finally:
            self._loading = False

    @staticmethod
    def _describe(node: Node) -> str:
        label = node.name or "(#%d)" % node.id
        if node.is_leaf:
            return label
        return "%s [clade]" % label

    # ----------------------------------------------------------- navigation

    def go_next(self) -> None:
        self._step(1)

    def go_previous(self) -> None:
        self._step(-1)

    def _step(self, delta: int) -> None:
        """Move the cursor through the hits, wrapping at both ends.

        Wrapping matters more than it looks: with three hits in a 40 000-tip
        tree, a cursor that stops at the end makes the user retype the query to
        get back to the first one.
        """
        if not self._hits:
            return
        self._cursor = (self._cursor + delta) % len(self._hits)
        nid = self._hits[self._cursor]
        self._session.set_selection([nid])
        self.centerOnNode.emit(nid)
        self._highlight_current()
        self.status_label.setText(
            "Match %d of %d" % (self._cursor + 1, len(self._hits)))

    def _highlight_current(self) -> None:
        if not (0 <= self._cursor < self.results.count()):
            return
        self._loading = True
        try:
            self.results.setCurrentRow(self._cursor)
        finally:
            self._loading = False

    def _on_result_clicked(self) -> None:
        if self._loading:
            return
        ids = [int(i.data(Qt.ItemDataRole.UserRole))
               for i in self.results.selectedItems()
               if i.data(Qt.ItemDataRole.UserRole) is not None]
        if not ids:
            return
        self._session.set_selection(ids)
        self._cursor = self.results.currentRow()
        self.centerOnNode.emit(ids[0])

    def select_all_matches(self) -> None:
        self._session.set_selection(self._hits)

    # ---------------------------------------------------- collapsed clades

    def collapsed_ancestors(self) -> list[Node]:
        """Collapsed nodes that hide at least one hit, nearest the root first.

        Order matters for the caller only in that expanding an outer clade does
        not expand an inner one, so both must be in the command.
        """
        tree = self._session.tree
        found: dict[int, Node] = {}
        for nid in self._hits:
            node = tree.by_id(nid)
            if node is None:
                continue
            for anc in node.iter_ancestors():
                if anc.collapsed:
                    found[anc.id] = anc
        return [found[k] for k in sorted(found)]

    def expand_to_hits(self) -> None:
        """Expand exactly the collapsed clades that hide a hit, in one entry."""
        ancestors = self.collapsed_ancestors()
        if not ancestors:
            return
        tree = self._session.tree
        cmds = [expand(tree, n) for n in ancestors]
        if len(cmds) == 1:
            self._session.do(cmds[0])
        else:
            self._session.do(CompositeCommand(
                label="expand %d clades" % len(cmds), commands=cmds,
                touches_topology=True, touches_order=False))
        self.run_search()

    # -------------------------------------------------------------- refresh

    def _update_buttons(self) -> None:
        has = bool(self._hits)
        self.next_button.setEnabled(has)
        self.prev_button.setEnabled(has)
        self.select_all_button.setEnabled(has)
        self.expand_button.setEnabled(bool(self.collapsed_ancestors()))

    def _on_document_replaced(self) -> None:
        self.reload_fields()
        self._set_hits([])
        self.status_label.setText("")
