# SPDX-License-Identifier: MIT
"""The search dock: it looks through collapsed clades and offers to open them."""

from __future__ import annotations

from makeyourtree.doc.document import Document
from makeyourtree.ops.edit import collapse
from makeyourtree_studio.panels.search_panel import (MODE_REGEX, MODE_WHOLE_WORD,
                                                 SearchPanel)
from makeyourtree_studio.session import Session

from _panels_support import sample_tree


def _names(session: Session, ids: list[int]) -> set[str]:
    return {session.tree.by_id(i).name for i in ids}


def test_substring_search_finds_every_matching_node(studio: Session):
    panel = SearchPanel(studio)
    panel.query_edit.setText("c")
    assert _names(studio, panel.hits) == {"c", "cd", "abcd"}
    assert studio.search_hits == panel.hits


def test_leaves_only_excludes_internal_nodes(studio: Session):
    panel = SearchPanel(studio)
    panel.leaves_check.setChecked(True)
    panel.query_edit.setText("c")
    assert _names(studio, panel.hits) == {"c"}


def test_whole_word_matches_the_entire_value(studio: Session):
    panel = SearchPanel(studio)
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData(MODE_WHOLE_WORD))
    panel.query_edit.setText("cd")
    assert _names(studio, panel.hits) == {"cd"}


def test_regex_mode_understands_anchors(studio: Session):
    panel = SearchPanel(studio)
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData(MODE_REGEX))
    panel.query_edit.setText("^a.$")
    assert _names(studio, panel.hits) == {"ab"}


def test_a_half_typed_regex_reports_rather_than_raises(studio: Session):
    panel = SearchPanel(studio)
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData(MODE_REGEX))
    panel.query_edit.setText("a[")
    assert panel.hits == []
    assert "Incomplete" in panel.status_label.text()


def test_case_sensitivity_is_honoured(studio: Session):
    panel = SearchPanel(studio)
    panel.case_check.setChecked(True)
    panel.query_edit.setText("AB")
    assert panel.hits == []
    panel.case_check.setChecked(False)
    assert _names(studio, panel.hits) == {"ab", "abcd"}


def test_searching_an_attribute_field(studio: Session):
    panel = SearchPanel(studio)
    assert panel.field_combo.findData("habitat") >= 0
    panel.field_combo.setCurrentIndex(panel.field_combo.findData("habitat"))
    panel.query_edit.setText("marine")
    assert _names(studio, panel.hits) == {"a"}


def test_an_empty_query_clears_the_hits(studio: Session):
    panel = SearchPanel(studio)
    panel.query_edit.setText("a")
    assert panel.hits
    panel.query_edit.setText("")
    assert panel.hits == []
    assert studio.search_hits == []


def test_search_finds_a_node_inside_a_collapsed_clade(studio: Session):
    panel = SearchPanel(studio)
    clade = studio.tree.by_name("cd")
    studio.do(collapse(studio.tree, clade, True))
    assert clade.collapsed is True

    panel.query_edit.setText("d")
    leaf = studio.tree.by_name("d")
    assert leaf.id in panel.hits
    assert [n.id for n in panel.collapsed_ancestors()] == [clade.id]
    assert "collapsed" in panel.status_label.text()
    assert panel.expand_button.isEnabled()


def test_expanding_to_hits_opens_only_the_clades_that_hide_one(studio: Session):
    panel = SearchPanel(studio)
    hidden = studio.tree.by_name("cd")
    untouched = studio.tree.by_name("ef")
    studio.do(collapse(studio.tree, hidden, True))
    studio.do(collapse(studio.tree, untouched, True))
    before = len(studio.stack.history())

    panel.query_edit.setText("d")
    panel.expand_to_hits()

    assert hidden.collapsed is False
    assert untouched.collapsed is True
    assert len(studio.stack.history()) == before + 1
    assert panel.collapsed_ancestors() == []
    studio.undo()
    assert hidden.collapsed is True


def test_expanding_several_clades_is_one_history_entry(studio: Session):
    panel = SearchPanel(studio)
    for name in ("ab", "cd"):
        studio.do(collapse(studio.tree, studio.tree.by_name(name), True))
    before = len(studio.stack.history())
    # One hit under each collapsed clade, so both must be opened.
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData(MODE_REGEX))
    panel.query_edit.setText("^[bd]$")
    assert len(panel.collapsed_ancestors()) == 2
    panel.expand_to_hits()
    assert len(studio.stack.history()) == before + 1
    studio.undo()
    assert studio.tree.by_name("ab").collapsed is True
    assert studio.tree.by_name("cd").collapsed is True


def test_next_and_previous_walk_the_hits_and_wrap(studio: Session):
    panel = SearchPanel(studio)
    centred: list[int] = []
    panel.centerOnNode.connect(centred.append)
    panel.query_edit.setText("c")
    total = len(panel.hits)
    assert total == 3

    seen = []
    for _ in range(total + 1):
        panel.go_next()
        seen.append(sorted(studio.selection)[0])
    assert seen[0] == seen[-1]
    assert len(centred) == total + 1

    panel.go_previous()
    assert len(studio.selection) == 1


def test_navigation_without_hits_is_a_no_op(studio: Session):
    panel = SearchPanel(studio)
    panel.go_next()
    panel.go_previous()
    assert studio.selection == set()


def test_select_all_matches_selects_every_hit(studio: Session):
    panel = SearchPanel(studio)
    panel.query_edit.setText("c")
    panel.select_all_matches()
    assert studio.selection == set(panel.hits)


def test_clicking_a_result_selects_and_centres_it(studio: Session):
    panel = SearchPanel(studio)
    centred: list[int] = []
    panel.centerOnNode.connect(centred.append)
    panel.query_edit.setText("ef")
    panel.results.setCurrentRow(0)
    expected = panel.hits[0]
    assert studio.selection == {expected}
    assert centred == [expected]


def test_panel_survives_document_replaced(studio: Session):
    panel = SearchPanel(studio)
    panel.query_edit.setText("c")
    assert panel.hits
    studio.set_document(Document(tree=sample_tree()))
    assert panel.hits == []
    assert studio.search_hits == []
    assert panel.field_combo.findData("habitat") >= 0
