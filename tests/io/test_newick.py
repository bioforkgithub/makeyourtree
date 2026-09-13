# SPDX-License-Identifier: MIT
"""The Newick/NHX reader and writer."""
from __future__ import annotations

import pytest
from io_helpers import caterpillar, fixture_text, signature

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.errors import ParseError
from makeyourtree.core.traversal import preorder
from makeyourtree.io.newick import read_newick, read_newick_multi, write_newick


def parse(text, **kw):
    sink = DiagnosticSink()
    tree = read_newick(text, sink=sink, **kw)
    return tree, sink


def codes(sink):
    return [d.code for d in sink]


# ------------------------------------------------------------------- grammar

GRAMMAR = [
    ("(A,B);", ["A", "B"], 2),
    ("(A,B,C);", ["A", "B", "C"], 3),                        # polytomy
    ("((C,D),(A,(B,X)),E);", ["C", "D", "A", "B", "X", "E"], 3),
    ("A;", ["A"], 0),                                        # bare leaf
    ("(A);", ["A"], 1),
    ("(,);", [None, None], 2),                               # unnamed leaves
    ("(A,);", ["A", None], 2),                               # named plus unnamed
    ("( A : 1 , B : 2 ) ;", ["A", "B"], 2),                  # whitespace anywhere
    ("(A\n,\nB\n)\n;", ["A", "B"], 2),                       # newlines anywhere
]


@pytest.mark.parametrize("text,leaves,n_children", GRAMMAR)
def test_grammar(text, leaves, n_children):
    tree, sink = parse(text)
    assert [n.name for n in tree.leaves] == leaves
    assert len(tree.root.children) == n_children
    assert not sink.has_errors


def test_degree_one_internal_node_is_never_collapsed():
    """(A)B is the NEXUS standard's own way to place an ancestral taxon."""
    tree, _ = parse(fixture_text("ancestral.nwk"))
    ancestrum = tree.by_name("Ancestrum")
    assert ancestrum is not None
    assert [c.name for c in ancestrum.children] == ["Chicksome"]


def test_root_label_and_root_length():
    tree, sink = parse("(A,B)Root:0.0;")
    assert tree.root.name == "Root"
    assert tree.root.branch_length == 0.0
    assert not sink.has_errors


def test_multiple_trees_including_several_on_one_line():
    trees = read_newick_multi(fixture_text("multi.nwk"))
    assert len(trees) == 4
    assert [len(t.leaves) for t in trees] == [2, 3, 2, 4]


def test_missing_semicolon_at_eof_is_accepted():
    trees, sink = read_newick_multi("(A,B)", sink=(s := DiagnosticSink())), s
    assert len(trees) == 1
    assert "newick.missing-semicolon" in codes(sink)


# -------------------------------------------------------------------- labels


def test_quoted_labels_and_escaped_quotes():
    tree, sink = parse(fixture_text("quoted.nwk"))
    assert [n.name for n in tree.leaves] == [
        "Alpha beta", "O'Hara, R.", "Gamma[1]", "Delta epsilon"]
    assert not sink.has_errors


def test_underscore_becomes_a_blank_only_when_unquoted():
    tree, _ = parse("(A_B,'C_D');")
    assert [n.name for n in tree.leaves] == ["A B", "C_D"]


def test_preserve_underscores_switches_the_conversion_off():
    tree, _ = parse("(A_B,'C_D');", preserve_underscores=True)
    assert [n.name for n in tree.leaves] == ["A_B", "C_D"]


def test_underscore_round_trips_without_becoming_a_quoted_space():
    text = "(A_B,C);"
    tree, _ = parse(text)
    assert write_newick(tree) == text


def test_literal_underscore_is_quoted_on_the_way_out():
    tree, _ = parse("('A_B',C);")
    assert write_newick(tree) == "('A_B',C);"


def test_empty_label_is_not_invented():
    tree, _ = parse("(A,);")
    assert write_newick(tree) == "(A,);"


# ------------------------------------------------------------------ lengths


LENGTHS = [
    ("(A:0.5,B:1);", [0.5, 1.0]),
    ("(A:.5,B:5.);", [0.5, 5.0]),
    ("(A:1e-5,B:1E+2);", [1e-5, 100.0]),
    ("(A:+0.3,B:-0.25);", [0.3, -0.25]),
    ("(A:0,B:0.0);", [0.0, 0.0]),
    ("(A:0.000000000000000000001,B:1);", [1e-21, 1.0]),
]


@pytest.mark.parametrize("text,expected", LENGTHS)
def test_branch_lengths(text, expected):
    tree, sink = parse(text)
    assert [n.branch_length for n in tree.leaves] == expected
    assert not sink.has_errors


