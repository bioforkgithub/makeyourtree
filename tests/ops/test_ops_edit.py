# SPDX-License-Identifier: MIT
"""Structural edits: pruning, deletion, singleton removal, extraction, naming.

The property that matters for pruning and deletion is the same one that matters
for rerooting: distances between the taxa that survive must not move.  That is
what catches a branch length dropped instead of summed onto the surviving edge.
"""

from __future__ import annotations

import pytest

from makeyourtree.core.errors import OperationError
from makeyourtree.core.traversal import iter_leaves
from makeyourtree.ops import (collapse, collapse_singletons, delete_node, expand,
                          extract_subtree, prune, rename)

from _ops_helpers import (build, caterpillar, leaf_names, newick,
                          pairwise_distances, random_tree, signature,
                          total_length)


def _distances_between(tree, names):
    keep = set(names)
    return {k: v for k, v in pairwise_distances(tree).items()
            if k[0] in keep and k[1] in keep}


@pytest.mark.parametrize("seed", range(6))
def test_prune_preserves_distances_among_survivors(seed):
    tree = random_tree(20, seed=seed)
    victims = [f"t{i}" for i in (1, 4, 9, 17)]
    survivors = [n for n in leaf_names(tree) if n not in victims]
    before = _distances_between(tree, survivors)
    prune(tree, victims).apply(tree)
    assert sorted(leaf_names(tree)) == sorted(survivors)
    after = pairwise_distances(tree)
    assert set(after) == set(before)
    for key, d in before.items():
        assert after[key] == pytest.approx(d), f"{key} moved after pruning"


def test_prune_suppresses_the_degree_two_node_it_leaves_behind():
    tree = build("((a:1,b:2):3,(c:4,d:5):6);")
    prune(tree, ["b"]).apply(tree)
    # `a` loses its sibling, so its parent is spliced out and the two lengths fuse.
    assert newick(tree) == "(a:4,(c:4,d:5):6);"
    assert total_length(tree) == pytest.approx(19.0)


def test_prune_cascades_through_emptied_clades():
    tree = build("(((a:1,b:1):1,(c:1,d:1):1):1,(e:1,f:1):1);")
    prune(tree, ["a", "b", "c", "d"]).apply(tree)
    assert sorted(leaf_names(tree)) == ["e", "f"]
    # Everything above the removed leaves was emptied and then promoted away, so
    # the survivors' own clade is now the root.
    assert len(tree.root.children) == 2


def test_prune_accepts_a_whole_clade():
    tree = build("(((a:1,b:1):1,c:1):1,(d:1,e:1):1);")
    clade = tree.by_name("a").parent
    prune(tree, [clade]).apply(tree)
    assert sorted(leaf_names(tree)) == ["c", "d", "e"]


def test_prune_ignores_nodes_nested_in_other_victims():
    tree = build("(((a:1,b:1):1,c:1):1,(d:1,e:1):1);")
    clade = tree.by_name("a").parent
    prune(tree, [clade, "a", "b"]).apply(tree)
    assert sorted(leaf_names(tree)) == ["c", "d", "e"]


def test_prune_undo_restores_everything():
    tree = random_tree(24, seed=2)
    before = signature(tree)
    cmd = prune(tree, ["t3", "t8", "t11", "t19"])
    cmd.apply(tree)
    assert signature(tree) != before
    cmd.undo(tree)
    assert signature(tree) == before


def test_prune_redo_matches_the_first_apply():
    tree = random_tree(16, seed=6)
    cmd = prune(tree, ["t2", "t5"])
    cmd.apply(tree)
    first = signature(tree)
    cmd.undo(tree)
    cmd.redo(tree)
    assert signature(tree) == first


def test_prune_refuses_to_empty_the_tree():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        prune(tree, ["a", "b", "c"])


def test_prune_refuses_the_root():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        prune(tree, [tree.root])


def test_prune_needs_a_target():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        prune(tree, [])


def test_prune_on_a_caterpillar_is_iterative():
    tree = caterpillar(20_000)
    prune(tree, [f"c{i}" for i in range(0, 2_000)]).apply(tree)
    assert tree.n_leaves == 18_000


@pytest.mark.parametrize("seed", range(4))
def test_delete_node_keeps_every_leaf_at_its_root_distance(seed):
    # Summing the deleted edge onto each child edge is what holds the tips still.
    # It does not hold the distance *between* the children fixed -- that path used
    # the deleted edge once and now uses its length twice -- and it cannot: the
    # branching point they met at no longer exists.
    tree = random_tree(15, seed=seed)
    tree.refresh()
    before = {lf.id: lf.depth_len for lf in iter_leaves(tree.root)}
    sig = signature(tree)
    victims = [n for n in tree.nodes if n.children and n.parent is not None][:3]
    for v in victims:
        cmd = delete_node(tree, v)
        cmd.apply(tree)
        tree.refresh()
        assert {lf.id: lf.depth_len for lf in iter_leaves(tree.root)} == \
            pytest.approx(before)
        cmd.undo(tree)
        assert signature(tree) == sig


