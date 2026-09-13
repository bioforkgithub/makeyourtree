# SPDX-License-Identifier: MIT
"""The NEXUS reader and writer."""
from __future__ import annotations

import pytest
from io_helpers import fixture_text, signature

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.errors import ParseError
from makeyourtree.io.nexus import read_nexus, write_nexus


def parse(text, **kw):
    sink = DiagnosticSink()
    return read_nexus(text, sink=sink, **kw), sink


def codes(sink):
    return [d.code for d in sink]


def test_translate_table_is_applied_to_leaf_labels():
    trees, sink = parse(fixture_text("translate.nex"))
    assert len(trees) == 2
    assert [n.name for n in trees[0].leaves] == \
        ["Alpha", "Beta", "Gamma delta", "Epsilon zeta"]
    assert not sink.has_errors


def test_tree_names_and_the_default_marker():
    trees, _ = parse(fixture_text("translate.nex"))
    assert [t.name for t in trees] == ["first", "second"]


def test_rooting_hint_is_honoured():
    trees, _ = parse(fixture_text("named_taxa.nex"))
    assert [t.rooted for t in trees] == [False, True]


def test_utree_is_read_as_unrooted():
    trees, _ = parse("#NEXUS\nbegin trees; utree u = ((A,B),C); end;")
    assert trees[0].rooted is False


def test_taxon_number_resolves_through_taxlabels_when_untranslated():
    trees, _ = parse(fixture_text("named_taxa.nex"))
    assert [n.name for n in trees[0].leaves] == ["Alpha", "Beta", "Gamma"]


def test_translate_keys_beat_the_numeric_position():
    """A TRANSLATE key must win: BEAST writes keys in tree order, not taxon order."""
    text = ("#NEXUS\nbegin taxa; dimensions ntax=2; taxlabels Alpha Beta; end;\n"
            "begin trees; translate 1 Beta, 2 Alpha; tree t = (1,2); end;")
    trees, _ = parse(text)
    assert [n.name for n in trees[0].leaves] == ["Beta", "Alpha"]


def test_unknown_blocks_are_skipped_even_when_they_mention_end():
    trees, sink = parse(fixture_text("unknown_block.nex"))
    assert len(trees) == 1
    assert [n.name for n in trees[0].leaves] == ["Alpha", "Beta", "Gamma"]
    assert "nexus.unterminated-block" not in codes(sink)


def test_endblock_is_accepted():
    trees, _ = parse("#NEXUS\nbegin trees; tree t = (A,B); endblock;")
    assert len(trees) == 1


def test_support_inside_a_nexus_tree_is_read_like_newick():
    trees, _ = parse(fixture_text("named_taxa.nex"))
    inner = trees[1].root.children[0]
    assert inner.support == 0.99


def test_a_file_with_no_block_at_all_raises():
    with pytest.raises(ParseError):
        read_nexus("#NEXUS\n")


def test_concatenated_documents_are_both_read():
    text = fixture_text("named_taxa.nex") + fixture_text("unknown_block.nex")
    trees, _ = parse(text)
    assert len(trees) == 3


# ------------------------------------------------------------------ writing


def test_written_file_reads_back_identically():
    trees, _ = parse(fixture_text("translate.nex"))
    text = write_nexus(trees)
    again, sink = parse(text)
    assert not sink.has_errors
    assert [signature(t) for t in again] == [signature(t) for t in trees]


def test_translate_table_is_emitted_when_it_shortens_the_file():
    """The table costs a line per taxon, so it only pays once trees repeat."""
    trees, _ = parse(fixture_text("translate.nex"))
    text = write_nexus(trees * 8)
    assert "TRANSLATE" in text
    assert "TREE first = [&R] ((1:0.1,2:0.2):0.3,(3:0.4,4:0.5):0.6);" in text
    again, sink = parse(text)
    assert not sink.has_errors
    assert [signature(t) for t in again] == [signature(t) for t in trees * 8]
    assert "TRANSLATE" not in write_nexus(trees)


def test_translate_is_skipped_when_it_would_not_pay():
    trees, _ = parse("#NEXUS\nbegin trees; tree t = (A,B); end;")
    text = write_nexus(trees)
    assert "TRANSLATE" not in text
    assert "(A,B)" in text


def test_translate_can_be_forced_either_way():
    trees, _ = parse("#NEXUS\nbegin trees; tree t = (A,B); end;")
    assert "TRANSLATE" in write_nexus(trees, translate=True)
    long_trees, _ = parse(fixture_text("translate.nex"))
    assert "TRANSLATE" not in write_nexus(long_trees, translate=False)


def test_taxa_block_lists_every_tip_once():
    trees, _ = parse(fixture_text("translate.nex"))
    text = write_nexus(trees)
    assert "DIMENSIONS NTAX=4;" in text
    assert text.count("\n        Alpha\n") == 1


def test_nexus_quoting_covers_punctuation_newick_would_leave_bare():
    from makeyourtree.io.newick import read_newick
    tree = read_newick("('a+b','c<d',`e);")
    text = write_nexus([tree], translate=False)
    assert "'a+b'" in text and "'c<d'" in text and "'`e'" in text
    again, sink = parse(text)
    assert [n.name for n in again[0].leaves] == ["a+b", "c<d", "`e"]
    assert not sink.has_errors


def test_all_digit_labels_are_quoted_so_they_are_not_taxon_numbers():
    from makeyourtree.io.newick import read_newick
    tree = read_newick("(1001,2003);")
    text = write_nexus([tree], translate=False)
    assert "'1001'" in text


def test_rooting_is_always_declared():
    trees, _ = parse(fixture_text("named_taxa.nex"))
    text = write_nexus(trees)
    assert "[&U]" in text and "[&R]" in text
    assert write_nexus(trees, rooting=False).count("[&") == 0


@pytest.mark.parametrize("text,expect", [
    ("#NEXUS\nbegin trees;\ntranslate 1 = Alpha, 2 = Beta;\ntree t=(1,2);\nend;",
     ["Alpha", "Beta"]),
    ("#NEXUS\nbegin trees;\ntranslate 1 Alpha 2 Beta;\ntree t=(1,2);\nend;",
     ["Alpha", "Beta"]),
    ("#NEXUS\nbegin trees;\ntranslate 1 Alpha, 2 Beta,;\ntree t=(1,2);\nend;",
     ["Alpha", "Beta"]),
])
def test_translate_list_malformations(text, expect):
    trees, _ = parse(text)
    assert [n.name for n in trees[0].leaves] == expect
