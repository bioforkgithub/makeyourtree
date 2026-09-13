# SPDX-License-Identifier: MIT
"""The editable keyboard map.

Two things make this more than a table widget.

*Conflicts are rejected, not resolved.* Qt's answer to two actions sharing a
sequence is to fire neither and log "ambiguous shortcut overload" -- a silent
failure the user experiences as a key that stopped working. So a binding that
would collide is refused at the moment it is typed, naming the command it
collides with, and the cell reverts.

*Only the differences are stored.* :meth:`~makeyourtree_studio.settings.Settings.collect_shortcuts`
writes the deltas from the in-code defaults. Storing the whole table would
freeze a user's bindings at the version they first ran, so a shortcut added or
corrected in a later release would never reach anyone who had opened this
dialog once.
"""

from __future__ import annotations

from typing import Any, Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QHeaderView, QKeySequenceEdit, QLabel,
                               QLineEdit, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .actions import ActionRegistry, ActionSpec

__all__ = ["ShortcutsDialog", "conflict_message"]

COL_COMMAND = 0
COL_GROUP = 1
COL_SHORTCUT = 2


def conflict_message(registry: ActionRegistry, action_id: str) -> str | None:
    """Describe the clash *action_id* is part of, or ``None`` if there is none.

    Asks the registry rather than re-deriving the answer, so the dialog and the
    test that asserts ``conflicts()`` is empty are looking at one definition of
    "conflict".
    """
    for sequence, ids in registry.conflicts().items():
        if action_id in ids:
            others = [registry.spec(i).text for i in ids if i != action_id]
            return (f"{sequence} is already used by "
                    f"{', '.join(others)}." if others
                    else f"{sequence} is bound more than once.")
    return None


