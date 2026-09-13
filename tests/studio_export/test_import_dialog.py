# SPDX-License-Identifier: MIT
"""The annotation import wizard, driven over tables with known key overlap.

The fixtures deliberately contain keys that match nothing. A wizard that reports
"imported" on a file whose keys are all wrong has helped nobody, so the
assertions here are mostly about the *numbers in the match report* rather than
about the widgets.
"""

from __future__ import annotations

import pytest

from makeyourtree_studio.dialogs.import_dialog import (ImportDialog, MatchReport,
                                                   detect_delimiter)

# The session tree has six tips: alpha beta gamma delta epsilon zeta.
GOOD_CSV = """name,colour
alpha,#ff0000
beta,#00ff00
gamma,#0000ff
delta,#ffff00
"""

MOSTLY_UNMATCHED_CSV = """name,colour
alpha,#ff0000
NOT_A_TIP_1,#00ff00
NOT_A_TIP_2,#0000ff
NOT_A_TIP_3,#ffff00
NOT_A_TIP_4,#ff00ff
NOT_A_TIP_5,#00ffff
NOT_A_TIP_6,#111111
NOT_A_TIP_7,#222222
NOT_A_TIP_8,#333333
NOT_A_TIP_9,#444444
"""

KEY_IN_SECOND_COLUMN_TSV = "accession\tname\tcolour\nA1\talpha\t#ff0000\n" \
                           "A2\tbeta\t#00ff00\nA3\tnobody\t#0000ff\n"

CANN = """[track]
type = color-strip
title = Clade colour

[data]
alpha\t#ff0000
beta\t#00ff00
nobody\t#0000ff
"""


@pytest.fixture
def dialog(qapp, session):
    d = ImportDialog(session)
    yield d
    d.deleteLater()


def _write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# ------------------------------------------------------------ construction


def test_dialog_constructs_offscreen(dialog):
    assert dialog.windowTitle() == "Import Annotations"
    assert dialog._track_type.count() > 0
    assert dialog.report is None


def test_import_is_disabled_until_the_report_has_been_seen(dialog, tmp_path):
    dialog.set_source(_write(tmp_path, "good.csv", GOOD_CSV))
    assert dialog._import_button.isEnabled() is False
    dialog.analyse()
    assert dialog._import_button.isEnabled() is True


# ---------------------------------------------------------------- preview


def test_preview_shows_the_header_and_rows(dialog, tmp_path):
    dialog.set_source(_write(tmp_path, "good.csv", GOOD_CSV))
    assert dialog._preview.columnCount() == 2
    assert dialog._preview.rowCount() == 4
    assert dialog._preview.item(0, 0).text() == "alpha"
    assert dialog._preview.horizontalHeaderItem(1).text() == "colour"


def test_delimiter_can_be_forced(dialog, tmp_path):
    """A comma file read as tab-separated collapses into one column."""
    dialog.set_source(_write(tmp_path, "good.csv", GOOD_CSV))
    index = dialog._delimiter.findData("\t")
    dialog._delimiter.setCurrentIndex(index)
    assert dialog._preview.columnCount() == 1


def test_detect_delimiter_handles_both_common_cases():
    assert detect_delimiter("a,b\n1,2\n3,4\n") == ","
    assert detect_delimiter("a\tb\n1\t2\n3\t4\n") == "\t"


# ----------------------------------------------------------- match report


def test_report_counts_matches_and_orphan_tips(dialog, tmp_path):
    dialog.set_source(_write(tmp_path, "good.csv", GOOD_CSV))
    dialog._track_type.setCurrentIndex(dialog._track_type.findData("color-strip"))
    report = dialog.analyse()

    assert report.total_keys == 4
    assert report.matched_keys == 4
    assert report.unmatched_keys == 0
    assert report.matched_nodes == 4
    assert report.total_tips == 6
    assert report.tips_without_data == 2
    assert report.is_suspect is False
    assert report.is_empty is False


def test_report_flags_a_mostly_unmatched_file(dialog, tmp_path):
    """A 90 % unmatched file is a user error worth reporting clearly."""
    dialog.set_source(_write(tmp_path, "bad.csv", MOSTLY_UNMATCHED_CSV))
    dialog._track_type.setCurrentIndex(dialog._track_type.findData("color-strip"))
    report = dialog.analyse()

    assert report.total_keys == 10
    assert report.matched_keys == 1
    assert report.unmatched_keys == 9
    assert report.unmatched_fraction == pytest.approx(0.9)
    assert report.is_suspect is True
    assert "NOT_A_TIP_1" in report.summary()
    assert "matched nothing" in report.summary()


