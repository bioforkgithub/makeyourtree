# SPDX-License-Identifier: MIT
"""The entry point, exercised through the real startup path.

The clean-start test runs in a subprocess on purpose. A Qt warning is written
to the process's stderr, not raised, so the only way to assert that starting and
quitting the application is silent is to own the process and read its streams --
and doing that in a child also proves the module can be launched from a cold
interpreter, which is what the packaged binary does.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from shell_helpers import NEWICK, PRIMATES, ROOT, close_window

from makeyourtree_studio.app import build_application, file_arguments, install_metrics
from makeyourtree_studio.session import Session
from makeyourtree_studio.settings import Settings

SRC = ROOT / "src"


def _run(script: str, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    runner = tmp_path / "runner.py"
    runner.write_text(textwrap.dedent(script), encoding="utf-8")
    env = {
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONPATH": str(SRC),
        "PYTHONIOENCODING": "utf-8",
        "PATH": "",
        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "MAKEYOURTREE_TEST_SETTINGS": str(tmp_path / "settings"),
    }
    return subprocess.run([sys.executable, str(runner), *args],
                          capture_output=True, text=True, timeout=180, env=env)


CLEAN_START = """
    import os
    import sys

    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication

    # Never touch the developer's real preference store.
    root = os.environ["MAKEYOURTREE_TEST_SETTINGS"]
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, root)

    app = QApplication(sys.argv)
    QTimer.singleShot(0, app.quit)

    import runpy
    try:
        runpy.run_module("makeyourtree_studio", run_name="__main__")
    except SystemExit as exc:
        sys.exit(exc.code)