def test_absent_length_is_none_and_not_zero():
    tree, _ = parse("(A:1,B);")
    a, b = tree.leaves
    assert a.branch_length == 1.0
    assert b.branch_length is None
    assert write_newick(tree) == "(A:1,B);"


def test_negative_and_zero_lengths_survive_a_round_trip():
    text = fixture_text("negative.nwk").strip()
    tree, sink = parse(text)
    assert tree.has_negative_lengths()
    assert not sink.has_errors
    assert signature(read_newick(write_newick(tree))) == signature(tree)


def test_lengths_can_be_dropped_on_write():
    tree, _ = parse("(A:1,B:2):3;")
    assert write_newick(tree, lengths=False) == "(A,B);"


def test_precision_is_lossless_by_default():
    tree, _ = parse("(A:0.1234567890123,B:2);")
    assert write_newick(tree) == "(A:0.1234567890123,B:2);"
    assert write_newick(tree, precision=3) == "(A:0.123,B:2);"


# ------------------------------------------------------------------ support


def test_numeric_internal_label_is_read_as_support():
    tree, sink = parse(fixture_text("support.nwk"))
    inner = [n for n in preorder(tree.root) if n.children and n is not tree.root]
    assert [n.support for n in inner] == [95.0, 72.5]
    assert all(n.name is None for n in inner)
    assert "newick.internal-label-ambiguous" in codes(sink)


def test_the_root_label_is_never_support():
    """The root has no parent branch, so a number there cannot be support."""
    tree, _ = parse(fixture_text("support.nwk"))
    assert tree.root.name == "100"
    assert tree.root.support is None


def test_numeric_tip_labels_are_never_support():
    tree, _ = parse("(1001,2003)90;")
    assert [n.name for n in tree.leaves] == ["1001", "2003"]
    assert all(n.support is None for n in tree.leaves)


def test_internal_labels_can_be_forced_to_stay_names():
    tree, sink = parse(fixture_text("support.nwk"), internal_labels="name")
    inner = [n for n in preorder(tree.root) if n.children and n is not tree.root]
    assert [n.name for n in inner] == ["95", "72.5"]
    assert all(n.support is None for n in inner)
    assert "newick.internal-label-ambiguous" not in codes(sink)


def test_forced_support_mode_is_silent():
    _, sink = parse(fixture_text("support.nwk"), internal_labels="support")
    assert "newick.internal-label-ambiguous" not in codes(sink)


def test_unknown_internal_label_mode_is_a_programming_error():
    with pytest.raises(ValueError):
        read_newick("(A,B)90;", internal_labels="whatever")


def test_clade_names_are_kept_as_names():
    tree, sink = parse(fixture_text("clade_names.nwk"))
    assert tree.by_name("Vestibula") is not None
    assert "newick.internal-label-ambiguous" not in codes(sink)


def test_bracket_branch_labels_become_support():
    tree, _ = parse(fixture_text("raxml_branchlabels.nwk"))
    inner = [n for n in preorder(tree.root) if n.children and n is not tree.root]
    assert [n.support for n in inner] == [100.0, 87.0]


def test_composite_support_labels_are_kept_whole():
    tree, _ = parse(fixture_text("iqtree_composite.nwk"))
    node = [n for n in preorder(tree.root) if n.children and n is not tree.root][0]
    assert node.name == "95.4/100"
    assert node.attrs["support_values"] == (95.4, 100.0)


def test_support_from_a_comment_and_from_a_label_are_both_kept():
    tree, _ = parse("((A,B)[95]90,C);")
    node = tree.root.children[0]
    assert node.support == 95.0
    assert node.attrs["label_support"] == 90.0


# ---------------------------------------------------------------- NHX/BEAST


def test_nhx_fields_land_in_attrs():
    tree, sink = parse(fixture_text("nhx.nwk"))
    leaf = tree.by_name("AlphaB")
    assert leaf.attrs == {"S": "hostA", "E": "1.1.1.1"}
    assert not sink.has_errors


def test_nhx_b_tag_is_support_not_an_attribute():
    tree, _ = parse(fixture_text("nhx.nwk"))
    clade = [n for n in preorder(tree.root) if n.attrs.get("S") == "Clade1"][0]
    assert clade.support == 100.0
    assert "B" not in clade.attrs


def test_nhx_round_trips_through_the_writer():
    tree, _ = parse(fixture_text("nhx.nwk"))
    again = read_newick(write_newick(tree, attrs=True))
    assert signature(again) == signature(tree)
    assert [n.attrs for n in preorder(again.root)] == \
           [n.attrs for n in preorder(tree.root)]


def test_beast_metacomments_are_coerced():
    tree, _ = parse(fixture_text("beast_meta.nwk"))
    inner = tree.root.children[0]
    assert inner.attrs["posterior"] == 0.98
    assert inner.attrs["height_95%_HPD"] == (0.1, 0.4)
    assert tree.by_name("Alpha").attrs["rate"] == 1.2


