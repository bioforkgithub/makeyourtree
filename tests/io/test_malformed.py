# SPDX-License-Identifier: MIT
"""The real-world malformation checklist.

Every input here violates a specification in a way that has been observed in
files people actually try to open.  The contract under test is uniform: the
reader repairs what it can, records a diagnostic saying what it did, and returns
a tree.  Refusing to open the file is not an acceptable outcome for any of
them -- only genuinely structureless input raises.
"""
from __future__ import annotations

import pytest

from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.errors import MakeYourTreeError
from makeyourtree.io import load_trees
from makeyourtree.io.newick import read_newick_multi
from makeyourtree.io.nexus import read_nexus

# (label, text, expected diagnostic code or None when the input is merely
#  unusual rather than wrong, expected leaf labels)
NEWICK_CASES = [
    ("missing semicolon", "(Alpha,Beta)", "newick.missing-semicolon",
     ["Alpha", "Beta"]),
    ("stray semicolons", "(Alpha,Beta);;", "newick.empty-tree", ["Alpha", "Beta"]),
    ("unbalanced parens", "((Alpha,Beta);", "newick.unclosed-parens",
     ["Alpha", "Beta"]),
    ("single child", "(Alpha)Inner;", None, ["Alpha"]),
    ("empty group", "(Alpha,());", "newick.empty-group", ["Alpha", None]),
    ("trailing comma", "(Alpha,Beta,);", "newick.empty-child",
     ["Alpha", "Beta", None]),
    ("leading comma", "(,Alpha,Beta);", "newick.empty-child",
     [None, "Alpha", "Beta"]),
    ("comma with nothing between", "(Alpha,,Beta);", "newick.empty-child",
     ["Alpha", None, "Beta"]),
    ("root length", "(Alpha,Beta):0.0;", None, ["Alpha", "Beta"]),
    ("wrapped mid-token", "(Alpha:\n0.1,Beta:0.2\n);", None, ["Alpha", "Beta"]),
    ("newline inside a label", "(Al\npha,Beta);", "newick.space-in-label",
     ["Al pha", "Beta"]),
    ("unescaped quote", "('O'Hara',Beta);", "newick.unescaped-quote",
     ["O'Hara", "Beta"]),
    ("double quotes", '("Alpha beta",Beta);', None, ["Alpha beta", "Beta"]),
    ("space in an unquoted label", "(Alpha beta:0.1,Beta);",
     "newick.space-in-label", ["Alpha beta", "Beta"]),
    ("duplicate tips", "(Alpha,Alpha);", None, ["Alpha", "Alpha"]),
    ("empty labels", "(,);", "newick.empty-child", [None, None]),
    ("negative length", "(Alpha:-0.5,Beta:1);", None, ["Alpha", "Beta"]),
    ("colon with no number", "(Alpha:,Beta:1);", "newick.missing-length",
     ["Alpha", "Beta"]),
    ("european decimal comma", "(Alpha:1,5,Beta:2);", "newick.decimal-comma",
     ["Alpha", "5", "Beta"]),
    ("not a number", "(Alpha:nan,Beta:1);", "newick.bad-length", ["Alpha", "Beta"]),
    ("msvc infinity", "(Alpha:1.#INF,Beta:1);", "newick.bad-length",
     ["Alpha", "Beta"]),
    ("unterminated comment", "(Alpha,Beta)[note;", "newick.unterminated-comment",
     ["Alpha", "Beta"]),
    ("nested comment", "(Alpha,Beta)[a [b] c];", None, ["Alpha", "Beta"]),
    ("unescaped quote in a metacomment", '(Alpha,Beta)[&name="say "hi""];', None,
     ["Alpha", "Beta"]),
    ("empty nhx block", "(Alpha[&&NHX]:1,Beta[&&NHX:]:2);", None,
     ["Alpha", "Beta"]),
    ("split metacomments", "(Alpha,Beta)[&a=1][&b=2];", None, ["Alpha", "Beta"]),
    ("mixed comment styles", "((Alpha,Beta)[100][&prob=1.0],Gamma);", None,
     ["Alpha", "Beta", "Gamma"]),
    ("trailing garbage", "(Alpha,Beta)) junk", "newick.trailing-garbage",
     ["Alpha", "Beta"]),
]


@pytest.mark.parametrize("label,text,code,leaves",
                         NEWICK_CASES, ids=[c[0] for c in NEWICK_CASES])
def test_newick_malformations_are_repaired(label, text, code, leaves):
    sink = DiagnosticSink()
    trees = read_newick_multi(text, sink=sink)
    assert trees, label
    assert [n.name for n in trees[0].leaves] == leaves
    if code is not None:
        assert code in [d.code for d in sink], (label, sink.format())


# ------------------------------------------------- hazards of the whole tree
#
# These two are properties of the finished tree rather than of any token, so
# they are reported by ``load_trees`` for every format rather than by each
# reader.  The parametrised cases above go through ``read_newick_multi``, which
# is below that layer and correctly stays silent about them.


