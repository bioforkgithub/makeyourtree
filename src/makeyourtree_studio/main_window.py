# SPDX-License-Identifier: MIT
"""The application shell: one window, one session, one action registry.

Everything the user can *do* is declared once, as data, in
:func:`declare_actions`. The menu bar, the toolbar, the canvas context menu, the
command palette and the shortcut editor are then rendered from that one list.
The alternative -- a ``QAction`` created wherever it happened to be needed --
guarantees that the four views drift apart, and makes "is every command
reachable and uniquely bound?" a manual audit instead of a table scan.

The window owns no document state. It reads from
:class:`~makeyourtree_studio.session.Session` and writes back through session
methods, so an edit made from the menu, from a panel and from the context menu
take the identical path onto the undo stack.

Two seams exist purely so the shell is testable without a human: every modal
question (choose a file, discard changes, report an error) goes through a small
overridable method, and every dialog is shown with ``open()`` rather than
``exec()`` so nothing here can block an event loop that a test owns.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Callable, Iterable

from PySide6.QtCore import QByteArray, QPoint, Qt, Signal
from PySide6.QtGui import QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (QApplication, QDialog, QDockWidget, QFileDialog,
                               QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QToolBar, QVBoxLayout, QWidget)

from makeyourtree.core.errors import MakeYourTreeError
from makeyourtree.core.tree import Tree
from makeyourtree.doc.document import Document
from makeyourtree.doc.io import load_project, save_project
from makeyourtree.io import load_tree, save_tree
from makeyourtree.layout.params import BranchMode, LayoutMode
from makeyourtree.ops.edit import extract_subtree
from makeyourtree.ops.rooting import midpoint_root, outgroup_root, unroot
from makeyourtree.ops.select import select_clade
from makeyourtree.style.theme import DARK, LIGHT, Theme

from .actions import ActionRegistry, ActionSpec, Group
from .canvas.view import TreeCanvas
from .command_palette import CommandPalette
from .dialogs.about_dialog import PRODUCT_NAME, AboutDialog
from .dialogs.export_dialog import ExportDialog
from .dialogs.import_dialog import ImportDialog
from .dialogs.licenses_dialog import LicensesDialog
from .panels.inspector import InspectorPanel
from .panels.search_panel import SearchPanel
from .panels.style_panel import StylePanel
from .panels.tracks_panel import TracksPanel, TrackTypeDialog
from .panels.tree_panel import TreePanel
from .session import Session
from .settings import Settings
from .shortcuts_dialog import ShortcutsDialog

__all__ = ["MainWindow", "DiagnosticsDialog", "declare_actions",
           "apply_named_theme", "TREE_FILTER", "PROJECT_FILTER", "OPEN_FILTER",
           "LAYOUT_MODE_ACTIONS", "BRANCH_MODE_ACTIONS", "TOOLBAR_IDS"]

_STATUS_MS = 5000

TREE_FILTER = ("Tree files (*.nwk *.newick *.tre *.tree *.nex *.nexus *.xml "
               "*.phyloxml)")
PROJECT_FILTER = "MakeYourTree project (*.mytree *.mytree.json)"
OPEN_FILTER = ("All supported (*.nwk *.newick *.tre *.tree *.nex *.nexus "
               "*.xml *.phyloxml *.mytree *.mytree.json);;"
               f"{TREE_FILTER};;{PROJECT_FILTER};;All files (*)")

PROJECT_SUFFIXES = (".mytree", ".mytree.json")

#: File suffix to the writer name used by :func:`makeyourtree.io.save_tree`.
TREE_SUFFIX_FORMAT = {
    ".nwk": "newick", ".newick": "newick", ".tre": "newick", ".tree": "newick",
    ".nhx": "nhx", ".nex": "nexus", ".nexus": "nexus",
    ".xml": "phyloxml", ".phyloxml": "phyloxml",
}

LAYOUT_MODE_ACTIONS = {
    "view.mode.rectangular": LayoutMode.RECTANGULAR,
    "view.mode.slanted": LayoutMode.SLANTED,
    "view.mode.circular": LayoutMode.CIRCULAR,
    "view.mode.radial": LayoutMode.RADIAL,
    "view.mode.unrooted": LayoutMode.UNROOTED,
}

BRANCH_MODE_ACTIONS = {
    "view.branch.phylogram": BranchMode.PHYLOGRAM,
    "view.branch.cladogram_aligned": BranchMode.CLADOGRAM_ALIGNED,
    "view.branch.cladogram_level": BranchMode.CLADOGRAM_LEVEL,
}

#: Actions on the toolbar, in order; ``None`` is a separator. Every entry is an
#: id from the registry -- the toolbar is a view of the registry, never a second
#: place where commands are invented.
TOOLBAR_IDS: tuple[str | None, ...] = (
    "view.mode.rectangular", "view.mode.slanted", "view.mode.circular",
    "view.mode.radial", "view.mode.unrooted", None,
    "view.branch.phylogram", "view.branch.cladogram_aligned",
    "view.branch.cladogram_level", None,
    "view.align_tips", "tree.order.ladderize_asc", None,
    "view.zoom_out", "view.zoom_in", "view.zoom_fit",
)


def declare_actions(registry: ActionRegistry) -> None:
    """Populate *registry* with every command the application offers.

    A free function so a test -- or the shortcut editor's "restore defaults" --
    can build the complete table without constructing a window.
    """
    registry.extend([
        # ---------------------------------------------------------- file
        ActionSpec("file.new", "New", Group.FILE, "Ctrl+N",
                   "Start an empty document.", needs_document=False),
        ActionSpec("file.open", "Open Tree...", Group.FILE, "Ctrl+O",
                   "Open a tree file in any supported format.",
                   needs_document=False),
        ActionSpec("file.open_project", "Open Project...", Group.FILE,
                   "Ctrl+Shift+O", "Open a saved MakeYourTree project.",
                   needs_document=False),
        ActionSpec("file.open_recent", "Open Recent", Group.FILE, None,
                   "Files opened in this or an earlier session.",
                   needs_document=False),
        ActionSpec("file.recent.clear", "Clear Recent Files", Group.FILE, None,
                   "Forget the recent-file list.", needs_document=False),
        ActionSpec("file.save", "Save", Group.FILE, "Ctrl+S",
                   "Write the document back to the file it came from.",
                   separator_before=True),
        ActionSpec("file.save_as", "Save As...", Group.FILE, "Ctrl+Shift+S",
                   "Write the document to a new file."),
        ActionSpec("file.export", "Export Figure...", Group.FILE, "Ctrl+E",
                   "Render the figure to PNG, PDF or SVG."),
        ActionSpec("file.quit", "Quit", Group.FILE, "Ctrl+Q",
                   "Close the window, offering to save first.",
                   separator_before=True, needs_document=False),

        # ---------------------------------------------------------- edit
        ActionSpec("edit.undo", "Undo", Group.EDIT, "Ctrl+Z",
                   "Reverse the last edit."),
        ActionSpec("edit.redo", "Redo", Group.EDIT, "Ctrl+Shift+Z",
                   "Reapply the edit that was just undone."),
        ActionSpec("edit.select_all", "Select All", Group.EDIT, "Ctrl+A",
                   "Select every node in the tree.", separator_before=True),
        ActionSpec("edit.select_clade", "Select Clade", Group.EDIT,
                   "Ctrl+Shift+A",
                   "Extend the selection to every descendant of it.",
                   context_menu=True, needs_selection=True),
        ActionSpec("edit.clear_selection", "Clear Selection", Group.EDIT, "Esc",
                   "Deselect everything."),

        # ---------------------------------------------------------- tree
        ActionSpec("tree.root.reroot", "Reroot Here", Group.TREE, "R",
                   "Place the root on the edge above the selected node.",
                   context_menu=True, needs_selection=True),
        ActionSpec("tree.root.midpoint", "Midpoint Root", Group.TREE, "M",
                   "Root at the midpoint of the longest tip-to-tip path."),
        ActionSpec("tree.root.outgroup", "Root on Outgroup", Group.TREE,
                   "Ctrl+Shift+R",
                   "Root on the edge separating the selected taxa from the rest.",
                   needs_selection=True),
        ActionSpec("tree.root.unroot", "Unroot", Group.TREE, None,
                   "Merge the root into a trifurcation."),
        ActionSpec("tree.order.ladderize_asc", "Ladderize Ascending",
                   Group.TREE, "L",
                   "Order children so the smallest clade comes first.",
                   separator_before=True),
        ActionSpec("tree.order.ladderize_desc", "Ladderize Descending",
                   Group.TREE, "Shift+L",
                   "Order children so the largest clade comes first."),
        ActionSpec("tree.order.rotate", "Rotate Children", Group.TREE, "Ctrl+R",
                   "Reverse the order of the selected node's children.",
                   context_menu=True, needs_selection=True),
        ActionSpec("tree.collapse", "Collapse / Expand", Group.TREE, "C",
                   "Fold the selected clades into a summary shape, or unfold them.",
                   separator_before=True, context_menu=True,
                   needs_selection=True),
        ActionSpec("tree.expand_all", "Expand All", Group.TREE, "Shift+C",
                   "Unfold every collapsed clade."),
        ActionSpec("tree.prune", "Remove Selected Taxa", Group.TREE, "Del",
                   "Delete the selected nodes and tidy the resulting stubs.",
                   separator_before=True, context_menu=True,
                   needs_selection=True),
        ActionSpec("tree.extract", "Extract Subtree", Group.TREE, "Ctrl+Shift+X",
                   "Open the selected clade on its own as a new document.",
                   context_menu=True, needs_selection=True),

        # ---------------------------------------------------------- view
        ActionSpec("view.mode.rectangular", "Rectangular", Group.VIEW, "1",
                   "Elbow edges on a straight axis.", checkable=True,
                   checked=True),
        ActionSpec("view.mode.slanted", "Slanted", Group.VIEW, "2",
                   "One straight segment per edge.", checkable=True),
        ActionSpec("view.mode.circular", "Circular", Group.VIEW, "3",
                   "Fan layout; radius follows branch length.", checkable=True),
        ActionSpec("view.mode.radial", "Radial", Group.VIEW, "4",
                   "Fan layout with every tip on the outer ring.",
                   checkable=True),
        ActionSpec("view.mode.unrooted", "Unrooted", Group.VIEW, "5",
                   "Equal-daylight placement; no root is implied.",
                   checkable=True),
        ActionSpec("view.branch.phylogram", "Phylogram", Group.VIEW, "Ctrl+1",
                   "Draw branch lengths to scale.", checkable=True,
                   checked=True, separator_before=True),
        ActionSpec("view.branch.cladogram_aligned", "Cladogram (aligned tips)",
                   Group.VIEW, "Ctrl+2",
                   "Ignore lengths; flush every tip at the far edge.",
                   checkable=True),
        ActionSpec("view.branch.cladogram_level", "Cladogram (by level)",
                   Group.VIEW, "Ctrl+3",
                   "Ignore lengths; place each node at its level.",
                   checkable=True),
        ActionSpec("view.align_tips", "Align Tips", Group.VIEW, "A",
                   "Extend tips to the label column and draw guide lines.",
                   checkable=True, separator_before=True),
        ActionSpec("view.zoom_in", "Zoom In", Group.VIEW, "Ctrl+=",
                   "Magnify the figure.", separator_before=True),
        ActionSpec("view.zoom_out", "Zoom Out", Group.VIEW, "Ctrl+-",
                   "Shrink the figure."),
        ActionSpec("view.zoom_fit", "Fit to Window", Group.VIEW, "Ctrl+0",
                   "Scale the figure so all of it is visible."),
        ActionSpec("view.zoom_reset", "Actual Size", Group.VIEW, "Ctrl+Shift+0",
                   "Return to one scene unit per pixel."),
        ActionSpec("view.theme", "Dark Theme", Group.VIEW, "Ctrl+T",
                   "Switch the figure between the light and dark presets.",
                   checkable=True, separator_before=True),
        ActionSpec("view.palette", "Command Palette...", Group.VIEW, "Ctrl+P",
                   "Find and run any command by typing part of its name.",
                   separator_before=True, needs_document=False),
        ActionSpec("view.panel.tree", "Tree Panel", Group.VIEW, "Alt+1",
                   "Show or hide the tree outline.", checkable=True,
                   checked=True, separator_before=True, needs_document=False),
        ActionSpec("view.panel.style", "Style Panel", Group.VIEW, "Alt+2",
                   "Show or hide the style controls.", checkable=True,
                   checked=True, needs_document=False),
        ActionSpec("view.panel.tracks", "Tracks Panel", Group.VIEW, "Alt+3",
                   "Show or hide the track stack.", checkable=True,
                   checked=True, needs_document=False),
        ActionSpec("view.panel.search", "Search Panel", Group.VIEW, "Ctrl+F",
                   "Show the search panel and put the cursor in the query box.",
                   checkable=True, checked=True, needs_document=False),
        ActionSpec("view.panel.inspector", "Inspector Panel", Group.VIEW,
                   "Alt+4", "Show or hide the node inspector.", checkable=True,
                   checked=True, needs_document=False),

        # ------------------------------------------------------ annotate
        ActionSpec("annotate.import", "Import Annotations...", Group.ANNOTATE,
                   "Ctrl+I",
                   "Load a .mytrack table or a delimited file as a new track."),
        ActionSpec("annotate.add_track", "Add Track...", Group.ANNOTATE,
                   "Ctrl+Shift+T", "Append an empty track of a chosen type."),
        ActionSpec("annotate.manage", "Manage Tracks", Group.ANNOTATE,
                   "Ctrl+Shift+M",
                   "Bring the track stack forward for reordering and editing."),

        # ---------------------------------------------------------- help
        ActionSpec("help.guide", "Guide Me...", Group.HELP, "F1",
                   "Answer a few questions -- or hand over a figure from a "
                   "paper -- and get a step-by-step plan you can save and "
                   "come back to.", needs_document=False),
        ActionSpec("help.resume_plan", "Resume a Plan...", Group.HELP, None,
                   "Reopen a saved plan and carry on where you stopped.",
                   needs_document=False),
        ActionSpec("help.shortcuts", "Keyboard Shortcuts...", Group.HELP,
                   "Ctrl+K", "View and change every key binding.",
                   needs_document=False),
        ActionSpec("help.diagnostics", "Diagnostics...", Group.HELP, "Ctrl+D",
                   "Problems reported while reading or drawing this document.",
                   needs_document=False),
        ActionSpec("help.about", f"About {PRODUCT_NAME}", Group.HELP, None,
                   "Version and component information.", separator_before=True,
                   needs_document=False),
        ActionSpec("help.licenses", "Third-Party Licences", Group.HELP, None,
                   "Licence texts for every bundled component.",
                   needs_document=False),
    ])


def apply_named_theme(session: Session, name: str) -> str:
    """Copy the ``light`` or ``dark`` preset onto the session's theme.

    Field by field rather than by replacing the object, because the canvas and
    every track already hold the live :class:`~makeyourtree.style.theme.Theme`;
    swapping the object would leave them painting the old one. ``system``
    resolves to the light preset -- the figure is a document, not chrome, and
    white is what it will be exported and printed as.
    """
    resolved = "dark" if name == "dark" else "light"
    preset = DARK if resolved == "dark" else LIGHT
    values = {f.name: getattr(preset, f.name) for f in dataclasses.fields(Theme)}
    session.set_theme_attr(**values)
    return resolved


def _by_severity(items) -> tuple[int, int, int]:
    """``(errors, warnings, notes)`` across *items*."""
    from makeyourtree.core.diagnostics import Severity

    errors = sum(1 for d in items if d.severity >= Severity.ERROR)
    warnings = sum(1 for d in items if d.severity == Severity.WARNING)
    return errors, warnings, len(items) - errors - warnings


def _diagnostics_label(items) -> str:
    """The status-bar summary: the worst thing present, and how many of it.

    Calling every diagnostic a "problem" made an ordinary file look broken --
    reading a tree whose internal labels are numeric is worth mentioning, and
    is not a fault in the file.  The label therefore names the highest severity
    present and counts only that level; the full list is one click away.
    """
    errors, warnings, notes = _by_severity(items)
    if errors:
        return f"{errors} error{'s' if errors != 1 else ''}"
    if warnings:
        return f"{warnings} warning{'s' if warnings != 1 else ''}"
    if notes:
        return f"{notes} note{'s' if notes != 1 else ''}"
    return "no notes"


def _diagnostics_tooltip(items) -> str:
    if not items:
        return "Nothing was reported about this document"
    errors, warnings, notes = _by_severity(items)
    return (f"{errors} error(s), {warnings} warning(s), {notes} note(s) "
            f"while reading or drawing this document")


class DiagnosticsDialog(QDialog):
    """Everything the parsers and the compositor complained about.

    A dialog rather than a dock because diagnostics are consulted when something
    looks wrong and ignored the rest of the time; a permanently visible panel
    would spend its screen space displaying "no problems".
    """

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnostics")
        self.setObjectName("diagnosticsDialog")
        self.resize(720, 420)
        self._session = session

        self.text = QPlainTextEdit(self)
        self.text.setObjectName("diagnosticsText")
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.clear_button = QPushButton("Clear", self)
        self.close_button = QPushButton("Close", self)
        self.clear_button.clicked.connect(self.clear)
        self.close_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addLayout(buttons)

        session.diagnosticsChanged.connect(self.reload)
        self.reload()

    def report_text(self) -> str:
        sink = self._session.diagnostics
        return sink.format() if len(sink) else "Nothing to report."

    def reload(self) -> None:
        self.text.setPlainText(self.report_text())

    def clear(self) -> None:
        """Forget the accumulated diagnostics.

        They describe events, not state: once read, keeping them only makes the
        next real problem harder to spot in the list.
        """
        self._session.diagnostics.items.clear()
        self._session.diagnosticsChanged.emit()
        self.reload()


class MainWindow(QMainWindow):
    """The application shell."""

    documentOpened = Signal(str)
    """A file was loaded; the argument is its path. For tests and scripting."""

    def __init__(self, session: Session | None = None,
                 settings: Settings | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.session = session if session is not None else Session()
        self.settings = settings if settings is not None else Settings()
        self._dialogs: list[QDialog] = []
        self._theme_name = "light"

        self.canvas = TreeCanvas(self.session, self)
        self.canvas.setObjectName("treeCanvas")
        self.setCentralWidget(self.canvas)

        self._build_panels()

        self.actions_registry = ActionRegistry()
        declare_actions(self.actions_registry)
        # Captured before any override is applied: `Settings.collect_shortcuts`
        # stores only the differences, so a binding corrected in a later release
        # still reaches a user who never customised it.
        self.default_shortcuts = {s.id: s.shortcut
                                  for s in self.actions_registry.specs()}
        self.settings.apply_shortcuts(self.actions_registry)
        self._bind_actions()
        self.actions_registry.build(self)
        self._scope_bare_key_shortcuts()
        self._make_exclusive_groups()

        self._build_menus()
        self._build_toolbar()
        self._build_status_bar()

        self.canvas.set_action_registry(self.actions_registry)
        self._connect_session()
        self._restore_state()

        self._sync_view_actions()
        self._on_history_changed()
        self._on_selection_changed()
        self._on_diagnostics_changed()
        self._update_title()

    # --------------------------------------------------------------- build

    def _build_panels(self) -> None:
        self.tree_panel = TreePanel(self.session, self)
        self.style_panel = StylePanel(self.session, self)
        self.tracks_panel = TracksPanel(self.session, self)
        self.search_panel = SearchPanel(self.session, self)
        self.inspector_panel = InspectorPanel(self.session, self)

        self.tree_dock = self._dock("Tree", "treeDock", self.tree_panel,
                                    Qt.DockWidgetArea.LeftDockWidgetArea)
        self.style_dock = self._dock("Style", "styleDock", self.style_panel,
                                     Qt.DockWidgetArea.RightDockWidgetArea)
        self.tracks_dock = self._dock("Tracks", "tracksDock", self.tracks_panel,
                                      Qt.DockWidgetArea.RightDockWidgetArea)
        self.search_dock = self._dock("Search", "searchDock", self.search_panel,
                                      Qt.DockWidgetArea.RightDockWidgetArea)
        self.inspector_dock = self._dock("Inspector", "inspectorDock",
                                         self.inspector_panel,
                                         Qt.DockWidgetArea.RightDockWidgetArea)
        for other in (self.tracks_dock, self.search_dock, self.inspector_dock):
            self.tabifyDockWidget(self.style_dock, other)
        self.style_dock.raise_()

        self.search_panel.centerOnNode.connect(self.canvas.center_on_node)

    def _dock(self, title: str, name: str, widget: QWidget,
              area: Qt.DockWidgetArea) -> QDockWidget:
        """Wrap *widget* in a dock.

        The object name is mandatory, not cosmetic: ``QMainWindow.saveState``
        keys the stored layout on it and warns for an unnamed dock, so a window
        built without one cannot restore its own layout.
        """
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(area, dock)
        return dock

    def _bind_actions(self) -> None:
        bind = self.actions_registry.bind
        panel = self.tree_panel
        handlers: dict[str, Callable[[], Any]] = {
            "file.new": self.new_document,
            "file.open": self.open_file,
            "file.open_project": self.open_project,
            "file.open_recent": self.show_recent_menu,
            "file.recent.clear": self.clear_recent_files,
            "file.save": self.save,
            "file.save_as": self.save_as,
            "file.export": self.export_figure,
            # Late-bound on purpose: a bound method captured here would ignore
            # a subclass or a test that replaces `close`.
            "file.quit": lambda: self.close(),

            "edit.undo": self.session.undo,
            "edit.redo": self.session.redo,
            "edit.select_all": self.select_all,
            "edit.select_clade": self.select_clade,
            "edit.clear_selection": self.session.clear_selection,

            "tree.root.reroot": panel.reroot_selection,
            "tree.root.midpoint": self.midpoint_root,
            "tree.root.outgroup": self.outgroup_root,
            "tree.root.unroot": self.unroot,
            "tree.order.ladderize_asc": lambda: panel.ladderize(True),
            "tree.order.ladderize_desc": lambda: panel.ladderize(False),
            "tree.order.rotate": panel.rotate_selection,
            "tree.collapse": panel.toggle_collapse,
            "tree.expand_all": self.expand_all,
            "tree.prune": panel.prune_selection,
            "tree.extract": self.extract_subtree,

            "view.align_tips": self.toggle_align_tips,
            "view.zoom_in": lambda: self.canvas.zoom_by(1.25),
            "view.zoom_out": lambda: self.canvas.zoom_by(1.0 / 1.25),
            "view.zoom_fit": self.canvas.fit_to_view,
            "view.zoom_reset": self.canvas.reset_zoom,
            "view.theme": self.toggle_theme,
            "view.palette": self.show_command_palette,

            "annotate.import": self.import_annotations,
            "annotate.add_track": self.add_track,
            "annotate.manage": lambda: self._raise_dock(self.tracks_dock),

            "help.guide": self.show_guide,
            "help.resume_plan": self.resume_plan,
            "help.shortcuts": self.show_shortcuts,
            "help.diagnostics": self.show_diagnostics,
            "help.about": self.show_about,
            "help.licenses": self.show_licenses,
        }
        for action_id, handler in handlers.items():
            bind(action_id, handler)
        for action_id, mode in LAYOUT_MODE_ACTIONS.items():
            bind(action_id, lambda m=mode: self.set_layout_mode(m))
        for action_id, branch in BRANCH_MODE_ACTIONS.items():
            bind(action_id, lambda m=branch: self.set_branch_mode(m))
        for action_id in self._panel_docks():
            bind(action_id, lambda i=action_id: self.toggle_panel(i))

    def _panel_docks(self) -> dict[str, QDockWidget]:
        return {
            "view.panel.tree": self.tree_dock,
            "view.panel.style": self.style_dock,
            "view.panel.tracks": self.tracks_dock,
            "view.panel.search": self.search_dock,
            "view.panel.inspector": self.inspector_dock,
        }

    def _scope_bare_key_shortcuts(self) -> None:
        """Confine modifier-free shortcuts to the canvas.

        ``R``, ``C``, ``Del`` and the digits are the fastest possible bindings
        for the operations a user repeats most, but a window-wide single-letter
        shortcut swallows the keystroke before a ``QLineEdit`` ever sees it --
        typing a species name into the search box would reroot the tree.
        Scoping them to the canvas keeps the speed and gives the text fields
        their keys back.
        """
        for spec in self.actions_registry.specs():
            if not spec.shortcut or _has_modifier(spec.shortcut):
                continue
            action = self.actions_registry.action(spec.id)
            action.setShortcutContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.canvas.addAction(action)

    def _make_exclusive_groups(self) -> None:
        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)
        for action_id in LAYOUT_MODE_ACTIONS:
            self._mode_group.addAction(self.actions_registry.action(action_id))
        self._branch_group = QActionGroup(self)
        self._branch_group.setExclusive(True)
        for action_id in BRANCH_MODE_ACTIONS:
            self._branch_group.addAction(self.actions_registry.action(action_id))

    def _build_menus(self) -> None:
        self.recent_menu = QMenu("Open Recent", self)
        self.recent_menu.setObjectName("recentMenu")
        bar = self.menuBar()
        self.menus: dict[str, QMenu] = {}
        for group in Group.ORDER:
            menu = bar.addMenu(group)
            menu.setObjectName(f"menu.{group.lower()}")
            self.menus[group] = menu
            for spec in self.actions_registry.in_group(group):
                if spec.separator_before:
                    menu.addSeparator()
                if spec.id == "file.open_recent":
                    self.recent_menu.setTitle(spec.text)
                    menu.addMenu(self.recent_menu)
                    self.recent_menu.menuAction().setObjectName(spec.id)
                    continue
                menu.addAction(self.actions_registry.action(spec.id))
        self._rebuild_recent_menu()

    def _build_toolbar(self) -> None:
        self.toolbar = QToolBar("Main", self)
        self.toolbar.setObjectName("mainToolBar")
        self.toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        for action_id in TOOLBAR_IDS:
            if action_id is None:
                self.toolbar.addSeparator()
            else:
                self.toolbar.addAction(self.actions_registry.action(action_id))

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.selection_label = QLabel("No selection", self)
        self.selection_label.setObjectName("selectionSummary")
        self.diagnostics_button = QPushButton(_diagnostics_label([]), self)
        self.diagnostics_button.setObjectName("diagnosticsButton")
        self.diagnostics_button.setFlat(True)
        self.diagnostics_button.setToolTip(
            "What the readers and the compositor reported about this document")
        self.diagnostics_button.clicked.connect(self.show_diagnostics)
        bar.addPermanentWidget(self.selection_label)
        bar.addPermanentWidget(self.diagnostics_button)

    def _connect_session(self) -> None:
        s = self.session
        s.statusMessage.connect(self._on_status_message)
        s.selectionChanged.connect(self._on_selection_changed)
        s.historyChanged.connect(self._on_history_changed)
        s.modifiedChanged.connect(self._on_modified_changed)
        s.diagnosticsChanged.connect(self._on_diagnostics_changed)
        s.documentReplaced.connect(self._on_document_replaced)
        # The check marks are a view of the document, so they have to follow a
        # change made anywhere -- the style panel, a loaded project, a scripted
        # `set_params`. Without this, switching mode from the panel leaves the
        # View menu and the toolbar asserting the previous mode.
        s.dirtied.connect(lambda _level: self._sync_view_actions())
        for action_id, dock in self._panel_docks().items():
            dock.visibilityChanged.connect(
                lambda visible, i=action_id: self._on_dock_visibility(i, visible))

    # ------------------------------------------------------------ overridable

    def ask_open_path(self, caption: str, filters: str) -> str:
        """Ask for a file to read. Overridden in tests to avoid a modal dialog."""
        path, _ = QFileDialog.getOpenFileName(
            self, caption, self.settings.last_import_directory(), filters)
        return path

    def ask_save_path(self, caption: str, suggested: str, filters: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, caption, suggested, filters)
        return path

    def ask_save_changes(self) -> str:
        """``"save"``, ``"discard"`` or ``"cancel"``, from the unsaved prompt."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(PRODUCT_NAME)
        box.setText("This document has unsaved changes.")
        box.setInformativeText("Save them before continuing?")
        box.setStandardButtons(QMessageBox.StandardButton.Save
                               | QMessageBox.StandardButton.Discard
                               | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        answer = box.exec()
        if answer == QMessageBox.StandardButton.Save:
            return "save"
        if answer == QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"

    def report_error(self, title: str, message: str) -> None:
        """Show a failure the user must know about.

        A message box rather than a traceback: a file that has been moved,
        truncated, or is not a tree at all is an ordinary event, not a bug, and
        the application has to survive it.
        """
        QMessageBox.critical(self, title, message)

    def open_dialog(self, dialog: QDialog) -> QDialog:
        """Show *dialog* without blocking, keeping a reference to it.

        ``open()`` rather than ``exec()`` so no handler here can start a nested
        event loop inside one a caller already owns -- which is what makes every
        action invocable from a test.
        """
        self._dialogs.append(dialog)
        dialog.finished.connect(lambda _r, d=dialog: self._forget_dialog(d))
        dialog.open()
        return dialog

    def _forget_dialog(self, dialog: QDialog) -> None:
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)

    def open_dialogs(self) -> list[QDialog]:
        """Dialogs this window opened and has not yet seen closed."""
        return list(self._dialogs)

    # ------------------------------------------------------------------ file

    def maybe_save(self) -> bool:
        """True when it is safe to replace or close the document."""
        if not self.session.is_modified:
            return True
        answer = self.ask_save_changes()
        if answer == "cancel":
            return False
        if answer == "save":
            return self.save()
        return True

    def new_document(self) -> bool:
        if not self.maybe_save():
            return False
        self.session.set_document(Document(tree=Tree()))
        self._say("New document")
        return True

    def open_file(self) -> str:
        path = self.ask_open_path("Open Tree", OPEN_FILTER)
        if path:
            self.open_path(path)
        return path

    def open_project(self) -> str:
        path = self.ask_open_path("Open Project", PROJECT_FILTER)
        if path:
            self.open_path(path)
        return path

    def open_path(self, path: str | os.PathLike[str]) -> bool:
        """Load *path*, replacing the open document. Never raises.

        Anything the core refuses to read -- a missing file, a permission error,
        a project written by a newer build -- is reported and the current
        document is left exactly as it was.
        """
        target = os.fspath(path)
        if not self.maybe_save():
            return False
        try:
            document = self.load_document(target)
        except (OSError, MakeYourTreeError, ValueError) as exc:
            self.settings.remove_recent_file(target)
            self._rebuild_recent_menu()
            self.report_error("Cannot open file",
                              f"{target}\n\n{type(exc).__name__}: {exc}")
            return False
        self.session.set_document(document)
        self.settings.add_recent_file(target)
        self.settings.set_last_import_directory(target)
        self._rebuild_recent_menu()
        self._sync_view_actions()
        self._update_title()
        self._say(f"Opened {os.path.basename(target)}")
        self.documentOpened.emit(target)
        return True

    def load_document(self, path: str) -> Document:
        """Read *path* as a project or as a bare tree, whichever it is."""
        if _is_project_path(path):
            return load_project(path)
        sink = self.session.diagnostics
        before = len(sink)
        tree = load_tree(path, sink=sink,
                         internal_labels=self.settings.internal_labels())
        if len(sink) != before:
            self.session.diagnosticsChanged.emit()
        document = Document(tree=tree, source_path=path)
        document.title = os.path.splitext(os.path.basename(path))[0]
        return document

    def save(self) -> bool:
        if not self.session.path:
            return self.save_as()
        return self.save_to(self.session.path)

    def save_as(self) -> bool:
        suggested = self.session.path or _default_save_name(self.session)
        path = self.ask_save_path("Save As", suggested,
                                  f"{PROJECT_FILTER};;{TREE_FILTER}")
        if not path:
            return False
        return self.save_to(path)

    def save_to(self, path: str | os.PathLike[str]) -> bool:
        """Write the document to *path*, choosing the writer from the suffix."""
        target = os.fspath(path)
        try:
            if _is_project_path(target):
                save_project(self.session.document, target,
                             flat=target.lower().endswith(".json"))
            else:
                fmt = TREE_SUFFIX_FORMAT.get(
                    os.path.splitext(target)[1].lower(), "newick")
                save_tree(self.session.tree, target, format=fmt)
        except (OSError, MakeYourTreeError, ValueError) as exc:
            self.report_error("Cannot save file",
                              f"{target}\n\n{type(exc).__name__}: {exc}")
            return False
        self.session.mark_saved(target)
        self.settings.add_recent_file(target)
        self._rebuild_recent_menu()
        self._update_title()
        self._say(f"Saved {os.path.basename(target)}")
        return True

    def export_figure(self) -> QDialog:
        return self.open_dialog(ExportDialog(self.session, self))

    # ---------------------------------------------------------- recent files

    def _rebuild_recent_menu(self) -> None:
        """Rebuild the recent list from the store.

        The entries are *data*, not commands: every one runs the same
        :meth:`open_path`, differing only in its argument, which is why they are
        not registry specs. The two commands here -- opening the submenu and
        clearing it -- are.
        """
        self.recent_menu.clear()
        paths = self.settings.recent_files()
        for path in paths:
            entry = self.recent_menu.addAction(_elide_path(path))
            entry.setToolTip(path)
            entry.setStatusTip(path)
            entry.triggered.connect(lambda _c=False, p=path: self.open_path(p))
        self.recent_menu.setEnabled(bool(paths))
        if "file.recent.clear" in self.actions_registry:
            self.actions_registry.action(
                "file.recent.clear").setEnabled(bool(paths))

    def recent_paths(self) -> list[str]:
        return self.settings.recent_files()

    def clear_recent_files(self) -> None:
        self.settings.clear_recent_files()
        self._rebuild_recent_menu()

    def show_recent_menu(self) -> QMenu:
        """Drop the submenu down when the command is invoked by keyboard."""
        self.recent_menu.popup(self.mapToGlobal(QPoint(0, 0)))
        return self.recent_menu

    # -------------------------------------------------------------- selection

    def select_all(self) -> None:
        self.session.set_selection(n.id for n in self.session.tree.nodes)

    def select_clade(self) -> None:
        """Grow the selection to every descendant of everything selected."""
        tree = self.session.tree
        ids: set[int] = set(self.session.selection)
        for node_id in list(ids):
            node = tree.by_id(node_id)
            if node is None:
                continue
            ids.update(n.id for n in select_clade(tree, node))
        self.session.set_selection(ids)

    # ------------------------------------------------------------------ tree

    def midpoint_root(self) -> None:
        self._edit(lambda: midpoint_root(self.session.tree))

    def outgroup_root(self) -> None:
        nodes = self.session.selected_nodes()
        if not nodes:
            self._say("Select the outgroup taxa first")
            return
        self._edit(lambda: outgroup_root(self.session.tree, nodes))

    def unroot(self) -> None:
        self._edit(lambda: unroot(self.session.tree))

    def expand_all(self) -> None:
        from makeyourtree.ops.command import CompositeCommand
        from makeyourtree.ops.edit import expand

        tree = self.session.tree
        nodes = tree.collapsed_nodes()
        if not nodes:
            self._say("Nothing is collapsed")
            return
        commands = [expand(tree, n) for n in nodes]
        self._edit(lambda: CompositeCommand(
            label=f"expand {len(commands)} clades", commands=commands,
            touches_topology=False))

    def extract_subtree(self) -> Document | None:
        """Open the selected clade as a document of its own.

        A new document rather than an edit, because nothing in the source tree
        changes; the original stays only if the user saved it, which is what the
        unsaved-changes prompt is for.
        """
        nodes = self.session.selected_nodes()
        if len(nodes) != 1:
            self._say("Select exactly one node to extract")
            return None
        if not self.maybe_save():
            return None
        try:
            subtree = extract_subtree(self.session.tree, nodes[0])
        except MakeYourTreeError as exc:
            self._say(str(exc))
            return None
        document = Document(tree=subtree, params=self.session.params,
                            theme=self.session.theme)
        document.title = nodes[0].name or "subtree"
        self.session.set_document(document)
        self._update_title()
        return document

    def _edit(self, build: Callable[[], Any]) -> None:
        """Build a command and stack it, or turn a refusal into a message."""
        try:
            command = build()
        except MakeYourTreeError as exc:
            self._say(str(exc))
            return
        if command is not None:
            self.session.do(command)

    # ------------------------------------------------------------------ view

    def set_layout_mode(self, mode: LayoutMode) -> None:
        if self.session.params.mode is not mode:
            self.session.set_params(mode=mode)
        self._sync_view_actions()

    def set_branch_mode(self, mode: BranchMode) -> None:
        if self.session.params.branch_mode is not mode:
            self.session.set_params(branch_mode=mode)
        self._sync_view_actions()

    def toggle_align_tips(self) -> None:
        action = self.actions_registry.action("view.align_tips")
        self.session.set_params(align_tips=bool(action.isChecked()))

    def toggle_theme(self) -> None:
        action = self.actions_registry.action("view.theme")
        self.set_theme_name("dark" if action.isChecked() else "light")

    def set_theme_name(self, name: str) -> str:
        self._theme_name = apply_named_theme(self.session, name)
        self.settings.set_theme(self._theme_name)
        self.actions_registry.action("view.theme").setChecked(
            self._theme_name == "dark")
        return self._theme_name

    @property
    def theme_name(self) -> str:
        return self._theme_name

    def toggle_panel(self, action_id: str) -> None:
        """Show or hide one dock, following its action's check state."""
        dock = self._panel_docks()[action_id]
        action = self.actions_registry.action(action_id)
        visible = bool(action.isChecked())
        dock.setVisible(visible)
        if visible:
            self._raise_dock(dock)
            if dock is self.search_dock:
                self.search_panel.query_edit.setFocus()

    def _raise_dock(self, dock: QDockWidget) -> None:
        dock.setVisible(True)
        dock.raise_()

    def _on_dock_visibility(self, action_id: str, visible: bool) -> None:
        action = self.actions_registry.action(action_id)
        if action.isChecked() != visible:
            action.setChecked(visible)

    def _sync_view_actions(self) -> None:
        """Push the document's own settings onto the checkable actions.

        Layout mode and branch mode live in the document, so opening a file or
        changing them from the style panel must move the check mark; the menu is
        a view of the document, never a second copy of it.
        """
        params = self.session.params
        for action_id, mode in LAYOUT_MODE_ACTIONS.items():
            self.actions_registry.action(action_id).setChecked(
                params.mode == mode)
        for action_id, branch in BRANCH_MODE_ACTIONS.items():
            self.actions_registry.action(action_id).setChecked(
                params.branch_mode == branch)
        align = self.actions_registry.action("view.align_tips")
        align.setChecked(bool(params.align_tips))
        # An unrooted drawing has no edge to flush tips against, so the command
        # cannot do anything.  Disabling it says that; leaving it enabled
        # invites the user to click and conclude the application is broken.
        aligns = params.mode is not LayoutMode.UNROOTED
        align.setEnabled(aligns)
        align.setToolTip("" if aligns else
                         "Tips cannot be aligned in an unrooted drawing: they "
                         "point in every direction, so there is no edge to "
                         "align them to")
        # The theme lives in the document too, and the style panel can swap it.
        # Read it back rather than trusting `_theme_name`, which only records
        # what *this* window last asked for.
        is_dark = self.session.theme.name == DARK.name
        self._theme_name = "dark" if is_dark else "light"
        self.actions_registry.action("view.theme").setChecked(is_dark)

    def show_command_palette(self) -> CommandPalette:
        palette = CommandPalette(self.actions_registry, self)
        self.open_dialog(palette)
        return palette

    # -------------------------------------------------------------- annotate

    def import_annotations(self) -> QDialog:
        return self.open_dialog(ImportDialog(self.session, self))

    def add_track(self) -> QDialog:
        """Choose a track type, then append an empty track of it."""
        self._raise_dock(self.tracks_dock)
        dialog = TrackTypeDialog(self)
        dialog.accepted.connect(lambda d=dialog: self._add_chosen_track(d))
        return self.open_dialog(dialog)

    def _add_chosen_track(self, dialog: TrackTypeDialog) -> None:
        type_id = dialog.selected_type_id()
        if type_id:
            self.tracks_panel.add_track_of_type(type_id)

    # ------------------------------------------------------------------ help

    def show_guide(self) -> "GuideDialog":
        """Open the guided interview.

        Imported here rather than at module scope so that starting the
        application does not pay for a dialog most sessions never open.
        """
        from .dialogs.guide_dialog import GuideDialog

        dialog = GuideDialog(self)
        self.open_dialog(dialog)
        return dialog

    def resume_plan(self) -> "GuideDialog | None":
        """Reopen a saved plan and carry on from where it stopped."""
        from .dialogs.guide_dialog import GuideDialog

        dialog = GuideDialog.resume(self)
        if dialog is not None:
            self.open_dialog(dialog)
        return dialog

    def show_shortcuts(self) -> ShortcutsDialog:
        dialog = ShortcutsDialog(self.actions_registry, self.settings,
                                 self.default_shortcuts, self)
        self.open_dialog(dialog)
        return dialog

    def show_diagnostics(self) -> DiagnosticsDialog:
        dialog = DiagnosticsDialog(self.session, self)
        self.open_dialog(dialog)
        return dialog

    def show_about(self) -> AboutDialog:
        dialog = AboutDialog(self)
        self.open_dialog(dialog)
        return dialog

    def show_licenses(self) -> LicensesDialog:
        dialog = LicensesDialog(self)
        self.open_dialog(dialog)
        return dialog

    # --------------------------------------------------------------- status

    def _on_status_message(self, message: str, timeout: int) -> None:
        self.statusBar().showMessage(message, timeout)

    def _say(self, message: str) -> None:
        self.session.statusMessage.emit(message, _STATUS_MS)

    def selection_summary(self) -> str:
        ids = self.session.selection
        if not ids:
            return "No selection"
        if len(ids) == 1:
            node = self.session.tree.by_id(next(iter(ids)))
            if node is not None:
                what = node.name or f"node {node.id}"
                return f"{what} ({'clade' if node.children else 'tip'})"
        leaves = sum(1 for n in self.session.selected_nodes() if not n.children)
        return f"{len(ids)} nodes selected, {leaves} tips"

    def _on_selection_changed(self) -> None:
        self.selection_label.setText(self.selection_summary())
        self.actions_registry.update_enabled(
            has_document=self.session.tree.root is not None,
            has_selection=bool(self.session.selection))
        # update_enabled has just overwritten the history-driven enablement.
        self._sync_history_enabled()
        self._sync_recent_enabled()

    def _on_history_changed(self) -> None:
        """Name the operation in the undo and redo items.

        "Undo reroot" tells a user what is about to happen; a bare "Undo" makes
        them try it to find out.
        """
        stack = self.session.stack
        undo = self.actions_registry.action("edit.undo")
        redo = self.actions_registry.action("edit.redo")
        undo.setText(f"Undo {stack.undo_label}" if stack.can_undo else "Undo")
        redo.setText(f"Redo {stack.redo_label}" if stack.can_redo else "Redo")
        self._sync_history_enabled()
        self._update_title()

    def _sync_history_enabled(self) -> None:
        stack = self.session.stack
        self.actions_registry.action("edit.undo").setEnabled(stack.can_undo)
        self.actions_registry.action("edit.redo").setEnabled(stack.can_redo)

    def _sync_recent_enabled(self) -> None:
        has_recent = bool(self.settings.recent_files())
        self.recent_menu.setEnabled(has_recent)
        self.actions_registry.action("file.recent.clear").setEnabled(has_recent)

    def _on_modified_changed(self, _modified: bool) -> None:
        self._update_title()

    def _on_diagnostics_changed(self) -> None:
        self._dedupe_diagnostics()
        items = list(self.session.diagnostics)
        self.diagnostics_button.setText(_diagnostics_label(items))
        self.diagnostics_button.setToolTip(_diagnostics_tooltip(items))

    def _dedupe_diagnostics(self) -> None:
        """Collapse identical reports to one entry.

        ``Session.recompose`` appends the compositor's diagnostics to the
        session sink on *every* recomposition, and the compositor says the same
        thing about the same figure every time. Left alone, flipping between
        layout modes ticks the status bar up by one per pass -- "37 problems"
        for a document with one -- and the diagnostics dialog repeats itself
        thirty-seven times. The sink is the right place to hold the accumulated
        report; it is the wrong place to hold the same sentence twice.

        Diagnostics are frozen dataclasses, so identity is by value: severity,
        code, message and position. Two genuinely different lines of the same
        file therefore still count separately.
        """
        items = self.session.diagnostics.items
        seen: set[Any] = set()
        unique = []
        for d in items:
            if d in seen:
                continue
            seen.add(d)
            unique.append(d)
        if len(unique) != len(items):
            items[:] = unique

    def _on_document_replaced(self) -> None:
        self._sync_view_actions()
        self._on_selection_changed()
        self._on_history_changed()
        self._on_diagnostics_changed()
        self._update_title()

    def _update_title(self) -> None:
        name = (self.session.document.title
                or (os.path.basename(self.session.path) if self.session.path
                    else "Untitled"))
        mark = "*" if self.session.is_modified else ""
        self.setWindowTitle(f"{mark}{name} - {PRODUCT_NAME}")

    # ------------------------------------------------------- persisted state

    def _restore_state(self) -> None:
        geometry = self.settings.window_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1280, 840)
        state = self.settings.window_state()
        if state is not None:
            self.restoreState(state)
        # Apply the saved theme, do not merely remember its name. `app.py`
        # applies it before the window is built so the first composition is in
        # the right colours, but a MainWindow constructed directly -- which the
        # public signature allows, and every test does -- has a fresh document
        # still holding the light preset. Recording "dark" without applying it
        # left the menu, the style panel and the canvas disagreeing.
        self.set_theme_name(self.settings.theme())
        for action_id, dock in self._panel_docks().items():
            self.actions_registry.action(action_id).setChecked(
                not dock.isHidden())

    def save_window_state(self) -> None:
        self.settings.set_window_geometry(QByteArray(self.saveGeometry()))
        self.settings.set_window_state(QByteArray(self.saveState()))
        self.settings.collect_shortcuts(self.actions_registry,
                                        self.default_shortcuts)
        self.settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if not self.maybe_save():
            event.ignore()
            return
        self.save_window_state()
        for dialog in list(self._dialogs):
            dialog.close()
        self._dialogs.clear()
        event.accept()


