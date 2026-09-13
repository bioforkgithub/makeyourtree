# SPDX-License-Identifier: MIT
"""Binding annotation tables and plain delimited files to a tree."""

from __future__ import annotations

import pytest

from makeyourtree.annot import (load_annotation, parse_annotation, track_from_delimited,
                            track_from_table)
from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.errors import FormatError
from makeyourtree.style.color import Color
from _annot_support import node_ids

CANN = """#makeyourtree-annotation 1
[track]
type = test-probe
title = Groups
id = groups-1

[options]
thickness = 18

[columns]
names = group, score

[colors]
Alpha = #ff0000

[legend]
title = Groups
show = true

[data]
A\tAlpha\t1.5
B\tBeta\t-
Z\tOther\t9
"""


def test_track_from_table_binds_names_to_ids(tree):
    sink = DiagnosticSink()
    table = parse_annotation(CANN, source="groups.mytrack")
    track = track_from_table(table, tree, sink=sink)

    ids = node_ids(tree)
    assert track.type_id == "test-probe"
    assert track.id == "groups-1"
    assert track.title == "Groups"
    assert track.data.columns == ["group", "score"]
    assert track.data.rows[ids["A"]] == ["Alpha", 1.5]
    assert track.data.rows[ids["B"]] == ["Beta", None]
    assert track.data.source == "groups.mytrack"


def test_unmatched_keys_are_reported_not_dropped(tree):
    sink = DiagnosticSink()
    track = track_from_table(parse_annotation(CANN), tree, sink=sink)
    assert track.data.unmatched == ["Z"]
    assert "track.unmatched" in {d.code for d in sink}


def test_match_leaves_ignores_internal_names(tree):
    text = "[track]\ntype = test-probe\n[data]\nAB\t1\n"
    leaves_only = track_from_table(parse_annotation(text), tree)
    assert leaves_only.data.rows == {}
    assert leaves_only.data.unmatched == ["AB"]


def test_match_all_reaches_internal_nodes(tree):
    text = "[track]\ntype = test-probe\nmatch = all\n[data]\nAB\t1\n"
    track = track_from_table(parse_annotation(text), tree)
    assert track.data.rows == {node_ids(tree)["AB"]: [1]}


def test_colors_and_legend_reach_the_track_options(tree):
    track = track_from_table(parse_annotation(CANN), tree)
    assert track.options["colors"] == {"Alpha": Color(255, 0, 0)}
    assert track.options["legend"] == {"title": "Groups", "show": True}
    assert track.options["thickness"] == 18
    assert track.options["shape"] == "square"     # class default survives


def test_unknown_option_is_kept_with_a_diagnostic(tree):
    sink = DiagnosticSink()
    text = "[track]\ntype = test-probe\n[options]\nwobble = 3\n[data]\nA\t1\n"
    track = track_from_table(parse_annotation(text), tree, sink=sink)
    assert track.options["wobble"] == 3
    assert [d.code for d in sink] == ["annot.unknown-option"]


def test_unknown_track_type_is_a_format_error(tree):
    table = parse_annotation("[track]\ntype = no-such-track\n[data]\nA\t1\n")
    with pytest.raises(FormatError):
        track_from_table(table, tree)


def test_a_table_that_matches_nothing_is_an_error(tree):
    sink = DiagnosticSink()
    text = "[track]\ntype = test-probe\n[data]\nX\t1\nY\t2\n"
    track_from_table(parse_annotation(text), tree, sink=sink)
    assert sink.has_errors


def test_load_annotation_from_text(tree):
    track = load_annotation(CANN, tree)
    assert len(track.data) == 2
    assert track.data.source is None


def test_load_annotation_from_a_path(tree, tmp_path):
    path = tmp_path / "groups.mytrack"
    path.write_text(CANN, encoding="utf-8")
    track = load_annotation(str(path), tree)
    assert track.data.source == str(path)
    assert len(track.data) == 2


def test_delimited_csv_with_header(tree):
    text = "name,group,score\nA,Alpha,1\nB,Beta,2\nC,Gamma,\n"
    track = track_from_delimited(text, tree, type_id="test-probe", title="From CSV")
    ids = node_ids(tree)
    assert track.title == "From CSV"
    assert track.data.columns == ["group", "score"]
    assert track.data.rows[ids["A"]] == ["Alpha", 1]
    assert track.data.rows[ids["C"]] == ["Gamma", None]


