# SPDX-License-Identifier: MIT
"""Type-to-run access to every command in the registry.

A tree viewer accumulates dozens of commands and only a handful of them can
have a memorable shortcut. The palette is the escape valve: it makes the whole
:class:`~makeyourtree_studio.actions.ActionRegistry` reachable by typing part of a
name, and -- because it lists each match's group and shortcut -- it doubles as
the place a user *learns* the shortcut for something they have been finding
through the menus.

The matcher is a subsequence match, not a substring match. "sbr" should find
"Scale Bar" and "ldsc" should find "Ladderize Descending"; requiring a
contiguous substring would force the user to remember the exact wording, which
is the thing the palette exists to avoid.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QLabel, QLineEdit, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .actions import ActionRegistry, ActionSpec

__all__ = ["CommandPalette", "Match", "fuzzy_score", "rank_specs"]

_ROLE_ID = Qt.ItemDataRole.UserRole


class Match(NamedTuple):
    """One ranked candidate."""

    spec: ActionSpec
    score: float


def fuzzy_score(query: str, candidate: str) -> float | None:
    """Rank *candidate* against *query*, or ``None`` when it does not match.

    Higher is better. Three things earn points, in the order a user notices
    them: matching at the start of the string, matching at the start of a word,
    and matching in a run rather than scattered across the string. That ordering
    is what makes "ex" put "Export Figure..." above "Extract Subtree" only when
    "Export" is the earlier word, and what stops a long name winning merely
    because it contains more letters.
    """
    if not query:
        return 0.0
    q = query.casefold()
    c = candidate.casefold()
    score = 0.0
    # A contiguous hit outranks any scattered one. Without this, "fit" scores
    # higher against "File ... Tree" -- a genuine subsequence -- than against
    # "Fit to Window", and the palette answers a question nobody asked.
    literal = c.find(q)
    if literal >= 0:
        score += 25.0
        if literal == 0 or c[literal - 1] in " .-_/":
            score += 15.0
    pos = 0
    previous = -2
    for ch in q:
        found = c.find(ch, pos)
        if found < 0:
            return None
        if found == 0:
            score += 12.0
        elif c[found - 1] in " .-_/":
            score += 8.0
        if found == previous + 1:
            score += 6.0
        score -= found * 0.05
        previous = found
        pos = found + 1
    # Two candidates that match equally well are separated by brevity: the
    # shorter name is the more exact answer to the same query.
    return score - len(c) * 0.02


def rank_specs(specs: Iterable[ActionSpec], query: str) -> list[Match]:
    """Score every spec and return the matches, best first.

    The query is matched against ``"<group> <text>"`` and against the action id,
    so both "view circ" and "mode.circular" find the same command; the id path
    is how a user who read the shortcut file or a bug report gets there.
    """
    out: list[Match] = []
    for spec in specs:
        haystack = f"{spec.group} {spec.text}"
        best = fuzzy_score(query, haystack)
        by_id = fuzzy_score(query, spec.id)
        if by_id is not None:
            # An id match is a weaker signal than a name match: it is punctuated
            # machine text and matches almost anything if given equal weight.
            by_id -= 6.0
            best = by_id if best is None else max(best, by_id)
        if best is not None:
            out.append(Match(spec, best))
    out.sort(key=lambda m: (-m.score, m.spec.group, m.spec.text))
    return out


class CommandPalette(QDialog):
    """A fuzzy finder over the action registry."""

    def __init__(self, registry: ActionRegistry,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Commands")
        self.setObjectName("commandPalette")
        self.setModal(True)
        self.resize(640, 420)
        self._registry = registry
        self._matches: list[ActionSpec] = []

        self.query_edit = QLineEdit(self)
        self.query_edit.setObjectName("paletteQuery")
        self.query_edit.setPlaceholderText("Run a command...")
        self.query_edit.setClearButtonEnabled(True)

        self.list = QTreeWidget(self)
        self.list.setObjectName("paletteResults")
        self.list.setColumnCount(3)
        self.list.setHeaderLabels(["Command", "Group", "Shortcut"])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setAllColumnsShowFocus(True)
        self.list.header().setStretchLastSection(False)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("paletteStatus")

        layout = QVBoxLayout(self)
        layout.addWidget(self.query_edit)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.status_label)

        self.query_edit.textChanged.connect(self.set_filter)
        self.query_edit.returnPressed.connect(self.run_current)
        self.list.itemActivated.connect(lambda _i, _c: self.run_current())
        self.list.itemDoubleClicked.connect(lambda _i, _c: self.run_current())

        self.set_filter("")
        self.query_edit.setFocus()

    # -------------------------------------------------------------- filtering

    def set_filter(self, text: str) -> list[ActionSpec]:
        """Refill the list from *text* and return the matches, best first."""
        self._matches = [m.spec for m in rank_specs(self._registry.specs(), text)]
        self.list.clear()
        for spec in self._matches:
            item = QTreeWidgetItem([
                spec.text, spec.group,
                QKeySequence(spec.shortcut).toString() if spec.shortcut else "",
            ])
            item.setData(0, _ROLE_ID, spec.id)
            if spec.tip:
                item.setToolTip(0, spec.tip)
            enabled = self._is_enabled(spec.id)
            item.setDisabled(not enabled)
            self.list.addTopLevelItem(item)
        if self._matches:
            first = self._first_enabled_row()
            if first >= 0:
                self.list.setCurrentItem(self.list.topLevelItem(first))
        self.status_label.setText(
            "No matching command" if not self._matches
            else f"{len(self._matches)} command"
                 f"{'s' if len(self._matches) != 1 else ''}")
        return list(self._matches)

    def matches(self) -> list[ActionSpec]:
        """The specs currently listed, in display order."""
        return list(self._matches)

    def match_ids(self) -> list[str]:
        return [s.id for s in self._matches]

    def _is_enabled(self, action_id: str) -> bool:
        try:
            return self._registry.action(action_id).isEnabled()
        except KeyError:
            # The registry has not been built (no window); nothing is disabled.
            return True

    def _first_enabled_row(self) -> int:
        for row in range(self.list.topLevelItemCount()):
            if not self.list.topLevelItem(row).isDisabled():
                return row
        return 0 if self.list.topLevelItemCount() else -1

    # ------------------------------------------------------------ invocation

    def current_spec(self) -> ActionSpec | None:
        """The highlighted command, or the top hit when nothing is highlighted.

        A disabled row cannot become the current item in Qt, so without the
        fallback pressing Enter on a list whose only match is unavailable would
        do nothing at all and explain nothing.
        """
        item = self.list.currentItem() or self.list.topLevelItem(0)
        if item is None:
            return None
        return self._registry.spec(item.data(0, _ROLE_ID))

    def run_current(self) -> ActionSpec | None:
        """Close, then run the highlighted command.

        Closing first matters: a command that opens a dialog of its own would
        otherwise put it behind the palette, and one that changes the selection
        would leave a stale list on screen.
        """
        spec = self.current_spec()
        if spec is None:
            return None
        if not self._is_enabled(spec.id):
            self.status_label.setText(f"{spec.text} is not available right now")
            return None
        self.accept()
        self.trigger(spec)
        return spec

    def trigger(self, spec: ActionSpec) -> None:
        """Invoke *spec* through its ``QAction`` when there is one.

        Going through the action rather than straight to the handler keeps
        checkable commands honest: the action toggles its own state first, and
        the handler reads that state back.
        """
        try:
            action = self._registry.action(spec.id)
        except KeyError:
            action = None
        if action is not None:
            action.trigger()
        elif spec.handler is not None:
            spec.handler()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Send the arrow keys to the result list while the cursor stays typing."""
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown,
                   Qt.Key.Key_PageUp):
            self.list.keyPressEvent(event)
            event.accept()
            return
        super().keyPressEvent(event)
