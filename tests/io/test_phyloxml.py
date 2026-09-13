# SPDX-License-Identifier: MIT
"""The phyloXML reader and writer, including its hostile-input handling."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from io_helpers import fixture_text, signature

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.errors import ParseError
from makeyourtree.io.phyloxml import (PHYLOXML_NS, _CLADE_ORDER, _PHYLOGENY_ORDER,
                                  read_phyloxml, write_phyloxml)


def parse(text, **kw):
    sink = DiagnosticSink()
    return read_phyloxml(text, sink=sink, **kw), sink


def codes(sink):
    return [d.code for d in sink]


def local_names(el):
    return [c.tag.split("}")[-1] for c in el]


def test_clade_mapping():
    trees, sink = parse(fixture_text("simple.xml"))
    assert len(trees) == 1
    tree = trees[0]
    assert tree.name == "example"
    assert tree.metadata["description"] == "a synthetic tree"
    assert [n.name for n in tree.leaves] == ["Alpha", "Beta", "Gamma"]
    inner = tree.root.children[0]
    assert inner.support == 88.0
    assert inner.attrs["confidence_type"] == "bootstrap"
    assert not sink.has_errors


def test_branch_length_attribute_form_is_read():
    tree = parse(fixture_text("simple.xml"))[0][0]
    assert tree.by_name("Beta").branch_length == 0.2
    assert tree.by_name("Alpha").branch_length == 0.1


def test_taxonomy_and_properties_land_in_attrs():
    tree = parse(fixture_text("simple.xml"))[0][0]
    alpha = tree.by_name("Alpha")
    assert alpha.attrs["taxonomy_scientific_name"] == "Alpha primus"
    assert alpha.attrs["taxonomy_code"] == "ALPHA"
    # <property> is mixed content, so the value arrives with padding.
    assert tree.by_name("Gamma").attrs["habitat"] == "wetland"


def test_colour_becomes_a_node_style():
    tree = parse(fixture_text("simple.xml"))[0][0]
    assert tree.by_name("Beta").style["branch_color"].rgb_hex == "#ff0000"


def test_several_phylogenies_give_several_trees():
    trees, sink = parse(fixture_text("two_phylogenies.xml"))
    assert [t.name for t in trees] == ["one", "two"]
    assert [t.rooted for t in trees] == [False, True]
    assert "phyloxml.missing-rooted" in codes(sink)
    assert "phyloxml.namespace" in codes(sink)


def test_round_trip_preserves_the_model():
    trees, _ = parse(fixture_text("simple.xml"))
    again, sink = parse(write_phyloxml(trees))
    assert not sink.has_errors
    assert signature(again[0]) == signature(trees[0])
    assert again[0].by_name("Alpha").attrs == trees[0].by_name("Alpha").attrs


def test_written_document_is_namespaced_and_declares_rooting():
    trees, _ = parse(fixture_text("simple.xml"))
    text = write_phyloxml(trees)
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    root = ET.fromstring(text)
    assert root.tag == f"{{{PHYLOXML_NS}}}phyloxml"
    phylogeny = root[0]
    assert phylogeny.get("rooted") == "true"


def test_written_clade_children_follow_the_schema_sequence():
    """xs:sequence is strict, so element order is part of being valid."""
    trees, _ = parse(fixture_text("simple.xml"))
    root = ET.fromstring(write_phyloxml(trees))
    for clade in root.iter(f"{{{PHYLOXML_NS}}}clade"):
        seen = [_CLADE_ORDER.index(n) for n in local_names(clade)]
        assert seen == sorted(seen), local_names(clade)


def test_written_phylogeny_children_follow_the_schema_sequence():
    trees, _ = parse(fixture_text("simple.xml"))
    root = ET.fromstring(write_phyloxml(trees))
    for phylogeny in root:
        seen = [_PHYLOGENY_ORDER.index(n) for n in local_names(phylogeny)]
        assert seen == sorted(seen), local_names(phylogeny)


def test_missing_namespace_is_tolerated():
    text = ("<phyloxml><phylogeny rooted='true'><clade>"
            "<clade><name>Alpha</name></clade>"
            "<clade><name>Beta</name></clade></clade></phylogeny></phyloxml>")
    trees, sink = parse(text)
    assert [n.name for n in trees[0].leaves] == ["Alpha", "Beta"]
    assert "phyloxml.namespace" in codes(sink)


def test_a_wrong_namespace_is_tolerated():
    text = ('<phyloxml xmlns="https://www.phyloxml.org/"><phylogeny rooted="true">'
            "<clade><name>Solo</name></clade></phylogeny></phyloxml>")
    trees, _ = parse(text)
    assert trees[0].root.name == "Solo"


def test_elements_out_of_schema_order_are_still_read():
    text = ('<phyloxml xmlns="http://www.phyloxml.org"><phylogeny rooted="true">'
            "<clade><confidence type='ml'>0.5</confidence>"
            "<branch_length>0.25</branch_length><name>Solo</name>"
            "</clade></phylogeny></phyloxml>")
    trees, _ = parse(text)
    root = trees[0].root
    assert (root.name, root.branch_length, root.support) == ("Solo", 0.25, 0.5)


def test_both_branch_length_forms_prefers_the_element():
    text = ('<phyloxml xmlns="http://www.phyloxml.org"><phylogeny rooted="true">'
            '<clade branch_length="9.0"><branch_length>0.25</branch_length>'
            "</clade></phylogeny></phyloxml>")
    trees, sink = parse(text)
    assert trees[0].root.branch_length == 0.25
    assert "phyloxml.duplicate-branch-length" in codes(sink)


def test_confidence_without_a_type_is_a_warning_not_a_failure():
    text = ('<phyloxml xmlns="http://www.phyloxml.org"><phylogeny rooted="true">'
            "<clade><confidence>77</confidence></clade></phylogeny></phyloxml>")
    trees, sink = parse(text)
    assert trees[0].root.support == 77.0
    assert "phyloxml.confidence-without-type" in codes(sink)


def test_entities_and_cdata_in_a_name():
    text = ('<phyloxml xmlns="http://www.phyloxml.org"><phylogeny rooted="true">'
            "<clade><name>a &amp; b</name><clade><name><![CDATA[c<d]]></name>"
            "</clade></clade></phylogeny></phyloxml>")
    trees, _ = parse(text)
    assert trees[0].root.name == "a & b"
    assert trees[0].leaves[0].name == "c<d"


def test_a_document_with_no_phylogeny_raises():
    with pytest.raises(ParseError):
        read_phyloxml('<phyloxml xmlns="http://www.phyloxml.org"/>')


def test_malformed_xml_raises_a_positioned_parse_error():
    with pytest.raises(ParseError) as excinfo:
        read_phyloxml("<phyloxml><phylogeny></phyloxml>")
    assert excinfo.value.line is not None


# ------------------------------------------------------------------ security


BILLION_LAUGHS = (
    '<?xml version="1.0"?>\n'
    '<!DOCTYPE lolz [\n'
    '  <!ENTITY lol "lol">\n'
    '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
    '  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">\n'
    ']>\n'
    '<phyloxml><phylogeny rooted="true"><clade><name>&lol3;</name>'
    "</clade></phylogeny></phyloxml>")

XXE = (
    '<?xml version="1.0"?>\n'
    '<!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
    '<phyloxml><phylogeny rooted="true"><clade><name>&xxe;</name>'
    "</clade></phylogeny></phyloxml>")


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, XXE])
def test_entity_attacks_are_refused_rather_than_expanded(payload):
    with pytest.raises(ParseError):
        read_phyloxml(payload)


def test_deeply_nested_xml_is_capped():
    from makeyourtree.io.phyloxml import _MAX_DEPTH
    text = "<phyloxml>" + "<clade>" * (_MAX_DEPTH + 5)
    with pytest.raises(ParseError):
        read_phyloxml(text)
