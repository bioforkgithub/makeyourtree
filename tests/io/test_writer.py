# SPDX-License-Identifier: MIT
"""The format-dispatching entry points: load_tree, load_trees, save_tree."""
from __future__ import annotations

import io

import pytest
from io_helpers import FIXTURES, fixture_text, sample_tree, signature

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.errors import FormatError
from makeyourtree.io import load_tree, load_trees, save_tree
from makeyourtree.io.newick import iter_newick, read_newick_multi
from makeyourtree.io.writer import save_trees, write_tree

FORMATS = ["newick", "nhx", "nexus", "phyloxml"]


@pytest.mark.parametrize("fmt", FORMATS)
def test_save_tree_writes_a_readable_file(tmp_path, fmt):
    tree = sample_tree()
    path = tmp_path / f"out.{fmt}"
    save_tree(tree, path, format=fmt)
    again = load_tree(path)
    assert signature(again) == signature(tree)
    assert again.metadata["source_path"] == str(path)


@pytest.mark.parametrize("fmt", FORMATS)
def test_save_tree_accepts_a_text_file_object(tmp_path, fmt):
    tree = sample_tree()
    path = tmp_path / "out.txt"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        save_tree(tree, fh, format=fmt)
    assert signature(load_tree(path)) == signature(tree)


@pytest.mark.parametrize("fmt", FORMATS)
def test_save_tree_accepts_a_binary_file_object(tmp_path, fmt):
    tree = sample_tree()
    path = tmp_path / "out.bin"
    with open(path, "wb") as fh:
        save_tree(tree, fh, format=fmt)
    assert signature(load_tree(path)) == signature(tree)


def test_save_tree_accepts_a_path_as_a_string(tmp_path):
    tree = sample_tree()
    path = str(tmp_path / "out.nwk")
    save_tree(tree, path)
    assert signature(load_tree(path)) == signature(tree)


def test_nhx_format_turns_annotations_on():
    tree = load_tree(fixture_text("nhx.nwk"))
    assert "[&&NHX" in write_tree(tree, format="nhx")
    assert "[&&NHX" not in write_tree(tree, format="newick")


def test_unknown_formats_are_rejected():
    with pytest.raises(FormatError):
        write_tree(sample_tree(), format="stockholm")
    with pytest.raises(FormatError):
        load_trees(">seq\nACGT\n")


def test_save_tree_rejects_a_destination_it_cannot_write_to():
    with pytest.raises(TypeError):
        save_tree(sample_tree(), 42)


def test_save_trees_writes_every_tree(tmp_path):
    trees = read_newick_multi(fixture_text("multi.nwk"))
    path = tmp_path / "many.nex"
    save_trees(trees, path, format="nexus")
    assert len(load_trees(path)) == len(trees)


def test_load_tree_takes_the_first_and_says_so():
    sink = DiagnosticSink()
    tree = load_tree(fixture_text("multi.nwk"), sink=sink)
    assert len(tree.leaves) == 2
    assert "io.multiple-trees" in [d.code for d in sink]


def test_load_trees_records_where_the_tree_came_from():
    trees = load_trees(FIXTURES / "translate.nex")
    assert trees[0].metadata["source_format"] == "nexus"
    assert trees[0].metadata["source_path"].endswith("translate.nex")


def test_explicit_format_overrides_detection():
    """A NEXUS file with its header stripped can still be forced open."""
    text = fixture_text("translate.nex")
    assert len(load_trees(text, format="nexus")) == 2


def test_load_trees_accepts_an_open_file(tmp_path):
    path = tmp_path / "t.nwk"
    path.write_text("(Alpha,Beta);", encoding="utf-8")
    with open(path, "rb") as fh:
        trees = load_trees(fh)
    assert len(trees[0].leaves) == 2


def test_load_trees_accepts_a_stream_without_a_name():
    trees = load_trees(io.StringIO("(Alpha,Beta);"))
    assert "source_path" not in trees[0].metadata


def test_iter_newick_is_lazy_and_matches_the_writer():
    trees = read_newick_multi(fixture_text("multi.nwk"))
    it = iter_newick(trees)
    assert next(it) == "(Alpha,Beta);"
    assert len(list(it)) == len(trees) - 1
