# SPDX-License-Identifier: MIT
"""Selection queries: pure reads, predictable order."""

from __future__ import annotations

import pytest

from makeyourtree.core.errors import OperationError
from makeyourtree.ops import (select_by_name, select_clade, select_leaves,
                          select_path)

from _ops_helpers import build, caterpillar, names_of, signature


def test_select_clade_is_preorder_and_includes_the_node():
    tree = build("((a:1,b:1)inner:1,(c:1,d:1):1);")
    node = tree.by_name("inner")
    got = select_clade(tree, node)
    assert got[0] is node
    assert names_of(got[1:]) == ["a", "b"]


def test_select_clade_stops_at_a_collapsed_node_when_asked():
    tree = build("((a:1,b:1)inner:1,(c:1,d:1):1);")
    tree.by_name("inner").collapsed = True
    assert len(select_clade(tree, tree.root)) == 7
    visible = select_clade(tree, tree.root, visible_only=True)
    assert "a" not in names_of(visible) and "c" in names_of(visible)


def test_select_clade_skips_hidden_subtrees():
    tree = build("((a:1,b:1)inner:1,(c:1,d:1):1);")
    tree.by_name("inner").hidden = True
    visible = select_clade(tree, tree.root, visible_only=True)
    assert len(visible) == 4
    assert {n.name for n in visible if n.name} == {"c", "d"}


def test_select_leaves_left_to_right():
    tree = build("((a:1,b:1):1,(c:1,d:1):1);")
    assert names_of(select_leaves(tree, tree.root)) == ["a", "b", "c", "d"]


def test_select_leaves_of_a_leaf_is_that_leaf():
    tree = build("((a:1,b:1):1,c:1);")
    assert names_of(select_leaves(tree, "a")) == ["a"]


def test_select_leaves_yields_tips_when_visible_only():
    tree = build("((a:1,b:1)inner:1,(c:1,d:1):1);")
    tree.by_name("inner").collapsed = True
    assert names_of(select_leaves(tree, tree.root, visible_only=True)) == \
        ["inner", "c", "d"]


def test_select_path_walks_through_the_mrca():
    tree = build("((a:1,b:1):1,(c:1,d:1):1);")
    path = select_path(tree, "a", "d")
    assert path[0] is tree.by_name("a")
    assert path[-1] is tree.by_name("d")
    assert tree.root in path
    # Consecutive entries must be adjacent, so the result can be paired into edges.
    for x, y in zip(path, path[1:]):
        assert x.parent is y or y.parent is x


def test_select_path_from_a_node_to_itself_is_that_node():
    tree = build("((a:1,b:1):1,c:1);")
    assert select_path(tree, "a", "a") == [tree.by_name("a")]


def test_select_path_on_a_caterpillar_is_iterative():
    tree = caterpillar(20_000)
    path = select_path(tree, "c0", "c19999")
    # c0 hangs off the root, c19999 sits at the far end of the spine.
    assert len(path) == 20_001
    assert path[1] is tree.root


def test_select_by_name_matches_substrings_case_insensitively():
    tree = build("((Alpha:1,beta:1):1,gamma:1);")
    assert names_of(select_by_name(tree, "a")) == ["Alpha", "beta", "gamma"]
    assert names_of(select_by_name(tree, "ALPHA")) == ["Alpha"]


def test_select_by_name_forwards_search_options():
    tree = build("((Alpha:1,beta:1):1,gamma:1);")
    assert names_of(select_by_name(tree, "^g", regex=True)) == ["gamma"]
    assert select_by_name(tree, "alpha", case_sensitive=True) == []
    assert names_of(select_by_name(tree, "beta", whole_word=True)) == ["beta"]


def test_selection_never_changes_the_tree():
    tree = build("((a:1,b:1)inner:1,(c:1,d:1):1);")
    before = signature(tree)
    select_clade(tree, "inner")
    select_leaves(tree, tree.root)
    select_path(tree, "a", "d")
    select_by_name(tree, "a")
    assert signature(tree) == before


def test_selection_rejects_an_unknown_reference():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        select_clade(tree, "nope")