def test_report_names_a_total_mismatch_explicitly(dialog, tmp_path):
    nothing = "name,colour\nzzz1,#ff0000\nzzz2,#00ff00\n"
    dialog.set_source(_write(tmp_path, "none.csv", nothing))
    dialog._track_type.setCurrentIndex(dialog._track_type.findData("color-strip"))
    report = dialog.analyse()

    assert report.is_empty is True
    assert report.matched_nodes == 0
    assert report.tips_without_data == report.total_tips
    assert "Nothing matched" in report.summary()


def test_report_is_shown_in_the_dialog(dialog, tmp_path):
    dialog.set_source(_write(tmp_path, "good.csv", GOOD_CSV))
    dialog.analyse()
    assert dialog._report_view.toPlainText() == dialog.report.summary()


def test_changing_a_setting_invalidates_the_report(dialog, tmp_path):
    dialog.set_source(_write(tmp_path, "good.csv", GOOD_CSV))
    dialog.analyse()
    assert dialog.report is not None
    dialog._match_internal.setChecked(True)
    assert dialog.report is None
    assert dialog._import_button.isEnabled() is False


# ------------------------------------------------------------ key mapping


def test_the_key_column_can_be_any_column(dialog, tmp_path):
    """Accession in column one, tip name in column two: pick the second."""
    dialog.set_source(_write(tmp_path, "keys.tsv", KEY_IN_SECOND_COLUMN_TSV))
    dialog._track_type.setCurrentIndex(dialog._track_type.findData("color-strip"))

    with_first_column = dialog.analyse()
    assert with_first_column.matched_keys == 0

    dialog._key_column.setCurrentIndex(dialog._key_column.findData(1))
    with_second_column = dialog.analyse()
    assert with_second_column.total_keys == 3
    assert with_second_column.matched_keys == 2
    assert with_second_column.unmatched_keys == 1
    assert with_second_column.unmatched_examples == ["nobody"]


def test_the_key_column_is_never_also_a_value_column(dialog, tmp_path):
    dialog.set_source(_write(tmp_path, "keys.tsv", KEY_IN_SECOND_COLUMN_TSV))
    dialog._key_column.setCurrentIndex(dialog._key_column.findData(1))
    assert 1 not in dialog.value_columns()


def test_internal_names_only_match_when_asked(dialog, tmp_path):
    internal = "name,colour\nab,#ff0000\ngd,#00ff00\n"
    dialog.set_source(_write(tmp_path, "internal.csv", internal))
    dialog._track_type.setCurrentIndex(dialog._track_type.findData("color-strip"))

    assert dialog.analyse().matched_keys == 0
    dialog._match_internal.setChecked(True)
    assert dialog.analyse().matched_keys == 2


# ------------------------------------------------------------ .mytrack files


def test_a_cann_file_carries_its_own_mapping(dialog, tmp_path):
    dialog.set_source(_write(tmp_path, "clade.mytrack", CANN))
    assert dialog.is_annotation_file() is True
    assert dialog._mapping.isEnabled() is False

    report = dialog.analyse()
    assert report.total_keys == 3
    assert report.matched_keys == 2
    assert report.unmatched_keys == 1
    assert dialog.track is not None
    assert dialog.track.type_id == "color-strip"


# ---------------------------------------------------------------- import


def test_accepting_adds_the_track_to_the_session(dialog, tmp_path, session):
    dialog.set_source(_write(tmp_path, "good.csv", GOOD_CSV))
    dialog._track_type.setCurrentIndex(dialog._track_type.findData("color-strip"))
    dialog.analyse()

    imported: list[str] = []
    dialog.trackImported.connect(imported.append)
    dialog.accept()

    assert len(session.document.tracks) == 1
    assert imported == [session.document.tracks[0].id]


def test_accepting_without_a_report_analyses_first(dialog, tmp_path, session):
    """The user must never be able to import a track sight-unseen."""
    dialog.set_source(_write(tmp_path, "good.csv", GOOD_CSV))
    dialog.accept()
    assert dialog.report is not None
    assert session.document.tracks == []
    assert dialog.isVisible() is False or dialog.result() == 0


# ----------------------------------------------------------- report model


def test_match_report_summary_is_readable_when_empty():
    report = MatchReport()
    assert "0 of 0" in report.summary()
    assert report.is_suspect is False
    assert report.unmatched_fraction == 0.0
