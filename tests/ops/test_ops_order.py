# SPDX-License-Identifier: MIT
"""Child-order operations.

The headline property is idempotence: without a total-order tie-break, ``sort``
is merely stable, so ladderizing a tree twice -- or ladderizing two files that
describe the same topology in a different order -- gives different pictures.
"""

from __future__ import annotations

import pytest

from makeyourtree.core.errors import OperationError
from makeyourtree.ops import ladderize, rotate, sort_children

from _ops_helpers import (build, caterpillar, leaf_names, newick, random_tree,
                          signature)


@pytest.mark.parametrize("key", ["size", "depth", "len", "name"])
@pytest.mark.parametrize("ascending", [True, False])
def test_ladderize_is_idempotent(key, ascending):
    tree = random_tree(30, seed=7)
    ladderize(tree, ascending=ascending, key=key).apply(tree)
    once = leaf_names(tree)
    cmd = ladderize(tree, ascending=ascending, key=key)
    cmd.apply(tree)
    assert leaf_names(tree) == once
    # A second run changed nothing, so its undo must also be a no-op.
    cmd.undo(tree)
    assert leaf_names(tree) == once


@pytest.mark.parametrize("key", ["size", "depth", "len", "name"])
def test_ladderize_does_not_depend_on_the_input_child_order(key):
    # Same topology, different declared order: the ladderized leaf order must agree.
    a = build("((x1:1,(x2:1,x3:1):1):1,(x4:1,x5:1):1);")
    b = build("((x5:1,x4:1):1,((x3:1,x2:1):1,x1:1):1);")
    ladderize(a, key=key).apply(a)
    ladderize(b, key=key).apply(b)
    assert leaf_names(a) == leaf_names(b)


def test_ladderize_ascending_and_descending_are_mirror_images():
    tree = random_tree(24, seed=5)
    ladderize(tree, ascending=True).apply(tree)
    up = leaf_names(tree)
    ladderize(tree, ascending=False).apply(tree)
    assert leaf_names(tree) == list(reversed(up))


def test_ladderize_by_size_puts_the_smaller_clade_first():
    tree = build("(((a:1,b:1):1,(c:1,(d:1,e:1):1):1):1,f:1);")
    ladderize(tree, ascending=True, key="size").apply(tree)
    assert leaf_names(tree) == ["f", "a", "b", "c", "d", "e"]


def test_ladderize_by_name_sorts_on_the_first_leaf_name():
    tree = build("((zz:1,mm:1):1,(bb:1,aa:1):1);")
    ladderize(tree, key="name").apply(tree)
    assert leaf_names(tree) == ["aa", "bb", "mm", "zz"]


def test_ladderize_by_length_uses_cumulative_depth():
    # "len" ranks by the greatest root-to-leaf length inside each subtree, so the
    # shallow-but-wide clade must come before the deep two-leaf one.
    tree = build("((a:0.1,b:0.1,c:0.1):1,(d:5,e:5):1);")
    ladderize(tree, ascending=True, key="len").apply(tree)
    assert leaf_names(tree) == ["a", "b", "c", "d", "e"]


def test_ladderize_changes_no_lengths_or_topology():
    tree = random_tree(20, seed=9)
    before = sorted(n.edge_length() for n in tree.nodes)
    parents_before = {n.id: (n.parent.id if n.parent else None) for n in tree.nodes}
    ladderize(tree).apply(tree)
    assert sorted(n.edge_length() for n in tree.nodes) == pytest.approx(before)
    assert {n.id: (n.parent.id if n.parent else None) for n in tree.nodes} == \
        parents_before


def test_ladderize_undo_restores_the_exact_order():
    tree = random_tree(30, seed=13)
    before = signature(tree)
    cmd = ladderize(tree, ascending=False, key="depth")
    cmd.apply(tree)
    assert signature(tree) != before
    cmd.undo(tree)
    assert signature(tree) == before


def test_ladderize_on_a_caterpillar_is_iterative():
    tree = caterpillar(20_000)
    ladderize(tree).apply(tree)
    assert tree.n_leaves == 20_000


def test_order_commands_declare_they_touch_only_order():
    tree = random_tree(8, seed=1)
    for cmd in (ladderize(tree), rotate(tree, tree.root),
                sort_children(tree, tree.root, "name", True)):
        assert cmd.touches_topology is False
        assert cmd.touches_order is True


def test_ladderize_rejects_an_unknown_key():
    tree = random_tree(6, seed=1)
    with pytest.raises(OperationError):
        ladderize(tree, key="colour")


def test_ladderize_accepts_a_callable_key():
    tree = build("((bb:1,aa:1):1,(dd:1,cc:1):1);")
    ladderize(tree, key=lambda n: n.name or "").apply(tree)
    # Internal nodes have no name, so the callable ties on them and the id
    # tie-break decides; the leaf pairs themselves must sort alphabetically.
    assert leaf_names(tree)[:2] == ["aa", "bb"]


def test_rotate_reverses_one_node_and_is_its_own_inverse():
    tree = build("((a:1,b:1):1,(c:1,d:1):1);")
    node = tree.by_name("a").parent
    cmd = rotate(tree, node)
    cmd.apply(tree)
    assert leaf_names(tree) == ["b", "a", "c", "d"]
    cmd.undo(tree)
    assert leaf_names(tree) == ["a", "b", "c", "d"]


def test_rotate_leaves_ancestors_and_lengths_alone():
    tree = build("((a:1,b:2):3,(c:4,d:5):6);")
    before = newick(tree, ids=False)
    node = tree.by_name("a").parent
    rotate(tree, node).apply(tree)
    assert newick(tree, ids=False) == before.replace("(a:1,b:2)", "(b:2,a:1)")


def test_rotate_refuses_a_leaf():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        rotate(tree, tree.by_name("a"))


def test_sort_children_touches_only_the_named_node():
    tree = build("((b1:1,a1:1):1,(b2:1,a2:1):1);")
    node = tree.by_name("b1").parent
    cmd = sort_children(tree, node, "name", True)
    cmd.apply(tree)
    assert leaf_names(tree) == ["a1", "b1", "b2", "a2"]
    cmd.undo(tree)
    assert leaf_names(tree) == ["b1", "a1", "b2", "a2"]


def test_sort_children_descending():
    tree = build("(a:1,c:1,b:1);")
    sort_children(tree, tree.root, "name", False).apply(tree)
    assert leaf_names(tree) == ["c", "b", "a"]


def test_sort_children_rejects_an_unknown_key():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        sort_children(tree, tree.root, "colour", True)
