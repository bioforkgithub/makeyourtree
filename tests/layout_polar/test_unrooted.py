# SPDX-License-Identifier: MIT
"""Unrooted layout: equal-angle and equal-daylight.

The defining property of an unrooted drawing is that every edge is drawn at
exactly its own length, so that is asserted directly on random trees rather
than on a fixture or two.  Planarity is checked the honest way -- an all-pairs
segment-intersection sweep over non-adjacent edges.
"""

from __future__ import annotations

import math
import statistics

import pytest

from makeyourtree.core.traversal import preorder
from makeyourtree.layout import compute_layout
from makeyourtree.layout.params import (BranchMode, LayoutMode, LayoutParams,
                                    UnrootedMethod)
from makeyourtree.layout.projector import LinearProjector
from makeyourtree.layout.unrooted import (UnrootedLayout, build_skeleton,
                                      daylight_gaps, equal_angle,
                                      equal_daylight)
import makeyourtree.layout.unrooted as unrooted
from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics

from _polar_support import (balanced, caterpillar, distance, edge_pairs, make_tree,
                      named, random_tree, star)

SEEDS = (0, 1, 2, 3, 4)


def _params(**kw):
    return LayoutParams(mode=LayoutMode.UNROOTED, **kw)


def _frame(tree, **kw):
    params = _params(**kw)
    return UnrootedLayout().compute(tree, params,
                                    CachedMetrics(FallbackMetrics())), params


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _crosses(p1, p2, p3, p4) -> bool:
    """True when the open segments p1p2 and p3p4 properly intersect."""
    d1, d2 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    d3, d4 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _gap_variance(gaps) -> float:
    return sum(statistics.pvariance(g) for g in gaps.values() if len(g) > 1)


# ------------------------------------------------------- length is sacred


@pytest.mark.parametrize("seed", SEEDS)
def test_equal_angle_preserves_every_branch_length(seed):
    tree = random_tree(45, seed=seed, polytomy=0.25)
    params = _params()
    pos = equal_angle(tree, params)
    for parent, child in edge_pairs(tree):
        length = tree.by_id(child).branch_length
        assert distance(pos[parent], pos[child]) == pytest.approx(length, abs=1e-9)


@pytest.mark.parametrize("seed", SEEDS)
def test_equal_daylight_preserves_every_branch_length(seed):
    tree = random_tree(45, seed=seed, polytomy=0.25)
    params = _params(daylight_iterations=6)
    pos = equal_daylight(tree, params)
    for parent, child in edge_pairs(tree):
        length = tree.by_id(child).branch_length
        assert distance(pos[parent], pos[child]) == pytest.approx(length, abs=1e-9)


def test_frame_preserves_lengths_up_to_the_single_uniform_scale():
    tree = random_tree(40, seed=7)
    frame, _ = _frame(tree)
    for parent, child in edge_pairs(tree):
        length = tree.by_id(child).branch_length
        drawn = distance(frame.xy(parent), frame.xy(child))
        assert drawn == pytest.approx(length * frame.scale, abs=1e-9)
    assert frame.scale > 0.0


# ------------------------------------------------------------- planarity


@pytest.mark.parametrize("seed", SEEDS)
def test_equal_angle_output_has_no_crossing_edges(seed):
    tree = random_tree(35, seed=seed, polytomy=0.3)
    pos = equal_angle(tree, _params())
    edges = edge_pairs(tree)
    for i, (a, b) in enumerate(edges):
        for c, d in edges[i + 1:]:
            if len({a, b, c, d}) < 4:
                continue        # edges sharing a node always "touch"
            assert not _crosses(pos[a], pos[b], pos[c], pos[d]), \
                f"edges {a}-{b} and {c}-{d} cross"


def test_the_crossing_predicate_actually_detects_a_crossing():
    assert _crosses((0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0))
    assert not _crosses((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))


# --------------------------------------------------------------- daylight


@pytest.mark.parametrize("seed", SEEDS)
def test_equal_daylight_reduces_the_variance_of_the_gaps(seed):
    tree = random_tree(40, seed=seed)
    params = _params(daylight_iterations=5)
    before = _gap_variance(daylight_gaps(tree, params, equal_angle(tree, params)))
    after = _gap_variance(daylight_gaps(tree, params, equal_daylight(tree, params)))
    assert before > 0.0
    assert after < before


