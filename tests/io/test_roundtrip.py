# SPDX-License-Identifier: MIT
"""The headline guarantee: read -> write -> read changes nothing that matters.

Every fixture is pushed through every writer and read back, and the resulting
trees must agree on topology, labels, branch lengths and support.  This is the
test that catches quoting mistakes, number formatting drift, child reordering
and the underscore-to-blank trap, all of which are silent corruptions rather
than crashes.
"""
from __future__ import annotations

import itertools

import pytest
from io_helpers import ALL_FILES, caterpillar, fixture_text, signature

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.io import load_trees
from makeyourtree.io.newick import read_newick_multi, write_newick
from makeyourtree.io.nexus import read_nexus, write_nexus
from makeyourtree.io.phyloxml import read_phyloxml, write_phyloxml

WRITERS = {
    "newick": (lambda trees: "\n".join(write_newick(t) for t in trees),
               read_newick_multi),
    "nexus": (write_nexus, read_nexus),
    "phyloxml": (write_phyloxml, read_phyloxml),
}

CASES = list(itertools.product(ALL_FILES, WRITERS))


@pytest.mark.parametrize("name,writer", CASES,
                         ids=[f"{n}->{w}" for n, w in CASES])
def test_every_fixture_through_every_writer(name, writer):
    write, read = WRITERS[writer]
    original = load_trees(fixture_text(name))
    sink = DiagnosticSink()
    again = read(write(original), sink=sink)
    assert not sink.has_errors, sink.format()
    assert [signature(t) for t in again] == [signature(t) for t in original]


@pytest.mark.parametrize("name", ALL_FILES)
def test_writing_twice_is_stable(name):
    """A second pass must not keep changing the file (quoting, in particular)."""
    original = load_trees(fixture_text(name))
    once = "\n".join(write_newick(t) for t in original)
    twice = "\n".join(write_newick(t) for t in read_newick_multi(once))
    assert once == twice


def test_annotations_round_trip_through_nhx():
    original = load_trees(fixture_text("nhx.nwk"))[0]
    again = read_newick_multi(write_newick(original, attrs=True))[0]
    assert signature(again) == signature(original)
    assert [n.attrs for n in again.nodes] == [n.attrs for n in original.nodes]


def test_annotations_round_trip_through_phyloxml_properties():
    original = load_trees(fixture_text("beast_meta.nwk"))[0]
    again = read_phyloxml(write_phyloxml([original]))[0]
    assert signature(again) == signature(original)
    assert again.by_name("Alpha").attrs["rate"] == 1.2
    # A list value has no phyloXML datatype and keeps its brace form.
    assert again.root.children[0].attrs["height_95%_HPD"] == (0.1, 0.4)


def test_rooting_survives_nexus_but_not_bare_newick():
    """Plain Newick has no rooting flag; NEXUS does, and must carry it."""
    unrooted = load_trees(fixture_text("rooting.nwk"))[0]
    assert unrooted.rooted is False
    assert read_nexus(write_nexus([unrooted]))[0].rooted is False
    assert read_phyloxml(write_phyloxml([unrooted]))[0].rooted is False


def test_support_stays_in_the_slot_it_came_from():
    original = load_trees(fixture_text("support.nwk"))[0]
    text = write_newick(original)
    assert text.count("95") == 1
    again = read_newick_multi(text)[0]
    assert [n.support for n in again.nodes] == [n.support for n in original.nodes]


def test_a_large_tree_survives_every_format():
    tree = caterpillar(2000)
    for writer, (write, read) in WRITERS.items():
        again = read(write([tree]))
        assert signature(again[0]) == signature(tree), writer
