# SPDX-License-Identifier: MIT
"""Circular and radial layout: angle mapping, radius rules, edge geometry."""

from __future__ import annotations

import math

import pytest

from makeyourtree.core.node import Node
from makeyourtree.core.traversal import descend, preorder
from makeyourtree.layout import compute_layout
from makeyourtree.layout.params import (BranchMode, LayoutMode, LayoutParams,
                                    ParentRule)
from makeyourtree.layout.polar import PolarLayout
from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics

from _polar_support import (balanced, caterpillar, make_tree, named, random_tree,
                      star, tip_angles)

TOL = 1e-9


def _metrics():
    return CachedMetrics(FallbackMetrics())


def lay(tree, **kw):
    params = LayoutParams(mode=kw.pop("mode", LayoutMode.CIRCULAR), **kw)
    return PolarLayout().compute(tree, params, _metrics()), params


# ------------------------------------------------------------------ angles


def test_tip_angles_are_the_banded_row_formula():
    tree = balanced(3)                      # 8 tips
    frame, params = lay(tree, arc=350.0, start_angle=-90.0)
    n = len(frame.tips)
    assert n == 8
    for i, angle in enumerate(tip_angles(frame)):
        expected = params.start_angle + (i + 0.5) / n * params.arc
        assert angle == pytest.approx(expected, abs=TOL)


def test_tip_angles_span_exactly_the_requested_arc():
    for arc in (90.0, 180.0, 270.0, 350.0, 360.0):
        tree = balanced(4)                  # 16 tips
        frame, _ = lay(tree, arc=arc)
        angles = tip_angles(frame)
        n = len(angles)
        assert max(angles) - min(angles) == pytest.approx(arc * (n - 1) / n, abs=1e-9)


def test_seam_gap_is_respected():
    tree = balanced(4)
    frame, params = lay(tree, arc=270.0, start_angle=-90.0)
    lo = params.start_angle
    hi = params.start_angle + params.arc
    for angle in tip_angles(frame):
        assert lo <= angle <= hi
    # Nothing at all -- tips, internal nodes or arc endpoints -- may stray into
    # the 90 degrees left open at the seam.
    for node in preorder(tree.root):
        assert lo <= frame.angle(node.id) <= hi
    for _cx, _cy, _r, a0, a1 in frame.arcs:
        assert lo <= a0 <= hi and lo <= a1 <= hi


def test_direction_minus_one_mirrors_the_fan():
    tree = balanced(3)
    fwd, params = lay(tree, direction=1)
    rev, _ = lay(tree, direction=-1)
    for node in preorder(tree.root):
        mirrored = 2 * params.start_angle - fwd.angle(node.id)
        assert rev.angle(node.id) == pytest.approx(mirrored, abs=TOL)
        assert rev.radius(node.id) == pytest.approx(fwd.radius(node.id), abs=TOL)


def test_full_circle_wraps_without_a_seam_artefact():
    tree = balanced(4)
    frame, _ = lay(tree, arc=360.0)
    angles = tip_angles(frame)
    n = len(angles)
    assert angles == sorted(angles)
    # No tip lands on top of another, and the wrap-around gap equals one row.
    step = 360.0 / n
    for a, b in zip(angles, angles[1:]):
        assert b - a == pytest.approx(step, abs=TOL)
    assert (angles[0] + 360.0) - angles[-1] == pytest.approx(step, abs=TOL)
    # No arc connector takes the long way round the circle.
    for _cx, _cy, _r, a0, a1 in frame.arcs:
        assert abs(a1 - a0) < 360.0


def test_angles_are_not_normalised_mid_pass():
    """A clade spanning the seam keeps a bisector between its children.

    Normalising into [0, 360) during the pass is the classic bug: the midpoint
    of 350 and 10 becomes 180 instead of 0.
    """
    tree = balanced(3)
    frame, _ = lay(tree, arc=360.0, start_angle=0.0)
    for node in preorder(tree.root):
        kids = descend(node, True)
        if not kids:
            continue
        mid = 0.5 * (frame.angle(kids[0].id) + frame.angle(kids[-1].id))
        assert frame.angle(node.id) == pytest.approx(mid, abs=TOL)


# ------------------------------------------------------------------ radius


