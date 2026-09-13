# SPDX-License-Identifier: MIT
"""One registry for every command the application can perform.

Menus, toolbars, context menus, the command palette and the editable shortcut
table are all *views* of this registry. Declaring an action once and rendering it
four ways is what keeps them from drifting apart — and it makes the
"every action is reachable and uniquely bound" test a table scan rather than a
manual audit.

An :class:`ActionSpec` is pure data. Binding to a real ``QAction`` happens in
:class:`ActionRegistry.build`, once, at window construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

__all__ = ["ActionSpec", "ActionRegistry", "Group"]


class Group:
    """Menu groups. The order here is the order of the menu bar."""

    FILE = "File"
    EDIT = "Edit"
    TREE = "Tree"
    VIEW = "View"
    ANNOTATE = "Annotate"
    HELP = "Help"

    ORDER = (FILE, EDIT, TREE, VIEW, ANNOTATE, HELP)


@dataclass(slots=True)
class ActionSpec:
    """Declaration of one command."""

    id: str
    """Stable dotted identifier, e.g. ``tree.root.midpoint``. Never rename in place —
    user keybindings are stored against it."""
    text: str
    group: str = Group.FILE
    shortcut: str | None = None
    """Portable sequence string, e.g. ``"Ctrl+Shift+R"``. ``None`` for no default."""
    tip: str = ""
    """Status-bar and tooltip text. A short sentence saying what it does."""
    icon: str | None = None
    checkable: bool = False
    checked: bool = False
    separator_before: bool = False
    context_menu: bool = False
    """Also offered on the canvas context menu for the node under the cursor."""
    needs_selection: bool = False
    """Disabled unless at least one node is selected."""
    needs_document: bool = True
    handler: Callable[[], None] | None = None
    """Bound at build time; the spec itself stays serialisable without it."""

    def key_sequence(self) -> QKeySequence:
        return QKeySequence(self.shortcut) if self.shortcut else QKeySequence()


class ActionRegistry:
    """Holds the specs and the ``QAction`` objects built from them."""

    def __init__(self) -> None:
        self._specs: dict[str, ActionSpec] = {}
        self._actions: dict[str, QAction] = {}
        self._order: list[str] = []

    # ------------------------------------------------------------ declare

    def add(self, spec: ActionSpec) -> ActionSpec:
        if spec.id in self._specs:
            raise ValueError(f"duplicate action id {spec.id!r}")
        self._specs[spec.id] = spec
        self._order.append(spec.id)
        return spec

    def extend(self, specs: Iterable[ActionSpec]) -> None:
        for s in specs:
            self.add(s)

    def bind(self, action_id: str, handler: Callable[[], None]) -> None:
        """Attach the callable that performs the action."""
        self._specs[action_id].handler = handler
        act = self._actions.get(action_id)
        if act is not None:
            try:
                act.triggered.disconnect()
            except (RuntimeError, TypeError):
                pass
            act.triggered.connect(lambda _checked=False, h=handler: h())

    # -------------------------------------------------------------- build

    def build(self, parent: QWidget) -> None:
        """Create a ``QAction`` for every spec. Call once, after all specs exist."""
        for spec in self.specs():
            act = QAction(spec.text, parent)
            act.setObjectName(spec.id)
            if spec.shortcut:
                act.setShortcut(spec.key_sequence())
            if spec.tip:
                act.setToolTip(spec.tip)
                act.setStatusTip(spec.tip)
            act.setCheckable(spec.checkable)
            act.setChecked(spec.checked)
            if spec.handler is not None:
                act.triggered.connect(lambda _c=False, h=spec.handler: h())
            self._actions[spec.id] = act

    # -------------------------------------------------------------- query

    def specs(self) -> list[ActionSpec]:
        return [self._specs[i] for i in self._order]

    def spec(self, action_id: str) -> ActionSpec:
        return self._specs[action_id]

    def action(self, action_id: str) -> QAction:
        return self._actions[action_id]

    def actions(self) -> list[QAction]:
        return [self._actions[i] for i in self._order if i in self._actions]

    def in_group(self, group: str) -> list[ActionSpec]:
        return [s for s in self.specs() if s.group == group]

    def context_actions(self) -> list[QAction]:
        return [self._actions[s.id] for s in self.specs()
                if s.context_menu and s.id in self._actions]

    def set_shortcut(self, action_id: str, sequence: str | None) -> None:
        """Rebind a shortcut at runtime, from the preferences table."""
        self._specs[action_id].shortcut = sequence
        act = self._actions.get(action_id)
        if act is not None:
            act.setShortcut(QKeySequence(sequence) if sequence else QKeySequence())

    def update_enabled(self, *, has_document: bool, has_selection: bool) -> None:
        for spec in self.specs():
            act = self._actions.get(spec.id)
            if act is None:
                continue
            ok = True
            if spec.needs_document and not has_document:
                ok = False
            if spec.needs_selection and not has_selection:
                ok = False
            act.setEnabled(ok)

    def conflicts(self) -> dict[str, list[str]]:
        """Shortcut sequences bound to more than one action.

        The shortcut table and a test both consult this; a conflict is a bug,
        not a warning.
        """
        seen: dict[str, list[str]] = {}
        for spec in self.specs():
            if not spec.shortcut:
                continue
            seen.setdefault(QKeySequence(spec.shortcut).toString(), []).append(spec.id)
        return {k: v for k, v in seen.items() if len(v) > 1}

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, action_id: object) -> bool:
        return action_id in self._specs
