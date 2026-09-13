# SPDX-License-Identifier: MIT
"""A list model over ``session.document.tracks``.

The track stack is short -- tens of entries, not thousands -- so this model does
not need the laziness the tree model needs, and it can afford a full reset on
every ``tracksChanged``. That simplicity buys something worth having: reordering
is expressed purely as a call to :meth:`Session.move_track`, and the model
rebuilds from whatever the document then says. There is no second copy of the
order to drift out of step with the document's.

Drag and drop therefore does *not* move rows itself. ``moveRows`` and
``dropMimeData`` both delegate to the session and let the resulting
``tracksChanged`` reset the view. Moving the rows here as well would apply the
move twice.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (QAbstractListModel, QMimeData, QModelIndex, Qt)

from makeyourtree.tracks.base import Track

from ..session import Session

__all__ = ["TrackModel", "TRACK_MIME"]

TRACK_MIME = "application/x-makeyourtree-track-row"
"""Private drag payload: the source row index, as ASCII digits."""


class TrackModel(QAbstractListModel):
    """One row per track: title, type, visibility checkbox and row count."""

    TrackIdRole = int(Qt.ItemDataRole.UserRole) + 1
    TrackTypeRole = int(Qt.ItemDataRole.UserRole) + 2
    RowCountRole = int(Qt.ItemDataRole.UserRole) + 3

    def __init__(self, session: Session, parent: Any = None) -> None:
        super().__init__(parent)
        self._session = session
        session.tracksChanged.connect(self._reset)
        session.documentReplaced.connect(self._reset)

    # ------------------------------------------------------------- contents

    @property
    def session(self) -> Session:
        return self._session

    @property
    def tracks(self) -> list[Track]:
        return self._session.document.tracks

    def track_at(self, row: int) -> Track | None:
        tracks = self.tracks
        if 0 <= row < len(tracks):
            return tracks[row]
        return None

    def row_of(self, track_id: str) -> int:
        for i, t in enumerate(self.tracks):
            if t.id == track_id:
                return i
        return -1

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.tracks)

    def data(self, index: QModelIndex,
             role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        track = self.track_at(index.row()) if index.isValid() else None
        if track is None:
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return track.title or track.display_name or track.type_id
        if role == Qt.ItemDataRole.CheckStateRole:
            return (Qt.CheckState.Checked if track.visible
                    else Qt.CheckState.Unchecked)
        if role == self.TrackIdRole:
            return track.id
        if role == self.TrackTypeRole:
            return track.display_name or track.type_id
        if role == self.RowCountRole:
            return len(track.data)
        if role == Qt.ItemDataRole.ToolTipRole:
            return "%s - %d row(s)" % (track.display_name or track.type_id,
                                       len(track.data))
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDropEnabled)
        if not index.isValid():
            return base
        return (base | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsDragEnabled)

    def setData(self, index: QModelIndex, value: Any,
                role: int = Qt.ItemDataRole.EditRole) -> bool:
        track = self.track_at(index.row()) if index.isValid() else None
        if track is None:
            return False
        if role == Qt.ItemDataRole.CheckStateRole:
            want = Qt.CheckState(value) is Qt.CheckState.Checked
            self._session.set_track_visible(track.id, want)
            return True
        return False

    # ------------------------------------------------------------- reorder

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [TRACK_MIME]

    def mimeData(self, indexes: Any) -> QMimeData:
        md = QMimeData()
        rows = sorted({i.row() for i in indexes if i.isValid()})
        if rows:
            md.setData(TRACK_MIME, str(rows[0]).encode("ascii"))
        return md

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int,
                     column: int, parent: QModelIndex) -> bool:
        if action is Qt.DropAction.IgnoreAction:
            return True
        if not data.hasFormat(TRACK_MIME):
            return False
        try:
            src = int(bytes(data.data(TRACK_MIME)).decode("ascii"))
        except ValueError:
            return False
        dest = row if row >= 0 else (parent.row() if parent.isValid()
                                     else len(self.tracks))
        return self.moveRows(QModelIndex(), src, 1, QModelIndex(), dest)

    def moveRows(self, sourceParent: QModelIndex, sourceRow: int, count: int,
                 destinationParent: QModelIndex, destinationChild: int) -> bool:
        """Move one track, expressed in Qt's pre-removal row coordinates.

        Qt names the destination as the row the item would occupy *before* the
        source is taken out, while :meth:`Document.move_track` inserts *after*
        the removal. Translating between the two is the whole of this method;
        getting it wrong shifts every downward drag by one.
        """
        if sourceParent.isValid() or destinationParent.isValid() or count != 1:
            return False
        n = len(self.tracks)
        if not (0 <= sourceRow < n) or not (0 <= destinationChild <= n):
            return False
        if destinationChild in (sourceRow, sourceRow + 1):
            return False
        target = (destinationChild if destinationChild < sourceRow
                  else destinationChild - 1)
        self._session.move_track(self.tracks[sourceRow].id, target)
        return True

    def move_track_to(self, track_id: str, index: int) -> bool:
        """Reorder by id, in final-position coordinates.

        The buttons in the tracks panel think in "move this one up by one", not
        in Qt's drop coordinates, so they call this rather than ``moveRows``.
        """
        row = self.row_of(track_id)
        if row < 0 or index < 0 or index >= len(self.tracks) or index == row:
            return False
        self._session.move_track(track_id, index)
        return True

    # --------------------------------------------------------------- reset

    def _reset(self) -> None:
        self.beginResetModel()
        self.endResetModel()
