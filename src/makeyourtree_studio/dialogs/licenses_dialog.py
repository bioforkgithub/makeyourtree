# SPDX-License-Identifier: MIT
"""Third-party licence texts, reachable at runtime.

This dialog is a **licence obligation**, not a nicety.  MakeYourTree Studio links Qt
dynamically under LGPL-3.0, and §4(a) requires the combined work to carry a
prominent notice that Qt is used and covered by that licence, while §4(c)
requires the licence texts themselves to be displayed during execution.  A build
that cannot show these files is a build that may not be distributed.

The consequence for the code is that *failing to find a file must be loud*.  A
missing licence text is a compliance defect; showing a blank pane would hide it
from exactly the person who could fix it, so the pane names the file it could
not read and where it looked.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPlainTextEdit,
                               QSplitter, QVBoxLayout, QWidget)

__all__ = ["LicensesDialog", "resource_root", "NOTICES_NAME", "LICENSES_DIR"]

NOTICES_NAME = "THIRD-PARTY-NOTICES.md"
LICENSES_DIR = "LICENSES"

_ROLE_PATH = int(Qt.ItemDataRole.UserRole)


def resource_root() -> Path:
    """Directory holding ``THIRD-PARTY-NOTICES.md`` and ``LICENSES/``.

    Two deployments have to work.  Under PyInstaller the data files are unpacked
    beside the interpreter and ``sys._MEIPASS`` names that directory.  In a
    source checkout (and in an editable install) the files sit at the repository
    root, some way above this module, so we walk up until both landmarks appear
    rather than hard-coding a parent count that a future move would silently
    break.

    Falls back to the highest ancestor searched, so callers always get a real
    path to name in an error message instead of ``None``.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)

    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / NOTICES_NAME).is_file() and (candidate / LICENSES_DIR).is_dir():
            return candidate
    # No landmark found: point at the distribution root we would expect, which
    # is where the packaging step is supposed to place these files.
    return here.parents[min(3, len(here.parents) - 1)]


def _title_for(path: Path) -> str:
    """Human-readable component name for the list on the left."""
    if path.name == NOTICES_NAME:
        return "Third-party notices"
    return path.stem


def _discover(root: Path) -> list[Path]:
    """Every document the dialog should offer, notices first.

    ``THIRD-PARTY-NOTICES.md`` is listed even when absent so its absence is
    visible in the UI; the licence directory can only be enumerated if it
    exists, and an empty one is reported by the placeholder message instead.
    """
    documents: list[Path] = [root / NOTICES_NAME]
    licenses = root / LICENSES_DIR
    if licenses.is_dir():
        documents.extend(sorted(p for p in licenses.iterdir()
                                if p.is_file() and p.suffix.lower() in (".txt", ".md")))
    return documents


def read_document(path: Path) -> str:
    """Text of one licence document, or an explicit report of why there is none.

    Never raises and never returns an empty string for a missing file: silence
    here would turn a distribution defect into an invisible one.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return (f"Missing licence file: {path.name}\n\n"
                f"Expected at: {path}\n\n"
                "This file is required to be distributed with MakeYourTree Studio. "
                "The installation is incomplete; please reinstall or report this "
                "to the vendor.")
    except OSError as exc:
        return (f"Could not read licence file: {path.name}\n\n"
                f"Expected at: {path}\n\n{exc}")


class LicensesDialog(QDialog):
    """Component list on the left, full licence text on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Third-Party Licences")
        self.setObjectName("licensesDialog")
        self.resize(880, 620)

        self._root = resource_root()
        self._documents = _discover(self._root)

        heading = QLabel(
            "MakeYourTree Studio includes the components below. Each is governed by "
            "its own licence, reproduced here in full.")
        heading.setWordWrap(True)

        self._list = QListWidget()
        self._list.setObjectName("componentList")
        for path in self._documents:
            item = QListWidgetItem(_title_for(path))
            item.setData(_ROLE_PATH, str(path))
            if not path.is_file():
                item.setToolTip(f"Missing: {path}")
            self._list.addItem(item)

        self._text = QPlainTextEdit()
        self._text.setObjectName("licenseText")
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # A monospaced view keeps the ASCII layout of the GPL texts intact.
        font = self._text.font()
        font.setStyleHint(font.StyleHint.Monospace)
        font.setFamily("monospace")
        self._text.setFont(font)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._list)
        splitter.addWidget(self._text)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 660])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        body = QHBoxLayout()
        body.addWidget(splitter)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

        self._list.currentRowChanged.connect(self._show_row)
        if self._documents:
            self._list.setCurrentRow(0)

    # ------------------------------------------------------------- queries

    @property
    def root(self) -> Path:
        """Where the dialog looked for licence files."""
        return self._root

    def component_names(self) -> list[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]

    def document_paths(self) -> list[Path]:
        return list(self._documents)

    def text_for(self, name: str) -> str:
        """Full text shown for the component listed as *name*.

        Raises ``KeyError`` rather than returning a placeholder for an unknown
        name, so a typo in a caller is not mistaken for a missing licence.
        """
        for path in self._documents:
            if _title_for(path) == name:
                return read_document(path)
        raise KeyError(f"no licence document named {name!r}")

    def missing_documents(self) -> list[Path]:
        """Documents that should be present but are not.  Empty is compliant."""
        return [p for p in self._documents if not p.is_file()]

    # -------------------------------------------------------------- slots

    def _show_row(self, row: int) -> None:
        if row < 0 or row >= len(self._documents):
            self._text.setPlainText("")
            return
        self._text.setPlainText(read_document(self._documents[row]))
        self._text.moveCursor(self._text.textCursor().MoveOperation.Start)