def test_delimited_tsv_with_quoted_field(tree):
    text = 'name\tlabel\nA\t"one, two"\nB\t-\n'
    track = track_from_delimited(text, tree, type_id="test-probe")
    ids = node_ids(tree)
    assert track.data.rows[ids["A"]] == ["one, two"]
    assert track.data.rows[ids["B"]] == [None]


def test_delimited_options_and_match_pass_through(tree):
    text = "name,value\nAB,7\n"
    track = track_from_delimited(text, tree, type_id="test-probe", match="all",
                                 id="from-sheet", thickness=9.0)
    assert track.id == "from-sheet"
    assert track.options["thickness"] == 9.0
    assert track.data.rows == {node_ids(tree)["AB"]: [7]}


def test_delimited_falls_back_when_sniffing_fails(tree):
    sink = DiagnosticSink()
    track = track_from_delimited("name\nA\nB\n", tree, type_id="test-probe",
                                 sink=sink)
    assert track.data.columns == []
    assert set(track.data.rows) == {node_ids(tree)["A"], node_ids(tree)["B"]}
    assert "annot.sniff-failed" in {d.code for d in sink}


def test_delimited_from_a_path(tree, tmp_path):
    path = tmp_path / "sheet.csv"
    path.write_text("name,value\nA,1\n", encoding="utf-8")
    track = track_from_delimited(str(path), tree, type_id="test-probe")
    assert track.data.source == str(path)
    assert track.data.get(node_ids(tree)["A"]) == 1


def test_binds_to_a_real_registered_track_type(tree):
    """The seam works against a real track, not only against the probe."""
    tracks = pytest.importorskip("makeyourtree.tracks")
    if "color-strip" not in {t.type_id for t in tracks.track_types()}:
        pytest.skip("built-in track types are not available yet")
    sink = DiagnosticSink()
    track = load_annotation(
        "[track]\ntype = color-strip\ntitle = Clades\n"
        "[colors]\nAlpha = #ff0000\n[data]\nA\tAlpha\nB\tBeta\n",
        tree, sink=sink)
    assert track.type_id == "color-strip"
    assert track.data.rows[node_ids(tree)["A"]] == ["Alpha"]
    assert track.options["colors"]["Alpha"] == Color(255, 0, 0)
    assert not sink.has_errors


def test_missing_cells_stay_missing_after_binding(tree):
    track = track_from_delimited("name,value\nA,1\nB,\n", tree, type_id="test-probe")
    ids = node_ids(tree)
    assert track.data.get(ids["B"]) is None
    assert track.data.get(ids["B"], default="gap") == "gap"
    assert track.data.numeric_column(0) == [1.0]


# ------------------------------------------------------------ ambiguous keys


AMBIGUOUS = """#makeyourtree-annotation 1
[track]
type = test-probe
title = Groups

[columns]
names = group

[data]
A\tone
C\ttwo
"""


def test_a_key_matching_two_tips_is_reported(tree):
    """``bind`` paints every match, so one row can colour a tip nobody measured."""
    duplicate = next(n for n in tree.leaves if n.name == "B")
    duplicate.name = "A"
    tree.refresh()

    sink = DiagnosticSink()
    track_from_table(parse_annotation(AMBIGUOUS), tree, sink=sink)
    codes = [d.code for d in sink]
    assert "annot.ambiguous-key" in codes, sink.format()
    message = next(d.message for d in sink if d.code == "annot.ambiguous-key")
    assert "'A' (x2)" in message
    assert "every match" in message


def test_unique_keys_raise_no_ambiguity_warning(tree):
    sink = DiagnosticSink()
    track_from_table(parse_annotation(AMBIGUOUS), tree, sink=sink)
    assert "annot.ambiguous-key" not in [d.code for d in sink]


def test_an_ambiguous_key_really_does_paint_both_nodes(tree):
    duplicate = next(n for n in tree.leaves if n.name == "B")
    duplicate.name = "A"
    tree.refresh()

    track = track_from_table(parse_annotation(AMBIGUOUS), tree)
    painted = {nid for nid in track.data.rows}
    both = {n.id for n in tree.leaves if n.name == "A"}
    assert both <= painted