def test_inner_radius_is_honoured():
    tree = random_tree(20, seed=3)
    frame, _ = lay(tree, inner_radius=0.25)
    inner = frame.metadata["inner_radius"]
    assert inner == pytest.approx(0.25 * frame.max_radius, abs=TOL)
    assert frame.radius(tree.root.id) == pytest.approx(inner, abs=TOL)
    for node in preorder(tree.root):
        assert frame.radius(node.id) >= inner - TOL


def test_zero_inner_radius_puts_the_root_at_the_centre():
    tree = random_tree(12, seed=4)
    frame, _ = lay(tree, inner_radius=0.0)
    assert frame.radius(tree.root.id) == pytest.approx(0.0, abs=TOL)
    cx, cy = frame.center
    assert frame.xy(tree.root.id) == pytest.approx((cx, cy), abs=1e-9)


def test_radial_aligns_every_tip_but_circular_does_not():
    tree = random_tree(25, seed=5)
    radial, _ = lay(tree, mode=LayoutMode.RADIAL)
    circular, _ = lay(tree, mode=LayoutMode.CIRCULAR)
    radii = [radial.radius(t) for t in radial.tips]
    assert max(radii) - min(radii) == pytest.approx(0.0, abs=1e-9)
    assert radii[0] == pytest.approx(radial.max_radius, abs=TOL)
    spread = [circular.radius(t) for t in circular.tips]
    assert max(spread) - min(spread) > 1.0


def test_radial_suppresses_branch_lengths_and_the_scale_bar():
    tree = random_tree(16, seed=6)
    frame, _ = lay(tree, mode=LayoutMode.RADIAL, branch_mode=BranchMode.PHYLOGRAM)
    assert frame.scale == 1.0
    assert frame.metadata["along"] == "aligned"
    # Two trees with the same topology but different lengths draw identically.
    other = random_tree(16, seed=6, lo=5.0, hi=9.0)
    twin, _ = lay(other, mode=LayoutMode.RADIAL)
    for a, b in zip(preorder(tree.root), preorder(other.root)):
        assert frame.radius(a.id) == pytest.approx(twin.radius(b.id), abs=1e-9)


def test_circular_radius_is_cumulative_length_times_scale():
    tree = random_tree(20, seed=7)
    frame, _ = lay(tree, inner_radius=0.1)
    inner = frame.metadata["inner_radius"]
    for node in preorder(tree.root):
        assert frame.radius(node.id) == pytest.approx(
            inner + node.depth_len * frame.scale, abs=1e-9)
    assert max(frame.radius(t) for t in frame.tips) == pytest.approx(
        frame.max_radius, abs=1e-9)


def test_cladogram_level_radius_tracks_level():
    tree = caterpillar(6)
    frame, _ = lay(tree, branch_mode=BranchMode.CLADOGRAM_LEVEL)
    inner = frame.metadata["inner_radius"]
    band = frame.max_radius - inner
    top = max(n.level for n in preorder(tree.root))
    for node in preorder(tree.root):
        assert frame.radius(node.id) == pytest.approx(
            inner + band * node.level / top, abs=1e-9)
    assert frame.scale == 1.0


def test_missing_lengths_fall_back_to_the_topological_rule():
    tree = balanced(2)
    for node in preorder(tree.root):
        node.branch_length = None
    tree.refresh()
    frame, _ = lay(tree, branch_mode=BranchMode.PHYLOGRAM)
    assert frame.metadata["along"] == "aligned"
    assert frame.scale == 1.0
    assert len({round(frame.radius(t), 9) for t in frame.tips}) == 1


# ------------------------------------------------------------------- edges


def test_every_internal_node_gets_an_arc_across_its_children():
    tree = random_tree(15, seed=8)
    frame, _ = lay(tree)
    cx, cy = frame.center
    wanted = set()
    for node in preorder(tree.root):
        kids = descend(node, True)
        if len(kids) < 2:
            continue
        wanted.add((round(frame.radius(node.id), 9),
                    round(frame.angle(kids[0].id), 9),
                    round(frame.angle(kids[-1].id), 9)))
    got = set()
    for acx, acy, r, a0, a1 in frame.arcs:
        assert (acx, acy) == (cx, cy)
        got.add((round(r, 9), round(a0, 9), round(a1, 9)))
    assert wanted <= got


