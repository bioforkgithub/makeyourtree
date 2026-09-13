# SPDX-License-Identifier: MIT
"""Fixtures for the application-shell suite.

One ``QApplication`` for the whole session and never torn down: rebuilding it
between tests is a well known way to crash the offscreen platform.

``QSettings`` is redirected to a temporary INI tree. The window persists its
geometry, dock layout and shortcut overrides on close, and a suite that wrote
those into the real registry would both leak state between runs and vandalise
the developer's own preferences.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from shell_helpers import (NEWICK, PRIMATES, ScriptedWindow,  # noqa: E402
                           close_window, make_window)

from makeyourtree.core.tree import Tree  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(scope="session", autouse=True)
def _isolated_settings(tmp_path_factory):
    root = tmp_path_factory.mktemp("shell-qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(root))
    yield root


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> ScriptedWindow:
    w = make_window(tmp_path)
    yield w
    close_window(w)


@pytest.fixture
def newick_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.nwk"
    path.write_text(NEWICK + "\n", encoding="utf-8")
    return path


@pytest.fixture
def loaded(window: ScriptedWindow, newick_file: Path) -> ScriptedWindow:
    """A window with the synthetic tree open and no unsaved changes."""
    assert window.open_path(newick_file)
    return window


@pytest.fixture
def primates(window: ScriptedWindow) -> ScriptedWindow:
    assert PRIMATES.is_file(), "the example tree is part of the checkout"
    assert window.open_path(PRIMATES)
    return window


@pytest.fixture
def tree() -> Tree:
    return Tree.from_newick(NEWICK)
