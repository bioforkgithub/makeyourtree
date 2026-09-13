# SPDX-License-Identifier: MIT
"""The along coordinate: branch modes, scaling and length policy."""
from __future__ import annotations

import pytest

from makeyourtree.layout.linear import LinearLayout
from makeyourtree.layout.params import BranchMode, LayoutParams

from .conftest import C, L, build, rows_of, xs_of

MARGIN = 24.0
WIDTH = 900.0


def lay(tree, metrics, **kw):
    return LinearLayout().compute(tree, LayoutParams(**kw), metrics)


def test_phylogram_x_is_cumulative_length_fitted_to_width(three_tips, metrics):
    frame = lay(three_tips, metrics)
    assert frame.scale == pytest.approx(WIDTH / 1.0)
    assert frame.x(three_tips.root.id) == pytest.approx(MARGIN)
    xs = xs_of(frame, three_tips)
    assert xs["A"] == pytest.approx(MARGIN + 0.5 * WIDTH)
    assert xs["B"] == pytest.approx(MARGIN + 0.25 * WIDTH)
    assert xs["C"] == pytest.approx(MARGIN + WIDTH)


def test_explicit_x_scale_overrides_the_fit(three_tips, metrics):
    frame = lay(three_tips, metrics, x_scale=100.0)
    assert frame.scale == 100.0
    assert frame.x(three_tips.by_name("A").id) == pytest.approx(MARGIN + 50.0)
    assert frame.body_bounds[2] == pytest.approx(MARGIN + 100.0)


def test_cladogram_aligned_puts_every_tip_at_the_far_edge(unbalanced, metrics):
    frame = lay(unbalanced, metrics, branch_mode=BranchMode.CLADOGRAM_ALIGNED)
    assert frame.scale == 1.0
    far = MARGIN + WIDTH
    assert all(frame.x(t) == pytest.approx(far) for t in frame.tips)
    assert frame.x(unbalanced.root.id) == pytest.approx(MARGIN)


def test_cladogram_level_spaces_nodes_by_topological_depth(unbalanced, metrics):
    frame = lay(unbalanced, metrics, branch_mode=BranchMode.CLADOGRAM_LEVEL)
    step = WIDTH / 3.0
    xs = xs_of(frame, unbalanced)
    assert frame.x(unbalanced.root.id) == pytest.approx(MARGIN)
    assert xs["left"] == pytest.approx(MARGIN + step)
    assert xs["D"] == pytest.approx(MARGIN + step)
    assert xs["A"] == pytest.approx(MARGIN + 3 * step)
    assert xs["C"] == pytest.approx(MARGIN + 2 * step)


def test_negative_lengths_are_clamped_by_default(metrics):
    tree = build(C(L("A", -0.5), L("B", 1.0)))
    frame = lay(tree, metrics)
    assert frame.x(tree.by_name("A").id) == pytest.approx(MARGIN)


def test_negative_lengths_survive_when_the_user_says_so(metrics):
    tree = build(C(L("A", -0.5), L("B", 1.0)))
    frame = lay(tree, metrics, ignore_negative_lengths=False)
    assert frame.x(tree.by_name("A").id) == pytest.approx(MARGIN - 0.5 * WIDTH)


def test_min_branch_length_floors_zero_length_edges(metrics):
    tree = build(C(L("A", 0.0), L("B", 1.0)))
    plain = lay(tree, metrics)
    floored = lay(tree, metrics, min_branch_length=0.25)
    assert plain.x(tree.by_name("A").id) == pytest.approx(MARGIN)
    assert floored.x(tree.by_name("A").id) > MARGIN + 100.0


def test_missing_lengths_give_a_degenerate_but_usable_scale(metrics):
    tree = build(C(L("A", None), L("B", None)))
    frame = lay(tree, metrics)
    assert frame.scale == 0.0
    assert frame.x(tree.by_name("A").id) == pytest.approx(MARGIN)
    assert frame.body_bounds[2] == pytest.approx(MARGIN + WIDTH)
    assert frame.n_rows == 2.0


def test_switching_branch_mode_changes_x_but_never_rows(unbalanced, metrics):
    phylo = lay(unbalanced, metrics, branch_mode=BranchMode.PHYLOGRAM)
    clado = lay(unbalanced, metrics, branch_mode=BranchMode.CLADOGRAM_ALIGNED)
    assert rows_of(phylo, unbalanced) == rows_of(clado, unbalanced)
    assert xs_of(phylo, unbalanced) != xs_of(clado, unbalanced)


def test_reordering_children_changes_rows_but_never_x(three_tips, metrics):
    before = lay(three_tips, metrics)
    three_tips.root.children.reverse()
    after = lay(three_tips, metrics)
    assert xs_of(before, three_tips) == xs_of(after, three_tips)
    assert rows_of(before, three_tips) != rows_of(after, three_tips)
    assert after.row(three_tips.by_name("A").id) == 2.5


def test_ladderizing_by_subtree_size_reorders_rows_only(unbalanced, metrics):
    before = lay(unbalanced, metrics)
    for node in unbalanced.nodes:
        if len(node.children) > 1:
            node.children.sort(key=lambda c: (c.n_leaves, c.name or ""))
    after = lay(unbalanced, metrics)
    assert xs_of(before, unbalanced) == xs_of(after, unbalanced)
    assert [unbalanced.by_id(t).name for t in before.tips] == ["A", "B", "C", "D"]
    assert [unbalanced.by_id(t).name for t in after.tips] == ["D", "C", "A", "B"]


# ------------------------------------------------- negative lengths, reported


def test_negative_lengths_are_counted_onto_the_frame(metrics):
    """A layout has no diagnostic sink, so the count travels on the frame."""
    tree = build(C(L("A", -0.5), C(L("B", 1.0), L("C", -0.25))))
    frame = lay(tree, metrics)
    assert frame.metadata["negative_lengths_clamped"] == 2


def test_nothing_is_counted_when_no_length_is_negative(three_tips, metrics):
    assert three_tips is not None
    frame = lay(three_tips, metrics)
    assert frame.metadata.get("negative_lengths_clamped", 0) == 0


def test_no_count_is_published_when_clamping_is_switched_off(metrics):
    """With ``ignore_negative_lengths`` off nothing is flattened, so there is
    nothing to report; publishing a count would make the compositor warn about
    a change that never happened."""
    tree = build(C(L("A", -0.5), L("B", 1.0)))
    frame = lay(tree, metrics, ignore_negative_lengths=False)
    assert "negative_lengths_clamped" not in frame.metadata


def test_the_clamp_flattens_the_drawn_edge_but_not_the_data(metrics):
    tree = build(C(L("A", -0.5), L("B", 1.0)))
    frame = lay(tree, metrics)
    root_x = frame.x(tree.root.id)
    assert frame.x(tree.by_name("A").id) == pytest.approx(root_x)
    assert tree.by_name("A").branch_length == pytest.approx(-0.5)
