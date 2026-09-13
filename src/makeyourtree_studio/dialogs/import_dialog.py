# SPDX-License-Identifier: MIT
"""The annotation import wizard.

Importing annotations is where users lose the most time, and almost always for
the same reason: the keys in the spreadsheet are not the names in the tree.
``ACC_00123`` against ``ACC00123``, a stray trailing space, tip labels that were
renamed after the table was made.  The failure is silent by default -- the track
binds, matches nothing, and draws an empty strip -- so this dialog refuses to
import without first showing a **match report**: how many keys found a node, how
many found nothing, and how many tips of the tree ended up with no data.

Everything the dialog builds goes through :mod:`makeyourtree.annot.loaders`; the
column-mapping controls only decide which columns are handed over and in what
order.  There is no second parser here, because two parsers means two behaviours
and the file that works in the wizard but not on reload.
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from makeyourtree.annot.loaders import load_annotation, track_from_delimited
from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.tree import Tree
from makeyourtree.tracks import track_types
from makeyourtree.tracks.base import Track

from ..session import Session

__all__ = ["ImportDialog", "MatchReport", "DELIMITERS", "ANNOTATION_SUFFIXES",
           "DELIMITED_SUFFIXES", "detect_delimiter", "match_report"]

ANNOTATION_SUFFIXES = (".mytrack",)
DELIMITED_SUFFIXES = (".csv", ".tsv", ".txt", ".tab")

DELIMITERS: tuple[tuple[str, str | None], ...] = (
    ("Detect automatically", None),
    ("Tab", "\t"),
    ("Comma", ","),
    ("Semicolon", ";"),
    ("Pipe", "|"),
)

_SNIFF_DELIMITERS = ",\t;|"
_PREVIEW_ROWS = 12
_UNMATCHED_EXAMPLES = 8
_SUSPECT_FRACTION = 0.5
"""Above this share of unmatched keys the report is flagged, not just stated.
Half a file missing its target is a key-format mismatch, not a data gap."""

_ROLE_COLUMN = int(Qt.ItemDataRole.UserRole)


# ------------------------------------------------------------------ report


@dataclass(slots=True)
class MatchReport:
    """What binding an annotation table to the tree actually achieved."""

    total_keys: int = 0
    matched_keys: int = 0
    unmatched_keys: int = 0
    matched_nodes: int = 0
    total_tips: int = 0
    tips_without_data: int = 0
    unmatched_examples: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def unmatched_fraction(self) -> float:
        return self.unmatched_keys / self.total_keys if self.total_keys else 0.0

    @property
    def is_suspect(self) -> bool:
        """True when the file looks keyed against a different tree."""
        return self.total_keys > 0 and self.unmatched_fraction > _SUSPECT_FRACTION

    @property
    def is_empty(self) -> bool:
        return self.matched_keys == 0

    def summary(self) -> str:
        """Plain-text report shown in the dialog and used by the tests."""
        lines = [
            f"{self.matched_keys} of {self.total_keys} key(s) matched a node "
            f"({self.matched_nodes} node(s) annotated).",
            f"{self.unmatched_keys} key(s) matched nothing.",
            f"{self.tips_without_data} of {self.total_tips} tip(s) have no data.",
        ]
        if self.unmatched_examples:
            shown = ", ".join(self.unmatched_examples)
            more = self.unmatched_keys - len(self.unmatched_examples)
            lines.append("Unmatched keys: " + shown + (f", +{more} more" if more > 0
                                                       else ""))
        if self.is_empty and self.total_keys:
            lines.append("Nothing matched. Check that the key column holds tip "
                         "names as they appear in the tree.")
        elif self.is_suspect:
            lines.append("Most keys matched nothing. The file is probably keyed "
                         "against a different tree or a different identifier.")
        lines.extend(self.diagnostics)
        return "\n".join(lines)


def match_report(track: Track, tree: Tree, total_keys: int,
                 sink: DiagnosticSink | None = None) -> MatchReport:
    """Summarise how *track* bound to *tree*.

    ``total_keys`` comes from the caller because the track keeps only what it
    matched plus the leftovers; the original record count is the denominator the
    user cares about.
    """
    unmatched = list(track.data.unmatched)
    tips = tree.leaves
    without = sum(1 for tip in tips if tip.id not in track.data.rows)
    messages = [d.format() for d in sink] if sink is not None else []
    return MatchReport(
        total_keys=total_keys,
        matched_keys=max(0, total_keys - len(unmatched)),
        unmatched_keys=len(unmatched),
        matched_nodes=len(track.data.rows),
        total_tips=len(tips),
        tips_without_data=without,
        unmatched_examples=unmatched[:_UNMATCHED_EXAMPLES],
        diagnostics=messages,
    )


# ------------------------------------------------------------- delimiters


def detect_delimiter(text: str) -> str:
    """Guess the field separator the same way the core loader does.

    Deliberately mirrors :func:`makeyourtree.annot.loaders._dialect`: a preview that
    splits differently from the importer would be worse than no preview at all.
    """
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=_SNIFF_DELIMITERS).delimiter
    except csv.Error:
        lines = sample.splitlines()
        return "\t" if lines and "\t" in lines[0] else ","


def _split_rows(text: str, delimiter: str) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter,
                           skipinitialspace=True))
    return [r for r in rows if any(f.strip() for f in r)]


# ----------------------------------------------------------------- dialog


class ImportDialog(QDialog):
    """Pick a file, map its columns, read the match report, then import."""

    trackImported = Signal(str)
    """Emitted with the new track's id once it is on the document."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._rows: list[list[str]] = []
        self._header: list[str] = []
        self._text = ""
        self._track: Track | None = None
        self._report: MatchReport | None = None

        self.setWindowTitle("Import Annotations")
        self.setObjectName("importDialog")
        self._build_widgets()
        self._connect()
        self._update_enabled()

    # ------------------------------------------------------------ widgets

    def _build_widgets(self) -> None:
        self._path = QLineEdit()
        self._path.setObjectName("pathEdit")
        self._browse = QPushButton("Browse...")
        self._browse.setObjectName("browseButton")
        path_row = QHBoxLayout()
        path_row.addWidget(self._path, 1)
        path_row.addWidget(self._browse)

        self._delimiter = QComboBox()
        self._delimiter.setObjectName("delimiterCombo")
        for label, value in DELIMITERS:
            self._delimiter.addItem(label, value)

        self._preview = QTableWidget(0, 0)
        self._preview.setObjectName("previewTable")
        self._preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._preview.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        self._key_column = QComboBox()
        self._key_column.setObjectName("keyColumnCombo")

        self._track_type = QComboBox()
        self._track_type.setObjectName("trackTypeCombo")
        for klass in track_types():
            self._track_type.addItem(klass.display_name or klass.type_id,
                                     klass.type_id)

        self._value_columns = QListWidget()
        self._value_columns.setObjectName("valueColumnList")
        self._value_columns.setMaximumHeight(120)

        self._title = QLineEdit()
        self._title.setObjectName("titleEdit")

        self._match_internal = QCheckBox("Also match internal node names")
        self._match_internal.setObjectName("matchInternal")

        self._analyse_button = QPushButton("Check matches")
        self._analyse_button.setObjectName("analyseButton")

        self._report_view = QPlainTextEdit()
        self._report_view.setObjectName("matchReport")
        self._report_view.setReadOnly(True)
        self._report_view.setMaximumHeight(140)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._import_button = self._buttons.addButton(
            "Import", QDialogButtonBox.ButtonRole.AcceptRole)
        self._import_button.setObjectName("importButton")

        self._mapping = QWidget()
        mapping_form = QFormLayout(self._mapping)
        mapping_form.addRow("Delimiter:", self._delimiter)
        mapping_form.addRow("Key column:", self._key_column)
        mapping_form.addRow("Value columns:", self._value_columns)

        form = QFormLayout()
        form.addRow("File:", path_row)
        form.addRow("Track type:", self._track_type)
        form.addRow("Title:", self._title)
        form.addRow("", self._match_internal)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._mapping)
        layout.addWidget(QLabel("Preview:"))
        layout.addWidget(self._preview, 1)
        layout.addWidget(self._analyse_button)
        layout.addWidget(QLabel("Match report:"))
        layout.addWidget(self._report_view)
        layout.addWidget(self._buttons)

    def _connect(self) -> None:
        self._browse.clicked.connect(self.browse)
        self._path.textChanged.connect(self._on_path_changed)
        self._delimiter.currentIndexChanged.connect(lambda _i: self._reload())
        self._key_column.currentIndexChanged.connect(lambda _i: self._invalidate())
        self._track_type.currentIndexChanged.connect(lambda _i: self._invalidate())
        self._match_internal.toggled.connect(lambda _b: self._invalidate())
        self._value_columns.itemChanged.connect(lambda _i: self._invalidate())
        self._analyse_button.clicked.connect(self.analyse)
        self._buttons.rejected.connect(self.reject)
        self._import_button.clicked.connect(self.accept)

    # -------------------------------------------------------------- source

    def browse(self) -> str:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Import Annotations", self._path.text(),
            "Annotation files (*.mytrack *.csv *.tsv *.txt *.tab);;All files (*)")
        if chosen:
            self.set_source(chosen)
        return chosen

    def set_source(self, path: str | os.PathLike[str]) -> None:
        """Point the wizard at a file and rebuild the mapping controls."""
        self._path.setText(str(path))

    def _on_path_changed(self, _text: str) -> None:
        self._reload()

    @property
    def source_path(self) -> Path:
        return Path(self._path.text().strip())

    def is_annotation_file(self) -> bool:
        """True for a ``.mytrack`` file, which carries its own column mapping."""
        return self.source_path.suffix.lower() in ANNOTATION_SUFFIXES

    def _reload(self) -> None:
        """Re-read the source and repopulate the preview and column pickers."""
        self._invalidate()
        path = self.source_path
        self._rows = []
        self._header = []
        self._text = ""
        if not path.is_file():
            self._mapping.setEnabled(False)
            self._fill_preview()
            self._update_enabled()
            return

        self._text = path.read_text(encoding="utf-8-sig", errors="replace")
        if self.is_annotation_file():
            self._mapping.setEnabled(False)
            self._fill_preview()
            self._update_enabled()
            return

        self._mapping.setEnabled(True)
        rows = _split_rows(self._text, self.delimiter())
        self._rows = rows[1:]
        self._header = list(rows[0]) if rows else []
        self._fill_columns()
        self._fill_preview()
        self._update_enabled()

    def delimiter(self) -> str:
        chosen = self._delimiter.currentData()
        return chosen if chosen else detect_delimiter(self._text)

    # -------------------------------------------------------- column model

    def _fill_columns(self) -> None:
        previous_key = self._key_column.currentData()
        self._key_column.blockSignals(True)
        self._value_columns.blockSignals(True)
        try:
            self._key_column.clear()
            self._value_columns.clear()
            for index, name in enumerate(self._header):
                label = name.strip() or f"Column {index + 1}"
                self._key_column.addItem(label, index)
                item = QListWidgetItem(label)
                item.setData(_ROLE_COLUMN, index)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # Everything but the key column is data by default: the common
                # spreadsheet has exactly one value column and selecting it by
                # hand every time would be busywork.
                item.setCheckState(Qt.CheckState.Checked if index > 0
                                   else Qt.CheckState.Unchecked)
                self._value_columns.addItem(item)
            restored = self._key_column.findData(previous_key)
            self._key_column.setCurrentIndex(restored if restored >= 0 else 0)
        finally:
            self._key_column.blockSignals(False)
            self._value_columns.blockSignals(False)

    def key_column(self) -> int:
        data = self._key_column.currentData()
        return int(data) if data is not None else 0

    def value_columns(self) -> list[int]:
        """Data columns, in list order, excluding whichever holds the key."""
        key = self.key_column()
        out: list[int] = []
        for i in range(self._value_columns.count()):
            item = self._value_columns.item(i)
            index = int(item.data(_ROLE_COLUMN))
            if index != key and item.checkState() == Qt.CheckState.Checked:
                out.append(index)
        return out

    def _fill_preview(self) -> None:
        self._preview.clear()
        if not self._header:
            self._preview.setRowCount(0)
            self._preview.setColumnCount(0)
            return
        body = self._rows[:_PREVIEW_ROWS]
        self._preview.setColumnCount(len(self._header))
        self._preview.setRowCount(len(body))
        self._preview.setHorizontalHeaderLabels(
            [h.strip() or f"Column {i + 1}" for i, h in enumerate(self._header)])
        for r, row in enumerate(body):
            for c in range(len(self._header)):
                value = row[c] if c < len(row) else ""
                self._preview.setItem(r, c, QTableWidgetItem(value))

    # ------------------------------------------------------------ building

    def _reordered_text(self) -> str:
        """The table rewritten as TSV with the key column first.

        ``track_from_delimited`` takes the key from column zero, so remapping is
        done by rewriting the table rather than by teaching the loader a second
        convention.  Values are re-quoted through ``csv``, so a field containing
        a tab survives the round trip.
        """
        columns = [self.key_column(), *self.value_columns()]
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
        for source in [self._header, *self._rows]:
            writer.writerow([source[c] if c < len(source) else ""
                             for c in columns])
        return buffer.getvalue()

    def build_track(self, sink: DiagnosticSink | None = None) -> Track:
        """Construct the track the current settings describe.

        Always via :mod:`makeyourtree.annot.loaders`, so an imported track is
        indistinguishable from one loaded straight off disk.
        """
        tree = self._session.tree
        if self.is_annotation_file():
            return load_annotation(self.source_path, tree, sink=sink)
        return track_from_delimited(
            self._reordered_text(), tree,
            type_id=str(self._track_type.currentData()),
            sink=sink,
            title=self._title.text().strip() or self.source_path.stem,
            match="all" if self._match_internal.isChecked() else "leaves")

    def _key_count(self) -> int:
        """Distinct record keys in the source, the report's denominator."""
        if self.is_annotation_file():
            from makeyourtree.annot.parser import parse_annotation

            return len(parse_annotation(self._text).records)
        column = self.key_column()
        keys = {row[column].strip() for row in self._rows
                if column < len(row) and row[column].strip()}
        return len(keys)

    def analyse(self) -> MatchReport:
        """Bind the track and report the outcome without touching the document."""
        sink = DiagnosticSink()
        self._track = self.build_track(sink)
        self._report = match_report(self._track, self._session.tree,
                                    self._key_count(), sink)
        self._report_view.setPlainText(self._report.summary())
        self._update_enabled()
        return self._report

    @property
    def report(self) -> MatchReport | None:
        """The last computed report, or ``None`` if none has been run."""
        return self._report

    @property
    def track(self) -> Track | None:
        return self._track

    def _invalidate(self) -> None:
        """A setting changed, so the previous report no longer describes it."""
        self._track = None
        self._report = None
        self._report_view.setPlainText("")
        self._update_enabled()

    def _update_enabled(self) -> None:
        ready = self.source_path.is_file()
        self._analyse_button.setEnabled(ready)
        # Importing is gated on having seen the report: an annotation that
        # matches nothing should never be added without the user being told.
        self._import_button.setEnabled(ready and self._track is not None)

    # ------------------------------------------------------------- accept

    def accept(self) -> None:
        if self._track is None:
            self.analyse()
            return
        track = self._track
        self._session.add_track(track)
        self.trackImported.emit(track.id)
        super().accept()
