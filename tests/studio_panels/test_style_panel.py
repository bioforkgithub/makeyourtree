# SPDX-License-Identifier: MIT
"""The style dock: view settings bypass undo, node styling does not."""

from __future__ import annotations

from makeyourtree.doc.document import Document
from makeyourtree.layout.params import BranchMode, LayoutMode, ParentRule
from makeyourtree.style.color import Color
from makeyourtree.style.theme import DARK, LIGHT
from makeyourtree_studio.panels.style_panel import StylePanel
from makeyourtree_studio.session import Dirty, Session

from _panels_support import sample_tree


def _select(session: Session, *names: str) -> None:
    session.set_selection([session.tree.by_name(n).id for n in names])


def test_panel_loads_the_documents_current_settings(studio: Session):
    studio.params.row_spacing = 21.0
    studio.params.mode = LayoutMode.CIRCULAR
    panel = StylePanel(studio)
    assert panel.row_spacing_spin.value() == 21.0
    assert panel.mode_combo.currentData() == LayoutMode.CIRCULAR.value


def test_layout_controls_write_params_without_touching_history(studio: Session):
    panel = StylePanel(studio)
    panel.mode_combo.setCurrentIndex(
        panel.mode_combo.findData(LayoutMode.SLANTED.value))
    panel.branch_mode_combo.setCurrentIndex(
        panel.branch_mode_combo.findData(BranchMode.CLADOGRAM_LEVEL.value))
    panel.parent_rule_combo.setCurrentIndex(
        panel.parent_rule_combo.findData(ParentRule.WEIGHTED.value))
    panel.row_spacing_spin.setValue(24.0)
    panel.align_tips_check.setChecked(True)

    assert studio.params.mode is LayoutMode.SLANTED
    assert studio.params.branch_mode is BranchMode.CLADOGRAM_LEVEL
    assert studio.params.parent_rule is ParentRule.WEIGHTED
    assert studio.params.row_spacing == 24.0
    assert studio.params.align_tips is True
    assert studio.stack.history() == []


def test_polar_and_unrooted_controls_reach_the_params(studio: Session):
    panel = StylePanel(studio)
    panel.start_angle_spin.setValue(-45.0)
    panel.arc_spin.setValue(300.0)
    panel.inner_radius_spin.setValue(0.25)
    panel.direction_combo.setCurrentIndex(panel.direction_combo.findData(-1))
    panel.rotate_labels_check.setChecked(False)
    panel.daylight_spin.setValue(7)

    assert studio.params.start_angle == -45.0
    assert studio.params.arc == 300.0
    assert studio.params.inner_radius == 0.25
    assert studio.params.direction == -1
    assert studio.params.rotate_labels is False
    assert studio.params.daylight_iterations == 7


def test_x_scale_zero_means_fit(studio: Session):
    panel = StylePanel(studio)
    panel.x_scale_spin.setValue(12.5)
    assert studio.params.x_scale == 12.5
    panel.x_scale_spin.setValue(0.0)
    assert studio.params.x_scale is None


def test_label_and_support_controls_write_the_theme(studio: Session):
    panel = StylePanel(studio)
    panel.tip_labels_check.setChecked(False)
    panel.label_size_spin.setValue(14.0)
    panel.show_support_check.setChecked(True)
    panel.support_min_spin.setValue(70.0)
    panel.support_position_combo.setCurrentIndex(
        panel.support_position_combo.findData("below"))
    panel.scalebar_check.setChecked(False)

    assert studio.params.show_tip_labels is False
    assert studio.theme.label_size == 14.0
    assert studio.theme.show_support is True
    assert studio.theme.support_min == 70.0
    assert studio.theme.support_position == "below"
    assert studio.theme.scalebar_show is False


def test_an_unusable_support_format_is_refused(studio: Session):
    panel = StylePanel(studio)
    messages: list[str] = []
    studio.statusMessage.connect(lambda text, _ms: messages.append(text))
    before = studio.theme.support_format
    panel.support_format_edit.setText("{:.3q}")
    panel.support_format_edit.editingFinished.emit()
    assert studio.theme.support_format == before
    assert messages
    panel.support_format_edit.setText("{:.0f}")
    panel.support_format_edit.editingFinished.emit()
    assert studio.theme.support_format == "{:.0f}"