@pytest.mark.parametrize("text", ["(Alpha,Alpha);", "((Alpha,Beta),Alpha);"])
def test_repeated_tip_names_are_reported_by_the_loader(text):
    sink = DiagnosticSink()
    load_trees(text, sink=sink)
    codes = [d.code for d in sink]
    assert "io.duplicate-tip-name" in codes, sink.format()
    message = next(d.message for d in sink if d.code == "io.duplicate-tip-name")
    assert "'Alpha' (x2)" in message


def test_a_tree_with_unique_names_says_nothing_about_duplicates():
    sink = DiagnosticSink()
    load_trees("(Alpha,Beta,Gamma);", sink=sink)
    assert "io.duplicate-tip-name" not in [d.code for d in sink]


def test_negative_branch_lengths_are_reported_by_the_loader():
    sink = DiagnosticSink()
    load_trees("(Alpha:-0.5,Beta:1);", sink=sink)
    codes = [d.code for d in sink]
    assert "io.negative-branch-lengths" in codes, sink.format()


def test_negative_lengths_survive_reading_untouched():
    """The reader reports them; clamping is the drawing's business, not its own."""
    trees = load_trees("(Alpha:-0.5,Beta:1);")
    alpha = next(n for n in trees[0].leaves if n.name == "Alpha")
    assert alpha.branch_length == pytest.approx(-0.5)


def test_a_tree_with_positive_lengths_says_nothing_about_negatives():
    sink = DiagnosticSink()
    load_trees("(Alpha:0.5,Beta:1);", sink=sink)
    assert "io.negative-branch-lengths" not in [d.code for d in sink]


def test_a_broken_label_reports_rather_than_crashing():
    """Parentheses inside an unquoted label cannot be recovered, only reported."""
    sink = DiagnosticSink()
    trees = read_newick_multi("(E.coli(K12),str);", sink=sink)
    assert trees
    assert "newick.unclosed-parens" in [d.code for d in sink]


def test_nesting_can_be_switched_off_for_strict_newick():
    sink = DiagnosticSink()
    trees = read_newick_multi("(Alpha,Beta)[a [b] c];", sink=sink,
                              nested_comments=False)
    assert [n.name for n in trees[0].leaves] == ["Alpha", "Beta"]


NEXUS_CASES = [
    ("missing header", "begin trees; tree t = (Alpha,Beta); end;",
     "nexus.missing-header"),
    ("missing end", "#NEXUS\nbegin trees;\n tree t = (Alpha,Beta);\n",
     "nexus.unterminated-block"),
    ("duplicate translate key",
     "#NEXUS\nbegin trees; translate 1 Alpha, 1 Beta; tree t = (1,1); end;",
     "nexus.duplicate-translate-key"),
    ("unknown taxon",
     "#NEXUS\nbegin trees; translate 1 Alpha, 2 Beta; tree t = (1,Zeta); end;",
     "nexus.unknown-taxon"),
    ("ntax mismatch",
     "#NEXUS\nbegin taxa; dimensions ntax=5; taxlabels Alpha Beta; end;\n"
     "begin trees; tree t = (Alpha,Beta); end;",
     "nexus.ntax-mismatch"),
    ("tree without a body", "#NEXUS\nbegin trees; tree t; tree u = (A,B); end;",
     "nexus.tree-without-body"),
]


@pytest.mark.parametrize("label,text,code", NEXUS_CASES,
                         ids=[c[0] for c in NEXUS_CASES])
def test_nexus_malformations_are_repaired(label, text, code):
    sink = DiagnosticSink()
    trees = read_nexus(text, sink=sink)
    assert trees, label
    assert code in [d.code for d in sink], (label, sink.format())


def test_lowercase_rooting_comment_before_the_equals_sign():
    trees = read_nexus("#NEXUS\nbegin trees;\n\ttree [&u] t1 = (Alpha,Beta);\nend;")
    assert trees[0].rooted is False


def test_indented_mrbayes_style_tree_command():
    text = ("#NEXUS\nbegin trees;\n"
            "\ttree con_50 = [&R] ((Alpha:0.1[&length_mean=1.0e-01],"
            "Beta:0.2)[&prob=1.00000000e+00]:0.3,Gamma:0.4);\nend;\n")
    trees = read_nexus(text)
    inner = trees[0].root.children[0]
    assert inner.attrs["prob"] == 1.0
    assert trees[0].by_name("Alpha").attrs["length_mean"] == 0.1


def test_empty_input_is_an_error_not_a_tree():
    with pytest.raises(MakeYourTreeError):
        load_trees("")
    with pytest.raises(MakeYourTreeError):
        load_trees("   \n\t  ")


def test_non_ascii_bytes_do_not_kill_the_read():
    trees = load_trees(b"(Alpha,Sm\xf8rrebr\xf8d);")
    assert len(trees[0].leaves) == 2
