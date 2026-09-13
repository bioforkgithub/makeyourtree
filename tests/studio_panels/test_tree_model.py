# SPDX-License-Identifier: MIT
"""The lazy tree model: structure, laziness, editing and selection sync."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt
from PySide6.QtWidgets import QTreeView

from makeyourtree.doc.document import Document
from makeyourtree_studio.models.tree_model import TreeModel
from makeyourtree_studio.session import Session

from _panels_support import Counter, balanced_tree, sample_tree

ROOT = QModelIndex()


def _root_index(model: TreeModel):
    return model.index(0, 0, ROOT)


def test_root_is_a_single_top_level_row(studio: Session):
    model = TreeModel(studio)
    assert model.rowCount(ROOT) == 1
    assert model.columnCount(ROOT) == 4
    root = _root_index(model)
    assert model.node_for(root) is studio.tree.root
    assert model.rowCount(root) == len(studio.tree.root.children)


def test_parent_round_trips_through_the_node_id(studio: Session):
    model = TreeModel(studio)
    root = _root_index(model)
    child = model.index(0, 0, root)
    assert model.parent(child) == root
    grandchild = model.index(1, 0, child)
    assert model.node_for(grandchild) is studio.tree.root.children[0].children[1]
    assert model.parent(grandchild) == child
    assert not model.parent(root).isValid()


def test_columns_report_name_length_support_and_leaf_count(studio: Session):
    model = TreeModel(studio)
    leaf_a = studio.tree.by_name("a")
    idx = model.index_for_node(leaf_a.id)
    assert idx.isValid()
    row = [model.data(idx.sibling(idx.row(), c)) for c in range(4)]
    assert row[TreeModel.COL_NAME] == "a"
    assert row[TreeModel.COL_LENGTH] == "0.1"
    assert row[TreeModel.COL_LEAVES] == ""

    clade = studio.tree.by_name("abcd")
    cidx = model.index_for_node(clade.id)
    assert model.data(cidx.sibling(cidx.row(), TreeModel.COL_LEAVES)) == "4"
    assert model.data(cidx.sibling(cidx.row(), TreeModel.COL_SUPPORT)) == "55"


def test_header_labels_cover_every_column(studio: Session):
    model = TreeModel(studio)
    labels = [model.headerData(c, Qt.Orientation.Horizontal)
              for c in range(model.columnCount(ROOT))]
    assert labels == ["Name", "Length", "Support", "Leaves"]


def test_model_survives_document_replaced(studio: Session):
    model = TreeModel(studio)
    _root_index(model)
    other = Document(tree=sample_tree())
    studio.set_document(other)
    root = _root_index(model)
    assert model.node_for(root) is other.tree.root
    assert model.rowCount(root) == len(other.tree.root.children)


def test_editing_a_name_makes_exactly_one_undoable_command(studio: Session):
    model = TreeModel(studio)
    leaf = studio.tree.by_name("b")
    idx = model.index_for_node(leaf.id)
    assert model.setData(idx, "beta", Qt.ItemDataRole.EditRole)
    assert len(studio.stack.history()) == 1
    assert leaf.name == "beta"
    studio.undo()
    assert leaf.name == "b"
    assert studio.stack.history() == []


def test_editing_the_same_name_again_makes_no_command(studio: Session):
    model = TreeModel(studio)
    leaf = studio.tree.by_name("b")
    idx = model.index_for_node(leaf.id)
    assert not model.setData(idx, "b", Qt.ItemDataRole.EditRole)
    assert studio.stack.history() == []


def test_editing_branch_length_is_undoable_and_blank_means_absent(studio: Session):
    model = TreeModel(studio)
    leaf = studio.tree.by_name("c")
    idx = model.index_for_node(leaf.id).sibling(
        model.index_for_node(leaf.id).row(), TreeModel.COL_LENGTH)
    assert model.setData(idx, "1.25", Qt.ItemDataRole.EditRole)
    assert leaf.branch_length == 1.25
    assert len(studio.stack.history()) == 1
    assert model.setData(idx, "", Qt.ItemDataRole.EditRole)
    assert leaf.branch_length is None
    studio.undo()
    assert leaf.branch_length == 1.25
    studio.undo()
    assert leaf.branch_length == 0.4


def test_selection_round_trips_without_a_signal_loop(studio: Session):
    model = TreeModel(studio)
    counter = Counter()
    studio.selectionChanged.connect(counter)

    leaf = studio.tree.by_name("d")
    studio.set_selection([leaf.id])
    assert counter.n == 1
    picked = {int(i.internalId())
              for i in model.selection_model.selectedIndexes()}
    assert picked == {leaf.id}

    other = studio.tree.by_name("e")
    idx = model.index_for_node(other.id)
    model.selection_model.select(
        idx,
        QItemSelectionModel.SelectionFlag.ClearAndSelect
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    assert studio.selection == {other.id}
    assert counter.n == 2


def test_clearing_the_selection_clears_the_view(studio: Session):
    model = TreeModel(studio)
    studio.set_selection([studio.tree.by_name("a").id])
    studio.clear_selection()
    assert not model.selection_model.selectedIndexes()


def test_a_topology_change_resets_the_model(studio: Session):
    model = TreeModel(studio)
    _root_index(model)
    counter = Counter()
    model.modelReset.connect(counter)
    from makeyourtree.ops.order import ladderize

    studio.do(ladderize(studio.tree))
    assert counter.n >= 1


def test_a_style_change_repaints_only_materialised_rows(studio: Session):
    model = TreeModel(studio)
    # The canvas normally recomposes after every burst of changes; without that
    # the accumulated dirty level never falls below TOPOLOGY and every edit
    # would be reported as structural.
    studio.recompose()
    leaf = studio.tree.by_name("a")
    model.index_for_node(leaf.id)
    touched: list[int] = []
    model.dataChanged.connect(
        lambda top, bottom, roles=None: touched.append(int(top.internalId())))
    from makeyourtree.ops.edit import rename

    studio.do(rename(studio.tree, leaf, "alpha"))
    assert touched
    assert set(touched) <= set(model.materialised)


def test_model_stays_lazy_on_a_twenty_thousand_leaf_tree(qapp):
    tree = balanced_tree(20_000)
    session = Session(Document(tree=tree))
    model = TreeModel(session)

    assert len(tree.nodes) >= 20_000
    assert model.materialised == frozenset()

    view = QTreeView()
    view.setModel(model)
    view.setSelectionModel(model.selection_model)
    root = model.index(0, 0, ROOT)
    view.expand(root)
    qapp.processEvents()

    # The whole point: a view over 40 000 nodes must have handed out a few
    # dozen indexes, not one per node.
    assert len(model.materialised) < 500
    assert model.rowCount(root) == len(tree.root.children)

    deep = tree.by_name("leaf19999")
    idx = model.index_for_node(deep.id)
    assert idx.isValid()
    assert model.data(idx) == "leaf19999"
    # Reaching one deep node costs its ancestors, nothing more.
    assert len(model.materialised) < 600
    view.setModel(None)


def test_selecting_everything_does_not_cost_a_quadratic_number_of_lookups(qapp):
    """Select All on a big tree must not freeze the window.

    ``QItemSelectionModel.select`` with ``SelectionFlag.Rows`` re-expands every
    range through the model and calls :meth:`TreeModel.parent` while merging;
    the cost is quadratic in the number of ranges. On a 5 000-tip tree that was
    fifty million ``parent()`` calls and about 150 seconds of frozen UI. The
    ranges this model builds already span every column -- they *are* whole rows
    -- so the flag only asked Qt to redo work it had been handed.

    Counting the lookups rather than the seconds keeps the test deterministic:
    a linear sync touches each node a small constant number of times.
    """
    tree = balanced_tree(2000)
    session = Session(Document(tree=tree))
    model = TreeModel(session)
    n_nodes = len(tree.nodes)

    calls = Counter()
    real_parent = model.parent

    def counted(index=QModelIndex()):
        calls()
        return real_parent(index)

    model.parent = counted
    try:
        session.set_selection([n.id for n in tree.nodes])
        qapp.processEvents()
    finally:
        del model.parent

    rows = model.selection_model.selectedRows()
    assert len(rows) == n_nodes, "every node must end up selected"
    assert {int(i.internalId()) for i in rows} == {n.id for n in tree.nodes}
    assert calls.n < 20 * n_nodes, (
        f"{calls.n} parent() lookups for {n_nodes} nodes -- the selection "
        "sync has gone superlinear again")
