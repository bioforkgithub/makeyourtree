# SPDX-License-Identifier: MIT
"""The export dialog: choose a format and a size, then write the file.

Two design decisions carry most of the weight here.

**The predicted size is the produced size.**  The label shows the width and
height spin boxes verbatim, and the scene handed to the exporter is composed at
``pixels / scale`` scene units, so
:func:`~makeyourtree_studio.export.raster.png_size` gives those same pixels back.
"1600 x 1200 px" on screen is therefore exactly what lands on disk.  Anything
less and the figure has to be re-exported by trial and error, which is how
figures end up at the wrong size in a journal submission.

**The page can be padded but never cropped.**  ``makeyourtree.scene.compose`` treats
its *size* argument as a floor, so a requested page larger than the figure adds
whitespace and a smaller one is ignored.  The width and height controls therefore
have the natural size as their minimum: the aspect lock ties them to the figure's
own ratio, and unlocking lets the user pad out to a fixed canvas.  Cropping is
deliberately not offered, because silently cutting off a clade is worse than any
layout inconvenience.

Rasterising a 300-dpi poster takes seconds, so the write happens on a
``QThreadPool`` worker; ``QImage`` and ``QPdfWriter`` are both usable off the GUI
thread, and the dialog is modal, so the document cannot change underneath it.
"""

from __future__ import annotations

import dataclasses
import math
import os
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import (QEventLoop, QObject, QRunnable, QSettings,
                            QThreadPool, QTimer, Qt, Signal)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from makeyourtree.scene.marks import Scene
from makeyourtree.style.color import Color

from ..export.raster import export_pdf, export_png, export_svg
from ..session import Session

__all__ = ["ExportDialog", "ExportSettings", "FORMATS", "BACKGROUNDS",
           "ORGANISATION", "APPLICATION"]

ORGANISATION = "MakeYourTree"
APPLICATION = "MakeYourTree Studio"
_SETTINGS_GROUP = "export"

FORMATS: tuple[tuple[str, str, str], ...] = (
    ("svg", "SVG (vector)", ".svg"),
    ("png", "PNG (raster)", ".png"),
    ("pdf", "PDF (vector)", ".pdf"),
)
"""``(key, label, suffix)`` per supported format, in menu order."""

BACKGROUNDS: tuple[tuple[str, str], ...] = (
    ("theme", "Theme background"),
    ("white", "White"),
    ("transparent", "Transparent"),
)

_TRANSPARENT = Color(0, 0, 0, 0)
_WHITE = Color(255, 255, 255, 255)

_MAX_PIXELS = 60000
"""Upper bound on either output dimension.  Past this a ``QImage`` allocation
starts failing on ordinary machines, and a spin box that offers a size the
exporter cannot deliver is a broken promise."""

_POINTS_PER_INCH = 72.0

_PIXEL_EPS = 1e-6
"""Tolerance absorbing float round-trip error when a pixel size is converted
back into scene units and out again."""


@dataclass(slots=True)
class ExportSettings:
    """The dialog's state, in a form that survives a restart."""

    format: str = "png"
    scale: float = 2.0
    width: int = 0
    height: int = 0
    lock_aspect: bool = True
    background: str = "theme"
    include_legend: bool = True
    directory: str = ""

    @property
    def suffix(self) -> str:
        for key, _label, suffix in FORMATS:
            if key == self.format:
                return suffix
        return ".png"

    @property
    def is_raster(self) -> bool:
        return self.format == "png"

    def background_color(self) -> Color | None:
        """Colour to paint the page, or ``None`` to keep the theme's."""
        if self.background == "white":
            return _WHITE
        if self.background == "transparent":
            return _TRANSPARENT
        return None


class _ExportSignals(QObject):
    """``QRunnable`` cannot own signals, so the worker borrows these."""

    finished = Signal(str)
    failed = Signal(str)


