# SPDX-License-Identifier: MIT
"""Undoable operations.

Every user-facing tree edit returns a :class:`Command` rather than mutating in
place and forgetting how.  A command knows how to apply itself and how to undo
itself, which is what makes the studio's history dock possible and what lets
the test suite assert that a scripted session round-trips exactly.

Undo strategy
-------------
Commands capture the *minimum* state needed to reverse themselves -- a parent
id and a child index, not a copy of the tree.  Rerooting is the exception: it
rewrites the parent chain, so :class:`RerootCommand` snapshots the edge
lengths and parent links along the affected path.  A whole-tree snapshot is
the fallback of last resort and is marked as such, because on a 100 000-leaf
tree it costs real memory.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.tree import Tree

__all__ = ["Command", "FunctionCommand", "CompositeCommand", "CommandStack"]


class Command(abc.ABC):
    """One reversible edit."""

    label: str = "edit"
    """Human-readable, shown in the history dock and the undo menu item."""
    touches_topology: bool = True
    """False for pure style or ordering changes, which lets the canvas skip a
    full relayout of the along coordinate."""
    touches_order: bool = False
    """True when only the cross coordinate is affected (rotate, ladderize)."""

    @abc.abstractmethod
    def apply(self, tree: Tree) -> None: ...

    @abc.abstractmethod
    def undo(self, tree: Tree) -> None: ...

    def redo(self, tree: Tree) -> None:
        self.apply(tree)

    def merge_with(self, later: "Command") -> "Command | None":
        """Coalesce with a command issued immediately after this one, or return
        ``None`` to keep them separate.  Used so that dragging a slider does not
        create two hundred history entries."""
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.label!r}>"


@dataclass(slots=True)
class FunctionCommand(Command):
    """Adapter for edits that are easier to express as a pair of closures."""

    label: str = "edit"
    _do: Callable[[Tree], None] = lambda t: None
    _undo: Callable[[Tree], None] = lambda t: None
    touches_topology: bool = True
    touches_order: bool = False

    def apply(self, tree: Tree) -> None:
        self._do(tree)

    def undo(self, tree: Tree) -> None:
        self._undo(tree)


@dataclass(slots=True)
class CompositeCommand(Command):
    """Several commands that undo and redo as a unit."""

    label: str = "edit"
    commands: list[Command] = field(default_factory=list)
    touches_topology: bool = True
    touches_order: bool = False

    def apply(self, tree: Tree) -> None:
        for c in self.commands:
            c.apply(tree)

    def undo(self, tree: Tree) -> None:
        for c in reversed(self.commands):
            c.undo(tree)


class CommandStack:
    """Linear undo history with a coalescing window and a dirty flag."""

    __slots__ = ("_tree", "_done", "_undone", "_limit", "_clean_at", "listeners")

    def __init__(self, tree: Tree, limit: int = 500) -> None:
        self._tree = tree
        self._done: list[Command] = []
        self._undone: list[Command] = []
        self._limit = limit
        self._clean_at = 0
        self.listeners: list[Callable[[str], None]] = []

    def do(self, command: Command, *, coalesce: bool = False) -> Command:
        """Apply *command* and push it.  Clears the redo branch."""
        command.apply(self._tree)
        self._tree.touch()
        if coalesce and self._done:
            merged = self._done[-1].merge_with(command)
            if merged is not None:
                self._done[-1] = merged
                self._undone.clear()
                self._notify("do")
                return merged
        self._done.append(command)
        self._undone.clear()
        if len(self._done) > self._limit:
            drop = len(self._done) - self._limit
            del self._done[:drop]
            self._clean_at = max(0, self._clean_at - drop)
        self._notify("do")
        return command

    def undo(self) -> Command | None:
        if not self._done:
            return None
        c = self._done.pop()
        c.undo(self._tree)
        self._tree.touch()
        self._undone.append(c)
        self._notify("undo")
        return c

    def redo(self) -> Command | None:
        if not self._undone:
            return None
        c = self._undone.pop()
        c.redo(self._tree)
        self._tree.touch()
        self._done.append(c)
        self._notify("redo")
        return c

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    @property
    def undo_label(self) -> str | None:
        return self._done[-1].label if self._done else None

    @property
    def redo_label(self) -> str | None:
        return self._undone[-1].label if self._undone else None

    @property
    def is_dirty(self) -> bool:
        return len(self._done) != self._clean_at

    def mark_clean(self) -> None:
        self._clean_at = len(self._done)

    def clear(self) -> None:
        self._done.clear()
        self._undone.clear()
        self._clean_at = 0
        self._notify("clear")

    def history(self) -> list[str]:
        return [c.label for c in self._done]

    def _notify(self, what: str) -> None:
        for fn in self.listeners:
            fn(what)
