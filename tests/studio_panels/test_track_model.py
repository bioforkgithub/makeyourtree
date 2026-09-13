# SPDX-License-Identifier: MIT
"""The track list model: roles, visibility and reordering."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QModelIndex, Qt

from makeyourtree.doc.document import Document
from makeyourtree.tracks.base import get_track_class
from makeyourtree_studio.models.track_model import TRACK_MIME, TrackModel
from makeyourtree_studio.session import Session

from _panels_support import Counter, sample_tree, strip_track

ROOT = QModelIndex()


def _add(session: Session, title: str, type_id: str = "color-strip"):
    track = get_track_class(type_id)(title=title)
    session.add_track(track)
    return track


def test_empty_document_has_no_rows(studio: Session):
    model = TrackModel(studio)
    assert model.rowCount(ROOT) == 0


def test_rows_expose_title_type_visibility_and_row_count(studio: Session):
    track = strip_track(studio.tree, title="Region")
    studio.add_track(track)
    model = TrackModel(studio)
    idx = model.index(0, 0, ROOT)
    assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "Region"
    assert model.data(idx, TrackModel.TrackIdRole) == track.id
    assert model.data(idx, TrackModel.TrackTypeRole) == track.display_name
    assert model.data(idx, TrackModel.RowCountRole) == 2
    assert model.data(idx, Qt.ItemDataRole.CheckStateRole) is Qt.CheckState.Checked


def test_unchecking_a_row_hides_the_track(studio: Session):
    track = _add(studio, "Region")
    model = TrackModel(studio)
    idx = model.index(0, 0, ROOT)
    assert model.setData(idx, Qt.CheckState.Unchecked.value,
                         Qt.ItemDataRole.CheckStateRole)
    assert track.visible is False
    assert model.data(idx, Qt.ItemDataRole.CheckStateRole) is Qt.CheckState.Unchecked
    model.setData(idx, Qt.CheckState.Checked.value,
                  Qt.ItemDataRole.CheckStateRole)
    assert track.visible is True


def test_rows_are_draggable_and_the_view_is_a_drop_target(studio: Session):
    _add(studio, "A")
    model = TrackModel(studio)
    flags = model.flags(model.index(0, 0, ROOT))
    assert flags & Qt.ItemFlag.ItemIsDragEnabled
    assert flags & Qt.ItemFlag.ItemIsUserCheckable
    assert model.flags(ROOT) & Qt.ItemFlag.ItemIsDropEnabled
    assert model.supportedDropActions() is Qt.DropAction.MoveAction


@pytest.mark.parametrize(
    "source, destination, expected",
    [
        (2, 0, ["C", "A", "B"]),
        (0, 3, ["B", "C", "A"]),
        (0, 2, ["B", "A", "C"]),
        (1, 0, ["B", "A", "C"]),
    ],
)
def test_move_rows_uses_qt_pre_removal_coordinates(
        studio: Session, source: int, destination: int, expected: list[str]):
    for name in ("A", "B", "C"):
        _add(studio, name)
    model = TrackModel(studio)
    assert model.moveRows(ROOT, source, 1, ROOT, destination)
    assert [t.title for t in studio.document.tracks] == expected


def test_move_rows_refuses_a_no_op(studio: Session):
    for name in ("A", "B"):
        _add(studio, name)
    model = TrackModel(studio)
    assert not model.moveRows(ROOT, 0, 1, ROOT, 0)
    assert not model.moveRows(ROOT, 0, 1, ROOT, 1)
    assert not model.moveRows(ROOT, 5, 1, ROOT, 0)
    assert [t.title for t in studio.document.tracks] == ["A", "B"]


def test_move_track_to_uses_final_position_coordinates(studio: Session):
    for name in ("A", "B", "C"):
        _add(studio, name)
    model = TrackModel(studio)
    track = studio.document.tracks[2]
    assert model.move_track_to(track.id, 0)
    assert [t.title for t in studio.document.tracks] == ["C", "A", "B"]
    assert not model.move_track_to(track.id, 0)
    assert not model.move_track_to(track.id, -1)
    assert not model.move_track_to("no-such-track", 1)


def test_drop_mime_data_reorders_through_the_session(studio: Session):
    for name in ("A", "B", "C"):
        _add(studio, name)
    model = TrackModel(studio)
    payload = QMimeData()
    payload.setData(TRACK_MIME, b"2")
    assert model.dropMimeData(payload, Qt.DropAction.MoveAction, 0, 0, ROOT)
    assert [t.title for t in studio.document.tracks] == ["C", "A", "B"]
    assert model.mimeTypes() == [TRACK_MIME]


def test_drop_rejects_a_foreign_payload(studio: Session):
    _add(studio, "A")
    model = TrackModel(studio)
    payload = QMimeData()
    payload.setText("something else")
    assert not model.dropMimeData(payload, Qt.DropAction.MoveAction, 0, 0, ROOT)


def test_mime_data_carries_the_source_row(studio: Session):
    for name in ("A", "B"):
        _add(studio, name)
    model = TrackModel(studio)
    payload = model.mimeData([model.index(1, 0, ROOT)])
    assert bytes(payload.data(TRACK_MIME)) == b"1"


def test_model_resets_when_the_document_is_replaced(studio: Session):
    _add(studio, "A")
    model = TrackModel(studio)
    counter = Counter()
    model.modelReset.connect(counter)
    studio.set_document(Document(tree=sample_tree()))
    assert model.rowCount(ROOT) == 0
    assert counter.n >= 1


def test_removing_a_track_shortens_the_model(studio: Session):
    track = _add(studio, "A")
    _add(studio, "B")
    model = TrackModel(studio)
    assert model.rowCount(ROOT) == 2
    studio.remove_track(track.id)
    assert model.rowCount(ROOT) == 1
    assert model.row_of(track.id) == -1
