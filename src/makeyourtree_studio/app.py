# SPDX-License-Identifier: MIT
"""Application entry point.

Startup order is not arbitrary. The text metrics must be installed on the
session *before* the window exists, because the canvas composes once
synchronously as it is constructed and would otherwise reserve label widths
measured by the Qt-free fallback and then paint them with real Qt fonts. The
saved theme is applied for the same reason: it is cheaper to compose once in the
right colours than to compose in the wrong ones and invalidate.

:func:`build_application` does the assembly and stops short of the event loop,
so a test, a scripted export, or a future ``--render-to`` batch mode can drive a
fully wired window without ``exec()``. :func:`main` is that plus the loop.
"""

from __future__ import annotations

import os
import sys
from typing import Sequence

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from makeyourtree import __version__ as makeyourtree_version
from makeyourtree.text.metrics import CachedMetrics

from .canvas.qt_metrics import QtMetrics
from .main_window import MainWindow, apply_named_theme
from .session import Session
from .settings import Settings

__all__ = ["main", "build_application", "install_metrics", "file_arguments"]


def install_metrics(session: Session, family: str | None = None) -> CachedMetrics:
    """Give *session* Qt-backed text measurement, memoised.

    Wrapped in :class:`~makeyourtree.text.metrics.CachedMetrics` because the layout
    measures the same tip label on every recomposition and a ``QFontMetricsF``
    call is far from free; the cache turns a per-frame cost into a per-string
    one.
    """
    metrics = CachedMetrics(QtMetrics(family))
    session.metrics = metrics
    session.document.metadata.setdefault("text_metrics", metrics)
    return metrics


def file_arguments(argv: Sequence[str]) -> list[str]:
    """The paths in *argv*, ignoring the program name and any option flags.

    Qt itself consumes arguments such as ``-platform``; anything beginning with
    a dash is therefore left alone rather than mistaken for a file.
    """
    return [a for a in argv[1:] if a and not a.startswith("-")]


def build_application(argv: Sequence[str] | None = None,
                      settings: Settings | None = None) -> tuple[QApplication,
                                                                 MainWindow]:
    """Create (or adopt) the application and build a fully wired window.

    Returns before the event loop starts, so callers that own their own loop --
    the test suite above all -- get the real startup path rather than a
    reimplementation of it.
    """
    args = list(sys.argv if argv is None else argv)
    app = QApplication.instance()
    if app is None:
        app = QApplication(args)
    QCoreApplication.setOrganizationName(Settings.ORGANISATION)
    QCoreApplication.setApplicationName(Settings.APPLICATION)
    QCoreApplication.setApplicationVersion(makeyourtree_version)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)

    store = settings if settings is not None else Settings()
    session = Session()
    install_metrics(session)
    apply_named_theme(session, store.theme())

    window = MainWindow(session=session, settings=store)
    for path in file_arguments(args):
        if _open_or_report(window, path):
            break
    return app, window


def _open_or_report(window: MainWindow, path: str) -> bool:
    """Open one command-line path, reporting a bad one instead of crashing.

    A launcher, a file association and a shell glob can all hand us something
    that no longer exists; the application must start anyway and say why the
    file did not open.
    """
    if not os.path.exists(path):
        QMessageBox.critical(window, "Cannot open file",
                             f"{path}\n\nNo such file.")
        return False
    return window.open_path(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Run MakeYourTree Studio. Returns the process exit code."""
    app, window = build_application(argv)
    window.show()
    return int(app.exec())


if __name__ == "__main__":  # pragma: no cover - exercised via __main__.py
    sys.exit(main())
