# SPDX-License-Identifier: MIT
"""Format sniffing and source decoding."""
from __future__ import annotations

import gzip
import io

import pytest
from io_helpers import ALL_FILES, FIXTURES, fixture_text

from makeyourtree.io.detect import detect_format, read_source

EXPECTED = {
    ".nwk": ("newick", "nhx"),
    ".nex": ("nexus",),
    ".xml": ("phyloxml",),
}


@pytest.mark.parametrize("name", ALL_FILES)
def test_every_fixture_is_recognised(name):
    info = detect_format(fixture_text(name))
    suffix = "." + name.rsplit(".", 1)[1]
    assert info.format in EXPECTED[suffix], (name, info)
    # A bare 'Alpha;' is a legal one-node tree but has almost no signature, so
    # it is the one fixture allowed to score below the confident band.
    floor = 0.4 if name == "single_tip.nwk" else 0.9
    assert info.confidence >= floor


def test_is_known_reflects_the_verdict():
    assert detect_format(fixture_text("simple.nwk")).is_known is True
    assert detect_format(">seq\nACGT\n").is_known is False


def test_nhx_is_distinguished_from_plain_newick():
    assert detect_format(fixture_text("nhx.nwk")).format == "nhx"
    assert detect_format(fixture_text("simple.nwk")).format == "newick"


def test_nexus_header_wins_over_the_newick_inside_it():
    info = detect_format(fixture_text("translate.nex"))
    assert info.format == "nexus"
    assert info.confidence == 1.0
    assert info.n_trees == 2


def test_headerless_nexus_is_recognised_by_its_block():
    text = fixture_text("translate.nex").split("\n", 1)[1]
    info = detect_format(text)
    assert info.format == "nexus"
    assert any("BEGIN" in note for note in info.notes)


def test_leading_rooting_comment_does_not_hide_a_newick_file():
    info = detect_format(fixture_text("rooting.nwk"))
    assert info.format == "newick"


def test_multi_tree_count():
    assert detect_format(fixture_text("multi.nwk")).n_trees == 4


def test_semicolon_in_a_quoted_label_is_not_a_tree_separator():
    assert detect_format("('a;b','c;d');").n_trees == 1


def test_non_tree_inputs_are_reported_as_unknown():
    assert detect_format(">seq1\nACGT\n").format == "unknown"
    assert detect_format("4 120\nAlpha ACGT\n").format == "unknown"
    assert detect_format("").format == "unknown"
    assert detect_format("   \n\t").format == "unknown"


def test_xml_that_is_not_phyloxml_is_unknown():
    info = detect_format('<?xml version="1.0"?><nexml version="0.9"/>')
    assert info.format == "unknown"
    assert "NeXML" in info.notes[0]


def test_phyloxml_without_a_namespace_still_detected():
    info = detect_format("<phyloxml><phylogeny rooted='true'/></phyloxml>")
    assert info.format == "phyloxml"
    assert any("namespace" in note for note in info.notes)


def test_utf8_bom_before_the_nexus_magic():
    data = "﻿".encode("utf-8") + fixture_text("translate.nex").encode("utf-8")
    text, origin = read_source(data)
    assert origin is None
    assert text.startswith("#NEXUS")
    assert detect_format(text).format == "nexus"


def test_latin1_fallback_never_fails():
    text, _ = read_source(b"(Alpha,Sm\xf8rrebr\xf8d);")
    assert "Sm" in text
    assert detect_format(text).format == "newick"


def test_gzip_is_transparently_decompressed():
    raw = gzip.compress(b"(Alpha,Beta);")
    text, _ = read_source(raw)
    assert text == "(Alpha,Beta);"


def test_carriage_returns_are_normalised():
    text, _ = read_source(b"(Alpha,\r\nBeta);\r(Gamma,Delta);\r\n")
    assert "\r" not in text
    assert detect_format(text).n_trees == 2


def test_read_source_accepts_paths_and_file_objects():
    path = FIXTURES / "simple.nwk"
    by_path, origin = read_source(path)
    assert origin == str(path)
    by_str, origin_str = read_source(str(path))
    assert origin_str == str(path)
    with open(path, encoding="utf-8") as fh:
        by_file, origin_file = read_source(fh)
    assert origin_file == str(path)
    assert by_path == by_str == by_file
    inline, origin_inline = read_source("(Alpha,Beta);")
    assert inline == "(Alpha,Beta);" and origin_inline is None


def test_read_source_accepts_binary_streams():
    text, origin = read_source(io.BytesIO(b"(Alpha,Beta);"))
    assert text == "(Alpha,Beta);"
    assert origin is None


def test_read_source_rejects_nonsense():
    with pytest.raises(TypeError):
        read_source(object())
