# SPDX-License-Identifier: MIT
"""Where internal nodes sit on the cross axis, per :class:`ParentRule`."""
from __future__ import annotations

import pytest

from makeyourtree.layout.linear import LinearLayout
from makeyourtree.layout.params import LayoutParams, ParentRule

from .conftest import C, L, balanced, build, rows_of


def lay(tree, metrics, rule):
    return LinearLayout().compute(tree, LayoutParams(parent_rule=rule), metrics)


@pytest.fixture
def polytomy():
    """A three-way split whose children hold 2, 1 and 1 tips."""
    return build(C(C(L("A"), L("B"), name="ab"), L("C"), L("D")))


def test_all_rules_agree_on_a_balanced_binary_tree(metrics):
    tree = balanced(3)
    seen = {rule: rows_of(lay(tree, metrics, rule), tree) for rule in ParentRule}
    assert seen[ParentRule.MIDPOINT] == seen[ParentRule.MEAN]
    assert seen[ParentRule.MIDPOINT] == seen[ParentRule.WEIGHTED]


def test_midpoint_and_mean_agree_on_every_binary_tree(unbalanced, metrics):
    mid = lay(unbalanced, metrics, ParentRule.MIDPOINT)
    mean = lay(unbalanced, metrics, ParentRule.MEAN)
    assert rows_of(mid, unbalanced) == rows_of(mean, unbalanced)


def test_weighted_is_the_tip_centroid_not_the_extreme_midpoint(unbalanced, metrics):
    """Documents a real divergence: WEIGHTED puts a node at the centre of the
    rows its subtree occupies, which on an UNBALANCED binary tree is not the
    midpoint of its two children.  ``ParentRule``'s docstring claims all three
    rules agree on binary trees; that holds for MIDPOINT and MEAN only."""
    weighted = lay(unbalanced, metrics, ParentRule.WEIGHTED)
    root = unbalanced.root
    lo, hi = weighted.row_span(root.id)
    assert weighted.row(root.id) == pytest.approx((lo + hi) / 2)
    assert weighted.row(root.id) == pytest.approx(2.0)

    midpoint = lay(unbalanced, metrics, ParentRule.MIDPOINT)
    assert midpoint.row(root.id) == pytest.approx(2.625)


def test_the_three_rules_split_at_a_polytomy(polytomy, metrics):
    root = polytomy.root.id
    assert lay(polytomy, metrics, ParentRule.MIDPOINT).row(root) == pytest.approx(2.25)
    assert lay(polytomy, metrics, ParentRule.MEAN).row(root) == pytest.approx(7 / 3)
    assert lay(polytomy, metrics, ParentRule.WEIGHTED).row(root) == pytest.approx(2.0)


def test_midpoint_row_is_a_function_of_the_span_alone(polytomy, metrics):
    """The property that makes rotation a local update: reordering children
    below a node must not move the node, its ancestors, or their spans."""
    before = lay(polytomy, metrics, ParentRule.MIDPOINT)
    root_row = before.row(polytomy.root.id)
    ab = polytomy.by_name("ab")
    ab_row, ab_span = before.row(ab.id), before.row_span(ab.id)

    ab.children.reverse()
    after = lay(polytomy, metrics, ParentRule.MIDPOINT)
    assert after.row(polytomy.root.id) == root_row
    assert after.row(ab.id) == ab_row
    assert after.row_span(ab.id) == ab_span
    assert after.row(polytomy.by_name("A").id) == 1.5
