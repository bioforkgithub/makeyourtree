# SPDX-License-Identifier: MIT
"""Application state and the signals that broadcast changes to it.

One :class:`Session` per open document. Everything in the UI reads state from
the session and writes it through the session's methods, so there is exactly one
path by which the document changes and exactly one set of signals announcing it.
Panels never talk to each other directly.

Recomposition is the expensive part, so it is staged. A style change does not
need a relayout; a rotation needs only the cross coordinate; a reroot needs
everything. :class:`Dirty` records how much became stale, and
:meth:`Session.invalidate` accumulates the worst level seen since the last
repaint rather than recomputing eagerly on every keystroke.
"""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QObject, Signal

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.node import Node
from makeyourtree.core.tree import Tree
from makeyourtree.doc.document import Document
from makeyourtree.layout.frame import LayoutFrame
from makeyourtree.layout.params import LayoutParams
from makeyourtree.ops.command import Command, CommandStack
from makeyourtree.scene.marks import Scene
from makeyourtree.style.theme import Theme
from makeyourtree.tracks.base import Track

__all__ = ["Dirty", "Session"]


class Dirty(enum.IntEnum):
    """How much of the render pipeline a change invalidated.

    Ordered so that ``max()`` over several changes gives the work actually needed.
    """

    NOTHING = 0
    OVERLAY = 1
    """Selection or hover only. Repaint the overlay layer; reuse the scene."""
    STYLE = 2
    """Colours, fonts, theme. Recompose marks; reuse the layout frame."""
    ORDER = 3
    """Child order changed (rotate, ladderize). Recompute the cross coordinate."""
    LAYOUT = 4
    """Geometry changed (mode, scale, collapse). Recompute the whole frame."""
    TOPOLOGY = 5
    """Tree structure changed (reroot, prune). Rebuild indexes, then everything."""


