# SPDX-License-Identifier: MIT
"""Help > Third-Party Licences is a licence obligation, not a courtesy.

LGPL-3.0 §4(a) and §4(c) require the combined work to display the notices and
reproduce the licence texts. If this menu item is missing, or opens on an empty
pane, the right to distribute Qt with a proprietary product lapses -- so the
test asserts that the command exists, that it opens, and that what it opens is
not blank.
"""

from __future__ import annotations

from shell_helpers import trigger

from makeyourtree_studio.dialogs.about_dialog import DISCLAIMER, PRODUCT_NAME
from makeyourtree_studio.dialogs.licenses_dialog import LicensesDialog


def test_the_help_menu_offers_third_party_licences(window):
    spec = window.actions_registry.spec("help.licenses")
    assert spec.group == "Help"
    assert spec.text == "Third-Party Licences"
    names = {a.objectName() for a in window.menus["Help"].actions()}
    assert "help.licenses" in names


def test_the_licences_dialog_opens_and_shows_real_text(window):
    trigger(window, "help.licenses")
    dialogs = [d for d in window.open_dialogs() if isinstance(d, LicensesDialog)]
    assert len(dialogs) == 1
    dialog = dialogs[0]
    try:
        assert dialog.missing_documents() == [], (
            "every bundled licence text must be present in the checkout")
        names = dialog.component_names()
        assert names, "the component list must not be empty"
        for name in names:
            assert dialog.text_for(name).strip(), f"{name} has no licence text"
        assert dialog.isVisible()
    finally:
        dialog.close()


def test_the_licence_texts_are_the_real_ones(qapp):
    dialog = LicensesDialog()
    try:
        combined = "\n".join(dialog.text_for(n) for n in dialog.component_names())
        assert "GNU GENERAL PUBLIC LICENSE" in combined
        assert "GNU LESSER GENERAL PUBLIC LICENSE" in combined
        assert "MIT License" in combined
        assert "PySide6" in combined
    finally:
        dialog.close()


def test_the_about_dialog_states_the_exact_qt_version(window):
    """LGPL-3.0 §4(d)(1): a user cannot build a replacement Qt without it."""
    from PySide6.QtCore import qVersion

    trigger(window, "help.about")
    dialogs = [d for d in window.open_dialogs()
               if type(d).__name__ == "AboutDialog"]
    assert len(dialogs) == 1
    dialog = dialogs[0]
    try:
        summary = dialog.summary_text()
        assert f"Qt: {qVersion()}" in summary
        assert PRODUCT_NAME in summary
        assert DISCLAIMER in summary
    finally:
        dialog.close()


def test_the_shortcut_editor_opens_from_the_help_menu(window):
    from makeyourtree_studio.shortcuts_dialog import ShortcutsDialog

    trigger(window, "help.shortcuts")
    dialogs = [d for d in window.open_dialogs()
               if isinstance(d, ShortcutsDialog)]
    assert len(dialogs) == 1
    try:
        assert dialogs[0].rows()
    finally:
        dialogs[0].reject()


def test_closing_the_window_closes_the_dialogs_it_opened(window):
    trigger(window, "help.licenses")
    trigger(window, "help.diagnostics")
    assert len(window.open_dialogs()) == 2
    window.session.mark_saved()
    window.close()
    assert window.open_dialogs() == []