class ShortcutsDialog(QDialog):
    """Every command and its key binding, editable in place."""

    def __init__(self, registry: ActionRegistry,
                 settings: Any | None = None,
                 defaults: Mapping[str, str | None] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setObjectName("shortcutsDialog")
        self.resize(720, 560)
        self._registry = registry
        self._settings = settings
        self._defaults: dict[str, str | None] = dict(
            defaults if defaults is not None
            else {s.id: s.shortcut for s in registry.specs()})
        self._specs: list[ActionSpec] = list(registry.specs())
        # The bindings as they were when the dialog opened, so Cancel really
        # cancels: edits are applied to the live registry as they are made
        # (that is what makes the conflict check meaningful), and without this
        # snapshot there would be nothing to roll back to.
        self._initial: dict[str, str | None] = {s.id: s.shortcut
                                                for s in self._specs}
        self._editors: dict[str, QKeySequenceEdit] = {}
        self._loading = False

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setObjectName("shortcutFilter")
        self.filter_edit.setPlaceholderText("Filter commands...")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.set_filter)

        self.table = QTableWidget(len(self._specs), 3, self)
        self.table.setObjectName("shortcutTable")
        self.table.setHorizontalHeaderLabels(["Command", "Group", "Shortcut"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_COMMAND, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_GROUP,
                                    QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_SHORTCUT,
                                    QHeaderView.ResizeMode.ResizeToContents)

        self.message_label = QLabel("", self)
        self.message_label.setObjectName("shortcutMessage")
        self.message_label.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        self.reset_button = buttons.addButton(
            "Restore Defaults", QDialogButtonBox.ButtonRole.ResetRole)
        self.reset_button.setObjectName("restoreDefaultsButton")
        self.reset_button.clicked.connect(self.restore_defaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.message_label)
        layout.addWidget(buttons)

        self._populate()

    # ---------------------------------------------------------------- table

    def _populate(self) -> None:
        self._loading = True
        for row, spec in enumerate(self._specs):
            command = QTableWidgetItem(spec.text)
            command.setData(Qt.ItemDataRole.UserRole, spec.id)
            command.setToolTip(spec.tip or spec.id)
            self.table.setItem(row, COL_COMMAND, command)
            self.table.setItem(row, COL_GROUP, QTableWidgetItem(spec.group))
            editor = QKeySequenceEdit(self.table)
            editor.setObjectName(f"shortcut.{spec.id}")
            editor.setKeySequence(QKeySequence(spec.shortcut or ""))
            # Only `editingFinished`: `keySequenceChanged` fires on every
            # keystroke of a multi-key sequence, so a user typing Ctrl+Shift+K
            # would have Ctrl+Shift rejected before they reached the K.
            editor.editingFinished.connect(
                lambda e=editor, i=spec.id: self._on_edited(i, e))
            self._editors[spec.id] = editor
            self.table.setCellWidget(row, COL_SHORTCUT, editor)
        self._loading = False

    def set_filter(self, text: str) -> list[str]:
        """Hide rows that do not match *text*; return the ids left visible."""
        needle = text.casefold().strip()
        visible: list[str] = []
        for row, spec in enumerate(self._specs):
            hay = f"{spec.group} {spec.text} {spec.id}".casefold()
            shown = not needle or needle in hay
            self.table.setRowHidden(row, not shown)
            if shown:
                visible.append(spec.id)
        return visible

    def rows(self) -> list[ActionSpec]:
        return list(self._specs)

    def editor_for(self, action_id: str) -> QKeySequenceEdit:
        return self._editors[action_id]

    def message(self) -> str:
        return self.message_label.text()

    # --------------------------------------------------------------- editing

    def _on_edited(self, action_id: str, editor: QKeySequenceEdit) -> None:
        if self._loading:
            return
        self.set_shortcut(action_id, editor.keySequence().toString())

    def set_shortcut(self, action_id: str, sequence: str | None) -> str | None:
        """Rebind *action_id*. Returns an error message, or ``None`` on success.

        An empty sequence is a legitimate value meaning "deliberately unbound",
        and several actions may be unbound at once without that counting as a
        conflict.
        """
        wanted = (sequence or "").strip()
        previous = self._registry.spec(action_id).shortcut
        if QKeySequence(wanted).toString() == QKeySequence(previous or "").toString():
            self.message_label.setText("")
            return None
        self._registry.set_shortcut(action_id, wanted or None)
        problem = conflict_message(self._registry, action_id)
        if problem is not None:
            self._registry.set_shortcut(action_id, previous)
            self._show_sequence(action_id, previous)
            self.message_label.setText(problem)
            return problem
        self._show_sequence(action_id, wanted or None)
        self.message_label.setText("")
        return None

    def _show_sequence(self, action_id: str, sequence: str | None) -> None:
        editor = self._editors.get(action_id)
        if editor is None:
            return
        was_loading = self._loading
        self._loading = True
        try:
            editor.setKeySequence(QKeySequence(sequence or ""))
        finally:
            self._loading = was_loading

    def restore_defaults(self) -> None:
        """Put every binding back to the value declared in code.

        All at once and in two passes, because restoring one at a time would
        trip the conflict check against a binding that is itself about to move.
        """
        self._loading = True
        try:
            for spec in self._specs:
                self._registry.set_shortcut(spec.id, None)
            for spec in self._specs:
                self._registry.set_shortcut(spec.id, self._defaults.get(spec.id))
                self._show_sequence(spec.id, self._defaults.get(spec.id))
        finally:
            self._loading = False
        self.message_label.setText("Defaults restored.")

    # ----------------------------------------------------------------- close

    def accept(self) -> None:
        """Persist the overrides, then close."""
        self.save()
        super().accept()

    def reject(self) -> None:
        """Roll the registry back to the bindings the dialog opened with."""
        self.revert()
        super().reject()

    def revert(self) -> None:
        self._loading = True
        try:
            for spec in self._specs:
                self._registry.set_shortcut(spec.id, None)
            for spec in self._specs:
                self._registry.set_shortcut(spec.id, self._initial.get(spec.id))
                self._show_sequence(spec.id, self._initial.get(spec.id))
        finally:
            self._loading = False

    def save(self) -> None:
        if self._settings is not None:
            self._settings.collect_shortcuts(self._registry, self._defaults)