class Session(QObject):
    """The open document, its undo history, and the derived render state."""

    # ---- change notifications ----------------------------------------
    documentReplaced = Signal()
    """A different document was loaded. Every view must rebuild from scratch."""
    dirtied = Signal(int)
    """Something changed; the argument is a :class:`Dirty` level."""
    recomposed = Signal()
    """A new frame and scene are available on the session."""
    selectionChanged = Signal()
    historyChanged = Signal()
    diagnosticsChanged = Signal()
    tracksChanged = Signal()
    modifiedChanged = Signal(bool)
    statusMessage = Signal(str, int)
    """Human-readable message and a timeout in milliseconds."""

    def __init__(self, document: Document | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._doc = document if document is not None else Document(tree=Tree())
        self._stack = CommandStack(self._doc.tree)
        self._stack.listeners.append(lambda _what: self.historyChanged.emit())
        self._frame: LayoutFrame | None = None
        self._scene: Scene | None = None
        self._dirty = Dirty.TOPOLOGY
        self._selection: set[int] = set()
        self._hover: int | None = None
        self._search_hits: list[int] = []
        self.diagnostics = DiagnosticSink()
        self.metrics = None
        """Injected at startup with the Qt-backed :class:`TextMetrics`."""

    # ------------------------------------------------------------ document

    @property
    def document(self) -> Document:
        return self._doc

    @property
    def tree(self) -> Tree:
        return self._doc.tree

    @property
    def params(self) -> LayoutParams:
        return self._doc.params

    @property
    def theme(self) -> Theme:
        return self._doc.theme

    @property
    def stack(self) -> CommandStack:
        return self._stack

    @property
    def path(self) -> str | None:
        return self._doc.path

    @property
    def is_modified(self) -> bool:
        return self._stack.is_dirty

    def set_document(self, document: Document) -> None:
        """Replace the open document wholesale (file open, project load)."""
        self._doc = document
        self._stack = CommandStack(document.tree)
        self._stack.listeners.append(lambda _what: self.historyChanged.emit())
        self._frame = None
        self._scene = None
        self._selection.clear()
        self._hover = None
        self._search_hits.clear()
        self._dirty = Dirty.TOPOLOGY
        self.documentReplaced.emit()
        self.selectionChanged.emit()
        self.tracksChanged.emit()
        self.historyChanged.emit()
        self.modifiedChanged.emit(False)

    def mark_saved(self, path: str | Path | None = None) -> None:
        if path is not None:
            self._doc.path = str(path)
        self._stack.mark_clean()
        self.modifiedChanged.emit(False)
        self.historyChanged.emit()

    # ---------------------------------------------------------- mutations

    def do(self, command: Command, *, coalesce: bool = False) -> Command:
        """Apply an undoable operation and invalidate the right amount.

        The single entry point for every tree edit in the UI. Nothing calls
        ``command.apply`` directly, so undo can never miss an edit.
        """
        was_modified = self.is_modified
        self._stack.do(command, coalesce=coalesce)
        if command.touches_topology:
            self.invalidate(Dirty.TOPOLOGY)
        elif command.touches_order:
            self.invalidate(Dirty.ORDER)
        else:
            self.invalidate(Dirty.STYLE)
        if self.is_modified != was_modified:
            self.modifiedChanged.emit(self.is_modified)
        return command

    def undo(self) -> None:
        if self._stack.undo() is not None:
            self.invalidate(Dirty.TOPOLOGY)
            self.modifiedChanged.emit(self.is_modified)

    def redo(self) -> None:
        if self._stack.redo() is not None:
            self.invalidate(Dirty.TOPOLOGY)
            self.modifiedChanged.emit(self.is_modified)

    def set_params(self, **kw: Any) -> None:
        """Update layout parameters and invalidate the layout."""
        for k, v in kw.items():
            setattr(self._doc.params, k, v)
        self.invalidate(Dirty.LAYOUT)

    def set_theme_attr(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self._doc.theme, k, v)
        self.invalidate(Dirty.STYLE)

    # ------------------------------------------------------------- tracks

    def add_track(self, track: Track, index: int | None = None) -> Track:
        self._doc.add_track(track, index)
        self.tracksChanged.emit()
        self.invalidate(Dirty.LAYOUT)
        return track

    def remove_track(self, track_id: str) -> None:
        if self._doc.remove_track(track_id) is not None:
            self.tracksChanged.emit()
            self.invalidate(Dirty.LAYOUT)

    def move_track(self, track_id: str, index: int) -> None:
        self._doc.move_track(track_id, index)
        self.tracksChanged.emit()
        self.invalidate(Dirty.LAYOUT)

    def set_track_visible(self, track_id: str, visible: bool) -> None:
        t = self._doc.track(track_id)
        if t is not None and t.visible != visible:
            t.visible = visible
            self.tracksChanged.emit()
            self.invalidate(Dirty.LAYOUT)

    # ---------------------------------------------------------- selection

    @property
    def selection(self) -> set[int]:
        """Selected node ids. Treat as read-only; mutate via the setters."""
        return self._selection

    def selected_nodes(self) -> list[Node]:
        out = [self.tree.by_id(i) for i in self._selection]
        return [n for n in out if n is not None]

    def set_selection(self, node_ids: Iterable[int]) -> None:
        new = set(node_ids)
        if new != self._selection:
            self._selection = new
            self.selectionChanged.emit()
            self.invalidate(Dirty.OVERLAY)

    def toggle_selection(self, node_id: int) -> None:
        self._selection.symmetric_difference_update({node_id})
        self.selectionChanged.emit()
        self.invalidate(Dirty.OVERLAY)

    def clear_selection(self) -> None:
        self.set_selection(())

    @property
    def hover(self) -> int | None:
        return self._hover

    def set_hover(self, node_id: int | None) -> None:
        if node_id != self._hover:
            self._hover = node_id
            self.invalidate(Dirty.OVERLAY)

    @property
    def search_hits(self) -> list[int]:
        return self._search_hits

    def set_search_hits(self, node_ids: Iterable[int]) -> None:
        self._search_hits = list(node_ids)
        self.invalidate(Dirty.OVERLAY)

    # -------------------------------------------------------- composition

    @property
    def frame(self) -> LayoutFrame | None:
        return self._frame

    @property
    def scene(self) -> Scene | None:
        return self._scene

    def invalidate(self, level: "Dirty") -> None:
        """Record that *level* of the pipeline went stale.

        Accumulates the worst level seen so a burst of changes costs one
        recomposition, not one per change.
        """
        if level > self._dirty:
            self._dirty = level
        self.dirtied.emit(int(self._dirty))

    @property
    def dirty(self) -> "Dirty":
        return self._dirty

    def recompose(self, *, force: bool = False, interactive: bool = True) -> Scene | None:
        """Rebuild the frame and scene if stale, then announce the result.

        Called from the canvas on a zero-timer after ``dirtied``, so a burst of
        changes coalesces into one recomposition.
        """
        from makeyourtree.layout import compute_layout
        from makeyourtree.scene import compose

        if not force and self._dirty <= Dirty.NOTHING and self._scene is not None:
            return self._scene
        if self._dirty >= Dirty.TOPOLOGY:
            self.tree.touch()
            self.tree.refresh()
        sink = DiagnosticSink()
        self._frame = compute_layout(self.tree, self._doc.params, self.metrics)
        self._scene = compose(self._doc, interactive=interactive, sink=sink)
        if len(sink):
            self.diagnostics.extend(sink)
            self.diagnosticsChanged.emit()
        self._dirty = Dirty.NOTHING
        self.recomposed.emit()
        return self._scene
