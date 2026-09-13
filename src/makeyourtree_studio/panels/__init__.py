# SPDX-License-Identifier: MIT
"""Dock panels, and the few widgets more than one of them needs.

This module deliberately does **not** re-export the panel classes. Two panels
share the colour button below, so a panel module imports from this package; if
the package also imported the panel modules the two would form a cycle whose
resolution depended on which name a caller happened to import first. Callers
import the concrete module instead -- ``from makeyourtree_studio.panels.style_panel
import StylePanel``.

Every panel obeys the same rule, which is the reason the session exists: read
state from the session, write it back through a session method, and refresh from
the session's signals. A panel never holds a reference to another panel, and
never calls ``Command.apply`` -- only ``Session.do``, which is what puts the edit
on the undo stack.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QColorDialog, QPushButton, QWidget

from makeyourtree.style.color import Color, parse_color

__all__ = ["ColorButton", "to_qcolor", "from_qcolor", "as_color"]


def to_qcolor(color: Color | None) -> QColor:
    """Core colour to Qt colour. ``None`` becomes an invalid ``QColor``."""
    if color is None:
        return QColor()
    return QColor(color.r, color.g, color.b, color.a)


def from_qcolor(qc: QColor) -> Color | None:
    if not qc.isValid():
        return None
    return Color(qc.red(), qc.green(), qc.blue(), qc.alpha())


def as_color(value: Any) -> Color | None:
    """Best-effort coercion of a stored option value to a :class:`Color`.

    Track options hold colours as hex strings because that is what survives JSON,
    while node styles hold real ``Color`` objects. The options editor has to cope
    with both, and with a value that simply is not a colour at all -- in which
    case ``None`` (meaning "inherit") is the honest answer rather than an
    exception that would take the whole panel down.
    """
    if value is None or value == "":
        return None
    if isinstance(value, Color):
        return value
    try:
        return parse_color(value)
    except Exception:
        return None


class ColorButton(QPushButton):
    """A swatch that opens a colour dialog.

    ``None`` is a real value here, not an absence to be papered over: for a node
    style it means "inherit", and for a track option it means "use the theme".
    The button shows it as an empty swatch and ``allow_clear`` offers a way back
    to it, because a user who colours a clade by accident must be able to undo the
    *decision*, not just pick a colour that looks similar to the default.
    """

    colorChanged = Signal(object)

    def __init__(self, color: Color | None = None, *, allow_clear: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color: Color | None = color
        self._allow_clear = allow_clear
        self.setFlat(True)
        self.setIconSize(QSize(16, 16))
        self._refresh()
        self.clicked.connect(self.pick)

    def color(self) -> Color | None:
        return self._color

    def set_color(self, color: Color | None, *, notify: bool = False) -> None:
        """Show *color*. Silent by default so a panel can reload without echoing."""
        if color == self._color:
            return
        self._color = color
        self._refresh()
        if notify:
            self.colorChanged.emit(color)

    def pick(self) -> None:
        """Open the colour dialog and adopt the result."""
        opts = QColorDialog.ColorDialogOption.ShowAlphaChannel
        qc = QColorDialog.getColor(to_qcolor(self._color), self,
                                   "Choose colour", opts)
        if qc.isValid():
            self.set_color(from_qcolor(qc), notify=True)

    def clear_color(self) -> None:
        if self._allow_clear:
            self.set_color(None, notify=True)

    def _refresh(self) -> None:
        pm = QPixmap(16, 16)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        if self._color is None:
            p.setPen(QColor(120, 120, 130))
            p.drawRect(0, 0, 15, 15)
            p.drawLine(0, 15, 15, 0)
        else:
            p.fillRect(0, 0, 16, 16, to_qcolor(self._color))
            p.setPen(QColor(90, 90, 100))
            p.drawRect(0, 0, 15, 15)
        p.end()
        self.setIcon(QIcon(pm))
        self.setText("inherit" if self._color is None else self._color.hex)
        self.setToolTip("No override; inherits the theme"
                        if self._color is None else self._color.hex)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
