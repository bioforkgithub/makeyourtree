# SPDX-License-Identifier: MIT
"""The shortcut editor, and the one rule that makes it worth having.

Qt's response to two actions sharing a sequence is to fire neither and log
"ambiguous shortcut overload". A shortcut editor that permits a collision
therefore hands the user a key that has silently stopped working, so the
refusal is the feature under test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QKeySequence

from makeyourtree_studio.actions import ActionRegistry
from makeyourtree_studio.main_window import declare_actions
from makeyourtree_studio.settings import Settings
from makeyourtree_studio.shortcuts_dialog import ShortcutsDialog


@pytest.fixture
def registry() -> ActionRegistry:
    r = ActionRegistry()
    declare_actions(r)
    return r


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.for_file(tmp_path / "shortcuts.ini")


@pytest.fixture
def dialog(qapp, registry: ActionRegistry, settings: Settings):
    d = ShortcutsDialog(registry, settings,
                        {s.id: s.shortcut for s in registry.specs()})
    yield d
    d.close()


def test_the_table_lists_every_command(dialog, registry: ActionRegistry):
    assert len(dialog.rows()) == len(registry.specs())
    assert dialog.table.rowCount() == len(registry.specs())


def test_each_row_shows_its_current_binding(dialog, registry: ActionRegistry):
    editor = dialog.editor_for("view.zoom_fit")
    assert editor.keySequence() == QKeySequence("Ctrl+0")
    assert dialog.editor_for("tree.root.unroot").keySequence() == QKeySequence()


def test_a_free_sequence_is_accepted(dialog, registry: ActionRegistry):
    assert dialog.set_shortcut("tree.root.unroot", "Ctrl+Alt+U") is None
    assert registry.spec("tree.root.unroot").shortcut == "Ctrl+Alt+U"
    assert dialog.editor_for("tree.root.unroot").keySequence() == \
        QKeySequence("Ctrl+Alt+U")
    assert registry.conflicts() == {}


def test_a_conflicting_sequence_is_refused_and_names_the_other_command(
        dialog, registry: ActionRegistry):
    message = dialog.set_shortcut("tree.root.unroot", "Ctrl+S")
    assert message is not None
    assert "Save" in message
    assert registry.spec("tree.root.unroot").shortcut is None
    assert registry.spec("file.save").shortcut == "Ctrl+S"
    assert registry.conflicts() == {}
    assert dialog.message() == message
    assert dialog.editor_for("tree.root.unroot").keySequence() == QKeySequence()


def test_unbinding_is_allowed_and_several_unbound_are_not_a_conflict(
        dialog, registry: ActionRegistry):
    assert dialog.set_shortcut("file.save", "") is None
    assert dialog.set_shortcut("file.open", "") is None
    assert registry.spec("file.save").shortcut is None
    assert registry.spec("file.open").shortcut is None
    assert registry.conflicts() == {}


def test_rebinding_to_the_sequence_it_already_has_is_a_no_op(
        dialog, registry: ActionRegistry):
    assert dialog.set_shortcut("file.save", "Ctrl+S") is None
    assert registry.spec("file.save").shortcut == "Ctrl+S"


def test_swapping_two_bindings_works_when_one_is_freed_first(
        dialog, registry: ActionRegistry):
    assert dialog.set_shortcut("file.save", "") is None
    assert dialog.set_shortcut("file.open", "Ctrl+S") is None
    assert dialog.set_shortcut("file.save", "Ctrl+O") is None
    assert registry.conflicts() == {}


def test_accepting_persists_only_the_differences(dialog, registry, settings):
    dialog.set_shortcut("tree.root.unroot", "Ctrl+Alt+U")
    dialog.accept()
    stored = settings.load_shortcuts()
    assert stored == {"tree.root.unroot": "Ctrl+Alt+U"}


def test_cancelling_restores_the_bindings_the_dialog_opened_with(
        dialog, registry: ActionRegistry, settings: Settings):
    dialog.set_shortcut("tree.root.unroot", "Ctrl+Alt+U")
    dialog.set_shortcut("file.save", "")
    dialog.reject()
    assert registry.spec("tree.root.unroot").shortcut is None
    assert registry.spec("file.save").shortcut == "Ctrl+S"
    assert settings.load_shortcuts() == {}


def test_restore_defaults_puts_everything_back(dialog, registry: ActionRegistry):
    defaults = {s.id: s.shortcut for s in registry.specs()}
    dialog.set_shortcut("file.save", "")
    dialog.set_shortcut("file.open", "Ctrl+S")
    dialog.restore_defaults()
    assert {s.id: s.shortcut for s in registry.specs()} == defaults
    assert registry.conflicts() == {}


def test_filtering_narrows_the_visible_rows(dialog):
    visible = dialog.set_filter("zoom")
    assert visible
    assert all(i.startswith("view.zoom") for i in visible)
    assert len(visible) < len(dialog.rows())
    assert dialog.set_filter("") == [s.id for s in dialog.rows()]


def test_an_override_survives_a_restart(qapp, tmp_path: Path):
    from shell_helpers import close_window, make_window

    first = make_window(tmp_path)
    d = first.show_shortcuts()
    assert d.set_shortcut("tree.root.unroot", "Ctrl+Alt+U") is None
    d.accept()
    close_window(first)

    second = make_window(tmp_path)
    try:
        assert second.actions_registry.spec(
            "tree.root.unroot").shortcut == "Ctrl+Alt+U"
        assert second.actions_registry.action(
            "tree.root.unroot").shortcut() == QKeySequence("Ctrl+Alt+U")
        assert second.actions_registry.conflicts() == {}
        # The default table is still the in-code one, so a binding corrected in
        # a later release would still reach this user.
        assert second.default_shortcuts["tree.root.unroot"] is None
    finally:
        close_window(second)