"""


#: Lines the *offscreen platform plugin* writes about itself, which the
#: application neither causes nor can prevent. Qt no longer ships fonts, so the
#: offscreen plugin falls back to the FreeType database and says so; and it has
#: no window manager, so it announces the size-hint call it cannot forward.
#: Both appear only when the parent process has a console attached -- Qt routes
#: qWarning to the debugger otherwise -- which is why this file was green under
#: CI and red in a developer's terminal. Every other line on stderr still fails
#: the test: this names two known platform sentences, it is not a "warnings are
#: acceptable" switch, and `test_the_noise_filter_only_removes_what_it_names`
#: pins that.
PLATFORM_NOISE = (
    "QFontDatabase: Cannot find font directory",
    "Note that Qt no longer ships fonts.",
    "This plugin does not support propagateSizeHints()",
)


def application_stderr(result: subprocess.CompletedProcess) -> str:
    """*result*'s stderr with the offscreen plugin's own chatter removed."""
    kept = [line for line in result.stderr.splitlines()
            if line.strip() and not line.startswith(PLATFORM_NOISE)]
    return "\n".join(kept)


def test_the_noise_filter_only_removes_what_it_names():
    fake = subprocess.CompletedProcess(
        [], 0, "",
        "QFontDatabase: Cannot find font directory C:/x/fonts.\n"
        "This plugin does not support propagateSizeHints()\n"
        "QObject::connect: No such slot MainWindow::nope()\n")
    assert application_stderr(fake) == (
        "QObject::connect: No such slot MainWindow::nope()")


def test_the_application_starts_and_quits_cleanly_with_no_qt_warnings(tmp_path):
    result = _run(CLEAN_START, tmp_path)
    assert result.returncode == 0, result.stderr
    assert application_stderr(result) == "", \
        f"Qt complained on startup:\n{result.stderr}"


def test_it_starts_with_a_tree_on_the_command_line(tmp_path: Path):
    tree = tmp_path / "cli.nwk"
    tree.write_text(NEWICK + "\n", encoding="utf-8")
    result = _run(CLEAN_START, tmp_path, str(tree))
    assert result.returncode == 0, result.stderr
    assert application_stderr(result) == "", \
        f"Qt complained opening a file:\n{result.stderr}"


def test_it_starts_with_an_example_tree(tmp_path: Path):
    result = _run(CLEAN_START, tmp_path, str(PRIMATES))
    assert result.returncode == 0, result.stderr
    assert application_stderr(result) == "", \
        f"Qt complained opening the example tree:\n{result.stderr}"


# ------------------------------------------------------------- in-process


def test_build_application_wires_metrics_before_the_window_exists(qapp,
                                                                  tmp_path):
    from makeyourtree.text.metrics import CachedMetrics

    settings = Settings.for_file(tmp_path / "app.ini")
    _app, window = build_application(["prog"], settings)
    try:
        assert isinstance(window.session.metrics, CachedMetrics)
        assert (window.session.document.metadata["text_metrics"]
                is window.session.metrics)
    finally:
        close_window(window)


def test_install_metrics_measures_a_string(qapp):
    session = Session()
    metrics = install_metrics(session)
    width = metrics.advance("alpha", 12.0)
    assert width > 0, "even the fallback must return a usable advance"
    assert metrics.advance("alpha", 12.0) == width


def test_build_application_opens_a_path_from_the_command_line(qapp, tmp_path):
    tree = tmp_path / "cli.nwk"
    tree.write_text(NEWICK + "\n", encoding="utf-8")
    settings = Settings.for_file(tmp_path / "app.ini")
    _app, window = build_application(["prog", str(tree)], settings)
    try:
        assert window.session.tree.n_leaves == 7
        assert window.session.path is None
        assert window.session.document.source_path == str(tree)
    finally:
        close_window(window)


def test_a_missing_command_line_file_reports_instead_of_raising(
        qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a[2]))
    settings = Settings.for_file(tmp_path / "app.ini")
    missing = tmp_path / "nowhere.nwk"
    _app, window = build_application(["prog", str(missing)], settings)
    try:
        assert shown and str(missing) in shown[0]
        assert window.session.tree.n_leaves == 1
    finally:
        close_window(window)


def test_the_saved_theme_is_applied_before_the_first_composition(qapp,
                                                                 tmp_path):
    settings = Settings.for_file(tmp_path / "app.ini")
    settings.set_theme("dark")
    _app, window = build_application(["prog"], settings)
    try:
        assert window.theme_name == "dark"
        from makeyourtree.style.theme import DARK
        assert window.session.theme.background == DARK.background
    finally:
        close_window(window)


@pytest.mark.parametrize("argv,expected", [
    (["prog"], []),
    (["prog", "a.nwk"], ["a.nwk"]),
    (["prog", "-platform", "offscreen", "a.nwk"], ["offscreen", "a.nwk"]),
    (["prog", "--verbose"], []),
])
def test_file_arguments_ignores_flags(argv, expected):
    assert file_arguments(argv) == expected


def test_the_organisation_and_application_names_are_set(qapp, tmp_path):
    from PySide6.QtCore import QCoreApplication

    settings = Settings.for_file(tmp_path / "app.ini")
    _app, window = build_application(["prog"], settings)
    try:
        assert QCoreApplication.organizationName() == Settings.ORGANISATION
        assert QCoreApplication.applicationName() == Settings.APPLICATION
        assert QCoreApplication.applicationVersion()
    finally:
        close_window(window)


def test_a_window_built_by_the_entry_point_can_save_a_project(qapp, tmp_path):
    """Save has to work on the *real* startup path, not just a bare window.

    ``install_metrics`` puts a live ``CachedMetrics`` into
    ``document.metadata["text_metrics"]`` because that is where ``compose``
    reads it from. ``Document.manifest`` serialises the metadata dict whole, so
    for a while every ``File > Save`` in the assembled application died with
    "CachedMetrics is not JSON-serialisable" -- while the shell tests, which
    build a window around a metric-less ``Session``, stayed green.
    """
    from makeyourtree.doc.io import load_project

    tree = tmp_path / "cli.nwk"
    tree.write_text(NEWICK + "\n", encoding="utf-8")
    settings = Settings.for_file(tmp_path / "app.ini")
    _app, window = build_application(["prog", str(tree)], settings)
    try:
        assert window.session.document.metadata.get("text_metrics") is not None
        for name in ("figure.mytree", "figure.mytree.json"):
            target = tmp_path / name
            assert window.save_to(target), f"save_to({name}) reported failure"
            assert target.is_file() and target.stat().st_size > 0
            reloaded = load_project(target)
            assert reloaded.tree.n_leaves == 7
        # The measurer is still on the live document: saving must not disarm
        # the compositor.
        assert window.session.document.metadata["text_metrics"] is \
            window.session.metrics
    finally:
        close_window(window)
