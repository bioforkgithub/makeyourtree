# SPDX-License-Identifier: MIT
"""The tracks dock: the annotation stack and the selected track's options.

Track *membership* and *order* are session operations -- ``add_track``,
``remove_track``, ``move_track``, ``set_track_visible`` -- because they change
what the document contains. Track *options* are not: the frozen session contract
has no setter for them, and inventing one here would fork the contract. So an
option edit writes to the track the document already owns and then calls
``session.invalidate(Dirty.LAYOUT)``, which is a session method and which is what
makes the change appear. Track options are figure settings rather than tree
edits, so like the layout parameters they stay off the undo stack.

The options form is generated, not hand-written. There are thirteen track types
and each has between six and thirty options; a hand-built form per type would be
thirteen forms to keep in step with the core. Instead the widget is inferred from
the *value* in ``default_options()``: booleans get a checkbox, numbers a spin
box, colour-ish keys a colour button, everything else a line edit. The cost of
inference is that a ``None`` default carries no type, so those get a text field
that parses back to a number when it can and to ``None`` when it is empty.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListView,
                               QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from makeyourtree.tracks.base import Track, track_types

from ..models.track_model import TrackModel
from ..session import Dirty, Session
from . import ColorButton, as_color

__all__ = ["TracksPanel", "TrackTypeDialog"]

_COLOUR_HINTS = ("color", "colour", "fill", "stroke")


def _looks_like_colour(key: str, value: Any) -> bool:
    """True when an option should be edited with a colour button.

    Keyed on the option *name* rather than on the value, because the common case
    is a colour option whose default is ``None`` -- there is nothing in the value
    to inspect. Names such as ``color_column`` are excluded: they hold a column
    index, not a colour, and a colour button would silently destroy the data.
    """
    k = key.lower()
    if k.endswith(("_column", "_columns", "_labels", "_format", "_mode")):
        return False
    if not any(h in k for h in _COLOUR_HINTS):
        return False
    return value is None or isinstance(value, str)


class TrackTypeDialog(QDialog):
    """Chooser listing every registered track type.

    Built from :func:`makeyourtree.tracks.track_types` rather than a hard-coded
    list, so a track type added to the core appears here with no change to the
    studio.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add track")
        self.list = QListWidget(self)
        for klass in track_types():
            item = QListWidgetItem(klass.display_name or klass.type_id)
            item.setData(Qt.ItemDataRole.UserRole, klass.type_id)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        buttons = QDialogButtonBox(self)
        buttons.setStandardButtons(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Track type", self))
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons)

    def selected_type_id(self) -> str | None:
        item = self.list.currentItem()
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole))


