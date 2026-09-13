# SPDX-License-Identifier: MIT
"""Helpers shared by the shell tests.

Named ``shell_helpers`` rather than ``helpers`` because pytest's prepend import
mode puts every test directory on ``sys.path``: two suites with a module of the
same name shadow each other and the second one to be collected fails to import.

The window is built through the real entry point wherever possible, with only
the modal seams replaced. A test that constructed its own widgets would prove
that the widgets work and nothing about whether the application wires them up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication

from makeyourtree_studio.main_window import MainWindow
from makeyourtree_studio.session import Session
from makeyourtree_studio.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
PRIMATES = EXAMPLES / "primates.nwk"
VIRUS_NEXUS = EXAMPLES / "virus.nex"

NEWICK = ("(((alpha:0.1,beta:0.2)ab:0.3,(gamma:0.15,delta:0.25)gd:0.2)abgd:0.1,"
          "((epsilon:0.4,zeta:0.35)ez:0.2,eta:0.5)ezeta:0.3);")
"""Synthetic, seven named tips. Enough depth for reroot, prune and collapse."""


class ScriptedWindow(MainWindow):
    """A window whose modal questions are answered from attributes.

    Subclassing rather than monkeypatching so the seams are visible in one
    place, and so a test that forgets to set one gets a clear failure instead of
    a dialog that blocks the suite forever.
    """

    def __init__(self, *args: Any, **kw: Any) -> None:
        self.open_answer: str = ""
        self.save_answer: str = ""
        self.discard_answer: str = "discard"
        self.errors: list[tuple[str, str]] = []
        self.asked: list[str] = []
        super().__init__(*args, **kw)

    def ask_open_path(self, caption: str, filters: str) -> str:
        self.asked.append(caption)
        return self.open_answer

    def ask_save_path(self, caption: str, suggested: str, filters: str) -> str:
        self.asked.append(caption)
        return self.save_answer

    def ask_save_changes(self) -> str:
        self.asked.append("save-changes")
        return self.discard_answer

    def report_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))


def make_window(tmp_path: Path, **kw: Any) -> ScriptedWindow:
    """A window backed by a throwaway settings file."""
    settings = Settings.for_file(tmp_path / "settings.ini")
    session = Session()
    window = ScriptedWindow(session=session, settings=settings, **kw)
    window.resize(1000, 700)
    return window


def close_window(window: MainWindow) -> None:
    """Close without the unsaved-changes prompt getting in the way.

    ``deleteLater`` only queues the deletion; without an event-loop turn the
    window, its session and its canvas survive for the whole pytest process,
    and any recomposition its canvas still had pending on a zero-timer fires
    inside whatever *later* test next spins the loop. One ``processEvents``
    both drains that timer and performs the deletion.
    """
    window.session.mark_saved()
    window.close()
    window.deleteLater()
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def internal_nodes(window: MainWindow) -> list[int]:
    return [n.id for n in window.session.tree.nodes if n.children]


def leaf_ids(window: MainWindow) -> list[int]:
    return [n.id for n in window.session.tree.nodes if not n.children]


def trigger(window: MainWindow, action_id: str) -> None:
    """Invoke a command the way the menu bar does."""
    window.actions_registry.action(action_id).trigger()
