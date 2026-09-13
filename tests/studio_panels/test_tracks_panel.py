# SPDX-License-Identifier: MIT
"""The tracks dock: the stack, the chooser and the generated options form."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QLabel, QLineEdit,
                               QSpinBox)

from makeyourtree.doc.document import Document
from makeyourtree.tracks.base import track_types
from makeyourtree_studio.panels import ColorButton
from makeyourtree_studio.panels.tracks_panel import TrackTypeDialog, TracksPanel
from makeyourtree_studio.session import Dirty, Session

from _panels_support import sample_tree


def _editor(panel: TracksPanel, key: str):
    return panel._editors.get(key)


def test_panel_starts_empty_with_the_form_disabled(studio: Session):
    panel = TracksPanel(studio)
    assert panel.model.rowCount() == 0
    assert panel.selected_track() is None
    assert not panel.remove_button.isEnabled()


def test_type_chooser_offers_every_registered_track(qapp):
    dialog = TrackTypeDialog()
    offered = {dialog.list.item(i).data(Qt.ItemDataRole.UserRole)
               for i in range(dialog.list.count())}
    assert offered == {k.type_id for k in track_types()}
    assert dialog.selected_type_id() is not None


def test_adding_a_track_selects_it_and_builds_its_options(studio: Session):
    panel = TracksPanel(studio)
    track = panel.add_track_of_type("color-strip")
    assert track is not None
    assert studio.document.tracks == [track]
    assert panel.selected_track() is track
    assert set(panel._editors) >= {"thickness", "opacity", "merge_runs"}


def test_adding_an_unknown_type_is_reported_not_raised(studio: Session):
    panel = TracksPanel(studio)
    messages: list[str] = []
    studio.statusMessage.connect(lambda text, _ms: messages.append(text))
    assert panel.add_track_of_type("no-such-track") is None
    assert messages
    assert studio.document.tracks == []


def test_option_widgets_are_inferred_from_the_default_value(studio: Session):
    panel = TracksPanel(studio)
    panel.add_track_of_type("heatmap")
    assert isinstance(_editor(panel, "use_mid"), QCheckBox)
    assert isinstance(_editor(panel, "cell_size"), QDoubleSpinBox)
    assert isinstance(_editor(panel, "ramp_steps"), QSpinBox)
    assert isinstance(_editor(panel, "color_min"), ColorButton)
    assert isinstance(_editor(panel, "missing_color"), ColorButton)
    assert isinstance(_editor(panel, "value_format"), QLineEdit)
    assert isinstance(_editor(panel, "label_rotation"), QDoubleSpinBox)


def test_a_column_index_option_is_not_mistaken_for_a_colour(studio: Session):
    panel = TracksPanel(studio)
    panel.add_track_of_type("symbols")
    assert isinstance(_editor(panel, "color_column"), QLineEdit)
    assert isinstance(_editor(panel, "color"), ColorButton)


def test_a_structured_option_is_shown_read_only(studio: Session):
    panel = TracksPanel(studio)
    panel.add_track_of_type("color-strip")
    widget = _editor(panel, "colors")
    assert isinstance(widget, QLabel)
    assert not widget.isEnabled()


def test_editing_an_option_updates_the_track_and_invalidates_layout(
        studio: Session):
    panel = TracksPanel(studio)
    track = panel.add_track_of_type("color-strip")
    studio.recompose()
    assert studio.dirty is Dirty.NOTHING

    _editor(panel, "thickness").setValue(48.0)
    assert track.options["thickness"] == 48.0
    assert studio.dirty is Dirty.LAYOUT

    _editor(panel, "merge_runs").setChecked(False)
    assert track.options["merge_runs"] is False

    colour = _editor(panel, "missing_color")
    from makeyourtree.style.color import Color

    colour.set_color(Color(10, 20, 30), notify=True)
    assert track.options["missing_color"] == "#0a141e"
    assert studio.stack.history() == []


def test_a_blank_text_option_becomes_none(studio: Session):
    panel = TracksPanel(studio)
    track = panel.add_track_of_type("text-labels")
    editor = _editor(panel, "max_width")
    editor.setText("120")
    editor.editingFinished.emit()
    assert track.options["max_width"] == 120
    editor.setText("")
    editor.editingFinished.emit()
    assert track.options["max_width"] is None


def test_editing_the_title_renames_the_row(studio: Session):
    panel = TracksPanel(studio)
    track = panel.add_track_of_type("color-strip")
    editor = panel._editors["__title__"]
    editor.setText("Biome")
    editor.editingFinished.emit()
    assert track.title == "Biome"
    assert panel.model.data(panel.model.index(0, 0)) == "Biome"


def test_hiding_and_showing_goes_through_the_session(studio: Session):
    panel = TracksPanel(studio)
    track = panel.add_track_of_type("color-strip")
    panel.toggle_selected_visible()
    assert track.visible is False
    assert panel.visible_button.text() == "Show"
    panel.toggle_selected_visible()
    assert track.visible is True
    assert panel.visible_button.text() == "Hide"


def test_moving_a_track_keeps_it_selected(studio: Session):
    panel = TracksPanel(studio)
    first = panel.add_track_of_type("color-strip")
    second = panel.add_track_of_type("heatmap")
    panel.select_track(second.id)
    panel.move_selected(-1)
    assert [t.id for t in studio.document.tracks] == [second.id, first.id]
    assert panel.selected_track() is second
    panel.move_selected(1)
    assert [t.id for t in studio.document.tracks] == [first.id, second.id]


def test_moving_past_the_end_does_nothing(studio: Session):
    panel = TracksPanel(studio)
    only = panel.add_track_of_type("color-strip")
    panel.move_selected(1)
    panel.move_selected(-1)
    assert [t.id for t in studio.document.tracks] == [only.id]


def test_removing_a_track_clears_the_options_form(studio: Session):
    panel = TracksPanel(studio)
    panel.add_track_of_type("color-strip")
    panel.remove_selected()
    assert studio.document.tracks == []
    assert panel.selected_track() is None
    assert "thickness" not in panel._editors


def test_panel_survives_document_replaced(studio: Session):
    panel = TracksPanel(studio)
    panel.add_track_of_type("color-strip")
    studio.set_document(Document(tree=sample_tree()))
    assert panel.model.rowCount() == 0
    assert panel.selected_track() is None
    panel.add_track_of_type("heatmap")
    assert panel.model.rowCount() == 1
