# SPDX-License-Identifier: MIT
"""Rerooting: the invariants that catch the edge-transfer bug.

Rerooting reverses edges, and a length or support left behind on the wrong node
produces a tree that still parses, still draws, and is quietly wrong.  Three
properties pin it down and are checked here over every edge of several random
trees: the total tree length, every pairwise patristic distance, and the map from
bipartition to support.
"""

from __future__ import annotations

import pytest

from makeyourtree.core.errors import OperationError
from makeyourtree.core.traversal import iter_leaves
from makeyourtree.ops import midpoint_root, outgroup_root, reroot_on_edge, unroot

from _ops_helpers import (bipartitions, build, caterpillar, newick,
                          pairwise_distances, random_tree, signature,
                          total_length)


def _reroot_targets(tree):
    """Every edge of the tree, named by its child endpoint."""
    return [n for n in tree.nodes if n.parent is not None]


def _leaf_names(node):
    return {lf.name for lf in iter_leaves(node)}


@pytest.mark.parametrize("seed", range(6))
def test_reroot_then_undo_restores_the_tree_exactly(seed):
    tree = random_tree(12, seed=seed)
    before = signature(tree)
    for target in _reroot_targets(tree):
        cmd = reroot_on_edge(tree, target)
        cmd.apply(tree)
        assert signature(tree) != before
        cmd.undo(tree)
        assert signature(tree) == before


@pytest.mark.parametrize("seed", range(6))
def test_reroot_preserves_total_length_and_all_distances(seed):
    tree = random_tree(14, seed=seed)
    length_before = total_length(tree)
    dists_before = pairwise_distances(tree)
    for target in _reroot_targets(tree):
        cmd = reroot_on_edge(tree, target, dist_from_node=0.25 * target.edge_length())
        cmd.apply(tree)
        assert total_length(tree) == pytest.approx(length_before)
        after = pairwise_distances(tree)
        assert set(after) == set(dists_before)
        for key, d in dists_before.items():
            assert after[key] == pytest.approx(d), f"{key} moved after rerooting"
        cmd.undo(tree)


@pytest.mark.parametrize("seed", range(6))
def test_support_values_stay_on_their_bipartitions(seed):
    tree = random_tree(15, seed=seed, root_degree=3)
    before = bipartitions(tree)
    assert len(before) >= 10
    assert all(len(v) == 1 for v in before.values()), "fixture supports are not distinct"
    for target in _reroot_targets(tree):
        cmd = reroot_on_edge(tree, target)
        cmd.apply(tree)
        after = bipartitions(tree)
        assert set(after) == set(before), "rerooting invented or lost a bipartition"
        for split, values in before.items():
            assert after[split] == values, "a support value changed bipartition"
        cmd.undo(tree)


def test_support_survives_a_bifurcating_root_being_suppressed():
    # The two edges below a bifurcating root describe one split and so carry one
    # number; rerooting elsewhere fuses them, and that number must survive intact.
    tree = build("((a:1,b:1)[70]:0.5,((c:1,d:1)[88]:1,e:2)[70]:0.5);")
    before = bipartitions(tree)
    assert before == {frozenset({"c", "d", "e"}): {70.0}, frozenset({"c", "d"}): {88.0}}
    reroot_on_edge(tree, tree.by_name("c")).apply(tree)
    assert bipartitions(tree) == before
    assert len(tree.root.children) == 2


def test_reroot_splits_the_edge_at_the_requested_offset():
    tree = build("((a:1,b:1):4,c:6,d:7);")
    reroot_on_edge(tree, tree.by_name("a").parent, dist_from_node=1.5).apply(tree)
    assert sorted(c.edge_length() for c in tree.root.children) == pytest.approx([1.5, 2.5])


def test_reroot_offset_is_clamped_into_the_edge():
    tree = build("((a:1,b:1):4,c:6,d:7);")
    reroot_on_edge(tree, tree.by_name("a").parent, dist_from_node=99.0).apply(tree)
    assert sorted(c.edge_length() for c in tree.root.children) == pytest.approx([0.0, 4.0])


def test_reroot_default_offset_is_the_middle_of_the_edge():
    tree = build("((a:1,b:1):4,c:6,d:7);")
    reroot_on_edge(tree, tree.by_name("a").parent).apply(tree)
    assert sorted(c.edge_length() for c in tree.root.children) == pytest.approx([2.0, 2.0])


