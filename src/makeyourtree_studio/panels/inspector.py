# SPDX-License-Identifier: MIT
"""Everything known about the current selection, in one place.

The inspector is where a user checks what the drawing is actually claiming, so
it shows the derived quantities too -- level, descendant leaves, root-to-tip
distance -- and it computes them live rather than reading ``Node.level`` and
``Node.depth_len``. Those are caches that ``Tree.refresh`` owns; between an edit
and the next recomposition they hold the *previous* geometry, and an inspector
that reports the previous geometry as fact is worse than one that reports
nothing.

Three fields are editable, and each commits exactly one command through
:meth:`Session.do`. The commit fires on ``editingFinished`` -- which Qt raises on
Return and on focus loss -- and it first compares against the stored value, so
tabbing through the form without typing produces no history entries at all. That
comparison is the whole reason a user can trust Ctrl+Z here: an undo stack full
of no-op edits is an undo stack nobody reads.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QGroupBox, QHeaderView, QLabel,
                               QLineEdit, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from makeyourtree.core.node import Node
from makeyourtree.ops.edit import rename

from ..models import SetFieldCommand
from ..models.tree_model import parse_number
from ..session import Session

__all__ = ["InspectorPanel"]


class InspectorPanel(QWidget):
    """Fields, attributes and track values for the selected node."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._loading = False

        body = QWidget(self)
        vbox = QVBoxLayout(body)
        vbox.setContentsMargins(6, 6, 6, 6)

        self.heading = QLabel("Nothing selected", body)
        self.heading.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        vbox.addWidget(self.heading)

        self.fields_group = QGroupBox("Node", body)
        form = QFormLayout(self.fields_group)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("unnamed")
        self.length_edit = QLineEdit()
        self.length_edit.setPlaceholderText("no length")
        self.support_edit = QLineEdit()
        self.support_edit.setPlaceholderText("no support")
        self.name_edit.editingFinished.connect(self._commit_name)
        self.length_edit.editingFinished.connect(
            lambda: self._commit_number("branch_length", self.length_edit))
        self.support_edit.editingFinished.connect(
            lambda: self._commit_number("support", self.support_edit))
        form.addRow("Name", self.name_edit)
        form.addRow("Branch length", self.length_edit)
        form.addRow("Support", self.support_edit)
        vbox.addWidget(self.fields_group)

        self.derived_group = QGroupBox("Derived", body)
        derived = QFormLayout(self.derived_group)
        self.level_label = QLabel("-")
        self.leaves_label = QLabel("-")
        self.distance_label = QLabel("-")
        self.children_label = QLabel("-")
        derived.addRow("Level", self.level_label)
        derived.addRow("Descendant leaves", self.leaves_label)
        derived.addRow("Root-to-tip distance", self.distance_label)
        derived.addRow("Children", self.children_label)
        vbox.addWidget(self.derived_group)

        self.attrs_table = _two_column_table("Key", "Value", body)
        attrs_box = QGroupBox("Attributes", body)
        attrs_layout = QVBoxLayout(attrs_box)
        attrs_layout.addWidget(self.attrs_table)
        vbox.addWidget(attrs_box)

        self.tracks_table = _two_column_table("Track", "Value", body)
        tracks_box = QGroupBox("Track values", body)
        tracks_layout = QVBoxLayout(tracks_box)
        tracks_layout.addWidget(self.tracks_table)
        vbox.addWidget(tracks_box)
        vbox.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        session.selectionChanged.connect(self.reload)
        session.documentReplaced.connect(self.reload)
        session.tracksChanged.connect(self.reload)
        session.historyChanged.connect(self.reload)
        self.reload()

    # ---------------------------------------------------------------- state

    @property
    def session(self) -> Session:
        return self._session

    def current_node(self) -> Node | None:
        """The single selected node, or ``None`` for zero or many.

        Editing is offered only for one node: a name field shared by twelve
        selected taxa would either overwrite all twelve or silently pick one, and
        neither is what anyone means by typing a name.
        """
        nodes = self._session.selected_nodes()
        return nodes[0] if len(nodes) == 1 else None

    # -------------------------------------------------------------- editing

    def _commit_name(self) -> None:
        node = self.current_node()
        if self._loading or node is None:
            return
        new = self.name_edit.text().strip() or None
        if new == node.name:
            return
        self._session.do(rename(self._session.tree, node, new))

    def _commit_number(self, field: str, editor: QLineEdit) -> None:
        node = self.current_node()
        if self._loading or node is None:
            return
        text = editor.text().strip()
        value = parse_number(text)
        if text and value is None:
            self._session.statusMessage.emit(
                "Not a number: %s" % text, 4000)
            editor.setText(_number_text(getattr(node, field)))
            return
        if value == getattr(node, field):
            return
        self._session.do(SetFieldCommand(node, field, value))

    # -------------------------------------------------------------- reading

    def reload(self) -> None:
        """Repopulate everything from the session."""
        self._loading = True
        try:
            nodes = self._session.selected_nodes()
            node = nodes[0] if len(nodes) == 1 else None
            editable = node is not None
            self.fields_group.setEnabled(editable)
            self.derived_group.setEnabled(editable)
            if node is None:
                self.heading.setText(
                    "Nothing selected" if not nodes
                    else "%d nodes selected" % len(nodes))
                self.name_edit.setText("")
                self.length_edit.setText("")
                self.support_edit.setText("")
                for label in (self.level_label, self.leaves_label,
                              self.distance_label, self.children_label):
                    label.setText("-")
                self.attrs_table.setRowCount(0)
                self.tracks_table.setRowCount(0)
                return
            kind = "Leaf" if node.is_leaf else "Clade"
            if node.parent is None:
                kind = "Root"
            self.heading.setText(
                ("%s #%d %s" % (kind, node.id, node.name or "")).strip())
            self.name_edit.setText(node.name or "")
            self.length_edit.setText(_number_text(node.branch_length))
            self.support_edit.setText(_number_text(node.support))
            self.level_label.setText(str(_level_of(node)))
            self.leaves_label.setText(str(_leaf_count(node)))
            self.distance_label.setText(format(_root_distance(node), ".6g"))
            self.children_label.setText(str(len(node.children)))
            self._fill_attrs(node)
            self._fill_tracks(node)
        finally:
            self._loading = False

    def _fill_attrs(self, node: Node) -> None:
        items = sorted(node.attrs.items(), key=lambda kv: str(kv[0]))
        if node.comment:
            items.append(("comment", node.comment))
        if node.collapsed:
            items.append(("collapsed", True))
        _fill_table(self.attrs_table,
                    [(str(k), _short(v)) for k, v in items])

    def _fill_tracks(self, node: Node) -> None:
        """One row per column of every attached track that holds this node.

        Tracks with no value for the node are skipped rather than shown as
        blank: on a document with twenty tracks and a leaf in two of them, twenty
        empty rows would hide the two that matter.
        """
        rows: list[tuple[str, str]] = []
        for track in self._session.document.tracks:
            values = track.data.rows.get(node.id)
            if not values:
                continue
            title = track.title or track.display_name or track.type_id
            columns = track.data.columns
            for i, value in enumerate(values):
                name = columns[i] if i < len(columns) else "column %d" % (i + 1)
                label = title if len(values) == 1 else "%s / %s" % (title, name)
                rows.append((label, _short(value)))
        _fill_table(self.tracks_table, rows)