def test_delete_of_a_unary_node_preserves_every_distance():
    tree = build("(((a:1,b:1):2):3,(c:1,d:1):4);")
    before = pairwise_distances(tree)
    stem = tree.by_name("a").parent.parent
    assert len(stem.children) == 1
    delete_node(tree, stem).apply(tree)
    assert pairwise_distances(tree) == pytest.approx(before)


def test_delete_node_reattaches_children_in_place():
    tree = build("((a:1,b:1):2,(c:1,d:1):3);")
    node = tree.by_name("a").parent
    cmd = delete_node(tree, node)
    cmd.apply(tree)
    assert newick(tree) == "(a:3,b:3,(c:1,d:1):3);"
    cmd.undo(tree)
    assert newick(tree) == "((a:1,b:1):2,(c:1,d:1):3);"


def test_delete_node_on_a_leaf_just_removes_it():
    tree = build("((a:1,b:1):2,c:3);")
    delete_node(tree, "b").apply(tree)
    assert sorted(leaf_names(tree)) == ["a", "c"]


def test_delete_node_refuses_the_root():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        delete_node(tree, tree.root).apply(tree)


def test_delete_node_keeps_support_only_when_the_split_survives():
    # One child: the fused edge induces the same bipartition, so 88 carries over.
    tree = build("(((a:1,b:1)[88]:2):1,c:1);")
    stem = tree.by_name("a").parent.parent
    delete_node(tree, stem).apply(tree)
    assert tree.by_name("a").parent.support == pytest.approx(88.0)

    # Two children: the deleted node's own split is gone, so its number goes too.
    tree2 = build("((a:1,b:1)[88]:2,c:1);")
    node = tree2.by_name("a").parent
    delete_node(tree2, node).apply(tree2)
    assert all(n.support is None for n in tree2.nodes)


def test_collapse_singletons_removes_every_unary_node():
    tree = build("((((a:1):1,b:1):1):1,c:1);")
    before = pairwise_distances(tree)
    cmd = collapse_singletons(tree)
    cmd.apply(tree)
    assert all(len(n.children) != 1 for n in tree.nodes)
    assert pairwise_distances(tree) == pytest.approx(before)
    assert newick(tree) == "((a:2,b:1):2,c:1);"
    cmd.undo(tree)
    assert any(len(n.children) == 1 for n in tree.nodes)


def test_collapse_singletons_leaves_a_stem_root_alone():
    tree = build("((a:1,b:1):1);")
    collapse_singletons(tree).apply(tree)
    assert len(tree.root.children) == 1


def test_collapse_singletons_is_a_no_op_on_a_clean_tree():
    tree = random_tree(12, seed=4)
    before = signature(tree)
    collapse_singletons(tree).apply(tree)
    assert signature(tree) == before


def test_extract_subtree_copies_without_touching_the_source():
    tree = build("(((a:1,b:1):2,c:3):1,(d:1,e:1):1);")
    node = tree.by_name("a").parent.parent
    before = signature(tree)
    sub = extract_subtree(tree, node)
    assert signature(tree) == before
    assert sorted(leaf_names(sub)) == ["a", "b", "c"]
    assert sub.root.branch_length is None
    assert sub.root.support is None
    assert sub.by_name("a") is not tree.by_name("a")
    assert sub.by_name("a").id == tree.by_name("a").id
    assert sub.distance("a", "c") == pytest.approx(tree.distance("a", "c"))


def test_extract_subtree_of_a_leaf_is_a_one_node_tree():
    tree = build("((a:1,b:1):1,c:1);")
    sub = extract_subtree(tree, "a")
    assert sub.n_leaves == 1
    assert sub.root.name == "a"


def test_collapse_and_expand_round_trip():
    tree = build("((a:1,b:1):1,(c:1,d:1):1);")
    node = tree.by_name("a").parent
    cmd = collapse(tree, node)
    cmd.apply(tree)
    assert node.collapsed
    assert [t.id for t in tree.tips] == [node.id, tree.by_name("c").id,
                                         tree.by_name("d").id]
    expand(tree, node).apply(tree)
    assert not node.collapsed
    cmd.undo(tree)
    assert not node.collapsed


def test_collapse_refuses_a_leaf():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        collapse(tree, "a")


def test_rename_updates_the_name_index_both_ways():
    tree = build("((a:1,b:1):1,c:1);")
    cmd = rename(tree, "a", "alpha")
    cmd.apply(tree)
    assert tree.by_name("alpha") is not None
    assert tree.by_name("a") is None
    cmd.undo(tree)
    assert tree.by_name("a") is not None
    assert tree.by_name("alpha") is None


def test_rename_can_clear_a_name():
    tree = build("((a:1,b:1):1,c:1);")
    node = tree.by_name("a")
    rename(tree, node, None).apply(tree)
    assert node.name is None


def test_rename_does_not_touch_topology():
    tree = build("((a:1,b:1):1,c:1);")
    assert rename(tree, "a", "z").touches_topology is False


def test_edits_leave_no_dangling_ids_in_the_index():
    tree = random_tree(14, seed=8)
    removed = tree.by_name("t3").id
    prune(tree, ["t3"]).apply(tree)
    assert tree.by_id(removed) is None
    assert all(tree.by_id(n.id) is n for n in iter_leaves(tree.root))