def test_equalising_one_node_shares_its_daylight_exactly():
    """Including the wrap-around gap, which is the one everybody gets wrong."""
    tree = random_tree(30, seed=2)
    params = _params()
    skel = build_skeleton(tree, params)
    xs, ys = unrooted._equal_angle_positions(skel, params.start_radians)
    degrees = skel.degree
    checked = 0
    for i in range(len(skel)):
        if degrees[i] < 3:
            continue
        if unrooted._arcs_at(skel, xs, ys, i) is None:
            continue        # documented bail-out: a component subtends >= pi
        unrooted._equalize_at(skel, xs, ys, i, 1.0)
        arcs = unrooted._arcs_at(skel, xs, ys, i)
        assert arcs is not None
        gaps = [arcs[k + 1][0] - arcs[k][1] for k in range(len(arcs) - 1)]
        gaps.append(arcs[0][0] + 2 * math.pi - arcs[-1][1])
        assert len(gaps) == degrees[i]
        assert max(gaps) - min(gaps) == pytest.approx(0.0, abs=1e-9)
        checked += 1
    assert checked > 5


def test_daylight_rotations_leave_the_pinned_side_untouched():
    """The parent-side component is the anchor, so it must not move at all."""
    tree = random_tree(25, seed=3)
    params = _params()
    skel = build_skeleton(tree, params)
    xs, ys = unrooted._equal_angle_positions(skel, params.start_radians)
    target = next(i for i in range(len(skel))
                  if skel.parent[i] >= 0 and len(skel.children[i]) >= 2)
    before = [(float(xs[j]), float(ys[j])) for j in range(len(skel))]
    unrooted._equalize_at(skel, xs, ys, target, 1.0)
    lo, hi = target, target + skel.size[target]
    for j in range(len(skel)):
        moved = (float(xs[j]), float(ys[j])) != before[j]
        if not lo <= j < hi:
            assert not moved, "the anchored parent-side component was rotated"
    assert (float(xs[target]), float(ys[target])) == before[target]


def test_daylight_reports_its_own_convergence():
    tree = random_tree(30, seed=4)
    frame, _ = _frame(tree, daylight_iterations=1)
    info = frame.metadata["daylight"]
    assert info["passes"] == 1
    assert info["residual"] > 0.0
    assert frame.metadata["method"] == UnrootedMethod.EQUAL_DAYLIGHT.value


def test_zero_iterations_leaves_the_equal_angle_drawing_alone():
    tree = random_tree(20, seed=5)
    params = _params()
    base = equal_angle(tree, params)
    same = equal_daylight(tree, params, iterations=0)
    for nid, xy in base.items():
        assert same[nid] == pytest.approx(xy, abs=1e-12)


# ---------------------------------------------------------- wedge geometry


def test_a_star_tree_fans_out_at_exactly_equal_angles():
    """With equal weights the wedge bisectors are the banded angle formula."""
    tree = star(7, length=1.0)
    params = _params(start_angle=0.0)
    pos = equal_angle(tree, params)
    step = 2 * math.pi / 7
    for i, leaf in enumerate(tree.root.children):
        x, y = pos[leaf.id]
        # Compared as a wrapped difference: the i = 3 bisector lands on exactly
        # pi, where atan2 may report either sign.
        off = math.remainder(math.atan2(y, x) - (i + 0.5) * step, 2 * math.pi)
        assert off == pytest.approx(0.0, abs=1e-12)
        assert math.hypot(x, y) == pytest.approx(1.0, abs=1e-12)


def test_degree_two_root_is_suppressed():
    """The root must not become a visible kink splitting the drawing in two."""
    tree = random_tree(24, seed=6)
    assert len(tree.root.children) == 2
    pos = equal_angle(tree, _params())
    root = pos[tree.root.id]
    left = pos[tree.root.children[0].id]
    right = pos[tree.root.children[1].id]
    ux, uy = left[0] - root[0], left[1] - root[1]
    vx, vy = right[0] - root[0], right[1] - root[1]
    cross = ux * vy - uy * vx
    dot = ux * vx + uy * vy
    assert abs(cross) < 1e-9                       # collinear
    assert dot < 0.0                               # and on opposite sides
    # The drawing starts at the heavier child, not at the root.
    heavier = max(tree.root.children, key=lambda c: c.n_leaves)
    assert pos[heavier.id] == pytest.approx((0.0, 0.0), abs=1e-12)


def test_start_angle_rotates_the_whole_drawing_rigidly():
    tree = random_tree(20, seed=8)
    a = equal_angle(tree, _params(start_angle=0.0))
    b = equal_angle(tree, _params(start_angle=37.0))
    ids = list(a)
    for i, u in enumerate(ids):
        for v in ids[i + 1:]:
            assert distance(a[u], a[v]) == pytest.approx(distance(b[u], b[v]),
                                                         abs=1e-9)
    moved = [u for u in ids if a[u] != pytest.approx(b[u], abs=1e-6)]
    assert len(moved) == len(ids) - 1        # every node but the pinned start


def test_cladogram_mode_draws_unit_edges():
    tree = random_tree(20, seed=9)
    params = _params(branch_mode=BranchMode.CLADOGRAM_ALIGNED)
    pos = equal_angle(tree, params)
    for parent, child in edge_pairs(tree):
        assert distance(pos[parent], pos[child]) == pytest.approx(1.0, abs=1e-9)
    frame, _ = _frame(tree, branch_mode=BranchMode.CLADOGRAM_ALIGNED)
    assert frame.scale == 1.0