# ------------------------------------------------------------------ helpers


def _two_column_table(a: str, b: str, parent: QWidget) -> QTableWidget:
    table = QTableWidget(0, 2, parent)
    table.setHorizontalHeaderLabels([a, b])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    return table


def _fill_table(table: QTableWidget, rows: list[tuple[str, str]]) -> None:
    table.setRowCount(len(rows))
    for r, (key, value) in enumerate(rows):
        table.setItem(r, 0, QTableWidgetItem(key))
        table.setItem(r, 1, QTableWidgetItem(value))


def _number_text(value: float | None) -> str:
    return "" if value is None else format(float(value), ".6g")


def _short(value: Any, limit: int = 200) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _level_of(node: Node) -> int:
    """Edges from the root, counted live rather than read from the cache."""
    n = 0
    cur = node.parent
    while cur is not None:
        n += 1
        cur = cur.parent
    return n


def _root_distance(node: Node) -> float:
    """Summed branch lengths from the root to *node*.

    Absent lengths count as zero, matching what the layout draws for a
    cladogram: reporting ``None`` for a tree with a few missing lengths would be
    less useful than reporting the distance the picture actually shows.
    """
    total = 0.0
    cur = node
    while cur.parent is not None:
        total += cur.edge_length(0.0)
        cur = cur.parent
    return total


def _leaf_count(node: Node) -> int:
    if not node.children:
        return 1
    total = 0
    stack = [node]
    while stack:
        n = stack.pop()
        if n.children:
            stack.extend(n.children)
        else:
            total += 1
    return total
