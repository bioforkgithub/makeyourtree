# SPDX-License-Identifier: MIT
"""The tree dock: structural edits arrive as commands, selection stays in step."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel

from makeyourtree.doc.document import Document
from makeyourtree_studio.panels.tree_panel import TreePanel
from makeyourtree_studio.session import Session

from _panels_support import Counter, sample_tree


def test_panel_constructs_and_shows_the_root(studio: Session):
    panel = TreePanel(studio)
    assert panel.model.rowCount() == 1
    assert panel.view.model() is panel.model
    assert panel.view.selectionModel() is panel.model.selection_model


def test_panel_survives_document_replaced(studio: Session):
    panel = TreePanel(studio)
    other = Document(tree=sample_tree())
    studio.set_document(other)
    root = panel.model.index(0, 0)
    assert panel.model.node_for(root) is other.tree.root
    assert panel.view.isExpanded(root)


def test_collapsing_a_clade_is_one_undoable_command(studio: Session):
    panel = TreePanel(studio)
    clade = studio.tree.by_name("ab")
    studio.set_selection([clade.id])
    panel.toggle_collapse()
    assert clade.collapsed is True
    assert len(studio.stack.history()) == 1
    studio.undo()
    assert clade.collapsed is False


def test_collapsing_several_clades_is_still_one_history_entry(studio: Session):
    panel = TreePanel(studio)
    ids = [studio.tree.by_name(n).id for n in ("ab", "cd", "ef")]
    studio.set_selection(ids)
    panel.toggle_collapse()
    assert all(studio.tree.by_id(i).collapsed for i in ids)
    assert len(studio.stack.history()) == 1
    studio.undo()
    assert not any(studio.tree.by_id(i).collapsed for i in ids)


def test_collapse_button_toggles_back_to_expand(studio: Session):
    panel = TreePanel(studio)
    clade = studio.tree.by_name("cd")
    studio.set_selection([clade.id])
    panel.toggle_collapse()
    assert panel.collapse_button.text() == "Expand"
    panel.toggle_collapse()
    assert clade.collapsed is False
    assert panel.collapse_button.text() == "Collapse"


def test_ladderize_reorders_and_undoes(studio: Session):
    panel = TreePanel(studio)
    before = [n.name for n in studio.tree.leaves]
    panel.ladderize(False)
    assert len(studio.stack.history()) == 1
    assert [n.name for n in studio.tree.leaves] != before
    studio.undo()
    assert [n.name for n in studio.tree.leaves] == before


def test_rotate_reverses_the_children_of_the_selection(studio: Session):
    panel = TreePanel(studio)
    clade = studio.tree.by_name("ab")
    studio.set_selection([clade.id])
    panel.rotate_selection()
    assert [c.name for c in clade.children] == ["b", "a"]
    studio.undo()
    assert [c.name for c in clade.children] == ["a", "b"]


def test_reroot_moves_the_root_and_undoes(studio: Session):
    panel = TreePanel(studio)
    leaf = studio.tree.by_name("e")
    old_root = studio.tree.root
    studio.set_selection([leaf.id])
    panel.reroot_selection()
    assert studio.tree.root is not old_root
    assert len(studio.stack.history()) == 1
    studio.undo()
    assert studio.tree.root is old_root


def test_reroot_on_the_root_is_reported_not_raised(studio: Session):
    panel = TreePanel(studio)
    messages: list[str] = []
    studio.statusMessage.connect(lambda text, _ms: messages.append(text))
    studio.set_selection([studio.tree.root.id])
    panel.reroot_selection()
    assert studio.stack.history() == []
    assert messages


def test_prune_removes_taxa_and_clears_the_selection(studio: Session):
    panel = TreePanel(studio)
    leaf = studio.tree.by_name("f")
    studio.set_selection([leaf.id])
    panel.prune_selection()
    assert studio.tree.by_name("f") is None
    assert studio.selection == set()
    studio.undo()
    studio.tree.refresh()
    assert studio.tree.by_name("f") is not None


def test_pruning_everything_is_refused_with_a_message(studio: Session):
    panel = TreePanel(studio)
    messages: list[str] = []
    studio.statusMessage.connect(lambda text, _ms: messages.append(text))
    studio.set_selection([n.id for n in studio.tree.leaves])
    panel.prune_selection()
    assert studio.stack.history() == []
    assert messages


def test_selecting_a_node_expands_and_scrolls_to_its_row(studio: Session):
    panel = TreePanel(studio)
    leaf = studio.tree.by_name("d")
    studio.set_selection([leaf.id])
    idx = panel.model.index_for_node(leaf.id)
    assert idx.isValid()
    parent = idx.parent()
    while parent.isValid():
        assert panel.view.isExpanded(parent)
        parent = parent.parent()


def test_selecting_a_row_selects_the_node_exactly_once(studio: Session):
    panel = TreePanel(studio)
    counter = Counter()
    studio.selectionChanged.connect(counter)
    leaf = studio.tree.by_name("c")
    idx = panel.model.index_for_node(leaf.id)
    panel.model.selection_model.select(
        idx,
        QItemSelectionModel.SelectionFlag.ClearAndSelect
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    assert studio.selection == {leaf.id}
    assert counter.n == 1


def test_buttons_disable_without_a_usable_selection(studio: Session):
    panel = TreePanel(studio)
    studio.clear_selection()
    assert not panel.collapse_button.isEnabled()
    assert not panel.rotate_button.isEnabled()
    assert not panel.reroot_button.isEnabled()
    assert not panel.prune_button.isEnabled()
    studio.set_selection([studio.tree.by_name("ab").id])
    assert panel.collapse_button.isEnabled()
    assert panel.rotate_button.isEnabled()
    assert panel.reroot_button.isEnabled()
