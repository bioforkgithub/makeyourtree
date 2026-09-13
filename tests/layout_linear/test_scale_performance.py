# SPDX-License-Identifier: MIT
"""Big-tree behaviour: no recursion, and a bounded time budget.

The two shapes that break tree code have opposite hot spots -- a caterpillar is
depth-bound and blows a recursive stack, a balanced tree is primitive-bound --
so both are laid out here.
"""
from __future__ import annotations

import sys
import time

import pytest

from makeyourtree.layout.linear import LinearLayout
from makeyourtree.layout.params import BranchMode, LayoutMode, LayoutParams

from .conftest import bifurcating, caterpillar

BUDGET_SECONDS = 12.0
"""Deliberately loose: this guards against an accidental quadratic pass, not
against a slow machine."""


N_LEAVES = 20_000


@pytest.fixture(scope="module")
def big():
    return bifurcating(N_LEAVES)


def test_a_twenty_thousand_leaf_tree_lays_out_in_reasonable_time(big, metrics):
    params = LayoutParams()
    start = time.perf_counter()
    frame = LinearLayout().compute(big, params, metrics)
    elapsed = time.perf_counter() - start
    assert len(frame.tips) == N_LEAVES
    assert frame.n_rows == float(N_LEAVES)
    assert frame.n_segments == sum(1 + len(n.children)
                                   for n in big.nodes if n.children)
    assert elapsed < BUDGET_SECONDS


def test_the_first_and_last_row_are_where_they_should_be(big, metrics):
    frame = LinearLayout().compute(big, LayoutParams(), metrics)
    assert frame.row(frame.tips[0]) == 0.5
    assert frame.row(frame.tips[-1]) == N_LEAVES - 0.5
    assert frame.row_span(big.root.id) == (0.0, float(N_LEAVES))
    # 20 000 does not split into equal halves all the way down, so the
    # midpoint of the two extreme children is near, not at, the centre row.
    assert abs(frame.row(big.root.id) - N_LEAVES / 2) < 10.0


def test_a_deep_caterpillar_does_not_touch_the_recursion_limit(metrics):
    depth = sys.getrecursionlimit() * 20
    tree = caterpillar(depth, bl=0.01)
    frame = LinearLayout().compute(tree, LayoutParams(), metrics)
    assert len(frame.tips) == depth
    assert frame.n_rows == float(depth)
    deepest = max(frame.x(t) for t in frame.tips)
    assert deepest == pytest.approx(frame.body_bounds[2])


def test_slanted_mode_costs_one_segment_per_edge_at_scale(big, metrics):
    frame = LinearLayout().compute(
        big, LayoutParams(mode=LayoutMode.SLANTED), metrics)
    assert frame.n_segments == sum(len(n.children) for n in big.nodes)


def test_cladogram_of_a_big_tree_still_aligns_every_tip(big, metrics):
    frame = LinearLayout().compute(
        big, LayoutParams(branch_mode=BranchMode.CLADOGRAM_ALIGNED), metrics)
    far = frame.body_bounds[2]
    assert all(frame.x(t) == pytest.approx(far) for t in frame.tips)