def _has_modifier(sequence: str) -> bool:
    """True when *sequence* is safe to leave window-wide.

    ``Shift`` alone does not count: ``Shift+L`` is still a letter a user can
    type into a text field.
    """
    lowered = sequence.lower()
    return any(mod in lowered for mod in ("ctrl", "alt", "meta"))


def _is_project_path(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(suffix) for suffix in PROJECT_SUFFIXES)


def _default_save_name(session: Session) -> str:
    stem = session.document.title or "untitled"
    directory = os.path.dirname(session.document.source_path or "")
    return os.path.join(directory, f"{stem}.mytree")


def _elide_path(path: str, keep: int = 48) -> str:
    """Shorten a long path from the left, so the file name always survives."""
    if len(path) <= keep:
        return path
    return "..." + path[-(keep - 3):]


def sequence_text(sequence: str | None) -> str:
    """Portable display form of a shortcut string; ``""`` when unbound."""
    return QKeySequence(sequence).toString() if sequence else ""


def specs_with_handlers(registry: ActionRegistry) -> Iterable[ActionSpec]:
    """Every spec that has something bound to it. Used by tests and the palette."""
    return (s for s in registry.specs() if s.handler is not None)


def running_application() -> QApplication | None:
    """The live application, if any. A convenience for scripted sessions."""
    return QApplication.instance()