def test_reroot_keeps_a_cladogram_free_of_invented_lengths():
    tree = build("((a,b),(c,d));")
    reroot_on_edge(tree, tree.by_name("c")).apply(tree)
    assert not tree.has_branch_lengths


def test_reroot_on_the_root_is_refused():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        reroot_on_edge(tree, tree.root)


def test_reroot_preserves_polytomies_at_the_old_root():
    tree = build("(a:1,b:1,(c:1,d:1):1);")
    reroot_on_edge(tree, tree.by_name("c")).apply(tree)
    # The old root lost one child of three, so it is still a branching node and must
    # not be suppressed; only a root left with a single child is an artefact.
    assert sorted(len(n.children) for n in tree.nodes if n.children) == [2, 2, 2]
    assert total_length(tree) == pytest.approx(5.0)


def test_reroot_redo_matches_the_first_apply():
    tree = random_tree(10, seed=3)
    cmd = reroot_on_edge(tree, tree.by_name("t4"))
    cmd.apply(tree)
    first = signature(tree)
    cmd.undo(tree)
    cmd.redo(tree)
    assert signature(tree) == first


def test_reroot_on_a_deep_caterpillar_does_not_recurse():
    n = 20_000
    tree = caterpillar(n)
    before = total_length(tree)
    assert before == pytest.approx(2 * n - 2)
    cmd = reroot_on_edge(tree, tree.by_name(f"c{n - 1}"))
    cmd.apply(tree)
    assert tree.n_leaves == n
    assert total_length(tree) == pytest.approx(before)
    cmd.undo(tree)
    assert tree.n_leaves == n
    assert total_length(tree) == pytest.approx(before)


@pytest.mark.parametrize("seed", range(6))
def test_midpoint_root_makes_the_two_deepest_leaves_equidistant(seed):
    tree = random_tree(20, seed=seed)
    (na, nb), diameter = max(pairwise_distances(tree).items(), key=lambda kv: kv[1])
    midpoint_root(tree).apply(tree)
    tree.refresh()
    assert tree.by_name(na).depth_len == pytest.approx(diameter / 2.0)
    assert tree.by_name(nb).depth_len == pytest.approx(diameter / 2.0)
    assert tree.max_root_to_tip == pytest.approx(diameter / 2.0)


def test_midpoint_root_is_idempotent():
    tree = random_tree(18, seed=11)
    midpoint_root(tree).apply(tree)
    tree.refresh()
    once_distances = pairwise_distances(tree)
    once_depth = tree.max_root_to_tip
    midpoint_root(tree).apply(tree)
    tree.refresh()
    assert pairwise_distances(tree) == pytest.approx(once_distances)
    assert tree.max_root_to_tip == pytest.approx(once_depth)


def test_midpoint_root_handles_a_dominant_terminal_edge():
    # The longest path ends on a tip edge, so the root lands on a terminal branch.
    tree = build("((a:0.1,b:0.1):0.1,c:10);")
    midpoint_root(tree).apply(tree)
    tree.refresh()
    assert tree.by_name("c").depth_len == pytest.approx(5.1)
    assert total_length(tree) == pytest.approx(10.3)


def test_midpoint_root_works_with_negative_branch_lengths():
    # Distance methods emit negative branches; the longest-path search must still
    # find the true extremes, not the ones a clamped search would pick.
    tree = build("((a:5,b:-0.5):1,(c:0.2,d:0.2):1);")
    (na, nb), diameter = max(pairwise_distances(tree).items(), key=lambda kv: kv[1])
    assert na == "a" and nb in ("c", "d")
    midpoint_root(tree).apply(tree)
    tree.refresh()
    assert tree.by_name(na).depth_len == pytest.approx(diameter / 2.0)
    assert tree.by_name(nb).depth_len == pytest.approx(diameter / 2.0)


def test_midpoint_root_on_a_caterpillar_is_iterative():
    n = 20_000
    tree = caterpillar(n)
    midpoint_root(tree).apply(tree)
    tree.refresh()
    assert tree.max_root_to_tip == pytest.approx(n / 2.0)


def test_midpoint_root_needs_two_leaves():
    with pytest.raises(OperationError):
        midpoint_root(build("a;"))