def test_each_edge_gets_a_radial_spoke_at_the_child_angle():
    tree = random_tree(12, seed=9)
    frame, _ = lay(tree)
    cx, cy = frame.center
    flat = frame.straight
    spokes = {(round(flat[i], 6), round(flat[i + 1], 6),
               round(flat[i + 2], 6), round(flat[i + 3], 6))
              for i in range(0, len(flat), 4)}
    for node in preorder(tree.root):
        for child in descend(node, True):
            a = math.radians(frame.angle(child.id))
            r0 = frame.radius(node.id)
            r1 = frame.radius(child.id)
            key = (round(cx + r0 * math.cos(a), 6), round(cy + r0 * math.sin(a), 6),
                   round(cx + r1 * math.cos(a), 6), round(cy + r1 * math.sin(a), 6))
            assert key in spokes
    assert frame.n_segments == sum(1 for _ in preorder(tree.root)) - 1


def test_root_stub_is_drawn_and_clipped_to_the_hole():
    tree = balanced(2)
    n_edges = sum(1 for _ in preorder(tree.root)) - 1
    plain, _ = lay(tree, inner_radius=0.2)
    assert plain.n_segments == n_edges       # no root length, no stub

    tree.root.branch_length = 10.0           # far longer than the hole
    tree.refresh()
    frame, _ = lay(tree, inner_radius=0.2)
    assert frame.n_segments == n_edges + 1
    inner = frame.metadata["inner_radius"]
    cx, cy = frame.center
    a = math.radians(frame.angle(tree.root.id))
    flat = frame.straight
    stub = [tuple(flat[i:i + 4]) for i in range(0, len(flat), 4)
            if math.hypot(flat[i] - cx, flat[i + 1] - cy) < inner - 1e-9]
    assert len(stub) == 1
    x0, y0, x1, y1 = stub[0]
    assert (x0, y0) == pytest.approx((cx, cy), abs=1e-9)     # clipped at the centre
    assert (x1, y1) == pytest.approx(
        (cx + inner * math.cos(a), cy + inner * math.sin(a)), abs=1e-9)


# ------------------------------------------------------- band space / rows


def test_projector_reproduces_every_node_position():
    tree = random_tree(18, seed=10)
    frame, _ = lay(tree)
    proj = frame.projector
    assert proj is not None and proj.is_polar
    for node in preorder(tree.root):
        offset = frame.radius(node.id) - proj.base_r
        x, y = proj.point(frame.row(node.id), offset)
        assert (x, y) == pytest.approx(frame.xy(node.id), abs=1e-9)


def test_rows_are_contiguous_and_total_the_tip_count():
    tree = random_tree(30, seed=11)
    frame, _ = lay(tree)
    cursor = 0.0
    for tid in frame.tips:
        lo, hi = frame.row_span(tid)
        assert lo == pytest.approx(cursor, abs=TOL)
        cursor = hi
    assert cursor == pytest.approx(frame.n_rows, abs=TOL)
    assert frame.n_rows == len(frame.tips)


def test_collapsed_clade_consumes_several_rows():
    tree = balanced(3)
    clade = tree.root.children[0]
    clade.collapsed = True
    frame, params = lay(tree)
    assert clade.id in frame.tips
    lo, hi = frame.row_span(clade.id)
    assert hi - lo == pytest.approx(params.rows_for_collapsed(clade.n_leaves), abs=TOL)
    assert frame.n_rows == pytest.approx(hi - lo + 4, abs=TOL)
    assert frame.angle(clade.id) == pytest.approx(
        frame.projector.angle_of(0.5 * (lo + hi)), abs=TOL)


def test_collapsed_clade_publishes_its_depth_statistics():
    """The summary glyph and the layout must read one set of numbers."""
    from makeyourtree.layout.collapse import (STATS_METADATA_KEY, collapse_outline,
                                          depth_stats)
    tree = balanced(3)
    clade = tree.root.children[0]
    clade.collapsed = True
    frame, params = lay(tree)
    assert frame.metadata[STATS_METADATA_KEY][clade.id] == pytest.approx(
        depth_stats(clade))
    outline = collapse_outline(clade, frame, params)
    points = [seg for seg in outline if seg[0] in ("M", "L")]
    assert len(points) >= 3
    lo, hi = frame.row_span(clade.id)
    for _op, row, along in points:
        assert lo - 1e-9 <= row <= hi + 1e-9
        assert frame.radius(clade.id) - 1e-9 <= along <= frame.max_radius + 1e-9


def test_hidden_subtree_is_excluded_entirely():
    tree = balanced(3)
    hidden = tree.root.children[0]
    hidden.hidden = True
    frame, _ = lay(tree)
    assert len(frame.tips) == 4
    assert not frame.has(hidden.id)
    assert frame.n_rows == 4


