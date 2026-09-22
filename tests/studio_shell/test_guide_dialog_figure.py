# SPDX-License-Identifier: MIT
"""The guide window's "Read a published figure..." button, clicked for real.

It once raised on every click: the dialog stored its scroll-area widget as
``self._host``, which replaced the ``_host()`` method used to reach the main
window, so the file chooser never opened and nothing but a traceback on the
console said why. No test drove the button, so nothing caught it.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from makeyourtree_studio.dialogs.guide_dialog import GuideDialog

pytest.importorskip("PySide6.QtPdf")


def _ring_png(path) -> None:
    image = QImage(240, 240, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QPen(QColor("black"), 30))
    painter.drawEllipse(40, 40, 160, 160)
    painter.end()
    assert image.save(str(path))


def test_reading_a_figure_opens_the_chooser_and_reports(window, qapp, tmp_path):
    figure = tmp_path / "published.png"
    _ring_png(figure)
    window.open_answer = str(figure)
    dialog = GuideDialog(window)
    try:
        dialog._figure_button.click()
        assert window.asked == ["Read a published figure"]
        assert window.errors == []
        [(title, body)] = window.infos
        assert title == "What the figure showed"
        assert "circle" in body
        assert "Do you have a shape in mind?" in body, \
            "names the question it filled in, not an internal id"
        assert dialog._session.answers.get("shape") == "circular"
    finally:
        dialog.deleteLater()


def test_cancelling_the_chooser_changes_nothing(window, qapp):
    window.open_answer = ""
    dialog = GuideDialog(window)
    try:
        dialog._figure_button.click()
        assert window.asked == ["Read a published figure"]
        assert window.errors == [] and window.infos == []
        assert dialog._session.answers == {}
    finally:
        dialog.deleteLater()
