# SPDX-License-Identifier: MIT
"""Collapsed-clade row accounting and summary-glyph geometry."""
from __future__ import annotations

import math

import pytest

from makeyourtree.layout.collapse import (STATS_METADATA_KEY, collapse_outline,
                                      collapse_rows, depth_stats)
from makeyourtree.layout.linear import LinearLayout
from makeyourtree.layout.params import (BranchMode, CollapseRows, CollapseShape,
                                    LayoutParams)

from .conftest import C, L, build, caterpillar


def lay(tree, metrics, **kw):
    return LinearLayout().compute(tree, LayoutParams(**kw), metrics)


@pytest.fixture
def clade_tree():
    tree = build(C(
        C(L("A", 0.1), L("B", 0.3), L("C", 0.2), bl=0.5, name="clade"),
        L("D", 1.0),
    ))
    tree.by_name("clade").collapsed = True
    return tree


def test_collapse_rows_delegates_to_the_params_ladder(clade_tree):
    params = LayoutParams()
    clade = clade_tree.by_name("clade")
    assert collapse_rows(clade, params) == params.rows_for_collapsed(3)
    assert collapse_rows(clade, params) == pytest.approx(2.0 * math.sqrt(3))


def test_fixed_ladder_gives_exactly_the_requested_rows(clade_tree, metrics):
    frame = lay(clade_tree, metrics, collapse_rows_mode=CollapseRows.FIXED,
                collapse_rows=2.0)
    clade = clade_tree.by_name("clade")
    assert frame.row_span(clade.id) == (0.0, 2.0)
    assert frame.n_rows == 3.0


def test_a_collapsed_clade_consumes_its_budget_and_its_children_none(clade_tree, metrics):
    frame = lay(clade_tree, metrics)
    clade = clade_tree.by_name("clade")
    budget = collapse_rows(clade, LayoutParams())
    assert frame.row_span(clade.id) == (0.0, pytest.approx(budget))
    assert frame.row(clade.id) == pytest.approx(budget / 2)
    for name in ("A", "B", "C"):
        assert not frame.has(clade_tree.by_name(name).id)
    assert [clade_tree.by_id(t).name for t in frame.tips] == ["clade", "D"]
    assert frame.n_rows == pytest.approx(budget + 1.0)


def test_collapsing_makes_the_remaining_rows_taller(clade_tree, metrics):
    clade = clade_tree.by_name("clade")
    clade.collapsed = False
    expanded = lay(clade_tree, metrics, height=400.0)
    clade.collapsed = True
    collapsed = lay(clade_tree, metrics, height=400.0,
                    collapse_rows_mode=CollapseRows.FIXED, collapse_rows=2.0)
    assert expanded.n_rows == 4.0
    assert collapsed.n_rows == 3.0
    assert collapsed.row_height > expanded.row_height


def test_depth_stats_are_absolute_and_iterative(clade_tree):
    d_min, d_max, d_mean = depth_stats(clade_tree.by_name("clade"))
    assert d_min == pytest.approx(0.6)
    assert d_max == pytest.approx(0.8)
    assert d_mean == pytest.approx(0.7)


def test_depth_stats_of_a_leaf_are_its_own_depth(clade_tree):
    leaf = clade_tree.by_name("D")
    assert depth_stats(leaf) == pytest.approx((1.0, 1.0, 1.0))


def test_depth_stats_survive_a_deep_caterpillar():
    tree = caterpillar(5000, bl=0.001)
    d_min, d_max, d_mean = depth_stats(tree.root)
    assert d_min == pytest.approx(0.001)
    assert d_max == pytest.approx(4999 * 0.001)
    assert d_min < d_mean < d_max


def test_the_glyph_never_spills_past_the_tree_body(metrics):
    tree = build(C(
        C(L("A", 1.0), L("B", 2.0), bl=0.5, name="clade"),
        L("D", 0.5),
    ))
    tree.by_name("clade").collapsed = True
    frame = lay(tree, metrics, collapse_shape=CollapseShape.TRAPEZOID)
    outline = collapse_outline(tree.by_name("clade"), frame, frame.params)
    far = max(seg[2] for seg in outline if seg[0] == "L")
    assert far == pytest.approx(frame.body_bounds[2])


def test_triangle_outline_is_apex_and_a_mean_depth_base(clade_tree, metrics):
    frame = lay(clade_tree, metrics, collapse_shape=CollapseShape.TRIANGLE)
    clade = clade_tree.by_name("clade")
    outline = collapse_outline(clade, frame, frame.params)
    lo, hi = frame.row_span(clade.id)
    base = frame.x(clade.id) + 0.2 * frame.scale
    assert [seg[0] for seg in outline] == ["M", "L", "L", "Z"]
    assert outline[0] == ("M", frame.row(clade.id), frame.x(clade.id))
    assert outline[1][1] == pytest.approx(lo + 0.15)
    assert outline[2][1] == pytest.approx(hi - 0.15)
    assert outline[1][2] == pytest.approx(base)
    assert outline[2][2] == pytest.approx(base)


def test_trapezoid_outline_shows_the_min_and_max_spread(clade_tree, metrics):
    frame = lay(clade_tree, metrics, collapse_shape=CollapseShape.TRAPEZOID)
    clade = clade_tree.by_name("clade")
    outline = collapse_outline(clade, frame, frame.params)
    apex = frame.x(clade.id)
    near = apex + 0.1 * frame.scale
    far = apex + 0.3 * frame.scale
    reach = [seg[2] for seg in outline if seg[0] == "L"]
    assert reach == pytest.approx([near, far, far, near])


def test_bar_outline_is_a_rectangle_from_the_apex(clade_tree, metrics):
    frame = lay(clade_tree, metrics, collapse_shape=CollapseShape.BAR)
    clade = clade_tree.by_name("clade")
    outline = collapse_outline(clade, frame, frame.params)
    apex = frame.x(clade.id)
    far = apex + 0.3 * frame.scale
    rows = [seg[1] for seg in outline if seg[0] in ("M", "L")]
    assert rows[0] == rows[1] and rows[2] == rows[3]
    assert [seg[2] for seg in outline if seg[0] in ("M", "L")] == pytest.approx(
        [apex, far, far, apex])


def test_cladogram_glyphs_run_to_the_far_edge(clade_tree, metrics):
    frame = lay(clade_tree, metrics, branch_mode=BranchMode.CLADOGRAM_ALIGNED)
    outline = collapse_outline(clade_tree.by_name("clade"), frame, frame.params)
    reach = [seg[2] for seg in outline if seg[0] == "L"]
    assert reach and all(v == pytest.approx(frame.body_bounds[2]) for v in reach)


def test_the_layout_caches_depth_stats_for_the_compositor(clade_tree, metrics):
    frame = lay(clade_tree, metrics)
    clade = clade_tree.by_name("clade")
    assert frame.metadata["collapsed"] == [clade.id]
    cached = frame.metadata[STATS_METADATA_KEY][clade.id]
    assert cached == pytest.approx(depth_stats(clade))


def test_the_outline_uses_the_cached_stats_when_present(clade_tree, metrics):
    frame = lay(clade_tree, metrics, collapse_shape=CollapseShape.TRIANGLE)
    clade = clade_tree.by_name("clade")
    frame.metadata[STATS_METADATA_KEY][clade.id] = (0.5, 0.5, 0.5)
    outline = collapse_outline(clade, frame, frame.params)
    reach = [seg[2] for seg in outline if seg[0] == "L"]
    assert reach and all(v == pytest.approx(frame.x(clade.id)) for v in reach)