class TracksPanel(QWidget):
    """The track stack, its ordering controls, and a generated options form."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._loading = False
        self._editors: dict[str, QWidget] = {}
        self._current_id: str | None = None

        self.model = TrackModel(session, self)
        self.view = QListView(self)
        self.view.setModel(self.model)
        self.view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove)
        self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.view.setDragDropOverwriteMode(False)
        self.view.selectionModel().currentChanged.connect(
            self._on_current_changed)

        self.add_button = QPushButton("Add track...", self)
        self.remove_button = QPushButton("Remove", self)
        self.up_button = QPushButton("Up", self)
        self.down_button = QPushButton("Down", self)
        self.visible_button = QPushButton("Hide", self)
        self.add_button.clicked.connect(self.choose_track_type)
        self.remove_button.clicked.connect(self.remove_selected)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        self.visible_button.clicked.connect(self.toggle_selected_visible)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        for b in (self.add_button, self.remove_button, self.up_button,
                  self.down_button, self.visible_button):
            buttons.addWidget(b)
        buttons.addStretch(1)

        self.options_host = QWidget(self)
        self.options_form = QFormLayout(self.options_host)
        options_scroll = QScrollArea(self)
        options_scroll.setWidgetResizable(True)
        options_scroll.setWidget(self.options_host)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.view, 1)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("Options", self))
        layout.addWidget(options_scroll, 2)

        session.tracksChanged.connect(self._on_tracks_changed)
        session.documentReplaced.connect(self._on_tracks_changed)
        self.rebuild_options()

    # ---------------------------------------------------------------- state

    @property
    def session(self) -> Session:
        return self._session

    def selected_track(self) -> Track | None:
        idx = self.view.currentIndex()
        if not idx.isValid():
            return None
        return self.model.track_at(idx.row())

    def select_track(self, track_id: str) -> None:
        row = self.model.row_of(track_id)
        if row >= 0:
            self.view.setCurrentIndex(self.model.index(row, 0, QModelIndex()))

    # ------------------------------------------------------------ the stack

    def choose_track_type(self) -> None:
        """Open the type chooser and add whatever it returns."""
        dialog = TrackTypeDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            type_id = dialog.selected_type_id()
            if type_id:
                self.add_track_of_type(type_id)

    def add_track_of_type(self, type_id: str) -> Track | None:
        """Append an empty track of *type_id* and select it.

        Empty on purpose: binding data is the import dialog's job, and a track
        with no rows still measures and draws as a blank band, which is the
        honest picture of "you added it but have not fed it yet".
        """
        from makeyourtree.tracks.base import get_track_class
        try:
            klass = get_track_class(type_id)
        except KeyError as exc:
            self._session.statusMessage.emit(str(exc), 4000)
            return None
        track = klass(title=klass.display_name or klass.type_id)
        self._session.add_track(track)
        self.select_track(track.id)
        return track

    def remove_selected(self) -> None:
        track = self.selected_track()
        if track is None:
            return
        self._session.remove_track(track.id)

    def move_selected(self, delta: int) -> None:
        track = self.selected_track()
        if track is None:
            return
        row = self.model.row_of(track.id)
        if self.model.move_track_to(track.id, row + delta):
            self.select_track(track.id)

    def toggle_selected_visible(self) -> None:
        track = self.selected_track()
        if track is None:
            return
        self._session.set_track_visible(track.id, not track.visible)

    # -------------------------------------------------------------- options

    def rebuild_options(self) -> None:
        """Regenerate the options form for the currently selected track."""
        self._loading = True
        try:
            while self.options_form.rowCount():
                self.options_form.removeRow(0)
            self._editors.clear()
            track = self.selected_track()
            self.remove_button.setEnabled(track is not None)
            self.up_button.setEnabled(track is not None)
            self.down_button.setEnabled(track is not None)
            self.visible_button.setEnabled(track is not None)
            if track is None:
                self.options_form.addRow(QLabel("No track selected"))
                return
            self.visible_button.setText("Show" if not track.visible else "Hide")
            title = QLineEdit(track.title)
            title.editingFinished.connect(
                lambda w=title: self._set_title(w.text()))
            self.options_form.addRow("Title", title)
            self._editors["__title__"] = title
            for key in sorted(track.options):
                widget = self._editor_for(track, key, track.options[key])
                if widget is not None:
                    self.options_form.addRow(key.replace("_", " "), widget)
                    self._editors[key] = widget
        finally:
            self._loading = False

    def _editor_for(self, track: Track, key: str, value: Any) -> QWidget | None:
        if isinstance(value, bool):
            w = QCheckBox()
            w.setChecked(value)
            w.toggled.connect(lambda on, k=key: self._set_option(k, bool(on)))
            return w
        if _looks_like_colour(key, value):
            w = ColorButton(as_color(value))
            w.colorChanged.connect(
                lambda c, k=key: self._set_option(k, None if c is None else c.hex))
            return w
        if isinstance(value, int):
            w = QSpinBox()
            w.setRange(-1_000_000, 1_000_000)
            w.setKeyboardTracking(False)
            w.setValue(value)
            w.valueChanged.connect(lambda v, k=key: self._set_option(k, int(v)))
            return w
        if isinstance(value, float):
            w = QDoubleSpinBox()
            w.setRange(-1e9, 1e9)
            w.setDecimals(3)
            w.setKeyboardTracking(False)
            w.setValue(value)
            w.valueChanged.connect(
                lambda v, k=key: self._set_option(k, float(v)))
            return w
        if isinstance(value, (dict, list, tuple)):
            # Structured options -- per-column colour maps, gradient stops -- have
            # no sensible one-line editor. Showing a read-only summary is better
            # than a line edit whose text would be parsed back wrongly.
            label = QLabel("%d entr%s (edit on import)"
                           % (len(value), "y" if len(value) == 1 else "ies"))
            label.setEnabled(False)
            return label
        w = QLineEdit("" if value is None else str(value))
        w.setPlaceholderText("default")
        w.editingFinished.connect(
            lambda k=key, e=w: self._set_option(k, _parse_text(e.text())))
        return w

    def _set_option(self, key: str, value: Any) -> None:
        track = self.selected_track()
        if self._loading or track is None:
            return
        if track.options.get(key) == value:
            return
        track.options[key] = value
        self._session.invalidate(Dirty.LAYOUT)

    def _set_title(self, text: str) -> None:
        track = self.selected_track()
        if self._loading or track is None or track.title == text:
            return
        track.title = text
        self._session.tracksChanged.emit()
        self._session.invalidate(Dirty.LAYOUT)

    # -------------------------------------------------------------- refresh

    def _on_current_changed(self, current: QModelIndex,
                            _previous: QModelIndex) -> None:
        """Remember which track is current, by id rather than by row.

        Rows are not stable: the model resets on every ``tracksChanged``, and a
        reorder changes what row 2 means. The id is what the user is pointing at.
        """
        if current.isValid():
            track = self.model.track_at(current.row())
            if track is not None:
                self._current_id = track.id
        self.rebuild_options()

    def _on_tracks_changed(self) -> None:
        """Keep the selection on the same track across a model reset.

        The model resets wholesale on every ``tracksChanged`` -- and it is
        connected first, so by the time this runs the view has already lost its
        current index. Reselecting by remembered id is what stops a reorder from
        blanking the options form the user was working in.
        """
        if self._current_id is not None and self.model.row_of(self._current_id) >= 0:
            self.select_track(self._current_id)
        elif self.model.rowCount():
            self.view.setCurrentIndex(self.model.index(0, 0, QModelIndex()))
        else:
            self._current_id = None
        self.rebuild_options()


def _parse_text(text: str) -> Any:
    """Parse a free-text option back to the narrowest type that fits.

    Blank means "unset" and must become ``None``, not ``""``: several tracks
    treat the empty string as a real value (a label that is deliberately blank)
    and would then draw nothing where a default was wanted.
    """
    s = text.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s
