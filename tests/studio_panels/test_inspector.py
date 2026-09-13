# SPDX-License-Identifier: MIT
"""The inspector: what the selection is, and the three fields it can change."""

from __future__ import annotations

from makeyourtree.doc.document import Document
from makeyourtree_studio.panels.inspector import InspectorPanel
from makeyourtree_studio.session import Session

from _panels_support import sample_tree, strip_track


def _select(session: Session, name: str) -> None:
    session.set_selection([session.tree.by_name(name).id])


def test_nothing_selected_disables_the_editors(studio: Session):
    panel = InspectorPanel(studio)
    assert panel.heading.text() == "Nothing selected"
    assert not panel.fields_group.isEnabled()
    assert panel.name_edit.text() == ""


def test_a_single_selection_shows_its_fields(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "a")
    assert panel.fields_group.isEnabled()
    assert panel.name_edit.text() == "a"
    assert panel.length_edit.text() == "0.1"
    assert panel.children_label.text() == "0"
    assert panel.leaves_label.text() == "1"
    assert "Leaf" in panel.heading.text()


def test_derived_values_are_computed_live(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "a")
    # a sits under ab (0.3) under abcd (0.7) under the root.
    assert panel.level_label.text() == "3"
    assert float(panel.distance_label.text()) == 1.1
    _select(studio, "abcd")
    assert panel.leaves_label.text() == "4"
    assert panel.children_label.text() == "2"
    assert panel.support_edit.text() == "55"


def test_the_root_is_labelled_as_such(studio: Session):
    panel = InspectorPanel(studio)
    studio.set_selection([studio.tree.root.id])
    assert panel.heading.text().startswith("Root")
    assert panel.length_edit.text() == ""


def test_several_nodes_selected_disables_editing(studio: Session):
    panel = InspectorPanel(studio)
    studio.set_selection([studio.tree.by_name(n).id for n in ("a", "b")])
    assert panel.heading.text() == "2 nodes selected"
    assert not panel.fields_group.isEnabled()
    assert panel.current_node() is None


def test_renaming_makes_exactly_one_command_and_undoes(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "a")
    node = studio.tree.by_name("a")
    panel.name_edit.setText("alpha")
    panel.name_edit.editingFinished.emit()
    assert node.name == "alpha"
    assert len(studio.stack.history()) == 1
    studio.undo()
    assert node.name == "a"
    assert panel.name_edit.text() == "a"


def test_committing_an_unchanged_name_adds_no_history(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "a")
    panel.name_edit.editingFinished.emit()
    panel.name_edit.setText("a")
    panel.name_edit.editingFinished.emit()
    assert studio.stack.history() == []


def test_clearing_the_name_stores_none(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "a")
    node = studio.tree.by_name("a")
    panel.name_edit.setText("   ")
    panel.name_edit.editingFinished.emit()
    assert node.name is None
    studio.undo()
    assert node.name == "a"


def test_editing_the_branch_length_is_one_undoable_command(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "b")
    node = studio.tree.by_name("b")
    panel.length_edit.setText("0.75")
    panel.length_edit.editingFinished.emit()
    assert node.branch_length == 0.75
    assert len(studio.stack.history()) == 1
    studio.undo()
    assert node.branch_length == 0.2


def test_a_blank_branch_length_means_absent(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "b")
    node = studio.tree.by_name("b")
    panel.length_edit.setText("")
    panel.length_edit.editingFinished.emit()
    assert node.branch_length is None
    studio.undo()
    assert node.branch_length == 0.2


def test_editing_support_is_one_undoable_command(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "ab")
    node = studio.tree.by_name("ab")
    panel.support_edit.setText("42")
    panel.support_edit.editingFinished.emit()
    assert node.support == 42.0
    assert len(studio.stack.history()) == 1
    studio.undo()
    assert node.support == 98.0


def test_a_non_numeric_entry_is_refused_and_restored(studio: Session):
    panel = InspectorPanel(studio)
    messages: list[str] = []
    studio.statusMessage.connect(lambda text, _ms: messages.append(text))
    _select(studio, "b")
    node = studio.tree.by_name("b")
    panel.length_edit.setText("not a number")
    panel.length_edit.editingFinished.emit()
    assert node.branch_length == 0.2
    assert studio.stack.history() == []
    assert messages
    assert panel.length_edit.text() == "0.2"


def test_node_attributes_are_listed(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "a")
    rows = {panel.attrs_table.item(r, 0).text(): panel.attrs_table.item(r, 1).text()
            for r in range(panel.attrs_table.rowCount())}
    assert rows["habitat"] == "marine"
    assert rows["accession"] == "X12345"


def test_track_values_for_the_node_are_listed(studio: Session):
    studio.add_track(strip_track(studio.tree, title="Region"))
    panel = InspectorPanel(studio)
    _select(studio, "a")
    rows = {panel.tracks_table.item(r, 0).text(): panel.tracks_table.item(r, 1).text()
            for r in range(panel.tracks_table.rowCount())}
    assert rows == {"Region": "north"}
    _select(studio, "c")
    assert panel.tracks_table.rowCount() == 0


def test_panel_survives_document_replaced(studio: Session):
    panel = InspectorPanel(studio)
    _select(studio, "a")
    studio.set_document(Document(tree=sample_tree()))
    assert panel.heading.text() == "Nothing selected"
    assert not panel.fields_group.isEnabled()
    _select(studio, "e")
    assert panel.name_edit.text() == "e"