# ------------------------------------------------------ frame integration


def test_band_space_is_populated_and_flagged_as_approximate():
    tree = random_tree(30, seed=10)
    frame, params = _frame(tree)
    assert len(frame.tips) == 30
    cursor = 0.0
    for tid in frame.tips:
        lo, hi = frame.row_span(tid)
        assert lo == pytest.approx(cursor, abs=1e-12)
        cursor = hi
    assert cursor == pytest.approx(frame.n_rows, abs=1e-12)
    assert isinstance(frame.projector, LinearProjector)
    assert frame.projector.base_x == pytest.approx(frame.body_bounds[2])
    assert frame.projector.n_rows == frame.n_rows
    assert frame.metadata["band_space"] == "approximate"
    assert "indicative" in frame.metadata["band_space_note"]
    x, y = frame.projector.point(0.0, 0.0)
    assert x >= frame.body_bounds[2] - 1e-9


def test_internal_nodes_get_rows_so_tracks_degrade_gracefully():
    tree = balanced(3)
    frame, _ = _frame(tree)
    for node in preorder(tree.root):
        lo, hi = frame.row_span(node.id)
        assert 0.0 <= lo < hi <= frame.n_rows
        assert lo <= frame.row(node.id) <= hi


def test_body_bounds_is_the_node_extent():
    tree = random_tree(30, seed=11)
    frame, _ = _frame(tree)
    xs = [frame.xy(n.id)[0] for n in preorder(tree.root)]
    ys = [frame.xy(n.id)[1] for n in preorder(tree.root)]
    assert frame.body_bounds == pytest.approx((min(xs), min(ys), max(xs), max(ys)),
                                              abs=1e-9)
    assert frame.n_segments == len(edge_pairs(tree))


def test_collapsed_clade_becomes_a_single_drawn_tip():
    tree = balanced(3)
    clade = tree.root.children[0]
    clade.collapsed = True
    frame, params = _frame(tree)
    assert clade.id in frame.tips
    assert not frame.has(clade.children[0].id)
    lo, hi = frame.row_span(clade.id)
    assert hi - lo == pytest.approx(params.rows_for_collapsed(clade.n_leaves))


def test_hidden_subtree_is_absent_from_the_drawing():
    tree = balanced(3)
    hidden = tree.root.children[0]
    hidden.hidden = True
    frame, _ = _frame(tree)
    assert not frame.has(hidden.id)
    assert len(frame.tips) == 4


def test_layout_never_mutates_the_tree():
    tree = random_tree(25, seed=12)
    before = [(n.id, n.name, n.branch_length,
               None if n.parent is None else n.parent.id,
               [c.id for c in n.children]) for n in preorder(tree.root)]
    _frame(tree)
    _frame(tree, unrooted_method=UnrootedMethod.EQUAL_ANGLE)
    after = [(n.id, n.name, n.branch_length,
              None if n.parent is None else n.parent.id,
              [c.id for c in n.children]) for n in preorder(tree.root)]
    assert before == after


def test_deep_caterpillar_does_not_recurse():
    tree = caterpillar(3000)
    frame, _ = _frame(tree, unrooted_method=UnrootedMethod.EQUAL_ANGLE)
    assert len(frame.tips) == 3000
    for node in preorder(tree.root):
        x, y = frame.xy(node.id)
        assert math.isfinite(x) and math.isfinite(y)


def test_single_tip_tree_is_laid_out():
    tree = make_tree(named("only", None))
    frame, _ = _frame(tree)
    assert frame.tips == [tree.root.id]
    assert frame.xy(tree.root.id) == pytest.approx(frame.body_bounds[:2])


def test_rejects_a_rooted_mode():
    tree = balanced(2)
    with pytest.raises(ValueError):
        UnrootedLayout().compute(tree, LayoutParams(mode=LayoutMode.CIRCULAR),
                                 CachedMetrics(FallbackMetrics()))


def test_compute_layout_dispatches_to_the_unrooted_layout():
    tree = balanced(3)
    frame = compute_layout(tree, LayoutParams(mode=LayoutMode.UNROOTED))
    assert frame.mode is LayoutMode.UNROOTED
    assert frame.projector is not None and not frame.projector.is_polar


def test_the_two_methods_are_reachable_from_the_class():
    tree = random_tree(15, seed=13)
    params = _params()
    layout = UnrootedLayout()
    assert layout.equal_angle(tree, params) == equal_angle(tree, params)
    assert layout.equal_daylight(tree, params, 2, 0.001) == \
        equal_daylight(tree, params, 2, 0.001)
