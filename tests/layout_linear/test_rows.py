# SPDX-License-Identifier: MIT
"""The cross coordinate: row allocation and row spans."""
from __future__ import annotations

import pytest

from makeyourtree.layout.linear import LinearLayout
from makeyourtree.layout.params import LayoutMode, LayoutParams, ParentRule

from .conftest import C, L, balanced, build, rows_of


def lay(tree, metrics, **kw):
    return LinearLayout().compute(tree, LayoutParams(**kw), metrics)


def test_leaf_rows_are_half_integers(three_tips, metrics):
    frame = lay(three_tips, metrics)
    assert [frame.row(t) for t in frame.tips] == [0.5, 1.5, 2.5]


def test_leaf_row_spans_are_unit_and_contiguous(three_tips, metrics):
    frame = lay(three_tips, metrics)
    spans = [frame.row_span(t) for t in frame.tips]
    assert spans == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    assert frame.n_rows == 3.0


def test_tips_are_in_left_to_right_order(three_tips, metrics):
    frame = lay(three_tips, metrics)
    names = [three_tips.by_id(t).name for t in frame.tips]
    assert names == ["A", "B", "C"]


def test_root_of_a_balanced_tree_sits_at_the_midpoint(metrics):
    tree = balanced(3)
    frame = lay(tree, metrics)
    assert frame.n_rows == 8.0
    assert frame.row(tree.root.id) == 4.0
    assert frame.row_span(tree.root.id) == (0.0, 8.0)


def test_internal_node_span_covers_exactly_its_subtree(unbalanced, metrics):
    frame = lay(unbalanced, metrics)
    left = unbalanced.by_name("left")
    assert frame.row_span(left.id) == (0.0, 3.0)
    assert frame.row(left.id) == pytest.approx(1.75)
    assert frame.row_span(unbalanced.root.id) == (0.0, 4.0)


def test_scene_y_is_row_times_row_height_plus_margin(three_tips, metrics):
    frame = lay(three_tips, metrics, row_spacing=20.0, margin=10.0)
    assert frame.row_height == 20.0
    for tip in frame.tips:
        assert frame.y(tip) == pytest.approx(10.0 + frame.row(tip) * 20.0)


def test_explicit_height_divides_into_rows(three_tips, metrics):
    frame = lay(three_tips, metrics, height=90.0)
    assert frame.row_height == pytest.approx(30.0)
    assert frame.body_bounds[3] - frame.body_bounds[1] == pytest.approx(90.0)


def test_hidden_subtree_consumes_no_rows(metrics):
    tree = build(C(L("A"), C(L("B"), L("C")), L("D")))
    tree.by_name("B").parent.hidden = True
    frame = lay(tree, metrics)
    assert [tree.by_id(t).name for t in frame.tips] == ["A", "D"]
    assert frame.n_rows == 2.0
    assert not frame.has(tree.by_name("B").id)


def test_single_leaf_tree_still_lays_out(metrics):
    tree = build(L("only", 1.0))
    frame = lay(tree, metrics)
    assert frame.n_rows == 1.0
    assert frame.row(tree.root.id) == 0.5


def test_slanted_shares_the_rectangular_rows(three_tips, metrics):
    rect = lay(three_tips, metrics, mode=LayoutMode.RECTANGULAR)
    slant = lay(three_tips, metrics, mode=LayoutMode.SLANTED)
    assert rows_of(rect, three_tips) == rows_of(slant, three_tips)


def test_polar_mode_is_refused(three_tips, metrics):
    with pytest.raises(ValueError):
        LinearLayout().compute(three_tips,
                               LayoutParams(mode=LayoutMode.CIRCULAR), metrics)


def test_parent_rule_does_not_move_tips(unbalanced, metrics):
    tips = {}
    for rule in ParentRule:
        frame = lay(unbalanced, metrics, parent_rule=rule)
        tips[rule] = [frame.row(t) for t in frame.tips]
    assert tips[ParentRule.MIDPOINT] == tips[ParentRule.MEAN] == tips[ParentRule.WEIGHTED]
