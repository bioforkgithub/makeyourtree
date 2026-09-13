# SPDX-License-Identifier: MIT
"""A lazy :class:`QAbstractItemModel` over the tree, plus selection sync.

Why lazy matters here
---------------------
A 100 000-leaf tree is ~200 000 nodes. Building a ``QModelIndex`` -- or worse, a
proxy object -- per node at construction would cost hundreds of megabytes and
seconds of startup for a view that can show forty rows. So this model creates an
index only when Qt asks for one, keyed on the node id, and holds no per-node
state beyond the ids it has actually handed out. ``internalId()`` carries the
node id directly, so an index costs nothing to keep and nothing to discard.

The set of ids handed out is tracked in :attr:`materialised` for one reason
besides testing: when a style-level change lands, the model must tell the view
which rows to repaint, and the only rows that can be on screen are ones it has
already created indexes for. That turns "repaint everything" into a bounded list.

Selection
---------
The model owns a :class:`QItemSelectionModel` so that the view-side selection and
``session.selection`` stay in step without either side driving the other in a
loop. A single re-entrancy flag guards both directions; without it, pushing a
selection into the session raises ``selectionChanged``, which would push it back
into the view, which would raise Qt's own ``selectionChanged`` again.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (QAbstractItemModel, QItemSelection,
                            QItemSelectionModel, QModelIndex, Qt)

from makeyourtree.core.node import Node
from makeyourtree.ops.edit import rename

from ..session import Dirty, Session
from . import SetFieldCommand

__all__ = ["TreeModel"]


class TreeModel(QAbstractItemModel):
    """Tree rows with name, branch length, support and descendant count."""

    COL_NAME = 0
    COL_LENGTH = 1
    COL_SUPPORT = 2
    COL_LEAVES = 3
    COLUMN_COUNT = 4

    NodeIdRole = int(Qt.ItemDataRole.UserRole) + 1

    _HEADERS = ("Name", "Length", "Support", "Leaves")

    def __init__(self, session: Session, parent: Any = None) -> None:
        super().__init__(parent)
        self._session = session
        self._materialised: set[int] = set()
        self._syncing = False
        self.selection_model = QItemSelectionModel(self, self)

        self._after_command = False
        session.documentReplaced.connect(self._on_document_replaced)
        session.historyChanged.connect(self._on_history_changed)
        session.dirtied.connect(self._on_dirtied)
        session.selectionChanged.connect(self.sync_from_session)
        self.selection_model.selectionChanged.connect(self._on_view_selection)

    # ------------------------------------------------------------- lazy tree

    @property
    def session(self) -> Session:
        return self._session

    @property
    def materialised(self) -> frozenset[int]:
        """Node ids for which an index has been created since the last reset.

        Read by the laziness test, and by :meth:`_on_dirtied` to bound repaints.
        """
        return frozenset(self._materialised)

    def node_for(self, index: QModelIndex) -> Node | None:
        if not index.isValid():
            return None
        return self._session.tree.by_id(int(index.internalId()))

    def index(self, row: int, column: int,
              parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if column < 0 or column >= self.COLUMN_COUNT or row < 0:
            return QModelIndex()
        if not parent.isValid():
            root = self._session.tree.root
            if row != 0 or root is None:
                return QModelIndex()
            node = root
        else:
            p = self.node_for(parent)
            if p is None or row >= len(p.children):
                return QModelIndex()
            node = p.children[row]
        self._materialised.add(node.id)
        return self.createIndex(row, column, node.id)

    def parent(self, index: QModelIndex = QModelIndex()) -> QModelIndex:
        node = self.node_for(index)
        if node is None or node.parent is None:
            return QModelIndex()
        p = node.parent
        self._materialised.add(p.id)
        return self.createIndex(p.child_index(), 0, p.id)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return 1 if self._session.tree.root is not None else 0
        if parent.column() > 0:
            return 0
        node = self.node_for(parent)
        return 0 if node is None else len(node.children)

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if not parent.isValid():
            return self._session.tree.root is not None
        node = self.node_for(parent)
        return bool(node is not None and node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return self.COLUMN_COUNT

    # ----------------------------------------------------------------- data

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if (orientation is Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole
                and 0 <= section < self.COLUMN_COUNT):
            return self._HEADERS[section]
        return None

    def data(self, index: QModelIndex,
             role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node = self.node_for(index)
        if node is None:
            return None
        col = index.column()
        if role == self.NodeIdRole:
            return node.id
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            edit = role == Qt.ItemDataRole.EditRole
            if col == self.COL_NAME:
                if node.name:
                    return node.name
                return "" if edit else "(%d)" % node.id
            if col == self.COL_LENGTH:
                if node.branch_length is None:
                    return ""
                return (float(node.branch_length) if edit
                        else format(node.branch_length, ".6g"))
            if col == self.COL_SUPPORT:
                if node.support is None:
                    return ""
                return float(node.support) if edit else format(node.support, ".6g")
            if col == self.COL_LEAVES:
                if edit:
                    return None
                return "" if node.is_leaf else str(self._leaf_count(node))
        if role == Qt.ItemDataRole.TextAlignmentRole and col != self.COL_NAME:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            kind = "leaf" if node.is_leaf else "clade of %d" % self._leaf_count(node)
            return ("#%d %s (%s)" % (node.id, node.name or "", kind)).strip()
        return None

    @staticmethod
    def _leaf_count(node: Node) -> int:
        """Descendant leaves, counted live.

        ``Node.n_leaves`` is a cache only valid after ``Tree.refresh``, and the
        model is asked for data at moments when an edit has invalidated it but no
        recomposition has run yet. Counting costs O(subtree) and is only ever
        asked for rows the view is actually showing.
        """
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

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() in (self.COL_NAME, self.COL_LENGTH, self.COL_SUPPORT):
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def setData(self, index: QModelIndex, value: Any,
                role: int = Qt.ItemDataRole.EditRole) -> bool:
        """Commit an in-place edit as exactly one undoable command."""
        if role != Qt.ItemDataRole.EditRole:
            return False
        node = self.node_for(index)
        if node is None:
            return False
        col = index.column()
        if col == self.COL_NAME:
            new = str(value).strip() or None
            if new == node.name:
                return False
            self._session.do(rename(self._session.tree, node, new))
            return True
        if col in (self.COL_LENGTH, self.COL_SUPPORT):
            field = "branch_length" if col == self.COL_LENGTH else "support"
            new_num = parse_number(value)
            if new_num == getattr(node, field):
                return False
            self._session.do(SetFieldCommand(node, field, new_num))
            return True
        return False

    # ------------------------------------------------------------ navigation

    def index_for_node(self, node_id: int, column: int = 0) -> QModelIndex:
        """Index for *node_id*, built by walking down from the root.

        O(depth), and it materialises only the ancestors it passes through --
        which is the point: revealing one search hit in a 200 000-node tree must
        not touch 200 000 rows.
        """
        node = self._session.tree.by_id(node_id)
        if node is None:
            return QModelIndex()
        chain: list[Node] = []
        cur: Node | None = node
        while cur is not None:
            chain.append(cur)
            cur = cur.parent
        chain.reverse()
        if chain[0] is not self._session.tree.root:
            return QModelIndex()
        idx = self.index(0, column, QModelIndex())
        for child in chain[1:]:
            idx = self.index(child.child_index(), column, idx)
            if not idx.isValid():
                return QModelIndex()
        return idx

    # ------------------------------------------------------------- selection

    def sync_from_session(self) -> None:
        """Mirror ``session.selection`` into the view's selection model.

        Each range already spans column 0 to the last column, which *is* the
        whole row, so ``SelectionFlag.Rows`` would only ask Qt to redo work it
        has already been handed. It is not free: with ``Rows`` set,
        ``QItemSelectionModel`` re-expands and re-merges every range through the
        model, calling :meth:`parent` on the way, and the cost is quadratic in
        the number of ranges. Select All on a 5 000-tip tree spent **150
        seconds** inside that one call -- 50 million ``parent()`` round trips --
        and the window was frozen for every one of them. Without the flag the
        identical selection lands in 0.4 s; ``selectedRows()`` returns the same
        rows either way, which is asserted in the tests.
        """
        if self._syncing:
            return
        self._syncing = True
        try:
            sel = QItemSelection()
            for nid in sorted(self._session.selection):
                idx = self.index_for_node(nid)
                if idx.isValid():
                    last = idx.sibling(idx.row(), self.COLUMN_COUNT - 1)
                    sel.select(idx, last)
            self.selection_model.select(
                sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        finally:
            self._syncing = False

    def _on_view_selection(self, _selected: QItemSelection,
                           _deselected: QItemSelection) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            ids = {int(i.internalId())
                   for i in self.selection_model.selectedIndexes()}
            self._session.set_selection(ids)
        finally:
            self._syncing = False

    # --------------------------------------------------------- invalidation

    def _on_document_replaced(self) -> None:
        self.reset_model()

    def reset_model(self) -> None:
        """Rebuild every index, then put the selection back.

        A reset empties the ``QItemSelectionModel``. The session, not the view,
        owns what is selected, so the selection is restored from it afterwards --
        which also makes an over-eager reset merely wasteful rather than
        destructive.
        """
        self.beginResetModel()
        self._materialised.clear()
        self.endResetModel()
        self.sync_from_session()

    def _on_history_changed(self) -> None:
        """Note that the next ``dirtied`` came from a command, not a selection.

        ``Session.do`` raises ``historyChanged`` from inside the command stack
        and ``dirtied`` immediately afterwards, so this pairing identifies the
        dirty notifications that actually followed a tree edit. Without it the
        model would have to treat every ``dirtied`` as structural -- and
        ``dirtied`` also fires for a plain selection change, whose reported level
        is the *accumulated* one, still reading TOPOLOGY until the canvas has
        recomposed. Resetting on that would silently discard the selection the
        user just made, which is how a selection round-trip turns into a
        selection that never sticks.
        """
        self._after_command = True

    def _on_dirtied(self, level: int) -> None:
        """Repaint or rebuild, depending on how much of the tree moved.

        Anything at or above ``ORDER`` can move rows -- ladderize permutes
        children, a reroot rewrites the parent chain -- so the row identities the
        view holds are no longer trustworthy and a reset is the only correct
        answer. A style-level change cannot move a row, so the far cheaper
        ``dataChanged`` over the rows actually on screen is enough.
        """
        if not self._after_command:
            return
        self._after_command = False
        if level >= int(Dirty.ORDER):
            self.reset_model()
        elif level >= int(Dirty.STYLE):
            for nid in sorted(self._materialised):
                idx = self.index_for_node(nid)
                if idx.isValid():
                    self.dataChanged.emit(
                        idx, idx.sibling(idx.row(), self.COLUMN_COUNT - 1))


def parse_number(value: Any) -> float | None:
    """Coerce editor text to a number, treating blank as "no value".

    Blank must map to ``None`` rather than to ``0.0``: a cladogram with no branch
    lengths and a phylogram whose branches are all zero are different trees, and
    conflating them silently invents data.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