def test_metacomment_keys_with_punctuation_survive():
    tree, _ = parse('(A,B)[&prob(percent)="100",prob+-sd="100+-0",flag];')
    attrs = tree.root.attrs
    assert attrs["prob(percent)"] == "100"
    assert attrs["prob+-sd"] == "100+-0"
    assert attrs["flag"] is True


def test_two_consecutive_metacomments_are_merged():
    tree, _ = parse("(A,B)[&a=1][&b=2];")
    assert tree.root.attrs == {"a": 1, "b": 2}


def test_figtree_colour_becomes_a_node_style():
    tree, _ = parse(fixture_text("figtree_colour.nwk"))
    alpha = tree.by_name("Alpha")
    assert alpha.style["branch_color"].rgb_hex == "#ff0000"
    assert tree.root.children[0].collapsed is True


def test_plain_comments_are_kept_verbatim_unless_switched_off():
    tree, _ = parse("(A,B)[a note];")
    assert tree.root.comment == "a note"
    quiet, _ = parse("(A,B)[a note];", keep_comments=False)
    assert quiet.root.comment is None


def test_a_stray_close_bracket_does_not_stall_the_scanner():
    tree, sink = parse("(A,B)[a [b] c];", nested_comments=False)
    assert [n.name for n in tree.leaves] == ["A", "B"]
    assert "newick.stray-bracket" in codes(sink)


def test_nhx_colour_uses_dotted_decimals_not_hex():
    tree, _ = parse("(A[&&NHX:C=255.0.0],B);")
    assert tree.by_name("A").style["branch_color"].rgb_hex == "#ff0000"


def test_node_ids_round_trip_exactly():
    tree, _ = parse(fixture_text("lengths.nwk"))
    for i, node in enumerate(preorder(tree.root)):
        node.id = i * 7 + 3
    tree.reindex()
    text = write_newick(tree, node_ids=True)
    again = read_newick(text)
    assert [n.id for n in preorder(again.root)] == [n.id for n in preorder(tree.root)]
    assert "ID" not in again.root.attrs


def test_rooting_hint_is_read_and_written():
    tree, _ = parse(fixture_text("rooting.nwk"))
    assert tree.rooted is False
    assert write_newick(tree, rooting=True).startswith("[&U] ")


def test_rooting_defaults_to_the_shape_of_the_root():
    assert parse("((A,B),C);")[0].rooted is True
    assert parse("(A,B,C);")[0].rooted is False
    assert parse("(A,B,C);")[0].metadata["rooting_declared"] is False
    assert parse("[&R] (A,B,C);")[0].metadata["rooting_declared"] is True


# ------------------------------------------------------------------ writing


def test_labels_are_quoted_only_when_they_must_be():
    tree, _ = parse("('Alpha beta','O''Hara, R.',Gamma);")
    assert write_newick(tree) == "(Alpha_beta,'O''Hara, R.',Gamma);"
    assert write_newick(tree, quote_style="always") == \
        "('Alpha beta','O''Hara, R.','Gamma');"
    # 'never' is the caller taking responsibility: the comma in the second
    # label is emitted raw and the result no longer reparses to the same tree.
    assert write_newick(tree, quote_style="never") == "(Alpha_beta,O'Hara,_R.,Gamma);"


def test_a_bare_node_can_be_written_without_a_tree():
    tree, _ = parse("((A,B)90,C);")
    assert write_newick(tree.root.children[0]) == "(A,B);"


def test_unknown_quote_style_is_a_programming_error():
    with pytest.raises(ValueError):
        write_newick(read_newick("(A,B);"), quote_style="curly")


def test_support_can_be_suppressed_or_moved_to_nhx():
    tree, _ = parse("((A,B)95,C);")
    assert write_newick(tree, support=False) == "((A,B),C);"
    tree.root.children[0].name = "Clade"
    assert write_newick(tree, attrs=True) == "((A,B)Clade[&&NHX:B=95],C);"


def test_internal_labels_can_be_suppressed():
    tree, _ = parse(fixture_text("clade_names.nwk"))
    assert "Vestibula" not in write_newick(tree, internal_labels=False)


def test_empty_input_raises():
    with pytest.raises(ParseError):
        read_newick("   \n  ")


# ----------------------------------------------------------------- capacity


def test_a_deep_caterpillar_neither_recurses_nor_crashes():
    """100k-leaf pectinate trees are the reason nothing here recurses."""
    tree = caterpillar(4000)
    text = write_newick(tree)
    again = read_newick(text)
    assert again.n_leaves == tree.n_leaves
    assert write_newick(again) == text