def test_outgroup_root_puts_the_outgroup_below_the_root():
    tree = build("(((a:1,b:1):1,(c:1,d:1):1):1,(o1:1,o2:1):2);")
    outgroup_root(tree, ["o1", "o2"]).apply(tree)
    assert len(tree.root.children) == 2
    outgroup_side = next(k for k in tree.root.children
                         if _leaf_names(k) == {"o1", "o2"})
    assert outgroup_side.edge_length() == pytest.approx(1.0)
    ingroup_side = next(k for k in tree.root.children if k is not outgroup_side)
    assert _leaf_names(ingroup_side) == {"a", "b", "c", "d"}
    assert ingroup_side.edge_length() == pytest.approx(2.0)


def test_outgroup_root_honours_the_fraction():
    tree = build("(((a:1,b:1):1,(c:1,d:1):1):1,(o1:1,o2:1):2);")
    outgroup_root(tree, ["o1", "o2"], at_fraction=0.25).apply(tree)
    og = next(k for k in tree.root.children if _leaf_names(k) == {"o1", "o2"})
    assert og.edge_length() == pytest.approx(0.5)


def test_outgroup_root_accepts_an_outgroup_that_spans_the_current_root():
    # {o1, o2} is not a clade in this rooting, but it is one side of a real split:
    # the complement {a, b} is a clade, so the tree can be rooted on that edge.
    tree = build("(o1:1,(a:1,b:1):1,o2:1);")
    outgroup_root(tree, ["o1", "o2"]).apply(tree)
    sides = [_leaf_names(k) for k in tree.root.children]
    assert {"o1", "o2"} in sides and {"a", "b"} in sides


def test_outgroup_root_accepts_an_internal_node_as_the_outgroup():
    tree = build("(((a:1,b:1):1,(c:1,d:1):1):1,(o1:1,o2:1):2);")
    stem = tree.by_name("o1").parent
    outgroup_root(tree, [stem]).apply(tree)
    sides = [_leaf_names(k) for k in tree.root.children]
    assert sorted(map(sorted, sides)) == [["a", "b", "c", "d"], ["o1", "o2"]]


def test_outgroup_root_names_the_offending_taxa():
    tree = build("((o1:1,ing1:1):1,(o2:1,ing2:1):1);")
    with pytest.raises(OperationError) as exc:
        outgroup_root(tree, ["o1", "o2"])
    message = str(exc.value)
    assert "monophyletic" in message
    assert "ing1" in message and "ing2" in message


def test_outgroup_root_refuses_the_whole_tree():
    tree = build("((a:1,b:1):1,c:1);")
    with pytest.raises(OperationError):
        outgroup_root(tree, ["a", "b", "c"])


def test_outgroup_root_preserves_distances_and_undoes():
    tree = build("(((a:1,b:2):1,(c:3,d:1):1):1,(o1:1,o2:2):2);")
    before, sig = pairwise_distances(tree), signature(tree)
    cmd = outgroup_root(tree, ["o1", "o2"])
    cmd.apply(tree)
    assert pairwise_distances(tree) == pytest.approx(before)
    cmd.undo(tree)
    assert signature(tree) == sig


def test_unroot_makes_a_trifurcation_and_sums_the_root_edges():
    tree = build("((a:1,b:1):2,(c:1,d:1):3);")
    before, sig = pairwise_distances(tree), signature(tree)
    cmd = unroot(tree)
    cmd.apply(tree)
    assert not tree.rooted
    assert len(tree.root.children) == 3
    assert tree.root.branch_length is None
    moved = next(c for c in tree.root.children if c.children)
    assert moved.edge_length() == pytest.approx(5.0)
    assert pairwise_distances(tree) == pytest.approx(before)
    cmd.undo(tree)
    assert signature(tree) == sig
    assert tree.rooted


def test_unroot_keeps_the_support_of_the_fused_root_edges():
    tree = build("((a:1,b:1)[95]:2,(c:1,d:1)[95]:3);")
    unroot(tree).apply(tree)
    moved = next(c for c in tree.root.children if c.children)
    assert moved.support == pytest.approx(95.0)


def test_unroot_of_a_polytomous_root_only_clears_the_flag():
    tree = build("(a:1,b:1,(c:1,d:1):1);")
    sig = newick(tree, ids=True)
    cmd = unroot(tree)
    cmd.apply(tree)
    assert not tree.rooted
    assert newick(tree, ids=True) == sig
    cmd.undo(tree)
    assert tree.rooted


def test_unroot_of_a_two_taxon_tree_is_refused():
    tree = build("(a:1,b:1);")
    with pytest.raises(OperationError):
        unroot(tree).apply(tree)
