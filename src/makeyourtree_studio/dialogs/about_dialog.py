# SPDX-License-Identifier: MIT
"""Product identity, exact component versions, and the independence disclaimer.

The version block is not vanity.  LGPL-3.0 §4(d)(1) gives the user the right to
replace the bundled Qt with their own build, and they cannot exercise that right
without knowing which Qt this binary was linked against -- Qt guarantees binary
compatibility only within a minor series.  So the exact ``qVersion()`` string is
shown, not a marketing version and not the version PySide6 was compiled against.

The disclaimer accompanies every user-facing mention of comparable software, so
that no one reads a comparison as a claim of affiliation.
"""

from __future__ import annotations

import platform
from typing import TYPE_CHECKING

import PySide6
from PySide6.QtCore import Qt, qVersion
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QVBoxLayout, QWidget)

from makeyourtree import __version__ as makeyourtree_version

if TYPE_CHECKING:
    from .licenses_dialog import LicensesDialog

__all__ = ["AboutDialog", "PRODUCT_NAME", "TAGLINE", "DISCLAIMER",
           "version_rows"]

PRODUCT_NAME = "MakeYourTree Studio"
TAGLINE = ("An offline desktop studio for visualising and annotating "
           "phylogenetic trees.")
DISCLAIMER = ("Independent project; not affiliated with, endorsed by, or "
              "derived from any other phylogenetics package.")


def version_rows() -> list[tuple[str, str]]:
    """Label/value pairs for the version table, in display order.

    Split out from the widget so a support-bundle exporter, a crash report and
    the dialog all quote identical strings.
    """
    return [
        ("MakeYourTree", makeyourtree_version),
        ("Qt", qVersion()),
        ("PySide6", PySide6.__version__),
        ("Python", platform.python_version()),
        ("Platform", f"{platform.system()} {platform.release()} "
                     f"({platform.machine()})"),
    ]


class AboutDialog(QDialog):
    """Who made this, which version it is, and what it is not affiliated with."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {PRODUCT_NAME}")
        self.setObjectName("aboutDialog")

        title = QLabel(PRODUCT_NAME)
        title_font = title.font()
        title_font.setPointSizeF(title_font.pointSizeF() * 1.6)
        title_font.setBold(True)
        title.setFont(title_font)

        tagline = QLabel(TAGLINE)
        tagline.setWordWrap(True)

        versions = QFormLayout()
        versions.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for label, value in version_rows():
            value_label = QLabel(value)
            value_label.setObjectName(f"version.{label.lower()}")
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            versions.addRow(QLabel(label + ":"), value_label)

        disclaimer = QLabel(DISCLAIMER)
        disclaimer.setObjectName("disclaimer")
        disclaimer.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._licences_button = buttons.addButton(
            "Third-Party Licences", QDialogButtonBox.ButtonRole.ActionRole)
        self._licences_button.setObjectName("thirdPartyLicencesButton")
        self._licences_button.clicked.connect(self.show_licenses)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(tagline)
        layout.addSpacing(8)
        layout.addLayout(versions)
        layout.addSpacing(8)
        layout.addWidget(disclaimer)
        layout.addStretch(1)
        layout.addWidget(buttons)

    # ------------------------------------------------------------- queries

    def summary_text(self) -> str:
        """Everything the dialog states, as one plain-text block.

        Used by the tests and by "copy version info" support workflows, so the
        two can never drift from what is on screen.
        """
        lines = [PRODUCT_NAME, TAGLINE, ""]
        lines += [f"{label}: {value}" for label, value in version_rows()]
        lines += ["", DISCLAIMER]
        return "\n".join(lines)

    @property
    def licences_button(self):
        """The button that opens :class:`LicensesDialog`."""
        return self._licences_button

    # -------------------------------------------------------------- slots

    def show_licenses(self) -> "LicensesDialog":
        """Open the licence texts.  Returns the dialog so callers can drive it."""
        from .licenses_dialog import LicensesDialog

        dialog = LicensesDialog(self)
        dialog.open()
        return dialog
