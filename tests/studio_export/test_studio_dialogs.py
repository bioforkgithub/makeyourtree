# SPDX-License-Identifier: MIT
"""About and third-party licence dialogs.

The licence tests are compliance tests, not UI tests. LGPL-3.0 §4(a) and §4(c)
require the notices and the full licence texts to be reachable while the program
runs; if this dialog cannot find and display them, the build may not be
distributed. Asserting that each document is present *and non-empty* is the
runtime half of the check that ``tests/test_licensing.py`` performs on the repo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import qVersion

from makeyourtree import __version__ as makeyourtree_version
from makeyourtree_studio.dialogs.about_dialog import (DISCLAIMER, PRODUCT_NAME,
                                                  AboutDialog, version_rows)
from makeyourtree_studio.dialogs.licenses_dialog import (LICENSES_DIR,
                                                     NOTICES_NAME,
                                                     LicensesDialog,
                                                     read_document,
                                                     resource_root)

REQUIRED_DOCUMENTS = ("Third-party notices", "MIT", "GPL-3.0", "LGPL-3.0")

REPO_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------ resource_root


def test_resource_root_finds_the_source_checkout(qapp):
    root = resource_root()
    assert (root / NOTICES_NAME).is_file()
    assert (root / LICENSES_DIR).is_dir()
    assert root == REPO_ROOT


def test_resource_root_prefers_a_pyinstaller_bundle(monkeypatch, tmp_path):
    """Inside a onedir bundle the data files sit at ``sys._MEIPASS``."""
    import sys

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resource_root() == tmp_path


# ---------------------------------------------------------- LicensesDialog


def test_licenses_dialog_constructs_offscreen(qapp):
    dialog = LicensesDialog()
    assert dialog.windowTitle() == "Third-Party Licences"
    dialog.deleteLater()


def test_licenses_dialog_lists_every_required_document(qapp):
    dialog = LicensesDialog()
    names = dialog.component_names()
    for required in REQUIRED_DOCUMENTS:
        assert required in names, f"{required} is not offered at runtime"
    dialog.deleteLater()


@pytest.mark.parametrize("name", REQUIRED_DOCUMENTS)
def test_licenses_dialog_loads_non_empty_text(qapp, name):
    dialog = LicensesDialog()
    text = dialog.text_for(name)
    assert text.strip(), f"{name} rendered empty; that is a compliance failure"
    assert not text.startswith("Missing licence file")
    dialog.deleteLater()


def test_the_gpl_texts_are_the_real_ones(qapp):
    """A truncated placeholder would satisfy "non-empty" but not the licence."""
    dialog = LicensesDialog()
    assert "GNU GENERAL PUBLIC LICENSE" in dialog.text_for("GPL-3.0")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in dialog.text_for("LGPL-3.0")
    assert "MIT License" in dialog.text_for("MIT")
    assert "PySide6" in dialog.text_for("Third-party notices")
    dialog.deleteLater()


def test_nothing_is_missing_in_this_checkout(qapp):
    dialog = LicensesDialog()
    assert dialog.missing_documents() == []
    dialog.deleteLater()


def test_selecting_a_component_shows_its_text(qapp):
    dialog = LicensesDialog()
    index = dialog.component_names().index("MIT")
    dialog._list.setCurrentRow(index)
    assert "MIT License" in dialog._text.toPlainText()
    dialog.deleteLater()


def test_a_missing_file_names_itself_rather_than_failing_silently(tmp_path):
    """A blank pane would hide a distribution defect from the only person who
    could report it, so the reader returns an explicit report instead."""
    absent = tmp_path / "LGPL-3.0.txt"
    message = read_document(absent)
    assert "LGPL-3.0.txt" in message
    assert str(absent) in message
    assert "Missing licence file" in message


def test_unknown_component_raises_rather_than_looking_missing(qapp):
    dialog = LicensesDialog()
    with pytest.raises(KeyError):
        dialog.text_for("Not A Component")
    dialog.deleteLater()


# ------------------------------------------------------------- AboutDialog


def test_about_dialog_constructs_offscreen(qapp):
    dialog = AboutDialog()
    assert PRODUCT_NAME in dialog.windowTitle()
    dialog.deleteLater()


def test_about_dialog_carries_the_independence_disclaimer(qapp):
    dialog = AboutDialog()
    assert DISCLAIMER in dialog.summary_text()
    assert "not affiliated with, endorsed by, or derived from" in DISCLAIMER
    dialog.deleteLater()


def test_about_dialog_reports_the_exact_qt_version(qapp):
    """LGPL-3.0 §4(d)(1) is unusable without knowing which Qt was linked."""
    dialog = AboutDialog()
    summary = dialog.summary_text()
    assert f"Qt: {qVersion()}" in summary
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", qVersion()), (
        "qVersion() must be a real version string, not a placeholder")
    dialog.deleteLater()


def test_about_dialog_reports_pyside_python_and_makeyourtree_versions(qapp):
    import platform

    import PySide6

    rows = dict(version_rows())
    assert rows["PySide6"] == PySide6.__version__
    assert rows["Python"] == platform.python_version()
    assert rows["MakeYourTree"] == makeyourtree_version


def test_about_dialog_opens_the_licences_dialog(qapp):
    dialog = AboutDialog()
    assert dialog.licences_button is not None
    licences = dialog.show_licenses()
    assert isinstance(licences, LicensesDialog)
    assert licences.component_names()
    licences.close()
    licences.deleteLater()
    dialog.deleteLater()