class _ExportTask(QRunnable):
    """Runs one export off the GUI thread and reports the outcome."""

    def __init__(self, work: Callable[[], None], path: str,
                 signals: _ExportSignals) -> None:
        super().__init__()
        self._work = work
        self._path = path
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            self._work()
        except Exception as exc:                      # noqa: BLE001
            # A failed export must surface as a message, not as a silent
            # no-file; the worker thread has no other way to report.
            self._signals.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self._signals.finished.emit(self._path)


class ExportDialog(QDialog):
    """Format, size, background and legend for one figure export."""

    exportStarted = Signal()
    exportFinished = Signal(str)
    exportFailed = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._updating = False
        self._natural: tuple[float, float] = (0.0, 0.0)
        self._signals = _ExportSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)

        self.setWindowTitle("Export Figure")
        self.setObjectName("exportDialog")
        self.setModal(True)

        self._build_widgets()
        self._settings = QSettings(ORGANISATION, APPLICATION)
        self._load_settings()
        self._refresh_natural_size()
        self._sync_from_scale(self._scale.value())
        self._update_format_state()
        self._update_size_label()
        self._connect()

    # ------------------------------------------------------------- widgets

    def _build_widgets(self) -> None:
        self._format = QComboBox()
        self._format.setObjectName("formatCombo")
        for key, label, _suffix in FORMATS:
            self._format.addItem(label, key)

        self._path = QLineEdit()
        self._path.setObjectName("pathEdit")
        self._browse = QPushButton("Browse...")
        self._browse.setObjectName("browseButton")
        path_row = QHBoxLayout()
        path_row.addWidget(self._path, 1)
        path_row.addWidget(self._browse)

        self._width = QSpinBox()
        self._width.setObjectName("widthSpin")
        self._width.setRange(1, _MAX_PIXELS)
        self._height = QSpinBox()
        self._height.setObjectName("heightSpin")
        self._height.setRange(1, _MAX_PIXELS)
        self._lock = QCheckBox("Lock aspect ratio")
        self._lock.setObjectName("lockAspect")
        self._lock.setChecked(True)
        self._lock.setToolTip(
            "Keep the figure's own proportions. Unlock to pad the page out to a "
            "fixed canvas; the figure is never cropped.")

        size_row = QHBoxLayout()
        size_row.addWidget(self._width)
        size_row.addWidget(QLabel("x"))
        size_row.addWidget(self._height)
        size_row.addWidget(self._lock)
        size_row.addStretch(1)

        self._scale = QDoubleSpinBox()
        self._scale.setObjectName("scaleSpin")
        self._scale.setRange(0.05, 100.0)
        self._scale.setDecimals(3)
        self._scale.setSingleStep(0.5)
        self._scale.setValue(2.0)
        self._dpi = QSpinBox()
        self._dpi.setObjectName("dpiSpin")
        self._dpi.setRange(4, 7200)
        self._dpi.setValue(144)
        self._dpi.setSuffix(" dpi")
        scale_row = QHBoxLayout()
        scale_row.addWidget(self._scale)
        scale_row.addWidget(self._dpi)
        scale_row.addStretch(1)

        self._background = QComboBox()
        self._background.setObjectName("backgroundCombo")
        for key, label in BACKGROUNDS:
            self._background.addItem(label, key)

        self._legend = QCheckBox("Include legend")
        self._legend.setObjectName("includeLegend")
        self._legend.setChecked(True)

        self._size_label = QLabel()
        self._size_label.setObjectName("outputSizeLabel")
        self._size_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)

        self._progress = QProgressBar()
        self._progress.setObjectName("exportProgress")
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)

        form = QFormLayout()
        form.addRow("Format:", self._format)
        form.addRow("File:", path_row)
        form.addRow("Size:", size_row)
        form.addRow("Scale:", scale_row)
        form.addRow("Background:", self._background)
        form.addRow("", self._legend)
        form.addRow("Output:", self._size_label)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel)
        self._export_button = self._buttons.addButton(
            "Export", QDialogButtonBox.ButtonRole.AcceptRole)
        self._export_button.setObjectName("exportButton")

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._progress)
        layout.addStretch(1)
        layout.addWidget(self._buttons)

    def _connect(self) -> None:
        self._format.currentIndexChanged.connect(self._on_format_changed)
        self._width.valueChanged.connect(self._on_width_changed)
        self._height.valueChanged.connect(self._on_height_changed)
        self._scale.valueChanged.connect(self._on_scale_changed)
        self._dpi.valueChanged.connect(self._on_dpi_changed)
        self._lock.toggled.connect(self._on_lock_toggled)
        self._legend.toggled.connect(self._on_legend_toggled)
        self._background.currentIndexChanged.connect(
            lambda _i: self._update_size_label())
        self._browse.clicked.connect(self.browse)
        self._buttons.rejected.connect(self.reject)
        self._export_button.clicked.connect(self.accept)

    # ------------------------------------------------------------- scenes

    def _compose(self, size: tuple[float, float] | None) -> Scene:
        """Compose the document at *size*, honouring the legend checkbox.

        The theme flag and the injected text metrics are toggled around the call
        rather than copied, because ``Theme`` is shared with the live canvas and
        a copy would drift from it; the ``finally`` restores both.
        """
        from makeyourtree.scene import compose

        document = self._session.document
        theme = document.theme
        previous_legend = theme.legend_show
        had_metrics = "text_metrics" in document.metadata
        previous_metrics = document.metadata.get("text_metrics")
        theme.legend_show = self._legend.isChecked()
        if self._session.metrics is not None:
            document.metadata["text_metrics"] = self._session.metrics
        try:
            return compose(document, size=size, interactive=False)
        finally:
            theme.legend_show = previous_legend
            if had_metrics:
                document.metadata["text_metrics"] = previous_metrics
            else:
                document.metadata.pop("text_metrics", None)

    def _refresh_natural_size(self) -> None:
        """Remember the unpadded page size, in scene units."""
        scene = self._compose(None)
        self._natural = (float(scene.width), float(scene.height))

    def build_scene(self) -> Scene:
        """The exact ``Scene`` :meth:`run_export` will hand to the exporter.

        Padding is expressed in scene units (``pixels / scale``) so the raster
        and vector paths request the same page.
        """
        scale = self._effective_scale()
        target = (self._width.value() / scale, self._height.value() / scale)
        scene = self._compose(target)
        color = self.settings().background_color()
        if color is not None:
            scene = dataclasses.replace(scene, background=color)
        return scene

    # -------------------------------------------------------------- state

    def _effective_scale(self) -> float:
        """Rasterisation factor.  Vector formats are always 1:1 with points."""
        return float(self._scale.value()) if self._is_raster() else 1.0

    def _is_raster(self) -> bool:
        return self._format.currentData() == "png"

    def _natural_pixels(self, scale: float) -> tuple[int, int]:
        """Smallest output that holds the whole figure at *scale*.

        Rounded **up**, which is what makes the prediction exact: because the
        minimum is at or above ``natural * scale``, ``build_scene`` always pads
        the page to ``pixels / scale`` scene units, and
        ``png_size(padded, scale)`` returns those pixels back unchanged.  Round
        to nearest instead and the page would sometimes stay at its natural size
        while the label claimed a pixel more.
        """
        w = max(1, math.ceil(self._natural[0] * scale - _PIXEL_EPS))
        h = max(1, math.ceil(self._natural[1] * scale - _PIXEL_EPS))
        return w, h

    def settings(self) -> ExportSettings:
        """Current dialog state as plain data."""
        return ExportSettings(
            format=str(self._format.currentData()),
            scale=self._effective_scale(),
            width=self._width.value(),
            height=self._height.value(),
            lock_aspect=self._lock.isChecked(),
            background=str(self._background.currentData()),
            include_legend=self._legend.isChecked(),
            directory=os.path.dirname(self._path.text()),
        )

    def predicted_size(self) -> tuple[int, int]:
        """Output dimensions -- pixels for PNG, points for SVG and PDF."""
        return self._width.value(), self._height.value()

    def output_path(self) -> str:
        return self._path.text().strip()

    # -------------------------------------------------------- size linkage

    def _sync_from_scale(self, scale: float) -> None:
        """Push a new scale through to every dependent control.

        The floor on the size boxes depends on the aspect lock.  Locked, a
        smaller width means a smaller scale, so any positive value is legal.
        Unlocked, the two axes are independent and the only way to honour a
        value below the figure would be to crop it, so the natural size becomes
        the minimum.
        """
        raster_scale = scale if self._is_raster() else 1.0
        nw, nh = self._natural_pixels(raster_scale)
        floor_w, floor_h = (1, 1) if self._lock.isChecked() else (nw, nh)
        self._updating = True
        try:
            self._width.setMinimum(floor_w)
            self._height.setMinimum(floor_h)
            self._width.setValue(nw)
            self._height.setValue(nh)
            self._dpi.setValue(max(self._dpi.minimum(),
                                   int(round(raster_scale * _POINTS_PER_INCH))))
        finally:
            self._updating = False

    def _on_scale_changed(self, value: float) -> None:
        if self._updating:
            return
        self._sync_from_scale(value)
        self._update_size_label()

    def _on_dpi_changed(self, value: int) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self._scale.setValue(value / _POINTS_PER_INCH)
        finally:
            self._updating = False
        self._sync_from_scale(self._scale.value())
        self._update_size_label()

    def _on_width_changed(self, value: int) -> None:
        if self._updating:
            return
        if self._lock.isChecked() and self._natural[0] > 0:
            self._updating = True
            try:
                self._scale.setValue(value / self._natural[0])
            finally:
                self._updating = False
            self._sync_from_scale(self._scale.value())
            self._updating = True
            try:
                self._width.setValue(value)
            finally:
                self._updating = False
        self._update_size_label()

    def _on_height_changed(self, value: int) -> None:
        if self._updating:
            return
        if self._lock.isChecked() and self._natural[1] > 0:
            self._updating = True
            try:
                self._scale.setValue(value / self._natural[1])
            finally:
                self._updating = False
            self._sync_from_scale(self._scale.value())
            self._updating = True
            try:
                self._height.setValue(value)
            finally:
                self._updating = False
        self._update_size_label()

    def _on_lock_toggled(self, _locked: bool) -> None:
        # The floors differ between the two modes, so re-derive them and drop
        # any padding the user had typed while unlocked.
        self._sync_from_scale(self._scale.value())
        self._update_size_label()

    def _on_legend_toggled(self, _checked: bool) -> None:
        self._refresh_natural_size()
        self._sync_from_scale(self._scale.value())
        self._update_size_label()

    def _on_format_changed(self, _index: int) -> None:
        self._update_format_state()
        self._sync_from_scale(self._scale.value())
        self._update_size_label()
        self._retarget_suffix()

    def _update_format_state(self) -> None:
        raster = self._is_raster()
        self._scale.setEnabled(raster)
        self._dpi.setEnabled(raster)
        self._background.setEnabled(True)

    def _update_size_label(self) -> None:
        w, h = self.predicted_size()
        unit = "px" if self._is_raster() else "pt"
        text = f"{w} × {h} {unit}"
        if self._is_raster():
            text += f"  (×{self._scale.value():g})"
        self._size_label.setText(text)

    # --------------------------------------------------------------- paths

    def _retarget_suffix(self) -> None:
        current = self._path.text().strip()
        if not current:
            return
        base, _ext = os.path.splitext(current)
        self._path.setText(base + self.settings().suffix)

    def suggested_path(self) -> str:
        """Where the file should go if the user has not said."""
        settings = self.settings()
        source = self._session.path or self._session.document.source_path
        stem = os.path.splitext(os.path.basename(source))[0] if source else "figure"
        directory = settings.directory or self._last_directory() or os.getcwd()
        return os.path.join(directory, stem + settings.suffix)

    def browse(self) -> str:
        """Ask for a destination.  Returns the chosen path, empty if cancelled."""
        _key, label, suffix = next(f for f in FORMATS
                                   if f[0] == self._format.currentData())
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Export Figure", self.output_path() or self.suggested_path(),
            f"{label} (*{suffix})")
        if chosen:
            self._path.setText(chosen)
        return chosen

    # ------------------------------------------------------------- running

    def accept(self) -> None:
        """Start the export.  The dialog closes only once the file is written."""
        if not self.output_path():
            if not self.browse():
                return
        self.run_export()

    def run_export(self) -> None:
        """Compose on the GUI thread, write on a worker thread."""
        path = self.output_path()
        scene = self.build_scene()
        settings = self.settings()
        work = self._writer(scene, path, settings)

        self._set_busy(True)
        self.exportStarted.emit()
        QThreadPool.globalInstance().start(_ExportTask(work, path, self._signals))

    def _writer(self, scene: Scene, path: str,
                settings: ExportSettings) -> Callable[[], None]:
        """Bind the right exporter to the chosen scene and path.

        All three take the same ``Scene``, which is what stops a format from
        drifting away from what the canvas shows.
        """
        if settings.format == "svg":
            return lambda: export_svg(scene, path)
        if settings.format == "pdf":
            return lambda: export_pdf(scene, path,
                                      size=(scene.width, scene.height))
        background: Any = settings.background_color()
        return lambda: export_png(scene, path, scale=settings.scale,
                                  background=background)

    def _set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        self._export_button.setEnabled(not busy)

    def _on_finished(self, path: str) -> None:
        self._set_busy(False)
        self._save_settings()
        self.exportFinished.emit(path)
        self._session.statusMessage.emit(f"Exported {os.path.basename(path)}", 4000)
        super().accept()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self._size_label.setText(f"Export failed: {message}")
        self.exportFailed.emit(message)

    def wait_for_export(self, timeout_ms: int = 30000) -> bool:
        """Block the caller (not the worker) until the export settles.

        Exists for tests and for scripted exports; the interactive path is
        purely signal-driven and never calls this.
        """
        loop = QEventLoop()
        outcome: dict[str, bool] = {}

        def done(_arg: object = None) -> None:
            outcome["ok"] = True
            loop.quit()

        def failed(_arg: object = None) -> None:
            outcome["ok"] = False
            loop.quit()

        self.exportFinished.connect(done)
        self.exportFailed.connect(failed)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        try:
            loop.exec()
        finally:
            timer.stop()
            self.exportFinished.disconnect(done)
            self.exportFailed.disconnect(failed)
        return bool(outcome.get("ok", False))

    # ------------------------------------------------------------ settings

    def _last_directory(self) -> str:
        self._settings.beginGroup(_SETTINGS_GROUP)
        try:
            return str(self._settings.value("directory", "", type=str))
        finally:
            self._settings.endGroup()

    def _load_settings(self) -> None:
        """Restore last-used choices.  Sizes are not restored -- they belong to
        the figure, and a new document has a different natural size."""
        s = self._settings
        s.beginGroup(_SETTINGS_GROUP)
        try:
            fmt = str(s.value("format", "png", type=str))
            index = self._format.findData(fmt)
            if index >= 0:
                self._format.setCurrentIndex(index)
            self._scale.setValue(float(s.value("scale", 2.0, type=float)))
            self._lock.setChecked(bool(s.value("lock_aspect", True, type=bool)))
            background = str(s.value("background", "theme", type=str))
            bg_index = self._background.findData(background)
            if bg_index >= 0:
                self._background.setCurrentIndex(bg_index)
            self._legend.setChecked(bool(s.value("include_legend", True, type=bool)))
        finally:
            s.endGroup()

    def _save_settings(self) -> None:
        current = self.settings()
        s = self._settings
        s.beginGroup(_SETTINGS_GROUP)
        try:
            s.setValue("format", current.format)
            s.setValue("scale", float(self._scale.value()))
            s.setValue("lock_aspect", current.lock_aspect)
            s.setValue("background", current.background)
            s.setValue("include_legend", current.include_legend)
            if current.directory:
                s.setValue("directory", current.directory)
        finally:
            s.endGroup()
        s.sync()
