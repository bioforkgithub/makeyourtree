# SPDX-License-Identifier: MIT
"""Grammar coverage for the ``.mytrack`` reader and writer."""

from __future__ import annotations

import pytest

from makeyourtree.annot import parse_annotation, write_annotation
from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.errors import ParseError
from makeyourtree.style.color import Color

TAB_SAMPLE = """#makeyourtree-annotation 1
# every section, tab separated
; a second comment style

[track]
type = test-probe
title = Sample strip
id = strip-1
match = all

[options]
thickness = 30
border.width = 0.5
border.color = #112233
font = Segoe UI, sans-serif
show_title = false
palette = ["#ff0000", "#00ff00"]

[columns]
names = group, score

[colors]
Alpha = #ff0000
Beta = rgb(0,128,255)

[legend]
title = Groups
show = true
order = Alpha, Beta

[data]
A\tAlpha\t1.5
B\tBeta\t-
C\t-\t2
"""

COMMA_SAMPLE = """#makeyourtree-annotation 1
[track]
type = test-probe

[columns]
names = label, value

[data]
A,"a, quoted, label",1
B,plain,2
"C, odd",  spaced  ,3
"""

SPACE_SAMPLE = """[track]
type = test-probe

[data]
name      group    score
A         Alpha    1
B         Beta     -
"""

QUOTED_SAMPLE = '''[track]
type = test-probe

[columns]
names = text

[data]
A\t"-"
B\t"12"
C\t"say ""hi"""
D\t007
E\ttrue
'''

MALFORMED_SAMPLE = """#makeyourtree-annotation X
stray line before any section
[track]
type = test-probe
colour = blue

[weird]
key = 1
loose text

[columns]
names = a
extent = 3

[colors]
bad = not-a-colour

[legend]
show = maybe

[data]
A\t1
A\t2
\t3
"""

ALL_SAMPLES = [TAB_SAMPLE, COMMA_SAMPLE, SPACE_SAMPLE, QUOTED_SAMPLE,
               MALFORMED_SAMPLE]


@pytest.mark.parametrize("text", ALL_SAMPLES)
def test_write_then_parse_round_trips(text):
    table = parse_annotation(text)
    again = parse_annotation(write_annotation(table))
    assert again == table


@pytest.mark.parametrize("text", ALL_SAMPLES)
def test_written_output_is_clean(text):
    """Our own output must not provoke a single diagnostic when read back."""
    sink = DiagnosticSink()
    parse_annotation(write_annotation(parse_annotation(text)), sink=sink)
    assert sink.format() == ""


def test_track_section():
    t = parse_annotation(TAB_SAMPLE)
    assert t.track_type == "test-probe"
    assert t.title == "Sample strip"
    assert t.track_id == "strip-1"
    assert t.match == "all"
    assert t.version == 1


def test_options_json_and_dotted_nesting():
    t = parse_annotation(TAB_SAMPLE)
    assert t.options["thickness"] == 30
    assert t.options["border"] == {"width": 0.5, "color": "#112233"}
    assert t.options["show_title"] is False
    assert t.options["palette"] == ["#ff0000", "#00ff00"]
    assert t.options["font"] == "Segoe UI, sans-serif"


def test_colors_and_legend():
    t = parse_annotation(TAB_SAMPLE)
    assert t.colors["Alpha"] == Color(255, 0, 0)
    assert t.colors["Beta"] == Color(0, 128, 255)
    assert t.legend == {"title": "Groups", "show": True, "order": ["Alpha", "Beta"]}


def test_tab_separated_data():
    t = parse_annotation(TAB_SAMPLE)
    assert t.columns == ["group", "score"]
    assert t.records == {"A": ["Alpha", 1.5], "B": ["Beta", None], "C": [None, 2]}


def test_comma_separated_data_with_quoted_fields():
    t = parse_annotation(COMMA_SAMPLE)
    assert t.records == {
        "A": ["a, quoted, label", 1],
        "B": ["plain", 2],
        "C, odd": ["spaced", 3],
    }


def test_space_separated_data_and_header_row():
    t = parse_annotation(SPACE_SAMPLE)
    assert t.columns == ["group", "score"]
    assert t.records == {"A": ["Alpha", 1], "B": ["Beta", None]}


def test_missing_values_are_none_not_zero():
    t = parse_annotation(TAB_SAMPLE)
    assert t.records["B"][1] is None
    assert t.records["C"][0] is None
    for row in t.records.values():
        assert 0 not in row and "" not in row


def test_quoting_pins_a_field_as_text():
    t = parse_annotation(QUOTED_SAMPLE)
    assert t.records == {
        "A": ["-"],          # quoted, so a literal dash and not "no value"
        "B": ["12"],         # quoted, so text and not the number 12
        "C": ['say "hi"'],
        "D": ["007"],        # a leading zero marks an identifier
        "E": [True],
    }


