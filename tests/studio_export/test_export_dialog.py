# SPDX-License-Identifier: MIT
"""The export dialog, checked against the files it actually produces.

The dialog's central promise is that the number in the "Output" label is the
number of pixels in the file. Every size test here exports for real and measures
the result rather than re-deriving the prediction, because a test that recomputed
the same arithmetic would agree with a wrong dialog just as happily.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage

from makeyourtree_studio.dialogs.export_dialog import (APPLICATION, ORGANISATION,
                                                   ExportDialog, ExportSettings)


def _select_format(dialog: ExportDialog, key: str) -> None:
    index = dialog._format.findData(key)
    assert index >= 0
    dialog._format.setCurrentIndex(index)


def _select_background(dialog: ExportDialog, key: str) -> None:
    index = dialog._background.findData(key)
    assert index >= 0
    dialog._background.setCurrentIndex(index)


@pytest.fixture
def dialog(qapp, session):
    d = ExportDialog(session)
    yield d
    d.deleteLater()


# ----------------------------------------------------------- construction


def test_dialog_constructs_offscreen(dialog):
    assert dialog.windowTitle() == "Export Figure"
    assert dialog._format.count() == 3
    assert dialog.predicted_size()[0] > 0
    assert dialog.predicted_size()[1] > 0


def test_defaults_to_png_at_the_figure_size(dialog):
    _select_format(dialog, "png")
    settings = dialog.settings()
    assert settings.format == "png"
    assert settings.is_raster
    assert settings.suffix == ".png"


def test_size_label_states_pixels_for_png_and_points_for_vector(dialog):
    _select_format(dialog, "png")
    assert "px" in dialog._size_label.text()
    _select_format(dialog, "svg")
    assert "pt" in dialog._size_label.text()


# ------------------------------------------------------ predicted vs real


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0, 3.0])
def test_predicted_pixels_match_the_exported_png(dialog, tmp_path, scale):
    _select_format(dialog, "png")
    dialog._scale.setValue(scale)
    predicted = dialog.predicted_size()

    path = tmp_path / f"scale_{scale}.png"
    dialog._path.setText(str(path))
    dialog.run_export()
    assert dialog.wait_for_export(20000), "export did not complete"

    image = QImage(str(path))
    assert not image.isNull()
    assert (image.width(), image.height()) == predicted


@pytest.mark.parametrize("width", [400, 813, 1600])
def test_typing_a_width_produces_exactly_that_width(dialog, tmp_path, width):
    """With the aspect lock on, the width the user types is the width they get."""
    _select_format(dialog, "png")
    dialog._lock.setChecked(True)
    dialog._width.setValue(width)
    predicted = dialog.predicted_size()
    assert predicted[0] == width

    path = tmp_path / f"width_{width}.png"
    dialog._path.setText(str(path))
    dialog.run_export()
    assert dialog.wait_for_export(20000)

    image = QImage(str(path))
    assert (image.width(), image.height()) == predicted


def test_unlocked_aspect_pads_the_page_and_still_predicts_exactly(dialog, tmp_path):
    """Unlocking lets the page grow; it must never crop and never mispredict."""
    _select_format(dialog, "png")
    dialog._scale.setValue(1.0)
    dialog._lock.setChecked(False)
    natural_h = dialog._height.value()
    dialog._height.setValue(natural_h + 250)
    predicted = dialog.predicted_size()
    assert predicted[1] == natural_h + 250

    path = tmp_path / "padded.png"
    dialog._path.setText(str(path))
    dialog.run_export()
    assert dialog.wait_for_export(20000)

    image = QImage(str(path))
    assert (image.width(), image.height()) == predicted


def test_width_cannot_be_set_below_the_figure(dialog):
    """Cropping is not on offer, so the spin box floor is the natural size."""
    _select_format(dialog, "png")
    dialog._scale.setValue(1.0)
    natural = dialog._width.value()
    dialog._lock.setChecked(False)
    dialog._width.setValue(1)
    assert dialog._width.value() == natural


def test_dpi_and_scale_stay_in_step(dialog):
    _select_format(dialog, "png")
    dialog._dpi.setValue(288)
    assert dialog._scale.value() == pytest.approx(4.0)
    dialog._scale.setValue(1.0)
    assert dialog._dpi.value() == 72


# ------------------------------------------------------------ other formats


def test_svg_export_writes_a_vector_file(dialog, tmp_path):
    _select_format(dialog, "svg")
    path = tmp_path / "figure.svg"
    dialog._path.setText(str(path))
    dialog.run_export()
    assert dialog.wait_for_export(20000)
    assert path.read_text(encoding="utf-8").startswith("<svg")


def test_pdf_export_writes_a_pdf(dialog, tmp_path):
    _select_format(dialog, "pdf")
    path = tmp_path / "figure.pdf"
    dialog._path.setText(str(path))
    dialog.run_export()
    assert dialog.wait_for_export(20000)
    assert path.read_bytes().startswith(b"%PDF")


def test_a_failed_export_reports_instead_of_writing_nothing(dialog, tmp_path):
    """An unwritable path must reach the user, not vanish on the worker thread."""
    _select_format(dialog, "png")
    dialog._path.setText(str(tmp_path / "no-such-directory" / "x.png"))
    failures: list[str] = []
    dialog.exportFailed.connect(failures.append)
    dialog.run_export()
    assert dialog.wait_for_export(20000) is False
    assert failures and failures[0]


# ------------------------------------------------------------- background


def test_transparent_background_reaches_the_file(dialog, tmp_path):
    _select_format(dialog, "png")
    _select_background(dialog, "transparent")
    dialog._scale.setValue(1.0)
    path = tmp_path / "clear.png"
    dialog._path.setText(str(path))
    dialog.run_export()
    assert dialog.wait_for_export(20000)
    assert QImage(str(path)).pixelColor(0, 0).alpha() == 0


def test_legend_toggle_changes_the_composed_page(dialog, session):
    """The legend is part of the exported page, so toggling it must resize it."""
    from makeyourtree.tracks.strip import ColorStripTrack

    track = ColorStripTrack(id="strip-test", title="Clade")
    track.bind(session.tree, {"alpha": ["red"], "beta": ["blue"]},
               columns=["value"], match_internal=False)
    session.add_track(track)

    dialog._legend.setChecked(True)
    dialog._on_legend_toggled(True)
    with_legend = dialog.build_scene()
    dialog._legend.setChecked(False)
    dialog._on_legend_toggled(False)
    without_legend = dialog.build_scene()

    assert with_legend.width >= without_legend.width
    assert session.theme.legend_show is True, "the live theme must be restored"


# --------------------------------------------------------------- settings


def test_settings_round_trip_through_qsettings(qapp, session, tmp_path):
    first = ExportDialog(session)
    _select_format(first, "pdf")
    _select_background(first, "white")
    first._legend.setChecked(False)
    first._lock.setChecked(False)
    first._scale.setValue(3.0)
    path = tmp_path / "remembered.pdf"
    first._path.setText(str(path))
    first.run_export()
    assert first.wait_for_export(20000)

    stored = QSettings(ORGANISATION, APPLICATION)
    stored.beginGroup("export")
    assert stored.value("format", type=str) == "pdf"
    assert stored.value("background", type=str) == "white"
    stored.endGroup()

    second = ExportDialog(session)
    assert second.settings().format == "pdf"
    assert second.settings().background == "white"
    assert second.settings().include_legend is False
    assert second.settings().lock_aspect is False
    first.deleteLater()
    second.deleteLater()


def test_export_settings_suffix_falls_back_for_an_unknown_format():
    assert ExportSettings(format="svg").suffix == ".svg"
    assert ExportSettings(format="nonsense").suffix == ".png"


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.5])
def test_the_label_and_the_exporter_agree_on_the_same_scene(dialog, scale):
    """The prediction is not a parallel calculation: composing the export scene
    and asking the exporter's own sizer must return the label's numbers."""
    from makeyourtree_studio.export.raster import png_size

    _select_format(dialog, "png")
    dialog._scale.setValue(scale)
    assert png_size(dialog.build_scene(), scale) == dialog.predicted_size()