@pytest.mark.parametrize("rule,expected", [
    (ParentRule.MIDPOINT, 2.25),
    (ParentRule.MEAN, 2.0),
    (ParentRule.WEIGHTED, 3.0),
])
def test_parent_rule_at_a_polytomy(rule, expected):
    quad = named(None, 1.0,
                 named(None, 1.0, named("c", 1.0), named("d", 1.0)),
                 named(None, 1.0, named("e", 1.0), named("f", 1.0)))
    tree = make_tree(named("root", None, named("a", 1.0), named("b", 1.0), quad))
    frame, _ = lay(tree, parent_rule=rule)
    assert frame.row(tree.root.id) == pytest.approx(expected, abs=TOL)
    assert frame.angle(tree.root.id) == pytest.approx(
        frame.projector.angle_of(expected), abs=TOL)


# ------------------------------------------------------------------ labels


def test_tip_offset_clears_the_longest_label():
    tree = star(4)
    tree.root.children[2].name = "a_very_long_taxon_name_indeed"
    metrics = _metrics()
    params = LayoutParams(mode=LayoutMode.CIRCULAR)
    frame = PolarLayout().compute(tree, params, metrics)
    widest = max(metrics.advance(n.name, 11.0) for n in tree.root.children)
    assert frame.label_widths[tree.root.children[2].id] == pytest.approx(widest)
    assert frame.tip_offset >= widest + params.tip_label_gap
    assert frame.tip_offset == pytest.approx(widest + 2 * params.tip_label_gap)


def test_labels_are_capped_by_max_label_width():
    tree = star(3)
    tree.root.children[0].name = "x" * 200
    frame, _ = lay(tree, max_label_width=40.0)
    assert max(frame.label_widths.values()) == pytest.approx(40.0)
    assert frame.tip_offset == pytest.approx(40.0 + 2 * 6.0)


def test_labels_off_reserves_only_the_gap():
    tree = star(3)
    frame, params = lay(tree, show_tip_labels=False)
    assert frame.label_widths == {}
    assert frame.tip_offset == pytest.approx(params.tip_label_gap)


# ------------------------------------------------------------------- misc


def test_body_bounds_is_the_outer_circle():
    tree = random_tree(10, seed=12)
    frame, _ = lay(tree)
    cx, cy = frame.center
    r = frame.max_radius
    assert frame.body_bounds == pytest.approx((cx - r, cy - r, cx + r, cy + r))
    for node in preorder(tree.root):
        x, y = frame.xy(node.id)
        assert math.hypot(x - cx, y - cy) <= r + 1e-9


def test_layout_never_mutates_the_tree():
    tree = random_tree(20, seed=13)
    before = [(n.id, n.name, n.branch_length, n.collapsed, n.hidden,
               None if n.parent is None else n.parent.id,
               [c.id for c in n.children]) for n in preorder(tree.root)]
    lay(tree, mode=LayoutMode.CIRCULAR)
    lay(tree, mode=LayoutMode.RADIAL)
    after = [(n.id, n.name, n.branch_length, n.collapsed, n.hidden,
              None if n.parent is None else n.parent.id,
              [c.id for c in n.children]) for n in preorder(tree.root)]
    assert before == after


def test_deep_caterpillar_does_not_recurse():
    tree = caterpillar(4000)
    frame, _ = lay(tree)
    assert len(frame.tips) == 4000
    for node in preorder(tree.root):
        x, y = frame.xy(node.id)
        assert math.isfinite(x) and math.isfinite(y)


def test_single_tip_tree_is_laid_out():
    tree = make_tree(Node("only"))
    frame, _ = lay(tree)
    assert frame.tips == [tree.root.id]
    assert frame.n_rows == 1
    assert math.isfinite(frame.radius(tree.root.id))


def test_rejects_a_non_polar_mode():
    tree = balanced(2)
    with pytest.raises(ValueError):
        PolarLayout().compute(tree, LayoutParams(mode=LayoutMode.RECTANGULAR),
                              _metrics())


def test_compute_layout_dispatches_to_the_polar_layout():
    tree = balanced(2)
    frame = compute_layout(tree, LayoutParams(mode=LayoutMode.CIRCULAR))
    assert frame.mode is LayoutMode.CIRCULAR
    assert frame.projector is not None and frame.projector.is_polar
