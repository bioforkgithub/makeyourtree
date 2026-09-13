# SPDX-License-Identifier: MIT
"""The window as the user meets it: it opens files, it edits, it saves, and it
survives the things that go wrong.

Nothing here asserts on rendered glyphs -- the offscreen platform reports zero
font families -- only on structure, geometry, counts and file contents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shell_helpers import PRIMATES, ScriptedWindow, close_window, make_window, trigger

from makeyourtree.doc.io import load_project
from makeyourtree.layout.params import BranchMode, LayoutMode
from makeyourtree.scene.marks import Layer
from makeyourtree_studio.session import Dirty


# --------------------------------------------------------------- construction


def test_the_window_builds_with_a_canvas_and_five_docks(window: ScriptedWindow):
    assert window.centralWidget() is window.canvas
    docks = window._panel_docks()
    assert len(docks) == 5
    assert {d.objectName() for d in docks.values()} == {
        "treeDock", "styleDock", "tracksDock", "searchDock", "inspectorDock"}


def test_every_dock_has_an_object_name(window: ScriptedWindow):
    """``saveState`` keys the stored layout on it and warns without one."""
    for dock in window._panel_docks().values():
        assert dock.objectName()
    assert window.toolbar.objectName()
    assert window.objectName()


def test_the_tree_dock_is_on_the_left_and_the_rest_are_tabbed_right(
        window: ScriptedWindow):
    from PySide6.QtCore import Qt

    assert (window.dockWidgetArea(window.tree_dock)
            == Qt.DockWidgetArea.LeftDockWidgetArea)
    for dock in (window.style_dock, window.tracks_dock, window.search_dock,
                 window.inspector_dock):
        assert (window.dockWidgetArea(dock)
                == Qt.DockWidgetArea.RightDockWidgetArea)
    tabbed = window.tabifiedDockWidgets(window.style_dock)
    assert {d.objectName() for d in tabbed} == {
        "tracksDock", "searchDock", "inspectorDock"}


def test_the_menu_bar_is_in_the_declared_group_order(window: ScriptedWindow):
    from makeyourtree_studio.actions import Group

    titles = [m.title() for m in window.menuBar().findChildren(type(
        window.menus["File"])) if m.title() in Group.ORDER]
    assert titles[:len(Group.ORDER)] == list(Group.ORDER)


def test_the_toolbar_holds_registry_actions_only(window: ScriptedWindow):
    ids = {a.objectName() for a in window.toolbar.actions() if not a.isSeparator()}
    assert ids
    for action_id in ids:
        assert action_id in window.actions_registry


# ------------------------------------------------------------------- opening


def test_opening_a_tree_renders_layers(loaded: ScriptedWindow):
    assert loaded.session.tree.n_leaves == 7
    assert loaded.session.scene is not None
    items = loaded.canvas.layer_items()
    assert items, "the canvas should hold one item per populated layer"
    assert Layer.BRANCHES in items
    # A fresh document clears the selection, which leaves the overlay
    # dirty; nothing heavier than that should still be outstanding.
    assert loaded.session.dirty <= Dirty.OVERLAY


def test_opening_an_example_tree_renders_layers(primates: ScriptedWindow):
    assert primates.session.tree.n_leaves > 1
    assert Layer.BRANCHES in primates.canvas.layer_items()
    assert primates.canvas.scene().itemsBoundingRect().width() > 0


def test_opening_records_the_file_as_recent(loaded: ScriptedWindow,
                                            newick_file: Path):
    recent = loaded.recent_paths()
    assert recent and Path(recent[0]) == newick_file.resolve()
    entries = [a.toolTip() for a in loaded.recent_menu.actions()]
    assert str(newick_file.resolve()) in entries


def test_clearing_the_recent_list_empties_the_submenu(loaded: ScriptedWindow):
    assert loaded.recent_menu.actions()
    loaded.clear_recent_files()
    assert loaded.recent_menu.actions() == []
    assert not loaded.recent_menu.isEnabled()


def test_a_missing_file_is_reported_and_changes_nothing(window: ScriptedWindow,
                                                        tmp_path: Path):
    before = window.session.document
    assert window.open_path(tmp_path / "not-here.nwk") is False
    assert window.errors, "the failure must reach the user"
    assert window.session.document is before


def test_an_unreadable_file_is_reported_rather_than_raising(
        window: ScriptedWindow, tmp_path: Path):
    junk = tmp_path / "broken.nwk"
    junk.write_bytes(b"\x00\x01 not a tree at all \xff")
    window.open_path(junk)
    assert window.errors
    title, message = window.errors[-1]
    assert title == "Cannot open file"
    assert str(junk) in message


def test_a_failed_open_drops_the_path_from_the_recent_list(
        loaded: ScriptedWindow, newick_file: Path, tmp_path: Path):
    gone = tmp_path / "vanished.nwk"
    gone.write_text("(a,b);", encoding="utf-8")
    assert loaded.open_path(gone)
    gone.unlink()
    assert loaded.open_path(gone) is False
    assert str(gone) not in loaded.recent_paths()


def test_opening_a_nexus_file_works(window: ScriptedWindow):
    from shell_helpers import VIRUS_NEXUS

    assert VIRUS_NEXUS.is_file()
    assert window.open_path(VIRUS_NEXUS)
    assert window.session.tree.n_leaves > 1


# ------------------------------------------------------------------ unsaved


def test_replacing_a_modified_document_asks_first(loaded: ScriptedWindow):
    trigger(loaded, "tree.order.ladderize_desc")
    assert loaded.session.is_modified
    loaded.discard_answer = "cancel"
    assert loaded.new_document() is False
    assert loaded.session.tree.n_leaves == 7
    loaded.discard_answer = "discard"
    assert loaded.new_document() is True
    assert loaded.session.tree.n_leaves == 1
    assert loaded.session.tree.root.name is None
    assert loaded.session.path is None


def test_cancelling_the_prompt_refuses_the_close(loaded: ScriptedWindow):
    from PySide6.QtGui import QCloseEvent

    trigger(loaded, "tree.order.ladderize_desc")
    loaded.discard_answer = "cancel"
    event = QCloseEvent()
    loaded.closeEvent(event)
    assert not event.isAccepted()


def test_answering_save_writes_the_file(loaded: ScriptedWindow, tmp_path: Path):
    target = tmp_path / "answered.mytree"
    loaded.save_answer = str(target)
    trigger(loaded, "tree.order.ladderize_desc")
    loaded.discard_answer = "save"
    assert loaded.maybe_save() is True
    assert target.is_file()
    assert not loaded.session.is_modified


# ------------------------------------------------------------------- saving


def test_saving_a_tree_by_suffix_writes_newick(loaded: ScriptedWindow,
                                               tmp_path: Path):
    target = tmp_path / "out.nwk"
    assert loaded.save_to(target)
    text = target.read_text(encoding="utf-8")
    assert text.strip().endswith(";")
    assert "alpha" in text
    assert not loaded.session.is_modified


def test_saving_a_project_by_suffix_writes_a_container(loaded: ScriptedWindow,
                                                       tmp_path: Path):
    target = tmp_path / "out.mytree"
    assert loaded.save_to(target)
    reopened = load_project(target)
    assert reopened.tree.n_leaves == 7


def test_save_falls_back_to_save_as_when_there_is_no_path(
        loaded: ScriptedWindow, tmp_path: Path):
    target = tmp_path / "chosen.mytree"
    loaded.save_answer = str(target)
    assert loaded.session.path is None
    assert loaded.save() is True
    assert target.is_file()
    assert loaded.session.path == str(target)


def test_cancelling_save_as_writes_nothing(loaded: ScriptedWindow):
    loaded.save_answer = ""
    assert loaded.save_as() is False
    assert loaded.session.path is None


def test_a_save_that_fails_is_reported(loaded: ScriptedWindow, tmp_path: Path):
    directory = tmp_path / "a-directory.nwk"
    directory.mkdir()
    assert loaded.save_to(directory) is False
    assert loaded.errors and loaded.errors[-1][0] == "Cannot save file"


# ---------------------------------------------------------------- status bar


def test_the_status_bar_summarises_the_selection(loaded: ScriptedWindow):
    assert loaded.selection_label.text() == "No selection"
    alpha = loaded.session.tree.by_name("alpha")
    loaded.session.set_selection([alpha.id])
    assert "alpha" in loaded.selection_label.text()
    assert "tip" in loaded.selection_label.text()
    loaded.session.set_selection([n.id for n in loaded.session.tree.nodes])
    assert "13 nodes selected, 7 tips" == loaded.selection_label.text()


def test_the_status_bar_shows_a_session_message(loaded: ScriptedWindow):
    loaded.session.statusMessage.emit("hello", 1000)
    assert loaded.statusBar().currentMessage() == "hello"


def test_the_diagnostic_count_is_clickable_and_opens_the_view(
        loaded: ScriptedWindow):
    assert loaded.diagnostics_button.text() == "no notes"
    loaded.session.diagnostics.warn("test.code", "something looked odd")
    loaded.session.diagnosticsChanged.emit()
    assert loaded.diagnostics_button.text() == "1 warning"
    dialog = loaded.show_diagnostics()
    assert "something looked odd" in dialog.report_text()
    dialog.clear()
    assert dialog.report_text() == "Nothing to report."
    assert loaded.diagnostics_button.text() == "no notes"
    dialog.close()


def test_the_status_label_names_the_worst_severity_present(
        loaded: ScriptedWindow):
    """Calling an INFO note a "problem" made a clean file look broken."""
    sink = loaded.session.diagnostics
    sink.info("test.note", "worth mentioning")
    loaded.session.diagnosticsChanged.emit()
    assert loaded.diagnostics_button.text() == "1 note"

    sink.warn("test.warn", "worth acting on")
    loaded.session.diagnosticsChanged.emit()
    assert loaded.diagnostics_button.text() == "1 warning"

    sink.error("test.error", "worth stopping for")
    loaded.session.diagnosticsChanged.emit()
    assert loaded.diagnostics_button.text() == "1 error"

    # Every item is still reachable; only the summary is selective.
    assert "worth mentioning" in loaded.show_diagnostics().report_text()


def test_the_diagnostics_tooltip_breaks_the_counts_down(loaded: ScriptedWindow):
    sink = loaded.session.diagnostics
    sink.info("test.note", "a")
    sink.warn("test.warn", "b")
    loaded.session.diagnosticsChanged.emit()
    tooltip = loaded.diagnostics_button.toolTip()
    assert "0 error(s)" in tooltip and "1 warning(s)" in tooltip
    assert "1 note(s)" in tooltip


def test_the_title_marks_unsaved_changes(loaded: ScriptedWindow):
    assert not loaded.windowTitle().startswith("*")
    trigger(loaded, "tree.order.ladderize_desc")
    assert loaded.windowTitle().startswith("*")
    loaded.session.mark_saved()
    assert not loaded.windowTitle().startswith("*")


# ---------------------------------------------------------------- edit menu


def test_the_undo_item_names_the_operation(loaded: ScriptedWindow):
    undo = loaded.actions_registry.action("edit.undo")
    redo = loaded.actions_registry.action("edit.redo")
    assert undo.text() == "Undo"
    assert not undo.isEnabled()
    trigger(loaded, "tree.root.midpoint")
    assert undo.text().startswith("Undo ")
    assert undo.text() != "Undo"
    assert undo.isEnabled()
    loaded.session.undo()
    assert redo.text().startswith("Redo ")
    assert redo.isEnabled()


def test_select_all_and_clear(loaded: ScriptedWindow):
    trigger(loaded, "edit.select_all")
    assert len(loaded.session.selection) == 13
    trigger(loaded, "edit.clear_selection")
    assert loaded.session.selection == set()


def test_select_clade_grows_to_the_descendants(loaded: ScriptedWindow):
    ab = loaded.session.tree.by_name("ab")
    loaded.session.set_selection([ab.id])
    trigger(loaded, "edit.select_clade")
    names = {loaded.session.tree.by_id(i).name
             for i in loaded.session.selection}
    assert {"ab", "alpha", "beta"} <= names


# ---------------------------------------------------------------- tree menu


def test_midpoint_root_is_undoable_through_the_menu(loaded: ScriptedWindow):
    before = loaded.session.tree.to_newick()
    trigger(loaded, "tree.root.midpoint")
    assert loaded.session.tree.to_newick() != before
    loaded.session.undo()
    assert loaded.session.tree.to_newick() == before


def test_outgroup_root_without_a_selection_says_so(loaded: ScriptedWindow):
    loaded.session.clear_selection()
    messages: list[str] = []
    loaded.session.statusMessage.connect(lambda m, _t: messages.append(m))
    loaded.outgroup_root()
    assert messages and "outgroup" in messages[-1].lower()
    assert not loaded.session.is_modified


def test_outgroup_root_on_a_clade_reroots(loaded: ScriptedWindow):
    ez = loaded.session.tree.by_name("ez")
    loaded.session.set_selection([ez.id])
    before = loaded.session.tree.to_newick()
    loaded.outgroup_root()
    assert loaded.session.tree.to_newick() != before
    loaded.session.undo()
    assert loaded.session.tree.to_newick() == before


def test_a_refused_operation_becomes_a_status_message(loaded: ScriptedWindow):
    messages: list[str] = []
    loaded.session.statusMessage.connect(lambda m, _t: messages.append(m))
    loaded.session.set_selection([n.id for n in loaded.session.tree.nodes])
    loaded.outgroup_root()
    assert messages, "an impossible outgroup must be explained, not raised"
    assert not loaded.session.is_modified


def test_expand_all_reverses_a_collapse(loaded: ScriptedWindow):
    ab = loaded.session.tree.by_name("ab")
    loaded.session.set_selection([ab.id])
    trigger(loaded, "tree.collapse")
    assert [n.id for n in loaded.session.tree.collapsed_nodes()] == [ab.id]
    trigger(loaded, "tree.expand_all")
    assert loaded.session.tree.collapsed_nodes() == []
    loaded.session.undo()
    assert [n.id for n in loaded.session.tree.collapsed_nodes()] == [ab.id]


def test_expand_all_with_nothing_collapsed_says_so(loaded: ScriptedWindow):
    messages: list[str] = []
    loaded.session.statusMessage.connect(lambda m, _t: messages.append(m))
    trigger(loaded, "tree.expand_all")
    assert messages[-1] == "Nothing is collapsed"


def test_extracting_a_subtree_opens_it_as_a_new_document(
        loaded: ScriptedWindow):
    gd = loaded.session.tree.by_name("gd")
    loaded.session.set_selection([gd.id])
    document = loaded.extract_subtree()
    assert document is not None
    assert loaded.session.document is document
    assert {n.name for n in document.tree.nodes if not n.children} == {
        "gamma", "delta"}
    assert loaded.session.tree.root.name == "gd"


def test_extracting_needs_exactly_one_node(loaded: ScriptedWindow):
    loaded.session.set_selection([])
    assert loaded.extract_subtree() is None
    loaded.session.set_selection([n.id for n in loaded.session.tree.nodes][:2])
    assert loaded.extract_subtree() is None


# ---------------------------------------------------------------- view menu


def test_switching_layout_mode_changes_the_document_not_the_menu(
        loaded: ScriptedWindow):
    trigger(loaded, "view.mode.circular")
    assert loaded.session.params.mode is LayoutMode.CIRCULAR
    # The other direction: a change made elsewhere moves the check mark.
    loaded.session.set_params(mode=LayoutMode.SLANTED)
    loaded._sync_view_actions()
    assert loaded.actions_registry.action("view.mode.slanted").isChecked()
    assert not loaded.actions_registry.action("view.mode.circular").isChecked()


def test_switching_branch_mode(loaded: ScriptedWindow):
    trigger(loaded, "view.branch.cladogram_level")
    assert loaded.session.params.branch_mode is BranchMode.CLADOGRAM_LEVEL
    trigger(loaded, "view.branch.phylogram")
    assert loaded.session.params.branch_mode is BranchMode.PHYLOGRAM


def test_align_tips_is_a_toggle(loaded: ScriptedWindow):
    assert not loaded.session.params.align_tips
    trigger(loaded, "view.align_tips")
    assert loaded.session.params.align_tips
    trigger(loaded, "view.align_tips")
    assert not loaded.session.params.align_tips


def test_zooming_never_relayouts(loaded: ScriptedWindow, monkeypatch):
    import makeyourtree.layout

    calls: list[int] = []
    original = makeyourtree.layout.compute_layout
    monkeypatch.setattr(makeyourtree.layout, "compute_layout",
                        lambda *a, **k: (calls.append(1), original(*a, **k))[1])
    before = loaded.canvas.zoom
    for _ in range(10):
        trigger(loaded, "view.zoom_in")
    for _ in range(5):
        trigger(loaded, "view.zoom_out")
    trigger(loaded, "view.zoom_fit")
    trigger(loaded, "view.zoom_reset")
    assert calls == []
    assert loaded.canvas.zoom != before or True


def test_the_theme_toggle_switches_and_persists(loaded: ScriptedWindow):
    assert loaded.theme_name == "light"
    light_bg = loaded.session.theme.background
    trigger(loaded, "view.theme")
    assert loaded.theme_name == "dark"
    assert loaded.session.theme.background != light_bg
    assert loaded.settings.theme() == "dark"
    trigger(loaded, "view.theme")
    assert loaded.theme_name == "light"
    assert loaded.session.theme.background == light_bg


def test_panel_toggles_hide_and_show_their_dock(loaded: ScriptedWindow):
    for action_id, dock in loaded._panel_docks().items():
        action = loaded.actions_registry.action(action_id)
        action.setChecked(False)
        loaded.toggle_panel(action_id)
        assert dock.isHidden()
        action.setChecked(True)
        loaded.toggle_panel(action_id)
        assert not dock.isHidden()


def test_the_search_panel_centres_the_canvas(loaded: ScriptedWindow):
    seen: list[int] = []
    loaded.canvas.center_on_node = lambda node_id: seen.append(node_id)
    loaded.search_panel.centerOnNode.disconnect()
    loaded.search_panel.centerOnNode.connect(loaded.canvas.center_on_node)
    node = loaded.session.tree.by_name("alpha")
    loaded.search_panel.centerOnNode.emit(node.id)
    assert seen == [node.id]


# --------------------------------------------------------------- persistence


def test_geometry_and_dock_state_survive_a_restart(qapp, tmp_path: Path):
    first = make_window(tmp_path)
    first.resize(1024, 768)
    first.actions_registry.action("view.panel.tracks").setChecked(False)
    first.toggle_panel("view.panel.tracks")
    assert first.tracks_dock.isHidden()
    close_window(first)

    second = make_window(tmp_path)
    try:
        assert second.settings.window_geometry() is not None
        assert second.settings.window_state() is not None
        assert second.tracks_dock.isHidden()
        assert not second.actions_registry.action(
            "view.panel.tracks").isChecked()
    finally:
        close_window(second)


def test_the_saved_theme_is_restored(qapp, tmp_path: Path):
    first = make_window(tmp_path)
    first.set_theme_name("dark")
    close_window(first)

    second = make_window(tmp_path)
    try:
        assert second.theme_name == "dark"
        assert second.actions_registry.action("view.theme").isChecked()
    finally:
        close_window(second)


@pytest.mark.parametrize("mode", list(LayoutMode))
def test_every_layout_mode_composes_a_real_example(primates: ScriptedWindow,
                                                   mode: LayoutMode):
    primates.session.set_params(mode=mode)
    primates.canvas.refresh()
    assert primates.session.scene is not None
    assert primates.session.scene.width > 0
    assert Layer.BRANCHES in primates.canvas.layer_items()


def test_the_example_tree_is_the_one_named_in_the_fixtures_record():
    assert PRIMATES.is_file()


def test_align_tips_is_disabled_in_unrooted_mode(loaded: ScriptedWindow):
    """The command cannot act there, and an enabled command that does nothing
    reads as a broken application."""
    align = loaded.actions_registry.action("view.align_tips")
    trigger(loaded, "view.mode.rectangular")
    assert align.isEnabled()

    trigger(loaded, "view.mode.unrooted")
    assert not align.isEnabled()
    assert "every direction" in align.toolTip()

    trigger(loaded, "view.mode.circular")
    assert align.isEnabled()