def test_theme_preset_replaces_every_field_in_place(studio: Session):
    panel = StylePanel(studio)
    theme = studio.theme
    panel.theme_combo.setCurrentIndex(panel.theme_combo.findData("dark"))
    assert studio.theme is theme
    assert theme.name == DARK.name
    assert theme.background == DARK.background
    panel.theme_combo.setCurrentIndex(panel.theme_combo.findData("light"))
    assert theme.background == LIGHT.background


def test_branch_colour_is_an_undoable_command(studio: Session):
    panel = StylePanel(studio)
    _select(studio, "ab")
    node = studio.tree.by_name("ab")
    panel.branch_color_button.set_color(Color(200, 30, 30), notify=True)
    assert node.style["branch_color"] == Color(200, 30, 30)
    assert len(studio.stack.history()) == 1
    studio.undo()
    assert node.style is None


def test_styling_applies_to_every_selected_node(studio: Session):
    panel = StylePanel(studio)
    _select(studio, "a", "b", "c")
    panel.apply_node_style("label_bold", True)
    for name in ("a", "b", "c"):
        assert studio.tree.by_name(name).style["label_bold"] is True
    assert len(studio.stack.history()) == 1
    studio.undo()
    for name in ("a", "b", "c"):
        assert studio.tree.by_name(name).style is None


def test_styling_with_no_selection_reports_instead_of_editing(studio: Session):
    panel = StylePanel(studio)
    messages: list[str] = []
    studio.statusMessage.connect(lambda text, _ms: messages.append(text))
    studio.clear_selection()
    panel.apply_node_style("label_bold", True)
    assert studio.stack.history() == []
    assert messages


def test_a_fifty_step_slider_drag_makes_one_history_entry(studio: Session):
    panel = StylePanel(studio)
    _select(studio, "ab")
    node = studio.tree.by_name("ab")

    for step in range(1, 51):
        panel.branch_width_slider.setValue(step)

    assert len(studio.stack.history()) == 1
    assert node.style["branch_width"] == 50 / 10.0
    studio.undo()
    assert node.style is None
    assert studio.stack.history() == []


def test_a_drag_after_a_real_edit_does_not_swallow_it(studio: Session):
    panel = StylePanel(studio)
    _select(studio, "ab")
    panel.apply_node_style("label_bold", True)
    for step in range(1, 11):
        panel.branch_width_slider.setValue(step)
    assert len(studio.stack.history()) == 2


def test_a_second_drag_on_a_different_selection_is_a_new_entry(studio: Session):
    panel = StylePanel(studio)
    _select(studio, "ab")
    for step in range(1, 6):
        panel.branch_width_slider.setValue(step)
    _select(studio, "cd")
    for step in range(1, 6):
        panel.branch_width_slider.setValue(step)
    assert len(studio.stack.history()) == 2


def test_clearing_styles_removes_every_override_in_one_entry(studio: Session):
    panel = StylePanel(studio)
    _select(studio, "ab")
    node = studio.tree.by_name("ab")
    panel.apply_node_style("branch_color", Color(1, 2, 3))
    panel.apply_node_style("label_italic", True)
    before = len(studio.stack.history())
    panel.clear_selection_style()
    assert node.style is None
    assert len(studio.stack.history()) == before + 1
    studio.undo()
    assert node.style["label_italic"] is True


def test_selection_group_disables_without_a_selection(studio: Session):
    panel = StylePanel(studio)
    studio.clear_selection()
    assert not panel.selection_group.isEnabled()
    _select(studio, "a")
    assert panel.selection_group.isEnabled()
    assert panel.selection_label.text() == "1 node selected"
    _select(studio, "a", "b")
    assert panel.selection_label.text() == "2 nodes selected"


def test_panel_reloads_after_document_replaced(studio: Session):
    panel = StylePanel(studio)
    panel.row_spacing_spin.setValue(33.0)
    replacement = Document(tree=sample_tree())
    replacement.params.row_spacing = 9.0
    replacement.params.mode = LayoutMode.RADIAL
    studio.set_document(replacement)
    assert panel.row_spacing_spin.value() == 9.0
    assert panel.mode_combo.currentData() == LayoutMode.RADIAL.value
    assert not panel.selection_group.isEnabled()


def test_layout_changes_invalidate_the_layout_stage(studio: Session):
    panel = StylePanel(studio)
    studio.recompose()
    assert studio.dirty is Dirty.NOTHING
    panel.row_spacing_spin.setValue(30.0)
    assert studio.dirty is Dirty.LAYOUT