def test_unquoted_numbers_become_numbers():
    t = parse_annotation("[track]\ntype = test-probe\n[data]\nA\t3\tB\t-2.5e3\n")
    assert t.records["A"] == [3, "B", -2500.0]


def test_separator_is_detected_once_from_the_first_line():
    """A comma in a later tab-separated record must not re-open the question."""
    t = parse_annotation("[track]\ntype = test-probe\n[data]\nA\tx\nB\ty,z\n")
    assert t.records == {"A": ["x"], "B": ["y,z"]}


def test_quoted_key_does_not_change_the_separator():
    t = parse_annotation('[track]\ntype = test-probe\n[data]\n"A,1"\tx\nB\ty\n')
    assert list(t.records) == ["A,1", "B"]


def test_columns_are_generated_when_absent():
    t = parse_annotation("[track]\ntype = test-probe\n[data]\nA\t1\t2\t3\n")
    assert t.columns == ["value", "value2", "value3"]


def test_short_column_list_is_widened_with_a_diagnostic():
    sink = DiagnosticSink()
    t = parse_annotation("[track]\ntype = test-probe\n[columns]\nnames = a\n"
                         "[data]\nA\t1\t2\n", sink=sink)
    assert t.columns == ["a", "value2"]
    assert [d.code for d in sink] == ["annot.extra-columns"]


def test_short_record_is_padded_with_no_value():
    t = parse_annotation("[track]\ntype = test-probe\n[columns]\nnames = a, b\n"
                         "[data]\nA\t1\n")
    assert t.records["A"] == [1, None]


def test_missing_track_type_is_fatal():
    with pytest.raises(ParseError):
        parse_annotation("[track]\ntitle = nameless\n[data]\nA\t1\n")


def test_malformed_input_reports_diagnostics_instead_of_raising():
    sink = DiagnosticSink()
    t = parse_annotation(MALFORMED_SAMPLE, sink=sink)
    codes = {d.code for d in sink}
    assert {"annot.bad-version", "annot.stray-line", "annot.unknown-section",
            "annot.bad-color", "annot.bad-bool", "annot.duplicate-key",
            "annot.empty-key", "annot.unknown-key"} <= codes
    assert t.track_type == "test-probe"
    assert t.records == {"A": [2]}       # the later duplicate wins
    assert t.colors == {} and t.legend == {}


def test_unknown_material_is_preserved():
    t = parse_annotation(MALFORMED_SAMPLE)
    assert t.options["weird"] == {"key": 1, "_lines": ["loose text"]}
    assert t.options["track"] == {"colour": "blue"}
    assert t.options["columns"] == {"extent": 3}


def test_unreadable_match_falls_back_to_leaves():
    sink = DiagnosticSink()
    t = parse_annotation("[track]\ntype = test-probe\nmatch = tips\n[data]\nA\t1\n",
                         sink=sink)
    assert t.match == "leaves"
    assert [d.code for d in sink] == ["annot.bad-match"]


def test_missing_data_section_warns_but_parses():
    sink = DiagnosticSink()
    t = parse_annotation("[track]\ntype = test-probe\n", sink=sink)
    assert len(t) == 0
    assert [d.code for d in sink] == ["annot.no-data"]


def test_newer_format_version_is_kept_and_noted():
    sink = DiagnosticSink()
    t = parse_annotation("#makeyourtree-annotation 2\n[track]\ntype = test-probe\n"
                         "[data]\nA\t1\n", sink=sink)
    assert t.version == 2
    assert [d.code for d in sink] == ["annot.newer-version"]
    assert write_annotation(t).startswith("#makeyourtree-annotation 2")


def test_source_is_not_part_of_the_file():
    t = parse_annotation(TAB_SAMPLE, source="/tmp/x.mytrack")
    assert t.source == "/tmp/x.mytrack"
    assert "/tmp/x.mytrack" not in write_annotation(t)


def test_writer_quotes_only_what_needs_it():
    t = parse_annotation(QUOTED_SAMPLE)
    text = write_annotation(t)
    assert 'A\t"-"' in text
    assert 'B\t"12"' in text
    assert "D\t007" in text
    assert "E\ttrue" in text


def test_case_insensitive_keys_but_case_sensitive_categories():
    t = parse_annotation("[TRACK]\nTYPE = test-probe\n[Options]\nThickness = 4\n"
                         "[Colors]\nAlpha = #ff0000\n[data]\nA\t1\n")
    assert t.track_type == "test-probe"
    assert t.options["thickness"] == 4
    assert list(t.colors) == ["Alpha"]


def test_column_index():
    t = parse_annotation(TAB_SAMPLE)
    assert t.column_index("score") == 1
    assert t.column_index("absent") == -1
