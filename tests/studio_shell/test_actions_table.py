# SPDX-License-Identifier: MIT
"""The action table is the contract between the menus, the toolbar, the context
menu, the palette and the shortcut editor.

Every assertion here guards something a user would experience as a broken
application rather than as a cosmetic flaw: a command with no menu home cannot
be found, a duplicated sequence makes Qt fire neither action, and an unbound
handler is a menu item that does nothing.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QKeySequence

from shell_helpers import trigger

from makeyourtree_studio.actions import ActionRegistry, Group
from makeyourtree_studio.main_window import (BRANCH_MODE_ACTIONS,
                                         LAYOUT_MODE_ACTIONS, TOOLBAR_IDS,
                                         declare_actions)

REQUIRED_SHORTCUTS = {
    "file.open": "Ctrl+O",
    "file.save": "Ctrl+S",
    "file.save_as": "Ctrl+Shift+S",
    "file.export": "Ctrl+E",
    "edit.undo": "Ctrl+Z",
    "edit.redo": "Ctrl+Shift+Z",
    "view.panel.search": "Ctrl+F",
    "view.zoom_fit": "Ctrl+0",
    "view.zoom_in": "Ctrl+=",
    "view.zoom_out": "Ctrl+-",
    "view.palette": "Ctrl+P",
    "tree.root.reroot": "R",
    "tree.root.midpoint": "M",
    "tree.order.ladderize_asc": "L",
    "tree.collapse": "C",
    "tree.prune": "Del",
    "edit.clear_selection": "Esc",
}
"""Every binding named in the studio specification, section 5."""


@pytest.fixture
def registry() -> ActionRegistry:
    r = ActionRegistry()
    declare_actions(r)
    return r


def test_every_spec_has_a_unique_id(registry: ActionRegistry):
    ids = [s.id for s in registry.specs()]
    assert len(ids) == len(set(ids))
    assert len(ids) > 40, "the declared table should cover the whole application"


def test_every_spec_has_text_a_tip_and_a_menu_home(registry: ActionRegistry):
    for spec in registry.specs():
        assert spec.text.strip(), f"{spec.id} has no label"
        assert spec.tip.strip(), f"{spec.id} has no status-bar text"
        assert spec.group in Group.ORDER, f"{spec.id} is in no menu"


def test_no_two_actions_share_a_key_sequence(registry: ActionRegistry):
    assert registry.conflicts() == {}


def test_the_specified_shortcuts_are_the_declared_ones(registry: ActionRegistry):
    for action_id, sequence in REQUIRED_SHORTCUTS.items():
        spec = registry.spec(action_id)
        assert QKeySequence(spec.shortcut) == QKeySequence(sequence), (
            f"{action_id} should be bound to {sequence}, not {spec.shortcut}")


def test_every_group_in_the_menu_bar_has_at_least_one_command(
        registry: ActionRegistry):
    for group in Group.ORDER:
        assert registry.in_group(group), f"the {group} menu would be empty"


def test_context_menu_commands_act_on_a_node(registry: ActionRegistry):
    """A context-menu entry that ignores the node under the cursor is a trap."""
    offered = [s for s in registry.specs() if s.context_menu]
    assert offered, "the canvas context menu would be empty"
    for spec in offered:
        assert spec.needs_selection, (
            f"{spec.id} is offered on a node but does not require one")


def test_the_toolbar_only_names_ids_that_exist(registry: ActionRegistry):
    for action_id in TOOLBAR_IDS:
        if action_id is not None:
            assert action_id in registry


def test_layout_and_branch_mode_actions_cover_every_enum_member(
        registry: ActionRegistry):
    from makeyourtree.layout.params import BranchMode, LayoutMode

    assert set(LAYOUT_MODE_ACTIONS.values()) == set(LayoutMode)
    assert set(BRANCH_MODE_ACTIONS.values()) == set(BranchMode)
    for action_id in list(LAYOUT_MODE_ACTIONS) + list(BRANCH_MODE_ACTIONS):
        assert registry.spec(action_id).checkable


# --------------------------------------------------------- the built window


def test_the_window_binds_a_handler_to_every_command(window):
    unbound = [s.id for s in window.actions_registry.specs()
               if s.handler is None]
    assert unbound == []


def test_the_built_registry_has_no_conflicts(window):
    assert window.actions_registry.conflicts() == {}


def test_every_command_appears_in_its_menu(window):
    """The menu bar is generated from the registry, so this is a scan.

    It is still worth asserting: a spec whose group is misspelt would silently
    land in no menu at all.
    """
    for group, menu in window.menus.items():
        names = {a.objectName() for a in menu.actions()}
        for spec in window.actions_registry.in_group(group):
            assert spec.id in names, f"{spec.id} is missing from the {group} menu"


def test_every_command_is_invocable(window, monkeypatch, tmp_path):
    """Call every handler once and require that none of them raises.

    Nothing is stubbed except the two genuinely destructive answers -- closing
    the window and choosing a file -- because the point is to exercise the real
    handlers against a real session.
    """
    monkeypatch.setattr(window, "close", lambda: None)
    window.open_answer = ""
    window.save_answer = ""
    window.session.set_selection([n.id for n in window.session.tree.nodes][:1])
    for spec in window.actions_registry.specs():
        assert spec.handler is not None
        spec.handler()
    for dialog in window.open_dialogs():
        dialog.close()


def test_every_command_is_invocable_with_a_document_open(loaded, monkeypatch):
    monkeypatch.setattr(loaded, "close", lambda: None)
    monkeypatch.setattr(loaded, "maybe_save", lambda: True)
    root = loaded.session.tree.root
    loaded.session.set_selection([root.children[0].id])
    for spec in loaded.actions_registry.specs():
        spec.handler()
    assert loaded.errors == []
    for dialog in loaded.open_dialogs():
        dialog.close()


def test_needs_selection_actions_are_disabled_without_one(loaded):
    loaded.session.clear_selection()
    for spec in loaded.actions_registry.specs():
        if spec.needs_selection:
            assert not loaded.actions_registry.action(spec.id).isEnabled()
    loaded.session.set_selection([loaded.session.tree.root.id])
    for spec in loaded.actions_registry.specs():
        if spec.needs_selection:
            assert loaded.actions_registry.action(spec.id).isEnabled()


def test_bare_key_shortcuts_are_confined_to_the_canvas(window):
    """A window-wide ``R`` would reroot the tree while a user types in a field."""
    from PySide6.QtCore import Qt

    scoped = 0
    for spec in window.actions_registry.specs():
        action = window.actions_registry.action(spec.id)
        if not spec.shortcut:
            continue
        lowered = spec.shortcut.lower()
        if any(m in lowered for m in ("ctrl", "alt", "meta")):
            assert (action.shortcutContext()
                    == Qt.ShortcutContext.WindowShortcut)
        else:
            assert (action.shortcutContext()
                    == Qt.ShortcutContext.WidgetWithChildrenShortcut)
            assert action in window.canvas.actions()
            scoped += 1
    assert scoped >= 8, "the single-key bindings from the spec should be scoped"


def test_layout_mode_actions_are_mutually_exclusive(loaded):
    for action_id in LAYOUT_MODE_ACTIONS:
        trigger(loaded, action_id)
        checked = [i for i in LAYOUT_MODE_ACTIONS
                   if loaded.actions_registry.action(i).isChecked()]
        assert checked == [action_id]
        assert loaded.session.params.mode is LAYOUT_MODE_ACTIONS[action_id]
